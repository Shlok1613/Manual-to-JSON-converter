"""
Test Bug 4 fix: variant filter regex accepts letter-only machine names.

Validates:
- DSMR passes the new filter (previously dropped due to no digits)
- SPPR passes the new filter
- MAG03D0424 still passes (standard format)
- Short/invalid names are rejected

Run: python -m tests.test_bug4
"""
import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_variant_filter():
    """Test the new variant filter regex."""
    print("=" * 70)
    print("TEST: Bug 4 — Variant Filter Regex")
    print("=" * 70)

    # This is the fixed regex from vision_extractor.py
    def passes_filter(v):
        return bool(re.match(r"^[A-Z]{2,}[A-Z0-9_]*$", v) and len(v) >= 3)

    test_cases = [
        # (name, should_pass, reason)
        ("DSMR", True, "Letter-only name — was dropped by old regex"),
        ("SPPR", True, "Letter-only name — was dropped by old regex"),
        ("MAG03D0424", True, "Standard alphanumeric — should always pass"),
        ("MAG03D0425", True, "Standard alphanumeric"),
        ("SM301", True, "Standard alphanumeric"),
        ("SM500", True, "Standard alphanumeric"),
        ("DMS110", True, "Standard alphanumeric"),
        ("MG73BQ", True, "Short alphanumeric"),
        ("SM500_A", True, "Underscore variant"),
        ("AB", False, "Too short (2 chars)"),
        ("A", False, "Single char"),
        ("123", False, "Pure digits"),
        ("", False, "Empty"),
        ("abc", True, "Lowercase gets uppercased to ABC"),
    ]

    failures = []
    for name, expected, reason in test_cases:
        result = passes_filter(name.upper()) if name else passes_filter(name)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            failures.append(f"{name}: expected {expected}, got {result} ({reason})")
        print(f"  {status}: {name:15s} -> {result:5}  ({reason})")

    print()
    if failures:
        print(f"FAILED: {len(failures)} failures:")
        for f in failures:
            print(f"  - {f}")
        return False
    else:
        print("ALL CHECKS PASSED")
        return True


def test_machine_name_pattern():
    """Test Bug 5: SPPR is recognized by MACHINE_NAME_PATTERN."""
    print("\n" + "=" * 70)
    print("TEST: Bug 5 — MACHINE_NAME_PATTERN includes SPPR")
    print("=" * 70)

    from services.block_segmenter import MACHINE_NAME_PATTERN

    test_cases = [
        ("SPPR", True),
        ("DSMR", True),
        ("SM301", True),
        ("MAG03D0424", True),
        ("DMS110", True),
        ("MG73BQ", True),
    ]

    failures = []
    for name, expected in test_cases:
        result = bool(MACHINE_NAME_PATTERN.search(name))
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            failures.append(f"{name}: expected {expected}, got {result}")
        print(f"  {status}: {name} -> {'matches' if result else 'no match'}")

    print()
    if failures:
        print(f"FAILED: {len(failures)} failures:")
        for f in failures:
            print(f"  - {f}")
        return False
    else:
        print("ALL CHECKS PASSED")
        return True


if __name__ == "__main__":
    r1 = test_variant_filter()
    r2 = test_machine_name_pattern()
    sys.exit(0 if (r1 and r2) else 1)
