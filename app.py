# app.py - AI Invoice to SdI/TeamSystem CONSPAY
import io
import zipfile
import pandas as pd
import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="AI Invoice to SdI | TeamSystem CONSPAY",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Funzioni di validazione integrate
def valida_partita_iva(piva: str, paese: str = "IT") -> bool:
    p = str(piva).strip().upper()
    if paese == "IT":
        if len(p) != 11 or not p.isdigit():
            return False
        s = sum(int(p[i]) if i % 2 == 0 else ((int(p[i]) * 2) - 9 if int(p[i]) * 2 > 9 else int(p[i]) * 2) for i in range(10))
        return ((10 - (s % 10)) % 10) == int(p[10])
    return 4 <= len(p) <= 15

def valida_quadratura(riepilogo, totale):
    tot_calc = sum(r["imponibile"] + r["imposta"] for r in riepilogo)
    diff = abs(tot_calc - totale)
    errs = [f"Differenza totale calcolato ({tot_calc:.2f}€) vs dichiarato ({totale:.2f}€)"] if diff > 0.05 else []
    return (len(errs) == 0), errs

# Import moduli secondari
from extractor import estrai_dati_fattura
from xml_generator import genera_xml_teamsystem

try:
    from gdrive import upload_to_drive
    GDRIVE_OK = True
except Exception:
    GDRIVE_OK = False
    def upload_to_drive(*args, **kwargs):
        return False, "Drive non attivo"

# Session State
for k in ["invoice_data", "xml_content", "xml_filename", "last_file_id", "validation_report", "gdrive_status", "motore_usato", "testo_grezzo", "errore_ai"]:
    if k not in st.session_state:
        st.session_state[k] = None

# Sidebar
with st.sidebar:
    st.title("⚙️ Configurazione")
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
    api_key_input = st.text_input("Google Gemini API Key", value=secret_key, type="password")
    if api_key_input and len(api_key_input.strip()) > 10:
        st.success("🟢 Chiave IA Registrata")
    else:
        st.info("ℹ️ Inserisci la chiave per il motore AI o usa il parser locale")

    st.divider()
    codice_dest_default = st.text_input("Codice SdI Ricevente", value="0000000", max_chars=7)
    salva_drive = st.checkbox("Archivia su Google Drive", value=True)

st.title("🧾 AI Invoice to SdI / TeamSystem CONSPAY")
st.caption("Fatturazione FPR12 v1.2.2 - Estrazione garantita Cedente, Cessionario, Dati Bancari e Riconciliazione.")

uploaded_file = st.file_uploader("Carica fattura (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state["last_file_id"] != file_id:
        with st.status("Elaborazione del documento in corso...", expanded=True) as status:
            file_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            dati, motore, testo_raw, err_ai = estrai_dati_fattura(file_bytes, uploaded_file.name, api_key=api_key_input)
            
            st.session_state["invoice_data"] = dati
            st.session_state["motore_usato"] = motore
            st.session_state["testo_grezzo"] = testo_raw
            st.session_state["errore_ai"] = err_ai
            st.session_state["last_file_id"] = file_id
            st.session_state["xml_content"] = None
            st.session_state["xml_filename"] = None
            st.session_state["validation_report"] = None
            status.update(label=f"✅ Analisi completata: {motore}", state="complete", expanded=False)

if st.session_state["invoice_data"] is None:
    st.info("👆 Carica una fattura per iniziare.")
    st.stop()

inv = st.session_state["invoice_data"]

if st.session_state.get("errore_ai"):
    st.warning(f"⚠️ Avviso Motore AI: {st.session_state['errore_ai']} (Dati estratti tramite parser locale).")

# Tabella di controllo rapido
st.markdown("### 🔍 Verifica Soggetti Estratti (Human-in-the-Loop)")
df_rep = pd.DataFrame([
    {
        "Ruolo": "🏢 FORNITORE (Cedente/Emittente)",
        "Denominazione": inv.get("cedente_denominazione", ""),
        "P.IVA": inv.get("cedente_piva", ""),
        "Indirizzo Sede": f"{inv.get('cedente_indirizzo', '')}, {inv.get('cedente_cap', '')} {inv.get('cedente_comune', '')} ({inv.get('cedente_provincia', '')})"
    },
    {
        "Ruolo": "👤 CLIENTE STUDIO (Cessionario/Ricevente)",
        "Denominazione": inv.get("cessionario_denominazione", ""),
        "P.IVA": inv.get("cessionario_piva", "") or inv.get("cessionario_cf", ""),
        "Indirizzo Sede": f"{inv.get('cessionario_indirizzo', '')}, {inv.get('cessionario_cap', '')} {inv.get('cessionario_comune', '')} ({inv.get('cessionario_provincia', '')})"
    }
])
st.data_editor(df_rep, use_container_width=True, disabled=True)

# Inversione manuale di sicurezza
if st.button("🔄 Inverti Fornitore e Cliente (se scambiati)"):
    for campo in ["denominazione", "paese", "piva", "indirizzo", "cap", "comune", "provincia"]:
        inv[f"cedente_{campo}"], inv[f"cessionario_{campo}"] = inv.get(f"cessionario_{campo}", ""), inv.get(f"cedente_{campo}", "")
    st.session_state["invoice_data"] = inv
    st.rerun()

st.markdown("---")

# Form Revisione Dati
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
    st.markdown("#### 🏢 2. Anagrafiche Fiscali Segregate")
    col_ced,
