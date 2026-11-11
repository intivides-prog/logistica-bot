"""
Parser de lenguaje natural para pedidos de planilla.
Ejemplos que entiende:
  "hace una planilla para kayak mascardi para 4 pax"
  "plani kayak mascardi 3 pax el 14/4, guia julian"
  "kayak mascardi 5 pax 15/3, guia rodri, 2 vegetarianos"
  "fd kayak tres reyes 6 pax 20/4 julian donatelli"
"""

import re
from datetime import date, datetime, timedelta

SITES = {
    'mascardi':     'Lago Mascardi',
    'tres reyes':   'Tres Reyes',
    'nahuel':       'Lago Nahuel Huapi',
    'llao':         'Llao Llao',
    'pampa linda':  'Pampa Linda',
    'colonia suiza':'Colonia Suiza',
    'traful':       'Lago Traful',
    'espejo':       'Lago Espejo',
    'villa la angostura': 'Villa La Angostura',
    'vla':          'Villa La Angostura',
}

MONTHS_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12
}

DAYS_ES = {
    'lunes': 0, 'martes': 1, 'miércoles': 2, 'miercoles': 2,
    'jueves': 3, 'viernes': 4, 'sábado': 5, 'sabado': 5, 'domingo': 6,
}

# ── Consultas de fecha en lenguaje natural ────────────────────────────────────

def parse_date_query(text: str) -> date | None:
    """
    Detecta si el mensaje es una consulta de qué hay en una fecha.
    Ej: "qué hay el viernes", "que tenemos el 12/2", "qué salidas hay el viernes 2/3"
    Devuelve la fecha consultada, o None si no es una consulta.
    """
    t = text.lower().strip()

    if not re.search(
        r'qu[eé]\s+(?:hay|tenemos|salidas?|excursion|pasa|queda|sale)|'
        r'(?:hay|tenemos)\s+(?:algo|salidas?)|mostrame\s+(?:el|la|los)',
        t
    ):
        return None

    today = date.today()

    # "pasado mañana" — antes de "mañana"
    if re.search(r'pasado\s+ma[ñn]ana', t):
        return today + timedelta(days=2)

    # "mañana"
    if 'mañana' in t or 'manana' in t:
        return today + timedelta(days=1)

    # "hoy"
    if 'hoy' in t:
        return today

    # "esta semana" / "la semana que viene" → primer día
    if re.search(r'esta\s+semana', t):
        return today
    if re.search(r'semana\s+que\s+viene|pr[oó]xima\s+semana', t):
        monday = today + timedelta(days=(7 - today.weekday()))
        return monday

    # D/M — tiene prioridad sobre día de semana si viene con fecha exacta
    dm = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b', text)
    if dm:
        day, month = int(dm.group(1)), int(dm.group(2))
        year = int(dm.group(3)) if dm.group(3) else (
            today.year if month >= today.month else today.year + 1
        )
        try:
            return date(year, month, day)
        except ValueError:
            pass

    # "D de mes"
    de_mes = re.search(r'\b(\d{1,2})\s+de\s+([a-záéíóú]+)', t)
    if de_mes:
        day = int(de_mes.group(1))
        month = MONTHS_ES.get(de_mes.group(2))
        if month:
            year = today.year if month >= today.month else today.year + 1
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # Día de semana: "el viernes", "el próximo martes"
    for day_name, day_num in DAYS_ES.items():
        if day_name in t:
            days_ahead = day_num - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return today + timedelta(days=days_ahead)

    return None

# ── Números en palabras ───────────────────────────────────────────────────────
NUM_WORDS = {
    'un': '1', 'uno': '1', 'una': '1',
    'dos': '2', 'tres': '3', 'cuatro': '4', 'cinco': '5',
    'seis': '6', 'siete': '7', 'ocho': '8', 'nueve': '9', 'diez': '10',
}
# patrón que acepta dígito O palabra numérica
_NUM = r'(\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)'

def _n(m, g=1):
    """Convierte grupo g del match a número string (dígito o palabra)."""
    val = (m.group(g) or '1').lower().strip()
    return NUM_WORDS.get(val, val if val.isdigit() else '1')

# Palabras clave para detección rápida en parse_update
DIET_KEYWORDS = (
    r'restrict|vegetar|veggie|vegan|pescatar|celi[aá]c|gluten|tacc|'
    r'lactosa|al[eé]rgic|diab[eé]t|frutos?\s+secos?|mariscos?|kosher|halal'
)

DIET_PATTERNS = [
    # vegetariano / veggie
    (rf'{_NUM}\s*(?:vegetarian[oa]s?|veggies?)',    lambda m: f"{_n(m)}x vegetariano/a"),
    (r'un[ao]?\s+(?:vegetarian[oa]|veggie)',         lambda m: "1x vegetariano/a"),
    # vegano (estricto)
    (rf'{_NUM}\s*vegan[oa]s?',                       lambda m: f"{_n(m)}x vegano/a"),
    (r'un[ao]?\s+vegan[oa]',                         lambda m: "1x vegano/a"),
    # pescatariano
    (rf'{_NUM}\s*pescatarian[oa]s?',                 lambda m: f"{_n(m)}x pescatariano/a"),
    (r'un[ao]?\s+pescatarian[oa]',                   lambda m: "1x pescatariano/a"),
    # celíaco / sin TACC / gluten free
    (rf'{_NUM}\s*celi[aá]c[oa]s?',                   lambda m: f"{_n(m)}x celíaco/a (sin TACC)"),
    (r'un[ao]?\s+celi[aá]c[oa]',                     lambda m: "1x celíaco/a (sin TACC)"),
    (rf'{_NUM}\s*sin\s+tacc',                         lambda m: f"{_n(m)}x sin TACC"),
    (r'sin\s+tacc',                                   lambda m: "1x sin TACC"),
    (rf'{_NUM}\s*(?:sin\s+gluten|gluten\s*free)',     lambda m: f"{_n(m)}x sin gluten"),
    (r'(?:sin\s+gluten|gluten\s*free)',               lambda m: "1x sin gluten"),
    # sin lactosa
    (rf'{_NUM}\s*sin\s+lactosa',                      lambda m: f"{_n(m)}x sin lactosa"),
    (r'sin\s+lactosa',                                lambda m: "1x sin lactosa"),
    # diabético
    (rf'{_NUM}\s*diab[eé]tic[oa]s?',                 lambda m: f"{_n(m)}x diabético/a"),
    (r'un[ao]?\s+diab[eé]tic[oa]',                   lambda m: "1x diabético/a"),
    # alergia a frutos secos
    (r'alergi[ao]\s+(?:a\s+)?frutos?\s+secos?',      lambda m: "alergia frutos secos"),
    (r'frutos?\s+secos?',                             lambda m: "alergia frutos secos"),
    # alergia a mariscos
    (r'alergi[ao]\s+(?:a\s+)?mariscos?',             lambda m: "alergia mariscos"),
    (r'alergi[ao]\s+(?:a\s+)?nueces?',               lambda m: "alergia nueces"),
    # alergia genérica
    (rf'{_NUM}\s*al[eé]rgic[oa]s?\s+a\s+(\w+)',      lambda m: f"{_n(m)}x alergia a {m.group(2)}"),
    (rf'{_NUM}\s*al[eé]rgic[oa]s?',                  lambda m: f"{_n(m)}x alergia"),
    (r'un[ao]?\s+al[eé]rgic[oa]',                    lambda m: "1x alergia"),
    # kosher / halal
    (r'kosher',                                       lambda m: "kosher"),
    (r'halal',                                        lambda m: "halal"),
]


# ══ Detectores reutilizables (reglas) ════════════════════════════════════════

def _sin_tildes(text: str) -> str:
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if unicodedata.category(c) != 'Mn')


# Orden importa: lo más específico primero.
# (condición sobre el texto sin tildes, nombre de la actividad)
ACTIVITY_RULES = [
    (r'\b(hd|half\s*day|medio\s*dia)\b.*\bkayak|\bkayak\b.*\b(hd|half\s*day|medio\s*dia)\b', 'HD Kayak'),
    (r'\bkayak\b.*\btrek|\btrek.*\bkayak\b',                       'FD Kayak y Trekking'),
    (r'\bkayak',                                                    'FD Kayak'),
    (r'tronador|glaciares',                                         'Montañas y Glaciares del Tronador'),
    (r'limay|rios\s+y\s+lagos',                                     'Rios y Lagos del Limay'),
    (r'cascada|alerces|\bmanso\b',                                  'Lagos y Cascadas del Manso'),
    (r'san\s+martin|\bsma\b',                                       'San Martin de los Andes'),
    (r'\btrucha',                                                   'Valle Encantado Trucha'),
    (r'\bpollo|\bdisco\b',                                          'Valle Encantado Pollo'),
    (r'\basado\b',                                                  'Valle Asado'),
    (r'hiking|\bbrc\b',                                             'Bariloche Hiking'),
    (r'\bfrey\b',                                                   'FD Trekking Frey'),
    (r'goye|bella\s+vista',                                         'FD Trekking Bella Vista / Goye'),
    (r'(naveg|barco|lancha).*\b(ac|almuerzo|pvt|privad[ao])\b|\b(ac|almuerzo|pvt|privad[ao])\b.*(naveg|barco|lancha)',
                                                                    'Navegacion AC'),
    (r'naveg|barco|lancha',                                         'Navegacion Regular'),
    (r'\bmtb\b|mountain\s*bike|\bbici',                             'MTB'),
    (r'\btrek',                                                     'FD Trekking'),
]
ACTIVITY_WORDS = (r'kayak|tronador|glaciares|limay|rios\s+y\s+lagos|valle\s+encantado|\basado\b|naveg|barco|lancha|'
                  r'\bmtb\b|mountain\s*bike|\bbici|\btrek|plani|cascada|alerces|\bmanso\b|san\s+martin|\bsma\b|'
                  r'trucha|\bpollo|hiking|\bbrc\b|\bfrey\b|goye|bella\s+vista|\bvalle\b')

# "Valle Encantado" solo, sin decir qué comida: hay que preguntar
VALLE_AMBIGUO = r'valle\s+encantado|\bvalle\b'


def detect_activity(text: str):
    t = _sin_tildes(text)
    for pattern, name in ACTIVITY_RULES:
        if re.search(pattern, t):
            return name
    return None


def mentions_activity(text: str) -> bool:
    return bool(re.search(ACTIVITY_WORDS, _sin_tildes(text)))


def detect_site(text: str):
    t = _sin_tildes(text)
    for key, val in SITES.items():
        if key in t:
            return val
    return None


def detect_pax(text: str):
    t = _sin_tildes(text)
    for pat in (r'(\d+)\s*(?:pax|personas?|pasajeros?|pasaj)\b',
                r'\bx\s?(\d+)\b',
                r'\bson\s+(\d+)\b',
                r'\b(?:para|de)\s+(\d+)(?!\s*[/:hd])\b'):
        m = re.search(pat, t)
        if m:
            return int(m.group(1))
    m = re.search(r'\b(dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+(?:pax|personas?|pasajeros?)', t)
    if m:
        return int(NUM_WORDS[m.group(1)])
    return None


def _infer_year(day: int, month: int, today: date):
    """Sin año explícito: la próxima vez que ocurra esa fecha."""
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    if d < today:
        try:
            d = date(today.year + 1, month, day)
        except ValueError:
            return None
    return d


def find_all_dates(text: str, today: date | None = None) -> list:
    """Todas las fechas explícitas (D/M, D/M/AAAA, 'D de mes'), en orden de aparición."""
    today = today or date.today()
    t = _sin_tildes(text)
    found = []
    for m in re.finditer(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', t):
        day, month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            y = int(m.group(3)); y = y + 2000 if y < 100 else y
            try:
                found.append((m.start(), date(y, month, day)))
            except ValueError:
                pass
        else:
            d = _infer_year(day, month, today)
            if d: found.append((m.start(), d))
    for m in re.finditer(r'\b(\d{1,2})\s+de\s+([a-z]+)', t):
        month = MONTHS_ES.get(m.group(2))
        if month:
            d = _infer_year(int(m.group(1)), month, today)
            if d: found.append((m.start(), d))
    return [d for _, d in sorted(found, key=lambda x: x[0])]


def detect_relative_date(text: str, today: date | None = None):
    """hoy / mañana / pasado mañana / día de la semana."""
    today = today or date.today()
    t = _sin_tildes(text)
    if re.search(r'pasado\s+manana', t):
        return today + timedelta(days=2)
    # "mañana" como día, no "a la mañana"
    if re.search(r'(?<!la\s)\bmanana\b', t):
        return today + timedelta(days=1)
    if re.search(r'\bhoy\b', t):
        return today
    for day_name, day_num in DAYS_ES.items():
        if re.search(rf'\b{_sin_tildes(day_name)}\b', t):
            ahead = day_num - today.weekday()
            if ahead <= 0:
                ahead += 7
            return today + timedelta(days=ahead)
    return None


def detect_date(text: str, today: date | None = None):
    dates = find_all_dates(text, today)
    return dates[0] if dates else detect_relative_date(text, today)


def detect_hora(text: str):
    t = _sin_tildes(text)
    m = (re.search(r'\b(\d{1,2})[:.](\d{2})\s*(?:hs?|horas)?\b', t)
         or re.search(r'\b(\d{1,2})\s*(?:hs|h|horas)\b', t)
         or re.search(r'\ba\s+las\s+(\d{1,2})\b', t))
    if not m:
        return None
    h = int(m.group(1))
    mins = m.group(2) if m.lastindex and m.lastindex >= 2 else '00'
    if h > 23:
        return None
    return f"{h}:{mins} hs"


EXTRA_PATTERNS = {
    'infusiones': (r'infusion|caja\s+de\s+te\b|\bte\s+y\s+cafe|\bcafe\s+y\s+te\b|set\s+de\s+(?:te|cafe)\b|'
                   r'set\s+(?:para\s+)?(?:infusion|cafe)|\bcafe\b|hace\s+frio|dia\s+frio|\bdia\s+de\s+frio'),
    'sopa':       r'\bsopa|calabaza',
}


def detect_extras(text: str) -> list:
    t = _sin_tildes(text)
    return [k for k, pat in EXTRA_PATTERNS.items() if re.search(pat, t)]


def merge_followup(text: str, pending: dict) -> dict | None:
    """
    Con un borrador pendiente, intenta completarlo/corregirlo con reglas.
    Devuelve el borrador actualizado, o None si no reconoce nada útil.
    """
    t = text.strip()
    new = parse_message(t)
    # Si el mensaje es un pedido completo nuevo, no es un complemento
    if new.get('activity') and new.get('pax') and new.get('date'):
        return None
    merged = dict(pending)
    changed = False
    for field in ('activity', 'site', 'pax', 'date', 'guide', 'client', 'hora', 'hotel'):
        if new.get(field) and new[field] != pending.get(field):
            merged[field] = new[field]; changed = True
    if new.get('activity'):
        merged['gastronomy_type'] = new.get('gastronomy_type', 'AC')
    for ex in new.get('extras') or []:
        if ex not in (merged.get('extras') or []):
            merged['extras'] = (merged.get('extras') or []) + [ex]; changed = True
    if new.get('dietary_restrictions'):
        merged['dietary_restrictions'] = ', '.join(filter(None, [pending.get('dietary_restrictions'),
                                                                 new['dietary_restrictions']]))
        changed = True
    # Número suelto ("5") cuando falta la cantidad de pax
    if not pending.get('pax') and re.fullmatch(r'\d{1,2}', t):
        merged['pax'] = int(t); changed = True
    # Nombre suelto ("Rodri") cuando falta el guía
    if not changed and not pending.get('guide') and re.fullmatch(r'[A-Za-záéíóúñÁÉÍÓÚÑ]{3,15}', t):
        merged['guide'] = t.title(); changed = True
    return merged if changed else None


def update_is_complete(upd: dict) -> bool:
    """¿Las reglas entendieron la modificación lo suficiente como para ejecutarla?"""
    if not upd or not upd.get('action') or not upd.get('date'):
        return False
    if upd['action'] in ('cancel', 'resend_planilla', 'reset_planilla'):
        return True
    if upd['action'] in ('add_extra', 'remove_extra'):
        return bool(upd.get('new_value'))
    if upd['action'] == 'edit_item':
        nv = upd.get('new_value') or {}
        return bool(nv.get('item')) and (nv.get('op') == 'remove' or nv.get('qty') not in (None, ''))
    return upd.get('new_value') not in (None, '')


def parse_message(text: str) -> dict:
    t = text.lower().strip()
    result = {}

    # ── Actividad ────────────────────────────────────────────────────────────
    result['activity'] = detect_activity(text)
    result['extras'] = detect_extras(text)
    result['_valle'] = (result['activity'] is None and bool(re.search(VALLE_AMBIGUO, _sin_tildes(text))))

    # ── Modalidad FD / HD (para gastronomía) ─────────────────────────────────
    result['gastronomy_type'] = 'snacks' if result['activity'] == 'HD Kayak' else 'AC'

    # ── Sitio ─────────────────────────────────────────────────────────────────
    result['site'] = detect_site(text)

    # ── Cantidad de pax ───────────────────────────────────────────────────────
    result['pax'] = detect_pax(text)

    # ── Fecha ─────────────────────────────────────────────────────────────────
    result['date'] = detect_date(text)

    # ── Cliente / nombre de reserva ───────────────────────────────────────────
    result['client'] = None
    client_m = re.search(
        r'(?:reserva|cliente|contacto)\s+(?:de\s+)?'
        r'([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)',
        text, re.IGNORECASE
    )
    if client_m:
        result['client'] = client_m.group(1).strip().title()

    # ── Guía ─────────────────────────────────────────────────────────────────
    # La segunda palabra NO puede ser una palabra clave (hotel, pax, hay, etc.)
    result['guide'] = None
    guide_m = re.search(
        r'gu[ií]a(?:\s+(?:es|va\s+a\s+ser|ser[aá]|:))?\s+'
        r'([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+'
        r'(?:\s+(?!(?:hotel|pax|hay|con|para|el|la|los|las|de|del|en|al|a|y|x|hs|reserva|guia|gu[ií]a|son|uno|una|un)\b)[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)',
        text, re.IGNORECASE
    )
    if guide_m:
        result['guide'] = guide_m.group(1).strip().title()

    # ── Hora ─────────────────────────────────────────────────────────────────
    result['hora'] = detect_hora(text)

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
        m = re.search(pattern, t) or re.search(pattern, _sin_tildes(t))
        if m:
            restrictions.append(formatter(m))
    result['dietary_restrictions'] = ', '.join(restrictions) if restrictions else None

    return result


# ══ Edición de ítems de la planilla desde el chat ═════════════════════════════
_ITEM = r'(?P<item>[a-zñ0-9][a-zñ0-9 .,/]*?)'
_TARGET = r'\s+(?:en|al|a\s+la|a|del|de\s+la|para)\s+(?:el|la|los|las)?\s*(?=' \
          r'kayak|trek|tronador|glaciares|limay|cascada|manso|san\s+martin|valle|hiking|brc|frey|goye|bella|naveg|barco|mtb|salida|excursion|' \
          r'reserva|planilla|grupo|\d|[a-zñ]+\s+(?:del|de|el)\b|[a-zñ]+$)'
_QTY = r'(?P<qty>\d+(?:[.,]\d+)?|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|varios|varias)'

ITEM_EDIT_PATTERNS = [
    # "sacá las polainas del trekking de Rodri" / "quitale el vino a ..."
    ('remove', rf'\b(?:saca(?:le)?|quita(?:le)?|elimina(?:le)?|borra(?:le)?)\s+(?:(?:el|la|los|las)\s+)?{_ITEM}{_TARGET}'),
    # "agregá 2 termos al tronador de Rodri" / "sumale 1 vino"
    ('add',    rf'\b(?:agrega(?:le)?|suma(?:le)?|anadi(?:le)?)\s+{_QTY}\s+{_ITEM}{_TARGET}'),
    # "poné 4 vinos en el tronador de Rodri" / "dejá 2 heladeras"
    ('set',    rf'\b(?:pone(?:le)?|deja(?:le)?|cambia|modifica|que\s+sean)\s+{_QTY}\s+{_ITEM}{_TARGET}'),
    # "cambiá los vinos a 4 en el tronador de Rodri"
    ('set',    rf'\b(?:cambia|modifica|pone|deja)\s+(?:el|la|los|las)\s+{_ITEM}\s+(?:a|en)\s+{_QTY}\b'),
]


def parse_item_edit(text: str):
    """Detecta pedidos para cambiar un ítem de la planilla. Devuelve dict o None."""
    t = _sin_tildes(text)
    for op, pat in ITEM_EDIT_PATTERNS:
        m = re.search(pat, t)
        if not m:
            continue
        item = re.sub(r'^(?:el|la|los|las|un|una)\s+', '', m.group('item').strip(' .,'))
        if not item or item in ('hora', 'horario', 'guia', 'fecha', 'dia', 'pax', 'hotel', 'lugar', 'sitio'):
            return None
        qty = None
        if 'qty' in m.groupdict() and m.group('qty'):
            q = m.group('qty')
            qty = NUM_WORDS.get(q, q)
        return {'op': op, 'item': item, 'qty': qty, 'rest': t[m.end('item'):]}
    return None


def parse_set_restrictions(text: str):
    """'Las restricciones son: 1 celíaco' / 'sin restricciones' → valor completo nuevo."""
    t = _sin_tildes(text)
    if re.search(r'\b(?:sin|no\s+hay|no\s+tiene[n]?|saca(?:le)?\s+las|borra(?:le)?\s+las|quita(?:le)?\s+las)\s+restricciones', t):
        return 'Ninguna'
    m = re.search(r'restricciones?\s*(?:son|ahora\s+son|quedan|:)\s*:?\s*(.+)', text, re.IGNORECASE)
    if not m:
        return None
    val = m.group(1)
    found = []
    for pattern, formatter in DIET_PATTERNS:
        mm = re.search(pattern, _sin_tildes(val.lower()))
        if mm:
            found.append(formatter(mm))
    if found:
        return ', '.join(found)
    # texto libre: cortar donde empieza la referencia a la salida
    val = re.split(r'\s+(?:en|para|del|de\s+la|al)\s+(?:el|la)?\s*(?:kayak|trek|tronador|salida|reserva|valle|\d)', val, flags=re.I)[0]
    return val.strip(' .') or None


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
    if re.search(r'planilla\s+(?:original|autom[aá]tica)|volv[eé]\s+a\s+la\s+planilla', t):
        action = 'reset_planilla'
    elif re.search(r'cancel[ao]|no\s+va|se\s+cancela|suspende', t):
        action = 'cancel'
    elif re.search(rf'{VERBS}\s+(?:el\s+|la\s+)?(?:hora|horario)|nueva\s+hora|cambi[oó]\s+(?:la\s+)?hora', t):
        action = 'update_hora'
    elif re.search(r'\b(?:pas[aá]|mov[eé]|corr[eé])l[oa]s?\b', t) and detect_hora(text):
        action = 'update_hora'
    elif re.search(r'\b(?:pas[aá]|mov[eé]|corr[eé])l[oa]s?\b', t) and (find_all_dates(text) or detect_relative_date(text)):
        action = 'update_date'
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
    elif detect_extras(text) and re.search(r'\b(?:saca|quita|elimina|borra|sin)\w*', _sin_tildes(t)) and \
            re.search(r'\b(?:saca|quita|elimina|borra)\w*\s+(?:el|la|los|las)?\s*(?:set|infusion|sopa|te|cafe|termo)|\bsin\s+(?:sopa|infusion|cafe|te)', _sin_tildes(t)):
        action = 'remove_extra'
    elif detect_extras(text) and re.search(r'\b(?:agrega|suma|pone|lleva|quiero|incluye|anadi)\w*\s+(?:el\s+|la\s+|un\s+|una\s+)?(?:set|infusion|sopa|te|cafe|termo)', _sin_tildes(t)):
        action = 'add_extra'
    elif parse_set_restrictions(text):
        action = 'set_restrictions'
    elif re.search(r'como\s+restricci[oó]n', t):
        action = 'update_restrictions'
    elif re.search(DIET_KEYWORDS, _sin_tildes(t)) and re.search(r'agrega[r]?|añadi[r]?|suma[r]?', t):
        action = 'update_restrictions'
    elif re.search(DIET_KEYWORDS, _sin_tildes(t)) and re.search(
            r'hay\s+(?:un[ao]?|\d+|uno|dos|tres|cuatro|cinco)|tiene[n]?\s+(?:un[ao]?|\d+)', t):
        # "hay 2 celíacos" — solo es update si NO hay actividad en el mensaje
        # (con actividad = pedido nuevo de planilla)
        if not mentions_activity(text):
            action = 'update_restrictions'

    item_edit = None
    if not action:
        item_edit = parse_item_edit(text)
        if item_edit:
            action = 'edit_item'

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
    all_dates = find_all_dates(text)
    if all_dates:
        result['date'] = all_dates[0]
    elif action != 'update_date':
        result['date'] = detect_relative_date(text)

    STOP_WORDS = {'el', 'la', 'los', 'las', 'en', 'al', 'del', 'un', 'una', 'de', 'para', 'con', 'hotel', 'pax', 'hay', 'reserva', 'a', 'y', 'hs'}

    # Identificador — guía o cliente (en ediciones de ítem, se busca después del ítem)
    id_text = item_edit['rest'] if item_edit else text
    if action in ('add_extra', 'remove_extra'):
        # "agregá el set de infusiones AL VALLE DE CINTIA": la salida viene después de al/del/en
        parts = re.split(r'\s(?:al|a\s+la|del|de\s+la|en\s+el|en\s+la|para\s+el|para\s+la)\s', text, maxsplit=1, flags=re.I)
        id_text = parts[1] if len(parts) > 1 else text
    guide_m = re.search(
        r'gu[ií]a\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)',
        id_text, re.IGNORECASE
    )
    if guide_m:
        # Filtrar stop words del final
        words = guide_m.group(1).strip().split()
        words = [w for i, w in enumerate(words) if i == 0 or w.lower() not in STOP_WORDS]
        result['identifier'] = ' '.join(words).title()
        result['identifier_type'] = 'guide'
    else:
        # Busca "de [Nombre]" — solo una palabra para evitar capturar "de Lark el 20/6"
        client_m = re.search(r'\bde\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]{3,})', id_text, re.IGNORECASE)
        if client_m:
            word = client_m.group(1)
            if word.lower() not in STOP_WORDS:
                result['identifier'] = word.title()
                result['identifier_type'] = 'client'

    # Extraer nuevo valor según acción
    if action == 'update_hora':
        # La hora nueva es la que viene después de "a las" / "para las"; si no, la primera
        tail = re.search(r'\b(?:a|para)\s+las?\s+(.*)$', text, re.IGNORECASE)
        result['new_value'] = (detect_hora('a las ' + tail.group(1)) if tail else None) or detect_hora(text)

    elif action == 'update_guide':
        new_m = re.search(
            r'(?:a|por|es|ser[aá])\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)?)(?:\s*$)',
            text, re.IGNORECASE
        )
        if new_m:
            result['new_value'] = new_m.group(1).strip().title()

    elif action == 'update_date':
        if len(all_dates) >= 2:
            result['new_value'] = all_dates[1]
        else:
            rel = detect_relative_date(text)
            if rel:
                result['new_value'] = rel
            elif len(all_dates) == 1 and not re.search(r'\bdel\s+\d', _sin_tildes(text)):
                # "pasalo al 22/6" sin decir la fecha original
                result['new_value'] = all_dates[0]
                result['date'] = None

    elif action == 'update_site':
        for key, val in SITES.items():
            if key in t:
                result['new_value'] = val
                break

    elif action == 'update_pax':
        result['new_value'] = detect_pax(text)

    elif action == 'update_hotel':
        # "agrega el hotel Llao Llao" / "el hotel es Panamericano"
        hotel_m = re.search(r'hotel\s+(?:es\s+)?([A-Za-záéíóúüñÁÉÍÓÚÜÑ][A-Za-záéíóúüñÁÉÍÓÚÜÑ\s]+?)(?:\s*$|\s+en\s|\s+el\s|\s+\d)', text, re.IGNORECASE)
        if hotel_m:
            result['new_value'] = hotel_m.group(1).strip().title()

    elif action in ('add_extra', 'remove_extra'):
        result['new_value'] = detect_extras(text)

    elif action == 'set_restrictions':
        result['new_value'] = parse_set_restrictions(text)

    elif action == 'edit_item':
        result['new_value'] = {k: v for k, v in item_edit.items() if k != 'rest'}

    elif action == 'update_restrictions':
        # Formato libre: "agrega X como restriccion"
        freeform_m = re.search(r'agrega[r]?\s+(.+?)\s+como\s+restricci[oó]n', text, re.IGNORECASE)
        if freeform_m:
            result['new_value'] = freeform_m.group(1).strip().title()
        else:
            restrictions = []
            for pattern, formatter in DIET_PATTERNS:
                m = re.search(pattern, t) or re.search(pattern, _sin_tildes(t))
                if m:
                    restrictions.append(formatter(m))
            result['new_value'] = ', '.join(restrictions) if restrictions else None

    return result


def format_missing(parsed: dict) -> list[str]:
    """Devuelve lista de campos faltantes para pedir al usuario."""
    missing = []
    if not parsed.get('activity'):
        if parsed.get('_valle'):
            missing.append('qué comida en Valle Encantado: asado, pollo al disco o trucha')
        else:
            missing.append('actividad (kayak, MTB, trekking, etc.)')
    if not parsed.get('pax'):      missing.append('cantidad de pax')
    if not parsed.get('date'):     missing.append('fecha (ej: 14/4)')
    return missing
