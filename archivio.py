# === INIZIO FILE archivio.py ===
"""
archivio.py - Gestore Archiviazione Gerarchica per Cliente / Anno / Mese (01 - Gennaio .. 12 - Dicembre)
Supporta:
1) Salvataggio in qualsiasi cartella locale o Google Drive Desktop (percorso modificabile).
2) Salvataggio diretto su Google Drive Cloud API (ID, Link o Nome cartella modificabile).
Riconosce automaticamente clienti già esistenti tramite P.IVA / CF e nome normalizzato (evita duplicati).
"""

from datetime import datetime
import difflib
import io
import json
import os
import re
import unicodedata


MESI_ITALIANI = {
    1: "01 - Gennaio",
    2: "02 - Febbraio",
    3: "03 - Marzo",
    4: "04 - Aprile",
    5: "05 - Maggio",
    6: "06 - Giugno",
    7: "07 - Luglio",
    8: "08 - Agosto",
    9: "09 - Settembre",
    10: "10 - Ottobre",
    11: "11 - Novembre",
    12: "12 - Dicembre",
}

LEGAL_STOPWORDS = {
    "SRL", "SRLS", "SPA", "SAS", "SNC", "SAPA", "SCARL", "SCRL", "SRCRL",
    "LTD", "LIMITED", "INC", "LLC", "CORP", "GMBH", "AG", "BV", "NV",
    "SA", "SL", "SARL", "EURL", "ETS", "ONLUS", "APS", "ODV", "DI", "E", "C",
}


def _pulisci_nome_cartella(nome: str, fallback: str = "CLIENTE_GENERICO") -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(nome or "")).strip()
    s = re.sub(r"\s+", " ", s)
    # Rimuove eventuali prefissi duplicati tipo "SRL SRL 4SALE" -> "SRL 4SALE"
    parole = s.split(" ")
    pulite = []
    for w in parole:
        if pulite and w.upper() == pulite[-1].upper():
            continue
        pulite.append(w)
    s = " ".join(pulite).strip(" .")
    return s[:80] if s else fallback


def _normalizza_chiave_cliente(nome: str) -> str:
    txt = str(nome or "").upper()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^A-Z0-9\s]", " ", txt)
    tokens = [t for t in txt.split() if t and t not in LEGAL_STOPWORDS]
    # Rimuove eventuali token duplicati preservando l'ordine
    unici = []
    for t in tokens:
        if t not in unici:
            unici.append(t)
    return " ".join(unici) if unici else re.sub(r"\s+", " ", txt).strip()


def _nomi_compatibili(nome_a: str, nome_b: str) -> bool:
    ka = _normalizza_chiave_cliente(nome_a)
    kb = _normalizza_chiave_cliente(nome_b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.88:
        return True
    return False


def _estrai_anno_mese(data_doc: str):
    s = str(data_doc or "").strip()[:10]
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        dt = datetime.today()
    return str(dt.year), MESI_ITALIANI[dt.month]


def _estrai_drive_folder_id(val: str) -> str:
    """Estrae l'ID cartella se l'utente ha incollato un link di Google Drive o un ID diretto."""
    v = str(val or "").strip()
    if not v:
        return ""
    m_url = re.search(r"/folders/([a-zA-Z0-9_-]{15,})", v)
    if m_url:
        return m_url.group(1)
    m_id = re.search(r"[?&]id=([a-zA-Z0-9_-]{15,})", v)
    if m_id:
        return m_id.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", v) and " " not in v:
        return v
    return ""


def _nome_file_univoco_locale(cartella: str, nome_file: str, contenuto_bytes: bytes) -> str:
    base, ext = os.path.splitext(nome_file)
    cand = nome_file
    idx = 2
    while os.path.exists(os.path.join(cartella, cand)):
        try:
            with open(os.path.join(cartella, cand), "rb") as f:
                if f.read() == contenuto_bytes:
                    return cand  # Stesso identico file: aggiorna senza duplicare
        except Exception:
            pass
        cand = f"{base}_{idx}{ext}"
        idx += 1
    return cand


# ==============================================================================
# MODALITA' 1: ARCHIVIO LOCALE / GOOGLE DRIVE DESKTOP (PERCORSO MODIFICABILE)
# ==============================================================================
def salva_in_cartella_locale(
    root_path: str,
    cliente_nome: str,
    cliente_piva: str,
    data_documento: str,
    xml_filename: str,
    xml_content: str,
    precrea_12_mesi: bool = True,
    pdf_filename: str = None,
    pdf_bytes: bytes = None,
):
    root = os.path.expanduser(str(root_path or "./Archivio_Fatture_XML").strip())
    os.makedirs(root, exist_ok=True)

    piva_clean = re.sub(r"[^A-Za-z0-9]", "", str(cliente_piva or "")).upper()
    if piva_clean.startswith("IT") and len(piva_clean) == 13:
        piva_clean = piva_clean[2:]

    index_path = os.path.join(root, ".clienti_index.json")
    indice = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                indice = json.load(f) or {}
        except Exception:
            indice = {}

    cartelle_esistenti = [
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
    ]

    cartella_cliente = None

    # 1. Cerca prima per P.IVA esatta nell'indice
    if piva_clean and piva_clean in indice:
        cand = indice[piva_clean]
        if cand in cartelle_esistenti:
            cartella_cliente = cand

    # 2. Cerca per P.IVA nel nome cartella o per somiglianza nome tra tutte le cartelle esistenti
    if not cartella_cliente:
        for d in cartelle_esistenti:
            if piva_clean and piva_clean in d:
                cartella_cliente = d
                break
            if _nomi_compatibili(cliente_nome, d):
                cartella_cliente = d
                break

    # 3. Se non esiste ancora, crea nuova cartella cliente
    creato_nuovo_cliente = False
    if not cartella_cliente:
        cartella_cliente = _pulisci_nome_cartella(cliente_nome)
        creato_nuovo_cliente = True

    if piva_clean:
        indice[piva_clean] = cartella_cliente
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(indice, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    anno, mese_nome = _estrai_anno_mese(data_documento)
    path_anno = os.path.join(root, cartella_cliente, anno)
    os.makedirs(path_anno, exist_ok=True)

    if precrea_12_mesi:
        for m_label in MESI_ITALIANI.values():
            os.makedirs(os.path.join(path_anno, m_label), exist_ok=True)

    path_mese = os.path.join(path_anno, mese_nome)
    os.makedirs(path_mese, exist_ok=True)

    xml_bytes = xml_content.encode("utf-8")
    nome_xml_finale = _nome_file_univoco_locale(path_mese, xml_filename, xml_bytes)
    dest_xml = os.path.join(path_mese, nome_xml_finale)
    with open(dest_xml, "wb") as f:
        f.write(xml_bytes)

    if pdf_filename and pdf_bytes:
        nome_pdf_finale = _nome_file_univoco_locale(path_mese, pdf_filename, pdf_bytes)
        with open(os.path.join(path_mese, nome_pdf_finale), "wb") as f:
            f.write(pdf_bytes)

    percorso_relativo = f"{cartella_cliente}/{anno}/{mese_nome}/{nome_xml_finale}"
    return True, percorso_relativo, creato_nuovo_cliente


# ==============================================================================
# MODALITA' 2: GOOGLE DRIVE CLOUD API (martina.studio.evangelista@gmail.com)
# ==============================================================================
def _ottieni_servizio_drive(secrets_dict=None):
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None, (
            "Librerie Google Drive mancanti. Installa: "
            "google-api-python-client google-auth google-auth-oauthlib"
        )

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = None

    # 1. OAuth utente da st.secrets["GOOGLE_OAUTH"] o token.json (ideale per account @gmail.com)
    if secrets_dict and "GOOGLE_OAUTH" in secrets_dict:
        try:
            info = dict(secrets_dict["GOOGLE_OAUTH"])
            creds = Credentials.from_authorized_user_info(info, scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
        except Exception as e:
            return None, f"Errore credenziali GOOGLE_OAUTH: {e}"
    elif os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open("token.json", "w", encoding="utf-8") as tf:
                    tf.write(creds.to_json())
        except Exception as e:
            return None, f"Errore token.json: {e}"

    # 2. Service Account da st.secrets["gcp_service_account"] o service_account.json
    if not creds and secrets_dict and "gcp_service_account" in secrets_dict:
        try:
            creds = service_account.Credentials.from_service_account_info(
                dict(secrets_dict["gcp_service_account"]), scopes=scopes
            )
        except Exception as e:
            return None, f"Errore gcp_service_account: {e}"
    elif not creds and os.path.exists("service_account.json"):
        try:
            creds = service_account.Credentials.from_service_account_file(
                "service_account.json", scopes=scopes
            )
        except Exception as e:
            return None, f"Errore service_account.json: {e}"

    if not creds:
        return None, (
            "Nessuna credenziale Google Drive configurata (inserisci GOOGLE_OAUTH o "
            "gcp_service_account nei Secrets, oppure usa 'Cartella sul PC / Drive Desktop')."
        )

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service, None
    except Exception as e:
        return None, f"Errore connessione Google Drive: {e}"


def _drive_lista_sottocartelle(service, parent_id: str) -> list:
    ris = []
    page_token = None
    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    while True:
        resp = service.files().list(
            q=q,
            spaces="drive",
            fields="nextPageToken, files(id, name, description)",
            pageToken=page_token,
            pageSize=200,
        ).execute()
        ris.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ris


def _drive_crea_cartella(service, nome: str, parent_id: str = None, description: str = "") -> dict:
    meta = {
        "name": nome,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        meta["parents"] = [parent_id]
    if description:
        meta["description"] = description
    return service.files().create(body=meta, fields="id, name, description").execute()


def _drive_trova_o_crea_cartella_esatta(service, nome: str, parent_id: str = None) -> dict:
    q = (
        f"name='{nome.replace(chr(39), '')}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    if parent_id:
        q = f"'{parent_id}' in parents and " + q
    resp = service.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=10).execute()
    files = resp.get("files", [])
    if files:
        return files[0]
    return _drive_crea_cartella(service, nome, parent_id=parent_id)


def _drive_carica_file(service, parent_id: str, filename: str, content_bytes: bytes, mime_type: str) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    base, ext = os.path.splitext(filename)
    q = f"'{parent_id}' in parents and trashed=false"
    esistenti = {
        f["name"]: f["id"]
        for f in service.files().list(q=q, fields="files(id, name)", pageSize=200).execute().get("files", [])
    }
    nome_finale = filename
    idx = 2
    while nome_finale in esistenti:
        nome_finale = f"{base}_{idx}{ext}"
        idx += 1

    media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime_type, resumable=False)
    meta = {"name": nome_finale, "parents": [parent_id]}
    service.files().create(body=meta, media_body=media, fields="id").execute()
    return nome_finale


def salva_su_google_drive(
    drive_destinazione: str,
    cliente_nome: str,
    cliente_piva: str,
    data_documento: str,
    xml_filename: str,
    xml_content: str,
    precrea_12_mesi: bool = True,
    pdf_filename: str = None,
    pdf_bytes: bytes = None,
    secrets_dict=None,
):
    service, err = _ottieni_servizio_drive(secrets_dict=secrets_dict)
    if err:
        return False, err, False

    try:
        # 1. Risolvi cartella radice (può essere Link, ID o Nome cartella)
        root_id = _estrai_drive_folder_id(drive_destinazione)
        if not root_id:
            nome_root = _pulisci_nome_cartella(drive_destinazione or "Fatture_XML_SdI", "Fatture_XML_SdI")
            root_id = _drive_trova_o_crea_cartella_esatta(service, nome_root, parent_id=None)["id"]

        # 2. Cerca cliente già esistente su Drive (P.IVA nella description o nome compatibile)
        piva_clean = re.sub(r"[^A-Za-z0-9]", "", str(cliente_piva or "")).upper()
        if piva_clean.startswith("IT") and len(piva_clean) == 13:
            piva_clean = piva_clean[2:]

        sottocartelle = _drive_lista_sottocartelle(service, root_id)
        folder_cliente = None

        if piva_clean:
            for fc in sottocartelle:
                desc = str(fc.get("description") or "")
                if f"PIVA:{piva_clean}" in desc or piva_clean in fc.get("name", ""):
                    folder_cliente = fc
                    break

        if not folder_cliente:
            for fc in sottocartelle:
                if _nomi_compatibili(cliente_nome, fc.get("name", "")):
                    folder_cliente = fc
                    break

        creato_nuovo_cliente = False
        if not folder_cliente:
            nome_cli_pulito = _pulisci_nome_cartella(cliente_nome)
            desc_cli = f"PIVA:{piva_clean}" if piva_clean else ""
            folder_cliente = _drive_crea_cartella(service, nome_cli_pulito, parent_id=root_id, description=desc_cli)
            creato_nuovo_cliente = True

        # 3. Anno e Mese (01 - Gennaio .. 12 - Dicembre)
        anno, mese_nome = _estrai_anno_mese(data_documento)
        folder_anno = _drive_trova_o_crea_cartella_esatta(service, anno, parent_id=folder_cliente["id"])

        cartelle_mesi = {
            f["name"]: f for f in _drive_lista_sottocartelle(service, folder_anno["id"])
        }
        if precrea_12_mesi:
            for m_label in MESI_ITALIANI.values():
                if m_label not in cartelle_mesi:
                    cartelle_mesi[m_label] = _drive_crea_cartella(service, m_label, parent_id=folder_anno["id"])

        if mese_nome not in cartelle_mesi:
            cartelle_mesi[mese_nome] = _drive_crea_cartella(service, mese_nome, parent_id=folder_anno["id"])
        folder_mese = cartelle_mesi[mese_nome]

        # 4. Carica XML (ed eventuale PDF)
        nome_xml_finale = _drive_carica_file(
            service, folder_mese["id"], xml_filename, xml_content.encode("utf-8"), "application/xml"
        )
        if pdf_filename and pdf_bytes:
            _drive_carica_file(service, folder_mese["id"], pdf_filename, pdf_bytes, "application/pdf")

        percorso_rel = f"{folder_cliente['name']}/{anno}/{mese_nome}/{nome_xml_finale}"
        return True, percorso_rel, creato_nuovo_cliente
    except Exception as e:
        return False, f"Errore Drive: {e}", False
# === FINE FILE archivio.py ===
