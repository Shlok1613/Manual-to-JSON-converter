"""
PDF Text Extractor
Supports both regular PDFs and ZIP-based scanned PDFs with OCR text.
"""
import pdfplumber
import zipfile
from pathlib import Path
from typing import List
import logging
import re

logger = logging.getLogger(__name__)


def is_zip_with_text(pdf_path: Path) -> bool:
    """
    Check if file is a ZIP archive containing text files.

    Some scanned PDFs are actually ZIP files with JPEGs + OCR text files.
    """
    try:
        with zipfile.ZipFile(pdf_path, 'r') as zf:
            files = zf.namelist()
            has_text_files = any(f.endswith('.txt') for f in files)

            if has_text_files:
                text_count = len([
                    f for f in files
                    if f.endswith('.txt') and 'manifest' not in f.lower()
                ])
                logger.info(f"Detected ZIP-based PDF with {text_count} text files")
                return True
    except (zipfile.BadZipFile, Exception):
        pass

    return False


def extract_from_zip_pdf(pdf_path: Path) -> List[str]:
    """
    Extract text from ZIP-based PDF (scanned document with OCR).

    Format: ZIP archive containing:
    - X.jpeg: Scanned page images
    - X.txt: OCR extracted text
    - manifest.json: Metadata
    """
    pages = []

    with zipfile.ZipFile(pdf_path, 'r') as zf:
        # Get all text files, excluding manifest
        text_files = [
            f for f in zf.namelist()
            if f.endswith('.txt') and 'manifest' not in f.lower()
        ]

        # Sort by page number (extract number from filename)
        def get_page_num(filename):
            try:
                numbers = re.findall(r'\d+', filename)
                return int(numbers[0]) if numbers else 0
            except Exception:
                return 0

        text_files = sorted(text_files, key=get_page_num)

        logger.info(f"Extracting {len(text_files)} pages from ZIP-based PDF")

        for txt_file in text_files:
            try:
                text_content = zf.read(txt_file).decode('utf-8', errors='ignore')
                pages.append(text_content)
            except Exception as e:
                logger.warning(f"Failed to read {txt_file}: {e}")
                pages.append("")

    return pages


def extract_text(pdf_path: Path) -> List[str]:
    """
    Extract text from PDF file.

    Supports:
    - Regular text-based PDFs (pdfplumber)
    - ZIP-based scanned PDFs with OCR text

    Args:
        pdf_path: Path to PDF file (or ZIP file with .pdf extension)

    Returns:
        List of strings, one per page
    """
    logger.info(f"Extracting text from: {pdf_path.name}")

    # Check if it's a ZIP-based PDF (NEW!)
    if is_zip_with_text(pdf_path):
        logger.info("Processing as ZIP-based scanned PDF")
        return extract_from_zip_pdf(pdf_path)

    # Process as regular PDF (EXISTING)
    try:
        logger.info("Processing as regular PDF with pdfplumber")
        with pdfplumber.open(pdf_path) as pdf:
            pages = []
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    pages.append(text)
                else:
                    logger.warning(f"Page {i} returned no text")
                    pages.append("")

            logger.info(f"Extracted {len(pages)} pages")
            return pages

    except Exception as e:
        logger.error(f"pdfplumber failed: {e}")

        # Try PyMuPDF fallback if available
        try:
            import fitz
            logger.info("Trying PyMuPDF fallback")

            doc = fitz.open(pdf_path)
            pages = []

            for page in doc:
                text = page.get_text()
                pages.append(text if text else "")

            doc.close()
            logger.info(f"Extracted {len(pages)} pages with PyMuPDF")
            return pages

        except Exception as e2:
            logger.error(f"PyMuPDF also failed: {e2}")
            raise Exception(f"Could not extract text from PDF: {e}")