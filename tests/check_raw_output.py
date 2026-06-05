"""Check raw Gemini response for MAG03D0424 with new prompt."""
import sys, os, time
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from services.pdf_extractor import extract_pages
from services.block_segmenter import segment_blocks
from services.vision_extractor import _classify_pages_for_variant, _extract_procedure, _normalize_specs
from services.types import Specs
import google.generativeai as genai
import logging
logging.basicConfig(level=logging.INFO)

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

pages = extract_pages(Path('source/WI.pdf'))
blocks = segment_blocks(pages)
block = [b for b in blocks if b.machine == 'MAG03D0424'][0]
cls = _classify_pages_for_variant(block, 'MAG03D0424')
proc_pages = cls['proc_pages']
print(f'Sending pages: {[p.num for p in proc_pages]}')

specs = Specs()
steps_raw = _extract_procedure(genai, block.machine, 'MAG03D0424', specs, proc_pages)
print(f'\nGot {len(steps_raw)} raw steps')
for i, s in enumerate(steps_raw[:10]):
    name = s.get("step_name", "?")
    vpn = s.get("voltages_pn", [])
    leds = s.get("leds", [])
    relay = s.get("relay_status")
    settings = s.get("settings", [])
    on_d = s.get("on_delay")
    off_d = s.get("off_delay")
    sb = s.get("section_break")
    print(f"  step {i+1}:")
    print(f"    name: {name}")
    print(f"    vpn: {vpn}")
    print(f"    leds: {leds}")
    print(f"    relay: {relay}")
    print(f"    settings: {settings}")
    print(f"    on_delay: {on_d}, off_delay: {off_d}, section_break: {sb}")
    print()
