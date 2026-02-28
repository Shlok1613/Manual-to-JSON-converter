"""End-to-end test: segmentation -> table extraction -> specs -> results."""
import sys
from pathlib import Path
sys.path.insert(0, r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend")

from services.pdf_extractor import extract_text
from services.block_segmenter import segment_blocks
from services.table_extractor import extract_tables
from services.spec_parser import parse_specifications

pdf_dir = Path(r"c:\Users\SHLOK\Desktop\Project\Manual-to-JSON-converter\backend\uploads")
pdfs = list(pdf_dir.glob("ext_*_FUnctional*.pdf"))
latest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)

pages = extract_text(latest_pdf)
full_text = "\n\n".join(pages)

blocks = segment_blocks(full_text)
print(f"Total blocks: {len(blocks)}\n")
print(f"{'Machine':16s} {'Chars':>6s}  {'Tables':>6s}  {'V.Params':>8s}  {'T.Params':>8s}")
print("-" * 60)

for b in blocks:
    tables = extract_tables(b['text'])
    specs = parse_specifications(b['text'], tables)
    vp = len(specs.get('voltage_parameters', {}))
    tp = len(specs.get('timing_parameters', {}))
    print(f"{b['machine']:16s} {len(b['text']):6d}  {len(tables):6d}  {vp:8d}  {tp:8d}")
