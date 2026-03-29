# Smart Manufacturing Extraction Engine

A web-based system that converts industrial manufacturing Work Instruction (WI) PDFs into structured Excel test specification files for factory floor operators.

Built for GIC — a manufacturer of industrial voltage monitoring relays.

---

## The Problem

GIC produces voltage monitoring relays (SPPR, SM500, DMS120, MAG03D series, etc.). Each product has a functional testing procedure documented in a PDF manual. These manuals contain 8–10 products mixed together across 20–60 pages.

Before this system, factory operators manually read these PDFs to extract test parameters — UV/OV voltage ranges, delays, LED states, relay behavior — and filled in Excel test sheets by hand. This was:

- Time-consuming and error-prone
- Inconsistent across operators
- Not scalable when new product variants were added
- Impossible to automate with simple copy-paste due to mixed product sections

The target output was a specific Excel template already in use on the factory floor — a multi-row format where each test condition spans 5 rows covering voltage settings, LED statuses, relay behavior, and delays.

---

## What Was Planned

1. Upload a PDF → parse it → generate one Excel per machine
2. Match the exact factory Excel template format
3. Handle both regular PDFs and scanned/OCR-based ZIPs
4. Support all product families without hardcoding machine-specific logic
5. Track extraction history with a database
6. Let users control which machines to extract

---

## What Was Built

### Architecture

```
PDF Upload
    ↓
pdf_extractor.py        — text extraction (pdfplumber + PyMuPDF fallback + ZIP/OCR)
    ↓
block_segmenter.py      — splits full text into per-machine blocks
    ↓
universal_spec_extractor.py  — extracts voltage specs from each block
    ↓
condition_generator.py  — delegates to universal extractor
    ↓
excel_writer.py         — writes structured Excel with 5-row condition format
    ↓
Output: one .xlsx per machine
```

### Frontend

Vanilla JS + Tailwind CSS. No framework.

- Upload interface with drag-and-drop
- Machine name input modal — user specifies which machines to extract before processing starts
- Extraction history with unique IDs
- Per-extraction delete: results only (keeps PDF and DB entry) or full delete
- Download individual Excel files per machine
- Analytics: total extractions, machines processed

### Backend

FastAPI + SQLite + SQLAlchemy.

- `POST /api/extract` — accepts PDF + optional machine names, returns extraction ID
- `GET /api/extractions` — lists all extractions from database
- `GET /api/files/{id}` — lists Excel files for one extraction
- `GET /api/download/{id}/{filename}` — download a specific Excel file
- `DELETE /api/extraction/{id}` — delete results or full extraction
- `GET /api/pdf/{id}` — download original PDF
- `GET /health` — server health check

---

## Key Technical Decisions

### Three PDF formats, one extractor

The PDFs came in three data formats:

- **Format A** — table inline: `"Under Voltage (UV): 347 to 357 VAC"`
- **Format B** — procedure text: `"range of 220.8V to 225.6V"`
- **Format C** — PCT inline: `"85% (353 VAC) 343 TO 363 VAC"`

Instead of branching logic per format, `universal_spec_extractor.py` tries all three patterns for every block. Whichever finds data wins. This means the same extractor works on all PDFs without knowing the format in advance.

### 5-row Excel format

Each test condition in the output spans exactly 5 rows:

```
Row 1: condition name | POT | RN voltage  | PWR LED  | relay | on delay | off delay
Row 2:                |     | YN voltage  | UV LED   |
Row 3:                |     | BN voltage  | OV LED   |
Row 4:                |     |             | ASY LED  |
Row 5: (blank spacer)
```

This matches the factory template exactly. The `_write_condition_5row()` function in `excel_writer.py` handles this.

### Block segmentation

`block_segmenter.py` uses regex patterns to detect section headers (`PROCESS:`, `Functional Testing`, `For MG73BQ product`, etc.) and splits the PDF into per-machine text blocks. Key safeguards:

- Minimum block size (1000 chars) prevents premature splits
- Table reference check — won't split if a table reference was just made but no table has appeared yet
- Short block merging — blocks under 1500 chars with no table spec are merged with the next block

### SCOPE-based documents (WI.pdf)

Some PDFs (WI.pdf) are ZIP archives containing JPEG page scans + OCR text files. `pdf_extractor.py` detects this and reads from the text files directly.

These documents use a SCOPE line (`SCOPE : MAG03D0424 / MAG03D0425 / ...`) to identify products. When 70%+ of auto-detected blocks share the same name, SCOPE mode fires — it reads the SCOPE line, extracts all product names, and creates one block per product sharing the full combined text.

### User-provided machine names

When a PDF has unknown machine names (not matching any known prefix), the user can type the machine names manually via the modal. The segmenter:

1. Validates each name against the full PDF text (case-insensitive)
2. Silently ignores names not found
3. Falls back to auto-detection if all names are invalid
4. After standard segmentation, filters blocks to only those matching user names
5. Merges multiple same-named blocks into one

---

## Extraction Results

| Machine | Conditions Generated | Notes |
|---|---|---|
| SPPR | 28 | UV×2 sets, OV×2, ASY, phase, neutral |
| SM301 | 2 | Automated jig — no voltage specs extractable |
| SM500 | 20 | UV, OV, ASY, phase |
| SM500_A | 20 | Same structure as SM500 |
| SM501_B | 24 | UV, OV, ASY, phase, neutral |
| DSMR | 24 | UV, OV, ASY, phase reverse |
| DMS120 | 24 | UV, OV, ASY, phase |
| DMS12024 | 24 | UV, OV, ASY, phase, neutral |
| MAG03D0424–0428 | 34 each | LV/HV cutoffs, phase fail/reverse |

Both input PDFs handled:
- `FUnctional_Testing_WI_Five_series.pdf` — 20 pages, 9 machines, standard PDF
- `WI.pdf` — 62 pages, 5 MAG03D machines, ZIP/OCR format

---

## Known Limitations

**SCOPE documents produce identical output per machine.** When WI.pdf is processed in SCOPE mode, all 5 MAG machines share the same combined text blob. The extractor finds mixed specs from all machines and generates the same conditions for each. The factory template was created manually — someone who knew each machine's specs filled it in by hand. The PDF itself doesn't cleanly separate per-machine specs in a way the extractor can isolate.

The FUnctional_Testing PDF works correctly because each machine has its own clearly delimited section.

**POT setting column is always empty.** The POT settings (P1, P2, P3) are physical knob positions on the test jig — not written in the PDF. Operators fill this column manually.

**SM301 produces only 2 conditions.** This is correct behavior — SM301 is an automated jig test with no voltage specifications in the PDF.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI |
| PDF extraction | pdfplumber (primary), PyMuPDF (fallback), zipfile (OCR/ZIP) |
| Excel generation | openpyxl |
| Database | SQLite + SQLAlchemy |
| Frontend | Vanilla JavaScript, Tailwind CSS |
| Server | Uvicorn |

---

## Project Structure

```
backend/
├── main.py                          # FastAPI app, all endpoints
├── requirements.txt
├── database.py                      # SQLAlchemy engine + session
├── models/
│   ├── schemas.py                   # Pydantic models, ID generation
│   └── db_models.py                 # SQLAlchemy ORM models
├── services/
│   ├── pdf_extractor.py             # PDF text extraction
│   ├── block_segmenter.py           # Per-machine text splitting
│   ├── universal_spec_extractor.py  # Voltage/spec extraction + condition generation
│   ├── condition_generator.py       # Delegates to universal extractor
│   └── excel_writer.py             # Excel file generation
├── static/
│   ├── index.html                   # Main upload + history UI
│   ├── extraction.html              # Per-extraction detail + download UI
│   └── script.js                   # Frontend logic
├── uploads/                         # Uploaded PDFs (gitignored)
├── outputs/                         # Generated Excel files (gitignored)
└── metadata/                        # Extraction metadata JSONs (gitignored)
```

---

## Running the Project

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000` in your browser.

---

## Future Goals

**LLM integration for SCOPE documents.** The biggest remaining gap — different MAG machines produce identical output. An LLM call after text extraction, before segmentation, could read the full document and return per-machine spec summaries. This would fix the SCOPE output problem without changing the rest of the pipeline.

**Auto machine name detection.** Currently users type machine names manually for unknown PDFs. An LLM reading the first 2–3 pages could return the machine list automatically, eliminating the manual step entirely.

**NLP-based block segmentation.** A custom spaCy model trained on GIC PDFs could replace the regex SECTION_PATTERNS entirely — catching any product code format without needing prefix lists or user input.

**POT setting extraction.** If a future PDF version includes POT settings in the procedure text, the extractor could be extended to populate column G automatically.

**Batch upload.** Currently one PDF per upload. Multiple PDFs could be queued and processed in the background.

**REST API for MES/ERP integration.** The existing FastAPI backend is already structured for this — adding authentication and a formal API spec would allow factory systems to trigger extractions programmatically.
