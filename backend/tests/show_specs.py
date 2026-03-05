"""Show JUST the spec keys and values for SPPR - clean format."""
import sys
sys.path.insert(0, r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend")
from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
from services.table_extractor import extract_tables
from services.spec_parser import parse_specifications
from pathlib import Path
import json

pdf_dir = Path(r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend\uploads")
pdfs = list(pdf_dir.glob("ext_*_FUnctional*.pdf"))
latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
pages = extract_text(latest_pdf)
full_text = "\n\n".join(pages)
blocks = segment_blocks(full_text)

for b in blocks:
    if b['machine'] == 'SPPR':
        tables = extract_tables(b['text'])
        specs = parse_specifications(b['text'], tables)
        # Write to file for clean reading
        with open("tests/sppr_specs.json", "w") as f:
            json.dump(specs, f, indent=2, default=str)
        print("Wrote tests/sppr_specs.json")
        
        # Key summary
        print(f"\nref_voltage: {specs.get('reference_voltage')}")
        vp = specs.get('voltage_parameters', {})
        print(f"\nvoltage_parameters keys: {list(vp.keys())}")
        for k, v in vp.items():
            print(f"  {k}: setting={v.get('setting')}, variants={v.get('variants')}")
        
        tp = specs.get('timing_parameters', {})
        print(f"\ntiming_parameters keys: {list(tp.keys())}")
        for k, v in tp.items():
            print(f"  {k}: {v}")
        
        print(f"\nled_states: {len(specs.get('led_states', []))} items")
        for ls in specs.get('led_states', [])[:5]:
            print(f"  {ls}")
        
        print(f"\nrelay_states: {len(specs.get('relay_states', []))} items")
        for rs in specs.get('relay_states', [])[:3]:
            print(f"  {rs}")
        
        print(f"\npercentages: {len(specs.get('percentages', []))} items")
        for p in specs.get('percentages', [])[:5]:
            print(f"  {p}")
