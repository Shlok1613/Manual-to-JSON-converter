# backend/main.py
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from services.pdf_extractor import extract_text
from services.spec_parser import extract_specifications
from services.excel_json_converter import save_to_excel, convert_excel_to_json
from pathlib import Path

app = FastAPI(title="Smart Mfg JSON - Backend")

# Folders
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

@app.get("/")
def root():
    return {"status": "ok", "message": "Smart Mfg JSON backend running"}

@app.post("/extract-text/")
async def extract_text_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save uploaded PDF
    save_path = UPLOAD_DIR / file.filename
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Extract text
    with open(save_path, "rb") as f:
        pages = extract_text(f)

    # Combine text from all pages
    page_texts = [p.strip() for p in pages]
    full_text = "\n\n".join([p for p in page_texts if p])

    # Save text file for reference
    text_path = OUTPUT_DIR / f"{file.filename.replace('.pdf', '.txt')}"
    text_path.write_text(full_text, encoding="utf-8")

    # Generate Excel and JSON
    excel_path = OUTPUT_DIR / f"{file.filename.replace('.pdf', '.xlsx')}"
    save_to_excel(full_text, excel_path)
    json_path = convert_excel_to_json(excel_path)

    # Combine text from all pages
    page_texts = [p.strip() for p in pages]
    full_text = "\n\n".join([p for p in page_texts if p])

    # ✨ New: Use AI to extract structured data
    structured_data = extract_specifications(full_text)

    # Save structured data to Excel and JSON
    excel_path = OUTPUT_DIR / f"{file.filename.replace('.pdf', '.xlsx')}"
    json_path = OUTPUT_DIR / f"{file.filename.replace('.pdf', '.json')}"

    # Convert dict → Excel → JSON
    import pandas as pd, json
    df = pd.DataFrame(list(structured_data.items()), columns=["Parameter", "Value"])
    df.to_excel(excel_path, index=False)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(structured_data, f, indent=4)

    return JSONResponse({
        "filename": file.filename,
        "num_pages": len(pages),
        "structured_data": structured_data,
        "excel_file": str(excel_path.name),
        "json_file": str(json_path.name)
    })

