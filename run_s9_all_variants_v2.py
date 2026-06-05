#!/usr/bin/env python3
"""Test each remaining MAG variant individually."""
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

from services.pdf_extractor import extract_pages
from services.block_segmenter import segment_blocks
from services.vision_extractor import extract_machine_data
from services.enricher import enrich_variant
from services.normalizer import normalize_variant
from services.spec_linker import link_specs_to_steps
from services.validator import validate_variants
from services.template_writer import write_variant_workbook
import tools.compare_excel as compare_excel

OUTPUT_DIR = Path('outputs/s9_variants')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Variants to test (excluding MAG03D0424 which we already tested)
VARIANTS_TO_TEST = [
    ('MAG03D0424EG', 'A'),  # Expected layout
    ('MAG03D0425', 'A'),
    ('MAG03D0426', 'A'),
    ('MAG03D0428', 'B'),  # Layout B (cutoff)
    ('MAG03D0427', 'B'),  # Layout B (cutoff)
]
REF_FILE = 'source/1M SPP SM175 AUTO FUNCTION All CatID.xlsx'

print(f"Starting multi-variant testing at {datetime.now().isoformat()}")
print(f"Output directory: {OUTPUT_DIR}\n")

# Load PDF once
pages = extract_pages(Path('source/WI.pdf'))
blocks = segment_blocks(pages)

results = []

for variant_name, expected_layout in VARIANTS_TO_TEST:
    print(f"\n{'='*60}")
    print(f"Testing: {variant_name} (expect Layout {expected_layout})")
    print(f"{'='*60}")
    
    base_machine = variant_name.split('EG')[0]  # Strip EG suffix if present
    
    # Find block for this machine
    machine_blocks = [b for b in blocks if b.machine == base_machine]
    if not machine_blocks:
        print(f"  ERROR: No block found for {base_machine}")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'layout': 'N/A',
            'status': 'BLOCK_NOT_FOUND'
        })
        continue
    
    block = machine_blocks[0]
    
    # Extract
    try:
        print(f"  Extracting {variant_name}...")
        variants = extract_machine_data(block=block, sub_machines=[variant_name])
        time.sleep(10)  # Quota protection between variants
    except Exception as e:
        print(f"  ERROR: Extraction failed: {e}")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'layout': 'N/A',
            'status': f'ERROR: {str(e)[:50]}'
        })
        continue
    
    if not variants:
        print(f"  WARNING: No variants extracted")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'layout': 'N/A',
            'status': 'NO_DATA'
        })
        continue
    
    # Process
    for vname, vdata in variants.items():
        vdata = enrich_variant(vdata, block.text)
        vdata = normalize_variant(vdata)
        variants[vname] = vdata
    
    variants = link_specs_to_steps(variants)
    variants = validate_variants(variants)
    
    # Get variant data
    vdata = variants.get(variant_name)
    if not vdata:
        print(f"  WARNING: Variant data not found")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'layout': 'N/A',
            'status': 'NO_VARIANT_DATA'
        })
        continue
    
    usable = vdata.is_usable()
    print(f"  Steps: {len(vdata.test_steps)}")
    print(f"  Usable: {usable}")
    
    if usable:
        # Determine layout
        from services.template_writer import detect_layout
        layout = detect_layout(vdata.specs, test_steps=vdata.test_steps)
        layout_name = 'A' if layout['has_dip_block'] else 'B'
        print(f"  Layout: {layout_name} (expected: {expected_layout})")
        
        if layout_name != expected_layout:
            print(f"  WARNING: Layout mismatch! Expected {expected_layout}, got {layout_name}")
        
        # Write
        filename = write_variant_workbook(
            's9_variants',
            base_machine,
            vdata,
            OUTPUT_DIR
        )
        fpath = OUTPUT_DIR / filename
        print(f"  Output: {filename}")
        
        # Compare
        try:
            import io
            from contextlib import redirect_stdout
            
            f = io.StringIO()
            with redirect_stdout(f):
                compare_excel.compare(str(fpath), REF_FILE, variant_name)
            output = f.getvalue()
            
            # Extract accuracy
            for line in output.split('\n'):
                if f'{variant_name}:' in line and '===' in line:
                    parts = line.split('=')[-1].strip()
                    if '%' in parts:
                        accuracy_str = parts.split('%')[0].strip()
                        accuracy_pct = float(accuracy_str)
                        break
            else:
                accuracy_pct = 0.0
            
            status = 'OK' if accuracy_pct >= 85 else 'LOW'
            print(f"  Accuracy: {accuracy_pct:.1f}% [{status}]")
            results.append({
                'variant': variant_name,
                'accuracy': f"{accuracy_pct:.1f}%",
                'layout': layout_name,
                'status': status
            })
        except Exception as e:
            print(f"  ERROR during comparison: {e}")
            results.append({
                'variant': variant_name,
                'accuracy': 'N/A',
                'layout': layout_name,
                'status': f'COMPARE_ERROR'
            })
    else:
        print(f"  WARNING: Data not usable")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'layout': 'N/A',
            'status': 'NOT_USABLE'
        })

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
for r in results:
    status_marker = '✓' if r['status'] == 'OK' else '✗' if r['status'] == 'LOW' else '-'
    print(f"{status_marker} {r['variant']:15} {r['accuracy']:>8} layout={r['layout']} {r['status']}")

# Count passes
passes = [r for r in results if r['status'] == 'OK' and '%' in r['accuracy']]
print(f"\nPassed ≥85%: {len(passes)}/5 (target: ≥3)")
print(f"Done at {datetime.now().isoformat()}")
