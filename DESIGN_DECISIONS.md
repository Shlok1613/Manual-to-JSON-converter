# Design Decisions

## D1: PROCEDURE_PROMPT must target test condition table, not procedure steps
The reference Excel contains test CONDITIONS (observable states with measured values),
not procedure INSTRUCTIONS (operator actions). The prompt must be rewritten to tell
Gemini to extract from the tabular test condition data, not the narrative instructions.

## D2: Score tie-breaking prefers later pages
For SCOPE documents, assembly pages come before functional test pages.
When anchor scores tie, the later page wins (functional test section).

## D3: Forward-fill for merged spec table cells
When a value spans multiple variant columns in the spec table,
it must be attributed to all of them via forward-filling.

## D4: Layout detection based on spec content
Layout A: has UV/OV thresholds or ranges → DIP switch machine
Layout B: only has cutoff values, or high ref_voltage + no DIP → cutoff machine

## D5: Known variants passed through pipeline
User-provided submachine names are passed directly to variant_mapper
for header detection, avoiding heuristic pattern matching failures.

## D6: No hardcoding of extracted data (RULE.md R1)
The normalizer must remain generic — it validates and flags data, not overwrite it.
All accuracy improvements must come through prompt engineering or generic post-processing.

## D7: Template writer column placement is content-driven
- "Supply couple at X VAC" → voltage_pn_col (col H)
- "Supply OFF change voltages..." → step_col (col F)
- This is determined by content pattern, not by position or machine variant.

## D8: LED normalization is generic regex, not value mapping
Gemini may return verbose LED states ("Fast Blink (200ms ON & 200ms OFF)").
These are normalized via regex to "BLINKING" — no machine-specific mappings.

## D9: Mid-test DIP blocks can carry functional data
Some DIP S/W Change steps have voltages, LEDs, relay, and delays.
The template writer writes both DIP settings AND functional data on the same row.
This is detected generically (if step has voltages_pn or leds).

## D10: Voltage arrays support 4 entries, not just 3
Phase reverse steps need a 4th entry like "(change phase angle)".
voltages_pn[:4] and voltage_pp[:4] are used throughout.
