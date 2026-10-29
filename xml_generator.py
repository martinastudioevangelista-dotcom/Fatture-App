import xml.etree.ElementTree as ET
from xml.dom import minidom
import datetime

def genera_xml_sdi(dati, progressivo="00001"):
    # Root Element (Fattura Elettronica v1.2)
    ns_map = {"p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"}
    root = ET.Element("{http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2}FatturaElettronica", 
                      versione="FPR12")
    
    # --- HEADER ---
    header = ET.SubElement(root, "FatturaElettronicaHeader")
    
    # Dati Trasmissione
    trasmissione = ET.SubElement(header, "DatiTrasmissione")
    id_trasmittente = ET.SubElement(trasmissione, "IdTrasmittente")
    ET.SubElement(id_trasmittente, "IdPaese").text = "IT"
    ET.SubElement(id_trasmittente, "IdCodice").text = dati["fornitore"].get("partita_iva", "").replace("IT", "")
    ET.SubElement(trasmissione, "ProgressivoInvio").text = progressivo
    ET.SubElement(trasmissione, "FormatoTrasmissione").text = "FPR12"
    ET.SubElement(trasmissione, "CodiceDestinatario").text = "0000000"
    
    # Cedente Prestatore (Fornitore)
    cedente = ET.SubElement(header, "CedentePrestatore")
    dati_anag_ced = ET.SubElement(cedente, "DatiAnagrafici")
    id_fisc_iva = ET.SubElement(dati_anag_ced, "IdFiscaleIVA")
    ET.SubElement(id_fisc_iva, "IdPaese").text = "IT"
    ET.SubElement(id_fisc_iva, "IdCodice").text = dati["fornitore"].get("partita_iva", "")
    anagrafica_ced = ET.SubElement(dati_anag_ced, "Anagrafica")
    ET.SubElement(anagrafica_ced, "Denominazione").text = dati["fornitore"].get("ragione_sociale", "Sconosciuto")
    ET.SubElement(dati_anag_ced, "RegimeFiscale").text = "RF01"
    sede_ced = ET.SubElement(cedente, "Sede")
    ET.SubElement(sede_ced, "Indirizzo").text = dati["fornitore"].get("indirizzo", "")
    ET.SubElement(sede_ced, "CAP").text = dati["fornitore"].get("cap", "00000")
    ET.SubElement(sede_ced, "Comune").text = dati["fornitore"].get("comune", "")
    ET.SubElement(sede_ced, "Provincia").text = dati["fornitore"].get("provincia", "EE")
    ET.SubElement(sede_ced, "Nazione").text = "IT"

    # Cessionario Committente (Cliente)
    cessionario = ET.SubElement(header, "CessionarioCommittente")
    dati_anag_ces = ET.SubElement(cessionario, "DatiAnagrafici")
    id_fisc_iva_ces = ET.SubElement(dati_anag_ces, "IdFiscaleIVA")
    ET.SubElement(id_fisc_iva_ces, "IdPaese").text = "IT"
    ET.SubElement(id_fisc_iva_ces, "IdCodice").text = dati["cliente"].get("partita_iva", "")
    anagrafica_ces = ET.SubElement(dati_anag_ces, "Anagrafica")
    ET.SubElement(anagrafica_ces, "Denominazione").text = dati["cliente"].get("ragione_sociale", "Sconosciuto")
    sede_ces = ET.SubElement(cessionario, "Sede")
    ET.SubElement(sede_ces, "Indirizzo").text = dati["cliente"].get("indirizzo", "")
    ET.SubElement(sede_ces, "CAP").text = dati["cliente"].get("cap", "00000")
    ET.SubElement(sede_ces, "Comune").text = dati["cliente"].get("comune", "")
    ET.SubElement(sede_ces, "Provincia").text = dati["cliente"].get("provincia", "EE")
    ET.SubElement(sede_ces, "Nazione").text = "IT"

    # --- BODY ---
    body = ET.SubElement(root, "FatturaElettronicaBody")
    dati_generali = ET.SubElement(body, "DatiGenerali")
    dati_gen_doc = ET.SubElement(dati_generali, "DatiGeneraliDocumento")
    ET.SubElement(dati_gen_doc, "TipoDocumento").text = "TD01"
    ET.SubElement(dati_gen_doc, "Divisa").text = "EUR"
    ET.SubElement(dati_gen_doc, "Data").text = dati["documento"].get("data", datetime.date.today().isoformat())
    ET.SubElement(dati_gen_doc, "Numero").text = str(dati["documento"].get("numero", "1"))

    # Beni e Servizi & Riepilogo
    dati_beni = ET.SubElement(body, "DatiBeniServizi")
    dettaglio = ET.SubElement(dati_beni, "DettaglioLinee")
    ET.SubElement(dettaglio, "NumeroLinea").text = "1"
    ET.SubElement(dettaglio, "Descrizione").text = "Servizi/Beni come da PDF"
    imponibile_tot = sum([float(r.get("imponibile", 0)) for r in dati.get("riepilogo_iva", [])])
    aliquota_max = max([float(r.get("aliquota_iva", 22)) for r in dati.get("riepilogo_iva", [])]) if dati.get("riepilogo_iva") else 22.0
    ET.SubElement(dettaglio, "PrezzoUnitario").text = f"{imponibile_tot:.2f}"
    ET.SubElement(dettaglio, "PrezzoTotale").text = f"{imponibile_tot:.2f}"
    ET.SubElement(dettaglio, "AliquotaIVA").text = f"{aliquota_max:.2f}"

    for riga in dati.get("riepilogo_iva", []):
        riepilogo = ET.SubElement(dati_beni, "DatiRiepilogo")
        aliquota = float(riga.get("aliquota_iva", 0))
        ET.SubElement(riepilogo, "AliquotaIVA").text = f"{aliquota:.2f}"
        ET.SubElement(riepilogo, "ImponibileImporto").text = f"{float(riga.get('imponibile',0)):.2f}"
        ET.SubElement(riepilogo, "Imposta").text = f"{float(riga.get('imposta',0)):.2f}"
        if aliquota == 0:
            ET.SubElement(riepilogo, "Natura").text = "N2.2"
        ET.SubElement(riepilogo, "EsigibilitaIVA").text = "I"

    xml_str = ET.tostring(root, encoding='utf-8')
    parsed_xml = minidom.parseString(xml_str)
    return parsed_xml.toprettyxml(indent="  ")
