"""
Integración con Google Calendar.
Requiere: GOOGLE_CREDENTIALS_JSON (contenido del JSON de service account) y GOOGLE_CALENDAR_ID
"""
import os
import json
from datetime import date, datetime, timedelta
 
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
 
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')
 
# Abreviaciones de sitios para el título del calendario
SITE_SHORT = {
    'Lago Mascardi':      'Masc',
    'Tres Reyes':         '3 Reyes',
    'Llao Llao':          'Llao',
    'Lago Nahuel Huapi':  'Nahuel',
    'Pampa Linda':        'P. Linda',
    'Colonia Suiza':      'Col. Suiza',
    'Lago Traful':        'Traful',
    'Lago Espejo':        'Espejo',
}
 
# Sitios que son siempre FD (no se muestra prefijo)
ALWAYS_FD = {'Lago Mascardi'}
 
# Nombres cortos de actividad (sin el prefijo FD/HD)
ACTIVITY_SHORT = {
    'FD Kayak y Trekking': 'Kayak y Trekking',
    'FD Kayak':            'Kayak',
    'MTB':                 'MTB',
    'Trekking':            'Trekking',
    'Navegación':          'Naveg',
}
 
 
def _build_cal_title(activity: str, site: str, pax, gtype: str) -> str:
    """Construye el título compacto para Google Calendar."""
    site_short = SITE_SHORT.get(site, site)
    act_short  = ACTIVITY_SHORT.get(activity, activity)
    prefix     = '' if site in ALWAYS_FD else ('HD ' if gtype == 'snacks' else 'FD ')
    return f"{prefix}{act_short} {site_short} x{pax}"
 
 
def _get_service():
    if not GOOGLE_AVAILABLE:
        raise RuntimeError("google-api-python-client no instalado")
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON no configurado")
    creds_info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )
    return build('calendar', 'v3', credentials=creds)
 
 
def test_connection() -> str:
    """Prueba la conexión con Google Calendar. Devuelve mensaje de éxito o error."""
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        return "❌ Variable GOOGLE_CREDENTIALS_JSON no encontrada en Railway."
    try:
        creds_info = json.loads(creds_json)
    except Exception as e:
        return f"❌ Error al parsear JSON de credenciales: {e}"
    try:
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        service.calendarList().list().execute()
        return f"✅ Conexión exitosa con Google Calendar. Calendar ID: {CALENDAR_ID}"
    except Exception as e:
        return f"❌ Error de conexión: {e}"
 
 
def add_excursion(params: dict) -> str | None:
    """
    Agrega la excursión al Google Calendar.
    Devuelve el link del evento o None si falla.
    """
    if not os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        return None   # Calendar no configurado — silencioso
 
    excursion_date = params.get('date')
    if not isinstance(excursion_date, date):
        return None
 
    activity = params.get('activity', 'Excursión')
    site     = params.get('site', '')
    pax      = params.get('pax', '')
    guide    = params.get('guide', '')
    hora     = params.get('hora', '09:00')
    gtype    = params.get('gastronomy_type', 'AC')
 
    # Parsear hora
    hora_clean = hora.replace('hs','').strip()
    try:
        h, m = hora_clean.split(':') if ':' in hora_clean else (hora_clean, '00')
        start_dt = datetime(excursion_date.year, excursion_date.month, excursion_date.day,
                            int(h), int(m))
    except Exception:
        start_dt = datetime(excursion_date.year, excursion_date.month, excursion_date.day, 9, 0)
 
    end_dt = start_dt + timedelta(hours=8 if gtype == 'AC' else 4)
 
    diet = params.get('dietary_restrictions')
    desc_parts = [
        f"Pax: {pax}",
        f"Guía: {guide}" if guide else '',
        f"Sitio: {site}" if site else '',
        f"Restricciones: {diet}" if diet else '',
    ]
    description = '\n'.join(p for p in desc_parts if p)
 
    event = {
        'summary': _build_cal_title(activity, site, pax, gtype),
        'description': description,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Argentina/Buenos_Aires'},
        'end':   {'dateTime': end_dt.isoformat(),   'timeZone': 'America/Argentina/Buenos_Aires'},
        'colorId': '2',   # verde
    }
 
    try:
        service = _get_service()
        result  = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return result.get('htmlLink')
    except Exception as e:
        print(f"[Calendar] Error: {e}")
        return None
