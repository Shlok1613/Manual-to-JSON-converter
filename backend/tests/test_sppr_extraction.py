"""
Test extraction on SPPR block specifically.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
from services.table_extractor import extract_tables
from services.spec_parser import parse_specifications, format_spec_summary


def test_sppr():
    """Test SPPR extraction specifically."""
    
    # Get the PDF
    pdf_path = Path(__file__).parent.parent / "uploads"
    pdfs = list(pdf_path.glob("ext_*_FUnctional*.pdf"))
    if not pdfs:
        print("❌ No PDF found!")
        return
    
    latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
    
    # Extract and segment
    pages = extract_text(latest_pdf)
    full_text = "\n\n".join(pages)
    blocks = segment_blocks(full_text)
    
    # Find SPPR block
    sppr_block = None
    for block in blocks:
        if "SPPR" in block["machine"]:
            sppr_block = block
            break
    
    if not sppr_block:
        print("❌ SPPR block not found!")
        return
    
    print("=" * 80)
    print(f"SPPR BLOCK ANALYSIS")
    print("=" * 80)
    print(f"Machine: {sppr_block['machine']}")
    print(f"Header: {sppr_block['header']}")
    print(f"Text length: {len(sppr_block['text'])} chars\n")
    
    # Extract tables
    tables = extract_tables(sppr_block['text'])
    print(f"Tables found: {len(tables)}\n")
    
    for i, table in enumerate(tables, 1):
        print(f"Table {i}: {table['table_id']} - {table['title']}")
        print(f"  Rows: {table['num_rows']}")
        print(f"  Sample rows:")
        for row in table['rows'][:3]:
            print(f"    - {row.get('parameter', 'N/A')}: {row.get('setting', 'N/A')}")
        print()
    
    # Parse specifications
    specs = parse_specifications(sppr_block['text'], tables)
    
    print("\n" + format_spec_summary(specs))
    
    print("\n" + "=" * 80)
    print("VOLTAGE PARAMETERS DETAIL:")
    print("=" * 80)
    for param, data in specs.get('voltage_parameters', {}).items():
        print(f"\n{param}:")
        print(f"  Setting: {data.get('setting', 'N/A')}")
        print(f"  Range: {data.get('range', 'N/A')}")
        print(f"  Raw: {data.get('raw', 'N/A')}")


if __name__ == "__main__":
    test_sppr()