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
    # La segunda palabra NO puede ser una palabra clave (hotel, pax, hay, etc.)
    result['guide'] = None
    guide_m = re.search(
        r'gu[ií]a(?:\s+(?:es|va\s+a\s+ser|ser[aá]|:))?\s+'
        r'([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+'
        r'(?:\s+(?!(?:hotel|pax|hay|con|para|el|la|los|las|de|del|en|al)\b)[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)',
        text, re.IGNORECASE
    )
    if guide_m:
        result['guide'] = guide_m.group(1).strip().title()

    # ── Hora ─────────────────────────────────────────────────────────────────
    result['hora'] = None
    hora_m = re.search(r'\b(\d{1,2})[:.h](\d{2})?\s*hs?\b', t)
    if hora_m:
        h = hora_m.group(1)
        m2 = hora_m.group(2) or '00'
        result['hora'] = f"{h}:{m2} hs"

    # ── Hotel ─────────────────────────────────────────────────────────────────
    result['hotel'] = None
    hotel_m = re.search(
        r'hotel\s+(?:es\s+)?([A-Za-záéíóúüñÁÉÍÓÚÜÑ][A-Za-záéíóúüñÁÉÍÓÚÜÑ\s]{2,30}?)(?:\s*$|,|\s+\d|\s+el\s|\s+la\s|\s+para\s|\s+pax|\s+guia)',
        text, re.IGNORECASE
    )
    if hotel_m:
        result['hotel'] = hotel_m.group(1).strip().title()

    # ── Restricciones alimentarias ────────────────────────────────────────────
    restrictions = []
    for pattern, formatter in DIET_PATTERNS:
        m = re.search(pattern, t)
        if m:
            restrictions.append(formatter(m))
    result['dietary_restrictions'] = ', '.join(restrictions) if restrictions else None

    return result


def parse_update(text: str) -> dict | None:
    """
    Detecta si el mensaje es una actualización de excursión existente.
    Devuelve dict con: action, date, identifier, identifier_type, new_value
    O None si no parece una actualización.
    """
    t = text.lower().strip()

    VERBS = r'(?:cambia[r]?|modifica[r]?|actualiza[r]?|correg[ií][r]?|ponele?|pone[r]?|mov[eé][r]?|actualiz[ao])'

    # Detectar acción
    action = None
    if re.search(r'cancel[ao]|no\s+va|se\s+cancela|suspende', t):
        action = 'cancel'
    elif re.search(rf'{VERBS}\s+(?:el\s+|la\s+)?(?:hora|horario)|nueva\s+hora|cambi[oó]\s+(?:la\s+)?hora', t):
        action = 'update_hora'
    elif re.search(rf'{VERBS}\s+(?:el\s+)?(?:gu[ií]a|guia)|nuevo\s+gu[ií]a|cambi[oó]\s+(?:el\s+)?gu[ií]a', t):
        action = 'update_guide'
    elif re.search(rf'{VERBS}\s+(?:el\s+)?(?:d[ií]a|fecha)|nueva\s+fecha|cambi[oó]\s+(?:la\s+)?fecha|mov[eé]la?\s+al?', t):
        action = 'update_date'
    elif re.search(rf'{VERBS}\s+(?:el\s+)?(?:lugar|sitio|locaci[oó]n)|nueva\s+(?:lugar|sitio)|cambi[oó]\s+(?:el\s+)?(?:lugar|sitio)', t):
        action = 'update_site'
    elif re.search(rf'{VERBS}\s+(?:los?\s+)?(?:pax|pasajeros?|cantidad)|son\s+\d+\s+pax\s+ahora|ahora\s+son\s+\d+', t):
        action = 'update_pax'
    elif re.search(rf'{VERBS}\s+(?:el\s+)?hotel|agrega[r]?\s+(?:el\s+)?hotel|nuevo\s+hotel', t):
        action = 'update_hotel'
    elif re.search(r'reenv[ií]a[r]?|manda[r]?\s+(?:de\s+)?nuevo|volver\s+a\s+mandar|pasame\s+(?:de\s+nuevo\s+)?(?:la\s+)?plan[i]?|devolv[eé][r]?\s+(?:la\s+)?plan[i]?', t) and re.search(r'plan[i]?|excel', t):
        action = 'resend_planilla'
    elif re.search(rf'reenv[ií]a[r]?|mand[aá][r]?\s+de\s+nuevo|pas[aá]me\s+(?:la\s+)?plan', t):
        action = 'resend_planilla'
    elif re.search(r'agrega[r]?|añadi[r]?|suma[r]?|hay\s+un[ao]?|tiene[n]?\s+un[ao]?', t) and re.search(
            r'restrict|vegetar|vegan|celi[aá]c|gluten|lactosa|alérgic', t):
        action = 'update_restrictions'

    if not action:
        return None

    result = {
        'action': action,
        'date': None,
        'identifier': None,
        'identifier_type': None,
        'new_value': None,
    }

    # Extraer fecha(s) — la primera es la excursión a modificar
    all_dates = list(re.finditer(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b', text))
    if not all_dates:
        # Intentar "D de mes"
        de_mes = re.search(r'\b(\d{1,2})\s+de\s+([a-záéíóú]+)', t)
        if de_mes:
            day_t = int(de_mes.group(1))
            month_t = MONTHS_ES.get(de_mes.group(2))
            if month_t:
                try:
                    result['date'] = date(datetime.now().year, month_t, day_t)
                except ValueError:
                    pass
        if not result.get('date'):
            return None
    dm = all_dates[0]
    day, month = int(dm.group(1)), int(dm.group(2))
    year = int(dm.group(3)) if dm.group(3) else (
        datetime.now().year if month >= datetime.now().month else datetime.now().year + 1
    )
    try:
        result['date'] = date(year, month, day)
    except ValueError:
        return None

    STOP_WORDS = {'el', 'la', 'los', 'las', 'en', 'al', 'del', 'un', 'una', 'de', 'para', 'con'}

    # Identificador — guía o cliente
    guide_m = re.search(
        r'gu[ií]a\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)',
        text, re.IGNORECASE
    )
    if guide_m:
        # Filtrar stop words del final
        words = guide_m.group(1).strip().split()
        words = [w for i, w in enumerate(words) if i == 0 or w.lower() not in STOP_WORDS]
        result['identifier'] = ' '.join(words).title()
        result['identifier_type'] = 'guide'
    else:
        # Busca "de [Nombre]" — solo una palabra para evitar capturar "de Lark el 20/6"
        client_m = re.search(r'\bde\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]{3,})', text, re.IGNORECASE)
        if client_m:
            word = client_m.group(1)
            if word.lower() not in STOP_WORDS:
                result['identifier'] = word.title()
                result['identifier_type'] = 'client'

    # Extraer nuevo valor según acción
    if action == 'update_hora':
        hora_m = re.search(r'(?:a\s+las?\s+)?(\d{1,2})(?:[:.h](\d{2}))?\s*(?:hs?|am|pm)\b', t)
        if hora_m:
            h = int(hora_m.group(1))
            m2 = hora_m.group(2) or '00'
            if 'pm' in t and h < 12:
                h += 12
            result['new_value'] = f"{h}:{m2} hs"

    elif action == 'update_guide':
        new_m = re.search(
            r'(?:a|por|es|ser[aá])\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)(?:\s*$)',
            text, re.IGNORECASE
        )
        if new_m:
            result['new_value'] = new_m.group(1).strip().title()

    elif action == 'update_date':
        if len(all_dates) >= 2:
            dm2 = all_dates[1]
            day2, month2 = int(dm2.group(1)), int(dm2.group(2))
            year2 = int(dm2.group(3)) if dm2.group(3) else (
                datetime.now().year if month2 >= datetime.now().month else datetime.now().year + 1
            )
            try:
                result['new_value'] = date(year2, month2, day2)
            except ValueError:
                pass

    elif action == 'update_site':
        for key, val in SITES.items():
            if key in t:
                result['new_value'] = val
                break

    elif action == 'update_pax':
        pax_m = re.search(r'(\d+)\s*pax', t) or re.search(r'son\s+(\d+)|ahora\s+son\s+(\d+)', t)
        if pax_m:
            result['new_value'] = int(next(g for g in pax_m.groups() if g))

    elif action == 'update_hotel':
        # "agrega el hotel Llao Llao" / "el hotel es Panamericano"
        hotel_m = re.search(r'hotel\s+(?:es\s+)?([A-Za-záéíóúüñÁÉÍÓÚÜÑ][A-Za-záéíóúüñÁÉÍÓÚÜÑ\s]+?)(?:\s*$|\s+en\s|\s+el\s|\s+\d)', text, re.IGNORECASE)
        if hotel_m:
            result['new_value'] = hotel_m.group(1).strip().title()

    elif action == 'update_restrictions':
        restrictions = []
        for pattern, formatter in DIET_PATTERNS:
            m = re.search(pattern, t)
            if m:
                restrictions.append(formatter(m))
        result['new_value'] = ', '.join(restrictions) if restrictions else None

    return result


def format_missing(parsed: dict) -> list[str]:
    """Devuelve lista de campos faltantes para pedir al usuario."""
    missing = []
    if not parsed.get('activity'): missing.append('actividad (kayak, MTB, trekking, etc.)')
    if not parsed.get('pax'):      missing.append('cantidad de pax')
    if not parsed.get('date'):     missing.append('fecha (ej: 14/4)')
    return missing
