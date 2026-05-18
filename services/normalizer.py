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

        # ---- Voltages: preserve extracted values ----
        # do not invent synthetic voltages
        if len(step.voltages_pn) == 0:
            step.flags.append("missing voltages")
        elif len(step.voltages_pn) < 3:
            step.flags.append(
                f"incomplete voltages extracted ({len(step.voltages_pn)}/3)"
            )

        # ---- LEDs: flag missing standard labels but preserve all extracted entries ----
        # Do NOT overwrite step.leds — only add quality flags.
        # This preserves non-standard LED labels (e.g., "R (RED LED)" for simpler machines).
        for key in EXPECTED_LEDS:
            found = next((l for l in step.leds if key in l.upper()), None)
            if not found:
                step.flags.append(f"{key} LED missing")
        # step.leds is intentionally left unchanged

        # ---- Delay validation ----
        for delay_name in ["on_delay", "off_delay"]:
            delay_value = getattr(step, delay_name, None)

            if delay_value:
                val = delay_value.lower().strip()

        # normalize OCR-collapsed spacing:
        # "10.5s" -> valid
        # "7 sec" -> valid
            has_unit = any(
                x in val
                for x in [
                    "sec",
                    "secs",
                    "second",
                    "seconds",
                "ms",
                "millisecond",
                "min",
                "minute",
                "instant",
                "continuous",
                "s"
            ]
            )

            has_range = (
                "-" in val
                or "to" in val
            )

            if not has_unit:
                step.flags.append(
                    f"{delay_name} missing time unit: '{delay_value}'"
                )

            elif not has_range and not any(
                c.isdigit() for c in val
            ):
                step.flags.append(
                    f"{delay_name} format suspicious"
                )

    return vd