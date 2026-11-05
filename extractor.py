# extractor.py - Motore Ibrido di Estrazione Fiscale
import re
import fitz  # PyMuPDF
import json
from datetime import datetime
import streamlit as st

def parse_importo(val_str: str) -> float:
    """Converte stringhe numeriche contabili (es. 1.250,50 o 1250.50) in float."""
    if not val_str:
        return 0.0
    val_str = str(val_str).strip().replace("€", "").replace(" ", "")
    # Se presente virgola come decimale
    if "," in val_str and "." in val_str:
        if val_str.rfind(",") > val_str.rfind("."):
            val_str = val_str.replace(".", "").replace(",", ".")
        else:
            val_str = val_str.replace(",", "")
    elif "," in val_str:
        val_str = val_str.replace(",", ".")
    try:
        return round(float(val_str), 2)
    except ValueError:
        return 0.0

def trova_tripletta_matematica(numeri: list) -> tuple:
    """
    Individua tra tutti i numeri estratti la tripletta (A=Imponibile, B=IVA, C=Totale)
    tale che |(A + B) - C| <= 0.02 e B/A corrisponde a un'aliquota italiana reale (4, 5, 10, 22%).
    """
    numeri_validi = sorted(list(set(n for n in numeri if 0.01 <= n < 1_000_000.0)), reverse=True)
    aliquote_valide = [4.0, 5.0, 10.0, 22.0]

    for c in numeri_validi:  # C = Totale (valore più alto)
        for a in numeri_validi:  # A = Imponibile
            if a >= c:
                continue
            b = round(c - a, 2)  # B = IVA teorica
            if b <= 0:
                continue
            
            # Verifica se B/A corrisponde a un'aliquota reale
            perc = round((b / a) * 100.0, 1)
            for aliq in aliquote_valide:
                if abs(perc - aliq) <= 0.5:
                    return a, b, c, aliq

    return None, None, None, 22.0

def estrai_con_pymupdf(file_bytes: bytes) -> dict:
    """Esegue il parsing vettoriale ad alta velocità del PDF tramite PyMuPDF."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    testo_completo = ""
    for page in doc:
        testo_completo += page.get_text("text") + "\n"

    if len(testo_completo.strip()) < 50:
        return None  # Documento scansionato, necessita fallback AI

    # 1. Ricerca Partite IVA (11 cifre) con esclusione da numeri contabili
    piva_matches = re.findall(r"\b([0-9]{11})\b", testo_completo)
    piva_uniche = list(dict.fromkeys(piva_matches))
    cedente_piva = piva_uniche[0] if len(piva_uniche) > 0 else ""
    cessionario_piva = piva_uniche[1] if len(piva_uniche) > 1 else ""

    # 2. Ricerca Data
    date_patterns = [
        r"\b([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])\b",
        r"\b((?:20)[2-3][0-9][/\-.][0-1]?[0-9][/\-.][0-3]?[0-9])\b"
    ]
    data_doc = datetime.today().strftime("%Y-%m-%d")
    for pat in date_patterns:
        m = re.search(pat, testo_completo)
        if m:
            d_raw = m.group(1).replace("/", "-").replace(".", "-")
            parti = d_raw.split("-")
            if len(parti[0]) == 4:
                data_doc = f"{parti[0]}-{parti[1].zfill(2)}-{parti[2].zfill(2)}"
            else:
                anno = parti[2] if len(parti[2]) == 4 else f"20{parti[2]}"
                data_doc = f"{anno}-{parti[1].zfill(2)}-{parti[0].zfill(2)}"
            break

    # 3. Ricerca Numero Documento
    num_match = re.search(r"(?:fattura|fatt\.|doc\.|documento|n°|num\.)\s*(?:n\.?|numero)?\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)", testo_completo, re.IGNORECASE)
    numero_doc = num_match.group(1).strip() if num_match else "1"

    # 4. Estrazione Token Numerici escludendo P.IVA (11 cifre) e Anni (4 cifre)
    tokens = re.findall(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b", testo_completo)
    numeri_candidati = []
    for t in tokens:
        val = parse_importo(t)
        # Filtro falsi positivi: escludi anni e interi puri mascherati
        if val not in [2022.0, 2023.0, 2024.0, 2025.0, 2026.0]:
            numeri_candidati.append(val)

    # 5. Risoluzione Tripletta Matematica (A + B = C)
    imponibile, imposta, totale, aliquota = trova_tripletta_matematica(numeri_candidati)

    if totale is None:
        if numeri_candidati:
            totale = max(numeri_candidati)
            imponibile = round(totale / 1.22, 2)
            imposta = round(totale - imponibile, 2)
            aliquota = 22.0
        else:
            imponibile, imposta, totale, aliquota = 0.0, 0.0, 0.0, 22.0

    # Ricerca denominazioni elementari
    righe = [r.strip() for r in testo_completo.split("\n") if len(r.strip()) > 3]
    denominazione_cedente = righe[0] if righe else "FORNITORE"

    return {
        "tipo_documento": "TD01",
        "numero_documento": numero_doc,
        "data_documento": data_doc,
        "cedente_denominazione": denominazione_cedente[:80],
        "cedente_piva": cedente_piva,
        "cessionario_denominazione": "CLIENTE STUDIO",
        "cessionario_piva": cessionario_piva,
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

def fallback_gemini(file_bytes: bytes) -> dict:
    """Fallback con Gemini AI per scansioni raster o immagini pure."""
    try:
        import google.generativeai as genai
        api_key = st.secrets.get("GEMINI_API_KEY", None)
        if not api_key:
            return None

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        prompt = """
        Estrai i dati contabili di questa fattura in formato JSON puro conforme a questa struttura:
        {
          "tipo_documento": "TD01",
          "numero_documento": "123",
          "data_documento": "YYYY-MM-DD",
          "cedente_denominazione": "",
          "cedente_piva": "",
          "cessionario_denominazione": "",
          "cessionario_piva": "",
          "totale_documento": 0.0,
          "riepilogo_iva": [{"aliquota": 22.0, "imponibile": 0.0, "imposta": 0.0, "natura": ""}]
        }
        Rispondi ESCLUSIVAMENTE con il blocco JSON valido.
        """
        response = model.generate_content(
            [prompt, {"mime_type": "application/pdf", "data": file_bytes}],
            request_options={"timeout": 8.0}
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception:
        return None

def estrai_dati_fattura(file_input, filename="fattura.pdf") -> dict:
    """
    Funzione d'ingresso: riceve bytes, oggetti UploadedFile o percorsi file
    ed esegue la pipeline ibrida con fail-safe garantito.
    """
    # No
