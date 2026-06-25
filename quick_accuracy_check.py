#!/usr/bin/env python3
"""Quick accuracy check for completed variants."""
import sys
from pathlib import Path

sys.path.insert(0, '.')
import tools.compare_excel as compare_excel
import io
from contextlib import redirect_stdout

OUTPUT_DIR = Path('outputs/s9_variants')
REF_FILE = 'source/1M SPP SM175 AUTO FUNCTION All CatID.xlsx'

VARIANTS = [
    ('MAG03D0424EG', 's9_variants_MAG03D0424_MAG03D0424EG.xlsx'),
    ('MAG03D0425', 's9_variants_MAG03D0425.xlsx'),
    ('MAG03D0426', 's9_variants_MAG03D0426.xlsx'),
]

print("\nQUICK ACCURACY CHECK\n" + "="*60)

for variant_name, filename in VARIANTS:
    fpath = OUTPUT_DIR / filename
    
    if not fpath.exists():
        print(f"[!] {variant_name}: FILE NOT FOUND ({filename})")
        continue
    
    try:
        f = io.StringIO()
        with redirect_stdout(f):
            compare_excel.compare(str(fpath), REF_FILE, variant_name)
        output = f.getvalue()
        
        accuracy_pct = 0.0
        for line in output.split('\n'):
            if '===' in line and '%' in line:
                parts = line.split('=')[-1].strip()
                if '%' in parts:
                    accuracy_str = parts.split('%')[0].strip()
                    accuracy_pct = float(accuracy_str)
                    break
        
        status = '[OK]' if accuracy_pct >= 85 else '[LOW]'
        print(f"[+] {variant_name}: {accuracy_pct:.1f}% {status}")
    except Exception as e:
        print(f"[X] {variant_name}: ERROR - {str(e)[:50]}")

print("="*60)
