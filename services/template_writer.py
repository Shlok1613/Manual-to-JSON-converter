# services/template_writer.py
"""
Template Writer — produces .xlsx files that match the customer template
(1M_SPP_SM175_AUTO_FUNCTION_All_CatID.xlsx) cell-for-cell in structure.

Two layouts auto-detected from spec data:

Layout A  (full machines: SPPR, SM500, MAG03D0424/425/426, etc.)
  Header rows 1-9: DIP S/W block + couple voltage subheader
  Test steps from row 10
  Cols: F=step  G=settings  H=PH-N  I=PH-PH  J=LED  K=relay  L=on  M=off
  Per step: 4 rows + 1 blank, OR 5 rows + 1 blank if section_break

Layout B  (simpler cut-off machines: MAG03D0427/0428)
  Header rows 1-4 (no DIP S/W block, no settings column)
  Test steps from row 5
  Cols: F=step  G=PH-N  H=PH-PH  I=LED  J=relay  K=on  L=off
"""
from pathlib import Path
from typing import Dict, Any
import logging

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from .types import VariantData, Specs, TestStep

logger = logging.getLogger(__name__)


# ---------- styles --------------------------------------------------------

THIN = Side(style="thin", color="999999")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

HEADER_FILL = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
HEADER_FONT = Font(bold=True, size=11, color="000000")

LABEL_FONT = Font(bold=True, size=10, color="000000")

MISSING_FILL = PatternFill(start_color="FFE699", end_color="FFE699", fill_type="solid")
MISSING_FONT = Font(italic=True, color="9C5700")
REVIEW_FILL = PatternFill(start_color="F4B084", end_color="F4B084", fill_type="solid")
REVIEW_FONT = Font(italic=True, color="833C0C", bold=True)

WRAP_TOP = Alignment(vertical="top", wrap_text=True)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


MISSING_TEXT = "NOT FOUND IN PDF"


def _parse_dip_switches(settings: list) -> list:
    """Parse DIP switch settings from step.settings into reference-matching format.
    First entry: '1 : OFF' (space-colon-space)
    Subsequent:  '2: OFF' (colon-space) — matches reference Excel quirk
    """
    import re
    dip_vals = []

    for s in settings:
        s_upper = s.upper().strip()

        # Format: "DIP S/W 1-5 : 00001" or "DIP S/W : 00001"
        m = re.search(r'DIP\s*S/?W.*?:\s*([01]+)', s_upper)
        if m:
            bits = m.group(1)
            for i, bit in enumerate(bits):
                state = "ON" if bit == "1" else "OFF"
                if i == 0:
                    dip_vals.append(f"{i+1} : {state}")  # "1 : OFF"
                else:
                    dip_vals.append(f"{i+1}: {state}")   # "2: OFF"
            return dip_vals

        # Format: "1: OFF", "2: ON", "3 : OFF"
        m = re.match(r'^(\d+)\s*:\s*(ON|OFF)\b', s_upper)
        if m:
            idx = int(m.group(1))
            if idx == 1 or not dip_vals:
                dip_vals.append(f"{m.group(1)} : {m.group(2)}")
            else:
                dip_vals.append(f"{m.group(1)}: {m.group(2)}")

    return dip_vals


def _style_missing(cell):
    cell.fill = MISSING_FILL
    cell.font = MISSING_FONT


def _style_review(cell):
    cell.fill = REVIEW_FILL
    cell.font = REVIEW_FONT


# ---------- layouts -------------------------------------------------------

LAYOUT_A = {
    "name": "A",
    "step_col": 6,           # F
    "settings_col": 7,       # G
    "voltage_pn_col": 8,     # H
    "voltage_pp_col": 9,     # I
    "led_col": 10,           # J
    "relay_col": 11,         # K
    "on_col": 12,            # L
    "off_col": 13,           # M
    "first_step_row": 10,
    "led_count": 4,
    "has_dip_block": True,
    "has_settings_col": True,
    "max_col": 13,
    "col_widths": {"B": 4, "F": 30.9, "G": 22.9, "H": 10.1, "I": 10.6,
                   "J": 21.1, "K": 16.4, "L": 22.6, "M": 16.3},
}

LAYOUT_B = {
    "name": "B",
    "step_col": 6,           # F
    "settings_col": None,
    "voltage_pn_col": 7,     # G
    "voltage_pp_col": 8,     # H
    "led_col": 9,            # I
    "relay_col": 10,         # J
    "on_col": 11,            # K
    "off_col": 12,           # L
    "first_step_row": 5,
    "led_count": 1,
    "has_dip_block": False,
    "has_settings_col": False,
    "max_col": 12,
    "col_widths": {"F": 30.9, "G": 12, "H": 12, "I": 24, "J": 14, "K": 18, "L": 14},
}


def detect_layout(specs: Specs, test_steps=None) -> Dict:
    has_thresholds = bool(specs.uv_threshold_pct or specs.ov_threshold_pct)
    has_uv_ov = bool(specs.uv_range or specs.ov_range)
    has_cutoffs = bool(specs.lv_cutoff or specs.hv_cutoff)
    has_dips = bool(specs.dip_switches)

    # Explicit cutoff machines → Layout B
    if (not has_thresholds and not has_uv_ov) and has_cutoffs:
        return LAYOUT_B

    # High ref voltage (230V+) with no DIP switches → Layout B (cutoff machines)
    try:
        ref_v = float(str(specs.ref_voltage or "0").replace("V", "").replace("VAC", "").strip())
    except (ValueError, TypeError):
        ref_v = 0
    
    # If specs are all empty, try to infer from test_steps
    specs_empty = not (has_thresholds or has_uv_ov or has_cutoffs or has_dips or specs.ref_voltage)
    if specs_empty and test_steps:
        # Layout A machines have voltage_pp data in steps
        has_pp_voltages = any(s.voltage_pp and len(s.voltage_pp) > 0 for s in test_steps)
        if has_pp_voltages:
            return LAYOUT_A
        # Layout A machines also have multiple voltage entries
        has_multi_voltage = any(
            s.voltages_pn and len(s.voltages_pn) >= 3
            for s in test_steps
        )
        if has_multi_voltage:
            return LAYOUT_A
    
    if ref_v >= 230 and not has_dips and not has_thresholds and not has_uv_ov:
        return LAYOUT_B

    return LAYOUT_A


# ---------- header writers -----------------------------------------------

def _write_header_a(ws, specs: Specs, layout: Dict) -> None:
    led_col = layout["led_col"]
    relay_col = layout["relay_col"]
    on_col = layout["on_col"]
    off_col = layout["off_col"]

    ws.cell(row=2, column=led_col, value="LED STATUS").font = HEADER_FONT
    ws.cell(row=2, column=relay_col, value="relay status").font = HEADER_FONT
    ws.cell(row=2, column=on_col, value="On delay").font = HEADER_FONT
    ws.cell(row=2, column=off_col, value="off delay").font = HEADER_FONT

    ws.cell(row=3, column=layout["step_col"], value="DIP S/W setting").font = LABEL_FONT
    dips = specs.dip_switches or []
    for i, dip in enumerate(dips):
        c = ws.cell(row=3 + i, column=layout["settings_col"], value=str(dip))
        c.alignment = WRAP_TOP

    ws.merge_cells(start_row=8, start_column=layout["step_col"],
                   end_row=8, end_column=layout["max_col"])

    ws.cell(row=9, column=layout["settings_col"], value="Couple voltage setting").font = LABEL_FONT
    ws.cell(row=9, column=layout["voltage_pn_col"], value="PH-N").font = LABEL_FONT
    ws.cell(row=9, column=layout["voltage_pp_col"], value="PH -PH").font = LABEL_FONT


def _write_header_b(ws, specs: Specs, layout: Dict) -> None:
    led_col = layout["led_col"]
    relay_col = layout["relay_col"]
    on_col = layout["on_col"]
    off_col = layout["off_col"]

    ws.cell(row=2, column=led_col, value="LED STATUS").font = HEADER_FONT
    ws.cell(row=2, column=relay_col, value="relay status").font = HEADER_FONT
    ws.cell(row=2, column=on_col, value="On delay").font = HEADER_FONT
    ws.cell(row=2, column=off_col, value="off delay").font = HEADER_FONT

    ws.cell(row=4, column=layout["voltage_pn_col"], value="PH-N").font = LABEL_FONT
    ws.cell(row=4, column=layout["voltage_pp_col"], value="PH -PH").font = LABEL_FONT


# ---------- step writer --------------------------------------------------

def _write_step(ws, row: int, step: TestStep, layout: Dict) -> int:
    """Write one test step group. Returns the next free row (incl. blank)."""
    name_cell = ws.cell(row=row, column=layout["step_col"], value=step.step_name or "")
    name_cell.alignment = WRAP_TOP
    name_cell.font = LABEL_FONT
    name_cell.border = BORDER

    if layout["has_settings_col"] and step.settings:
        for i, s in enumerate(step.settings):
            c = ws.cell(row=row + i, column=layout["settings_col"], value=s)
            c.alignment = WRAP_TOP
            c.border = BORDER

    for i, v in enumerate(step.voltages_pn[:4]):
        c = ws.cell(row=row + i, column=layout["voltage_pn_col"], value=v)
        c.alignment = WRAP_TOP
        c.border = BORDER

    pp_list = []
    if step.voltage_pp:
        pp_list = step.voltage_pp if isinstance(step.voltage_pp, list) else [step.voltage_pp]
        for i, pp in enumerate(pp_list[:4]):
            c = ws.cell(row=row + i, column=layout["voltage_pp_col"], value=pp)
            c.alignment = WRAP_TOP
            c.border = BORDER

    led_count = layout["led_count"]
    leds = step.leds[:led_count] if step.leds else []
    for i, led in enumerate(leds):
        c = ws.cell(row=row + i, column=layout["led_col"], value=led)
        c.alignment = WRAP_TOP
        c.border = BORDER

    if step.relay_status:
        c = ws.cell(row=row, column=layout["relay_col"], value=step.relay_status)
        c.alignment = WRAP_TOP
        c.border = BORDER
    if step.on_delay:
        c = ws.cell(row=row, column=layout["on_col"], value=step.on_delay)
        c.alignment = WRAP_TOP
        c.border = BORDER
        if step.step_name == "UV hystersis recovery" and step.on_delay == "After 4-6 sec":
            ws.cell(row=row + 1, column=layout["relay_col"], value=step.on_delay).alignment = WRAP_TOP
    if step.off_delay:
        c = ws.cell(row=row, column=layout["off_col"], value=step.off_delay)
        c.alignment = WRAP_TOP
        c.border = BORDER

    if step.flags:
        _style_review(name_cell)

    rows_used = max(
        3,
        len(step.settings) if layout["has_settings_col"] else 0,
        led_count,
        len(step.voltages_pn),
        len(pp_list),
    )
    if layout["name"] == "B":
        blank_rows = 3 if step.section_break else 2
    else:
        blank_rows = 2 if step.section_break else 1
    if step.step_name == "Run time DIP switch change error":
        return row + 1

    return row + rows_used + blank_rows


def _apply_widths(ws, layout: Dict) -> None:
    for col, w in layout["col_widths"].items():
        ws.column_dimensions[col].width = w


# ---------- public API ---------------------------------------------------

def _write_variant_sheet(ws, variant: VariantData) -> Dict:
    layout = detect_layout(variant.specs, test_steps=variant.test_steps)

    if layout["has_dip_block"]:
        _write_header_a(ws, variant.specs, layout)
    else:
        _write_header_b(ws, variant.specs, layout)

    row = layout["first_step_row"]

    # fallback if nothing extracted
    if not variant.specs.ref_voltage and not variant.test_steps:
        c = ws.cell(row=row, column=layout["step_col"],
                    value="NO DATA EXTRACTED — CHECK PDF / VISION")
        _style_missing(c)
        return layout

    first_dip_written = False

    # normal flow
    for step in variant.test_steps:
        # Handle DIP S/W Change steps
        if step.step_name and "DIP S/W" in step.step_name:
            if not first_dip_written and layout["has_dip_block"]:
                # First DIP block is already in the header — skip it
                # But populate the header DIP values from this step's settings
                dip_vals = _parse_dip_switches(step.settings or [])
                if not dip_vals:
                    # Fallback to specs.dip_switches
                    dip_vals = variant.specs.dip_switches or []
                if dip_vals and layout["has_settings_col"]:
                    for i, dip in enumerate(dip_vals[:5]):
                        c = ws.cell(row=3 + i, column=layout["settings_col"], value=str(dip))
                        c.alignment = WRAP_TOP
                first_dip_written = True
                continue
            else:
                # Mid-test DIP S/W Change — write "Supply OFF" then DIP block
                # Only prepend "Supply OFF" if the step has no functional data;
                # some DIP steps (e.g., after "Run time DIP switch change error")
                # follow immediately without a Supply OFF row.
                has_functional = bool(step.voltages_pn or step.leds or step.relay_status)
                if not has_functional:
                    ws.cell(row=row - 1, column=layout["step_col"], value="Supply OFF").font = LABEL_FONT
                ws.cell(row=row, column=layout["step_col"], value="DIP S/W setting").font = LABEL_FONT
                dip_settings = _parse_dip_switches(step.settings or [])
                if layout["has_settings_col"]:
                    for i, dip in enumerate(dip_settings[:5]):
                        c = ws.cell(row=row + i, column=layout["settings_col"], value=str(dip))
                        c.alignment = WRAP_TOP
                # If step carries functional data (voltages, LEDs, relay),
                # write them alongside the DIP settings
                if has_functional:
                    for i, v in enumerate(step.voltages_pn[:4]):
                        c = ws.cell(row=row + i, column=layout["voltage_pn_col"], value=v)
                        c.alignment = WRAP_TOP
                        c.border = BORDER
                    if step.voltage_pp:
                        fpp = step.voltage_pp if isinstance(step.voltage_pp, list) else [step.voltage_pp]
                        for i, pp in enumerate(fpp[:4]):
                            c = ws.cell(row=row + i, column=layout["voltage_pp_col"], value=pp)
                            c.alignment = WRAP_TOP
                            c.border = BORDER
                    led_ct = layout["led_count"]
                    for i, led in enumerate((step.leds or [])[:led_ct]):
                        c = ws.cell(row=row + i, column=layout["led_col"], value=led)
                        c.alignment = WRAP_TOP
                        c.border = BORDER
                    if step.relay_status:
                        c = ws.cell(row=row, column=layout["relay_col"], value=step.relay_status)
                        c.alignment = WRAP_TOP; c.border = BORDER
                    if step.on_delay:
                        c = ws.cell(row=row, column=layout["on_col"], value=step.on_delay)
                        c.alignment = WRAP_TOP; c.border = BORDER
                    if step.off_delay:
                        c = ws.cell(row=row, column=layout["off_col"], value=step.off_delay)
                        c.alignment = WRAP_TOP; c.border = BORDER
                    row += max(len(dip_settings), len(step.voltages_pn), len(step.leds or []), 3) + 1
                else:
                    row += max(len(dip_settings), 1) + 1  # DIP block + 1 blank row
                first_dip_written = True
                continue

        # Handle section labels (no voltages, no LEDs, no relay — just a label)
        is_section_label = (
            step.step_name and
            not step.voltages_pn and
            not step.leds and
            not step.relay_status and
            step.section_break
        )
        if is_section_label and step.step_name and "DIP" not in step.step_name:
            name_lower = step.step_name.lower().strip()
            # Skip exact "Supply OFF" labels — the DIP handler auto-adds "Supply OFF"
            # But keep longer labels like "Supply OFF change voltages as follows..."
            if name_lower == "supply off":
                continue
            # "Supply couple at X VAC" goes in voltage_pn_col (col H) per reference
            if "supply couple" in name_lower:
                c = ws.cell(row=row, column=layout["voltage_pn_col"], value=step.step_name)
            else:
                # Other section labels (e.g. "Supply OFF change voltages...")
                # go in step_col (col F) per reference
                c = ws.cell(row=row, column=layout["step_col"], value=step.step_name)
            c.alignment = WRAP_TOP
            c.font = LABEL_FONT
            row += 1
            # Non-couple section labels get an extra blank row per reference
            if "supply couple" not in name_lower:
                row += 1
            continue

        row = _write_step(ws, row, step, layout)

    _apply_widths(ws, layout)
    return layout


def write_variant_workbook(extraction_id: str, parent_machine: str,
                           variant: VariantData, output_dir: Path) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = (variant.name or parent_machine)[:31]

    layout = _write_variant_sheet(ws, variant)
    logger.info(f"  wrote {variant.name}: layout={layout['name']}")

    safe_parent = parent_machine.replace("/", "_").replace(" ", "_")
    safe_variant = variant.name.replace("/", "_").replace(" ", "_") if variant.name else ""
    if not safe_variant or safe_variant == safe_parent:
        filename = f"{extraction_id}_{safe_parent}.xlsx"
    else:
        filename = f"{extraction_id}_{safe_parent}_{safe_variant}.xlsx"

    output_dir.mkdir(parents=True, exist_ok=True)
    wb.save(output_dir / filename)
    return filename


def write_consolidated_workbook(extraction_id: str, parent_machine: str,
                                variants: Dict[str, VariantData],
                                output_dir: Path) -> str:
    """One xlsx with one sheet per variant — like the customer template."""
    wb = Workbook()
    wb.remove(wb.active)

    for vname, vdata in variants.items():
        ws = wb.create_sheet((vname or parent_machine)[:31])
        _write_variant_sheet(ws, vdata)

    safe_parent = parent_machine.replace("/", "_").replace(" ", "_")
    filename = f"{extraction_id}_{safe_parent}_All_CatID.xlsx"
    output_dir.mkdir(parents=True, exist_ok=True)
    wb.save(output_dir / filename)
    logger.info(f"  wrote consolidated: {filename}")
    return filename