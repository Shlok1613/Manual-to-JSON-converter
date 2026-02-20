"""
Test on actual PDF to see block segmentation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks, get_block_summary


def test_real_pdf():
    """Test on your actual PDF."""
    
    # Path to your PDF in uploads
    pdf_path = Path(__file__).parent.parent / "uploads"
    
    # Find the most recent PDF
    pdfs = list(pdf_path.glob("ext_*_FUnctional*.pdf"))
    if not pdfs:
        print("❌ No PDF found! Upload one first.")
        return
    
    latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
    print(f"Testing with: {latest_pdf.name}\n")
    
    # Extract text
    pages = extract_text(latest_pdf)
    full_text = "\n\n".join(pages)
    
    print(f"Extracted {len(pages)} pages, {len(full_text)} characters\n")
    
    # Segment blocks
    blocks = segment_blocks(full_text)
    
    print(get_block_summary(blocks))
    print("\n" + "=" * 80)
    
    # Show first few lines of each block
    for i, block in enumerate(blocks[:5], 1):
        print(f"\n{i}. {block['machine']} - {block['header'][:60]}")
        print("-" * 80)
        
        # Show first 200 chars
        preview = block['text'][:200].replace('\n', ' ')
        print(f"Preview: {preview}...")
        
        # Show if it has tables
        from services.table_extractor import extract_tables
        tables = extract_tables(block['text'])
        print(f"Tables found: {len(tables)}")


if __name__ == "__main__":
    test_real_pdf()