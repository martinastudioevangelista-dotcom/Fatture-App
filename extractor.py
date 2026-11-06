# extractor.py - Motore Fiscale con Gestione Fornitori Esteri (FR/UE) e Natura N3.2
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

def normalizza_piva_paese(piva_raw: str, default_paese="IT") -> tuple:
    """
    Riconosce P.IVA estere (es. FR20422518746, DE123456789) o italiane.
    Ritorna: (Paese a 2 lettere es. 'FR' o 'IT', Codice pulito es. '20422518746')
    """
    if not piva_raw:
        return default_paese, ""
    
    clean = re.sub(r"[^A-Za-z0-9]", "", str(piva_raw)).upper()
    # Verifica se inizia con 2 lettere del paese (es. FR, DE, ES, IT, NL)
    if len(clean) >= 4 and clean[:2].isalpha():
        return clean[:2], clean[2:]
    
    # Se numerica pura di 11 cifre è italiana
    if len(clean) == 11 and clean.isdigit():
        return "IT", clean
    
    return default_paese, clean

def estrai_spaziale_blocchi(file_bytes: bytes):
    """Estrae blocchi di testo preservando le coordinate grafiche."""
    testo_totale = ""
    blocchi_sinistra = []
    blocchi_destra = []
    doc = None
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for i in range(min(len(doc), 3)):
            page = doc[i]
            meta_larghezza = page.rect.width / 2.0
            for b in page.get_text("blocks"):
                if b[6] == 0:  # Blocco di testo
                    testo = b[4].strip()
                    testo_totale += testo + "\n"
                    if b[0] < meta_larghezza:
                        blocchi_sinistra.append(testo)
                    else:
                        blocchi_destra.append(testo)
    except Exception:
        pass
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
    return testo_totale, "\n".join(blocchi_sinistra), "\n".join(blocchi_destra)

def estrai_con_gemini_avanzato(file_bytes: bytes, filename: str, api_key: str, testo_estratto: str) -> dict:
    """Interroga Gemini con istruzioni rigorose su Fornitori Esteri UE, Natura N3.2 e CONSPAY."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )

        prompt = """
        Sei un revisore contabile esperto di fatturazione elettronica FPR12 per TeamSystem e CONSPAY.
        Analizza questa fattura facendo massima attenzione alla SEPARAZIONE RIGIDA DEI RUOLI:

        1. CEDENTE / PRESTATORE (Fornitore Emittente):
           - È l'azienda che emette la fattura (es. SGB Finance, CGI Finance o altre società emittenti).
           - Può avere Partita IVA estera (es. Francese: FR20422518746, FR84303236186, ecc.) e sede all'estero.
           - Estrai nazione di sede reale (es. FR, DE, IT). Se estera, la provincia deve essere vuota ("").

        2. CESSIONARIO / COMMITTENTE (Cliente Ricevente):
           - È lo studio o l'azienda italiana cliente che riceve e paga la fattura (destinatario).
           - Non invertire MAI fornitore e cliente.

        3. REGOLA FISCALE FORNITORI ESTERI (UE / Intra-comunitari):
           - Se il fornitore è comunitario (es. Francia FR) e non addebita IVA italiana, l'aliquota è 0.00, imposta 0.00 e natura 'N3.2' (operazioni intracomunitarie).

        4. DATI PAGAMENTO CONSPAY:
           - Estrai l'IBAN del fornitore su cui effettuare il bonifico e la data di scadenza.

        Restituisci ESCLUSIVAMENTE un JSON conforme a questa struttura:
        {
          "cedente_denominazione": "",
          "cedente_paese": "FR",
          "cedente_piva": "20422518746",
          "cedente_indirizzo": "",
          "cedente_cap": "",
          "cedente_comune": "",
          "cedente_nazione": "FR",
          "cedente_provincia": "",
          "cessionario_denominazione": "",
          "cessionario_paese": "IT",
          "cessionario_piva": "",
          "cessionario_cf": "",
          "cessionario_indirizzo": "",
          "cessionario_cap": "",
          "cessionario_comune": "",
          "cessionario_nazione": "IT",
          "cessionario_provincia": "RM",
          "numero_documento": "1",
          "data_documento": "YYYY-MM-DD",
          "tipo_documento": "TD01",
          "imponibile": 0.0,
          "aliquota_prevalente": 0.0,
          "imposta": 0.0,
          "natura": "N3.2",
          "totale_documento": 0.0,
          "iban": "",
          "data_scadenza": "YYYY-MM-DD",
          "modalita_pagamento": "MP05"
        }
        """

        mime = "application/pdf" if str(filename).lower().endswith(".pdf") else "image/jpeg"
        if len(testo_estratto.strip()) > 100:
            payload = [prompt, f"Contenuto testuale della fattura:\n{testo_estratto[:6500]}"]
        else:
            payload = [prompt, {"mime_type": mime, "data": file_bytes}]

        response = model.generate_content(payload, request_options={"timeout": 14.0})
        res = json.loads(response.text)

        # Normalizzazioni P.IVA
        ced_paese, ced_cod = normalizza_piva_paese(res.get("cedente_piva", ""), res.get("cedente_paese", "IT"))
        res["cedente_paese"] = ced_paese
        res["cedente_piva"] = ced_cod
        res["cedente_nazione"] = ced_paese
        if ced_paese != "IT":
            res["cedente_provincia"] = ""  # L'Agenzia Entrate scarta se c'è provincia estera

        cess_paese, cess_cod = normalizza_piva_paese(res.get("cessionario_piva", ""), res.get("cessionario_paese", "IT"))
        res["cessionario_paese"] = cess_paese
        res["cessionario_piva"] = cess_cod

        # Regola automatica Intra-UE N3.2
        res["imponibile"] = pulisci_cifra(res.get("imponibile", 0.0))
        res["totale_documento"] = pulisci_cifra(res.get("totale_documento", 0.0))
        if res["cedente_nazione"] != "IT" and res.get("imposta", 0.0) == 0.0:
            res["aliquota_prevalente"] = 0.0
            res["imposta"] = 0.0
            res["natura"] = "N3.2"
        else:
            res["imposta"] = pulisci_cifra(res.get("imposta", 0.0))
            res["aliquota_prevalente"] = float(res.get("aliquota_prevalente", 22.0))
            res["natura"] = str(res.get("natura", ""))

        res["iban"] = str(res.get("iban", "")).replace(" ", "").upper()
        return res
    except Exception:
        return None

def parser_euristico_multinazionale(testo_totale: str, testo_sx: str, testo_dx: str) -> dict:
    """Parser locale a regole per fatture italiane ed estere comunitarie."""
    # Ricerca P.IVA estere (es. FR..., DE...) o italiane (11 cifre)
    pivas_estere = re.findall(r"\b([A-Z]{2}[0-9A-Z]{8,12})\b", testo_totale)
    pivas_ita = re.findall(r"\b(\d{11})\b", testo_totale)

    ced_paese, ced_piva, ced_nome = "IT", "", "FORNITORE"
    cess_paese, cess_piva, cess_nome = "IT", "", "CLIENTE STUDIO"
    cess_cf = ""

    # Se troviamo una P.IVA comunitaria con prefisso diverso da IT, è tipicamente il fornitore estero
    piva_estera_fornitore = [p for p in pivas_estere if not p.startswith("IT")]
    if piva_estera_fornitore:
        ced_paese, ced_piva = normalizza_piva_paese(piva_estera_fornitore[0])
        # Il cliente è la P.IVA italiana
        if pivas_ita:
            cess_piva = pivas_ita[0]
    else:
        # Entrambi italiani
        if len(pivas_ita) >= 2:
            ced_piva = pivas_ita[0]
            cess_piva = pivas_ita[1]
        elif len(pivas_ita) == 1:
            ced_piva = pivas_ita[0]

    # Codice Fiscale Cliente privato
    cfs = re.findall(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", testo_totale.upper())
    if cfs and not cess_piva:
        cess_cf = cfs[0]

    # Ricerca Denominazioni per coordinate
    righe_sx = [r.strip() for r in testo_sx.split("\n") if len(r.strip()) > 3]
    righe_dx = [r.strip() for r in testo_dx.split("\n") if len(r.strip()) > 3]
    if righe_sx:
        ced_nome = righe_sx[0]
    if righe_dx:
        cess_nome = righe_dx[0]

    # Estremi fattura
    m_data = re.search(r"\b([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])\b", testo_totale)
    data_doc = datetime.today().strftime("%Y-%m-%d")
    if m_data:
        p = m_data.group(1).replace("/", "-").replace(".", "-").split("-")
        anno = p[2] if len(p[2]) == 4 else f"20{p[2]}" if len(p[0]) != 4 else p[0]
        mese = p[1].zfill(2)
        giorno = p[0].zfill(2) if len(p[0]) != 4 else p[2].zfill(2)
        data_doc = f"{anno}-{mese}-{giorno}"

    m_num = re.search(r"(?:fattura|invoice|doc|num|n°|n\.)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)", testo_totale, re.IGNORECASE)
    numero_doc = m_num.group(1).strip() if m_num else "1"

    # IBAN
    m_iban = re.search(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b", testo_totale.replace(" ", "").upper())
    iban_doc = m_iban.group(1) if m_iban else ""

    # Importi
    tokens = re.findall(r"\b\d+[\.,]\d{2}\b", testo_totale)
    numeri = [pulisci_cifra(t) for t in tokens if pulisci_cifra(t) > 0.0]
    candidati = sorted(list(set(numeri)), reverse=True)[:25]

    totale = max(candidati) if candidati else 0.0
    # Se fornitore estero, l'aliquota standard di default è 0% con N3.2
    if ced_paese != "IT":
        imponibile = totale
        imposta = 0.0
        aliquota = 0.0
        natura = "N3.2"
    else:
        imponibile = round(totale / 1.22, 2)
        imposta = round(totale - imponibile, 2)
        aliquota = 22.0
        natura = ""

    return {
        "tipo_documento": "TD01",
        "numero_documento": numero_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_paese": ced_paese,
        "cedente_piva": ced_piva,
        "cedente_indirizzo": "Via Fornitore 1",
        "cedente_cap": "75001" if ced_paese == "FR" else "00100",
        "cedente_comune": "Parigi" if ced_paese == "FR" else "Roma",
        "cedente_nazione": ced_paese,
        "cedente_provincia": "" if ced_paese != "IT" else "RM",
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": "IT",
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf,
        "cessionario_indirizzo": "Via Studio 10",
        "cessionario_cap": "00100",
        "cessionario_comune": "Roma",
        "cessionario_nazione": "IT",
        "cessionario_provincia": "RM",
        "iban": iban_doc,
        "data_scadenza": data_doc,
        "modalita_pagamento": "MP05",
        "imponibile": imponibile,
        "imposta": imposta,
        "totale_documento": totale,
        "aliquota_prevalente": aliquota,
        "natura": natura
    }

def estrai_dati_fattura(file_input, filename="fattura.pdf", api_key: str = None):
    """Pipeline integrata con gestione sicura dei byte e fallback garantito."""
    if hasattr(file_input, "read"):
        file_input.seek(0)
        file_bytes = file_input.read()
    elif isinstance(file_input, bytes):
        file_bytes = file_input
    else:
        with open(file_input, "rb") as f:
            file_bytes = f.read()

    testo_tot, testo_sx, testo_dx = estrai_spaziale_blocchi(file_bytes)

    if api_key and len(api_key.strip()) > 10:
        dati_ai = estrai_con_gemini_avanzato(file_bytes, filename, api_key.strip(), testo_tot)
        if dati_ai:
            return dati_ai, "Gemini AI (Vision & Riconoscimento Fornitori UE)", testo_tot

    dati_locale = parser_euristico_multinazionale(testo_tot, testo_sx, testo_dx)
    return dati_locale, "Parser Geometrico Locale", testo_tot
