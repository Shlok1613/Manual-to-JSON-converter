"""
Table Extraction Service
Detects and extracts tables from PDF text.

Tables in manufacturing PDFs typically have:
- Header line (TABLE 1, TABLE 2, etc.)
- Parameter rows (key: value format)
- Multiple columns separated by spaces or |
"""
import re
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def detect_table_headers(text: str) -> List[Dict[str, any]]:
    """
    Find all table headers in text.
    
    More strict: Only match actual table headers at start of line.
    """
    headers = []
    lines = text.splitlines()
    
    # Pattern: "TABLE X (...)" at start of line
    table_pattern = re.compile(
        r'^TABLE\s+(\d+)\s*(?:\((.+?)\))?',
        re.IGNORECASE
    )
    
    for line_num, line in enumerate(lines):
        line_stripped = line.strip()
        
        # Must be at start of line and have content in parentheses
        match = table_pattern.match(line_stripped)
        if match:
            table_num = match.group(1)
            table_title = match.group(2) if match.group(2) else ""
            
            # Only add if it has a title or is followed by data
            if table_title or (line_num + 1 < len(lines) and ":" in lines[line_num + 1]):
                headers.append({
                    "table_id": f"TABLE_{table_num}",
                    "title": table_title.strip(),
                    "start_line": line_num,
                    "header_text": line_stripped
                })
                logger.info(f"Found table: TABLE {table_num} - {table_title}")
    
    return headers
    """
    Find all table headers in text.
    
    Patterns we detect:
    - "TABLE 1 (LED INDICATIONS)"
    - "TABLE 2 (PRODUCT SETTINGS @ 415 VAC)"
    - "LED / Parameters"
    
    Returns:
        List of table locations with metadata
        [{
            "table_id": "TABLE_1",
            "title": "LED INDICATIONS",
            "start_line": 45,
            "header_text": "TABLE 1 (LED INDICATIONS)"
        }]
    """
    headers = []
    lines = text.splitlines()
    
    # Pattern 1: "TABLE X (...)"
    table_pattern = re.compile(
        r'TABLE\s+(\d+)\s*(?:\((.+?)\))?',
        re.IGNORECASE
    )
    
    # Pattern 2: Headers with Parameters/Settings
    param_header_pattern = re.compile(
        r'(LED|Parameters?|Settings?)\s*[/\|]\s*(Parameters?|Settings?)',
        re.IGNORECASE
    )
    
    for line_num, line in enumerate(lines):
        line_stripped = line.strip()
        
        # Check for TABLE X pattern
        match = table_pattern.search(line_stripped)
        if match:
            table_num = match.group(1)
            table_title = match.group(2) if match.group(2) else ""
            
            headers.append({
                "table_id": f"TABLE_{table_num}",
                "title": table_title.strip(),
                "start_line": line_num,
                "header_text": line_stripped
            })
            logger.info(f"Found table: TABLE {table_num} - {table_title}")
            continue
        
        # Check for parameter header pattern
        if param_header_pattern.search(line_stripped):
            headers.append({
                "table_id": f"PARAM_TABLE_{len(headers) + 1}",
                "title": "Parameters",
                "start_line": line_num,
                "header_text": line_stripped
            })
            logger.info(f"Found parameter table at line {line_num}")
    
    return headers


def parse_table_rows(text: str, start_line: int, max_lines: int = 50) -> List[Dict[str, str]]:
    """
    Parse rows from a table starting at given line.
    
    Stops when:
    - Empty line
    - Next table header
    - Next section header
    - Max lines reached
    
    Each row typically looks like:
    "Under Voltage (UV): 85.00%, 347 to 357 VAC"
    
    Parsed as:
    {
        "parameter": "Under Voltage (UV)",
        "setting": "85.00%",
        "range": "347 to 357 VAC"
    }
    """
    lines = text.splitlines()
    rows = []
    
    # Start from line after header
    current_line = start_line + 1
    
    # Check if this looks like a multi-column table (no colons in first few lines)
    is_multi_column = True
    for i in range(current_line, min(current_line + 3, len(lines))):
        if i < len(lines) and ':' in lines[i]:
            is_multi_column = False
            break
    
    # If multi-column format (like your TABLE 2)
    if is_multi_column:
        logger.info("Detected multi-column table format")
        
        while current_line < len(lines) and current_line < start_line + max_lines:
            line = lines[current_line].strip()
            current_line += 1
            
            # Stop conditions
            if not line:
                continue
            
            if line.upper().startswith(('PROCESS:', 'PROCEDURE:', 'ACCESSORIES', 'CTQ', 'CHECK LIST', 'NOTE:', 'PHASE')):
                break
            
            if re.match(r'^TABLE\s+\d+', line.upper()):
                break
            
            # Parse multi-column row
            # Try to extract parameter name (usually at start)
            # Format: "Under Voltage 85.00% 318 to 328"
            # or: "347 to 357 VAC 318 to 328 VAC ..."
            
            # Look for parameter names
            param_match = re.match(r'^(Under\s+Voltage|Over\s+Voltage|Asymmetry|ON\s+Delay|OFF\s+Delay|UV/OV|On\s+delay|Off\s+delay)\s*(.+)?', line, re.IGNORECASE)
            
            if param_match:
                param_name = param_match.group(1).strip()
                rest = param_match.group(2).strip() if param_match.group(2) else ""
                
                rows.append({
                    "parameter": param_name,
                    "raw_value": rest,
                    "setting": "",  # Will extract from rest
                    "range": ""     # Will extract from rest
                })
            else:
                # Continuation line (like "347 to 357 VAC ...")
                # Add to previous row if exists
                if rows:
                    rows[-1]["raw_value"] += " " + line
        
        logger.info(f"Parsed {len(rows)} rows from multi-column table")
        return rows
    
    # Patterns for key-value extraction
    # Pattern: "Key: value1, value2"
    kv_pattern = re.compile(
        r'^([^:]+):\s*(.+)$'
    )
    
    # Pattern for multi-column tables (using |)
    column_pattern = re.compile(
        r'\|'
    )
    
    while current_line < len(lines) and current_line < start_line + max_lines:
        line = lines[current_line].strip()
        current_line += 1
        
        # Stop conditions
# Stop conditions
        if not line:
            continue  # Skip empty lines but keep going
        
        # Stop if we hit a new major section
        if line.upper().startswith(('PROCESS:', 'PROCEDURE:', 'ACCESSORIES REQUIRED', 'CTQ', 'CHECK LIST')):
            break
        
        # Stop if we hit a new table header (but not TABLE in middle of text)
        if re.match(r'^TABLE\s+\d+', line.upper()):
            break
        
        # Skip note lines but don't stop
        if line.upper().startswith('NOTE:'):
            continue
        
        # Try key-value pattern
        match = kv_pattern.match(line)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            
            # Try to split value into setting and range
            # Example: "85.00%, 347 to 357 VAC" → setting="85.00%", range="347 to 357 VAC"
            value_parts = [v.strip() for v in value.split(',')]
            
            row = {
                "parameter": key,
                "raw_value": value
            }
            
            if len(value_parts) >= 1:
                row["setting"] = value_parts[0]
            
            if len(value_parts) >= 2:
                row["range"] = value_parts[1]
            
            if len(value_parts) >= 3:
                row["notes"] = value_parts[2]
            
            rows.append(row)
            continue
        
        # Try column-separated format
        if column_pattern.search(line):
            parts = [p.strip() for p in line.split('|')]
            # Remove empty parts
            parts = [p for p in parts if p]
            
            if len(parts) >= 2:
                row = {
                    "parameter": parts[0],
                    "raw_value": ' | '.join(parts[1:])
                }
                
                if len(parts) >= 2:
                    row["setting"] = parts[1]
                if len(parts) >= 3:
                    row["range"] = parts[2]
                if len(parts) >= 4:
                    row["notes"] = parts[3]
                
                rows.append(row)
    
    logger.info(f"Parsed {len(rows)} rows from table at line {start_line}")
    return rows


def extract_tables(text: str) -> List[Dict[str, any]]:
    """
    Main function: Extract all tables from text.
    
    Process:
    1. Find all table headers
    2. Parse rows for each table
    3. Return structured table data
    
    Args:
        text: Full text block (e.g., one machine's text)
    
    Returns:
        List of tables:
        [{
            "table_id": "TABLE_1",
            "title": "LED INDICATIONS",
            "rows": [
                {"parameter": "Green", "setting": "Healthy", "range": "Continuous ON"},
                ...
            ]
        }]
    
    Example:
        tables = extract_tables(machine_text)
        for table in tables:
            print(f"{table['table_id']}: {len(table['rows'])} rows")
    """
    # Find all table headers
    headers = detect_table_headers(text)
    
    if not headers:
        logger.warning("No tables found in text")
        return []
    
    # Extract rows for each table
    tables = []
    for header in headers:
        rows = parse_table_rows(text, header["start_line"])
        
        if rows:  # Only include tables that have data
            table = {
                "table_id": header["table_id"],
                "title": header["title"],
                "header_text": header["header_text"],
                "rows": rows,
                "num_rows": len(rows)
            }
            tables.append(table)
            logger.info(f"Extracted {header['table_id']} with {len(rows)} rows")
    
    logger.info(f"Total tables extracted: {len(tables)}")
    return tables


def get_table_by_id(tables: List[Dict], table_id: str) -> Optional[Dict]:
    """
    Helper: Get a specific table by ID.
    
    Args:
        tables: List of tables from extract_tables()
        table_id: Table ID like "TABLE_1" or "TABLE_2"
    
    Returns:
        Table dict or None if not found
    
    Example:
        table2 = get_table_by_id(tables, "TABLE_2")
        if table2:
            print(table2['rows'])
    """
    for table in tables:
        if table["table_id"] == table_id:
            return table
    return None


def get_table_row(table: Dict, parameter_name: str) -> Optional[Dict]:
    """
    Helper: Get a specific row from a table.
    
    Args:
        table: Table dict from extract_tables()
        parameter_name: Parameter to find (case-insensitive, partial match)
    
    Returns:
        Row dict or None if not found
    
    Example:
        uv_row = get_table_row(table2, "Under Voltage")
        if uv_row:
            print(f"UV Range: {uv_row['range']}")
    """
    param_lower = parameter_name.lower()
    
    for row in table.get("rows", []):
        row_param = row.get("parameter", "").lower()
        if param_lower in row_param or row_param in param_lower:
            return row
    
    return None