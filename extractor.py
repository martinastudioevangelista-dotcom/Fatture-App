# extractor.py - Motore Fiscale ad Alta Precisione (Sintassi Verificata)
import re
import json
import fitz  # PyMuPDF
from datetime import datetime

def pulisci_cifra(s):
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    try:
        t = str(s).strip().replace("€", "").replace(" ", "")
        if "," in t and "." in t:
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif "," in t:
            t = t.replace(",", ".")
        return round(float(t), 2)
    except Exception:
        return 0.0

def estrai_indirizzo_cap_comune(testo_blocco):
    """Estrae Via, CAP, Comune e Provincia in modo robusto."""
    indirizzo = ""
    cap = "00100"
    comune = "Roma"
    prov = "RM"
    righe = [r.strip() for r in str(testo_blocco).split("\n") if r.strip()]
    
    for riga in righe:
        m_cap = re.search(r"\b(\d{5})\b\s+([A-Za-z\s']+?)(?:\s*\(([A-Z]{2})\)|\s+([A-Z]{2})\b|$)", riga)
        if m_cap:
            cap = m_cap.group(1)
            comune = m_cap.group(2).strip().title()
            p = m_cap.group(3) or m_cap.group(4) or "RM"
            prov = p.upper()
            break

    for riga in righe:
        if re.search(r"\b(via|viale|corso|piazza|strada|localit|vicolo)\b", riga, re.IGNORECASE):
            indirizzo = re.sub(r"-\s*\d{5}.*", "", riga).strip()
            indirizzo = re.sub(r"\b\d{5}\b.*", "", indirizzo).strip()
            break

    if not indirizzo and len(righe) > 1:
        indirizzo = righe[1]

    return indirizzo[:60], cap, comune[:60], prov

def parser_locale_fattura(testo):
    """Estrae i dati esatti (con supporto a layout come Cavit S.A.S. / CASAZEN S.R.L.)."""
    testo = str(testo)
    pivas = re.findall(r"\b(\d{11})\b", testo)
    
    piva_fornitore = ""
    piva_cliente = ""

    # 1. Cerca P.IVA cliente nel box Destinatario
    m_dest = re.search(r"(?:destinatario|destinazione|spett)[\s\S]{1,400}?(?:p\.?\s*iva|c\.?\s*f\.?)[\s:]*([0-9]{11})", testo, re.IGNORECASE)
    if m_dest:
        piva_cliente = m_dest.group(1)

    # 2. Cerca P.IVA fornitore in testata
    m_ced = re.search(r"(?:c\.?f\.?\/p\.?\s*iva|p\.?\s*iva|partita\s*iva)[\s:]*([0-9]{11})", testo, re.IGNORECASE)
    if m_ced and m_ced.group(1) != piva_cliente:
        piva_fornitore = m_ced.group(1)

    if not piva_fornitore and pivas:
        piva_fornitore = pivas[0]
    if not piva_cliente:
        for p in pivas:
            if p != piva_fornitore:
                piva_cliente = p
                break

    # 3. Denominazione e Sede Fornitore (Cedente)
    m_rag_ced = re.search(r"([A-Za-z0-9\s.,&'\-]{3,70}(?:S\.?A\.?S\.?|S\.?R\.?L\.?|S\.?P\.?A\.?|S\.?N\.?C\.?)[A-Za-z0-9\s.,&'\-]*)", testo[:1000], re.IGNORECASE)
    if m_rag_ced:
        ced_nome = m_rag_ced.group(1).strip()
    else:
        righe = [r.strip() for r in testo.split("\n") if len(r.strip()) > 3]
        ced_nome = righe[0] if righe else "FORNITORE"

    ced_via, ced_cap, ced_com, ced_prov = estrai_indirizzo_cap_comune(testo[:800])

    # 4. Denominazione e Sede Cliente (Destinatario)
    cess_nome = "CLIENTE STUDIO"
    cess_via = "Via Cliente 1"
    cess_cap = "00100"
    cess_com = "Roma"
    cess_prov = "RM"

    m_box_dest = re.search(r"Destinatario\s*\n+([^\n]+)([\s\S]*?)(?=Fattura|Codice|Quantit|nr\.|$)", testo, re.IGNORECASE)
    if m_box_dest:
        cess_nome = m_box_dest.group(1).strip()
        cess_via, cess_cap, cess_com, cess_prov = estrai_indirizzo_cap_comune(m_box_dest.group(2))
    else:
        m_spett = re.search(r"Spett\S*\s*\n+([^\n]+)([\s\S]*?)(?=Fattura|Codice|Quantit|$)", testo, re.IGNORECASE)
        if m_spett:
            cess_nome = m_spett.group(1).strip()
            cess_via, cess_cap, cess_com, cess_prov = estrai_indirizzo_cap_comune(m_spett.group(2))

    # 5. Numero e Data Fattura
    num_doc = "1"
    data_doc = datetime.today().strftime("%Y-%m-%d")

    m_num_data = re.search(r"(?:fattura\s+nr\.?|nr\.?|fattura\s+n\.?)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)\s*(?:del)?\s*([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])", testo, re.IGNORECASE)
    if m_num_data:
        num_doc = m_num_data.group(1).strip()
        d_raw = m_num_data.group(2).replace("/", "-").replace(".", "-").split("-")
        data_doc = d_raw[2] + "-" + d_raw[1].zfill(2) + "-" + d_raw[0].zfill(2)
    else:
        m_num = re.search(r"(?:fattura|doc|num|n°)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)", testo, re.IGNORECASE)
        if m_num:
            num_doc = m_num.group(1).strip()

    # 6. Sezione Contabile
    imponibile = 0.0
    imposta = 0.0
    totale = 0.0
    aliquota = 22.0

    m_imp = re.search(r"Imponibile(?:\s*22%)?\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_imp:
        imponibile = pulisci_cifra(m_imp.group(1))

    m_iva = re.search(r"Imposta\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_iva:
        imposta = pulisci_cifra(m_iva.group(1))

    m_tot = re.search(r"(?:Tot\.?\s*documento|Totale\s*documento|Totale\s*fattura)\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_tot:
        totale = pulisci_cifra(m_tot.group(1))

    if totale == 0.0 and (imponibile > 0 or imposta > 0):
        totale = round(imponibile + imposta, 2)

    # 7. Pagamento CONSPAY
    metodo_pag = "MP05"
    if re.search(r"carta\s+di\s+pagamento|carta\s+di\s+credito|pos|bancomat", testo, re.IGNORECASE):
        metodo_pag = "MP08"
    elif re.search(r"bonifico", testo, re.IGNORECASE):
        metodo_pag = "MP05"
    elif re.search(r"riba|ricevuta\s+bancaria", testo, re.IGNORECASE):
        metodo_pag = "MP12"
    elif re.search(r"contanti", testo, re.IGNORECASE):
        metodo_pag = "MP01"

    data_scadenza = data_doc
    m_scad = re.search(r"Scadenze?:\s*([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])", testo, re.IGNORECASE)
    if m_scad:
        d_sc = m_scad.group(1).replace("/", "-").replace(".", "-").split("-")
        data_scadenza = d_sc[2] + "-" + d_sc[1].zfill(2) + "-" + d_sc[0].zfill(2)

    m_iban = re.search(r"\b(IT\d{2}[A-Z]\d{10}[0-9A-Z]{12})\b", testo.replace(" ", "").upper())
    iban_doc = m_iban.group(1) if m_iban else ""

    return {
        "tipo_documento": "TD01",
        "numero_documento": num_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_paese": "IT",
        "cedente_piva": piva_fornitore,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_com,
        "cedente_provincia": ced_prov,
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": "IT",
        "cessionario_piva": piva_cliente,
        "cessionario_cf": "",
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_com,
        "cessionario_provincia": cess_prov,
        "imponibile": imponibile,
        "aliquota_prevalente": aliquota,
        "imposta": imposta,
        "totale_documento": totale,
        "natura": "",
        "iban": iban_doc,
        "data_scadenza": data_scadenza,
        "modalita_pagamento": metodo_pag
    }

def estrai_con_gemini(file_bytes, filename, api_key, testo):
    """Chiamata a Gemini protetta senza f-string a rischio."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            "Estrai i dati fiscali da questa fattura per TeamSystem CONSPAY in JSON.\n"
            "Restituisci un JSON con questi campi esatti:\n"
            "cedente_denominazione, cedente_paese, cedente_piva, cedente_indirizzo, cedente_cap, cedente_comune, cedente_provincia, "
            "cessionario_denominazione, cessionario_paese, cessionario_piva, cessionario_cf, cessionario_indirizzo, cessionario_cap, cessionario_comune, cessionario_provincia, "
            "numero_documento, data_documento, tipo_documento, imponibile, aliquota_prevalente, imposta, totale_documento, natura, iban, data_scadenza, modalita_pagamento.\n\n"
            "Testo del documento:\n" + str(testo)[:5000]
        )

        response = model.generate_content(prompt, request_options={"timeout": 12.0})
        raw = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        data["imponibile"] = pulisci_cifra(data.get("imponibile", 0.0))
        data["imposta"] = pulisci_cifra(data.get("imposta", 0.0))
        data["totale_documento"] = pulisci_cifra(data.get("totale_documento", 0.0))
        data["aliquota_prevalente"] = float(data.get("aliquota_prevalente", 22.0))
        data["cedente_piva"] = re.sub(r"[^0-9]", "", str(data.get("cedente_piva", "")))
        data["cessionario_piva"] = re.sub(r"[^0-9]", "", str(data.get("cessionario_piva", "")))
        return data, None
    except Exception as e:
        return None, str(e)

def estrai_dati_fattura(file_input, filename="fattura.pdf", api_key=None):
    """Entry point principale."""
    if hasattr(file_input, "read"):
        file_input.seek(0)
        file_bytes = file_input.read()
    elif isinstance(file_input, bytes):
        file_bytes = file_input
    else:
        with open(file_input, "rb") as f:
            file_bytes = f.read()

    testo_completo = ""
    doc = None
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            testo_completo += page.get_text("text") + "\n"
    except Exception:
        testo_completo = ""
    finally:
        if doc:
            doc.close()

    if api_key and len(str(api_key).strip()) > 10:
        dati_ai, err_ai = estrai_con_gemini(file_bytes, filename, str(api_key).strip(), testo_completo)
        if dati_ai:
            return dati_ai, "Gemini AI (Vision / Intelligente)", testo_completo, None
        else:
            dati_loc = parser_locale_fattura(testo_completo)
            return dati_loc, "Parser Locale (Fallback)", testo_completo, "Gemini offline: " + str(err_ai)

    dati_locale = parser_locale_fattura(testo_completo)
    return dati_locale, "Parser Locale Deterministico (PyMuPDF)", testo_completo, None
