# extractor.py - Motore Fiscale Compatto (Anagrafiche Bloccate & Quadratura Contabile)
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
            r_pulita = re.sub(r"-\s*\d{5}.*", "", riga).strip()
            r_pulita = re.sub(r"\b\d{5}\b.*", "", r_pulita).strip()
            indirizzo = r_pulita
            break

    if not indirizzo and len(righe) > 1:
        indirizzo = righe[1]

    return indirizzo[:60], cap, comune[:60], prov

def risolvi_sezione_contabile(testo):
    """Calcola e quadra matematicamente: Imponibile + IVA - Ritenuta = Totale."""
    # 1. Ritenuta d'acconto (es. Ferraiuolo: 140.40)
    ritenuta = 0.0
    m_rit = re.search(r"ritenuta\s*(?:d['\s]acconto)?(?:\s*del\s*\d+[\d.,]*\s*%)?\s*pari\s*a\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if not m_rit:
        m_rit = re.search(r"ritenuta\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_rit:
        ritenuta = pulisci_cifra(m_rit.group(1))

    # 2. Aliquota
    aliquota = 22.0
    m_aliq = re.search(r"\b(22|10|5|4|0)\s*%", testo)
    if m_aliq:
        aliquota = float(m_aliq.group(1))

    # 3. Imposta IVA
    imposta = 0.0
    m_iva = re.search(r"(?:maggiorato\s+dell['\s]IVA\s+pari\s+a|Totale\s+IVA|Imposte?)\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if not m_iva:
        m_iva = re.search(r"Imposta\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_iva:
        imposta = pulisci_cifra(m_iva.group(1))

    # 4. Imponibile
    imponibile = 0.0
    m_imp = re.search(r"(?:Totale\s*imponibile|Imponibile(?:\s*22%)?)\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_imp:
        imponibile = pulisci_cifra(m_imp.group(1))
    else:
        m_imp_notula = re.search(r"Totale\s*\n\s*(?:0,00\s+)?([\d.,]+)", testo, re.IGNORECASE)
        if m_imp_notula:
            imponibile = pulisci_cifra(m_imp_notula.group(1))

    # 5. Totale Netto a Pagare
    totale = 0.0
    m_tot = re.search(r"(?:totale\s*netto\s*di|Tot\.?\s*documento|Totale\s*documento|Totale\s*fattura)\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_tot:
        totale = pulisci_cifra(m_tot.group(1))
    else:
        m_scad_tot = re.search(r"(?:SCADENZE|Scadenze?)[^0-9\n]*\d{2}[/\-.]\d{2}[/\-.]\d{4}[^0-9\n]*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
        if m_scad_tot:
            totale = pulisci_cifra(m_scad_tot.group(1))

    # Quadratura vincolante
    if imponibile > 0 and imposta > 0 and totale == 0.0:
        totale = round(imponibile + imposta - ritenuta, 2)
    elif totale > 0 and imposta > 0 and imponibile == 0.0:
        imponibile = round(totale - imposta + ritenuta, 2)
    elif imponibile > 0 and totale > 0 and imposta == 0.0:
        imposta = round(totale - imponibile + ritenuta, 2)
    elif totale > 0 and imponibile == 0.0 and imposta == 0.0:
        imponibile = round(totale / (1.0 + (aliquota / 100.0)), 2)
        imposta = round(totale - imponibile, 2)

    if imponibile > 0 and aliquota > 0:
        iva_calc = round((imponibile * aliquota) / 100.0, 2)
        if imposta == 0.0 or abs(imposta - iva_calc) <= 0.05:
            imposta = iva_calc
            totale = round(imponibile + imposta - ritenuta, 2)

    return imponibile, aliquota, imposta, ritenuta, totale

def parser_locale_universale(testo):
    """Estrazione anagrafica consolidata e bloccata."""
    righe = [r.strip() for r in testo.split("\n") if r.strip()]

    idx_dest = -1
    for i, r in enumerate(righe):
        if re.search(r"^(?:destinatario|spett\.?le)\b", r, re.IGNORECASE):
            idx_dest = i
            break

    ced_nome, ced_piva, ced_cf = "", "", ""
    cess_nome, cess_piva, cess_cf = "", "", ""
    ced_via, ced_cap, ced_com, ced_prov = "Via Sede 1", "00100", "Roma", "RM"
    cess_via, cess_cap, cess_com, cess_prov = "Via Cliente 10", "00100", "Roma", "RM"

    if idx_dest != -1:
        blocco_dest = "\n".join(righe[idx_dest: idx_dest + 10])
        blocco_ced = "\n".join(righe[:idx_dest] + righe[idx_dest + 10:])

        if len(righe) > idx_dest + 1:
            riga_d1 = righe[idx_dest + 1]
            cess_nome = riga_d1 if len(riga_d1) > 4 else (righe[idx_dest + 2] if len(righe) > idx_dest + 2 else "CLIENTE")

        cess_via, cess_cap, cess_com, cess_prov = estrai_indirizzo_cap_comune(blocco_dest)
        m_cp = re.findall(r"\b(\d{11})\b", blocco_dest)
        cess_piva = m_cp[0] if m_cp else ""
        m_ccf = re.findall(r"\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]{3}[A-Z])\b", blocco_dest.upper())
        cess_cf = m_ccf[0] if m_ccf else (cess_piva if len(cess_piva) == 11 else "")

        ced_nome = righe[0]
        if "casazen" in ced_nome.lower() and len(righe) > 1 and "s.r.l" in righe[1].lower():
            ced_nome = "CASAZEN S.R.L."
        ced_via, ced_cap, ced_com, ced_prov = estrai_indirizzo_cap_comune(blocco_ced)
        m_ced_p = re.findall(r"\b(\d{11})\b", blocco_ced)
        ced_piva = m_ced_p[0] if m_ced_p else ""
        m_ced_cf = re.findall(r"\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]{3}[A-Z])\b", blocco_ced.upper())
        ced_cf = m_ced_cf[0] if m_ced_cf else ""
    else:
        pivas = re.findall(r"\b(\d{11})\b", testo)
        ced_piva = pivas[0] if len(pivas) > 0 else ""
        cess_piva = pivas[1] if len(pivas) > 1 else ""
        ced_nome = righe[0] if righe else "FORNITORE"
        cess_nome = "CLIENTE STUDIO"

    ced_nome = re.sub(r"(?:P\.?IVA|C\.?F\.?|Tel\.|e-mail).*$", "", ced_nome, flags=re.IGNORECASE).strip()
    cess_nome = re.sub(r"(?:P\.?IVA|C\.?F\.?|Tel\.|e-mail).*$", "", cess_nome, flags=re.IGNORECASE).strip()

    # Numero e Data
    num_doc = "1"
    data_doc = datetime.today().strftime("%Y-%m-%d")
    m_nd = re.search(r"(?:fattura\s+proforma\s+n\.?|fattura\s+nr\.?|fattura\s+n\.?|nr\.?)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)\s*(?:del)?\s*([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])", testo, re.IGNORECASE)
    if m_nd:
        num_doc = m_nd.group(1).strip()
        d_p = m_nd.group(2).replace("/", "-").replace(".", "-").split("-")
        data_doc = d_p[2] + "-" + d_p[1].zfill(2) + "-" + d_p[0].zfill(2)
    else:
        m_d = re.search(r"\b([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])\b", testo)
        if m_d:
            d_p = m_d.group(1).replace("/", "-").replace(".", "-").split("-")
            data_doc = d_p[2] + "-" + d_p[1].zfill(2) + "-" + d_p[0].zfill(2)

    # Sezione contabile ad alta precisione
    imponibile, aliquota, imposta, ritenuta, totale = risolvi_sezione_contabile(testo)

    # Dati CONSPAY
    metodo_pag = "MP05"
    if re.search(r"carta\s+di\s+pagamento|pos|credito", testo, re.IGNORECASE):
        metodo_pag = "MP08"
    elif re.search(r"riba", testo, re.IGNORECASE):
        metodo_pag = "MP12"
    elif re.search(r"contanti", testo, re.IGNORECASE):
        metodo_pag = "MP01"

    m_iban = re.search(r"\b(IT\d{2}[A-Z]\d{10}[0-9A-Z]{12})\b", testo.replace(" ", "").upper())
    iban_doc = m_iban.group(1) if m_iban else ""

    data_scad = data_doc
    m_sc = re.search(r"(?:Scadenze?|SCADENZE)\s*[:.\s]?\s*([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])", testo, re.IGNORECASE)
    if m_sc:
        dp = m_sc.group(1).replace("/", "-").replace(".", "-").split("-")
        data_scad = dp[2] + "-" + dp[1].zfill(2) + "-" + dp[0].zfill(2)

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
        "modalita_pagamento": metodo_pag
    }

def estrai_con_gemini_sicuro(file_bytes, filename, api_key, testo):
    """Cascata modelli Gemini con guida contabile."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        prompt = (
            "Sei un contabile esperto di fatturazione FPR12 e TeamSystem CONSPAY. "
            "Estrai con assoluta esattezza i dati di questa fattura. "
            "Distingui CEDENTE (chi emette) da CESSIONARIO (chi riceve nel box Spett.le/Destinatario). "
            "SEZIONE CONTABILE:\n"
            "- imponibile: importo netto imponibile (es. 162.29, 702.00, 2620.00).\n"
            "- aliquota_prevalente: aliquota IVA (es. 22).\n"
            "- imposta: IVA calcolata (es. 35.71, 154.44, 576.40).\n"
            "- ritenuta: eventuale ritenuta d'acconto (es. 20% = 140.40). Se assente metti 0.0.\n"
            "- totale_documento: TOTALE NETTO A PAGARE (Imponibile + IVA - Ritenuta es. 198.00, 716.04, 3196.40).\n"
            "- modalita_pagamento: MP05 se bonifico, MP08 se carta/pos.\n\n"
            "Rispondi ESCLUSIVAMENTE con un JSON con questi campi:\n"
            "cedente_denominazione, cedente_paese, cedente_piva, cedente_cf, cedente_indirizzo, cedente_cap, cedente_comune, cedente_provincia, "
            "cessionario_denominazione, cessionario_paese, cessionario_piva, cessionario_cf, cessionario_indirizzo, cessionario_cap, cessionario_comune, cessionario_provincia, "
            "numero_documento, data_documento, tipo_documento, imponibile, aliquota_prevalente, imposta, ritenuta, totale_documento, natura, iban, data_scadenza, modalita_pagamento.\n\n"
            "Testo del documento:\n" + str(testo)[:6000]
        )

        modelli = ["gemini-3.8-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-2.0-flash", "gemini-pro"]
        ultimo_err = None

        for m_name in modelli:
            try:
                model = genai.GenerativeModel(m_name)
                res = model.generate_content(prompt, request_options={"timeout": 14.0})
                clean_json = res.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_json)

                data["imponibile"] = pulisci_cifra(data.get("imponibile", 0.0))
                data["imposta"] = pulisci_cifra(data.get("imposta", 0.0))
                data["ritenuta"] = pulisci_cifra(data.get("ritenuta", 0.0))
                data["totale_documento"] = pulisci_cifra(data.get("totale_documento", 0.0))
                data["aliquota_prevalente"] = float(data.get("aliquota_prevalente", 22.0))
                data["cedente_piva"] = re.sub(r"[^0-9]", "", str(data.get("cedente_piva", "")))
                data["cessionario_piva"] = re.sub(r"[^0-9]", "", str(data.get("cessionario_piva", "")))

                calc_tot = round(data["imponibile"] + data["imposta"] - data["ritenuta"], 2)
                if data["totale_documento"] == 0.0 or abs(calc_tot - data["totale_documento"]) <= 0.05:
                    data["totale_documento"] = calc_tot

                return data, None, m_name
            except Exception as e:
                ultimo_err = str(e)
                continue

        return None, ultimo_err, None
    except Exception as e:
        return None, str(e), None

def estrai_dati_fattura(file_input, filename="fattura.pdf", api_key=None):
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
        dati_ai, err_ai, mod_name = estrai_con_gemini_sicuro(file_bytes, filename, str(api_key).strip(), testo_completo)
        if dati_ai:
            return dati_ai, "Gemini AI (" + str(mod_name) + ")", testo_completo, None
        else:
            dati_loc = parser_locale_universale(testo_completo)
            return dati_loc, "Parser Locale Universale", testo_completo, "Gemini: " + str(err_ai)

    dati_locale = parser_locale_universale(testo_completo)
    return dati_locale, "Parser Locale Universale (PyMuPDF)", testo_completo, None
