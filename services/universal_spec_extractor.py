"""
Universal Spec Extractor
Handles ALL manufacturing WI PDF formats:
  Format A: TABLE inline  "Under Voltage (UV)...347 to 357 VAC"
  Format B: Procedure text "range of 220.8V to 225.6V"
  Format C: PCT inline    "85% (353 VAC) 343 TO 363 VAC"
"""
import re
import math
from typing import List, Dict, Tuple


def extract_specs(block: str) -> Dict:
    """
    Extract all voltage specs from a machine block.
    Tries multiple patterns — works regardless of PDF format.
    """
    s = {
        'ref_pn': 240.0,
        'uv': [], 'ov': [],
        'asy_pct': [], 'asy_v': [],
        'delay_on': (4.0, 6.0), 'delay_off': (4.0, 6.0),
        'phase_fail': False, 'phase_rev': False,
        'neutral': False, 'virtual_neutral': False,
        'lv': [], 'hv': []
    }

    # ── Reference voltage ──────────────────────────────────────────────
    for p in [
        r'SETTINGS\s+&\s+ACCEPTABLE\s+LIMITS\s*@\s*(\d+)\s*VAC',
        r'REF\.\s*VOLTAGE\s+(\d+)\s*VAC',
        r'at\s+(\d+)\s*VAC?\s*P-N',
        r'(\d+)\s*VAC\s*P-N',
        r'respect\s+to\s+Neutral\s+at\s+(\d+)V',
    ]:
        m = re.search(p, block[:4000], re.I)
        if m:
            v = float(m.group(1))
            if 100 <= v <= 500:
                s['ref_pn'] = v
                break

    # Compute Ph-Ph reference for UV/OV separation
    import math
    ref_pp = s['ref_pn'] * math.sqrt(3)  # Ph-N to Ph-Ph conversion

    # ── UV: context window after "Under Voltage" keyword ───────────────
    uv_found, seen_uv = [], set()
    for m in re.finditer(r'Under\s*[Vv]oltage', block):
        ctx = block[m.start():m.start() + 300]
        for a, b in re.findall(
            r'(\d{3,}(?:\.\d+)?)\s+(?:to|TO)\s+(\d{3,}(?:\.\d+)?)\s*(?:VAC|V)\b',
            ctx, re.I
        ):
            a, b = float(a), float(b)
            if a < b and a > 100 and round(a) not in seen_uv:
                uv_found.append((a, b))
                seen_uv.add(round(a))
    # UV fallback: procedure "range of X to Y V" with UV context
    if not uv_found:
        for m in re.finditer(
            r'range\s+of\s+(\d+(?:\.\d+)?)\s*V?\s+to\s+(\d+(?:\.\d+)?)\s*V',
            block, re.I
        ):
            ctx = block[max(0, m.start() - 200):m.start()].lower()
            a, b = float(m.group(1)), float(m.group(2))
            if (a > 50 and a < b and round(a) not in seen_uv and
                    any(k in ctx for k in [
                        'uv', 'under volt', 'reduce r phase',
                        'trip voltage', 'r ph and neutral'
                    ])):
                uv_found.append((a, b))
                seen_uv.add(round(a))
    s['uv'] = uv_found[:3]

    # UV Format C: PCT inline  "85% (353 VAC) 343 TO 363"
    # These appear in TABLE sections near Under Voltage rows
    for m in re.finditer(
        r'Under\s*[Vv]oltage[\s\S]{0,200}?'
        r'(\d+)\s*%\s*\(\s*(\d+)\s*VAC\s*\)\s*(\d+)\s+TO\s+(\d+)',
        block, re.I
    ):
        a, b = float(m.group(3)), float(m.group(4))
        if a < b and a > 100 and round(a) not in seen_uv:
            uv_found.append((a, b))
            seen_uv.add(round(a))
    s['uv'] = uv_found[:3]

    # ── OV: same two patterns ──────────────────────────────────────────
    ov_found, seen_ov = [], set()
    for m in re.finditer(r'Over\s*[Vv]oltage', block):
        ctx = block[m.start():m.start() + 300]
        for a, b in re.findall(
            r'(\d{3,}(?:\.\d+)?)\s+(?:to|TO)\s+(\d{3,}(?:\.\d+)?)\s*(?:VAC|V)\b',
            ctx, re.I
        ):
            a, b = float(a), float(b)
            if a < b and a > 200 and round(a) not in seen_ov:
                ov_found.append((a, b))
                seen_ov.add(round(a))
    if not ov_found:
        for m in re.finditer(
            r'range\s+of\s+(\d+(?:\.\d+)?)\s*V?\s+to\s+(\d+(?:\.\d+)?)\s*V',
            block, re.I
        ):
            ctx = block[max(0, m.start() - 200):m.start()].lower()
            a, b = float(m.group(1)), float(m.group(2))
            if (a > 200 and a < b and round(a) not in seen_ov and
                    any(k in ctx for k in [
                        'ov', 'over volt', 'yb or ry', 'br or yb'
                    ])):
                ov_found.append((a, b))
                seen_ov.add(round(a))
    s['ov'] = ov_found[:3]

    # OV Format C: PCT inline  "110% (456 VAC) 446 TO 466"
    for m in re.finditer(
        r'Over\s*[Vv]oltage[\s\S]{0,200}?'
        r'(\d+)\s*%\s*\(\s*(\d+)\s*VAC\s*\)\s*(\d+)\s+TO\s+(\d+)',
        block, re.I
    ):
        a, b = float(m.group(3)), float(m.group(4))
        if a < b and a > 200 and round(a) not in seen_ov:
            ov_found.append((a, b))
            seen_ov.add(round(a))
    s['ov'] = ov_found[:3]

    # ── Asymmetry % ────────────────────────────────────────────────────
    # Handles: "9 to 11 %", "9% to 11%", "range of 26% to 34%"
    for a, b in re.findall(
        r'(?:range\s+of\s+)?(\d+(?:\.\d+)?)\s*%?\s+(?:to|TO)\s+(\d+(?:\.\d+)?)\s*%',
        block, re.I
    ):
        a, b = float(a), float(b)
        if 1 < a < 50 and a < b:
            s['asy_pct'].append((a, b))
            break

    # Asymmetry voltage fallback: "90 to 98 VAC" near "Asymmetry"
    if not s['asy_pct']:
        for m in re.finditer(
            r'Asymmetry[^\n]{0,80}?(\d+)\s+(?:to|TO)\s+(\d+)\s+VAC',
            block, re.I | re.DOTALL
        ):
            a, b = float(m.group(1)), float(m.group(2))
            if a < b and a < 150:
                s['asy_v'].append((a, b))
                break

    # ── LV / HV cutoff ────────────────────────────────────────────────
    for m in re.finditer(
        r'range\s+of\s+(\d+(?:\.\d+)?)\s*V?\s+to\s+(\d+(?:\.\d+)?)\s*V',
        block, re.I
    ):
        ctx = block[max(0, m.start() - 250):m.start()].lower()
        a, b = float(m.group(1)), float(m.group(2))
        if a >= b or a < 50:
            continue
        if any(k in ctx for k in ['low voltage cut', 'symmetrically reduce']) and a < 300:
            s['lv'].append((a, b))
        elif any(k in ctx for k in ['high voltage cut', 'symmetrically increase']) and a > 300:
            s['hv'].append((a, b))

    # ── Delays ────────────────────────────────────────────────────────
    delays = []
    for a, b in re.findall(
        r'(\d+(?:\.\d+)?)\s*(?:–|-|to)\s*(\d+(?:\.\d+)?)\s*(?:sec|s)\b',
        block, re.I
    ):
        a, b = float(a), float(b)
        if 1 <= a <= b <= 60:
            delays.append((a, b))
    for v, u in re.findall(
        r'(\d+(?:\.\d+)?)\s*(min|sec)\s*\(\s*\+/?\-\s*\d+\)',
        block, re.I
    ):
        v = float(v) * (60 if u.lower() == 'min' else 1)
        if 1 <= v <= 120:
            delays.append((v, v))
    if delays:
        s['delay_on']  = delays[0]
        s['delay_off'] = delays[1] if len(delays) > 1 else delays[0]

    # ── Phase / neutral features ───────────────────────────────────────
    s['phase_fail'] = bool(re.search(
        r'PHASE\s+FAIL\s+(?:Enable|VERIFICATION)'
        r'|Make.*?phase.*?fail.*?[Tt]est\s*[Jj]ig',
        block
    ))
    s['phase_rev'] = bool(re.search(
        r'PHASE\s+REVERSE\s+(?:Enable|VERIFICATION|YES)'
        r'|[Rr]everse\s+one\s+of\s+the\s+phases'
        r'|ASY/REV\s+Phase\s+[Rr]everse'
        r'|Phase\s+Reverse\s+Continuous',
        block, re.DOTALL
    ))
    s['neutral'] = bool(re.search(
        r'NEUTRAL\s+FAIL\s+YES|NEUTRAL\s*OPEN|System\s*[Nn]eutral\s*[Ff]ail'
        r'|Neutral\s+fail.*?500\s*ms'
        r'|Neutral\s+fail\s+Enable'
        r'|NEUTRAL\s+FAIL\s+\d+V',
        block, re.DOTALL
    ))
    s['virtual_neutral'] = bool(re.search(
        r'VIRTUAL\s+NUT[RU]AL|Virtual\s*[Nn]eutral\s*[Ff]ail|VIRTUAL\s+NEUTRAL',
        block
    ))
    return s


def generate_conditions(spec: Dict) -> List[Dict]:
    """
    Generate multi-row test conditions from extracted specs.
    Returns list of condition dicts for excel_writer.py.
    """
    pn    = spec['ref_pn']
    d_on  = spec['delay_on']
    d_off = spec['delay_off']
    on_s  = (f'{d_on[0]:.0f}-{d_on[1]:.0f} sec'
             if d_on[0] != d_on[1] else f'{d_on[0]:.0f} sec')
    off_s = (f'{d_off[0]:.0f}-{d_off[1]:.0f} sec'
             if d_off[0] != d_off[1] else f'{d_off[0]:.0f} sec')
    yn    = f'YN : {pn:.0f}'
    bn    = f'BN : {pn:.0f}'
    led   = {
        'l1': 'PWR (GREEN LED) : ON', 'l2': 'UV (RED LED) : OFF',
        'l3': 'OV (RED LED) : OFF',   'l4': 'ASY (RED LED) : OFF'
    }

    conds = [{
        **led,
        'tc': 'healthy condition',
        'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': bn,
        'relay': 'ON', 'on_d': 'Instant ON', 'off_d': '-'
    }]

    # UV conditions (up to 2 sets)
    for i, (u0, u1) in enumerate(spec['uv'][:2]):
        sfx = f' (set {i + 1})' if i > 0 else ''
        h   = max(1, round((u1 - u0) * 0.4))
        conds += [
            {**led, 'tc': f'UV Healthy condition{sfx}',
             'v1': f'RN : {u1:g}', 'v2': yn, 'v3': bn,
             'relay': 'ON', 'on_d': 'Continuous ON', 'off_d': '-'},
            {**led, 'tc': f'UV faulty condition with delay{sfx}',
             'v1': f'RN : {u0:g}', 'v2': yn, 'v3': bn,
             'l2': 'UV (RED LED) : ON',
             'relay': f'OFF in {off_s}', 'on_d': '-', 'off_d': f'OFF in {off_s}'},
            {**led, 'tc': f'UV hysteresis not recovery{sfx}',
             'v1': f'RN : {u0 + h:g}', 'v2': yn, 'v3': bn,
             'l2': 'UV (RED LED) : ON',
             'relay': 'Continuous OFF', 'on_d': '-', 'off_d': 'Continuous OFF'},
            {**led, 'tc': f'UV hysteresis recovery{sfx}',
             'v1': f'RN : {u1:g}', 'v2': yn, 'v3': bn,
             'relay': 'ON', 'on_d': f'After {on_s}', 'off_d': '-'},
        ]

    # OV conditions (up to 2 sets)
    for i, (o0, o1) in enumerate(spec['ov'][:2]):
        sfx = f' (set {i + 1})' if i > 0 else ''
        h   = max(1, round((o1 - o0) * 0.4))
        conds += [
            {**led, 'tc': f'OV Healthy condition{sfx}',
             'v1': f'RN : {o0:g}', 'v2': yn, 'v3': bn,
             'relay': 'ON', 'on_d': 'Continuous ON', 'off_d': '-'},
            {**led, 'tc': f'OV faulty condition{sfx}',
             'v1': f'RN : {o1:g}', 'v2': yn, 'v3': bn,
             'l3': 'OV (RED LED) : ON',
             'relay': f'OFF in {off_s}', 'on_d': '-', 'off_d': f'OFF in {off_s}'},
            {**led, 'tc': f'OV hysteresis not recovery{sfx}',
             'v1': f'RN : {o1 - h:g}', 'v2': yn, 'v3': bn,
             'l3': 'OV (RED LED) : ON',
             'relay': 'Continuous OFF', 'on_d': '-', 'off_d': 'Continuous OFF'},
            {**led, 'tc': f'OV hysteresis recovery{sfx}',
             'v1': f'RN : {o0:g}', 'v2': yn, 'v3': bn,
             'relay': 'ON', 'on_d': f'After {on_s}', 'off_d': '-'},
        ]

    # Asymmetry % conditions
    for ap0, ap1 in spec['asy_pct'][:1]:
        av = round(pn * (1 - ap1 / 100))
        conds += [
            {**led, 'tc': 'Phase Asymmetry Healthy',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': bn,
             'relay': 'ON', 'on_d': 'Continuous ON', 'off_d': '-'},
            {**led, 'tc': 'Phase Asymmetry faulty',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': f'BN : {av}',
             'l4': 'ASY (RED LED) : BLINKING',
             'relay': f'OFF in {off_s}', 'on_d': '-', 'off_d': f'OFF in {off_s}'},
            {**led, 'tc': 'Phase Asymmetry not recovery',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': f'BN : {av + 2}',
             'l4': 'ASY (RED LED) : BLINKING',
             'relay': 'Continuous OFF', 'on_d': '-', 'off_d': 'Continuous OFF'},
            {**led, 'tc': 'Phase Asymmetry recovery',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': f'BN : {round(pn * 0.95)}',
             'relay': 'ON', 'on_d': f'After {on_s}', 'off_d': '-'},
        ]

    # Asymmetry voltage conditions
    for av0, av1 in spec['asy_v'][:1]:
        conds += [
            {**led, 'tc': 'Phase Asymmetry Healthy',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': bn,
             'relay': 'ON', 'on_d': 'Continuous ON', 'off_d': '-'},
            {**led, 'tc': 'Phase Asymmetry faulty',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': f'Diff : {av1:.0f} VAC',
             'l4': 'ASY (RED LED) : BLINKING',
             'relay': f'OFF in {off_s}', 'on_d': '-', 'off_d': f'OFF in {off_s}'},
            {**led, 'tc': 'Phase Asymmetry not recovery',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': f'Diff : {av1:.0f} VAC',
             'l4': 'ASY (RED LED) : BLINKING',
             'relay': 'Continuous OFF', 'on_d': '-', 'off_d': 'Continuous OFF'},
            {**led, 'tc': 'Phase Asymmetry recovery',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': bn,
             'relay': 'ON', 'on_d': f'After {on_s}', 'off_d': '-'},
        ]

    # Phase fail
    if spec['phase_fail']:
        on_str_pf = f'ON after {on_s}' if d_on[0] >= 1 else 'Instant ON'
        conds += [
            {'tc': 'Phase fail',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': 'BN : 0',
             'l1': 'PWR : BLINKING', 'l2': 'UV (RED LED) : ON',
             'l3': 'OV (RED LED) : OFF', 'l4': 'ASY : BLINKING',
             'relay': 'Instant OFF', 'on_d': '-', 'off_d': 'Instant OFF'},
            {**led, 'tc': 'Phase recovery',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': bn,
             'relay': on_str_pf, 'on_d': on_str_pf, 'off_d': '-'},
        ]

    # Phase reverse
    if spec['phase_rev']:
        conds += [
            {**led, 'tc': 'Phase reverse',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': bn,
             'l4': 'ASY (RED LED) : ON',
             'relay': 'Instant OFF', 'on_d': '-', 'off_d': 'Instant OFF'},
            {**led, 'tc': 'Phase reverse recovery',
             'v1': f'RN : {pn:.0f}', 'v2': yn, 'v3': bn,
             'relay': 'Instant ON', 'on_d': 'Instant ON', 'off_d': '-'},
        ]

    # Neutral
    if spec['neutral']:
        conds.append({
            **led, 'tc': 'System neutral fail',
            'v1': 'Neutral open', 'v2': '', 'v3': '',
            'relay': 'OFF in 500 ms', 'on_d': '-', 'off_d': 'OFF in 500 ms'
        })
    if spec['virtual_neutral']:
        conds.append({
            **led, 'tc': 'Virtual neutral fail',
            'v1': '8 to 14 V', 'v2': '', 'v3': '',
            'relay': 'OFF in 500 ms', 'on_d': '-', 'off_d': 'OFF in 500 ms'
        })

    # LV cutoff (Ph-Ph values → convert to Ph-N, repeated twice per standard)
    for lv0, lv1 in spec['lv'][:1]:
        lp  = round(lv1 / math.sqrt(3))
        lm  = round(lv0 / math.sqrt(3))
        lrc = lp + 10
        for _ in range(2):
            conds += [
                {'tc': 'Lower Cut OFF healthy',
                 'v1': f'RN : {lp}', 'v2': f'YN : {lp}', 'v3': f'BN : {lp}',
                 'l1': 'R (RED LED) : ON', 'l2': '', 'l3': '', 'l4': '',
                 'relay': 'ON', 'on_d': 'Instant ON', 'off_d': '-'},
                {'tc': 'Lower Cut OFF',
                 'v1': f'RN : {lm}', 'v2': f'YN : {lm}', 'v3': f'BN : {lm}',
                 'l1': 'R (RED LED) : OFF', 'l2': '', 'l3': '', 'l4': '',
                 'relay': 'OFF', 'on_d': '-', 'off_d': 'Instant OFF'},
                {'tc': 'Lower Cut OFF not recovery',
                 'v1': f'RN : {lp}', 'v2': f'YN : {lp}', 'v3': f'BN : {lp}',
                 'l1': 'R (RED LED) : OFF', 'l2': '', 'l3': '', 'l4': '',
                 'relay': 'OFF', 'on_d': '-', 'off_d': 'Continuous OFF'},
                {'tc': 'Lower Cut OFF recovery',
                 'v1': f'RN : {lrc}', 'v2': f'YN : {lrc}', 'v3': f'BN : {lrc}',
                 'l1': 'R (RED LED) : ON', 'l2': '', 'l3': '', 'l4': '',
                 'relay': 'ON', 'on_d': 'Instant ON', 'off_d': '-'},
            ]

    # HV cutoff
    for hv0, hv1 in spec['hv'][:1]:
        conds += [
            {'tc': 'Higher Cut OFF healthy',
             'v1': f'RN : {round(hv0/math.sqrt(3))}',
             'v2': f'YN : {round(hv0/math.sqrt(3))}',
             'v3': f'BN : {round(hv0/math.sqrt(3))}',
             'l1': 'R (RED LED) : ON', 'l2': '', 'l3': '', 'l4': '',
             'relay': 'ON', 'on_d': 'Instant ON', 'off_d': '-'},
            {'tc': 'Higher Cut OFF',
             'v1': f'RN : {round(hv1/math.sqrt(3))}',
             'v2': f'YN : {round(hv1/math.sqrt(3))}',
             'v3': f'BN : {round(hv1/math.sqrt(3))}',
             'l1': 'R (RED LED) : OFF', 'l2': '', 'l3': '', 'l4': '',
             'relay': 'OFF', 'on_d': '-', 'off_d': 'Instant OFF'},
        ]

    # Supply OFF always last
    conds.append({
        'tc': 'Supply OFF',
        'v1': 'All phases : 0', 'v2': '', 'v3': '',
        'l1': 'All LEDs : OFF', 'l2': '', 'l3': '', 'l4': '',
        'relay': 'OFF', 'on_d': '-', 'off_d': '-'
    })
    return conds


def extract_and_generate(machine_block: str) -> List[Dict]:
    """One-call entry point: extract specs then generate conditions."""
    return generate_conditions(extract_specs(machine_block))
