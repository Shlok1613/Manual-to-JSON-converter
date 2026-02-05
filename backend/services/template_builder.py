# backend/services/template_builder.py

import re
from typing import Dict, List

STEP_SECTIONS = [
    "PROCEDURE",
    "UNDER VOLTAGE",
    "OVER VOLTAGE",
    "ASYMMETRY",
    "HYSTERESIS",
    "SYSTEM NUTRAL FAIL VERIFICATION",
    "VIRTUAL NUTRAL FAIL VERIFICATION"
]

EXCLUDED_SECTIONS = [
    "ACCESSORIES REQUIRED",
    "CHECK LIST",
    "PARAMETERS",
    "ACCEPTABLE LIMITS"
]

ACTION_VERBS = (
    "TURN", "INSERT", "SET", "REDUCE", "INCREASE",
    "MAKE", "ENSURE", "RECOVER", "RESET",
    "KEEP", "VARY", "REMOVE", "STORE", "MARK"
)

def is_new_action(line: str) -> bool:
    upper = line.upper()
    return any(upper.startswith(v) for v in ACTION_VERBS)

def build_template_skeleton(block: Dict) -> Dict:
    lines = [ln.strip() for ln in block["text"].splitlines() if ln.strip()]

    # ---- Specifications (minimal, safe) ----
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

        # ---- Section detection ----
        if upper.endswith(":"):
            header = upper.replace(":", "")
            if header in STEP_SECTIONS:
                current_section = header
            elif header in EXCLUDED_SECTIONS:
                current_section = None
            continue

        # ---- Spec extraction (outside procedure sections only) ----
        if current_section is None:
            if "VAC" in line and "P-N" in line:
                specs["Voltage"] = line
            continue

        # ---- Step extraction ONLY inside valid sections ----
        if current_section in STEP_SECTIONS:
            match = re.match(r"^(\d+)\.\s*(.+)", line)
            if not match:
                continue

            content = match.group(2).strip()

            if is_new_action(content):
                if current_step:
                    merged_steps.append(current_step)

                current_step = {
                    "Action": content,
                    "Expected Behavior": "N/A",
                    "Relay Status": "N/A",
                    "LED Indicator": "N/A",
                    "Delay": "N/A",
                    "Condition Type": "N/A"
                }
            else:
                if current_step:
                    if current_step["Expected Behavior"] == "N/A":
                        current_step["Expected Behavior"] = content
                    else:
                        current_step["Expected Behavior"] += " " + content

    if current_step:
        merged_steps.append(current_step)

    return {
        "block_id": block["block_id"],
        "title": block["title"],
        "template_data": {
            "Specifications": specs,
            "TestSteps": merged_steps
        }
    }
