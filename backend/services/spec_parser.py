from __future__ import annotations

import re
from typing import Dict, List

from .table_extractor import extract_tables

VOLTAGE_SIMPLE = r"(\d+(?:\.\d+)?)\s*(?:VAC|V)"
VOLTAGE_RANGE = r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:VAC|V)"
PERCENTAGE = r"(\d+(?:\.\d+)?)\s*%"
DELAY_SIMPLE = r"(\d+(?:\.\d+)?)\s*(?:sec|second|s|ms|min)\b"


def _bucket_param_name(name: str) -> str:
    nm = name.lower()
    if "under" in nm or nm.startswith("uv"):
        return "under_voltage"
    if "over" in nm or nm.startswith("ov"):
        return "over_voltage"
    if "asym" in nm:
        return "asymmetry"
    if "on delay" in nm:
        return "on_delay"
    if "off delay" in nm:
        return "off_delay"
    return re.sub(r"\W+", "_", nm).strip("_")


def parse_specifications(block_text: str) -> Dict[str, object]:
    """Stage 4: parse specification entities from prose + extracted tables."""
    specs: Dict[str, object] = {
        "reference_voltage": None,
        "voltage_parameters": {},
        "timing_parameters": {},
        "raw_tables": extract_tables(block_text),
    }

    ref = re.search(r"(?:reference|rated|input)\s*voltage\s*[:\-]?\s*" + VOLTAGE_SIMPLE, block_text, re.IGNORECASE)
    if ref:
        specs["reference_voltage"] = f"{ref.group(1)} VAC"

    for line in block_text.splitlines():
        clean = line.strip()
        if not clean:
            continue

        kv = re.match(r"([A-Za-z0-9\-\s()/]+)\s*[:\-]\s*(.+)", clean)
        if not kv:
            continue
        key, value = kv.group(1).strip(), kv.group(2).strip()
        bucket = _bucket_param_name(key)

        pct = re.search(PERCENTAGE, value, re.IGNORECASE)
        vr = re.search(VOLTAGE_RANGE, value, re.IGNORECASE)
        delay = re.search(DELAY_SIMPLE, value, re.IGNORECASE)

        item = {"setting": pct.group(0) if pct else None, "range": None, "raw": value}
        if vr:
            item["range"] = f"{vr.group(1)} to {vr.group(2)} VAC"
        if delay:
            item["delay"] = delay.group(0)

        if "delay" in bucket:
            specs["timing_parameters"][bucket] = item
        else:
            specs["voltage_parameters"][bucket] = item

    for table in specs["raw_tables"]:
        for row in table.get("rows", []):
            bucket = _bucket_param_name(str(row.get("parameter", "")))
            if not bucket:
                continue
            row_item = {
                "setting": row.get("setting") or None,
                "range": row.get("range") or None,
                "notes": row.get("notes") or "",
            }
            if "delay" in bucket:
                specs["timing_parameters"].setdefault(bucket, row_item)
            else:
                specs["voltage_parameters"].setdefault(bucket, row_item)

    return specs
