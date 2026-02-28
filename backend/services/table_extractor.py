"""
Table Extraction Service - IMPROVED VERSION
Handles:
1. Numbered tables: "TABLE 2 (PRODUCT SETTINGS...)"
2. Unnumbered tables: "TABLE (PRODUCT SETTINGS...)"
3. Actual column headers when present
"""
import re
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def detect_table_headers(text: str) -> List[Dict[str, any]]:
    """
    Find all table headers in text - IMPROVED to handle unnumbered tables.
    
    Detects patterns like:
    - "TABLE 2 (LED INDICATIONS)"  ← numbered
    - "TABLE (PRODUCT SETTINGS...)" ← unnumbered (NEW!)
    """
    headers = []
    lines = text.splitlines()
    
    # IMPROVED PATTERN: Optional table number
    table_pattern = re.compile(
        r'^TABLE\s*(?:(\d+))?\s*(?:\((.+?)\))?',
        re.IGNORECASE
    )
    
    for line_num, line in enumerate(lines):
        line_stripped = line.strip()
        
        match = table_pattern.match(line_stripped)
        if match:
            table_num = match.group(1) if match.group(1) else "UNNUMBERED"
            table_title = match.group(2) if match.group(2) else ""
            
            # Only add if it has a title or is followed by data
            if table_title or (line_num + 1 < len(lines) and ":" in lines[line_num + 1]):
                table_id = f"TABLE_{table_num}" if table_num != "UNNUMBERED" else f"TABLE_UNNUMBERED_{len(headers)+1}"
                
                headers.append({
                    "table_id": table_id,
                    "title": table_title.strip(),
                    "start_line": line_num,
                    "header_text": line_stripped
                })
                logger.info(f"Found table: {table_id} - {table_title}")
    
    return headers


def extract_column_headers(text: str, table_start_line: int, max_lookback: int = 5) -> List[str]:
    """
    NEW: Try to extract actual column headers if they exist.
    
    Looks for lines like:
    "DMS110 DMS120 /DMS120-V DMA220"
    
    Returns list of column names or empty list.
    """
    lines = text.splitlines()
    
    # Look backwards from table start
    for i in range(max(0, table_start_line - max_lookback), table_start_line):
        line = lines[i].strip()
        
        # Skip section headers
        if line.upper().startswith(('TABLE', 'PARAMETERS', 'LED', 'SETTINGS', 'GOAL', 'NOTE')):
            continue
        
        # Look for lines with multiple product codes (at least 2)
        # Common patterns: MA..., SM..., DMS..., MG...
        # Also handle /variants like "DMS120 /DMS120-V"
        product_codes = re.findall(r'\b(?:MA|SM|DMS|DMA|MG|MAC|MD|MB)[\w-]+\b', line)
        
        if len(product_codes) >= 2:
            # Deduplicate while preserving order
            seen = set()
            unique_codes = []
            for code in product_codes:
                # Remove variant suffix for comparison (e.g., DMS120-V → DMS120)
                base_code = re.sub(r'-[A-Z]$', '', code)
                if base_code not in seen:
                    seen.add(base_code)
                    unique_codes.append(code)
            
            logger.info(f"Found column headers: {unique_codes}")
            return unique_codes
    
    return []


def parse_table_rows(text: str, start_line: int, max_lines: int = 50) -> Dict[str, any]:
    """
    Parse rows from a table with STRICT parameter boundary detection.
    
    IMPROVED: Can use actual column headers if found.
    
    Returns:
        {
            "headers": ["DMS110", "DMS120", ...] or ["Variant_1", "Variant_2", ...],
            "rows": [...]
        }
    """
    lines = text.splitlines()
    current_line = start_line + 1
    
    # NEW: Try to extract actual column headers
    actual_headers = extract_column_headers(text, start_line)
    
    rows = []
    max_variants = 0
    
    # Collect all rows
    temp_rows = []
    current_param = None
    current_setting = None
    accumulated_values = []
    lines_since_param = 0
    
    while current_line < len(lines) and current_line < start_line + max_lines:
        line = lines[current_line].strip()
        current_line += 1
        
        # Stop conditions
        if not line:
            lines_since_param += 1
            if lines_since_param > 2:
                if current_param:
                    temp_rows.append({
                        "parameter": current_param,
                        "setting": current_setting or "",
                        "value_list": accumulated_values.copy()
                    })
                    max_variants = max(max_variants, len(accumulated_values))
                    current_param = None
            continue
        
        if line.upper().startswith(('PROCESS:', 'PROCEDURE:', 'NOTE:', 'ACCESSORIES', 'CTQ', 'CHECK LIST', 'VIRTUAL', 'PHASE', 'DEFAULT', 'B]', 'C]')):
            break
        
        if re.match(r'^TABLE\s', line.upper()):
            break
        
        # Check if this is a NEW parameter line
        param_patterns = [
            r'^(Under\s+Voltage|Over\s+Voltage|Asymmetry|ON\s+Delay|OFF\s+Delay|UV\s*/\s*OV\s+Hysteresis|LOW\s+CUT\s+OFF|HIGH\s+CUT\s+OFF|PHASE\s+FAIL|PHASE\s+REVERSE|NEUTRAL\s+FAIL|VIRTUAL\s+NEUTRAL)',
        ]
        
        is_new_param = False
        for pattern in param_patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                # Save previous parameter
                if current_param:
                    temp_rows.append({
                        "parameter": current_param,
                        "setting": current_setting or "",
                        "value_list": accumulated_values.copy()
                    })
                    max_variants = max(max_variants, len(accumulated_values))
                
                # Start new parameter
                current_param = match.group(1).strip()
                accumulated_values = []
                lines_since_param = 0
                
                # Extract setting and values from same line
                rest_of_line = line[match.end():].strip()
                
                # Look for setting (percentage or voltage)
                setting_match = re.search(r'(\d+(?:\.\d+)?%|\d+VAC)', rest_of_line)
                if setting_match:
                    current_setting = setting_match.group(1)
                    rest_of_line = rest_of_line[setting_match.end():].strip()
                else:
                    current_setting = None
                
                # Extract values
                if rest_of_line:
                    values = re.findall(r'(\d+(?:\.\d+)?(?:\s+to\s+\d+(?:\.\d+)?)?\s*(?:VAC|V|sec?|ms|%)?(?:\s*\([^)]+\))?)', rest_of_line, re.IGNORECASE)
                    accumulated_values.extend([v.strip() for v in values if v.strip() and len(v.strip()) > 2])
                
                is_new_param = True
                break
        
        if is_new_param:
            continue
        
        # Continuation line
        if current_param and lines_since_param < 3:
            lines_since_param += 1
            
            # Skip lines that look like new sections
            if re.match(r'^[A-Z]{2,}[\s/:]', line):
                continue
            
            # Extract values
            values = re.findall(r'(\d+(?:\.\d+)?(?:\s+to\s+\d+(?:\.\d+)?)?\s*(?:VAC|V|sec?|ms|%)?(?:\s*\([^)]+\))?)', line, re.IGNORECASE)
            
            # Check for special keywords
            if re.search(r'\b(?:NA|Enable|YES|Product\s+should\s+trip)\b', line, re.IGNORECASE):
                special_match = re.search(r'\b(NA|Enable|YES|Product\s+should\s+trip[^.]+\.)', line, re.IGNORECASE)
                if special_match:
                    accumulated_values.append(special_match.group(1))
            
            accumulated_values.extend([v.strip() for v in values if v.strip() and len(v.strip()) > 2])
    
    # Save last parameter
    if current_param:
        temp_rows.append({
            "parameter": current_param,
            "setting": current_setting or "",
            "value_list": accumulated_values.copy()
        })
        max_variants = max(max_variants, len(accumulated_values))
    
    # Create headers - use actual headers if found, otherwise Variant_N
    if actual_headers and len(actual_headers) >= max_variants:
        headers = actual_headers[:max_variants]
    elif max_variants > 0:
        headers = [f"Variant_{i+1}" for i in range(max_variants)]
    else:
        headers = []
    
    # Normalize rows
    for temp_row in temp_rows:
        values_dict = {}
        
        for i, value in enumerate(temp_row["value_list"]):
            if i < len(headers):
                values_dict[headers[i]] = value
        
        setting = temp_row["setting"]
        if not setting and temp_row["value_list"]:
            first_val = temp_row["value_list"][0]
            if '%' in first_val or 'VAC' in first_val.upper():
                setting = first_val
        
        rows.append({
            "parameter": temp_row["parameter"],
            "setting": setting,
            "values": values_dict
        })
    
    logger.info(f"Parsed {len(rows)} rows with {len(headers)} columns: {headers}")
    
    return {
        "headers": headers,
        "rows": rows
    }


def extract_tables(text: str) -> List[Dict[str, any]]:
    """
    Main function: Extract all tables from text.
    """
    headers = detect_table_headers(text)
    
    if not headers:
        logger.warning("No tables found in text")
        return []
    
    tables = []
    for header in headers:
        rows_data = parse_table_rows(text, header["start_line"])
        
        if rows_data["rows"]:
            table = {
                "table_id": header["table_id"],
                "title": header["title"],
                "header_text": header["header_text"],
                "headers": rows_data.get("headers", []),
                "rows": rows_data["rows"],
                "num_rows": len(rows_data["rows"])
            }
            tables.append(table)
            logger.info(f"Extracted {header['table_id']} with {len(rows_data['rows'])} rows")
    
    logger.info(f"Total tables extracted: {len(tables)}")
    return tables


def get_table_by_id(tables: List[Dict], table_id: str) -> Optional[Dict]:
    """Helper: Get a specific table by ID."""
    for table in tables:
        if table["table_id"] == table_id:
            return table
    return None


def get_table_row(table: Dict, parameter_name: str) -> Optional[Dict]:
    """Helper: Get a specific row from a table."""
    param_lower = parameter_name.lower()
    
    for row in table.get("rows", []):
        row_param = row.get("parameter", "").lower()
        if param_lower in row_param or row_param in param_lower:
            return row
    
    return None