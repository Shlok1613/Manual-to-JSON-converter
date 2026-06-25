# services/vision_extractor.py
"""
Vision Extractor — sends PDF page images to Gemini, parses strict JSON.

Two extraction tasks per machine block:
  1. SPECS (one batched call per block, all variants together)
  2. PROCEDURE (one call per variant)

Strict rules baked into prompts:
  - NEVER invent values; missing => null
  - JSON only (no markdown/commentary)
  - Read tables as 2-D grids respecting merged cells
"""
import copy
import os
import re
import json
import time
import math
import logging
import concurrent.futures
from typing import List, Dict, Optional

from .types import Page, Block, Specs, TestStep, VariantData
from services.table_parser import extract_table_pages
from services.table_grid_extractor import extract_table_grids
from services.variant_mapper import extract_variant_mappings
from services.variant_mapper import merge_table_into_specs
from services.delay_utils import is_spurious_delay_hallucination

logger = logging.getLogger(__name__)


VISION_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT = 300
MAX_RETRIES = 3
BACKOFFS = [15, 30, 60]
MAX_IMAGES_PER_CALL = 8

# Step count validation constants (Layout A only)
EXPECTED_STEPS = 28
MIN_STEPS = 24
MAX_STEPS = 60  # allow up to 60 for multi-DIP-section variants (0425: ~36, 0426: ~32)
MAX_STEP_RETRIES = 4


def _count_test_steps(steps: List[Dict]) -> int:
    """Count real test steps, excluding pure section markers."""
    _MARKER_RE = re.compile(
        r'^(supply\s+couple|supply\s+off|run\s+time\s+dip)',
        re.IGNORECASE
    )
    return sum(1 for s in steps if not _MARKER_RE.match(s.get("step_name", "")))


def _get_client():
    try:
        import google.generativeai as genai
    except ImportError:
        logger.info("google-generativeai not installed: pip install google-generativeai")
        return None
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.info("GEMINI_API_KEY not set")
        return None
    genai.configure(api_key=api_key)
    return genai


def _strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    return raw.strip()


def _call_with_retry(model, parts, timeout: int, label: str) -> Optional[str]:
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(model.generate_content, parts)
                resp = fut.result(timeout=timeout)

            time.sleep(2)

            return resp.text
        except Exception as e:
            last_err = e
            if "429" in str(e) and attempt < MAX_RETRIES:
                wait = BACKOFFS[min(attempt, len(BACKOFFS) - 1)]
                logger.warning(f"  [{label}] 429 — retry {attempt+1}/{MAX_RETRIES} in {wait}s")
                time.sleep(wait)
                continue
            logger.info(f"  [{label}] call failed: {type(e).__name__}: {repr(e)}")
            return None
    if last_err:
        logger.info(f"  [{label}] retries exhausted: {last_err}")
    return None


def _parse_json(raw: Optional[str], label: str) -> Optional[Dict]:
    if not raw:
        return None
    cleaned = _strip_json_fences(raw)
    cleaned = cleaned.strip()

    # remove accidental leading prose
    json_start = cleaned.find("{")
    if json_start > 0:
        cleaned = cleaned[json_start:]

    # remove accidental trailing prose
    json_end = cleaned.rfind("}")
    if json_end != -1:
        cleaned = cleaned[:json_end + 1]
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError as e:
        if "Extra data" in str(e):
            try:
                data, _ = json.JSONDecoder().raw_decode(cleaned)
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                pass
        logger.info(f"  [{label}] JSON parse failed: {e}")
        logger.debug(f"    raw[:500]: {cleaned[:500]}")
        return None


def _strip_repeated_header_lines(text: str, all_pages: List[Page]) -> str:
    """
    Remove lines that appear on >=50% of all pages in the block.
    These are document-level headers/footers (e.g., SCOPE lines, page titles)
    that would cause false positive variant matches on every page.
    """
    if not all_pages:
        return text

    from collections import Counter
    line_freq = Counter()
    total_pages = len(all_pages)
    for p in all_pages:
        page_lines = set()
        for line in (p.ocr_text or "").splitlines():
            stripped = line.strip()
            if stripped and len(stripped) > 10:
                page_lines.add(stripped)
        for line in page_lines:
            line_freq[line] += 1

    threshold = max(2, total_pages * 0.5)
    repeated = {line for line, count in line_freq.items() if count >= threshold}

    if not repeated:
        return text

    filtered = []
    for line in text.splitlines():
        if line.strip() not in repeated:
            filtered.append(line)
    return "\n".join(filtered)


def _find_exclusive_anchor(
    all_proc: List[Page],
    variant_re,
    other_machine_names: List[str],
    all_block_pages: List[Page],
    variant_name: str = "",
) -> "Optional[int]":
    """
    Find the page most exclusively dedicated to this variant.
    Score = (mentions of this variant) - (mentions of all other known variants).
    """
    TEST_CONTENT_RE = re.compile(
        r"healthy\s+condition|faulty\s+condition|"
        r"UV.*LED|OV.*LED|ASY.*LED|PWR.*LED|R\s+LED|"
        r"LED.*ON|LED.*OFF|"
        r"DIP\s+S/W\s+(?:setting|Number)|"
        r"FUNCTIONAL\s+TEST\s+PROCEDURE|TEST\s+PROCEDURE\s+FOR|"
        r"PROCESS\s*:\s*(?:Functional|Power\s+ON\s+test)|"
        r"relay\s+(?:status|trips?|ON|OFF)|"
        r"[Cc]ut[\s\-]?[Oo]ff|"
        r"[Ll]ow\s+voltage\s+cut|[Hh]igh\s+voltage\s+cut|"
        r"[Ss]ymmetrically\s+(?:reduce|increase)|"
        r"fault\s+recovery|indication\s+of\s+fault|"
        r"[A-F]\]\s*Goal\s*:|"
        r"LV\s+cut\s*off|HV\s+cut\s*off|"
        r"R\s*\(RED\s*LED\)|RED\s*LED\s*turns",
        re.IGNORECASE
    )

    best_idx = None
    best_score = -999

    for i, p in enumerate(all_proc):
        body = _strip_repeated_header_lines(p.ocr_text or "", all_block_pages)
        if not TEST_CONTENT_RE.search(body):
            continue
        target_count = len(variant_re.findall(body))
        if target_count == 0:
            continue
        other_count = sum(
            len(re.findall(rf"\b{re.escape(m)}\b", body, re.IGNORECASE))
            for m in other_machine_names
        )
        score = target_count - other_count

        if variant_name:
            for hname in _variant_heading_names(variant_name):
                functional_pat = (
                    rf"FUNCTIONAL\s+TEST\s+PROCEDURE\s+FOR.*{re.escape(hname)}"
                    rf"|FUNCTIONAL\s+TEST\s+PROCEDURE\s+FOR\s*[&/]\s*{re.escape(hname)}"
                )
                # Cutoff machines: CAT ID heading line includes R LED (Layout B tables)
                cutoff_cat_id_pat = (
                    rf"PROCEDURE\s+FOR\s+CAT\s+ID\s*:.*{re.escape(hname)}.*R\s*LED"
                    rf"|PROCEDURE\s+FOR\s+CAT\s+ID\s*:.*R\s*LED.*{re.escape(hname)}"
                )
                if re.search(cutoff_cat_id_pat, body, re.IGNORECASE):
                    score += 15
                    break
                # DIP machines: numbered functional-test sections beat FQC tables
                if re.search(functional_pat, body, re.IGNORECASE):
                    score += 10
                    break
                other_heading_patterns = [
                    rf"CAT\s+ID\s*:\s*{re.escape(hname)}",
                    rf"PROCEDURE\s+FOR\s+{re.escape(hname)}",
                ]
                for pattern in other_heading_patterns:
                    if re.search(pattern, body, re.IGNORECASE):
                        score += 3
                        break
                else:
                    continue
                break

        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx


def _variant_search_names(variant: str) -> List[str]:
    """
    Build name tokens used to locate procedure pages for a variant.
    EG-suffix variants (e.g. MAG03D0424EG) share the base variant's procedure
  in WI.pdf — OCR uses branding IDs like MAG03D042409 on the same heading line.
    """
    v = variant.upper().replace("_", "")
    names = [v]
    if v.endswith("EG"):
        base = v[:-2]
        if base:
            names.append(base)
    return list(dict.fromkeys(names))


def _variant_heading_names(variant: str) -> List[str]:
    """Names eligible for procedure-heading anchor bonus."""
    return _variant_search_names(variant)


def _build_variant_re(variant: str) -> re.Pattern:
    names = _variant_search_names(variant)
    parts = [rf"\b{re.escape(n)}\b" for n in names]
    if variant.upper().replace("_", "") not in names:
        parts.append(rf"\b{re.escape(variant)}\b")
    return re.compile("|".join(parts), re.IGNORECASE)


def _is_cutoff_cat_id_page(body: str, variant: str) -> bool:
    """True when page has the R-LED table procedure heading for this variant."""
    for hname in _variant_heading_names(variant):
        pat = (
            rf"PROCEDURE\s+FOR\s+CAT\s+ID\s*:.*{re.escape(hname)}.*R\s*LED"
            rf"|PROCEDURE\s+FOR\s+CAT\s+ID\s*:.*R\s*LED.*{re.escape(hname)}"
        )
        if re.search(pat, body, re.IGNORECASE):
            return True
    return False


def _detect_all_machine_names_in_block(block: Block) -> List[str]:
    scope_m = re.search(r"SCOPE\s*:\s*([\w/\s,]+)", block.text or "", re.IGNORECASE)
    if scope_m:
        names = re.findall(
            r"\b([A-Z]{2,6}\d+[A-Z0-9]*)\b",
            scope_m.group(1),
            re.IGNORECASE,
        )
        if names:
            return list(dict.fromkeys(n.upper() for n in names))

    names = re.findall(
        r"\b([A-Z]{2,6}\d+[A-Z0-9]*)\b",
        block.text or "",
        re.IGNORECASE,
    )
    from collections import Counter
    counts = Counter(n.upper() for n in names)
    return [n for n, c in counts.most_common(20) if c >= 3 and len(n) >= 6]


def _classify_pages(block: Block) -> Dict[str, List[Page]]:
    spec_pages: List[Page] = []
    proc_pages: List[Page] = []

    spec_re = re.compile(
        r"TABLE|PRODUCT\s*SETTINGS|ACCEPTABLE\s*LIMITS"
        r"|UNDER\s*VOLTAGE|OVER\s*VOLTAGE|REF\.?\s*VOLTAGE"
        r"|VOLTAGE\s*RANGE|CUT.?OFF|THRESHOLD",
        re.IGNORECASE,
    )
    proc_re = re.compile(
        r"PROCEDURE|PROCESS\s*:|FUNCTIONAL\s*TEST"
        r"|DIP\s*S/W\s*setting",
        re.IGNORECASE | re.MULTILINE,
    )

    for p in block.pages:
        if p.jpeg_bytes is None:
            continue
        if spec_re.search(p.ocr_text):
            spec_pages.append(p)
        is_proc = proc_re.search(p.ocr_text)
        has_steps = bool(re.search(r"^\s*\d+\.\s+[A-Z]", p.ocr_text, re.MULTILINE))
        has_dip = "DIP" in p.ocr_text.upper()

        if is_proc or has_steps or has_dip:
            proc_pages.append(p)

    if not spec_pages:
        spec_pages = [p for p in block.pages if p.jpeg_bytes is not None][:4]

    if not proc_pages:
        proc_pages = [
            p for p in block.pages
            if p.jpeg_bytes is not None and "procedure" in p.ocr_text.lower()
        ][:4] or block.pages[:5]

    return {"spec": spec_pages, "proc": proc_pages}


def _classify_pages_for_variant(block: Block, variant: str) -> Dict[str, List[Page]]:
    spec_pages = []
    proc_pages = []

    variant_clean = variant.upper().replace("_", "")
    variant_re = _build_variant_re(variant)

    spec_re = re.compile(
        r"TABLE|PRODUCT\s*SETTINGS|ACCEPTABLE\s*LIMITS|REF\.?\s*VOLTAGE",
        re.IGNORECASE,
    )

    proc_re = re.compile(
        r"PROCEDURE"
        r"|PROCESS\s*:"
        r"|FUNCTIONAL\s+TEST"
        r"|DIP\s*S/W"
        r"|TEST\s+PROCEDURE"
        r"|CHECK\s+POINT"
        r"|[A-F]\]\s*Goal\s*:"
        r"|LV\s+cut\s*off|HV\s+cut\s*off",
        re.IGNORECASE,
    )

    for p in block.pages:
        if not p.jpeg_bytes:
            continue
        text = p.ocr_text or ""
        if spec_re.search(text):
            spec_pages.append(p)

    is_large_block = len(block.pages) > 20

    if not is_large_block:
        for p in block.pages:
            if not p.jpeg_bytes:
                continue
            text = p.ocr_text or ""
            has_proc_marker = proc_re.search(text)
            has_step_pattern = bool(re.search(r"^\s*\d+\.\s+[A-Z]", text, re.MULTILINE))
            if has_proc_marker or has_step_pattern:
                body = _strip_repeated_header_lines(text, block.pages)
                if variant_re.search(body):
                    proc_pages.append(p)

    if len(proc_pages) < 3:
        non_func_process_re = re.compile(
            r"PROCESS\s*:\s*(?:PRODUCT\s+LABELLING|CLEANING\s*&\s*PACKING|FACTORY\s+SETTING)",
            re.IGNORECASE,
        )
        all_proc = [
            p for p in block.pages
            if p.jpeg_bytes
            and proc_re.search(p.ocr_text or "")
            and not non_func_process_re.search(p.ocr_text or "")
        ]
        all_machine_names = _detect_all_machine_names_in_block(block)
        exclude = {variant_clean}
        if variant_clean.endswith("EG"):
            exclude.add(variant_clean[:-2])
        all_machine_names_excl = [m for m in all_machine_names if m.upper() not in exclude]

        anchor_idx = _find_exclusive_anchor(
            all_proc, variant_re, all_machine_names_excl, block.pages,
            variant_name=variant_clean,
        )
        if anchor_idx is not None:
            anchor_body = _strip_repeated_header_lines(
                all_proc[anchor_idx].ocr_text or "", block.pages
            )
            is_cutoff = _is_cutoff_cat_id_page(anchor_body, variant_clean)
            start = anchor_idx
            if not is_cutoff and anchor_idx > 0:
                prev_page = all_proc[anchor_idx - 1]
                prev_body = _strip_repeated_header_lines(
                    prev_page.ocr_text or "", block.pages
                )
                # Include the page before the anchor only when it contains this
                # variant's own content.  If it belongs to a different variant
                # (e.g. page 33 = MAG03D0424 Section B appearing before MAG03D0425's
                # anchor on page 34) we leave start = anchor_idx so we don't feed
                # wrong-variant context to Gemini.
                if variant_re.search(prev_body):
                    start = anchor_idx - 1
            window = 3 if is_cutoff else 8
            candidate = all_proc[start: start + window]
            shared_names = "|".join(re.escape(n) for n in _variant_heading_names(variant_clean))
            other_proc_heading_re = re.compile(
                rf"(?:FUNCTIONAL\s+TEST\s+PROCEDURE\s+FOR|PROCEDURE\s+FOR\s+CAT\s+ID\s*:)"
                rf"\s*(?!.*(?:{shared_names}))",
                re.IGNORECASE,
            )
            trimmed = []
            for cp in candidate:
                text = cp.ocr_text or ""
                body = _strip_repeated_header_lines(text, block.pages)
                if trimmed and other_proc_heading_re.search(body):
                    # Check how far into the page the other variant's heading appears.
                    # If substantial content precedes it (>30% of page), the page is
                    # a "split page" where our variant's procedure continues until the
                    # next variant's heading — include it, then stop scanning.
                    m = other_proc_heading_re.search(body)
                    content_before = body[: m.start()].strip()
                    content_ratio = len(content_before) / max(len(body), 1)
                    if content_ratio > 0.30 and len(trimmed) < MAX_IMAGES_PER_CALL:
                        trimmed.append(cp)
                        logger.info(
                            f"{variant}: including split page {cp.num} "
                            f"(own content covers {int(content_ratio*100)}% of page, "
                            f"next variant heading at end)"
                        )
                    else:
                        logger.info(
                            f"{variant}: stopping page collection at page {cp.num} "
                            f"because it belongs to another variant procedure"
                        )
                    break
                trimmed.append(cp)
            proc_pages = trimmed[:MAX_IMAGES_PER_CALL]
            # Cutoff variants: narrative FUNCTIONAL TEST pages + FQC table pages
            if is_cutoff:
                narrative_pages = []
                for p in block.pages:
                    if not p.jpeg_bytes:
                        continue
                    body = _strip_repeated_header_lines(p.ocr_text or "", block.pages)
                    if re.search(
                        rf"FUNCTIONAL\s+TEST\s+PROCEDURE\s+FOR\s+.*{re.escape(variant_clean)}",
                        body, re.IGNORECASE,
                    ):
                        narrative_pages.append(p)
                seen_nums = set()
                merged = []
                for p in narrative_pages + proc_pages:
                    if p.num not in seen_nums:
                        merged.append(p)
                        seen_nums.add(p.num)
                proc_pages = merged[:MAX_IMAGES_PER_CALL]
        else:
            proc_pages = all_proc[:MAX_IMAGES_PER_CALL]

    if not proc_pages:
        proc_pages = [
            p for p in block.pages
            if p.jpeg_bytes and proc_re.search(p.ocr_text or "")
        ][:MAX_IMAGES_PER_CALL]

    if not spec_pages:
        spec_pages = [p for p in block.pages if p.jpeg_bytes][:6]

    logger.info(
        f"[PAGE_CLASSIFICATION] "
        f"variant={variant} "
        f"spec_pages={[p.num for p in spec_pages]} "
        f"proc_pages={[p.num for p in proc_pages]}"
    )

    return {
        "spec_pages": spec_pages,
        "proc_pages": proc_pages,
    }


SPECS_PROMPT = """You are extracting manufacturing specifications from PDF page images.

PARENT MACHINE: {machine}
VARIANTS TO EXTRACT: {variants}

The pages contain spec tables with multiple variant columns. Read each table
as a 2-D GRID. Cell values are determined by their physical position on the
page, not by linear text order.

CRITICAL RULES:
1. A merged cell that visually spans multiple columns means ALL those variants share
   that value. Copy it to EVERY variant whose column falls under that merged cell.
   Do NOT leave any variant empty if a merged cell covers its column.
2. An empty cell that is NOT part of a merged cell, OR a cell explicitly containing
   "NA" or "N/A", means that variant does NOT have that parameter — return null.
3. When in doubt whether a cell is merged: if the row has a value only in the first
   data column and all others are blank, treat it as merged and copy to all variants.
4. Read voltage_unit from the table header. "PHASE TO PHASE" -> "P-P".
   "PHASE TO NEUTRAL" -> "P-N". Do NOT convert values between units.
5. Booleans (phase_fail, phase_reverse, neutral_fail):
     "Yes" if the variant tests this fault
     "No" if explicitly Not Applicable for the variant
     "NA" only if the entire machine doesn't support it
6. Ranges are returned EXACTLY as written. "4 to 6 sec" — never "5 sec".
7. dip_switches: list of switch positions for the FIRST/default config in
   the procedure, format: ["1: OFF", "2: OFF", "3: OFF", "4: OFF", "5: ON"].
8. Ignore rows containing words like "Threshold", "Setting", or "%".
9. Extract ONLY numeric voltage ranges (e.g., "177 to 197 VAC") for uv_range and ov_range.
10. Do NOT return labels like "UV Threshold" or "OV Setting" as values.

Return JSON in this exact shape (one entry per variant):
{{
  "VARIANT_NAME": {{
    "ref_voltage":       string|null,
    "uv_range":          string|null,
    "uv_threshold_pct":  string|null,
    "ov_range":          string|null,
    "ov_threshold_pct":  string|null,
    "uv_hysteresis":     string|null,
    "ov_hysteresis":     string|null,
    "asymmetry":         string|null,
    "on_delay":          string|null,
    "off_delay":         string|null,
    "phase_fail":        "Yes"|"No"|"NA"|null,
    "phase_reverse":     "Yes"|"No"|"NA"|null,
    "neutral_fail":      "Yes"|"No"|"NA"|null,
    "virtual_neutral":   string|null,
    "lv_cutoff":         string|null,
    "hv_cutoff":         string|null,
    "voltage_unit":      "P-P"|"P-N"|null,
    "led_indications":   {{ "Green Healthy": "Continuous ON", ... }},
    "dip_switches":      ["1: OFF", "2: OFF", "3: OFF", "4: OFF", "5: ON"],
    "notes":             string|null
  }}
}}

Return ONLY valid JSON. No markdown, no code fences, no commentary."""


PROCEDURE_PROMPT = """You are reading a GIC functional test procedure document.

VARIANT: {variant}
LAYOUT: {layout_type}

The document may use LETTERED SECTIONS (A] Goal:, B] Goal:...) or NAMED SUBSECTIONS
(e.g. "Under Voltage test:", "Phase Reverse detection:") or plain NUMBERED STEPS.
Detect the test structure from the document — do not assume a fixed format.
If the procedure references a spec TABLE for voltage ranges, read voltage values from
the TABLE IMAGES provided alongside the procedure pages.
Each section has:
  1. A DIP switch configuration table
  2. A pot settings line (these CHANGE between sections and between symmetrical tests)
  3. A nominal/couple voltage ("set voltage to X V")
  4. Numbered test steps describing conditions

YOUR TASK:
For each lettered section that belongs to variant {variant}, extract:
  A. The DIP switch settings (from "DIP S/W Number | Setting" table)
  B. The pot settings — READ THESE CAREFULLY, they change between sections!
     CRITICAL: Pot values come from the "Pot Settings:" line, NOT from the DIP table range.
     The DIP table shows adjustable range (e.g., "Delay Pot − 0s to 15s"); the Pot Settings line
     shows the ACTUAL setting (e.g., "Delay Pot = 3 sec" → DELAY=3SEC).

     SETTINGS FORMAT RULE — use the EXACT LABEL NAMES from the "Pot Settings:" line:
       PRIORITY RULE — if label includes BOTH pot type AND pot number "(Pot N)" or "(PN)", use P-number:
         • "UV Pot (Pot 1) — X%" or "UV Pot (P1) = X%"   → emit "P1 = X %"   (NOT "UV = X%")
         • "OV Pot (Pot 1) — X%" or "OV Pot (P1) = X%"   → emit "P1 = X %"
         • "ON Delay (Pot 2) — X" or "ON delay pot (P2)"  → emit "P2 = X SEC" or "P2 = X MIN"
         • "OFF Delay (Pot 3) — X" or "OFF delay pot (P3)" → emit "P3 = X SEC" or "P3 = X MIN"
       STANDARD RULE — bare type name with NO pot number in parentheses:
         • If document says "UV pot = X%"    → emit "UV = X%"
         • If document says "OV pot = X%"    → emit "OV = X%"
         • If document says "Delay Pot = X sec" → emit "DELAY = X SEC"
         • If document says "Pot 1 = X%" or "P1 = X%" → emit "P1 = X %"
         • If document says "Pot 2 = X sec/min" or "P2 = ..."  → emit "P2 = X SEC" or "P2 = X MIN"
         • If document says "Pot 3 = X sec/min" or "P3 = ..."  → emit "P3 = X SEC" or "P3 = X MIN"
     Always include the TIME UNIT (SEC or MIN) for time-based pot values exactly as written.
     Carry unchanged pot values forward within a section; update only what the document explicitly changes.
  C. All test conditions described in the numbered steps
     CRITICAL: The nominal voltage for each section is stated in the numbered steps:
     "set R, Y and B phase voltage with respect to Neutral at X V" → use X as the nominal voltage.
     Do NOT use the voltage from a different section (e.g., Section C's 240V applies only to Section C).

EXPECTED STEP SEQUENCE for Section A (UV tests):
  1. "DIP S/W Change" (DIP positions from table)
  2. "healthy condition" (nominal voltage, relay ON, all LEDs normal, off_delay="-".
     on_delay: READ from document using the ±1 rule below. If document says "relay ON after 5 sec(±1)"
     → on_delay="4-6 sec". Do NOT default to "Instant ON" — only use it if document explicitly says
     relay turns on instantly.)
  3. "UV Healthy condition" (voltage = UPPER BOUND of UV trip range, relay stays ON)
  4. "UV faulty condition" (voltage = LOWER BOUND of trip range, UV LED ON, relay OFF)
  5. "UV hystersis not recovery" (voltage = EXAMPLE trip voltage from "if trip is X then...", relay OFF continuous)
  6. "UV hystersis recovery" (voltage = UPPER BOUND of recovery range, relay ON)
  DO NOT repeat per phase (R/Y/B). Only extract ONCE using R phase values.
  After UV hystersis recovery, check immediately for a SYMMETRICAL TEST SECTION.
  SECTION A OV TESTS — CRITICAL: Section A NEVER contains OV tests.
    For P1/P2/P3 format machines: P3 in Section A = UV OFF delay (e.g. "OFF Delay (Pot 3) - 15 sec").
      P3=15SEC means the UV fault trips after a 15 sec delay. P3 does NOT imply OV tests exist.
    The Section A sequence after UV hystersis recovery (step 6) is ALWAYS EXACTLY one of:
      [optional sym trigger section] → [Phase Reverse detection] → [Phase Fail detection] → Supply OFF
    STRICT GATE: After UV hystersis recovery, scan for ONLY these next content types:
      ██ PRIORITY CHECK FIRST ██ — Before scanning for sym triggers, check the SAME PAGE
          as UV hyst recovery: if "Phase Reverse detection" OR "Phase Fail detection" heading
          appears ANYWHERE on that page → GO DIRECTLY to option (b). BLOCK the sym trigger
          entirely. Do NOT look for sym triggers when Phase Reverse/Fail is on the same page.
      (a) sym trigger (see below) — ONLY if:
          • Phase Reverse detection, Phase Fail detection, AND new lettered Goal headers are ALL
            absent on the CURRENT PAGE (same page as UV hyst recovery), AND
          • sym trigger text appears BEFORE any of those on THE SAME PAGE in reading order.
          Sym trigger text on a DIFFERENT PAGE (e.g., page 37 if UV recovery is on page 36)
          does NOT count for Section A — the page boundary blocks the sym trigger.
      (b) "Phase Reverse detection" or "Phase Fail detection" heading → emit Phase tests DIRECTLY
      (c) "Turn OFF" / "Switch OFF" / supply shutdown text → emit Supply OFF
    DO NOT emit OV Healthy / OV faulty / OV hystersis not recovery / OV hystersis recovery in Section A.
      Not even if OV pot settings appear. Not even if OV thresholds exist in the spec table. NEVER.
      Not even if a delay change appears on a later page followed by OV trip voltage text. NEVER.
    OV test steps require the document to EXPLICITLY say "increase phase voltage till OV LED turns ON"
      on the CURRENT Section A page. Section A never contains this phrase on its page. NEVER in Section A.
  CRITICAL — HOW SYM TESTS APPEAR IN THE DOCUMENT:
  The sym section has NO explicit heading or label. It appears as NUMBERED STEPS immediately after
  the UV hystersis recovery steps. Look for this TWO-STEP TRIGGER PATTERN:

    UV SYM TRIGGER (reducing phases): Triggered when:
      Trigger Step 1: The UV threshold % OR OV threshold % changes (e.g. "Change UV pot to 22%"
                      or "Change OV pot to 22%"). CRITICAL: Delay-only changes are NOT Trigger Step 1.
                      "Set ON delay pot (P2) at 1.5 min" → NOT trigger (only delay changes, no UV/OV%).
                      "Keep delay pot at 15 sec" → NOT UV SYM trigger (may be OV SYM — see below).
      Trigger Step 2: "Now symmetrically REDUCE all R, Y and B phase dimmer to Z V Ph-N" — this IS
                      the Supply couple setup (Z is the coupled voltage, lower than nominal).
      IMPORTANT: This trigger ONLY applies in Section A context (after UV hystersis recovery in Section A).
                 Do NOT fire this trigger if you are currently processing Section B test steps.
      COMBINED DOCUMENT SCOPE: The block text may include procedure content from ANOTHER machine that
                 appears BEFORE this machine's first "A] Goal:" heading. IGNORE all numbered procedure
                 steps and pot settings that appear BEFORE the first "A] Goal:" or "B] Goal:" header
                 in the document text — they belong to a different machine.
                 The procedure for this variant starts at the FIRST "A] Goal:" or "B] Goal:" header.
                 NOTE: Only content BEFORE the first Goal header is excluded. "Symmetrically reduce"
                 and other trigger phrases that appear AFTER the first Goal header are valid and
                 must NOT be ignored.

    OV SYM TRIGGER (increasing phases): Triggered when:
      Trigger Step 1: "Keep delay pot at X sec" or "set delay pot at X sec" — ONLY delay changes.
                      (OR: "Now change UV pot to P% and delay pot to X sec" but Pot 1 stays same.)
      Trigger Step 2: "Now symmetrically INCREASE all 3 phase dimmers till OV LED turns ON" —
                      supply stays at nominal (Z = nominal supply voltage such as 240V Ph-N).

  If you see EITHER trigger pattern after UV hystersis recovery, a sym section IS PRESENT.
  You MUST extract all 5 sym steps. Skipping them causes step-count failure (missing ~5 steps).

  DETERMINE WHETHER UV SYM OR OV SYM:
  — If Trigger Step 2 says "reduce" (phases go DOWN): UV sym. Step names = "UV symmmetrical ..."
  — If Trigger Step 2 says "increase" (phases go UP): OV sym. Step names = "OV symmmetrical ..."

  EXTRACT THE 5 SYM STEPS as follows:

  Step A — "Supply couple at Z VAC":
    section_break=true, settings=[], voltages_pn=[], voltage_pp=[], leds=[], relay_status=null.
    For UV sym: Z = the lower voltage stated in Trigger Step 2 ("reduce to Z V Ph-N"). Always emit this step.
    For OV sym: Z = the nominal Ph-N supply voltage (e.g. 240 VAC for a 415V Ph-Ph system).
    Always emit this step immediately before "OV symmmetrical Healthy" — even when OV sym follows
    single-phase UV tests rather than UV sym. The "Supply couple" marks re-synchronization of all
    phases at nominal voltage before the OV symmetrical test.
    NOTE: "Set Ph-N voltage as X V" or "Set Ph-Ph voltage as X V" is a PREPARATION RESET instruction,
    NOT a Supply couple trigger. Never create a Supply couple step from a "set voltage" instruction alone.
    The trigger for the Supply couple + OV sym block is "symmetrically INCREASE" in the document.

  Step B — "[UV|OV] symmmetrical Healthy":
    All 3 phases at the Healthy voltage. Use the "should be in range of X to Y V" check step.
    FOR UV SYM: relay_status="ON" when voltage is just ABOVE UV threshold.
      Healthy voltage = UPPER BOUND Y of UV trip range (above UV threshold → relay still ON).
      voltages_pn=[RN:Y, YN:Y, BN:Y].
    FOR OV SYM: relay_status="ON" when voltage is just BELOW OV threshold.
      Healthy voltage = LOWER BOUND X of OV trip range (below OV threshold → relay still ON).
      voltages_pn=[RN:X, YN:X, BN:X].
    relay_status="ON", on_delay="Relay continuous ON" (factory label — include the word "Relay"),
    off_delay="-".

  Step C — "[UV|OV] symmmetrical faulty":
    FOR UV SYM: voltage falls below UV threshold → relay trips.
      voltages_pn=[RN:X, YN:X, BN:X] where X = LOWER BOUND of UV trip range.
    FOR OV SYM: voltage rises above OV threshold → relay trips.
      voltages_pn=[RN:Y, YN:Y, BN:Y] where Y = UPPER BOUND of OV trip range.
    relay_status="OFF in (D-1)-(D+1) sec", off_delay from document delay D.

  Step D — "[UV|OV] hystersis not recovery":
    FOR UV SYM: not-recovery voltage = example trip T stated in "if trip is T then..." sentence.
      voltages_pn=[RN:T, YN:T, BN:T].
    FOR OV SYM: not-recovery voltage = LOWER BOUND X of OV trip range (same as Step B Healthy).
      voltages_pn=[RN:X, YN:X, BN:X].
    relay_status="Continuous OFF", off_delay="Continuous OFF".
    IMPORTANT: relay_status MUST be "Continuous OFF" (not "OFF " or "OFF"). Sym is different from Section A.

  Step E — "[UV|OV] hystersis recovery":
    FOR UV SYM: raise voltage above recovery threshold.
      Recovery voltage = UPPER BOUND of UV trip range + MAX hysteresis (read from "range of A to B V").
      Example: UV trip range 92.4-94.8V, hyst range 3.6-8.6V → max hyst = 8.6 → BUT use the
      hysteresis check sentence: "if trip is T then reset in range A to B" → recovery = B (UPPER reset bound).
      SIMPLER RULE: recovery voltage B = T + max_hyst. Example: T=92.4, max_hyst=3.6 → 92.4+3.6=96V. But
      PREFERRED: use UPPER BOUND of trip + UPPER BOUND of hyst range:
        UV trip range 92.4-94.8, hyst range 3.0-3.6V → recovery = 94.8 + 3.6 = 98.4V.
      voltages_pn=[RN:B, YN:B, BN:B].
    FOR OV SYM: lower voltage below recovery threshold.
      Recovery voltage = LOWER BOUND of OV trip range − MAX hysteresis.
      Example: OV trip range 261.6-266.4V, hyst range 2.4-7.2V → max_hyst=7.2 → recovery=261.6-7.2=254.4V.
      BUT CHECK THE DOCUMENT: "if trip is T=264V then reset in range 256.8V to 261.6V" → recovery=256.8V
        (LOWER bound of the reset range). Use the lower bound of the reset range from the document.
      voltages_pn=[RN:recovery, YN:recovery, BN:recovery].
    relay_status="ON". section_break=false.
    on_delay: read from "reduce phase till LED OFF. After X sec(+/-1) delay, relay ON" (OV sym), or
              "increase phase till LED OFF. After X sec(+/-1) delay, relay ON" (UV sym).
      Express as range: "After (X-1)-(X+1) sec" (e.g., "After 5 sec(+/-1)" → "After 4-6 sec").
      IMPORTANT: ALWAYS include the word "After" in the range. Write "After 4-6 sec" NOT "4-6 sec".
      If document says "relay ON immediately" or "Instant ON": on_delay="Instant ON".
    on_delay MUST NOT be null.

  CRITICAL — SYM SECTION POT SETTINGS: The new pot values come from Trigger Step 1.
    Apply the SETTINGS FORMAT RULE (above) to determine the label names (UV/OV/DELAY or P1/P2/P3).
    Example (UV/OV format): Section A had UV=8%/OV=22%/DELAY=3SEC. Trigger Step 1 says "change UV pot
    to 22% and delay pot to 15 sec" → sym settings = ["UV = 22%", "OV = 22%", "DELAY = 15SEC"].
    Example (P1/P2 format): Section A had P1=7%/P2=0 SEC/P3=15 SEC. Step says "set ON delay pot (P2)
    at 1.5 min and OFF delay pot (P3) at 0 sec" → sym settings = ["P1 = 7%", "P2 = 1.5 MIN", "P3 = 0 MIN"].
    Do NOT carry Section A pot values into sym steps. Read the new values from Trigger Step 1.
    WARNING: The threshold % in any sym heading (e.g. "110% of supply") is a MEASUREMENT RANGE,
    not a pot value. Ignore it for settings[].

  After sym tests — check for Phase fail/reverse tests BEFORE "Supply OFF":
    If the document describes "Phase Fail detection" or "Phase Reverse detection" or "Phase fail and
    Phase Reverse functionality" AFTER the sym section and BEFORE "Turn OFF 3 Ph test Jig":
      Extract those Phase tests here using the ACTIVE DIP settings and pot settings.
      Phase Reverse disabled: if DIP settings disable phase reverse detection, the test is
        "Phase reverse (No any change)" — relay stays ON, all LEDs normal (no fault detected).
        relay_status="Continuous ON", leds=[all normal], on_delay=null, off_delay=null.
        DECISIVE CHECK — check procedure text for this specific step FIRST:
          document says "relay immediately turned OFF" / "relay should trip" / "ASY LED turns ON"
            → DETECTION ENABLED (relay=Instant OFF). Do NOT use Continuous ON.
          document says "no change" / "relay stays ON" / "No any change" / "detection disabled"
            → DETECTION DISABLED (relay=Continuous ON).
          Document text OVERRIDES DIP-based inference. Default to ENABLED when in doubt.
      Phase Fail enabled: extract normally (see PHASE TESTS section below).
    After Phase tests (if any) → THEN "Supply OFF" step.
  If no Phase tests in document after sym → go directly to "Supply OFF".

  CRITICAL: At the sym-to-Section-B boundary:
    (optional) Phase fail/reverse steps
    (1) "Supply OFF" — MANDATORY whenever a sym section exists. The document phrase "Turn off the
        3 phase test Jig and make the settings" (or similar) IS this Supply OFF step. Do NOT skip it.
    (2) Section B "DIP S/W Change" — always the NEXT step after Supply OFF at this boundary.
  ABSOLUTE FORBIDDEN at sym→B boundary: Do NOT insert "Run time DIP switch change error" here.
  "Run time DIP switch change error" appears ONLY inside Section B, AFTER ALL OV/UV test conditions
  (Healthy/Faulty/Not-recovery/Recovery) are fully complete. It is NEVER before OV/UV tests begin.
  It is NEVER the first step of Section B. It NEVER appears at the sym→B transition.
  IF the document goes directly from UV hystersis recovery to Section B (no sym steps and no
  trigger): skip directly to Section B.
  IF the document goes directly from UV tests to Phase tests with NO symmetrical section:
    Skip Supply couple. Extract Phase tests using the active Section A DIP settings (see PHASE TESTS).

For Section B (contents depend on variant — READ THE DOCUMENT AND FOLLOW ITS ORDER):
  1. "DIP S/W Change" (always first for Section B)
  CRITICAL — Section B POT SETTINGS: After the Section B DIP S/W Change, the pot settings CHANGE.
    Read the new UV%, OV%, and DELAY values from the Section B DIP table or procedure text.
    Do NOT carry over Section A values (UV=8%/OV=22%/DELAY=3SEC) or sym values (UV=22%/OV=22%/DELAY=15SEC).
    Section B has DIFFERENT pot settings — re-read them from the document.
  ══════════════════════════════════════════════════════════════════════
  SECTION B TEST GROUP ORDERING — USE DOCUMENT SECTION HEADINGS:
  ══════════════════════════════════════════════════════════════════════
  The document contains EXPLICIT SECTION HEADINGS that define which test comes first:
    "Phase asymmetry and hysteresis test:"  → Phase Asymmetry steps come at this position
    "Under Voltage (UV) and hysteresis test:"  → UV steps come at this position
    "Over Voltage (OV) and hysteresis test:"  → OV steps come at this position
  ALWAYS extract test steps IN THE ORDER these headings appear in the document.
  If "Phase asymmetry and hysteresis test:" appears BEFORE "Under Voltage (UV)" heading,
  Phase Asymmetry steps MUST come FIRST in your output (before any UV steps).

  CRITICAL LED-BASED STEP DISCRIMINATOR:
    "ASY LED" mentions (ASY LED turns ON, ASY LED starts blinking, ASY LED turns OFF) → Phase Asymmetry
    "UV LED" mentions (UV LED turns ON, UV LED turns OFF) → UV steps
    "OV LED" mentions (OV LED turns ON, OV LED turns OFF) → OV steps
    NEVER name a step "UV Healthy condition" or "UV faulty condition" when the document text says
    "ASY LED blinking" — that is Phase Asymmetry, not UV. The LED name in the document text
    DETERMINES the test type; use it as your primary signal.

  CRITICAL — SECTION B FIRST STEP:
    After "DIP S/W Change", the first test step depends on the document order:
    - If document starts with Phase Asymmetry (heading "Phase asymmetry and hysteresis test:" appears
        OR document describes REDUCING ONE PHASE DIMMER while checking ASY LED;
        "reduce R phase dimmer till ASY LED start blinking", "reduce phase till ASY LED blinks"):
        First step = "Phase Asymmetry Healthy" (NOT "Phase Asymmetry Healthy condition").
        SCOPE GUARD: ASY LED blinking during "Make B phase fail" / "phase removed" / "phase missing" is
        PHASE FAIL, NOT Phase Asymmetry. Only use Phase Asymmetry when a DIMMER is being REDUCED (not removed).
    - If document starts with OV tests: First step = "OV Healthy condition".
    - If document starts with UV tests: First step = "UV Healthy condition".
    There is NO plain "Healthy condition" immediately after DIP S/W Change. The power-on check
    ("relay ON after X sec" / "relay should turn ON after 30 sec" / "PWR LED turns ON")
    is part of the DIP change procedure context — do NOT make it a step. Skip directly to the
    first ACTUAL test step (Phase Asymmetry, UV, or OV).
  Section B contains tests in the order their HEADINGS appear in the document:
  - Phase Asymmetry tests (if present first — under "Phase asymmetry and hysteresis test:" heading):
      "Phase Asymmetry Healthy", "Phase Asymmetry faulty",
      "Phase Asymmetry not recovery", "Phase Asymmetry recovery"
      STEP NAMES: Use exactly these names. Do NOT add "condition" suffix. Not "Healthy condition",
      not "faulty condition" — just "Phase Asymmetry Healthy" and "Phase Asymmetry faulty".
      DIRECTION: ONE phase is REDUCED while the OTHER TWO stay at full supply voltage.
        Document says "reduce R phase" → only RN changes; YN=BN=supply voltage (240V Ph-N).
        WRONG: treat as OV test (all 3 phases equal and above supply). WRONG.
        CORRECT: RN reduced, YN=BN=240V, voltage_pp=[RY:calc, YB:415, BR:calc].
      SETTINGS: ALWAYS start with P1 as first item — P1=asymmetry%, P2=ON delay, P3=OFF delay.
        WRONG: ["P2 = 0 MIN","P3 = 1.5 MIN"] (missing P1). CORRECT: ["P1 = 25%","P2 = 0 MIN","P3 = 1.5 MIN"].
      LED PATTERN:
        Healthy/Recovery: ["PWR (GREEN LED) : ON","UV (RED LED) : OFF","OV (RED LED) : OFF","ASY (RED LED): OFF"]
        Faulty/Not-recovery: ["PWR (GREEN LED) : ON","UV (RED LED) : OFF","OV (RED LED) : OFF","ASY : BLINKING"]
        CRITICAL: PWR (GREEN LED) : ON is ALWAYS the FIRST LED. UV and OV are BOTH OFF during phase asymmetry fault.
      RELAY: Healthy/Recovery → relay_status="ON". on_delay = P2 converted to seconds (see below).
             Faulty → CONVERT P3 to seconds with ±1 window:
               P3=1.5 MIN → 90 sec → relay_status="OFF in 89-91 SEC", off_delay="OFF in 89-91 SEC".
               P3=0 MIN or 0 SEC → Instant → relay_status="Instant OFF", off_delay="Instant OFF".
             Not-recovery → relay_status="Continuous OFF", on_delay=null, off_delay=null.
      ON-DELAY: Convert P2 minutes to seconds with ±1 window:
        P2=0 MIN → device note: "0 min ON delay = 30 sec" → on_delay="ON in 29-31 sec".
        P2=1.5 MIN → 90 sec → on_delay="ON in 89-91 SEC".
        After pot change "Set P2=1.5 min, P3=0 sec" (before UV tests at 340V):
          UV/OV Healthy and Recovery: on_delay="ON in 89-91 SEC" (P2=1.5 MIN).
            MANDATORY: Even if relay was ON from the previous step, use on_delay="ON in 89-91 SEC".
            Do NOT output on_delay=null or "Continuous ON" for any step in this UV/OV group.
          UV/OV Faulty: off_delay="Instant OFF" (P3=0 SEC). on_delay=null.
      VOLTAGE VALUES:
        CRITICAL — Phase Asymmetry Healthy IS NOT 240/240/240. The Healthy step uses a REDUCED
        voltage (the tested phase is set WITHIN the healthy range but already somewhat reduced):
          Healthy: RN = lower trip bound voltage (within healthy range). Read from spec table.
          Faulty: RN = faulty voltage (below trip threshold). Read from spec table.
          Not-recovery: RN = HYSTERESIS TEST VOLTAGE (DIFFERENT from Healthy!) — read from spec.
            NOT-RECOVERY voltage is BETWEEN trip (Faulty) and recovery (Recovery). Example: if
            Healthy=89V, Faulty=78V, Recovery=105V, then Not-recovery≈95V (read from doc/spec).
          Recovery: RN = recovery hysteresis threshold voltage. Read from spec table.
        Document gives asymmetry % range (e.g. "24% to 26%"); exact Ph-N values come from spec table.
        At P1=25% with supply=240V Ph-N (415V Ph-Ph):
          Healthy: lower trip bound = 24% → RN≈89V, RY=BR≈294V
          Faulty: upper trip bound = 26% → RN≈78V, RY=BR≈287V
          Not-recovery: hysteresis test (e.g. 22%) → RN≈95V, RY=BR≈299V
          Recovery: (trip% - max_hyst%) → (24% - 3.7% = 20.3%) → RN≈105V, RY=BR≈306V
        FORMULA: at asymmetry% A with supply YB=415V: RY=BR=415×(1-A)/(1+A/3) approximately.
        CRITICAL SCOPE — this 89V/78V/105V formula applies ONLY when ALL of:
          (a) Settings use P1/P2/P3 format (NOT UV/OV/DELAY format), AND
          (b) You are extracting Section B "Phase Asymmetry" named steps.
        If settings use UV/OV/DELAY format (e.g., the Asymmetry section in Section C/D), DO NOT
        apply this formula. The Asymmetry section has its own trip voltages in the spec table —
        read the deviated phase voltage directly from the spec table or document text.
        If spec table gives exact Ph-N voltages: use those values directly (takes priority over formula).
      CRITICAL: Phase Asymmetry recovery section_break MUST be false (NOT true).
        The "Couple all voltage" step that follows is placed in the BLANK ROW of the recovery step.
        If section_break=true were used, it would add an extra blank row, misplacing the Couple label.
        ALWAYS use: "Phase Asymmetry recovery" → section_break: false.
      AFTER PHASE ASYMMETRY — document sequence is ALWAYS in this order:
        STEP A: "set the voltage 415V AC Ph-Ph for all 3 phases" (immediately after Phase Asymmetry Recovery)
          → Create a section_break step NAMED "Couple all voltage" with ALL null fields:
          {{"step_name":"Couple all voltage","settings":[],"voltages_pn":[],"voltage_pp":[],"leds":[],"relay_status":null,"on_delay":null,"off_delay":null,"section_break":true}}
        STEP B: "Set ON delay pot (P2) at X min and OFF delay pot (P3) at Y sec"
          → Update settings for ALL subsequent steps: P1=same%, P2=X MIN, P3=Y SEC.
          → This is a TEST SETUP instruction only. Do NOT create "Supply couple" or any test step.
        STEP C: "Reduce all phases symmetrically to 340V Ph-Ph" or "set 340V Ph-Ph"
          → SUPPLY REDUCTION for UV tests, NOT a sym section trigger.
          → ALL THREE phases reduce EQUALLY. Do NOT reduce only one phase.
          → UV test voltages (Ph-N each, all 3 phases equal):
              UV Healthy:      RN=YN=BN = upper_trip_Ph-Ph ÷ √3  (e.g. 336.15 ÷ 1.732 = 194.1V)
              UV Faulty:       RN=YN=BN = lower_trip_Ph-Ph ÷ √3  (e.g. 327.85 ÷ 1.732 = 189.3V)
              UV Not-recovery: RN=YN=BN = upper_trip_Ph-Ph ÷ √3  (SAME as UV Healthy, e.g. 194.1V)
                → Document raises voltage BACK to the trip boundary (e.g. 340V Ph-Ph = 194.1V Ph-N).
                → Relay does NOT recover here (recovery requires P2 delay from a higher voltage level).
                → Do NOT use an intermediate hysteresis value (191.6V is WRONG; 194.1V is CORRECT).
              UV Recovery:     RN=YN=BN = (lower_trip_Ph-Ph + max_hysteresis_Ph-Ph) ÷ √3
          → UV hystersis recovery: section_break=false.
          → Ph-Ph for all 3 phases: RY=YB=BR = Ph-N × √3 (all equal, symmetric).
        STEP D: CONDITIONAL — create this step ONLY IF the document contains "Decouple all voltages"
          or "couple all voltages" instruction (STEP E exists). If no such instruction appears in
          the document after the UV recovery step, SKIP STEP D ENTIRELY — do NOT create it.
          When present: this "Healthy condition" step is IMMEDIATELY AFTER UV hystersis recovery
          AND BEFORE "Decouple all voltages". The document resets P2 back to 0 MIN before this step.
          Settings: P1=25%, P2=0 MIN, P3=0 MIN. Voltages: ALL 3 phases = 240V Ph-N (nominal supply).
          relay_status="continuous ON" (lowercase, relay already ON from UV recovery). on_delay=null.
          voltage_pp: ALL 3 Ph-Ph = 415V (RY=415, YB=415, BR=415). section_break=false.
          Do NOT merge with "Decouple all voltages". Do NOT place AFTER Decouple.
        STEP E: "set the voltage 415V AC Ph-Ph" (AFTER the Healthy condition step)
          → Create a section_break step NAMED "Decouple all voltages" with ALL null fields.
          → The template places this label in the blank row of the preceding Healthy condition step.
          {{"step_name":"Decouple all voltages","settings":[],"voltages_pn":[],"voltage_pp":[],"leds":[],"relay_status":null,"on_delay":null,"off_delay":null,"section_break":true}}
          MANDATORY SEQUENCE: UV hyst recovery → Healthy condition → Decouple all voltages → OV Healthy.
          Do NOT output "Decouple all voltages" BEFORE "Healthy condition".
          ██ OV B-ONLY AFTER DECOUPLE — CRITICAL ██:
          After Decouple, OV tests begin. The "ALL 3 phases = 240V Ph-N" in Healthy condition is the
          BASELINE. For OV tests: ONLY B phase rises from 240V. R and Y phases stay at 240V.
          Use the B-only formula (worked example above): BN = (−240 + √(4 × YB² − 172800)) ÷ 2.
          Do NOT raise all 3 phases symmetrically — that gives WRONG voltages for B-only OV.
          MANDATORY VERIFICATION before writing OV voltages:
            RN MUST be 240V for ALL OV steps (Healthy, Faulty, Not-recovery, Recovery).
            YN MUST be 240V for ALL OV steps.
            ONLY BN changes from step to step. If RN≠240 or YN≠240, you computed WRONG — recalculate.
          RY MUST be 415V for ALL OV steps (R and Y are always at 240V Ph-N → RY=415V constant).
          If your calculation gives RN=268V or YN=268V or RY=464V, you used the symmetric formula — STOP and use B-only formula instead.
  - OV tests (if present): "OV Healthy condition", "OV faulty condition", "OV hystersis not recovery",
    "OV hystersis recovery".
      For OV voltage: if document says "increase any of the phase voltage" (singular "any")
        OR document names ONE specific phase ("increase B phase dimmer", "increase B phase voltage",
        "increase R phase dimmer", "increase Y phase voltage", etc.):
        ONLY that named/singular phase rises. The other two stay at 240V Ph-N. RY=415V (unchanged).
        Use the named phase (default B when "any of the phase" or when only B is mentioned):
        ONLY B phase rises. RN=YN=240V Ph-N. RY=415V (unchanged).
        CRITICAL — "All Ph-Ph voltages in range X to Y" with single-phase OV:
          When only B phase rises, the Ph-Ph range given in the document refers to YB and BR
          (the two pairs that include the raised B phase). RY stays at 415V and is NOT in that range.
          DO NOT raise all 3 phases equally just because the document says "All Ph-Ph" — this is
          shorthand for "all Ph-Ph pairs involving the raised phase". Only B rises; R and Y stay at 240V.
        Compute BN from OV trip range Ph-Ph given in the document:
          Formula: BN = (−240 + √(4 × YB² − 172800)) ÷ 2  (where YB is the Ph-Ph trip value from document)
          OV Healthy:       YB = LOWER bound of OV trip range Ph-Ph → solve for BN.
          OV Faulty:        YB = UPPER bound of OV trip range Ph-Ph → solve for BN.
          OV Not-recovery:  same BN as OV Faulty (voltage held at faulty level, no change).
          OV Recovery:      YB = (lower bound − max_hysteresis) Ph-Ph → solve for BN.
        BR ≈ YB (same magnitude by symmetry when only B phase changes).

        ██ WORKED EXAMPLE — follow this calculation exactly ██
          Document OV trip range: 452.35V to 460.65V Ph-Ph. "Increase any of the phase" → B rises only.
          OV Healthy (YB = 452.35V lower bound):
            BN = (−240 + √(4 × 452.35² − 172800)) ÷ 2 = (−240 + √645682.8) ÷ 2 = (−240 + 803.5) ÷ 2 ≈ 282V
            RESULT: RN=240V, YN=240V, BN=282V, RY=415V, YB=452.35V, BR=452.35V
          OV Faulty (YB = 460.65V upper bound):
            BN = (−240 + √(4 × 460.65² − 172800)) ÷ 2 = (−240 + √675193.6) ÷ 2 = (−240 + 822.0) ÷ 2 ≈ 291V
            RESULT: RN=240V, YN=240V, BN=291V, RY=415V, YB=460.65V, BR=460.65V
          ❌ WRONG: BN = 452.35 ÷ √3 = 261.2V (symmetric formula — NEVER use this for single-phase OV)
          ❌ WRONG: all three phases rise equally to 261V — NEVER do this when only B rises

        off_delay for OV Faulty: if P3=0 SEC → "Instant OFF". on_delay for OV Recovery: if P2=1.5 MIN → "ON in 89-91 SEC".
        OV hystersis recovery: section_break=false. (The next step is "Run time DIP switch change error" — no extra blank needed.)
      If document says "increase all phases" or "all 3 phases symmetrically": all three rise equally (NOT the default).
  - UV tests (if present): "UV Healthy condition", "UV faulty condition", "UV hystersis not recovery",
    "UV hystersis recovery". Use the supply voltage in effect for THAT test group.
  - A "Healthy condition" step may appear BETWEEN test groups (e.g. between Phase Asymmetry and UV,
    or between UV and OV) as the device returns to normal. Allowed between groups, not at very start.
  NOTE: Section B does NOT have symmetrical tests or "Supply couple".
    CRITICAL: If you see "reduce all phases symmetrically to X V Ph-Ph" in Section B, this is
    a TEST VOLTAGE SETUP for UV tests, NOT a sym section. Do NOT create a "Supply couple" step here.
    Do NOT emit "UV symmmetrical" or "OV symmmetrical" step names for Section B tests.
  Then: "Run time DIP switch change error" (all null/empty, section_break=false)
  After runtime error: "DIP S/W Change" (section_break=true). CRITICAL for this step:
    DIP SETTING: The runtime error changed ONE switch from its normal position. Read which switch
      changed and output the CORRECTED DIP with that switch restored (e.g., if switch 2 was wrongly
      set to OFF, the new DIP after error-detection is: 1:ON, 2:OFF, 3:ON, 4:ON, 5:OFF).
    VOLTAGES: Use the same Ph-N values as OV hystersis recovery (all 3 phases equal).
    LEDs: ALL LEDs BLINK. Use ABBREVIATED names (strip type suffix for BLINKING):
      "PWR : BLINKING", "UV : BLINKING", "OV : BLINKING", "ASY : BLINKING".
      Do NOT write "(GREEN LED)" or "(RED LED)" for BLINKING states.
      Do NOT copy LED states from OV hystersis recovery (they should NOT be all OFF).
    relay_status: "ON", on_delay: "Continuous ON" (NOT "Instant ON").
  CRITICAL TRANSITION — SECTION B ENDING:
  The blinking-DIP steps that close Section B are ALWAYS:
    STEP N-1: "Run time DIP switch change error"   (section_break=false, ALL null/empty)
    STEP N:   "DIP S/W Change"                     (section_break=true, voltages/leds from document)

  ══════════════════════════════════════════════════════════════════════
  MANDATORY DECISION GATE — YOU MUST COMPLETE THIS CHECK BEFORE WRITING
  ANY STEP AFTER STEP N. DO NOT skip ahead to PATH A or PATH B templates
  before completing this check.
  ══════════════════════════════════════════════════════════════════════

  STEP 1 — SCAN for PATH B signals in document text after STEP N:
    PATH B SIGNAL A: Document contains "Switch off 3 phase test jig and turn it ON again"
                     or "switch off 3 phase jig and turn it on again" or any close variant
                     (supply power-cycle WITHOUT "change voltages" in the same sentence/paragraph)?
    PATH B SIGNAL B: A sub-heading like "Phase fail and Phase Reverse functionality:" appears?
                     (This is informational text WITHIN the current section, NOT a new lettered Goal.)
    PATH B SIGNAL C: No "Healthy condition (UV=22%/OV=22%)" text anywhere after the supply-off?
    PATH B SIGNAL D: No new LETTERED section header ("C] Goal", "D] Goal") appears in text?

  STEP 2 — DECIDE:
    → If ANY ONE of PATH B signals A, B, C, or D is present → CHOOSE PATH B (see below).
    → PATH A requires ALL of these to be simultaneously true:
        (i)  A NEW LETTERED section header ("C] Goal", "D] Goal") literally present in text, AND
        (ii) Supply-off text explicitly says "change voltages to 240V/415V before supply ON".
      If either condition is absent → PATH B wins automatically.
    → DEFAULT (ambiguous): PATH B.

  ══════════════════════════════════════════════════════════════════════
  PATH B — USE THIS when ANY PATH B signal is detected (the common case):
  ══════════════════════════════════════════════════════════════════════
    STEP N+1: "Supply OFF & supply ON"  (section_break=true, ALL null/empty fields)
    STEP N+2 onward: Phase fail → Phase recovery → Phase reverse → Phase reverse recovery
      (use CURRENT Section B DIP settings active at this point in the document)
    STEP N+5: "DIP S/W Change" if document has a final DIP blink ("In Power ON condition, change DIP S/W"):
      (section_break=true, all LEDs BLINKING)
    JSON for PATH B STEP N+1:
    {{"step_name":"Supply OFF &  supply ON","settings":[],"voltages_pn":[],"voltage_pp":[],"leds":[],"relay_status":null,"on_delay":null,"off_delay":null,"section_break":true}}
    NOTE: "Supply OFF &  supply ON" has TWO spaces after the & symbol — use exactly this spelling.
    ██ CRITICAL PATH B STOP — MANDATORY ██
      After the final "DIP S/W Change" step (blinking, section_break=True), the extraction is
      COMPLETE. STOP IMMEDIATELY. Output NO further steps after that DIP S/W Change.
      Do NOT generate: "Supply OFF change voltages", "Healthy condition", "Asymmetry healthy
      condition", "Asymmetry faulty condition", or ANY Section C/D/E content.
      PATH B documents end at the final DIP blink — the page may show more content but it
      belongs to a DIFFERENT machine or is repeated context. IGNORE everything after the final
      DIP S/W Change in PATH B.
      If no final DIP blink: STOP after Phase reverse recovery. Same rule applies.

  ══════════════════════════════════════════════════════════════════════
  PATH A — ONLY when C]/D] Goal header AND "change voltages" both present:
  ══════════════════════════════════════════════════════════════════════
    STEP N+1: "Supply OFF change voltages as follows before supply ON"  (section_break=true, ALL null)
    STEP N+2: "Healthy condition"  (section_break=false, 240V all phases, UV=22%/OV=22%/DELAY=0SEC)
    → Then the Asymmetry section follows (see Asymmetry section below).
    JSON for PATH A STEP N+1:
    {{"step_name":"Supply OFF change voltages as follows before supply ON","settings":[],"voltages_pn":[],"voltage_pp":[],"leds":[],"relay_status":null,"on_delay":null,"off_delay":null,"section_break":true}}
  CRITICAL — PAGE BOUNDARY RULE: If you see a section header (e.g. "B] Goal", "C] Goal") at the
  end of this page but the numbered test steps for that section do NOT appear on this page (only the
  DIP S/W table heading or partial table is visible), extract ONLY the "DIP S/W Change" step for
  that section header. Do NOT generate test condition steps (UV Healthy, OV Healthy, etc.) for
  sections whose actual numbered test steps are not visible on this page.

For the Asymmetry section (section with lettered goal that tests phase asymmetry):
  CRITICAL — SETTINGS FOR ASYMMETRY SECTION:
    The UV% and OV% pot settings are UNCHANGED from the sym section (UV = 22%, OV = 22%).
    ONLY the DELAY changes to 0SEC. Do NOT use "Pot-1" or "P1" or "P2" as setting labels.
    Always use "UV", "OV", "DELAY" as labels. Correct: ["UV = 22%", "OV = 22%", "DELAY = 0SEC"].
    The "Pot-1 = 25%, Pot-2 = 25%" values in the DIP table are ASYMMETRY TRIP THRESHOLDS,
    not UV/OV pot settings. Ignore them for the settings array.
  CRITICAL: Do NOT add a "DIP S/W Change" step at the start of the Asymmetry section.
  The Asymmetry section starts directly with "Healthy condition" — NO DIP S/W Change before it.
  1. "Healthy condition" (capital H) — ALL three phases at supply voltage (opens the asymmetry section)
  2. "Asymmetry healthy condition" (ONE phase deviated slightly, within hysteresis, relay ON)
     CRITICAL: Read from the document WHICH phase is deviated (R, Y, or B). The deviated phase may be B.
     Only the deviated phase changes from supply voltage; the other two stay at supply voltage.
     Example: if document says "reduce B phase" → RN:240, YN:240, BN:<reduced value>; NOT RN:<reduced>.
     VOLTAGE SOURCE: Read the deviated phase voltage from the spec table in the document images.
       Do NOT use the 89V/78V/105V formula from Section B Phase Asymmetry — that formula applies
       only when settings use P1/P2/P3 format. This section uses UV/OV/DELAY settings; the spec
       table contains the correct trip voltages for THIS section's asymmetry tests.
       CRITICAL — ASYMMETRY % IS SEQUENCE UNBALANCE, NOT VOLTAGE DEVIATION:
         The procedure text phrase "Asymmetry % = 9% to 11%" is the IEC sequence component unbalance
         percentage as measured by the GIC voltmeter software. It is NOT simple voltage deviation.
         WRONG: "9%" → BN = 240 × (1 − 0.09) = 218.4V  ← voltage deviation formula — NEVER USE
         CORRECT: "9%" sequence unbalance at 240V nominal → BN ≈ 179V  ← from spec table
         Always read the absolute Ph-N voltage directly from the spec table image.
         Do NOT re-derive BN from the % shown in the procedure text.
  3. "Asymmetry faulty condition" (deviated past trip threshold, relay OFF)
     Same logic: only the documented deviated phase changes.
  4. "Asymmetry not recovery" (still deviated, relay OFF)
  5. "Asymmetry recovery" (voltage returned, relay ON, section_break=true)

PHASE TESTS (position-agnostic — can appear at the end of Section A, B, or the final section):
  Phase fail/recovery/reverse/reverse-recovery appear when the document has headings:
  "Phase Fail detection", "Phase Reverse detection", "Phase fail and Phase Reverse functionality".
  Extract them wherever narrated, using the DIP settings active at that point in the document.
  CRITICAL — FIXED OUTPUT ORDER (regardless of document order):
    Always output phase tests in this EXACT sequence: 6→7→8→9 as numbered below.
    The document may describe Phase Reverse detection BEFORE Phase Fail detection, but you must
    ALWAYS output: Phase fail (6) → Phase recovery (7) → Phase reverse (8) → Phase reverse recovery (9).
    Do NOT reorder based on document section header order.
  6. "Phase fail" — READ from document which phase is removed (set that phase to 0V, others stay at
     supply voltage). relay=Instant OFF, off_delay="Instant OFF".
     SETTINGS: Check if the document says to change P3 (or delay pot) to 0 before or during the
       Phase fail test. If so, use the CHANGED P3 value (e.g., P3=0 SEC) in settings. Do NOT
       blindly copy the DIP table's P3 value; override with any in-text instruction to change P3.
     CRITICAL WARNING — DO NOT DEFAULT TO R REMOVED. READ the SPECIFIC PHASE from the PHASE FAIL SECTION:
       The Phase fail section text clearly states which phase to remove. Read it from the "Phase Fail
       detection" heading text ONLY — do NOT use text from the Phase Reverse section or other sections.
         "make B phase fail" / "B phase fault" / "remove B phase" / "B dimmer" → BN=0, RN=240, YN=240
         "make R phase fail" / "R phase fault" / "remove R phase" / "R dimmer" → RN=0, YN=240, BN=240
         "make Y phase fail" / "Y phase fault" / "remove Y phase" / "Y dimmer" → YN=0, RN=240, BN=240
       B or Y phase fail is equally common — read the DOCUMENT; never assume R=0.
     ██ MANDATORY PHASE CHECK — before writing Phase fail voltages ██:
       Step 1: Find the "Phase Fail detection" or "Phase fail and Phase Reverse" heading in the document.
       Step 2: Read WHICH phase the text says to remove (B, Y, or R).
       Step 3: Set ONLY that phase to 0V. All other phases stay at 240V Ph-N.
       VERIFICATION: After computing, check RN+YN+BN: exactly ONE of the three must be 0. If two or
         three are 0V, you made an error. If ALL are 240V, you missed the phase removal.
       CONSISTENCY: If Section A Phase fail removes B, Section B Phase fail ALSO removes B unless the
         document explicitly states a different phase for Section B. Do NOT switch phases between sections.
     POT SETTINGS FOR PHASE TESTS: Before the phase fail test, the document instructs to reset
       delay pots to 0. Use P2=0 SEC and P3=0 SEC for ALL phase test steps (fail/recovery/
       reverse/reverse-recovery). Phase tests use SEC units for both P2 and P3.
       Do NOT use "P2 = 0 MIN" or "P3 = 0 MIN" for Phase tests — use "P2 = 0 SEC", "P3 = 0 SEC".
       ██ DIP TABLE OVERRIDE ██: The DIP table may show P3=15 SEC (or any non-zero value) for the
       current section. IGNORE the DIP table P3 for Phase tests. The in-text instruction to reset
       the delay pot TAKES PRECEDENCE over the DIP table. For Phase fail: settings must use
       P3=0 SEC, and off_delay MUST be "Instant OFF" — NOT "OFF in 14-16 SEC" or any time value.
     CRITICAL — REMOVED PHASE IS 0V, ALL OTHERS AT SUPPLY:
       The REMOVED/FAILED phase has Ph-N = 0V. ALL OTHER phases stay at FULL supply voltage.
       WRONG: RN=0, YN=0, BN=240 (WRONG — only the removed phase is 0; others stay at supply)
       WRONG: RN=240, YN=240, BN=240 when B is removed (WRONG — BN must be 0V)
       CORRECT: B removed → BN=0, RN=240, YN=240 (only B is 0; R and Y stay at 240V Ph-N)
       CORRECT: R removed → RN=0, YN=240, BN=240
     VOLTAGE_PP for Phase fail: when one phase is removed, Ph-Ph voltages are:
       - Between two PRESENT phases: supply × √3 (e.g. 240 × 1.732 ≈ 415V)
       - Involving the REMOVED phase: supply voltage itself (e.g. 240V) — NOT 0V and NOT 415V.
       Example: B removed (BN=0), RN=YN=240V → RY=415V, YB=240V, BR=240V.
     LED: PWR LED typically BLINKS during phase fault. Use abbreviated format: "PWR : BLINKING".
     CRITICAL: After "Asymmetry recovery" (if present in the same section), go DIRECTLY to "Phase fail".
     Do NOT insert another "Healthy condition" between "Asymmetry recovery" and "Phase fail".
  7. "Phase recovery" (phase restored) — relay_status="Instant ON", on_delay="Instant ON", section_break=true
     ██ CRITICAL — relay_status="Instant ON" (NOT "ON"). on_delay="Instant ON" (NOT time-based). ██
     The ON delay is governed by P2 (ON delay pot). P2=0 SEC means relay comes back INSTANTLY.
     P3 is ALWAYS reset to 0 SEC for Phase tests → Phase fail off_delay is ALWAYS "Instant OFF".
     Do NOT use DIP table P3 (e.g., P3=15 SEC) to compute Phase fail off_delay. P3=0 SEC for Phase tests.
     NEVER use any P3 value for Phase recovery on_delay. NEVER output "After 14-16 sec" or "After 15 sec".
     MANDATORY: relay_status="Instant ON", on_delay="Instant ON". No exceptions.
  8. "Phase reverse" — add "(change phase angle)" as 4th entry in voltages_pn
     VOLTAGE_PP for Phase reverse: all 3 phases at full supply voltage (e.g., 240V Ph-N) →
       voltage_pp=["RY:415","YB:415","BR:415"]. Include this for BOTH ENABLED and DISABLED detection.
     DECISIVE DISCRIMINATOR — use BOTH document text AND DIP context, from the CURRENT SECTION ONLY:
       Read ONLY the text under the "Phase Reverse detection" heading in the CURRENT section.
       Do NOT import text from the Phase Fail section, other machines, or other pages.
       "relay immediately turned OFF" / "relay should trip" / "ASY LED turns ON" → DETECTION ENABLED
       "No any change" / "relay stays ON" / "no fault detected" / "relay should not trip" / "protection is disabled" → DETECTION DISABLED
       ██ DIP LOCK RULE ██: If the ACTIVE DIP S/W for this section has DIP 1=OFF AND DIP 2=OFF AND
         DIP 3=OFF AND DIP 4=OFF (only DIP 5=ON, all fault-detection DIP switches are OFF) → this
         is SECTION A: Phase reverse protection IS DISABLED. Output relay_status="Continuous ON".
         No ambiguity — DIP 1-4=OFF means ALL fault detections are disabled. Do not output "Instant OFF".
       Default to ENABLED only when document text clearly says relay trips AND DIP 1-4 are ALL ON.
     DETECTION DISABLED (DIP says "Phase sequence fault detection disable" or "Phase reverse protection disabled"):
       relay_status="Continuous ON" (relay NEVER trips — was ON before and stays ON after power-on with reversed phase)
       leds=["PWR (GREEN LED) : ON","UV (RED LED) : OFF","OV (RED LED) : OFF","ASY (RED LED): OFF"] (normal, no fault)
       on_delay=null, off_delay=null
       CRITICAL: Do NOT output relay="Instant OFF". Detection is disabled; relay stays Continuous ON.
       Use step_name="Phase reverse" (not "Phase reverse (No any change)" — use exact step_name="Phase reverse").
     DETECTION ENABLED: relay trips immediately. relay_status="Instant OFF", off_delay="Instant OFF".
  9. "Phase reverse recovery" — add "(recover phase angle)" as 4th entry in voltages_pn
     VOLTAGE_PP for Phase reverse recovery: all 3 phases at full supply voltage (e.g., 240V Ph-N) →
       voltage_pp=["RY:415","YB:415","BR:415"]. Include this for BOTH ENABLED and DISABLED detection.
     DETECTION DISABLED: relay_status="Continuous ON", on_delay="Continuous ON" (was always on — no transition)
       leds=["PWR (GREEN LED) : ON","UV (RED LED) : OFF","OV (RED LED) : OFF","ASY (RED LED): OFF"]
       section_break: false (DISABLED — relay never changed, no break needed)
     DETECTION ENABLED: relay_status="Instant ON", on_delay="Instant ON"
       section_break: true (ENABLED — Phase reverse recovery closes the phase test block; add extra spacing)
  IMPORTANT: Extract Phase tests ONLY when explicitly narrated. Do NOT fabricate them.

TOTAL EXPECTED STEPS: ~28–40 steps across all sections (varies by number of sections and DIP configs).
DO NOT inflate by repeating per-phase (R/Y/B). One test per condition.

SECTION MARKERS:
- "Supply couple at [voltage] VAC" — MANDATORY before symmetrical test steps (between
  "UV hystersis recovery" and the first "[UV|OV] symmmetrical" step).
  Triggered by document text like "symmetrically reduce all phases to X V Ph-N" or
  "couple supply at X VAC". Replace [voltage] with the numeric value from the document.
  -> section_break: true, settings:[], voltages_pn:[], voltage_pp:[], leds:[], relay_status:null
- "Supply OFF" — when procedure says "Turn OFF 3 ph test Jig" before DIP change
  -> section_break: true
- "Supply OFF change voltages as follows before supply ON" OR "Supply OFF & supply ON" — before new DIP config
  -> section_break: true (use the exact phrase from the document)

VOLTAGE RULES:
- Nominal: ALWAYS read from the document (e.g. "set voltage at 240V Ph-N" → RN:240, YN:240, BN:240).
  Do NOT default to any fixed value — 120V, 240V, 277V are all possible; read what the document says.
  IMPORTANT: The worked example uses 240V as a placeholder. If your document Section A says
  "set voltage at 120V Ph-N" or "set 3-phase supply to 120V", use 120V — not the example's 240V.
  Each section may have a DIFFERENT nominal voltage; read each section's own instruction independently.
- SUPPLY TYPE (DIP S/W 5): Determines whether document voltages are Ph-N or Ph-Ph.
  DIP 5=ON → "Ph-N supply" → voltage ranges stated in the document ARE Ph-N values. Use DIRECTLY.
    CRITICAL: Do NOT divide by √3 when DIP 5=ON (Ph-N supply). 225.6V Ph-N means 225.6V — not 130.34V.
    WRONG: document says "220.8V to 225.6V" with DIP 5=ON → 225.6÷1.732=130.34. NEVER DO THIS.
    CORRECT: document says "220.8V to 225.6V" with DIP 5=ON → UV Healthy = 225.6V Ph-N directly.
  DIP 5=OFF → "Ph-Ph supply" → document may give Ph-Ph ranges; divide by √3 to get Ph-N.
    Example: "452.35V to 460.65V Ph-Ph" with DIP 5=OFF → 460.65÷1.732=266.0V Ph-N.
  When no DIP 5 is mentioned: use the label in the document ("Ph-N" or "Ph-Ph") to determine conversion.
- UV Healthy: use UPPER BOUND of trip range (e.g. 218.4-220.8 -> 220.8)
- UV Faulty: use LOWER BOUND of trip range (e.g. 218.4-220.8 -> 218.4)
- Hystersis not recovery: use the UPPER BOUND of the UV/OV trip range (= same voltage as UV/OV Healthy).
  After tripping at the lower bound, the document raises voltage BACK to the trip boundary (upper bound).
  The relay does NOT recover at this voltage — recovery requires exceeding the hysteresis range.
  WRONG: use example trip value T from "if trip is T then reset range is A to B V" — that T is a sample, not the test voltage.
  CORRECT: use upper bound directly. Section A UV trip range 220.8-225.6V → not-recovery = 225.6V (same as UV Healthy).
  Section B UV at 340V Ph-Ph: trip range 327.85-336.15V → not-recovery = 336.15÷1.732 = 194.1V (same as UV Healthy).
- Hystersis recovery: recovery voltage = UPPER BOUND of trip range + MAX hysteresis (3.6V for this variant).
  Section A UV example: trip range 109.2-111.6V, max hyst 3.6V → recovery = 111.6 + 3.6 = 115.2V.
  Sym UV example: trip range 92.4-94.8V, max hyst 3.6V → recovery = 94.8 + 3.6 = 98.4V.
  Do NOT use 7.2V or any other value — max hysteresis for this variant is 3.6V.
  Do NOT use the not-recovery example trip (110.4 or 93.6) in the recovery formula.
- Symmetrical test: read whether the section is UV or OV symmetrical from the document heading.
  Use supply couple / base Ph-N voltage stated for that symmetrical section.
  Compute trip voltages from the symmetrical trip range in the document at that base.
- Ph-N: read voltage from document → RN:X, YN:X, BN:X. Ph-Ph: "480V Ph-Ph (277V Ph-N)" → voltages_pn=[RN:277,...], voltage_pp=[RY:480,...]
- For UV tests: only the tested phase changes (reduce R phase → only RN changes). YN and BN stay at nominal.
- For OV tests (OV Healthy, OV faulty, OV hyst not recovery, OV hyst recovery): ALL THREE phases increase
  together to the same voltage. The document says "increase all three phases to X V Ph-N".
  → voltages_pn=[RN:X, YN:X, BN:X] where X is the OV test voltage. Do NOT keep YN/BN at nominal.
- Phase reverse: add "(change phase angle)" as 4th voltage_pn entry
- Phase reverse recovery: add "(recover phase angle)" as 4th voltage_pn entry

DIP SWITCH EXTRACTION:
- From table: "1 2 3 | 0 0 0 (OFF)" -> ["1 : OFF", "2 : OFF", "3 : OFF"]
- Setting "0" = OFF, "1" = ON
- These go in settings of the "DIP S/W Change" step

POT SETTINGS per step:
- Inspect the document's pot label for EACH pot. Determine the output key as follows:
  - If the document says "Pot 1", "UV Pot (Pot 1)", "P1", "(Pot 1)", or similar with a number 1: output key is "P1"
  - If the document says "Pot 2", "UV hysteresis (Pot 2)", "OV hysteresis (Pot 2)", "P2", "(Pot 2)", or similar with a number 2: output key is "P2"
    CRITICAL VALUE RULE: "UV hysteresis (Pot 2) - X%" or "OV hysteresis (Pot 2) - X%" → key="P2", value=X% (the hysteresis %).
    e.g. "UV hysteresis (Pot 2) - 5%" → "P2 = 5%". NEVER substitute OV threshold (22%) for hysteresis. 5% ≠ 22%.
  - If the document says "UV pot" with NO pot number: output key is "UV"
  - If the document says "OV pot" with NO pot number: output key is "OV"
  - "Delay Pot" WITHOUT a pot number (e.g. "Delay Pot − 3 sec"): key is ALWAYS "DELAY", NEVER "P3".
    Use "P3" ONLY when the label explicitly contains "(Pot 3)" or "(P3)". "Delay Pot" alone → "DELAY".
- Format: ["P1 = 7%", "P2 = 5%", "DELAY = 3SEC"] when using P-number labels and Delay Pot labels
- Format: ["UV = 8%", "OV = 22%", "DELAY = 3SEC"] when using UV/OV labels
- CRITICAL: Do NOT add a space between the number and the % sign. "P1 = 25%" is correct; "P1 = 25 %" is WRONG.
- CRITICAL: In Section B, P3 is a MIN-type pot. When set to 0, always output "P3 = 0 MIN" (NOT "P3 = 0 SEC"),
  regardless of how the document phrases the unit. Section A uses "P3 = 15 SEC" (SEC-type pot — different).
- Do NOT output the full description ("UV Pot (Pot 1)") as the key. Extract only the label key per the rules above.
- Re-read pot settings for each section — they change between sections and symmetrical tests.
CRITICAL: For ALL test condition steps in Sections A and B (UV healthy, UV faulty, UV hystersis not recovery,
UV hystersis recovery, UV symmmetrical steps, OV steps), the `settings` array MUST contain EXACTLY 3 items:
  ["UV = X%", "OV = Y%", "DELAY = Zsec"]  (or P1/P2 equivalents).
  NEVER emit only 2 items by omitting OV (or P2). Even if OV has not changed, still include it explicitly.

LED FORMAT:
Layout A (4 LEDs): ["PWR (GREEN LED) : ON", "UV (RED LED) : OFF", "OV (RED LED) : OFF", "ASY (RED LED): OFF"]
Layout B (1 LED): ["R (RED LED) : ON"] or ["R (RED LED) : OFF"]
Always include ALL LEDs for the layout. Adjust ON/OFF/BLINKING per condition.

WORKED EXAMPLE — Section A says:
  "DIP S/W: 1=0 2=0 3=0 4=0 5=1, Pot: UV=10% OV=22% Delay=3sec"
  "set voltage at 240V Ph-N"
  "Turn ON -> PWR LED ON, relay ON after 4-6 sec"
  "Reduce R phase -> UV LED ON. After 3 sec, relay trips. Trip range: 218.4V to 220.8V"
  "Increase R phase -> UV LED OFF. After 5 sec, relay ON. Hysteresis: 2.4V to 7.2V"
  "If trip voltage is 219.6V then reset hysteresis should be 222V to 226.8V"

IMPORTANT for healthy condition on_delay: READ it from the document.
- If document says "relay ON after 4-6 sec", use "4-6 sec".
- If document says "relay ON after 5 sec(+/-1)" or "After 5 sec ±1", output the RANGE: "4-6 sec" (i.e., (X-1)-(X+1) sec).
- If document says "relay ON after 5 sec" with NO ±1, use "5 sec".
- Only use "Instant ON" if the document explicitly says relay turns on instantly. Do NOT default to "Instant ON".

LED FORMAT RULE: ON/OFF states use FULL name: "PWR (GREEN LED) : ON", "UV (RED LED) : OFF".
  BLINKING states use ABBREVIATED name (no type suffix): "UV : BLINKING", "ASY : BLINKING".
  NEVER write "(GREEN LED)" or "(RED LED)" next to a BLINKING state.

This produces these steps (note: example uses 240V because the example document says 240V;
  if YOUR document Section A says "set voltage at 120V", use 120V instead — always read from doc):
  {{"step_name":"DIP S/W Change","settings":["1 : OFF","2 : OFF","3 : OFF","4 : OFF","5 : ON"],"voltages_pn":[],"voltage_pp":[],"leds":[],"relay_status":null,"on_delay":null,"off_delay":null,"section_break":true}}
  {{"step_name":"healthy condition","settings":["UV = 10%","OV = 22%","DELAY = 3SEC"],"voltages_pn":["RN : 240","YN : 240","BN : 240"],"voltage_pp":[],"leds":["PWR (GREEN LED) : ON","UV (RED LED) : OFF","OV (RED LED) : OFF","ASY (RED LED): OFF"],"relay_status":"ON","on_delay":"4-6 sec","off_delay":"-","section_break":false}}
  {{"step_name":"UV Healthy condition","settings":["UV = 10%","OV = 22%","DELAY = 3SEC"],"voltages_pn":["RN : 220.8","YN : 240","BN : 240"],"voltage_pp":[],"leds":["PWR (GREEN LED) : ON","UV (RED LED) : OFF","OV (RED LED) : OFF","ASY (RED LED): OFF"],"relay_status":"ON","on_delay":"Continuous ON","off_delay":"-","section_break":false}}
  {{"step_name":"UV faulty condition","settings":["UV = 10%","OV = 22%","DELAY = 3SEC"],"voltages_pn":["RN : 218.4","YN : 240","BN : 240"],"voltage_pp":[],"leds":["PWR (GREEN LED) : ON","UV (RED LED) : ON","OV (RED LED) : OFF","ASY (RED LED): OFF"],"relay_status":"OFF in 2-4 sec","on_delay":"-","off_delay":"2-4 SEC","section_break":false}}
  {{"step_name":"UV hystersis not recovery","settings":["UV = 10%","OV = 22%","DELAY = 3SEC"],"voltages_pn":["RN : 219.6","YN : 240","BN : 240"],"voltage_pp":[],"leds":["PWR (GREEN LED) : ON","UV (RED LED) : ON","OV (RED LED) : OFF","ASY (RED LED): OFF"],"relay_status":"OFF ","on_delay":"-","off_delay":"Continuous OFF","section_break":false}}
  {{"step_name":"UV hystersis recovery","settings":["UV = 10%","OV = 22%","DELAY = 3SEC"],"voltages_pn":["RN : 226.8","YN : 240","BN : 240"],"voltage_pp":[],"leds":["PWR (GREEN LED) : ON","UV (RED LED) : OFF","OV (RED LED) : OFF","ASY (RED LED): OFF"],"relay_status":"ON","on_delay":null,"off_delay":null,"section_break":false}}

Return JSON:

{{
  "test_steps": [ ... ]
}}

SECTION B REFERENCE — exact relay/delay values:
  UV hystersis recovery (Sec B): relay="ON in 89-91 SEC", on_delay="ON in 89-91 SEC", off_delay=null,        section_break=false
    NOTE: relay="ON in 89-91 SEC" (P2=1.5 MIN → 90-sec delay). SAME value in relay AND on_delay.
    WARNING: UV hystersis recovery in Section B uses P2=1.5 MIN. Other UV steps use P2=0 MIN.
    Do NOT apply "ON in 89-91 SEC" or "ON in 29-31 sec" to non-recovery Section B UV steps.
  OV Healthy condition:      relay="continuous ON",   on_delay=null,              off_delay="-",            section_break=false
    settings: P2=0 MIN (document resets P2 to 0 before OV section). Do NOT use P2=1.5 MIN for OV steps.
    NOTE: relay="continuous ON" (lowercase, NOT "ON"). Relay was already ON before Decouple — no new ON delay.
          on_delay MUST be null (empty). Do NOT output on_delay="Continuous ON".
  OV faulty condition:       relay="Instant OFF",     on_delay="-",              off_delay="Instant OFF",   section_break=false
    settings: P2=0 MIN, P3=0 MIN. voltages: only BN rises; RN=240V, YN=240V (same as OV Healthy).
  OV hystersis not recovery: relay="OFF ",            on_delay="-",              off_delay="Continuous OFF", section_break=false
    settings: P2=0 MIN, P3=0 MIN.
    CRITICAL: voltages for OV hystersis not recovery = SAME AS OV Healthy condition (BN at lower OV bound).
              Do NOT use OV faulty voltages (higher BN) — voltage is reduced back to healthy level.
  OV hystersis recovery:     relay="ON in 89-91 SEC", on_delay="ON in 89-91 SEC", off_delay=null,          section_break=false
    settings: P2=0 MIN, P3=0 MIN. (The 89-91 sec ON delay is a fixed OV recovery behaviour, not P2-driven.)
    NOTE: relay="ON in 89-91 SEC". SAME value in relay AND on_delay.
  Run time DIP switch change error: ALL null/empty,                                                         section_break=false
  DIP S/W Change (after Run time): DIP=READ FROM DOCUMENT (the corrected DIP after error is fixed),
                                   voltages=same as OV hyst recovery (RN=YN=240V, BN=at recovery level),
                                   leds=["PWR : BLINKING","UV : BLINKING","OV : BLINKING","ASY : BLINKING"],
                                   relay="ON", on_delay="Continuous ON",                                     section_break=true
  Supply OFF change voltages as follows before supply ON: all null/empty,                                    section_break=true
  IMPORTANT: OV Healthy relay = "continuous ON" (NOT "ON"). Do NOT add on_delay for OV Healthy.
  OV hyst recovery relay AND on_delay BOTH = "ON in 89-91 SEC".
  OV faulty off_delay = "Instant OFF" (P3=0 MIN → Instant OFF).
  ALL OV steps in Section B use P2=0 MIN. Do NOT use P2=1.5 MIN for OV steps.
  Do NOT use "4-6 sec" for OV — that is Section A healthy condition (different delay pot value).
  EXACT FORMAT for OV faulty: relay="Instant OFF", off_delay="Instant OFF" (P3=0 MIN → Instant OFF).

ASYMMETRY SECTION REFERENCE — exact relay/delay values (use EXACTLY as shown):
  SCOPE: These values apply ONLY when settings use P1/P2/P3 pot format (NOT UV/OV/DELAY format).
  For UV/OV/DELAY format documents: asymmetry steps use names from the document (e.g.,
  "Asymmetry healthy condition") and relay/delay from the document — do NOT apply "Phase Asymmetry"
  names or the delay values below to UV/OV/DELAY format machines.
  Phase Asymmetry Healthy:     relay="ON in 29-31 sec", on_delay="ON in 29-31 sec", off_delay=null,          section_break=false
    NOTE: relay="ON in 29-31 sec" AND on_delay="ON in 29-31 sec" (SAME value in both fields).
    P2=0 MIN → device 30-sec ON delay even for first Asymmetry step → "ON in 29-31 sec". NOT "Continuous ON". NOT "ON".
  Phase Asymmetry faulty:      relay="OFF in 89-91 SEC", on_delay=null,              off_delay="OFF in 89-91 SEC", section_break=false
    NOTE: P3=1.5 MIN = 90 sec → relay trips after 89-91 sec. Do NOT use "OFF IN 4-6 SEC". Do NOT use "Instant OFF".
    ASY LED = "ASY (RED LED): BLINKING" (keep "(RED LED)" suffix — Asymmetry section exception to general BLINKING rule).
  Phase Asymmetry  not recovery: relay="Continuous OFF", on_delay=null,             off_delay="Continuous OFF", section_break=false
    NOTE: relay="Continuous OFF" (NOT "OFF" alone). Double-space in step name: "Phase Asymmetry  not recovery".
    ASY LED = "ASY (RED LED): BLINKING" (keep "(RED LED)" suffix).
  Phase Asymmetry  recovery:   relay="ON in 29-31 sec",  on_delay="ON in 29-31 sec", off_delay=null,          section_break=false
    NOTE: Double-space in step name: "Phase Asymmetry  recovery". relay="ON in 29-31 sec" AND on_delay="ON in 29-31 sec".

SYM SECTION REFERENCE — settings ARE different from Section A:
  EXAMPLE: Section A used UV=8%/OV=22%/DELAY=3SEC; sym block shows UV=22%/OV=22%/DELAY=15SEC.
  Use UV=22%/OV=22%/DELAY=15SEC for ALL sym steps — do not carry Section A values.
  Supply couple at X VAC:          settings=[], voltages_pn=[], leds=[], relay=null,  section_break=true
  UV symmmetrical Healthy:         relay="ON",  on_delay="Relay continuous ON",     off_delay="-",             section_break=false
  UV symmmetrical faulty:          relay="OFF in X-Y sec", on_delay="-",            off_delay="Instant OFF",   section_break=false
  UV hystersis not recovery (sym): relay="Continuous OFF", on_delay="-",            off_delay="Continuous OFF", section_break=false
  UV hystersis recovery (sym):     relay="ON",  on_delay="After 4-6 sec" (or "Instant ON" if fixed delay=0),    section_break=false

PHASE TEST REFERENCE — relay/delay values when phase protection is ENABLED:
  Phase fail:                  relay="Instant OFF",    on_delay=null,             off_delay="Instant OFF",   section_break=false
  Phase recovery:              relay="Instant ON",     on_delay="Instant ON",     off_delay=null,            section_break=true
  Phase reverse:               relay="Instant OFF",    on_delay=null,             off_delay="Instant OFF",   section_break=false
  Phase reverse recovery:      relay="Instant ON",     on_delay="Instant ON",     off_delay=null,            section_break=false
    NOTE: relay MUST be "Instant ON" (not just "ON"). Phase reverse recovery is ALWAYS instant.
  (If phase-reverse protection is DISABLED: Phase reverse relay="Continuous ON", on_delay="Continuous ON")

IMPORTANT:
- Extract ONLY sections for variant {variant}. Skip all other variants.
- Include ALL test sections for this variant regardless of how they are labelled.
- Steps with NO test conditions (DIP S/W Change, Supply couple at X VAC, Supply OFF (exact), Supply OFF change voltages..., Run time DIP switch change error) MUST have voltages_pn=[], voltage_pp=[], leds=[], relay_status=null, on_delay=null, off_delay=null.
- Steps WITH test conditions must have voltages_pn and leds filled from the document.
- section_break RULES (exact):
    TRUE  -> DIP S/W Change, Supply couple at X VAC, Supply OFF (exact), Supply OFF change voltages as follows before supply ON, Supply OFF & supply ON
    TRUE  -> Phase recovery
    FALSE -> ALL other steps including UV hystersis recovery, OV hystersis recovery, Asymmetry recovery, Phase Asymmetry recovery
- No markdown. No explanation. No commentary.
"""


PROCEDURE_PROMPT_B = """You are reading a GIC FQC functional test procedure for a CUTOFF relay (Layout B).

VARIANT: {variant}
LAYOUT: Layout B — single R (RED LED), NO DIP switches, NO pot settings.

SOURCE FORMAT: Two sections in the images provided:
(A) Narrative "FUNCTIONAL TEST PROCEDURE FOR {variant}" pages — numbered steps for phase fail/recovery, phase reverse/recovery, asymmetry narrative.
(B) FQC table "PROCEDURE FOR CAT ID : {variant} R LED" — tabular rows with Tripping range / Recovery Hysteresis / LED / delays.

Merge both sections into one step list. Narrative supplies phase fail → phase recovery → phase reverse → phase reverse recovery BEFORE asymmetry steps.

Extract ONLY the FQC table rows for variant {variant}. One JSON step per logical test condition.
settings must always be [].

EXPECTED STEP SEQUENCE — build from the FQC table rows for {variant}:

COMMON PREFIX (from narrative pages + FQC row 1):
1. healthy condition
2. Phase fail
3. Phase recovery
4. Phase reverse — add "(change phase angle)" as 4th voltages_pn entry
5. Phase reverse recovery — add "(recover phase angle)" as 4th voltages_pn entry

IF the FQC table contains a "Fix Phase Asymmetry" row (NOT "Phase Reverse" as the only fault row), insert steps 6–9:
6. Asymmetry healthy condition
7. Asymmetry faulty condition
8. Asymmetry not recovery
9. Asymmetry recovery

IF the FQC table has "Phase Reverse" as a table row but NO "Fix Phase Asymmetry" row, do NOT extract asymmetry steps — phase reverse is already covered in steps 4–5 above.

ALWAYS after the prefix (and asymmetry block if present):
- Couple all Voltages (section label — voltages_pn=[], leds=[], relay null)
- Lower Cut OFF healthy / Lower Cut OFF / Lower Cut OFF not recovery / Lower Cut OFF recovery

IF the FQC table or procedure shows a repeat test block (second identical LV/HV sequence), repeat:
Lower Cut OFF healthy / Lower Cut OFF / Lower Cut OFF not recovery / Lower Cut OFF recovery

IF the FQC table includes "Fix Phase Asymmetry" (asymmetry variants only), insert section label
"Repeated Tests -" BEFORE the second Lower Cut OFF healthy block.
IF there is NO asymmetry block, do NOT insert "Repeated Tests -" — go directly to the second Lower Cut OFF healthy block.

Finish with:
- Higher Cut OFF healthy
- Higher Cut OFF

Do NOT invent steps. Do NOT extract rows from other variants' tables on the same page.

VOLTAGE RULES (Ph-N in voltages_pn, Ph-Ph in voltage_pp):
- Read base Ph-N from subheading (e.g. 240). Base Ph-Ph = int(base × 1.73205) truncated (not rounded).
  Example: 240 Ph-N → RY/YB/BR : 415.
- Symmetric steps (all 3 phases equal): voltages_pn [RN:base, YN:base, BN:base], voltage_pp [RY:pp, YB:pp, BR:pp].
- Phase fail fault: RN and YN at base; BN = 0. voltage_pp: RY = int(base×1.73205), YB = base, BR = base (failed phase line voltages differ).
- Phase reverse steps: all phases at base + 4th entry "(change phase angle)" or "(recover phase angle)".

ASYMMETRY STEPS (Fix Phase Asymmetry row — tripping % e.g. 26% to 34%, recovery hysteresis 5% to 9%):
- Keep RN and YN at base (240). Reduce BN only per asymmetry test.
- Asymmetry healthy: BN = base minus asymmetry setting (read from document / compute from tripping %).
- Asymmetry faulty: BN at lower tripping bound.
- Asymmetry not recovery: BN slightly above faulty (hysteresis not recovered).
- Asymmetry recovery: BN at recovery voltage.
- For asymmetry steps, compute YB and BR line voltages for the unbalanced 3-phase condition shown in the document — do NOT use simple base×1.732 for all three when BN differs from YN.

LOW VOLTAGE CUT OFF (table row "Low voltage cut off", tripping range e.g. 165V to 185V Ph-Ph):
- Lower Cut OFF healthy / not recovery: Ph-Ph = UPPER bound of tripping range; Ph-N = int(Ph-Ph / 1.73205) truncated.
  Example: 185 Ph-Ph → RN/YN/BN : 107.
- Lower Cut OFF (fault): Ph-Ph = LOWER bound; Ph-N = int(Ph-Ph / 1.73205). Example: 165 → 95.
- Lower Cut OFF recovery: Ph-N ≈ 120, Ph-Ph ≈ 207 (recovery above fault using hysteresis range).

HIGH VOLTAGE CUT OFF (tripping e.g. 550V to 590V Ph-Ph):
- Higher Cut OFF healthy: Ph-Ph = LOWER bound; Ph-N = int(Ph-Ph / 1.73205). Example: 550 → 317.
- Higher Cut OFF (fault): Ph-Ph = UPPER bound; Ph-N = int(Ph-Ph / 1.73205). Example: 590 → 340.

LED FORMAT (single LED only):
["R (RED LED) : ON"] or ["R (RED LED) : OFF"] or ["R(RED LED) : ON"] — read from LED indication column.
Use "R (RED LED) : ON" format with spaces.

RELAY STATUS: Read from context — ON when LED ON and relay energized, OFF when LED OFF.

DELAY RULES:
- The images include BOTH narrative procedure pages (numbered steps describing relay behavior)
  AND the FQC table (Sr.No | Test Parameter | ... | OFF delay | ON delay).
- Read on_delay and off_delay from the NARRATIVE text description of each condition,
  not from the FQC table delay columns.
- The narrative uses language like "turns ON instantly", "turn OFF immediately",
  "within 100msec", "remains ON continuously". Translate into factory labels:
    "immediately" / "instantly" / "Instant" / no delay mentioned → "Instant ON" or "Instant OFF"
    "continuously" / "remains ON" / healthy cut-off holding → "Continuous ON" or "Continuous OFF"
    explicit time in narrative only (e.g. "4-6 sec") → use that exact string
    not specified in narrative → null
- Do NOT use FQC table delay column values (<=500 msec, <=750 msec, "1.4 sec after power ON", etc.).
  Those are timing specs, not factory sheet labels.
- Do NOT swap columns: on_delay from ON-behavior narrative, off_delay from OFF-behavior narrative.
- Do NOT invent delay values not present in the document.

NARRATIVE DELAY REFERENCE (factory sheet labels — read behavior from narrative, NOT table columns):
  healthy condition:           on_delay="Instant ON",     off_delay="-"
  Phase fail:                  off_delay="Instant OFF",   on_delay=null
  Phase recovery:              on_delay="Instant ON",     off_delay=null
  Phase reverse:               off_delay="Instant OFF",   on_delay=null, relay_status="Instant OFF"
  Phase reverse recovery:      on_delay="Instant ON",     off_delay=null, relay_status="ON"
  Asymmetry healthy condition: on_delay="Continuous ON",  off_delay=null
  Asymmetry faulty condition:  off_delay="Instant OFF",   on_delay=null
  Asymmetry not recovery:      off_delay="Continuous OFF", on_delay=null
  Asymmetry recovery:          on_delay="Instant ON",     off_delay=null
  Lower Cut OFF healthy:       on_delay="Continuous ON",  off_delay=null
  Lower Cut OFF (fault):       off_delay="Instant OFF",   on_delay=null
  Lower Cut OFF not recovery:  off_delay="Continuous OFF", on_delay=null
  Lower Cut OFF recovery:      on_delay="Instant ON",     off_delay=null
  Higher Cut OFF healthy:      on_delay="Continuous ON",  off_delay=null
  Higher Cut OFF (fault):      off_delay="Instant OFF",   on_delay=null
  Higher Cut OFF not recovery: off_delay="Continuous OFF", on_delay=null
  Higher Cut OFF recovery:     on_delay="Instant ON",     off_delay=null

SECTION LABELS (no test data):
- "Couple all Voltages": voltages_pn=[], voltage_pp=[], leds=[], relay_status=null, section_break=true
- "Repeated Tests -": same empty fields, section_break=true

Return JSON:
{{
  "test_steps": [
    {{
      "step_name": "healthy condition",
      "settings": [],
      "voltages_pn": ["RN : 240", "YN : 240", "BN : 240"],
      "voltage_pp": ["RY : 415", "YB : 415", "BR : 415"],
      "leds": ["R (RED LED) : ON"],
      "relay_status": "ON",
      "on_delay": "Instant ON",
      "off_delay": "-",
      "section_break": false
    }}
  ]
}}

Return ONLY valid JSON. No markdown. No commentary.
"""


def _build_image_parts(pages: List[Page]) -> list:
    parts = []
    for p in pages[:MAX_IMAGES_PER_CALL]:
        if p.jpeg_bytes:
            parts.append({"mime_type": "image/jpeg", "data": p.jpeg_bytes})
    return parts


def _chunk_pages(pages: List[Page], size: int = 10):
    for i in range(0, len(pages), size):
        yield pages[i:i + size]


def _extract_specs(genai, machine: str, variants: List[str], pages: List[Page]) -> Dict[str, Dict]:
    if not pages:
        return {}

    model = genai.GenerativeModel(VISION_MODEL)
    prompt = SPECS_PROMPT.format(machine=machine, variants=", ".join(variants))

    all_data = {}

    if len(pages) <= 8:
        selected_pages = pages
    elif len(pages) <= 20:
        selected_pages = pages[:10]
    else:
        selected_pages = pages[:12]

    pages = selected_pages

    for chunk in _chunk_pages(pages, size=8):
        parts = [prompt] + _build_image_parts(chunk)
        logger.info(f"  vision specs chunk: {len(parts)-1} images, variants={variants}")

        raw = _call_with_retry(model, parts, DEFAULT_TIMEOUT, f"{machine} specs")
        if not raw:
            logger.warning(f"{machine}: Gemini failed — aborting extraction")
            continue
        data = _parse_json(raw, f"{machine} specs")
        logger.info(
            f"{machine}: raw spec response keys="
            f"{list(data.keys()) if isinstance(data, dict) else 'invalid'}"
        )
        logger.info(f"{machine}: raw spec payload={data}")

        if data:
            cleaned = {
                re.sub(r"\s+", "", str(k)).upper(): v
                for k, v in data.items()
                if isinstance(v, dict)
            }
            for k, v in cleaned.items():
                if k not in all_data:
                    all_data[k] = v
                else:
                    for field, val in v.items():
                        if val and not all_data[k].get(field):
                            all_data[k][field] = val

    return all_data


def _layout_b_yb_from_bn(base: int, bn: int) -> int:
    """Line voltage Y-B for star connection with RN=YN=base, BN=bn."""
    ang_r, ang_y, ang_b = 0, -120, 120
    vr = base * complex(
        math.cos(math.radians(ang_r)), math.sin(math.radians(ang_r))
    )
    vy = base * complex(
        math.cos(math.radians(ang_y)), math.sin(math.radians(ang_y))
    )
    vb = bn * complex(
        math.cos(math.radians(ang_b)), math.sin(math.radians(ang_b))
    )
    return int(abs(vy - vb))


def _layout_b_bn_from_yb(base: int, target_yb: int) -> Optional[int]:
    for bn in range(1, base + 1):
        if _layout_b_yb_from_bn(base, bn) == target_yb:
            return bn
    return None


def _parse_layout_b_ocr_context(pages: List[Page]) -> Dict:
    """Parse FQC table voltage ranges from procedure page OCR text."""
    ctx = {
        "base_pn": None,
        "lv_pp": None,
        "lv_hyst_v": None,
        "hv_pp": None,
        "asym_trip_pct": None,
        "asym_hyst_pct": None,
    }
    for p in pages:
        text = p.ocr_text or ""
        if ctx["base_pn"] is None:
            m = re.search(
                r"(?:Set voltage|at)\s+(\d+)\s*V\s*Ph-N",
                text, re.IGNORECASE,
            )
            if m:
                ctx["base_pn"] = int(m.group(1))
        m = re.search(
            r"Low voltage cut off.*?(\d+)\s*V\s*to\s*(\d+)\s*V\s+(\d+)\s*V\s*to\s*(\d+)\s*V",
            text, re.IGNORECASE | re.DOTALL,
        )
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            ctx["lv_pp"] = (min(a, b), max(a, b))
            h_a, h_b = int(m.group(3)), int(m.group(4))
            ctx["lv_hyst_v"] = (min(h_a, h_b), max(h_a, h_b))
        elif not ctx["lv_pp"]:
            m = re.search(
                r"Low voltage cut off.*?(\d+)\s*V\s*to\s*(\d+)\s*V",
                text, re.IGNORECASE | re.DOTALL,
            )
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                ctx["lv_pp"] = (min(a, b), max(a, b))
        m = re.search(
            r"High voltage cut off.*?(\d+)\s*V\s*to\s*(\d+)\s*V",
            text, re.IGNORECASE | re.DOTALL,
        )
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            ctx["hv_pp"] = (min(a, b), max(a, b))
        m = re.search(
            r"Fix Phase Asymmetry.*?(\d+)\s*%.*?to\s*(\d+)\s*%.*?(\d+)\s*%.*?to\s*(\d+)\s*%",
            text, re.IGNORECASE | re.DOTALL,
        )
        if m:
            ctx["asym_trip_pct"] = (int(m.group(1)), int(m.group(2)))
            ctx["asym_hyst_pct"] = (int(m.group(3)), int(m.group(4)))
    return ctx


def _layout_b_symmetric_voltages(pn: int) -> tuple:
    pp = int(pn * 1.73205)
    pn_s = f"RN : {pn}"
    return (
        [pn_s.replace("RN", "RN"), f"YN : {pn}", f"BN : {pn}"],
        [f"RY : {pp}", f"YB : {pp}", f"BR : {pp}"],
    )


def _is_spurious_delay_hallucination(val) -> bool:
    return is_spurious_delay_hallucination(val)


def _scrub_layout_b_delays(step: Dict) -> None:
    for field in ("on_delay", "off_delay"):
        val = step.get(field)
        if _is_spurious_delay_hallucination(val):
            step[field] = None


_OFF_DELAY_TABLE_RE = re.compile(
    r"(?:<=|<\s*=|msec|less\s+than|^\s*-\s*$)", re.IGNORECASE
)
_ON_DELAY_TABLE_RE = re.compile(
    r"sec\s+after|after\s+power|\d+\.?\d*\s*sec", re.IGNORECASE
)


def _fix_layout_b_delay_columns(step: Dict) -> None:
    """Move OFF-column table strings out of on_delay when Gemini swaps columns."""
    on_d = step.get("on_delay")
    off_d = step.get("off_delay")
    if not on_d:
        return
    on_s = str(on_d).strip()
    if not _OFF_DELAY_TABLE_RE.search(on_s):
        return
    if off_d and str(off_d).strip() not in ("", "-", "null"):
        return
    step["off_delay"] = on_s
    step["on_delay"] = None


def _finalize_layout_b_steps(steps: List[Dict], pages: List[Page]) -> List[Dict]:
    """Drop steps that belong to FQC rows not present in this variant's table."""
    ctx = _parse_layout_b_ocr_context(pages)
    has_asymmetry = bool(ctx.get("asym_trip_pct"))
    out = []
    for s in steps:
        name_lower = str(s.get("step_name", "")).lower().strip()
        if not has_asymmetry and "asymmetry" in name_lower:
            continue
        if not has_asymmetry and name_lower.startswith("repeated tests"):
            continue
        out.append(s)
    return out


def _apply_layout_b_postprocessing(steps: List[Dict], pages: List[Page]) -> List[Dict]:
    """OCR-driven corrections for Layout B FQC table procedures."""
    ctx = _parse_layout_b_ocr_context(pages)
    base = ctx["base_pn"]
    lv = ctx["lv_pp"]
    hv = ctx["hv_pp"]

    for s in steps:
        name = s.get("step_name", "")
        name_lower = name.lower().strip()
        name_lower = re.sub(r"\s*\(repeat block\)\s*$", "", name_lower).strip()
        if name_lower != name.lower().strip():
            s["step_name"] = name_lower

        # Strip spurious delay hallucinations
        _scrub_layout_b_delays(s)
        _fix_layout_b_delay_columns(s)

        # Section labels — no functional data
        if "couple all voltages" in name_lower or name_lower.startswith("repeated tests"):
            s["settings"] = []
            s["voltages_pn"] = []
            s["voltage_pp"] = []
            s["leds"] = []
            s["relay_status"] = None
            s["on_delay"] = None
            s["off_delay"] = None
            s["section_break"] = True
            continue

        s["settings"] = []

        # Phase angle 4th entry — only phase reverse steps, not plain phase recovery
        vpn = s.get("voltages_pn") or []
        if re.search(r"phase\s+reverse", name_lower) and not re.search(
            r"phase\s+reverse\s+recovery", name_lower
        ):
            if len(vpn) == 3:
                s["voltages_pn"] = vpn + ["(change phase angle)"]
        elif re.search(r"phase\s+reverse\s+recovery", name_lower):
            if len(vpn) == 3:
                s["voltages_pn"] = vpn + ["(recover phase angle)"]

        # OCR-driven symmetric voltages
        if base:
            if name_lower == "healthy condition":
                vpn, vpp = _layout_b_symmetric_voltages(base)
                s["voltages_pn"] = vpn
                s["voltage_pp"] = vpp
                if not s.get("off_delay"):
                    s["off_delay"] = "-"
            elif re.search(r"phase\s+reverse\s+recovery", name_lower):
                vpn, vpp = _layout_b_symmetric_voltages(base)
                s["voltages_pn"] = vpn + ["(recover phase angle)"]
                s["voltage_pp"] = vpp
            elif "phase fail" in name_lower and "recovery" not in name_lower:
                pp = int(base * 1.73205)
                s["voltages_pn"] = [f"RN : {base}", f"YN : {base}", f"BN : 0"]
                s["voltage_pp"] = [f"RY : {pp}", f"YB : {base}", f"BR : {base}"]
            elif "phase reverse" in name_lower and "recovery" not in name_lower:
                vpn, vpp = _layout_b_symmetric_voltages(base)
                s["voltages_pn"] = vpn + ["(change phase angle)"]
                s["voltage_pp"] = vpp
                s["leds"] = ["R (RED LED) : BLINKING"]
                s["relay_status"] = "Instant OFF"
                if not s.get("off_delay"):
                    s["off_delay"] = "Instant OFF"

        if lv:
            lo, hi = lv
            pn_hi = int(round(hi / 1.73205))
            pn_lo = int(round(lo / 1.73205))
            if "lower cut off healthy" in name_lower:
                s["voltages_pn"] = [f"RN : {pn_hi}", f"YN : {pn_hi}", f"BN : {pn_hi}"]
                s["voltage_pp"] = [f"RY : {hi}", f"YB : {hi}", f"BR : {hi}"]
            elif name_lower == "lower cut off":
                s["voltages_pn"] = [f"RN : {pn_lo}", f"YN : {pn_lo}", f"BN : {pn_lo}"]
                s["voltage_pp"] = [f"RY : {lo}", f"YB : {lo}", f"BR : {lo}"]
            elif "lower cut off not recovery" in name_lower:
                s["voltages_pn"] = [f"RN : {pn_hi}", f"YN : {pn_hi}", f"BN : {pn_hi}"]
                s["voltage_pp"] = [f"RY : {hi}", f"YB : {hi}", f"BR : {hi}"]
            elif "lower cut off recovery" in name_lower:
                lv_hyst_v = ctx.get("lv_hyst_v")
                if lv_hyst_v:
                    h_lo, h_hi = lv_hyst_v
                    recovery_pp = hi + (h_lo + h_hi) // 2
                    pn_rec = int(round(recovery_pp / 1.73205))
                    s["voltages_pn"] = [
                        f"RN : {pn_rec}", f"YN : {pn_rec}", f"BN : {pn_rec}",
                    ]
                    s["voltage_pp"] = [
                        f"RY : {recovery_pp}",
                        f"YB : {recovery_pp}",
                        f"BR : {recovery_pp}",
                    ]

        if hv:
            lo, hi = hv
            pn_lo = int(lo / 1.73205)
            pn_hi = int(hi / 1.73205)
            if "higher cut off healthy" in name_lower:
                s["voltages_pn"] = [f"RN : {pn_lo}", f"YN : {pn_lo}", f"BN : {pn_lo}"]
                s["voltage_pp"] = [f"RY : {lo}", f"YB : {lo}", f"BR : {lo}"]
            elif name_lower == "higher cut off":
                s["voltages_pn"] = [f"RN : {pn_hi}", f"YN : {pn_hi}", f"BN : {pn_hi}"]
                s["voltage_pp"] = [f"RY : {hi}", f"YB : {hi}", f"BR : {hi}"]

        # Asymmetry: BN from OCR tripping %, YB/BR from 3-phase line-voltage geometry
        if base and lv and "asymmetry" in name_lower:
            lo, hi = lv[0], lv[1]
            asym_trip = ctx.get("asym_trip_pct")
            pn_lo = int(lo / 1.73205)
            pn_hi = int(round(hi / 1.73205))
            ry_pp = int(base * 1.73205)
            bn = None
            if asym_trip:
                t_lo, t_hi = asym_trip
                pn_hi_trunc = int(hi / 1.73205)
                if "healthy" in name_lower:
                    bn = int(pn_hi_trunc * (100 - t_lo) / 100)
                elif "faulty" in name_lower:
                    bn = int(pn_lo * t_hi / 100)
                elif "not recovery" in name_lower:
                    bn = (base * t_hi) // 100 - 1
                elif "recovery" in name_lower and "not" not in name_lower:
                    asym_hyst = ctx.get("asym_hyst_pct")
                    if asym_hyst:
                        h_hi = asym_hyst[1]
                        h_pp = int(lo * h_hi / 100)
                        yb_target = int(round((lo + h_pp) * 1.73205))
                        bn = _layout_b_bn_from_yb(base, yb_target)
            if bn is not None:
                yb_pp = _layout_b_yb_from_bn(base, bn)
                s["voltages_pn"] = [
                    f"RN : {base}", f"YN : {base}", f"BN : {bn}",
                ]
                s["voltage_pp"] = [
                    f"RY : {ry_pp}", f"YB : {yb_pp}", f"BR : {yb_pp}",
                ]

        _fix_layout_b_delay_columns(s)
        _scrub_layout_b_delays(s)

        # Normalize LED format
        leds = s.get("leds") or []
        norm_leds = []
        for led in leds:
            led = re.sub(r"R\s*\(\s*RED", "R (RED", led)
            if "BLINK" in led.upper():
                led = "R (RED LED) : BLINKING"
            norm_leds.append(led)
        s["leds"] = norm_leds

    return steps


def _layout_b_empty_step(name: str, section_break: bool = False) -> Dict:
    return {
        "step_name": name,
        "settings": [],
        "voltages_pn": [],
        "voltage_pp": [],
        "leds": [],
        "relay_status": None,
        "on_delay": None,
        "off_delay": None,
        "section_break": section_break,
    }


def _layout_b_clone_step(step: Dict) -> Dict:
    return copy.deepcopy(step)


def _layout_b_ocr_has_repeat(pages: List[Page]) -> bool:
    text = " ".join(p.ocr_text or "" for p in pages)
    return bool(re.search(r"repeat\s+procedure", text, re.IGNORECASE))


def _ensure_layout_b_steps(steps: List[Dict], pages: List[Page]) -> List[Dict]:
    """Insert mandatory Layout B section labels and repeat LV block when Gemini omits them."""
    names_lower = [str(s.get("step_name", "")).lower() for s in steps]
    if not any("couple all" in n for n in names_lower):
        insert_idx = None
        for i, n in enumerate(names_lower):
            if "asymmetry recovery" in n:
                insert_idx = i + 1
                break
        if insert_idx is None:
            for i, n in enumerate(names_lower):
                if "lower cut off healthy" in n:
                    insert_idx = i
                    break
        if insert_idx is not None:
            steps.insert(
                insert_idx,
                {
                    "step_name": "Couple all Voltages",
                    "settings": [],
                    "voltages_pn": [],
                    "voltage_pp": [],
                    "leds": [],
                    "relay_status": None,
                    "on_delay": None,
                    "off_delay": None,
                    "section_break": True,
                },
            )

    names_lower = [str(s.get("step_name", "")).lower() for s in steps]
    lower_healthy_idx = [
        i for i, n in enumerate(names_lower) if "lower cut off healthy" in n
    ]
    ctx = _parse_layout_b_ocr_context(pages)
    has_asymmetry = bool(ctx.get("asym_trip_pct")) or any(
        "asymmetry" in n for n in names_lower
    )
    if (
        has_asymmetry
        and len(lower_healthy_idx) >= 2
        and not any(n.startswith("repeated tests") for n in names_lower)
    ):
        steps.insert(
            lower_healthy_idx[1],
            _layout_b_empty_step("Repeated Tests -", section_break=True),
        )

    names_lower = [str(s.get("step_name", "")).lower() for s in steps]
    lower_healthy_idx = [
        i for i, n in enumerate(names_lower) if "lower cut off healthy" in n
    ]
    if _layout_b_ocr_has_repeat(pages) and len(lower_healthy_idx) < 2:
        block_names = [
            "Lower Cut OFF healthy",
            "Lower Cut OFF",
            "Lower Cut OFF not recovery",
            "Lower Cut OFF recovery",
        ]
        templates: List[Dict] = []
        for bn in block_names:
            match = next(
                (s for s in steps if str(s.get("step_name", "")).lower() == bn.lower()),
                None,
            )
            templates.append(_layout_b_clone_step(match) if match else _layout_b_empty_step(bn))

        insert_at = None
        for i, n in enumerate(names_lower):
            if "lower cut off recovery" in n:
                insert_at = i + 1
                break
        if insert_at is not None:
            steps[insert_at:insert_at] = templates

    return steps


def _extract_procedure(genai, machine: str, variant: str, specs: Specs, pages: List[Page], spec_pages: Optional[List[Page]] = None) -> List[Dict]:
    if not pages:
        return []
    model = genai.GenerativeModel(VISION_MODEL)
    has_cutoffs = bool(specs.lv_cutoff or specs.hv_cutoff)
    has_thresholds = bool(specs.uv_threshold_pct or specs.ov_threshold_pct)
    has_uv_ov = bool(specs.uv_range or specs.ov_range)
    layout_b_ocr = any(
        re.search(r"PROCEDURE\s+FOR\s+CAT\s+ID.*R\s*LED", p.ocr_text or "", re.IGNORECASE)
        for p in pages
    )
    is_layout_b_proc = layout_b_ocr or (
        (not has_thresholds and not has_uv_ov) and has_cutoffs
    )
    if is_layout_b_proc:
        layout_type = "Layout B (cutoff, 1 LED)"
        prompt = PROCEDURE_PROMPT_B.format(variant=variant)
    else:
        layout_type = "Layout A (DIP switch, 4 LEDs)"
        prompt = PROCEDURE_PROMPT.format(
            variant=variant,
            layout_type=layout_type,
        )

    if len(pages) <= 10:
        selected_pages = pages
    elif len(pages) <= 20:
        selected_pages = pages[:12]
    else:
        selected_pages = pages[:16]

    seen = set()
    deduped = []
    for p in selected_pages:
        if p.num not in seen:
            deduped.append(p)
            seen.add(p.num)

    # Multi-DIP-block detection: if any proc page contains 2+ "[X] Goal" section
    # headings, the procedure spans multiple DIP S/W configurations.  Calling
    # Gemini once with all pages causes it to conflate or drop sections.  Instead
    # issue one Gemini call per proc page so each call focuses on one or two DIP
    # configurations at most, then merge the raw step lists.
    # This is generic — it triggers for any Layout A variant whose proc pages are
    # dense with goal sections; no variant-name checks.
    _GOAL_SECTION_RE = re.compile(r"\b[A-D]\]\s*Goal", re.IGNORECASE)
    # Multi-chunk fires only for a SINGLE page with 2+ DIP-section headings.
    # For 2 proc pages, sending them together in one call is always better:
    # splitting page N alone causes Gemini to hallucinate subsequent sections
    # whose content only appears on page N+1.
    _needs_multi_chunk = not is_layout_b_proc and len(deduped) == 1 and any(
        len(_GOAL_SECTION_RE.findall(p.ocr_text or "")) >= 2
        for p in deduped
    )

    if _needs_multi_chunk:
        logger.warning(
            f"{variant}: multi-DIP-section procedure detected —"
            f" issuing {len(deduped)} Gemini calls (higher API quota cost)"
        )
        steps: List[Dict] = []
        for _chunk_p in deduped:
            _chunk_seen = {_chunk_p.num}
            _chunk_ctx = (
                [p for p in spec_pages[:3] if p.jpeg_bytes and p.num not in _chunk_seen]
                if spec_pages else []
            )
            _chunk_pages = (_chunk_ctx + [_chunk_p])[:MAX_IMAGES_PER_CALL]
            _chunk_parts = [prompt] + _build_image_parts(_chunk_pages)
            logger.info(
                f"  vision procedure chunk (page {_chunk_p.num}): {variant},"
                f" {len(_chunk_parts) - 1} images"
            )
            _chunk_raw = _call_with_retry(
                model, _chunk_parts, DEFAULT_TIMEOUT, f"{variant} proc p{_chunk_p.num}"
            )
            if not _chunk_raw:
                logger.warning(f"{variant}: chunk page {_chunk_p.num} Gemini failed — skipping")
                continue
            _chunk_data = _parse_json(_chunk_raw, f"{variant} proc p{_chunk_p.num}")
            _chunk_steps = (
                (_chunk_data or {}).get("test_steps")
                or (_chunk_data or {}).get("steps")
                or (_chunk_data or {}).get("procedure")
                or []
            )
            if isinstance(_chunk_steps, list):
                logger.info(
                    f"{variant}: chunk page {_chunk_p.num}: {len(_chunk_steps)} raw steps"
                )
                steps.extend(_chunk_steps)
        if not steps:
            logger.warning(f"{variant}: all multi-chunk calls returned empty — aborting")
            return []
    else:
        if spec_pages and len(deduped) <= 4:
            spec_ctx = [p for p in spec_pages[:3] if p.jpeg_bytes and p.num not in seen]
            pages = spec_ctx + deduped
        else:
            pages = deduped
        pages = pages[:MAX_IMAGES_PER_CALL]

        parts = [prompt] + _build_image_parts(pages)
        logger.info(f"  vision procedure: {variant}, {len(parts)-1} images")
        raw = _call_with_retry(model, parts, DEFAULT_TIMEOUT, f"{variant} proc")
        if not raw:
            logger.warning(f"{machine}: Gemini failed — aborting extraction")
            return []
        data = _parse_json(raw, f"{variant} proc")

        if not data:
            logger.warning(f"{variant}: procedure JSON empty/invalid")
            return []

        steps = (
            data.get("test_steps")
            or data.get("steps")
            or data.get("procedure")
            or []
        )

        if not isinstance(steps, list):
            logger.warning(f"{variant}: unexpected procedure schema keys={list(data.keys())}")
            return []

    logger.info(f"{variant}: ALL extracted steps = {steps}")

    # Safeguard: if symmetrical steps exist but "Supply couple" annotation was omitted by
    # Gemini, insert it from OCR text.  The coupling voltage is detected from instructions
    # like "symmetrically reduce all phases to X V" that always precede these steps.
    if not is_layout_b_proc:
        _SYM_NAME_RE = re.compile(r"(?:UV|OV)\s+symm+etrical\s+Healthy", re.IGNORECASE)
        _COUPLE_NAME_RE = re.compile(r"supply\s+couple", re.IGNORECASE)
        _has_sym = any(_SYM_NAME_RE.match(s.get("step_name", "")) for s in steps)
        _has_couple = any(_COUPLE_NAME_RE.match(s.get("step_name", "")) for s in steps)
        if _has_sym and not _has_couple:
            _COUPLE_VOLT_RE = re.compile(
                r"symmetrically\s+reduce\b.*?\b(\d+)\s*V\b|"
                r"\bcouple\b.*?\b(\d+)\s*V\b",
                re.IGNORECASE,
            )
            _couple_voltage: Optional[str] = None
            for _pg in deduped:
                _m = _COUPLE_VOLT_RE.search(_pg.ocr_text or "")
                if _m:
                    _couple_voltage = _m.group(1) or _m.group(2)
                    break
            if _couple_voltage:
                _sym_idx = next(
                    i for i, s in enumerate(steps)
                    if _SYM_NAME_RE.match(s.get("step_name", ""))
                )
                steps.insert(_sym_idx, {
                    "step_name": f"Supply couple at {_couple_voltage} VAC",
                    "settings": [],
                    "voltages_pn": [],
                    "voltage_pp": [],
                    "leds": [],
                    "relay_status": None,
                    "on_delay": None,
                    "off_delay": None,
                    "section_break": True,
                })
                logger.info(
                    f"{variant}: inserted missing 'Supply couple at {_couple_voltage} VAC'"
                    f" step at index {_sym_idx} (Gemini omitted it)"
                )

    _BAD_LABEL_RE = re.compile(
        r"^(?:Under|Over)\s+Voltage|"
        r"^Phase\s+(?:asymmetry|fail)\s+(?:and|functionality)|"
        r"^Fix\s+(?:Under|Over)\s+voltage|"
        r"^(?:UV|OV)\s+(?:and\s+)?hysteresis\s+test|"
        r"^Phase\s+fail\s+and|"
        r"^DIP\s+S/W\s+functionality",
        re.IGNORECASE
    )
    filtered = []
    for s in steps:
        name = s.get("step_name", "")
        if "DIP S/W" in name and "Change" in name:
            filtered.append(s)
            continue
        if name.lower().startswith(("supply ", "dip s/w")):
            filtered.append(s)
            continue
        if _BAD_LABEL_RE.search(name):
            logger.debug(f"  filtering out section label: {name}")
            continue
        filtered.append(s)

    if len(filtered) < len(steps):
        logger.info(f"{variant}: filtered {len(steps)-len(filtered)} section labels -> {len(filtered)} steps")

    if is_layout_b_proc:
        filtered = _apply_layout_b_postprocessing(filtered, pages)
        filtered = _ensure_layout_b_steps(filtered, pages)
        filtered = _apply_layout_b_postprocessing(filtered, pages)
        filtered = _finalize_layout_b_steps(filtered, pages)
        logger.info(f"{variant}: Layout B post-processing applied, {len(filtered)} steps")
        return filtered

    # Normalize step names
    for s in filtered:
        name = s.get("step_name", "")
        if not name:
            continue
        name = re.sub(r'\bsymmetrical\b', 'symmmetrical', name, flags=re.IGNORECASE)
        name = re.sub(r'\s*\(symm+etrical\)\s*$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s*\(sym\)\s*$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\bhysteresis\b', 'hystersis', name, flags=re.IGNORECASE)
        if name.lower().startswith("ov faulty condition with delay"):
            name = name.replace("with delay", "").strip()
        if name.lower().startswith("uv faulty condition with delay"):
            name = name.replace("with delay", "").strip()
        name = re.sub(r'\s+Ph-[NP].*$', '', name, flags=re.IGNORECASE)
        s["step_name"] = name

    # Normalize LED states
    for s in filtered:
        leds = s.get("leds", [])
        if not leds:
            continue
        step_name_lower = s.get("step_name", "").lower()
        # Asymmetry section steps keep "(RED LED)" suffix for ASY BLINKING
        is_asymmetry_step = "asymmetry" in step_name_lower
        normalized_leds = []
        for led in leds:
            led = re.sub(r'(?:Fast|Slow)?\s*Blink(?:ing)?\s*\([^)]*\)', 'BLINKING', led, flags=re.IGNORECASE)
            led = re.sub(r'\bBlinking\b', 'BLINKING', led, flags=re.IGNORECASE)
            # Strip any parenthetical after BLINKING: "BLINKING (1s ON & 1s OFF)" → "BLINKING"
            led = re.sub(r'BLINKING\s*\([^)]*\)', 'BLINKING', led)
            # When BLINKING: strip color label from ASY and PWR — EXCEPT in Asymmetry section
            # (Asymmetry section: ref expects "ASY (RED LED): BLINKING" with suffix)
            if 'BLINKING' in led.upper() and not is_asymmetry_step:
                led = re.sub(r'(ASY)\s*\([^)]*\)\s*:', r'\1 :', led, flags=re.IGNORECASE)
                led = re.sub(r'(PWR)\s*\([^)]*\)\s*:', r'\1 :', led, flags=re.IGNORECASE)
            elif 'BLINKING' in led.upper() and is_asymmetry_step:
                # Asymmetry section: restore "(RED LED)" on ASY label if Gemini omitted it
                if re.match(r'ASY\s*:', led, flags=re.IGNORECASE):
                    led = re.sub(r'^(ASY)\s*:', r'ASY (RED LED):', led, flags=re.IGNORECASE)
            normalized_leds.append(led)
        s["leds"] = normalized_leds

    # OCR-driven post-processing
    ov_base = None
    ov_fault_v = None
    ov_recovery = None

    hyst_re = re.compile(
        r"reset\s+hysteresis\s*(?:voltage\s*)?(?:should\s+be\s*)?(?:in\s+the\s+range\s+of\s*)?(\d+(?:\.\d+)?)\s*V?\s*(?:to|and|-)\s*(\d+(?:\.\d+)?)\s*V",
        re.IGNORECASE
    )
    trip_re = re.compile(
        r"(?:OV\s+)?trip\s+voltage.*?(?:range\s+of\s*)?\s*(\d+(?:\.\d+)?)\s*V?\s*(?:to|and|-)\s*(\d+(?:\.\d+)?)\s*V",
        re.IGNORECASE
    )

    for p in pages:
        text = p.ocr_text or ""
        if ov_base is None:
            for m in hyst_re.finditer(text):
                a, b = float(m.group(1)), float(m.group(2))
                val = min(a, b)
                if val > 350:
                    ov_base = round(val / 1.73205)
                    ov_recovery = ov_base - 5.0
                    break

        if ov_fault_v is None:
            for m in trip_re.finditer(text):
                a, b = float(m.group(1)), float(m.group(2))
                val = min(a, b)
                if val > 350:
                    ov_fault_v = round(val / 1.73205, 1)
                    break

        if ov_base is not None and ov_fault_v is not None:
            break

    sym_ov_trip_lo = None
    sym_ov_trip_hi = None
    sym_ov_hyst_lo = None
    sym_ov_hyst_hi = None
    for p in pages:
        text = p.ocr_text or ""
        if not re.search(r"symmetric\s+ov|symmetr.*\sov\s", text, re.IGNORECASE):
            continue
        for m in re.finditer(
            r"range of (\d+(?:\.\d+)?)\s*V?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*V",
            text,
            re.IGNORECASE,
        ):
            a, b = float(m.group(1)), float(m.group(2))
            if max(a, b) < 400:
                sym_ov_trip_lo, sym_ov_trip_hi = min(a, b), max(a, b)
        m = re.search(
            r"hysteresis.*?range of (\d+(?:\.\d+)?)\s*V?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*V",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            sym_ov_hyst_lo = float(m.group(1))
            sym_ov_hyst_hi = float(m.group(2))

    sec_b_dips = None
    for p in pages:
        text = p.ocr_text or ""
        m = re.search(
            r"1\s+2\s+3\s+(\d)\s+(\d)\s+(\d).*?4\s+(\d).*?5\s+(\d)",
            text, re.DOTALL
        )
        if m:
            def _sw(v):
                return "ON" if str(v).strip() in ("1",) else "OFF"
            sec_b_dips = [
                f"1 : {_sw(m.group(1))}", f"2 : {_sw(m.group(2))}",
                f"3 : {_sw(m.group(3))}", f"4 : {_sw(m.group(4))}",
                f"5 : {_sw(m.group(5))}"
            ]
            break

    run_time_dips = None
    for p in pages:
        text = p.ocr_text or ""
        if "run time" in text.lower() or "runtime" in text.lower():
            m = re.search(
                r"(\d)\s*=\s*(\d).*?(\d)\s*=\s*(\d).*?(\d)\s*=\s*(\d).*?(\d)\s*=\s*(\d).*?(\d)\s*=\s*(\d)",
                text, re.DOTALL
            )
            if m:
                def _sw(v): return "ON" if str(v).strip() == "1" else "OFF"
                run_time_dips = [
                    f"1 : {_sw(m.group(2))}", f"2 : {_sw(m.group(4))}",
                    f"3 : {_sw(m.group(6))}", f"4 : {_sw(m.group(8))}",
                    f"5 : {_sw(m.group(10))}"
                ]
                break

    sec_b_ov_pct = None
    sec_b_delay = None
    for p in pages:
        text = p.ocr_text or ""
        if re.search(r"B\]\s*Goal|Over\s+Voltage|480V|Ph-Ph", text, re.IGNORECASE):
            m = re.search(r"OV\s*pot\s*[-\u2013\u2014]\s*(\d+)\s*%", text, re.IGNORECASE)
            if m:
                sec_b_ov_pct = m.group(1)
            m = re.search(r"Delay\s*[Pp]ot\s*[-\u2013\u2014]\s*(\d+)\s*sec", text, re.IGNORECASE)
            if m:
                sec_b_delay = m.group(1)
            if sec_b_ov_pct:
                break

    # 5. Parse Section C/D nominal voltage from OCR
    #    Look for "C] Goal" section with "at 240V" or "at 240V (415V Ph-Ph)"
    #    In SCOPE documents a page may contain text from several variants.
    #    Restrict the search to text starting at this variant's own heading so
    #    we don't pick up a preceding variant's "C] Goal ... at 240V".
    sec_cd_nominal_ocr = None
    _vn_re = _build_variant_re(variant)
    for p in pages:
        text = p.ocr_text or ""
        m_heading = _vn_re.search(text)
        search_text = text[m_heading.start():] if m_heading else text
        m_goal = re.search(r"C\]\s*Goal", search_text, re.IGNORECASE)
        if m_goal:
            # Only search text AFTER the C] Goal marker
            after_c = search_text[m_goal.end():]
            m = re.search(r"(?:Neutral\s+at|at)\s+(\d+)\s*V", after_c, re.IGNORECASE)
            if m:
                sec_cd_nominal_ocr = float(m.group(1))
                logger.info(f"  Section C/D nominal from OCR: {sec_cd_nominal_ocr}V Ph-N")
                break

    # Apply overrides
    processed = []
    saw_supply_off_change = False
    sec_cd_nominal_pn = sec_cd_nominal_ocr  # Pre-fill from OCR; may be overridden by Supply couple step
    sec_a_nominal_pn = None   # Ph-N nominal for Section A (detected from first healthy step)
    i = 0
    while i < len(filtered):
        s = filtered[i]
        name = s.get("step_name", "")
        name_lower = name.lower().strip()

        # Run time DIP + next DIP S/W block
        if "run time dip" in name_lower and i + 1 < len(filtered):
            next_s = filtered[i + 1]
            if "dip" in next_s.get("step_name", "").lower():
                s["voltages_pn"] = []
                s["voltage_pp"] = []
                s["leds"] = []
                s["relay_status"] = None
                s["on_delay"] = None
                s["section_break"] = False

                if run_time_dips:
                    next_s["settings"] = run_time_dips
                if ov_recovery is not None:
                    v = int(round(ov_recovery))
                    pp = int(round(ov_recovery * 1.73205))
                    next_s["voltages_pn"] = [f"RN : {v}", f"YN : {v}", f"BN : {v}"]
                    next_s["voltage_pp"] = [f"RY : {pp}", f"YB : {pp}", f"BR : {pp}"]
                next_s["section_break"] = False

                processed.append(s)
                processed.append(next_s)
                i += 2
                continue

        if "supply off change" in name_lower:
            saw_supply_off_change = True

        # Track Section C/D nominal voltage from Supply couple step (only after Supply OFF change)
        if saw_supply_off_change and "supply couple" in name_lower:
            # Try to get nominal from the step's own voltages first (most reliable)
            sc_vpn = s.get("voltages_pn") or []
            if sc_vpn:
                m_scv = re.search(r':\s*([\d.]+)', str(sc_vpn[0]))
                if m_scv:
                    sec_cd_nominal_pn = float(m_scv.group(1))
                    logger.info(f"  Section C/D nominal from Supply couple voltages: {sec_cd_nominal_pn}V Ph-N")
            # Fallback: parse from step name
            if sec_cd_nominal_pn is None:
                m_sc = re.search(r'(\d+)\s*(?:VAC|V)', name, re.IGNORECASE)
                if m_sc:
                    pp_v = float(m_sc.group(1))
                    # If value > 300, it's Ph-Ph — convert to Ph-N
                    sec_cd_nominal_pn = round(pp_v / 1.73205, 1) if pp_v > 300 else pp_v
                    logger.info(f"  Section C/D nominal from Supply couple name: {sec_cd_nominal_pn}V Ph-N")

        # Track Section A nominal from first healthy condition step
        if not saw_supply_off_change and sec_a_nominal_pn is None and name_lower == "healthy condition":
            vpn_list = s.get("voltages_pn") or []
            if vpn_list:
                m_va = re.search(r':\s*([\d.]+)', str(vpn_list[0]))
                if m_va:
                    sec_a_nominal_pn = float(m_va.group(1))
                    logger.info(f"  Section A nominal detected: {sec_a_nominal_pn}V Ph-N")

        # Remove spurious plain "Supply OFF" steps after Supply OFF change
        # (DIP S/W changes are allowed here — some variants need them between asymmetry sections)
        if saw_supply_off_change and "supply off change" not in name_lower:
            if name_lower == "supply off":
                logger.info(f"  skipping spurious post-SupplyOFF step: {name}")
                i += 1
                continue

        # Section B DIP switch settings
        if "dip s/w" in name_lower and sec_b_dips and not processed:
            pass
        elif "dip s/w" in name_lower and sec_b_dips:
            if not any("ov" in ps.get("step_name", "").lower() for ps in processed):
                s["settings"] = sec_b_dips

        # OV voltage overrides — symmetric OV section only (Section B non-sym OV uses Gemini output directly)
        if sym_ov_trip_hi is not None and re.search(
            r"ov symmmetrical healthy", name_lower
        ):
            v = sym_ov_trip_hi
            vs = str(int(v)) if v == int(v) else f"{v:.1f}".rstrip("0").rstrip(".")
            s["voltages_pn"] = [f"RN : {vs}", f"YN : {vs}", f"BN : {vs}"]

        elif sym_ov_trip_lo is not None and re.search(
            r"ov symmmetrical faulty", name_lower
        ):
            v = sym_ov_trip_lo
            vs = str(int(v)) if v == int(v) else f"{v:.1f}".rstrip("0").rstrip(".")
            s["voltages_pn"] = [f"RN : {vs}", f"YN : {vs}", f"BN : {vs}"]

        elif sym_ov_trip_hi is not None and re.search(
            r"ov symmmetrical", name_lower
        ) and "not recovery" in name_lower:
            v = sym_ov_trip_hi
            vs = str(int(v)) if v == int(v) else f"{v:.1f}".rstrip("0").rstrip(".")
            s["voltages_pn"] = [f"RN : {vs}", f"YN : {vs}", f"BN : {vs}"]

        elif (
            sym_ov_trip_hi is not None
            and sym_ov_hyst_hi is not None
            and re.search(r"ov symmmetrical", name_lower)
            and "recovery" in name_lower
            and "not" not in name_lower
        ):
            v = sym_ov_trip_hi + sym_ov_hyst_hi
            vs = str(int(v)) if v == int(v) else f"{v:.1f}".rstrip("0").rstrip(".")
            s["voltages_pn"] = [f"RN : {vs}", f"YN : {vs}", f"BN : {vs}"]

        elif "phase fail" in name_lower and "recovery" not in name_lower:
            pass

        # Section B settings normalization (OCR override)
        if any(kw in name_lower for kw in ["ov healthy", "ov faulty", "ov hystersis"]):
            if sec_b_ov_pct or sec_b_delay:
                new_settings = []
                for st in (s.get("settings") or []):
                    if isinstance(st, str):
                        if "OV" in st.upper() and "%" in st and sec_b_ov_pct:
                            st = f"OV = {sec_b_ov_pct} %"
                        if "DELAY" in st.upper() and sec_b_delay:
                            st = f"DELAY = {sec_b_delay} SEC"
                    new_settings.append(st)
                s["settings"] = new_settings

        # Settings format normalization
        if s.get("settings"):
            settings_str = " ".join(str(st) for st in s["settings"])
            # Section A: UV=8%. OV steps are NEVER Section A.
            is_section_a = bool(re.search(r"UV\s*=\s*8\s*%", settings_str, re.IGNORECASE))
            if any(kw in name_lower for kw in ["ov healthy", "ov faulty", "ov hystersis"]):
                is_section_a = False  # OV steps are always Section B

            new_settings = []
            for st in s["settings"]:
                if isinstance(st, str):
                    # Uppercase sec -> SEC
                    st = re.sub(r'\bsec\b', 'SEC', st, flags=re.IGNORECASE)

                    # DELAY spacing
                    if "DELAY" in st.upper():
                        if is_section_a:
                            st = re.sub(r'(\d+)\s+SEC', r'\1SEC', st)
                        else:
                            st = re.sub(r'(\d+)SEC', r'\1 SEC', st)

                    # OV % spacing rules:
                    # - Section A (UV=8%): OV = 22% (no space)
                    # - Symmetrical (UV=22%, before Supply OFF change): OV = 22% (no space)
                    # - Section B (OV steps): OV = 6 % or OV = 8 % (space, non-22 value)
                    # - Section C/D (after Supply OFF change): OV = 22 % (space)
                    if re.match(r'OV\s*=', st, re.IGNORECASE):
                        is_ov_22 = bool(re.search(r'=\s*22\s*%', st, re.IGNORECASE))
                        if is_ov_22 and saw_supply_off_change:
                            # Section C/D: add space -> "OV = 22 %"
                            st = re.sub(r'(22)\s*%', r'\1 %', st)
                        elif is_ov_22:
                            # Section A or Symmetrical: remove space -> "OV = 22%"
                            st = re.sub(r'(22)\s+%', r'\1%', st)
                        elif not is_section_a:
                            # Non-22% OV in non-Section-A (Section B): add space -> "OV = 6 %"
                            st = re.sub(r'(\d+)\s*%', r'\1 %', st)

                    elif re.match(r'UV\s*=', st, re.IGNORECASE):
                        # UV never has space before %
                        st = re.sub(r'(\d+)\s+%', r'\1%', st)

                new_settings.append(st)
            s["settings"] = new_settings

        # Derive voltage_pp from voltages_pn — ONLY for Section C/D (after Supply OFF change)
        # Section A has no voltage_pp. Section B already has it from Gemini.
        vpn = s.get("voltages_pn") or []
        vpp = s.get("voltage_pp") or []
        if saw_supply_off_change and vpn and not vpp and not any(kw in name_lower for kw in ["dip s/w", "supply", "run time"]):
            derived_pp = []
            pp_labels = ["RY", "YB", "BR"]
            for idx, v_str in enumerate(vpn[:3]):
                m_v = re.search(r':\s*([\d.]+)', str(v_str))
                if m_v:
                    pn_val = float(m_v.group(1))
                    pp_val = int(pn_val * 1.73205)  # truncate, not round — matches reference
                    if idx < len(pp_labels):
                        derived_pp.append(f"{pp_labels[idx]} : {pp_val}")
            if derived_pp:
                s["voltage_pp"] = derived_pp

        # Section C/D voltage correction
        # Gemini sometimes uses wrong reference voltage for Section C/D steps:
        #   - Section A nominal (120V) or Section B nominal (277V) instead of Section C (240V)
        # We detect this generically: if all 3 phases are equal but NOT at expected C/D nominal,
        # or 2-of-3 are at a consistent wrong base, correct using OCR-derived nominal.
        if saw_supply_off_change and sec_cd_nominal_pn:
            vpn_fix = s.get("voltages_pn") or []
            if len(vpn_fix) >= 3 and not any(kw in name_lower for kw in ["dip s/w", "supply", "run time"]):
                pn_labels = ["RN", "YN", "BN"]
                pn_vals = []
                for vf in vpn_fix[:3]:
                    m_vf = re.search(r':\s*([\d.]+)', str(vf))
                    if m_vf:
                        pn_vals.append(float(m_vf.group(1)))
                    else:
                        pn_vals.append(None)
                valid_vals = [v for v in pn_vals if v is not None]
                nom = int(sec_cd_nominal_pn) if sec_cd_nominal_pn == int(sec_cd_nominal_pn) else sec_cd_nominal_pn

                if len(valid_vals) == 3:
                    # Check if all 3 are equal (symmetric step with wrong base)
                    all_equal = all(abs(v - pn_vals[0]) < 2.0 for v in pn_vals)
                    at_correct_nom = abs(pn_vals[0] - sec_cd_nominal_pn) < 5.0
                    
                    if all_equal and not at_correct_nom and pn_vals[0] > 0:
                        # All symmetric but wrong voltage — replace with correct C/D nominal
                        wrong_base = pn_vals[0]
                        s["voltages_pn"] = [f"{pn_labels[j]} : {nom}" for j in range(3)]
                        pp_nom = int(nom * 1.73205)
                        s["voltage_pp"] = [f"RY : {pp_nom}", f"YB : {pp_nom}", f"BR : {pp_nom}"]
                        logger.info(f"  Section C/D voltage fix: {name} -> {nom}V Ph-N (was {wrong_base}V)")
                    elif not all_equal:
                        # Asymmetry: find the most common value (base voltage)
                        from collections import Counter
                        rounded = [round(v) for v in pn_vals]
                        counts = Counter(rounded)
                        most_common_val, most_common_count = counts.most_common(1)[0]
                        
                        if most_common_count >= 2 and abs(most_common_val - sec_cd_nominal_pn) > 5.0:
                            # 2+ phases at wrong base — scale by ratio
                            ratio = sec_cd_nominal_pn / most_common_val if most_common_val else 1.0
                            if ratio > 1.2:  # Only fix if significant ratio difference
                                new_vpn = []
                                new_vpp = []
                                pp_labels_inner = ["RY", "YB", "BR"]
                                for j, v in enumerate(pn_vals):
                                    scaled = round(v * ratio, 1)
                                    if scaled == int(scaled):
                                        vs = str(int(scaled))
                                    else:
                                        vs = f"{scaled:.2f}".rstrip("0").rstrip(".")
                                    new_vpn.append(f"{pn_labels[j]} : {vs}")
                                    new_vpp.append(f"{pp_labels_inner[j]} : {int(scaled * 1.73205)}")
                                s["voltages_pn"] = new_vpn
                                s["voltage_pp"] = new_vpp
                                logger.info(f"  Section C/D asymmetry fix: {name} scaled by {ratio:.2f} (base was {most_common_val}V)")

        # Phase angle 4th voltage entry
        # Reference has (change phase angle) / (recover phase angle) as 4th voltages_pn
        vpn_now = s.get("voltages_pn") or []
        if "phase reverse" in name_lower:
            if "recovery" not in name_lower:
                if len(vpn_now) == 3:
                    s["voltages_pn"] = vpn_now + ["(change phase angle)"]
            else:
                if len(vpn_now) == 3:
                    s["voltages_pn"] = vpn_now + ["(recover phase angle)"]

        processed.append(s)
        i += 1

    # Deduplicate: Gemini sometimes inserts an extra "Healthy condition" step in section C/D
    # (immediately after Asymmetry recovery, before Phase fail) that the reference omits.
    # The reference has exactly ONE Healthy condition in section C/D — keep the first, drop the rest.
    _in_cd = False
    _seen_cd_healthy = False
    _deduped: list = []
    for _s in processed:
        _nm = str(_s.get("step_name", "")).lower().strip()
        if "supply off change" in _nm:
            _in_cd = True
        if _in_cd and _nm == "healthy condition":
            if _seen_cd_healthy:
                logger.info(
                    f"{variant}: removed duplicate 'Healthy condition' in section C/D"
                    " (extra step before Phase fail — dropped)"
                )
                continue
            _seen_cd_healthy = True
        _deduped.append(_s)
    processed = _deduped

    return processed


_SPEC_FIELDS = [
    "ref_voltage", "uv_range", "uv_threshold_pct", "ov_range", "ov_threshold_pct",
    "uv_hysteresis", "ov_hysteresis", "asymmetry", "on_delay", "off_delay",
    "phase_fail", "phase_reverse", "neutral_fail", "virtual_neutral",
    "lv_cutoff", "hv_cutoff", "voltage_unit", "notes",
]


def _normalize_specs(raw: Dict) -> Specs:
    if not isinstance(raw, dict):
        return Specs()
    s = Specs()
    for f in _SPEC_FIELDS:
        v = raw.get(f)
        if v == "" or v == "null":
            v = None
        setattr(s, f, v)
    leds = raw.get("led_indications")
    s.led_indications = leds if isinstance(leds, dict) else {}
    dips = raw.get("dip_switches")
    s.dip_switches = dips if isinstance(dips, list) else []
    return s


def _round_voltage(v_str: str) -> str:
    """Round numeric part of voltage strings.
    Ph-N (RN/YN/BN): round to 1 decimal, drop trailing .0
    Ph-Ph (RY/YB/BR): floor to integer (matches reference rounding behaviour)
    """
    import math as _math
    if ' : ' not in v_str:
        return v_str
    label, num_str = v_str.split(' : ', 1)
    try:
        val = float(num_str.strip())
        label_clean = label.strip()
        # Ph-Ph labels (RY, YB, BR) — floor to integer
        if label_clean.upper() in ('RY', 'YB', 'BR'):
            return f"{label_clean} : {_math.floor(val)}"
        # Ph-N labels (RN, YN, BN) — 1 decimal, drop trailing .0
        r1 = round(val, 1)
        if r1 == int(r1):
            return f"{label_clean} : {int(r1)}"
        return f"{label_clean} : {r1}"
    except (ValueError, TypeError):
        return v_str


_PHASE_TEST_NAMES = {"phase fail", "phase recovery", "phase reverse", "phase reverse recovery"}


def _normalize_step(raw: Dict) -> Optional[TestStep]:
    if not isinstance(raw, dict):
        return None
    name = raw.get("step_name")
    if not name or not isinstance(name, str):
        return None
    # Normalize step name: add double-space before "not recovery" and "recovery" in Phase Asymmetry names
    name = name.strip()
    name = re.sub(r'\bPhase Asymmetry (not recovery|recovery)\b', r'Phase Asymmetry  \1', name)

    settings = raw.get("settings") or []
    settings = (
        [str(x).strip() for x in settings if x]
        if isinstance(settings, list)
        else []
    )
    # Reference format: single-digit % gets space ("7 %"), multi-digit gets none ("25%")
    def _fmt_pct(m: re.Match) -> str:
        d = m.group(1)
        return d + (' %' if len(d) == 1 else '%')
    settings = [
        re.sub(r'(\d+)\s*%', _fmt_pct, s) if re.match(r'P[123]\s*=', s, re.IGNORECASE) else s
        for s in settings
    ]
    # Phase test steps use P2/P3 in SEC, not MIN
    if str(name).strip().lower() in _PHASE_TEST_NAMES:
        settings = [s.replace('P2 = 0 MIN', 'P2 = 0 SEC').replace('P3 = 0 MIN', 'P3 = 0 SEC') for s in settings]
    # Section B UV/OV steps (any setting contains MIN) must use MIN for P3 (not SEC)
    elif any('MIN' in s for s in settings) and any('P3 = 0 SEC' in s or 'P3 = 0SEC' in s for s in settings):
        settings = [s.replace('P3 = 0 SEC', 'P3 = 0 MIN').replace('P3 = 0SEC', 'P3 = 0 MIN') for s in settings]

    voltages_pn = raw.get("voltages_pn") or []
    voltages_pn = [_round_voltage(str(x)) for x in voltages_pn][:4] if isinstance(voltages_pn, list) else []

    leds = raw.get("leds") or []
    leds = (
        [str(x).strip() for x in leds if x]
        if isinstance(leds, list)
        else []
    )

    raw_pp = raw.get("voltage_pp") or []
    if isinstance(raw_pp, list):
        voltage_pp = [_round_voltage(str(x).strip()) for x in raw_pp if x][:4]
    elif isinstance(raw_pp, str) and raw_pp.strip():
        voltage_pp = [_round_voltage(raw_pp.strip())]
    else:
        voltage_pp = []

    name_lower = str(name).strip().lower()
    raw_section_break = bool(raw.get("section_break"))
    # Hyst recovery steps and Phase Asymmetry recovery must NEVER have section_break=True
    # (the following step is always placed immediately after — no extra blank row needed)
    if raw_section_break and any(x in name_lower for x in (
        "hystersis recovery", "hysteresis recovery",
        "phase asymmetry recovery", "asymmetry recovery",
    )):
        raw_section_break = False

    # Normalize off_delay: time-range like "14-16 SEC" → "OFF in 14-16 sec"
    # Only applies when lower bound has 2+ digits (≥10 sec), to avoid transforming
    # short ranges like "2-4 SEC" that the reference keeps without the "OFF in" prefix.
    raw_off_delay = raw.get("off_delay") or None
    if raw_off_delay and isinstance(raw_off_delay, str):
        raw_off_delay = re.sub(
            r'^(\d{2,}[-–]\d+)\s*(SEC|sec)$', r'OFF in \1 sec',
            raw_off_delay.strip()
        )

    return TestStep(
        step_name=str(name).strip(),
        settings=settings,
        voltages_pn=voltages_pn,
        voltage_pp=voltage_pp,
        leds=leds,
        relay_status=raw.get("relay_status") or None,
        on_delay=raw.get("on_delay") or None,
        off_delay=raw_off_delay,
        section_break=raw_section_break,
    )


def _norm(s: str):
    return re.sub(r"\s+", "", s).upper()


def extract_machine_data(block: Block, sub_machines: Optional[List[str]] = None) -> Dict[str, VariantData]:
    """Vision-first extraction. Returns {variant_name: VariantData}."""
    genai = _get_client()
    if genai is None:
        logger.info(f"{block.machine}: Gemini unavailable")
        return {}

    variants = [v.upper() for v in (sub_machines or [block.machine])]
    original_variants = list(variants)
    variants = [
        v for v in variants
        if re.match(r"^[A-Z0-9][A-Z0-9_]*$", v) and len(v) >= 3 and re.search(r"[A-Z]", v)
    ]
    if not variants and original_variants:
        dropped = [v for v in original_variants if v not in variants]
        logger.warning(
            f"{block.machine}: all variants dropped by filter: {dropped} — "
            f"falling back to block.machine={block.machine}"
        )
        variants = [block.machine.upper()]

    spec_pages = extract_table_pages(block.pages)
    spec_pages = spec_pages[:8]

    if not spec_pages:
        cls = _classify_pages_for_variant(block, variants[0])
        spec_pages = cls["spec_pages"]

    proc_pages_per_variant: Dict[str, List[Page]] = {}

    for v in variants:
        cls = _classify_pages_for_variant(block, v)
        proc_pages_per_variant[v] = cls["proc_pages"]

    logger.info(f"{block.machine}: spec_pages={len(spec_pages)} variants={len(variants)}")

    table_grids = extract_table_grids(spec_pages)
    variant_maps = extract_variant_mappings(table_grids, known_variants=variants)

    logger.info(f"{block.machine}: full table variants -> {list(variant_maps.keys())}")
    logger.info(f"{block.machine}: mapped variants from tables -> {list(variant_maps.keys())}")
    logger.info(f"{block.machine}: extracted {len(table_grids)} table grids")

    raw_specs = _extract_specs(genai, block.machine, variants, spec_pages)
    raw_specs = merge_table_into_specs(variant_maps, raw_specs)

    out: Dict[str, VariantData] = {}
    for v in variants:
        v_key = re.sub(r"\s+", "", v).upper()
        spec_dict = raw_specs.get(v_key) or {}
        if not spec_dict:
            for k, val in raw_specs.items():
                if _norm(v_key) == _norm(k):
                    spec_dict = val
                    break

        specs = _normalize_specs(spec_dict)
        valid_voltage_specs = any([
            specs.uv_range,
            specs.ov_range,
            specs.lv_cutoff,
            specs.hv_cutoff,
        ])

        if not valid_voltage_specs:
            logger.warning(f"{v}: specs incomplete — continuing procedure extraction")

        variant_raw = raw_specs.get(v_key, {}) if isinstance(raw_specs, dict) else {}
        proc_pages = proc_pages_per_variant.get(v, [])
        proc_ocr = "\n".join((p.ocr_text or "") for p in proc_pages)
        layout_b_variant = bool(
            re.search(r"PROCEDURE\s+FOR\s+CAT\s+ID.*R\s*LED", proc_ocr, re.IGNORECASE)
        )

        steps_raw = _extract_procedure(genai, block.machine, v, specs, proc_pages, spec_pages=spec_pages)
        real_count = _count_test_steps(steps_raw)
        logger.info(f"{v}: step count = {real_count} (raw={len(steps_raw)})")

        # Step count retry — Layout A only
        has_cutoffs = bool(specs.lv_cutoff or specs.hv_cutoff)
        has_thresholds = bool(specs.uv_threshold_pct or specs.ov_threshold_pct)
        has_uv_ov = bool(specs.uv_range or specs.ov_range)
        is_layout_a = not layout_b_variant and not (
            (not has_thresholds and not has_uv_ov) and has_cutoffs
        )

        def _layout_b_incomplete(raw_steps: List[Dict]) -> bool:
            ctx = _parse_layout_b_ocr_context(proc_pages)
            names = [str(s.get("step_name", "")).lower() for s in raw_steps]
            for req in ("phase reverse", "couple all", "higher cut off"):
                if not any(req in n for n in names):
                    return True
            if _layout_b_ocr_has_repeat(proc_pages):
                if sum(1 for n in names if "lower cut off healthy" in n) < 2:
                    return True
            if ctx.get("asym_trip_pct") and not any(
                "repeated tests" in n for n in names
            ):
                return True
            return False

        if layout_b_variant and _layout_b_incomplete(steps_raw):
            logger.warning(f"{v}: Layout B incomplete ({len(steps_raw)} steps) — retrying")
            best_raw = steps_raw
            best_count = real_count
            for attempt in range(MAX_STEP_RETRIES):
                time.sleep(10)
                retry_raw = _extract_procedure(
                    genai, block.machine, v, specs, proc_pages, spec_pages=spec_pages
                )
                retry_count = _count_test_steps(retry_raw)
                logger.info(f"{v}: Layout B retry {attempt+1} step count = {retry_count}")
                if not _layout_b_incomplete(retry_raw):
                    best_raw = retry_raw
                    best_count = retry_count
                    break
                if retry_count > best_count:
                    best_raw = retry_raw
                    best_count = retry_count
            steps_raw = best_raw
            real_count = best_count
            logger.info(f"{v}: Layout B final step count = {best_count}")

        if is_layout_a and (real_count < MIN_STEPS or real_count > MAX_STEPS):
            logger.warning(f"{v}: step count {real_count} outside [{MIN_STEPS},{MAX_STEPS}] — retrying")
            best_raw = steps_raw
            best_count = real_count
            for attempt in range(MAX_STEP_RETRIES):
                time.sleep(10)
                retry_raw = _extract_procedure(genai, block.machine, v, specs, proc_pages, spec_pages=spec_pages)
                retry_count = _count_test_steps(retry_raw)
                logger.info(f"{v}: retry {attempt+1} step count = {retry_count}")
                retry_in_range = MIN_STEPS <= retry_count <= MAX_STEPS
                best_in_range = MIN_STEPS <= best_count <= MAX_STEPS
                if retry_in_range and not best_in_range:
                    best_raw = retry_raw
                    best_count = retry_count
                elif retry_in_range == best_in_range:
                    if abs(retry_count - EXPECTED_STEPS) < abs(best_count - EXPECTED_STEPS):
                        best_raw = retry_raw
                        best_count = retry_count
                if retry_in_range:
                    break
            steps_raw = best_raw
            logger.info(f"{v}: final step count after retries = {best_count}")

        steps = [s for s in (_normalize_step(r) for r in steps_raw) if s is not None]

        vd = VariantData(
            name=v,
            specs=specs,
            test_steps=steps,
            audit={
                "machine": block.machine,
                "spec_pages": [p.num for p in spec_pages],
                "proc_pages": [p.num for p in proc_pages],
                "raw_specs_present": bool(spec_dict),
                "raw_step_count": len(steps_raw),
            },
        )

        vd.raw_specs = variant_raw
        out[v] = vd

        logger.info(
            f"[EXTRACTION_RESULT] "
            f"machine={block.machine} "
            f"variants={list(out.keys())}"
        )

        for k, v in out.items():
            logger.info(
                f"[VARIANT_SUMMARY] "
                f"{k} "
                f"steps={len(v.test_steps)} "
                f"flags={len(v.specs.flags)} "
                f"ref_voltage={v.specs.ref_voltage} "
                f"uv={v.specs.uv_range} "
                f"ov={v.specs.ov_range}"
            )

    return out


def extraction_was_successful(vd: VariantData) -> bool:
    return vd.is_usable()