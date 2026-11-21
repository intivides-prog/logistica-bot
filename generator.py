"""
Generador de planillas Excel para todas las actividades.
Uso: generate(params, output_dir) → path del archivo generado

params keys: activity, site, pax, date, guide, client, hotel,
             hora, gastronomy_type, dietary_restrictions
"""
import os
import re
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# ── Estilos ────────────────────────────────────────────────────────────────────
_fl = Font(name="Arial", bold=True, size=10)
_fn = Font(name="Arial", size=10)
_fi = Font(name="Arial", size=10, color="0000CC")
_fa = Font(name="Arial", size=10, color="1A6B1A")
_fs = Font(name="Arial", size=9, color="777777", italic=True)

_sub  = PatternFill("solid", start_color="D6E4F0")
_inp  = PatternFill("solid", start_color="FFF9C4")
_auto = PatternFill("solid", start_color="E8F5E9")
_wht  = PatternFill("solid", start_color="FFFFFF")
_opt  = PatternFill("solid", start_color="F5F5F5")

_al = Alignment(horizontal="left",   vertical="center")
_ac = Alignment(horizontal="center", vertical="center")
_th = Side(style="thin", color="AAAAAA")
_bd = Border(left=_th, right=_th, top=_th, bottom=_th)

PAX = "$B$6"

# Reglas de bebidas (iguales en todas las salidas que las llevan)
CERVEZA = f"=INT({PAX}*1.5)"          # 1,5 por pax, redondeo hacia abajo
VINO    = f"=CEILING({PAX}/2,1)"      # 1 botella cada 2 pax
AGUA_15 = f"=CEILING({PAX}/4,1)"      # 1 cada 4 pax

# ── Helpers ────────────────────────────────────────────────────────────────────
def _sec(ws, row, text):
    ws.merge_cells(f"A{row}:C{row}")
    c = ws[f"A{row}"]
    c.value, c.font, c.alignment = text, Font(name="Arial", bold=True, size=10, color="FFFFFF"), _al
    c.fill = PatternFill("solid", start_color="2E4057")
    ws.row_dimensions[row].height = 18

def _hdr(ws, row):
    for col, txt in [("A","Item"),("B","Cantidad"),("C","Observaciones")]:
        c = ws[f"{col}{row}"]
        c.value, c.font, c.alignment, c.border = txt, Font(name="Arial", bold=True, size=10, color="FFFFFF"), _ac, _bd
        c.fill = PatternFill("solid", start_color="4A7FB5")
    ws.row_dimensions[row].height = 18

def _lv(ws, row, label, value="", mode="auto"):
    ws[f"A{row}"] = label
    ws[f"A{row}"].font, ws[f"A{row}"].fill = _fl, _sub
    ws[f"A{row}"].alignment, ws[f"A{row}"].border = _al, _bd
    ws[f"B{row}"] = value
    ws[f"B{row}"].font  = _fa if mode == "auto" else _fi
    ws[f"B{row}"].fill  = _auto if mode == "auto" else _inp
    ws[f"B{row}"].alignment, ws[f"B{row}"].border = _al, _bd
    ws[f"C{row}"].border = _bd
    ws.merge_cells(f"B{row}:C{row}")   # los datos de la salida ocupan todo el ancho
    ws.row_dimensions[row].height = 16

def _it(ws, row, label, val, mode="auto"):
    """
    mode: auto=formula/fijo, input=celda amarilla editable, optional=gris 'consultar con guía'
    """
    ws[f"A{row}"] = label
    ws[f"A{row}"].font, ws[f"A{row}"].alignment, ws[f"A{row}"].border = _fn, _al, _bd

    ws[f"B{row}"] = val
    ws[f"B{row}"].alignment, ws[f"B{row}"].border = _ac, _bd
    ws[f"C{row}"].border, ws[f"C{row}"].fill = _bd, _inp

    if mode == "input":
        ws[f"B{row}"].font, ws[f"B{row}"].fill = _fi, _inp
    elif mode == "optional":
        ws[f"B{row}"].font, ws[f"B{row}"].fill = _fs, _opt
    else:
        ws[f"B{row}"].font, ws[f"B{row}"].fill = _fn, _wht
    ws.row_dimensions[row].height = 16

def _gap(ws, row, h=6):
    ws.row_dimensions[row].height = h

def _drinks(ws, start_row):
    _sec(ws, start_row, "  BEBIDAS")
    _hdr(ws, start_row + 1)
    items = [
        ("Agua 600ml",       f"={PAX}"),
        ("Agua 1.5L",        AGUA_15),
        ("Cerveza",          CERVEZA),
        ("Vinos (botellas)", VINO),
    ]
    for i, (lbl, val) in enumerate(items):
        _it(ws, start_row + 2 + i, lbl, val)
    return start_row + 2 + len(items)

# ── Extras opcionales para días fríos ─────────────────────────────────────────
EXTRAS = {
    'infusiones': ("SET INFUSIONES / CAFÉ", [
        ("Caja de té",                   "1",          "auto"),
        ("Tazas (1 por pax + guía)",     f"={PAX}+1",  "auto"),
        ("Termo de agua caliente",       "1",          "input"),
    ]),
    'sopa': ("SOPA DE CALABAZA", [
        ("Sopa de calabaza (porciones)", f"={PAX}",    "auto"),
        ("Cuencos para sopa",            f"={PAX}",    "auto"),
    ]),
}
EXTRAS_LABEL = {'infusiones': 'infusiones/café', 'sopa': 'sopa de calabaza'}


def parse_extras(val) -> list:
    if not val:
        return []
    if isinstance(val, (list, tuple, set)):
        items = val
    else:
        items = str(val).split(',')
    return [e.strip() for e in items if e.strip() in EXTRAS]


def add_extras_sections(ws, start_row, extras) -> int:
    """Agrega las secciones de extras desde start_row. Devuelve la próxima fila libre."""
    row = start_row
    for key in parse_extras(extras):
        title, items = EXTRAS[key]
        _sec(ws, row, f"  {title}"); row += 1
        _hdr(ws, row);               row += 1
        for lbl, val, mode in items:
            _it(ws, row, lbl, val, mode=mode)
            row += 1
        _gap(ws, row); row += 1
    return row


def _personal_val(label, valor, params):
    """Si cargaron cuánto personal va, esa fila usa ese número."""
    if params.get('personal') is not None and _sin_acentos(label).startswith('personal'):
        return params['personal']
    return valor


def _sin_acentos(text: str) -> str:
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).lower())
                   if unicodedata.category(c) != 'Mn')


def _cabecera(ws, params):
    fecha = params.get('date')
    fecha_str = fecha.strftime('%d/%m/%Y') if isinstance(fecha, date) else (fecha or '')
    _sec(ws, 1, "  DATOS DE LA SALIDA")
    _lv(ws, 2,  "SALIDA:",            params.get('activity') or '', mode="auto")
    _lv(ws, 3,  "SITIO:",             params.get('site') or '',     mode="input")
    _lv(ws, 4,  "FECHA:",             fecha_str,                    mode="auto")
    _lv(ws, 5,  "HORA DE RETIRO:",    params.get('hora') or '',     mode="input")
    _lv(ws, 6,  "CANT. PAX:",         params.get('pax') or 0,      mode="auto")
    _lv(ws, 7,  "NOMBRE:",            params.get('client') or '',   mode="input")
    _lv(ws, 8,  "CLIENTE / AGENCIA:", params.get('agency') or '',   mode="input")
    _lv(ws, 9,  "HOTEL:",             params.get('hotel') or '',    mode="input")
    _lv(ws, 10, "GUIA:",              params.get('guide') or '',    mode="input")
    _lv(ws, 11, "CONDUCTOR:",         params.get('driver') or '',   mode="input")
    _lv(ws, 12, "RESTRICCIONES:",     params.get('dietary_restrictions') or 'Ninguna', mode="input")
    ws["A6"].font = Font(name="Arial", bold=True, size=10, color="CC0000")
    ws["B6"].font = Font(name="Arial", bold=True, size=11, color="1A6B1A")
    ws["B6"].fill = _auto
    _gap(ws, 13)

# ── Templates de secciones ─────────────────────────────────────────────────────
# Cada item: (label, value, mode)
# mode: "auto" | "input" | "optional"
# "optional" → value se ignora, muestra "consultar con guía"
OPT = "consultar con guía"

def _get_almuerzo_campestre_rows(mesa4_row, mesa2_row, barco=False):
    """Items del almuerzo campestre. mesa4_row y mesa2_row son las filas de las mesas para referencia."""
    m4 = f"B{mesa4_row}"
    m2 = f"B{mesa2_row}"
    return [
        (f"Mesa roja (de 4 personas)",             f"=INT(({PAX}+1)/4)",                              "auto"),
        (f"Mesa (de 2 personas)",                  f"=IF(AND(MOD({PAX},4)>=1,MOD({PAX},4)<=2),1,0)", "auto"),
        ("Sillitas de camping azules",             f"={PAX}",                                         "auto"),
        ("Mantitas norteñas",                      f"={PAX}",                                         "auto"),
        ("Manta cuadros turquesa",                 "1",                                               "auto"),
        ("Copas grandes (vino)",                   f"={PAX}",                                         "auto"),
        ("Copas chicas (agua)",                    f"={PAX}",                                         "auto"),
        ("Tenedores",                              f"={PAX}",                                         "auto"),
        ("Cucharitas (postre / cafe)",             f"={PAX}",                                         "auto"),
        ("Cuchillos",                              f"={PAX}",                                         "auto"),
        ("Cuchara ensalada",                       "1 juego",                                         "auto"),
        ("Destapador",                             "1",                                               "auto"),
        ("Cuencos ceramicos (sopa/dips)",          f"=IF({PAX}<=4,2,IF({PAX}<=7,3,4))",              "auto"),
        ("Cucharita madera",                       f"=IF({PAX}<=4,2,IF({PAX}<=7,3,4))",              "auto"),
        ("Servilletas / pax",                      "varios",                                          "auto"),
        ("Servilletas rollo cocina",               "varios",                                          "auto"),
        ("Servilleteros",                          "1",                                               "auto"),
        ("Paneras tela",                           "1",                                               "auto"),
        ("Individuales tela",                      f"={PAX}" if barco else "/",                      "auto"),
        ("Platos cerámica (principal)" if barco else "Platos principal", f"={PAX}",                  "auto"),
        ("Platos ceramicos kawen (postre)",        f"=IF({PAX}<=4,1,IF({PAX}<=8,2,3))",              "auto"),
        ("Tablas de madera",                       f"=CEILING({PAX}/2,1)",                            "auto"),
        ("Ensaladera madera",                      "1",                                               "auto"),
        ("Broches mantel",                         f"={m4}+{m2}",                                    "auto"),
        ("Manteles",                               f"={m4}+{m2}",                                    "auto"),
        ("Caminos",                                f"={m4}+{m2}",                                    "auto"),
        ("Alcohol gel",                            "1",                                               "auto"),
        ("Bolsas de basura",                       "varios",                                          "auto"),
    ]

TEMPLATES = {

    'FD Kayak': {
        'gastronomy_title': 'GASTRONOMIA — Almuerzo Campestre FD',
        'equipment': [
            ("Guantes (pares)",                    f"={PAX}",   "auto"),
            ("Mitones para los remos (sin talle)", "2",         "auto"),
            ("Botitas neopreno (talles)",          "",          "input"),
            ("Chaleco / PFD (talles)",            "",          "input"),
            ("Chaqueta impermeable (talles)",     "",          "input"),
            ("Copit / cubre (talle unico)",       f"={PAX}",   "auto"),
            ("Culotes / asientos kayak",           f"={PAX}+1", "auto"),
            ("Bomba achique",                      "1",         "auto"),
            ("Bolsas secas",                       "1",         "auto"),
            ("Remos",                              f"={PAX}",   "auto"),
            ("Remos / palas desmontables negras",  f"={PAX}+1", "auto"),
            ("Radio / Handys",                     "2",         "auto"),
        ],
        'gastronomy': None,   # se genera dinámicamente (almuerzo campestre)
        'gastronomy_type': 'AC',
    },

    'HD Kayak': {
        'gastronomy_title': 'GASTRONOMIA — Snacks HD',
        'equipment': [
            ("Guantes (pares)",                    f"={PAX}",   "auto"),
            ("Mitones para los remos (sin talle)", "2",         "auto"),
            ("Botitas neopreno (talles)",          "",          "input"),
            ("Chaleco / PFD (talles)",            "",          "input"),
            ("Chaqueta impermeable (talles)",     "",          "input"),
            ("Copit / cubre (talle unico)",       f"={PAX}",   "auto"),
            ("Culotes / asientos kayak",           f"={PAX}",   "auto"),
            ("Bomba achique",                      "1",         "auto"),
            ("Bolsas secas",                       "3",         "auto"),
            ("Remos",                              f"={PAX}",   "auto"),
            ("Remos / palas desmontables negras",  "1",         "auto"),
            ("Radio / Handys",                     "2",         "auto"),
        ],
        'gastronomy': [
            ("Tazas te",                           f"={PAX}",   "auto"),
            ("Cucharitas te",                      f"={PAX}",   "auto"),
            ("Caja de te madera",                  "1",         "auto"),
            ("Termo agua",                         "1",         "auto"),
            ("Mesa pequeña",                       "1",         "auto"),
            ("Mantel verde",                       "1",         "auto"),
            ("Mantitas norteñas",                  f"={PAX}",   "auto"),
            ("Sillitas camping",                   f"={PAX}",   "auto"),
            ("Bolsas de residuos",                 "varios",    "auto"),
            ("Servilletas",                        "varios",    "auto"),
            ("Alcohol gel",                        "1",         "auto"),
            ("Pinza comida",                       "1",         "auto"),
            ("Cuchillo",                           "1",         "auto"),
            ("Tabla de madera + ceramica kawen",   "1 + 1",     "auto"),
            ("— COMIDA —",                         "",          "auto"),
            ("Agua",                               f"={PAX}",   "auto"),
            ("Brownie",                            f"={PAX}",   "auto"),
            ("Budin",                              "varios",    "auto"),
            ("Cookies",                            "varios",    "auto"),
            ("Sandwich de miga",                   "varios",    "auto"),
        ],
        'gastronomy_type': 'snacks',
        'no_drinks': True,   # bebidas integradas en snacks section
    },

    'FD MTB': {
        'gastronomy_title': 'GASTRONOMIA — Box Lunch',
        'equipment': [
            ("Guantes",         f"={PAX}", "auto"),
            ("Ponchos lluvia",  f"={PAX}", "auto"),
            ("Radios",          "2",       "auto"),
        ],
        'gastronomy': [
            ("BLT",             f"={PAX}", "auto"),
            ("Personal (guia + conductor — ajustar si hay backup)", "2", "input"),
            ("Aguas 600ml",     f"={PAX}", "auto"),
            ("Agua 1.5L",       AGUA_15,   "auto"),
        ],
        'no_drinks': True,
        'gastronomy_type': 'BL',
    },

    'FD Trekking': {
        # Frey, Cerro Goye y Bella Vista comparten planilla. Solo agua.
        'gastronomy_title': 'GASTRONOMIA — Box Lunch Trekking',
        'equipment': [
            ("Bastones",  "pedir si necesita", "input"),
            ("Radios",    "/",                 "auto"),
            ("Polainas",  "/",                 "auto"),
        ],
        'gastronomy': [
            ("BLTREK",       f"={PAX}", "auto"),
            ("Personal",     "1",       "input"),
            ("Aguas 600ml",  f"={PAX}", "auto"),
            ("Agua 1.5L",    AGUA_15,   "auto"),
        ],
        'no_drinks': True,
        'gastronomy_type': 'BL',
    },

    'Bariloche Hiking': {
        'gastronomy_title': 'GASTRONOMIA — Box Lunch Trekking',
        'equipment': [
            ("Bastones",  "/", "auto"),
            ("Radios",    "/", "auto"),
        ],
        'gastronomy': [
            ("BLT",                 f"={PAX}", "auto"),
            ("Box lunch personal",  "2",       "input"),
            ("Aguas 600ml",         f"={PAX}", "auto"),
            ("Agua 1.5L",           AGUA_15,   "auto"),
        ],
        'no_drinks': True,
        'gastronomy_type': 'BL',
    },

    'Montañas y Glaciares del Tronador': {
        # Según planilla modelo (2 pax). Con más pax solo escalan box lunch y bebidas;
        # vasos y sillitas también.
        'gastronomy_title': 'GASTRONOMIA — Box Lunch Gourmet',
        'equipment': [
            ("Bastones",            "/",  "auto"),
            ("Radios",              "/",  "auto"),
            ("Vasos",               f"={PAX}",  "auto"),
            ("Sacacorchos",         "1",  "auto"),
            ("Mesa",                "1",  "auto"),
            ("Mantel",              "1",  "auto"),
            ("Sillitas de camping", f"={PAX}",  "auto"),
        ],
        'gastronomy': [
            ("BLgourmet",  f"={PAX}", "auto"),
            ("Personal (guía + conductor)", "2", "input"),
            ("Cerveza",    CERVEZA, "auto"),
            ("Agua",       f"={PAX}",   "auto"),
            ("Agua 1.5L",  "/",         "auto"),
            ("Vino",       VINO, "auto"),
        ],
        'no_drinks': True,   # las bebidas van dentro de GASTRONOMIA, como en la planilla modelo
        'gastronomy_type': 'BL',
    },

    'Rios y Lagos del Limay': {
        'gastronomy_title': 'GASTRONOMIA — Box Lunch Gourmet',
        'equipment': [
            ("Bastones",  OPT,       "optional"),
            ("Mantitas",  f"={PAX}", "auto"),
            ("Radios",    "2",       "auto"),
        ],
        'gastronomy': [
            ("BLgourmet",  f"={PAX}", "auto"),
            ("Personal (guia + conductor — ajustar si hay backup)", "2", "input"),
        ],
        'gastronomy_type': 'BL',
    },

    'Navegacion Regular': {
        'gastronomy_title': 'GASTRONOMIA',
        'equipment': [
            ("Bastones",          OPT, "optional"),
            ("Radios",            OPT, "optional"),
            ("Ponchos de lluvia", OPT, "optional"),
        ],
        'gastronomy': [
            ("BLT",               f"={PAX}", "auto"),
            ("Personal (guia + conductor — ajustar si hay backup)", "2", "input"),
            ("Aguas 600ml",       f"={PAX}", "auto"),
            ("Agua 1.5L",         AGUA_15,   "auto"),
        ],
        'no_drinks': True,
        'gastronomy_type': 'BL',
    },

    'Navegacion AC': {
        # Navegación privada: mismo almuerzo campestre que el kayak FD (con mobiliario),
        # + individuales de tela por pax y platos principales de cerámica.
        'gastronomy_title': 'GASTRONOMIA — Almuerzo Campestre (Navegación privada)',
        'equipment': [
            ("Bastones",          OPT, "optional"),
            ("Radios",            OPT, "optional"),
            ("Ponchos de lluvia", OPT, "optional"),
        ],
        'gastronomy': None,   # almuerzo campestre dinámico
        'barco': True,
        'gastronomy_type': 'AC',
    },

    'Valle Encantado Pollo': {
        'gastronomy_title': 'CATERING — Pollo al disco Valle Encantado',
        'default_site': 'Valle Encantado',
        'equipment': [
            ("Bastones",  "pedir de ser necesario", "input"),
            ("Radios",    "/",                      "auto"),
            ("Heladeras", "2",                      "auto"),
        ],
        'gastronomy': [
            ("Pollo al disco", f"={PAX}", "auto"),
            ("Flan",           f"={PAX}", "auto"),
            ("Crema",          "/",       "input"),
            ("Dulce de leche", "/",       "input"),
            ("Pan",            "varios",  "auto"),
            ("Café",           "1",       "auto"),
        ],
        'gastronomy_type': 'valle',
    },

    'Valle Asado': {
        'gastronomy_title': 'CATERING — Asado Valle Encantado',
        'equipment': [
            ("Bastones / Radios", OPT, "optional"),
            ("Heladera comida",   "1", "auto"),
            ("Heladera bebidas",  "1", "auto"),
        ],
        'gastronomy': [
            ("Empanadas (humita)",              f"={PAX}",                "auto"),
            ("Colita de cuadril",               f"=CEILING({PAX}/2,1)",  "auto"),
            ("Chori de cerdo",                  f"={PAX}",                "auto"),
            ("Morcilla",                        f"={PAX}",                "auto"),
            ("Cerdo",                           f"=CEILING({PAX}/2,1)",  "auto"),
            ("Pan",                             "1 kg",                   "input"),
            ("Ensaladas",                       "varias",                 "input"),
            ("Verduras para parrilla",          "varias",                 "input"),
            ("Dulce de leche",                  "1",                      "auto"),
            ("Postre / Flan",                   f"={PAX}",                "auto"),
            ("Crema",                           "1",                      "auto"),
            ("Café",                            "1",                      "auto"),
            ("Carbón",                          "1",                      "auto"),
            ("Leña",                            "1",                      "auto"),
        ],
        'gastronomy_type': 'asado',
    },

    'Brazo Tristeza REG TRF PVT': {
        'gastronomy_title': 'GASTRONOMIA — Box Lunch Trekking',
        'default_site': 'Brazo Tristeza',
        'equipment': [
            ("Bastones", OPT, "optional"),
            ("Radios",   OPT, "optional"),
        ],
        'gastronomy': [
            ("BLT",          f"={PAX}", "auto"),
            ("Personal",     "1",       "input"),
            ("Aguas 600ml",  f"={PAX}", "auto"),
            ("Agua 1.5L",    AGUA_15,   "auto"),
        ],
        'no_drinks': True,
        'gastronomy_type': 'BL',
    },

    'HD Hiking Cerro Llao-Llao': {
        'gastronomy_title': 'GASTRONOMIA — Snacks de marcha',
        'default_site': 'Cerro Llao Llao',
        'equipment': [
            ("Bastones", OPT, "optional"),
            ("Radios",   OPT, "optional"),
        ],
        'gastronomy': [
            ("Snacks de marcha", f"={PAX}", "auto"),
            ("Personal",         "1",       "input"),
            ("Aguas 600ml",      f"={PAX}", "auto"),
            ("Agua 1.5L",        AGUA_15,   "auto"),
        ],
        'no_drinks': True,
        'gastronomy_type': 'snacks',
    },

    'FD Valle Encantado Hiking': {
        'gastronomy_title': 'GASTRONOMIA — Box Lunch Trekking',
        'default_site': 'Valle Encantado',
        'equipment': [
            ("Bastones", OPT, "optional"),
            ("Radios",   OPT, "optional"),
        ],
        'gastronomy': [
            ("BLT",          f"={PAX}", "auto"),
            ("Personal",     "1",       "input"),
            ("Aguas 600ml",  f"={PAX}", "auto"),
            ("Agua 1.5L",    AGUA_15,   "auto"),
        ],
        'no_drinks': True,
        'gastronomy_type': 'BL',
    },
}

# Alias para parsear variantes del nombre
# ── Variantes: mismo contenido, otro nombre / destino ─────────────────────────
import copy as _copy

def _variant(base, **changes):
    t = _copy.deepcopy(TEMPLATES[base])
    t.update(changes)
    return t

# Trucha: igual que pollo al disco, cambia solo el plato principal
TEMPLATES['Valle Encantado Trucha'] = _variant(
    'Valle Encantado Pollo',
    gastronomy_title='CATERING — Trucha Valle Encantado',
    gastronomy=[("Trucha", f"={PAX}", "auto")] + _copy.deepcopy(TEMPLATES['Valle Encantado Pollo']['gastronomy'][1:]),
)
# Misma gastronomía que Limay (box lunch gourmet)
TEMPLATES['Lagos y Cascadas del Manso'] = _variant('Rios y Lagos del Limay', default_site='Cascada de los Alerces')
TEMPLATES['San Martin de los Andes']   = _variant('Rios y Lagos del Limay', default_site='San Martín de los Andes')
# Trekkings: misma planilla, cambia el destino
TEMPLATES['FD Trekking Frey']             = _variant('FD Trekking', default_site='Base Cerro Catedral')
TEMPLATES['FD Trekking Bella Vista / Goye'] = _variant('FD Trekking', default_site='Bella Vista / Cerro Goye')
# Mismo equipo y gastronomía que los otros trekkings y MTB, cambia el destino
TEMPLATES['FD Trekking Cerro Centinela'] = _variant('FD Trekking', default_site='Cerro Centinela (VLA)')
TEMPLATES['HD MTB Bosque de Arrayanes'] = _variant('FD MTB', default_site='Bosque de Arrayanes (VLA)')
# Valle Asado: sitio por defecto
TEMPLATES['Valle Asado'].setdefault('default_site', 'Valle Encantado')
TEMPLATES['Rios y Lagos del Limay'].setdefault('default_site', 'Río Limay')
TEMPLATES['Bariloche Hiking'].setdefault('default_site', 'Llao Llao')
TEMPLATES['Montañas y Glaciares del Tronador'].setdefault('default_site', 'Tronador')


# Código corto que se usa en la reconfirmación de gastronomía de las 11.
# ⚠️ Si alguno no coincide con cómo lo nombran ustedes, cambiar acá.
GASTRO_CODES = {
    'FD Kayak':                        'AC',
    'FD Kayak y Trekking':             'AC',
    'Navegacion AC':                   'AC',
    'HD Kayak':                        'SNACK KAYAK',
    'Montañas y Glaciares del Tronador': 'BLG',
    'Rios y Lagos del Limay':          'BLG',
    'Lagos y Cascadas del Manso':      'BLG',
    'San Martin de los Andes':         'BLG',
    'FD Trekking':                     'BLT',
    'FD Trekking Frey':                'BLT',
    'FD Trekking Bella Vista / Goye':  'BLT',
    'Bariloche Hiking':                'BLT',
    'FD MTB':                          'BLT',
    'Navegacion Regular':              'BLT',
    'Valle Asado':                     'EEPP',
    'Valle Encantado Pollo':           'EPP',
    'Valle Encantado Trucha':          'EPP',
    'Brazo Tristeza REG TRF PVT':      'BLT',
    'HD Hiking Cerro Llao-Llao':       'SNACK MARCHA',
    'FD Valle Encantado Hiking':       'BLT',
    'FD Trekking Cerro Centinela':     'BLT',
    'HD MTB Bosque de Arrayanes':      'BLT',
}

# Cuánto personal lleva cada salida por defecto (guía + conductor, o solo guía)
PERSONAL_DEFAULT = {
    'FD Trekking': 1, 'FD Trekking Frey': 1, 'FD Trekking Bella Vista / Goye': 1,
    'FD Trekking Cerro Centinela': 1, 'Brazo Tristeza REG TRF PVT': 1,
    'HD Hiking Cerro Llao-Llao': 1,
}


# Cómo se escribe cada salida en la planilla DESPACHOS.
# Si el nombre cambia según el sitio, va la plantilla con {sitio}.
DESPACHO_NOMBRES = {
    'FD Kayak':                        'FD KAYAK/KAYAK Y TREKKING {sitio_corto}',
    'HD Kayak':                        'HD KAYAK {sitio}',
    'Montañas y Glaciares del Tronador': 'FD MONTAÑAS Y GLACIARES DEL TRONADOR',
    'Rios y Lagos del Limay':          'RIOS Y LAGOS DEL LIMAY',
    'Lagos y Cascadas del Manso':      'LAGOS Y CASCADAS DEL MANSO',
    'San Martin de los Andes':         'FD SAN MARTIN DE LOS ANDES',
    'FD Trekking':                     'FD TREKKING {sitio}',
    'FD Trekking Frey':                'FD TREKKING FREY AGUJAS DEL CATEDRAL',
    'FD Trekking Bella Vista / Goye':  'FD TREKKING BELLA VISTA/GOYE',
    'FD Trekking Cerro Centinela':     'FD TREKKING CERRO CENTINELA (VLA)',
    'Bariloche Hiking':                'BARILOCHE HIKING',
    'HD Hiking Cerro Llao-Llao':       'HD HIKING CERRO LLAO-LLAO',
    'FD Valle Encantado Hiking':       'FD VALLE ENCANTADO HIKING',
    'Brazo Tristeza REG TRF PVT':      'BRAZO TRISTEZA REG TRF PVT Y GUIA',
    'Navegacion AC':                   'NAVEGACION BRAZO TRISTEZA/ISLA PVT',
    'Navegacion Regular':              'NAVEGACION REGULAR',
    'FD MTB':                          'HD MTB {sitio}',
    'HD MTB Bosque de Arrayanes':      'HD MTB BOSQUE DE ARRAYANES (VLA)',
    'Valle Asado':                     'VALLE ENCANTADO ASADO',
    'Valle Encantado Pollo':           'VALLE ENCANTADO POLLO',
    'Valle Encantado Trucha':          'VALLE ENCANTADO TRUCHA',
}

# La navegación en Villa La Angostura tiene nombre propio
DESPACHO_POR_SITIO = {
    ('Navegacion AC', 'villa la angostura'):      'VILLA LA ANGOSTURA FD',
    ('Navegacion Regular', 'villa la angostura'): 'NAVEGACION BAYS AND FOREST (VLA)',
}


def despacho_nombre(activity: str, site: str = None) -> str:
    """El nombre de la salida tal como se escribe en la planilla DESPACHOS."""
    act = resolve_activity(activity or '')
    sitio = (site or default_site(act) or '').strip()
    especial = DESPACHO_POR_SITIO.get((act, _sin_acentos(sitio)))
    if especial:
        return especial
    plantilla = DESPACHO_NOMBRES.get(act)
    if not plantilla:
        return (act or '').upper()
    if '{sitio' in plantilla:
        corto = re.sub(r'^(?:lago|r[ií]o|base|cerro)\s+', '', sitio, flags=re.IGNORECASE)
        return plantilla.format(sitio=sitio.upper(), sitio_corto=corto.upper()).strip()
    return plantilla


def gastro_code(activity: str) -> str:
    act = resolve_activity(activity or '')
    return GASTRO_CODES.get(act, 'BL')


def default_personal(activity: str) -> int:
    return PERSONAL_DEFAULT.get(resolve_activity(activity or ''), 2)


# Las cuatro salidas con BLG cargan siempre el mismo equipo y mobiliario
BLG_EQUIPO = [
    ("Bastones",            OPT,       "optional"),
    ("Radios",              OPT,       "optional"),
    ("Mantitas norteñas",   f"={PAX}", "auto"),
    ("Mesa",                "1",       "auto"),
    ("Mantel",              "1",       "auto"),
    ("Sillitas de camping", f"={PAX}", "auto"),
    ("Vasos",               f"={PAX}", "auto"),
    ("Sacacorchos",         "1",       "auto"),
]
for _blg in ('Montañas y Glaciares del Tronador', 'Rios y Lagos del Limay',
             'Lagos y Cascadas del Manso', 'San Martin de los Andes'):
    TEMPLATES[_blg]['equipment'] = [tuple(fila) for fila in BLG_EQUIPO]


def default_site(activity: str):
    t = TEMPLATES.get(resolve_activity(activity or ''))
    return t.get('default_site') if t else None


ACTIVITY_ALIASES = {
    'fd kayak y trekking': 'FD Kayak',
    'fd kayak':            'FD Kayak',
    'kayak mascardi':      'FD Kayak',
    'hd kayak':            'HD Kayak',
    'kayak snacks':        'HD Kayak',
    'mtb':                 'FD MTB',
    'fd mtb':              'FD MTB',
    'trekking':            'FD Trekking',
    'fd trekking':         'FD Trekking',
    'tronador':            'Montañas y Glaciares del Tronador',
    'montañas y glaciares':'Montañas y Glaciares del Tronador',
    'limay':               'Rios y Lagos del Limay',
    'rios y lagos':        'Rios y Lagos del Limay',
    'navegacion regular':  'Navegacion Regular',
    'navegacion':          'Navegacion Regular',
    'navegacion ac':       'Navegacion AC',
    'navegacion pvt':      'Navegacion AC',
    'barco':               'Navegacion Regular',
    'valle asado':         'Valle Asado',
    'asado':               'Valle Asado',
    'valle encantado pollo': 'Valle Encantado Pollo',
    'valle encantado trucha': 'Valle Encantado Trucha',
    'trekking':            'FD Trekking',
    'bariloche hiking':    'Bariloche Hiking',
    'brc hiking':          'Bariloche Hiking',
    'cascada de los alerces': 'Lagos y Cascadas del Manso',
    'lagos y cascadas del manso': 'Lagos y Cascadas del Manso',
    'san martin de los andes': 'San Martin de los Andes',
    'frey':                'FD Trekking Frey',
    'goye':                'FD Trekking Bella Vista / Goye',
    'bella vista':         'FD Trekking Bella Vista / Goye',
    'centinela':           'FD Trekking Cerro Centinela',
    'arrayanes':           'HD MTB Bosque de Arrayanes',
    'brazo tristeza':      'Brazo Tristeza REG TRF PVT',
    'cerro llao llao':     'HD Hiking Cerro Llao-Llao',
    'valle encantado hiking': 'FD Valle Encantado Hiking',
}


def resolve_activity(raw: str) -> str:
    """Convierte el nombre parseado al nombre canónico del template."""
    import unicodedata
    key = raw.lower().strip()
    key_sin_tildes = ''.join(c for c in unicodedata.normalize('NFD', key)
                             if unicodedata.category(c) != 'Mn')
    return ACTIVITY_ALIASES.get(key) or ACTIVITY_ALIASES.get(key_sin_tildes, raw)


def generate(params: dict, output_dir: str = ".") -> str:
    activity_raw = params.get('activity') or 'FD Kayak'
    activity     = resolve_activity(activity_raw)
    tmpl         = TEMPLATES.get(activity, TEMPLATES['FD Kayak'])

    pax   = params.get('pax') or 0
    fecha = params.get('date')
    fecha_str = fecha.strftime('%d/%m/%Y') if isinstance(fecha, date) else (fecha or '')

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\\/*?:\[\]]', '-', activity)[:28]   # Excel no admite / \\ * ? : [ ] y máx. 31 caracteres
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 30

    # CABECERA
    _cabecera(ws, {**params, 'activity': activity,
                   'site': params.get('site') or tmpl.get('default_site')})

    # EQUIPAMIENTO
    equip = tmpl.get('equipment', [])
    row = 14
    _sec(ws, row, "  EQUIPAMIENTO");   row += 1
    _hdr(ws, row);                     row += 1
    talles = params.get('wetsuit')
    usados = False
    for lbl, val, mode in equip:
        display = OPT if mode == "optional" else val
        # Si ya hay una fila de botitas, los talles van ahí en vez de repetirse abajo
        if talles and not usados and re.search(r'botita.*talle', _sin_acentos(lbl)):
            display, mode, usados = talles, "input", True
        _it(ws, row, lbl, display, mode=mode)
        row += 1
    if talles and not usados:
        _it(ws, row, "Botitas neoprene (talles)", talles, mode="input")
        row += 1
    _gap(ws, row); row += 1

    # GASTRONOMIA
    gast_title = tmpl.get('gastronomy_title', 'GASTRONOMIA')
    _sec(ws, row, f"  {gast_title}"); row += 1
    _hdr(ws, row);                    row += 1

    gastronomy = tmpl.get('gastronomy')
    if gastronomy is None:
        # Almuerzo campestre kayak FD (con referencia a filas de mesas)
        mesa4_row = row  # B de esta fila = mesas de 4
        mesa2_row = row + 1
        rows_data = _get_almuerzo_campestre_rows(mesa4_row, mesa2_row, barco=tmpl.get('barco', False))
        for lbl, val, mode in rows_data:
            _it(ws, row, lbl, _personal_val(lbl, val, params), mode=mode)
            row += 1
    else:
        for lbl, val, mode in gastronomy:
            display = OPT if mode == "optional" else val
            _it(ws, row, lbl, _personal_val(lbl, display, params), mode=mode)
            row += 1

    _gap(ws, row); row += 1

    # BEBIDAS (salvo HD Kayak que las integra en snacks)
    if not tmpl.get('no_drinks'):
        row = _drinks(ws, row)
        _gap(ws, row); row += 1

    # EXTRAS (infusiones / sopa), si se pidieron
    add_extras_sections(ws, row, params.get('extras'))

    # Guardar
    # Nombre: "16-11 Valle Encantado Asado x2.xlsx"
    # (la barra no se puede usar en un nombre de archivo, por eso 16-11 y no 16/11)
    date_slug = fecha.strftime('%d-%m') if isinstance(fecha, date) else 'sin fecha'
    nombre_act = re.sub(r'[\\/*?:\[\]]', '-', activity).strip()
    filename  = f"{date_slug} {nombre_act} x{pax}.xlsx"
    filepath  = os.path.join(output_dir, filename)
    wb.save(filepath)
    return filepath
