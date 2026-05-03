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
MAX_IMAGES_PER_CALL = 12


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
    """For SCOPE-based docs, narrow procedure pages to those mentioning this variant."""
    spec_pages = []
    proc_pages_all = []
    spec_re = re.compile(
        r"TABLE\s*\d?\s*\(\s*PRODUCT\s*SETTINGS|ACCEPTABLE\s*LIMITS|REF\.\s*VOLTAGE",
        re.IGNORECASE,
    )
    proc_re = re.compile(
        r"PROCEDURE|FUNCTIONAL\s+TEST\s+PROCEDURE|DIP\s*S/W",
        re.IGNORECASE,
    )
    variant_re = re.compile(
        rf"{re.escape(variant)}|{variant.replace('_','')}|{variant[:5]}",
        re.IGNORECASE
    )

    for p in block.pages:
        if p.jpeg_bytes is None:
            continue
        if spec_re.search(p.ocr_text):
            spec_pages.append(p)
        if proc_re.search(p.ocr_text):
            proc_pages_all.append(p)

    proc_for_variant = [p for p in proc_pages_all if variant_re.search(p.ocr_text)]
    if len(proc_for_variant) < 4:
        proc_for_variant = proc_pages_all
    if not spec_pages:
        spec_pages = [p for p in block.pages if p.jpeg_bytes is not None][:8]

    return {"spec": spec_pages, "proc": proc_for_variant}


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


PROCEDURE_PROMPT = """You are converting a manufacturing test procedure into structured test step rows.

VARIANT: {variant}
KNOWN SPECS:
  ref_voltage:  {ref_voltage}
  uv_range:     {uv_range}
  ov_range:     {ov_range}
  voltage_unit: {voltage_unit}

Read the procedure pages. The procedure is a sequence of numbered steps,
sometimes grouped into lettered sections (A], B], C], D]) where each section
starts with a different DIP S/W configuration.

Output one TEST STEP per meaningful verification action. Each test step has
this exact shape:
{{
  "step_name":     short label (e.g. "healthy condition", "UV faulty condition with delay"),
  "settings":      array of up to 3 strings — pot/UV/OV/delay settings active for this step
                   e.g. ["UV = 8%", "OV = 22%", "DELAY = 3SEC"]
                   OR empty array if no settings to display,
  "voltages_pn":   array of exactly 3 strings — phase-to-neutral voltages
                   e.g. ["RN : 120", "YN : 120", "BN : 120"]
                   If a step changes only one phase, still report all three
                   using the carried-forward values for the other phases,
  "voltage_pp":    string|null — phase-to-phase voltage if the procedure mentions one,
  "leds":          array of 1 to 4 strings — LED status lines
                   e.g. ["PWR (GREEN LED) : ON", "UV (RED LED) : OFF",
                         "OV (RED LED) : OFF", "ASY (RED LED) : OFF"],
  "relay_status":  "ON"|"OFF"|"OFF in 2-4 sec"|"-"|null,
  "on_delay":      string|null e.g. "4-6 sec" / "Instant ON" / "Continuous ON",
  "off_delay":     string|null e.g. "2-4 SEC" / "-" / "Continuous OFF",
  "section_break": boolean — true ONLY when this step starts a new
                   DIP S/W configuration block, otherwise false
}}

RULES:
- Carry forward values from previous steps when the procedure doesn't
  re-state them (e.g. voltages stay 240 V P-N until the procedure changes
  them).
- DO NOT invent steps. Each step must correspond to an actual numbered
  verification action in the PDF.
- DO NOT skip the "healthy condition" step that opens each section.
- Set section_break=true on the FIRST step of each new DIP S/W
  configuration (typically labelled "DIP S/W setting" or new lettered section).

Return JSON: {{ "test_steps": [ ... ] }}

Return ONLY valid JSON. No markdown, no commentary."""


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

    for chunk in _chunk_pages(pages, size=10):
        parts = [prompt] + _build_image_parts(chunk)
        logger.info(f"  vision specs chunk: {len(parts)-1} images, variants={variants}")

        raw = _call_with_retry(model, parts, DEFAULT_TIMEOUT, f"{machine} specs")
        data = _parse_json(raw, f"{machine} specs")

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
    parts = [prompt] + _build_image_parts(pages)
    logger.info(f"  vision procedure: {variant}, {len(parts)-1} images")
    raw = _call_with_retry(model, parts, DEFAULT_TIMEOUT, f"{variant} proc")
    data = _parse_json(raw, f"{variant} proc")
    if not data:
        return []
    steps = data.get("test_steps") or []
    return steps if isinstance(steps, list) else []


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
    settings = [str(x) for x in settings if x][:3] if isinstance(settings, list) else []

    voltages_pn = raw.get("voltages_pn") or []
    voltages_pn = [str(x) for x in voltages_pn][:3] if isinstance(voltages_pn, list) else []

    leds = raw.get("leds") or []
    leds = [str(x) for x in leds if x][:4] if isinstance(leds, list) else []

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


def extract_machine_data(block: Block, sub_machines: Optional[List[str]] = None) -> Dict[str, VariantData]:
    """Vision-first extraction. Returns {variant_name: VariantData}."""
    genai = _get_client()
    if genai is None:
        logger.info(f"{block.machine}: Gemini unavailable")
        return {}

    variants = [v.upper() for v in (sub_machines or [block.machine])]

    # When the block is the entire scope-fanned doc (62 pages), narrow to
    # variant-relevant procedure pages. Otherwise standard classify.
    is_wide_block = (
        len(block.pages) > 10
        or "SCOPE" in block.text.upper()
    )
    if is_wide_block:
        # specs likely on early-numbered pages, common across all variants
        spec_pages: List[Page] = extract_table_pages(block.pages)
        proc_pages_per_variant: Dict[str, List[Page]] = {}
        for v in variants:
            cls = _classify_pages_for_variant(block, v)
            if not spec_pages:
                spec_pages = cls["spec"]
            proc_pages_per_variant[v] = cls["proc"]
    else:
        cls = _classify_pages(block)
        spec_pages = cls["spec"]
        proc_pages_per_variant = {v: cls["proc"] for v in variants}

    logger.info(f"{block.machine}: spec_pages={len(spec_pages)} variants={len(variants)}")

    # 🔴 Phase 3: extract raw table grids (for future use)
    table_grids = extract_table_grids(spec_pages)
    variant_maps = extract_variant_mappings(table_grids)

    # ✅ KEEP ONLY REQUESTED VARIANTS
    filtered_variant_maps = {}

    for v in variants:
        key = v.upper()
        if key in variant_maps:
            filtered_variant_maps[key] = variant_maps[key]

    variant_maps = filtered_variant_maps

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
                if v_key in k.replace(" ", "").upper():
                    spec_dict = val
                    break

        specs = _normalize_specs(spec_dict)
        proc_pages = proc_pages_per_variant.get(v, [])
        steps_raw = _extract_procedure(genai, block.machine, v, specs, proc_pages)
        steps = [s for s in (_normalize_step(r) for r in steps_raw) if s is not None]

        out[v] = VariantData(
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

    return out


def extraction_was_successful(vd: VariantData) -> bool:
    return vd.is_usable()