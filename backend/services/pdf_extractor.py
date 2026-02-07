"""
PDF Text Extraction Service
"""
from pathlib import Path
from typing import List, Union
import logging

logger = logging.getLogger(__name__)

PdfInput = Union[Path, str]


def extract_text_pdfplumber(pdf_path: Path) -> List[str]:
    """Extract text using pdfplumber."""
    import pdfplumber
    
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    
    logger.info(f"pdfplumber extracted {len(pages)} pages")
    return pages


def extract_text_pymupdf(pdf_path: Path) -> List[str]:
    """Extract text using PyMuPDF (fallback)."""
    import fitz
    
    pages = []
    doc = fitz.open(pdf_path)
    
    for page in doc:
        text = page.get_text("text") or ""
        pages.append(text)
    
    doc.close()
    logger.info(f"pymupdf extracted {len(pages)} pages")
    return pages


def extract_text(pdf_input: PdfInput) -> List[str]:
    """
    Main extraction function with automatic fallback.
    
    Returns list of page texts.
    """
    pdf_path = Path(pdf_input)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    if not pdf_path.suffix.lower() == '.pdf':
        raise ValueError(f"File is not a PDF: {pdf_path}")
    
    # Try pdfplumber first
    try:
        logger.info(f"Attempting pdfplumber: {pdf_path.name}")
        return extract_text_pdfplumber(pdf_path)
    except Exception as e1:
        logger.warning(f"pdfplumber failed, trying pymupdf: {e1}")
        
        # Fallback to pymupdf
        try:
            logger.info(f"Attempting pymupdf: {pdf_path.name}")
            return extract_text_pymupdf(pdf_path)
        except Exception as e2:
            raise Exception(
                f"PDF extraction failed. "
                f"pdfplumber: {e1}, pymupdf: {e2}"
            )