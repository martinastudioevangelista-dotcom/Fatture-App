import io
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import streamlit as st
import json

def get_drive_service():
    raw_creds = st.secrets["GCP_SERVICE_ACCOUNT"]
    creds_json = json.loads(raw_creds, strict=False)
    creds = service_account.Credentials.from_service_account_info(
        creds_json, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)

def find_or_create_folder(service, folder_name, parent_id):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false and '{parent_id}' in parents"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    items = results.get('files', [])
    
    if not items:
        file_metadata = {
            'name': folder_name, 
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
        return folder.get('id')
    return items[0]['id']

def upload_to_drive(pdf_bytes, xml_string, nome_cliente, filename_base):
    service = get_drive_service()
    
    # Prende la cartella che hai condiviso dal tuo Google Drive
    root_id = st.secrets["GDRIVE_FOLDER_ID"]
    
    cliente_id = find_or_create_folder(service, nome_cliente, root_id)
    mese_id = find_or_create_folder(service, datetime.date.today().strftime("%Y-%m"), cliente_id)
    
    # Upload PDF
    media_pdf = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
    service.files().create(body={'name': f"{filename_base}.pdf", 'parents': [mese_id]}, media_body=media_pdf, supportsAllDrives=True).execute()
    
    # Upload XML
    media_xml = MediaIoBaseUpload(io.BytesIO(xml_string.encode('utf-8')), mimetype='application/xml', resumable=True)
    service.files().create(body={'name': f"{filename_base}.xml", 'parents': [mese_id]}, media_body=media_xml, supportsAllDrives=True).execute()
