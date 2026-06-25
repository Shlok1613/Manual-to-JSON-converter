from typing import Dict
from services.types import VariantData
from services.delay_utils import is_spurious_delay_hallucination


def link_specs_to_steps(variants: Dict[str, VariantData]) -> Dict[str, VariantData]:
    """
    Ensure each step inherits correct spec context.
    Prevent cross-variant leakage.

    Only sets fields that actually exist on the TestStep dataclass:
    on_delay, off_delay.

    Previously set phantom fields (uv_range, ov_range, ref_voltage)
    that don't exist on TestStep — removed to avoid AttributeError risk.
    """

    for vname, vdata in variants.items():
        specs = vdata.specs

        if not specs:
            continue

        for step in vdata.test_steps:
            # Timing backfill from specs (these fields exist on TestStep)
            if not step.on_delay and specs.on_delay:
                if not is_spurious_delay_hallucination(specs.on_delay):
                    step.on_delay = specs.on_delay

            if not step.off_delay and specs.off_delay:
                if not is_spurious_delay_hallucination(specs.off_delay):
                    step.off_delay = specs.off_delay

    return variants