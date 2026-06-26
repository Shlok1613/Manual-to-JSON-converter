# services/validator.py
"""
Validation Layer — deterministic Python rules, NO AI.

Runs after vision extraction, before Excel writing. Flags physically
impossible or structurally invalid data. Flags accumulate in
specs.flags / step.flags. Data is never silently mutated — operator
sees both the raw value and the flag.

Rules:
  R1.  voltage_unit in {"P-P", "P-N"}
  R2.  ranges should look like ranges
  R3.  threshold_pct must match digit + "%"
  R4.  UV max < OV min  (UV must be lower than OV)
  R5.  LV cutoff < HV cutoff
  R6.  delays should mention sec/ms/min/instant
  R7.  cross-variant: same threshold_pct -> same range
  R8.  test_step has at least step_name + voltages_pn
"""
import re
import logging
from typing import Dict, List, Optional, Tuple

from .types import VariantData, Specs, TestStep

logger = logging.getLogger(__name__)


_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[A-Za-z]*\s*(?:to|TO|-|–|—|±)\s*(\d+(?:\.\d+)?)")


def _parse_range(s: Optional[str]) -> Optional[Tuple[float, float]]:
    if not s or not isinstance(s, str):
        return None
    m = _RANGE_RE.search(s)
    if not m:
        single = re.search(r"(\d+(?:\.\d+)?)", s)
        if single:
            n = float(single.group(1))
            return (n, n)
        return None
    a, b = float(m.group(1)), float(m.group(2))
    return (min(a, b), max(a, b))


def _validate_specs(specs: Specs, variant: str) -> List[str]:
    flags: List[str] = []

    if specs.voltage_unit and specs.voltage_unit not in ("P-P", "P-N"):
        flags.append(f"voltage_unit invalid: {specs.voltage_unit!r}")

    if not specs.voltage_unit:
        flags.append("missing voltage_unit")

    # Only flag missing voltage ranges when there are no procedure steps to compensate.
    # Procedure-rich documents (WI PDFs) encode voltage data inside steps, not spec tables.
    if not specs.uv_range and not specs.ov_range and not specs.lv_cutoff:
        flags.append("no voltage ranges extracted")

    for fname in ("uv_range", "ov_range", "asymmetry"):
        val = getattr(specs, fname)
        if val and isinstance(val, str) and not _RANGE_RE.search(val) and not re.search(r"\d", val):
            flags.append(f"{fname} not numeric: {val!r}")

    for fname in ("uv_threshold_pct", "ov_threshold_pct"):
        val = getattr(specs, fname)
        if val:
            if not re.match(
                r"^\d+(\.\d+)?%\s*(\(.+\))?$",
                val.strip(),
                re.IGNORECASE,
            ):
                flags.append(
                    f"{fname} not a percentage: '{val}'"
                )

    uv = _parse_range(specs.uv_range)
    ov = _parse_range(specs.ov_range)
    if uv and ov and uv[1] >= ov[0]:
        flags.append(f"UV max ({uv[1]}) >= OV min ({ov[0]}) — physically invalid")

    lv = _parse_range(specs.lv_cutoff)
    hv = _parse_range(specs.hv_cutoff)
    if lv and hv and lv[1] >= hv[0]:
        flags.append("LV cutoff >= HV cutoff — physically invalid")

    for fname in ("on_delay", "off_delay"):
        val = getattr(specs, fname)
        if val and isinstance(val, str):
            v_low = val.lower()
            has_unit = any(
                u in v_low
                for u in (
                    "sec",
                    "secs",
                    "second",
                    "seconds",
                    "ms",
                    "millisecond",
                    "min",
                    "minute",
                    "instant",
                    "continuous",
                )
            )

            # OCR collapsed units:
            # "10.5s"
            # "7s"
            # "2.5m"
            if not has_unit:
                has_unit = bool(
                    re.search(
                        r"\d+(?:\.\d+)?\s*[smh]\b",
                        v_low
                    )
                )
            has_dash = val.strip() in {"-", "—", "–"}
            if not has_unit and not has_dash and re.search(r"\d", val):
                flags.append(f"{fname} missing time unit: {val!r}")

    return flags


def _validate_step(step: TestStep) -> List[str]:
    flags: List[str] = []
    if not step.step_name or not step.step_name.strip():
        flags.append("missing step_name")
    if not step.voltages_pn or not any(re.search(r"\d", v) for v in step.voltages_pn):
        flags.append("missing valid voltages_pn")
    for v in step.voltages_pn:
        if isinstance(v, str) and not re.search(r"\d", v):
            flags.append(f"voltage_pn missing number: {v!r}")
            break
    return flags


def _cross_check_variants(variants: Dict[str, VariantData]) -> None:
    for field_pair in (("uv_threshold_pct", "uv_range"), ("ov_threshold_pct", "ov_range")):
        pct_field, rng_field = field_pair
        by_pct: Dict[str, List[Tuple[str, str]]] = {}
        for name, vd in variants.items():
            pct = getattr(vd.specs, pct_field)
            rng = getattr(vd.specs, rng_field)
            if pct and rng:
                by_pct.setdefault(pct, []).append((name, rng))
        for pct, entries in by_pct.items():
            if len(entries) < 2:
                continue
            unique_ranges = {r for _, r in entries}
            if len(unique_ranges) > 1:
                for name, _ in entries:
                    variants[name].specs.flags.append(
                        f"cross-check: variants sharing {pct} have differing {rng_field} — verify"
                    )


def validate_variants(variants: Dict[str, VariantData]) -> Dict[str, VariantData]:
    for name, vd in variants.items():
        spec_flags = _validate_specs(vd.specs, name)
        vd.specs.flags.extend(spec_flags)
        if spec_flags:
            logger.warning(f"  {name}: {len(spec_flags)} spec flag(s)")
            for f in spec_flags:
                logger.warning(f"    - {f}")
        if len(vd.test_steps) < 1:
            vd.specs.flags.append("too few steps — extraction unreliable")
        for i, step in enumerate(vd.test_steps):
            sf = _validate_step(step)
            step.flags.extend(sf)
            if sf:
                logger.warning(f"  {name} step {i+1}: {sf}")
    _cross_check_variants(variants)
    for vname, vdata in variants.items():
        # table vs vision consistency check
        mismatch_flags = compare_table_vs_vision(vdata)

        if mismatch_flags:
            logger.warning(f"  {vname}: {len(mismatch_flags)} table/vision mismatch(s)")
            for f in mismatch_flags:
                logger.warning(f"    - {f}")
    return variants

def compare_table_vs_vision(vdata):
    """
    Compare table-derived specs vs vision-derived specs.
    Logs mismatches without modifying data.
    """

    flags = []

    specs = vdata.specs
    raw = getattr(vdata, "raw_specs", None)

    if not raw:
        return flags

    # Compare selected critical fields
    fields = ["uv_range", "ov_range", "ref_voltage", "on_delay", "off_delay"]

    for f in fields:
        table_val = getattr(specs, f, None)
        vision_val = raw.get(f)

        if table_val and vision_val and table_val != vision_val:
            flags.append(f"{f} mismatch (table='{table_val}' vs vision='{vision_val}')")

    return flags