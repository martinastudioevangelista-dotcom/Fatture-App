import fitz  # PyMuPDF
from PIL import Image
import io
import json
import streamlit as st
import google.generativeai as genai

# Configura la chiave di Google Gemini
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Impostazioni ultra-veloci: temperatura bassa e output JSON diretto
generation_config = {
    "temperature": 0.1,
    "response_mime_type": "application/json",
}

model = genai.GenerativeModel(
    model_name='gemini-3.8-flash',
    generation_config=generation_config
)

def pdf_to_image(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(0)
    # DPI a 130 e formato JPEG: immagine 4 volte più leggera e veloce da spedire ai server
    pix = page.get_pixmap(dpi=130)
    img_data = pix.tobytes("jpeg")
    image = Image.open(io.BytesIO(img_data))
    return image

def estrai_dati_fattura(pdf_bytes):
    image = pdf_to_image(pdf_bytes)
    
    prompt = """
    Estrai i dati contabili da questa fattura italiana in formato JSON.
    Campi obbligatori:
    {
      "fornitore": {"ragione_sociale": "", "partita_iva": "", "codice_fiscale": "", "indirizzo": "", "cap": "", "comune": "", "provincia": ""},
      "cliente": {"ragione_sociale": "", "partita_iva": "", "codice_fiscale": "", "indirizzo": "", "cap": "", "comune": "", "provincia": ""},
      "documento": {"numero": "", "data": "YYYY-MM-DD"},
      "riepilogo_iva": [
        {"imponibile": 0.0, "aliquota_iva": 0.0, "imposta": 0.0}
      ],
      "totale_documento": 0.0
    }
    """

    response = model.generate_content([prompt, image])
    return json.loads(response.text)
