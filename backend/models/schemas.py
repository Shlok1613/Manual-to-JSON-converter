from __future__ import annotations

from typing import List

from pydantic import BaseModel


class ExtractResponse(BaseModel):
    filename: str
    num_pages: int
    num_blocks: int
    excel_files: List[str]
    json_files: List[str]
    flagged_items: List[dict]
    confidence_average: float
