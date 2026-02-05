from __future__ import annotations

from pathlib import Path
from typing import Dict

from .block_segmenter import segment_blocks
from .confidence_scorer import score_confidence
from .excel_writer import generate_excel
from .json_writer import generate_json
from .pdf_extractor import extract_text
from .spec_parser import parse_specifications
from .step_extractor import extract_steps


def _metadata_from_block(block: Dict[str, str], filename_stem: str) -> Dict[str, str]:
    header = block.get("header", "")
    criticality = "HIGH" if "high" in block.get("text", "").lower() else ""
    return {
        "product_name": block.get("machine") or filename_stem,
        "process_name": header or block.get("machine", filename_stem),
        "criticality": criticality,
    }


def process_pdf(pdf_path: Path, output_dir: Path) -> Dict[str, object]:
    pages = extract_text(pdf_path)
    full_text = "\n\n".join(p.strip() for p in pages if p and p.strip())
    blocks = segment_blocks(full_text) or [{"machine": pdf_path.stem, "header": pdf_path.stem, "text": full_text}]

    results: Dict[str, object] = {
        "excel_files": [],
        "json_files": [],
        "flagged_items": [],
        "confidence": 0.0,
        "num_pages": len(pages),
        "num_blocks": len(blocks),
    }
    confidences = []

    for block in blocks:
        specs = parse_specifications(block["text"])
        steps = extract_steps(block["text"])
        flagged, conf = score_confidence(specs, steps)
        meta = _metadata_from_block(block, pdf_path.stem)

        excel_name = generate_excel(block["machine"], meta, specs, steps, flagged, output_dir)
        json_name = generate_json(block["machine"], meta, specs, steps, flagged, output_dir)

        results["excel_files"].append(excel_name)
        results["json_files"].append(json_name)
        results["flagged_items"].extend(flagged)
        confidences.append(conf)

    if confidences:
        results["confidence"] = round(sum(confidences) / len(confidences), 3)

    return results
