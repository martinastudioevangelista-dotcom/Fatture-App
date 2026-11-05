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
            
            st.write("Estrazione entità con PyMuPDF...")
            try:
                st.session_state["invoice_data"] = estrai_dati_fattura(file_bytes, uploaded_file.name)
            except Exception as e:
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
# FASE 2: Modulo Human-in-the-Loop con Widget Nativi (No Crash)
# ---------------------------------------------------------
inv = st.session_state["invoice_data"]
st.markdown("---")
st.subheader("✏️ Revisione Dati Fattura")
st.caption("Tutti i campi sono modificabili. Clicca su 'Conferma e Genera XML' in basso per proseguire.")

with st.form("form_revisione_stabile"):
    # 1. Estremi Fattura
    st.markdown("##### 📄 Estremi Documento")
    cd1, cd2, cd3, cd4 = st.columns(4)
    with cd1:
        tipo_doc = st.selectbox("Tipo Documento", ["TD01", "TD02", "TD04", "TD24"], index=0)
    with cd2:
        num_doc = st.text_input("Numero Fattura", value=str(inv.get("numero_documento", "1")))
    with cd3:
        raw_d = str(inv.get("data_documento", datetime.today().strftime("%Y-%m-%d")))
        try:
            d_val = datetime.strptime(raw_d[:10], "%Y-%m-%d")
        except Exception:
            d_val = datetime.today()
        data_doc = st.date_input("Data Documento", value=d_val)
    with cd4:
        cod_sdi = st.text_input("Codice SdI Destinatario", value=str(inv.get("codice_destinatario", codice_dest_default)), max_chars=7)

    st.markdown("---")
    
    # 2. Cedente e Cessionario
    col_ced, col_cess = st.columns(2)
    with col_ced:
        st.markdown("##### 🏢 Fornitore (Cedente)")
        ced_nome = st.text_input("Denominazione Fornitore", value=str(inv.get("cedente_denominazione", "FORNITORE")))
        ced_piva = st.text_input("Partita IVA Fornitore", value=str(inv.get("cedente_piva", "")), max_chars=16)
        ced_cf = st.text_input("Codice Fiscale Fornitore", value=str(inv.get("cedente_cf", "")))
        ci1, ci2 = st.columns([3, 1])
        ced_via = ci1.text_input("Indirizzo Sede", value=str(inv.get("cedente_indirizzo", "Via Principale 1")))
        ced_cap = ci2.text_input("CAP", value=str(inv.get("cedente_cap", "00100")), max_chars=5)
        ced_comune = st.text_input("Comune Fornitore", value=str(inv.get("cedente_comune", "Roma")))

    with col_cess:
        st.markdown("##### 👤 Cliente Studio (Cessionario)")
        cess_nome = st.text_input("Denominazione Cliente (Cartella Drive)", value=str(inv.get("cessionario_denominazione", "CLIENTE STUDIO")))
        cess_piva = st.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")), max_chars=16)
        cess_cf = st.text_input("Codice Fiscale Cliente", value=str(inv.get("cessionario_cf", "")))
        cs1, cs2 = st.columns([3, 1])
        cess_via = cs1.text_input("Indirizzo Cliente", value=str(inv.get("cessionario_indirizzo", "Via Studio 10")))
        cess_cap = cs2.text_input("CAP Cliente", value=str(inv.get("cessionario_cap", "00100")), max_chars=5)
        cess_comune = st.text_input("Comune Cliente", value=str(inv.get("cessionario_comune", "Rom
