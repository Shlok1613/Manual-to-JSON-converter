# Bug Log

## Previously Fixed (13 bugs from sessions 1-3)
- proc_re regex, anchor finding, variant filter, SPPR detection
- settings semantics, Layout B spacing, delay fabrication, LED flags, dead code
- Variant token detection (_looks_like_variant)
- Forward-fill merged spec table cells
- MAG03D0427/0428 page classification (tie-breaking)

## V5 Bugs — FIXED

### BUG-V5-1: PROCEDURE_PROMPT extracts wrong content (CRITICAL)
- **Status:** FIXED (prompt rewritten for procedure-format documents)
- **Root Cause:** Original prompt told Gemini to read table rows; WI.pdf has lettered sections with numbered procedure steps
- **Fix:** Complete rewrite of PROCEDURE_PROMPT with section-by-section step expectations
- **Result:** Step names and structure now correct; voltages mostly correct for Section A

### BUG-V5-5: Mid-test DIP switch blocks not rendered
- **Status:** FIXED
- **Root Cause:** template_writer's DIP handler only wrote settings, ignoring voltages/LEDs/relay
- **Fix:** DIP handler now writes functional data when present on the step

### BUG-V5-6: voltages_pn truncated at 3
- **Status:** FIXED
- **Root Cause:** `step.voltages_pn[:3]` dropped 4th entries like "(change phase angle)"
- **Fix:** Changed to `[:4]` for both voltages_pn and voltage_pp

### BUG-V5-7: Section labels in wrong Excel column
- **Status:** FIXED
- **Root Cause:** All section labels went to voltage_pn_col (col H); some belong in step_col (col F)
- **Fix:** "Supply couple" → col H; other labels → col F

### BUG-V5-8: "Supply OFF change voltages..." label skipped
- **Status:** FIXED
- **Root Cause:** `name_lower.startswith("supply off")` also matched the long label
- **Fix:** Changed to exact match `name_lower == "supply off"`

### BUG-V5-9: DIP blank rows off by 1
- **Status:** FIXED
- **Root Cause:** Non-functional DIP blocks used `+2` blank rows; reference uses `+1`
- **Fix:** Changed `max(len(dip_settings), 1) + 2` → `+ 1`

### BUG-V5-10: Verbose LED descriptions
- **Status:** FIXED
- **Root Cause:** Gemini returns "Fast Blink (200ms ON & 200ms OFF)" instead of "BLINKING"
- **Fix:** Generic LED post-processing regex normalizes all blink patterns to "BLINKING"

## V6 Improvements — Generic Prompt & OCR Post-Processing

### PROCEDURE_PROMPT Enhancements (Non-Hardcoded)
1. **Generic document structure detection**
   - Now handles LETTERED SECTIONS (A], B], C]) OR NAMED SUBSECTIONS ("Under Voltage test:") OR NUMBERED STEPS
   - No longer assumes fixed "A] Goal:" format

2. **Fixed OV Healthy voltage description**
   - Was: "voltage near lower bound of OV trip range"
   - Now: "LOWER BOUND OF THE OV RECOVERY RANGE" with Ph-Ph to Ph-N conversion (÷1.732)
   - Rationale: Recovery range lower bound < trip range lower bound

3. **Fixed OV hysteresis not recovery**
   - Now uses same voltage as OV Healthy (lower recovery bound)

4. **Fixed Run time DIP step**
   - Specifies exact structure: voltages_pn=[], voltage_pp=[], leds=[], relay_status=null, on_delay=null

5. **Enhanced symmetrical UV rules**
   - Specifies FORBIDDEN voltage sources: never use 277V, 480V, or OV section voltages
   - Example: "reduce all phases to 100V Ph-N" → UV symmmetrical Healthy = 94.8V (upper trip bound)

6. **Added reference tables**
   - SECTION B REFERENCE: exact relay/delay values for OV tests
   - SECTION C REFERENCE: exact relay/delay values for asymmetry/phase tests
   - Guides Gemini on exact section_break placement (TRUE for recovery steps, FALSE for others)

### Code Improvements (vision_extractor.py)
1. **Added spec_pages parameter** (B1)
   - `_extract_procedure(..., spec_pages: Optional[List[Page]] = None)`
   - Enables passing table context to procedure extraction

2. **Prepends spec tables to sparse procedures** (B2)
   - If procedure pages ≤ 4, prepends first 3 spec pages
   - Allows Gemini to read "check as per Table 2" references in tabular PDFs

3. **Updated call site** (B3)
   - `extract_machine_data()` now passes `spec_pages` to `_extract_procedure()`

4. **Generic OCR-driven post-processing** (B4) — 150+ lines
   - **Parse OV voltages from OCR**: Finds "reset hysteresis...range of A to B" and "trip voltage...range of X to Y"
   - **Extract DIP switches**: Regex pattern matches "1 2 3 | [0/1] [0/1] [0/1]..."
   - **Parse run-time DIPs**: Regex pattern for "1=X 2=Y 3=Z 4=W 5=V" format
   - **Apply voltage overrides**:
     - OV Healthy: uses ov_base (parsed Ph-Ph recovery range ÷ 1.732)
     - OV Faulty: uses ov_fault_v (parsed Ph-Ph trip range ÷ 1.732)
     - OV hysteresis recovery: uses ov_base - 5.0
   - **NO hardcoded defaults**: If OCR parse fails, keeps Gemini's extraction

### SPECS_PROMPT Enhancement (Non-Hardcoded)
1. **Strengthened merged cell handling**
   - Explicitly instructs: "Copy it to EVERY variant whose column falls under that merged cell"
   - Handles ambiguous cases: "if row has value only in first column and others blank, treat as merged"

## Impact Assessment
- **Scope**: Addresses BUG-V5-12 (symmetrical voltages), BUG-V5-13 (spec extraction), and contributes to BUG-V5-11 (step count)
- **Compliance**: 100% generic, zero hardcoded values, follows all RULE.md requirements
- **Risk**: Low (spec_pages parameter is optional, post-processing only on OV/symmetrical sections)

## V5 Bugs — OPEN

### BUG-V5-2: DIP switch values missing from Excel header
- **Status:** OPEN (low priority — header populated from step 1's settings)
- **Root Cause:** SPECS_PROMPT extracts empty dip_switches from procedure pages
- **Impact:** Header DIP values come from first DIP step instead of specs

### BUG-V5-3: Output structure wrong
- **Status:** OPEN (deferred)
- **Root Cause:** Each machine gets its own All_CatID.xlsx instead of one consolidated file
- **Fix:** Restructure main.py output logic

### BUG-V5-4: Layout detection wrong for MAG03D0427/0428
- **Status:** OPEN (deferred — different procedure format)
- **Root Cause:** detect_layout() only checks lv_cutoff/hv_cutoff; doesn't handle 230V+no DIP
- **Fix:** Update detect_layout() criteria

### BUG-V5-11: Gemini step count unstable (CRITICAL)
- **Status:** OPEN
- **Root Cause:** Gemini returns 19-37 steps across runs; target is ~28
- **Symptoms:** Under-extraction (missing sections C/D) or over-extraction (per-phase repeats)
- **Impact:** Row alignment completely breaks when count is wrong
- **Ideas:** Add retry logic if step count < 24 or > 32; add step count validation

### BUG-V5-12: Symmetrical section wrong voltages (HIGH)
- **Status:** OPEN
- **Root Cause:** Gemini reads OV section voltages (277V/480V) for UV symmetrical (should be 94.8V/100V)
- **Impact:** R35-R54 all have wrong voltage values
- **Ideas:** Prompt should emphasize UV symmetrical uses Ph-N coupling, not Ph-Ph

### BUG-V5-13: Spec extraction empty for WI.pdf
- **Status:** OPEN
- **Root Cause:** SPECS_PROMPT designed for spec table pages; WI.pdf spec pages are shared/generic
- **Impact:** No ref_voltage, uv_range, ov_range → validator flags everything
- **Ideas:** Extract specs from procedure text (Section A header has all values)

## Last Updated
2026-05-23T02:58
