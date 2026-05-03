# services/block_segmenter.py
"""
Block Segmenter — page-aware.

Walks Page objects in order, returns Block objects with page_range and
the actual Page instances. Vision extractor needs the JPEG bytes downstream,
so we keep them attached.
"""
import re
import logging
from typing import List, Optional
from collections import Counter

from .types import Page, Block

logger = logging.getLogger(__name__)


SECTION_PATTERNS = [
    r"^Neutral\s+Open\s+SPPR",
    r"^PROCESS:\s*(.+)",
    r"^(SM\d+_[A-Z])\s+Functional\s+Testing",
    r"^(SM\d+)\s+(.+Testing)",
    r"^(SM\d+)\s+Functional\s+Testing",
    r"^Process:\s+Functional\s+Testing\s+(SM\d+)",
    r"^PROCESS\s*:\s*Functional\s+Testing\s+DSMR",
    r"^Functional\s+Testing\s+table\s+for\s+(\w+)",
    r"^For\s+(MG\d+[A-Z]+)\s+product",
    r"^(DMS\d+)",
    r"^(MG\d+[A-Z]+)(?:\s+product|:|\s+Functional|\s+CRITICALITY|\s+\(.+Testing)",
    r"^PROCEDURE\s+FOR\s+(.+?):",
    r"FUNCTIONAL\s+TEST\s+PROCEDURE\s+FOR\s+([A-Z0-9][A-Z0-9_]{2,})",
    r"^([A-Z0-9][A-Z0-9_]{2,})\s+(?:AUTOMATED\s+)?FUNCTIONAL\s+TESTING",
    r"([A-Z]{2,})PROCESS\s*:\s*Functional",
    r"PROCESS\s*:\s*Functional\s+Testing\s+([A-Z0-9][A-Z0-9_]{2,})",
]

FORCE_SPLIT_PATTERNS = [
    r"^PROCESS:\s*(.+)",
    r"^PROCEDURE\s+FOR\s+(.+?):",
    r"^For\s+(MG\d+[A-Z]+)\s+product",
]

MACHINE_NAME_PATTERN = re.compile(
    r"\b(SPPR|SM\d+_[A-Z]|SM\d+|DSMR|DMS\d+|DMA\d+|MAG\w+|MAC\w+|MG\d+\w+|MD\d+\w+|MB\d+\w+)\b",
    re.IGNORECASE,
)
SCOPE_PATTERN = re.compile(r"SCOPE\s*:\s*([\w/\s]+)", re.IGNORECASE)


def _find_machine_name(text: str, fallback: str = "UNKNOWN") -> str:
    sm = SCOPE_PATTERN.search(text)
    if sm:
        match = MACHINE_NAME_PATTERN.search(sm.group(1))
        if match:
            return match.group(1).upper()
    match = MACHINE_NAME_PATTERN.search(text)
    return match.group(1).upper() if match else fallback


def _has_table_spec(text: str) -> bool:
    return bool(re.search(
        r"TABLE\s*\d?\s*\(PRODUCT\s*SETTINGS"
        r"|Under\s*Voltage\s*\(UV\).*?\d+\s+to\s+\d+\s+VAC",
        text, re.I | re.DOTALL,
    ))


def _has_incomplete_table_reference(text: str) -> bool:
    recent = text[-200:] if len(text) > 200 else text
    recent_u = recent.upper()
    has_ref = bool(
        re.search(r"REFER\s+(?:THE\s+)?(?:FOLLOWING\s+)?TABLES?", recent_u)
        or re.search(r"(?:TABLE|TABLES)\s+(?:BELOW|GIVEN|1|2|01|02)", recent_u)
        or re.search(r"AS\s+PER\s+TABLE", recent_u)
    )
    if not has_ref:
        return False
    full_u = text.upper()
    has_struct = bool(
        re.search(r"TABLE\s+\d+\s*\(", full_u)
        or re.search(r"TABLE\s+\(", full_u)
        or re.search(r"TABLE\s+0\d\s*:", full_u)
    )
    return not has_struct


def segment_blocks(pages: List[Page], user_names: Optional[List[str]] = None) -> List[Block]:
    if not pages:
        return []

    full_text = "\n\n".join(p.ocr_text for p in pages)

    if user_names:
        user_names = [
            n for n in user_names
            if re.search(rf"\b{re.escape(n)}\b", full_text, re.IGNORECASE)
        ] or None

    MIN_BLOCK_SIZE = 400
    blocks: List[Block] = []
    current = Block(machine="MACHINE_1", text="", page_range=[], pages=[])

    for page in pages:
        # Always claim this page for the current block. If a section break
        # happens mid-page, both old and new block claim it (intentional).
        if page.num not in current.page_range:
            current.page_range.append(page.num)
            current.pages.append(page)

        for line in page.ocr_text.splitlines():
            stripped = line.strip()
            if not stripped:
                current.text += "\n"
                continue

            split_here = False
            for pat in SECTION_PATTERNS:
                m = re.search(pat, stripped, flags=re.IGNORECASE)
                if not m:
                    continue
                size = len(current.text.strip())
                force = any(re.search(fp, stripped, flags=re.IGNORECASE) for fp in FORCE_SPLIT_PATTERNS)
                allow = (
                    not current.text.strip()
                    or force
                    or (size > MIN_BLOCK_SIZE and not _has_incomplete_table_reference(current.text))
                )
                if allow:
                    if current.text.strip():
                        blocks.append(current)
                    machine_name = _find_machine_name(
                        m.group(0), fallback=f"MACHINE_{len(blocks) + 1}"
                    )
                    current = Block(
                        machine=machine_name,
                        text=stripped + "\n",
                        page_range=[page.num],
                        pages=[page],
                        header=m.group(0),
                    )
                    split_here = True
                break
            if not split_here:
                current.text += stripped + "\n"

    if current.text.strip():
        blocks.append(current)

    # merge blocks that are too short and lack table specs
    MIN_MERGE = 1500
    merged: List[Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if (
    len(b.text) < MIN_MERGE
    and not _has_table_spec(b.text)
    and i + 1 < len(blocks)
):
            nxt = blocks[i + 1]
            new_pages = list(b.pages)
            new_range = list(b.page_range)
            for p in nxt.pages:
                if p.num not in new_range:
                    new_range.append(p.num)
                    new_pages.append(p)
            merged.append(Block(
                machine=b.machine, text=b.text + nxt.text,
                page_range=new_range, pages=new_pages, header=b.header,
            ))
            i += 2
        else:
            merged.append(b)
            i += 1
    blocks = merged

    # second-pass machine name resolution
    for b in blocks:
        if b.machine.startswith("MACHINE_"):
            real = _find_machine_name(b.text, fallback=b.machine)
            if real != b.machine:
                b.machine = real

    # SCOPE-based fan-out: consolidated WI documents (SCOPE: A / B / C / ...)
    scope_fanned = False
    if blocks:
        combined_text = "\n".join(b.text for b in blocks)
        sm = SCOPE_PATTERN.search(combined_text)
        if sm:
            counts = Counter(b.machine for b in blocks)
            most_count = counts.most_common(1)[0][1]
            dominance = most_count / max(len(blocks), 1)
            scope_products = re.findall(
                r"(MAG\d+[A-Z0-9]+|MAC\d+[A-Z0-9]+|SM\d+_[A-Z]|SM\d+|MG\d+[A-Z]+)",
                sm.group(1), re.IGNORECASE,
            )
            scope_products = list(dict.fromkeys(p.upper() for p in scope_products))
            if len(scope_products) > 1 and (dominance >= 0.5 or len(blocks) <= 2):
                all_pages: List[Page] = []
                seen = set()
                all_range: List[int] = []
                for b in blocks:
                    for p in b.pages:
                        if p.num not in seen:
                            seen.add(p.num)
                            all_pages.append(p)
                            all_range.append(p.num)
                blocks = [
                    Block(machine=p, text=combined_text,
                          page_range=list(all_range), pages=list(all_pages),
                          header=f"SCOPE: {p}")
                    for p in scope_products
                ]
                scope_fanned = True
                logger.info(f"SCOPE fan-out: {scope_products}")

    if user_names:
        wanted = [n.upper() for n in user_names]
        kept = [b for b in blocks if b.machine.upper() in wanted]
        merged_by_name: dict = {}
        for b in kept:
            key = b.machine.upper()
            if key not in merged_by_name:
                merged_by_name[key] = Block(
                    machine=key, text=b.text,
                    page_range=list(b.page_range), pages=list(b.pages),
                    header=b.header,
                )
            else:
                m = merged_by_name[key]
                m.text += "\n" + b.text
                for p in b.pages:
                    if p.num not in m.page_range:
                        m.page_range.append(p.num)
                        m.pages.append(p)
        blocks = [merged_by_name[n] for n in wanted if n in merged_by_name]
        logger.info(f"After user filter: {[b.machine for b in blocks]}")
    elif not scope_fanned:
        seen_count: dict = {}
        for b in blocks:
            seen_count[b.machine] = seen_count.get(b.machine, 0) + 1
            if seen_count[b.machine] > 1:
                b.machine = f"{b.machine}_{seen_count[b.machine]}"

    logger.info(f"Segmentation: {len(blocks)} block(s)")
    for b in blocks:
        sample = b.page_range[:5]
        more = "..." if len(b.page_range) > 5 else ""
        logger.info(f"  {b.machine:18s} pages={sample}{more}  ({len(b.text):,} chars)")

    return blocks