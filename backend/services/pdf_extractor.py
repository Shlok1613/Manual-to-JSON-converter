# backend/services/pdf_extractor.py
from typing import List
import pdfplumber 
import fitz  

def extract_text_pdfplumber(file_stream) -> List[str]:
    """Extract text page-by-page using pdfplumber. Returns list of page texts."""
    pages = []
    try:
        with pdfplumber.open(file_stream) as pdf:
            for p in pdf.pages:
                pages.append(p.extract_text() or "")
    except Exception:
        # caller may fallback to fitz
        raise
    return pages

def extract_text_pymupdf(file_stream) -> List[str]:
    """Fallback extraction using PyMuPDF (fitz)."""
    pages = []
    # fitz expects file-like or bytes; ensure we are reading bytes:
    file_stream.seek(0)
    data = file_stream.read()
    doc = fitz.open(stream=data, filetype="pdf")
    for page in doc:
        pages.append(page.get_text("text") or "")
    return pages

def extract_text(file_stream) -> List[str]:
    """
    Try pdfplumber first, fallback to PyMuPDF.
    Returns list of page texts.
    """
    file_stream.seek(0)
    try:
        return extract_text_pdfplumber(file_stream)
    except Exception:
        file_stream.seek(0)
        return extract_text_pymupdf(file_stream)
