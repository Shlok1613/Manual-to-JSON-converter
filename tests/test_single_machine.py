"""Test single machine extraction for one WI.pdf variant (API quota conservation)."""
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
from services.template_writer import write_variant_workbook, detect_layout

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

VARIANT = sys.argv[1] if len(sys.argv) > 1 else 'MAG03D0424'
OUTPUT_DIR = Path('outputs')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

pages = extract_pages(Path('source/WI.pdf'))
blocks = segment_blocks(pages)
base_machine = VARIANT.split('EG')[0]
matches = [b for b in blocks if b.machine == base_machine]
if not matches:
    print(f'ERROR: no block for {base_machine}')
    sys.exit(1)
block = matches[0]

print(f'\n--- {VARIANT} (block={block.machine}) ---')
variants = extract_machine_data(block=block, sub_machines=[VARIANT])
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
    layout = detect_layout(vdata.specs, test_steps=vdata.test_steps)
    layout_name = 'A' if layout['has_dip_block'] else 'B'
    print(f'  {vname}: steps={len(vdata.test_steps)}, layout={layout_name}, usable={usable}')
    for i, step in enumerate(vdata.test_steps[:5]):
        print(f'    step {i+1}: "{step.step_name}" voltages={step.voltages_pn} leds={step.leds[:2]}')
    if usable:
        tmp_dir = OUTPUT_DIR / '_tmp'
        f = write_variant_workbook('run', block.machine, vdata, tmp_dir)
        src = tmp_dir / f
        dst = OUTPUT_DIR / f'{VARIANT}.xlsx'
        dst.write_bytes(src.read_bytes())
        print(f'    wrote {dst}')

print('\nDONE')
