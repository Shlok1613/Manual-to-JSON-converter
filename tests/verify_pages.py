"""Verify pages 32-38 contain MAG03D0424 functional test procedure with A/B/C/D sections."""
import sys
sys.path.insert(0, '.')
from pathlib import Path
from services.pdf_extractor import extract_pages

pages = extract_pages(Path('source/WI.pdf'))

for pn in range(32, 39):
    p = pages[pn - 1]
    text = p.ocr_text or ''
    print(f'=== PAGE {pn} ({len(text)} chars) ===')
    # Show key markers
    lines = text.split('\n')
    for line in lines:
        ll = line.strip()
        if any(kw in ll for kw in [
            'FUNCTIONAL TEST', 'Goal', 'DIP S/W',
            'Pot Setting', 'pot –', 'pot -',
            '120V', '277V', '240V', '415V',
            'UV trip', 'OV trip', 'hysteresis',
            'healthy', 'fault', 'Phase fail', 'Phase reverse',
            'A]', 'B]', 'C]', 'D]', 'E]', 'F]',
        ]):
            print(f'  {ll[:160]}')
    print()
