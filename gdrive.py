import io
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import streamlit as st
import json

def get_drive_service():
    creds_json = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(
        creds_json, scopes=['https://www.googleapis.com/auth/drive.file']
    )
    return build('drive', 'v3', credentials=creds)

def find_or_create_folder(service, folder_name, parent_id=None):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
        
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])
    
    if not items:
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id:
            file_metadata['parents'] = [parent_id]
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    return items[0]['id']

def upload_to_drive(pdf_bytes, xml_string, nome_cliente, filename_base):
    service = get_drive_service()
    
    # Struttura: "Fatture_App" -> "Nome Cliente" -> "YYYY-MM"
    root_id = find_or_create_folder(service, "Fatture_App")
    cliente_id = find_or_create_folder(service, nome_cliente, root_id)
    mese_id = find_or_create_folder(service, datetime.date.today().strftime("%Y-%m"), cliente_id)
    
    # Upload PDF
    media_pdf = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
    service.files().create(body={'name': f"{filename_base}.pdf", 'parents': [mese_id]}, media_body=media_pdf).execute()
    
    # Upload XML
    media_xml = MediaIoBaseUpload(io.BytesIO(xml_string.encode('utf-8')), mimetype='application/xml', resumable=True)
    service.files().create(body={'name': f"{filename_base}.xml", 'parents': [mese_id]}, media_body=media_xml).execute()
