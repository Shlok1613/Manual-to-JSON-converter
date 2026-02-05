from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Union

import fitz
import pdfplumber


PdfInput = Union[Path, str, bytes]


def _to_bytes(data: PdfInput) -> bytes:
    if isinstance(data, bytes):
        return data
    return Path(data).read_bytes()


def extract_text_pdfplumber(pdf_data: bytes) -> List[str]:
    pages: List[str] = []
    with pdfplumber.open(BytesIO(pdf_data)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def extract_text_pymupdf(pdf_data: bytes) -> List[str]:
    pages: List[str] = []
    doc = fitz.open(stream=pdf_data, filetype="pdf")
    for page in doc:
        pages.append(page.get_text("text") or "")
    return pages


def extract_text(data: PdfInput) -> List[str]:
    """Stage 1: extract page text with fallback to PyMuPDF."""
    pdf_data = _to_bytes(data)
    try:
        return extract_text_pdfplumber(pdf_data)
    except Exception:
        return extract_text_pymupdf(pdf_data)
