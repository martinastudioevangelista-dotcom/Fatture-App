"""xml_generator.py.

Generatore di Tracciati Fattura Elettronica FPR12 v1.2.2
Conforme alle specifiche dell'Agenzia delle Entrate e compatibile con TeamSystem CONSPAY.
"""

from datetime import datetime
import html
import re
import xml.etree.ElementTree as ET

# Namespace Ufficiali Ministeriali
NS_P = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOC = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2 http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_fattura_PA_v1.2.xsd"

# Registrazione dei prefissi per ElementTree
ET.register_namespace("p", NS_P)
ET.register_namespace("ds", NS_DS)
ET.register_namespace("xsi", NS_XSI)


def _qname(tag: str) -> str:
    """Restituisce il tag qualificato con il namespace ministeriale p:."""
    return f"{{{NS_P}}}{tag}"


def _sub_el(parent, tag: str, text: str = None):
    """Crea un sotto-elemento con il namespace ministeriale e testo protetto."""
    el = ET.SubElement(parent, _qname(tag))
    if text is not None:
        # Pulisce e applica escape caratteri speciali (&, <, >, ecc.)
        clean_text = str(text).strip()
        el.text = clean_text
    return el


def _clean_alphanumeric(value: str, max_chars: int = 10) -> str:
    """Formatta i progressivi di invio rimuovendo caratteri non ammessi dallo SdI."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value or "1"))
    return cleaned[-max_chars:].zfill(5)


def generate_sdi_xml(data: dict) -> str:
    """Genera una stringa XML FPR12 100% conforme a SdI e TeamSystem CONSPAY.

    data atteso:
      - 'cliente_piva', 'cliente_nome', 'cliente_indirizzo', 'cliente_cap', 'cliente_comune', 'cliente_nazione'
      - 'fornitore_piva', 'fornitore_nome', 'fornitore_indirizzo', 'fornitore_cap', 'fornitore_comune', 'fornitore_nazione'
      - 'numero', 'data' (YYYY-MM-DD), 'tipo_documento' (default TD01)
      - 'imponibile', 'aliquota_iva', 'imposta', 'totale'
      - 'natura' (es. N3.2 se estero o esente, vuoto se con IVA)
      - 'descrizione'
      - 'ritenuta' (opzionale, float)
      - 'scadenza' (opzionale YYYY-MM-DD), 'iban' (opzionale), 'metodo_pagamento' (opzionale es. MP05)
    """

    # 1. Radice con namespace formali
    root = ET.Element(
        _qname("FatturaElettronica"),
        {
            "versione": "FPR12",
            f"{{{NS_XSI}}}schemaLocation": SCHEMA_LOC,
        },
    )

    # -------------------------------------------------------------
    # 2. FatturaElettronicaHeader
    # -------------------------------------------------------------
    header = _sub_el(root, "FatturaElettronicaHeader")

    # Dati Trasmissione
    dt = _sub_el(header, "DatiTrasmissione")
    id_tr = _sub_el(dt, "IdTrasmittente")
    _sub_el(
        id_tr, "IdPaese", data.get("cliente_nazione", "IT")[:2].upper() or "IT"
    )
    _sub_el(id_tr, "IdCodice", data.get("cliente_piva", ""))
    _sub_el(
        dt, "ProgressivoInvio", _clean_alphanumeric(data.get("numero", "00001"))
    )
    _sub_el(dt, "FormatoTrasmissione", "FPR12")
    _sub_el(dt, "CodiceDestinatario", data.get("codice_destinatario", "0000000"))

    # Cedente/Prestatore (Fornitore)
    cedente = _sub_el(header, "CedentePrestatore")
    dati_anag_ced = _sub_el(cedente, "DatiAnagrafici")
    id_fisc_ced = _sub_el(dati_anag_ced, "IdFiscaleIVA")
    forn_paese = data.get("fornitore_nazione", "IT")[:2].upper()
    _sub_el(id_fisc_ced, "IdPaese", forn_paese)
    _sub_el(id_fisc_ced, "IdCodice", data.get("fornitore_piva", ""))
    anag_ced = _sub_el(dati_anag_ced, "Anagrafica")
    _sub_el(anag_ced, "Denominazione", data.get("fornitore_nome", "FORNITORE"))
    _sub_el(
        dati_anag_ced, "RegimeFiscale", data.get("regime_fiscale", "RF01")
    )  # RF01 ordinario

    sede_ced = _sub_el(cedente, "Sede")
    _sub_el(sede_ced, "Indirizzo", data.get("fornitore_indirizzo", "SEDE"))
    _sub_el(sede_ced, "CAP", data.get("fornitore_cap", "00000"))
    _sub_el(sede_ced, "Comune", data.get("fornitore_comune", "COMUNE"))
    _sub_el(sede_ced, "Nazione", forn_paese)

    # Cessionario/Committente (Cliente)
    cessionario = _sub_el(header, "CessionarioCommittente")
    dati_anag_ces = _sub_el(cessionario, "DatiAnagrafici")
    id_fisc_ces = _sub_el(dati_anag_ces, "IdFiscaleIVA")
    cli_paese = data.get("cliente_nazione", "IT")[:2].upper()
    _sub_el(id_fisc_ces, "IdPaese", cli_paese)
    _sub_el(id_fisc_ces, "IdCodice", data.get("cliente_piva", ""))
    anag_ces = _sub_el(dati_anag_ces, "Anagrafica")
    _sub_el(anag_ces, "Denominazione", data.get("cliente_nome", "CLIENTE"))

    sede_ces = _sub_el(cessionario, "Sede")
    _sub_el(sede_ces, "Indirizzo", data.get("cliente_indirizzo", "SEDE"))
    _sub_el(sede_ces, "CAP", data.get("cliente_cap", "00000"))
    _sub_el(sede_ces, "Comune", data.get("cliente_comune", "COMUNE"))
    _sub_el(sede_ces, "Nazione", cli_paese)

    # -------------------------------------------------------------
    # 3. FatturaElettronicaBody
    # -------------------------------------------------------------
    body = _sub_el(root, "FatturaElettronicaBody")

    # Dati Generali Documento
    imponibile = float(data.get("imponibile", 0.0))
    imposta = float(data.get("imposta", 0.0))
    totale_doc = float(data.get("totale", imponibile + imposta))
    ritenuta = float(data.get("ritenuta", 0.0))

    dati_generali = _sub_el(body, "DatiGenerali")
    dati_gen_doc = _sub_el(dati_generali, "DatiGeneraliDocumento")
    _sub_el(dati_gen_doc, "TipoDocumento", data.get("tipo_documento", "TD01"))
    _sub_el(dati_gen_doc, "Divisa", "EUR")
    _sub_el(dati_gen_doc, "Data", data.get("data", datetime.today().strftime("%Y-%m-%d")))
    _sub_el(dati_gen_doc, "Numero", str(data.get("numero", "1")))

    # Eventuale Ritenuta d'acconto (Notule Professionisti)
    if ritenuta > 0:
        dati_rit = _sub_el(dati_gen_doc, "DatiRitenuta")
        _sub_el(dati_rit, "TipoRitenuta", "RT02")  # Persone fisiche
        _sub_el(dati_rit, "ImportoRitenuta", f"{ritenuta:.2f}")
        _sub_el(dati_rit, "AliquotaRitenuta", "20.00")
        _sub_el(dati_rit, "CausalePagamento", "A")

    # Importo Totale Documento (Fondamentale per TeamSystem CONSPAY)
    _sub_el(dati_gen_doc, "ImportoTotaleDocumento", f"{totale_doc:.2f}")

    # Beni e Servizi
    beni_servizi = _sub_el(body, "BeniServizi")
    dettaglio = _sub_el(beni_servizi, "DettaglioLinee")
    _sub_el(dettaglio, "NumeroLinea", "1")
    _sub_el(
        dettaglio,
        "Descrizione",
        data.get("descrizione", "Prestazione di servizi / Beni"),
    )
    _sub_el(dettaglio, "PrezzoUnitario", f"{imponibile:.2f}")
    _sub_el(dettaglio, "PrezzoTotale", f"{imponibile:.2f}")

    aliquota = float(data.get("aliquota_iva", 0.0))
    _sub_el(dettaglio, "AliquotaIVA", f"{aliquota:.2f}")

    # Regola SdI: Se aliquota 0 -> Natura obbligatoria. Se aliquota > 0 -> Tag Natura VIETATO.
    natura = data.get("natura")
    if aliquota == 0.0:
        natura_val = (
            natura if natura else ("N3.2" if forn_paese != "IT" else "N2.2")
        )
        _sub_el(dettaglio, "Natura", natura_val)

    # Dati Riepilogo
    riepilogo = _sub_el(beni_servizi, "DatiRiepilogo")
    _sub_el(riepilogo, "AliquotaIVA", f"{aliquota:.2f}")
    if aliquota == 0.0:
        _sub_el(riepilogo, "Natura", natura_val)
    _sub_el(riepilogo, "ImponibileImporto", f"{imponibile:.2f}")
    _sub_el(riepilogo, "Imposta", f"{imposta:.2f}")

    # Se aliquota > 0, possiamo specificare l'esigibilità (I = immediata)
    if aliquota > 0.0:
        _sub_el(riepilogo, "EsigibilitaIVA", "I")

    # -------------------------------------------------------------
    # 4. DatiPagamento (MOTORE SPECIFICO TEAMSYSTEM CONSPAY)
    # -------------------------------------------------------------
    netto_a_pagare = (
        totale_doc - ritenuta
    )  # Al netto di ritenuta per professionisti
    data_scadenza = data.get("scadenza", data.get("data"))

    dati_pag = _sub_el(body, "DatiPagamento")
    _sub_el(dati_pag, "CondizioniPagamento", "TP02")  # Pagamento completo

    dett_pag = _sub_el(dati_pag, "DettaglioPagamento")
    # MP05 = Bonifico, MP08 = Carta/POS, MP01 = Contanti
    _sub_el(
        dett_pag, "ModalitaPagamento", data.get("metodo_pagamento", "MP05")
    )
    _sub_el(dett_pag, "DataScadenzaPagamento", data_scadenza)
    _sub_el(dett_pag, "ImportoPagamento", f"{netto_a_pagare:.2f}")

    iban = data.get("iban", "").replace(" ", "").upper()
    if iban and len(iban) >= 15:
        _sub_el(dett_pag, "IBAN", iban)

    # -------------------------------------------------------------
    # 5. Output con Intestazione XML
    # -------------------------------------------------------------
    raw_xml = ET.tostring(root, encoding="utf-8", method="xml").decode("utf-8")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{raw_xml}'
