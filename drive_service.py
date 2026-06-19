"""
Integración con Google Drive.
Requiere: GOOGLE_CREDENTIALS_JSON y GOOGLE_DRIVE_FOLDER_ID
"""
import os
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
FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
 
 
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
 
 
def upload_file(filepath: str, filename: str) -> str | None:
    """
    Sube un archivo a Google Drive.
    Devuelve el link del archivo o None si falla.
    """
    if not FOLDER_ID:
        return None
    if not os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        return None
 
    try:
        service = _get_service()
        file_metadata = {
            'name': filename,
            'parents': [FOLDER_ID],
        }
        media = MediaFileUpload(
            filepath,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            resumable=False,
        )
        result = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink',
        ).execute()
        return result.get('webViewLink')
    except Exception as e:
        import traceback
        print(f"[Drive] Error: {e}")
        print(f"[Drive] Traceback: {traceback.format_exc()}")
        return None
