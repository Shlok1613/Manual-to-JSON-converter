import re
from typing import List, Dict
from services.types import Page


def clean_cell(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.strip())


def split_row(line: str) -> List[str]:
    """
    More robust splitting for OCR text
    """
    # first try multi-space split
    parts = re.split(r"\s{2,}", line.strip())

    # fallback → single space grouping
    if len(parts) <= 1:
        parts = re.split(r"\s+", line.strip())

    return [clean_cell(p) for p in parts if p.strip()]


def is_table_line(line: str) -> bool:
    if not line:
        return False

    # must contain at least 2 numbers OR number range
    has_numbers = len(re.findall(r"\d", line)) >= 2

    # detect value-like patterns (important)
    has_range = bool(re.search(r"\d+\s*[-to]+\s*\d+", line, re.IGNORECASE))

    # detect multiple tokens (not just single word)
    tokens = line.strip().split()
    enough_tokens = len(tokens) >= 3

    return has_numbers and (has_range or enough_tokens)


def extract_table_grid_from_text(text: str) -> List[List[str]]:
    """
    Convert raw OCR text → grid (list of rows)
    """
    lines = text.split("\n")

    grid = []

    for line in lines:
        if is_table_line(line):
            row = split_row(line)
            if len(row) >= 2:
                grid.append(row)

    return grid


def extract_table_grids(pages: List[Page]) -> List[Dict]:
    """
    Extract grids from multiple pages.
    Returns:
    [
        {
            "page": 6,
            "grid": [[...], [...]]
        }
    ]
    """
    tables = []

    for p in pages:
        if not p.ocr_text:
            continue

        grid = extract_table_grid_from_text(p.ocr_text)

        if len(grid) >= 2:
            tables.append({
                "page": p.num,
                "grid": grid
            })

    return tables