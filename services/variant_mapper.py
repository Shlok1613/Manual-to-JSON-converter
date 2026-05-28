from typing import List, Dict, Optional
import re


FIELD_MAP = {
    "UV RANGE": "uv_range",
    "OVER VOLTAGE": "ov_range",
    "OV RANGE": "ov_range",
    "UNDER VOLTAGE": "uv_range",
    "REF VOLTAGE": "ref_voltage",
    "REFERENCE VOLTAGE": "ref_voltage",
    "ON DELAY": "on_delay",
    "OFF DELAY": "off_delay",
}

def normalize(s: str) -> str:
    return s.strip().upper()


def _looks_like_variant(cell: str) -> bool:
    """
    Heuristic: does this cell look like a product identifier?
    Must contain both letters and digits, be 3-12 chars, and not be a generic word.
    Works for: MGH3BF, MG73BR, MAC04D0100, MAG03D0424, MD71B9, SM500, etc.
    """
    cell = re.sub(r"[^\w]", "", cell.strip().upper()).split("/")[0]
    if len(cell) < 3 or len(cell) > 12:
        return False
    if not re.search(r"[A-Z]", cell) or not re.search(r"\d", cell):
        return False
    GENERIC = {
        "VAC", "LED", "TABLE", "VOLTAGE", "PHASE", "PROCESS", "TEST",
        "REF", "SEC", "MIN", "DELAY", "SETTING", "SETTINGS", "RANGE",
        "LIMIT", "LIMITS", "STATUS", "RELAY", "SWITCH", "POWER",
    }
    if cell in GENERIC:
        return False
    return True


def detect_header_row(grid: List[List[str]], known_variants: Optional[List[str]] = None) -> List[str]:
    """
    Detect header row based on known variant names or heuristic variant-like tokens.
    Priority 1: Match against user-provided known_variants.
    Priority 2: Heuristic — 2+ cells look like product identifiers.
    """
    known_upper = set()
    if known_variants:
        for v in known_variants:
            cleaned = re.sub(r"[^\w]", "", v.strip().upper()).split("/")[0]
            if cleaned:
                known_upper.add(cleaned)

    for row in grid:
        cells_upper = set()
        for c in row:
            cleaned = re.sub(r"[^\w]", "", c.strip().upper()).split("/")[0]
            if cleaned:
                cells_upper.add(cleaned)

        # Priority 1: known variant names found in this row
        if known_upper and len(known_upper & cells_upper) >= 1:
            return row

        # Priority 2: heuristic — 2+ cells look like product identifiers
        variant_like = sum(1 for c in row if _looks_like_variant(c))
        if variant_like >= 2:
            return row

    return []


def build_variant_map(grid: List[List[str]], known_variants: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
    """
    Convert grid → variant-wise mapping.
    Supports forward-filling merged/shared cells and filtering NA values.
    """
    if not grid or len(grid) < 2:
        return {}

    header = detect_header_row(grid, known_variants=known_variants)

    if not header or len(header) < 2:
        return {}

    # Determine which header cells are actual variant columns
    # If known_variants provided, use them; otherwise use heuristic
    if known_variants:
        known_upper = {re.sub(r"[^\w]", "", v.strip().upper()).split("/")[0] for v in known_variants if v}
        variants = []
        for cell in header[1:]:
            cleaned = re.sub(r"[^\w]", "", cell.strip().upper()).split("/")[0]
            if cleaned in known_upper or _looks_like_variant(cell):
                variants.append(cell)
            elif cell.strip():
                # Could be a parameter label column — skip it
                variants.append(cell)
        # Filter to only cells that look like variants or match known names
        variants = [v for v in header[1:] if _looks_like_variant(v) or
                    re.sub(r"[^\w]", "", v.strip().upper()).split("/")[0] in known_upper]
    else:
        variants = [v for v in header[1:] if _looks_like_variant(v)]

    if not variants:
        return {}

    result = {normalize(v): {} for v in variants if v}

    # Find column indices for each variant in the header
    variant_col_indices = []
    for v in variants:
        try:
            idx = header.index(v)
            variant_col_indices.append(idx)
        except ValueError:
            continue

    for row in grid:
        if row == header:
            continue
        if len(row) < 2:
            continue

        raw_param = normalize(row[0])
        # Also check second column for parameter name (some tables have 2 label columns)
        param = FIELD_MAP.get(raw_param, raw_param)

        # Forward-fill empty cells across data columns (merged cell handling)
        # Only fill within the data portion of the row (after the label columns)
        data_start = min(variant_col_indices) if variant_col_indices else 1
        # Make a copy of the row for forward-filling
        filled_row = list(row)
        last_val = ""
        for i in range(data_start, len(filled_row)):
            if filled_row[i].strip():
                last_val = filled_row[i].strip()
            elif last_val:
                filled_row[i] = last_val

        for col_idx, var_cell in zip(variant_col_indices, variants):
            variant_key = normalize(var_cell)
            if not variant_key:
                continue
            if col_idx >= len(filled_row):
                continue

            value = filled_row[col_idx].strip() if filled_row[col_idx] else ""

            # Skip NA, -, N/A, and empty values
            if value and value.upper() not in ("NA", "-", "N/A", ""):
                result[variant_key][param] = value

    return result


def extract_variant_mappings(tables: List[Dict], known_variants: Optional[List[str]] = None) -> Dict[str, Dict]:
    """
    Process multiple table grids.
    Passes known_variants through to build_variant_map for header detection.
    """
    combined = {}

    for table in tables:
        grid = table.get("grid", [])
        mapping = build_variant_map(grid, known_variants=known_variants)

        for variant, data in mapping.items():
            if variant not in combined:
                combined[variant] = {}

            combined[variant].update(data)

    return combined


def merge_table_into_specs(variant_maps: Dict[str, Dict], specs_dict: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Table data overrides vision data
    """
    merged = {}

    for variant, spec in specs_dict.items():
        v = variant.upper()
        merged[v] = spec.copy()

        table_data = variant_maps.get(v, {})

        for field, value in table_data.items():
            if value:
                existing = merged[v].get(field)

                # override ONLY if:
                # 1. no existing value
                # 2. existing is weak/empty
                if not existing or existing in ["NA", "-", "null"]:
                    merged[v][field] = value

    return merged