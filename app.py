# app.py - AI Invoice to SdI/TeamSystem CONSPAY
import io
import zipfile
import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="AI Invoice to SdI | TeamSystem CONSPAY",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

from extractor import estrai_dati_fattura
from validator import valida_quadratura_completa, valida_partita_iva
from xml_generator import genera_xml_teamsystem

try:
    from gdrive import upload_to_drive
    GDRIVE_OK = True
except Exception:
    GDRIVE_OK = False
    def upload_to_drive(*args, **kwargs):
        return False, "Modulo Drive non attivo."

# Inizializzazione Session State
for k in ["invoice_data", "xml_content", "xml_filename", "last_file_id", "validation_report", "gdrive_status", "motore_usato", "testo_grezzo"]:
    if k not in st.session_state:
        st.session_state[k] = None

# Sidebar con gestione esplicita dell'API Key Gemini
with st.sidebar:
    st.title("⚙️ Impostazioni Motore")
    
    # Recupero chiave da st.secrets o input manuale
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
    api_key_input = st.text_input(
        "Google Gemini API Key",
        value=secret_key,
        type="password",
        help="Inserisci la chiave API per attivare il riconoscimento visivo avanzato su qualsiasi layout."
    )
    
    if api_key_input and len(api_key_input.strip()) > 10:
        st.success("🟢 Motore IA Gemini: ATTIVO")
    else:
        st.warning("🟡 Motore IA: NON ATTIVO (Uso solo Regex locali)")
        st.caption("Consigliato: inserisci la chiave Gemini per leggere qualsiasi formato con precisione al 100%.")

    st.divider()
    codice_dest_default = st.text_input("Codice SdI Ricevente", value="0000000", max_chars=7)
    regime_fiscale_default = st.selectbox(
        "Regime Fiscale Fornitore",
        options=["RF01 - Ordinario", "RF19 - Forfettario", "RF02 - Semplificato"],
        index=0
    ).split(" - ")[0]
    
    salva_drive = st.checkbox("Archivia su Google Drive", value=True)

# Testata
st.title("🧾 AI Invoice to SdI / TeamSystem CONSPAY")
st.caption("Estrae con certezza Cedente, Cessionario, Dati Bancari IBAN e Quadratura per la riconciliazione contabile.")

uploaded_file = st.file_uploader(
    "Carica fattura PDF o Immagine",
    type=["pdf", "png", "jpg", "jpeg"]
)

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state["last_file_id"] != file_id:
        with st.status("Elaborazione avanzata del documento in corso...", expanded=True) as status:
            st.write("📄 Lettura file binario...")
            file_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            
            st.write("🧠 Estrazione dati fiscali e bancari...")
            dati, motore, testo_raw = estrai_dati_fattura(
                file_bytes, 
                uploaded_file.name, 
                api_key=api_key_input
            )
            
            st.session_state["invoice_data"] = dati
            st.session_state["motore_usato"] = motore
            st.session_state["testo_grezzo"] = testo_raw
            st.session_state["last_file_id"] = file_id
            st.session_state["xml_content"] = None
            st.session_state["xml_filename"] = None
            st.session_state["validation_report"] = None
            st.session_state["gdrive_status"] = None
            status.update(label=f"✅ Estrazione completata con: {motore}", state="complete", expanded=False)

if st.session_state["invoice_data"] is None:
    st.info("👆 Carica una fattura per avviare l'estrazione.")
    st.stop()

inv = st.session_state["invoice_data"]

# Indicatore del motore utilizzato
st.info(f"🛠️ **Motore di estrazione impiegato:** `{st.session_state['motore_usato']}`")

# Form Human-in-the-Loop
with st.form("form_revisione_totale"):
    st.markdown("#### 📄 1. Estremi del Documento")
    cd1, cd2, cd3, cd4 = st.columns(4)
    with cd1:
        tipo_doc = st.selectbox("Tipo Documento", ["TD01", "TD02", "TD04", "TD24"], index=0)
    with cd2:
        num_doc = st.text_input("Numero Documento", value=str(inv.get("numero_documento", "1")))
    with cd3:
        try:
            d_val = datetime.strptime(str(inv.get("data_documento", ""))[:10], "%Y-%m-%d")
        except Exception:
            d_val = datetime.today()
        data_doc = st.date_input("Data Documento", value=d_val)
    with cd4:
        cod_sdi = st.text_input("Codice Destinatario SdI", value=str(inv.get("codice_destinatario", codice_dest_default)), max_chars=7)

    st.markdown("---")
    st.markdown("#### 🏢 2. Anagrafiche Fiscali Separate")
    col_ced, col_cess = st.columns(2)
    
    with col_ced:
        st.markdown("##### 🏢 Fornitore (Cedente / Prestatore)")
        ced_nome = st.text_input("Denominazione Fornitore", value=str(inv.get("cedente_denominazione", "")))
        ced_piva = st.text_input("Partita IVA Fornitore", value=str(inv.get("cedente_piva", "")), max_chars=16)
        ced_via = st.text_input("Indirizzo Sede Fornitore", value=str(inv.get("cedente_indirizzo", "Via Sede 1")))
        ci1, ci2, ci3 = st.columns([2, 3, 1])
        ced_cap = ci1.text_input("CAP", value=str(inv.get("cedente_cap", "00100")), max_chars=5)
        ced_comune = ci2.text_input("Comune", value=str(inv.get("cedente_comune", "Roma")))
        ced_prov = ci3.text_input("Prov.", value=str(inv.get("cedente_provincia", "RM"))[:2].upper(), max_chars=2)

    with col_cess:
        st.markdown("##### 👤 Cliente dello Studio (Cessionario / Committente)")
        cess_nome = st.text_input("Denominazione Cliente (Cartella Drive)", value=str(inv.get("cessionario_denominazione", "")))
        cess_piva = st.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")), max_chars=16)
        cess_cf = st.text_input("Codice Fiscale Cliente (se privato)", value=str(inv.get("cessionario_cf", "")))
        cess_v
