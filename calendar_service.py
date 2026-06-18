
"""
Integración con Google Calendar.
Requiere: GOOGLE_CREDENTIALS_FILE (service account JSON) y GOOGLE_CALENDAR_ID
Instrucciones de setup en README.md
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
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'google_credentials.json')
CALENDAR_ID      = os.environ.get('GOOGLE_CALENDAR_ID', 'primary')
 
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
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=SCOPES
    )
    return build('calendar', 'v3', credentials=creds)
 
 
def add_excursion(params: dict) -> str | None:
    """
    Agrega la excursión al Google Calendar.
    Devuelve el link del evento o None si falla.
    """
    if not os.path.exists(CREDENTIALS_FILE):
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
