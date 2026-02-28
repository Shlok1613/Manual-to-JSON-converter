"""
Excel Writer Service - UPDATED WITH VARIANT SUPPORT
Generates formatted Excel files from extracted specifications.

NEW: Supports multi-variant parameters (Variant_1, Variant_2, etc.)
"""
from pathlib import Path
from typing import Dict, List, Optional
import logging
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


def generate_excel(
    extraction_id: str,
    machine: str,
    specs: Dict,
    output_dir: Path
) -> str:
    """Generate Excel file for one machine."""
    # Create workbook
    wb = Workbook()
    
    # Remove default sheet
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    
    # Create Specifications sheet
    ws_specs = wb.create_sheet("Specifications")
    create_specifications_sheet(ws_specs, machine, specs)
    
    # Create Test Procedures sheet (placeholder for now)
    ws_tests = wb.create_sheet("Test_Procedures")
    ws_tests.cell(row=1, column=1, value="Test Procedures")
    ws_tests.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws_tests.cell(row=3, column=1, value="Coming soon: Test step extraction")
    
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