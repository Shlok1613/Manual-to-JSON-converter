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
    Create the Test_Procedures sheet using GENERATED test conditions.
    
    Matches the template format exactly:
    - Each condition spans multiple rows (1 row per POT/voltage/LED line)
    - First row of condition has: F=test case, G=POT, H=voltage, J=LED, K=relay, L=on_delay, M=off_delay
    - Subsequent rows of same condition have: G=POT, H=voltage, J=LED (continuation)
    - Empty row between conditions
    """
    current_row = 1
    
    # Title
    ws.cell(row=current_row, column=1, value=f"Test Procedures: {machine}")
    ws.cell(row=current_row, column=1).font = Font(bold=True, size=14)
    current_row += 1
    
    # Row 2: Headers in columns F-M (matching template exactly)
    template_headers = {
        6: "Test cases/ parameters",  # F
        7: "POT Setting",             # G
        8: "Voltage Setting",         # H
        9: "",                         # I (empty)
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
    
    # Rows 3-7: DIP S/W settings placeholder
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
    
    # Row 10+: Test condition data
    if not test_conditions:
        ws.cell(row=current_row, column=6, value="No test conditions generated")
        ws.cell(row=current_row, column=6).font = Font(italic=True, color="999999")
    else:
        for cond in test_conditions:
            test_case = cond.get("test_case", "-")
            pot_settings = cond.get("pot_settings", ["-"])
            voltages = cond.get("voltages", ["-"])
            led_rows = cond.get("led_rows", ["-"])
            relay_status = cond.get("relay_status", "-")
            on_delay = cond.get("on_delay", "-")
            off_delay = cond.get("off_delay", "-")
            
            # Determine max sub-rows needed
            max_rows = max(len(pot_settings), len(voltages), len(led_rows))
            
            # Write each sub-row of this condition
            for i in range(max_rows):
                row_data = [None, None, None, None, None]  # Cols A-E empty
                
                # F: Test case name (only on first row)
                row_data.append(test_case if i == 0 else None)
                
                # G: POT Setting
                row_data.append(pot_settings[i] if i < len(pot_settings) else None)
                
                # H: Voltage Setting
                row_data.append(voltages[i] if i < len(voltages) else None)
                
                # I: empty
                row_data.append(None)
                
                # J: LED STATUS
                row_data.append(led_rows[i] if i < len(led_rows) else None)
                
                # K: Relay status (only on first row)
                row_data.append(relay_status if i == 0 else None)
                
                # L: On delay (only on first row)
                row_data.append(on_delay if i == 0 else None)
                
                # M: Off delay (only on first row)
                row_data.append(off_delay if i == 0 else None)
                
                write_data_row(ws, current_row, row_data)
                current_row += 1
            
            # Empty row between conditions
            current_row += 1
    
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
    
    logger.info(f"Created test procedures sheet for {machine} ({len(test_conditions)} conditions)")


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


