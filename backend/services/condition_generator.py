# backend/services/condition_generator.py
"""
Test Condition Generator - 100% Template Match
Generates test condition scenarios from voltage specifications.
Matches 1M_SPP_SM175_AUTO_FUNCTION_All_CatID.xlsx format exactly.

Output format per condition:
{
    "test_case": "healthy condition",
    "pot_setting": "P1 = 7 %, P2 = 0 SEC, P3 = 15 SEC",
    "voltage": "RN :0, YN :0, BN :0",
    "led_status": "PWR (GREEN LED) : ON, UV (RED LED) : OFF, ...",
    "relay_status": "ON",
    "on_delay": "Instant ON",
    "off_delay": "-"
}
"""

import re
import math
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# ─── SPEC PARSING HELPERS ────────────────────────────────────────────
# Bridge between spec_parser's nested output and flat values needed here

def _parse_percentage(text: str) -> Optional[float]:
    """Extract percentage from '85.00%' or '110%'."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', str(text))
    return float(m.group(1)) if m else None


def _parse_voltage_range(text: str) -> Optional[Tuple[float, float]]:
    """Extract min-max from '347 to 357 VAC' or '347-357'."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)', str(text))
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r'(\d+(?:\.\d+)?)\s*VAC', str(text), re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return v, v
    return None


def _parse_delay_range(text: str) -> Optional[Tuple[float, float]]:
    """Extract delay from '4 to 6s' or '2.8 to 3.2'."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)', str(text))
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:sec|s)\b', str(text), re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return v, v
    return None


def _best_voltage_range(param: Dict) -> Optional[Tuple[float, float]]:
    """Get best voltage range from a voltage_parameter entry.
    Prefers ranges with higher voltages (main spec over sub-variants)."""
    variants = param.get("variants", {})
    best = None
    for key in sorted(variants.keys()):
        result = _parse_voltage_range(variants[key])
        if result and result[0] > 50 and result[0] != result[1]:
            # Prefer higher voltage ranges (closer to main reference)
            if best is None or result[0] > best[0]:
                best = result
    if best:
        return best
    # Fallback: any variant
    for key in sorted(variants.keys()):
        result = _parse_voltage_range(variants[key])
        if result and result[0] > 50:
            return result
    return _parse_voltage_range(param.get("setting", ""))


def _best_delay(timing: Dict) -> Optional[Tuple[float, float]]:
    """Get best delay range from a timing_parameter entry."""
    variants = timing.get("variants", {})
    for key in sorted(variants.keys()):
        result = _parse_delay_range(variants[key])
        if result and result[0] >= 0.5:
            return result
    return _parse_delay_range(timing.get("setting", ""))


def _find_delay_from_raw(specs: Dict) -> Tuple[float, float]:
    """Find the most common delay from raw_extractions.delays."""
    delays = specs.get("raw_extractions", {}).get("delays", [])
    for d in delays:
        if d.get("type") == "range" and d.get("min", 0) >= 1:
            return d["min"], d["max"]
    for d in delays:
        if d.get("type") == "simple" and d.get("value", 0) >= 1:
            v = d["value"]
            return v, v
    return 4.0, 6.0  # Default


# ─── MAIN GENERATOR ──────────────────────────────────────────────────

def generate_test_conditions(specs: Dict) -> List[Dict]:
    """
    Generate test condition matrix from extracted specifications.
    100% matched to template format.

    Input: spec_parser output (nested dicts)
    Output: List of flat condition dicts ready for Excel
    """
    conditions = []

    vp = specs.get("voltage_parameters", {})
    tp = specs.get("timing_parameters", {})
    ref_v = specs.get("reference_voltage", {})

    # ── Reference voltage ──
    ref_voltage_pp = ref_v.get("value", 415) if isinstance(ref_v, dict) else 415
    ref_voltage_pn = round(ref_voltage_pp / math.sqrt(3), 1)
    # Clamp to standard values
    if 220 <= ref_voltage_pn <= 280:
        ref_voltage_pn = 240
    elif 110 <= ref_voltage_pn <= 130:
        ref_voltage_pn = 120

    # ── UV parameters ──
    uv_param = vp.get("under_voltage", {})
    uv_pct = _parse_percentage(uv_param.get("setting", ""))
    uv_range = _best_voltage_range(uv_param)

    # ── OV parameters ──
    ov_param = vp.get("over_voltage", {})
    ov_pct = _parse_percentage(ov_param.get("setting", ""))
    ov_range = _best_voltage_range(ov_param)
    # Fallback: search raw_extractions if OV is single value or missing
    if not ov_range or (ov_range and ov_range[0] == ov_range[1]):
        for rv in specs.get("raw_extractions", {}).get("voltages", []):
            if rv.get("type") == "range" and rv.get("min", 0) > 400:
                ov_range = (rv["min"], rv["max"])
                break

    # ── Asymmetry parameters ──
    asy_param = vp.get("asymmetry", {})
    asy_range = _best_voltage_range(asy_param)

    # ── Delays ──
    on_delay = _best_delay(tp.get("on_delay", {})) or _find_delay_from_raw(specs)
    off_delay = _best_delay(tp.get("off_delay", {})) or on_delay

    on_min, on_max = on_delay
    off_min, off_max = off_delay

    # ── Hysteresis (typically ~2-3% of ref voltage) ──
    hysteresis = round(ref_voltage_pp * 0.02)

    logger.info(
        f"Condition gen: ref={ref_voltage_pp}V PP ({ref_voltage_pn}V PN), "
        f"UV={uv_pct}% ({uv_range}), OV={ov_pct}% ({ov_range}), "
        f"ASY={asy_range}, on={on_min}-{on_max}s, off={off_min}-{off_max}s"
    )

    # ================================================================
    #  GENERATE CONDITIONS — 100% TEMPLATE MATCH
    # ================================================================

    # 1. HEALTHY CONDITION
    conditions.append({
        "test_case": "healthy condition",
        "pot_setting": "P1 = 7 %, P2 = 0 SEC, P3 = 15 SEC",
        "voltage": "RN :0, YN :0, BN :0",
        "led_status": "PWR (GREEN LED) : ON",
        "led_extra": [
            "UV (RED LED) : OFF",
            "OV (RED LED) : OFF",
            "ASY (RED LED) : OFF",
        ],
        "relay_status": "ON",
        "on_delay": "Instant ON",
        "off_delay": "-",
    })

    # ── UV CONDITIONS ──
    if uv_range:
        uv_min, uv_max = uv_range
        uv_hyst_no = round(uv_min + hysteresis * 0.5)
        uv_hyst_rec = round(uv_min + hysteresis * 1.5)

        # 2. UV Healthy condition
        conditions.append({
            "test_case": "UV Healthy condition",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {uv_max:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["UV (RED LED) : OFF"],
            "relay_status": "ON",
            "on_delay": "Continuous ON",
            "off_delay": "-",
        })

        # 3. UV faulty condition with delay
        conditions.append({
            "test_case": "UV faulty condition with delay",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {uv_min:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["UV (RED LED) : ON"],
            "relay_status": f"OFF in {off_min:g}-{off_max:g} sec",
            "on_delay": "-",
            "off_delay": f"OFF in {off_min:g}-{off_max:g} sec",
        })

        # 4. UV hysteresis not recovery
        conditions.append({
            "test_case": "UV hysteresis not recovery",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {uv_hyst_no:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["UV (RED LED) : ON"],
            "relay_status": "Continuous OFF",
            "on_delay": "-",
            "off_delay": "Continuous OFF",
        })

        # 5. UV hysteresis recovery
        conditions.append({
            "test_case": "UV hysteresis recovery",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {uv_hyst_rec:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["UV (RED LED) : OFF"],
            "relay_status": "ON",
            "on_delay": f"After {on_min:g}-{on_max:g} sec",
            "off_delay": "-",
        })

    # ── OV CONDITIONS ──
    if ov_range:
        ov_min_v, ov_max_v = ov_range
        ov_hyst_no = round(ov_max_v - hysteresis * 0.5)
        ov_hyst_rec = round(ov_max_v - hysteresis * 1.5)

        # 6. OV Healthy condition
        conditions.append({
            "test_case": "OV Healthy condition",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {ov_min_v:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["OV (RED LED) : OFF"],
            "relay_status": "ON",
            "on_delay": "Continuous ON",
            "off_delay": "-",
        })

        # 7. OV faulty condition with delay
        conditions.append({
            "test_case": "OV faulty condition with delay",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {ov_max_v:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["OV (RED LED) : ON"],
            "relay_status": f"OFF in {off_min:g}-{off_max:g} sec",
            "on_delay": "-",
            "off_delay": f"OFF in {off_min:g}-{off_max:g} sec",
        })

        # 8. OV hysteresis not recovery
        conditions.append({
            "test_case": "OV hysteresis not recovery",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {ov_hyst_no:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["OV (RED LED) : ON"],
            "relay_status": "Continuous OFF",
            "on_delay": "-",
            "off_delay": "Continuous OFF",
        })

        # 9. OV hysteresis recovery
        conditions.append({
            "test_case": "OV hysteresis recovery",
            "pot_setting": "P1 = 7 %",
            "voltage": f"RN : {ov_hyst_rec:g}",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["OV (RED LED) : OFF"],
            "relay_status": "ON",
            "on_delay": f"After {on_min:g}-{on_max:g} sec",
            "off_delay": "-",
        })

    # ── ASYMMETRY CONDITIONS ──
    if asy_range:
        asy_min, asy_max = asy_range

        # 10. Asymmetry healthy
        conditions.append({
            "test_case": "Asymmetry Healthy condition",
            "pot_setting": "P1 = 7 %",
            "voltage": f"Phase diff < {asy_min:g} VAC",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["ASY (RED LED) : OFF"],
            "relay_status": "ON",
            "on_delay": "Continuous ON",
            "off_delay": "-",
        })

        # 11. Asymmetry faulty
        conditions.append({
            "test_case": "Asymmetry faulty condition",
            "pot_setting": "P1 = 7 %",
            "voltage": f"Phase diff {asy_min:g}-{asy_max:g} VAC",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["ASY (RED LED) : ON"],
            "relay_status": f"OFF in {off_min:g}-{off_max:g} sec",
            "on_delay": "-",
            "off_delay": f"OFF in {off_min:g}-{off_max:g} sec",
        })

    # NOTE: Supply OFF is added by the comprehensive wrapper, not here
    # when called standalone, add it here as fallback
    logger.info(f"Generated {len(conditions)} voltage-based conditions")
    return conditions


def generate_comprehensive_conditions(specs: Dict, block_text: str = "") -> List[Dict]:
    """
    Generate test conditions for any machine block.
    Uses universal_spec_extractor — handles all PDF formats automatically.
    Falls back to legacy spec_parser path if block_text not available.
    """
    if block_text:
        try:
            from services.universal_spec_extractor import extract_and_generate
            conditions = extract_and_generate(block_text)
            logger.info(f"Universal extractor: {len(conditions)} conditions")
            return conditions
        except Exception as e:
            logger.warning(f"Universal extractor failed: {e}, using legacy fallback")

    # Fallback: no block text — use existing spec_parser output
    logger.warning("No block_text — using spec_parser fallback")
    return generate_test_conditions(specs)

