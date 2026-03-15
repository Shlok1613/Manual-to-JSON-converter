"""Final verification: comprehensive conditions + WI.pdf machine naming."""
import sys, warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend")

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
from services.table_extractor import extract_tables
from services.spec_parser import parse_specifications
from services.condition_generator import generate_comprehensive_conditions
from services.excel_writer import generate_excel
from pathlib import Path

output_dir = Path(r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend\outputs")

# ─── TEST 1: FUnctional PDF ───
print("=" * 60)
print("TEST 1: FUnctional_Testing_WI_Five_series.pdf")
print("=" * 60)
pdfs = list(Path("uploads").glob("ext_*_FUnctional*.pdf"))
if pdfs:
    pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
    pages = extract_text(pdf)
    blocks = segment_blocks("\n\n".join(pages))
    tid = "ext_comprehensive"
    
    print(f"Blocks: {len(blocks)}")
    print(f"{'Machine':16s} {'VoltC':>6s} {'ProcC':>6s} {'Total':>6s}")
    print("-" * 40)
    
    for b in blocks:
        tables = extract_tables(b['text'])
        specs = parse_specifications(b['text'], tables)
        conds = generate_comprehensive_conditions(specs, b['text'])
        
        # Count voltage vs procedure conditions
        volt_types = {'healthy condition', 'UV Healthy condition', 'UV faulty', 'UV hysteresis',
                      'OV Healthy', 'OV faulty', 'OV hysteresis', 'Asymmetry', 'Supply OFF'}
        volt_count = sum(1 for c in conds if any(v in c['test_case'] for v in volt_types))
        proc_count = len(conds) - volt_count
        
        print(f"{b['machine']:16s} {volt_count:6d} {proc_count:6d} {len(conds):6d}")
        generate_excel(tid, b['machine'], specs, output_dir, test_conditions=conds)
    
    # Show SPPR conditions in detail
    for b in blocks:
        if b['machine'] == 'SPPR':
            tables = extract_tables(b['text'])
            specs = parse_specifications(b['text'], tables)
            conds = generate_comprehensive_conditions(specs, b['text'])
            print(f"\n  SPPR conditions ({len(conds)} total):")
            for i, c in enumerate(conds, 1):
                print(f"    {i:2d}. {c['test_case']:40s} | {c['relay_status']:20s} | {c['on_delay']}")
            break
else:
    print("  No FUnctional PDF found")

# ─── TEST 2: WI.pdf ───
print("\n" + "=" * 60)
print("TEST 2: WI.pdf (MAG03D series)")
print("=" * 60)
wi_pdfs = list(Path("uploads").glob("*WI*.pdf"))
wi_pdfs = [p for p in wi_pdfs if 'Five_series' not in p.name]
if wi_pdfs:
    wi = wi_pdfs[0]
    print(f"File: {wi.name}")
    pages = extract_text(wi)
    blocks = segment_blocks("\n\n".join(pages))
    
    print(f"Blocks: {len(blocks)}")
    for b in blocks:
        print(f"  {b['machine']:20s} {len(b['text']):6d} chars")
else:
    print("  No WI.pdf found")
