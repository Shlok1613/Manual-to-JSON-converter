import re
from .types import VariantData

def _find_voltage_ranges(text: str):
    matches = re.findall(r"(\d{3})\s*to\s*(\d{3})\s*VAC", text, re.IGNORECASE)
    return matches

def _find_ref_voltage(text: str):
    m = re.search(
        r"REF\.?\s*VOLTAGE\s+(\d{3})\s*VAC",
        text,
        re.IGNORECASE
    )
    return m.group(1) if m else None


def _find_delay(text: str):
    m = re.search(
        r"(\d+\.?\d*\s*(?:to|-)\s*\d+\.?\d*\s*s|\d+\.?\d*\s*s|instant|continuous)",
        text,
        re.IGNORECASE
    )

    if not m:
        return None

    val = m.group(1).strip().lower()

    # normalize unit
    if val.endswith("s"):
        val = val.replace("s", " sec")
    elif "sec" not in val and val not in ["instant", "continuous"]:
        val = val + " sec"

    return val


def _normalize_voltages(step):
    # Ensure exactly 3 phases
    if len(step.voltages_pn) == 1:
        v = step.voltages_pn[0]
        step.voltages_pn = [v, v, v]
    elif len(step.voltages_pn) == 2:
        step.voltages_pn.append(step.voltages_pn[-1])


def _normalize_leds(step):
    expected = ["PWR", "UV", "OV", "ASY"]
    existing = step.leds or []

    fixed = []
    for e in expected:
        found = next((l for l in existing if e in l.upper()), None)
        fixed.append(found if found else f"{e}: UNKNOWN")

    step.leds = fixed


def enrich_variant(vd: VariantData, block_text: str) -> VariantData:

    # -------- SPECS PATCH --------
    if not vd.specs.ref_voltage:
        rv = _find_ref_voltage(block_text)
        if rv:
            vd.specs.ref_voltage = rv

    if not vd.specs.on_delay:
        d = _find_delay(block_text)
        if d:
            vd.specs.on_delay = d

    # -------- UV / OV FALLBACK --------
    if not vd.specs.uv_range or not vd.specs.ov_range:
        ranges = _find_voltage_ranges(block_text)

        if ranges:
            # First range → UV
            if not vd.specs.uv_range and len(ranges) >= 1:
                vd.specs.uv_range = f"{ranges[0][0]}-{ranges[0][1]} VAC"

            # Second range → OV
            if not vd.specs.ov_range and len(ranges) >= 2:
                vd.specs.ov_range = f"{ranges[1][0]}-{ranges[1][1]} VAC"

    # -------- STEPS NORMALIZATION --------
    for step in vd.test_steps:
        if not step.on_delay:
            d = _find_delay(block_text)
            if d:
                step.on_delay = d

    # -------- DIP SWITCH (FINAL BUILD — AFTER ALL EXTRACTION) --------
    dip = []

    if vd.specs.uv_range:
        dip.append(f"UV: {vd.specs.uv_range}")

    if vd.specs.ov_range:
        dip.append(f"OV: {vd.specs.ov_range}")

    if vd.specs.on_delay:
        dip.append(f"ON_DELAY: {vd.specs.on_delay}")

    if not vd.specs.dip_switches:
        vd.specs.dip_switches = dip

    return vd