from __future__ import annotations

import re
from typing import Dict, List

SECTION_PATTERNS = [
    r"PROCESS:\s*(.+)",
    r"(SM\d+)\s+(.+Testing)",
    r"(.+)\s+VERIFICATION:",
]
MACHINE_HINT = re.compile(r"\b(SPPR|SM\d+|DSMR|MAG\w+|MAC\w+)\b", re.IGNORECASE)


def _resolve_machine_name(header: str, fallback_idx: int) -> str:
    m = MACHINE_HINT.search(header)
    if m:
        return m.group(1).upper()
    return f"MACHINE_{fallback_idx}"


def segment_blocks(full_text: str) -> List[Dict[str, str]]:
    """Stage 2: split full text into machine/process blocks."""
    lines = full_text.splitlines()
    blocks: List[Dict[str, str]] = []
    current = {"machine": "MACHINE_1", "header": "", "text": ""}

    for line in lines:
        raw = line.strip()
        if not raw:
            current["text"] += "\n"
            continue

        hit = False
        for pattern in SECTION_PATTERNS:
            mm = re.search(pattern, raw, flags=re.IGNORECASE)
            if mm:
                if current["text"].strip():
                    blocks.append(current)
                header = mm.group(0)
                current = {
                    "machine": _resolve_machine_name(header, len(blocks) + 1),
                    "header": header,
                    "text": raw + "\n",
                }
                hit = True
                break

        if not hit:
            if re.search(r"\b(Functional\s+Test\w*\s+for)\b", raw, flags=re.IGNORECASE):
                if current["text"].strip():
                    blocks.append(current)
                current = {
                    "machine": _resolve_machine_name(raw, len(blocks) + 1),
                    "header": raw,
                    "text": raw + "\n",
                }
            else:
                current["text"] += raw + "\n"

    if current["text"].strip():
        blocks.append(current)

    for idx, block in enumerate(blocks, start=1):
        if block["machine"].startswith("MACHINE_"):
            block["machine"] = f"MACHINE_{idx}"

    return blocks
