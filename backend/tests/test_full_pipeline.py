"""End-to-end test: segmentation -> specs + test procedures -> Excel."""
import sys
from pathlib import Path
sys.path.insert(0, r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend")

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
from services.table_extractor import extract_tables
from services.spec_parser import parse_specifications
from services.template_builder import build_template_skeleton
from services.excel_writer import generate_excel

pdf_dir = Path(r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend\uploads")
pdfs = list(pdf_dir.glob("ext_*_FUnctional*.pdf"))
if not pdfs:
    pdfs = list(pdf_dir.glob("FUnctional*.pdf"))
if not pdfs:
    print("No PDF found!")
    sys.exit(1)

latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
print(f"PDF: {latest_pdf.name}\n")

pages = extract_text(latest_pdf)
full_text = "\n\n".join(pages)

blocks = segment_blocks(full_text)
print(f"Total blocks: {len(blocks)}\n")
print(f"{'Machine':16s} {'Chars':>6s} {'Tables':>6s} {'V.Params':>8s} {'T.Params':>8s} {'TestSteps':>9s}")
print("-" * 65)

output_dir = Path(r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend\outputs")
test_id = "ext_test_proc"

for b in blocks:
    tables = extract_tables(b['text'])
    specs = parse_specifications(b['text'], tables)
    
    template_result = build_template_skeleton(b)
    test_steps = template_result["template_data"]["TestSteps"]
    
    vp = len(specs.get('voltage_parameters', {}))
    tp = len(specs.get('timing_parameters', {}))
    
    print(f"{b['machine']:16s} {len(b['text']):6d} {len(tables):6d} {vp:8d} {tp:8d} {len(test_steps):9d}")
    
    # Generate Excel
    filename = generate_excel(
        test_id,
        b['machine'],
        specs,
        output_dir,
        test_steps=test_steps,
    )

print(f"\nExcel files generated in {output_dir}:")
for f in sorted(output_dir.glob(f"{test_id}_*.xlsx")):
    print(f"  {f.name} ({f.stat().st_size:,} bytes)")

# Show sample test steps from SPPR (first block)
if blocks:
    first_block = blocks[0]
    first_result = build_template_skeleton(first_block)
    steps = first_result["template_data"]["TestSteps"]
    print(f"\nSample test steps from {first_block['machine']} ({len(steps)} total):")
    for i, step in enumerate(steps[:5], 1):
        print(f"  {i}. Action: {step['Action'][:60]}")
        print(f"     Expected: {step['Expected Behavior'][:60]}")
        print(f"     LED: {step['LED Indicator']} | Relay: {step['Relay Status']} | Delay: {step['Delay']}")
        print(f"     Condition: {step['Condition Type']}")
        print()
