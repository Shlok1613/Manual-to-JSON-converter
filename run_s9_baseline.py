#!/usr/bin/env python3
"""Session 9 Baseline Run — MAG03D0424 extraction and comparison."""
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from services.pdf_extractor import extract_pages
from services.block_segmenter import segment_blocks
from services.vision_extractor import extract_machine_data
from services.enricher import enrich_variant
from services.normalizer import normalize_variant
from services.spec_linker import link_specs_to_steps
from services.validator import validate_variants
from services.template_writer import write_variant_workbook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("run_s9_baseline.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path('outputs/s9')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger.info("="*60)
logger.info("SESSION 9 BASELINE RUN — MAG03D0424")
logger.info(f"Started: {datetime.now().isoformat()}")
logger.info("="*60)

# Load PDF
logger.info("Loading PDF...")
pages = extract_pages(Path('source/WI.pdf'))
logger.info(f"Loaded {len(pages)} pages")

# Segment into blocks
logger.info("Segmenting blocks...")
blocks = segment_blocks(pages)
logger.info(f"Segmented into {len(blocks)} blocks:")
for b in blocks:
    logger.info(f"  {b.machine}: page_range={b.page_range}")

# Extract MAG03D0424
mag_blocks = [b for b in blocks if b.machine == 'MAG03D0424']
if not mag_blocks:
    logger.error("No MAG03D0424 block found!")
    sys.exit(1)

block = mag_blocks[0]
logger.info(f"Extracting {block.machine}...")

variants = extract_machine_data(block=block, sub_machines=['MAG03D0424'])
time.sleep(5)

if not variants:
    logger.error("No variants extracted!")
    sys.exit(1)

logger.info(f"Extracted {len(variants)} variants")

# Process each variant
for vname, vdata in variants.items():
    logger.info(f"Processing {vname}...")
    vdata = enrich_variant(vdata, block.text)
    vdata = normalize_variant(vdata)
    variants[vname] = vdata
    logger.info(f"  {vname}: {len(vdata.test_steps)} steps")

# Link specs to steps
variants = link_specs_to_steps(variants)

# Validate
variants = validate_variants(variants)

# Write output
for vname, vdata in variants.items():
    usable = vdata.is_usable()
    logger.info(f"  {vname}: usable={usable}")
    
    if usable:
        fpath = write_variant_workbook(
            's9_baseline',
            block.machine,
            vdata,
            OUTPUT_DIR
        )
        logger.info(f"  Wrote {fpath}")

logger.info("="*60)
logger.info("Baseline run complete. Now comparing...")
logger.info("="*60)

# Compare
sys.path.insert(0, 'tools')
import compare_excel

ref_path = Path('source') / '1M SPP SM175 AUTO FUNCTION All CatID.xlsx'
gen_path = OUTPUT_DIR / 's9_baseline_MAG03D0424_v3.xlsx'

if not gen_path.exists():
    logger.error(f"Generated file not found: {gen_path}")
    logger.info(f"Files in {OUTPUT_DIR}:")
    for f in OUTPUT_DIR.glob('*.xlsx'):
        logger.info(f"  {f.name}")
    sys.exit(1)

logger.info(f"Reference: {ref_path}")
logger.info(f"Generated: {gen_path}")
logger.info(f"Variant: MAG03D0424")

compare_excel.compare(str(gen_path), str(ref_path), 'MAG03D0424')

logger.info("="*60)
logger.info("End of baseline run")
logger.info("="*60)
