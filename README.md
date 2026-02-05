# PDF to Excel/JSON Converter for Manufacturing Test Procedures

This project provides a modular FastAPI backend that converts manufacturing work-instruction PDFs into structured Excel and JSON outputs.

## Implemented Pipeline

1. **PDF Text Extraction** (`backend/services/pdf_extractor.py`)
   - Primary: `pdfplumber`
   - Fallback: `PyMuPDF`
2. **Block Segmentation** (`backend/services/block_segmenter.py`)
   - Detects process/machine boundaries with regex patterns.
3. **Table Extraction** (`backend/services/table_extractor.py`)
   - Parses `TABLE <n>` and LED sections.
4. **Specification Parsing** (`backend/services/spec_parser.py`)
   - Extracts voltage/range/percentage/delay values.
5. **Step Extraction** (`backend/services/step_extractor.py`)
   - Extracts numbered steps and inferred fields.
6. **Confidence Scoring** (`backend/services/confidence_scorer.py`)
   - Scores extracted entities and flags uncertain fields.
7. **Excel Generation** (`backend/services/excel_writer.py`)
   - Writes two sheets per machine: `Specifications`, `Test_Procedures`.
8. **JSON Generation** (`backend/services/json_writer.py`)
   - Writes structured JSON with confidence and flagged items.

## API

- `POST /extract-text/`
  - Upload a PDF file and run full pipeline.
  - Returns generated filenames and extraction quality summary.
- `GET /download/{filename}`
  - Downloads generated output files.

## Run Locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Test

```bash
cd backend
pytest -q
```

## Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY backend .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

