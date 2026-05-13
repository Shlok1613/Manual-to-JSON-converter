from typing import List
from services.types import Page
import re


def filter_pages_for_variant(variant: str, pages: List[Page]) -> List[Page]:
    """
    Return only pages relevant to a variant.

    Logic:
    - Keep pages where variant name appears
    - If nothing found → fallback to original pages (safe fallback)
    """

    if not variant or not pages:
        return pages

    variant_upper = variant.upper()

    filtered = [
        p for p in pages
        if re.search(rf"\b{re.escape(variant_upper)}\b", (p.ocr_text or ""), re.IGNORECASE)
    ]

    # fallback → avoid empty input to vision
    return filtered if filtered else pages