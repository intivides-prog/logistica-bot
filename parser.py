"""
Parser de lenguaje natural para pedidos de planilla.
Ejemplos que entiende:
  "hace una planilla para kayak mascardi para 4 pax"
  "plani kayak mascardi 3 pax el 14/4, guia julian"
  "kayak mascardi 5 pax 15/3, guia rodri, 2 vegetarianos"
  "fd kayak tres reyes 6 pax 20/4 julian donatelli"
"""

import re
from datetime import date, datetime

SITES = {
    'mascardi':     'Lago Mascardi',
    'tres reyes':   'Tres Reyes',
    'nahuel':       'Lago Nahuel Huapi',
    'llao':         'Llao Llao',
    'pampa linda':  'Pampa Linda',
    'colonia suiza':'Colonia Suiza',
    'traful':       'Lago Traful',
    'espejo':       'Lago Espejo',
}

MONTHS_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12
}

DIET_PATTERNS = [
    (r'(\d+)\s*vegetarian[oa]s?',  lambda m: f"{m.group(1)}x vegetariano/a"),
    (r'un[ao]\s+vegetarian[oa]',   lambda m: "1x vegetariano/a"),
    (r'(\d+)\s*vegan[oa]s?',       lambda m: f"{m.group(1)}x vegano/a"),
    (r'un[ao]\s+vegan[oa]',        lambda m: "1x vegano/a"),
    (r'(\d+)\s*celi[aá]c[oa]s?',   lambda m: f"{m.group(1)}x celíaco/a"),
    (r'un[ao]\s+celi[aá]c[oa]',    lambda m: "1x celíaco/a"),
    (r'(\d+)\s*sin\s+gluten',      lambda m: f"{m.group(1)}x sin gluten"),
    (r'sin\s+gluten',              lambda m: "1x sin gluten"),
    (r'(\d+)\s*sin\s+lactosa',     lambda m: f"{m.group(1)}x sin lactosa"),
    (r'sin\s+lactosa',             lambda m: "1x sin lactosa"),
    (r'(\d+)\s*alérgic[oa]s?',     lambda m: f"{m.group(1)}x alergia"),
    (r'un[ao]\s+alérgic[oa]',      lambda m: "1x alergia"),
]


def parse_message(text: str) -> dict:
    t = text.lower().strip()
    result = {}

    # ── Actividad ────────────────────────────────────────────────────────────
    if ('kayak' in t and 'trekking' in t) or 'kayak y trek' in t:
        result['activity'] = 'FD Kayak y Trekking'
    elif 'kayak' in t:
        result['activity'] = 'FD Kayak'
    elif 'mtb' in t or 'mountain bike' in t or 'bici' in t:
        result['activity'] = 'MTB'
    elif 'trekking' in t or 'trek' in t:
        result['activity'] = 'Trekking'
    elif 'navegac' in t or 'barco' in t:
        result['activity'] = 'Navegación'
    else:
        result['activity'] = None

    # ── Modalidad FD / HD (para gastronomía) ─────────────────────────────────
    if 'hd' in t or 'half day' in t or 'medio d' in t:
        result['gastronomy_type'] = 'snacks'
    else:
        result['gastronomy_type'] = 'AC'   # default full day = almuerzo campestre

    # ── Sitio ─────────────────────────────────────────────────────────────────
    result['site'] = None
    for key, val in SITES.items():
        if key in t:
            result['site'] = val
            break

    # ── Cantidad de pax ───────────────────────────────────────────────────────
    pax_m = re.search(r'(\d+)\s*pax', t)
    if pax_m:
        result['pax'] = int(pax_m.group(1))
    else:
        # "para 4" / "de 4" sin la palabra pax
        pax_m2 = re.search(r'(?:para|de)\s+(\d+)(?!\s*/)', t)
        result['pax'] = int(pax_m2.group(1)) if pax_m2 else None

    # ── Fecha ─────────────────────────────────────────────────────────────────
    result['date'] = None
    # D/M o D/M/YYYY
    dm = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b', text)
    if dm:
        day, month = int(dm.group(1)), int(dm.group(2))
        year = int(dm.group(3)) if dm.group(3) else (
            datetime.now().year if month >= datetime.now().month else datetime.now().year + 1
        )
        try:
            result['date'] = date(year, month, day)
        except ValueError:
            pass
    else:
        # "el 14 de abril"
        de_mes = re.search(r'\b(\d{1,2})\s+de\s+([a-záéíóú]+)', t)
        if de_mes:
            day = int(de_mes.group(1))
            month = MONTHS_ES.get(de_mes.group(2))
            if month:
                year = datetime.now().year
                try:
                    result['date'] = date(year, month, day)
                except ValueError:
                    pass

    # ── Guía ─────────────────────────────────────────────────────────────────
    result['guide'] = None
    guide_m = re.search(
        r'gu[ií]a(?:\s+(?:es|va\s+a\s+ser|ser[aá]|:))?\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)',
        text, re.IGNORECASE
    )
    if guide_m:
        result['guide'] = guide_m.group(1).title()

    # ── Hora ─────────────────────────────────────────────────────────────────
    result['hora'] = None
    hora_m = re.search(r'\b(\d{1,2})[:.h](\d{2})?\s*hs?\b', t)
    if hora_m:
        h = hora_m.group(1)
        m2 = hora_m.group(2) or '00'
        result['hora'] = f"{h}:{m2} hs"

    # ── Restricciones alimentarias ────────────────────────────────────────────
    restrictions = []
    for pattern, formatter in DIET_PATTERNS:
        m = re.search(pattern, t)
        if m:
            restrictions.append(formatter(m))
    result['dietary_restrictions'] = ', '.join(restrictions) if restrictions else None

    return result


def format_missing(parsed: dict) -> list[str]:
    """Devuelve lista de campos faltantes para pedir al usuario."""
    missing = []
    if not parsed.get('activity'): missing.append('actividad (kayak, MTB, trekking, etc.)')
    if not parsed.get('pax'):      missing.append('cantidad de pax')
    if not parsed.get('date'):     missing.append('fecha (ej: 14/4)')
    return missing
