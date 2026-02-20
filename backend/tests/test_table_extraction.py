"""
Test table extraction on real PDF data.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.table_extractor import extract_tables, get_table_by_id, get_table_row


# Sample text from your PDF (SPPR section)
SAMPLE_TEXT = """
TABLE 2 (PRODUCT SETTINGS & ACCEPTABLE LIMITS @ 415 VAC)
Under Voltage (UV): 85.00%, 347 to 357 VAC
Over Voltage (OV): 110.00%, 453 to 459 VAC
UV/OV Hys. for MAC04D0124/125: UV :- 4V (+/-2V), OV :- 7V (+/-2V)
Asymmetry: 94 VAC, 90 to 98 VAC
ON Delay: 5s, 4 to 6s
OFF Delay: 5s, 4 to 6s (Except for NUTRAL FAIL fault)
Virtual Nutral Fail V: 8 to 14 V

NOTE: All voltages are phase to Phase
"""


def test_basic_extraction():
    """Test that we can extract the table."""
    print("\n=== TEST 1: Basic Table Extraction ===")
    
    tables = extract_tables(SAMPLE_TEXT)
    
    print(f"Found {len(tables)} tables")
    assert len(tables) == 1, "Should find 1 table"
    
    table = tables[0]
    print(f"Table ID: {table['table_id']}")
    print(f"Title: {table['title']}")
    print(f"Rows: {table['num_rows']}")
    
    assert table['table_id'] == "TABLE_2"
    assert table['num_rows'] >= 6  # At least 6 parameter rows
    
    print("✅ Basic extraction works!")


def test_row_parsing():
    """Test that rows are parsed correctly."""
    print("\n=== TEST 2: Row Parsing ===")
    
    tables = extract_tables(SAMPLE_TEXT)
    table = tables[0]
    
    # Check Under Voltage row
    uv_row = get_table_row(table, "Under Voltage")
    print(f"\nUnder Voltage row: {uv_row}")
    
    assert uv_row is not None, "Should find UV row"
    assert "85.00%" in uv_row.get("setting", ""), "Should extract setting"
    assert "347 to 357" in uv_row.get("range", ""), "Should extract range"
    
    # Check Over Voltage row
    ov_row = get_table_row(table, "Over Voltage")
    print(f"Over Voltage row: {ov_row}")
    
    assert ov_row is not None, "Should find OV row"
    assert "110.00%" in ov_row.get("setting", ""), "Should extract setting"
    
    # Check ON Delay row
    on_delay_row = get_table_row(table, "ON Delay")
    print(f"ON Delay row: {on_delay_row}")
    
    assert on_delay_row is not None, "Should find ON Delay row"
    assert "5s" in on_delay_row.get("setting", ""), "Should extract delay"
    
    print("✅ Row parsing works!")


def test_all_rows():
    """Print all extracted rows."""
    print("\n=== TEST 3: All Rows ===")
    
    tables = extract_tables(SAMPLE_TEXT)
    table = tables[0]
    
    print(f"\n{table['table_id']}: {table['title']}")
    print("-" * 80)
    
    for i, row in enumerate(table['rows'], 1):
        param = row.get('parameter', 'N/A')
        setting = row.get('setting', 'N/A')
        range_val = row.get('range', 'N/A')
        
        print(f"{i}. {param}")
        print(f"   Setting: {setting}")
        print(f"   Range: {range_val}")
        print()
    
    print("✅ All rows extracted!")


if __name__ == "__main__":
    print("=" * 80)
    print("TABLE EXTRACTION TESTS")
    print("=" * 80)
    
    try:
        test_basic_extraction()
        test_row_parsing()
        test_all_rows()
        
        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED!")
        print("=" * 80)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()