from services.block_segmenter import segment_blocks
from services.spec_parser import parse_specifications
from services.step_extractor import extract_steps
from services.table_extractor import extract_tables


SAMPLE_TEXT = """
PROCESS: Functional Testing - Neutral Open SPPR
CRITICALITY: HIGH
Reference Voltage: 415 VAC
TABLE 2 (PRODUCT SETTINGS @ 415 VAC):
Under Voltage: 85.00%, 347 to 357 VAC
Over Voltage: 110.00%, 453 to 459 VAC
ON Delay: 5s, 4 to 6s
OFF Delay: 5s, 4 to 6s
UV VERIFICATION:
8. Reduce R-Phase voltage till UV LED glows ON.
9. Ensure Relay turns OFF after 4 to 6s at 347 to 357 VAC.
"""


def test_segment_blocks_detects_process():
    blocks = segment_blocks(SAMPLE_TEXT)
    assert len(blocks) >= 1
    assert "SPPR" in blocks[0]["machine"]


def test_extract_tables_detects_table_rows():
    tables = extract_tables(SAMPLE_TEXT)
    assert len(tables) == 1
    assert any("Under Voltage" in str(r["parameter"]) for r in tables[0]["rows"])


def test_parse_specifications_extracts_ranges():
    specs = parse_specifications(SAMPLE_TEXT)
    uv = specs["voltage_parameters"].get("under_voltage")
    assert specs["reference_voltage"] == "415 VAC"
    assert uv is not None
    assert "347" in (uv.get("range") or uv.get("raw") or "")


def test_extract_steps_fields():
    steps = extract_steps(SAMPLE_TEXT)
    assert len(steps) == 2
    assert steps[0]["led"] == "UV ON"
    assert steps[1]["relay"] == "OFF"
