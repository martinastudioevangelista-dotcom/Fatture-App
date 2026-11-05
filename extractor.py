# extractor.py - Motore Ibrido di Estrazione Fiscale con Gemini Vision e Geometria PDF
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
    """Interroga Gemini 1.5 Flash forzando il formato JSON conforme a FatturaPA 1.2.2 e CONSPAY."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )

        prompt = """
        Sei un sistema esperto di contabilità italiana e fatturazione elettronica (FatturaPA 1.2.2 FPR12).
        Analizza questa fattura ed estrai con assoluta precisione i dati per l'importazione in TeamSystem CONSPAY.
        
        Regole tassative di distinzione:
        1. CEDENTE / PRESTATORE: è chi emette la fattura (il fornitore o venditore). Cerca la sua P.IVA, denominazione, indirizzo, CAP, comune e provincia (2 lettere).
        2. CESSIONARIO / COMMITTENTE: è chi riceve la fattura (il cliente, spesso preceduto da 'Spett.le', 'Destinatario', 'Fatturato a'). Estrai la sua P.IVA o Codice Fiscale.
        3. DATI PAGAMENTO CONSPAY: estrai l'IBAN del fornitore per il bonifico e la data di scadenza del pagamento.
        4. SEZIONE CONTABILE: estrai imponibile netto, aliquota IVA principale (22, 10, 5 o 4), imposta IVA e totale documento a pagare.

        Restituisci ESCLUSIVAMENTE un oggetto JSON con questa struttura esatta:
        {
          "cedente_denominazione": "string",
          "cedente_piva": "string (11 cifre)",
          "cedente_indirizzo": "string",
          "cedente_cap": "string (5 cifre)",
          "cedente_comune": "string",
          "cedente_provincia": "string (2 lettere maiuscole es. MI)",
          "cessionario_denominazione": "string",
          "cessionario_piva": "string (11 cifre o vuoto se privato)",
          "cessionario_cf": "string (16 caratteri o vuoto)",
          "cessionario_indirizzo": "string",
          "cessionario_cap": "string (5 cifre)",
          "cessionario_comune": "string",
          "cessionario_provincia": "string (2 lettere maiuscole)",
          "numero_documento": "string",
          "data_documento": "YYYY-MM-DD",
          "tipo_documento": "TD01",
          "imponibile": 0.0,
          "aliquota_prevalente": 22.0,
          "imposta": 0.0,
          "totale_documento": 0.0,
          "iban": "string (IT...)",
          "data_scadenza": "YYYY-MM-DD",
          "modalita_pagamento": "MP05"
        }
        """

        mime = "application/pdf" if str(filename).lower().endswith(".pdf") else "image/jpeg"
        # Se c'è testo estratto usiamo quello per massima velocità; se il testo è povero mandiamo il file binario
        if len(testo_estratto.strip()) > 150:
            contenuto = [prompt, f"Testo estratto dal documento:\n{testo_estratto[:6000]}"]
        else:
            contenuto = [prompt, {"mime_type": mime, "data": file_bytes}]

        response = model.generate_content(contenuto, request_options={"timeout": 12.0})
        res_json = json.loads(response.text)
        
        # Pulizia e normalizzazione importi
        res_json["im
