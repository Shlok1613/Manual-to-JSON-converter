# backend/main.py
#python -m uvicorn main:app --host 127.0.0.1 --port 8000

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from services.pdf_extractor import extract_text
from services.spec_parser import extract_specifications
from services.excel_template_writer import fill_template_excel
from services.block_segmenter import segment_functional_test_blocks
from services.template_builder import build_template_skeleton
from pathlib import Path
import pandas as pd, json

app = FastAPI(title="Smart Mfg JSON - Backend")

# Folders
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
TEMPLATE_PATH = Path("templates/1M SPP SM175 AUTO FUNCTION All CatID.xlsx")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


@app.get("/")
def root():
    return {"status": "ok", "message": "Smart Mfg JSON backend running"}


@app.post("/extract-text/")
async def extract_text_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # --- Save uploaded PDF ---
    save_path = UPLOAD_DIR / file.filename
    with open(save_path, "wb") as f:
        f.write(await file.read())

    # --- Extract text ---
    with open(save_path, "rb") as f:
        pages = extract_text(f)
        # 🔹 TEMP DEBUG START (Step-1 validation)
    blocks = segment_functional_test_blocks(pages)

    for b in blocks:
        skeleton = build_template_skeleton(b)

        print("TITLE:", skeleton["title"])
        print("NUMBER OF FINAL STEPS:", len(skeleton["template_data"]["TestSteps"]))

        print("FIRST STEP:")
        print(skeleton["template_data"]["TestSteps"][0])

        print("LAST STEP:")
        print(skeleton["template_data"]["TestSteps"][-1])
    # --- Combine extracted text ---
    full_text = "\n\n".join([p.strip() for p in pages if p.strip()])

    # --- Save extracted text for reference ---
    safe_name = Path(file.filename).stem.replace(" ", "_").replace("/", "_").replace("\\", "_")
    text_path = OUTPUT_DIR / f"{safe_name}.txt"
    text_path.write_text(full_text, encoding="utf-8")

    # --- Step 1: AI specification extraction ---
    # structured_data = extract_specifications(full_text)

    # # --- Step 2: Determine product name ---
    # product_name = structured_data.get("Product", file.filename.replace(".pdf", ""))

    # --- Step 3: Save structured Excel using the template ---
    # output_excel = OUTPUT_DIR / f"{product_name}_structured.xlsx"
    # fill_template_excel(TEMPLATE_PATH, output_excel, structured_data)

    # # --- Step 4: Save structured JSON as well ---
    # json_path = OUTPUT_DIR / f"{product_name}_structured.json"
    # with open(json_path, "w", encoding="utf-8") as f:
    #     json.dump(structured_data, f, indent=4, ensure_ascii=False)

    # --- Step 5: Return API response ---
    return JSONResponse({
        "filename": file.filename,
        "num_pages": len(pages),
        "blocks_detected": len(blocks),
        "first_block": {
            "title": skeleton["title"],
            "num_steps": len(skeleton["template_data"]["TestSteps"]),
            "first_step": skeleton["template_data"]["TestSteps"][0],
            "last_step": skeleton["template_data"]["TestSteps"][-1],
        }
    })

