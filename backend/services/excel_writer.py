from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


YELLOW_FILL = PatternFill(start_color="FFF59D", end_color="FFF59D", fill_type="solid")
HEADER_FILL = PatternFill(start_color="BBDEFB", end_color="BBDEFB", fill_type="solid")


def _set_headers(ws, row: int, headers: List[str]) -> None:
    for idx, header in enumerate(headers, start=1):
        c = ws.cell(row=row, column=idx, value=header)
        c.font = Font(bold=True)
        c.fill = HEADER_FILL


def generate_excel(machine: str, metadata: Dict[str, str], specs: Dict[str, object], steps: List[Dict[str, object]], flagged: List[Dict[str, object]], output_dir: Path) -> str:
    """Stage 7: create two-sheet workbook per machine and highlight flagged data."""
    wb = Workbook()
    ws_specs = wb.active
    ws_specs.title = "Specifications"
    ws_steps = wb.create_sheet("Test_Procedures")

    ws_specs["A1"] = "Product Information"
    ws_specs["A1"].font = Font(bold=True)
    _set_headers(ws_specs, 2, ["Field", "Value"])
    ws_specs.append(["Product Name", metadata.get("product_name", machine)])
    ws_specs.append(["Reference Voltage", specs.get("reference_voltage") or ""])
    ws_specs.append(["Criticality", metadata.get("criticality", "")])

    start = 7
    ws_specs[f"A{start}"] = "Voltage Parameters"
    ws_specs[f"A{start}"].font = Font(bold=True)
    _set_headers(ws_specs, start + 1, ["Parameter", "Setting", "Range", "Notes"])
    r = start + 2
    for param, value in specs.get("voltage_parameters", {}).items():
        ws_specs.append([param, value.get("setting"), value.get("range"), value.get("notes", "")])
        r += 1

    r += 1
    ws_specs[f"A{r}"] = "Timing Parameters"
    ws_specs[f"A{r}"].font = Font(bold=True)
    _set_headers(ws_specs, r + 1, ["Parameter", "Setting", "Range"])
    for param, value in specs.get("timing_parameters", {}).items():
        ws_specs.append([param, value.get("setting") or value.get("delay"), value.get("range")])

    _set_headers(ws_steps, 1, ["Step", "Action", "Expected", "Relay", "LED", "Delay", "Voltage", "Section", "Confidence"])
    for step in steps:
        ws_steps.append([
            step.get("step_number"),
            step.get("action"),
            step.get("expected_behavior"),
            step.get("relay"),
            step.get("led"),
            step.get("delay"),
            step.get("voltage"),
            step.get("section"),
            step.get("confidence"),
        ])

    flagged_steps = {f.get("step_number") for f in flagged if f.get("type") == "step"}
    for row in ws_steps.iter_rows(min_row=2, max_row=ws_steps.max_row):
        if row[0].value in flagged_steps:
            for cell in row:
                cell.fill = YELLOW_FILL

    for ws in (ws_specs, ws_steps):
        ws.column_dimensions["A"].width = 24
        ws.column_dimensions["B"].width = 28
        ws.column_dimensions["C"].width = 20
        ws.column_dimensions["D"].width = 22

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = machine.replace(" ", "_").replace("/", "_")
    out = output_dir / f"{safe_name}.xlsx"
    wb.save(out)
    return out.name
