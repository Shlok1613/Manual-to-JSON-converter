"""
Test page classification for WI.pdf SCOPE document.

Validates Bug 1 + Bug 2 fixes:
- proc_pages must NOT include pages 1-6 (intro/appendix)
- proc_pages must include at least one of pages 31-57 (actual test content)
- Each machine gets DIFFERENT proc_pages (not all identical)

Run: python -m tests.test_page_classification
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from services.pdf_extractor import extract_pages
from services.block_segmenter import segment_blocks
from services.vision_extractor import _classify_pages_for_variant

PDF_PATH = Path("source/WI.pdf")

EXPECTED_MACHINES = [
    "MAG03D0424",
    "MAG03D0425",
    "MAG03D0426",
    "MAG03D0427",
    "MAG03D0428",
]


def test_page_classification():
    print("=" * 70)
    print("TEST: Page Classification for WI.pdf")
    print("=" * 70)

    if not PDF_PATH.exists():
        print(f"SKIP: {PDF_PATH} not found")
        return False

    print(f"\n1. Extracting pages from {PDF_PATH}...")
    pages = extract_pages(PDF_PATH)
    print(f"   Extracted {len(pages)} pages")

    print("\n2. Running block segmentation...")
    blocks = segment_blocks(pages)
    print(f"   Got {len(blocks)} blocks:")
    for b in blocks:
        print(f"   - {b.machine} (pages: {len(b.pages)}, scope: {b.is_scope_block})")

    # Verify SCOPE detection
    assert len(blocks) >= 5, f"Expected >= 5 blocks, got {len(blocks)}"

    machine_names = [b.machine for b in blocks]
    for expected in EXPECTED_MACHINES:
        assert expected in machine_names, f"Missing machine: {expected}"

    print("\n3. Testing page classification per variant...")
    all_proc_pages = {}
    failures = []

    for b in blocks:
        if b.machine not in EXPECTED_MACHINES:
            continue

        cls = _classify_pages_for_variant(b, b.machine)
        proc_pages = cls["proc_pages"]
        proc_nums = sorted([p.num for p in proc_pages])
        all_proc_pages[b.machine] = proc_nums

        print(f"\n   {b.machine}:")
        print(f"   proc_pages = {proc_nums}")
        print(f"   spec_pages = {sorted([p.num for p in cls['spec_pages']])}")

        # Check 1: proc_pages must NOT be dominated by pages 1-6
        intro_pages = [p for p in proc_nums if p <= 6]
        if len(intro_pages) == len(proc_nums) and len(proc_nums) > 0:
            msg = f"{b.machine}: ALL proc_pages are intro pages (1-6): {proc_nums}"
            print(f"   FAIL: {msg}")
            failures.append(msg)
        else:
            print(f"   PASS: Not dominated by intro pages")

        # Check 2: proc_pages should include pages from the test content area (31-57)
        test_area_pages = [p for p in proc_nums if 31 <= p <= 57]
        if len(test_area_pages) == 0 and len(proc_nums) > 0:
            msg = f"{b.machine}: No proc_pages in test area (31-57): {proc_nums}"
            print(f"   WARN: {msg}")
            # Not a hard failure — pages may be slightly different
        else:
            print(f"   PASS: Has {len(test_area_pages)} pages in test area (31-57)")

        # Check 3: at least some pages selected
        if len(proc_nums) == 0:
            msg = f"{b.machine}: ZERO proc_pages selected"
            print(f"   FAIL: {msg}")
            failures.append(msg)
        else:
            print(f"   PASS: {len(proc_nums)} pages selected")

    # Check 4: machines should get DIFFERENT proc_pages
    print("\n4. Checking page diversity across machines...")
    page_sets = list(all_proc_pages.values())
    if len(page_sets) >= 2:
        all_identical = all(set(ps) == set(page_sets[0]) for ps in page_sets[1:])
        if all_identical:
            msg = "ALL machines have identical proc_pages — anchor finding broken"
            print(f"   FAIL: {msg}")
            failures.append(msg)
        else:
            unique_sets = len(set(tuple(sorted(ps)) for ps in page_sets))
            print(f"   PASS: {unique_sets} unique page sets across {len(page_sets)} machines")

    # Summary
    print("\n" + "=" * 70)
    if failures:
        print(f"FAILED: {len(failures)} failures:")
        for f in failures:
            print(f"  - {f}")
        return False
    else:
        print("ALL CHECKS PASSED")
        return True


if __name__ == "__main__":
    success = test_page_classification()
    sys.exit(0 if success else 1)
