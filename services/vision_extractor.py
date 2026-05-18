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
import os
import re
import json
import time
import logging
import concurrent.futures
from typing import List, Dict, Optional

from .types import Page, Block, Specs, TestStep, VariantData
from services.table_parser import extract_table_pages
from services.table_grid_extractor import extract_table_grids
from services.variant_mapper import extract_variant_mappings
from services.variant_mapper import merge_table_into_specs

logger = logging.getLogger(__name__)


VISION_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT = 120
MAX_RETRIES = 3
BACKOFFS = [15, 30, 60]
MAX_IMAGES_PER_CALL = 8


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
            logger.info(f"  [{label}] call failed: {e}")
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
        logger.info(f"  [{label}] JSON parse failed: {e}")
        logger.debug(f"    raw[:500]: {cleaned[:500]}")
        return None


def _classify_pages(block: Block) -> Dict[str, List[Page]]:
    """Pick spec-table pages and procedure pages from a block via cheap regex."""
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
        r"|^\s*\d+\.\s|DIP\s*S/W\s*setting",
        re.IGNORECASE | re.MULTILINE,
    )

    for p in block.pages:
        if p.jpeg_bytes is None:
            continue
        if spec_re.search(p.ocr_text):
            spec_pages.append(p)
        # Detect procedure start
        is_proc = proc_re.search(p.ocr_text)
        # Detect continuation (important)
        has_steps = bool(re.search(r"\d+\.", p.ocr_text))
        has_dip = "DIP" in p.ocr_text.upper()

        if is_proc or has_steps or has_dip:
            proc_pages.append(p)

    if not spec_pages:
        spec_pages = [
            p for p in block.pages
            if p.jpeg_bytes is not None
        ][:4]

    if not proc_pages:
        proc_pages = [
            p for p in block.pages
            if p.jpeg_bytes is not None and "procedure" in p.ocr_text.lower()
        ][:4] or block.pages[:5]

    return {"spec": spec_pages, "proc": proc_pages}


def _classify_pages_for_variant(block: Block, variant: str) -> Dict[str, List[Page]]:
    """
    Variant-aware classification.
    Keeps common spec pages, but narrows procedure pages.
    """

    spec_pages = []
    proc_pages = []

    variant_clean = variant.upper().replace("_", "")
    variant_re = re.compile(
        rf"\b{re.escape(variant_clean)}\b|\b{re.escape(variant)}\b",
        re.IGNORECASE
    )

    spec_re = re.compile(
        r"TABLE|PRODUCT\s*SETTINGS|ACCEPTABLE\s*LIMITS|REF\.?\s*VOLTAGE",
        re.IGNORECASE,
    )

    proc_re = re.compile(
        r"PROCEDURE"
        r"|FUNCTIONAL\s+TEST"
        r"|DIP\s*S/W"
        r"|TEST\s+PROCEDURE"
        r"|CHECK\s+POINT",
        re.IGNORECASE,
    )

    for p in block.pages:
        if not p.jpeg_bytes:
            continue

        text = p.ocr_text or ""

        # --- SPEC pages (shared across variants) ---
        if spec_re.search(text):
            spec_pages.append(p)

        # --- PROCEDURE pages (variant filtered) ---
        has_proc_marker = proc_re.search(text)

        # Step numbering only counts if it looks like an actual procedure list
        has_step_pattern = bool(
            re.search(r"^\s*\d+\.\s+[A-Z]", text, re.MULTILINE)
        )

        if (has_proc_marker or has_step_pattern):
            if variant_re.search(text):
                proc_pages.append(p)

    # Fallback: if too few variant-specific proc pages, find the page where the
    # variant name first appears in a procedure context, then take a window around it.
    # This is more targeted than taking the first 6 proc pages from a 60-page document.
    if len(proc_pages) < 3:
        all_proc = [
            p for p in block.pages
            if proc_re.search(p.ocr_text or "")
        ]
        # Find anchor: first proc page that mentions the variant
        anchor_idx = next(
            (i for i, p in enumerate(all_proc) if variant_re.search(p.ocr_text or "")),
            None
        )
        if anchor_idx is not None:
            # Take a window of 6 pages centered on the anchor
            start = max(0, anchor_idx - 1)
            proc_pages = all_proc[start: start + 6]
        else:
            proc_pages = all_proc[:20]

    # Final fallback
    if not proc_pages:
        proc_pages = [
            p for p in block.pages
            if proc_re.search(p.ocr_text or "")
        ][:20]

    # 🔴 fallback spec
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
1. A merged cell that visually spans multiple columns means ALL those
   variants share that value.
2. An empty cell or "NA" in a variant's column means that variant does NOT
   have that parameter — return null for that variant.
3. NEVER invent values. If something is not visible in the PDF for a variant,
   return null. Do not default to "240 VAC" or any other guess.
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


PROCEDURE_PROMPT = """You are extracting a manufacturing TEST PROCEDURE from industrial PDF pages.

VARIANT: {variant}

KNOWN SPECS:
  ref_voltage:  {ref_voltage}
  uv_range:     {uv_range}
  ov_range:     {ov_range}
  voltage_unit: {voltage_unit}

IMPORTANT CONTEXT:

These pages may be:
- formal numbered procedures
- work instructions (WI)
- instructional process sheets
- shared procedures for multiple machine variants
- mixed layouts containing tables + instructions

The procedure may NOT be perfectly tabular.

Your task:
Extract ALL real machine-testing actions relevant to the variant.

Even if the document is instructional or spread across pages,
convert the testing flow into structured TEST STEPS.

A test step may come from:
- numbered instructions
- verification actions
- DIP switch configuration sections
- healthy/fault condition checks
- voltage-setting actions
- relay verification
- LED verification
- fault testing sequences

DO NOT return empty output unless absolutely no testing actions exist.

Each test step must have this shape:

{{
  "step_name": short descriptive label,

  "settings": [
    "1: OFF",
    "2: ON",
    "3: OFF"
  ],

  "voltages_pn": [
    "RN : 230",
    "YN : 230",
    "BN : 230"
  ],

  "voltage_pp": string|null,

  "leds": [
    "PWR (GREEN LED) : ON",
    "UV (RED LED) : OFF"
  ],

  "relay_status": string|null,
  "on_delay": string|null,
  "off_delay": string|null,

  "section_break": boolean
}}

CRITICAL RULES:

1. DO NOT invent values.
   Missing values => null or [].

2. If a section starts with DIP S/W settings,
   preserve the FULL DIP configuration.

3. DO NOT require numbered steps.
   Instructional WI actions still count as steps.

4. If voltages/settings remain unchanged,
   carry forward previous values.

5. Prefer extracting imperfect but real steps
   instead of returning an empty list.

6. Include healthy condition checks,
   fault simulations,
   relay checks,
   LED checks,
   voltage change actions.

Return JSON only:

{{
  "test_steps": [ ... ]
}}

No markdown.
No explanation.
No commentary.
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

    # 🔴 HARD LIMIT pages for free tier
    # Keep broader spec context for WI-style manuals
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
        logger.info(
            f"{machine}: raw spec payload={data}"
        )

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


def _extract_procedure(genai, machine: str, variant: str, specs: Specs, pages: List[Page]) -> List[Dict]:
    if not pages:
        return []
    model = genai.GenerativeModel(VISION_MODEL)
    prompt = PROCEDURE_PROMPT.format(
        variant=variant,
        ref_voltage=specs.ref_voltage or "unknown",
        uv_range=specs.uv_range or "unknown",
        ov_range=specs.ov_range or "unknown",
        voltage_unit=specs.voltage_unit or "unknown",
    )
    # Adaptive procedure context selection
    # Avoid assuming useful steps are only at the beginning.
    if len(pages) <= 10:
        selected_pages = pages

    elif len(pages) <= 20:
        # keep continuity
        selected_pages = pages[:12]

    else:
        # Long WI-style manuals:
        # preserve contiguous context
        # instead of fragmented sampling
        selected_pages = pages[:16]

    # remove duplicates while preserving order
    seen = set()
    pages = []

    for p in selected_pages:
        if p.num not in seen:
            pages.append(p)
            seen.add(p.num)

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

    # Accept common response shapes safely
    steps = (
        data.get("test_steps")
        or data.get("steps")
        or data.get("procedure")
        or []
    )

    if not isinstance(steps, list):
        logger.warning(
            f"{variant}: unexpected procedure schema "
            f"keys={list(data.keys())}"
        )
        return []

    logger.info(
        f"{variant}: ALL extracted steps = {steps}"
    )

    return steps


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


def _normalize_step(raw: Dict) -> Optional[TestStep]:
    if not isinstance(raw, dict):
        return None
    name = raw.get("step_name")
    if not name or not isinstance(name, str):
        return None

    settings = raw.get("settings") or []

    # preserve all extracted settings
    # DIP switches frequently exceed 3 entries
    settings = (
        [str(x).strip() for x in settings if x]
        if isinstance(settings, list)
        else []
    )

    voltages_pn = raw.get("voltages_pn") or []
    voltages_pn = [str(x) for x in voltages_pn][:3] if isinstance(voltages_pn, list) else []

    leds = raw.get("leds") or []

    # preserve all extracted LEDs
    leds = (
        [str(x).strip() for x in leds if x]
        if isinstance(leds, list)
        else []
    )

    return TestStep(
        step_name=str(name).strip(),
        settings=settings,
        voltages_pn=voltages_pn,
        voltage_pp=raw.get("voltage_pp") or None,
        leds=leds,
        relay_status=raw.get("relay_status") or None,
        on_delay=raw.get("on_delay") or None,
        off_delay=raw.get("off_delay") or None,
        section_break=bool(raw.get("section_break")),
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
    variants = [
    v for v in variants
    if re.match(r"^[A-Z]{2,6}\d+[A-Z0-9_]*$", v)
]

    # When the block is the entire scope-fanned doc (62 pages), narrow to
    # variant-relevant procedure pages. Otherwise standard classify.
    # 🔴 Phase 5 Part 2: always variant-aware procedure mapping

    # 🔴 Phase 5 FIX: robust spec page selection
    spec_pages = extract_table_pages(block.pages)

    # keep only highest-confidence subset
    spec_pages = spec_pages[:8]

    if not spec_pages:
        # fallback using classifier (any variant)
        cls = _classify_pages_for_variant(block, variants[0])
        spec_pages = cls["spec_pages"]

    proc_pages_per_variant: Dict[str, List[Page]] = {}

    for v in variants:
        cls = _classify_pages_for_variant(block, v)

        proc_pages_per_variant[v] = cls["proc_pages"]

    logger.info(f"{block.machine}: spec_pages={len(spec_pages)} variants={len(variants)}")

    # 🔴 Phase 3: extract raw table grids (for future use)
    table_grids = extract_table_grids(spec_pages)
    variant_maps = extract_variant_mappings(table_grids)

    # ✅ DO NOT FILTER — keep full table context
    logger.info(f"{block.machine}: full table variants → {list(variant_maps.keys())}")

    logger.info(f"{block.machine}: mapped variants from tables → {list(variant_maps.keys())}")
    logger.info(f"{block.machine}: extracted {len(table_grids)} table grids")

    raw_specs = _extract_specs(genai, block.machine, variants, spec_pages)

    # 🔴 Phase 3: merge table data
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
        
        # 🔴 Phase 4: store raw vision specs for validation
        variant_raw = raw_specs.get(v_key, {}) if isinstance(raw_specs, dict) else {}
        proc_pages = proc_pages_per_variant.get(v, [])
        steps_raw = _extract_procedure(genai, block.machine, v, specs, proc_pages)
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

        # 🔴 attach raw specs
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