# xml_generator.py - Generatore FPR12 conforme ad Agenzia delle Entrate e TeamSystem CONSPAY
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

def genera_xml_teamsystem(dati: dict) -> str:
    """Genera tracciato FatturaPA 1.2.2 (FPR12) idoneo alla riconciliazione bancaria CONSPAY."""
    root = ET.Element("p:FatturaElettronica", {
        "versione": "FPR12",
        "xmlns:ds": "http://www.w3.org/2000/09/xmldsig#",
        "xmlns:p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2 http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_fattura_PA_v1.2.xsd"
    })

    # 1. HEADER
    header = ET.SubElement(root, "FatturaElettronicaHeader")
    dati_trasm = ET.SubElement(header, "DatiTrasmissione")
    id_trasm = ET.SubElement(dati_trasm, "IdTrasmittente")
    ET.SubElement(id_trasm, "IdPaese").text = "IT"
    piva_ced = dati.get("cedente_piva", "").replace("IT", "").strip() or "00000000000"
    ET.SubElement(id_trasm, "IdCodice").text = piva_ced
    ET.SubElement(dati_trasm, "ProgressivoInvio").text = str(dati.get("numero_documento", "1"))[:10].replace("/", "")
    ET.SubElement(dati_trasm, "FormatoTrasmissione").text = "FPR12"
    ET.SubElement(dati_trasm, "CodiceDestinatario").text = str(dati.get("codice_destinatario", "0000000")).strip()

    # Cedente/Prestatore (Fornitore)
    cedente = ET.SubElement(header, "CedentePrestatore")
    dati_anag_ced = ET.SubElement(cedente, "DatiAnagrafici")
    id_fisc_ced = ET.SubElement(dati_anag_ced, "IdFiscaleIVA")
    ET.SubElement(id_fisc_ced, "IdPaese").text = "IT"
    ET.SubElement(id_fisc_ced, "IdCodice").text = piva_ced
    if dati.get("cedente_cf"):
        ET.SubElement(dati_anag_ced, "CodiceFiscale").text = str(dati["cedente_cf"]).strip()
    anag_ced = ET.SubElement(dati_anag_ced, "Anagrafica")
    ET.SubElement(anag_ced, "Denominazione").text = str(dati.get("cedente_denominazione", "FORNITORE"))[:80]
    ET.SubElement(dati_anag_ced, "RegimeFiscale").text = str(dati.get("regime_fiscale", "RF01"))
    
    sede_ced = ET.SubElement(cedente, "Sede")
    ET.SubElement(sede_ced, "Indirizzo").text = str(dati.get("cedente_indirizzo", "Via Sede 1"))[:60]
    ET.SubElement(sede_ced, "CAP").text = str(dati.get("cedente_cap", "00100"))[:5]
    ET.SubElement(sede_ced, "Comune").text = str(dati.get("cedente_comune", "Roma"))[:60]
    ET.SubElement(sede_ced, "Provincia").text = str(dati.get("cedente_provincia", "RM"))[:2].upper()
    ET.SubElement(sede_ced, "Nazione").text = "IT"

    # Cessionario/Committente (Cliente dello Studio)
    cessionario = ET.SubElement(header, "CessionarioCommittente")
    dati_anag_cess = ET.SubElement(cessionario, "DatiAnagrafici")
    piva_cess = dati.get("cessionario_piva", "").replace("IT", "").strip()
    if piva_cess:
        id_fisc_cess = ET.SubElement(dati_anag_cess, "IdFiscaleIVA")
        ET.SubElement(id_fisc_cess, "IdPaese").text = "IT"
        ET.SubElement(id_fisc_cess, "IdCodice").text = piva_cess
    if dati.get("cessionario_cf"):
        ET.SubElement(dati_anag_cess, "CodiceFiscale").text = str(dati["cessionario_cf"]).strip()
    anag_cess = ET.SubElement(dati_anag_cess, "Anagrafica")
    ET.SubElement(anag_cess, "Denominazione").text = str(dati.get("cessionario_denominazione", "CLIENTE"))[:80]
    
    sede_cess = ET.SubElement(cessionario, "Sede")
    ET.SubElement(sede_cess, "Indirizzo").text = str(dati.get("cessionario_indirizzo", "Via Cliente 10"))[:60]
    ET.SubElement(sede_cess, "CAP").text = str(dati.get("cessionario_cap", "00100"))[:5]
    ET.SubElement(sede_cess, "Comune").text = str(dati.get("cessionario_comune", "Roma"))[:60]
    ET.SubElement(sede_cess, "Provincia").text = str(dati.get("cessionario_provincia", "RM"))[:2].upper()
    ET.SubElement(sede_cess, "Nazione").text = "IT"

    # 2. BODY
    body = ET.SubElement(root, "FatturaElettronicaBody")
    dati_gen = ET.SubElement(body, "DatiGenerali")
    dati_doc = ET.SubElement(dati_gen, "DatiGeneraliDocumento")
    ET.SubElement(dati_doc, "TipoDocumento").text = dati.get("tipo_documento", "TD01")
    ET.SubElement(dati_doc, "Divisa").text = "EUR"
    ET.SubElement(dati_doc, "Data").text = str(dati.get("data_documento", datetime.today().strftime("%Y-%m-%d")))
    ET.SubElement(dati_doc, "Numero").text = str(dati.get("numero_documento", "1"))[:20]
    totale_doc = float(dati.get("totale_documento", 0.0))
    ET.SubElement(dati_doc, "ImportoTotaleDocumento").text = f"{totale_doc:.2f}"

    # Beni e Servizi
    dati_beni = ET.SubElement(body, "DatiBeniServizi")
    linee = dati.get("linee", [])
    if not linee:
        linee = [{"descrizione": "Merci/Servizi", "prezzo_totale": totale_doc, "aliquota": 22.0}]

    for idx, linea in enumerate(linee, start=1):
        det_linea = ET.SubElement(dati_beni, "DettaglioLinee")
        ET.SubElement(det_linea, "NumeroLinea").text = str(idx)
        ET.SubElement(det_linea, "Descrizione").text = str(linea.get("descrizione", "Merci/Servizi"))[:990]
        pr_tot = float(linea.get("prezzo_totale", 0.0))
        ET.SubElement(det_linea, "PrezzoUnitario").text = f"{pr_tot:.2f}"
        ET.SubElement(det_linea, "PrezzoTotale").text = f"{pr_tot:.2f}"
        aliq = float(linea.get("aliquota", 22.0))
        ET.SubElement(det_linea, "AliquotaIVA").text = f"{aliq:.2f}"
        if aliq == 0.0 and linea.get("natura"):
            ET.SubElement(det_linea, "Natura").text = str(linea["natura"]).strip()

    # Dati Riepilogo IVA
    for rie in dati.get("riepilogo_iva", []):
        dati_rie = ET.SubElement(dati_beni, "DatiRiepilogo")
        aliq = float(rie.get("aliquota", 22.0))
        ET.SubElement(dati_rie, "AliquotaIVA").text = f"{aliq:.2f}"
        if aliq == 0.0 and rie.get("natura"):
            ET.SubElement(dati_rie, "Natura").text = str(rie["natura"]).strip()
        ET.SubElement(dati_rie, "ImponibileImporto").text = f"{float(rie.get('imponibile', 0.0)):.2f}"
        ET.SubElement(dati_rie, "Imposta").text = f"{float(rie.get('imposta', 0.0)):.2f}"
        ET.SubElement(dati_rie, "EsigibilitaIVA").text = str(rie.get("esigibilita", "I"))

    # 3. DATI PAGAMENTO FONDAMENTALI PER TEAMSYSTEM CONSPAY (Blocco 2.4 XSD)
    dati_pag = ET.SubElement(body, "DatiPagamento")
    ET.SubElement(dati_pag, "CondizioniPagamento").text = "TP02"  # Pagamento completo
    det_pag = ET.SubElement(dati_pag, "DettaglioPagamento")
    
    # Modalità pagamento: MP05 (Bonifico), MP08 (Carta), MP01 (Contanti)
    metodo = dati.get("modalita_pagamento", "MP05")
    ET.SubElement(det_pag, "ModalitaPagamento").text = metodo
    ET.SubElement(det_pag, "DataScadenzaPagamento").text = str(dati.get("data_scadenza", dati.get("data_documento")))
    ET.SubElement(det_pag, "ImportoPagamento").text = f"{totale_doc:.2f}"
    
    # IBAN per riconciliazione automatica estratto conto bancario in CONSPAY
    iban_val = str(dati.get("iban", "")).strip().replace(" ", "")
    if iban_val:
        ET.SubElement(det_pag, "IBAN").text = iban_val

    xml_raw = ET.tostring(root, encoding="utf-8")
    parsed_xml = minidom.parseString(xml_raw)
    return parsed_xml.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
