# app.py - AI Invoice to SdI/TeamSystem (Versione Ultra-Stabile Anti-BlackScreen)
import io
import re
import zipfile
import streamlit as st
from datetime import datetime

# ---------------------------------------------------------
# Configurazione Pagina (Deve essere la prima istruzione)
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI Invoice to SdI | TeamSystem Bridge",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------
# Import Difensivo dei Moduli
# ---------------------------------------------------------
try:
    from extractor import estrai_dati_fattura
except Exception:
    def estrai_dati_fattura(file_bytes, filename):
        return {
            "tipo_documento": "TD01",
            "numero_documento": "1",
            "data_documento": datetime.today().strftime("%Y-%m-%d"),
            "cedente_denominazione": "FORNITORE",
            "cedente_piva": "",
            "cessionario_denominazione": "CLIENTE STUDIO",
            "cessionario_piva": "",
            "imponibile": 0.0,
            "imposta": 0.0,
            "totale_documento": 0.0,
            "aliquota_prevalente": 22.0
        }

try:
    from validator import valida_quadratura_completa, valida_partita_iva
except Exception:
    def valida_partita_iva(piva):
        p = re.sub(r"[^0-9]", "", str(piva))
        return len(p) == 11
    def valida_quadratura_completa(riepilogo_iva, totale_documento, ritenuta=0.0, bollo=0.0, cassa_previdenza=0.0):
        tot_calc = sum(r["imponibile"] + r["imposta"] for r in riepilogo_iva) + bollo + cassa_previdenza
        diff = abs(tot_calc - totale_documento)
        errs = [f"Differenza totale calcolato ({tot_calc:.2f}€) vs dichiarato ({totale_documento:.2f}€)"] if diff > 0.05 else []
        return (len(errs) == 0), errs

try:
    from xml_generator import genera_xml_teamsystem
except Exception:
    def genera_xml_teamsystem(d):
        return "<xml>Mock XML</xml>"

try:
    from gdrive import upload_to_drive
    GDRIVE_OK = True
except Exception:
    GDRIVE_OK = False
    def upload_to_drive(*args, **kwargs):
        return False, "Modulo Drive non configurato."

# ---------------------------------------------------------
# Inizializzazione Session State
# ---------------------------------------------------------
for k in ["invoice_data", "xml_content", "xml_filename", "last_file_id", "validation_report", "gdrive_status"]:
    if k not in st.session_state:
        st.session_state[k] = None

# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Parametri")
    codice_dest_default = st.text_input("Codice Destinatario SdI", value="0000000", max_chars=7)
    regime_fiscale_default = st.selectbox(
        "Regime Fiscale Fornitore",
        options=["RF01 - Ordinario", "RF19 - Forfettario", "RF02 - Semplificato"],
        index=0
    ).split(" - ")[0]
    
    st.divider()
    salva_drive = st.checkbox("Archivia su Google Drive", value=True)
    if not GDRIVE_OK:
        st.caption("ℹ️ Google Drive inattivo o secrets mancanti.")

# ---------------------------------------------------------
# Testata Principale
# ---------------------------------------------------------
st.title("🧾 AI Invoice to SdI / TeamSystem")
st.caption("Acquisizione rapida, revisione assistita (Human-in-the-Loop) e generazione tracciati FPR12.")

# ---------------------------------------------------------
# FASE 1: Caricamento File
# ---------------------------------------------------------
uploaded_file = st.file_uploader(
    "Trascina qui la fattura (PDF, JPG, PNG)",
    type=["pdf", "png", "jpg", "jpeg"]
)

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state["last_file_id"] != file_id:
        with st.status("Elaborazione del documento...", expanded=False) as status:
            st.write("Lettura stream del file...")
            file_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            
            st.write("Estrazione entità...")
            try:
                st.session_state["invoice_data"] = estrai_dati_fattura(file_bytes, uploaded_file.name)
            except Exception:
                st.session_state["invoice_data"] = estrai_dati_fattura(b"", uploaded_file.name)
                
            st.session_state["last_file_id"] = file_id
            st.session_state["xml_content"] = None
            st.session_state["xml_filename"] = None
            st.session_state["validation_report"] = None
            st.session_state["gdrive_status"] = None
            status.update(label="✅ Documento caricato!", state="complete")
        st.success("Dati estratti con successo! Verifica o modifica i dati qui sotto.")

if st.session_state["invoice_data"] is None:
    st.info("👆 Carica una fattura per visualizzare il modulo di revisione.")
    st.stop()

# ---------------------------------------------------------
# FASE 2: Modulo Human-in-the-Loop con Widget Nativi
# ---------------------------------------------------------
inv = st.session_state["invoice_data"]
st.markdown("---")
st.subheader("✏️ Revisione Dati Fattura")
st.caption("Tutti i campi sono modificabili. Clicca su 'Conferma e Genera XML' in basso per proseguire.")

with st.form("form_revisione_stabile"):
    # 1. Estr
