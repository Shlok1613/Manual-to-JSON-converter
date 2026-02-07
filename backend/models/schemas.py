"""
Data models and schemas for the application.
These define the structure of our data.
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


def generate_extraction_id() -> str:
    """
    Generate a unique ID for each extraction.
    
    Format: ext_xxxxxxxx (8 characters after ext_)
    Example: ext_a3f2b9c1
    
    Why this format?
    - Short and readable
    - Unique (astronomically unlikely to collide)
    - Easy to search in database
    - URL-safe
    """
    return f"ext_{uuid.uuid4().hex[:8]}"


class ExtractionRequest(BaseModel):
    """
    Data we receive when user uploads a PDF.
    """
    # Nothing needed here - FastAPI handles file upload
    pass


class ExtractionResult(BaseModel):
    """
    Data we return after processing a PDF.
    
    This is what the API sends back to the user.
    """
    extraction_id: str = Field(
        ..., 
        description="Unique ID for this extraction (e.g., ext_a3f2b9c1)"
    )
    filename: str = Field(
        ..., 
        description="Original PDF filename"
    )
    num_pages: int = Field(
        ..., 
        description="Number of pages extracted"
    )
    num_machines: int = Field(
        default=0, 
        description="Number of machine/product sections found"
    )
    status: str = Field(
        default="completed", 
        description="Status: processing, completed, failed"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When extraction was created"
    )
    excel_files: List[str] = Field(
        default_factory=list,
        description="List of generated Excel filenames"
    )
    json_files: List[str] = Field(
        default_factory=list,
        description="List of generated JSON filenames"
    )
    download_url: str = Field(
        ...,
        description="URL to download results"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "extraction_id": "ext_a3f2b9c1",
                "filename": "FUnctional_Testing_WI_Five_series.pdf",
                "num_pages": 12,
                "num_machines": 7,
                "status": "completed",
                "created_at": "2026-02-07T10:30:00Z",
                "excel_files": [
                    "ext_a3f2b9c1_SPPR.xlsx",
                    "ext_a3f2b9c1_SM301.xlsx"
                ],
                "json_files": [
                    "ext_a3f2b9c1_SPPR.json",
                    "ext_a3f2b9c1_SM301.json"
                ],
                "download_url": "/api/download/ext_a3f2b9c1"
            }
        }


class FileInfo(BaseModel):
    """
    Information about a generated file.
    """
    filename: str
    machine_name: str
    file_type: str  # "excel" or "json"
    size_bytes: int
    created_at: datetime


class ExtractionMetadata(BaseModel):
    """
    Complete metadata for an extraction.
    This is what you'd store in your database.
    """
    extraction_id: str
    original_filename: str
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    status: str
    num_pages: int
    num_machines: int
    files: List[FileInfo] = []
    error_message: Optional[str] = None