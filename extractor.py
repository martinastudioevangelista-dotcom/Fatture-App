# extractor.py - Motore Ibrido di Estrazione Fiscale
import re
import json
import fitz  # PyMuPDF
from datetime import datetime

def pulisci_cifra(s) -> float:
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

def estrai_con_gemini(file_bytes: bytes, filename: str, api_key: str, testo_estratto: str) -> dict:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )

        prompt = (
            "Sei un sistema esperto di contabilita italiana e fatturazione elettronica (FatturaPA 1.2.2). "
            "Estrai con precisione assoluta i dati della fattura per TeamSystem CONSPAY. "
            "Distingui tassativamente CEDENTE (fornitore che emette) da CESSIONARIO (cliente che riceve). "
            "Estrai IBAN fornitore, Scadenza, Imponibile, IVA e Totale. "
            "Restituisci ESCLUSIVAMENTE un JSON con questi campi: "
            '{"cedente_denominazione": "", "cedente_piva": "", "cedente_indirizzo": "", '
            '"cedente_cap": "", "cedente_comune": "", "cedente_provincia": "RM", '
            '"cessionario_denominazione": "", "cessionario_piva": "", "cessionario_cf": "", '
            '"cessionario_indirizzo": "", "cessionario_cap": "", "cessionario_comune": "", "cessionario_provincia": "RM", '
            '"numero_documento": "", "data_documento": "YYYY-MM-DD", "tipo_documento": "TD01", '
            '"imponibile": 0.0, "aliquota_prevalente": 22.0, "imposta": 0.0, "totale_documento": 0.0, '
            '"iban": "", "data_scadenza": "YYYY-MM-DD", "modalita_pagamento": "MP05"}'
        )

        mime = "application/pdf" if str(filename).lower().endswith(".pdf") else "image/jpeg"
        if len(testo_estratto.strip()) > 120:
            payload = [prompt, "Testo del documento:\n" + testo_estratto[:5000]]
        else:
            payload = [prompt, {"mime_type": mime, "data": file_bytes}]

        response = model.generate_content(payload, request_options={"timeout": 12.0})
        res_json = json.loads(response.text)

        res_json["imponibile"] = pulisci_cifra(res_json.get("imponibile", 0.0))
        res_json["imposta"] = pulisci_cifra(res_json.get("imposta", 0.0))
        res_json["totale_documento"] = pulisci_cifra(res_json.get("totale_documento", 0.0))
        res_json["aliquota_prevalente"] = float(res_json.get("aliquota_prevalente", 22.0))
        res_json["cedente_piva"] = re.sub(r"[^0-9]", "", str(res_json.get("cedente_piva", "")))
        res_json["cessionario_piva"] = re.sub(r"[^0-9]", "", str(res_json.get("cessionario_piva", "")))
        res_json["iban"] = str(res_json.get("iban", "")).replace(" ", "").upper()
        return res_json
    except Exception:
        return None

def estrai_spaziale_locale(file_bytes: bytes):
    testo_completo = ""
    blocco_sx = []
    blocco_dx = []
    doc = None
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for i in range(min(len(doc), 2)):
            page = doc[i]
            meta_largh = page.rect.width / 2.0
            blocks = page.get_text("blocks")
            for b in blocks:
                if b[6] == 0:
                    t = b[4].strip()
                    testo_completo += t + "\n"
                    if b[0] < meta_largh:
                        blocco_sx.append(t)
                    else:
                        blocco_dx.append(t)
    except Exception:
        pass
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
    return testo_completo, "\n".join(blocco_sx), "\n".join(blocco_dx)

def parser_locale_euristico(testo_totale: str, testo_sx: str, testo_dx: str) -> dict:
    pivas_sx = re.findall(r"\b\d{11}\b", testo_sx)
    pivas_dx = re.findall(r"\b\d{11}\b", testo_dx)
    pivas_all = re.findall(r"\b\d{11}\b", testo_totale)

    ced_piva = pivas_sx[0] if pivas_sx else (pivas_all[0] if pivas_all else "")
    cess_piva = pivas_dx[0] if pivas_dx else (pivas_all[1] if len(pivas_all) > 1 else "")

    cfs = re.findall(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]{3}[A-Z]\b", testo_dx.upper())
    cess_cf = cfs[0] if cfs else ""

    righe_sx = [r.strip() for r in testo_sx.split("\n") if len(r.strip()) > 3]
    righe_dx = [r.strip() for r in testo_dx.split("\n") if len(r.strip()) > 3]
    ced_nome = righe_sx[0] if righe_sx else "FORNITORE"
    cess_nome = righe_dx[0] if righe_dx else "CLIENTE STUDIO"

    data_doc = datetime.today().strftime("%Y-%m-%d")
    m_data = re.search(r"\b([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])\b", testo_totale)
    if m_data:
        parti = m_data.group(1).replace("/", "-").replace(".", "-").split("-")
        if len(parti[0]) == 4:
            data_doc = f"{parti[0]}-{parti[1].zfill(2)}-{parti[2].zfill(2)}"
        else:
            anno = parti[2] if len(parti[2]) == 4 else f"20{parti[2]}"
            data_doc = f"{anno}-{parti[1].zfill(2)}-{parti[0].zfill(2)}"

    m_num = re.search(r"(?:fattura|doc|num|n°|n\.)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)", testo_totale, re.IGNORECASE)
    numero_doc = m_num.group(1).strip() if m_num else "1"

    m_iban = re.search(r"\b(IT\d{2}[A-Z]\d{10}[0-9A-Z]{12})\b", testo_totale.replace(" ", "").upper())
    iban_doc = m_iban.group(1) if m_iban else ""

    tokens = re.findall(r"\b\d+[\.,]\d{2}\b", testo_totale)
    numeri = [pulisci_cifra(t) for t in tokens if pulisci_cifra(t) > 0.0]
    candidati = sorted(list(set(n for n in numeri if 0.50 <= n < 200000.0)), reverse=True)[:25]

    imponibile = 0.0
    imposta = 0.0
    totale = 0.0
    aliquota = 22.0

    for c in candidati:
        for a in candidati:
            if a >= c:
                continue
            b = round(c - a, 2)
            if b <= 0.05:
                continue
            ratio = round((b / a) * 100.0, 1)
            for aliq in [22.0, 10.0, 5.0, 4.0]:
                if abs(ratio - aliq) <= 0.5:
                    imponibile, imposta, totale, aliquota = a, b, c, aliq
                    break
            if totale > 0:
                break
        if totale > 0:
            break

    if totale == 0.0 and candidati:
        totale = max(candidati)
        imponibile = round(totale / 1.22, 2)
        imposta = round(totale - imponibile, 2)

    return {
        "tipo_documento": "TD01",
        "numero_documento": numero_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_piva": ced_piva,
        "cedente_indirizzo": "Via Sede 1",
        "cedente_cap": "00100",
        "cedente_comune": "Roma",
        "cedente_provincia": "RM",
        "cessionario_denominazione": cess_nome,
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf,
        "cessionario_indirizzo": "Via Studio 10",
        "cessionario_cap": "00100",
        "cessionario_comune": "Roma",
        "cessionario_provincia": "RM",
        "iban": iban_doc,
        "data_scadenza": data_doc,
        "modalita_pagamento": "MP05",
        "imponibile": imponibile,
        "imposta": imposta,
        "totale_documento": totale,
        "aliquota_prevalente": aliquota
    }

def estrai_dati_fattura(file_input, filename="fattura.pdf", api_key: str = None):
    if hasattr(file_input, "read"):
        file_input.seek(0)
        file_bytes = file_input.read()
    elif isinstance(file_input, bytes):
        file_bytes = file_input
    else:
        with open(file_input, "rb") as f:
            file_bytes = f.read()

    testo_tot, testo_sx, testo_dx = estrai_spaziale_locale(file_bytes)

    if api_key and len(api_key.strip()) > 10:
        dati_ai = estrai_con_gemini(file_bytes, filename, api_key.strip(), testo_tot)
        if dati_ai:
            return dati_ai, "Gemini AI (Vision & Layout Multistruttura)", testo_tot

    dati_locale = parser_locale_euristico(testo_tot, testo_sx, testo_dx)
    return dati_locale, "Parser Locale Geometrico (PyMuPDF)", testo_tot
