"""
FastAPI main application with unique extraction IDs.
"""
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, File, Request, UploadFile, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import logging
import json
from fastapi.staticfiles import StaticFiles

from models.schemas import ExtractionResult, generate_extraction_id

from database import engine
from models.db_models import Base
from database import SessionLocal
from models.db_models import ExtractionDB

Base.metadata.create_all(bind=engine)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="PDF to Excel/JSON Converter",
    description="Extracts manufacturing test procedures from PDFs with unique tracking IDs",
    version="1.0.0"
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Define directories
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
METADATA_DIR = BASE_DIR / "metadata"  # NEW: Store extraction metadata

# Create directories
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger.info(f"Upload directory: {UPLOAD_DIR}")
logger.info(f"Output directory: {OUTPUT_DIR}")
METADATA_DIR.mkdir(exist_ok=True)


@app.post("/api/extract", response_model=ExtractionResult)
async def extract_pdf(file: UploadFile = File(...)):
    """
    Main extraction endpoint with unique ID generation.
    
    Complete process:
    1. Generate unique extraction ID
    2. Save uploaded PDF
    3. Extract text from PDF
    4. Segment into machine blocks
    5. Save text files (extracted + summary)
    6. Save metadata
    7. Return result with unique ID
    """
    
    # STEP 1: Generate unique ID
    extraction_id = generate_extraction_id()
    logger.info(f"New extraction: {extraction_id} - {file.filename}")
    
    # STEP 2: Validate file
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported"
        )
    
    # STEP 3: Save PDF with unique ID
    safe_filename = file.filename.replace(" ", "_")
    pdf_filename = f"{extraction_id}_{safe_filename}"
    pdf_path = UPLOAD_DIR / pdf_filename
    
    try:
        content = await file.read()
        pdf_path.write_bytes(content)
        logger.info(f"Saved PDF: {pdf_path.name}")
    except Exception as e:
        logger.error(f"Failed to save PDF: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save file: {str(e)}"
        )
    
    # STEP 4: Extract text from PDF
    try:
        from services.pdf_extractor import extract_text
        
        pages = extract_text(pdf_path)
        num_pages = len(pages)
        
        logger.info(f"Extracted {num_pages} pages from {extraction_id}")
        
    except Exception as e:
        logger.error(f"Extraction failed for {extraction_id}: {e}")
        
        # Save error metadata
        error_metadata = {
            "extraction_id": extraction_id,
            "filename": file.filename,
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
        metadata_path = METADATA_DIR / f"{extraction_id}_error.json"
        metadata_path.write_text(json.dumps(error_metadata, indent=2))
        
        raise HTTPException(
            status_code=500,
            detail=f"Extraction failed: {str(e)}"
        )
    
    # STEP 5: Segment into machine blocks (NEW!)
    try:
        from services.block_segmenter import segment_blocks, get_block_summary
        
        # Combine all pages
        full_text = "\n\n".join(pages)
        
        # Segment into machine blocks
        blocks = segment_blocks(full_text)
        num_machines = len(blocks)
        
        # Create summary
        summary = get_block_summary(blocks)
        
        logger.info(f"Found {num_machines} machine blocks in {extraction_id}")
        
    except Exception as e:
        logger.error(f"Segmentation failed for {extraction_id}: {e}")
        # Don't fail the whole extraction if segmentation fails
        blocks = []
        num_machines = 0
        summary = f"Segmentation failed: {str(e)}"

    
    # STEP 5.5: Generate test conditions per machine block
    processed_blocks = []
    try:
        from services.universal_spec_extractor import extract_specs, extract_and_generate

        for block in blocks:
            spec = extract_specs(block["text"])
            test_conditions = extract_and_generate(block["text"])
            block["spec_data"] = spec
            block["test_conditions"] = test_conditions
            block["num_test_conditions"] = len(test_conditions)
            processed_blocks.append(block)
        logger.info(f"{block['machine']}: {len(test_conditions)} conditions")

    except Exception as e:
        logger.error(f"Condition generation failed: {e}")
        import traceback
        traceback.print_exc()
        processed_blocks = blocks

    print("TOTAL BLOCKS:", len(processed_blocks))
    
    # STEP 6: Text files DISABLED (not needed - only Excel outputs)
    text_files = []

    # STEP 6.5: Generate Excel files with specs AND test conditions
    excel_files = []
    try:
        from services.excel_writer import generate_excel
        
        print("STARTING EXCEL GENERATION")

        for block in processed_blocks:
            print("PROCESSING MACHINE:", block["machine"])

            filename = generate_excel(
                extraction_id,
                block["machine"],
                block.get("spec_data", {}),     # ← was block.get("specifications", {})
                OUTPUT_DIR,
                test_conditions=block.get("test_conditions", [])
            )
            #print("SAVING FILE TO:", OUTPUT_DIR / filename)
            excel_files.append(filename)
            logger.info(f"Generated Excel: {filename}")
        
    except Exception as e:
        logger.error(f"Excel generation failed: {e}")
        import traceback
        traceback.print_exc()
        # Don't fail the whole request if Excel generation fails
    
# STEP 7: Save extraction metadata (UPDATED!)
    metadata = {
        "extraction_id": extraction_id,
        "original_filename": file.filename,
        "saved_as": pdf_filename,
        "num_pages": num_pages,
        "num_machines": num_machines,
        "machines": [block["machine"] for block in processed_blocks],
        "machine_details": [
            {
                "machine": block["machine"],
                "num_test_conditions": block.get("num_test_conditions", 0),
            }
            for block in processed_blocks
        ],
        "status": "completed",
        "uploaded_at": datetime.utcnow().isoformat(),
        "processed_at": datetime.utcnow().isoformat(),
        "text_files": text_files,
        "excel_files": excel_files,  # Will populate next
        "json_files": []    # Will populate next
    }
    
    metadata_path = METADATA_DIR / f"{extraction_id}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))
    logger.info(f"Saved metadata: {metadata_path.name}")

    # STEP 7.5: Save to database
    from database import SessionLocal
    from models.db_models import ExtractionDB

    db = SessionLocal()

    db_entry = ExtractionDB(
        extraction_id=extraction_id,
        filename=file.filename,
        num_pages=num_pages,
        num_machines=num_machines,
        status="completed",
        uploaded_at=datetime.utcnow().isoformat()
    )

    db.add(db_entry)
    db.commit()
    db.close()
    
    # STEP 8: Return result (UPDATED!)
    result = ExtractionResult(
        extraction_id=extraction_id,
        filename=file.filename,
        num_pages=num_pages,
        num_machines=num_machines,
        status="completed",
        created_at=datetime.utcnow(),
        excel_files=excel_files,  # NOW FILLED!
        json_files=[],   # Will populate in Week 3
        download_url=f"/api/download/{extraction_id}"
    )
    
    return result


@app.get("/api/extraction/{extraction_id}")
def get_extraction_info(extraction_id: str):
    """
    Get information about a specific extraction.
    
    URL: /api/extraction/ext_a3f2b9c1
    
    Returns metadata about the extraction.
    """
    metadata_path = METADATA_DIR / f"{extraction_id}.json"
    
    if not metadata_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Extraction {extraction_id} not found"
        )
    
    metadata = json.loads(metadata_path.read_text())
    return metadata


@app.get("/api/download/{extraction_id}/{filename}")
def download_file(extraction_id: str, filename: str):
    """
    Download a specific file from an extraction.
    
    URL: /api/download/ext_a3f2b9c1/ext_a3f2b9c1_SPPR.xlsx
    
    Returns the file for download.
    """
    file_path = OUTPUT_DIR / filename
    
    # Verify the file belongs to this extraction
    if not filename.startswith(extraction_id):
        raise HTTPException(
            status_code=403,
            detail="File does not belong to this extraction"
        )
    
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File {filename} not found"
        )
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )

@app.get("/api/files/{extraction_id}")
def list_extraction_files(extraction_id: str):
    """
    List all files for a specific extraction.
    
    URL: /api/files/ext_a3f2b9c1
    
    Returns list of files you can download.
    """
    # Check extraction exists
    metadata_path = METADATA_DIR / f"{extraction_id}.json"
    if not metadata_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Extraction {extraction_id} not found"
        )
    
    # Get metadata
    metadata = json.loads(metadata_path.read_text())
    
    # Find all files for this extraction
    files = []
    for file_path in OUTPUT_DIR.glob(f"{extraction_id}_*"):
        if file_path.is_file():
            files.append({
                "filename": file_path.name,
                "size_bytes": file_path.stat().st_size,
                "download_url": f"/api/download/{extraction_id}/{file_path.name}"
            })
    
    return {
        "extraction_id": extraction_id,
        "total_files": len(files),
        "files": files,
        "metadata": metadata
    }


@app.get("/api/extractions")
def list_extractions(limit: int = 50):
    """
    List all extractions.

    URL: /api/extractions?limit=50

    Returns list of extraction metadata. Filters out ghost DB entries
    (rows whose metadata JSON file no longer exists on disk).
    """
    from database import SessionLocal
    from models.db_models import ExtractionDB

    db = SessionLocal()
    data = db.query(ExtractionDB).order_by(ExtractionDB.uploaded_at.desc()).all()
    db.close()

    extractions = []
    for e in data:
        meta_path = METADATA_DIR / f"{e.extraction_id}.json"
        if not meta_path.exists():
            # Ghost DB entry — metadata file missing; skip it
            logger.warning(f"Ghost DB entry detected (no metadata): {e.extraction_id}")
            continue
        extractions.append({
            "extraction_id": e.extraction_id,
            "original_filename": e.filename,
            "num_machines": e.num_machines,
            "uploaded_at": e.uploaded_at,
            "status": e.status
        })

    return {
        "total": len(extractions),
        "extractions": extractions
    }
    
# extractions = []
#     for meta_file in metadata_files[:limit]:
#         if "_error" in meta_file.name:
#             continue  # Skip error files
        
#         try:
#             metadata = json.loads(meta_file.read_text())
#             extractions.append(metadata)
#         except Exception as e:
#             logger.warning(f"Failed to read {meta_file.name}: {e}")
    
#     return {
#         "total": len(extractions),
#         "extractions": extractions
#     }

@app.delete("/api/extraction/{extraction_id}")
def delete_extraction(extraction_id: str, delete_pdf: bool = False):
    """
    Delete an extraction.

    If delete_pdf=false (default – "Delete Results Only"):
      - Deletes Excel output files from outputs/
      - KEEPS metadata JSON, DB entry, and original PDF

    If delete_pdf=true ("Delete Results & PDF"):
      - Deletes Excel output files
      - Deletes metadata JSON
      - Deletes DB entry
      - Deletes original uploaded PDF
    """

    extraction_id = extraction_id.strip()
    metadata_path = METADATA_DIR / f"{extraction_id}.json"

    if not metadata_path.exists():
        # Metadata gone — only clean up DB if this is a full delete
        if delete_pdf:
            db = SessionLocal()
            entry = db.query(ExtractionDB).filter(
                ExtractionDB.extraction_id == extraction_id
            ).first()
            if entry:
                db.delete(entry)
                db.commit()
            db.close()
        return {
            "status": "already_deleted",
            "message": "Metadata not found",
            "results_deleted": True,
            "pdf_deleted": delete_pdf
        }

    deleted_files = []
    errors = []

    try:
        # ── Step 1: Always delete output (Excel) files ──────────────────────
        for file_path in OUTPUT_DIR.glob(f"{extraction_id}_*"):
            try:
                file_path.unlink()
                deleted_files.append(file_path.name)
                logger.info(f"Deleted output file: {file_path.name}")
            except Exception as e:
                errors.append(f"Failed to delete {file_path.name}: {str(e)}")

        if delete_pdf:
            # ── Step 2 (full delete): remove metadata JSON ──────────────────
            try:
                metadata_path.unlink()
                deleted_files.append(metadata_path.name)
                logger.info(f"Deleted metadata: {metadata_path.name}")
            except Exception as e:
                errors.append(f"Failed to delete metadata: {str(e)}")

            # ── Step 3 (full delete): remove original PDF ───────────────────
            for pdf_path in UPLOAD_DIR.glob(f"{extraction_id}_*"):
                try:
                    pdf_path.unlink()
                    deleted_files.append(pdf_path.name)
                    logger.info(f"Deleted PDF: {pdf_path.name}")
                except Exception as e:
                    errors.append(f"Failed to delete PDF: {str(e)}")

            # ── Step 4 (full delete): remove DB entry ───────────────────────
            db = SessionLocal()
            entry = db.query(ExtractionDB).filter(
                ExtractionDB.extraction_id == extraction_id
            ).first()
            if entry:
                db.delete(entry)
                db.commit()
            db.close()
        else:
            logger.info(
                f"Results-only delete for {extraction_id}: "
                "metadata, DB entry, and PDF are preserved."
            )

        return {
            "extraction_id": extraction_id,
            "status": "deleted",
            "results_deleted": True,
            "pdf_deleted": delete_pdf,
            "deleted_files": deleted_files,
            "deleted_count": len(deleted_files),
            "errors": errors if errors else None
        }

    except Exception as e:
        logger.error(f"Delete extraction failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete extraction: {str(e)}"
        )


@app.api_route("/api/pdf/{extraction_id}", methods=["GET", "HEAD"])
def download_pdf(extraction_id: str, request: Request):
    """
    Download or check the original uploaded PDF for an extraction.

    GET  /api/pdf/ext_a3f2b9c1  → returns the PDF file for download
    HEAD /api/pdf/ext_a3f2b9c1  → returns 200 if PDF exists, 404 if not
                                   (used by frontend to check availability)
    """
    matches = list(UPLOAD_DIR.glob(f"{extraction_id}_*"))
    pdf_matches = [p for p in matches if p.suffix.lower() == ".pdf"]

    if not pdf_matches:
        raise HTTPException(
            status_code=404,
            detail=f"Original PDF for {extraction_id} not found. It may have been deleted."
        )

    pdf_path = pdf_matches[0]

    # HEAD request: confirm existence only, no body
    if request.method == "HEAD":
        from fastapi.responses import Response
        return Response(
            status_code=200,
            headers={"Content-Type": "application/pdf"}
        )

    # GET request: serve the file
    return FileResponse(
        path=pdf_path,
        filename=pdf_path.name,
        media_type="application/pdf"
    )


@app.delete("/api/extraction/{extraction_id}/file/{filename}")
def delete_single_file(extraction_id: str, filename: str):
    """
    Delete a single Excel file from an extraction.
    
    Useful for removing specific machine Excel files without deleting entire extraction.
    
    Args:
        extraction_id: Extraction ID
        filename: Filename to delete (e.g., ext_abc12345_SPPR.xlsx)
    
    Usage:
        DELETE /api/extraction/ext_abc12345/file/ext_abc12345_SPPR.xlsx
    """
    
    # Verify file belongs to this extraction
    if not filename.startswith(extraction_id):
        raise HTTPException(
            status_code=403,
            detail="File does not belong to this extraction"
        )
    
    file_path = OUTPUT_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File {filename} not found"
        )
    
    try:
        file_path.unlink()
        logger.info(f"Deleted file: {filename}")
        
        return {
            "extraction_id": extraction_id,
            "filename": filename,
            "status": "deleted"
        }
        
    except Exception as e:
        logger.error(f"Failed to delete file {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete file: {str(e)}"
        )


@app.get("/health")
def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "upload_dir_exists": UPLOAD_DIR.exists(),
        "output_dir_exists": OUTPUT_DIR.exists(),
        "metadata_dir_exists": METADATA_DIR.exists(),
        "total_extractions": len(list(METADATA_DIR.glob("ext_*.json")))
    }

@app.get("/")
def serve_index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")