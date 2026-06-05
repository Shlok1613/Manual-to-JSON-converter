# Session 9 Variant Testing Plan

## Objective
Test all 6 MAG variants to determine:
1. Which variants exceed 85% accuracy threshold
2. Whether layout detection fix works for both Layout A and Layout B machines
3. Overall pipeline stability across variant diversity

## Variants to Test

| Variant | Expected Layout | Pages | Reference Cells | Status |
|---------|-----------------|-------|-----------------|--------|
| MAG03D0424 | A (3-phase layout) | 7-13 | 374 | TESTING |
| MAG03D0424EG | A (3-phase layout) | Same section as 0424 | TBD | TESTING |
| MAG03D0425 | A (3-phase layout) | TBD | TBD | TESTING |
| MAG03D0426 | A (3-phase layout) | TBD | TBD | TESTING |
| MAG03D0428 | B (cutoff layout) | TBD | TBD | TESTING |
| MAG03D0427 | B (cutoff layout) | TBD | TBD | TESTING |

## Success Criteria
- **Primary**: ≥3 variants with ≥85% accuracy
- **Secondary**: Both Layout A and B detection working
- **Validation**: Layout A/B correctly assigned by updated `detect_layout()`

## Test Configuration
- **PDF**: source/WI.pdf (62 pages, image-only)
- **Reference**: source/1M SPP SM175 AUTO FUNCTION All CatID.xlsx
- **Output**: outputs/s9_variants/
- **Quota Protection**: 10-second delay between variants
- **Timeout**: ~10 minutes for full suite

## Expected Outcomes

### Layout A Variants (0424, 0424EG, 0425, 0426)
- Should detect Layout A (has_dip_block=True)
- Should extract 3-phase voltages (voltage_pp present)
- Expected accuracy: 85-90% (based on S9-R1/R3 pattern)
- Known issues: DIP switches, asymmetry voltages, settings mismatches

### Layout B Variants (0427, 0428)
- Should detect Layout B (has_dip_block=False)
- Should extract single/dual-phase voltages (no voltage_pp)
- Expected accuracy: May be higher (simpler structure)

## Running Test
```bash
python3 run_s9_all_variants.py 2>&1 | tee run_s9_all_variants.log
```

## Output Format
Summary table with:
- Variant name
- Accuracy %
- Step count
- Layout (A/B)
- Status (OK, NOT_USABLE, ERROR, etc)

Final pass count: "Passed ≥85%: X/5"
