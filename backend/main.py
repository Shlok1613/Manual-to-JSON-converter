from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from models.schemas import ExtractResponse
from services.pipeline import process_pdf

app = FastAPI(title="PDF to Excel/JSON Converter")

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/")
def root() -> dict:
    return {"status": "ok", "message": "PDF extraction service ready"}


@app.post("/extract-text/", response_model=ExtractResponse)
async def extract_text_endpoint(file: UploadFile = File(...)) -> ExtractResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    pdf_path = UPLOAD_DIR / Path(file.filename).name
    pdf_path.write_bytes(await file.read())

    try:
        results = process_pdf(pdf_path, OUTPUT_DIR)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc

    return ExtractResponse(
        filename=file.filename,
        num_pages=results["num_pages"],
        num_blocks=results["num_blocks"],
        excel_files=results["excel_files"],
        json_files=results["json_files"],
        flagged_items=results["flagged_items"],
        confidence_average=results["confidence"],
    )


@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=file_path.name)
