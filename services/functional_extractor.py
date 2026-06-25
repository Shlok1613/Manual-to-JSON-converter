"""
Functional Testing PDF extractor — separate path from the WI pipeline.

Table model (v3.1):
  - Every spec table: [Parameter | Setting | sub1 | sub2 | ...]
  - Vertically-merged parameter cells repeated on each setting row.
  - Horizontally-merged value cells repeated once per column spanned.
  - Multiple tables per family; submachine set = UNION of spec tables.
  - Integrity failures mark a table "unverified" (excluded from workbook).

Integrity checks (ALL mandatory; skipped check = family is NOT clean):
  1. pad_trim_ban         — row length mismatch → table unverified
  2. unreadable_header    — Column_X placeholder → table unverified
  3. non_model_column     — voltage strings as cols → table aux
  4. value_fragment       — whitespace + value chars in col → table unverified
  5. split_header         — flag only (informational)
  6. cross_source_prefix_vote — requires title_submachines from meta file

CLEAN = all 6 checks ran AND zero flags.

Modes:
  Full:       render pages → Gemini → parse + checks → write + report
  Reprocess:  load saved raw/*.json → parse + checks → write + report  (no API)
"""

import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side

logger = logging.getLogger(__name__)

DPI = 150
VISION_MODEL = "gemini-2.5-flash"
_CALL_TIMEOUT = 300
_MAX_IMAGES = 12

ALL_CHECKS = [
    "pad_trim_ban",
    "unreadable_header",
    "non_model_column",
    "value_fragment",
    "split_header",
    "cross_source_prefix_vote",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PageMeta:
    page_num: int
    content_type: str
    family_label: Optional[str] = None
    submachines_in_title: List[str] = field(default_factory=list)
    table_title: Optional[str] = None


@dataclass
class FamilyInfo:
    label: str
    page_range: Tuple[int, int]
    # None = unknown (no meta/raw-JSON available); [] = known-empty (title had no codes);
    # [...] = known codes from PDF title banner
    title_submachines: Optional[List[str]]
    all_pages: List[int]
    # False = title_submachines was derived from raw JSON spec cols (proxy);
    # prefix-vote runs trivially (same source as table data) — cannot catch OCR errors
    title_from_external: bool = True


@dataclass
class SpecRow:
    parameter: str
    setting: str
    values: List[str]            # one per submachine_column; NOT padded/trimmed


@dataclass
class FuncTable:
    kind: str                    # "spec" | "aux" | "unverified"
    title: str
    submachine_columns: List[str]
    rows: List[SpecRow]
    flags: List[str] = field(default_factory=list)


@dataclass
class FamilyExtract:
    info: FamilyInfo
    tables: List[FuncTable] = field(default_factory=list)
    raw_json_path: Optional[Path] = None
    flags: List[str] = field(default_factory=list)
    checks_run: List[str] = field(default_factory=list)
    # Checks that are N/A: applicable in principle but no independent source was available.
    # N/A is distinct from "ran" (verified) and "could not run" (hard failure).
    checks_na: List[str] = field(default_factory=list)

    def submachine_union(self) -> List[str]:
        seen, out = set(), []
        for t in self.tables:
            if t.kind == "spec":
                for s in t.submachine_columns:
                    if s not in seen:
                        seen.add(s)
                        out.append(s)
        return out

    def is_clean(self) -> bool:
        """True only if ALL 6 checks ran or were N/A, AND zero non-INFO flags."""
        real_flags = [f for f in self.flags if not f.startswith("INFO:")]
        covered = set(self.checks_run) | set(self.checks_na)
        return all(c in covered for c in ALL_CHECKS) and len(real_flags) == 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_pages(pdf_path: Path, dpi: int = DPI) -> List[bytes]:
    doc = fitz.open(str(pdf_path))
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    out = []
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        out.append(pix.tobytes("jpeg"))
    doc.close()
    logger.info(f"Rendered {len(out)} pages at {dpi} DPI from {pdf_path.name}")
    return out


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------

def _get_client():
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    return genai


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    return raw.strip()


def _call_gemini(model, parts: list, label: str) -> Optional[str]:
    import concurrent.futures
    for attempt in range(4):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(model.generate_content, parts)
                resp = fut.result(timeout=_CALL_TIMEOUT)
            time.sleep(2)
            return resp.text
        except Exception as exc:
            logger.warning(f"  [{label}] attempt {attempt+1} failed: {exc}")
            if attempt < 3:
                time.sleep(10 * (attempt + 1))
    return None


def _img(jpeg_bytes: bytes) -> dict:
    return {"mime_type": "image/jpeg", "data": jpeg_bytes}


# ---------------------------------------------------------------------------
# "/" header expansion with sibling-length correction
# ---------------------------------------------------------------------------

def _expand_slash_headers(raw_headers: List[str]) -> List[str]:
    """
    Expand '/' packed column headers.
    Uses the modal length of clean (no-'/') sibling headers to determine correct prefix,
    avoiding inherited OCR errors from the (possibly misread) first token.
    """
    clean_lengths = [len(h) for h in raw_headers if "/" not in h and h.strip()]
    expected_len: Optional[int] = None
    if clean_lengths:
        expected_len = Counter(clean_lengths).most_common(1)[0][0]

    result: List[str] = []
    for header in raw_headers:
        parts = [p.strip() for p in header.split("/") if p.strip()]
        if len(parts) == 1:
            result.append(parts[0])
            continue
        first = parts[0]
        ref_len = expected_len if expected_len is not None else len(first)
        expanded = [first]
        for part in parts[1:]:
            if len(part) >= ref_len:
                expanded.append(part)
            else:
                prefix_len = ref_len - len(part)
                if 0 < prefix_len <= len(first):
                    expanded.append(first[:prefix_len] + part)
                else:
                    expanded.append(part)
        result.extend(expanded)
    return result


# ---------------------------------------------------------------------------
# Row sanity check
# ---------------------------------------------------------------------------

def _torn_row_flag(parameter: str) -> Optional[str]:
    """Return a flag string if parameter looks like a numeric/symbolic setting with no text label."""
    p = parameter.strip()
    if not p:
        return None
    if len(re.findall(r"[A-Za-z]", p)) < 2:
        return f"probable torn row: parameter='{p}' has no text label"
    return None


# ---------------------------------------------------------------------------
# Integrity-check helpers (Stage 2 / Stage B)
# ---------------------------------------------------------------------------

# (b) Unreadable-header guard — placeholder names Gemini invents for unread columns
_PLACEHOLDER_COL = re.compile(r"^Column[_\s]?\w*$", re.IGNORECASE)


def _is_placeholder(col: str) -> bool:
    return not col.strip() or bool(_PLACEHOLDER_COL.match(col.strip()))


# (a) Non-model-column guard — voltage / numeric strings that are not model codes
_NON_MODEL_COL = re.compile(
    r"^[\d.]+\s*(VAC|VAC\s*P-?N|V|Hz|A|W|mA)?$",
    re.IGNORECASE,
)


def _is_non_model(col: str) -> bool:
    return bool(_NON_MODEL_COL.match(col.strip()))


def _is_value_fragment(col: str) -> bool:
    """
    True if column header is a broken value string rather than a model code.
    Condition: contains whitespace AND suffix after whitespace contains digits, %,
    (, ), +/-, ±.
    Exception: trailing parenthesized ALL-ALPHA suffix like '(DAIKIN)' is stripped
    before checking so 'DM5120-D (DAIKIN)' is NOT flagged.
    """
    col = col.strip()
    if not re.search(r"\s", col):
        return False  # no whitespace at all → can't be a split fragment
    # Strip trailing parenthesized ALL-ALPHA suffix (brand names, series names)
    cleaned = re.sub(r"\s*\([A-Za-z\s]+\)\s*$", "", col).strip()
    parts = re.split(r"\s+", cleaned, maxsplit=1)
    if len(parts) < 2:
        return False  # whitespace was only in the stripped suffix
    suffix = parts[1]
    return bool(re.search(r"[%()±+]|\d|\+/?-", suffix))


def _alpha_prefix(s: str, n: int = 3) -> str:
    """Return first n letters of s (used for prefix-vote comparison)."""
    m = re.match(r"^([A-Za-z]+)", s.strip())
    return m.group(1)[:n].upper() if m else ""


def _derive_from_spec_cols(raw_data: dict) -> List[str]:
    """
    Derive a proxy for title_submachines from spec table submachine_columns in raw JSON.
    Used in reprocess Source 3 when no external meta exists.
    The resulting proxy contains the same names as the raw table headers (unexpanded),
    so prefix-vote always passes trivially — it cannot detect OCR errors without an
    independent title source.
    Returns [] if no spec tables exist (known-empty → prefix-vote trivially passes).
    """
    seen: set = set()
    out: List[str] = []
    for t in (raw_data.get("tables") or []):
        if t.get("kind") != "spec":
            continue
        for col in (t.get("submachine_columns") or []):
            c = str(col).strip()
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    return out


def _apply_integrity_checks(
    tables: List[FuncTable],
    family_info: FamilyInfo,
    flags: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Mutate table.kind in place based on all integrity guards.
    Returns (checks_run sorted, checks_na sorted).
    checks_na holds checks that are N/A: applicable in principle but no independent
    source was available (e.g., prefix-vote when title_submachines is proxy-derived).
    Appends flags (including "INTEGRITY CHECK COULD NOT RUN: ...") to shared list.
    """
    checks_run: set = {"pad_trim_ban"}  # always runs in _parse_table
    checks_na: set = set()

    # --- Per-table checks ---
    ran_per_table = False
    for t in [x for x in tables if x.kind == "spec"]:
        cols = t.submachine_columns
        if not cols:
            continue

        ran_per_table = True
        # (b) Unreadable-header guard
        checks_run.add("unreadable_header")
        placeholders = [c for c in cols if _is_placeholder(c)]
        if placeholders:
            t.kind = "unverified"
            flags.append(
                f"[{t.title}] unreadable column headers {placeholders} → unverified, excluded from workbook"
            )
            continue

        # (a) Non-model-column guard
        checks_run.add("non_model_column")
        non_models = [c for c in cols if _is_non_model(c)]
        if len(non_models) > len(cols) / 2:
            t.kind = "aux"
            flags.append(
                f"[{t.title}] columns appear to be voltage values not model codes "
                f"{non_models} → reclassified aux"
            )
            continue

        # (NEW) Value-fragment guard
        checks_run.add("value_fragment")
        fragments = [c for c in cols if _is_value_fragment(c)]
        if fragments:
            t.kind = "unverified"
            flags.append(
                f"[{t.title}] value-fragment column headers {fragments} → unverified, excluded from workbook"
            )
            continue

        # Split-header detection (flag only; alpha-paren suffixes exempted)
        checks_run.add("split_header")
        for col in cols:
            stripped_col = re.sub(r"\s*\([A-Za-z\s]+\)\s*$", "", col).strip()
            if re.search(r"\s+[\d.%()±+\-]+", stripped_col):
                flags.append(f"[{t.title}] probable split header: '{col}'")

    # Per-table checks trivially pass when there were no spec tables to examine
    # (SM301-style families: jig-only, no spec data → all checks "not-applicable")
    if not ran_per_table:
        checks_run.update(["unreadable_header", "non_model_column", "value_fragment", "split_header"])

    # (c) Cross-source prefix vote
    # None              → could not run (hard failure; flag it)
    # proxy (not external) → N/A: derived from same columns, self-comparison not useful
    # [] (known-empty)  → trivially passes (no codes to compare)
    # [...] (external)  → run actual comparison
    if family_info.title_submachines is None:
        flags.append(
            "INTEGRITY CHECK COULD NOT RUN: cross_source_prefix_vote "
            "(title_submachines unknown — run full extraction to generate meta)"
        )
    elif not family_info.title_from_external:
        # Proxy: title_submachines was derived from this table's own columns.
        # Comparing them would be a self-comparison — not a real verification.
        checks_na.add("cross_source_prefix_vote")
    elif family_info.title_submachines:
        checks_run.add("cross_source_prefix_vote")
        title_prefixes = [_alpha_prefix(s) for s in family_info.title_submachines if s]
        title_pv = Counter(title_prefixes).most_common(1)[0][0] if title_prefixes else ""
        for t in tables:
            if t.kind != "spec" or not t.submachine_columns:
                continue
            col_prefixes = [_alpha_prefix(c) for c in t.submachine_columns]
            col_pv = Counter(col_prefixes).most_common(1)[0][0] if col_prefixes else ""
            if (col_pv and title_pv and col_pv != title_pv
                    and all(p == col_pv for p in col_prefixes)):
                flags.append(
                    f"[{t.title}] uniform OCR prefix mismatch: "
                    f"table='{col_pv}*' vs title='{title_pv}*' (flag only — do not auto-correct)"
                )
    else:
        # Known-empty: title had no model codes → trivially no mismatch possible
        checks_run.add("cross_source_prefix_vote")

    return sorted(checks_run), sorted(checks_na)


def _check_title_coverage(
    tables: List[FuncTable],
    family_info: FamilyInfo,
    flags: List[str],
) -> None:
    """
    INFO-level report of title vs table submachine coverage differences.
    Subset mismatch is EXPECTED (some title machines appear only in Setting text).
    Never affects CLEAN status.
    """
    if not family_info.title_submachines:
        return  # None or [] — nothing to compare
    if not family_info.title_from_external:
        return  # derived proxy — comparison would be circular (same source as table data)
    table_subs = set()
    for t in tables:
        if t.kind == "spec":
            table_subs.update(t.submachine_columns)
    title_subs = set(family_info.title_submachines)
    missing = title_subs - table_subs
    extra = table_subs - title_subs
    if missing:
        flags.append(
            f"INFO: title subset coverage: {sorted(missing)} in title but not in any "
            "spec table (may appear only in Setting text — expected)"
        )
    if extra:
        flags.append(f"INFO: table coverage wider than title: {sorted(extra)}")


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def _parse_table(raw_t: dict, flags: List[str]) -> FuncTable:
    """
    Parse one raw Gemini table dict.
    pad_trim_ban: if any spec row has len(values) != len(submachine_columns),
    mark the TABLE kind='unverified' — never pad or trim.
    """
    kind = raw_t.get("kind", "spec")
    title = str(raw_t.get("title") or "").strip()
    raw_cols = [str(c).strip() for c in (raw_t.get("submachine_columns") or []) if c]
    expanded_cols = _expand_slash_headers(raw_cols) if kind == "spec" else []
    # Normalize whitespace around hyphens in model codes ('DMS120 - D' → 'DMS120-D')
    expanded_cols = [re.sub(r'\s*-\s*', '-', c) for c in expanded_cols]

    rows: List[SpecRow] = []
    has_mismatch = False

    for raw_row in (raw_t.get("rows") or []):
        param = str(raw_row.get("parameter") or "").strip()
        setting = str(raw_row.get("setting") or "").strip()
        vals = [str(v).strip() for v in (raw_row.get("values") or [])]

        if kind == "spec":
            n_col = len(expanded_cols)

            # Try to re-expand if Gemini matched raw (unexpanded) header count
            if len(vals) == len(raw_cols) and len(vals) != n_col:
                re_vals: List[str] = []
                for h, v in zip(raw_cols, vals):
                    re_vals.extend([v] * len(_expand_slash_headers([h])))
                vals = re_vals

            if len(vals) != n_col:
                flags.append(
                    f"[{title}] row '{param}'/'{setting}': "
                    f"{len(vals)} values vs {n_col} columns → table unverified"
                )
                has_mismatch = True
                # Keep vals as-is — no padding, no trimming

            flag = _torn_row_flag(param)
            if flag:
                flags.append(f"[{title}] {flag}")

        rows.append(SpecRow(parameter=param, setting=setting, values=vals))

    final_kind = "unverified" if (kind == "spec" and has_mismatch) else kind
    return FuncTable(kind=final_kind, title=title, submachine_columns=expanded_cols, rows=rows)


def _parse_family_tables(
    raw_json_str: str,
    family_info: FamilyInfo,
) -> Tuple[List[FuncTable], List[str], List[str], List[str]]:
    """
    Parse saved raw Gemini JSON and apply all integrity checks.
    Returns (tables, flags, checks_run, checks_na).
    checks_na: checks that are N/A (no independent source; not a failure).
    Used in both full-pipeline and --reprocess modes.
    """
    flags: List[str] = []
    try:
        data = json.loads(_strip_fences(raw_json_str))
    except json.JSONDecodeError as e:
        return [], [f"JSON parse error: {e}"], ["pad_trim_ban"], []

    raw_tables = data.get("tables") or []
    tables = [_parse_table(rt, flags) for rt in raw_tables]

    checks_run, checks_na = _apply_integrity_checks(tables, family_info, flags)
    _check_title_coverage(tables, family_info, flags)

    logger.info(
        f"  [{family_info.label}] parsed: "
        + ", ".join(f"{t.kind}:{t.title[:25]}" for t in tables)
        + f"  flags={len(flags)}"
        + f"  checks={checks_run}"
        + (f"  na={checks_na}" if checks_na else "")
    )
    return tables, flags, checks_run, checks_na


# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
You are analyzing pages from a scanned manufacturing Functional Testing specification.
N pages are shown, each labelled "=== PAGE X ===".

A new FAMILY starts when you see a COLORED TITLE BAR (any background color) that contains
the words "Functional Testing" in any order. Examples:
  "Process: Functional Testing SPPR (MAC04D0100/...)"
  "SM500 Functional Testing"
  "DSMR Functional Testing (DMS110 / DMS120 ...)"

Classify EVERY page. Return a JSON array:

[
  {
    "page_num": 1,
    "content_type": "family_start",
    "family_label": "SPPR",
    "submachines_in_title": ["MAC04D0100", "MAC04D0121"]
  },
  {
    "page_num": 2,
    "content_type": "procedure"
  },
  {
    "page_num": 3,
    "content_type": "table",
    "table_title": "TABLE 1: LED Indications"
  }
]

content_type:
  "family_start" — colored "Functional Testing" title bar
  "procedure"    — numbered steps or prose, no data table
  "table"        — data table with parameter rows and submachine value columns
  "aux_table"    — auxiliary table (JIG LED, Firmware — no spec value columns)
  "mixed"        — title bar AND a data table on the same page

For "family_start"/"mixed": include family_label and submachines_in_title ([] if none visible).
Do NOT merge different families. Each colored title bar = a new family.
If uncertain → "procedure".

Return ONLY valid JSON. No explanation.
"""


# ---------------------------------------------------------------------------
# Table extraction prompt
# ---------------------------------------------------------------------------

_TABLE_EXTRACT_PROMPT = """\
These pages are from ONE product family in a Functional Testing specification.

SPEC TABLE STRUCTURE:
  Columns: | Parameter | Setting | <sub1> | <sub2> | ... |
  - Two fixed leading columns: "Parameter" (group name) and "Setting" (specific value)
  - Then N submachine model-code columns under an "Acceptable Limits" header
  - VERTICAL MERGE: a Parameter cell spanning rows → repeat parameter text on each row
  - HORIZONTAL MERGE: a value cell spanning N columns → repeat that value N times

AUX TABLES (JIG LED Indication, Firmware Version, etc.): no submachine columns.

WORKED EXAMPLE:
  Visual:
    | Parameter | Setting | MG63BF  | MG63BH      |
    | ON Delay  | 5s      | 4-6 s   | NA          |
    | (merged)  | 9s      | NA      | 7.5-10.5 s  |
  Output:
    {"kind":"spec","title":"TABLE 2 ...","submachine_columns":["MG63BF","MG63BH"],
     "rows":[
       {"parameter":"ON Delay","setting":"5s","values":["4-6 s","NA"]},
       {"parameter":"ON Delay","setting":"9s","values":["NA","7.5-10.5 s"]}
     ]}

Output JSON:
{
  "tables": [
    {
      "kind": "spec",
      "title": "exact table title as printed",
      "submachine_columns": ["model1", "model2/3"],
      "rows": [
        {"parameter": "...", "setting": "...", "values": ["val1", "val2"]}
      ]
    }
  ]
}

Rules:
  1. submachine_columns: copy model codes EXACTLY as printed, including "/" (do NOT split).
  2. len(values) MUST equal len(submachine_columns) for every spec row.
  3. Repeat merged parameter text on each setting row.
  4. Repeat merged value for each column spanned.
  5. "NA" stays "NA".
  6. No Setting column → setting="" (empty string).
  7. List ALL tables in order. Include ALL rows.

Return ONLY valid JSON. No markdown. No explanation.
"""


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

def classify_all_pages(page_jpegs: List[bytes]) -> List[PageMeta]:
    genai = _get_client()
    model = genai.GenerativeModel(VISION_MODEL)
    all_metas: List[PageMeta] = []
    n = len(page_jpegs)

    for chunk_start in range(0, n, _MAX_IMAGES):
        chunk = page_jpegs[chunk_start: chunk_start + _MAX_IMAGES]
        base_pg = chunk_start + 1

        parts: list = []
        for i, jpeg in enumerate(chunk):
            parts.append(f"=== PAGE {base_pg + i} ===")
            parts.append(_img(jpeg))
        parts.append(_CLASSIFY_PROMPT.replace("N pages", f"{len(chunk)} pages"))

        logger.info(f"  classifying pages {base_pg}–{base_pg + len(chunk) - 1}")
        raw = _call_gemini(model, parts, f"classify {base_pg}-{base_pg+len(chunk)-1}")

        if not raw:
            for i in range(len(chunk)):
                all_metas.append(PageMeta(page_num=base_pg + i, content_type="procedure"))
            continue

        try:
            data = json.loads(_strip_fences(raw))
        except json.JSONDecodeError:
            for i in range(len(chunk)):
                all_metas.append(PageMeta(page_num=base_pg + i, content_type="procedure"))
            continue

        by_num = {d["page_num"]: d for d in data if isinstance(d, dict)}
        for i in range(len(chunk)):
            pg = base_pg + i
            d = by_num.get(pg, {})
            all_metas.append(PageMeta(
                page_num=pg,
                content_type=d.get("content_type", "procedure"),
                family_label=d.get("family_label"),
                submachines_in_title=d.get("submachines_in_title") or [],
                table_title=d.get("table_title"),
            ))

    return all_metas


# ---------------------------------------------------------------------------
# Family grouping
# ---------------------------------------------------------------------------

def group_into_families(metas: List[PageMeta]) -> List[FamilyInfo]:
    starts = [
        i for i, m in enumerate(metas)
        if m.content_type in ("family_start", "mixed") and m.family_label
    ]
    if not starts:
        logger.warning("No family_start pages found — treating entire doc as one family")
        starts = [0]

    families: List[FamilyInfo] = []
    for idx, start_idx in enumerate(starts):
        end_idx = starts[idx + 1] - 1 if idx + 1 < len(starts) else len(metas) - 1
        start_meta = metas[start_idx]
        page_nums = [m.page_num for m in metas[start_idx: end_idx + 1]]
        families.append(FamilyInfo(
            label=start_meta.family_label or f"FAMILY_{idx+1}",
            page_range=(start_meta.page_num, metas[end_idx].page_num),
            title_submachines=start_meta.submachines_in_title or [],
            all_pages=page_nums,
        ))
        logger.info(
            f"  family '{start_meta.family_label}': "
            f"pages {start_meta.page_num}–{metas[end_idx].page_num}"
        )
    return families


# ---------------------------------------------------------------------------
# Table extraction (API)
# ---------------------------------------------------------------------------

def _save_family_meta(family: FamilyInfo, raw_dir: Path) -> None:
    safe = re.sub(r"[^\w\-]", "_", family.label)
    (raw_dir / f"{safe}_meta.json").write_text(
        json.dumps({
            "label": family.label,
            "page_range": list(family.page_range),
            "title_submachines": family.title_submachines,
            "all_pages": family.all_pages,
            "title_from_external": family.title_from_external,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_family_tables(
    family: FamilyInfo,
    page_jpegs: List[bytes],
    genai_client,
    raw_dir: Path,
) -> Tuple[List[FuncTable], List[str], List[str]]:
    """API call → save raw JSON + meta → parse + integrity checks.
    Returns (tables, flags, checks_run)."""
    pages_to_send = family.all_pages[:_MAX_IMAGES]
    if not pages_to_send:
        return [], ["no pages"], ["pad_trim_ban"]

    model = genai_client.GenerativeModel(VISION_MODEL)
    parts: list = [_TABLE_EXTRACT_PROMPT]
    for pg in pages_to_send:
        parts.append(f"--- PAGE {pg} ---")
        parts.append(_img(page_jpegs[pg - 1]))

    logger.info(f"  [{family.label}] extracting tables from pages {pages_to_send}")
    raw = _call_gemini(model, parts, f"{family.label} tables")
    if not raw:
        return [], ["Gemini call failed"], ["pad_trim_ban"]

    raw_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", family.label)
    raw_path = raw_dir / f"{safe}_tables_raw.json"

    # Enrich raw JSON with family meta so --reprocess never needs a separate meta file
    try:
        raw_data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        raw_data = {"tables": []}
    enriched = {
        "family_label": family.label,
        "title_submachines": family.title_submachines,
        "page_range": list(family.page_range),
        "all_pages": family.all_pages,
        "tables": raw_data.get("tables", []),
    }
    raw_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_family_meta(family, raw_dir)
    logger.info(f"  raw JSON → {raw_path.name}")

    return _parse_family_tables(raw, family)


# ---------------------------------------------------------------------------
# Reprocess from cache (no API)
# ---------------------------------------------------------------------------

def reprocess_from_cache(output_dir: Path) -> str:
    """
    Load raw/<FAMILY>_tables_raw.json, re-run parsing + integrity + write + report.
    No Gemini calls.

    Priority for family meta (label + title_submachines):
      1. Top-level fields in raw JSON (enriched v3.1+ format written by extract_family_tables)
      2. Separate <FAMILY>_meta.json file (written as side-effect or bootstrap)
      3. Fallback: infer label from filename, title_submachines=None → prefix-vote flagged

    Writes meta file as side-effect whenever source 1 or 2 supplies the data and no
    meta file exists yet, so future --reprocess runs are self-sufficient.
    """
    raw_dir = output_dir / "raw"
    if not raw_dir.exists():
        return f"ERROR: {raw_dir} not found. Run full extraction first."

    extracts: List[FamilyExtract] = []
    processed: List[str] = []
    proxy_families: List[str] = []

    for raw_path in sorted(raw_dir.glob("*_tables_raw.json")):
        safe_name = raw_path.stem[: -len("_tables_raw")]
        meta_path = raw_dir / f"{safe_name}_meta.json"

        raw_json = raw_path.read_text(encoding="utf-8")

        # --- Source 1: top-level fields in raw JSON (enriched format) ---
        try:
            raw_data = json.loads(_strip_fences(raw_json))
        except json.JSONDecodeError:
            raw_data = {}

        if "family_label" in raw_data:
            fam = FamilyInfo(
                label=raw_data["family_label"],
                page_range=tuple(raw_data.get("page_range", [0, 0])),
                title_submachines=raw_data.get("title_submachines"),  # None/[]/[...]
                all_pages=raw_data.get("all_pages", []),
            )
            if not meta_path.exists():
                _save_family_meta(fam, raw_dir)
                logger.info(f"  [{fam.label}] wrote meta as side-effect of --reprocess")

        # --- Source 2: separate meta file ---
        elif meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fam = FamilyInfo(
                label=meta["label"],
                page_range=tuple(meta["page_range"]),
                title_submachines=meta.get("title_submachines"),  # None/[]/[...]
                all_pages=meta["all_pages"],
                title_from_external=meta.get("title_from_external", True),
            )

        # --- Source 3: no external meta — derive proxy from raw JSON spec cols ---
        else:
            label = safe_name.replace("_", " ").strip()
            derived_subs = _derive_from_spec_cols(raw_data)
            fam = FamilyInfo(
                label=label, page_range=(0, 0),
                title_submachines=derived_subs,   # [] or [...]: prefix-vote runs trivially
                all_pages=[],
                title_from_external=False,        # proxy — coverage check suppressed
            )
            _save_family_meta(fam, raw_dir)       # write meta as side-effect
            proxy_families.append(label)
            logger.info(
                f"  [{label}] no external meta — derived {len(derived_subs)} proxy subs "
                f"from spec cols; meta written as side-effect"
            )

        tables, flags, checks_run, checks_na = _parse_family_tables(raw_json, fam)
        ex = FamilyExtract(
            info=fam, tables=tables, flags=flags,
            checks_run=checks_run, checks_na=checks_na, raw_json_path=raw_path,
        )
        extracts.append(ex)
        processed.append(fam.label)

    print(f"Loaded from cache: {processed}")
    if proxy_families:
        print(f"  INFO: {proxy_families} — no external meta; used derived proxy subs (prefix-vote runs trivially)")

    for ex in extracts:
        if ex.submachine_union():
            write_family_workbook(ex, output_dir)

    return generate_report(extracts, page_jpegs=[], output_dir=output_dir)


# ---------------------------------------------------------------------------
# Excel writer
# ---------------------------------------------------------------------------

_HDR_FILL = PatternFill(fill_type="solid", fgColor="4472C4")
_HDR_FONT = Font(bold=True, color="FFFFFF")
_PARAM_FILL = PatternFill(fill_type="solid", fgColor="D9E1F2")
_PARAM_FONT = Font(bold=True)
_SEC_FILL = PatternFill(fill_type="solid", fgColor="BDD7EE")
_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(wrap_text=True, vertical="top")


def _cell(ws, row, col, value, fill=None, font=None):
    c = ws.cell(row=row, column=col, value=value)
    if fill:
        c.fill = fill
    if font:
        c.font = font
    c.border = _BORDER
    c.alignment = _WRAP
    return c


def write_family_workbook(extract: FamilyExtract, output_dir: Path) -> Optional[Path]:
    sub_union = extract.submachine_union()
    if not sub_union:
        return None

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    for sub in sub_union:
        sheet_name = re.sub(r"[\\/*?:\[\]]", "_", sub)[:31]
        ws = wb.create_sheet(title=sheet_name)
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 20
        ws.column_dimensions["C"].width = 38

        row = 1
        ws.cell(row=row, column=1,
                value=f"{extract.info.label}  |  pages {extract.info.all_pages}").font = Font(italic=True)
        row += 2

        _cell(ws, row, 1, "Parameter", _HDR_FILL, _HDR_FONT)
        _cell(ws, row, 2, "Setting", _HDR_FILL, _HDR_FONT)
        _cell(ws, row, 3, "Acceptable Limit", _HDR_FILL, _HDR_FONT)
        row += 1

        for t in extract.tables:
            if t.kind != "spec":          # skip aux AND unverified
                continue
            if sub not in t.submachine_columns:
                continue

            col_idx = t.submachine_columns.index(sub)
            c = ws.cell(row=row, column=1, value=t.title)
            c.fill = _SEC_FILL
            c.font = Font(bold=True)
            c.border = _BORDER
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
            row += 1

            prev_param = None
            for sr in t.rows:
                val = sr.values[col_idx] if col_idx < len(sr.values) else ""
                if str(val).strip().upper() == "NA":
                    continue
                param_text = sr.parameter if sr.parameter != prev_param else ""
                _cell(ws, row, 1, param_text,
                      _PARAM_FILL if sr.parameter != prev_param else None,
                      _PARAM_FONT if sr.parameter != prev_param else None)
                _cell(ws, row, 2, sr.setting)
                _cell(ws, row, 3, str(val))
                prev_param = sr.parameter
                row += 1

            row += 1  # blank between tables

    # AUX sheet
    aux_tables = [t for t in extract.tables if t.kind == "aux"]
    if aux_tables:
        ws_aux = wb.create_sheet(title="AUX")
        ws_aux.column_dimensions["A"].width = 30
        ws_aux.column_dimensions["B"].width = 20
        ws_aux.column_dimensions["C"].width = 45
        r = 1
        for t in aux_tables:
            ws_aux.cell(row=r, column=1, value=t.title).font = Font(bold=True)
            r += 1
            for sr in t.rows:
                ws_aux.cell(row=r, column=1, value=sr.parameter)
                ws_aux.cell(row=r, column=2, value=sr.setting)
                ws_aux.cell(row=r, column=3, value=", ".join(sr.values))
                r += 1
            r += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", extract.info.label)
    out_path = output_dir / f"{safe}.xlsx"
    wb.save(str(out_path))
    logger.info(f"  wrote {out_path} ({len(sub_union)} submachine sheets)")
    return out_path


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def generate_report(
    extracts: List[FamilyExtract],
    page_jpegs: List[bytes],
    output_dir: Path,
) -> str:
    lines = ["# Functional PDF Extraction Report (v3.1)", ""]

    blocked_tables: List[Tuple[str, FuncTable, List[str]]] = []

    for ex in extracts:
        sub_union = ex.submachine_union()
        checks_not_run = [
            c for c in ALL_CHECKS
            if c not in ex.checks_run and c not in ex.checks_na
        ]
        clean = ex.is_clean()
        status = "✅ CLEAN" if clean else "❌ NOT CLEAN"

        spec = [t for t in ex.tables if t.kind == "spec"]
        aux = [t for t in ex.tables if t.kind == "aux"]
        unverified = [t for t in ex.tables if t.kind == "unverified"]

        title_subs_str = (
            f"{ex.info.title_submachines} (derived proxy — prefix-vote is N/A)"
            if not ex.info.title_from_external
            else (
                str(ex.info.title_submachines)
                if ex.info.title_submachines is not None
                else "(unknown — no external meta)"
            )
        )

        lines += [
            f"## {ex.info.label}",
            f"- **Status**: {status}",
            f"- **Pages**: {ex.info.page_range[0]}–{ex.info.page_range[1]}",
            f"- **Title submachines**: {title_subs_str}",
            f"- **Checks run** ({len(ex.checks_run)}): {ex.checks_run}",
        ]
        if ex.checks_na:
            lines.append(f"- **Checks N/A** (no independent source): {ex.checks_na}")
        if checks_not_run:
            lines.append(f"- **Checks NOT run**: {checks_not_run}")

        lines.append(f"- **Submachine union** ({len(sub_union)}): {sub_union}")
        lines.append(f"- **Spec tables** ({len(spec)}):")
        for t in spec:
            lines.append(
                f"  - `{t.title[:60]}` — cols({len(t.submachine_columns)})={t.submachine_columns}  rows={len(t.rows)}"
            )
        if aux:
            lines.append(f"- **Aux tables** ({len(aux)}):")
            for t in aux:
                lines.append(f"  - `{t.title[:60]}` rows={len(t.rows)}")
        if unverified:
            lines.append(f"- **Unverified tables** ({len(unverified)}) — excluded from workbook:")
            for t in unverified:
                lines.append(f"  - `{t.title[:60]}` cols={t.submachine_columns}")
                blocked_tables.append((ex.info.label, t, ex.flags))

        real_flags = [f for f in ex.flags if not f.startswith("INFO:")]
        info_flags = [f for f in ex.flags if f.startswith("INFO:")]
        if real_flags:
            lines.append(f"- **Flags** ({len(real_flags)}):")
            for f in real_flags:
                lines.append(f"  - {f}")
        else:
            lines.append("- **Flags**: none")
        if info_flags:
            lines.append(f"- **Info** ({len(info_flags)}):")
            for f in info_flags:
                lines.append(f"  - {f[6:]}")  # strip "INFO: " prefix
        lines.append("")

    # BLOCKED TABLES section
    if blocked_tables:
        lines += ["---", "## BLOCKED TABLES (unverified — excluded from workbook)", ""]
        for family_label, t, fam_flags in blocked_tables:
            # Match flags to this specific table title (prefix match)
            title_key = t.title[:30]
            table_flags = [f for f in fam_flags if title_key in f]
            lines += [
                f"### [{family_label}] {t.title}",
                f"- **Columns** ({len(t.submachine_columns)}): {t.submachine_columns}",
                f"- **Rows**: {len(t.rows)}",
            ]
            if table_flags:
                lines.append("- **Reasons**:")
                for f in table_flags:
                    lines.append(f"  - {f}")
            if t.rows:
                lines.append("- **Sample rows (first 3)**:")
                for sr in t.rows[:3]:
                    lines.append(
                        f"  - `{sr.parameter}` / `{sr.setting}` → {sr.values}"
                    )
            lines.append("")

    # Audit crops (only in full mode)
    if not page_jpegs:
        lines += ["---", "*(Audit crops: not available in --reprocess mode)*", ""]
        return "\n".join(lines)

    audit_dir = output_dir / "audit_crops"
    audit_dir.mkdir(parents=True, exist_ok=True)
    lines += ["---", "## Audit Crops", ""]

    ranked = sorted(
        [ex for ex in extracts if ex.submachine_union()],
        key=lambda x: sum(len(t.rows) for t in x.tables if t.kind == "spec"),
        reverse=True,
    )
    dsmr = next((ex for ex in extracts if "DSMR" in ex.info.label.upper()), None)
    targets: List[FamilyExtract] = []
    for ex in ranked:
        if ex not in targets:
            targets.append(ex)
        if len(targets) >= 2:
            break
    if dsmr and dsmr not in targets and len(targets) >= 2:
        targets[-1] = dsmr

    for ex in targets[:2]:
        pg = ex.info.all_pages[-1] if ex.info.all_pages else None
        if pg is None:
            continue
        safe = re.sub(r"[^\w\-]", "_", ex.info.label)
        crop_path = audit_dir / f"{safe}_page{pg}.jpg"
        crop_path.write_bytes(page_jpegs[pg - 1])
        biggest = max(
            (t for t in ex.tables if t.kind == "spec"),
            key=lambda t: len(t.rows),
            default=None,
        )
        lines += [
            f"### {ex.info.label} — page {pg}",
            f"Image: `{crop_path.name}`",
            "",
            "**Largest spec table (first 8 rows):**",
            "```json",
            json.dumps({
                "title": biggest.title if biggest else None,
                "submachine_columns": biggest.submachine_columns if biggest else [],
                "rows": [
                    {"parameter": r.parameter, "setting": r.setting, "values": r.values}
                    for r in (biggest.rows[:8] if biggest else [])
                ],
            }, indent=2, ensure_ascii=False),
            "```",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point (full pipeline)
# ---------------------------------------------------------------------------

def extract_all(pdf_path: Path, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    page_jpegs = render_pages(pdf_path)

    logger.info("Phase 1: classifying pages ...")
    metas = classify_all_pages(page_jpegs)
    families = group_into_families(metas)
    if not families:
        return "ERROR: no families detected."

    genai_client = _get_client()
    extracts: List[FamilyExtract] = []

    for fam in families:
        logger.info(f"Phase 2: [{fam.label}] extracting tables ...")
        tables, flags, checks_run, checks_na = extract_family_tables(fam, page_jpegs, genai_client, raw_dir)
        safe = re.sub(r"[^\w\-]", "_", fam.label)
        ex = FamilyExtract(
            info=fam, tables=tables, flags=flags,
            checks_run=checks_run, checks_na=checks_na,
            raw_json_path=raw_dir / f"{safe}_tables_raw.json",
        )
        extracts.append(ex)

    for ex in extracts:
        if ex.submachine_union():
            write_family_workbook(ex, output_dir)

    return generate_report(extracts, page_jpegs, output_dir)
