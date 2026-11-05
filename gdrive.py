# gdrive.py - Archiviazione su Google Drive v3
import io
import re
import datetime
import json
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

def get_drive_service():
    """Autentica il Service Account tramite secrets Streamlit."""
    if "GCP_SERVICE_ACCOUNT" not in st.secrets:
        raise ValueError("Chiave 'GCP_SERVICE_ACCOUNT' non trovata nei secrets.")
    
    raw_creds = st.secrets["GCP_SERVICE_ACCOUNT"]
    if isinstance(raw_creds, str):
        creds_json = json.loads(raw_creds, strict=False)
    else:
        creds_json = dict(raw_creds)
        
    creds = service_account.Credentials.from_service_account_info(
        creds_json, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)

def sanitize_folder_name(name: str) -> str:
    """Rimuove caratteri non ammessi nei nomi di cartella."""
    clean = re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()
    return clean if clean else "CLIENTE_NON_DEFINITO"

def find_or_create_folder(service, folder_name, parent_id):
    """Cerca una cartella; se non esiste la crea e ne restituisce l'ID."""
    folder_name_clean = sanitize_folder_name(folder_name)
    query = (
        f"name='{folder_name_clean}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false and '{parent_id}' in parents"
    )
    results = service.files().list(
        q=query, 
        spaces='drive', 
        fields='files(id, name)', 
        supportsAllDrives=True, 
        includeItemsFromAllDrives=True
    ).execute()
    
    items = results.get('files', [])
    if not items:
        file_metadata = {
            'name': folder_name_clean,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = service.files().create(
            body=file_metadata, 
            fields='id', 
            supportsAllDrives=True
        ).execute()
        return folder.get('id')
    return items[0]['id']

def upload_to_drive(pdf_bytes: bytes, xml_string: str, nome_cliente: str, filename_base: str):
    """
    Carica PDF e XML nella cartella Cliente/Anno-Mese su Google Drive.
    Restituisce: (successo: bool, messaggio: str)
    """
    try:
        if "GDRIVE_FOLDER_ID" not in st.secrets:
            return False, "ID cartella Google Drive ('GDRIVE_FOLDER_ID') mancante nei secrets."

        service = get_drive_service()
        root_id = st.secrets["GDRIVE_FOLDER_ID"]
        
        # 1. Cartella Cliente e Cartella Mese (AAAA-MM)
        cliente_id = find_or_create_folder(service, nome_cliente, root_id)
        mese_cartella = datetime.date.today().strftime("%Y-%m")
        mese_id = find_or_create_folder(service, mese_cartella, cliente_id)
        
        clean_base = sanitize_folder_name(filename_base)
        
        # 2. Upload PDF
        media_pdf = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
        service.files().create(
            body={'name': f"{clean_base}.pdf", 'parents': [mese_id]}, 
            media_body=media_pdf, 
            supportsAllDrives=True
        ).execute()
        
        # 3. Upload XML
        media_xml = MediaIoBaseUpload(io.BytesIO(xml_string.encode('utf-8')), mimetype='application/xml', resumable=True)
        service.files().create(
            body={'name': f"{clean_base}.xml", 'parents': [mese_id]}, 
            media_body=media_xml, 
            supportsAllDrives=True
        ).execute()
        
        return True, f"Archiviazione completata su Drive nella cartella: {nome_cliente} / {mese_cartella}"

    except HttpError as http_err:
        err_content = str(http_err)
        if "storage quota" in err_content.lower():
            return False, "Google Drive Quota Error: I Service Account non hanno quota di storage sui drive personali Gmail. Usa una cartella condivisa Google Workspace o scarica lo ZIP."
        return False, f"Errore Google Drive API: {http_err}"
    except Exception as e:
        return False, f"Errore durante l'upload su Drive: {str(e)}"
