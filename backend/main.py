"""
FastAPI main application with unique extraction IDs.
"""
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import logging
import json

from models.schemas import ExtractionResult, generate_extraction_id

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="PDF to Excel/JSON Converter",
    description="Extracts manufacturing test procedures from PDFs with unique tracking IDs",
    version="1.0.0"
)

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


@app.get("/")
def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "message": "PDF Extraction Service is running",
        "version": "1.0.0",
        "features": [
            "Unique extraction IDs",
            "Database-ready structure",
            "File tracking"
        ]
    }


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
    
    # STEP 6: Save text files (NEW!)
    text_files = []
    try:
        # Save full extracted text
        text_path = OUTPUT_DIR / f"{extraction_id}_extracted.txt"
        text_path.write_text(full_text, encoding='utf-8')
        text_files.append(text_path.name)
        logger.info(f"Saved extracted text: {text_path.name}")
        
        # Save summary
        summary_path = OUTPUT_DIR / f"{extraction_id}_summary.txt"
        summary_path.write_text(summary, encoding='utf-8')
        text_files.append(summary_path.name)
        logger.info(f"Saved summary: {summary_path.name}")
        
        # Save individual machine blocks (NEW!)
        for block in blocks:
            block_filename = f"{extraction_id}_{block['machine']}.txt"
            block_path = OUTPUT_DIR / block_filename
            block_path.write_text(block['text'], encoding='utf-8')
            text_files.append(block_filename)
            logger.info(f"Saved block: {block_filename}")
        
    except Exception as e:
        logger.warning(f"Failed to save text files: {e}")
        # Don't fail the whole request
    
    # STEP 7: Save extraction metadata (UPDATED!)
    metadata = {
        "extraction_id": extraction_id,
        "original_filename": file.filename,
        "saved_as": pdf_filename,
        "num_pages": num_pages,
        "num_machines": num_machines,  # NEW!
        "machines": [block["machine"] for block in blocks],  # NEW!
        "status": "completed",
        "uploaded_at": datetime.utcnow().isoformat(),
        "processed_at": datetime.utcnow().isoformat(),
        "text_files": text_files,  # NEW!
        "excel_files": [],  # Will populate in Week 2
        "json_files": []    # Will populate in Week 2
    }
    
    metadata_path = METADATA_DIR / f"{extraction_id}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))
    logger.info(f"Saved metadata: {metadata_path.name}")
    
    # STEP 8: Return result (UPDATED!)
    result = ExtractionResult(
        extraction_id=extraction_id,
        filename=file.filename,
        num_pages=num_pages,
        num_machines=num_machines,  # NOW ACCURATE!
        status="completed",
        created_at=datetime.utcnow(),
        excel_files=[],  # Will populate in Week 2
        json_files=[],   # Will populate in Week 2
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
    
    Returns list of extraction metadata.
    Useful for database/UI to show history.
    """
    metadata_files = sorted(
        METADATA_DIR.glob("ext_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True  # Newest first
    )
    
    extractions = []
    for meta_file in metadata_files[:limit]:
        if "_error" in meta_file.name:
            continue  # Skip error files
        
        try:
            metadata = json.loads(meta_file.read_text())
            extractions.append(metadata)
        except Exception as e:
            logger.warning(f"Failed to read {meta_file.name}: {e}")
    
    return {
        "total": len(extractions),
        "extractions": extractions
    }


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