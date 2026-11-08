# xml_reader.py - Motore di Decodifica e Lettura XML / P7M FatturaPA
import re
import xml.etree.ElementTree as ET
from datetime import datetime

def pulisci_cifra(s) -> float:
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    try:
        t = str(s).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
        if "," in t and "." in t:
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif "," in t:
            t = t.replace(",", ".")
        return round(float(t), 2)
    except Exception:
        return 0.0

def estrai_xml_da_p7m(file_bytes: bytes) -> bytes:
    """Estrae il contenuto XML puro da una busta crittografica PKCS#7 / P7M."""
    # Cerca l'inizio del tag XML
    pattern_inizio = re.compile(b"<\??xml|(?i)<(?:[a-z0-9]+:)?FatturaElettronica")
    match_inizio = pattern_inizio.search(file_bytes)
    
    if not match_inizio:
        return file_bytes  # Non è un p7m o è già XML in chiaro

    inizio_idx = match_inizio.start()
    
    # Cerca la chiusura del tag radice FatturaElettronica
    pattern_fine = re.compile(b"</(?:[a-z0-9]+:)?FatturaElettronica>", re.IGNORECASE)
    match_fine = pattern_fine.search(file_bytes, inizio_idx)
    
    if match_fine:
        fine_idx = match_fine.end()
        return file_bytes[inizio_idx:fine_idx]
    
    return file_bytes[inizio_idx:]

def get_node_text(element, tag_name, default=""):
    """Cerca un nodo figlio ignorando i prefissi di namespace (es. p:, ns2:, ecc.)."""
    if element is None:
        return default
    for child in element.iter():
        # Rimuove il namespace tipo {http://...}
        clean_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if clean_tag.lower() == tag_name.lower():
            return (child.text or "").strip()
    return default

def get_node(element, tag_name):
    """Restituisce il primo elemento che corrisponde al tag ignorando i namespace."""
    if element is None:
        return None
    for child in element.iter():
        clean_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if clean_tag.lower() == tag_name.lower():
            return child
    return None

def leggi_xml_fattura(file_bytes: bytes, filename: str = "fattura.xml") -> tuple:
    """
    Legge un file XML (anche firmato .p7m) e restituisce un dizionario
    perfettamente conforme al nostro standard di quadratura e TeamSystem.
    Ritorna: (dati: dict, motore: str, testo_anteprima: str, errore: str)
    """
    try:
        # 1. Decodifica se P7M
        if filename.lower().endswith(".p7m"):
            xml_bytes = estrai_xml_da_p7m(file_bytes)
        else:
            xml_bytes = file_bytes

        # 2. Parsing ElementTree con gestione encoding
        try:
            root = ET.fromstring(xml_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            root = ET.fromstring(xml_bytes.decode("latin-1"))

        # 3. Dati Trasmissione
        dati_trasm = get_node(root, "DatiTrasmissione")
        cod_sdi = get_node_text(dati_trasm, "CodiceDestinatario", "0000000")

        # 4. Cedente / Prestatore (Fornitore)
        cedente = get_node(root, "CedentePrestatore")
        dati_anag_ced = get_node(cedente, "DatiAnagrafici")
        ced_piva = get_node_text(dati_anag_ced, "IdCodice", "")
        ced_paese = get_node_text(dati_anag_ced, "IdPaese", "IT")
        ced_cf = get_node_text(dati_anag_ced, "CodiceFiscale", "")
        
        anag_ced = get_node(dati_anag_ced, "Anagrafica")
        ced_nome = get_node_text(anag_ced, "Denominazione", "")
        if not ced_nome:
            nome = get_node_text(anag_ced, "Nome", "")
            cognome = get_node_text(anag_ced, "Cognome", "")
            ced_nome = f"{cognome} {nome}".strip().upper()

        sede_ced = get_node(cedente, "Sede")
        ced_via = get_node_text(sede_ced, "Indirizzo", "")
        ced_cap = get_node_text(sede_ced, "CAP", "00100")
        ced_com = get_node_text(sede_ced, "Comune", "Roma")
        ced_prov = get_node_text(sede_ced, "Provincia", "")

        # 5. Cessionario / Committente (Cliente Studio)
        cessionario = get_node(root, "CessionarioCommittente")
        dati_anag_cess = get_node(cessionario, "DatiAnagrafici")
        cess_piva = get_node_text(dati_anag_cess, "IdCodice", "")
        cess_paese = get_node_text(dati_anag_cess, "IdPaese", "IT")
        cess_cf = get_node_text(dati_anag_cess, "CodiceFiscale", "")

        anag_cess = get_node(dati_anag_cess, "Anagrafica")
        cess_nome = get_node_text(anag_cess, "Denominazione", "")
        if not cess_nome:
            nome_c = get_node_text(anag_cess, "Nome", "")
            cognome_c = get_node_text(anag_cess, "Cognome", "")
            cess_nome = f"{cognome_c} {nome_c}".strip().upper()

        sede_cess = get_node(cessionario, "Sede")
        cess_via = get_node_text(sede_cess, "Indirizzo", "")
        cess_cap = get_node_text(sede_cess, "CAP", "00100")
        cess_com = get_node_text(sede_cess, "Comune", "Roma")
        cess_prov = get_node_text(sede_cess, "Provincia", "RM")

        # 6. Dati Generali Documento
        body = get_node(root, "FatturaElettronicaBody")
        dati_gen_doc = get_node(body, "DatiGeneraliDocumento")
        tipo_doc = get_node_text(dati_gen_doc, "TipoDocumento", "TD01")
        num_doc = get_node_text(dati_gen_doc, "Numero", "1")
        data_doc = get_node_text(dati_gen_doc, "Data", datetime.today().strftime("%Y-%m-%d"))
        totale_doc = pulisci_cifra(get_node_text(dati_gen_doc, "ImportoTotaleDocumento", 0.0))

        # Ritenuta
        dati_rit = get_node(dati_gen_doc, "DatiRitenuta")
        ritenuta = pulisci_cifra(get_node_text(dati_rit, "ImportoRitenuta", 0.0))

        # 7. Riepilogo IVA & Imponibile
        imponibile = 0.0
        imposta = 0.0
        aliquota = 22.0
        natura = ""

        beni_servizi = get_node(body, "DatiBeniServizi")
        if beni_servizi is not None:
            for child in beni_servizi:
                tag_name = child.tag.split("}")[-1]
                if tag_name.lower() == "datiriepilogo":
                    aliq_str = get_node_text(child, "AliquotaIVA", "0.00")
                    imp_str = get_node_text(child, "ImponibileImporto", "0.00")
                    iva_str = get_node_text(child, "Imposta", "0.00")
                    nat_str = get_node_text(child, "Natura", "")

                    imponibile += pulisci_cifra(imp_str)
                    imposta += pulisci_cifra(iva_str)
                    if pulisci_cifra(aliq_str) > 0:
                        aliquota = pulisci_cifra(aliq_str)
                    if nat_str:
                        natura = nat_str

        # Se totale_documento mancava nel nodo generale, calcola con ritenuta
        if totale_doc == 0.0:
            totale_doc = round(imponibile + imposta - ritenuta, 2)

        # 8. Dati Pagamento (CONSPAY)
        dati_pag = get_node(body, "DatiPagamento")
        det_pag = get_node(dati_pag, "DettaglioPagamento")
        metodo_pag = get_node_text(det_pag, "ModalitaPagamento", "MP05")
        data_scad = get_node_text(det_pag, "DataScadenzaPagamento", data_doc)
        iban_doc = get_node_text(det_pag, "IBAN", "")

        # Se nel dettaglio pagamento c'è l'importo netto a pagare
        imp_pag = pulisci_cifra(get_node_text(det_pag, "ImportoPagamento", 0.0))
        if imp_pag > 0.0 and totale_doc == 0.0:
            totale_doc = imp_pag

        dati_normalizzati = {
            "tipo_documento": tipo_doc,
            "numero_documento": num_doc,
            "data_documento": data_doc,
            "codice_destinatario": cod_sdi,
            "cedente_denominazione": ced_nome,
            "cedente_paese": ced_paese,
            "cedente_piva": ced_piva,
            "cedente_cf": ced_cf,
            "cedente_indirizzo": ced_via,
            "cedente_cap": ced_cap,
            "cedente_comune": ced_com,
            "cedente_provincia": ced_prov,
            "cessionario_denominazione": cess_nome,
            "cessionario_paese": cess_paese,
            "cessionario_piva": cess_piva,
            "cessionario_cf": cess_cf,
            "cessionario_indirizzo": cess_via,
            "cessionario_cap": cess_cap,
            "cessionario_comune": cess_com,
            "cessionario_provincia": cess_prov,
            "imponibile": round(imponibile, 2),
            "aliquota_prevalente": aliquota,
            "imposta": round(imposta, 2),
            "ritenuta": round(ritenuta, 2),
            "totale_documento": round(totale_doc, 2),
            "natura": natura,
            "iban": iban_doc,
            "data_scadenza": data_scad,
            "modalita_pagamento": metodo_pag
        }

        # Anteprima testo XML per la console
        anteprima = xml_bytes.decode("utf-8", errors="ignore")[:3000]
        return dati_normalizzati, f"Lettore Nativo XML SdI ({'P7M Firmato' if filename.lower().endswith('.p7m') else 'XML Puro'})", anteprima, None

    except Exception as e:
        return None, "Errore Parser XML", "", str(e)
