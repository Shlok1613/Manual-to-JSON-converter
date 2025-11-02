# backend/main.py
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from services.pdf_extractor import extract_text
import os
from pathlib import Path

app = FastAPI(title="Smart Mfg JSON - Backend")

# simple uploads folder
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

@app.get("/")
def root():
    return {"status": "ok", "message": "Smart Mfg JSON backend running"}

@app.post("/extract-text/")
async def extract_text_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # save uploaded file temporarily
    save_path = UPLOAD_DIR / file.filename
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # open saved file for extraction
    with open(save_path, "rb") as f:
        pages = extract_text(f)

    # minimal cleaning: join pages and return both page-wise and full text
    page_texts = [p.strip() for p in pages]
    full_text = "\n\n".join([p for p in page_texts if p])

    # optional: write outputs to outputs/ folder (for later)
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / (file.filename.replace(".pdf", ".txt"))
    out_path.write_text(full_text, encoding="utf-8")

    return JSONResponse({
        "filename": file.filename,
        "num_pages": len(page_texts),
        "page_texts_preview": [p[:800] for p in page_texts],  # preview only
        "full_text_preview": full_text[:3000]
    })
