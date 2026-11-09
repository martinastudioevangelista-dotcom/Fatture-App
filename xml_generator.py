"""
xml_generator.py
Generatore Formale Tracciato FPR12 v1.2.2 conforme AdE / SdI e TeamSystem CONSPAY.
"""
import xml.etree.ElementTree as ET
from datetime import datetime
import re

# Namespace Ufficiali Ministeriali
NS_P = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOC = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2 http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_fattura_PA_v1.2.xsd"

ET.register_namespace("p", NS_P)
ET.register_namespace("ds", NS_DS)
ET.register_namespace("xsi", NS_XSI)

def _qname(tag: str) -> str:
    """Qualifica il tag con il namespace ministeriale p:."""
    return f"{{{NS_P}}}{tag}"

def _sub_el(parent, tag: str, text: str = None):
    """Crea un sotto-nodo garantendo namespace p: ed escape automatico dei caratteri speciali."""
    el = ET.SubElement(parent, _qname(tag))
    if text is not None:
        el.text = str(text).strip()
    return el

def _clean_alphanumeric(value: str, max_chars: int = 10) -> str:
    """Formatta i progressivi di invio rimuovendo caratteri speciali vietati dallo SdI."""
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(value or "1"))
    return cleaned[-max_chars:].zfill(5)

def genera_xml_teamsystem(data: dict) -> str:
    """
    Funzione attesa da app.py:
    Genera una stringa XML FPR12 conforme ad Agenzia delle Entrate e TeamSystem CONSPAY.
    """
    # 1. Radice con namespace formali FPR12
    root = ET.Element(_qname("FatturaElettronica"), {
        "versione": "FPR12",
        f"{{{NS_XSI}}}schemaLocation": SCHEMA_LOC
    })

    # -------------------------------------------------------------
    # 2. Header
    # -------------------------------------------------------------
    header = _sub_el(root, "FatturaElettronicaHeader")
    
    # Dati Trasmissione
    dt = _sub_el(header, "DatiTrasmissione")
    id_tr = _sub_el(dt, "IdTrasmittente")
    _sub_el(id_tr, "IdPaese", (data.get("cliente_nazione") or "IT")[:2].upper())
    _sub_el(id_tr, "IdCodice", data.get("cliente_piva", ""))
    _sub_el(dt, "ProgressivoInvio", _clean_alphanumeric(data.get("numero", "00001")))
    _sub_el(dt, "FormatoTrasmissione", "FPR12")
    _sub_el(dt, "CodiceDestinatario", data.get("codice_destinatario", "0000000"))

    # Cedente/Prestatore (Fornitore)
    cedente = _sub_el(header, "CedentePrestatore")
    dati_anag_ced = _sub_el(cedente, "DatiAnagrafici")
    id_fisc_ced = _sub_el(dati_anag_ced, "IdFiscaleIVA")
    forn_paese = (data.get("fornitore_nazione") or "IT")[:2].upper()
    _sub_el(id_fisc_ced, "IdPaese", forn_paese)
    _sub_el(id_fisc_ced, "IdCodice", data.get("fornitore_piva", ""))
    anag_ced = _sub_el(dati_anag_ced, "Anagrafica")
    _sub_el(anag_ced, "Denominazione", data.get("fornitore_nome", "FORNITORE"))
    _sub_el(dati_anag_ced, "RegimeFiscale", data.get("regime_fiscale", "RF01"))
    
    sede_ced = _sub_el(cedente, "Sede")
    _sub_el(sede_ced, "Indirizzo", data.get("fornitore_indirizzo", "SEDE"))
    _sub_el(sede_ced, "CAP", str(data.get("fornitore_cap", "00000")))
    _sub_el(sede_ced, "Comune", data.get("fornitore_comune", "COMUNE"))
    _sub_el(sede_ced, "Nazione", forn_paese)

    # Cessionario/Committente (Cliente)
    cessionario = _sub_el(header, "CessionarioCommittente")
    dati_anag_ces = _sub_el(cessionario, "DatiAnagrafici")
    id_fisc_ces = _sub_el(dati_anag_ces, "IdFiscaleIVA")
    cli_paese = (data.get("cliente_nazione") or "IT")[:2].upper()
    _sub_el(id_fisc_ces, "IdPaese", cli_paese)
    _sub_el(id_fisc_ces, "IdCodice", data.get("cliente_piva", ""))
    anag_ces = _sub_el(dati_anag_ces, "Anagrafica")
    _sub_el(anag_ces, "Denominazione", data.get("cliente_nome", "CLIENTE"))
    
    sede_ces = _sub_el(cessionario, "Sede")
    _sub_el(sede_ces, "Indirizzo", data.get("cliente_indirizzo", "SEDE"))
    _sub_el(sede_ces, "CAP", str(data.get("cliente_cap", "00000")))
    _sub_el(sede_ces, "Comune", data.get("cliente_comune", "COMUNE"))
    _sub_el(sede_ces, "Nazione", cli_paese)

    # -------------------------------------------------------------
    # 3. Body
    # -------------------------------------------------------------
    body = _sub_el(root, "FatturaElettronicaBody")

    # Calcoli Imponibile / IVA / Ritenuta
    imponibile = float(data.get("imponibile", 0.0) or 0.0)
    imposta = float(data.get("imposta", 0.0) or 0.0)
    totale_doc = float(data.get("totale", imponibile + imposta) or (imponibile + imposta))
    ritenuta = float(data.get("ritenuta", 0.0) or 0.0)
    aliquota = float(data.get("aliquota_iva", 0.0) or 0.0)

    # Dati Generali
    dati_generali = _sub_el(body, "DatiGenerali")
    dati_gen_doc = _sub_el(dati_generali, "DatiGeneraliDocumento")
    _sub_el(dati_gen_doc, "TipoDocumento", data.get("tipo_documento", "TD01"))
    _sub_el(dati_gen_doc, "Divisa", "EUR")
    _sub_el(dati_gen_doc, "Data", str(data.get("data", datetime.today().strftime("%Y-%m-%d"))))
    _sub_el(dati_gen_doc, "Numero", str(data.get("numero", "1")))

    # Notule professionisti (Ritenuta d'acconto)
    if ritenuta > 0:
        dati_rit = _sub_el(dati_gen_doc, "DatiRitenuta")
        _sub_el(dati_rit, "TipoRitenuta", "RT02")
        _sub_el(dati_rit, "ImportoRitenuta", f"{ritenuta:.2f}")
        _sub_el(dati_rit, "AliquotaRitenuta", "20.00")
        _sub_el(dati_rit, "CausalePagamento", "A")

    # Importo Totale Documento (Indispensabile per TeamSystem CONSPAY)
    _sub_el(dati_gen_doc, "ImportoTotaleDocumento", f"{totale_doc:.2f}")

    # Linee di Dettaglio
    beni_servizi = _sub_el(body, "BeniServizi")
    dettaglio = _sub_el(beni_servizi, "DettaglioLinee")
    _sub_el(dettaglio, "NumeroLinea", "1")
    _sub_el(dettaglio, "Descrizione", data.get("descrizione", "Prestazione di servizi / Beni"))
    _sub_el(dettaglio, "PrezzoUnitario", f"{imponibile:.2f}")
    _sub_el(dettaglio, "PrezzoTotale", f"{imponibile:.2f}")
    _sub_el(dettaglio, "AliquotaIVA", f"{aliquota:.2f}")

    # Regole Natura IVA SdI
    natura = data.get("natura")
    if aliquota == 0.0:
        natura_val = natura if natura else ("N3.2" if forn_paese != "IT" else "N2.2")
        _sub_el(dettaglio, "Natura", natura_val)

    # Riepilogo IVA
    riepilogo = _sub_el(beni_servizi, "DatiRiepilogo")
    _sub_el(riepilogo, "AliquotaIVA", f"{aliquota:.2f}")
    if aliquota == 0.0:
        _sub_el(riepilogo, "Natura", natura_val)
    _sub_el(riepilogo, "ImponibileImporto", f"{imponibile:.2f}")
    _sub_el(riepilogo, "Imposta", f"{imposta:.2f}")
    if aliquota > 0.0:
        _sub_el(riepilogo, "EsigibilitaIVA", "I")

    # -------------------------------------------------------------
    # 4. DatiPagamento (Aggancio CONSPAY TeamSystem)
    # -------------------------------------------------------------
    netto_a_pagare = totale_doc - ritenuta
    data_scadenza = str(data.get("scadenza") or data.get("data") or datetime.today().strftime("%Y-%m-%d"))

    dati_pag = _sub_el(body, "DatiPagamento")
    _sub_el(dati_pag, "CondizioniPagamento", "TP02")  # Completo

    dett_pag = _sub_el(dati_pag, "DettaglioPagamento")
    _sub_el(dett_pag, "ModalitaPagamento", data.get("metodo_pagamento", "MP05"))  # Bonifico
    _sub_el(dett_pag, "DataScadenzaPagamento", data_scadenza)
    _sub_el(dett_pag, "ImportoPagamento", f"{netto_a_pagare:.2f}")

    iban = str(data.get("iban", "")).replace(" ", "").upper()
    if iban and len(iban) >= 15:
        _sub_el(dett_pag, "IBAN", iban)

    # -------------------------------------------------------------
    # 5. Serializzazione Output
    # -------------------------------------------------------------
    raw_xml = ET.tostring(root, encoding="utf-8", method="xml").decode("utf-8")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{raw_xml}'

# Alias di sicurezza per evitare futuri errori di import
generate_sdi_xml = genera_xml_teamsystem
genera_xml = genera_xml_teamsystem
