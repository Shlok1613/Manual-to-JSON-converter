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

    # heuristic: many numbers + structured spacing
    number_density = len(re.findall(r"\d+", text)) > 20
    multi_columns = len(re.findall(r"\s{2,}", text)) > 10

    return keyword_hit or (number_density and multi_columns)


def extract_table_pages(pages: List[Page]) -> List[Page]:
    return [
        p for p in pages
        if p.jpeg_bytes is not None and is_table_page(p.ocr_text)
    ]