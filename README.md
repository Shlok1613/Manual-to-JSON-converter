# Bridging the Gap: Turning Human Know-How into JSON for Smart Manufacturing

**Phase 1 — Industrial PDF to Structured Excel**  
Industry Partner: General Industrial Controls (GIC), Pune  
Institution: M.E.S. Wadia College of Engineering, SPPU  
Academic Year: 2025–2026  
Team: Shlok Shah (72237288E) · Ishwari Surwase (72237329F)  
Guide: Prof. Yogita Ajgar

---

## What This System Does

GIC manufactures voltage monitoring relays. Testing each relay requires following a Work Instruction PDF — a 62-page document containing DIP switch settings, voltage thresholds, LED states, relay timings, and test procedure steps across 6 product variants.

Before this project, workers manually read the PDF and typed all values into Excel sheets. This was slow, error-prone, and could not scale.

This system automates that process entirely:

1. Operator uploads a PDF through the browser interface
2. System rasterises each page to a 300 DPI image
3. Google Gemini 2.5 Flash reads each image and extracts structured data
4. Data is validated, normalised, and written into an Excel workbook
5. Operator downloads the Excel and uses it directly on the factory floor

No manual reading. No copy-paste. No human transcription errors.

---

## Accuracy Results (Validated Against GIC Reference Excel)

| Variant | Accuracy | Status |
|---------|----------|--------|
| MAG03D0428 | 99.4% | ✅ PASS |
| MAG03D0427 | 97.5% | ✅ PASS |
| MAG03D0424EG | 93.0% | ✅ PASS |
| MAG03D0426 | 92.7% | ✅ PASS |
| MAG03D0424 | 92.5% | ✅ PASS |
| MAG03D0425 | 21.3% | ⚠️ Accepted — documented architectural ceiling |

**Functional Testing PDF (6 machine families):** All 6 at CLEAN status ✅

Accuracy is cell-level match against GIC's own reference Excel (`1M_SPP_SM175_AUTO_FUNCTION_All_CatID.xlsx`). Target threshold: 90%.

---

## Project Structure

```
Manual-to-JSON-converter/
│
├── main.py                          # FastAPI application — entry point
├── database.py                      # SQLAlchemy engine and session setup
├── requirements.txt                 # Python dependencies
├── .env                             # GEMINI_API_KEY (never commit this)
│
├── models/
│   ├── db_models.py                 # SQLAlchemy ORM model (ExtractionDB)
│   └── schemas.py                   # Pydantic response schemas
│
├── services/
│   ├── types.py                     # Shared dataclasses: Page, Block, Specs, TestStep, VariantData
│   ├── pdf_extractor.py             # PDF ingestion — text layer + 300 DPI rasterisation
│   ├── block_segmenter.py           # Layout classification and variant boundary detection
│   ├── vision_extractor.py          # ⚠️ FROZEN — Gemini vision extraction (WI pipeline)
│   ├── functional_extractor.py      # ⚠️ FROZEN — Gemini extraction (Functional pipeline)
│   ├── enricher.py                  # Structural metadata enrichment
│   ├── normalizer.py                # Unit and format standardisation
│   ├── spec_linker.py               # Maps extracted fields to output schema
│   ├── template_writer.py           # Excel generation via OpenPyXL
│   ├── validator.py                 # Deterministic validation rules
│   ├── delay_utils.py               # Shared delay validation helpers
│   ├── table_extractor.py           # Variant detection from text
│   ├── table_grid_extractor.py      # Grid parsing from OCR text
│   ├── table_parser.py              # Table page detection
│   └── variant_mapper.py            # Column-per-variant matrix parsing
│
├── static/
│   ├── index.html                   # Dashboard — upload and history
│   ├── extraction.html              # Extraction detail and download page
│   └── script.js                    # Frontend JavaScript
│
├── tests/
│   └── test_single_machine.py       # Single-variant extraction test runner
│
├── tools/
│   └── compare_excel.py             # Cell-level accuracy measurement tool
│
├── source/                          # Source documents (not committed to git)
│   ├── WI.pdf
│   ├── FUnctional_Testing_WI_Five_series.pdf
│   └── 1M_SPP_SM175_AUTO_FUNCTION_All_CatID.xlsx
│
├── outputs/                         # Generated Excel files (runtime)
├── uploads/                         # Uploaded PDFs (runtime)
├── metadata/                        # Extraction run metadata JSON (runtime)
│
├── RULE.md                          # Architectural integrity rules (no hardcoding)
├── BUG_LOG.md                       # Root cause analysis for all known issues
└── README.md                        # This file
```

---

## How It Works — Pipeline Overview

```
PDF Upload
    │
    ▼
pdf_extractor.py
    ├── Text layer (pdfplumber) → layout classification signals
    └── 300 DPI images (pdf2image + Poppler) → sent to Gemini
    │
    ▼
block_segmenter.py
    ├── Detects document type (WI page-per-variant vs Functional matrix)
    ├── Finds variant boundaries using SCOPE line and heading regex
    └── Returns: List of Block objects, each = one machine + its pages
    │
    ▼
    ├── WI PDF → vision_extractor.py (FROZEN)
    │       ├── Specs extraction: 4 spec pages → Gemini → JSON
    │       ├── Procedure extraction: 3–6 proc pages → Gemini → JSON steps
    │       └── Step count validation + retry (up to 4 retries)
    │
    └── Functional PDF → functional_extractor.py (FROZEN)
            ├── Matrix detection: column headers = sub-machine names
            ├── Row-by-row parameter extraction per sub-machine
            └── Merged cell handling: shared values copied to all covered variants
    │
    ▼
enricher.py → normalizer.py → spec_linker.py → validator.py
    │
    ▼
template_writer.py
    ├── Auto-detects Layout A (DIP switch, 4 LEDs) or Layout B (single LED, cutoff)
    ├── Generates one sheet per variant
    └── Saves consolidated .xlsx (all variants) + individual .xlsx per variant
    │
    ▼
FastAPI → SQLite → Browser UI → Operator downloads Excel
```

---

## Prerequisites

- Python 3.10+
- Node is not required
- Poppler (required by pdf2image for PDF rasterisation)
- A valid Google Gemini API key

### Install Poppler (Windows)

Download from: https://github.com/oschwartz10612/poppler-windows/releases

Extract the zip. Add the `bin` folder to your system PATH.

Example: if you extracted to `C:\poppler-25.01.0`, add `C:\poppler-25.01.0\Library\bin` to PATH.

Verify: open a new terminal and run `pdftoppm -v`. You should see a version number.

### Install Poppler (Linux/Mac)

```bash
# Ubuntu / Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler
```

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd Manual-to-JSON-converter

# 2. Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / Mac
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Create the .env file and add your Gemini API key
echo GEMINI_API_KEY=your_key_here > .env
```

---

## Requirements

Create a `requirements.txt` with these packages:

```
fastapi
uvicorn[standard]
python-dotenv
pdfplumber
pdf2image
google-generativeai
openpyxl
sqlalchemy
pydantic
python-multipart
```

---

## Running the System

```bash
# Activate virtual environment first
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux / Mac

# Start the server
uvicorn main:app --reload
```

Open your browser and go to: **http://127.0.0.1:8000**

The `--reload` flag restarts the server automatically when code files change. Remove it for production.

---

## Using the Interface

### Upload and Extract

1. Open http://127.0.0.1:8000
2. Drag and drop a PDF onto the upload zone (or click to browse)
3. Click **Extract Specifications**
4. A modal will ask for machine names — enter the machine name (e.g. `MAG03D0427`) or leave blank for auto-detection
5. Click **Start Extraction**
6. Wait for the extraction to complete (typically 60–120 seconds per variant)
7. The result card will appear showing machine count and extraction ID

### Download Results

- The **Recent Activity** panel shows all past extractions
- Each card shows the machine name, date, and a **Download Full** button (consolidated Excel with all variants as sheets)
- Expand a card to see individual variants, each with its own **Download** button
- Click a card's machine name to go to the extraction detail page

### Extraction Detail Page

- Accessible by clicking the machine name on any history card
- Shows: pages processed, machines found, extraction date
- Lists each machine with expandable variant list
- Each variant has an individual download button
- Delete options at the bottom: delete results only, or delete results and original PDF

---

## Testing Accuracy

To test extraction accuracy for a specific variant against the reference Excel:

```bash
# Run extraction for a single variant (uses existing WI.pdf in source/)
python -m tests.test_single_machine MAG03D0427

# Compare generated Excel against reference
python tools/compare_excel.py outputs/MAG03D0427.xlsx "source/1M SPP SM175 AUTO FUNCTION All CatID.xlsx" MAG03D0427
```

The compare tool reports:
- **Correct** — exact cell matches
- **Wrong** — cells present but value differs
- **Missing** — cells expected but not generated
- **Extra** — cells generated but not in reference
- **Overall %** — correct / total reference cells

Target: ≥ 90% for production acceptance.

---

## Frozen Modules

`vision_extractor.py` and `functional_extractor.py` are **frozen**.

This means: do not edit these files. They produce validated extraction results for passing variants. Any change risks accuracy regression on variants that currently pass 90%.

If a new variant or document type needs to be supported, validate it in a separate branch, confirm accuracy with `compare_excel.py`, and only then merge.

All other modules (enricher, normaliser, template_writer, validator, block_segmenter) can be modified. After any change to these modules, run the compare tool against the frozen baseline outputs to confirm no regression.

---

## Design Rules (RULE.md summary)

The full rules are in `RULE.md`. The most critical:

**R1 — No hardcoded extracted values.** Every value in the output must come from Gemini reading the source PDF. No values are injected based on variant name, step name, or expected range.

**R3 — No per-variant branching in extraction code.** The extractors must generalise. A solution that works by detecting the variant name and applying different logic is not a solution.

**R4 — Prompt engineering has a ceiling.** When a problem requires arithmetic (e.g. voltage × √3), the fix is a Python post-processing module, not a larger prompt.

**R5 — Freeze before refactor.** Save frozen baseline outputs before any refactoring pass. Run compare after to confirm no regression.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google Gemini API key. Get one at https://aistudio.google.com |

The `.env` file is loaded automatically at startup via `python-dotenv`. Never commit `.env` to git.

---

## Known Limitations

| Issue | Status |
|-------|--------|
| MAG03D0425 at 21.3% | Accepted. Requires √3 voltage arithmetic post-processing not yet implemented. |
| SM500 kind-flip requires manual step | Documented. Automated kind detection on Phase 2 roadmap. |
| Gemini API key required per extraction run | Key rotation strategy on Phase 2 roadmap. |

---

## Phase 2 Roadmap

Phase 1 output: Excel workbooks for factory floor use.  
Phase 2 output: Structured JSON for ERP/MES system integration.

Planned additions:
- JSON serialisation path in `template_writer.py` alongside existing Excel path
- `/api/extract` `output_format` parameter: `excel`, `json`, or `both`
- Webhook endpoint to POST extracted JSON to configured ERP on completion
- Python arithmetic module for MAG03D0425 voltage threshold derivation
- Automated kind-flip detection for SM500
- Cell-level accuracy measurement for Functional pipeline

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Vision AI | Google Gemini 2.5 Flash | PDF page interpretation and structured extraction |
| PDF Text | pdfplumber | Text layer extraction for layout classification |
| PDF Raster | pdf2image + Poppler | 300 DPI page images for vision AI |
| Backend | FastAPI + Uvicorn | REST API, file handling, pipeline orchestration |
| Database | SQLite (extractions.db) | Run history, machine names, file paths |
| Excel Output | OpenPyXL | Structured workbook generation |
| Frontend | HTML5 + JavaScript | Operator upload and download interface |
| Language | Python 3.10+ | All pipeline modules |

The system does **not** use: Tesseract OCR, Pandas, NumPy, or any ML training pipeline. All intelligence comes from Gemini's pre-trained vision capability applied to rasterised page images.

---

## Academic Context

This project was developed as a final year B.E. (Electronics & Telecommunication) capstone at M.E.S. Wadia College of Engineering, Pune (SPPU), in collaboration with General Industrial Controls (GIC), Pune.

Project title: *Bridging the Gap: Turning Human Know-How into JSON for Smart Manufacturing*  
Phase 1 scope: PDF to structured Excel  
Phase 2 scope (planned): Excel to JSON for ERP/MES integration