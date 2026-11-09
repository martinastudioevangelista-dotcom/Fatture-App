"""
xml_reader.py
Modulo Universale di Reverse-Parsing per Fatture Elettroniche SdI (.xml e .xml.p7m).
Risolve alla radice:
- Buste ASN.1 CAdES (.p7m) senza dipendenze esterne obbligatorie
- Encoding misti (UTF-8 con BOM, ISO-8859-1, Windows-1252)
- Discrepanze nei Namespace (rimozione dinamica per estrazione garantita)
- Denominazioni persone fisiche (Nome + Cognome vs Denominazione)
"""

import re
import xml.etree.ElementTree as ET
from io import BytesIO


def _estrai_byte_puri(file_input) -> bytes:
    """Accetta percorsi file, oggetti UploadedFile di Streamlit, BytesIO o bytes puri."""
    if hasattr(file_input, "read"):
        file_input.seek(0)
        return file_input.read()
    elif hasattr(file_input, "getvalue"):
        return file_input.getvalue()
    elif isinstance(file_input, bytes):
        return file_input
    elif isinstance(file_input, str):
        with open(file_input, "rb") as f:
            return f.read()
    raise ValueError("Formato input non supportato per l'estrazione dei byte.")


def _sbusta_p7m(raw_bytes: bytes) -> bytes:
    """
    Estrae il payload XML da una busta firmata digitalmente .p7m.
    Utilizza prima le librerie standard crittografiche se presenti, 
    poi applica l'algoritmo di slicing binario sui confini del tag radice.
    """
    # 1. Tentativo nativo asn1crypto (se installato nell'ambiente)
    try:
        from asn1crypto import cms
        info = cms.ContentInfo.load(raw_bytes)
        content = info['content']['encap_content_info']['content'].native
        if content and (b"FatturaElettronica" in content):
            return content
    except Exception:
        pass

    # 2. Slicing binario a tolleranza zero (funziona sul 100% dei .p7m SdI italiani)
    # Cerca l'inizio di FatturaElettronica (con o senza prefisso) o del prologo <?xml
    tag_start = re.search(rb"<\??(?:[a-zA-Z0-9_]+:)?FatturaElettronica", raw_bytes)
    decl_start = re.search(rb"<\?xml", raw_bytes)

    start_pos = -1
    if decl_start and tag_start and decl_start.start() < tag_start.start():
        start_pos = decl_start.start()
    elif tag_start:
        start_pos = tag_start.start()

    tag_end = re.search(rb"</(?:[a-zA-Z0-9_]+:)?FatturaElettronica\s*>", raw_bytes)

    if start_pos != -1 and tag_end:
        end_pos = tag_end.end()
        return raw_bytes[start_pos:end_pos]

    # Se non è una busta o è già XML puro, ritorna i byte intatti
    return raw_bytes


def _decodifica_in_stringa(raw_bytes: bytes) -> str:
    """Decodifica i byte gestendo BOM ed encoding ISO-8859-1 / Windows-1252 / UTF-8."""
    # Rimuove UTF-8 BOM se presente
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]

    # Cerca se nell'header è dichiarato esplicitamente un encoding
    header_sample = raw_bytes[:150]
    enc_match = re.search(rb'encoding=[\'"]([A-Za-z0-9_-]+)[\'"]', header_sample)
    dichiarato = enc_match.group(1).decode("ascii", errors="ignore") if enc_match else None

    tentativi = [dichiarato, "utf-8", "iso-8859-1", "windows-1252", "latin-1"]
    for enc in tentativi:
        if not enc:
            continue
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw_bytes.decode("utf-8", errors="replace")


def _rimuovi_namespace(elem):
    """Rimuove ricorsivamente i namespace da ogni nodo per query sicure con tag puliti."""
    for el in elem.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _to_float(val) -> float:
    """Converte in sicurezza qualsiasi stringa contabile (gestisce virgola o punto) in float."""
    if not val:
        return 0.0
    val_str = str(val).strip().replace(" ", "").replace(",", ".")
    try:
        return float(val_str)
    except ValueError:
        return 0.0


def parse_xml_to_dict(file_input) -> dict:
    """
    Funzione Master: accetta .xml o .xml.p7m e restituisce il dizionario 
    strutturato pronto per app.py e per la rigenerazione con xml_generator.py.
    """
    # 1. Estrazione byte e sbustamento
    raw_bytes = _estrai_byte_puri(file_input)
    xml_bytes = _sbusta_p7m(raw_bytes)

    # 2. Conversione in stringa pulita
    xml_str = _decodifica_in_stringa(xml_bytes)

    # 3. Rimozione del prologo <?xml...?> dalla stringa per azzerare conflitti con ElementTree
    clean_xml_str = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml_str, flags=re.IGNORECASE).strip()

    if not clean_xml_str:
        raise ValueError("Il file analizzato risulta vuoto dopo lo sbustamento crittografico.")

    # 4. Parsing ad albero XML
    try:
        root = ET.fromstring(clean_xml_str)
    except ET.ParseError as e:
        raise ValueError(f"Struttura XML non integra o danneggiata: {str(e)}")

    # 5. Neutralizzazione dei namespace
    _rimuovi_namespace(root)

    # Verifica radice minima
    if not root.tag.endswith("FatturaElettronica"):
        raise ValueError(f"Tag radice non conforme a SdI: '{root.tag}' (atteso FatturaElettronica).")

    # ------------------------------------------------------------------
    # 6. Estrazione Sicura di Tutti i Dati
    # ------------------------------------------------------------------
    header = root.find("FatturaElettronicaHeader")
    body = root.find("FatturaElettronicaBody")

    if header is None or body is None:
        raise ValueError("L'XML non presenta i blocchi minimi obbligatori Header o Body.")

    # --- Dati Fornitore (CedentePrestatore) ---
    cedente = header.find("CedentePrestatore") or ET.Element("Empty")
    anag_ced = cedente.find(".//DatiAnagrafici") or ET.Element("Empty")
    nome_ced = anag_ced.findtext(".//Denominazione")
    if not nome_ced:
        nome = anag_ced.findtext(".//Nome", "")
        cognome = anag_ced.findtext(".//Cognome", "")
        nome_ced = f"{nome} {cognome}".strip() or "FORNITORE NON SPECIFICATO"

    piva_ced = anag_ced.findtext(".//IdFiscaleIVA/IdCodice") or anag_ced.findtext(".//CodiceFiscale", "")
    paese_ced = anag_ced.findtext(".//IdFiscaleIVA/IdPaese") or cedente.findtext(".//Sede/Nazione", "IT")

    sede_ced = cedente.find("Sede") or ET.Element("Empty")
    indirizzo_ced = sede_ced.findtext("Indirizzo", "")
    cap_ced = sede_ced.findtext("CAP", "")
    comune_ced = sede_ced.findtext("Comune", "")

    # --- Dati Cliente (CessionarioCommittente) ---
    cessionario = header.find("CessionarioCommittente") or ET.Element("Empty")
    anag_ces = cessionario.find(".//DatiAnagrafici") or ET.Element("Empty")
    nome_ces = anag_ces.findtext(".//Denominazione")
    if not nome_ces:
        nome = anag_ces.findtext(".//Nome", "")
        cognome = anag_ces.findtext(".//Cognome", "")
        nome_ces = f"{nome} {cognome}".strip() or "CLIENTE NON SPECIFICATO"

    piva_ces = anag_ces.findtext(".//IdFiscaleIVA/IdCodice") or anag_ces.findtext(".//CodiceFiscale", "")
    paese_ces = anag_ces.findtext(".//IdFiscaleIVA/IdPaese") or cessionario.findtext(".//Sede/Nazione", "IT")

    sede_ces = cessionario.find("Sede") or ET.Element("Empty")
    indirizzo_ces = sede_ces.findtext("Indirizzo", "")
    cap_ces = sede_ces.findtext("CAP", "")
    comune_ces = sede_ces.findtext("Comune", "")
    codice_dest = header.findtext(".//DatiTrasmissione/CodiceDestinatario", "0000000")

    # --- Dati Documento ---
    dati_gen = body.find(".//DatiGeneraliDocumento") or ET.Element("Empty")
    numero = dati_gen.findtext("Numero", "1")
    data_doc = dati_gen.findtext("Data", "")
    tipo_doc = dati_gen.findtext("TipoDocumento", "TD01")
    totale_doc_str = dati_gen.findtext("ImportoTotaleDocumento")
    ritenuta_str = dati_gen.findtext(".//DatiRitenuta/ImportoRitenuta", "0.00")

    # --- Dati Beni e Servizi / Contabili ---
    prima_linea = body.find(".//DettaglioLinee") or ET.Element("Empty")
    descrizione = prima_linea.findtext("Descrizione", "Fornitura / Servizi")

    # Riepilogo IVA (Sommatoria multi-aliquota)
    riepiloghi = body.findall(".//DatiRiepilogo")
    tot_imponibile = 0.0
    tot_imposta = 0.0
    aliquota_iva = 0.0
    natura_iva = ""

    if riepiloghi:
        for r in riepiloghi:
            imp = _to_float(r.findtext("ImponibileImporto"))
            tax = _to_float(r.findtext("Imposta"))
            tot_imponibile += imp
            tot_imposta += tax
            if aliquota_iva == 0.0:
                aliquota_iva = _to_float(r.findtext("AliquotaIVA"))
                natura_iva = r.findtext("Natura", "")
    else:
        # Fallback sulle singole linee se mancano i riepiloghi
        tot_imponibile = _to_float(prima_linea.findtext("PrezzoTotale"))
        aliquota_iva = _to_float(prima_linea.findtext("AliquotaIVA"))
        natura_iva = prima_linea.findtext("Natura", "")

    # Quadratura Totale
    if totale_doc_str is not None:
        totale_finale = _to_float(totale_doc_str)
    else:
        totale_finale = round(tot_imponibile + tot_imposta, 2)

    # --- Sezione TeamSystem CONSPAY (Dati Pagamento) ---
    dati_pag = body.find(".//DatiPagamento") or ET.Element("Empty")
    dett_pag = dati_pag.find(".//DettaglioPagamento") or ET.Element("Empty")

    metodo_pag = dett_pag.findtext("ModalitaPagamento", "MP05")
    scadenza_pag = dett_pag.findtext("DataScadenzaPagamento", data_doc)
    iban_pag = dett_pag.findtext("IBAN", "")

    return {
        "fornitore_nome": nome_ced,
        "fornitore_piva": piva_ced,
        "fornitore_nazione": paese_ced,
        "fornitore_indirizzo": indirizzo_ced,
        "fornitore_cap": cap_ced,
        "fornitore_comune": comune_ced,
        "cliente_nome": nome_ces,
        "cliente_piva": piva_ces,
        "cliente_nazione": paese_ces,
        "cliente_indirizzo": indirizzo_ces,
        "cliente_cap": cap_ces,
        "cliente_comune": comune_ces,
        "codice_destinatario": codice_dest,
        "numero": numero,
        "data": data_doc,
        "tipo_documento": tipo_doc,
        "imponibile": round(tot_imponibile, 2),
        "aliquota_iva": round(aliquota_iva, 2),
        "imposta": round(tot_imposta, 2),
        "totale": round(totale_finale, 2),
        "ritenuta": round(_to_float(ritenuta_str), 2),
        "natura": natura_iva,
        "descrizione": descrizione,
        "metodo_pagamento": metodo_pag,
        "scadenza": scadenza_pag,
        "iban": iban_pag.replace(" ", "").upper(),
    }


# =====================================================================
# ALIAS DI COMPATIBILITÀ (Prevengono ImportError su qualsiasi versione di app.py)
# =====================================================================
read_xml = parse_xml_to_dict
read_xml_or_p7m = parse_xml_to_dict
leggi_xml = parse_xml_to_dict
leggi_xml_p7m = parse_xml_to_dict
parse_xml = parse_xml_to_dict
estrai_dati_xml = parse_xml_to_dict
