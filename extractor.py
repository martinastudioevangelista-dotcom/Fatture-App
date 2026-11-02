import fitz  # PyMuPDF
from PIL import Image
import io
import json
import streamlit as st
import google.generativeai as genai

# Configura Google Gemini
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Modalità JSON nativa: costringe Google a rispondere all'istante senza fronzoli
generation_config = {
    "temperature": 0.1,
    "response_mime_type": "application/json",
}
model = genai.GenerativeModel('gemini-3.8-flash', generation_config=generation_config)

def estrai_dati_fattura(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(0)
    
    # ⚡ ACCELERAZIONE: se il PDF ha testo digitale, lo legge all'istante
    testo_digitale = page.get_text()
    
    prompt = """
    Sei un esperto contabile. Estrai i dati della fattura in formato JSON esatto.
    Riconosci sinonimi di fornitore, cliente, date e totali.
    Schema JSON:
    {
      "fornitore": {"ragione_sociale": "", "partita_iva": "", "codice_fiscale": "", "indirizzo": "", "cap": "", "comune": "", "provincia": ""},
      "cliente": {"ragione_sociale": "", "partita_iva": "", "codice_fiscale": "", "indirizzo": "", "cap": "", "comune": "", "provincia": ""},
      "documento": {"numero": "", "data": "YYYY-MM-DD"},
      "riepilogo_iva": [
        {"imponibile": 0.0, "aliquota_iva": 0.0, "imposta": 0.0}
      ],
      "totale_documento": 0.0
    }
    Se un dato manca, lascia stringa vuota o 0.0 per i numeri.
    """

    # Se c'è testo digitale usiamo la modalità testo ultra-rapida (1-2 secondi!)
    if len(testo_digitale.strip()) > 60:
        response = model.generate_content([prompt, f"Contenuto fattura:\n{testo_digitale}"])
    else:
        # Se è una scansione/fotocopia cartacea, usa la fotocamera a bassa risoluzione
        pix = page.get_pixmap(dpi=80)
        img_data = pix.tobytes("jpeg", jpg_quality=60)
        image = Image.open(io.BytesIO(img_data))
        response = model.generate_content([prompt, image])

    return json.loads(response.text)
