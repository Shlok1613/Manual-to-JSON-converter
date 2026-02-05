from __future__ import annotations

import re
from typing import Dict, List

STEP_PATTERN = re.compile(r"^\s*(\d+)\.\s+(.+)")
LED_ON = re.compile(r"([A-Z]{2,})\s+(?:LED\s+)?(?:turns?|glows?)\s+ON", re.IGNORECASE)
LED_OFF = re.compile(r"([A-Z]{2,})\s+(?:LED\s+)?(?:turns?)\s+OFF", re.IGNORECASE)
DELAY_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:sec|s)", re.IGNORECASE)
VOLTAGE_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:VAC|V)", re.IGNORECASE)


def _expected_from_action(action: str) -> str:
    if "ensure" in action.lower() or "verify" in action.lower():
        return action
    if "till" in action.lower() or "until" in action.lower():
        return action.split("till")[-1].strip().capitalize()
    return ""


def extract_steps(block_text: str) -> List[Dict[str, object]]:
    """Stage 5: parse numbered steps and infer key fields."""
    steps: List[Dict[str, object]] = []
    current_section = ""

    for raw in block_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.upper().endswith("VERIFICATION:"):
            current_section = line.rstrip(":")
            continue

        mm = STEP_PATTERN.match(line)
        if not mm:
            continue

        step_number = int(mm.group(1))
        action = mm.group(2).strip()
        led = ""
        if on := LED_ON.search(action):
            led = f"{on.group(1).upper()} ON"
        elif off := LED_OFF.search(action):
            led = f"{off.group(1).upper()} OFF"

        relay = ""
        if "relay" in action.lower() and "off" in action.lower():
            relay = "OFF"
        elif "relay" in action.lower() and "on" in action.lower():
            relay = "ON"

        delay = ""
        if dr := DELAY_RANGE.search(action):
            delay = f"{dr.group(1)}-{dr.group(2)}s"
        elif ds := re.search(r"(\d+(?:\.\d+)?)\s*(?:sec|s|ms|min)", action, re.IGNORECASE):
            delay = ds.group(0)

        voltage = ""
        if vr := VOLTAGE_RANGE.search(action):
            voltage = f"{vr.group(1)}-{vr.group(2)}V"
        elif vv := re.search(r"(\d+(?:\.\d+)?)\s*(?:VAC|V)", action, re.IGNORECASE):
            voltage = f"{vv.group(1)}V"

        steps.append(
            {
                "step_number": step_number,
                "section": current_section,
                "action": action,
                "expected_behavior": _expected_from_action(action),
                "relay": relay,
                "led": led,
                "delay": delay,
                "voltage": voltage,
            }
        )

    return steps
