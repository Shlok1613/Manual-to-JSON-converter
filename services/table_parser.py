import re
from typing import List, Dict
from services.types import Page


TABLE_KEYWORDS = [
    "TABLE",
    "PRODUCT SETTINGS",
    "ACCEPTABLE LIMITS",
    "VOLTAGE",
    "CUT OFF",
    "THRESHOLD",
]


def is_table_page(text: str) -> bool:
    if not text:
        return False

    text_upper = text.upper()

    keyword_hit = any(k in text_upper for k in TABLE_KEYWORDS)

    # dense numeric content
    number_density = len(re.findall(r"\d+", text)) > 20

    # tabular spacing
    multi_columns = len(re.findall(r"\s{2,}", text)) > 10

    # bad procedural indicators
    BAD_TERMS = [
        "PROCEDURE",
        "STEP",
        "TEST PROCEDURE",
        "DIP S/W",
        "HEALTHY CONDITION",
    ]

    bad_hits = sum(
        1 for term in BAD_TERMS
        if term in text_upper
    )

    score = 0

    if keyword_hit:
        score += 2

    if number_density:
        score += 1

    if multi_columns:
        score += 1

    score -= bad_hits

    return score >= 3

def extract_table_pages(pages: List[Page]) -> List[Page]:
    return [
        p for p in pages
        if p.jpeg_bytes is not None and is_table_page(p.ocr_text)
    ]