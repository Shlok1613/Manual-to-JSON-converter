# backend/services/condition_generator.py
"""
Test Condition Matrix Generator

Generates state-based test condition scenarios from extracted voltage specifications.
Each condition describes a test STATE (not an action), matching the template format:

- Column F: Test case name (e.g., "healthy condition", "UV faulty condition with delay")
- Column G: POT Setting (e.g., "UV = 85%")
- Column H: Voltage Setting (e.g., "RN:240, YN:240, BN:240")
- Column J: LED STATUS (e.g., "PWR (GREEN LED) : ON")
- Column K: relay status (e.g., "ON", "OFF in 4-6 sec")
- Column L: On delay
- Column M: off delay

Input: spec_parser output (voltage_parameters, timing_parameters, raw_extractions)
Output: List of test condition dicts ready for Excel template
"""

import re
import math
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def _parse_percentage(setting: str) -> Optional[float]:
    """Extract percentage value from setting string like '85.00%' or '110%'."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', str(setting))
    return float(m.group(1)) if m else None


def _parse_voltage_range(text: str) -> Optional[Tuple[float, float]]:
    """Extract min-max voltage from '347 to 357 VAC' or '347-357'."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)', str(text))
    if m:
        return float(m.group(1)), float(m.group(2))
    # Single value
    m = re.search(r'(\d+(?:\.\d+)?)\s*VAC', str(text), re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return v, v
    return None


def _parse_delay_range(text: str) -> Optional[Tuple[float, float]]:
    """Extract delay range from '4 to 6s' or '2.8 to 3.2'."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)', str(text))
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:sec|s)\b', str(text), re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return v, v
    return None


def _format_delay(d_min: float, d_max: float) -> str:
    """Format delay range as '4-6 sec'."""
    if d_min == d_max:
        return f"{d_min:g} sec"
    return f"{d_min:g}-{d_max:g} sec"


def _extract_best_voltage_range(param: Dict) -> Optional[Tuple[float, float]]:
    """Get the best voltage range from a voltage_parameter entry."""
    # Try variants first (prefer Variant_2 which is often the primary spec)
    variants = param.get("variants", {})
    for key in sorted(variants.keys()):
        result = _parse_voltage_range(variants[key])
        if result and result[0] > 50:  # Skip suspiciously low values
            return result
    # Fallback to setting
    result = _parse_voltage_range(param.get("setting", ""))
    if result:
        return result
    return None


def _extract_best_delay(timing: Dict) -> Optional[Tuple[float, float]]:
    """Get the best delay range from a timing_parameter entry."""
    # Try variants
    variants = timing.get("variants", {})
    for key in sorted(variants.keys()):
        result = _parse_delay_range(variants[key])
        if result and result[0] >= 0.5:  # At least 500ms
            return result
    # Fallback to raw
    result = _parse_delay_range(timing.get("setting", ""))
    if result:
        return result
    return None


def _find_delay_from_raw(specs: Dict) -> Tuple[float, float]:
    """Find the most common delay range from raw_extractions.delays."""
    delays = specs.get("raw_extractions", {}).get("delays", [])
    for d in delays:
        if d.get("type") == "range" and d.get("min", 0) >= 1:
            return d["min"], d["max"]
    for d in delays:
        if d.get("type") == "simple" and d.get("value", 0) >= 1:
            v = d["value"]
            return v, v
    return 5.0, 5.0  # Default


def generate_test_conditions(specs: Dict) -> List[Dict]:
    """
    Generate a test condition matrix from extracted specifications.
    
    Takes the output of spec_parser.parse_specifications() and generates
    state-based test conditions matching the template format.
    
    Returns list of condition dicts, each with keys:
        test_case, pot_setting, voltage_rn, voltage_yn, voltage_bn,
        led_status, relay_status, on_delay, off_delay
    """
    conditions = []
    
    vp = specs.get("voltage_parameters", {})
    tp = specs.get("timing_parameters", {})
    ref_v = specs.get("reference_voltage", {})
    
    # --- Determine reference voltage (P-N) ---
    ref_voltage_pp = ref_v.get("value", 415) if isinstance(ref_v, dict) else 415
    # P-N = P-P / sqrt(3)
    ref_voltage_pn = round(ref_voltage_pp / math.sqrt(3), 1)
    # Clamp to common values
    if 220 <= ref_voltage_pn <= 280:
        ref_voltage_pn = 240  # Standard 240V P-N
    elif 110 <= ref_voltage_pn <= 130:
        ref_voltage_pn = 120  # Standard 120V P-N
    
    # --- Extract UV parameters ---
    uv_param = vp.get("under_voltage", {})
    uv_pct = _parse_percentage(uv_param.get("setting", ""))
    uv_range = _extract_best_voltage_range(uv_param)
    
    # --- Extract OV parameters ---
    ov_param = vp.get("over_voltage", {})
    ov_pct = _parse_percentage(ov_param.get("setting", ""))
    ov_range = _extract_best_voltage_range(ov_param)
    # If OV range not found, try raw_extractions
    if not ov_range:
        raw_voltages = specs.get("raw_extractions", {}).get("voltages", [])
        for rv in raw_voltages:
            if rv.get("type") == "range" and rv.get("min", 0) > 400:
                ov_range = (rv["min"], rv["max"])
                break
    
    # --- Extract asymmetry parameters ---
    asy_param = vp.get("asymmetry", {})
    asy_range = _extract_best_voltage_range(asy_param)
    
    # --- Extract delays ---
    on_delay_param = tp.get("on_delay", {})
    off_delay_param = tp.get("off_delay", {})
    
    on_delay = _extract_best_delay(on_delay_param) or _find_delay_from_raw(specs)
    off_delay = _extract_best_delay(off_delay_param) or on_delay  # Same if not found
    
    on_delay_str = _format_delay(*on_delay)
    off_delay_str = _format_delay(*off_delay)
    
    # --- Extract hysteresis (typically ~3-5% or fixed voltage) ---
    hysteresis_v = round(ref_voltage_pp * 0.035, 1)  # Default 3.5% hysteresis
    
    # Check raw for specific hysteresis values
    raw_pct = specs.get("raw_extractions", {}).get("percentages", [])
    for p in raw_pct:
        if p.get("type") == "range":
            # Could be hysteresis range
            pass
    
    logger.info(f"Condition generation: ref={ref_voltage_pp}V PP ({ref_voltage_pn}V PN), "
                f"UV={uv_pct}% ({uv_range}), OV={ov_pct}% ({ov_range}), "
                f"ASY={asy_range}, on_delay={on_delay_str}, off_delay={off_delay_str}")
    
    # ================================================================
    # GENERATE CONDITIONS
    # ================================================================
    
    pot_uv = f"UV = {uv_pct}%" if uv_pct else "-"
    pot_ov = f"OV = {ov_pct}%" if ov_pct else "-"
    
    # --- 1. HEALTHY CONDITION ---
    conditions.append({
        "test_case": "healthy condition",
        "pot_settings": [
            pot_uv,
            pot_ov,
        ],
        "voltages": [
            f"RN : {ref_voltage_pn}",
            f"YN : {ref_voltage_pn}",
            f"BN : {ref_voltage_pn}",
        ],
        "led_rows": [
            "PWR (GREEN LED) : ON",
            "UV (RED LED) : OFF",
            "OV (RED LED) : OFF",
            "ASY (RED LED) : OFF",
        ],
        "relay_status": "ON",
        "on_delay": f"{on_delay_str}",
        "off_delay": "-",
    })
    
    # --- UV CONDITIONS (if UV data available) ---
    if uv_range:
        uv_fault_v = uv_range[0]  # Lower limit = fault trigger
        uv_healthy_v = uv_range[1]  # Upper limit = still healthy
        uv_hyst_no_recovery = round(uv_fault_v + hysteresis_v * 0.5, 1)
        uv_hyst_recovery = round(uv_fault_v + hysteresis_v * 1.5, 1)
        
        # 2. UV Healthy condition (at threshold, still OK)
        conditions.append({
            "test_case": "UV Healthy condition",
            "pot_settings": [pot_uv],
            "voltages": [f"RN : {uv_healthy_v}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "UV (RED LED) : OFF",
            ],
            "relay_status": "ON",
            "on_delay": "Continuous ON",
            "off_delay": "-",
        })
        
        # 3. UV Faulty condition with delay
        conditions.append({
            "test_case": "UV faulty condition with delay",
            "pot_settings": [pot_uv],
            "voltages": [f"RN : {uv_fault_v}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "UV (RED LED) : ON",
            ],
            "relay_status": f"OFF in {off_delay_str}",
            "on_delay": "-",
            "off_delay": f"{off_delay_str}",
        })
        
        # 4. UV Hysteresis not recovery
        conditions.append({
            "test_case": "UV hysteresis not recovery",
            "pot_settings": [pot_uv],
            "voltages": [f"RN : {uv_hyst_no_recovery}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "UV (RED LED) : ON",
            ],
            "relay_status": "Continuous OFF",
            "on_delay": "-",
            "off_delay": "Continuous OFF",
        })
        
        # 5. UV Hysteresis recovery
        conditions.append({
            "test_case": "UV hysteresis recovery",
            "pot_settings": [pot_uv],
            "voltages": [f"RN : {uv_hyst_recovery}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "UV (RED LED) : OFF",
            ],
            "relay_status": "ON",
            "on_delay": f"After {on_delay_str}",
            "off_delay": "-",
        })
    
    # --- OV CONDITIONS (if OV data available) ---
    if ov_range:
        ov_healthy_v = ov_range[0]  # Lower limit = still OK
        ov_fault_v = ov_range[1]   # Upper limit = fault trigger
        ov_hyst_no_recovery = round(ov_fault_v - hysteresis_v * 0.5, 1)
        ov_hyst_recovery = round(ov_fault_v - hysteresis_v * 1.5, 1)
        
        # 6. OV Healthy condition
        conditions.append({
            "test_case": "OV Healthy condition",
            "pot_settings": [pot_ov],
            "voltages": [f"RN : {ov_healthy_v}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "OV (RED LED) : OFF",
            ],
            "relay_status": "ON",
            "on_delay": "Continuous ON",
            "off_delay": "-",
        })
        
        # 7. OV Faulty condition with delay
        conditions.append({
            "test_case": "OV faulty condition with delay",
            "pot_settings": [pot_ov],
            "voltages": [f"RN : {ov_fault_v}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "OV (RED LED) : ON",
            ],
            "relay_status": f"OFF in {off_delay_str}",
            "on_delay": "-",
            "off_delay": f"{off_delay_str}",
        })
        
        # 8. OV Hysteresis not recovery
        conditions.append({
            "test_case": "OV hysteresis not recovery",
            "pot_settings": [pot_ov],
            "voltages": [f"RN : {ov_hyst_no_recovery}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "OV (RED LED) : ON",
            ],
            "relay_status": "Continuous OFF",
            "on_delay": "-",
            "off_delay": "Continuous OFF",
        })
        
        # 9. OV Hysteresis recovery
        conditions.append({
            "test_case": "OV hysteresis recovery",
            "pot_settings": [pot_ov],
            "voltages": [f"RN : {ov_hyst_recovery}"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "OV (RED LED) : OFF",
            ],
            "relay_status": "ON",
            "on_delay": f"After {on_delay_str}",
            "off_delay": "-",
        })
    
    # --- ASYMMETRY CONDITIONS (if data available) ---
    if asy_range:
        asy_healthy_v = asy_range[0]  # Below threshold = healthy
        asy_fault_v = asy_range[1]    # At threshold = fault
        
        # 10. Asymmetry Healthy
        conditions.append({
            "test_case": "Asymmetry Healthy condition",
            "pot_settings": ["-"],
            "voltages": [f"Phase diff < {asy_healthy_v} VAC"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "ASY (RED LED) : OFF",
            ],
            "relay_status": "ON",
            "on_delay": "Continuous ON",
            "off_delay": "-",
        })
        
        # 11. Asymmetry Faulty
        conditions.append({
            "test_case": "Asymmetry faulty condition",
            "pot_settings": ["-"],
            "voltages": [f"Phase diff {asy_healthy_v}-{asy_fault_v} VAC"],
            "led_rows": [
                "PWR (GREEN LED) : ON",
                "ASY (RED LED) : ON",
            ],
            "relay_status": f"OFF in {off_delay_str}",
            "on_delay": "-",
            "off_delay": f"{off_delay_str}",
        })
    
    # --- SUPPLY OFF CONDITION ---
    conditions.append({
        "test_case": "Supply OFF",
        "pot_settings": ["-"],
        "voltages": ["All phases : 0"],
        "led_rows": [
            "PWR (GREEN LED) : OFF",
            "All LEDs : OFF",
        ],
        "relay_status": "OFF",
        "on_delay": "-",
        "off_delay": "-",
    })
    
    logger.info(f"Generated {len(conditions)} test conditions")
    return conditions
