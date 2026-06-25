"""
Stage C: 300-DPI header-only re-read for tables blocked by unreadable/fragment headers.
Merges recovered headers into saved raw JSON. Leaves row data untouched.

Run AFTER freeze (raw_frozen/ already created), BEFORE --reprocess.

Usage:
    python run_stage_c.py [pdf] [output_dir]

Defaults:
    pdf        = source/FUnctional Testing WI_Five series.pdf
    output_dir = outputs/functional
"""

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts (DO NOT mention expected codes or family names)
# ---------------------------------------------------------------------------

_SM500_HDR_PROMPT = """\
Look at this scanned page from a Functional Testing specification.
Find the product-settings table. It has two fixed leading columns (Parameter, Setting),
then model-code columns grouped under an "Acceptable Limits" banner.

Read ONLY the model-code header row — the row of codes directly beneath "Acceptable Limits".
Return those codes left-to-right as a JSON array of strings.
Do NOT include the Parameter column, the Setting column, or the "Acceptable Limits" text.

Return ONLY valid JSON. No markdown. No explanation.
Example output: ["MD71B9", "MD71BH", "MD71BF", "MG73B9"]
"""

_SM501B_HDR_PROMPT = """\
Look at these scanned pages from a Functional Testing specification.
Find TABLE 3: PRODUCT SETTINGS & ACCEPTABLE LIMITS.

This table has TWO data columns under "Acceptable Limits". The header row of this table
contains exactly 2 model codes.

IMPORTANT: Text like "(SYMMETRICAL)", "90% (+/-5V)", and "FOR MG53Bx" appears in the
Setting column or in data cells — it is NOT part of the column header.

Return the 2 model codes as a JSON array of exactly 2 strings.
Return ONLY valid JSON. No markdown. No explanation.
Example: ["MG53BQ", "MG53BM"]
"""

_DSMR_MULTI_PROMPT = """\
These 3 pages each show ONE product-settings table from a Functional Testing specification.
Each table has two fixed leading columns (Parameter, Setting), then model-code columns
grouped under an "Acceptable Limits" banner.

For EACH page, read ONLY the model-code header row of the table shown.
Return a JSON array of 3 arrays, one per page in page order:

[
  ["code1", "code2", ...],
  ["code1"],
  ["code1"]
]

Ignore the Parameter column, the Setting column, and the "Acceptable Limits" text.
Return ONLY valid JSON. No markdown. No explanation.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    return raw.strip()


def _render_pages(pdf_path: Path, page_nums: List[int], dpi: int = 300):
    import fitz
    doc = fitz.open(str(pdf_path))
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    out = {}
    for pg in page_nums:
        pix = doc[pg - 1].get_pixmap(matrix=matrix)
        out[pg] = pix.tobytes("jpeg")
    doc.close()
    logger.info(f"  Rendered pages {page_nums} at {dpi} DPI")
    return out


def _img(jpeg: bytes) -> dict:
    return {"mime_type": "image/jpeg", "data": jpeg}


def _call_gemini(model, parts: list, label: str) -> Optional[str]:
    import concurrent.futures
    for attempt in range(4):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(model.generate_content, parts)
                resp = fut.result(timeout=300)
            time.sleep(2)
            return resp.text
        except Exception as exc:
            logger.warning(f"  [{label}] attempt {attempt + 1} failed: {exc}")
            if attempt < 3:
                time.sleep(12 * (attempt + 1))
    return None


def _parse_flat_list(raw: Optional[str], label: str) -> Optional[List[str]]:
    if not raw:
        return None
    try:
        parsed = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        logger.error(f"  [{label}] JSON parse failed: {e}  raw={raw[:200]}")
        return None
    if isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, list):
                parsed = v
                break
    if not isinstance(parsed, list):
        logger.error(f"  [{label}] expected list, got {type(parsed).__name__}")
        return None
    return [str(c).strip() for c in parsed if c and str(c).strip()]


def _parse_list_of_lists(raw: Optional[str], label: str, expected: int) -> Optional[List[List[str]]]:
    if not raw:
        return None
    try:
        parsed = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        logger.error(f"  [{label}] JSON parse failed: {e}  raw={raw[:200]}")
        return None
    if not isinstance(parsed, list) or not all(isinstance(r, list) for r in parsed):
        logger.error(f"  [{label}] expected list-of-lists, got: {str(parsed)[:200]}")
        return None
    if len(parsed) != expected:
        logger.error(f"  [{label}] expected {expected} sublists, got {len(parsed)}: {parsed}")
        return None
    return [[str(c).strip() for c in row if c and str(c).strip()] for row in parsed]


def _has_placeholders(codes: List[str]) -> bool:
    return any(re.match(r'^Column_', c) for c in codes)


def _load_raw(path: Path):
    return json.loads(_strip_fences(path.read_text(encoding="utf-8")))


def _save_raw(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-target update functions
# ---------------------------------------------------------------------------

def _update_sm500_table(raw_dir: Path, model, pdf_path: Path,
                        page: int, match_all_numeric: bool, label: str) -> str:
    """Re-read one SM500 page; update the matching placeholder-column table."""
    imgs = _render_pages(pdf_path, [page])
    parts = [_SM500_HDR_PROMPT, f"--- PAGE {page} ---", _img(imgs[page])]
    raw = _call_gemini(model, parts, label)
    codes = _parse_flat_list(raw, label)

    if not codes:
        return f"FAIL (no parse)"
    print(f"  Gemini returned: {codes}")
    if _has_placeholders(codes):
        return f"SKIP (still placeholders: {codes})"

    raw_path = raw_dir / "SM500_tables_raw.json"
    data = _load_raw(raw_path)
    if match_all_numeric:
        pattern = re.compile(r'^Column_\d+$')
    else:
        pattern = re.compile(r'^Column_[A-Z]$')

    for t in data["tables"]:
        cols = t.get("submachine_columns", [])
        if cols and all(pattern.match(c) for c in cols):
            before = list(cols)
            t["submachine_columns"] = codes
            _save_raw(raw_path, data)
            print(f"  BEFORE: {before}")
            print(f"  AFTER:  {codes}")
            return "OK"

    return "NO_MATCH"


def _update_sm501b_table3(raw_dir: Path, model, pdf_path: Path) -> str:
    """Re-read SM501_B pages 14-15; update TABLE 3 PRODUCT SETTINGS."""
    label = "SM501_B TABLE3 PRODUCT"
    imgs = _render_pages(pdf_path, [14, 15])
    parts = [_SM501B_HDR_PROMPT, "--- PAGE 14 ---", _img(imgs[14]),
             "--- PAGE 15 ---", _img(imgs[15])]
    raw = _call_gemini(model, parts, label)
    codes = _parse_flat_list(raw, label)

    if not codes:
        return "FAIL (no parse)"
    print(f"  Gemini returned: {codes}")

    if len(codes) != 2:
        return f"SKIP (expected 2 codes, got {len(codes)}: {codes})"
    if _has_placeholders(codes):
        return f"SKIP (placeholders: {codes})"

    raw_path = raw_dir / "SM501_B_tables_raw.json"
    data = _load_raw(raw_path)
    for t in data["tables"]:
        cols = t.get("submachine_columns", [])
        # Target: table with value-fragment columns (whitespace or %)
        if cols and any(re.search(r'[\s%()]', c) for c in cols):
            before = list(cols)
            t["submachine_columns"] = codes
            _save_raw(raw_path, data)
            print(f"  BEFORE: {before}")
            print(f"  AFTER:  {codes}")
            return "OK"

    return "NO_MATCH"


def _update_dsmr_tables(raw_dir: Path, model, pdf_path: Path) -> str:
    """Re-read DSMR pages 16-18; update all 3 spec tables in order."""
    label = "DSMR 3 spec tables (pg16,17,18)"
    imgs = _render_pages(pdf_path, [16, 17, 18])
    parts = [_DSMR_MULTI_PROMPT,
             "--- PAGE 16 ---", _img(imgs[16]),
             "--- PAGE 17 ---", _img(imgs[17]),
             "--- PAGE 18 ---", _img(imgs[18])]
    raw = _call_gemini(model, parts, label)

    # Accept list-of-lists or try flat list (model may not follow format strictly)
    codes_per_table = None
    if raw:
        try:
            parsed = json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            logger.error(f"  [{label}] parse failed: {e}")
            return "FAIL (parse)"

        if isinstance(parsed, list) and all(isinstance(r, list) for r in parsed):
            if len(parsed) == 3:
                codes_per_table = [[str(c).strip() for c in row if c and str(c).strip()]
                                   for row in parsed]
            else:
                logger.error(f"  [{label}] expected 3 sublists, got {len(parsed)}: {parsed}")
                return f"FAIL (expected 3 sublists, got {len(parsed)})"
        elif isinstance(parsed, list):
            # Flat list — maybe model merged all codes; can't assign per-table
            logger.error(f"  [{label}] got flat list instead of list-of-lists: {parsed}")
            return f"FAIL (flat list: {parsed})"
        else:
            logger.error(f"  [{label}] unexpected format: {parsed}")
            return "FAIL (unexpected format)"

    if not codes_per_table:
        return "FAIL (no response)"

    for i, codes in enumerate(codes_per_table):
        print(f"  Table {i+1} (pg{16+i}): Gemini returned: {codes}")

    # Find all DM5* spec tables in order
    raw_path = raw_dir / "DSMR_tables_raw.json"
    data = _load_raw(raw_path)
    dm5_indices = [
        i for i, t in enumerate(data["tables"])
        if t.get("submachine_columns")
        and all(re.match(r'^DM5', c) for c in t["submachine_columns"])
    ]

    if len(dm5_indices) != 3:
        return f"NO_MATCH (expected 3 DM5* tables, found {len(dm5_indices)} at indices {dm5_indices})"

    updated = []
    for tbl_idx, codes in zip(dm5_indices, codes_per_table):
        if not codes:
            print(f"  Table at index {tbl_idx}: empty codes — skipping")
            continue
        t = data["tables"][tbl_idx]
        before = list(t["submachine_columns"])
        t["submachine_columns"] = codes
        print(f"  Table index {tbl_idx}: BEFORE={before}  AFTER={codes}")
        updated.append(tbl_idx)

    if updated:
        _save_raw(raw_path, data)
        return f"OK (updated tables at indices {updated})"
    return "NO_MATCH"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_stage_c(pdf_path: Path, raw_dir: Path) -> None:
    import os
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    print(f"\n{'='*60}")
    print(f"Stage C: 300-DPI header-only re-read")
    print(f"  PDF:     {pdf_path}")
    print(f"  raw_dir: {raw_dir}")
    print(f"{'='*60}\n")

    results = {}

    # ── SM500 TABLE2 @240V (page 7, Column_1..4) ──────────────────────────────
    print("─── SM500 TABLE2 @240V (page 7, Column_1..4) ───")
    r = _update_sm500_table(raw_dir, model, pdf_path, page=7,
                            match_all_numeric=True, label="SM500 TABLE2 @240V")
    results["SM500 TABLE2 @240V"] = r
    print(f"  → {r}\n")
    time.sleep(4)

    # ── SM500 TABLE2 2nd (page 8, Column_A..G) ────────────────────────────────
    print("─── SM500 TABLE2 2nd instance (page 8, Column_A..G) ───")
    r = _update_sm500_table(raw_dir, model, pdf_path, page=8,
                            match_all_numeric=False, label="SM500 TABLE2 2nd")
    results["SM500 TABLE2 2nd"] = r
    print(f"  → {r}\n")
    time.sleep(4)

    # ── SM501_B TABLE3 PRODUCT SETTINGS (pages 14-15) ─────────────────────────
    print("─── SM501_B TABLE3 PRODUCT SETTINGS (pages 14-15) ───")
    r = _update_sm501b_table3(raw_dir, model, pdf_path)
    results["SM501_B TABLE3"] = r
    print(f"  → {r}\n")
    time.sleep(4)

    # ── DSMR 3 spec tables (pages 16-18, one call) ────────────────────────────
    print("─── DSMR 3 spec tables (pages 16, 17, 18 — single call) ───")
    r = _update_dsmr_tables(raw_dir, model, pdf_path)
    results["DSMR 3 tables"] = r
    print(f"  → {r}\n")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print("Stage C summary:")
    for k, v in results.items():
        mark = "✓" if v.startswith("OK") else "✗"
        print(f"  {mark} {k}: {v}")
    print()
    print("Next step: python run_functional.py --reprocess outputs/functional")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="?",
                        default="source/FUnctional Testing WI_Five series.pdf")
    parser.add_argument("output_dir", nargs="?", default="outputs/functional")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    raw_dir = Path(args.output_dir) / "raw"

    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)
    if not raw_dir.exists():
        print(f"ERROR: raw/ not found under {args.output_dir}")
        sys.exit(1)

    run_stage_c(pdf_path, raw_dir)
