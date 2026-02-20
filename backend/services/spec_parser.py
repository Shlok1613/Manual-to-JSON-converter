"""
Specification Parser Service
Extracts structured specifications from text using regex patterns.

Extracts:
- Voltages (347 VAC, 240V, 415 VAC, etc.)
- Voltage ranges (347 to 357 VAC)
- Percentages (85%, 110%, etc.)
- Delays (5s, 4 to 6s, 500ms, etc.)
- LED states (ON, OFF, Blinking)
- Relay states (ON, OFF)
"""
import re
from typing import Dict, List, Optional, Union
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# REGEX PATTERNS
# ============================================================================

# Voltage patterns
VOLTAGE_SIMPLE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:VAC|V)\b',
    re.IGNORECASE
)

VOLTAGE_RANGE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:to|-|–|—)\s*(\d+(?:\.\d+)?)\s*(?:VAC|V)\b',
    re.IGNORECASE
)

VOLTAGE_WITH_TOLERANCE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:VAC|V)\s*\(\s*[+\-±]\s*(\d+(?:\.\d+)?)\s*(?:VAC|V)?\s*\)',
    re.IGNORECASE
)

# Percentage patterns
PERCENTAGE_SIMPLE = re.compile(
    r'(\d+(?:\.\d+)?)\s*%',
    re.IGNORECASE
)

PERCENTAGE_RANGE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*%',
    re.IGNORECASE
)

# Delay/timing patterns
DELAY_SIMPLE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:sec|second|s)\b',
    re.IGNORECASE
)

DELAY_MS = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:ms|millisec|millisecond)\b',
    re.IGNORECASE
)

DELAY_MIN = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:min|minute)\b',
    re.IGNORECASE
)

DELAY_RANGE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:sec|second|s)\b',
    re.IGNORECASE
)

# LED state patterns (IMPROVED - handles quotes)
LED_ON = re.compile(
    r'["\']?([A-Z]{2,}|Green|Red|Yellow|Blue|UV|OV|ASY|REV)["\']?\s+(?:LED\s+)?(?:turns?|glows?|is)\s+ON\b',
    re.IGNORECASE
)

LED_OFF = re.compile(
    r'["\']?([A-Z]{2,}|Green|Red|Yellow|Blue|UV|OV|ASY|REV)["\']?\s+(?:LED\s+)?(?:(?:on\s+product\s+)?turns?|is)\s+OFF\b',
    re.IGNORECASE
)

LED_BLINK = re.compile(
    r'["\']?([A-Z]{2,}|Green|Red|Yellow|Blue|UV|OV|ASY|REV)["\']?\s+(?:LED\s+)?(?:blink|flash|flashing)',
    re.IGNORECASE
)

# Relay state patterns
RELAY_ON = re.compile(
    r'relay\s+(?:turns?|is)\s+ON\b',
    re.IGNORECASE
)

RELAY_OFF = re.compile(
    r'relay\s+(?:turns?|is)\s+OFF\b',
    re.IGNORECASE
)


# ============================================================================
# EXTRACTION FUNCTIONS
# ============================================================================

def extract_voltages(text: str) -> List[Dict[str, Union[str, float]]]:
    """
    Extract all voltage values from text.
    
    Handles:
    - Simple: "240 VAC", "415V"
    - Range: "347 to 357 VAC"
    - Tolerance: "240V (±10V)"
    
    Returns:
        List of voltage dicts:
        [
            {"type": "simple", "value": 240.0, "unit": "VAC", "text": "240 VAC"},
            {"type": "range", "min": 347.0, "max": 357.0, "unit": "VAC", "text": "347 to 357 VAC"},
        ]
    """
    voltages = []
    
    # Extract ranges first (more specific)
    for match in VOLTAGE_RANGE.finditer(text):
        voltages.append({
            "type": "range",
            "min": float(match.group(1)),
            "max": float(match.group(2)),
            "unit": "VAC",
            "text": match.group(0)
        })
    
    # Extract simple voltages (skip if already in a range)
    range_texts = [v["text"] for v in voltages]
    for match in VOLTAGE_SIMPLE.finditer(text):
        if not any(match.group(0) in rt for rt in range_texts):
            voltages.append({
                "type": "simple",
                "value": float(match.group(1)),
                "unit": "VAC",
                "text": match.group(0)
            })
    
    # Extract tolerance format
    for match in VOLTAGE_WITH_TOLERANCE.finditer(text):
        base = float(match.group(1))
        tolerance = float(match.group(2))
        voltages.append({
            "type": "tolerance",
            "value": base,
            "tolerance": tolerance,
            "min": base - tolerance,
            "max": base + tolerance,
            "unit": "VAC",
            "text": match.group(0)
        })
    
    logger.info(f"Extracted {len(voltages)} voltage values")
    return voltages


def extract_percentages(text: str) -> List[Dict[str, Union[str, float]]]:
    """
    Extract percentage values from text.
    
    Handles:
    - Simple: "85%", "110.00%"
    - Range: "9 to 11%"
    
    Returns:
        List of percentage dicts
    """
    percentages = []
    
    # Extract ranges first
    for match in PERCENTAGE_RANGE.finditer(text):
        percentages.append({
            "type": "range",
            "min": float(match.group(1)),
            "max": float(match.group(2)),
            "text": match.group(0)
        })
    
    # Extract simple percentages
    range_texts = [p["text"] for p in percentages]
    for match in PERCENTAGE_SIMPLE.finditer(text):
        if not any(match.group(0) in rt for rt in range_texts):
            percentages.append({
                "type": "simple",
                "value": float(match.group(1)),
                "text": match.group(0)
            })
    
    logger.info(f"Extracted {len(percentages)} percentage values")
    return percentages


def extract_delays(text: str) -> List[Dict[str, Union[str, float]]]:
    """
    Extract timing/delay values from text.
    
    Handles:
    - Seconds: "5s", "4 to 6s", "3 sec"
    - Milliseconds: "100ms", "500 millisec"
    - Minutes: "3 min", "1.5 minutes"
    
    Returns:
        List of delay dicts with values normalized to seconds
    """
    delays = []
    
    # Extract ranges (seconds)
    for match in DELAY_RANGE.finditer(text):
        delays.append({
            "type": "range",
            "min": float(match.group(1)),
            "max": float(match.group(2)),
            "unit": "seconds",
            "text": match.group(0)
        })
    
    # Extract simple delays
    range_texts = [d["text"] for d in delays]
    
    # Milliseconds
    for match in DELAY_MS.finditer(text):
        if not any(match.group(0) in rt for rt in range_texts):
            delays.append({
                "type": "simple",
                "value": float(match.group(1)) / 1000,  # Convert to seconds
                "unit": "seconds",
                "original_unit": "milliseconds",
                "text": match.group(0)
            })
    
    # Minutes
    for match in DELAY_MIN.finditer(text):
        if not any(match.group(0) in rt for rt in range_texts):
            delays.append({
                "type": "simple",
                "value": float(match.group(1)) * 60,  # Convert to seconds
                "unit": "seconds",
                "original_unit": "minutes",
                "text": match.group(0)
            })
    
    # Seconds
    for match in DELAY_SIMPLE.finditer(text):
        if not any(match.group(0) in rt for rt in range_texts):
            delays.append({
                "type": "simple",
                "value": float(match.group(1)),
                "unit": "seconds",
                "text": match.group(0)
            })
    
    logger.info(f"Extracted {len(delays)} delay values")
    return delays


def extract_led_states(text: str) -> List[Dict[str, str]]:
    """
    Extract LED state information from text.
    
    Example:
    "UV LED turns ON" → {"led": "UV", "state": "ON"}
    "'UV' LED on product turns OFF" → {"led": "UV", "state": "OFF"}
    "Green LED blinking" → {"led": "Green", "state": "BLINKING"}
    
    Returns:
        List of LED state dicts
    """
    led_states = []
    
    # Filter out non-LED words
    EXCLUDED_WORDS = {'RELAY', 'PRODUCT', 'DEVICE', 'UNIT', 'SYSTEM', 'LED'}
    
    # ON states
    for match in LED_ON.finditer(text):
        led_name = match.group(1).upper()
        # Skip if it's not actually an LED name
        if led_name not in EXCLUDED_WORDS:
            led_states.append({
                "led": led_name,
                "state": "ON",
                "text": match.group(0)
            })
    
    # OFF states
    for match in LED_OFF.finditer(text):
        led_name = match.group(1).upper()
        # Skip if it's not actually an LED name
        if led_name not in EXCLUDED_WORDS:
            led_states.append({
                "led": led_name,
                "state": "OFF",
                "text": match.group(0)
            })
    
    # BLINKING states
    for match in LED_BLINK.finditer(text):
        led_name = match.group(1).upper()
        # Skip if it's not actually an LED name
        if led_name not in EXCLUDED_WORDS:
            led_states.append({
                "led": led_name,
                "state": "BLINKING",
                "text": match.group(0)
            })
    
    logger.info(f"Extracted {len(led_states)} LED states")
    return led_states


def extract_relay_states(text: str) -> List[Dict[str, str]]:
    """
    Extract relay state information from text.
    
    Example:
    "Relay turns OFF" → {"state": "OFF"}
    
    Returns:
        List of relay state dicts
    """
    relay_states = []
    
    # ON states
    for match in RELAY_ON.finditer(text):
        relay_states.append({
            "state": "ON",
            "text": match.group(0)
        })
    
    # OFF states
    for match in RELAY_OFF.finditer(text):
        relay_states.append({
            "state": "OFF",
            "text": match.group(0)
        })
    
    logger.info(f"Extracted {len(relay_states)} relay states")
    return relay_states


# ============================================================================
# MAIN PARSING FUNCTION
# ============================================================================

def parse_specifications(text: str, tables: Optional[List[Dict]] = None) -> Dict[str, any]:
    """
    Main function: Parse all specifications from text.
    
    Combines:
    - Table data (if provided)
    - Pattern-based extraction from prose
    
    Args:
        text: Text block to parse (e.g., one machine's text)
        tables: Optional list of tables from table_extractor
    
    Returns:
        Structured specification dict:
        {
            "reference_voltage": {"value": 415, "unit": "VAC"},
            "voltage_parameters": {
                "under_voltage": {
                    "percentage": 85.0,
                    "range": {"min": 347, "max": 357, "unit": "VAC"}
                },
                "over_voltage": {...}
            },
            "timing_parameters": {
                "on_delay": {"min": 4, "max": 6, "unit": "seconds"},
                "off_delay": {...}
            },
            "led_indicators": [...],
            "relay_states": [...],
            "raw_extractions": {
                "voltages": [...],
                "percentages": [...],
                "delays": [...]
            }
        }
    """
    specs = {
        "reference_voltage": None,
        "voltage_parameters": {},
        "timing_parameters": {},
        "led_indicators": [],
        "relay_states": [],
        "raw_extractions": {}
    }
    
    # Extract raw patterns
    voltages = extract_voltages(text)
    percentages = extract_percentages(text)
    delays = extract_delays(text)
    led_states = extract_led_states(text)
    relay_states = extract_relay_states(text)
    
    # Store raw extractions
    specs["raw_extractions"] = {
        "voltages": voltages,
        "percentages": percentages,
        "delays": delays,
        "led_states": led_states,
        "relay_states": relay_states
    }
    
    # Find reference voltage (usually the highest simple voltage mentioned)
    simple_voltages = [v for v in voltages if v["type"] == "simple"]
    if simple_voltages:
        ref_voltage = max(simple_voltages, key=lambda x: x["value"])
        specs["reference_voltage"] = {
            "value": ref_voltage["value"],
            "unit": ref_voltage["unit"]
        }
    
    # Process table data if provided
    if tables:
        for table in tables:
            for row in table.get("rows", []):
                param_name = row.get("parameter", "").lower()
                
                # Under Voltage
                if "under" in param_name and "voltage" in param_name:
                    specs["voltage_parameters"]["under_voltage"] = {
                        "setting": row.get("setting", ""),
                        "range": row.get("range", ""),
                        "raw": row.get("raw_value", "")
                    }
                
                # Over Voltage
                elif "over" in param_name and "voltage" in param_name:
                    specs["voltage_parameters"]["over_voltage"] = {
                        "setting": row.get("setting", ""),
                        "range": row.get("range", ""),
                        "raw": row.get("raw_value", "")
                    }
                
                # Asymmetry
                elif "asym" in param_name:
                    specs["voltage_parameters"]["asymmetry"] = {
                        "setting": row.get("setting", ""),
                        "range": row.get("range", ""),
                        "raw": row.get("raw_value", "")
                    }
                
                # ON Delay
                elif "on" in param_name and "delay" in param_name:
                    specs["timing_parameters"]["on_delay"] = {
                        "setting": row.get("setting", ""),
                        "range": row.get("range", ""),
                        "raw": row.get("raw_value", "")
                    }
                
                # OFF Delay
                elif "off" in param_name and "delay" in param_name:
                    specs["timing_parameters"]["off_delay"] = {
                        "setting": row.get("setting", ""),
                        "range": row.get("range", ""),
                        "raw": row.get("raw_value", "")
                    }
    
    # Store LED and relay states
    specs["led_indicators"] = led_states
    specs["relay_states"] = relay_states
    
    logger.info(f"Parsed specifications: {len(specs['voltage_parameters'])} voltage params, "
                f"{len(specs['timing_parameters'])} timing params")
    
    return specs


def format_spec_summary(specs: Dict) -> str:
    """
    Create a human-readable summary of specifications.
    
    Useful for debugging and display.
    
    Returns:
        Formatted string summary
    """
    lines = ["SPECIFICATIONS SUMMARY", "=" * 60]
    
    # Reference voltage
    if specs.get("reference_voltage"):
        ref = specs["reference_voltage"]
        lines.append(f"Reference Voltage: {ref['value']} {ref['unit']}")
        lines.append("")
    
    # Voltage parameters
    if specs.get("voltage_parameters"):
        lines.append("Voltage Parameters:")
        for key, val in specs["voltage_parameters"].items():
            lines.append(f"  {key}: {val.get('setting', 'N/A')} | Range: {val.get('range', 'N/A')}")
        lines.append("")
    
    # Timing parameters
    if specs.get("timing_parameters"):
        lines.append("Timing Parameters:")
        for key, val in specs["timing_parameters"].items():
            lines.append(f"  {key}: {val.get('setting', 'N/A')} | Range: {val.get('range', 'N/A')}")
        lines.append("")
    
    # Raw extractions count
    raw = specs.get("raw_extractions", {})
    lines.append("Raw Extractions:")
    lines.append(f"  Voltages: {len(raw.get('voltages', []))}")
    lines.append(f"  Percentages: {len(raw.get('percentages', []))}")
    lines.append(f"  Delays: {len(raw.get('delays', []))}")
    lines.append(f"  LED States: {len(raw.get('led_states', []))}")
    lines.append(f"  Relay States: {len(raw.get('relay_states', []))}")
    
    return "\n".join(lines)