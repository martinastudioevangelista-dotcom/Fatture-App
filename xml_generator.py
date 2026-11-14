# === INIZIO FILE xml_generator.py ===
"""
xml_generator.py - VERSIONE CERTIFICATA AdE / TEAMSYSTEM ECONS / CONSPAY
Supporta fatture italiane (comportamento congelato invariato) ed estere (conforme XSD SdI v1.2.2).
- Ordine DatiRiepilogo conforme XSD AdE: AliquotaIVA, Natura, ImponibileImporto, Imposta, RiferimentoNormativo.
- Validazione rigida dei codici enumerati TipoDocumento (TD01..TD29), ModalitaPagamento (MP01..MP23), Natura, IBAN.
"""

from datetime import datetime
import re
from xml.sax.saxutils import escape

EU_COUNTRIES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "GR", "ES", "FI",
    "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
    "RO", "SE", "SI", "SK", "XI",
}

VALID_TD = {
    "TD01", "TD02", "TD03", "TD04", "TD05", "TD06", "TD16", "TD17", "TD18",
    "TD19", "TD20", "TD21", "TD22", "TD23", "TD24", "TD25", "TD26", "TD27",
    "TD28", "TD29",
}

VALID_MP = {f"MP{i:02d}" for i in range(1, 24)}

VALID_NATURA = {
    "N1", "N2.1", "N2.2", "N3.1", "N3.2", "N3.3", "N3.4", "N3.5", "N3.6",
    "N4", "N5", "N6.1", "N6.2", "N6.3", "N6.4", "N6.5", "N6.6", "N6.7",
    "N6.8", "N6.9", "N7",
}


def _pulisci_testo_econs(val, default="", max_len: int = None) -> str:
    """
    Rimuove caratteri di controllo ASCII non ammessi, tronca PRIMA dell'escape (se richiesto)
    ed esegue l'escape XML per AdE / ECONS senza mai spezzare entità XML.
    """
    if val is None or str(val).strip() == "" or str(val).strip().lower() == "none":
        testo_pulito = str(default)
    else:
        testo_pulito = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", str(val).strip())
    if max_len is not None and len(testo_pulito) > max_len:
        testo_pulito = testo_pulito[:max_len].strip()
    return escape(testo_pulito)


def _norm_paese_sdi(val, default: str = "IT") -> str:
    code = re.sub(r"[^A-Za-z]", "", str(val or default))[:2].upper()
    if code == "UK":
        return "GB"
    if code == "EL":
        return "GR"
    return code if len(code) == 2 else default


def _norm_cap_sdi(cap_val: str, paese: str, default_it: str) -> str:
    c = re.sub(r"[^0-9]", "", str(cap_val or ""))
    if len(c) == 5:
        return c
    return "00000" if paese != "IT" else default_it


def _norm_tipo_documento(val) -> str:
    code = str(val or "TD01").strip().upper()
    return code if code in VALID_TD else "TD01"


def _norm_modalita_pagamento(val) -> str:
    raw = str(val or "").strip()
    up = raw.upper()
    if up in VALID_MP:
        return up
    low = raw.lower()
    if any(w in low for w in ("prel", "sepa", "sdd", "direct debit", "addebito", "domicilia")):
        return "MP19"
    if "rid" in low:
        return "MP09"
    if any(w in low for w in ("carta", "card", "credit", "bancomat", "pos")):
        return "MP08"
    if any(w in low for w in ("contant", "cash", "especes", "espèces")):
        return "MP01"
    if any(w in low for w in ("assegn", "check", "cheque", "chèque")):
        return "MP02"
    if "riba" in low or "ri.ba" in low:
        return "MP12"
    return "MP05"


def _norm_natura(val, ced_paese: str) -> str:
    n = str(val or "").strip().upper()
    if n in VALID_NATURA:
        return n
    if n == "N3":
        return "N3.2"
    if n == "N2":
        return "N2.2"
    if n == "N6":
        return "N6.9"
    return "N3.2" if (ced_paese != "IT" and ced_paese in EU_COUNTRIES) else "N2.2"


def genera_nome_file_sdi(data: dict = None, progressivo: str = "00001") -> str:
    """Genera la nomenclatura ministeriale: IT[P.IVA_Trasmittente]_[PROG5].xml"""
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
    ced_paese = _norm_paese_sdi(
        data.get("cedente_paese") or data.get("fornitore_nazione") or "IT", "IT"
    )
    ced_nome = _pulisci_testo_econs(
        data.get("cedente_denominazione") or data.get("fornitore_nome") or "FORNITORE",
        max_len=80,
    )

    ced_piva_raw = str(
        data.get("cedente_piva")
        or data.get("fornitore_piva")
        or data.get("cedente_cf")
        or ""
    )
    ced_piva_clean = re.sub(r"[^A-Za-z0-9]", "", ced_piva_raw).upper()
    if ced_piva_clean.startswith("IT") and ced_paese == "IT":
        ced_piva_clean = ced_piva_clean[2:]
    elif ced_paese != "IT" and ced_piva_clean.startswith(ced_paese) and len(ced_piva_clean) > 4:
        if not (ced_paese == "CH" and ced_piva_clean.startswith("CHE")):
            ced_piva_clean = ced_piva_clean[len(ced_paese):]

    if ced_piva_clean:
        ced_piva = ced_piva_clean[:28]
    elif ced_paese != "IT":
        ced_piva = "OO99999999999"
    else:
        ced_piva = "09087751211"

    ced_cap_orig = str(data.get("cedente_cap") or data.get("fornitore_cap") or "").strip()
    ced_via_raw = str(
        data.get("cedente_indirizzo")
        or data.get("fornitore_indirizzo")
        or ("Indirizzo estero" if ced_paese != "IT" else "VIA DEI CAMPI, 26")
    ).strip()
    if ced_paese != "IT" and ced_cap_orig and not re.fullmatch(r"\d{5}", ced_cap_orig):
        if ced_cap_orig not in ced_via_raw:
            ced_via_raw = f"{ced_via_raw} ({ced_cap_orig})"
    ced_via = _pulisci_testo_econs(ced_via_raw, max_len=60)
    ced_cap = _norm_cap_sdi(ced_cap_orig, ced_paese, "80061")
    ced_com = _pulisci_testo_econs(
        data.get("cedente_comune")
        or data.get("fornitore_comune")
        or ("Estero" if ced_paese != "IT" else "Massa Lubrense"),
        max_len=60,
    )

    # 2. CESSIONARIO / COMMITTENTE (Cliente)
    cess_paese = _norm_paese_sdi(
        data.get("cessionario_paese") or data.get("cliente_nazione") or "IT", "IT"
    )
    cess_nome = _pulisci_testo_econs(
        data.get("cessionario_denominazione")
        or data.get("cliente_nome")
        or "CASAZEN s.r.l.",
        max_len=80,
    )

    cess_piva_raw = str(
        data.get("cessionario_piva")
        or data.get("cliente_piva")
        or data.get("cessionario_cf")
        or "09847131217"
    )
    cess_piva_clean = re.sub(r"[^A-Za-z0-9]", "", cess_piva_raw).upper()
    if cess_piva_clean.startswith("IT") and cess_paese == "IT":
        cess_piva_clean = cess_piva_clean[2:]
    cess_piva = cess_piva_clean[:28] if cess_piva_clean else "09847131217"

    cess_cap_orig = str(data.get("cessionario_cap") or data.get("cliente_cap") or "80141").strip()
    cess_via = _pulisci_testo_econs(
        data.get("cessionario_indirizzo")
        or data.get("cliente_indirizzo")
        or "Via Generale Girolamo Calà Ulloa 24",
        max_len=60,
    )
    cess_cap = _norm_cap_sdi(cess_cap_orig, cess_paese, "80141")
    cess_com = _pulisci_testo_econs(
        data.get("cessionario_comune") or data.get("cliente_comune") or "Napoli",
        max_len=60,
    )

    # 3. TRASMITTENTE (Risolve errore SdI 00300)
    if "09847131217" in (ced_piva, cess_piva) or ced_paese != "IT" or not ced_piva:
        id_trasm_codice = "09847131217"
        id_trasm_paese = "IT"
    else:
        id_trasm_codice = ced_piva
        id_trasm_paese = ced_paese

    # 4. DATI GENERALI DOCUMENTO
    num_doc_raw = str(data.get("numero_documento") or data.get("numero") or "1").strip()
    num_doc_token = num_doc_raw.split()[0] if num_doc_raw else "1"
    num_doc = _pulisci_testo_econs(num_doc_token, default="1", max_len=20)
    prog_invio = re.sub(r"[^A-Za-z0-9]", "", num_doc_token)[-5:].zfill(5)

    data_doc_raw = str(
        data.get("data_documento")
        or data.get("data")
        or datetime.today().strftime("%Y-%m-%d")
    ).strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_doc_raw):
        data_doc = datetime.today().strftime("%Y-%m-%d")
    else:
        data_doc = data_doc_raw

    tipo_doc = _norm_tipo_documento(data.get("tipo_documento"))
    descrizione = _pulisci_testo_econs(
        data.get("descrizione") or "Prestazione di servizi / Beni",
        max_len=1000,
    )

    # 5. QUADRATURA CONTABILE RIGIDA (Regola 00421)
    try:
        imponibile = round(float(data.get("imponibile", 0.0) or 0.0), 2)
    except (ValueError, TypeError):
        imponibile = 0.0

    try:
        aliq_raw = data.get("aliquota_prevalente") if data.get("aliquota_prevalente") is not None else data.get("aliquota_iva")
        aliquota = round(float(22.0 if aliq_raw is None else aliq_raw), 2)
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
    tot_input = float(data.get("totale_documento") or data.get("totale") or 0.0 or 0.0)
    if tot_input > 0 and abs(tot_input - totale_lordo) <= 0.02:
        totale = tot_input
    else:
        totale = totale_lordo

    netto_a_pagare = round(totale - ritenuta, 2)

    # 6. CONSPAY TEAMSYSTEM
    iban_raw = str(data.get("iban") or "")
    iban_clean = re.sub
