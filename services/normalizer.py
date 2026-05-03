from .types import VariantData

EXPECTED_LEDS = ["PWR", "UV", "OV", "ASY"]

def normalize_variant(vd: VariantData) -> VariantData:
    for step in vd.test_steps:

        step.voltages_pn = [
            v for v in step.voltages_pn
            if any(c.isdigit() for c in v)
        ]

        # ---- Voltages: force exactly 3 ----
        if len(step.voltages_pn) == 1:
            step.voltages_pn *= 3
        elif len(step.voltages_pn) == 2:
            step.voltages_pn.append(step.voltages_pn[-1])
        elif len(step.voltages_pn) == 0:
            step.flags.append("missing voltages")

        # ---- LEDs: force 4 fixed labels ----
        fixed = []
        for key in EXPECTED_LEDS:
            found = next((l for l in step.leds if key in l.upper()), None)
            fixed.append(found if found else f"{key}: UNKNOWN")
        step.leds = fixed

        # ---- Delay: enforce non-averaged ----
        if step.on_delay and "-" not in step.on_delay.lower() and "to" not in step.on_delay.lower():
            step.flags.append("on_delay likely averaged — verify")

    return vd