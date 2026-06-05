"""
Full pipeline test for GIC PDF -> Excel extraction.

Tests:
1. WI.pdf -> 5 MAG variant Excel files
2. Functional Testing WI_Five series.pdf -> multiple machine Excel files
3. Structural comparison against reference Excel

Run: python -m tests.test_full_pipeline
"""
import sys
import os
import re
import time
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
from services.pdf_extractor import extract_pages
from services.block_segmenter import segment_blocks
from services.vision_extractor import extract_machine_data
from services.enricher import enrich_variant
from services.normalizer import normalize_variant
from services.spec_linker import link_specs_to_steps
from services.validator import validate_variants
from services.template_writer import write_variant_workbook, write_consolidated_workbook

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WI_PDF = Path("source/WI.pdf")
FUNC_PDF = Path("source/FUnctional Testing WI_Five series.pdf")
REF_EXCEL = Path("source/1M SPP SM175 AUTO FUNCTION All CatID.xlsx")
OUTPUT_DIR = Path("outputs/test_pipeline")

EXPECTED_WI_MACHINES = ["MAG03D0424", "MAG03D0425", "MAG03D0426", "MAG03D0427", "MAG03D0428"]


def run_pipeline_for_pdf(pdf_path, machine_dict=None):
    """Run the full extraction pipeline for a single PDF."""
    print(f"\n{'='*70}")
    print(f"PIPELINE: {pdf_path.name}")
    print(f"{'='*70}")

    pages = extract_pages(pdf_path)
    print(f"  Pages extracted: {len(pages)}")

    user_names = list(machine_dict.keys()) if machine_dict else None
    blocks = segment_blocks(pages, user_names=user_names)
    print(f"  Blocks segmented: {len(blocks)}")
    for b in blocks:
        print(f"    - {b.machine} (pages={len(b.pages)}, scope={b.is_scope_block})")

    results = {}
    excel_files = []

    for i, block in enumerate(blocks):
        machine_name = block.machine

        if block.is_scope_block:
            sub_machines = [machine_name]
        elif machine_dict and machine_name in machine_dict:
            sub_machines = machine_dict[machine_name] or [machine_name]
        else:
            sub_machines = [machine_name]

        print(f"\n  Processing {machine_name} with variants {sub_machines}...")

        try:
            variants = extract_machine_data(block=block, sub_machines=sub_machines)
            time.sleep(3)  # Rate limit
        except Exception as e:
            print(f"    ERROR: {e}")
            variants = {}

        if not variants:
            print(f"    No variants extracted")
            results[machine_name] = {"status": "empty", "variants": {}}
            continue

        # Enrich + normalize
        for vname, vdata in variants.items():
            vdata = enrich_variant(vdata, block.text)
            vdata = normalize_variant(vdata)
            variants[vname] = vdata

        variants = link_specs_to_steps(variants)
        variants = validate_variants(variants)

        machine_results = {}
        for vname, vdata in variants.items():
            is_usable = vdata.is_usable()
            machine_results[vname] = {
                "usable": is_usable,
                "steps": len(vdata.test_steps),
                "spec_flags": len(vdata.specs.flags),
                "step_flags": sum(1 for s in vdata.test_steps if s.flags),
                "has_ref_voltage": bool(vdata.specs.ref_voltage),
                "has_uv": bool(vdata.specs.uv_range),
                "has_ov": bool(vdata.specs.ov_range),
                "has_lv": bool(vdata.specs.lv_cutoff),
                "led_indications": vdata.specs.led_indications,
                "dip_switches": vdata.specs.dip_switches,
            }

            if is_usable:
                try:
                    fname = write_variant_workbook(
                        extraction_id="test",
                        parent_machine=machine_name,
                        variant=vdata,
                        output_dir=OUTPUT_DIR,
                    )
                    excel_files.append(fname)
                    machine_results[vname]["excel"] = fname
                except Exception as e:
                    print(f"    Excel write error for {vname}: {e}")

            print(f"    {vname}: steps={machine_results[vname]['steps']}, usable={is_usable}")

        # Write consolidated
        usable = {k: v for k, v in variants.items() if v.is_usable()}
        if usable:
            try:
                fname = write_consolidated_workbook(
                    extraction_id="test",
                    parent_machine=machine_name,
                    variants=usable,
                    output_dir=OUTPUT_DIR,
                )
                excel_files.append(fname)
            except Exception as e:
                print(f"    Consolidated write error: {e}")

        results[machine_name] = {"status": "ok", "variants": machine_results}

    return results, excel_files


def check_excel_structure(excel_path, ref_path):
    """Compare generated Excel structure against reference."""
    import openpyxl

    if not excel_path.exists():
        return {"error": f"File not found: {excel_path}"}
    if not ref_path.exists():
        return {"error": f"Reference not found: {ref_path}"}

    wb_gen = openpyxl.load_workbook(excel_path)
    wb_ref = openpyxl.load_workbook(ref_path)

    report = {
        "gen_sheets": wb_gen.sheetnames,
        "ref_sheets": wb_ref.sheetnames,
        "sheet_comparisons": {},
    }

    for sheet_name in wb_gen.sheetnames:
        if sheet_name not in wb_ref.sheetnames:
            report["sheet_comparisons"][sheet_name] = {"status": "not_in_reference"}
            continue

        ws_gen = wb_gen[sheet_name]
        ws_ref = wb_ref[sheet_name]

        total_cells = 0
        matching_cells = 0
        mismatches = []

        for row in ws_ref.iter_rows(min_row=1, max_row=ws_ref.max_row, values_only=False):
            for cell in row:
                if cell.value is not None:
                    total_cells += 1
                    gen_val = ws_gen.cell(row=cell.row, column=cell.column).value
                    if gen_val is not None:
                        # Loose match: normalize strings
                        ref_str = str(cell.value).strip().upper()
                        gen_str = str(gen_val).strip().upper()
                        if ref_str == gen_str:
                            matching_cells += 1
                        else:
                            if len(mismatches) < 20:
                                mismatches.append({
                                    "row": cell.row,
                                    "col": cell.column,
                                    "ref": str(cell.value)[:50],
                                    "gen": str(gen_val)[:50],
                                })

        match_pct = (matching_cells / total_cells * 100) if total_cells > 0 else 0
        report["sheet_comparisons"][sheet_name] = {
            "total_ref_cells": total_cells,
            "matching_cells": matching_cells,
            "match_pct": round(match_pct, 1),
            "sample_mismatches": mismatches[:10],
        }

    return report


def test_wi_pdf():
    """Test WI.pdf pipeline."""
    if not WI_PDF.exists():
        print(f"SKIP: {WI_PDF} not found")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results, excel_files = run_pipeline_for_pdf(WI_PDF)

    print(f"\n{'='*70}")
    print("WI.pdf RESULTS SUMMARY")
    print(f"{'='*70}")

    checks = []

    # Check 1: 5 machines processed
    machines_processed = list(results.keys())
    for m in EXPECTED_WI_MACHINES:
        if m in machines_processed:
            checks.append(("Machine found: " + m, True))
        else:
            checks.append(("Machine found: " + m, False))

    # Check 2: Each has non-zero steps
    for m in EXPECTED_WI_MACHINES:
        if m in results:
            variants = results[m].get("variants", {})
            for vname, vinfo in variants.items():
                has_steps = vinfo.get("steps", 0) > 0
                checks.append((f"{vname} has steps ({vinfo.get('steps', 0)})", has_steps))

    # Check 3: Excel files generated
    checks.append((f"Excel files generated ({len(excel_files)})", len(excel_files) > 0))

    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")

    return results, excel_files


def test_functional_pdf():
    """Test Functional Testing PDF pipeline."""
    if not FUNC_PDF.exists():
        print(f"SKIP: {FUNC_PDF} not found")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results, excel_files = run_pipeline_for_pdf(FUNC_PDF)

    print(f"\n{'='*70}")
    print("Functional PDF RESULTS SUMMARY")
    print(f"{'='*70}")

    for machine, data in results.items():
        status = data.get("status", "unknown")
        variants = data.get("variants", {})
        step_counts = {v: info.get("steps", 0) for v, info in variants.items()}
        print(f"  {machine}: status={status}, variants={step_counts}")

    print(f"  Total Excel files: {len(excel_files)}")
    return results, excel_files


def test_excel_comparison():
    """Compare WI.pdf output against reference Excel."""
    if not REF_EXCEL.exists():
        print(f"SKIP: Reference Excel not found")
        return None

    consolidated = OUTPUT_DIR / "test_MAG03D0424_All_CatID.xlsx"
    # Try to find any consolidated file
    candidates = list(OUTPUT_DIR.glob("test_*_All_CatID.xlsx"))
    if candidates:
        consolidated = candidates[0]
    else:
        # Compare individual files
        print("No consolidated file found, skipping comparison")
        return None

    print(f"\n{'='*70}")
    print(f"EXCEL COMPARISON: {consolidated.name} vs {REF_EXCEL.name}")
    print(f"{'='*70}")

    report = check_excel_structure(consolidated, REF_EXCEL)

    if "error" in report:
        print(f"  ERROR: {report['error']}")
        return report

    print(f"  Generated sheets: {report['gen_sheets']}")
    print(f"  Reference sheets: {report['ref_sheets']}")

    for sheet, comp in report.get("sheet_comparisons", {}).items():
        if comp.get("status") == "not_in_reference":
            print(f"  {sheet}: not in reference (extra sheet)")
        else:
            pct = comp.get("match_pct", 0)
            total = comp.get("total_ref_cells", 0)
            matching = comp.get("matching_cells", 0)
            print(f"  {sheet}: {pct}% match ({matching}/{total} cells)")
            if comp.get("sample_mismatches"):
                for mm in comp["sample_mismatches"][:5]:
                    print(f"    Row {mm['row']}, Col {mm['col']}: ref='{mm['ref']}' gen='{mm['gen']}'")

    return report


if __name__ == "__main__":
    print("GIC Full Pipeline Test")
    print("=" * 70)

    # Test 1: WI.pdf
    wi_results = test_wi_pdf()

    # Test 2: Functional PDF
    func_results = test_functional_pdf()

    # Test 3: Excel comparison
    comparison = test_excel_comparison()

    # Save results
    results_file = Path("TEST_RESULTS.md")
    with open(results_file, "w") as f:
        f.write("# GIC Pipeline Test Results\n\n")
        f.write(f"Run date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## WI.pdf Results\n\n")
        if wi_results:
            results, files = wi_results
            f.write(f"Excel files generated: {len(files)}\n\n")
            for machine, data in results.items():
                f.write(f"### {machine}\n")
                f.write(f"- Status: {data.get('status')}\n")
                for v, info in data.get("variants", {}).items():
                    f.write(f"- {v}: steps={info.get('steps', 0)}, usable={info.get('usable')}\n")
                f.write("\n")

        f.write("## Functional PDF Results\n\n")
        if func_results:
            results, files = func_results
            f.write(f"Excel files generated: {len(files)}\n\n")
            for machine, data in results.items():
                f.write(f"### {machine}\n")
                f.write(f"- Status: {data.get('status')}\n")
                for v, info in data.get("variants", {}).items():
                    f.write(f"- {v}: steps={info.get('steps', 0)}, usable={info.get('usable')}\n")
                f.write("\n")

        f.write("## Excel Comparison\n\n")
        if comparison and "sheet_comparisons" in comparison:
            for sheet, comp in comparison["sheet_comparisons"].items():
                if "match_pct" in comp:
                    f.write(f"- {sheet}: {comp['match_pct']}% match ")
                    f.write(f"({comp['matching_cells']}/{comp['total_ref_cells']} cells)\n")

    print(f"\nResults saved to {results_file}")
