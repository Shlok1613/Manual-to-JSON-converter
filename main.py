# main.py
"""
GIC Smart Manufacturing Extraction Engine — Backend (Vision-First v3).

Pipeline:
  1. extract_pages       (PDF/ZIP -> Page[] with text + jpeg)
  2. segment_blocks      (Page[] -> Block[] with page_range)
  3. extract_machine_data (vision: specs + procedure -> VariantData)
  4. validate_variants   (deterministic rules, flag bad data)
  5. write_*_workbook    (template-matching xlsx)
"""
from pathlib import Path
from datetime import datetime
import logging
import json
import os
from services.types import Specs

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from database import engine, SessionLocal
from models.db_models import Base, ExtractionDB
from models.schemas import ExtractionResult, generate_extraction_id

from services.types import Block
from services.pdf_extractor import extract_pages
from services.block_segmenter import segment_blocks
from services.vision_extractor import extract_machine_data, extraction_was_successful
from services.validator import validate_variants
from services.template_writer import write_variant_workbook, write_consolidated_workbook
from services.enricher import enrich_variant
from services.normalizer import normalize_variant
from services.table_extractor import detect_variants_from_text
from services.variant_page_mapper import filter_pages_for_variant

Base.metadata.create_all(bind=engine)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="GIC Extraction Engine", version="3.0.0")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
METADATA_DIR = BASE_DIR / "metadata"
STATIC_DIR = BASE_DIR / "static"

for d in (UPLOAD_DIR, OUTPUT_DIR, METADATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _save_metadata(extraction_id: str, payload: dict) -> None:
    path = METADATA_DIR / f"{extraction_id}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))


def _persist_extraction(extraction_id: str, payload: dict) -> None:
    try:
        with SessionLocal() as db:
            row = ExtractionDB(
                extraction_id=extraction_id,
                filename=payload.get("original_filename", ""),
                num_pages=payload.get("num_pages", 0),
                num_machines=payload.get("num_machines", 0),
                machines=json.dumps(payload.get("machines", [])),
                excel_files=json.dumps(payload.get("excel_files", [])),
                status=payload.get("status", "completed"),
                created_at=datetime.utcnow(),
            )
            db.add(row)
            db.commit()
    except Exception as e:
        logger.warning(f"DB persist failed (non-fatal): {e}")


@app.post("/api/extract", response_model=ExtractionResult)
async def extract_pdf(
    file: UploadFile = File(...),
    machine_data: str = Form(default="{}"),
):
    extraction_id = generate_extraction_id()
    logger.info(f"=== New extraction: {extraction_id} - {file.filename} ===")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files supported")

    safe = file.filename.replace(" ", "_")
    pdf_path = UPLOAD_DIR / f"{extraction_id}_{safe}"
    content = await file.read()
    pdf_path.write_bytes(content)
    logger.info(f"Saved upload: {pdf_path.name} ({len(content):,} bytes)")

    try:
        raw = json.loads(machine_data) if machine_data else {}
    except json.JSONDecodeError:
        raise HTTPException(400, "machine_data must be valid JSON (use double quotes)")
    machine_dict = {
        k.strip().upper(): [s.strip().upper() for s in (v or []) if s and s.strip()]
        for k, v in raw.items()
        if k and k.strip()
    }
    user_names = list(machine_dict.keys())
    logger.info(f"User-specified: {machine_dict}")

    # 1. extract pages
    try:
        pages = extract_pages(pdf_path)
        jpeg_count = sum(1 for p in pages if p.jpeg_bytes)
        logger.info(f"JPEG COUNT: {jpeg_count}")
    except Exception as e:
        logger.info(f"Page extraction failed: {e}")
        _save_metadata(extraction_id, {
            "extraction_id": extraction_id, "status": "failed",
            "error": f"Page extraction failed: {e}",
        })
        raise HTTPException(500, f"Page extraction failed: {e}")

    num_pages = len(pages)
    pages_with_jpeg = sum(1 for p in pages if p.jpeg_bytes)
    logger.info(f"Pages: {num_pages} total, {pages_with_jpeg} with jpeg")

    # 2. segment blocks
    try:
        blocks = segment_blocks(pages, user_names=user_names if user_names else None)
    except Exception as e:
        logger.info(f"Block segmentation failed: {e}")
        blocks = [Block(
            machine="UNKNOWN",
            text="\n\n".join(p.ocr_text for p in pages),
            page_range=[p.num for p in pages], pages=pages,
        )]

    excel_files = []
    machine_summary = []

    # 3-5. extract per block, validate, write Excel
    for block in blocks:
        machine_name = block.machine
        sub_machines = machine_dict.get(machine_name, [])

        # ✅ If user did NOT provide variants → auto detect
        if not sub_machines:
            detected = detect_variants_from_text(block.text)

            detected = [d for d in detected if d != machine_name]

            if detected:
                logger.info(f"{machine_name}: auto-detected variants → {detected}")
                sub_machines = detected

        logger.info(f"\n--- {machine_name} (variants: {sub_machines or 'NONE'}) ---")

        if sub_machines:
            valid_names = [
                v for v in sub_machines
                if v in block.text.upper()
            ]

            if not valid_names:
                logger.warning(f"{machine_name}: all user variants invalid → skipping")
                continue

            removed = set(sub_machines) - set(valid_names)
            if removed:
                logger.warning(f"{machine_name}: removed invalid variants → {list(removed)}")

            sub_machines = valid_names
                
        try:
            if sub_machines:
                variants = {}

                for variant in sub_machines:
                    filtered_pages = filter_pages_for_variant(variant, block.pages)

                    if len(filtered_pages) < 3:
                        logger.warning(f"{machine_name}/{variant}: too few pages after filter → using full block")
                        filtered_pages = block.pages

                    sub_block = Block(
                        machine=block.machine,
                        text="\n\n".join(p.ocr_text for p in filtered_pages),
                        page_range=[p.num for p in filtered_pages],
                        pages=filtered_pages,
                    )

                    try:
                        result = extract_machine_data(
                            block=sub_block,
                            sub_machines=[variant],
                        )
                        variants.update(result)
                    except Exception as e:
                        logger.info(f"{machine_name}/{variant}: extraction failed: {e}")

            else:
                variants = extract_machine_data(
                    block=block,
                    sub_machines=None,
                )
        except Exception as e:
            logger.info(f"{machine_name}: vision extraction crashed: {e}")
            variants = {}

        if not variants:
            logger.warning(f"{machine_name}: extraction failed — skipping")
            continue

        # Enrich BEFORE validation
        for vname, vdata in variants.items():
            vdata = enrich_variant(vdata, block.text)
            vdata = normalize_variant(vdata)
            variants[vname] = vdata

        # Then validate
        variants = validate_variants(variants)

        FATAL_KEYWORDS = ["physically invalid", "UV max", "LV cutoff"]

        def _is_fatal(flags):
            return any(any(k in f for k in FATAL_KEYWORDS) for f in flags)

        usable = {
            n: vd for n, vd in variants.items()
            if extraction_was_successful(vd) and not _is_fatal(vd.specs.flags)
        }

        if not usable:
            logger.warning(f"{machine_name}: no variant produced usable data")
            machine_summary.append({
                "machine": machine_name, "status": "no_usable_data",
                "variants": list(variants.keys()),
            })
            continue

        # 1. Always write individual variant files
        for vname, vdata in usable.items():
            try:
                fname = write_variant_workbook(
                    extraction_id=extraction_id,
                    parent_machine=machine_name,
                    variant=vdata,
                    output_dir=OUTPUT_DIR,
                )
                excel_files.append(fname)
            except Exception as e:
                logger.info(f"{machine_name}/{vname}: Excel write failed: {e}")

        # 2. ALWAYS write consolidated machine file (even if single variant)
        try:
            fname = write_consolidated_workbook(
                extraction_id=extraction_id,
                parent_machine=machine_name,
                variants=usable,
                output_dir=OUTPUT_DIR,
            )
            excel_files.append(fname)
        except Exception as e:
            logger.info(f"{machine_name}: consolidated Excel failed: {e}")

        machine_summary.append({
            "machine": machine_name,
            "status": "ok",
            "variants": list(usable.keys()),
            "flags": {
                vname: {
                    "spec_flags": vd.specs.flags,
                    "step_flag_count": sum(1 for s in vd.test_steps if s.flags),
                }
                for vname, vd in usable.items()
            },
        })

    metadata = {
        "extraction_id": extraction_id,
        "original_filename": file.filename,
        "saved_as": pdf_path.name,
        "num_pages": num_pages,
        "num_machines": len(blocks),
        "machines": [b.machine for b in blocks],
        "machine_summary": machine_summary,
        "excel_files": excel_files,
        "user_input": machine_dict,
        "status": "completed" if excel_files else "no_output",
        "timestamp": datetime.utcnow().isoformat(),
    }
    _save_metadata(extraction_id, metadata)
    _persist_extraction(extraction_id, metadata)

    return ExtractionResult(
        extraction_id=extraction_id,
        filename=file.filename,
        num_pages=num_pages,
        num_machines=len(blocks),
        machines=[b.machine for b in blocks],
        excel_files=excel_files,
        status=metadata["status"],
    )


@app.get("/api/extractions")
async def list_extractions():
    items = []
    for path in METADATA_DIR.glob("ext_*.json"):
        try:
            data = json.loads(path.read_text())
            items.append(data)
        except Exception as e:
            logger.warning(f"Failed to read {path.name}: {e}")
    items.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
    return JSONResponse(items)


@app.get("/api/extraction/{extraction_id}")
async def get_extraction(extraction_id: str):
    path = METADATA_DIR / f"{extraction_id}.json"
    if not path.exists():
        raise HTTPException(404, f"Extraction {extraction_id} not found")
    return JSONResponse(json.loads(path.read_text()))


@app.delete("/api/extraction/{extraction_id}")
async def delete_extraction(extraction_id: str, delete_pdf: bool = False):
    deleted = []
    md = METADATA_DIR / f"{extraction_id}.json"
    if md.exists():
        md.unlink(); deleted.append(md.name)
    for f in OUTPUT_DIR.glob(f"{extraction_id}_*"):
        f.unlink(); deleted.append(f.name)
    if delete_pdf:
        for f in UPLOAD_DIR.glob(f"{extraction_id}_*"):
            f.unlink(); deleted.append(f.name)
    try:
        with SessionLocal() as db:
            row = db.query(ExtractionDB).filter_by(extraction_id=extraction_id).first()
            if row:
                db.delete(row); db.commit()
    except Exception as e:
        logger.warning(f"DB delete failed (non-fatal): {e}")
    if not deleted:
        raise HTTPException(404, f"Nothing to delete for {extraction_id}")
    return {"deleted": deleted, "extraction_id": extraction_id}


@app.get("/api/download/{extraction_id}/{filename}")
async def download_excel(extraction_id: str, filename: str):
    if not filename.startswith(extraction_id):
        raise HTTPException(403, "Filename must belong to extraction id")
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"File not found: {filename}")
    return FileResponse(
        path=str(path), filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"service": "GIC Extraction Engine", "version": "3.0.0", "status": "running"}


@app.get("/extraction.html")
async def extraction_page():
    page = STATIC_DIR / "extraction.html"
    if page.exists():
        return FileResponse(str(page))
    raise HTTPException(404)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "version": "3.0.0",
    }