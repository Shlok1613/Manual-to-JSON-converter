from typing import Dict
from services.types import VariantData


def link_specs_to_steps(variants: Dict[str, VariantData]) -> Dict[str, VariantData]:
    """
    Ensure each step inherits correct spec context.
    Prevent cross-variant leakage.
    """

    for vname, vdata in variants.items():
        specs = vdata.specs

        if not specs:
            continue

        for step in vdata.test_steps:
            # Attach reference values if missing or inconsistent

            # UV Range
            if not getattr(step, "uv_range", None) and specs.uv_range:
                step.uv_range = specs.uv_range

            # OV Range
            if not getattr(step, "ov_range", None) and specs.ov_range:
                step.ov_range = specs.ov_range

            # Ref Voltage
            if not getattr(step, "ref_voltage", None) and specs.ref_voltage:
                step.ref_voltage = specs.ref_voltage

            # Timing
            if not getattr(step, "on_delay", None) and specs.on_delay:
                step.on_delay = specs.on_delay

            if not getattr(step, "off_delay", None) and specs.off_delay:
                step.off_delay = specs.off_delay

    return variants