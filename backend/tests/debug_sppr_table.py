"""
Debug: Show actual text around TABLE 2 in SPPR
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks


def debug_sppr():
    # Get PDF
    pdf_path = Path(__file__).parent.parent / "uploads"
    pdfs = list(pdf_path.glob("ext_*_FUnctional*.pdf"))
    latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
    
    # Extract
    pages = extract_text(latest_pdf)
    full_text = "\n\n".join(pages)
    blocks = segment_blocks(full_text)
    
    # Find SPPR
    sppr_block = None
    for block in blocks:
        if "SPPR" in block["machine"]:
            sppr_block = block
            break
    
    if not sppr_block:
        print("No SPPR found")
        return
    
    # Find TABLE 2 in text
    lines = sppr_block['text'].splitlines()
    
    for i, line in enumerate(lines):
        if 'TABLE' in line.upper() and '2' in line:
            print(f"\nFound at line {i}: {line}")
            print("-" * 80)
            print("Next 15 lines:")
            print("-" * 80)
            for j in range(i+1, min(i+16, len(lines))):
                print(f"{j-i}: {lines[j]}")
            print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    debug_sppr()