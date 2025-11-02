# backend/services/excel_json_converter.py
import pandas as pd
from openpyxl import Workbook # type: ignore
from pathlib import Path
import json

def save_to_excel(text_data: str, output_path: Path):
    """
    Creates a simple Excel file where each line of text becomes one row.
    Later this will be replaced by structured parameter mapping.
    """
    # Split text by lines and remove empties
    lines = [line.strip() for line in text_data.splitlines() if line.strip()]
    df = pd.DataFrame(lines, columns=["Extracted_Text"])
    
    output_path.parent.mkdir(exist_ok=True)
    df.to_excel(output_path, index=False)
    return output_path

def convert_excel_to_json(excel_path: Path):
    """
    Reads the Excel file and converts it to JSON format.
    """
    df = pd.read_excel(excel_path)
    json_data = df.to_dict(orient="records")
    
    json_path = excel_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)
    return json_path
