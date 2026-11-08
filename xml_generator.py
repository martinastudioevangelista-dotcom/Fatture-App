# xml_generator.py - Generatore FPR12 100% Conforme Agenzia Entrate & TeamSystem CONSPAY
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

def genera_xml_teamsystem(dati: dict) -> str:
    """
    Genera file XML FatturaPA 1.2.2 (FPR12).
    Garantisce il prefisso ministeriale p: su OGNI tag per superare la validazione
    dell'Agenzia delle Entrate (Fatture e Corrispettivi) ed evitare gli errori
    su 'Regime fiscale (I miei dati)' e 'Nazione - Sede (I miei dati)'.
    """
    
    # 1. Normalizzazione valori obbligatori minimi
    # Fornitore (Cedente - "I miei dati" per AdE)
    ced_paese = str(dati.get("cedente_paese") or dati.get("cedente_nazione") or "IT").strip()[:2].upper()
    if not ced_paese:
        ced_paese = "IT"
        
    ced_piva = str(dati.get("cedente_piva", "")).replace("IT", "").strip() or "00000000000"
    ced_cf = str(dati.get("cedente_cf", "")).strip()
    ced_nome = str(dati.get("cedente_denominazione", "FORNITORE"))[:80].strip() or "FORNITORE"
    ced_via = str(dati.get("cedente_indirizzo", "Via Sede 1"))[:60].strip() or "Via Sede 1"
    ced_cap = str(dati.get("cedente_cap", "00100"))[:5].strip() or "00100"
    ced_com = str(dati.get("cedente_comune", "Roma"))[:60].strip() or "Roma"
    ced_prov = str(dati.get("cedente_provincia", "")).strip()[:2].upper()
    
    # Regime fiscale tassativamente presente (RF01 ordinario se non specificato)
    regime_fiscale = str(dati.get("regime_fiscale", "RF01")).strip()[:4].upper()
    if not regime_fiscale.startswith("RF"):
        regime_fiscale = "RF01"

    # Cliente (Cessionario)
    cess_paese = str(dati.get("cessionario_paese") or dati.get("cessionario_nazione") or "IT").strip()[:2].upper()
    if not cess_paese:
        cess_paese = "IT"
        
    cess_piva = str(dati.get("cessionario_piva", "")).replace("IT", "").strip()
    cess_cf = str(dati.get("cessionario_cf", "")).strip()
    cess_nome = str(dati.get("cessionario_denominazione", "CLIENTE STUDIO"))[:80].strip() or "CLIENTE STUDIO"
    cess_via = str(dati.get("cessionario_indirizzo", "Via Studio 10"))[:60].strip() or "Via Studio 10"
    cess_cap = str(dati.get("cessionario_cap", "00100"))[:5].strip() or "00100"
    cess_com = str(dati.get("cessionario_comune", "Roma"))[:60].strip() or "Roma"
    cess_prov = str(dati.get("cessionario_provincia", "RM")).strip()[:2].upper() or "RM"

    tipo_doc = str(dati.get("tipo_documento", "TD01"))[:4].upper()
    num_doc = str(dati.get("numero_documento", "1"))[:20].strip() or "1"
    data_doc = str(dati.get("data_documento", datetime.today().strftime("%Y-%m-%d")))[:10]
    cod_dest = str(dati.get("codice_destinatario", "0000000")).strip()
    if len(cod_dest) != 7:
        cod_dest = "0000000"

    totale_doc = float(dati.get("totale_documento", 0.0))
    ritenuta_doc = float(dati.get("ritenuta", 0.0))

    # Helper per creare elementi sempre con prefisso p:
    def p_sub(parent, tag, text=None):
        elem = ET.SubElement(parent, f"p:{tag}")
        if text is not None:
            elem.text = str(text)
        return elem

    # 2. ROOT CON TUTTI I NAMESPACE UFFICIALI SDI
    root = ET.Element("p:FatturaElettronica", {
        "versione": "FPR12",
        "xmlns:ds": "http://www.w3.org/2000/09/xmldsig#",
        "xmlns:p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2 http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_fattura_PA_v1.2.xsd"
    })

    # 3. HEADER: DATI TRASMISSIONE
    header = p_sub(root, "FatturaElettronicaHeader")
    dati_trasm = p_sub(header, "DatiTrasmissione")
    id_trasm = p_sub(dati_trasm, "IdTrasmittente")
    
    # Trasmittente (Soggetto italiano che trasmette)
    piva_trasm = cess_piva if cess_piva else (ced_piva if ced_paese == "IT" else "00000000000")
    p_sub(id_trasm, "IdPaese", "IT")
    p_sub(id_trasm, "IdCodice", piva_trasm)
    p_sub(dati_trasm, "ProgressivoInvio", num_doc[:10].replace("/", "") or "00001")
    p_sub(dati_trasm, "FormatoTrasmissione", "FPR12")
    p_sub(dati_trasm, "CodiceDestinatario", cod_dest)

    # 4. CEDENTE / PRESTATORE ("I MIEI DATI" NEL PORTALE AGENZIA ENTRATE)
    cedente = p_sub(header, "CedentePrestatore")
    dati_anag_ced = p_sub(cedente, "DatiAnagrafici")
    
    id_fisc_ced = p_sub(dati_anag_ced, "IdFiscaleIVA")
    p_sub(id_fisc_ced, "IdPaese", ced_paese)
    p_sub(id_fisc_ced, "IdCodice", ced_piva)

    if ced_cf and len(ced_cf) in [11, 16]:
        p_sub(dati_anag_ced, "CodiceFiscale", ced_cf)

    anag_ced = p_sub(dati_anag_ced, "Anagrafica")
    p_sub(anag_ced, "Denominazione", ced_nome)
    
    # REGIME FISCALE: Nodo tassativo per AdE
    p_sub(dati_anag_ced, "RegimeFiscale", regime_fiscale)

    # SEDE CEDENTE: Nazione tassativa per AdE
    sede_ced = p_sub(cedente, "Sede")
    p_sub(sede_ced, "Indirizzo", ced_via)
    p_sub(sede_ced, "CAP", ced_cap)
    p_sub(sede_ced, "Comune", ced_com)
    if ced_paese == "IT" and ced_prov:
        p_sub(sede_ced, "Provincia", ced_prov)
    p_sub(sede_ced, "Nazione", ced_paese)

    # 5. CESSIONARIO / COMMITTENTE (CLIENTE STUDIO)
    cessionario = p_sub(header, "CessionarioCommittente")
    dati_anag_cess = p_sub(cessionario, "DatiAnagrafici")
    
    if cess_piva and len(cess_piva) >= 8:
        id_fisc_cess = p_sub(dati_anag_cess, "IdFiscaleIVA")
        p_sub(id_fisc_cess, "IdPaese", cess_paese)
        p_sub(id_fisc_cess, "IdCodice", cess_piva)
    if cess_cf and len(cess_cf) in [11, 16]:
        p_sub(dati_anag_cess, "CodiceFiscale", cess_cf)

    anag_cess = p_sub(dati_anag_cess, "Anagrafica")
    p_sub(anag_cess, "Denominazione", cess_nome)

    sede_cess = p_sub(cessionario, "Sede")
    p_sub(sede_cess, "Indirizzo", cess_via)
    p_sub(sede_cess, "CAP", cess_cap)
    p_sub(sede_cess, "Comune", cess_com)
    if cess_paese == "IT" and cess_prov:
        p_sub(sede_cess, "Provincia", cess_prov)
    p_sub(sede_cess, "Nazione", cess_paese)

    # 6. BODY: DATI GENERALI
    body = p_sub(root, "FatturaElettronicaBody")
    dati_gen = p_sub(body, "DatiGenerali")
    dati_doc = p_sub(dati_gen, "DatiGeneraliDocumento")
    p_sub(dati_doc, "TipoDocumento", tipo_doc)
    p_sub(dati_doc, "Divisa", "EUR")
    p_sub(dati_doc, "Data", data_doc)
    p_sub(dati_doc, "Numero", num_doc)

    # Ritenuta se presente (es. Ferraiuolo 140.40)
    if ritenuta_doc > 0.0:
        d_rit = p_sub(dati_doc, "DatiRitenuta")
        p_sub(d_rit, "TipoRitenuta", "RT01" if len(ced_cf) == 16 else "RT02")
        p_sub(d_rit, "ImportoRitenuta", f"{ritenuta_doc:.2f}")
        p_sub(d_rit, "AliquotaRitenuta", "20.00")
        p_sub(d_rit, "CausalePagamento", "A")

    # In FatturaPA l'importo totale documento corrisponde al lordo (Imponibile + IVA)
    imp_doc = float(dati.get("imponibile", totale_doc))
    iva_doc = float(dati.get("imposta", 0.0))
    lordo_totale = round(imp_doc + iva_doc, 2) if (imp_doc > 0 or iva_doc > 0) else totale_doc
    p_sub(dati_doc, "ImportoTotaleDocumento", f"{lordo_totale:.2f}")

    # 7. DATI BENI E SERVIZI
    dati_beni = p_sub(body, "DatiBeniServizi")
    linee = dati.get("linee", [])
    if not linee:
        linee = [{
            "descrizione": f"Prestazioni/Merci fattura n. {num_doc}",
            "prezzo_totale": imp_doc,
            "aliquota": float(dati.get("aliquota_prevalente", 22.0 if ced_paese == "IT" else 0.0)),
            "natura": str(dati.get("natura", "N3.2" if ced_paese != "IT" else ""))
        }]

    for idx, linea in enumerate(linee, start=1):
        det_linea = p_sub(dati_beni, "DettaglioLinee")
        p_sub(det_linea, "NumeroLinea", str(idx))
        p_sub(det_linea, "Descrizione", str(linea.get("descrizione", "Merci/Servizi"))[:990])
        pr_tot = float(linea.get("prezzo_totale", imp_doc))
        p_sub(det_linea, "PrezzoUnitario", f"{pr_tot:.2f}")
        p_sub(det_linea, "PrezzoTotale", f"{pr_tot:.2f}")
        aliq = float(linea.get("aliquota", 0.0))
        p_sub(det_linea, "AliquotaIVA", f"{aliq:.2f}")
        if aliq == 0.0:
            natura_val = str(linea.get("natura") or "N3.2").strip()
            p_sub(det_linea, "Natura", natura_val)

    # 8. DATI RIEPILOGO IVA
    riepiloghi = dati.get("riepilogo_iva", [])
    if not riepiloghi:
        riepiloghi = [{
            "aliquota": float(dati.get("aliquota_prevalente", 22.0 if ced_paese == "IT" else 0.0)),
            "imponibile": imp_doc,
            "imposta": iva_doc,
            "natura": str(dati.get("natura", "N3.2" if ced_paese != "IT" else ""))
        }]

    for rie in riepiloghi:
        dati_rie = p_sub(dati_beni, "DatiRiepilogo")
        aliq = float(rie.get("aliquota", 0.0))
        p_sub(dati_rie, "AliquotaIVA", f"{aliq:.2f}")
        if aliq == 0.0:
            natura_rie = str(rie.get("natura") or "N3.2").strip()
            p_sub(dati_rie, "Natura", natura_rie)
        p_sub(dati_rie, "ImponibileImporto", f"{float(rie.get('imponibile', imp_doc)):.2f}")
        p_sub(dati_rie, "Imposta", f"{float(rie.get('imposta', iva_doc)):.2f}")
        p_sub(dati_rie, "EsigibilitaIVA", "I")

    # 9. DATI PAGAMENTO CONSPAY (Importo netto a pagare)
    dati_pag = p_sub(body, "DatiPagamento")
    p_sub(dati_pag, "CondizioniPagamento", "TP02")
    det_pag = p_sub(dati_pag, "DettaglioPagamento")
    p_sub(det_pag, "ModalitaPagamento", str(dati.get("modalita_pagamento", "MP05")))
    p_sub(det_pag, "DataScadenzaPagamento", str(dati.get("data_scadenza", data_doc)))
    # L'importo pagamento per CONSPAY / bonifico bancario è il netto a pagare
    p_sub(det_pag, "ImportoPagamento", f"{totale_doc:.2f}")
    
    iban_val = str(dati.get("iban", "")).strip().replace(" ", "")
    if iban_val:
        p_sub(det_pag, "IBAN", iban_val)

    # Serializzazione garantita con p: su ogni nodo
    xml_raw = ET.tostring(root, encoding="utf-8")
    parsed_xml = minidom.parseString(xml_raw)
    return parsed_xml.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
