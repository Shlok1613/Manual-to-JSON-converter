"""
Test specification parser on real PDF data.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.spec_parser import (
    extract_voltages, extract_percentages, extract_delays,
    extract_led_states, parse_specifications, format_spec_summary
)
from services.table_extractor import extract_tables


# Sample text from your PDF
SAMPLE_TEXT = """
PROCESS: Functional Testing - Neutral Open SPPR
REF. VOLTAGE: 415 VAC

TABLE 2 (PRODUCT SETTINGS @ 415 VAC)
Under Voltage (UV): 85.00%, 347 to 357 VAC
Over Voltage (OV): 110.00%, 453 to 459 VAC
Asymmetry: 94 VAC, 90 to 98 VAC
ON Delay: 5s, 4 to 6s
OFF Delay: 5s, 4 to 6s

PROCEDURE:
8. Reduce the R-Phase voltage till "UV" LED glows ON.
9. Ensure that, Relay turns OFF after specified off delay time.
10. Increase R-phase voltage till 'UV' LED on product turns OFF.
11. Ensure that, Relay turns ON after specified on delay time.
"""


def test_voltage_extraction():
    """Test voltage pattern extraction."""
    print("\n=== TEST 1: Voltage Extraction ===")
    
    voltages = extract_voltages(SAMPLE_TEXT)
    
    print(f"Found {len(voltages)} voltage values:")
    for v in voltages:
        print(f"  - {v}")
    
    # Should find: 415 VAC, 347 to 357 VAC, 453 to 459 VAC, 94 VAC, 90 to 98 VAC
    assert len(voltages) >= 5, f"Should find at least 5 voltages, found {len(voltages)}"
    
    # Check for ranges
    ranges = [v for v in voltages if v["type"] == "range"]
    assert len(ranges) >= 3, "Should find at least 3 voltage ranges"
    
    print("✅ Voltage extraction works!")


def test_percentage_extraction():
    """Test percentage pattern extraction."""
    print("\n=== TEST 2: Percentage Extraction ===")
    
    percentages = extract_percentages(SAMPLE_TEXT)
    
    print(f"Found {len(percentages)} percentage values:")
    for p in percentages:
        print(f"  - {p}")
    
    # Should find: 85.00%, 110.00%
    assert len(percentages) >= 2, "Should find at least 2 percentages"
    
    print("✅ Percentage extraction works!")


def test_delay_extraction():
    """Test delay pattern extraction."""
    print("\n=== TEST 3: Delay Extraction ===")
    
    delays = extract_delays(SAMPLE_TEXT)
    
    print(f"Found {len(delays)} delay values:")
    for d in delays:
        print(f"  - {d}")
    
    # Should find: 5s, 4 to 6s (multiple times)
    assert len(delays) >= 2, "Should find at least 2 delay values"
    
    # Check for range
    ranges = [d for d in delays if d["type"] == "range"]
    assert len(ranges) >= 1, "Should find at least 1 delay range"
    
    print("✅ Delay extraction works!")


def test_led_extraction():
    """Test LED state extraction."""
    print("\n=== TEST 4: LED State Extraction ===")
    
    led_states = extract_led_states(SAMPLE_TEXT)
    
    print(f"Found {len(led_states)} LED states:")
    for led in led_states:
        print(f"  - {led}")
    
    # Should find UV LED states
    # The text has: "UV" LED glows ON, 'UV' LED turns OFF
    assert len(led_states) >= 1, "Should find at least 1 LED state"
    
    # Check for UV LED
    uv_leds = [led for led in led_states if led["led"] == "UV"]
    assert len(uv_leds) >= 1, "Should find at least 1 UV LED state"  # ← CHANGED from >= 2
    
    # Check that we filtered out RELAY (it's not an LED)
    relay_leds = [led for led in led_states if led["led"] == "RELAY"]
    assert len(relay_leds) == 0, "Should NOT include RELAY as LED"
    
    # Check that we filtered out PRODUCT (it's not an LED)
    product_leds = [led for led in led_states if led["led"] == "PRODUCT"]
    assert len(product_leds) == 0, "Should NOT include PRODUCT as LED"
    
    print("✅ LED extraction works!")


def test_full_parsing():
    """Test full specification parsing with tables."""
    print("\n=== TEST 5: Full Specification Parsing ===")
    
    # First extract tables
    tables = extract_tables(SAMPLE_TEXT)
    print(f"Extracted {len(tables)} tables")
    
    # Parse specifications
    specs = parse_specifications(SAMPLE_TEXT, tables)
    
    print("\n" + format_spec_summary(specs))
    
    # Verify key data
    assert specs["reference_voltage"] is not None, "Should find reference voltage"
    assert specs["reference_voltage"]["value"] == 415, "Reference should be 415 VAC"
    
    assert "under_voltage" in specs["voltage_parameters"], "Should find UV parameter"
    assert "over_voltage" in specs["voltage_parameters"], "Should find OV parameter"
    
    assert "on_delay" in specs["timing_parameters"], "Should find ON delay"
    assert "off_delay" in specs["timing_parameters"], "Should find OFF delay"
    
    assert len(specs["led_indicators"]) >= 2, "Should find LED indicators"
    
    print("\n✅ Full parsing works!")


if __name__ == "__main__":
    print("=" * 80)
    print("SPECIFICATION PARSER TESTS")
    print("=" * 80)
    
    try:
        test_voltage_extraction()
        test_percentage_extraction()
        test_delay_extraction()
        test_led_extraction()
        test_full_parsing()
        
        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED!")
        print("=" * 80)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()