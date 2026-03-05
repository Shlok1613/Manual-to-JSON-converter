"""Check why MG73BQ and DMS120 have 0 test steps."""
import sys
sys.path.insert(0, r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend")
from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
from pathlib import Path
import re

pdf_dir = Path(r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend\uploads")
pdfs = list(pdf_dir.glob("ext_*_FUnctional*.pdf"))
latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
pages = extract_text(latest_pdf)
full_text = "\n\n".join(pages)
blocks = segment_blocks(full_text)

for b in blocks:
    if b['machine'] in ('MG73BQ', 'DMS120'):
        lines = [l.strip() for l in b['text'].splitlines() if l.strip()]
        # Show lines that look like numbered steps or section headers
        print(f"=== {b['machine']} ({len(lines)} lines) ===")
        for i, line in enumerate(lines[:40]):
            print(f"  {i:3d}: {line[:100]}")
        print()
