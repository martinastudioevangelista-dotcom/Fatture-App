# xml_generator.py
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

def genera_xml_teamsystem(dati: dict) -> str:
    """
    Genera il tracciato XML conforme allo standard FatturaPA 1.2 (FPR12)
    ottimizzato per l'importazione nei gestionali TeamSystem.
    """
    root = ET.Element("p:FatturaElettronica", {
        "versione": "FPR12",
        "xmlns:ds": "http://www.w3.org/2000/09/xmldsig#",
        "xmlns:p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2 http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_fattura_PA_v1.2.xsd"
    })

    # 1. Header - Dati Trasmissione
    header = ET.SubElement(root, "FatturaElettronicaHeader")
    dati_trasm = ET.SubElement(header, "DatiTrasmissione")
    id_trasm = ET.SubElement(dati_trasm, "IdTrasmittente")
    ET.SubElement(id_trasm, "IdPaese").text = "IT"
    clean_piva_cedente = dati.get("cedente_piva", "00000000000").replace("IT", "").strip()
    ET.SubElement(id_trasm, "IdCodice").text = clean_piva_cedente if clean_piva_cedente else "00000000000"
    ET.SubElement(dati_trasm, "ProgressivoInvio").text = str(dati.get("progressivo", "00001"))[:10]
    ET.SubElement(dati_trasm, "FormatoTrasmissione").text = "FPR12"
    ET.SubElement(dati_trasm, "CodiceDestinatario").text = str(dati.get("codice_destinatario", "0000000")).strip()

    # 2. Cedente / Prestatore (Fornitore)
    cedente = ET.SubElement(header, "CedentePrestatore")
    dati_anag_ced = ET.SubElement(cedente, "DatiAnagrafici")
    id_fisc_ced = ET.SubElement(dati_anag_ced, "IdFiscaleIVA")
    ET.SubElement(id_fisc_ced, "IdPaese").text = dati.get("cedente_nazione", "IT")
    ET.SubElement(id_fisc_ced, "IdCodice").text = clean_piva_cedente if clean_piva_cedente else "00000000000"
    
    if dati.get("cedente_cf"):
        ET.SubElement(dati_anag_ced, "CodiceFiscale").text = str(dati["cedente_cf"]).strip()
        
    anag_ced = ET.SubElement(dati_anag_ced, "Anagrafica")
    ET.SubElement(anag_ced, "Denominazione").text = str(dati.get("cedente_denominazione", "FORNITORE"))[:80]
    ET.SubElement(dati_anag_ced, "RegimeFiscale").text = str(dati.get("regime_fiscale", "RF01"))
    
    sede_ced = ET.SubElement(cedente, "Sede")
    ET.SubElement(sede_ced, "Indirizzo").text = str(dati.get("cedente_indirizzo", "Via Sede 1"))[:60]
    ET.SubElement(sede_ced, "CAP").text = str(dati.get("cedente_cap", "00100"))[:5]
    ET.SubElement(sede_ced, "Comune").text = str(dati.get("cedente_comune", "Roma"))[:60]
    ET.SubElement(sede_ced, "Nazione").text = str(dati.get("cedente_nazione", "IT"))[:2]

    # 3. Cessionario / Committente (Cliente Studio)
    cessionario = ET.SubElement(header, "CessionarioCommittente")
    dati_anag_cess = ET.SubElement(cessionario, "DatiAnagrafici")
    clean_piva_cess = dati.get("cessionario_piva", "").replace("IT", "").strip()
    if clean_piva_cess:
        id_fisc_cess = ET.SubElement(dati_anag_cess, "IdFiscaleIVA")
        ET.SubElement(id_fisc_cess, "IdPaese").text = dati.get("cessionario_nazione", "IT")
        ET.SubElement(id_fisc_cess, "IdCodice").text = clean_piva_cess
    if dati.get("cessionario_cf"):
        ET.SubElement(dati_anag_cess, "CodiceFiscale").text = str(dati["cessionario_cf"]).strip()
        
    anag_cess = ET.SubElement(dati_anag_cess, "Anagrafica")
    ET.SubElement(anag_cess, "Denominazione").text = str(dati.get("cessionario_denominazione", "CLIENTE"))[:80]
    
    sede_cess = ET.SubElement(cessionario, "Sede")
    ET.SubElement(sede_cess, "Indirizzo").text = str(dati.get("cessionario_indirizzo", "Via Cliente 1"))[:60]
    ET.SubElement(sede_cess, "CAP").text = str(dati.get("cessionario_cap", "00100"))[:5]
    ET.SubElement(sede_cess, "Comune").text = str(dati.get("cessionario_comune", "Roma"))[:60]
    ET.SubElement(sede_cess, "Nazione").text = str(dati.get("cessionario_nazione", "IT"))[:2]

    # 4. Body - Dati Generali
    body = ET.SubElement(root, "FatturaElettronicaBody")
    dati_gen = ET.SubElement(body, "DatiGenerali")
    dati_doc = ET.SubElement(dati_gen, "DatiGeneraliDocumento")
    ET.SubElement(dati_doc, "TipoDocumento").text = dati.get("tipo_documento", "TD01")
    ET.SubElement(dati_doc, "Divisa").text = "EUR"
    ET.SubElement(dati_doc, "Data").text = str(dati.get("data_documento", datetime.today().strftime("%Y-%m-%d")))
    ET.SubElement(dati_doc, "Numero").text = str(dati.get("numero_documento", "1"))[:20]
    
    # Eventuale Ritenuta d'acconto
    if float(dati.get("ritenuta", 0.0)) > 0:
        dati_rit = ET.SubElement(dati_doc, "DatiRitenuta")
        ET.SubElement(dati_rit, "TipoRitenuta").text = "RT02"  # RT02 persone giuridiche / RT01 fisiche
        ET.SubElement(dati_rit, "ImportoRitenuta").text = f"{float(dati['ritenuta']):.2f}"
        ET.SubElement(dati_rit, "AliquotaRitenuta").text = "20.00"
        ET.SubElement(dati_rit, "CausalePagamento").text = "A"

    # Eventuale Bollo
    if float(dati.get("bollo", 0.0)) > 0:
        dati_bollo = ET.SubElement(dati_doc, "DatiBollo")
        ET.SubElement(dati_bollo, "BolloVirtuale").text = "SI"
        ET.SubElement(dati_bollo, "ImportoBollo").text = f"{float(dati['bollo']):.2f}"

    ET.SubElement(dati_doc, "ImportoTotaleDocumento").text = f"{float(dati.get('totale_documento', 0.0)):.2f}"

    # 5. Dettaglio Beni e Servizi
    dati_beni = ET.SubElement(body, "DatiBeniServizi")
    linee = dati.get("linee", [])
    if not linee:
        linee = [{
            "descrizione": "Merci e prestazioni di servizi",
            "prezzo_unitario": float(dati.get("totale_documento", 0.0)),
            "prezzo_totale": float(dati.get("totale_documento", 0.0)),
            "aliquota": 22.0
        }]

    for idx, linea in enumerate(linee, start=1):
        det_linea = ET.SubElement(dati_beni, "DettaglioLinee")
        ET.SubElement(det_linea, "NumeroLinea").text = str(idx)
        ET.SubElement(det_linea, "Descrizione").text = str(linea.get("descrizione", "Merci/Servizi"))[:990]
        ET.SubElement(det_linea, "PrezzoUnitario").text = f"{float(linea.get('prezzo_unitario', 0.0)):.2f}"
        ET.SubElement(det_linea, "PrezzoTotale").text = f"{float(linea.get('prezzo_totale', 0.0)):.2f}"
        aliq = float(linea.get("aliquota", 22.0))
        ET.SubElement(det_linea, "AliquotaIVA").text = f"{aliq:.2f}"
        if aliq == 0.0 and linea.get("natura"):
            ET.SubElement(det_linea, "Natura").text = str(linea["natura"]).strip()

    # 6. Dati Riepilogo IVA
    for riepilogo in dati.get("riepilogo_iva", []):
        dati_rie = ET.SubElement(dati_beni, "DatiRiepilogo")
        aliq = float(riepilogo.get("aliquota", 22.0))
        ET.SubElement(dati_rie, "AliquotaIVA").text = f"{aliq:.2f}"
        if aliq == 0.0 and riepilogo.get("natura"):
            ET.SubElement(dati_rie, "Natura").text = str(riepilogo["natura"]).strip()
        ET.SubElement(dati_rie, "ImponibileImporto").text = f"{float(riepilogo.get('imponibile', 0.0)):.2f}"
        ET.SubElement(dati_rie, "Imposta").text = f"{float(riepilogo.get('imposta', 0.0)):.2f}"
        ET.SubElement(dati_rie, "EsigibilitaIVA").text = str(riepilogo.get("esigibilita", "I"))

    # Indentazione e serializzazione XML
    xml_str = ET.tostring(root, encoding="utf-8")
    parsed_xml = minidom.parseString(xml_str)
    return parsed_xml.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

# Alias di sicurezza per evitare futuri ImportError
generate_xml = genera_xml_teamsystem
crea_xml_teamsystem = genera_xml_teamsystem
crea_xml_sdi = genera_xml_teamsystem
