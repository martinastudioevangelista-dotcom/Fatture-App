# extractor.py - Motore ultra-leggero e resiliente
import re
import fitz  # PyMuPDF
from datetime import datetime
import streamlit as st

def pulisci_numero(s: str) -> float:
    """Conversione sicura di stringhe contabili senza ReDoS."""
    try:
        s = s.strip().replace(" ", "").replace("€", "")
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        val = float(s)
        return round(val, 2)
    except Exception:
        return 0.0

def trova_tripletta_sicura(numeri: list) -> tuple:
    """Ricerca matematica istantanea (massimo 20 candidati, <0.001 sec)."""
    valori = sorted(list(set(n for n in numeri if 0.50 <= n < 200_000.0)), reverse=True)[:20]
    aliquote = [22.0, 10.0, 5.0, 4.0]

    for c in valori:  # Totale
        for a in valori:  # Imponibile
            if a >= c:
                continue
            b = round(c - a, 2)  # IVA
            if b <= 0:
                continue
            ratio = round((b / a) * 100.0, 1)
            for aliq in aliquote:
                if abs(ratio - aliq) <= 0.5:
                    return a, b, c, aliq

    return None, None, None, 22.0

def estrai_dati_fattura(file_input, filename="fattura.pdf") -> dict:
    """Funzione di estrazione garantita contro crash di memoria e timeout."""
    # 1. Lettura byte sicura
    if hasattr(file_input, "read"):
        file_input.seek(0)
        file_bytes = file_input.read()
    elif isinstance(file_input, bytes):
        file_bytes = file_input
    else:
        with open(file_input, "rb") as f:
            file_bytes = f.read()

    testo = ""
    # 2. PyMuPDF con chiusura esplicita della memoria
    doc = None
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        # Legge solo le prime 2 pagine per evitare consumi di RAM
        pagine_da_leggere = min(len(doc), 2)
        for i in range(pagine_da_leggere):
            testo += doc[i].get_text("text") + "\n"
    except Exception:
        testo = ""
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

    # 3. Parsing del testo (se presente)
    cedente_piva = ""
    data_doc = datetime.today().strftime("%Y-%m-%d")
    numero_doc = "1"
    imponibile, imposta, totale, aliquota = 0.0, 0.0, 0.0, 22.0

    if len(testo.strip()) > 30:
        # Partita IVA: sequenza lineare di 11 cifre
        pivas = re.findall(r"\b\d{11}\b", testo)
        if pivas:
            cedente_piva = pivas[0]

        # Data Documento: ricerca formato DD/MM/YYYY o YYYY-MM-DD
        date_match = re.search(r"\b([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])\b", testo)
        if date_match:
            d_str = date_match.group(1).replace("/", "-").replace(".", "-")
            p = d_str.split("-")
            if len(p[0]) == 4:
                data_doc = f"{p[0]}-{p[1].zfill(2)}-{p[2].zfill(2)}"
            else:
                anno = p[2] if len(p[2]) == 4 else f"20{p[2]}"
                data_doc = f"{anno}-{p[1].zfill(2)}-{p[0].zfill(2)}"

        # Numero Documento
        num_match = re.search(r"(?:fattura|doc|n°|num|n\.)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)", testo, re.IGNORECASE)
        if num_match:
            numero_doc = num_match.group(1).strip()

        # Numeri contabili: regex lineare e sicura (NO ReDoS)
        tokens = re.findall(r"\b\d+[\.,]\d{2}\b", testo)
        numeri_candidati = [pulisci_numero(t) for t in tokens if pulisci_numero(t) > 0.0]

        # Calcolo tripletta
        imp_calc, iva_calc, tot_calc, aliq_calc = trova_tripletta_sicura(numeri_candidati)
        if tot_calc is not None:
            imponibile, imposta, totale, aliquota = imp_calc, iva_calc, tot_calc, aliq_calc
        elif numeri_candidati:
            totale = max(numeri_candidati)
            imponibile = round(totale / 1.22, 2)
            imposta = round(totale - imponibile, 2)
            aliquota = 22.0

    # 4. Fallback leggero Gemini SOLO se il testo era completamente illeggibile (scansione)
    elif "GEMINI_API_KEY" in st.secrets and len(file_bytes) < 3 * 1024 * 1024:
        try:
            import google.generativeai as genai
            import json
            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            prompt = (
                "Estrai solo un JSON: "
                '{"numero": "", "data": "YYYY-MM-DD", "piva": "", "totale": 0.0, "imponibile": 0.0, "iva": 0.0}'
            )
            mime = "application/pdf" if str(filename).lower().endswith(".pdf") else "image/jpeg"
            res = model.generate_content(
                [prompt, {"mime_type": mime, "data": file_bytes}],
                request_options={"timeout": 5.0}
            )
            raw_json = res.text.replace("```json", "").replace("```", "").strip()
            data_ai = json.loads(raw_json)
            totale = float(data_ai.get("totale", 0.0))
            imponibile = float(data_ai.get("imponibile", 0.0))
            imposta = float(data_ai.get("iva", 0.0))
            cedente_piva = str(data_ai.get("piva", ""))
            numero_doc = str(data_ai.get("numero", "1"))
            data_doc = str(data_ai.get("data", data_doc))
        except Exception:
            pass  # Se l'AI fallisce o scade, passa subito al form senza bloccare

    # 5. Restituzione finale garantita (popola subito l'interfaccia Human-in-the-Loop)
    righe_testo = [r.strip() for r in testo.split("\n") if len(r.strip()) > 3]
    denominazione = righe_testo[0] if righe_testo else "FORNITORE"

    return {
        "tipo_documento": "TD01",
        "numero_documento": numero_doc,
        "data_documento": data_doc,
        "cedente_denominazione": denominazione[:80],
        "cedente_piva": cedente_piva,
        "cessionario_denominazione": "CLIENTE STUDIO",
        "cessionario_piva": "",
        "imponibile": imponibile,
        "imposta": imposta,
        "totale_documento": totale,
        "aliquota_prevalente": aliquota,
        "riepilogo_iva": [{
            "aliquota": aliquota,
            "imponibile": imponibile,
            "imposta": imposta,
            "natura": ""
        }]
    }

extract_data = estrai_dati_fattura
extract_invoice_data = estrai_dati_fattura
