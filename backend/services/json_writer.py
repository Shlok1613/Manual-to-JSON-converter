from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def generate_json(machine: str, metadata: Dict[str, str], specs: Dict[str, object], steps: List[Dict[str, object]], flagged: List[Dict[str, object]], output_dir: Path) -> str:
    """Stage 8: write machine JSON output with confidence and flags."""
    payload = {
        "metadata": {
            "product_name": metadata.get("product_name", machine),
            "extraction_date": datetime.now(timezone.utc).isoformat(),
            "process_name": metadata.get("process_name", machine),
            "criticality": metadata.get("criticality", ""),
        },
        "specifications": {
            "reference_voltage": {"value": specs.get("reference_voltage") or "", "unit": "VAC"},
            "voltage_parameters": specs.get("voltage_parameters", {}),
            "timing_parameters": specs.get("timing_parameters", {}),
        },
        "test_procedures": steps,
        "extraction_quality": {"flagged_for_review": flagged},
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = machine.replace(" ", "_").replace("/", "_")
    out = output_dir / f"{safe_name}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out.name
