# services/pdf_extractor.py
"""
PDF Page Extractor — returns Page objects with both OCR text and JPEG bytes.

Handles:
  - ZIP-bundle "PDFs": archive of N.jpeg + N.txt + manifest.json (the project files)
  - Real text-layer PDFs: pdfplumber for text + pdf2image for rendering
"""
import zipfile
import json
import io
import re
from pathlib import Path
from typing import List, Optional
import logging

import pdfplumber

from .types import Page

logger = logging.getLogger(__name__)


def _is_zip_bundle(pdf_path: Path) -> bool:
    try:
        with open(pdf_path, "rb") as fh:
            return fh.read(4) == b"PK\x03\x04"
    except Exception:
        return False


def _page_num_from_name(filename: str) -> int:
    digits = re.findall(r"\d+", filename)
    return int(digits[0]) if digits else 0


def _extract_zip_bundle(pdf_path: Path) -> List[Page]:
    pages: List[Page] = []
    with zipfile.ZipFile(pdf_path, "r") as zf:
        files = zf.namelist()

        manifest = {}
        for f in files:
            if "manifest" in f.lower() and f.endswith(".json"):
                try:
                    manifest = json.loads(zf.read(f).decode("utf-8", errors="ignore"))
                except Exception as e:
                    logger.warning(f"manifest parse failed: {e}")
                break
        manifest_pages = {p["page_number"]: p for p in manifest.get("pages", [])}

        text_files = sorted(
            [f for f in files if f.endswith(".txt") and "manifest" not in f.lower()],
            key=_page_num_from_name,
        )
        logger.info(f"ZIP bundle: {len(text_files)} pages")

        for tf in text_files:
            n = _page_num_from_name(tf)
            try:
                ocr_text = zf.read(tf).decode("utf-8", errors="ignore")
            except Exception:
                ocr_text = ""

            jpeg_name = f"{n}.jpeg"
            jpeg_bytes = zf.read(jpeg_name) if jpeg_name in files else None

            mp = manifest_pages.get(n, {})
            dims = mp.get("image", {}).get("dimensions", {}) if mp else {}

            pages.append(Page(
                num=n,
                ocr_text=ocr_text,
                jpeg_bytes=jpeg_bytes,
                width=dims.get("width", 0),
                height=dims.get("height", 0),
            ))
    return pages


def _extract_real_pdf(pdf_path: Path) -> List[Page]:
    pages: List[Page] = []
    text_per_page: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            text_per_page.append(p.extract_text() or "")
        page_count = len(pdf.pages)

    images_per_page: List[Optional[bytes]] = [None] * page_count
    try:
        from pdf2image import convert_from_path
        pil_images = convert_from_path(str(pdf_path), dpi=150)
        for i, img in enumerate(pil_images):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            images_per_page[i] = buf.getvalue()
    except ImportError:
        logger.warning("pdf2image not installed — vision will be unavailable for real PDFs")
    except Exception as e:
        logger.warning(f"pdf2image render failed: {e}")

    for i in range(page_count):
        pages.append(Page(num=i + 1, ocr_text=text_per_page[i], jpeg_bytes=images_per_page[i]))
    return pages


def extract_pages(pdf_path: Path) -> List[Page]:
    """Public: returns ordered list of Page objects with text + jpeg."""
    logger.info(f"Extracting: {pdf_path.name}")
    if _is_zip_bundle(pdf_path):
        logger.info("  format: ZIP bundle")
        return _extract_zip_bundle(pdf_path)
    logger.info("  format: real PDF")
    return _extract_real_pdf(pdf_path)


def extract_text(pdf_path: Path) -> List[str]:
    """Backward-compatible: returns just per-page text strings."""
    return [p.ocr_text for p in extract_pages(pdf_path)]

