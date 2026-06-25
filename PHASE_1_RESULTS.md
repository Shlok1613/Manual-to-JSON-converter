# Session 9 - Test Phase Results

## Phase 1: Variant Testing (IN PROGRESS)

### Completed Variants Results

| Variant | Accuracy | Status | Notes |
|---------|----------|--------|-------|
| MAG03D0424EG | 63.0% | ❌ FAIL | Generated 235/373 cells; expected ≥85% |
| MAG03D0425 | 0.4% | ❌ FAIL | Generated 2/506 cells; severe data mismatch |
| MAG03D0426 | 26.3% | ❌ FAIL | Generated 119/452 cells; incomplete extraction |
| MAG03D0428 | PENDING | ⏳ | Hitting API rate limits (429 errors) |
| MAG03D0427 | NOT STARTED | ⏳ | Awaiting MAG03D0428 completion |

### Current Status
- **Target**: ≥3 variants with ≥85% accuracy
- **Achieved**: 0/5 variants meeting threshold
- **Blocker**: API rate limits (Gemini 429 errors on variants 4-5)

### Root Cause Analysis

**Issue**: Non-baseline variants (0425, 0426) producing dramatically lower accuracy than baseline (0424)

**Data Comparison**:
- MAG03D0425: Generated 132 rows × 12 cols vs Reference 181 rows × 13 cols
- MAG03D0426: Generated 152 rows × 12 cols vs Reference 181 rows × 13 cols  
- MAG03D0424: Generated 160 rows (matches reference structure)

**Hypothesis**: Variants 0425, 0426 are extracting incomplete data despite having same machine structure. Possible causes:
1. Variant-specific extraction handling in vision_extractor.py
2. Step validation filtering too aggressively for certain variants
3. Spec detection failing for image-heavy variant sections
4. PDF layout differences between variant sections

## Phase 2: Functional PDF Smoke Test ✓ PASS

- **Result**: PASSED
- **File**: source/FUnctional Testing WI_Five series.pdf (20 pages)
- **Details**:
  - Loaded 20 pages ✓
  - Segmented 8 machine blocks ✓
  - Extracted SPPR variant successfully ✓
  - Generated Excel output ✓
  - No crashes or errors ✓

## Phase 3: Documentation Update

### Status: BLOCKED
- Cannot complete until Phase 1 resolves variant accuracy issue
- Smoke test results ready for documentation
- Need Phase 1 final results to complete TEST_RESULTS.md update

## Next Steps

1. **Immediate**: 
   - Wait for Phase 1 API rate limits to clear (MAG03D0428, MAG03D0427)
   - Investigate extraction differences between variants
   
2. **If ≥3 variants achieve ≥85%**:
   - Complete Phase 3 documentation
   - Mark tests PASSED
   - Proceed to production deployment

3. **If <3 variants achieve ≥85%**:
   - Root cause analysis on variant extraction logic
   - Consider sub-variant handling in vision_extractor.py
   - May need to investigate reference Excel for variant data accuracy

---
**Generated**: 2026-06-06 00:25 UTC  
**Session**: 9  
**PDF**: WI.pdf (62 pages)
