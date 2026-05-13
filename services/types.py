# services/types.py
"""Shared dataclasses. One source of truth — every module imports from here."""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Page:
    num: int
    ocr_text: str
    jpeg_bytes: Optional[bytes] = None
    width: int = 0
    height: int = 0


@dataclass
class Block:
    machine: str
    text: str
    page_range: List[int] = field(default_factory=list)
    pages: List[Page] = field(default_factory=list)
    header: str = ""
    is_scope_block: bool = False


@dataclass
class Specs:
    ref_voltage: Optional[str] = None
    uv_range: Optional[str] = None
    uv_threshold_pct: Optional[str] = None
    ov_range: Optional[str] = None
    ov_threshold_pct: Optional[str] = None
    uv_hysteresis: Optional[str] = None
    ov_hysteresis: Optional[str] = None
    asymmetry: Optional[str] = None
    on_delay: Optional[str] = None
    off_delay: Optional[str] = None
    phase_fail: Optional[str] = None
    phase_reverse: Optional[str] = None
    neutral_fail: Optional[str] = None
    virtual_neutral: Optional[str] = None
    lv_cutoff: Optional[str] = None
    hv_cutoff: Optional[str] = None
    voltage_unit: Optional[str] = None
    led_indications: Dict[str, str] = field(default_factory=dict)
    dip_switches: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    flags: List[str] = field(default_factory=list)


@dataclass
class TestStep:
    step_name: str
    settings: List[str] = field(default_factory=list)
    voltages_pn: List[str] = field(default_factory=list)
    voltage_pp: Optional[str] = None
    leds: List[str] = field(default_factory=list)
    relay_status: Optional[str] = None
    on_delay: Optional[str] = None
    off_delay: Optional[str] = None
    section_break: bool = False
    flags: List[str] = field(default_factory=list)


@dataclass
class VariantData:
    name: str
    specs: Specs = field(default_factory=Specs)
    test_steps: List[TestStep] = field(default_factory=list)
    audit: Dict = field(default_factory=dict)
    raw_specs: Dict = field(default_factory=dict)

    def is_usable(self) -> bool:
        has_anchor = bool(
            self.specs.ref_voltage
            or (self.specs.uv_range and self.specs.ov_range)
            or self.specs.lv_cutoff
        )
        has_steps = len(self.test_steps) >= 1
        return has_anchor and has_steps