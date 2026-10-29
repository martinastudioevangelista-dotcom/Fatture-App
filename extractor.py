import fitz  # PyMuPDF
from PIL import Image
import io
import json
import streamlit as st
import google.generativeai as genai

# Configura la chiave di Google Gemini
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def ottieni_modello_disponibile():
    # Chiede a Google quali modelli sono attivi sul tuo account
    try:
        modelli = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # Cerca prioritariamente flash o pro
        for nome in modelli:
            if 'flash' in nome:
                return genai.GenerativeModel(nome)
        for nome in modelli:
            if 'pro' in nome:
                return genai.GenerativeModel(nome)
        if modelli:
            return genai.GenerativeModel(modelli[0])
    except Exception:
        pass
    return genai.GenerativeModel('gemini-1.5-flash')

def pdf_to_image(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=150)
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))
    return image

def estrai_dati_fattura(pdf_bytes):
    image = pdf_to_image(pdf_bytes)
    model = ottieni_modello_disponibile()
    
    prompt = """
    Sei un esperto contabile italiano. Analizza l'immagine di questa fattura ed estrai i dati in formato JSON.
    Devi riconoscere in modo intelligente i campi anche se usano sinonimi (es. P.IVA, Partita IVA, VAT).
    
    Restituisci SOLO ED ESCLUSIVAMENTE codice JSON valido. Struttura richiesta esatta:
    {
      "fornitore": {"ragione_sociale": "", "partita_iva": "", "codice_fiscale": "", "indirizzo": "", "cap": "", "comune": "", "provincia": ""},
      "cliente": {"ragione_sociale": "", "partita_iva": "", "codice_fiscale": "", "indirizzo": "", "cap": "", "comune": "", "provincia": ""},
      "documento": {"numero": "", "data": "YYYY-MM-DD"},
      "riepilogo_iva": [
        {"imponibile": 0.0, "aliquota_iva": 0.0, "imposta": 0.0}
      ],
      "totale_documento": 0.0
    }
    Se un dato non è presente, lascia stringa vuota o 0.0. I numeri devono usare il punto per i decimali.
    """

    response = model.generate_content([prompt, image])
    
    testo_risposta = response.text
    if testo_risposta.startswith("```json"):
        testo_risposta = testo_risposta.replace("```json\n", "").replace("\n```", "")
    elif testo_risposta.startswith("```"):
        testo_risposta = testo_risposta.replace("```\n", "").replace("\n```", "")
        
    return json.loads(testo_risposta)
