"""Shared delay validation helpers."""
import re


def is_spurious_delay_hallucination(val) -> bool:
    """Detect narrative-page pot delays (e.g. '62 sec') wrongly applied to FQC steps."""
    if not val:
        return False
    text = re.sub(r"\\[nrt]", " ", str(val))
    text = re.sub(r"[\n\r\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return bool(re.search(r"\b62\s*sec\b", text) or text == "62")
