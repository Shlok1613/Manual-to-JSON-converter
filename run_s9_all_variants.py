#!/usr/bin/env python3
"""Test all 6 MAG variants from WI.pdf."""
import sys
import time
from datetime import datetime
from pathlib import Path

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

# Variants to test
VARIANTS = ['MAG03D0424', 'MAG03D0424EG', 'MAG03D0425', 'MAG03D0426', 'MAG03D0428', 'MAG03D0427']
REF_FILE = 'source/1M SPP SM175 AUTO FUNCTION All CatID.xlsx'

print(f"Starting variant testing at {datetime.now().isoformat()}")
print(f"Output directory: {OUTPUT_DIR}")
print()

# Load PDF once
pages = extract_pages(Path('source/WI.pdf'))
blocks = segment_blocks(pages)

results = []

for variant_name in VARIANTS:
    print(f"\n{'='*60}")
    print(f"Testing: {variant_name}")
    print(f"{'='*60}")
    
    # Find block for this machine
    machine_blocks = [b for b in blocks if b.machine == variant_name.split('EG')[0]]
    if not machine_blocks:
        print(f"  ERROR: No block found for {variant_name}")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'steps': 0,
            'layout': 'N/A',
            'status': 'BLOCK_NOT_FOUND'
        })
        continue
    
    block = machine_blocks[0]
    
    # Extract
    try:
        variants = extract_machine_data(block=block, sub_machines=[variant_name])
        time.sleep(10)  # Quota protection
    except Exception as e:
        print(f"  ERROR: Extraction failed: {e}")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'steps': 0,
            'layout': 'N/A',
            'status': 'EXTRACTION_ERROR'
        })
        continue
    
    if not variants:
        print(f"  WARNING: No variants extracted")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'steps': 0,
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
    
    # Write and compare
    vdata = variants.get(variant_name)
    if not vdata:
        print(f"  WARNING: Variant data not found")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'steps': 0,
            'layout': 'N/A',
            'status': 'NO_VARIANT_DATA'
        })
        continue
    
    usable = vdata.is_usable()
    print(f"  Steps: {len(vdata.test_steps)}")
    print(f"  Usable: {usable}")
    
    if usable:
        # Determine layout from first run
        from services.template_writer import detect_layout
        layout = detect_layout(vdata.specs, test_steps=vdata.test_steps)
        layout_name = 'A' if layout['has_dip_block'] else 'B'
        print(f"  Layout: {layout_name}")
        
        fpath = write_variant_workbook(
            's9_variants',
            block.machine,
            vdata,
            OUTPUT_DIR
        )
        print(f"  Output: {fpath.name}")
        
        # Compare
        gen_file = str(fpath)
        try:
            # Capture output
            import io
            from contextlib import redirect_stdout
            
            f = io.StringIO()
            with redirect_stdout(f):
                compare_excel.compare(gen_file, REF_FILE, variant_name)
            output = f.getvalue()
            
            # Extract accuracy line
            for line in output.split('\n'):
                if '===' in line and variant_name in line:
                    # Format: "=== MAG03D0424: 329/374 = 88.0% ==="
                    parts = line.split('=')[-1].strip()
                    if '%' in parts:
                        accuracy_pct = float(parts.split('%')[0].strip())
                        break
            else:
                accuracy_pct = 0.0
            
            print(f"  Accuracy: {accuracy_pct:.1f}%")
            results.append({
                'variant': variant_name,
                'accuracy': f"{accuracy_pct:.1f}%",
                'steps': len(vdata.test_steps),
                'layout': layout_name,
                'status': 'OK'
            })
        except Exception as e:
            print(f"  ERROR during comparison: {e}")
            results.append({
                'variant': variant_name,
                'accuracy': 'N/A',
                'steps': len(vdata.test_steps),
                'layout': layout_name,
                'status': f'COMPARE_ERROR: {str(e)[:30]}'
            })
    else:
        print(f"  WARNING: Data not usable")
        results.append({
            'variant': variant_name,
            'accuracy': 'N/A',
            'steps': len(vdata.test_steps),
            'layout': 'N/A',
            'status': 'NOT_USABLE'
        })

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
for r in results:
    print(f"{r['variant']:15} {r['accuracy']:>8} steps={r['steps']:2} layout={r['layout']} status={r['status']}")

# Count passes
passes = [r for r in results if r['status'] == 'OK' and r['accuracy'] != 'N/A']
passed = sum(1 for r in passes if float(r['accuracy'].rstrip('%')) >= 85)
print(f"\nPassed ≥85%: {passed}/5 (target: ≥3)")
print(f"Done at {datetime.now().isoformat()}")
