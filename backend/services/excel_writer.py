"""
Excel Writer Service - UPDATED WITH VARIANT SUPPORT
Generates formatted Excel files from extracted specifications.

NEW: Supports multi-variant parameters (Variant_1, Variant_2, etc.)
"""
from pathlib import Path
from typing import Dict, List, Optional
import logging
import re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# Color scheme
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
SUBHEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
SUBHEADER_FONT = Font(bold=True, size=10)
BORDER_THIN = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin')
)


def set_column_widths(ws, widths: Dict[str, int]):
    """Set column widths."""
    for col_letter, width in widths.items():
        ws.column_dimensions[col_letter].width = width


def write_header_row(ws, row: int, headers: List[str], start_col: int = 1):
    """Write a formatted header row."""
    for i, header in enumerate(headers):
        col = start_col + i
        cell = ws.cell(row=row, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = BORDER_THIN


def write_subheader(ws, row: int, col: int, text: str, span_cols: int = 1):
    """Write a subheader (section title)."""
    cell = ws.cell(row=row, column=col, value=text)
    cell.font = SUBHEADER_FONT
    cell.fill = SUBHEADER_FILL
    cell.alignment = Alignment(horizontal='left', vertical='center')
    cell.border = BORDER_THIN
    
    if span_cols > 1:
        ws.merge_cells(
            start_row=row,
            start_column=col,
            end_row=row,
            end_column=col + span_cols - 1
        )


def write_data_row(ws, row: int, data: List[any], start_col: int = 1):
    """Write a data row with borders."""
    for i, value in enumerate(data):
        col = start_col + i
        cell = ws.cell(row=row, column=col, value=value)
        cell.border = BORDER_THIN
        cell.alignment = Alignment(vertical='center')


def create_specifications_sheet(ws, machine: str, specs: Dict):
    """
    Create the Specifications sheet - WITH VARIANT SUPPORT!
    
    Layout:
    - Product information
    - Reference voltage
    - Voltage parameters (with variants if present)
    - Timing parameters (with variants if present)
    """
    current_row = 1
    
    # Title
    ws.cell(row=current_row, column=1, value=f"Specifications: {machine}")
    ws.cell(row=current_row, column=1).font = Font(bold=True, size=14)
    current_row += 2
    
    # Reference voltage
    if specs.get("reference_voltage"):
        ref = specs["reference_voltage"]
        write_subheader(ws, current_row, 1, "Reference Voltage", span_cols=2)
        current_row += 1
        
        write_data_row(ws, current_row, [
            "Voltage",
            f"{ref['value']} {ref['unit']}"
        ])
        current_row += 2
    
    # Voltage parameters - WITH VARIANT SUPPORT
    if specs.get("voltage_parameters"):
        write_subheader(ws, current_row, 1, "Voltage Parameters", span_cols=4)
        current_row += 1
        
        # Check if ANY parameter has variants
        has_variants = any("variants" in param_data for param_data in specs["voltage_parameters"].values())
        
        if has_variants:
            # NEW FORMAT: Show variants in rows
            write_header_row(ws, current_row, [
                "Parameter",
                "Setting",
                "Variant",
                "Range"
            ])
            current_row += 1
            
            # Data rows - one row per variant
            for param_name, param_data in specs["voltage_parameters"].items():
                setting = param_data.get("setting", "")
                
                if "variants" in param_data and param_data["variants"]:
                    # Write one row per variant
                    for variant_name, variant_value in param_data["variants"].items():
                        write_data_row(ws, current_row, [
                            param_name.replace("_", " ").title(),
                            setting,
                            variant_name,
                            variant_value
                        ])
                        current_row += 1
                else:
                    # No variants, write single row
                    write_data_row(ws, current_row, [
                        param_name.replace("_", " ").title(),
                        setting,
                        "N/A",
                        param_data.get("range", "")
                    ])
                    current_row += 1
        else:
            # OLD FORMAT: Simple table without variants
            write_header_row(ws, current_row, [
                "Parameter",
                "Setting",
                "Range",
                "Notes"
            ])
            current_row += 1
            
            for param_name, param_data in specs["voltage_parameters"].items():
                write_data_row(ws, current_row, [
                    param_name.replace("_", " ").title(),
                    param_data.get("setting", ""),
                    param_data.get("range", ""),
                    param_data.get("notes", "")
                ])
                current_row += 1
        
        current_row += 1
    
    # Timing parameters - WITH VARIANT SUPPORT
    if specs.get("timing_parameters"):
        write_subheader(ws, current_row, 1, "Timing Parameters", span_cols=4)
        current_row += 1
        
        # Check if ANY parameter has variants
        has_variants = any("variants" in param_data for param_data in specs["timing_parameters"].values())
        
        if has_variants:
            # NEW FORMAT: Show variants in rows
            write_header_row(ws, current_row, [
                "Parameter",
                "Setting",
                "Variant",
                "Range"
            ])
            current_row += 1
            
            for param_name, param_data in specs["timing_parameters"].items():
                setting = param_data.get("setting", "")
                
                if "variants" in param_data and param_data["variants"]:
                    for variant_name, variant_value in param_data["variants"].items():
                        write_data_row(ws, current_row, [
                            param_name.replace("_", " ").title(),
                            setting,
                            variant_name,
                            variant_value
                        ])
                        current_row += 1
                else:
                    write_data_row(ws, current_row, [
                        param_name.replace("_", " ").title(),
                        setting,
                        "N/A",
                        param_data.get("range", "")
                    ])
                    current_row += 1
        else:
            # OLD FORMAT
            write_header_row(ws, current_row, [
                "Parameter",
                "Setting",
                "Range"
            ])
            current_row += 1
            
            for param_name, param_data in specs["timing_parameters"].items():
                write_data_row(ws, current_row, [
                    param_name.replace("_", " ").title(),
                    param_data.get("setting", ""),
                    param_data.get("range", "")
                ])
                current_row += 1
        
        current_row += 1
    
    # Set column widths
    set_column_widths(ws, {
        "A": 25,
        "B": 20,
        "C": 25,
        "D": 30
    })
    
    logger.info(f"Created specifications sheet for {machine}")


def create_test_procedures_sheet(ws, machine: str, test_conditions: List[Dict]):
    """
    Create the Test_Procedures sheet with MULTI-ROW LED FORMAT.
    Each condition spans exactly 5 rows:
      Row 1: test_case | P1 | RN | PWR LED | relay | on_delay | off_delay
      Row 2:           | P2 | YN | UV LED  |       |          |
      Row 3:           | P3 | BN | OV LED  |       |          |
      Row 4:           |    |    | ASY LED |       |          |
      Row 5: (blank spacer)
    """
    current_row = 1
    
    # Title
    ws.cell(row=current_row, column=1, value=f"Test Procedures: {machine}")
    ws.cell(row=current_row, column=1).font = Font(bold=True, size=14)
    current_row += 1
    
    # Row 2: Headers in columns F-M
    template_headers = {
        6: "Test cases/ parameters",  # F
        7: "POT Setting",             # G
        8: "Voltage Setting",         # H
        9: "",                         # I
        10: "LED STATUS",             # J
        11: "relay status",           # K
        12: "On delay",               # L
        13: "off delay",              # M
    }
    for col, header in template_headers.items():
        cell = ws.cell(row=current_row, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = BORDER_THIN
    current_row += 1
    
    # Rows 3-7: DIP S/W settings
    ws.cell(row=current_row, column=6, value="DIP S/W setting")
    ws.cell(row=current_row, column=6).font = SUBHEADER_FONT
    ws.cell(row=current_row, column=6).fill = SUBHEADER_FILL
    ws.cell(row=current_row, column=6).border = BORDER_THIN
    for i in range(5):
        ws.cell(row=current_row + i, column=7, value=f"{i+1} : -")
        ws.cell(row=current_row + i, column=7).border = BORDER_THIN
    current_row += 5
    
    # Empty row
    current_row += 1
    
    # Row 9: Voltage settings sub-header
    ws.cell(row=current_row, column=7, value="Couple voltage setting")
    ws.cell(row=current_row, column=7).font = SUBHEADER_FONT
    ws.cell(row=current_row, column=7).fill = SUBHEADER_FILL
    ws.cell(row=current_row, column=7).border = BORDER_THIN
    ws.cell(row=current_row, column=8, value="PH-N")
    ws.cell(row=current_row, column=8).font = SUBHEADER_FONT
    ws.cell(row=current_row, column=8).fill = SUBHEADER_FILL
    ws.cell(row=current_row, column=8).border = BORDER_THIN
    ws.cell(row=current_row, column=9, value="PH -PH")
    ws.cell(row=current_row, column=9).font = SUBHEADER_FONT
    ws.cell(row=current_row, column=9).fill = SUBHEADER_FILL
    ws.cell(row=current_row, column=9).border = BORDER_THIN
    current_row += 1
    
    # === TEST CONDITIONS (Starting Row 10) ===
    if not test_conditions:
        ws.cell(row=current_row, column=6, value="No test conditions generated")
        ws.cell(row=current_row, column=6).font = Font(italic=True, color="999999")
    else:
        for cond in test_conditions:
            current_row = _write_condition_5row(ws, cond, current_row)
    
    # Set column widths
    set_column_widths(ws, {
        "F": 35,
        "G": 25,
        "H": 25,
        "I": 8,
        "J": 30,
        "K": 22,
        "L": 18,
        "M": 18,
    })
    
    logger.info(f"Created test procedures sheet for {machine} "
                f"({len(test_conditions)} conditions, {current_row - 1} rows)")


def _write_condition_5row(ws, cond: Dict, start_row: int) -> int:
    """
    Write one test condition across exactly 5 rows.
    Supports BOTH key formats:
      New (universal_spec_extractor): tc, v1, v2, v3, l1, l2, l3, l4, relay, on_d, off_d
      Old (legacy): test_case, pot_setting, voltage, led_status, led_extra, relay_status, on_delay, off_delay
    Returns next available row (start_row + 5).
    """
    # Detect format and extract values
    if 'tc' in cond:
        # NEW format — values already pre-split
        tc    = cond.get('tc', '')
        v1    = cond.get('v1', '')
        v2    = cond.get('v2', '')
        v3    = cond.get('v3', '')
        l1    = cond.get('l1', 'PWR (GREEN LED) : ON')
        l2    = cond.get('l2', 'UV (RED LED) : OFF')
        l3    = cond.get('l3', 'OV (RED LED) : OFF')
        l4    = cond.get('l4', 'ASY (RED LED) : OFF')
        relay = cond.get('relay', '-')
        on_d  = cond.get('on_d', '-')
        off_d = cond.get('off_d', '-')
        # No POT in new format — leave column G empty
        p1, p2, p3 = '', '', ''
    else:
        # OLD format — need to parse combined strings
        tc = cond.get('test_case', '')
        p1, p2, p3 = _parse_pot_settings(cond.get('pot_setting', '-'))
        v1, v2, v3 = _parse_voltages(cond.get('voltage', '-'))
        l1, l2, l3, l4 = _parse_led_statuses(
            cond.get('led_status', ''),
            cond.get('led_extra', [])
        )
        relay = cond.get('relay_status', '-')
        on_d  = cond.get('on_delay', '-')
        off_d = cond.get('off_delay', '-')
    
    r = start_row
    
    # ROW 1: Main condition row
    ws.cell(row=r, column=6, value=tc).border = BORDER_THIN
    ws.cell(row=r, column=7, value=p1).border = BORDER_THIN
    ws.cell(row=r, column=8, value=v1).border = BORDER_THIN
    ws.cell(row=r, column=10, value=l1).border = BORDER_THIN
    ws.cell(row=r, column=11, value=relay).border = BORDER_THIN
    ws.cell(row=r, column=12, value=on_d).border = BORDER_THIN
    ws.cell(row=r, column=13, value=off_d).border = BORDER_THIN
    ws.cell(row=r, column=6).font = Font(bold=True)
    
    # ROW 2: P2 + YN + UV LED
    ws.cell(row=r+1, column=7, value=p2).border = BORDER_THIN
    ws.cell(row=r+1, column=8, value=v2).border = BORDER_THIN
    ws.cell(row=r+1, column=10, value=l2).border = BORDER_THIN
    for col in [6, 9, 11, 12, 13]:
        ws.cell(row=r+1, column=col).border = BORDER_THIN
    
    # ROW 3: P3 + BN + OV LED
    ws.cell(row=r+2, column=7, value=p3).border = BORDER_THIN
    ws.cell(row=r+2, column=8, value=v3).border = BORDER_THIN
    ws.cell(row=r+2, column=10, value=l3).border = BORDER_THIN
    for col in [6, 9, 11, 12, 13]:
        ws.cell(row=r+2, column=col).border = BORDER_THIN
    
    # ROW 4: ASY LED only
    ws.cell(row=r+3, column=10, value=l4).border = BORDER_THIN
    for col in [6, 7, 8, 9, 11, 12, 13]:
        ws.cell(row=r+3, column=col).border = BORDER_THIN
    
    # ROW 5: Empty spacer (borders only)
    for col in range(6, 14):
        ws.cell(row=r+4, column=col).border = BORDER_THIN
    
    return r + 5  # Next condition starts 5 rows later


def _parse_pot_settings(pot_string: str) -> tuple:
    """Parse 'P1 = 7 %, P2 = 0 SEC, P3 = 15 SEC' → (P1, P2, P3) per-row."""
    if pot_string == "-" or not pot_string:
        return "-", "-", "-"
    
    p1_match = re.search(r'P1\s*=\s*([^,]+)', pot_string)
    p2_match = re.search(r'P2\s*=\s*([^,]+)', pot_string)
    p3_match = re.search(r'P3\s*=\s*([^,]+)', pot_string)
    
    p1 = f"P1 = {p1_match.group(1).strip()}" if p1_match else pot_string
    p2 = f"P2 = {p2_match.group(1).strip()}" if p2_match else "-"
    p3 = f"P3 = {p3_match.group(1).strip()}" if p3_match else "-"
    
    return p1, p2, p3


def _parse_voltages(voltage_string: str) -> tuple:
    """Parse 'RN :0, YN :0, BN :0' → (RN, YN, BN) per-row."""
    if not voltage_string or voltage_string == "-":
        return "-", "-", "-"
    
    if ',' in voltage_string:
        parts = [v.strip() for v in voltage_string.split(',')]
        rn = parts[0] if len(parts) > 0 else "-"
        yn = parts[1] if len(parts) > 1 else "-"
        bn = parts[2] if len(parts) > 2 else "-"
    else:
        # Single voltage (e.g., "RN : 347") — put it in RN, YN/BN get 240
        rn = voltage_string
        yn = "YN : 240"
        bn = "BN : 240"
    
    return rn, yn, bn


def _parse_led_statuses(led_string: str, led_extra: List[str] = None) -> tuple:
    """
    Parse LED status into exactly 4 values: (PWR, UV, OV, ASY).
    Uses led_extra list to fill in missing values.
    """
    pwr = "PWR (GREEN LED) : ON"
    uv = "UV (RED LED) : OFF"
    ov = "OV (RED LED) : OFF"
    asy = "ASY (RED LED) : OFF"
    
    # Try parsing from combined led_status string
    if led_string:
        pwr_match = re.search(r'PWR[^,]*?:\s*([^,]+)', led_string, re.IGNORECASE)
        if pwr_match:
            pwr = f"PWR (GREEN LED) : {pwr_match.group(1).strip()}"
        
        uv_match = re.search(r'UV[^,]*?:\s*([^,]+)', led_string, re.IGNORECASE)
        if uv_match:
            uv = f"UV (RED LED) : {uv_match.group(1).strip()}"
        
        ov_match = re.search(r'OV[^,]*?:\s*([^,]+)', led_string, re.IGNORECASE)
        if ov_match:
            ov = f"OV (RED LED) : {ov_match.group(1).strip()}"
        
        asy_match = re.search(r'(?:ASY|ASYM)[^,]*?:\s*([^,]+)', led_string, re.IGNORECASE)
        if asy_match:
            asy = f"ASY (RED LED) : {asy_match.group(1).strip()}"
        
        # Handle special cases
        if 'All LEDs : OFF' in led_string:
            pwr = "PWR (GREEN LED) : OFF"
            uv = "UV (RED LED) : OFF"
            ov = "OV (RED LED) : OFF"
            asy = "ASY (RED LED) : OFF"
        
        if 'Blinking' in led_string:
            pwr = led_string  # Keep full status like "PWR (GREEN LED) : Blinking"
    
    # Override from led_extra if present
    if led_extra:
        for extra in led_extra:
            extra_upper = extra.upper()
            if 'UV' in extra_upper:
                uv = extra
            elif 'OV' in extra_upper:
                ov = extra
            elif 'ASY' in extra_upper or 'ASYM' in extra_upper:
                asy = extra
            elif 'PWR' in extra_upper:
                pwr = extra
            elif 'ALL FAULT' in extra_upper or 'ALL LED' in extra_upper:
                uv = extra
                ov = "-"
                asy = "-"
            elif 'FAULT' in extra_upper or 'NF' in extra_upper or 'PHASE' in extra_upper:
                uv = extra
    
    return pwr, uv, ov, asy


def generate_excel(
    extraction_id: str,
    machine: str,
    specs: Dict,
    output_dir: Path,
    test_conditions: Optional[List[Dict]] = None
) -> str:
    """
    Generate Excel file for one machine with BOTH sheets.
    
    Sheet 1: Specifications (voltage parameters, timing)
    Sheet 2: Test_Procedures (generated test conditions in template format)
    """
    # Create workbook
    wb = Workbook()
    
    # Remove default sheet
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    
    # Create Specifications sheet (existing, keeps voltage specs)
    ws_specs = wb.create_sheet("Specifications")
    create_specifications_sheet(ws_specs, machine, specs)
    
    # Create Test Procedures sheet (condition matrix)
    ws_tests = wb.create_sheet("Test_Procedures")
    create_test_procedures_sheet(ws_tests, machine, test_conditions or [])
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    safe_machine = machine.replace("/", "_").replace(" ", "_")
    filename = f"{extraction_id}_{safe_machine}.xlsx"
    filepath = output_dir / filename
    
    # Save workbook
    wb.save(filepath)
    logger.info(f"Generated Excel file: {filename}")
    
    return filename


