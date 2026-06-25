# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GIC Smart Manufacturing Extraction Engine** — A vision-AI pipeline that converts industrial manufacturing Work Instruction (WI) PDFs into structured Excel test specification files for factory floor operators.

**Core problem**: Factory operators manually read PDF manuals (8–60 pages, 8–10 products mixed together) to extract test parameters (voltage ranges, LED states, relay behavior, delays) and fill in Excel sheets by hand. This system automates the extraction and Excel generation.

**Key constraint**: Different input PDFs have different text formats (inline tables, procedure text, PCT format). The extractor must handle all three without branching logic.

## Architecture & Pipeline

The extraction pipeline flows through 5 stages:

```
1. PDF EXTRACTION (pdf_extractor.py)
   - Input: PDF file or ZIP bundle (JPEG + OCR text files)
   - Output: Page[] with ocr_text + jpeg_bytes (for vision)
   
2. BLOCK SEGMENTATION (block_segmenter.py)
   - Input: Page[]
   - Output: Block[] (per-machine text groups with page_range)
   - Key: Detects machine names, handles SCOPE documents (fan-out)
   
3. MACHINE DATA EXTRACTION (vision_extractor.py)
   - Input: Block + sub_machines list
   - Output: Dict[variant_name → VariantData]
   - Vision tasks: SPECS extraction + PROCEDURE extraction (per variant)
   - Uses Gemini 2.5 Flash with strict JSON prompts + table grid parsing
   
4. ENRICHMENT & VALIDATION (enricher.py → normalizer.py → validator.py)
   - enricher: Backfill missing specs from block text (ref_voltage, ranges)
   - normalizer: Validate LED names, voltage arrays; flag incomplete data
   - validator: Check physical validity (UV max < OV min), cross-variant consistency
   
5. LINKER & EXCEL WRITER (spec_linker.py → template_writer.py)
   - spec_linker: Attach spec context (on_delay, off_delay) to test steps
   - template_writer: Write .xlsx matching factory template (Layout A or B)
```

### Key Files by Responsibility

| File | Role |
|------|------|
| `main.py` | FastAPI app; orchestrates pipeline; endpoints for upload, download, delete, history |
| `services/pdf_extractor.py` | Handles PDF text extraction (pdfplumber) + ZIP/OCR bundles |
| `services/block_segmenter.py` | Regex-based machine name detection; SCOPE document handling |
| `services/vision_extractor.py` | Gemini API calls; page classification; specs/procedure extraction; retry logic |
| `services/table_grid_extractor.py` | Table 2-D grid parsing (merged cells, forward-fill) |
| `services/variant_mapper.py` | Maps spec table columns to variant names; merges table data into specs |
| `services/enricher.py` | Backfills missing spec fields from block text |
| `services/normalizer.py` | Validates LED names, voltage arrays; adds quality flags |
| `services/validator.py` | Physical validity checks (UV < OV, LV < HV, etc.) |
| `services/spec_linker.py` | Attaches spec delays to test steps |
| `services/template_writer.py` | Writes .xlsx in Layout A or Layout B format |
| `services/types.py` | Shared dataclasses: Page, Block, Specs, TestStep, VariantData |
| `services/delay_utils.py` | Filters spurious delay hallucinations (e.g., "62 sec") |
| `database.py` | SQLAlchemy session + engine setup |
| `models/schemas.py` | Pydantic models; extraction ID generation |
| `models/db_models.py` | SQLAlchemy ORM: ExtractionDB table |
| `static/` | Frontend: index.html, extraction.html, script.js (vanilla JS + Tailwind) |

### Data Flow

```
User uploads PDF
  ↓
POST /api/extract (fastapi)
  ↓
extract_pages() → Page[] (text + jpeg)
  ↓
segment_blocks(pages, user_names) → Block[]
  ↓
For each block:
  - detect_variants_from_text() or use user-provided variants
  - extract_machine_data(block, sub_machines) → Dict[variant → VariantData]
    (internally: classify pages, extract specs, extract procedure, parse tables)
  - enrich_variant()
  - normalize_variant()
  - link_specs_to_steps()
  - validate_variants()
  - write_variant_workbook() (one .xlsx per variant)
  - write_consolidated_workbook() (one .xlsx per machine)
  ↓
Save metadata JSON + DB record
  ↓
Return extraction_id + excel_files list
```

## Layout Detection & Excel Writing

Template writer auto-detects **Layout A** or **Layout B** from spec content:

- **Layout A** (full machines: SPPR, SM500, MAG03D0424/425/426)
  - Header rows 1-9: DIP S/W block + couple voltage subheader
  - Test steps from row 10
  - Columns: F=step, G=settings, H=PH-N, I=PH-PH, J=LED, K=relay, L=on_delay, M=off_delay
  - Per step: 4 rows + 1 blank, or 5 rows + 1 blank if section_break

- **Layout B** (cutoff machines: MAG03D0427/0428)
  - Header rows 1-4 (no DIP S/W, no settings column)
  - Test steps from row 5
  - Columns: F=step, G=PH-N, H=PH-PH, I=LED, J=relay, K=on_delay, L=off_delay

Detection rule: If specs contain UV/OV thresholds or ranges → Layout A. If only cutoff values or high ref_voltage with no DIP → Layout B.

## Running the Project

### Setup
```bash
python -m venv .venv
source .venv/Scripts/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### Development Server
```bash
# Terminal 1: Backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Access frontend
# Open http://127.0.0.1:8000 in browser
```

### Testing

**Single variant test** (fast, low API quota cost):
```bash
python -m tests.test_single_machine
```

**Full pipeline test** (both input PDFs, all machines):
```bash
python -m tests.test_full_pipeline
```

**Accuracy comparison** (generated vs reference Excel):
```bash
python tools/compare_excel.py <generated.xlsx> <reference.xlsx> <sheet_name>
```

**Run all tests** (if pytest configured):
```bash
pytest tests/ -v
```
Currently no pytest.ini, so tests are standalone Python scripts. Run individually with `python -m tests.<test_name>`.

## Environment & API Keys

**File**: `.env`

```
GEMINI_API_KEY=<your_gemini_api_key>
```

Required for vision extraction. Get from Google Cloud Console. Rotate keys if hitting 429 quota errors (logged in CURRENT_STATUS.md).

## Mandatory Development Rules (RULE.md)

**These rules are mandatory. Violations must be flagged.**

### R1: No Hardcoding of Extracted Data
- Never hardcode voltages, step names, LED states, relay values, or row numbers for any variant.
- Never create gold-standard lookup tables that replace Gemini output.
- normalizer.py must remain generic — validate and flag data, don't fabricate it.
- **If Gemini extracts wrong values**: Fix the PROCEDURE_PROMPT or post-processing logic, not the data.

### R2: No PDF-Specific Changes
- Code must work for **any** GIC work instruction PDF, not just WI.pdf.
- Never check `if filename == "WI.pdf"`.
- Page numbers and document structure must be detected dynamically.

### R3: No Machine-Specific Branching
- Never add `if variant_name == "MAG03D0424"` special cases.
- All logic must be generic across variants (MAG03D0424, SM500, SPPR, etc.).

### R4: No Error-Specific Patches
- Never fix individual cell mismatches with targeted string replacements.
- Fix the root cause: improve the Gemini prompt, the regex, or the template writer logic.

### R5: Prompt Engineering Over Code Patches
- The primary tool for improving accuracy is the **PROCEDURE_PROMPT** in vision_extractor.py.
- Improve by:
  1. Clarifying prompt instructions
  2. Adding better worked examples
  3. Specifying exact output format
  4. Adding extraction rules (e.g., "use UPPER BOUND of range")

### R6: Template Writer Must Be Layout-Driven
- Row spacing, column placement, blank rows are determined by **Layout A/B rules**, not variant name.
- Do not inject `exact_row_number` or `no_supply_off` attributes onto steps.

### R7: Preserve Pipeline Architecture
- Follow the flow in ARCHITECTURE.md without merging concerns.
- Each module has a single responsibility.

### R8: Test Against Reference, Not Expectations
- Use `tests/test_compare_reference.py` as accuracy benchmark.
- Compare cell-by-cell against reference Excel.
- Reference Excel IS the expected output (no separate "expected output" files).

### R9: API Quota Conservation
- Use single-variant tests for iteration (not full pipeline).
- Add `time.sleep()` between API calls.

### R10: Document Changes
- Update CURRENT_STATUS.md after significant changes.
- Update TEST_RESULTS.md after each test run (include accuracy numbers).
- Update BUG_LOG.md when bugs are identified/resolved.

## Key Design Decisions

### Three PDF Formats, One Extractor
PDFs come in three data formats for specs:
- **Format A**: `"Under Voltage (UV): 347 to 357 VAC"`
- **Format B**: `"range of 220.8V to 225.6V"`
- **Format C**: `"85% (353 VAC) 343 TO 363 VAC"`

Instead of branching, `vision_extractor.py` prompts try all three patterns per block. Whichever finds data wins.

### SCOPE Documents (ZIP/OCR)
Some PDFs (WI.pdf) are ZIP archives with JPEG pages + OCR text files. Detection:
- `pdf_extractor.py` reads ZIP structure
- `block_segmenter.py` detects SCOPE line: `SCOPE : MAG03D0424 / MAG03D0425 / ...`
- If 70%+ auto-detected blocks share same name, SCOPE mode fires
- Extracts all product names from SCOPE, creates one block per product sharing combined text

### User-Provided Machine Names
When machine names are unknown, user inputs them via modal. Validation:
1. Case-insensitive text match against PDF
2. Silently ignore invalid names
3. Fall back to auto-detection if all invalid
4. Filter blocks to only matching names
5. Merge multiple same-named blocks

### Spec-to-Step Linking
`spec_linker.py` attaches spec delays (on_delay, off_delay) to test steps **only** if:
- Field is missing in step
- Spec field is populated
- Not a spurious hallucination (checked via `delay_utils.is_spurious_delay_hallucination()`)

### 5-Row Excel Format
Each test condition spans exactly 5 rows (matching factory template):
```
Row 1: condition name | POT | RN voltage  | PWR LED  | relay | on delay | off delay
Row 2:                |     | YN voltage  | UV LED   |
Row 3:                |     | BN voltage  | OV LED   |
Row 4:                |     |             | ASY LED  |
Row 5: (blank spacer)
```
Implemented in `template_writer.py` via `_write_condition_5row()`.

## Known Limitations

- **SCOPE documents produce identical output per machine**: All MAG machines share combined text blob; extractor finds mixed specs. FUnctional_Testing PDF works correctly (clear per-machine sections).
- **POT setting column empty**: POT positions are physical knob settings, not in PDF. Operators fill manually.
- **SM301 produces 2 conditions**: Correct behavior — automated jig test with no voltage specs in PDF.
- **Delay mismatch (open)**: Reference uses factory labels (e.g., "Instant ON"); extraction produces raw FQC table values (e.g., "<=750 msec").

## Current Status & Open Issues

See `CURRENT_STATUS.md` for latest accuracy numbers and API key rotation status.

**Session 13 (2026-06-14)**:
- Layout B delay normalization fixed
- 62 sec bug (spurious hallucination) traced and scrubbed
- API key rotated (primary exhausted)
- Open: MAG03D0425/0426 still output `UV Pot (1) = 7%` instead of `P1 = 7%` (prompt iteration needed)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI 0.115.5 |
| PDF extraction | pdfplumber 0.11.4, PyMuPDF 1.24.13, zipfile (OCR) |
| Excel generation | openpyxl 3.1.5 |
| Database | SQLite + SQLAlchemy |
| Frontend | Vanilla JavaScript, Tailwind CSS |
| Server | Uvicorn 0.32.1 |
| Vision API | Google Gemini 2.5 Flash (google-generativeai 0.8.3) |

## Frontend

- **index.html**: Upload interface with drag-and-drop; machine name input modal; extraction history.
- **extraction.html**: Per-extraction detail view; Excel download links; delete options.
- **script.js**: All logic vanilla JS (no framework). Handles modal, file upload, API calls, history refresh.

**User flow**:
1. Upload PDF via drag-drop or file picker
2. (Optional) Enter machine names in modal; submit
3. API processes; returns extraction_id + excel_files
4. Display results; allow per-file download or full extraction delete

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/extract` | Upload PDF + optional machine_data JSON; returns extraction_id + excel_files |
| GET | `/api/extractions` | List all past extractions (metadata from JSON files) |
| GET | `/api/extraction/{id}` | Get one extraction's metadata |
| DELETE | `/api/extraction/{id}` | Delete extraction (results + optional PDF) |
| GET | `/api/download/{id}/{filename}` | Download specific Excel file |
| GET | `/api/pdf/{id}` | Download original PDF (if not deleted) |
| GET | `/health` | Server health check (or GET `/` for index.html) |

## File Structure

```
├── main.py                          # FastAPI app, endpoints, orchestration
├── database.py                      # SQLAlchemy engine + SessionLocal
├── requirements.txt                 # Python dependencies
├── .env                            # API keys (gitignored)
├── RULE.md                         # Mandatory development rules
├── ARCHITECTURE.md                 # Pipeline flow diagram
├── DESIGN_DECISIONS.md             # D1-D10 design rationale
├── CURRENT_STATUS.md               # Latest accuracy, API status, open issues
├── BUG_LOG.md                      # Bug tracking and resolution history
├── TEST_RESULTS.md                 # Test run logs with accuracy %
├── models/
│   ├── schemas.py                  # Pydantic: ExtractionResult, ID generation
│   └── db_models.py                # SQLAlchemy: ExtractionDB table
├── services/
│   ├── types.py                    # Shared dataclasses (Page, Block, Specs, TestStep, VariantData)
│   ├── pdf_extractor.py            # PDF/ZIP text + JPEG extraction
│   ├── block_segmenter.py          # Per-machine text splitting + SCOPE detection
│   ├── vision_extractor.py         # Gemini calls; specs/procedure extraction
│   ├── table_grid_extractor.py     # Table 2-D grid parsing (merged cells)
│   ├── table_parser.py             # Table page classification + extraction
│   ├── variant_mapper.py           # Spec table → variant mapping + forward-fill
│   ├── variant_page_mapper.py      # Page-to-variant mapping helpers
│   ├── enricher.py                 # Backfill missing specs from block text
│   ├── normalizer.py               # LED/voltage validation + quality flags
│   ├── validator.py                # Physical validity checks (UV < OV, etc.)
│   ├── spec_linker.py              # Attach spec context to test steps
│   ├── delay_utils.py              # Filter spurious delay hallucinations
│   └── template_writer.py          # Excel generation (Layout A/B)
├── static/
│   ├── index.html                  # Main upload + history UI
│   ├── extraction.html             # Per-extraction detail + downloads
│   └── script.js                   # Frontend logic (435 lines)
├── uploads/                        # Uploaded PDFs (gitignored)
├── outputs/                        # Generated Excel files (gitignored)
├── metadata/                       # Extraction metadata JSONs (gitignored)
└── tests/                          # Test scripts (24 files, standalone Python)
    ├── test_full_pipeline.py       # WI.pdf + FUnctional PDF, all machines
    ├── test_single_machine.py      # Single variant test (fast)
    ├── compare_*.py                # Accuracy comparison tools
    └── ...
```

## Debugging & Logging

- **Logger**: Configured in main.py with format `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"` at INFO level.
- **Key log points**:
  - Extraction ID generation + PDF save
  - Page extraction + JPEG count
  - Block segmentation + machine names
  - Variant detection + extraction status
  - Validation flags + sanitization
  - Excel write success/failure
- **Metadata**: Every extraction saves JSON to `metadata/{extraction_id}.json` with full pipeline details.
- **Database**: ExtractionDB table tracks extraction_id, filename, num_pages, num_machines, machines, excel_files, status, created_at.

## Future Improvements (from README)

1. **LLM integration for SCOPE documents** — Use LLM to read full document before segmentation, return per-machine spec summaries.
2. **Auto machine name detection** — LLM reads first 2–3 pages, returns machine list automatically.
3. **NLP-based block segmentation** — Custom spaCy model to replace regex SECTION_PATTERNS.
4. **POT setting extraction** — If future PDFs include POT in procedure text.
5. **Batch upload** — Queue multiple PDFs, process in background.
6. **REST API for MES/ERP** — Add authentication + formal API spec for factory systems.
