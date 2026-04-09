"""
Gemini LLM Fallback Service
Called only when regex extraction produces poor quality output.
Sends PDF text to Gemini 1.5 Flash and returns per-machine spec data
in the same block dict format the rest of the pipeline expects.
"""
import os
import json
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def extraction_quality_poor(processed_blocks: List[Dict]) -> bool:
    """
    Evaluate whether regex extraction produced poor quality output.
    
    Returns True (poor) if:
    - Multiple machines all have identical condition counts (SCOPE problem)
    - Any machine has 2 or fewer conditions (specs not found)
    - All machines have default spec values (nothing was extracted)
    
    Returns False (good) if:
    - No blocks at all (user input error — not an extraction failure)
    - Single machine with reasonable conditions
    """
    if not processed_blocks:
        return False  # Empty = user input error, not extraction failure

    counts = [b.get("num_test_conditions", 0) for b in processed_blocks]

    # SCOPE problem: multiple machines, all identical condition count
    all_identical = len(set(counts)) == 1 and len(processed_blocks) > 1

    # Extraction failure: any machine produced almost nothing
    too_few = any(c < 2 for c in counts)

    # Default values: spec extractor found nothing real, used defaults
    all_default = all(
        b.get("spec_data", {}).get("ref_pn") == 240.0 and
        not b.get("spec_data", {}).get("uv") and
        not b.get("spec_data", {}).get("ov")
        for b in processed_blocks
    )

    result = all_identical or too_few or all_default
    if result:
        logger.info(
            f"Poor extraction quality detected: "
            f"all_identical={all_identical}, too_few={too_few}, all_default={all_default}"
        )
    return result


def call_gemini(full_text: str, machine_names: Optional[List[str]] = None) -> List[Dict]:
    """
    Call Gemini 1.5 Flash to extract per-machine specs from PDF text.
    
    Returns list of block dicts in the same format as block_segmenter.py:
    [
        {
            "machine": "MAG03D0424",
            "header": "GEMINI: MAG03D0424",
            "text": ""   # empty — spec_data filled directly
            "spec_data": { ... }  # pre-populated from Gemini response
        }
    ]
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai not installed. Run: pip install google-generativeai")
        return []

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set in .env")
        return []

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    machine_hint = (
        f"Machines to extract (these names are confirmed present in the document): "
        f"{', '.join(machine_names)}"
        if machine_names
        else "Auto-detect all machine/product names present in the document."
    )

    prompt = f"""You are a manufacturing test specification parser.

{machine_hint}

Read the following manufacturing Work Instruction document and extract test specifications for each machine/product.

For each machine, extract EXACTLY these fields:
- uv: list of UV (Under Voltage) ranges as [[min, max], ...] in VAC. Empty list if not found.
- ov: list of OV (Over Voltage) ranges as [[min, max], ...] in VAC. Empty list if not found.
- ref_pn: reference phase-to-neutral voltage as a number (e.g. 240). Default 240 if not found.
- delay_on: ON delay as [min, max] seconds (e.g. [4, 6]). Default [4, 6] if not found.
- delay_off: OFF delay as [min, max] seconds (e.g. [4, 6]). Default [4, 6] if not found.
- asy_pct: asymmetry percentage range as [[min, max]] or empty list.
- phase_fail: true or false
- phase_rev: true or false
- neutral: true or false
- virtual_neutral: true or false
- lv: low voltage cutoff ranges as [[min, max]] in VAC or empty list.
- hv: high voltage cutoff ranges as [[min, max]] in VAC or empty list.

Return ONLY a valid JSON object. No explanation, no markdown, no code fences.
Format:
{{
  "MACHINE_NAME": {{
    "ref_pn": 240,
    "uv": [[220.8, 225.6]],
    "ov": [[264, 268.8]],
    "delay_on": [4, 6],
    "delay_off": [4, 6],
    "asy_pct": [[9, 11]],
    "phase_fail": true,
    "phase_rev": false,
    "neutral": false,
    "virtual_neutral": false,
    "lv": [],
    "hv": []
  }}
}}

DOCUMENT:
{full_text[:50000]}
"""

    try:
        logger.info("Calling Gemini 1.5 Flash for spec extraction...")
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Strip markdown fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        data = json.loads(raw)
        logger.info(f"Gemini returned specs for {len(data)} machines: {list(data.keys())}")

        # Convert to block dict format
        blocks = []
        for machine_name, spec_raw in data.items():
            # Normalize spec format to match universal_spec_extractor output
            spec = {
                "ref_pn": float(spec_raw.get("ref_pn", 240)),
                "uv": [tuple(v) for v in spec_raw.get("uv", [])],
                "ov": [tuple(v) for v in spec_raw.get("ov", [])],
                "asy_pct": [tuple(v) for v in spec_raw.get("asy_pct", [])],
                "asy_v": [tuple(v) for v in spec_raw.get("asy_v", [])],
                "delay_on": tuple(spec_raw.get("delay_on", [4, 6])),
                "delay_off": tuple(spec_raw.get("delay_off", [4, 6])),
                "phase_fail": bool(spec_raw.get("phase_fail", False)),
                "phase_rev": bool(spec_raw.get("phase_rev", False)),
                "neutral": bool(spec_raw.get("neutral", False)),
                "virtual_neutral": bool(spec_raw.get("virtual_neutral", False)),
                "lv": [tuple(v) for v in spec_raw.get("lv", [])],
                "hv": [tuple(v) for v in spec_raw.get("hv", [])],
            }
            blocks.append({
                "machine": machine_name.upper(),
                "header": f"GEMINI: {machine_name.upper()}",
                "text": "",          # text not needed — spec_data populated directly
                "spec_data": spec,
            })

        return blocks

    except json.JSONDecodeError as e:
        logger.error(f"Gemini returned invalid JSON: {e}\nRaw: {raw[:500]}")
        return []
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return []
