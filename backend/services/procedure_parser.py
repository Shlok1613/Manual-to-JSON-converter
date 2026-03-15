# backend/services/procedure_parser.py
"""
Procedure Parser
Extracts phase fail, phase reverse, and neutral fail conditions from
VERIFICATION procedure sections in PDF text.
"""
import re
from typing import List, Dict
from services.pattern_library import UniversalPatternLibrary as Patterns
import logging

logger = logging.getLogger(__name__)


def extract_procedure_conditions(text: str) -> Dict[str, List[Dict]]:
    """
    Extract ALL procedure-based test conditions from block text.

    Returns dict with keys: 'phase_fail', 'phase_reverse', 'neutral_fail'
    Each value is a list of condition dicts ready for the template.
    """
    return {
        'phase_fail': _extract_phase_fail(text),
        'phase_reverse': _extract_phase_reverse(text),
        'neutral_fail': _extract_neutral_fail(text),
    }


def _extract_phase_fail(text: str) -> List[Dict]:
    """Extract phase failure conditions from PHASE FAIL VERIFICATION sections."""
    conditions = []
    sections = Patterns.find_section_content(text, Patterns.PHASE_FAIL_PATTERNS)

    if not sections:
        return conditions

    for section in sections:
        steps = Patterns.STEP_PATTERN.findall(section)

        # Track detected phases for unique conditions
        phases_seen = set()
        has_recovery = False

        for step_num, step_text in steps:
            step_upper = step_text.upper()

            # Detect phase
            phase_match = Patterns.PHASE_DETECT.search(step_text)
            phase = phase_match.group(1).upper() if phase_match else None

            # Check relay state
            relay_match = Patterns.RELAY_PATTERN.search(step_text)

            # Is this a recovery step?
            is_recovery = any(w in step_upper for w in ['RECOVER', 'RESTORE', 'RECONNECT'])

            if is_recovery and not has_recovery:
                has_recovery = True
                conditions.append({
                    "test_case": "Phase fail recovery",
                    "pot_setting": "P1 = 7 %",
                    "voltage": "RN : 240, YN : 240, BN : 240",
                    "led_status": "PWR (GREEN LED) : ON",
                    "led_extra": ["All fault LEDs : OFF"],
                    "relay_status": "ON after delay",
                    "on_delay": "After ON delay",
                    "off_delay": "-",
                })
            elif phase and phase not in phases_seen:
                phases_seen.add(phase)
                # Determine LED indication
                led_info = []
                blink = Patterns.LED_BLINK_PATTERN.findall(step_text)
                if blink:
                    led_info = [f"{b.upper()} LED : BLINKING" for b in blink]
                else:
                    led_info = ["Fault indication : ON"]

                relay_state = "OFF"
                delay_text = "Instant OFF"
                if relay_match:
                    relay_state = relay_match.group(1).upper()
                    if relay_match.group(2):
                        delay_text = f"OFF after {relay_match.group(2)}"

                conditions.append({
                    "test_case": f"Phase fail ({phase}-phase)",
                    "pot_setting": "P1 = 7 %",
                    "voltage": f"{phase}N : 0 (phase lost)",
                    "led_status": "PWR (GREEN LED) : Blinking",
                    "led_extra": led_info,
                    "relay_status": f"{relay_state} after OFF delay",
                    "on_delay": "-",
                    "off_delay": delay_text,
                })

    logger.info(f"Extracted {len(conditions)} phase fail conditions")
    return conditions


def _extract_phase_reverse(text: str) -> List[Dict]:
    """Extract phase reversal conditions from PHASE REVERSE VERIFICATION sections."""
    conditions = []
    sections = Patterns.find_section_content(text, Patterns.PHASE_REVERSE_PATTERNS)

    if not sections:
        return conditions

    for section in sections:
        steps = Patterns.STEP_PATTERN.findall(section)
        has_reverse = False
        has_recovery = False

        for step_num, step_text in steps:
            step_upper = step_text.upper()
            is_recovery = any(w in step_upper for w in ['RECOVER', 'CORRECT', 'NORMAL'])

            # Check for "not applicable" or "not detected"
            not_applicable = 'NOT APPLICABLE' in step_upper
            not_detected = 'NOT DETECT' in step_upper or 'REMAINS ON' in step_upper

            if not_applicable:
                continue

            if is_recovery and not has_recovery:
                has_recovery = True
                conditions.append({
                    "test_case": "Phase reverse recovery",
                    "pot_setting": "P1 = 7 %",
                    "voltage": "RN : 240, YN : 240, BN : 240 (correct sequence)",
                    "led_status": "PWR (GREEN LED) : ON",
                    "led_extra": ["Phase reverse LED : OFF"],
                    "relay_status": "ON after ON delay",
                    "on_delay": "After ON delay",
                    "off_delay": "-",
                })
            elif 'REVERSE' in step_upper and not has_reverse:
                has_reverse = True
                # Detect which phases reversed
                phase_pairs = re.findall(r'([RYB])-([RYB])', step_text, re.IGNORECASE)
                pair_str = "-".join([f"{a.upper()}-{b.upper()}" for a, b in phase_pairs]) if phase_pairs else "R-Y"

                if not_detected:
                    conditions.append({
                        "test_case": f"Phase reverse ({pair_str}) - not detected",
                        "pot_setting": "P1 = 7 %",
                        "voltage": f"Phases reversed ({pair_str})",
                        "led_status": "PWR (GREEN LED) : ON",
                        "led_extra": [],
                        "relay_status": "ON (no change)",
                        "on_delay": "Continuous ON",
                        "off_delay": "-",
                    })
                else:
                    conditions.append({
                        "test_case": f"Phase reverse ({pair_str})",
                        "pot_setting": "P1 = 7 %",
                        "voltage": f"Phases reversed ({pair_str})",
                        "led_status": "Phase reverse indication : ON",
                        "led_extra": [],
                        "relay_status": "Instant OFF",
                        "on_delay": "-",
                        "off_delay": "Instant OFF",
                    })

    logger.info(f"Extracted {len(conditions)} phase reverse conditions")
    return conditions


def _extract_neutral_fail(text: str) -> List[Dict]:
    """Extract neutral fail conditions from NEUTRAL FAIL sections."""
    conditions = []
    sections = Patterns.find_section_content(text, Patterns.NEUTRAL_FAIL_PATTERNS)

    if not sections:
        return conditions

    # Track across ALL sections to prevent duplicates
    has_fault = False
    has_recovery = False
    has_virtual = False

    for section in sections:
        steps = Patterns.STEP_PATTERN.findall(section)

        for step_num, step_text in steps:
            step_upper = step_text.upper()
            is_recovery = any(w in step_upper for w in ['RECOVER', 'CLOSE', 'RECONNECT', 'RESTORE'])

            # Extract delay
            delay_ms = Patterns.DELAY_MS_PATTERN.search(step_text)
            delay_str = f"{delay_ms.group(1)} ms" if delay_ms else "500 ms"

            # Extract voltage range for virtual neutral
            v_range = Patterns.VOLTAGE_RANGE.search(step_text)
            v_str = f"{v_range.group(1)} to {v_range.group(2)} V" if v_range else ""

            # Is this virtual neutral?
            is_virtual = any(w in step_upper for w in ['VIRTUAL', 'RHEOSTAT', 'POTENTIOMETER'])

            if is_recovery and not has_recovery:
                has_recovery = True
                conditions.append({
                    "test_case": "Neutral fail recovery",
                    "pot_setting": "P1 = 7 %",
                    "voltage": "Neutral restored",
                    "led_status": "PWR (GREEN LED) : ON",
                    "led_extra": ["NF LED : OFF"],
                    "relay_status": "ON after delay",
                    "on_delay": "After ON delay",
                    "off_delay": "-",
                })
            elif is_virtual and not has_virtual:
                has_virtual = True
                conditions.append({
                    "test_case": "Virtual neutral fail",
                    "pot_setting": "P1 = 7 %",
                    "voltage": v_str if v_str else "8 to 14 V (virtual neutral)",
                    "led_status": "NF (RED LED) : ON",
                    "led_extra": [],
                    "relay_status": f"OFF in {delay_str}",
                    "on_delay": "-",
                    "off_delay": f"OFF in {delay_str}",
                })
            elif ('NEUTRAL' in step_upper and 'FAIL' in step_upper) and not has_fault:
                has_fault = True
                conditions.append({
                    "test_case": "System neutral fail",
                    "pot_setting": "P1 = 7 %",
                    "voltage": "Neutral open",
                    "led_status": "NF (RED LED) : ON",
                    "led_extra": [],
                    "relay_status": f"OFF in {delay_str}",
                    "on_delay": "-",
                    "off_delay": f"OFF in {delay_str}",
                })

    # If sections found but no structured steps, add generic conditions
    if sections and not conditions:
        conditions.append({
            "test_case": "Neutral fail condition",
            "pot_setting": "P1 = 7 %",
            "voltage": "Neutral disconnected",
            "led_status": "NF (RED LED) : ON",
            "led_extra": [],
            "relay_status": "OFF in 500 ms",
            "on_delay": "-",
            "off_delay": "OFF in 500 ms",
        })
        conditions.append({
            "test_case": "Neutral fail recovery",
            "pot_setting": "P1 = 7 %",
            "voltage": "Neutral restored",
            "led_status": "PWR (GREEN LED) : ON",
            "led_extra": ["NF LED : OFF"],
            "relay_status": "ON after delay",
            "on_delay": "After ON delay",
            "off_delay": "-",
        })

    logger.info(f"Extracted {len(conditions)} neutral fail conditions")
    return conditions
