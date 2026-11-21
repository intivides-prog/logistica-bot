"""
Integración con Google Drive.
Requiere: GOOGLE_CREDENTIALS_JSON y GOOGLE_DRIVE_FOLDER_ID
"""
import os
import re
import json

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
]
def _limpiar_folder_id(valor):
    """
    Acepta el ID pelado, el ID con cosas pegadas ("...?hl=es") o el link entero
    de la carpeta, y devuelve solo el ID.
    """
    if not valor:
        return None
    valor = valor.strip().strip('"\'')
    m = re.search(r'/folders/([A-Za-z0-9_-]+)', valor)      # link completo
    if m:
        return m.group(1)
    return re.split(r'[?#/&\s]', valor)[0] or None


FOLDER_ID = _limpiar_folder_id(os.environ.get('GOOGLE_DRIVE_FOLDER_ID'))


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
    return build('drive', 'v3', credentials=creds)


def _buscar(service, filename: str, folder_id: str):
    """Devuelve el id de un archivo con ese nombre en la carpeta, si ya existe."""
    seguro = filename.replace("'", "\\'")
    res = service.files().list(
        q=f"name = '{seguro}' and '{folder_id}' in parents and trashed = false",
        fields='files(id)', pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    archivos = res.get('files', [])
    return archivos[0]['id'] if archivos else None


def upload_file(filepath: str, filename: str, folder_id: str = None) -> str | None:
    """
    Sube un archivo a Google Drive. Si ya hay uno con el mismo nombre en la
    carpeta, lo reemplaza en vez de dejar un duplicado.
    Devuelve el link del archivo o None si falla.
    """
    carpeta = _limpiar_folder_id(folder_id) or FOLDER_ID
    if not carpeta:
        return None
    if not os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        return None

    tipo = ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            if filename.lower().endswith(('.xlsx', '.xlsm'))
            else 'application/octet-stream')
    try:
        service = _get_service()
        media = MediaFileUpload(filepath, mimetype=tipo, resumable=False)
        existente = _buscar(service, filename, carpeta)
        if existente:
            result = service.files().update(
                fileId=existente, media_body=media,
                fields='id,webViewLink', supportsAllDrives=True,
            ).execute()
        else:
            result = service.files().create(
                body={'name': filename, 'parents': [carpeta]},
                media_body=media,
                fields='id,webViewLink',
                supportsAllDrives=True,
            ).execute()
        return result.get('webViewLink')
    except Exception as e:
        import traceback
        print(f"[Drive] Error: {e}")
        print(f"[Drive] Traceback: {traceback.format_exc()}")
        return None


def check() -> list:
    """
    Prueba de verdad el acceso a Drive y devuelve las líneas del diagnóstico.
    Mira las credenciales, el ID de la carpeta, si la cuenta la puede abrir y
    si puede escribir en ella.
    """
    crudo = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
    lineas = []

    if not GOOGLE_AVAILABLE:
        return ["❌ Faltan las librerías de Google (google-api-python-client)."]
    if not os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        return ["❌ Falta la variable GOOGLE_CREDENTIALS_JSON."]
    if not crudo:
        return ["❌ Falta la variable GOOGLE_DRIVE_FOLDER_ID."]

    lineas.append(f"Variable: `{crudo}`")
    if FOLDER_ID != crudo.strip():
        lineas.append(f"ID limpio: `{FOLDER_ID}`  _(le saqué lo que sobraba)_")

    try:
        service = _get_service()
    except Exception as e:
        return lineas + [f"❌ No pude autenticarme: {e}"]

    try:
        datos = service.files().get(
            fileId=FOLDER_ID, fields='id,name,mimeType',
            supportsAllDrives=True,
        ).execute()
    except Exception as e:
        err = str(e)
        if '404' in err:
            lineas.append("❌ La carpeta no existe, o no está compartida con la cuenta del bot.")
        elif '403' in err:
            lineas.append("❌ La cuenta del bot no tiene permiso sobre esa carpeta.")
        else:
            lineas.append(f"❌ No pude abrir la carpeta: {err[:160]}")
        try:
            lineas.append(f"Cuenta del bot: `{json.loads(os.environ['GOOGLE_CREDENTIALS_JSON']).get('client_email')}`")
            lineas.append("_Compartí la carpeta con esa dirección, como Editor._")
        except Exception:
            pass
        return lineas

    if 'folder' not in datos.get('mimeType', ''):
        lineas.append(f"⚠️ `{datos.get('name')}` no es una carpeta, es un archivo.")
        return lineas
    lineas.append(f"✅ Carpeta encontrada: *{datos.get('name')}*")

    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmp:
            prueba = os.path.join(tmp, 'prueba-bot.txt')
            with open(prueba, 'w') as f:
                f.write('prueba de escritura del bot de logistica')
            service_file = service.files().create(
                body={'name': 'prueba-bot.txt', 'parents': [FOLDER_ID]},
                media_body=MediaFileUpload(prueba, mimetype='text/plain', resumable=False),
                fields='id', supportsAllDrives=True,
            ).execute()
        service.files().delete(fileId=service_file['id'], supportsAllDrives=True).execute()
        lineas.append("✅ Puede escribir y borrar en esa carpeta. Todo listo.")
    except Exception as e:
        lineas.append(f"❌ Puede ver la carpeta pero no escribir: {str(e)[:160]}")
        try:
            lineas.append(f"Cuenta del bot: `{json.loads(os.environ['GOOGLE_CREDENTIALS_JSON']).get('client_email')}`")
            lineas.append("_Dale permiso de *Editor*, no de Lector._")
        except Exception:
            pass
    return lineas


def cuenta_del_bot():
    """La dirección de la cuenta de servicio, para compartirle carpetas."""
    try:
        return json.loads(os.environ.get('GOOGLE_CREDENTIALS_JSON', '{}')).get('client_email')
    except Exception:
        return None
