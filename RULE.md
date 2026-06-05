# Development Rules — GIC Extraction Pipeline

> These rules are **mandatory** for all future development on this project.
> Any AI assistant or developer MUST follow them. Violations must be flagged and reverted.

---

## R1: No Hardcoding of Extracted Data

- **NEVER** hardcode voltages, step names, LED states, relay values, settings, or row numbers for any specific machine variant.
- **NEVER** create gold-standard / lookup-table overrides that replace Gemini's extraction output with hand-typed values.
- The normalizer (`services/normalizer.py`) must remain **generic** — it validates and flags data, it does not fabricate or overwrite it.
- If Gemini extracts wrong values, fix the **prompt** or **post-processing logic**, not the data.

## R2: No PDF-Specific Changes

- Code must work for **any** GIC work instruction PDF, not just `WI.pdf`.
- Do not add `if filename == "WI.pdf"` or similar checks.
- Page numbers, section counts, and document structure must be detected dynamically, never assumed.

## R3: No Machine-Specific Branching

- Do not add `if variant_name == "MAG03D0424"` to special-case one machine's extraction.
- All logic must be generic across variants (MAG03D0424, MAG03D0425, SM301, SM500, etc.).
- If a pattern works for one variant, it should work for all variants of similar layout.

## R4: No Error-Specific Patches

- Do not fix individual cell mismatches by adding targeted string replacements (e.g., `if voltage == "114" then replace with "115.2"`).
- Fix the **root cause** — improve the Gemini prompt, the post-processing regex, or the template writer logic.
- Each fix should improve accuracy across **multiple** cells/steps, not just one.

## R5: Prompt Engineering Over Code Patches

- The primary tool for improving extraction accuracy is the **PROCEDURE_PROMPT** in `vision_extractor.py`.
- Improve extraction quality by:
  1. Clarifying prompt instructions
  2. Adding better worked examples
  3. Specifying exact output format expectations
  4. Adding extraction rules (e.g., "use UPPER BOUND of range")
- Do NOT add dozens of post-processing string replacements to compensate for bad prompts.

## R6: Template Writer Must Be Layout-Driven

- `services/template_writer.py` writes data based on **Layout A** or **Layout B** rules.
- Row spacing, column placement, and blank rows are determined by the layout, not by variant name.
- Do not inject `exact_row_number` or `no_supply_off` attributes onto steps — let the layout engine compute positions.

## R7: Preserve Existing Architecture

- Follow the pipeline flow defined in `ARCHITECTURE.md`:
  ```
  PDF → extract_pages → segment_blocks → per-block:
    → classify_pages → extract_specs → extract_procedure
    → enrich → normalize → link_specs → validate → write_excel
  ```
- Each module has a single responsibility. Do not merge concerns.
- Do not bypass the normalizer or enricher.

## R8: Test Against Reference, Not Against Expectations

- Use `tests/test_compare_reference.py` as the accuracy benchmark.
- Compare generated Excel cell-by-cell against the reference Excel.
- Do not create separate "expected output" files — the reference Excel IS the expected output.

## R9: API Quota Conservation

- Use `tests/test_single_machine.py` for iterative testing (single variant).
- Do not run full pipeline tests unless specifically verifying cross-variant behavior.
- Add `time.sleep()` between API calls as needed.

## R10: Document Changes

- Update `CURRENT_STATUS.md` after significant changes.
- Update `TEST_RESULTS.md` after each test run with accuracy numbers.
- Update `BUG_LOG.md` when bugs are identified or resolved.

---

## Anti-Patterns (What NOT to Do)

| ❌ Anti-Pattern | ✅ Correct Approach |
|----------------|-------------------|
| Hardcode 28 gold-standard steps for MAG03D0424 | Improve PROCEDURE_PROMPT so Gemini extracts correctly |
| Add `step.exact_row_number = 84` | Fix template writer spacing logic generically |
| Replace `normalizer.py` with variant-specific lookup tables | Keep normalizer as a generic validator |
| Add `if name == "supply off": skip` for one edge case | Handle section labels generically by structure |
| Fix one cell by adding a targeted string replacement | Fix the extraction rule that produces wrong values |

---

*Last updated: 2026-05-23*
