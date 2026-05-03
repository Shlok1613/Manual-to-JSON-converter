import re
from typing import List
from collections import Counter


TOKEN_PATTERN = re.compile(r"\b[A-Z0-9_]{4,}\b")


BLACKLIST = {
    "TABLE", "TEST", "VOLTAGE", "RANGE", "SETTING",
    "PROCESS", "FUNCTIONAL", "PROCEDURE", "PHASE",
    "INPUT", "OUTPUT", "DELAY", "TIME", "VALUE",
}


def detect_variants_from_text(text: str) -> List[str]:
    """
    Generic structured identifier detection.

    Strategy:
    1. Extract all tokens (A-Z0-9_)
    2. Remove common English / technical words
    3. Count frequency
    4. Keep identifiers that:
       - appear multiple times OR
       - appear clustered (table header-like)
    """

    if not text:
        return []

    tokens = TOKEN_PATTERN.findall(text.upper())

    # Filter
    filtered = [
        t for t in tokens
        if t not in BLACKLIST
        and any(c.isdigit() for c in t)  # must contain digit
    ]

    counts = Counter(filtered)

    # Keep strong candidates
    variants = [
        token for token, count in counts.items()
        if count >= 2
        and not token.isdigit()
        and not token.endswith("V")
        and not token.endswith("HZ")
    ]

    # fallback: if nothing repeated, take top few
    if not variants:
        variants = [
            t for t, _ in counts.most_common(10)
            if any(c.isalpha() for c in t)
            and any(c.isdigit() for c in t)
            and not t.endswith("V")
            and not t.endswith("HZ")
            and not t.startswith("SM")
        ][:5]

    return variants