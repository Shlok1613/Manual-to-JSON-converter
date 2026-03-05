# backend/services/template_builder.py
"""
Test Procedure Extraction Service
Extracts numbered test steps from PROCEDURE sections of machine blocks.

Output structure per step:
{
    "Action": "Reduce R-Phase voltage till UV LED glows ON",
    "Expected Behavior": "Relay turns OFF after specified off delay time",
    "Relay Status": "OFF",
    "LED Indicator": "UV LED: ON",
    "Delay": "4-6 sec",
    "Condition Type": "Under Voltage"
}
"""

import re
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

# Sections that contain numbered test steps
STEP_SECTIONS = [
    "PROCEDURE",
    "UNDER VOLTAGE",
    "OVER VOLTAGE",
    "ASYMMETRY",
    "HYSTERESIS",
    "SYSTEM NUTRAL FAIL VERIFICATION",
    "VIRTUAL NUTRAL FAIL VERIFICATION",
    "SYSTEM NEUTRAL FAIL VERIFICATION",
    "VIRTUAL NEUTRAL FAIL VERIFICATION",
    "PHASE REVERSAL",
    "NEUTRAL FAIL",
    "CALIBRATION",
]

# Sections to skip entirely (reference data, not steps)
EXCLUDED_SECTIONS = [
    "ACCESSORIES REQUIRED",
    "CHECK LIST",
    "PARAMETERS",
    "ACCEPTABLE LIMITS",
    "NOTE",
    "RESPONSIBILITY",
    "CRITICALITY",
]

# Verbs that start a NEW action step (expanded list for manufacturing)
ACTION_VERBS = (
    "TURN", "INSERT", "SET", "REDUCE", "INCREASE",
    "MAKE", "ENSURE", "RECOVER", "RESET",
    "KEEP", "VARY", "REMOVE", "STORE", "MARK",
    "CONNECT", "APPLY", "ADJUST", "DISCONNECT", "MEASURE",
    "SWITCH", "WAIT", "CHECK", "VERIFY", "OBSERVE",
    "RECORD", "NOTE", "OPEN", "CLOSE", "PRESS",
    "SELECT", "ROTATE", "PLACE", "SUPPLY", "GIVE",
)

# --- Enrichment regex patterns ---
LED_PATTERN = re.compile(
    r"""(?:'|")?(\w+)(?:'|")?\s+(?:LED\s+)?(?:on\s+product\s+)?(?:glows?|turns?|is)\s+(ON|OFF)""",
    re.IGNORECASE
)

RELAY_PATTERN = re.compile(
    r"relay\s+(?:turns?|is)\s+(ON|OFF)",
    re.IGNORECASE
)

DELAY_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:sec|s)\b",
    re.IGNORECASE
)

DELAY_SIMPLE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:sec|s)\b",
    re.IGNORECASE
)

# Condition type detection
CONDITION_PATTERNS = {
    "Under Voltage": re.compile(r"\bunder\s*voltage|UV\b", re.IGNORECASE),
    "Over Voltage": re.compile(r"\bover\s*voltage|OV\b", re.IGNORECASE),
    "Asymmetry": re.compile(r"\basym|ASY\b", re.IGNORECASE),
    "Hysteresis": re.compile(r"\bhyst", re.IGNORECASE),
    "Phase Reversal": re.compile(r"\bphase\s*rev|REV\b", re.IGNORECASE),
    "Neutral Fail": re.compile(r"\bneutral\s*fail|NF\b", re.IGNORECASE),
}


def is_new_action(line: str) -> bool:
    """Check if a line starts with an action verb (new step)."""
    upper = line.upper().lstrip()
    return any(upper.startswith(v) for v in ACTION_VERBS)


def enrich_step(step: Dict, current_section: str) -> Dict:
    """
    Auto-enrich a step with LED, relay, delay, and condition type
    by parsing the Action and Expected Behavior text.
    """
    combined_text = f"{step['Action']} {step['Expected Behavior']}"

    # --- LED Indicator ---
    led_matches = LED_PATTERN.findall(combined_text)
    if led_matches:
        led_parts = []
        for name, state in led_matches:
            name = name.upper()
            # Skip generic words that aren't LED names
            if name in ("RELAY", "PRODUCT", "DEVICE", "THE", "THAT", "IT"):
                continue
            led_parts.append(f"{name} LED: {state.upper()}")
        if led_parts:
            step["LED Indicator"] = ", ".join(led_parts)

    # --- Relay Status ---
    relay_match = RELAY_PATTERN.search(combined_text)
    if relay_match:
        step["Relay Status"] = relay_match.group(1).upper()

    # --- Delay ---
    delay_range = DELAY_PATTERN.search(combined_text)
    if delay_range:
        step["Delay"] = f"{delay_range.group(1)}-{delay_range.group(2)} sec"
    else:
        delay_simple = DELAY_SIMPLE.search(combined_text)
        if delay_simple:
            step["Delay"] = f"{delay_simple.group(1)} sec"

    # --- Condition Type (from section header or step text) ---
    if current_section:
        for cond_name, pattern in CONDITION_PATTERNS.items():
            if pattern.search(current_section):
                step["Condition Type"] = cond_name
                break

    # Fallback: check the step text itself
    if step["Condition Type"] == "N/A":
        for cond_name, pattern in CONDITION_PATTERNS.items():
            if pattern.search(combined_text):
                step["Condition Type"] = cond_name
                break

    return step


def build_template_skeleton(block: Dict) -> Dict:
    """
    Extract test procedure steps from a machine block.

    Args:
        block: Dict with keys "machine", "header", "text"
               (from block_segmenter output)

    Returns:
        Dict with:
        {
            "machine": "SPPR",
            "header": "Neutral Open SPPR",
            "template_data": {
                "Specifications": {...},
                "TestSteps": [
                    {"Action": "...", "Expected Behavior": "...", ...}
                ]
            }
        }
    """
    lines = [ln.strip() for ln in block["text"].splitlines() if ln.strip()]

    # ---- Specifications (minimal, extracted from non-procedure text) ----
    specs = {
        "Voltage": "N/A",
        "Under Voltage": "N/A",
        "Over Voltage": "N/A",
        "ON Delay": "N/A",
        "OFF Delay": "N/A",
        "Reference Voltage": "N/A"
    }

    current_section = None
    merged_steps: List[Dict] = []
    current_step = None

    for line in lines:
        upper = line.upper()

        # ---- Section detection (lines ending with ':') ----
        # Also handle "PROCEDURE:" or "UNDER VOLTAGE:" etc.
        stripped_upper = upper.rstrip()
        if stripped_upper.endswith(":"):
            header = stripped_upper.rstrip(":").strip()
            # Check if this is a test step section
            matched_section = False
            for section in STEP_SECTIONS:
                if section in header:
                    current_section = header
                    matched_section = True
                    break
            if not matched_section:
                for excluded in EXCLUDED_SECTIONS:
                    if excluded in header:
                        current_section = None
                        break
            continue

        # ---- Spec extraction (outside procedure sections only) ----
        if current_section is None:
            if "VAC" in line and "P-N" in line:
                specs["Voltage"] = line
            continue

        # ---- Step extraction ONLY inside valid sections ----
        # Match numbered lines: "8. Reduce the R-Phase voltage..."
        match = re.match(r"^(\d+)\.\s*(.+)", line)
        if not match:
            # Non-numbered continuation line — append to current step's expected behavior
            if current_step and line:
                if current_step["Expected Behavior"] == "N/A":
                    current_step["Expected Behavior"] = line
                else:
                    current_step["Expected Behavior"] += " " + line
            continue

        content = match.group(2).strip()

        if is_new_action(content):
            # Save previous step
            if current_step:
                current_step = enrich_step(current_step, current_section)
                merged_steps.append(current_step)

            # Start new step
            current_step = {
                "Action": content,
                "Expected Behavior": "N/A",
                "Relay Status": "N/A",
                "LED Indicator": "N/A",
                "Delay": "N/A",
                "Condition Type": "N/A"
            }
        else:
            # Non-action numbered line → expected behavior of current step
            if current_step:
                if current_step["Expected Behavior"] == "N/A":
                    current_step["Expected Behavior"] = content
                else:
                    current_step["Expected Behavior"] += " " + content
            else:
                # First line isn't an action verb — treat as standalone step
                current_step = {
                    "Action": content,
                    "Expected Behavior": "N/A",
                    "Relay Status": "N/A",
                    "LED Indicator": "N/A",
                    "Delay": "N/A",
                    "Condition Type": "N/A"
                }

    # Don't forget the last step
    if current_step:
        current_step = enrich_step(current_step, current_section)
        merged_steps.append(current_step)

    machine_name = block.get("machine", "UNKNOWN")
    header_text = block.get("header", "")

    logger.info(f"{machine_name}: Extracted {len(merged_steps)} test steps")

    return {
        "machine": machine_name,
        "header": header_text,
        "template_data": {
            "Specifications": specs,
            "TestSteps": merged_steps
        }
    }
