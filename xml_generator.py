import xml.etree.ElementTree as ET
from xml.dom import minidom
import datetime
import re

def clean_str(val, max_len=None):
    if not val:
        return ""
    # Pulisce spazi doppi e caratteri non ammessi in XML
    s = re.sub(r'[\r\n\t]+', ' ', str(val)).strip()
    return s[:max_len] if max_len else s

def genera_xml_sdi(dati, progressivo="00001"):
    # 1. Definizione Namespace come da file di riferimento
    ns_map = {
        "ns2": "http://www.w3.org/2000/09/xmldsig#",
        "ns3": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
    }
    
    # Root: <ns3:FatturaElettronica versione="FPR12" ...>
    root = ET.Element(
        "{http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2}FatturaElettronica",
        attrib={
            "versione": "FPR12",
            "xmlns:ns2": ns_map["ns2"],
            "xmlns:ns3": ns_map["ns3"]
        }
    )
    
    # -------------------------------------------------------------
    # HEADER
    # -------------------------------------------------------------
    header = ET.SubElement(root, "FatturaElettronicaHeader")
    
    # Dati Trasmissione
    dati_trasm = ET.SubElement(header, "DatiTrasmissione")
    id_trasm = ET.SubElement(dati_trasm, "IdTrasmittente")
    ET.SubElement(id_trasm, "IdPaese").text = "IT"
    
    # P.IVA Trasmittente (pulita da IT)
    piva_forn = clean_str(dati["fornitore"].get("partita_iva", "")).replace("IT", "").strip()
    ET.SubElement(id_trasm, "IdCodice").text = piva_forn if piva_forn else "00000000000"
    
    ET.SubElement(dati_trasm, "ProgressivoInvio").text = clean_str(progressivo, 10)
    ET.SubElement(dati_trasm, "FormatoTrasmissione").text = "FPR12"
    ET.SubElement(dati_trasm, "CodiceDestinatario").text = "0000000"
    
    # Cedente Prestatore (Fornitore)
    cedente = ET.SubElement(header, "CedentePrestatore")
    anag_ced = ET.SubElement(cedente, "DatiAnagrafici")
    
    if piva_forn:
        id_fisc = ET.SubElement(anag_ced, "IdFiscaleIVA")
        ET.SubElement(id_fisc, "IdPaese").text = "IT"
        ET.SubElement(id_fisc, "IdCodice").text = piva_forn
        
    cf_forn = clean_str(dati["fornitore"].get("codice_fiscale", "")).replace("IT", "").strip()
    if cf_forn:
        ET.SubElement(anag_ced, "CodiceFiscale").text = cf_forn
    elif piva_forn:
        ET.SubElement(anag_ced, "CodiceFiscale").text = piva_forn
        
    anag_dett_ced = ET.SubElement(anag_ced, "Anagrafica")
    ET.SubElement(anag_dett_ced, "Denominazione").text = clean_str(dati["fornitore"].get("ragione_sociale", "Fornitore SRL"), 80)
    ET.SubElement(anag_ced, "RegimeFiscale").text = "RF01"
    
    sede_ced = ET.SubElement(cedente, "Sede")
    ET.SubElement(sede_ced, "Indirizzo").text = clean_str(dati["fornitore"].get("indirizzo", "Via Sede Legale"), 60)
    ET.SubElement(sede_ced, "CAP").text = clean_str(dati["fornitore"].get("cap", "00100"), 5)
    ET.SubElement(sede_ced, "Comune").text = clean_str(dati["fornitore"].get("comune", "Roma"), 60)
    ET.SubElement(sede_ced, "Provincia").text = clean_str(dati["fornitore"].get("provincia", "RM"), 2).upper()
    ET.SubElement(sede_ced, "Nazione").text = "IT"
    
    # Cessionario Committente (Cliente)
    cessionario = ET.SubElement(header, "CessionarioCommittente")
    anag_ces = ET.SubElement(cessionario, "DatiAnagrafici")
    
    piva_cli = clean_str(dati["cliente"].get("partita_iva", "")).replace("IT", "").strip()
    cf_cli = clean_str(dati["cliente"].get("codice_fiscale", "")).replace("IT", "").strip()
    
    # REGOLE ANTI-ERRORE: Inserisce IdFiscaleIVA SOLO se piva_cli è valorizzata!
    if piva_cli:
        id_fisc_ces = ET.SubElement(anag_ces, "IdFiscaleIVA")
        ET.SubElement(id_fisc_ces, "IdPaese").text = "IT"
        ET.SubElement(id_fisc_ces, "IdCodice").text = piva_cli
        
    if cf_cli:
        ET.SubElement(anag_ces, "CodiceFiscale").text = cf_cli
    elif piva_cli:
        ET.SubElement(anag_ces, "CodiceFiscale").text = piva_cli
        
    anag_dett_ces = ET.SubElement(anag_ces, "Anagrafica")
    ET.SubElement(anag_dett_ces, "Denominazione").text = clean_str(dati["cliente"].get("ragione_sociale", "Cliente"), 80)
    
    sede_ces = ET.SubElement(cessionario, "Sede")
    ET.SubElement(sede_ces, "Indirizzo").text = clean_str(dati["cliente"].get("indirizzo", "Via Sede"), 60)
    ET.SubElement(sede_ces, "CAP").text = clean_str(dati["cliente"].get("cap", "00100"), 5)
    ET.SubElement(sede_ces, "Comune").text = clean_str(dati["cliente"].get("comune", "Roma"), 60)
    ET.SubElement(sede_ces, "Provincia").text = clean_str(dati["cliente"].get("provincia", "RM"), 2).upper()
    ET.SubElement(sede_ces, "Nazione").text = "IT"

    # -------------------------------------------------------------
    # BODY
    # -------------------------------------------------------------
    body = ET.SubElement(root, "FatturaElettronicaBody")
    dati_generali = ET.SubElement(body, "DatiGenerali")
    dati_gen_doc = ET.SubElement(dati_generali, "DatiGeneraliDocumento")
    
    ET.SubElement(dati_gen_doc, "TipoDocumento").text = "TD01"
    ET.SubElement(dati_gen_doc, "Divisa").text = "EUR"
    
    data_doc = dati["documento"].get("data", datetime.date.today().isoformat())
    ET.SubElement(dati_gen_doc, "Data").text = data_doc
    
    # Sanitizzazione Numero Fattura (evita parole come 'del', 'fattura')
    num_doc = clean_str(dati["documento"].get("numero", "1"), 20)
    if num_doc.lower() in ["del", "numero", "fattura", "n", "n.", ""]:
        num_doc = "1"
    ET.SubElement(dati_gen_doc, "Numero").text = num_doc
    
    # Importo Totale Documento (ESSENZIALE PER TEAMSYSTEM)
    totale_doc = float(dati.get("totale_documento", 0.0))
    ET.SubElement(dati_gen_doc, "ImportoTotaleDocumento").text = f"{totale_doc:.2f}"
    
    # Dati Beni e Servizi
    dati_beni = ET.SubElement(body, "DatiBeniServizi")
    
    # Dettaglio Linee
    riepiloghi = dati.get("riepilogo_iva", [])
    imponibile_tot = sum([float(r.get("imponibile", 0)) for r in riepiloghi]) if riepiloghi else totale_doc
    aliquota_princ = float(riepiloghi[0].get("aliquota_iva", 22.0)) if riepiloghi else 22.0
    
    dettaglio = ET.SubElement(dati_beni, "DettaglioLinee")
    ET.SubElement(dettaglio, "NumeroLinea").text = "1"
    ET.SubElement(dettaglio, "Descrizione").text = "Prestazioni di servizi / beni come da documento"
    ET.SubElement(dettaglio, "Quantita").text = "1.00" # Richiesto da TeamSystem
    ET.SubElement(dettaglio, "PrezzoUnitario").text = f"{imponibile_tot:.2f}"
    ET.SubElement(dettaglio, "PrezzoTotale").text = f"{imponibile_tot:.2f}"
    ET.SubElement(dettaglio, "AliquotaIVA").text = f"{aliquota_princ:.2f}"
    
    # Dati Riepilogo
    for riga in riepiloghi:
        riepilogo = ET.SubElement(dati_beni, "DatiRiepilogo")
        aliq = float(riga.get("aliquota_iva", 22.0))
        imp = float(riga.get("imponibile", 0.0))
        tax = float(riga.get("imposta", 0.0))
        
        ET.SubElement(riepilogo, "AliquotaIVA").text = f"{aliq:.2f}"
        ET.SubElement(riepilogo, "ImponibileImporto").text = f"{imp:.2f}"
        ET.SubElement(riepilogo, "Imposta").text = f"{tax:.2f}"
        if aliq == 0.0:
            ET.SubElement(riepilogo, "Natura").text = "N2.2"
        ET.SubElement(riepilogo, "EsigibilitaIVA").text = "I"
        
    # Dati Pagamento (PER SCADENZARIO TEAMSYSTEM)
    dati_pag = ET.SubElement(body, "DatiPagamento")
    ET.SubElement(dati_pag, "CondizioniPagamento").text = "TP02" # Pagamento completo
    dettaglio_pag = ET.SubElement(dati_pag, "DettaglioPagamento")
    ET.SubElement(dettaglio_pag, "ModalitaPagamento").text = "MP05" # Bonifico (standard universale)
    ET.SubElement(dettaglio_pag, "DataScadenzaPagamento").text = data_doc
    ET.SubElement(dettaglio_pag, "ImportoPagamento").text = f"{totale_doc:.2f}"

    # Generazione stringa XML con formattazione identica al modello
    xml_raw = ET.tostring(root, encoding='utf-8')
    parsed_xml = minidom.parseString(xml_raw)
    
    # Fix per l'encoding nell'intestazione: <?xml version="1.0" encoding="UTF-8"?>
    pretty_xml = parsed_xml.toprettyxml(indent="    ", encoding="UTF-8").decode("utf-8")
    return pretty_xml
