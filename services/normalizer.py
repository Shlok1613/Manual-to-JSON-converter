from .types import VariantData

EXPECTED_LEDS = ["PWR", "UV", "OV", "ASY"]

def normalize_variant(vd: VariantData) -> VariantData:
    for step in vd.test_steps:

        cleaned = []
        for v in step.voltages_pn:
            if any(c.isdigit() for c in v):
                cleaned.append(v)
            else:
                step.flags.append(f"invalid voltage entry: {v}")

        step.voltages_pn = cleaned

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
            if found:
                fixed.append(found)
            else:
                step.flags.append(f"{key} LED missing")
        step.leds = fixed

        # ---- Delay: enforce non-averaged ----
        if step.on_delay:
            val = step.on_delay.lower()

            if (
                "-" not in val
                and "to" not in val
                and not any(x in val for x in ["sec", "ms", "min", "instant", "continuous"])
            ):
                step.flags.append("on_delay format suspicious")

    return vd