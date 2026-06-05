"""
Tests for variant_mapper.py — Bug A (header detection) and Bug B (forward-fill).

Run: python -m tests.test_variant_map
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.variant_mapper import (
    detect_header_row,
    build_variant_map,
    _looks_like_variant,
)


def test_looks_like_variant():
    """Test _looks_like_variant heuristic."""
    # Valid variant names
    assert _looks_like_variant("MGH3BF"), "MGH3BF should be valid"
    assert _looks_like_variant("MG73BR"), "MG73BR should be valid"
    assert _looks_like_variant("MAC04D0100"), "MAC04D0100 should be valid"
    assert _looks_like_variant("MAG03D0424"), "MAG03D0424 should be valid"
    assert _looks_like_variant("MD71B9"), "MD71B9 should be valid"
    assert _looks_like_variant("SM500"), "SM500 should be valid"
    assert _looks_like_variant("MGI3BF"), "MGI3BF should be valid"

    # Invalid — generic words
    assert not _looks_like_variant("VOLTAGE"), "VOLTAGE should NOT be valid"
    assert not _looks_like_variant("LED"), "LED should NOT be valid (too short)"
    assert not _looks_like_variant("TABLE"), "TABLE should NOT be valid (no digits)"
    assert not _looks_like_variant(""), "Empty should NOT be valid"
    assert not _looks_like_variant("VAC"), "VAC should NOT be valid"

    print("✓ _looks_like_variant tests passed")


def test_detect_header_row_with_known_variants():
    """Test header detection using known_variants hint."""
    grid = [
        ["LED/Param.", "Parameter/Settings", "MGH3BF", "MGH3BY", "MGH3BH", "MG73BR", "MGI3BF"],
        ["Green", "Healthy", "Continuous ON", "", "", "", ""],
        ["UV", "Under Voltage", "Continuous ON", "", "", "", ""],
    ]
    known = ["MGH3BF", "MGH3BY", "MGH3BH", "MG73BR", "MGI3BF"]

    header = detect_header_row(grid, known_variants=known)
    assert header == grid[0], f"Expected first row as header, got: {header}"
    print("✓ detect_header_row with known_variants passed")


def test_detect_header_row_mac_names():
    """Test header detection with MAC-style names that fail old regex."""
    grid = [
        ["Parameter", "MAC04D0100", "MAC04D0119", "MAC04D0123"],
        ["UV range", "347-357 VAC", "318-328 VAC", "318-328 VAC"],
    ]
    known = ["MAC04D0100", "MAC04D0119", "MAC04D0123"]

    header = detect_header_row(grid, known_variants=known)
    assert header == grid[0], f"Expected first row as header, got: {header}"
    print("✓ detect_header_row with MAC names passed")


def test_detect_header_row_mag_names():
    """Test header detection with MAG-style names."""
    grid = [
        ["Parameter", "MAG03D0424", "MAG03D0425", "MAG03D0426"],
        ["LV cutoff", "175V", "175V", "175V"],
    ]
    known = ["MAG03D0424", "MAG03D0425", "MAG03D0426"]

    header = detect_header_row(grid, known_variants=known)
    assert header == grid[0], f"Expected first row as header, got: {header}"
    print("✓ detect_header_row with MAG names passed")


def test_detect_header_row_no_hints():
    """Test header detection without known_variants (heuristic fallback)."""
    grid = [
        ["LED/Param.", "Parameter/Settings", "MGH3BF", "MGH3BY", "MGH3BH"],
        ["Green", "Healthy", "Continuous ON", "", ""],
    ]

    header = detect_header_row(grid, known_variants=None)
    assert header == grid[0], f"Expected first row as header, got: {header}"
    print("✓ detect_header_row without hints passed")


def test_forward_fill_merged_cells():
    """Test Bug B: merged cell values are forward-filled."""
    grid = [
        ["LED/Param.", "Parameter/Settings", "MGH3BF", "MGH3BY", "MGH3BH", "MG73BR", "MGI3BF"],
        ["Green", "Healthy", "Continuous ON", "", "", "", ""],
        ["UV", "Under Voltage", "Continuous ON", "", "", "", ""],
    ]
    known = ["MGH3BF", "MGH3BY", "MGH3BH", "MG73BR", "MGI3BF"]

    result = build_variant_map(grid, known_variants=known)

    # All 5 submachines should be present
    for v in known:
        assert v.upper() in result, f"{v} not found in result keys: {list(result.keys())}"

    # Shared "Continuous ON" must propagate to all submachines
    for v in known:
        v_upper = v.upper()
        has_continuous = any("Continuous" in str(val) for val in result[v_upper].values())
        assert has_continuous, f"Shared 'Continuous ON' not attributed to {v}: {result[v_upper]}"

    print("✓ forward_fill_merged_cells passed")


def test_specific_values_per_submachine():
    """Test that specific values are correctly attributed per-submachine."""
    grid = [
        ["Param", "MGH3BF", "MGH3BY", "MG73BR"],
        ["UV range", "177 TO 197", "177 TO 197", "163 to 183"],
        ["OV range", "232-252", "232-252", "278 to 298"],
    ]
    known = ["MGH3BF", "MGH3BY", "MG73BR"]

    result = build_variant_map(grid, known_variants=known)

    assert "163" in str(result.get("MG73BR", {}).get("uv_range", "")), \
        f"MG73BR should have 163 UV range, got: {result.get('MG73BR')}"
    assert "177" in str(result.get("MGH3BF", {}).get("uv_range", "")), \
        f"MGH3BF should have 177 UV range, got: {result.get('MGH3BF')}"
    assert "278" in str(result.get("MG73BR", {}).get("ov_range", "")), \
        f"MG73BR should have 278 OV range, got: {result.get('MG73BR')}"

    print("✓ specific_values_per_submachine passed")


def test_na_filtering():
    """Test that NA values do not leak into output."""
    grid = [
        ["Param", "MGH3BF", "MG73BR"],
        ["UV range", "177 TO 197", "NA"],
        ["OV range", "NA", "278 to 298"],
    ]
    known = ["MGH3BF", "MG73BR"]

    result = build_variant_map(grid, known_variants=known)

    # MG73BR should NOT have UV range (it was NA)
    assert "uv_range" not in result.get("MG73BR", {}), \
        f"MG73BR should NOT have uv_range (was NA), got: {result.get('MG73BR')}"

    # MGH3BF should NOT have OV range (it was NA)
    assert "ov_range" not in result.get("MGH3BF", {}), \
        f"MGH3BF should NOT have ov_range (was NA), got: {result.get('MGH3BF')}"

    # But MGH3BF SHOULD have UV range
    assert "uv_range" in result.get("MGH3BF", {}), \
        f"MGH3BF should have uv_range, got: {result.get('MGH3BF')}"

    # And MG73BR SHOULD have OV range
    assert "ov_range" in result.get("MG73BR", {}), \
        f"MG73BR should have ov_range, got: {result.get('MG73BR')}"

    print("✓ na_filtering passed")


def test_mixed_shared_and_specific():
    """Full integration test with shared+specific values."""
    grid = [
        ["LED/Param.", "Parameter/Settings", "MGH3BF", "MGH3BY", "MGH3BH", "MG73BR", "MGI3BF"],
        ["Green", "Healthy", "Continuous ON", "", "", "", ""],
        ["UV", "Under Voltage", "Continuous ON", "", "", "", ""],
        ["", "72% (173 VAC)", "NA", "NA", "NA", "163 to 183", "NA"],
        ["", "85% (187 VAC)", "177 TO 197", "177 TO 197", "177 TO 197", "NA", "NA"],
        ["", "85% (195.5 V)", "NA", "NA", "NA", "NA", "186-204 V"],
    ]
    known = ["MGH3BF", "MGH3BY", "MGH3BH", "MG73BR", "MGI3BF"]

    result = build_variant_map(grid, known_variants=known)

    # All 5 should exist
    assert len(result) == 5, f"Expected 5 variants, got {len(result)}: {list(result.keys())}"

    # No NA values should appear
    for variant, specs in result.items():
        for field, value in specs.items():
            assert str(value).upper() not in ("NA", "N/A"), \
                f"NA leaked into {variant}.{field} = {value}"

    print("✓ mixed_shared_and_specific passed")


if __name__ == "__main__":
    test_looks_like_variant()
    test_detect_header_row_with_known_variants()
    test_detect_header_row_mac_names()
    test_detect_header_row_mag_names()
    test_detect_header_row_no_hints()
    test_forward_fill_merged_cells()
    test_specific_values_per_submachine()
    test_na_filtering()
    test_mixed_shared_and_specific()
    print("\n✅ ALL variant_map tests passed!")
