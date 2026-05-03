"""Data models and schemas for the GIC Extraction Engine."""
from datetime import datetime
from typing import List, Dict
from pydantic import BaseModel, Field
import uuid


def generate_extraction_id() -> str:
    return f"ext_{uuid.uuid4().hex[:8]}"


class ExtractionResult(BaseModel):
    extraction_id: str
    filename: str
    num_pages: int
    num_machines: int = 0
    machines: List[str] = Field(default_factory=list)
    excel_files: List[str] = Field(default_factory=list)
    status: str = "completed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MachineSummary(BaseModel):
    machine: str
    status: str
    variants: List[str] = Field(default_factory=list)