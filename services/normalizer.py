import re

from .types import VariantData

# Default LED set for full machines (Layout A).
# Will be overridden by actual led_indications from specs when available.
_DEFAULT_EXPECTED_LEDS = ["PWR", "UV", "OV", "ASY"]


def _derive_expected_leds(vd: VariantData) -> list:
    """
    Derive which LEDs are expected for this machine from its specs.led_indications.
    If led_indications is populated, use its keys to determine which LED labels
    should appear. Otherwise fall back to the default 4-LED set.
    """
    indications = vd.specs.led_indications
    if not indications:
        return list(_DEFAULT_EXPECTED_LEDS)

    # Inspect the led_indications keys/values for known LED tokens
    combined = " ".join(list(indications.keys()) + list(indications.values())).upper()

    # If only simple "R" or "RED" LED mentioned (Layout B machines), expect only that
    has_pwr = "PWR" in combined or "POWER" in combined or "GREEN" in combined
    has_uv = "UV" in combined
    has_ov = "OV" in combined
    has_asy = "ASY" in combined or "ASYMMETRY" in combined

    expected = []
    if has_pwr:
        expected.append("PWR")
    if has_uv:
        expected.append("UV")
    if has_ov:
        expected.append("OV")
    if has_asy:
        expected.append("ASY")

    # If we couldn't determine anything specific, check for single-LED machines
    if not expected:
        # Single-LED machine (e.g., only "R LED" or "Red LED")
        if "R " in combined or "RED" in combined:
            expected.append("R")
        else:
            # Truly unknown — fall back to defaults
            return list(_DEFAULT_EXPECTED_LEDS)

    return expected


def normalize_variant(vd: VariantData) -> VariantData:
    expected_leds = _derive_expected_leds(vd)

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
        # Only flag LEDs that are expected for THIS machine type.
        for key in expected_leds:
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