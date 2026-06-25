# Current Status — Session 2026-06-25 (WI pipeline — MAG03D0425 gate 3 FINAL + 0426 FINAL)

**Date**: 2026-06-25
**API**: ALL KEYS EXHAUSTED. Key 1 (0425 gate 1), Key 2 (0425 gate 2), Key 3 (0425 gate 3 — exhausted), Key 4, Key 5. ALWAYS SKIP: AQ.Ab8... OAuth tokens.

---

## Functional PDF Extractor Status (2026-06-24, end of session)

### Family CLEAN/NOT CLEAN — **ALL 6/6 ✅ CLEAN**

| Family | Status | Notes |
|--------|--------|-------|
| SPPR | ✅ CLEAN | 5 checks + prefix-vote N/A (no external title meta). 7 submachines. |
| SM301 | ✅ CLEAN | 5 checks trivially-ran + prefix-vote N/A (no spec tables). Jig-only. |
| SM500 A | ✅ CLEAN | All 6 checks ran. 2 submachines (MG63BF/MG63BH). |
| SM501 B | ✅ CLEAN | All 6 checks ran. 8 submachines. TABLE3 PRODUCT spec after 300 DPI header fix. |
| DSMR | ✅ CLEAN | Generic hyphen normalization (`re.sub(r'\s*-\s*','-',c)`) in `_parse_table`. Union: DMS110, DMS120, DMS120-V, DMS220, DMS12024, DMS120-D (DAIKIN). |
| SM500 | ✅ CLEAN | **FIXED 2026-06-24.** Two settings tables (Group1 6-col + Group2 5-col) extracted via single call pages 7+8. Merged-cell prompt rule fixed torn rows. TABLE @ REF VOLTAGE kind=aux in raw JSON. flags=0. |

### SM500 fix summary
- **Cross-page table**: TABLE 2 @240V header at bottom of page 7; data rows at top of page 8. Solved by sending pages 7+8 together in one Gemini call.
- **LED exclusion**: Prompt explicitly describes LED tables by their row values ("Continuous ON/Blinking") and instructs exclusion; describes settings tables by voltage-range values.
- **Merged cells**: Prompt rule requires repeating parameter label for all rows under a merged cell. Fixes torn rows (parameter='5s', parameter='85% (195.5 V)' artifacts).
- **TABLE @ REF VOLTAGE**: Changed `kind` from `spec` to `aux` in raw JSON (`outputs/functional/raw/SM500_tables_raw.json` index 5). Voltage values ('120 VAC', '220 VAC', etc.) are not model codes — correct annotation, eliminates reclassification flag.
- **Script**: `run_sm500_reextract.py` — single call, bleed check, pad_trim_ban, Stage-C header fallback, save-both-or-neither guard.

### DSMR fix detail
- Code: `services/functional_extractor.py` `_parse_table`, after slash expansion: `expanded_cols = [re.sub(r'\s*-\s*', '-', c) for c in expanded_cols]`
- Normalizes OCR-space artifacts around hyphens in model codes. Generic — applies to all families.
- Verified: `--reprocess` → DSMR ✅ CLEAN, all 6 checks ran, 0 real flags.

### Integrity check framework (as of this session)
- ALL_CHECKS = [pad_trim_ban, unreadable_header, non_model_column, value_fragment, split_header, cross_source_prefix_vote]
- CLEAN = all 6 checks either ran OR are N/A, AND zero non-INFO flags
- N/A = proxy-derived title_submachines (no external title source); not a failure, not a pass
- Proxy meta files written as side-effect for SPPR/SM301/SM500 (with `title_from_external: false`)
- Bootstrap meta files (DSMR, SM500_A, SM501_B) have real title_submachines → full prefix-vote runs

---

---

## Accuracy (cumulative best)

| Variant | Accuracy | Pass? | Notes |
|---------|----------|-------|-------|
| MAG03D0424 | **92.5%** | PASS ✓ | S22 gate run (346/374 correct). TASK 2 COMPLETE. |
| MAG03D0424EG | **93.0%** | PASS ✓ | S20 run 1. TASK 3 COMPLETE. |
| MAG03D0425 | **21.3%** | ACCEPTED | Gate 3 FINAL (108/506), 2026-06-25. Fix 3 revert restored OV sym. Score ACCEPTED. Baseline frozen: outputs/MAG03D0425_FINAL.xlsx |
| MAG03D0426 | **92.7%** | PASS ✓ | Gate 3 compare done 2026-06-25 (419/452). TASK COMPLETE. |
| MAG03D0427 | **97.5%** | OK | PASS |
| MAG03D0428 | **99.4%** | OK | PASS |

---

## Session 2026-06-25 (WI pipeline — 0425 gate 3 FINAL + 0426 compare FINAL)

### 0425 Gate 3 FINAL: 108/506 = **21.3%** (Key 3, 2026-06-25) — ACCEPTED
- Fix 3 revert confirmed in place (Supply couple always emitted before OV sym).
- OV sym section restored: Supply couple + OV sym Healthy/faulty/not-recovery/recovery all present in Section A.
- Score improved from 14.0% (gate 2) → 21.3% (gate 3). Structural fix confirmed working.
- Result ACCEPTED at 21.3%. No further gate runs planned for 0425.
- Baseline frozen: `outputs/MAG03D0425_FINAL.xlsx`

**Remaining known issues (ACCEPTED/WONTFIX):**
- P1 = 7 % space: _fmt_pct adds space for single-digit % (can't fix without breaking 0426 which uses '7 %')
- Supply couple voltages written to wrong column (H vs template position) — template_writer writes voltages_pn from Gemini even though prompt says []
- OV sym settings DELAY=3 SEC vs DELAY=15 SEC (Gemini carries Section A pot value; reference uses 15 SEC for OV sym)
- UV faulty "with delay" naming (opposite mismatch vs 0426 — cannot fix without R3 violation)
- Section B settings wrong (P1=25%/P2=0 MIN vs reference P1=25%/P2=25%; Delay Pot=9 sec vs DELAY=0 SEC)
- Phase fail wrong phase removed (R vs B)

---

## Session 2026-06-25 (WI pipeline — 0426 gate 3 compare + 0425 gate 2)

### 0426 Gate 3 Compare: 419/452 = **92.7%** — PASS ✓
- No API used. Free compare against reference Excel.
- Remaining wrong: DIP setting R3G (1:OFF vs 1:ON), voltage R10-R12H (0 vs 240), P3=0 SEC vs 15 SEC, ASY LED states, voltage rounding (327/328, 460/461), Supply couple voltages wrong, Phase reverse relay wrong, extra DIP rows at end.
- 0426 is DONE. No further work planned.

### 0425 Gate 2: 71/506 = **14.0%** (Key 2, 2026-06-25)
- Section B structure now CORRECT (OV-first → UV sym → Phase fail). Fix 4 worked.
- Section A missing entire OV sym block (Supply couple + 4 OV sym steps = ~6 steps).
- Root cause: Fix 3 (from prior session) was incorrectly analyzed. "Supply couple at 240 VAC" IS in the reference at R35H. Fix 3 told Gemini to omit it when UV was single-phase, causing Gemini to skip the entire OV sym section.
- **Fix applied this session**: Reverted Fix 3. Supply couple now always emitted before OV sym.
- Key 2 EXHAUSTED after gate 2 run.

### Gate 3 for 0425 — needs fresh key

### Session 2026-06-24 (WI pipeline — MAG03D0425 gate 1 + 5 prompt fixes)

### Gate 1: 63/506 = **12.5%** (Key 1, 2026-06-24)
- **Regression from S22-S29 0426 fixes bleeding into 0425**
- WRONG=175, MISSING=268, EXTRA=307
- proc_pages=[34,35] correct; Layout A detected correctly; 40 steps extracted

### Gate 1 Root Cause Analysis
| Category | Cells | Root Cause | Fixable? |
|----------|-------|-----------|---------|
| Settings P2=22% (should be P2=5%) | ~42 | Gemini confuses UV hysteresis with OV threshold | YES (Fix 1) |
| Settings P3=3SEC (should be DELAY=3 SEC) | ~14 | Delay Pot mapped to P3 instead of DELAY label | YES (Fix 2) |
| Spurious "Supply couple at 240 VAC" step | ~25 | OV SYM trigger fires on "Set Ph-N voltage as 240V" | YES (Fix 3) |
| Phase Asymmetry wrong in Section B | ~100 | 0426 Phase Asym template applied to 0425 Section B | YES (Fix 4) |
| UV faulty name missing "with delay" | 1 | Gemini ignores prompt step name change | LOW PRIORITY |
| UV not-recovery voltage 225.6 vs 223.2 | 3 | Reference uses midpoint example value | Cannot fix (hardcoded) |
| UV Healthy voltage 225.6 vs 226 | 3 | Reference uses rounded value | Cannot fix (hardcoded) |
| Phase fail wrong phase (R vs B removed) | 5 | Gemini extracts wrong phase | Needs deeper work |
| Section B structural mismatch | ~150 | See Fix 4 | PARTIAL |

### 5 Prompt Fixes Applied (gate 2, Key 4)
1. **Fix 1+2 (settings format)**: "UV hysteresis (Pot 2) - 5% → P2=5% (not 22%)". "Delay Pot without (Pot N) → DELAY, never P3."
2. **Fix 3 (Supply couple)**: OV sym Supply couple ONLY if UV sym preceded. "Set Ph-N voltage as X V" is NOT a trigger.
3. **Fix 4 (Phase Asym scope guard)**: ASY LED during phase FAIL = Phase Fail, not Phase Asymmetry. Only trigger on "reduce dimmer" (not "remove phase").
4. **Fix 5 (space)**: Worked example P1=7 % → P1=7% (matches existing no-space rule).

### Gate 2: BLOCKED — Key 4 RPD exhausted (0 steps extracted, 2026-06-24)
- All 5 API keys are now exhausted. Need new key before gate 2 can run.
- Fixes are staged in code. Run gate 2 first thing next session.

### Expected gate 2 ceiling (when key available)
- Settings format fixes: ~56 cells
- Supply couple fix: ~25 cells
- Phase Asymmetry scope guard: potentially large (100+ Section B cells)
- **Projected score: 30-45%** (structural Section B still partially mismatched)

---

## Session 2026-06-24 (WI pipeline — MAG03D0426)

### Gate 1: 387/452 = **85.6%** (Key 1)
- **CONFIRMED FIXED**: BUG-0426-F (OV Section B BN-only ✓), BUG-NEW-S28-1 (PATH B ✓)

### Gate 2: 395/452 = **87.4%** (Key 2, 2026-06-24 this session)
- BUG-0426-NEW-1 ✓: Phase fail off_delay='Instant OFF' confirmed working
- BUG-0426-NEW-4 ✓: UV Healthy Section B on_delay='ON in 89-91 SEC' confirmed working
- BUG-0426-NEW-2 PARTIAL: Section B Phase reverse/recovery voltage_pp correct ✓; Section A added 12 extra unwanted cells ✗
- BUG-0426-J NOT FIXED: P3=15 SEC still in Section A Phase test settings (5 cells)
- BUG-0426-NEW-3 WRONG DIRECTION: Reference expects "UV faulty condition with delay" — revert needed
- NEW FINDING: Phase recovery relay_status='ON'→'Instant ON', on_delay='After 14-16 sec'→'Instant ON' (4 cells)

### Remaining gaps after Gate 2 (46 wrong + 11 missing + 31 extra cells)
- BUG-0426-J: P3=15 SEC carried into Phase tests (5 cells) — see prompt fix below
- Phase fail relay off_delay wrongly time-based instead of Instant OFF (7 cells) — prompt fix below
- Missing voltage_pp for Phase reverse/recovery (9 cells) — prompt fix below
- Rounding (194.2 vs 194.1, 189.4 vs 189.3): 17 cells — not fixed (prompt-only unlikely to help)
- Extra final DIP S/W Change block with voltages/LEDs: 18 cells — not fixed this session

### Prompt fixes applied (UNTESTED — no API call after fixes)
All edits to `services/vision_extractor.py` PROCEDURE_PROMPT:

1. **UV faulty condition step name** (1 cell, line ~622 + worked example ~1249)
   - Changed "UV faulty condition with delay" → "UV faulty condition" in prompt and worked example
   - Added post-processing normalization (line ~2152) as safety net

2. **BUG-0426-J: P3 override for Phase tests** (5 cells, line ~1096)
   - Added ██ DIP TABLE OVERRIDE ██ rule: DIP table P3 (e.g., 15 SEC) is IGNORED for Phase tests
   - Phase fail settings: P3=0 SEC; off_delay: "Instant OFF" — mandatory, not derived from DIP table

3. **Phase fail relay always Instant OFF** (7 cells, line ~1116)
   - Removed confusing "P3=15 SEC controls Phase FAIL off_delay" reference
   - Replaced with: P3 is ALWAYS reset to 0 for Phase tests → off_delay always "Instant OFF"

4. **Missing voltage_pp Phase reverse** (9 cells, lines ~1119 + ~1137)
   - Added: Phase reverse + Phase reverse recovery → voltage_pp=["RY:415","YB:415","BR:415"] (all 3 phases at nominal supply → Ph-Ph = 415V)

5. **UV Healthy Section B on_delay** (2 cells, line ~844)
   - Strengthened existing rule: "Even if relay was ON from previous step, use on_delay='ON in 89-91 SEC'. Do NOT output null or 'Continuous ON'."

---

## Session 15 changes (2026-06-17)

1. **Supply couple MANDATORY fix** (PROCEDURE_PROMPT) -- Strengthened to require "Supply couple at X VAC" step between UV hystersis recovery and UV symmmetrical steps; added OCR fallback that inserts it when Gemini omits it.

2. **Multi-chunk guard** (`len(deduped) <= 2`) -- Prevents multi-chunk from misfiring on 0424/0424EG (proc_pages=[31,32,33], len=3 > 2). Correctly fires for 0425 (proc_pages=[34,35], len=2 <= 2 with 2+ Goal headings on page 34).

3. **`(symmmetrical)` suffix strip fix** (vision_extractor.py line 1563) -- Changed `\(symmetrical\)` to `\(symm+etrical\)` so the strip fires after the rename on line 1562.

4. **Section C/D duplicate Healthy condition removed** (vision_extractor.py) -- Post-processing deduplicates: if a second "Healthy condition" appears in section C/D (after "Supply OFF change" marker), it is removed. Fixes 0424EG Phase test row offset.

5. **Healthy condition on_delay fix** -- Code override simplified to always write "Instant ON" (was conditionally "4-6 sec" when UV=8%). Worked example updated to match.

6. **PROCEDURE_PROMPT DIP settings** -- Added CRITICAL instruction: settings array MUST contain exactly 3 items (UV, OV, DELAY). Never emit only 2.

7. **PROCEDURE_PROMPT Phase fail** -- Added: after Asymmetry recovery, go DIRECTLY to Phase fail; do not insert another Healthy condition. Added: read which phase is removed from the document.

---

## Session 16 changes (2026-06-17)

1. **Multi-chunk page boundary fix** -- Changed `len(deduped) <= 2` to `len(deduped) == 1`. For 0425 (proc_pages=[34,35]), previously page 34 sent alone -> Gemini hallucinated all B/C content; page 35 returned 0 steps. Now both pages sent together in one combined call (5 images: 3 spec + 2 proc). See BUG-S16-1.

2. **VOLTAGE RULES: remove 120V hardcode** -- Changed from `"set voltage at 120V" -> RN:120` to "ALWAYS read from document". Fixed worked example: 120V/UV=8% -> 240V/UV=10%. Section A voltages now correctly 240V throughout. See BUG-S16-2.

3. **OV sym settings clarification** -- Added: "if document ONLY changes delay, update ONLY DELAY; P1/P2 stay same as preceding UV section; threshold % in heading is NOT a pot value." See BUG-S16-3.

4. **Section C DELAY re-read instruction** -- Added to Asymmetry section: "Re-read the Pot Settings line; 0 sec means DELAY=0SEC -- do NOT carry over previous section's delay." See BUG-S16-4.

5. **Section B sym note: REVERTED** -- Adding "may have sym tests" caused 13.4% regression (step count < 24 -> bad retry). Reverted to "Section B does NOT have symmetrical tests." See BUG-S16-5.

6. **BUG-S15-6 root cause corrected** -- 0425 has **3 sections** (A=UV+Phase at P1=7%, B=OV+UV sym at P1=25%, C=Asymmetry at P1=25%/DELAY=0sec), NOT 4. Phase tests rows 161-180 are UNNARRATED (hard ceiling, cannot fix with prompt).

### Session 16 accuracy progression (MAG03D0425)

| Run | Change | Accuracy | Steps |
|-----|--------|----------|-------|
| Baseline (Session 14) | -- | 26.9% | 30 |
| Combined-call only | `len(deduped)==1` | ~26.5% | ~33 |
| + voltage fix | 120V->240V in prompt | **33.0%** | 33 |
| + Section B sym (reverted) | regression | 13.4% | -- |
| fix4 restored | reverted to fix2 | **33.0%** | 33 |

---

## Session 17 changes (2026-06-18)

1. **Deleted 5 hardcoded value-override blocks** (A1.1, A1.2, A1.3, A2.4, A2.5) from vision_extractor.py — these were R1/R4 violations that fabricated on_delay/leds/relay_status values gated on step-name string matches. See TEST_RESULTS.md Session 17 for details.

2. **Layout detection fix** (template_writer.py) — moved multi-LED guard outside `specs_empty` block; Layout A now correctly detected when only `ref_voltage` is set with all other spec fields null. Generic fix.

3. **Retry selection fix** (vision_extractor.py) — prefers in-range [24,60] retry over out-of-range initial result regardless of proximity to EXPECTED_STEPS=28. Prevents discarding valid 36-step results.

4. **(sym) suffix strip** (vision_extractor.py) — `re.sub(r'\s*\(sym\)\s*$', '')` added to step name normalizer. Gemini occasionally emits short-form `(sym)` suffix; this strips it for reference alignment.

5. **Part A4 + Part C prompt additions** — sym steps 7-10 described explicitly; healthy condition on_delay reads from document; runtime DIP next step instruction to extract LEDs/relay/on_delay.

### Impact assessment (Session 17)
- 0424: 90.9% → 35.0% (-55.9pp). Primary cause: step count variance (22-30 steps vs 28 reference) causing row cascade. 5 overrides covered ~2-3pp; rest was hidden Gemini extraction instability.
- 0424EG: 91.7% → 31.4% (-60.3pp). Same root causes.
- Part C prompt changes did not recover accuracy in single-session iteration.

## Open issues

### MAG03D0424 (57.5% prompt-only best as of S18-R6) — TASK 2 IN PROGRESS
Remaining gaps from S18-R6:
- **OV% mismatch** (8% extracted vs 6% in reference): document says 8%, reference says 6%. Unfixable (~8 cells).
- **"Relay countinuous ON" typo** (1 cell): reference has misspelled word. Unfixable.
- **LED BLINKING format**: reference uses "UV : BLINKING" (abbreviated), generated uses "UV (RED LED) : BLINKING" (~2 cells).
- **Section B OV voltages**: need all 3 phases equal for OV tests (fixed in S18, pending verification).
- **Asymmetry section DIP S/W Change**: extra step causing 6-row cascade (fixed in S18, pending verification after new API key).
- **"After" prefix on sym hyst recovery on_delay**: "4-6 sec" → "After 4-6 sec" (fixed in S18, pending verification).
- **on_delay for healthy condition**: "5 sec" vs "4-6 sec" (±1 rule added).

### MAG03D0424EG — Not re-run in S18
Last known: 91.7% (S15). S17 overrides removed. Will re-run once MAG03D0424 reaches ≥90%.

### MAG03D0425 (33.0%) -- ACCURACY CEILING ANALYSIS

### MAG03D0425 (33.0%) -- ACCURACY CEILING ANALYSIS
0425 has 3 sections. Known remaining gaps:
- **Section B settings wrong** (P1=23%/P2=5% extracted vs P1=25%/P2=25% in reference): OCR-to-reference calibration gap; prompt alone cannot bridge.
- **Section B UV sym tests missing** (rows 105-122): "no sym tests" note must stay to avoid regression. These ~40 cells are ceiling loss.
- **Rows 161-180 Phase tests UNNARRATED**: no OCR text exists. Hard ceiling (~40 cells = ~8pp loss).
- **Realistic accuracy ceiling**: ~85% absolute (unnarrated rows); ~50-60% without Section B sym fix.
- **Next step (next session)**: Targeted prompt change to enable Section B UV sym extraction without triggering step-count regression. Test on 0425 THEN move to 0426.

### MAG03D0426 (15.7%)
Not re-run this session. Session 16 prompt fixes (voltage scale, combined-call) apply generically. Run next session.

### Functional PDF (SPPR)
Not tested -- lower priority.

---

## Session 18 changes (2026-06-18)

1. **TASK 1 COMPLETE**: Verified 0427 (98.0%) and 0428 (99.4%) held after S17 changes.
2. **TASK 2 prompt iterations (MAG03D0424)** — best confirmed: 57.8% (run 9, 216/374 correct, 29 steps):
   - Sym section: rewrote trigger pattern (two-step: "change UV pot" + "symmetrically reduce to Z V") — sym section now extracted reliably
   - DELAY=3SEC: stronger clarification (DIP table range ≠ current setting) — now correct
   - UV hyst not recovery relay: "Continuous OFF" for sym, "OFF " for Section A (SYM SECTION REFERENCE + worked example corrected)
   - UV hyst recovery voltages: VOLTAGE RULES formula clarified (T + max_hyst where T is from "if trip is T" sentence; for sym, T = upper_trip_bound)
   - sym hyst recovery on_delay: "After" prefix enforced explicitly
   - Section B: No "Healthy condition" before first OV test; "Run time DIP" only after OV/UV tests
   - Asymmetry section: No DIP S/W Change step before first "Healthy condition"
   - OV voltage rule: All 3 phases increase together for OV tests
   - on_delay ±1 rule: "After X sec(+/-1)" → "After (X-1)-(X+1) sec" format
   - Run 9 confirmed: sym relay "Continuous OFF" ✓, sym recovery 98.4V ✓, Section A hyst recovery 115.2V ✓, on_delay "4-6 sec" ✓
3. **ALL API keys exhausted** after run 9 / run 10 attempt. Need new GEMINI_API_KEY.
4. **Run 10 prompt changes prepared** (applied to vision_extractor.py, waiting for new key):
   - "Supply OFF change voltages..." extraction: replaced MANDATORY instruction with NUMBERED SEQUENCE + JSON example (step N+1 in transition table)
   - OV hyst recovery on_delay clarification: "5-7 sec" = Section B DELAY=6sec±1 (NOT "4-6 sec" which is Section A)
   - OV faulty exact format noted: "OFF in 4-6sec" (no space before sec)

**Last Updated**: 2026-06-18 (Session 18, awaiting new API key)

---

## Session 19 changes (2026-06-18)

**TASK 2 COMPLETE**: MAG03D0424 reached 91.2% (341/374 correct, 29 steps, run 13).

### Prompt changes for run 13 (all in PROCEDURE_PROMPT_A):
1. **healthy condition on_delay**: Removed "Instant ON" from step sequence description; now says "READ from document using ±1 rule". Eliminates contradiction with existing IMPORTANT block at line 830.
2. **LED FORMAT RULE added**: ON/OFF states → full name ("PWR (GREEN LED) : ON"); BLINKING states → abbreviated (no type suffix, "UV : BLINKING"). Placed between LED FORMAT list and WORKED EXAMPLE.
3. **VOLTAGE RULES: worked example disclaimer**: Added note that "240V is a placeholder; if YOUR document Section A says 120V, use 120V" after the nominal rule.
4. **Worked example 240V note**: Updated note "example uses 240V because example document says 240V; if YOUR document says 120V, use that instead".
5. **Runtime DIP LED format**: Strengthened from "Use abbreviated names" to "Use ABBREVIATED names (strip type suffix for BLINKING) — do NOT write (GREEN LED) or (RED LED) for BLINKING states".
6. **Phase fail voltage_pp rule**: Added explicit physics: removed phase → Ph-Ph between removed phase and others = supply voltage (e.g. 240V), not 0V or 415V.
7. **Phase fail PWR LED**: Added "PWR LED typically BLINKS during phase fault. Use abbreviated: 'PWR : BLINKING'".
8. **Asymmetry faulty/not recovery ASY LED**: Added NOTE to each: "ASY LED = 'ASY : BLINKING' (no '(RED LED)' suffix)".
9. **Phase reverse recovery relay**: Added NOTE "relay MUST be 'Instant ON' (not just 'ON')".

### Accuracy progression (Session 19, TASK 2):
| Run | Key | Change | Accuracy |
|-----|-----|--------|----------|
| 12 (S18 last) | 3 | Sym fixes, Section B no-Healthy, B-phase asymmetry | 89.3% |
| 13 (S19 R1) | 5 | LED FORMAT RULE, Phase fail voltage_pp, Section A 120V hint | **91.2% PASS** |

### Remaining wrong cells at 91.2%:
- Section B settings UV=8%/OV=8% vs UV=22%/OV=6% (8 cells) — Gemini reads Section A values instead of Section B pot settings
- Asymmetry R-phase deviated (4+4+4+4+4=20 cells) — document says B-phase but variance occurred
- on_delay "5 sec" vs "4-6 sec" (1 cell) — Gemini reads "5 sec" without ±1
- DIP 2:ON vs 2:OFF (1 cell) — document reading issue
- Typo "Relay countinuous ON" (1 cell) — UNFIXABLE

### Session 20 changes (2026-06-19)

1. **Page truncation fix** (`_classify_pages_for_variant` ~line 445): content_ratio check — if another variant's heading appears >30% into the page body, include the page (split page) and break. Fixes 0426 collecting only pages [35,36] → now correctly gets [35,36,37].
2. **DIP filter fix** (post-Supply-OFF filter ~line 1947): removed `or "dip s/w" in name_lower` — DIP S/W Change steps after Supply OFF are now preserved for 0426's multi-section structure.
3. **Settings format rule** (PROCEDURE_PROMPT): explicit label mapping — P1/P2/P3 from "Pot 1/Pot 2/Pot 3" labels; UV/OV/DELAY from "UV pot/OV pot/Delay Pot" labels; always include time unit (SEC/MIN).
4. **OV sym trigger + direction** (PROCEDURE_PROMPT): added OV SYM TRIGGER detection (DELAY-only + "symmetrically INCREASE"); direction-aware Step B/C/D/E for OV vs UV sym.
5. **Phase tests after sym** (PROCEDURE_PROMPT): changed "EXACTLY 2 steps after sym" to allow Phase fail/reverse between sym and Supply OFF if described in document.
6. **Phase reverse disabled** (PROCEDURE_PROMPT): added "Phase reverse (No any change)" step — relay stays ON, no fault detected.

**MAG03D0424EG** (S20): 93.0% PASS (348/374 correct). TASK 3 COMPLETE.
**MAG03D0424** (S21 verification): 91.2% PASS — identical to S19 baseline. DIP filter + prompt changes are safe.

---

## Session 21 changes (2026-06-19)

No code/prompt changes this session. Verification + new baseline runs only.

**MAG03D0426** (S21 run 1): 29.2% (132/452 correct, 25 steps extracted).
- Improvement from 23.0% (+6.2pp) due to S20 page truncation fix + settings format rule.
- 149 WRONG, 171 MISSING, 97 EXTRA cells.

### MAG03D0426 root cause analysis (S21)

**Cat 1 — Ph-N/Ph-Ph division (~12 wrong cells, R15-R30):**
Gemini divides the document's Ph-N voltage values by √3, treating them as Ph-Ph.
Example: document says 225.6V Ph-N → Gemini outputs 225.6/√3 = 130.34V.
Reference expects 225.6V in the Ph-N column. Fix: add prompt rule "when document labels voltage as 'Ph-N', use it directly — do NOT divide by √3."

**Cat 2 — P3 not updating at UV hyst recovery (~5 wrong cells, R32,R37,R42,R48,R53):**
Document says change Pot 3 (P3) from 15 SEC to 0 SEC before Phase fail tests. Gemini keeps P3=15 SEC throughout. Fix: prompt rule to capture the pot change line after UV hyst recovery.

**Cat 3 — Phase fail voltages inverted (~6 wrong cells, R35-R37):**
Gemini sets remaining healthy phases to 0V and removed phase to supply voltage — exact inversion of correct behavior. Reference: B removed → BN=0, RN=YN=240V. Fix: reinforce prompt rule "the REMOVED phase is 0V; others stay at supply."

**Cat 4 — Phase reverse relay wrong (~5 wrong cells, R46,R51):**
Gemini sets relay=Instant OFF for phase reverse, but 0426's DIP settings disable phase reverse detection → relay stays Continuous ON throughout. Fix: stronger emphasis on "detection disabled → relay Continuous ON throughout" in prompt.

**Cat 5 — Phase Asymmetry section structurally wrong (~60 wrong cells, R63-R80):**
Gemini reads Phase Asymmetry tests as OV-style tests (all 3 phases equal, above supply).
Reference: only R-phase reduced (RN=89V, YN=BN=240V); relay ON after 30 sec; ASY LED blinks on fault.
Generated: all phases equal at 268V OV-style; UV/OV LEDs instead of PWR/ASY; settings missing P1 row (starts at P2).
Root cause: PROCEDURE_PROMPT has no Phase Asymmetry guidance for Layout A machines. Fix: add detailed Phase Asymmetry section.

**Cat 6 — Section B UV/OV structure collapse (~60+ wrong/missing cells, R83-R118):**
After Phase Asymmetry, Gemini enters the sym section (UV=22%, DELAY=0 SEC) instead of the UV coupled tests (P1=25%, P2=1.5 MIN, supply 340V/194.1V Ph-N). The entire Section B UV+OV structure is misidentified.
Root cause: no guidance in prompt for 0426's unique Section B sequence (Phase Asymmetry → UV at reduced supply → Healthy condition → Decouple → OV at elevated supply).

**Priority order for next prompt iteration:**
1. Phase Asymmetry section description (~60 cells)
2. Section B UV/OV structure guidance (~60 cells)
3. Ph-N/Ph-Ph rule (~12 cells)
4. Phase fail voltages inverted (~6 cells)
5. Phase reverse disabled relay (~5 cells)
6. P3 update at UV hyst recovery (~5 cells)

**Realistic 0426 ceiling:** ~85-90% after 3-4 more prompt iterations. Structure is fundamentally more complex than 0424.

---

## Open issues

### MAG03D0425 (33.0%) — S20 prompt changes not yet tested
Changes made: OV sym trigger (DELAY-only + "symmetrically INCREASE"), Phase tests after sym, settings format P1/P2/DELAY, Phase reverse disabled. Expect improvement from 33.0% but untested. Run next session.

### MAG03D0426 (29.2%) — Priority for next session
Six distinct root causes identified (see Cat 1-6 above). Phase Asymmetry + Section B structural guidance needed. Expect significant improvement with targeted prompt additions.

---

## Session 22 changes (2026-06-20)

5 prompt edits applied (no code changes):
1. **Edit 1** (UV SYM TRIGGER): Trigger Step 1 requires UV%/OV% change (P2/P3 delay-only excluded). "Section A context only" restriction added.
2. **Edit 2** (Phase Asymmetry + Section B): Direction (one phase reduced), LED/relay patterns, voltage formula (P1=25%→89/78/95/105V), UV at 340V guidance, OV single-phase note, "No sym in Section B" note.
3. **Edit 3** (Phase fail): WRONG/CORRECT examples reinforcing removed phase = 0V.
4. **Edit 4** (Phase reverse disabled): DETECTION DISABLED → relay=Continuous ON.
5. **Edit 5** (VOLTAGE RULES): DIP 5=ON → Ph-N supply → use values directly, NEVER divide by √3.

### S22 results
- **MAG03D0424 gate**: 92.5% PASS (Key 1). Phase Asymmetry content changed: BN=89V (Edit 2 formula applied) vs reference BN=179V. Investigation needed next session.
- **MAG03D0426**: 28.8% (Key 2) — slight regression from 29.2%. Phase Asymmetry content correct (89/78/105V, P1=25%) but wrong row placement due to structural issues. UV Ph-N no longer divided by √3.

### MAG03D0426 new root causes (S22) — 8 bugs total
**Cat 7 — Settings format UV/OV/DELAY instead of P1/P2/P3 (~30 cells, Section A)**:
0426 reference uses P1/P2/P3 labels uniformly. Document Section A likely uses "UV Pot/Delay" labels which Gemini transcribes literally. Fix: read Section A OCR labels; add mapping rule.

**Cat 8 — UV sym still fires in Section A (major structural offset, ~40+ row cascade)**:
Despite Edit 1, 0426 Section A still gets a spurious UV sym section (5 steps injected). Reference has NO UV sym in Section A (UV hyst recovery → Phase fail directly). The coupling instruction on page 36 belongs to Section B but Gemini assigns it to Section A.

**Cat 9 — UV at 340V should be symmetric (all 3 phases = 194.1V Ph-N)**:
Edit 2 said "single phase R reduced" but reference has all three phases simultaneously at 340V Ph-Ph (194.1V Ph-N each). ~12 cells wrong.

**Cat 10 — P2=0 MIN → 30 sec ON delay, P3=1.5 MIN → 90 sec OFF delay**:
P2=0 MIN in 0426 means minimum 30 sec pickup time → "ON in 29-31 sec". Prompt has no guidance. ~10 cells wrong.

**Cat 11 — Missing "Couple all voltage" / "Decouple all voltages" steps**:
Section B has two structural marker steps between test groups that are never generated. ~8 missing cells.

**Cat 12 — OV Section B is single phase B raised (not all-equal)**:
Only B phase rises to OV trip (BN=282/291V); RN=YN=240V. We output all-equal. ~12 cells wrong.

**Cat 13 — Section C P2/P3 not reset to 0 SEC**:
Phase fail/reverse in Section C use P2=0 SEC, P3=0 SEC but extraction keeps P2=0 MIN, P3=1.5 MIN. ~8 cells wrong.

**Cat 14 — Initial healthy condition starts at 0V (power-on from 0)**:
First test step: RN=YN=BN=0V (supply off before power-on). We output 240V. 3 cells wrong.

### Session 23 changes (2026-06-20) — no key spent

6 prompt edits applied targeting BUG-S22-1 through BUG-S22-6:

1. **S23-Edit1** (SETTINGS FORMAT PRIORITY RULE): When label contains both type AND "(Pot N)", use P-number. "UV Pot (Pot 1) — 7%" → "P1 = 7 %" (fixes Cat 7, ~30 cells).
2. **S23-Edit2** (COMBINED DOCUMENT SCOPE): Ignore all steps/phrases before first "A] Goal:" header — they belong to a different machine. Prevents 0425-ending content from firing 0426's UV SYM trigger (fixes Cat 8, dominant ~40-row cascade).
3. **S23-Edit3** (Phase Asymmetry relay/on_delay): relay_status="ON"; P2=0 MIN→on_delay="ON in 29-31 sec"; P3=1.5 MIN→off_delay="OFF in 89-91 SEC"; after P2=1.5 MIN→on_delay="ON in 89-91 SEC"; P3=0 SEC→"Instant OFF" (fixes Cat 10, ~10 cells).
4. **S23-Edit4** (UV at 340V ALL SYMMETRIC): ALL THREE phases equal at 194.1/189.3/~200.5V Ph-N. Explicit "Do NOT reduce only one phase." (fixes Cat 9, ~12 cells).
5. **S23-Edit5** (Couple/Decouple + Section B sequence): Section_break step JSON for "Couple all voltage" (after Phase Asymmetry Recovery) and "Decouple all voltages" (after UV tests). Full Section B sequence documented (fixes Cat 11 + BUG-S21-6, ~8 cells + row alignment).
6. **S23-Edit6** (OV single phase B formula): "any of the phase" → ONLY B rises. Formula BN=(−240+√(4×YB²−172800))÷2. off_delay "Instant OFF", on_delay "ON in 89-91 SEC" (fixes Cat 12, ~12 cells).

**Not addressed**: Cat 13 (Section C P2/P3 reset, ~8 cells), Cat 14 (initial 0V, ~3 cells).

### Next tasks (S24):
- **Decision gate FIRST** (Key 3): Run MAG03D0424 → must remain ≥88%
- **0426 run** (Key 3 or 4): Target >50% (dominant Cat 8 + Cat 7 fixes should free ~70+ cells)
- **0425 NOT until 0426 confirmed** (one key per variant rule)
- **TASK 6**: Process Functional PDF — not yet started

---

## Session 24 changes (2026-06-20)

**S24-Fix1** (Asymmetry scope, PROCEDURE_PROMPT): Added CRITICAL SCOPE to P1=25% formula — applies ONLY when (a) settings use P1/P2/P3 format AND (b) extracting "Phase Asymmetry" Section B steps. If settings use UV/OV/DELAY format (as in 0424's Section C/D), DO NOT apply this formula.

**S24-Fix2** (Asymmetry voltage source, PROCEDURE_PROMPT): Added guidance to 0424's Asymmetry section: read the deviated phase voltage from the spec table in the document images. Do NOT use the 89V/78V/105V formula which applies only to P1/P2/P3-format sections.

### S24 gate results (TASK 1)
- **Key 1** (first gate with S23+S24-Fix1): **85.8% FAIL** — cross-contamination in Asymmetry (BN=89V vs 179V), sym section UV=12% wrong
- **Key 3** (re-gate with S23+S24-Fix1+Fix2): **33.7% CATASTROPHIC FAIL** — S23-Edit2 "symmetrically reduce" globally blocked Supply couple creation for 0424; Section B structurally collapsed; REGRESSION PROTOCOL INVOKED

---

## Session 25 changes (2026-06-20)

**S25-Edit1** (S23-Edit2 repair, PROCEDURE_PROMPT): Removed "symmetrically reduce phrases" from COMBINED DOCUMENT SCOPE IGNORE clause. Only numbered procedure steps and pot settings BEFORE the first Goal header are now excluded. Added explicit NOTE that "symmetrically reduce" phrases AFTER the first Goal header are valid trigger phrases that must NOT be ignored.

### S25 gate results (TASK 1 continuation)
- **Key 5** (re-gate, S25-Edit1 applied): **56.1% (210/374)** — Supply couple RESTORED ✓, sym section all-3-equal ✓. Remaining failures from Key 5 Gemini variance (OV=10% not 22%, sym settings wrong, DIP 4/5 wrong)
- **Key 2** (final gate): **34.8% (130/374)** — New bugs discovered (BUG-S25-1, S25-2, S25-3)

### ALL API KEYS EXHAUSTED after S25
| Key | Used in | Result |
|-----|---------|--------|
| Key 1 (AIzaSyANmuPp...) | S24 first gate | 85.8% |
| Key 2 (AIzaSyAJLm...) | S25 final gate | 34.8% |
| Key 3 (AIzaSyCbJs...) | S24 re-gate | 33.7% |
| Key 4 (AIzaSyBMNm...) | Exhausted S16 | N/A |
| Key 5 (AIzaSyA8mb...) | S25 re-gate | 56.1% |
ALWAYS SKIP: AQ.Ab8RN6IE02cgZE5VZmrl... and AQ.Ab8RN6JXePVXND6Q... (OAuth tokens, NOT Gemini keys)

## Accuracy (current)

| Variant | Best Accuracy | Pass? | Notes |
|---------|--------------|-------|-------|
| MAG03D0424 | **92.5%** (S22, Key 1) | PASS ✓ | S23+S24+S25 prompt changes REGRESSED. New gate best: 85.8% (Key 1, S24). Keys exhausted. |
| MAG03D0424EG | **93.0%** (S20) | PASS ✓ | Not re-tested since S20. May be affected by S23 regressions. |
| MAG03D0425 | 33.0% (S16) | FAIL | S20 prompt changes not yet tested |
| MAG03D0426 | **28.8%** (S22) | FAIL | S23 fixes applied, not yet tested (gate blocked) |
| MAG03D0427 | **97.5%** | PASS ✓ | Stable |
| MAG03D0428 | **99.4%** | PASS ✓ | Stable |

## Session 26 changes (2026-06-20)

Free OCR inspection of 0424 pages 31-33 completed (no key spend). Root causes confirmed for BUG-S25-1, S25-2, S25-3. Three prompt fixes applied to PROCEDURE_PROMPT in vision_extractor.py:

**S26-Fix1** (BUG-S25-1 mitigation): Strengthened Supply OFF mandatory rule at sym→B boundary and Run time DIP position rule. Now reads: "Supply OFF MANDATORY whenever sym section exists; 'Turn off the 3 phase test Jig and make the settings' IS this step; do NOT skip it." And: "ABSOLUTE FORBIDDEN at sym→B boundary; Run time DIP ONLY appears AFTER ALL OV/UV test conditions complete."

**S26-Fix2** (BUG-S25-2 mitigation): Added DECISIVE DISCRIMINATOR for Phase reverse at both prompt occurrences. Document procedure text takes priority over DIP inference: "relay immediately turned OFF / ASY LED turns ON → DETECTION ENABLED (relay=Instant OFF). No any change / relay stays ON → DETECTION DISABLED. Default to ENABLED when in doubt." OCR confirms: 0424 document says "relay immediately turned OFF within 100 msec" for Phase reverse — unambiguous ENABLED.

**S26-Fix3** (BUG-S25-3 mitigation): Added WRONG vs CORRECT voltage example to Asymmetry section VOLTAGE SOURCE. Root cause identified: "9% to 11%" in document is IEC SEQUENCE COMPONENT UNBALANCE, not voltage deviation. At 9% sequence unbalance with 240V nominal, BN ≈ 179V (not 218.4V). Verified by sequence component formula: |V2|/|V1| = 9.25% at BN=179V.

**OCR findings (free)**:
- S23-Edit6 NOT the cause of BUG-S25-1: 0424 OV tests say "increase Y phase dimmer" (not "any of the phase")
- "Turn off the 3 phase test Jig and make the settings" exists at page 32 end → Supply OFF is there
- Section D (Phase reverse): "relay immediately turned OFF within 100 msec" → ENABLED confirmed
- Section C (Asymmetry): "Check Asymmetry % = 9% to 11%" = IEC sequence unbalance, not voltage deviation
- Second OV group (OV=16%, B-phase only) exists in document but is NOT in reference Excel (reference uses only first OV group, OV=6% not 8% due to factory calibration)

## Session 27 gate results (2026-06-20)

New API keys obtained (3 fresh keys added). Two gate runs completed.

### MAG03D0424 gate — Key 1 (new) — **89.6% PASS ✓**
335/374 correct. S26-Fix1/2/3 confirmed working:
- Supply OFF at sym→B boundary: PRESENT ✓
- Run time DIP correctly after OV tests ✓
- Phase reverse = Instant OFF (ENABLED) ✓
- Asymmetry BN=196.8≈197V (partial improvement; healthy/faulty still off by 4-13V)

Residual errors (accepted, not fixing this session):
- Phase fail wrong phase: RN=0 extracted, reference expects BN=0 ("make B phase fail") — ~4 cells
- Phase reverse ASY LED: BLINKING extracted, reference expects solid ON — ~1 cell
- Sym DELAY=10SEC extracted vs document says 15SEC — ~6 cells cascade
- OV=8% vs reference=6% (factory calibration) — unfixable

**0424 GATE PASSED ≥88%. Accepted as-is. Not reworking 0424 this session.**

### MAG03D0426 gate — Key 2 (new) — **18.1% FAIL**
82/452 correct. Bugs classified:

| Bug ID | Root Cause | Est. Cells |
|--------|------------|-----------|
| 0426-A | OV tests hallucinated in Section A (no OV tests exist there) | ~40 |
| 0426-B | Phase reverse DISABLED not triggered for Section A (Continuous ON missed) | ~8 |
| 0426-C | Phase Asymmetry steps entirely absent from Section B (~60 missing cells) | ~60 |
| 0426-D | Couple/Decouple steps missing (cascade from 0426-C) | ~4 |
| 0426-E | Section B UV: 225.6V (Section A values) + R-only instead of all-3 at 194.1V | ~30 |
| 0426-F | Section B OV: all-3-phases rising instead of B-only (282/291V) | ~20 |
| 0426-G | Supply OFF & supply ON missing at Section B→C boundary | ~5 |
| 0426-H | Phase fail wrong phase (R removed, should be B removed) | ~5 |
| 0426-I | Section C Phase reverse/recovery rows cascaded off by 0426-A displacement | ~20 |
| 0426-J | P3=0SEC vs P3=15SEC in Section A | ~3 |

Key #3 saved — user said stop after 0426 run.

---

## Session 28 changes (2026-06-20)

Free prompt fixes applied to PROCEDURE_PROMPT in vision_extractor.py. No key spend.

**S28-Fix1** (BUG-0426-A mitigation): Added "SECTION A OV TESTS — CRITICAL: Section A NEVER contains OV tests." After UV hyst recovery in Section A: if Phase tests appear, go directly to Phase tests — never insert OV Healthy/faulty/not-recovery/recovery. OV pot settings in Section A are reference values only.

**S28-Fix2** (BUG-0426-C mitigation): Broadened Phase Asymmetry trigger in SECTION B FIRST STEP. Now fires on ANY phrasing involving single-phase reduction + ASY LED check ("reduce R phase slowly till ASY LED BLINKING", etc.). Fixed step names: "Phase Asymmetry Healthy condition" → "Phase Asymmetry Healthy"; "Phase Asymmetry faulty condition" → "Phase Asymmetry faulty" (matches reference exactly).

**S28-Fix3** (BUG-0426-B mitigation): Added DIP-based tiebreaker to DECISIVE DISCRIMINATOR for Phase reverse. If ACTIVE DIP shows DIP 1=OFF, 2=OFF, 3=OFF, 4=OFF (all fault-detection switches off, only DIP 5 active): STRONGLY PREFER DISABLED (relay=Continuous ON), even if text is ambiguous.

**S28-Fix4** (BUG-0426-F mitigation): Extended Section B OV single-phase trigger. Now fires on "increase any of the phase voltage" OR "increase B phase dimmer" / "increase B phase voltage" / etc. (document names ONE specific phase). Named phase rises; others stay at 240V.

**S28-Fix5** (BUG-0426-G mitigation): Added "TRANSITION TO SECTION C (Phase tests)" block. When Section B is followed by C] Goal with Phase fail/reverse tests: STEP N+1 = "Supply OFF & supply ON" (ALL null fields, section_break=true) before Section C DIP S/W Change.

**S28-Fix6** (BUG-0426-H + BUG-S15-5 re-enforcement): Added "CRITICAL WARNING — DO NOT DEFAULT TO R REMOVED" with explicit B/R/Y examples and phrasing triggers. Strengthens existing instruction since Gemini still defaults to R removed despite prior fix.

## Accuracy (current)

| Variant | Best Accuracy | Pass? | Notes |
|---------|--------------|-------|-------|
| MAG03D0424 | **89.6%** (S27, Key 1 new) | PASS ✓ | Gate passed. S26+S27 fixes working. |
| MAG03D0424EG | **93.0%** (S20) | PASS ✓ | Not re-tested since S20. |
| MAG03D0425 | 33.0% (S16) | FAIL | Not being worked on this session. |
| MAG03D0426 | **18.1%** (S27, Key 2 new) | FAIL | 6 prompt fixes applied S28. Gate pending Key #3. |
| MAG03D0427 | **97.5%** | PASS ✓ | Stable |
| MAG03D0428 | **99.4%** | PASS ✓ | Stable |

## API Key Status (Session 28)
- Key 1 (AIzaSyANmuPp...) — used S27 0424 gate (89.6%)
- Key 2 (AIzaSyAJLm...) — used S27 0426 run (18.1%)
- Key 3 (AIzaSyCbJs...) — CURRENT (used S24 catastrophic re-gate — **AVAILABLE for 0426 re-gate**)
- Key 4 (AIzaSyBMNm...) — AVAILABLE ← SAVE
- Key 5 (AIzaSyA8mb...) — exhausted (S25)
ALWAYS SKIP: AQ.Ab8RN6IE02cgZE5VZmrl... and AQ.Ab8RN6JXePVXND6Q... (OAuth tokens)

## Open issues / Next session priorities

### READY FOR GATE — MAG03D0426 with Key #3
Run `python -m tests.test_single_machine` with MAG03D0426 after explicit go-ahead.
S28-Fix1/2/3/4/5/6 applied. Expected recoveries:
- Fix1 (Section A no OV): ~40 cells
- Fix2 (Phase Asymmetry trigger + names): ~60 cells
- Fix3 (Phase reverse DISABLED DIP tiebreaker): ~8 cells
- Fix4 (OV single-phase trigger): ~20 cells
- Fix5 (Supply OFF & supply ON at B→C): ~5 cells
- Fix6 (Phase fail B removed): ~5 cells
Total potential: ~138 cells recovered from 452 → current 82 correct + 138 = ~220/452 ≈ 49% estimated.

### STILL OPEN (smaller bugs)
- BUG-0426-J: P3=0SEC vs P3=15SEC in Section A (~3 cells) — not fixed this session
- BUG-S22-7: Section C P2/P3 not reset (~8 cells) — not fixed this session
- BUG-S22-8: Initial healthy condition 0V (~3 cells) — not fixed this session
- BUG-0426-E cascade: If Phase Asymmetry (Fix2) works, Section B UV voltages may auto-correct

### DO NOT touch MAG03D0425 until 0426 gate confirmed.
### DO NOT spend Key #4 without explicit user go-ahead.

---

## Session 29 changes (2026-06-20)

Two key uses spent (both Key #4). OCR analysis of WI.pdf pages 35-37 completed (free). Two S29 fixes applied (free prompt edits).

### Task 1 — MAG03D0426 with S28 6-fix baseline (Key #4, run 1)
**Result: 17.9% (~81/452)** — essentially unchanged from S27 18.1%.
S28 structural fixes (C/D/E) confirmed working in extraction log, but BUG-0426-A OV hallucination created 20-row Section A cascade, masking all gains.

### OCR finding (Step A — free, pages 35-37)

**BUG-0426-A root cause confirmed:** Pure hallucination — not 0425 bleed-through. Page 35's 0425 OV values are 514.6–522.9V Ph-Ph (≈297V Ph-N), completely different from the hallucinated 278.2/283.0V. Page 36 (0426 Section A) contains ZERO OV test text. Gemini generated OV steps from P3=15SEC in Section A pot settings, incorrectly interpreting it as an OV delay.

**BUG-NEW-S28-1 root cause confirmed:** 0426 has NO "C] Goal" section anywhere in pages 35-37. Phase fail/reverse tests (OCR steps 21-26) are within B] Goal (page 37). S28-Fix5's condition ("C] Goal follows Section B") was never true for 0426. The original CRITICAL TRANSITION PATH A template kept firing.

**S29-Fix1** (BUG-0426-K): Added sequential-position scope constraint to STRICT GATE clause (a) in PROCEDURE_PROMPT. Sym trigger only fires if sym trigger text appears BEFORE "Phase Reverse detection", "Phase Fail detection", or any new lettered Goal header in sequential reading order. Sym trigger text from Section B or later sections cannot retroactively fire for Section A.

**S29-Fix2** (BUG-NEW-S28-1): Replaced the PATH A/B DISCRIMINATOR with three STRONG PATH B SIGNALS: (1) "Switch off 3 phase test jig and turn it ON again" → PATH B; (2) "Phase fail and Phase Reverse functionality:" sub-heading → PATH B (not a lettered Goal section); (3) No "Healthy condition (UV=22%/OV=22%)" after supply-off → PATH B. PATH A now requires BOTH a new lettered C]/D] Goal header AND a "change voltages" instruction.

### Task 2 — MAG03D0426 with S29 Fix1+Fix2 (Key #4, run 2)
**Result: 20.6% (93/452)** — +2.5pp from S27 baseline.

**Confirmed fixed** in extraction log: BUG-0426-A ✓, BUG-0426-B ✓, BUG-0426-C ✓, BUG-0426-D ✓, BUG-0426-E ✓, BUG-0426-H ✓

**Still broken:**
- BUG-0426-K (NEW): Phantom UV sym section (Supply couple + 4 sym steps with P1=22%) still appeared after UV hyst recovery in Section A → ~130 cells wrong/misaligned from R35 onward. S29-Fix1 addresses root cause but was applied AFTER this run and is UNTESTED.
- BUG-NEW-S28-1 (PARTIAL): PATH A still fired in Task 2 ("Supply OFF change voltages"). S29-Fix2 addresses discriminator but is UNTESTED.
- BUG-0426-F: OV all-3-phases (261.1/266.0V) instead of B-only (282/291V) — out of scope until K and S28-1 confirmed.

**Additional S29 fixes applied after Task 2 (no key spend, UNTESTED):**
- S29-Fix1 (BUG-0426-K sym scope)
- S29-Fix2 (BUG-NEW-S28-1 PATH B discriminator)

## Accuracy (current)

| Variant | Best Accuracy | Pass? | Notes |
|---------|--------------|-------|-------|
| MAG03D0424 | **89.6%** (S27, Key 1 new) | PASS ✓ | Gate passed. Not reworking. |
| MAG03D0424EG | **93.0%** (S20) | PASS ✓ | Not re-tested since S20. |
| MAG03D0425 | 33.0% (S16) | FAIL | Not being worked on until 0426 passes. |
| MAG03D0426 | **20.6%** (S29, Key 4 run 2) | FAIL | S29-Fix1 (BUG-0426-K) + S29-Fix2 (BUG-NEW-S28-1) applied, UNTESTED. |
| MAG03D0427 | **97.5%** | PASS ✓ | Stable |
| MAG03D0428 | **99.4%** | PASS ✓ | Stable |

## API Key Status (Session 29)
- Key 1 (AIzaSyANmuPp...) — used S27 0424 gate (89.6%) — quota unknown
- Key 2 (AIzaSyAJLm...) — used S27 0426 run (18.1%) — quota unknown
- Key 3 (AIzaSyCbJs...) — used S24 catastrophic re-gate — quota unknown
- **Key 4 (AIzaSyBMNm...) — used S29 TWICE (Task 1: 17.9%, Task 2: 20.6%) — likely exhausted**
- Key 5 (AIzaSyA8mb...) — exhausted (S25)
- ALWAYS SKIP: AQ.Ab8RN6IE02cgZE5VZmrl... and AQ.Ab8RN6JXePVXND6Q... (OAuth tokens)

**Key #4 is likely exhausted after two uses this session. A fresh API key is needed for the next gate run.**

## Open issues / Next session priorities

### READY FOR GATE — MAG03D0426 with fresh key
MANDATORY first action next session: Run MAG03D0426 test with S29-Fix1 + S29-Fix2 (already in code).
DO NOT make additional prompt edits before this gate — verify the two fixes first.
Expected gains: BUG-0426-K fix should eliminate ~130-cell cascade from R35+; BUG-NEW-S28-1 fix should add ~25 missing rows (Phase fail/reverse/recovery). Combined: potential jump to 55-65%.

### STILL OPEN (pending K and S28-1 gate confirmation)
- BUG-0426-F: OV B-only trigger (S28-Fix4 not working — ~20 cells)
- BUG-0426-J: P3=0SEC vs P3=15SEC in Section A (~3 cells)
- BUG-S22-7: Section C P2/P3 reset to 0 SEC (~8 cells)
- BUG-S22-8: Initial healthy condition 0V (~3 cells)

### DO NOT touch MAG03D0425 until 0426 passes gate.
### DO NOT spend next key without explicit user go-ahead.
