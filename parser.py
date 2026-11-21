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
    'moreno':       'Lago Moreno',
    'gutierrez':    'Lago Gutiérrez',
    'guillelmo':    'Lago Guillelmo',
    'steffen':      'Lago Steffen',
    'hess':         'Lago Hess',
    'roca':         'Lago Roca',
    'correntoso':   'Lago Correntoso',
    'escondido':    'Lago Escondido',
    'catedral':     'Base Cerro Catedral',
    'frey':         'Refugio Frey',
    'goye':         'Cerro Goye',
    'bella vista':  'Bella Vista',
    'bahia lopez':  'Bahía López',
    'puerto panuelo': 'Puerto Pañuelo',
    'pañuelo':      'Puerto Pañuelo',
    'arelauquen':   'Arelauquen',
    'manso':        'Río Manso',
    'limay':        'Río Limay',
    'alerces':      'Cascada de los Alerces',
    'valle encantado': 'Valle Encantado',
    'tronador':     'Tronador',
    'san martin':   'San Martín de los Andes',
    'lopez':        'Cerro López',
    'ventana':      'Cerro Ventana',
    'cerro campanario': 'Cerro Campanario',
    'centinela':    'Cerro Centinela (VLA)',
    'arrayanes':    'Bosque de Arrayanes (VLA)',
    'tristeza':     'Brazo Tristeza',
    'cerro llao':   'Cerro Llao Llao',
    'lagos y montanas': 'Lagos y Montañas',
    'peninsula petit': 'Península Petit',
    'radisson':     'Radisson Blu',
    'circuito chico': 'Circuito Chico',
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

# ══ Varias reservas en un mismo mensaje ══════════════════════════════════════

def split_reservas(text: str) -> list:
    """
    Separa un mensaje con varias salidas. Cada línea (o cada ítem numerado /
    con guión) es una salida, siempre que mencione una actividad.
    Devuelve [] si es un pedido de una sola salida.
    """
    bruto = [l.strip() for l in text.splitlines()]
    lineas = []
    for l in bruto:
        l = re.sub(r'^\s*(?:\d{1,2}[.)\-]|[-•*·])\s*', '', l).strip()
        if l:
            lineas.append(l)
    # Encabezado tipo "para el viernes:" que aplica a todas
    encabezado = ''
    if lineas and not mentions_activity(lineas[0]) and len(lineas) > 1:
        encabezado = lineas.pop(0).rstrip(':').strip()
    con_actividad = [l for l in lineas if mentions_activity(l)]
    if len(con_actividad) < 2:
        return []
    salidas = []
    for l in lineas:
        if not mentions_activity(l):
            # línea suelta de detalle: se suma a la anterior
            if salidas:
                salidas[-1] = salidas[-1] + ' ' + l
            continue
        salidas.append((encabezado + ' ' + l).strip() if encabezado else l)
    return salidas


def parse_reservas(text: str) -> list:
    """Devuelve una lista de salidas parseadas, o [] si no es un mensaje en lote."""
    trozos = split_reservas(text)
    if not trozos:
        return []
    return [parse_message(t) for t in trozos]


# "en la 2 el guía es Fede" / "la primera son 5 pax" / "a la 3 agregale hotel X"
ORDINALES = {
    'primera': 1, 'primero': 1, 'uno': 1, 'una': 1,
    'segunda': 2, 'segundo': 2, 'dos': 2,
    'tercera': 3, 'tercero': 3, 'tres': 3,
    'cuarta': 4, 'cuarto': 4, 'cuatro': 4,
    'quinta': 5, 'quinto': 5, 'cinco': 5,
    'ultima': 99, 'último': 99, 'ultimo': 99,
}


def parse_correccion_lote(text: str, total: int):
    """
    Detecta a qué salida del lote se refiere una corrección.
    Devuelve (indice_0based, texto_sin_la_referencia) o None.
    """
    t = _sin_tildes(text)
    m = re.search(r'\b(?:en|a|para|de)\s+(?:la|el)\s+(\d{1,2}|' + '|'.join(ORDINALES) + r')\b', t)
    if not m:
        m = re.search(r'^\s*(?:la|el)\s+(\d{1,2}|' + '|'.join(ORDINALES) + r')\b', t)
    if not m:
        return None
    crudo = m.group(1)
    num = int(crudo) if crudo.isdigit() else ORDINALES.get(crudo, 0)
    if num == 99:
        num = total
    if not (1 <= num <= total):
        return None
    resto = (text[:m.start()] + ' ' + text[m.end():]).strip()
    return num - 1, resto



BACKROADS_GRUPOS = {
    'multi adventure': 'Multi Adventure', 'multi': 'Multi Adventure', 'ma': 'Multi Adventure',
    'easygoing': 'Easygoing', 'easy': 'Easygoing',
    'regular': 'Regular',
}
DIETAS_BACKROADS = {
    'veggie': 'veggie', 'vegetariano': 'veggie', 'vegetarianos': 'veggie', 'vegetariana': 'veggie',
    'vegan': 'vegan', 'vegano': 'vegan', 'veganos': 'vegan', 'vegana': 'vegan',
    'pescetarian': 'pescetarian', 'pescatariano': 'pescetarian', 'pescatarianos': 'pescetarian',
    'pescetariano': 'pescetarian', 'regular': 'regular', 'regulares': 'regular',
}


def parse_backroads(text: str) -> dict | None:
    """
    "Backroads Multi Adventure del 9/12, 12 pax, 2 veggie y 1 vegan"
    Devuelve los datos para completar la fila, o None si no habla de Backroads.
    """
    t = _sin_tildes(text)
    if 'backroads' not in t:
        return None

    grupo = None
    for clave in sorted(BACKROADS_GRUPOS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(clave)}\b', t):
            grupo = BACKROADS_GRUPOS[clave]
            break

    dietas = {}
    for m in re.finditer(r'(\d+)\s*([a-z]+)', t):
        clave = DIETAS_BACKROADS.get(m.group(2))
        if clave:
            dietas[clave] = int(m.group(1))

    personal = detect_personal(text)
    pax = detect_pax(text)
    if pax is None:
        m = re.search(r'\bson\s+(\d+)\b', t)
        pax = int(m.group(1)) if m else None

    return {
        'fecha': detect_date(text),
        'grupo': grupo,
        'actividad': detect_activity(text) and None,   # la actividad ya está en la planilla
        'pax': pax,
        'personal': personal,
        'dietas': dietas,
    }


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
    # Las más específicas primero: si no, "valle encantado hiking" cae en Valle a secas
    (r'valle\s+encantado\s+hiking|hiking\s+valle\s+encantado',    'FD Valle Encantado Hiking'),
    (r'centinela',                                                  'FD Trekking Cerro Centinela'),
    (r'arrayanes',                                                  'HD MTB Bosque de Arrayanes'),
    (r'cerro\s+llao|llao\s*-?\s*llao\s+hiking|hiking\s+llao',     'HD Hiking Cerro Llao-Llao'),
    (r'brazo\s+tristeza|tristeza',                                  'Brazo Tristeza REG TRF PVT'),
    (r'\b(hd|half\s*day|medio\s*dia)\b.*\bkayak|\bkayak\b.*\b(hd|half\s*day|medio\s*dia)\b', 'HD Kayak'),
    (r'\bkayak\b.*\btrek|\btrek.*\bkayak\b',                       'FD Kayak y Trekking'),
    (r'\bkayak',                                                    'FD Kayak'),

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
    (r'lagos\s+y\s+monta[nñ]as',                                    'MTB'),
    (r'\bmtb\b|mountain\s*bike|\bbici',                             'MTB'),
    (r'tronador|glaciares|monta[nñ]as',                             'Montañas y Glaciares del Tronador'),
    (r'\btrek',                                                     'FD Trekking'),
]
ACTIVITY_WORDS = (r'kayak|tronador|glaciares|monta[nñ]as|limay|rios\s+y\s+lagos|valle\s+encantado|\basado\b|naveg|barco|lancha|'
                  r'\bmtb\b|mountain\s*bike|\bbici|\btrek|plani|cascada|alerces|\bmanso\b|san\s+martin|\bsma\b|'
                  r'trucha|\bpollo|hiking|\bbrc\b|\bfrey\b|goye|bella\s+vista|\bvalle\b|'
                  r'centinela|arrayanes|tristeza|cerro\s+llao|lagos\s+y\s+monta[nñ]as')

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
    # de la clave más larga a la más corta: "cerro llao" gana sobre "llao llao"
    for key in sorted(SITES, key=len, reverse=True):
        if key in t:
            return SITES[key]
    return None


def detect_pax(text: str):
    t = _sin_tildes(text)
    t = re.sub(r'\+?\s*\d+\s*perso(?:nal)?\b', ' ', t)     # "+2 perso" no es cantidad de pax
    for pat in (r'(\d+)\s*(?:pax|personas?|pasajeros?|pasaj|pers\b|pp\b|px\b)',
                r'\bx\s?(\d+)\b',
                r'\b(\d+)\s*x\b',
                r'\bson\s+(\d+)\b',
                r'\bgrupo\s+de\s+(\d+)\b',
                r'\b(?:para|de)\s+(\d+)(?!\s*[/:hd])\b'):
        m = re.search(pat, t)
        if m:
            return int(m.group(1))
    m = re.search(r'\b(dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+(?:pax|personas?|pasajeros?)', t)
    if m:
        return int(NUM_WORDS[m.group(1)])
    return None


def detect_personal(text: str):
    """Cuánta gente de la empresa va: '2 perso', '+1 personal', 'personal 2'."""
    t = _sin_tildes(text)
    m = (re.search(r'\+?\s*(\d+)\s*perso(?:nal)?\b', t)
         or re.search(r'perso(?:nal)?\s*:?\s*(\d+)\b', t)
         or re.search(r'(?:con|son)\s+(\d+)\s+de\s+la\s+empresa', t))
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 <= n <= 9 else None


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


def detect_hora_entrega(text: str):
    """La hora en que se entrega el despacho: 'entrega 7hs', 'dejar 7 en pasillo'."""
    m = re.search(r'\b(?:entrega\w*|despach\w*|dej[aá]\w*|retir\w*\s+el\s+despacho)\b(.{0,28})',
                  text, re.IGNORECASE)
    if not m:
        return None
    return detect_hora(m.group(1))


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


# ── Captura de nombres (guía, pasajero, agencia, conductor, hotel) ────────────
# Palabras que nunca forman parte de un nombre: marcan dónde termina.
STOP_NOMBRE = {
    'hotel', 'pax', 'personas', 'persona', 'pasajeros', 'pasajero', 'hay', 'con', 'para',
    'el', 'la', 'los', 'las', 'de', 'del', 'en', 'al', 'a', 'y', 'o', 'x', 'hs', 'horas',
    'reserva', 'guia', 'agencia', 'operador', 'conductor', 'chofer', 'movil', 'vehiculo',
    'transporte', 'camioneta', 'combi', 'alojados', 'alojado', 'alojan', 'hospedados',
    'auto', 'talle', 'talles', 'botitas', 'botita', 'neoprene', 'neopren', 'nombre',
    'restricciones', 'restriccion', 'sin', 'mas', 'son', 'uno', 'una', 'un', 'dos', 'tres',
    'celiaco', 'celiacos', 'vegano', 'veganos', 'vegetariano', 'vegetarianos', 'veggie',
    'sopa', 'infusiones', 'infusion', 'cafe', 'te', 'termo', 'frio', 'hace', 'que', 'ahora',
    'nuevo', 'nueva', 'otra', 'otro', 'vuelta', 'planilla', 'excel', 'salida', 'excursion',
    'manana', 'hoy', 'pasado', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes',
    'sabado', 'domingo', 'kayak', 'trekking', 'trek', 'mtb', 'navegacion', 'tronador',
}

_PALABRA = r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’.-]*"


def capture_name(text: str, prefix: str, max_words: int = 2):
    """
    Busca `prefix` (regex) y devuelve hasta `max_words` palabras siguientes,
    cortando en la primera palabra de STOP_NOMBRE o en algo que no sea una palabra.
    """
    m = re.search(prefix, text, re.IGNORECASE)
    if not m:
        return None
    resto = text[m.end():]
    resto = re.sub(r'^\s*(?::|es|son|va\s+a\s+ser|ser[aá])?\s*', '', resto, flags=re.IGNORECASE)
    resto = resto.split('\n')[0]          # un dato por línea: no cruza al renglón siguiente
    palabras = []
    for tok in re.finditer(rf'\S+', resto):
        crudo = tok.group(0)
        w = crudo.strip('.,;:()[]')
        if not re.fullmatch(_PALABRA, w):
            break
        if _sin_tildes(w) in STOP_NOMBRE:
            break
        palabras.append(w)
        if len(palabras) >= max_words or crudo.rstrip().endswith(('.', ',', ';')):
            break                        # "peninsula petit." termina ahí
    if not palabras:
        return None
    # 'lark' → 'Lark', pero 'GFT' queda como está
    return ' '.join(w.capitalize() if w.islower() else w for w in palabras)


# ── Agencia / cliente corporativo ─────────────────────────────────────────────
# Agencias conocidas: se reconocen aunque no digan "agencia".
AGENCIES = [
    'say hueque', 'say vaya', 'beyond ba', 'gft', 'south american inside',
    'chimu', 'tangol', 'signature', 'kallpa', 'contours', 'lihue', 'nuevo mundo',
    'journey latin america', 'abercrombie', 'audley', 'swoop', 'pura aventura',
]
_NOMBRE = r'[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]+){0,2}'
_STOP_NOM = (r'(?:hotel|pax|hay|con|para|el|la|los|las|de|del|en|al|a|y|x|hs|reserva|guia|gu[ií]a|'
             r'son|uno|una|un|agencia|cliente|conductor|chofer|movil|m[oó]vil|talle|talles|'
             r'neoprene|botitas|nombre|restricciones|sin|mas|m[aá]s)\b')


# Formas de nombrar el hotel sin decir "hotel"
HOTEL_PREFIX = (r'\bhotel\b|\baloj\w*\s+en\b|\bhosped\w*\s+en\b|\bse\s+aloja\w*\s+en\b|'
                r'\bparan?\s+en\b|\best[aá]n?\s+en\s+(?=el\s|la\s|[A-Z])')


def detect_agency(text: str):
    val = capture_name(text, r'\b(?:agencia|operador|agency|agencia\s+es)\b', max_words=3)
    if val:
        return val
    t = _sin_tildes(text)
    for a in AGENCIES:
        m = re.search(rf'\b{re.escape(a)}\b', t)
        if m:
            original = text[m.start():m.end()]        # respeta cómo lo escribieron
            return original if any(c.isupper() for c in original) else original.title()
    return None


DRIVER_PREFIX = r'\b(?:conductor|chofer|m[oó]vil|movil|veh[ií]culo|vehiculo|transporte|camioneta|combi)\b'


def detect_driver(text: str):
    """Conductor o móvil: 'conductor Pablo', 'chofer sp 01', 'h1 julio picabea'."""
    m = re.search(DRIVER_PREFIX + r'\s*(?::|es\s+)?\s*([a-zA-Z]{1,3}\s?\d{1,2})\b',
                  text, re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()
    val = capture_name(text, DRIVER_PREFIX, max_words=3)
    if val:
        # "Julio Picabea H1": el móvil va pegado al nombre
        cola = re.search(rf'{re.escape(val)}\s+([a-zA-Z]{{1,3}}\s?\d{{1,2}})\b', text, re.IGNORECASE)
        return f"{val} {cola.group(1).upper()}" if cola else val
    m = re.search(r'\b(sp\s?\d{1,2}|h\s?\d{1,2})\b', _sin_tildes(text))
    if m:
        return m.group(1).strip().upper()
    val = capture_name(text, r'\bauto\b')
    return f"Auto {val}" if val else None


def detect_wetsuit(text: str):
    """Talles de botitas de neoprene: 'talles 38, 40, 42' · 'botitas 2x40 1x43'."""
    t = _sin_tildes(text)
    m = re.search(r'(?:talles?|botitas?|neoprene|neopren)\s*(?:de\s+)?(?:neoprene\s*)?[:\s]\s*'
                  r'((?:\d{1,2}\s*x\s*)?\d{2}(?:\s*(?:,|y|/|\s)\s*(?:\d{1,2}\s*x\s*)?\d{2})*)', t)
    if not m:
        return None
    crudo = m.group(1)
    partes = re.findall(r'(?:(\d{1,2})\s*x\s*)?(\d{2})', crudo)
    out = []
    for cant, talle in partes:
        if not (34 <= int(talle) <= 48):      # un talle real, no una hora ni un año
            continue
        out.append(f"{cant}x{talle}" if cant else talle)
    return ', '.join(out) or None



CAMPOS_SUELTOS = ('client', 'agency', 'hotel', 'driver', 'guide', 'hora', 'hora_entrega',
                  'wetsuit', 'personal', 'dietary_restrictions')


def campos_sueltos(text: str) -> dict:
    """
    Datos que llegan después, sin actividad ni fecha:
    "Nombre: oram david / Agencia: aliwen incoming / Hotel: peninsula petit".
    Devuelve solo los campos que el mensaje nombra explícitamente.
    """
    r = parse_message(text)
    out = {c: r[c] for c in CAMPOS_SUELTOS if r.get(c)}
    # Sin una etiqueta clara no se arriesga: evita tomar cualquier frase como nombre
    if not re.search(r'\b(?:nombre|cliente|reserva|agencia|hotel|aloja\w*|hosped\w*|conductor|chofer|'
                     r'veh[ií]culo|vehiculo|transporte|gu[ií]a|talles?|botitas?|perso\w*|entrega\w*|'
                     r'restricciones?|a\s+las?)\b', _sin_tildes(text)):
        return {}
    return out


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
    for field in ('activity', 'site', 'pax', 'date', 'guide', 'client', 'hora', 'hotel',
                  'agency', 'driver', 'wetsuit', 'personal', 'hora_entrega'):
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
    result['personal'] = detect_personal(text)

    # ── Fecha ─────────────────────────────────────────────────────────────────
    result['date'] = detect_date(text)

    # ── Cliente / nombre de reserva ───────────────────────────────────────────
    result['client'] = capture_name(
        text, r'\b(?:reserva|a\s+nombre\s+de|nombre|cliente|pasajeros?\s+es)\b', max_words=3)

    # ── Guía ─────────────────────────────────────────────────────────────────
    # La segunda palabra NO puede ser una palabra clave (hotel, pax, hay, etc.)
    result['guide'] = capture_name(text, r'\b(?:gu[ií]a|guiada\s+por|gu[ií]ada\s+por|lo\s+lleva|la\s+lleva|va\s+con)\b')

    # ── Agencia, conductor y talles de neoprene ──────────────────────────────
    result['agency']  = detect_agency(text)
    result['driver']  = detect_driver(text)
    result['wetsuit'] = detect_wetsuit(text)

    # ── Hora ─────────────────────────────────────────────────────────────────
    result['hora_entrega'] = detect_hora_entrega(text)
    # La hora de retiro se busca sobre el texto sin el pedazo de la entrega,
    # así "a las 9, entrega 7:30" no confunde una con la otra.
    sin_entrega = re.sub(r'\b(?:entrega\w*|despach\w*|dej[aá]\w*)\b.{0,28}', ' ', text, flags=re.IGNORECASE)
    result['hora'] = detect_hora(sin_entrega)

    # ── Hotel ─────────────────────────────────────────────────────────────────
    result['hotel'] = capture_name(text, HOTEL_PREFIX, max_words=3)
    # "hotel Llao Llao" no convierte a Llao Llao en el sitio de la excursión
    if result['hotel'] and result['site']:
        h = _sin_tildes(result['hotel'])
        if any(w in h for w in _sin_tildes(result['site']).split()):
            result['site'] = None

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


def _valor_final(text: str):
    """El valor nuevo de un cambio suele ir al final, después de 'a' o 'es'."""
    partes = re.split(r'\s+(?:a|es|por)\s+', text, flags=re.IGNORECASE)
    if len(partes) < 2:
        return None
    return capture_name(' ' + partes[-1], r'^')


# Verbos que dejan claro que se habla de una salida YA cargada
VERBOS_MODIFICACION = (r'\b(?:cambi\w*|modific\w*|cancel\w*|reenv\w*|mand[aá]\w*\s+de\s+nuevo|'
                       r'agreg\w*|sum[aá]\w*|sac[aá]\w*|quit\w*|elimin\w*|borr\w*|pon[eé]\w*|dej[aá]\w*|'
                       r'ahora|ya\s+no|pas[aá]l[oa]|corr[eé]l[oa]|actualiz\w*|edit\w*)\b')


def parece_salida_nueva(text: str) -> bool:
    """
    Un mensaje con actividad + al menos dos datos propios (pax, fecha, guía)
    es una salida nueva, aunque diga "el nombre es X" o "la agencia es Y".
    """
    r = parse_message(text)
    if not r.get('activity'):
        return False
    return sum(1 for c in ('pax', 'date', 'guide') if r.get(c)) >= 2


def parse_update(text: str) -> dict | None:
    """
    Detecta si el mensaje es una actualización de excursión existente.
    Devuelve dict con: action, date, identifier, identifier_type, new_value
    O None si no parece una actualización.
    """
    t = text.lower().strip()

    # "El sábado hay un valle encantado con 2 pax, guía Fer. El nombre es X" es
    # una salida nueva, no una modificación: sin verbo de cambio, no se toca nada.
    if parece_salida_nueva(text) and not re.search(VERBOS_MODIFICACION, _sin_tildes(t)):
        return None

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
    elif re.search(rf'{VERBS}\s+(?:la\s+)?agencia|agrega[r]?\s+(?:la\s+)?agencia|'
                   rf'(?:la\s+)?agencia\s+(?:es|:)|nueva\s+agencia', t):
        action = 'update_agency'
    elif re.search(r'\b(?:conductor|chofer|m[oó]vil)\b', t):
        action = 'update_driver'
    elif detect_wetsuit(text) and re.search(r'\b(?:talles?|botitas?|neoprene)\b', t):
        action = 'update_wetsuit'
    elif re.search(r'\bperso(?:nal)?\b', _sin_tildes(t)) and detect_personal(text) is not None:
        action = 'update_personal'
    elif re.search(rf'{VERBS}\s+(?:el\s+)?(?:nombre|cliente)|(?:nombre|cliente)\s+(?:es|:)|'
                   rf'cambi[oó]\s+(?:el\s+)?nombre', t):
        action = 'update_client'
    elif re.search(r'plan[i]?|excel', t) and re.search(
            r'reenv[ií]\w*|mand[aá]\w*|pas[aá]\w*|manda\w*|volver\s+a\s+mandar|devolv[eé]\w*|'
            r'necesito|dame|quiero', t):
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
    guide_id = capture_name(id_text, r'\bgu[ií]a\b')
    if guide_id:
        result['identifier'] = guide_id
        result['identifier_type'] = 'guide'
    else:
        # Busca "de [Nombre]" — solo una palabra para evitar capturar "de Lark el 20/6"
        # Primera palabra after "de"/"para" que sea un nombre propio y no relleno
        for m_cli in re.finditer(r'\b(?:de|para)\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]{3,})', id_text, re.IGNORECASE):
            word = m_cli.group(1)
            if word.lower() in STOP_WORDS or _sin_tildes(word) in STOP_NOMBRE:
                continue
            result['identifier'] = word.title()
            result['identifier_type'] = 'client'
            break

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
        # "agrega el hotel Llao Llao al kayak de Lark" / "el hotel es Panamericano"
        result['new_value'] = capture_name(text, r'\bhotel\b', max_words=3) or _valor_final(text)

    elif action in ('add_extra', 'remove_extra'):
        result['new_value'] = detect_extras(text)

    elif action == 'update_agency':
        result['new_value'] = detect_agency(text)

    elif action == 'update_driver':
        result['new_value'] = detect_driver(text) or _valor_final(text)

    elif action == 'update_wetsuit':
        result['new_value'] = detect_wetsuit(text)

    elif action == 'update_personal':
        result['new_value'] = detect_personal(text)

    elif action == 'update_client':
        result['new_value'] = capture_name(text, r'\b(?:nombre|cliente)\b', max_words=3) or _valor_final(text)

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
