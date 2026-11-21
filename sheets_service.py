"""
Escribe las reservas en la planilla DESPACHOS de Google Sheets.

La planilla está agrupada por día: una fila combinada con la fecha y, debajo,
una fila por cada despacho de ese día. Este módulo busca el bloque del día,
mete la fila donde corresponde y, si ese día todavía no existe, crea el bloque
en orden cronológico.

Requiere:
  GOOGLE_CREDENTIALS_JSON   las credenciales de la cuenta de servicio
  DESPACHOS_SHEET_ID        el id de la planilla (compartida con esa cuenta)
"""
import os
import re
import json
import logging
import unicodedata
from datetime import date

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

MESES = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
         'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
         'noviembre': 11, 'diciembre': 12}
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']

# Columnas de la planilla, en orden
COLUMNAS = ['Horario entrega', 'Cliente', 'Cantidad pax', 'Hotel', 'Actividad',
            'Detalles', 'Guía', 'Transporte', 'Observaciones']
PRIMERA_FILA_DATOS = 3      # fila 1 título, fila 2 encabezados


def _id_planilla():
    crudo = os.environ.get('DESPACHOS_SHEET_ID', '').strip()
    if not crudo:
        return None
    m = re.search(r'/spreadsheets/d/([A-Za-z0-9_-]+)', crudo)
    return m.group(1) if m else re.split(r'[?#/\s]', crudo)[0] or None


def disponible() -> bool:
    return bool(GOOGLE_AVAILABLE and os.environ.get('GOOGLE_CREDENTIALS_JSON') and _id_planilla())


def _servicio():
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ['GOOGLE_CREDENTIALS_JSON']), scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)


def _sin_tildes(texto) -> str:
    t = unicodedata.normalize('NFD', str(texto or '').lower())
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn')


# ── Leer la estructura de la planilla ─────────────────────────────────────────

def leer_fecha(texto):
    """
    Entiende las fechas de las filas separadoras, en cualquiera de sus formas:
    'miércoles, 28 de octubre de 2026' · '29/10/2026 - EVENTO ROFINA' · '5/11/2026'
    """
    t = _sin_tildes(texto).strip()
    if not t:
        return None
    m = re.search(r'(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})', t)
    if m:
        mes = MESES.get(m.group(2))
        if mes:
            try:
                return date(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                return None
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', t)
    if m:
        anio = int(m.group(3))
        anio = anio + 2000 if anio < 100 else anio
        try:
            return date(anio, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _es_separador(fila) -> bool:
    """Una fila separadora trae la fecha en la primera celda y el resto vacío o repetido."""
    if not fila or not str(fila[0]).strip():
        return False
    if leer_fecha(fila[0]) is None:
        return False
    resto = [str(c).strip() for c in fila[1:] if str(c).strip()]
    return all(c == str(fila[0]).strip() for c in resto)


def _mapa_de_dias(valores) -> list:
    """
    Recorre la planilla y devuelve un bloque por día:
    {'fecha', 'titulo', 'fila_separador', 'primera', 'ultima'}  (filas 1-based)
    """
    bloques = []
    for i, fila in enumerate(valores):
        nro = i + 1
        if nro < PRIMERA_FILA_DATOS or not _es_separador(fila):
            continue
        if bloques:
            bloques[-1]['ultima'] = nro - 1
        bloques.append({'fecha': leer_fecha(fila[0]), 'titulo': str(fila[0]).strip(),
                        'fila_separador': nro, 'primera': nro + 1, 'ultima': None})
    if bloques:
        bloques[-1]['ultima'] = len(valores)
    return bloques


def _leer_todo(service, planilla_id, hoja):
    res = service.spreadsheets().values().get(
        spreadsheetId=planilla_id, range=f"'{hoja}'!A:I").execute()
    return res.get('values', [])


def _primera_hoja(service, planilla_id):
    meta = service.spreadsheets().get(spreadsheetId=planilla_id,
                                      fields='sheets(properties(sheetId,title))').execute()
    props = meta['sheets'][0]['properties']
    return props['title'], props['sheetId']


# ── Armar la fila a partir de una salida ──────────────────────────────────────

def armar_fila(exc: dict) -> list:
    """Pasa una salida del bot a las nueve columnas de la planilla."""
    import generator

    pax = exc.get('pax')
    personal = exc.get('personal')
    if personal is None:
        personal = generator.default_personal(exc.get('activity') or '')
    cantidad = f"{pax} + {personal} perso" if pax else ''

    codigo = generator.gastro_code(exc.get('activity') or '')
    detalles = f"{pax} {codigo} + {personal} perso" if pax else codigo
    if exc.get('dietary_restrictions'):
        import scheduler
        cortas = scheduler._restricciones_cortas(exc['dietary_restrictions'])
        detalles += f" ({cortas})" if cortas else ''
    extras = generator.parse_extras(exc.get('extras'))
    if extras:
        detalles += ' + ' + ' + '.join(generator.EXTRAS_LABEL[e] for e in extras)

    observaciones = ''
    if exc.get('cancelled'):
        observaciones = 'CANCELADO'

    return [
        exc.get('hora_entrega') or '',
        exc.get('client') or exc.get('agency') or '',
        cantidad,
        exc.get('hotel') or '',
        generator.despacho_nombre(exc.get('activity') or '', exc.get('site')),
        detalles,
        (exc.get('guide') or '').upper(),
        (exc.get('driver') or '').upper(),
        observaciones,
    ]


def _titulo_de_fecha(fecha: date) -> str:
    return f"{DIAS[fecha.weekday()]}, {fecha.day} de " \
           f"{[k for k, v in MESES.items() if v == fecha.month][0]} de {fecha.year}"


# ── Escribir ──────────────────────────────────────────────────────────────────

def _insertar_filas(service, planilla_id, hoja_id, desde, cuantas=1):
    service.spreadsheets().batchUpdate(
        spreadsheetId=planilla_id,
        body={'requests': [{'insertDimension': {
            'range': {'sheetId': hoja_id, 'dimension': 'ROWS',
                      'startIndex': desde - 1, 'endIndex': desde - 1 + cuantas},
            'inheritFromBefore': False,
        }}]}).execute()


def _combinar(service, planilla_id, hoja_id, fila):
    service.spreadsheets().batchUpdate(
        spreadsheetId=planilla_id,
        body={'requests': [{'mergeCells': {
            'range': {'sheetId': hoja_id, 'startRowIndex': fila - 1, 'endRowIndex': fila,
                      'startColumnIndex': 0, 'endColumnIndex': 9},
            'mergeType': 'MERGE_ALL',
        }}]}).execute()


def _escribir(service, planilla_id, hoja, fila, valores):
    service.spreadsheets().values().update(
        spreadsheetId=planilla_id, range=f"'{hoja}'!A{fila}:I{fila}",
        valueInputOption='USER_ENTERED', body={'values': [valores]}).execute()


def agregar_despacho(exc: dict) -> dict:
    """
    Escribe la salida en la planilla, dentro del bloque de su fecha.
    Devuelve {'ok', 'fila', 'dia_nuevo', 'error'}.
    """
    if not disponible():
        return {'ok': False, 'error': 'La planilla DESPACHOS no está configurada.'}

    fecha = exc.get('date')
    if isinstance(fecha, str):
        try:
            fecha = date.fromisoformat(fecha[:10])
        except ValueError:
            fecha = None
    if not fecha:
        return {'ok': False, 'error': 'La salida no tiene fecha.'}

    planilla_id = _id_planilla()
    try:
        service = _servicio()
        hoja, hoja_id = _primera_hoja(service, planilla_id)
        valores = _leer_todo(service, planilla_id, hoja)
        bloques = _mapa_de_dias(valores)

        propio = next((b for b in bloques if b['fecha'] == fecha), None)
        if propio:
            destino = propio['ultima'] + 1
            dia_nuevo = False
            _insertar_filas(service, planilla_id, hoja_id, destino)
        else:
            posteriores = [b for b in bloques if b['fecha'] and b['fecha'] > fecha]
            inicio = (min(posteriores, key=lambda b: b['fecha'])['fila_separador']
                      if posteriores else len(valores) + 1)
            _insertar_filas(service, planilla_id, hoja_id, inicio, 2)
            _escribir(service, planilla_id, hoja, inicio, [_titulo_de_fecha(fecha)] + [''] * 8)
            _combinar(service, planilla_id, hoja_id, inicio)
            destino = inicio + 1
            dia_nuevo = True

        _escribir(service, planilla_id, hoja, destino, armar_fila(exc))
        return {'ok': True, 'fila': destino, 'dia_nuevo': dia_nuevo}
    except Exception as e:
        logger.error(f"[Despachos] No pude escribir: {e}")
        return {'ok': False, 'error': str(e)[:200]}


def _buscar_fila(valores, bloques, fecha, exc) -> int | None:
    """Ubica la fila de una salida ya escrita, por fecha más cliente o guía."""
    bloque = next((b for b in bloques if b['fecha'] == fecha), None)
    if not bloque:
        return None
    cliente = _sin_tildes(exc.get('client') or exc.get('agency') or '')
    guia = _sin_tildes(exc.get('guide') or '')
    import generator
    actividad = _sin_tildes(generator.despacho_nombre(exc.get('activity') or '', exc.get('site')))

    candidatas = []
    for nro in range(bloque['primera'], bloque['ultima'] + 1):
        fila = valores[nro - 1] if nro - 1 < len(valores) else []
        fila = list(fila) + [''] * (9 - len(fila))
        puntos = 0
        if cliente and _sin_tildes(fila[1]) == cliente:
            puntos += 2
        if guia and _sin_tildes(fila[6]) == guia:
            puntos += 2
        if actividad and _sin_tildes(fila[4]) == actividad:
            puntos += 1
        if puntos:
            candidatas.append((puntos, nro))
    if not candidatas:
        return None
    candidatas.sort(reverse=True)
    if len(candidatas) > 1 and candidatas[0][0] == candidatas[1][0]:
        return None          # dos filas igual de parecidas: mejor no tocar ninguna
    return candidatas[0][1]


def actualizar_despacho(exc: dict, cancelada: bool = False) -> dict:
    """Reescribe la fila de una salida ya cargada. Si no la encuentra, avisa."""
    if not disponible():
        return {'ok': False, 'error': 'La planilla DESPACHOS no está configurada.'}

    fecha = exc.get('date')
    if isinstance(fecha, str):
        try:
            fecha = date.fromisoformat(fecha[:10])
        except ValueError:
            fecha = None
    if not fecha:
        return {'ok': False, 'error': 'La salida no tiene fecha.'}

    planilla_id = _id_planilla()
    try:
        service = _servicio()
        hoja, _ = _primera_hoja(service, planilla_id)
        valores = _leer_todo(service, planilla_id, hoja)
        fila = _buscar_fila(valores, _mapa_de_dias(valores), fecha, exc)
        if not fila:
            return {'ok': False, 'error': 'No encontré esa salida en la planilla.'}

        nueva = armar_fila({**exc, 'cancelled': cancelada or exc.get('cancelled')})
        if cancelada:
            previa = list(valores[fila - 1]) + [''] * 9
            nota = str(previa[8]).strip()
            nueva[8] = f"CANCELADO · {nota}" if nota and 'CANCELADO' not in nota.upper() else 'CANCELADO'
        _escribir(service, planilla_id, hoja, fila, nueva)
        return {'ok': True, 'fila': fila}
    except Exception as e:
        logger.error(f"[Despachos] No pude actualizar: {e}")
        return {'ok': False, 'error': str(e)[:200]}


def check() -> list:
    """Diagnóstico para /testdespachos."""
    crudo = os.environ.get('DESPACHOS_SHEET_ID')
    if not GOOGLE_AVAILABLE:
        return ["❌ Faltan las librerías de Google."]
    if not os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        return ["❌ Falta GOOGLE_CREDENTIALS_JSON."]
    if not crudo:
        return ["❌ Falta la variable DESPACHOS_SHEET_ID."]

    lineas = [f"Planilla: `{_id_planilla()}`"]
    try:
        service = _servicio()
        hoja, _ = _primera_hoja(service, _id_planilla())
        valores = _leer_todo(service, _id_planilla(), hoja)
        bloques = _mapa_de_dias(valores)
        fechas = [b['fecha'] for b in bloques if b['fecha']]
        lineas.append(f"✅ La puedo leer. Hoja *{hoja}*, {len(valores)} filas, {len(bloques)} días.")
        if fechas:
            lineas.append(f"Van del {min(fechas).strftime('%d/%m/%Y')} al {max(fechas).strftime('%d/%m/%Y')}.")
    except Exception as e:
        err = str(e)
        lineas.append("❌ No pude abrirla: " + ('no está compartida con la cuenta del bot.'
                                                if '403' in err or '404' in err else err[:160]))
        try:
            import drive_service
            lineas.append(f"Cuenta del bot: `{drive_service.cuenta_del_bot()}`")
            lineas.append("_Compartile la planilla como *Editor*._")
        except Exception:
            pass
    return lineas


# ══ Planilla de despachos de Backroads ═══════════════════════════════════════
# Un calendario cargado de antemano: fecha, grupo, actividad y servicio ya
# están; el bot completa pasajeros, personal y el desglose por dieta a medida
# que los confirman.

BACKROADS_COLUMNAS = {'fecha': 0, 'grupo': 1, 'actividad': 2, 'servicio': 3,
                      'pax': 4, 'personal': 5, 'regular': 11, 'veggie': 12,
                      'vegan': 13, 'pescetarian': 14}
BACKROADS_DIETAS = ('regular', 'veggie', 'vegan', 'pescetarian')
BACKROADS_GRUPOS = ('Regular', 'Easygoing', 'Multi Adventure')


def _id_backroads():
    crudo = os.environ.get('BACKROADS_SHEET_ID', '').strip()
    if not crudo:
        return None
    m = re.search(r'/spreadsheets/d/([A-Za-z0-9_-]+)', crudo)
    return m.group(1) if m else re.split(r'[?#/\s]', crudo)[0] or None


def backroads_disponible() -> bool:
    return bool(GOOGLE_AVAILABLE and os.environ.get('GOOGLE_CREDENTIALS_JSON') and _id_backroads())


def _backroads_filas(valores) -> list:
    """Las filas de servicio: las que empiezan con una fecha que se pueda leer."""
    filas = []
    for i, fila in enumerate(valores):
        if not fila or not str(fila[0]).strip():
            continue
        fecha = leer_fecha(fila[0])
        if not fecha:
            continue
        completa = list(fila) + [''] * (15 - len(fila))
        filas.append({'nro': i + 1, 'fecha': fecha,
                      'grupo': str(completa[1]).strip(),
                      'actividad': str(completa[2]).strip(),
                      'servicio': str(completa[3]).strip(),
                      'pax': str(completa[4]).strip(),
                      'personal': str(completa[5]).strip(),
                      'dietas': {d: str(completa[BACKROADS_COLUMNAS[d]]).strip()
                                 for d in BACKROADS_DIETAS}})
    return filas


def _leer_backroads():
    service = _servicio()
    planilla_id = _id_backroads()
    hoja, _ = _primera_hoja(service, planilla_id)
    valores = _leer_todo(service, planilla_id, hoja)
    return service, planilla_id, hoja, valores


def backroads_servicios(fecha: date) -> list:
    """Los servicios de Backroads de una fecha."""
    if not backroads_disponible():
        return []
    try:
        _, _, _, valores = _leer_backroads()
        return [f for f in _backroads_filas(valores) if f['fecha'] == fecha]
    except Exception as e:
        logger.error(f"[Backroads] No pude leer la planilla: {e}")
        return []


def backroads_completar(fecha: date, grupo: str = None, actividad: str = None,
                        pax=None, personal=None, dietas: dict = None) -> dict:
    """
    Completa pasajeros, personal y dietas de un servicio ya cargado.
    Devuelve {'ok', 'fila', 'servicio', 'error', 'opciones'}.
    """
    if not backroads_disponible():
        return {'ok': False, 'error': 'La planilla de Backroads no está configurada.'}
    try:
        service, planilla_id, hoja, valores = _leer_backroads()
        candidatas = [f for f in _backroads_filas(valores) if f['fecha'] == fecha]
        if not candidatas:
            return {'ok': False, 'error': f'No hay servicios cargados el {fecha.strftime("%d/%m/%Y")}.'}
        if grupo:
            g = _sin_tildes(grupo)
            filtradas = [f for f in candidatas if g in _sin_tildes(f['grupo'])]
            candidatas = filtradas or candidatas
        if actividad:
            a = _sin_tildes(actividad)
            filtradas = [f for f in candidatas if a in _sin_tildes(f['actividad'])]
            candidatas = filtradas or candidatas
        if len(candidatas) > 1:
            return {'ok': False, 'error': 'Hay más de un servicio ese día.',
                    'opciones': [f"{f['grupo']} · {f['actividad'] or 'sin actividad'} · {f['servicio']}"
                                 for f in candidatas]}

        fila = candidatas[0]
        nuevos = {}
        if pax is not None:
            nuevos[BACKROADS_COLUMNAS['pax']] = pax
        if personal is not None:
            nuevos[BACKROADS_COLUMNAS['personal']] = personal
        for dieta, valor in (dietas or {}).items():
            if dieta in BACKROADS_COLUMNAS:
                nuevos[BACKROADS_COLUMNAS[dieta]] = valor
        if not nuevos:
            return {'ok': False, 'error': 'No me dijiste qué completar.'}

        actual = list(valores[fila['nro'] - 1]) + [''] * 15
        actual = actual[:15]
        for col, valor in nuevos.items():
            actual[col] = valor
        service.spreadsheets().values().update(
            spreadsheetId=planilla_id, range=f"'{hoja}'!A{fila['nro']}:O{fila['nro']}",
            valueInputOption='USER_ENTERED', body={'values': [actual]}).execute()
        return {'ok': True, 'fila': fila['nro'], 'servicio': fila}
    except Exception as e:
        logger.error(f"[Backroads] No pude completar: {e}")
        return {'ok': False, 'error': str(e)[:200]}


def backroads_reconfirmacion(fecha: date) -> str | None:
    """El aviso del día anterior, una línea por servicio."""
    servicios = backroads_servicios(fecha)
    if not servicios:
        return None
    lineas = [f"🚐 *BACKROADS — {fecha.strftime('%d/%m')}*\n"]
    faltan = []
    for s in servicios:
        partes = [s['grupo'] or 'Grupo', s['actividad'] or 'sin actividad']
        texto = ' · '.join(p for p in partes if p)
        pax = s['pax'] or '?'
        personal = s['personal'] or '?'
        linea = f"{texto} · {s['servicio'] or '—'} {pax} + {personal} perso"
        detalle = [f"{v} {d}" for d, v in s['dietas'].items()
                   if d != 'regular' and v and v not in ('-', '0')]
        if detalle:
            linea += ' (' + ' - '.join(detalle) + ')'
        lineas.append(linea)
        if not s['pax']:
            faltan.append(texto)
    if faltan:
        lineas.append('')
        lineas.append('⚠️ _Sin pasajeros cargados: ' + ' · '.join(faltan) + '_')
    return '\n'.join(lineas)


def backroads_check() -> list:
    if not GOOGLE_AVAILABLE:
        return ["❌ Faltan las librerías de Google."]
    if not os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        return ["❌ Falta GOOGLE_CREDENTIALS_JSON."]
    if not _id_backroads():
        return ["❌ Falta la variable BACKROADS_SHEET_ID."]
    lineas = [f"Planilla: `{_id_backroads()}`"]
    try:
        _, _, hoja, valores = _leer_backroads()
        filas = _backroads_filas(valores)
        sin_pax = [f for f in filas if not f['pax']]
        lineas.append(f"✅ La puedo leer. Hoja *{hoja}*, {len(filas)} servicios cargados.")
        if filas:
            fechas = [f['fecha'] for f in filas]
            lineas.append(f"Van del {min(fechas).strftime('%d/%m/%Y')} al {max(fechas).strftime('%d/%m/%Y')}.")
            lineas.append(f"Sin pasajeros cargados: {len(sin_pax)}.")
    except Exception as e:
        err = str(e)
        lineas.append("❌ No pude abrirla: " + ('no está compartida con la cuenta del bot.'
                                                if '403' in err or '404' in err else err[:160]))
        try:
            import drive_service
            lineas.append(f"Cuenta del bot: `{drive_service.cuenta_del_bot()}`")
        except Exception:
            pass
    return lineas
