from __future__ import annotations

from typing import Dict, List, Tuple


def score_confidence(specs: Dict[str, object], steps: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], float]:
    """Stage 6: score extraction confidence and return flagged items."""
    flagged: List[Dict[str, object]] = []
    scores: List[float] = []

    for key, value in specs.get("voltage_parameters", {}).items():
        score = 0.9
        if not value.get("setting") and not value.get("range"):
            score = 0.65
        elif value.get("setting") and value.get("range"):
            score = 0.98
        scores.append(score)
        if score < 0.75:
            flagged.append({"type": "specification", "field": key, "value": value, "confidence": score})

    for step in steps:
        score = 0.7
        if step.get("action"):
            score += 0.15
        if step.get("led") or step.get("relay"):
            score += 0.1
        if step.get("voltage") or step.get("delay"):
            score += 0.05
        score = min(score, 0.99)
        step["confidence"] = round(score, 2)
        scores.append(score)
        if score < 0.75:
            flagged.append({"type": "step", "step_number": step.get("step_number"), "action": step.get("action"), "confidence": score})

    average = sum(scores) / len(scores) if scores else 0.0
    return flagged, round(average, 3)
