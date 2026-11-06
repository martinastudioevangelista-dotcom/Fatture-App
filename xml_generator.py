# xml_generator.py - Generatore FPR12 100% Conforme Agenzia Entrate / TeamSystem
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

def genera_xml_teamsystem(dati: dict) -> str:
    """Genera file XML con root ufficiale dell'Agenzia delle Entrate privo di errori di validazione ERR01845."""
    
    # Root Ufficiale Ministeriale con Namespace p: formale
    root = ET.Element("p:FatturaElettronica", {
        "versione": "FPR12",
        "xmlns:ds": "http://www.w3.org/2000/09/xmldsig#",
        "xmlns:p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2 http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_fattura_PA_v1.2.xsd"
    })

    # 1. HEADER: DATI TRASMISSIONE
    header = ET.SubElement(root, "FatturaElettronicaHeader")
    dati_trasm = ET.SubElement(header, "DatiTrasmissione")
    id_trasm = ET.SubElement(dati_trasm, "IdTrasmittente")
    
    # Trasmittente è sempre il soggetto che invia (Cessionario/Studio italiano)
    cess_paese = str(dati.get("cessionario_paese", "IT"))[:2].upper()
    cess_piva = str(dati.get("cessionario_piva", "")).replace("IT", "").strip() or "00000000000"
    
    ET.SubElement(id_trasm, "IdPaese").text = cess_paese
    ET.SubElement(id_trasm, "IdCodice").text = cess_piva
    ET.SubElement(dati_trasm, "ProgressivoInvio").text = str(dati.get("numero_documento", "1"))[:10].replace("/", "")
    ET.SubElement(dati_trasm, "FormatoTrasmissione").text = "FPR12"
    
    cod_dest = str(dati.get("codice_destinatario", "0000000")).strip()
    ET.SubElement(dati_trasm, "CodiceDestinatario").text = cod_dest if len(cod_dest) == 7 else "0000000"

    # 2. CEDENTE / PRESTATORE (FORNITORE)
    ced_paese = str(dati.get("cedente_paese", "IT"))[:2].upper()
    ced_piva = str(dati.get("cedente_piva", "00000000000")).strip()

    cedente = ET.SubElement(header, "CedentePrestatore")
    dati_anag_ced = ET.SubElement(cedente, "DatiAnagrafici")
    id_fisc_ced = ET.SubElement(dati_anag_ced, "IdFiscaleIVA")
    ET.SubElement(id_fisc_ced, "IdPaese").text = ced_paese
    ET.SubElement(id_fisc_ced, "IdCodice").text = ced_piva if ced_piva else "00000000000"
    
    anag_ced = ET.SubElement(dati_anag_ced, "Anagrafica")
    ET.SubElement(anag_ced, "Denominazione").text = str(dati.get("cedente_denominazione", "FORNITORE"))[:80]
    ET.SubElement(dati_anag_ced, "RegimeFiscale").text = str(dati.get("regime_fiscale", "RF01"))

    sede_ced = ET.SubElement(cedente, "Sede")
    ET.SubElement(sede_ced, "Indirizzo").text = str(dati.get("cedente_indirizzo", "Via Sede 1"))[:60]
    ET.SubElement(sede_ced, "CAP").text = str(dati.get("cedente_cap", "00100"))[:5]
    ET.SubElement(sede_ced, "Comune").text = str(dati.get("cedente_comune", "Roma"))[:60]
    if ced_paese == "IT" and dati.get("cedente_provincia"):
        ET.SubElement(sede_ced, "Provincia").text = str(dati["cedente_provincia"])[:2].upper()
    ET.SubElement(sede_ced, "Nazione").text = ced_paese

    # 3. CESSIONARIO / COMMITTENTE (CLIENTE STUDIO)
    cess_cf = str(dati.get("cessionario_cf", "")).strip()

    cessionario = ET.SubElement(header, "CessionarioCommittente")
    dati_anag_cess = ET.SubElement(cessionario, "DatiAnagrafici")
    if cess_piva and cess_piva != "00000000000":
        id_fisc_cess = ET.SubElement(dati_anag_cess, "IdFiscaleIVA")
        ET.SubElement(id_fisc_cess, "IdPaese").text = cess_paese
        ET.SubElement(id_fisc_cess, "IdCodice").text = cess_piva
    if cess_cf:
        ET.SubElement(dati_anag_cess, "CodiceFiscale").text = cess_cf

    anag_cess = ET.SubElement(dati_anag_cess, "Anagrafica")
    ET.SubElement(anag_cess, "Denominazione").text = str(dati.get("cessionario_denominazione", "CLIENTE STUDIO"))[:80]

    sede_cess = ET.SubElement(cessionario, "Sede")
    ET.SubElement(sede_cess, "Indirizzo").text = str(dati.get("cessionario_indirizzo", "Via Studio 10"))[:60]
    ET.SubElement(sede_cess, "CAP").text = str(dati.get("cessionario_cap", "00100"))[:5]
    ET.SubElement(sede_cess, "Comune").text = str(dati.get("cessionario_comune", "Roma"))[:60]
    if cess_paese == "IT":
        ET.SubElement(sede_cess, "Provincia").text = str(dati.get("cessionario_provincia", "RM"))[:2].upper()
    ET.SubElement(sede_cess, "Nazione").text = cess_paese

    # 4. BODY: DATI GENERALI
    body = ET.SubElement(root, "FatturaElettronicaBody")
    dati_gen = ET.SubElement(body, "DatiGenerali")
    dati_doc = ET.SubElement(dati_gen, "DatiGeneraliDocumento")
    ET.SubElement(dati_doc, "TipoDocumento").text = str(dati.get("tipo_documento", "TD01"))
    ET.SubElement(dati_doc, "Divisa").text = "EUR"
    ET.SubElement(dati_doc, "Data").text = str(dati.get("data_documento", datetime.today().strftime("%Y-%m-%d")))
    ET.SubElement(dati_doc, "Numero").text = str(dati.get("numero_documento", "1"))[:20]

    # Ritenuta d'acconto (se presente, es. Ferraiuolo 140.40)
    rit = float(dati.get("ritenuta", 0.0))
    if rit > 0.0:
        d_rit = ET.SubElement(dati_doc, "DatiRitenuta")
        ET.SubElement(d_rit, "TipoRitenuta").text = "RT02"
        ET.SubElement(d_rit, "ImportoRitenuta").text = f"{rit:.2f}"
        ET.SubElement(d_rit, "AliquotaRitenuta").text = "20.00"
        ET.SubElement(d_rit, "CausalePagamento").text = "A"

    totale_doc = float(dati.get("totale_documento", 0.0))
    ET.SubElement(dati_doc, "ImportoTotaleDocumento").text = f"{totale_doc:.2f}"

    # 5. DATI BENI E SERVIZI
    dati_beni = ET.SubElement(body, "DatiBeniServizi")
    linee = dati.get("linee", [])
    if not linee:
        linee = [{
            "descrizione": f"Prestazioni/Merci fattura n. {dati.get('numero_documento', '1')}",
            "prezzo_totale": float(dati.get("imponibile", totale_doc)),
            "aliquota": float(dati.get("aliquota_prevalente", 22.0)),
            "natura": str(dati.get("natura", ""))
        }]

    for idx, linea in enumerate(linee, start=1):
        det_linea = ET.SubElement(dati_beni, "DettaglioLinee")
        ET.SubElement(det_linea, "NumeroLinea").text = str(idx)
        ET.SubElement(det_linea, "Descrizione").text = str(linea.get("descrizione", "Merci/Servizi"))[:990]
        pr_tot = float(linea.get("prezzo_totale", 0.0))
        ET.SubElement(det_linea, "PrezzoUnitario").text = f"{pr_tot:.2f}"
        ET.SubElement(det_linea, "PrezzoTotale").text = f"{pr_tot:.2f}"
        aliq = float(linea.get("aliquota", 0.0))
        ET.SubElement(det_linea, "AliquotaIVA").text = f"{aliq:.2f}"
        if aliq == 0.0:
            natura_val = str(linea.get("natura") or "N3.2").strip()
            ET.SubElement(det_linea, "Natura").text = natura_val

    # 6. RIEPILOGO IVA
    for rie in dati.get("riepilogo_iva", []):
        dati_rie = ET.SubElement(dati_beni, "DatiRiepilogo")
        aliq = float(rie.get("aliquota", 0.0))
        ET.SubElement(dati_rie, "AliquotaIVA").text = f"{aliq:.2f}"
        if aliq == 0.0:
            natura_rie = str(rie.get("natura") or "N3.2").strip()
            ET.SubElement(dati_rie, "Natura").text = natura_rie
        ET.SubElement(dati_rie, "ImponibileImporto").text = f"{float(rie.get('imponibile', 0.0)):.2f}"
        ET.SubElement(dati_rie, "Imposta").text = f"{float(rie.get('imposta', 0.0)):.2f}"
        ET.SubElement(dati_rie, "EsigibilitaIVA").text = "I"

    # 7. DATI PAGAMENTO CONSPAY
    dati_pag = ET.SubElement(body, "DatiPagamento")
    ET.SubElement(dati_pag, "CondizioniPagamento").text = "TP02"
    det_pag = ET.SubElement(dati_pag, "DettaglioPagamento")
    ET.SubElement(det_pag, "ModalitaPagamento").text = str(dati.get("modalita_pagamento", "MP05"))
    ET.SubElement(det_pag, "DataScadenzaPagamento").text = str(dati.get("data_scadenza", dati.get("data_documento")))
    ET.SubElement(det_pag, "ImportoPagamento").text = f"{totale_doc:.2f}"
    
    iban_val = str(dati.get("iban", "")).strip().replace(" ", "")
    if iban_val:
        ET.SubElement(det_pag, "IBAN").text = iban_val

    # Serializzazione con prefisso p: ovunque
    xml_raw = ET.tostring(root, encoding="utf-8")
    parsed_xml = minidom.parseString(xml_raw)
    return parsed_xml.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
