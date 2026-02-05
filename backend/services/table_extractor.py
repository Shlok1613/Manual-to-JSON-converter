from __future__ import annotations

import re
from typing import Dict, List

TABLE_HEADER_PATTERN = re.compile(r"\b(TABLE\s*\d+|LED\s+INDICATIONS?)\b", re.IGNORECASE)


def _parse_table_line(line: str) -> Dict[str, str]:
    parts = [p.strip() for p in re.split(r"\||\t|\s{2,}", line) if p.strip()]
    if len(parts) >= 3:
        return {"parameter": parts[0], "setting": parts[1], "range": parts[2], "notes": " | ".join(parts[3:])}

    kv = re.match(r"([\w\-\s()/]+)\s*[:\-]\s*(.+)", line)
    if kv:
        return {"parameter": kv.group(1).strip(), "setting": kv.group(2).strip(), "range": "", "notes": ""}

    return {"parameter": line.strip(), "setting": "", "range": "", "notes": ""}


def extract_tables(block_text: str) -> List[Dict[str, object]]:
    """Stage 3: locate table-like sections and parse rows."""
    tables: List[Dict[str, object]] = []
    current: Dict[str, object] | None = None

    for raw in block_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if TABLE_HEADER_PATTERN.search(line):
            if current:
                tables.append(current)
            current = {"name": line, "rows": []}
            continue

        if current is not None:
            if re.match(r"^\d+\.\s+", line):
                tables.append(current)
                current = None
                continue
            current["rows"].append(_parse_table_line(line))

    if current:
        tables.append(current)

    return tables
