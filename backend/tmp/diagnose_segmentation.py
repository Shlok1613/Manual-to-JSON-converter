"""
Diagnostic script to see how MG-series machine headers appear in the PDF.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "c:/Users/SHLOK/Desktop/Project/Manual-to-JSON-converter/backend"))
sys.path.insert(0, "c:/Users/SHLOK/Desktop/Project/Manual-to-JSON-converter/backend")

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
import re

# Find the PDF
pdf_dir = Path("c:/Users/SHLOK/Desktop/Project/Manual-to-JSON-converter/backend/uploads")
pdfs = list(pdf_dir.glob("ext_*_FUnctional*.pdf"))
if not pdfs:
    # Try the non-prefixed version
    pdfs = list(pdf_dir.glob("FUnctional*.pdf"))
if not pdfs:
    print("No PDF found!")
    sys.exit(1)

latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
print(f"Using PDF: {latest_pdf.name}\n")

# Extract text
pages = extract_text(latest_pdf)
full_text = "\n\n".join(pages)

# Search for MG-related lines
print("=" * 80)
print("LINES CONTAINING 'MG' (showing context)")
print("=" * 80)
lines = full_text.splitlines()
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped and re.search(r'\bMG\d+', stripped, re.IGNORECASE):
        print(f"  Line {i}: [{stripped[:120]}]")

print("\n" + "=" * 80)
print("LINES CONTAINING 'DSMR' (showing context)")
print("=" * 80)
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped and re.search(r'DSMR', stripped, re.IGNORECASE):
        print(f"  Line {i}: [{stripped[:120]}]")

print("\n" + "=" * 80)
print("LINES CONTAINING 'For.*product' (showing context)")
print("=" * 80)
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped and re.search(r'For\s+\w+.*product', stripped, re.IGNORECASE):
        print(f"  Line {i}: [{stripped[:120]}]")

print("\n" + "=" * 80)
print("LINES CONTAINING 'Functional Testing' (showing context)")
print("=" * 80)
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped and re.search(r'Functional\s+Testing', stripped, re.IGNORECASE):
        print(f"  Line {i}: [{stripped[:120]}]")

# Now run segmentation and show results
print("\n" + "=" * 80)
print("CURRENT SEGMENTATION RESULTS")
print("=" * 80)
blocks = segment_blocks(full_text)
for i, block in enumerate(blocks, 1):
    header_preview = block['header'][:80] if block['header'] else "(no header)"
    text_preview = block['text'][:150].replace('\n', ' ')
    print(f"\nBlock {i}: machine={block['machine']}")
    print(f"  Header: {header_preview}")
    print(f"  Size: {len(block['text'])} chars")
    print(f"  Preview: {text_preview}...")
