import re
from typing import List
from collections import Counter


TOKEN_PATTERN = re.compile(r"\b[A-Z0-9_]{4,}\b")

def detect_variants_from_text(text: str) -> List[str]:
    tokens = TOKEN_PATTERN.findall(text.upper())
    filtered = [t for t in tokens if is_valid_variant(t)]
    counts = Counter(filtered)

    strong = []
    weak = []

    for token, count in counts.items():
        if count >= 3:
            strong.append(token)
        elif appears_in_table_context(token, text):
            weak.append(token)

    # PRIORITIZE strong, fallback to weak
    variants = strong if strong else weak

    return sorted(variants, key=lambda x: (-counts[x], len(x)))[:8]

def is_valid_variant(token: str) -> bool:
    # must start with letters
    if not re.match(r"^[A-Z]", token):
        return False
    # must be alphanumeric structured (letters + digits)
    if not re.match(r"^[A-Z0-9]{4,}$", token):
        return False

    # must contain BOTH letters and digits
    if not (re.search(r"[A-Z]", token) and re.search(r"\d", token)):
        return False

    # avoid pure numeric or pure text
    if token.isdigit() or token.isalpha():
        return False

    # reject very long tokens (usually sentences/IDs)
    if len(token) > 10:
        return False

    # reject generic engineering words
    BAD_WORDS = {
        "VOLTAGE", "CURRENT", "PROCESS", "FUNCTIONAL",
        "SETTING", "SETTINGS", "TABLE", "PHASE",
        "THRESHOLD", "PROCEDURE", "TESTING",
        "HEALTHY", "FAULT", "DELAY"
    }

    if token in BAD_WORDS:
        return False

    return True

def appears_in_table_context(token: str, text: str) -> bool:
    lines = text.split("\n")

    for line in lines:
        if token in line:
            # must contain numbers → table-like
            if re.search(r"\d", line):
                return True

    return False