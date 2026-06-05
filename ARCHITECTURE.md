# Architecture

## Pipeline Flow
```
PDF → extract_pages() → segment_blocks() → per-block:
  → _classify_pages_for_variant()  (spec pages + proc pages)
  → extract_table_grids()          (pdfplumber table parsing)
  → extract_variant_mappings()     (variant_mapper)
  → _extract_specs()               (Gemini vision call)
  → merge_table_into_specs()       (table overrides vision)
  → _extract_procedure()           (Gemini vision call)
  → enrich_variant()               (enricher)
  → normalize_variant()            (normalizer)
  → link_specs_to_steps()          (spec_linker)
  → validate_variants()            (validator)
  → write_variant_workbook()       (per-variant .xlsx)
  → write_consolidated_workbook()  (All_CatID .xlsx)
```

## Key Files
| File | Responsibility |
|------|---------------|
| main.py | FastAPI endpoints, orchestration |
| services/vision_extractor.py | Gemini calls, page classification, prompts |
| services/template_writer.py | Excel generation (Layout A / B) |
| services/variant_mapper.py | Table grid → variant spec mapping |
| services/block_segmenter.py | SCOPE detection, page grouping |
| services/enricher.py | Block text enrichment |
| services/normalizer.py | LED/delay validation |
| services/validator.py | Spec validation rules |

## Layouts
- **Layout A**: DIP switch machines (4 LEDs). Header rows 1-9, steps from row 10.
- **Layout B**: Cutoff machines (1 LED). Header rows 1-4, steps from row 5.
