from typing import List, Dict
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


def detect_header_row(grid: List[List[str]]) -> List[str]:
    """
    Detect header row based on variant-like tokens
    """
    for row in grid:
        variant_count = sum(1 for cell in row if is_variant_token(cell))

        # header row should contain multiple variant-like values
        if variant_count >= 2:
            return row

    return []


def build_variant_map(grid: List[List[str]]) -> Dict[str, Dict[str, str]]:
    """
    Convert grid → variant-wise mapping
    """
    if not grid or len(grid) < 2:
        return {}

    header = detect_header_row(grid)

    if not header or len(header) < 2:
        return {}

    # assume first column = parameter
    variants = [v for v in header[1:] if is_variant_token(v)]

    result = {normalize(v): {} for v in variants if v}

    for row in grid:
        if len(row) < 2:
            continue

        raw_param = normalize(row[0])
        param = FIELD_MAP.get(raw_param, raw_param)

        for i, value in enumerate(row[1:]):
            if i >= len(variants):
                break

            variant = normalize(variants[i])
            if not variant:
                continue

            if value:
                result[variant][param] = value.strip()

    return result


def extract_variant_mappings(tables: List[Dict]) -> Dict[str, Dict]:
    """
    Process multiple table grids
    """
    combined = {}

    for table in tables:
        grid = table.get("grid", [])
        mapping = build_variant_map(grid)

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
                merged[v][field] = value

    return merged

def is_variant_token(cell: str) -> bool:
    """
    Strict variant detection (e.g., MGH3BF, MG73BF)
    """
    cell = cell.strip().upper()

    if not cell:
        return False

    # remove brackets or punctuation
    cell = re.sub(r"[^\w]", "", cell)

    # must follow pattern like MGH3BF, MG73BF, etc.
    pattern = r"^[A-Z]{2,5}\d+[A-Z]{1,3}$"

    return bool(re.match(pattern, cell))