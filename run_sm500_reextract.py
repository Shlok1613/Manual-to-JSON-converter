"""
SM500 two-table extraction — single API call, pages 7+8.

LAYOUT (confirmed from source):
  Page 7: LED TABLE 01 (Group 1) + at the bottom: HEADER ROW of TABLE 2 @240V (Group 1, 6 cols).
  Page 8: DATA ROWS of TABLE 2 @240V at top (no header visible — it is on page 7).
          TABLE 2 2nd (Group 2, 5 cols) complete below (header + all data rows).

Strategy: send pages 7+8 together so Gemini sees the cross-page header.
Ask for TWO tables in one call. Validate strictly before saving either.

Usage:
    python run_sm500_reextract.py [pdf] [output_dir]

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
from typing import List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt — two cross-page tables, single call, no column names passed in
# ---------------------------------------------------------------------------

_TWO_TABLE_PROMPT = """\
These two scanned pages (first then second) are from a Functional Testing specification.

PAGE 1 LAYOUT:
  - TOP portion: a table titled "TABLE 01" or "LED INDICATIONS" — rows have values
    like "Continuous ON", "Blinking", "OFF". SKIP THIS TABLE ENTIRELY. Do not return it.
  - BOTTOM portion: the column HEADER ROW of a PRODUCT SETTINGS table titled
    "TABLE 2" with subtitle "@240V" or "@ 240 VAC". This header row contains
    model codes (alphanumeric codes like MD71B9, MG73BF, etc.) under a banner
    "Acceptable Limits". The DATA ROWS of this table are NOT on PAGE 1 — they
    are on PAGE 2.

PAGE 2 LAYOUT:
  - TOP portion: the DATA ROWS of the TABLE 2 @240V whose header was at the
    bottom of PAGE 1. These rows have NO visible header on PAGE 2 — the header
    is on PAGE 1. The parameter values will be voltage-related terms such as
    "Under Voltage", "Over Voltage", "UV/OV Hysteresis", "Delay" etc.
    Data values will be VOLTAGE RANGES like "194 to 214 VAC" or percentages.
  - LOWER portion: a SECOND complete TABLE 2 with its own header + all data rows.
    This second table also has voltage-related parameter names and voltage values.

TASK: Extract BOTH product-settings (voltage-data) tables.
  Table 1 (UPPER): header from PAGE 1 bottom + data rows from PAGE 2 top.
  Table 2 (LOWER): complete table on PAGE 2 (lower portion).

Do NOT return any LED INDICATIONS table. If a table's rows contain values like
"Continuous ON", "Blinking", or "OFF" (not voltage values), SKIP IT.

Table structure:
  Column 1 = "Parameter" | Column 2 = "Setting" | remaining = model-code columns.
  If column header cells have a colored or shaded background, read the text inside.

Return a JSON array of EXACTLY 2 objects (upper settings table first):
[
  {
    "kind": "spec",
    "title": "<upper settings table title as printed>",
    "submachine_columns": ["<code1>", "<code2>", ...],
    "rows": [
      {"parameter": "<param>", "setting": "<setting>", "values": ["<v1>", "<v2>", ...]},
      ...
    ]
  },
  {
    "kind": "spec",
    "title": "<lower settings table title as printed>",
    "submachine_columns": ["<code1>", ...],
    "rows": [...]
  }
]

MERGED CELL RULE (critical):
  PDF tables often use vertically merged cells in the "Parameter" column — one label
  (e.g., "Under Voltage") spans multiple rows for different thresholds.
  For EVERY row, the "parameter" field MUST contain a descriptive text label
  (e.g., "Under Voltage", "Over Voltage", "ON Delay", "OFF Delay").
  If a row's Parameter cell appears blank or merged with the row above: REPEAT the
  parameter label from the nearest row above that has a real text label.
  NEVER put a setting/threshold value (like "85% (204 V)" or "5s" or "72% (173 VAC)")
  in the "parameter" field. Those belong in "setting" or "values".

STRICT RULES:
- Upper table submachine_columns: read from the header at the BOTTOM of PAGE 1.
- values: EXACTLY one entry per submachine_column per row, left-to-right order.
  len(values) MUST equal len(submachine_columns) for EVERY row without exception.
- Use "NA" for blank or not-applicable cells.
- Include ALL data rows; do not skip any.
- Do NOT merge the two tables. Return ONLY valid JSON. No markdown. No explanation.
"""

# ---------------------------------------------------------------------------
# Stage-C verified headers (300-DPI independent read; used for header
# validation after extraction; not passed into the prompt).
# ---------------------------------------------------------------------------
_SC_HEADERS = {
    "group1": ["MD71B9", "MD71BH", "MD71BF", "MG73B9", "MG73BH", "MG73BF"],   # 6 cols
    "group2": ["MGH3BF", "MGH3BY", "MGH3BH", "MG73BR", "MGI3BF"],              # 5 cols
}
_SC_N = {"group1": 6, "group2": 5}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    return raw.strip()


def _render_page(pdf_path: Path, page_num: int, dpi: int = 300) -> bytes:
    import fitz
    doc = fitz.open(str(pdf_path))
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = doc[page_num - 1].get_pixmap(matrix=matrix)
    jpeg = pix.tobytes("jpeg")
    doc.close()
    logger.info(f"  Rendered page {page_num} at {dpi} DPI ({len(jpeg)//1024} KB)")
    return jpeg


def _call_gemini(model, parts: list, label: str) -> Optional[str]:
    import concurrent.futures
    for attempt in range(3):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(model.generate_content, parts)
                resp = fut.result(timeout=360)
            time.sleep(2)
            return resp.text
        except Exception as exc:
            if "429" in str(exc):
                logger.error(f"  [{label}] QUOTA EXCEEDED (429) — rotate key")
                raise
            logger.warning(f"  [{label}] attempt {attempt + 1} failed: {exc}")
            if attempt < 2:
                time.sleep(15 * (attempt + 1))
    return None


def _parse_two_tables(raw: Optional[str], label: str) -> Optional[List[dict]]:
    if not raw:
        logger.error(f"  [{label}] no response from Gemini")
        return None
    try:
        parsed = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        logger.error(f"  [{label}] JSON parse failed: {e}\n  raw={raw[:500]}")
        return None
    if not isinstance(parsed, list):
        logger.error(f"  [{label}] expected list, got {type(parsed).__name__}: {str(parsed)[:200]}")
        return None
    if len(parsed) != 2:
        logger.error(f"  [{label}] expected 2 tables, got {len(parsed)}")
        return None
    for i, t in enumerate(parsed):
        if not isinstance(t, dict) or "submachine_columns" not in t or "rows" not in t:
            logger.error(f"  [{label}] table {i} missing keys: {list(t.keys()) if isinstance(t, dict) else type(t)}")
            return None
    return parsed


def _assign_groups(tables: List[dict], label: str) -> Optional[Tuple[dict, dict]]:
    """
    Assign upper/lower tables to group1 (6-col) and group2 (5-col) by column count.
    Handles ordering as returned by Gemini (may be swapped).
    Returns (group1_table, group2_table) or None on failure.
    """
    n0 = len(tables[0].get("submachine_columns") or [])
    n1 = len(tables[1].get("submachine_columns") or [])

    # Ideal: first returned = upper (6-col group1), second = lower (5-col group2)
    if n0 == 6 and n1 == 5:
        print(f"  [{label}] ordering correct: upper=6-col, lower=5-col")
        return tables[0], tables[1]
    elif n0 == 5 and n1 == 6:
        print(f"  [{label}] WARN: ordering reversed — swapping (lower=5-col came first)")
        return tables[1], tables[0]
    else:
        print(f"  [{label}] FAIL: unexpected column counts {n0} and {n1} (expected 6 and 5)")
        return None


def _validate_headers(tbl: dict, group: str, label: str) -> bool:
    """
    Compare extracted headers to Stage-C verified set.
    Applies Stage-C fallback only if all headers are blank but count matches.
    Returns True if headers are acceptable.
    """
    sc = _SC_HEADERS[group]
    expected_n = _SC_N[group]
    cols = list(tbl.get("submachine_columns") or [])

    if len(cols) != expected_n:
        print(f"  [{label}] FAIL: {group} expects {expected_n} cols, got {len(cols)}")
        return False

    all_empty = all(c.strip() == "" for c in cols)
    if all_empty:
        print(f"  [{label}] headers unreadable (all empty) — applying Stage-C headers")
        tbl["submachine_columns"] = list(sc)
        return True

    if set(cols) == set(sc):
        print(f"  [{label}] headers match Stage C exactly: {cols}")
        return True

    overlap = set(cols) & set(sc)
    if not overlap:
        print(f"  [{label}] FAIL: zero overlap with Stage-C headers")
        print(f"    Stage-C : {sc}")
        print(f"    Got     : {cols}")
        return False

    # Partial match — warn but apply Stage-C
    print(f"  [{label}] WARN: header partial drift vs Stage C")
    print(f"    Stage-C : {sc}")
    print(f"    Got     : {cols}")
    print(f"  [{label}] Applying Stage-C headers (overlap: {sorted(overlap)})")
    tbl["submachine_columns"] = list(sc)
    return True


def _validate_value_counts(tbl: dict, group: str, label: str) -> bool:
    """pad_trim_ban: every row must have exactly n values."""
    n = _SC_N[group]
    rows = tbl.get("rows") or []
    ok = True
    for i, row in enumerate(rows):
        vals = row.get("values") or []
        if len(vals) != n:
            print(f"  [{label}] FAIL row {i} "
                  f"'{row.get('parameter')}/{row.get('setting')}': "
                  f"{len(vals)} values ≠ {n} cols")
            ok = False
    return ok


def _bleed_check(g1_tbl: dict, g2_tbl: dict) -> bool:
    """
    Verify the two tables did not bleed into each other:
    - Group1 cols must contain NONE of the Group2 codes
    - Group2 cols must contain NONE of the Group1 codes
    """
    g1_cols = set(g1_tbl.get("submachine_columns") or [])
    g2_cols = set(g2_tbl.get("submachine_columns") or [])
    sc1 = set(_SC_HEADERS["group1"])
    sc2 = set(_SC_HEADERS["group2"])

    g1_bleed = g1_cols & sc2  # Group2 codes appearing in Group1 table
    g2_bleed = g2_cols & sc1  # Group1 codes appearing in Group2 table

    if g1_bleed:
        print(f"  BLEED FAIL: Group2 codes {sorted(g1_bleed)} appeared in upper (Group1) table")
        return False
    if g2_bleed:
        print(f"  BLEED FAIL: Group1 codes {sorted(g2_bleed)} appeared in lower (Group2) table")
        return False

    print("  Bleed check: PASS — no cross-group codes in either table")
    return True


def _audit_print(tbl: dict, group: str) -> None:
    """Print first 3 rows + last row for spot-check."""
    rows = tbl.get("rows") or []
    cols = tbl.get("submachine_columns") or []
    print(f"    title: {tbl.get('title', '?')!r}")
    print(f"    cols ({len(cols)}): {cols}")
    print(f"    rows: {len(rows)}")
    for i, row in enumerate(rows[:3]):
        print(f"      [{i}] {row.get('parameter')!r}/{row.get('setting')!r} "
              f"→ {row.get('values')}")
    if len(rows) > 3:
        row = rows[-1]
        print(f"      [{len(rows)-1}] {row.get('parameter')!r}/{row.get('setting')!r} "
              f"→ {row.get('values')}")
        print(f"      ...")


def _load_raw(path: Path) -> dict:
    return json.loads(_strip_fences(path.read_text(encoding="utf-8")))


def _save_raw(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_settings_indices(data: dict) -> List[int]:
    """Find spec tables with 'PRODUCT SETTINGS' in title and model-code headers."""
    out = []
    for i, t in enumerate(data.get("tables") or []):
        if (t.get("kind") == "spec"
                and "PRODUCT SETTINGS" in (t.get("title") or "").upper()
                and any(re.match(r"^[A-Za-z]{2,}", c)
                        for c in (t.get("submachine_columns") or []))):
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(pdf_path: Path, raw_dir: Path) -> None:
    import os
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    raw_path = raw_dir / "SM500_tables_raw.json"
    data = _load_raw(raw_path)

    print(f"\n{'='*60}")
    print("SM500 re-extract — pages 7+8 single call")
    print(f"  PDF: {pdf_path}")
    print(f"  raw: {raw_path}")
    print(f"{'='*60}\n")

    # Find target indices dynamically
    idx_list = _find_settings_indices(data)
    if len(idx_list) != 2:
        print(f"ERROR: expected 2 PRODUCT SETTINGS spec tables with model-code headers, "
              f"found {len(idx_list)} at {idx_list}")
        print("  Check raw JSON — settings tables may have been reclassified or saved already.")
        sys.exit(1)
    idx_g1, idx_g2 = idx_list[0], idx_list[1]
    print(f"Target indices: {idx_g1} (Group1, 6-col) and {idx_g2} (Group2, 5-col)")

    # Render pages 7 and 8
    print("Rendering pages 7 + 8 at 300 DPI...")
    jpeg7 = _render_page(pdf_path, 7)
    jpeg8 = _render_page(pdf_path, 8)

    # Single Gemini call
    print("Calling Gemini (single call, both pages)...")
    parts = [
        _TWO_TABLE_PROMPT,
        "--- PAGE 7 ---",
        {"mime_type": "image/jpeg", "data": jpeg7},
        "--- PAGE 8 ---",
        {"mime_type": "image/jpeg", "data": jpeg8},
    ]
    raw_resp = _call_gemini(model, parts, "SM500-pg7+8")
    tables = _parse_two_tables(raw_resp, "SM500-pg7+8")

    if tables is None:
        print("\nFAIL: could not parse 2-table response. Not saving.")
        sys.exit(1)

    # Assign to groups by column count
    result = _assign_groups(tables, "assign")
    if result is None:
        print("\nFAIL: column count mismatch. Not saving.")
        sys.exit(1)
    g1_tbl, g2_tbl = result

    # Validate headers
    print("\n--- Validating Group1 (6-col) table ---")
    if not _validate_headers(g1_tbl, "group1", "Group1"):
        print("\nFAIL: Group1 headers invalid. Not saving.")
        sys.exit(1)

    print("\n--- Validating Group2 (5-col) table ---")
    if not _validate_headers(g2_tbl, "group2", "Group2"):
        print("\nFAIL: Group2 headers invalid. Not saving.")
        sys.exit(1)

    # Validate value counts (pad_trim_ban)
    print("\n--- pad_trim_ban: Group1 ---")
    g1_ok = _validate_value_counts(g1_tbl, "group1", "Group1")
    print("--- pad_trim_ban: Group2 ---")
    g2_ok = _validate_value_counts(g2_tbl, "group2", "Group2")

    if not (g1_ok and g2_ok):
        print("\nFAIL: value-count mismatch. Not saving.")
        sys.exit(1)

    print("  pad_trim_ban: PASS on both tables")

    # Bleed check
    print("\n--- Bleed check ---")
    if not _bleed_check(g1_tbl, g2_tbl):
        print("\nFAIL: bleed detected. Not saving.")
        sys.exit(1)

    # Audit print for spot-check
    print("\n--- Audit: Group1 (upper, 6-col) ---")
    _audit_print(g1_tbl, "group1")
    print("\n--- Audit: Group2 (lower, 5-col) ---")
    _audit_print(g2_tbl, "group2")

    # Save
    print(f"\nAll checks passed. Saving to {raw_path}...")
    old_g1 = data["tables"][idx_g1].get("title", "?")
    old_g2 = data["tables"][idx_g2].get("title", "?")
    data["tables"][idx_g1] = g1_tbl
    data["tables"][idx_g2] = g2_tbl
    _save_raw(raw_path, data)

    print(f"  index {idx_g1}: '{old_g1}' → '{g1_tbl.get('title', '?')}'")
    print(f"  index {idx_g2}: '{old_g2}' → '{g2_tbl.get('title', '?')}'")
    print(f"\nSaved. Next step:")
    print("  python run_functional.py --reprocess outputs/functional")


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

    run(pdf_path, raw_dir)
