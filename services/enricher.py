import re
from .types import VariantData

def _find_voltage_ranges(text: str):
    matches = re.findall(
        r"(\d{3})\s*(?:to|-)\s*(\d{3})\s*VAC",
        text,
        re.IGNORECASE
    )

    cleaned = []

    for lo, hi in matches:
        lo_i = int(lo)
        hi_i = int(hi)

        # reject obvious percentages/settings
        if lo_i <= 50 and hi_i <= 50:
            continue

        cleaned.append((lo, hi))

    return cleaned

    
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


def enrich_variant(vd: VariantData, block_text: str) -> VariantData:

    # -------- SPECS PATCH --------
    if not vd.specs.ref_voltage:
        rv = _find_ref_voltage(block_text)
        if rv:
            vd.specs.ref_voltage = rv

    if not vd.specs.on_delay and vd.raw_specs:
        d = _find_delay(block_text)
        if d:
            vd.specs.on_delay = d

    # -------- UV / OV FALLBACK --------
    if (
        not vd.specs.uv_range
        and not vd.specs.ov_range
        and vd.raw_specs
    ):
        ranges = _find_voltage_ranges(block_text)

        if len(ranges) >= 2:
            vd.specs.uv_range = f"{ranges[0][0]}-{ranges[0][1]} VAC"
            vd.specs.ov_range = f"{ranges[1][0]}-{ranges[1][1]} VAC"

    # -------- STEPS NORMALIZATION --------
    # Only apply delay enrichment from block text if the block is small/targeted.
    # For SCOPE documents, block_text is the entire 62-page combined text —
    # _find_delay() would grab a random delay from an unrelated section.
    for step in vd.test_steps:
        if not step.on_delay and len(block_text) < 8000:
            d = _find_delay(block_text)
            if d:
                step.on_delay = d

    # DO NOT fabricate DIP switches
    pass

    return vd