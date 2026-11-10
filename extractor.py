# extractor.py - Motore Fiscale Universale Multi-Layout per qualsiasi fattura (IT / Estera)
from datetime import datetime
import json
import re
import fitz  # PyMuPDF


def pulisci_cifra(s):
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    try:
        t = str(s).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
        if "," in t and "." in t:
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif "," in t:
            t = t.replace(",", ".")
        m = re.search(r"[-+]?\d*\.?\d+", t)
        return round(float(m.group(0)), 2) if m else 0.0
    except Exception:
        return 0.0


def estrai_indirizzo_cap_comune(testo_blocco):
    indirizzo = ""
    cap = ""
    comune = ""
    prov = ""
    righe = [r.strip() for r in str(testo_blocco).split("\n") if r.strip()]

    for riga in righe:
        m_cap = re.search(
            r"\b(\d{5})\b\s+([A-Za-z\s']+?)(?:\s*([A-Z]{2})|\s+([A-Z]{2})\b|$)",
            riga,
        )
        if m_cap:
            cap = m_cap.group(1)
            comune = m_cap.group(2).strip().title()
            prov = (m_cap.group(3) or m_cap.group(4) or "").upper()
            break

    for riga in righe:
        if re.search(
            r"\b(via|viale|corso|piazza|strada|localit|vicolo|avenue|street|rue)\b",
            riga,
            re.IGNORECASE,
        ):
            r_pulita = re.sub(r"-\s*\d{5}.*", "", riga).strip()
            r_pulita = re.sub(r"\b\d{5}\b.*", "", r_pulita).strip()
            indirizzo = r_pulita
            break

    return indirizzo[:60], cap, comune[:60], prov


def _ponte_chiavi(dati: dict) -> dict:
    """Garantisce la compresenza di TUTTI i formati di chiave (ministeriali e colloquiali)

    azzerando qualsiasi rischio di KeyError in app.py e nella tabella Streamlit.
    """
    if not isinstance(dati, dict):
        dati = {}

    dati["imponibile"] = pulisci_cifra(dati.get("imponibile", 0.0))
    dati["aliquota_prevalente"] = pulisci_cifra(
        dati.get("aliquota_prevalente") or dati.get("aliquota_iva", 22.0)
    )
    dati["aliquota_iva"] = dati["aliquota_prevalente"]
    dati["imposta"] = pulisci_cifra(dati.get("imposta", 0.0))
    dati["totale_documento"] = pulisci_cifra(
        dati.get("totale_documento") or dati.get("totale", 0.0)
    )
    dati["totale"] = dati["totale_documento"]
    dati["ritenuta"] = pulisci_cifra(dati.get("ritenuta", 0.0))

    if dati["totale"] == 0.0 and dati["imponibile"] > 0:
        dati["totale"] = round(dati["imponibile"] + dati["imposta"], 2)
        dati["totale_documento"] = dati["totale"]

    # Fornitore (Cedente)
    fn = (
        dati.get("cedente_denominazione")
        or dati.get("fornitore_nome")
        or dati.get("fornitore")
        or "FORNITORE"
    )
    fp = re.sub(
        r"[^0-9A-Za-z]",
        "",
        str(
            dati.get("cedente_piva")
            or dati.get("fornitore_piva")
            or dati.get("cedente_cf")
            or ""
        ),
    )
    f_paese = (
        dati.get("cedente_paese") or dati.get("fornitore_nazione") or "IT"
    )[:2].upper()

    dati["cedente_denominazione"] = fn
    dati["fornitore_nome"] = fn
    dati["fornitore"] = fn
    dati["cedente_piva"] = fp
    dati["fornitore_piva"] = fp
    dati["cedente_paese"] = f_paese
    dati["fornitore_nazione"] = f_paese
    dati["cedente_indirizzo"] = (
        dati.get("cedente_indirizzo") or dati.get("fornitore_indirizzo") or ""
    )
    dati["fornitore_indirizzo"] = dati["cedente_indirizzo"]
    dati["cedente_cap"] = (
        dati.get("cedente_cap") or dati.get("fornitore_cap") or ""
    )
    dati["fornitore_cap"] = dati["cedente_cap"]
    dati["cedente_comune"] = (
        dati.get("cedente_comune") or dati.get("fornitore_comune") or ""
    )
    dati["fornitore_comune"] = dati["cedente_comune"]

    # Cliente (Cessionario)
    cn = (
        dati.get("cessionario_denominazione")
        or dati.get("cliente_nome")
        or dati.get("cliente")
        or "CLIENTE"
    )
    cp = re.sub(
        r"[^0-9A-Za-z]",
        "",
        str(
            dati.get("cessionario_piva")
            or dati.get("cliente_piva")
            or dati.get("cessionario_cf")
            or ""
        ),
    )
    c_paese = (
        dati.get("cessionario_paese") or dati.get("cliente_nazione") or "IT"
    )[:2].upper()

    dati["cessionario_denominazione"] = cn
    dati["cliente_nome"] = cn
    dati["cliente"] = cn
    dati["cessionario_piva"] = cp
    dati["cliente_piva"] = cp
    dati["cessionario_paese"] = c_paese
    dati["cliente_nazione"] = c_paese
    dati["cessionario_indirizzo"] = (
        dati.get("cessionario_indirizzo") or dati.get("cliente_indirizzo") or ""
    )
    dati["cliente_indirizzo"] = dati["cessionario_indirizzo"]
    dati["cessionario_cap"] = (
        dati.get("cessionario_cap") or dati.get("cliente_cap") or ""
    )
    dati["cliente_cap"] = dati["cessionario_cap"]
    dati["cessionario_comune"] = (
        dati.get("cessionario_comune") or dati.get("cliente_comune") or ""
    )
    dati["cliente_comune"] = dati["cessionario_comune"]

    # Numero e Data
    num = str(
        dati.get("numero_documento") or dati.get("numero") or "1"
    ).strip()
    dati["numero_documento"] = num
    dati["numero"] = num

    dt = str(
        dati.get("data_documento")
        or dati.get("data")
        or datetime.today().strftime("%Y-%m-%d")
    ).strip()
    dati["data_documento"] = dt
    dati["data"] = dt

    # Pagamento
    dati["data_scadenza"] = (
        dati.get("data_scadenza") or dati.get("scadenza") or dt
    )
    dati["scadenza"] = dati["data_scadenza"]
    dati["modalita_pagamento"] = (
        dati.get("modalita_pagamento")
        or dati.get("metodo_pagamento")
        or "MP05"
    )
    dati["metodo_pagamento"] = dati["modalita_pagamento"]

    return dati


# ---------------------------------------------------------
# PARSER FOGLIO DI STILE SDI DINAMICO (Per qualsiasi intestatario)
# ---------------------------------------------------------
def parser_foglio_stile_sdi(testo):
    m_piva_ced = re.search(
        r"Dati del cedente[\s\S]*?Identificativo fiscale ai fini"
        r" IVA:\s*(?:IT)?(\w+)",
        testo,
        re.IGNORECASE,
    )
    ced_piva = m_piva_ced.group(1) if m_piva_ced else ""
    m_cf_ced = re.search(
        r"Dati del cedente[\s\S]*?Codice fiscale:\s*([A-Z0-9]+)",
        testo,
        re.IGNORECASE,
    )
    ced_cf = m_cf_ced.group(1) if m_cf_ced else ced_piva

    ced_nome = ""
    m_den_ced = re.search(
        r"Dati del cedente[\s\S]*?Denominazione:\s*([^\n]+)",
        testo,
        re.IGNORECASE,
    )
    if m_den_ced:
        ced_nome = m_den_ced.group(1).strip()
    else:
        m_nc = re.search(
            r"Nome:\s*([^\n]+)\s*\n\s*Cognome:\s*([^\n]+)", testo, re.IGNORECASE
        )
        if m_nc:
            ced_nome = (
                f"{m_nc.group(2).strip()} {m_nc.group(1).strip()}".upper()
            )

    m_ind_ced = re.search(
        r"Dati del cedente[\s\S]*?Indirizzo:\s*([^\n]+)", testo, re.IGNORECASE
    )
    ced_via = m_ind_ced.group(1).strip() if m_ind_ced else ""
    m_cap_ced = re.search(
        r"Dati del cedente[\s\S]*?CAP:\s*(\d{5})", testo, re.IGNORECASE
    )
    ced_cap = m_cap_ced.group(1) if m_cap_ced else ""
    m_com_ced = re.search(
        r"Dati del cedente[\s\S]*?Comune:\s*([^\n]+)", testo, re.IGNORECASE
    )
    ced_com = m_com_ced.group(1).strip().title() if m_com_ced else ""
    m_pr_ced = re.search(
        r"Dati del cedente[\s\S]*?Provincia:\s*([A-Z]{2})", testo, re.IGNORECASE
    )
    ced_prov = m_pr_ced.group(1).upper() if m_pr_ced else ""

    m_piva_cess = re.search(
        r"Dati del cessionario[\s\S]*?Identificativo fiscale ai fini"
        r" IVA:\s*(?:IT)?(\w+)",
        testo,
        re.IGNORECASE,
    )
    cess_piva = m_piva_cess.group(1) if m_piva_cess else ""
    m_cf_cess = re.search(
        r"Dati del cessionario[\s\S]*?Codice [Ff]iscale:\s*([A-Z0-9]+)",
        testo,
        re.IGNORECASE,
    )
    cess_cf = m_cf_cess.group(1) if m_cf_cess else cess_piva

    cess_nome = ""
    m_den_cess = re.search(
        r"Dati del cessionario[\s\S]*?Denominazione:\s*([^\n]+)",
        testo,
        re.IGNORECASE,
    )
    if m_den_cess:
        cess_nome = m_den_cess.group(1).strip()

    m_ind_cess = re.search(
        r"Dati del cessionario[\s\S]*?Indirizzo:\s*([^\n]+)",
        testo,
        re.IGNORECASE,
    )
    cess_via = m_ind_cess.group(1).strip() if m_ind_cess else ""
    m_cap_cess = re.search(
        r"Dati del cessionario[\s\S]*?CAP:\s*(\d{5})", testo, re.IGNORECASE
    )
    cess_cap = m_cap_cess.group(1) if m_cap_cess else ""
    m_com_cess = re.search(
        r"Dati del cessionario[\s\S]*?Comune:\s*([^\n]+)", testo, re.IGNORECASE
    )
    cess_com = m_com_cess.group(1).strip().title() if m_com_cess else ""
    m_pr_cess = re.search(
        r"Dati del cessionario[\s\S]*?Provincia:\s*([A-Z]{2})",
        testo,
        re.IGNORECASE,
    )
    cess_prov = m_pr_cess.group(1).upper() if m_pr_cess else ""

    m_nd = re.search(r"Numero documento:\s*([^\n]+)", testo, re.IGNORECASE)
    num_doc = m_nd.group(1).strip().split()[0] if m_nd else "1"

    data_doc = datetime.today().strftime("%Y-%m-%d")
    m_dd = re.search(
        r"Data documento:\s*(\d{4}-\d{2}-\d{2})", testo, re.IGNORECASE
    )
    if m_dd:
        data_doc = m_dd.group(1).strip()

    m_imp = re.search(
        r"Totale imponibile/importo:\s*([\d\s.,]+)", testo, re.IGNORECASE
    )
    imponibile = pulisci_cifra(m_imp.group(1)) if m_imp else 0.0

    m_aliq = re.search(
        r"Aliquota IVA.*?:?\s*([\d\s.,]+)", testo, re.IGNORECASE
    )
    aliquota = pulisci_cifra(m_aliq.group(1)) if m_aliq else 22.0

    m_iva = re.search(
        r"Totale imposta:\s*([\d\s.,]+)", testo, re.IGNORECASE
    )
    imposta = pulisci_cifra(m_iva.group(1)) if m_iva else 0.0

    m_rit = re.search(
        r"Importo ritenuta:\s*([\d\s.,]+)", testo, re.IGNORECASE
    )
    ritenuta = pulisci_cifra(m_rit.group(1)) if m_rit else 0.0

    m_tot = re.search(
        r"Importo totale documento:\s*([\d\s.,]+)", testo, re.IGNORECASE
    )
    if m_tot:
        totale = pulisci_cifra(m_tot.group(1))
    else:
        totale = round(imponibile + imposta, 2)

    m_iban = re.search(
        r"(?:Codice IBAN|IBAN)[:\s]*([A-Z0-9]+)", testo, re.IGNORECASE
    )
    iban_doc = m_iban.group(1).strip().upper() if m_iban else ""

    m_scad = re.search(
        r"Data scadenza pagamento:\s*(\d{4}-\d{2}-\d{2})", testo, re.IGNORECASE
    )
    data_scad = m_scad.group(1).strip() if m_scad else data_doc

    return {
        "tipo_documento": "TD01",
        "numero_documento": num_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_paese": "IT",
        "cedente_piva": ced_piva,
        "cedente_cf": ced_cf,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_com,
        "cedente_provincia": ced_prov,
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": "IT",
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf,
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_com,
        "cessionario_provincia": cess_prov,
        "imponibile": imponibile,
        "aliquota_prevalente": aliquota,
        "imposta": imposta,
        "ritenuta": ritenuta,
        "totale_documento": totale,
        "natura": "",
        "iban": iban_doc,
        "data_scadenza": data_scad,
        "modalita_pagamento": "MP05",
    }


# ---------------------------------------------------------
# MOTORE COMMERCIALE UNIVERSALE (Per qualsiasi fattura cartacea/digitale)
# ---------------------------------------------------------
def parser_commerciale_generale(testo):
    righe = [r.strip() for r in testo.split("\n") if r.strip()]

    # Ricerca P.IVA Cedente (prima P.IVA del documento)
    pive = re.findall(
        r"(?:P\.?IVA|Partita IVA|C\.?F\.?\/P\.?IVA)[:\s]*([0-9]{11})",
        testo,
        re.IGNORECASE,
    )
    if not pive:
        pive = re.findall(r"\b(\d{11})\b", testo)

    ced_piva = pive[0] if pive else ""
    cess_piva = pive[1] if len(pive) > 1 else ""

    # Ricerca Denominazione Cedente (in cima al documento)
    ced_nome = ""
    for r in righe[:6]:
        if re.search(
            r"\b(s\.?r\.?l\.?|s\.?p\.?a\.?|s\.?a\.?s\.?|s\.?n\.?c\.?|ditta|studio|coop)\b",
            r,
            re.IGNORECASE,
        ):
            ced_nome = r
            break
    if not ced_nome and righe:
        ced_nome = righe[0]

    # Ricerca Cessionario
    cess_nome = ""
    m_dest = re.search(
        r"(?:Spett\.?le|Destinatario|Cliente|Fatturato a)[:\s]*\n*([^\n]+)",
        testo,
        re.IGNORECASE,
    )
    if m_dest:
        cess_nome = m_dest.group(1).strip()

    # Rilevamento fornitore estero (es. Francia, Germania)
    m_estero = re.search(r"\b(FR|DE|ES|NL|BE|AT)\w{8,14}\b", testo)
    ced_paese = "IT"
    if m_estero and not ced_piva:
        ced_paese = m_estero.group(1).upper()
        ced_piva = m_estero.group(0)

    # Numero e Data
    num_doc = "1"
    m_num = re.search(
        r"(?:Fattura|Documento|Doc\.)\s*(?:nr?\.?|del|n\.?)?\s*([A-Za-z0-9/\-_]+)",
        testo,
        re.IGNORECASE,
    )
    if m_num:
        num_doc = m_num.group(1).strip().split()[0]

    data_doc = datetime.today().strftime("%Y-%m-%d")
    m_data = re.search(r"\b([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.]20[2-3][0-9])\b", testo)
    if m_data:
        dp = m_data.group(1).replace("/", "-").replace(".", "-").split("-")
        data_doc = f"{dp[2]}-{dp[1].zfill(2)}-{dp[0].zfill(2)}"

    # Importi
    imponibile = 0.0
    m_imp = re.search(
        r"(?:Imponibile|Totale Imponibile)[^\d\n\r]*€?\s*([\d\s.,]+)",
        testo,
        re.IGNORECASE,
    )
    if m_imp:
        imponibile = pulisci_cifra(m_imp.group(1))

    imposta = 0.0
    m_iva = re.search(
        r"(?:IVA|Totale IVA|Imposta)[^\d\n\r]*€?\s*([\d\s.,]+)",
        testo,
        re.IGNORECASE,
    )
    if m_iva:
        imposta = pulisci_cifra(m_iva.group(1))

    totale = 0.0
    m_tot = re.search(
        r"(?:Totale Documento|Totale Fattura|Netto a pagare|Totale dovuto)[^\d\n\r]*€?\s*([\d\s.,]+)",
        testo,
        re.IGNORECASE,
    )
    if m_tot:
        totale = pulisci_cifra(m_tot.group(1))
    elif imponibile > 0:
        totale = round(imponibile + imposta, 2)

    aliquota = 22.0
    if ced_paese != "IT":
        aliquota = 0.0
        imposta = 0.0
    elif imponibile > 0 and imposta > 0:
        aliquota = round((imposta / imponibile) * 100.0, 1)

    m_iban = re.search(
        r"\b(IT\d{2}[A-Za-z0-9]{22})\b", testo.replace(" ", "").upper()
    )
    iban_doc = m_iban.group(1).strip() if m_iban else ""

    return {
        "tipo_documento": "TD01",
        "numero_documento": num_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_paese": ced_paese,
        "cedente_piva": ced_piva,
        "cedente_cf": ced_piva,
        "cedente_indirizzo": "",
        "cedente_cap": "",
        "cedente_comune": "",
        "cedente_provincia": "",
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": "IT",
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_piva,
        "cessionario_indirizzo": "",
        "cessionario_cap": "",
        "cessionario_comune": "",
        "cessionario_provincia": "",
        "imponibile": imponibile,
        "aliquota_prevalente": aliquota,
        "imposta": imposta,
        "ritenuta": 0.0,
        "totale_documento": totale,
        "natura": "N3.2" if (ced_paese != "IT" and aliquota == 0.0) else "",
        "iban": iban_doc,
        "data_scadenza": data_doc,
        "modalita_pagamento": "MP05",
    }


# ---------------------------------------------------------
# GEMINI VISION PER QUALSIASI FORMATO (Scansioni, Estero, Complesse)
# ---------------------------------------------------------
def estrai_con_gemini_vision(file_bytes, filename, api_key):
    """Analizza il file PDF direttamente tramite AI visiva per leggere qualsiasi grafica."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)

        prompt = (
            "Sei un contabile esperto di fatturazione elettronica FPR12 e"
            " TeamSystem CONSPAY. "
            "Analizza questo documento (che può essere una fattura italiana o"
            " estera, un foglio di stile ministeriale, una scansione o una"
            " fattura commerciale). "
            "Distingui accuratamente chi EMETTE la fattura (CEDENTE/Fornitore)"
            " da chi la RICEVE (CESSIONARIO/Cliente). "
            "Se il fornitore è estero (es. Francia, Germania), valorizza"
            " cedente_paese con il codice a due lettere (es. FR, DE),"
            " aliquota_prevalente=0.0 e natura='N3.2'. "
            "Se persona fisica italiana, estrai Nome e Cognome uniti in"
            " cedente_denominazione. "
            "Estrai con la massima precisione: numero, data, imponibile,"
            " aliquota, imposta, eventuale ritenuta d'acconto, totale da"
            " pagare, IBAN, scadenza e metodo di pagamento. "
            "Rispondi ESCLUSIVAMENTE con un JSON con questi campi esatti:\n"
            "cedente_denominazione, cedente_paese, cedente_piva, cedente_cf,"
            " cedente_indirizzo, cedente_cap, cedente_comune, cedente_provincia,"
            " "
            "cessionario_denominazione, cessionario_paese, cessionario_piva,"
            " cessionario_cf, cessionario_indirizzo, cessionario_cap,"
            " cessionario_comune, cessionario_provincia, "
            "numero_documento, data_documento, tipo_documento, imponibile,"
            " aliquota_prevalente, imposta, ritenuta, totale_documento, natura,"
            " iban, data_scadenza, modalita_pagamento."
        )

        modelli = [
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
        ]
        for m_name in modelli:
            try:
                model = genai.GenerativeModel(m_name)
                res = model.generate_content(
                    [
                        prompt,
                        {"mime_type": "application/pdf", "data": file_bytes},
                    ],
                    request_options={"timeout": 20.0},
                )
                clean_json = (
                    res.text.replace("```json", "").replace("```", "").strip()
                )
                data = json.loads(clean_json)

                data["imponibile"] = pulisci_cifra(data.get("imponibile", 0.0))
                data["imposta"] = pulisci_cifra(data.get("imposta", 0.0))
                data["ritenuta"] = puli
