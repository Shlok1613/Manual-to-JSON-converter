"""
Debug table parsing to see what's happening
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
from services.table_extractor import detect_table_headers, parse_table_rows


def debug_table_parsing():
    # Get PDF
    pdf_path = Path(__file__).parent.parent / "uploads"
    pdfs = list(pdf_path.glob("ext_*_FUnctional*.pdf"))
    if not pdfs:
        print("❌ No PDF found")
        return
    
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
        print("❌ SPPR not found")
        return
    
    print("=" * 80)
    print("DEBUG: TABLE PARSING")
    print("=" * 80)
    
    # Step 1: Find table headers
    print("\nSTEP 1: Detect table headers")
    print("-" * 80)
    headers = detect_table_headers(sppr_block['text'])
    
    for i, header in enumerate(headers, 1):
        print(f"\n{i}. {header['table_id']}: {header['title']}")
        print(f"   Start line: {header['start_line']}")
        print(f"   Header text: {header['header_text']}")
    
    # Step 2: Parse first table
    if headers:
        print("\n\nSTEP 2: Parse TABLE_2 rows")
        print("-" * 80)
        
        table2 = None
        for header in headers:
            if header['table_id'] == 'TABLE_2':
                table2 = header
                break
        
        if table2:
            # Show the next 20 lines after table header
            lines = sppr_block['text'].splitlines()
            start = table2['start_line']
            
            print(f"\nShowing lines {start-5} to {start+20} (including context BEFORE table):")
            print("-" * 80)
            for i in range(max(0, start - 5), min(start + 20, len(lines))):
                marker = ">>> " if i == start else "    "
                print(f"{marker}{i}: {lines[i]}")
            
            # Now parse the rows
            print("\n\nParsing rows...")
            print("-" * 80)
            rows_data = parse_table_rows(sppr_block['text'], table2['start_line'])
            
            print(f"\nResult:")
            print(f"  Headers detected: {rows_data.get('headers', [])}")
            print(f"  Number of rows: {len(rows_data.get('rows', []))}")
            
            if rows_data.get('rows'):
                print(f"\nFirst 3 rows:")
                for i, row in enumerate(rows_data['rows'][:3], 1):
                    print(f"\n  Row {i}:")
                    print(f"    Parameter: {row.get('parameter', 'N/A')}")
                    print(f"    Setting: {row.get('setting', 'N/A')}")
                    
                    if 'values' in row and row['values']:
                        print(f"    Values:")
                        for variant, value in row['values'].items():
                            print(f"      {variant}: {value}")
                    
                    if 'raw_value' in row:
                        print(f"    Raw: {row.get('raw_value', 'N/A')[:100]}...")


if __name__ == "__main__":
    debug_table_parsing()