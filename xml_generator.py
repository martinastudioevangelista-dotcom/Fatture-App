"""
xml_generator.py
Generatore Formale FPR12 certificato SdI (Agenzia delle Entrate) e TeamSystem ECONS / CONSPAY.
- Risolve Errore SdI 00300 (IdTrasmittente censito in Anagrafe Tributaria)
- Risolve Errore ECONS ERR01871 (Radice prefissata p: con elementi figli non prefissati)
- Bonifica caratteri UTF-8 per l'acquisizione sicura su ECONS
"""

from datetime import datetime
import re
from xml.sax.saxutils import escape


def _pulisci_testo_econs(val, default="") -> str:
    """Rimuove caratteri di controllo ASCII non ammessi ed esegue l'escape XML per ECONS."""
    if val is None or str(val).strip() == "" or str(val).strip().lower() == "none":
        return str(default)
    # Rimuove caratteri di controllo vietati da XML 1.0 (tranne tab, CR, LF)
    testo_pulito = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", str(val).strip())
    return escape(testo_pulito)


def genera_nome_file_sdi(data: dict = None, progressivo: str = "00001") -> str:
    """Genera la nomenclatura ministeriale esatta richiesta da SdI ed ECONS:

    IT[PartitaIVA_Trasmittente]_[Progressivo5Cifre].xml (es. IT09847131217_00001.xml)
    """
    if not isinstance(data, dict):
        data = {}

    piva_raw = str(data.get("trasmittente_piva") or "09847131217")
    piva = re.sub(r"[^A-Za-z0-9]", "", piva_raw)
    if piva.upper().startswith("IT"):
        piva = piva[2:]
    if not piva or len(piva) < 11:
        piva = "09847131217"

    num_raw = str(data.get("numero_documento") or data.get("numero") or progressivo)
    prog = re.sub(r"[^A-Za-z0-9]", "", num_raw)[-5:].zfill(5)
    return f"IT{piva}_{prog}.xml"


def genera_xml_teamsystem(data=None) -> str:
    if not isinstance(data, dict):
        data = {}

    # 1. CEDENTE / PRESTATORE (Fornitore)
    ced_nome = _pulisci_testo_econs(
        data.get("cedente_denominazione")
        or data.get("fornitore_nome")
        or "FORNITORE"
    )

    ced_piva_raw = str(
        data.get("cedente_piva")
        or data.get("fornitore_piva")
        or data.get("cedente_cf")
        or "09087751211"
    )
    ced_piva_clean = re.sub(r"[^A-Za-z0-9]", "", ced_piva_raw)
    if ced_piva_clean.upper().startswith("IT"):
        ced_piva_clean = ced_piva_clean[2:]
    ced_piva = ced_piva_clean if ced_piva_clean else "09087751211"

    ced_paese = (
        data.get("cedente_paese") or data.get("fornitore_nazione") or "IT"
    )[:2].upper()
    ced_via = _pulisci_testo_econs(
        data.get("cedente_indirizzo")
        or data.get("fornitore_indirizzo")
        or "VIA DEI CAMPI, 26"
    )
    ced_cap = _pulisci_testo_econs(
        data.get("cedente_cap") or data.get("fornitore_cap") or "80061"
    )
    ced_com = _pulisci_testo_econs(
        data.get("cedente_comune")
        or data.get("fornitore_comune")
        or "Massa Lubrense"
    )

    # 2. CESSIONARIO / COMMITTENTE (Cliente)
    cess_nome = _pulisci_testo_econs(
        data.get("cessionario_denominazione")
        or data.get("cliente_nome")
        or "CASAZEN s.r.l."
    )

    cess_piva_raw = str(
        data.get("cessionario_piva")
        or data.get("cliente_piva")
        or data.get("cessionario_cf")
        or "09847131217"
    )
    cess_piva_clean = re.sub(r"[^A-Za-z0-9]", "", cess_piva_raw)
    if cess_piva_clean.upper().startswith("IT"):
        cess_piva_clean = cess_piva_clean[2:]
    cess_piva = cess_piva_clean if cess_piva_clean else "09847131217"

    cess_paese = (
        data.get("cessionario_paese") or data.get("cliente_nazione") or "IT"
    )[:2].upper()
    cess_via = _pulisci_testo_econs(
        data.get("cessionario_indirizzo")
        or data.get("cliente_indirizzo")
        or "Via Generale Girolamo Calà Ulloa 24"
    )
    cess_cap = _pulisci_testo_econs(
        data.get("cessionario_cap") or data.get("cliente_cap") or "80141"
    )
    cess_com = _pulisci_testo_econs(
        data.get("cessionario_comune") or data.get("cliente_comune") or "Napoli"
    )

    # -------------------------------------------------------------
    # 3. RISOLUZIONE ERRORE SdI 00300 (IdTrasmittente censito in Anagrafe Tributaria)
    # -------------------------------------------------------------
    # Se il Cedente è italiano ed emette la fattura attiva, trasmette il Cedente.
    # In caso di acquisti esteri, autofatture o se il cliente è Casazen (09847131217),
    # il Trasmittente è sempre Casazen (09847131217), evitando P.IVA inesistenti (es. 08505861214).
    if "09847131217" in (ced_piva, cess_piva) or ced_paese != "IT" or not ced_piva:
        id_trasm_codice = "09847131217"
        id_trasm_paese = "IT"
    else:
        id_trasm_codice = ced_piva
        id_trasm_paese = ced_paese

    # 4. DATI GENERALI DOCUMENTO
    num_doc_raw = str(
        data.get("numero_documento") or data.get("numero") or "1"
    ).strip()
    num_doc = num_doc_raw.split()[0] if num_doc_raw else "1"
    prog_invio = re.sub(r"[^A-Za-z0-9]", "", num_doc)[-5:].zfill(5)

    data_doc = str(
        data.get("data_documento")
        or data.get("data")
        or datetime.today().strftime("%Y-%m-%d")
    )
    tipo_doc = str(data.get("tipo_documento") or "TD01")
    descrizione = _pulisci_testo_econs(
        data.get("descrizione") or "Prestazione di servizi / Beni"
    )

    # 5. QUADRATURA CONTABILE RIGIDA (Conforme a SdI e TeamSystem)
    try:
        imponibile = round(float(data.get("imponibile", 0.0) or 0.0), 2)
    except (ValueError, TypeError):
        imponibile = 0.0

    try:
        aliquota = round(
            float(
                data.get("aliquota_prevalente")
                or data.get("aliquota_iva")
                or 22.0
            ),
            2,
        )
    except (ValueError, TypeError):
        aliquota = 0.0

    try:
        imposta_in = float(data.get("imposta", 0.0) or 0.0)
    except (ValueError, TypeError):
        imposta_in = 0.0

    try:
        ritenuta = round(float(data.get("ritenuta", 0.0) or 0.0), 2)
    except (ValueError, TypeError):
        ritenuta = 0.0

    if aliquota == 0.0:
        imposta = 0.00
    else:
        imposta_attesa = round((imponibile * aliquota) / 100.0, 2)
        if imposta_in == 0.0 or abs(imposta_in - imposta_attesa) > 0.02:
            imposta = imposta_attesa
        else:
            imposta = round(imposta_in, 2)

    totale_lordo = round(imponibile + imposta, 2)
    tot_input = float(
        data.get("totale_documento") or data.get("totale") or 0.0 or 0.0
    )
    if tot_input > 0 and abs(tot_input - totale_lordo) <= 0.02:
        totale = tot_input
    else:
        totale = totale_lordo

    netto_a_pagare = round(totale - ritenuta, 2)

    # 6. CONSPAY TEAMSYSTEM (Dati Pagamento)
    iban_raw = str(data.get("iban") or "")
    iban_clean = re.sub(r"[^A-Za-z0-9]", "", iban_raw).upper()

    data_scad = str(
        data.get("data_scadenza") or data.get("scadenza") or data_doc
    )
    metodo_pag = str(
        data.get("modalita_pagamento")
        or data.get("metodo_pagamento")
        or "MP05"
    )

    # 7. SCHEMA AD ALBERO CONFORME A TEAMSYSTEM ECONS (ERR01871) E SDI
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<p:FatturaElettronica xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2" versione="FPR12">',
        "  <FatturaElettronicaHeader>",
        "    <DatiTrasmissione>",
        "      <IdTrasmittente>",
        f"        <IdPaese>{id_trasm_paese}</IdPaese>",
        f"        <IdCodice>{id_trasm_codice}</IdCodice>",
        "      </IdTrasmittente>",
        f"      <ProgressivoInvio>{prog_invio}</ProgressivoInvio>",
        "      <FormatoTrasmissione>FPR12</FormatoTrasmissione>",
        "      <CodiceDestinatario>0000000</CodiceDestinatario>",
        "    </DatiTrasmissione>",
        "    <CedentePrestatore>",
        "      <DatiAnagrafici>",
        "        <IdFiscaleIVA>",
        f"          <IdPaese>{ced_paese}</IdPaese>",
        f"          <IdCodice>{ced_piva}</IdCodice>",
        "        </IdFiscaleIVA>",
        "        <Anagrafica>",
        f"          <Denominazione>{ced_nome}</Denominazione>",
        "        </Anagrafica>",
        "        <RegimeFiscale>RF01</RegimeFiscale>",
        "      </DatiAnagrafici>",
        "      <Sede>",
        f"        <Indirizzo>{ced_via}</Indirizzo>",
        f"        <CAP>{ced_cap}</CAP>",
        f"        <Comune>{ced_com}</Comune>",
        f"        <Nazione>{ced_paese}</Nazione>",
        "      </Sede>",
        "    </CedentePrestatore>",
        "    <CessionarioCommittente>",
        "      <DatiAnagrafici>",
        "        <IdFiscaleIVA>",
        f"          <IdPaese>{cess_paese}</IdPaese>",
        f"          <IdCodice>{cess_piva}</IdCodice>",
        "        </IdFiscaleIVA>",
        "        <Anagrafica>",
        f"          <Denominazione>{cess_nome}</Denominazione>",
        "        </Anagrafica>",
        "      </DatiAnagrafici>",
        "      <Sede>",
        f"        <Indirizzo>{cess_via}</Indirizzo>",
        f"        <CAP>{cess_cap}</CAP>",
        f"        <Comune>{cess_com}</Comune>",
        f"        <Nazione>{cess_paese}</Nazione>",
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
    ]

    if ritenuta > 0:
        xml_lines.extend([
            "        <DatiRitenuta>",
            "          <TipoRitenuta>RT01</TipoRitenuta>",
            f"          <ImportoRitenuta>{ritenuta:.2f}</ImportoRitenuta>",
            "          <AliquotaRitenuta>20.00</AliquotaRitenuta>",
            "          <CausalePagamento>A</CausalePagamento>",
            "        </DatiRitenuta>",
        ])

    xml_lines.extend([
        f"        <ImportoTotaleDocumento>{totale:.2f}</ImportoTotaleDocumento>",
        "      </DatiGeneraliDocumento>",
        "    </DatiGenerali>",
        "    <DatiBeniServizi>",
        "      <DettaglioLinee>",
        "        <NumeroLinea>1</NumeroLinea>",
        f"        <Descrizione>{descrizione}</Descrizione>",
        f"        <PrezzoUnitario>{imponibile:.2f}</PrezzoUnitario>",
        f"        <PrezzoTotale>{imponibile:.2f}</PrezzoTotale>",
        f"        <AliquotaIVA>{aliquota:.2f}</AliquotaIVA>",
    ])

    if aliquota == 0.0:
        nat_val = str(
            data.get("natura") or ("N3.2" if ced_paese != "IT" else "N2.2")
        ).strip()
        if not nat_val:
            nat_val = "N3.2" if ced_paese != "IT" else "N2.2"
        xml_lines.append(f"        <Natura>{nat_val}</Natura>")

    xml_lines.extend([
        "      </DettaglioLinee>",
        "      <DatiRiepilogo>",
        f"        <AliquotaIVA>{aliquota:.2f}</AliquotaIVA>",
    ])

    if aliquota == 0.0:
        ref_norm = (
            "Operazione non imponibile art. 41"
            if nat_val == "N3.2"
            else "Operazione non soggetta"
        )
        xml_lines.extend([
            f"        <Natura>{nat_val}</Natura>",
            f"        <RiferimentoNormativo>{ref_norm}</RiferimentoNormativo>",
        ])

    xml_lines.extend([
        f"        <ImponibileImporto>{imponibile:.2f}</ImponibileImporto>",
        f"        <Imposta>{imposta:.2f}</Imposta>",
        "      </DatiRiepilogo>",
        "    </DatiBeniServizi>",
        "    <DatiPagamento>",
        "      <CondizioniPagamento>TP02</CondizioniPagamento>",
        "      <DettaglioPagamento>",
        f"        <ModalitaPagamento>{metodo_pag}</ModalitaPagamento>",
        f"        <DataScadenzaPagamento>{data_scad}</DataScadenzaPagamento>",
        f"        <ImportoPagamento>{netto_a_pagare:.2f}</ImportoPagamento>",
    ])

    if len(iban_clean) >= 15:
        xml_lines.append(f"        <IBAN>{iban_clean}</IBAN>")

    xml_lines.extend([
        "      </DettaglioPagamento>",
        "    </DatiPagamento>",
        "  </FatturaElettronicaBody>",
        "</p:FatturaElettronica>",
    ])

    return "\n".join(xml_lines)


# Alias di compatibilità
generate_sdi_xml = genera_xml_teamsystem
genera_xml = genera_xml_teamsystem
genera_nome_file_xml = genera_nome_file_sdi
