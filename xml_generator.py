import re
from datetime import datetime
from xml.sax.saxutils import escape


def _esc(val, default=""):
    """Evita campi vuoti e sanitizza i caratteri speciali."""
    if val is None or str(val).strip() == "" or str(val).strip().lower() == "none":
        return str(default)
    return escape(str(val).strip())


def genera_xml_teamsystem(data):
    if not isinstance(data, dict):
        data = {}

    # 1. Trasmittente e Cliente Italiano
    cli_piva_raw = str(data.get("cliente_piva") or "09847131217")
    cli_piva = re.sub(r"[^A-Za-z0-9]", "", cli_piva_raw)
    if cli_piva.upper().startswith("IT"):
        cli_piva = cli_piva[2:]
    if not cli_piva:
        cli_piva = "09847131217"

    cli_nazione = (data.get("cliente_nazione") or "IT")[:2].upper()
    cli_nome = _esc(data.get("cliente_nome"), "CLIENTE")
    cli_ind = _esc(data.get("cliente_indirizzo"), "PIAZZA SANNAZARO")
    cli_cap = _esc(data.get("cliente_cap"), "80122")
    cli_com = _esc(data.get("cliente_comune"), "NAPOLI")

    # 2. Fornitore Estero (es. CGI / SGB Finance)
    forn_paese = (data.get("fornitore_nazione") or "FR")[:2].upper()
    forn_piva_raw = str(data.get("fornitore_piva") or "12345678901")
    forn_piva = re.sub(r"[^A-Za-z0-9]", "", forn_piva_raw)
    if not forn_piva:
        forn_piva = "12345678901"

    forn_nome = _esc(data.get("fornitore_nome"), "FORNITORE ESTERO")
    forn_ind = _esc(data.get("fornitore_indirizzo"), "69 AVENUE DE FLANDRE")
    forn_cap = _esc(data.get("fornitore_cap"), "59708")
    forn_com = _esc(data.get("fornitore_comune"), "MARCQ EN BAROEUL")

    # 3. Documento
    num_doc_raw = str(data.get("numero") or "1").strip()
    num_doc = num_doc_raw if num_doc_raw else "1"
    prog_invio = re.sub(r"[^A-Za-z0-9]", "", num_doc)[-5:].zfill(5)
    data_doc = str(data.get("data") or datetime.today().strftime("%Y-%m-%d"))
    tipo_doc = str(data.get("tipo_documento") or "TD01")
    descrizione = _esc(data.get("descrizione"), "Fornitura / Canone leasing")

    # 4. Importi e Contabilita
    try:
        imponibile = float(data.get("imponibile", 0.0) or 0.0)
    except (ValueError, TypeError):
        imponibile = 0.0

    try:
        aliquota = float(data.get("aliquota_iva", 0.0) or 0.0)
    except (ValueError, TypeError):
        aliquota = 0.0

    try:
        imposta = float(data.get("imposta", 0.0) or 0.0)
    except (ValueError, TypeError):
        imposta = 0.0

    totale = round(imponibile + imposta, 2)
    if data.get("totale") is not None:
        try:
            totale = float(data.get("totale"))
        except (ValueError, TypeError):
            pass

    # Natura IVA (obbligatoria se aliquota 0%)
    natura_tag = ""
    natura_riepilogo = ""
    if aliquota == 0.0:
        nat_val = str(data.get("natura") or ("N3.2" if forn_paese != "IT" else "N2.2"))
        natura_tag = f"\n        <Natura>{nat_val}</Natura>"
        natura_riepilogo = f"\n      <Natura>{nat_val}</Natura>"

    # 5. Sezione CONSPAY TeamSystem (Dati Pagamento)
    iban_clean = re.sub(r"[^A-Za-z0-9]", "", str(data.get("iban", ""))).upper()
    iban_tag = f"\n        <IBAN>{iban_clean}</IBAN>" if len(iban_clean) >= 15 else ""
    scadenza_pag = str(data.get("scadenza") or data_doc)
    metodo_pag = str(data.get("metodo_pagamento") or "MP05")

    # Costruzione XML con <DatiBeniServizi> ufficiale ministeriale
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<FatturaElettronica versione="FPR12" xmlns="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">',
        "  <FatturaElettronicaHeader>",
        "    <DatiTrasmissione>",
        "      <IdTrasmittente>",
        f"        <IdPaese>{cli_nazione}</IdPaese>",
        f"        <IdCodice>{cli_piva}</IdCodice>",
        "      </IdTrasmittente>",
        f"      <ProgressivoInvio>{prog_invio}</ProgressivoInvio>",
        "      <FormatoTrasmissione>FPR12</FormatoTrasmissione>",
        "      <CodiceDestinatario>0000000</CodiceDestinatario>",
        "    </DatiTrasmissione>",
        "    <CedentePrestatore>",
        "      <DatiAnagrafici>",
        "        <IdFiscaleIVA>",
        f"          <IdPaese>{forn_paese}</IdPaese>",
        f"          <IdCodice>{forn_piva}</IdCodice>",
        "        </IdFiscaleIVA>",
        "        <Anagrafica>",
        f"          <Denominazione>{forn_nome}</Denominazione>",
        "        </Anagrafica>",
        "        <RegimeFiscale>RF01</RegimeFiscale>",
        "      </DatiAnagrafici>",
        "      <Sede>",
        f"        <Indirizzo>{forn_ind}</Indirizzo>",
        f"        <CAP>{forn_cap}</CAP>",
        f"        <Comune>{forn_com}</Comune>",
        f"        <Nazione>{forn_paese}</Nazione>",
        "      </Sede>",
        "    </CedentePrestatore>",
        "    <CessionarioCommittente>",
        "      <DatiAnagrafici>",
        "        <IdFiscaleIVA>",
        f"          <IdPaese>{cli_nazione}</IdPaese>",
        f"          <IdCodice>{cli_piva}</IdCodice>",
        "        </IdFiscaleIVA>",
        "        <Anagrafica>",
        f"          <Denominazione>{cli_nome}</Denominazione>",
        "        </Anagrafica>",
        "      </DatiAnagrafici>",
        "      <Sede>",
        f"        <Indirizzo>{cli_ind}</Indirizzo>",
        f"        <CAP>{cli_cap}</CAP>",
        f"        <Comune>{cli_com}</Comune>",
        f"        <Nazione>{cli_nazione}</Nazione>",
        "      </Sede>",
        "    </CessionarioCommittente>",
        "  </FatturaElettronicaHeader>",
        "  <FatturaElettronicaBody>",
        "    <DatiGenerali>",
        "      <DatiGeneraliDocumento>",
        f"        <TipoDocumento>{tipo_doc}</TipoDocumento>",
        "        <Divisa>EUR</Divisa>",
        f"        <Data>{data_doc}</Data>",
        f"        <Numero>{num_doc}</Numero>",
        f"        <ImportoTotaleDocumento>{totale:.2f}</ImportoTotaleDocumento>",
        "      </DatiGeneraliDocumento>",
        "    </DatiGenerali>",
        "    <DatiBeniServizi>",
        "      <DettaglioLinee>",
        "        <NumeroLinea>1</NumeroLinea>",
        f"        <Descrizione>{descrizione}</Descrizione>",
        f"        <PrezzoUnitario>{imponibile:.2f}</PrezzoUnitario>",
        f"        <PrezzoTotale>{imponibile:.2f}</PrezzoTotale>",
        f"        <AliquotaIVA>{aliquota:.2f}</AliquotaIVA>{natura_tag}",
        "      </DettaglioLinee>",
        "      <DatiRiepilogo>",
        f"        <AliquotaIVA>{aliquota:.2f}</AliquotaIVA>{natura_riepilogo}",
        f"        <ImponibileImporto>{imponibile:.2f}</ImponibileImporto>",
        f"        <Imposta>{imposta:.2f}</Imposta>",
        "      </DatiRiepilogo>",
        "    </DatiBeniServizi>",
        "    <DatiPagamento>",
        "      <CondizioniPagamento>TP02</CondizioniPagamento>",
        "      <DettaglioPagamento>",
        f"        <ModalitaPagamento>{metodo_pag}</ModalitaPagamento>",
        f"        <DataScadenzaPagamento>{scadenza_pag}</DataScadenzaPagamento>",
        f"        <ImportoPagamento>{totale:.2f}</ImportoPagamento>{iban_tag}",
        "      </DettaglioPagamento>",
        "    </DatiPagamento>",
        "  </FatturaElettronicaBody>",
        "</FatturaElettronica>",
    ]
    return "\n".join(xml_lines)


# Alias di compatibilità
generate_sdi_xml = genera_xml_teamsystem
genera_xml = genera_xml_teamsystem
