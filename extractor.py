"""
extractor_sdi.py / sezione per extractor.py
Modulo per l'estrazione perfetta da PDF con Foglio di Stile SdI (Ministeriale).
"""
import re


def estrai_foglio_stile_sdi(testo_pdf: str) -> dict:
    """Estrae tutti i campi da PDF generati con foglio di stile SdI (FatturaPA / AdE).

    Gestisce sia persone fisiche (Nome + Cognome) sia persone giuridiche
    (Denominazione), ritenute e casse previdenziali.
    """
    dati = {}

    # 1. Separazione dei blocchi principali
    blocco_cedente = ""
    blocco_cessionario = ""
    blocco_generale = ""
    blocco_pagamento = ""

    # Sezione Fornitore (Cedente/Prestatore)
    m_ced = re.search(
        r"Dati del cedente\s*/\s*prestatore(.*?)(?=Dati del cessionario|\Z)",
        testo_pdf,
        re.DOTALL | re.IGNORECASE,
    )
    if m_ced:
        blocco_cedente = m_ced.group(1)

    # Sezione Cliente (Cessionario/Committente)
    m_ces = re.search(
        r"Dati del cessionario\s*/\s*committente(.*?)(?=Dati generali"
        r" del documento|\Z)",
        testo_pdf,
        re.DOTALL | re.IGNORECASE,
    )
    if m_ces:
        blocco_cessionario = m_ces.group(1)

    # Sezione Dati Generali
    m_gen = re.search(
        r"Dati generali del documento(.*?)(?=Dati relativi al pagamento|\Z)",
        testo_pdf,
        re.DOTALL | re.IGNORECASE,
    )
    if m_gen:
        blocco_generale = m_gen.group(1)

    # Sezione Pagamento
    m_pag = re.search(
        r"Dati relativi al pagamento(.*?)\Z",
        testo_pdf,
        re.DOTALL | re.IGNORECASE,
    )
    if m_pag:
        blocco_pagamento = m_pag.group(1)

    # -----------------------------------------------------------------
    # 2. ESTRAZIONE FORNITORE (CEDENTE)
    # -----------------------------------------------------------------
    # Nome / Denominazione (Gestisce Antonio Ferraiuolo: Nome + Cognome)
    m_nome = re.search(
        r"Nome:\s*([^\n\r]+)", blocco_cedente, re.IGNORECASE
    )
    m_cognome = re.search(
        r"Cognome:\s*([^\n\r]+)", blocco_cedente, re.IGNORECASE
    )
    m_denom = re.search(
        r"Denominazione:\s*([^\n\r]+)", blocco_cedente, re.IGNORECASE
    )

    if m_nome and m_cognome:
        dati["fornitore_nome"] = (
            f"{m_nome.group(1).strip()} {m_cognome.group(1).strip()}"
        )
    elif m_denom:
        dati["fornitore_nome"] = m_denom.group(1).strip()
    else:
        dati["fornitore_nome"] = "FORNITORE"

    # P.IVA e Codice Fiscale
    m_piva = re.search(
        r"Identificativo fiscale ai fini IVA:\s*(?:IT)?([A-Za-z0-9]+)",
        blocco_cedente,
    )
    dati["fornitore_piva"] = m_piva.group(1).strip() if m_piva else ""

    m_cf = re.search(r"Codice fiscale:\s*([A-Za-z0-9]+)", blocco_cedente)
    dati["fornitore_cf"] = m_cf.group(1).strip() if m_cf else ""
    if not dati["fornitore_piva"] and dati["fornitore_cf"]:
        dati["fornitore_piva"] = dati["fornitore_cf"]

    # Sede Fornitore
    m_ind = re.search(
        r"Indirizzo:\s*([^\n\r]+)", blocco_cedente, re.IGNORECASE
    )
    dati["fornitore_indirizzo"] = m_ind.group(1).strip() if m_ind else ""

    m_cap = re.search(r"CAP:\s*(\d{5})", blocco_cedente)
    dati["fornitore_cap"] = m_cap.group(1).strip() if m_cap else ""

    m_comune = re.search(
        r"Comune:\s*([^\n\r]+)", blocco_cedente, re.IGNORECASE
    )
    dati["fornitore_comune"] = m_comune.group(1).strip() if m_comune else ""

    m_naz = re.search(r"Nazione:\s*([A-Za-z]{2})", blocco_cedente)
    dati["fornitore_nazione"] = m_naz.group(1).strip().upper() if m_naz else "IT"

    # -----------------------------------------------------------------
    # 3. ESTRAZIONE CLIENTE (CESSIONARIO - es. CASAZEN)
    # -----------------------------------------------------------------
    m_c_denom = re.search(
        r"Denominazione:\s*([^\n\r]+)", blocco_cessionario, re.IGNORECASE
    )
    dati["cliente_nome"] = (
        m_c_denom.group(1).strip() if m_c_denom else "CASAZEN s.r.l."
    )

    m_c_piva = re.search(
        r"Identificativo fiscale ai fini IVA:\s*(?:IT)?([A-Za-z0-9]+)",
        blocco_cessionario,
    )
    dati["cliente_piva"] = (
        m_c_piva.group(1).strip() if m_c_piva else "09847131217"
    )

    m_c_ind = re.search(
        r"Indirizzo:\s*([^\n\r]+)", blocco_cessionario, re.IGNORECASE
    )
    dati["cliente_indirizzo"] = m_c_ind.group(1).strip() if m_c_ind else ""

    m_c_cap = re.search(r"CAP:\s*(\d{5})", blocco_cessionario)
    dati["cliente_cap"] = m_c_cap.group(1).strip() if m_c_cap else "80141"

    m_c_com = re.search(
        r"Comune:\s*([^\n\r]+)", blocco_cessionario, re.IGNORECASE
    )
    dati["cliente_comune"] = (
        m_c_com.group(1).strip() if m_c_com else "NAPOLI"
    )
    dati["cliente_nazione"] = "IT"

    # -----------------------------------------------------------------
    # 4. DATI DOCUMENTO E IMPORTI
    # -----------------------------------------------------------------
    m_num = re.search(
        r"Numero documento:\s*([^\n\r]+)", blocco_generale, re.IGNORECASE
    )
    dati["numero"] = m_num.group(1).strip() if m_num else "1"

    m_data = re.search(r"Data documento:\s*(\d{4}-\d{2}-\d{2})", blocco_generale)
    dati["data"] = m_data.group(1).strip() if m_data else ""

    m_tipo = re.search(r"Tipologia documento:\s*(TD\d+)", blocco_generale)
    dati["tipo_documento"] = m_tipo.group(1).strip() if m_tipo else "TD01"

    # Imponibile, Aliquota, Imposta e Totale
    m_imp = re.search(
        r"Totale imponibile/importo:\s*([\d\.,]+)", blocco_generale
    )
    dati["imponibile"] = (
        float(m_imp.group(1).replace(",", ".")) if m_imp else 0.0
    )

    m_aliq = re.search(r"Aliquota IVA.*?:?\s*([\d\.,]+)", blocco_generale)
    dati["aliquota_iva"] = (
        float(m_aliq.group(1).replace(",", ".")) if m_aliq else 22.0
    )

    m_tax = re.search(r"Totale imposta:\s*([\d\.,]+)", blocco_generale)
    dati["imposta"] = (
        float(m_tax.group(1).replace(",", ".")) if m_tax else 0.0
    )

    m_tot = re.search(
        r"Importo totale documento:\s*([\d\.,]+)", blocco_generale
    )
    dati["totale"] = (
        float(m_tot.group(1).replace(",", ".")) if m_tot else 0.0
    )

    # Ritenuta d'acconto
    m_rit = re.search(r"Importo ritenuta:\s*([\d\.,]+)", blocco_generale)
    dati["ritenuta"] = (
        float(m_rit.group(1).replace(",", ".")) if m_rit else 0.0
    )

    # Descrizione prima linea
    m_desc = re.search(
        r"Descrizione bene/servizio:\s*([^\n\r]+)", blocco_generale
    )
    dati["descrizione"] = (
        m_desc.group(1).strip()
        if m_desc
        else "Prestazione professionale / Beni"
    )

    # -----------------------------------------------------------------
    # 5. DATI PAGAMENTO E CONSPAY
    # -----------------------------------------------------------------
    m_iban = re.search(r"Codice IBAN:\s*([A-Z0-9]+)", blocco_pagamento)
    dati["iban"] = m_iban.group(1).strip() if m_iban else ""

    m_scad = re.search(
        r"Data scadenza pagamento:\s*(\d{4}-\d{2}-\d{2})", blocco_pagamento
    )
    dati["scadenza"] = (
        m_scad.group(1).strip() if m_scad else dati.get("data", "")
    )

    m_metodo = re.search(r"Modalità:\s*(MP\d+)", blocco_pagamento)
    dati["metodo_pagamento"] = m_metodo.group(1).strip() if m_metodo else "MP05"

    return dati
