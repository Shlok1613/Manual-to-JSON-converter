"""Test single machine extraction — MAG03D0424 only (API quota conservation)."""
import sys, time, logging
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from services.pdf_extractor import extract_pages
from services.block_segmenter import segment_blocks
from services.vision_extractor import extract_machine_data
from services.enricher import enrich_variant
from services.normalizer import normalize_variant
from services.spec_linker import link_specs_to_steps
from services.validator import validate_variants
from services.template_writer import write_variant_workbook, write_consolidated_workbook

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path('outputs/test_v5')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# WI.pdf - MAG03D0424 only
pages = extract_pages(Path('source/WI.pdf'))
blocks = segment_blocks(pages)
block = [b for b in blocks if b.machine == 'MAG03D0424'][0]

print(f'\n--- {block.machine} ---')
variants = extract_machine_data(block=block, sub_machines=['MAG03D0424'])
time.sleep(5)

if not variants:
    print('  No variants extracted')
    sys.exit(1)

for vname, vdata in variants.items():
    vdata = enrich_variant(vdata, block.text)
    vdata = normalize_variant(vdata)
    variants[vname] = vdata

variants = link_specs_to_steps(variants)
variants = validate_variants(variants)

for vname, vdata in variants.items():
    usable = vdata.is_usable()
    print(f'  {vname}: steps={len(vdata.test_steps)}, usable={usable}')
    # Print first 3 step names to verify content
    for i, step in enumerate(vdata.test_steps[:5]):
        print(f'    step {i+1}: "{step.step_name}" voltages={step.voltages_pn} leds={step.leds[:2]}')
    if usable:
        f = write_variant_workbook('v5test', block.machine, vdata, OUTPUT_DIR)
        print(f'    wrote {f}')

print('\nDONE')
