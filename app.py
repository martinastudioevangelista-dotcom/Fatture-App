# app.py - AI Invoice to SdI/TeamSystem con interfaccia Human-in-the-Loop
import io
import json
import zipfile
import pandas as pd
import streamlit as st
from datetime import datetime

# Import dei moduli di progetto
try:
    from extractor import estrai_dati_fattura
except ImportError:
    # Fallback su eventuale naming alternativo
    from extractor import extract_data as estrai_dati_fattura

from validator import valida_quadratura_completa, valida_partita_iva, valida_codice_fiscale
from xml_generator import genera_xml_teamsystem

# ---------------------------------------------------------
# Configurazione Pagina
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI Invoice to SdI | TeamSystem Bridge",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inizializzazione Session State
if "invoice_data" not in st.session_state:
    st.session_state["invoice_data"] = None
if "xml_content" not in st.session_state:
    st.session_state["xml_content"] = None
if "xml_filename" not in st.session_state:
    st.session_state["xml_filename"] = None
if "last_uploaded_file_id" not in st.session_state:
    st.session_state["last_uploaded_file_id"] = None
if "validation_report" not in st.session_state:
    st.session_state["validation_report"] = None

# ---------------------------------------------------------
# Sidebar Informativa
# ---------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Parametri & Info")
    st.markdown("""
    **Pipeline Operativa:**
    1. 📥 **Estrazione Automatica** (PyMuPDF / AI Fallback)
    2. ✏️ **Revisione Umana Obbligatoria** (Form Interattivo)
    3. ⚖️ **Validazione Fiscale** (Regole SdI & TeamSystem)
    4. 📦 **Esportazione XML FPR12 / ZIP**
    """)
    st.divider()
    codice_dest_default = st.text_input("Codice Destinatario Default", value="0000000", max_chars=7)
    regime_fiscale_default = st.selectbox(
        "Regime Fiscale Predefinito Cedente",
        options=["RF01 - Ordinario", "RF19 - Forfettario", "RF02 - Semplificato"],
        index=0
    ).split(" - ")[0]
    st.caption("Standard tracciato: FatturaPA FPR12 v1.2.2")

# ---------------------------------------------------------
# Header Principale
# ---------------------------------------------------------
st.title("🧾 AI Invoice to SdI / TeamSystem")
st.caption("Modulo di acquisizione, revisione assistita Human-in-the-Loop e generazione tracciati per commercialisti.")

# ---------------------------------------------------------
# FASE 1: Caricamento ed Estrazione Dati
# ---------------------------------------------------------
uploaded_file = st.file_uploader(
    "Carica una fattura in formato PDF o Immagine (PNG, JPG, TIFF)",
    type=["pdf", "png", "jpg", "jpeg"],
    help="Il motore tenterà l'estrazione testuale ultra-rapida; in caso di scansioni raster attiverà il fallback OCR AI."
)

if uploaded_file is not None:
    current_file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    
    # Se è un nuovo file, avvia l'estrazione ed azzera lo stato precedente
    if st.session_state["last_uploaded_file_id"] != current_file_id:
        with st.spinner("Estrazione dati contabili in corso..."):
            file_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            
            # Chiamata al modulo extractor
            raw_data = estrai_dati_fattura(file_bytes, uploaded_file.name)
            
            # Normalizzazione dati estratti nel session_state
            st.session_state["invoice_data"] = raw_data
            st.session_state["last_uploaded_file_id"] = current_file_id
            st.session_state["xml_content"] = None
            st.session_state["xml_filename"] = None
            st.session_state["validation_report"] = None
            st.success("Dati estratti con successo! Verifica e correggi i dati sottostanti.")

# Se non c'è alcun file, interrompi l'esecuzione mostrando il prompt
if st.session_state["invoice_data"] is None:
    st.info("👆 Carica un file per avviare il processo di revisione.")
    st.stop()

# ---------------------------------------------------------
# FASE 2: Interfaccia di Modifica Manuale (Human-in-the-Loop)
# ---------------------------------------------------------
st.markdown("---")
st.subheader("✏️ Step 2: Revisione Manuale dei Dati Estratti")
st.warning("⚠️ **Controllo operatore obbligatorio**: Controlla e correggi i dati estratti prima di confermare la generazione dell'XML per TeamSystem.")

inv = st.session_state["invoice_data"]

# Preparazione righe IVA per il data_editor
initial_riepilogo = inv.get("riepilogo_iva", [])
if not initial_riepilogo:
    initial_riepilogo = [{
        "aliquota": float(inv.get("aliquota_prevalente", 22.0)),
        "imponibile": float(inv.get("imponibile", 0.0)),
        "imposta": float(inv.get("imposta", 0.0)),
        "natura": inv.get("natura", "")
    }]

df_iva = pd.DataFrame(initial_riepilogo)
# Assicura la presenza delle colonne minime
for col, default_val in [("aliquota", 22.0), ("imponibile", 0.0), ("imposta", 0.0), ("natura", "")]:
    if col not in df_iva.columns:
        df_iva[col] = default_val

# FORM DI REVISIONE E CONFERMA
with st.form("form_revisione_fattura"):
    # Sezione 1: Intestazione e Dati Documento
    st.markdown("#### 📄 Dati Generali del Documento")
    col_doc1, col_doc2, col_doc3, col_doc4 = st.columns(4)
    
    with col_doc1:
        tipo_documento = st.selectbox(
            "Tipo Documento",
            options=["TD01", "TD02", "TD04", "TD24"],
            index=["TD01", "TD02", "TD04", "TD24"].index(inv.get("tipo_documento", "TD01")) 
            if inv.get("tipo_documento", "TD01") in ["TD01", "TD02", "TD04", "TD24"] else 0,
            help="TD01: Fattura, TD04: Nota di credito, TD24: Fattura differita"
        )
    with col_doc2:
        numero_documento = st.text_input("Numero Documento", value=str(inv.get("numero_documento", "1")))
    with col_doc3:
        # Gestione data documento
        raw_date = str(inv.get("data_documento", datetime.today().strftime("%Y-%m-%d")))
        try:
            parsed_date = datetime.strptime(raw_date[:10], "%Y-%m-%d")
        except Exception:
            parsed_date = datetime.today()
        data_documento = st.date_input("Data Documento", value=parsed_date)
    with col_doc4:
        codice_destinatario = st.text_input(
            "Codice SDI / Canale", 
            value=str(inv.get("codice_destinatario", codice_dest_default)), 
            max_chars=7
        )

    st.markdown("---")
    
    # Sezione 2: Cedente (Fornitore) vs Cessionario (Cliente dello studio)
    col_ced, col_cess = st.columns(2)
    
    with col_ced:
        st.markdown("#### 🏢 Cedente / Prestatore (Fornitore)")
        cedente_denominazione = st.text_input("Denominazione / Cognome Nome", value=str(inv.get("cedente_denominazione", "")))
        cedente_piva = st.text_input("Partita IVA Cedente", value=str(inv.get("cedente_piva", "")), max_chars=16)
        cedente_cf = st.text_input("Codice Fiscale Cedente (se diverso)", value=str(inv.get("cedente_cf", "")))
        
        col_c_ind, col_c_cap = st.columns([3, 1])
        with col_c_ind:
            cedente_indirizzo = st.text_input("Indirizzo Sede", value=str(inv.get("cedente_indirizzo", "Via Principale 1")))
        with col_c_cap:
            cedente_cap = st.text_input("CAP", value=str(inv.get("cedente_cap", "00100")), max_chars=5)
            
        col_c_com, col_c_naz = st.columns([3, 1])
        with col_c_com:
            cedente_comune = st.text_input("Comune Sede", value=str(inv.get("cedente_comune", "Roma")))
        with col_c_naz:
            cedente_nazione = st.text_input("Nazione", value=str(inv.get("cedente_nazione", "IT")), max_chars=2)

    with col_cess:
        st.markdown("#### 👤 Cessionario / Committente (Cliente)")
        cessionario_denominazione = st.text_input("Denominazione Cliente", value=str(inv.get("cessionario_denominazione", "")))
        cessionario_piva = st.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")), max_chars=16)
        cessionario_cf = st.text_input("Codice Fiscale Cliente (se persona fisica)", value=str(inv.get("cessionario_cf", "")))
        
        col_cs_ind, col_cs_cap = st.columns([3, 1])
        with col_cs_ind:
            cessionario_indirizzo = st.text_input("Indirizzo Sede Cliente", value=str(inv.get("cessionario_indirizzo", "Via Studio 10")))
        with col_cs_cap:
            cessionario_cap = st.text_input("CAP Cliente", value=str(inv.get("cessionario_cap", "00100")), max_chars=5)
            
        col_cs_com, col_cs_naz = st.columns([3, 1])
        with col_cs_com:
            cessionario_comune = st.text_input("Comune Sede Cliente", value=str(inv.get("cessionario_comune", "Roma")))
        with col_cs_naz:
            cessionario_nazione = st.text_input("Nazione Cliente", value=str(inv.get("cessionario_nazione", "IT")), max_chars=2)

    st.markdown("---")

    # Sezione 3: Tabella Riepilogo IVA Interattiva
    st.markdown("#### 📊 Dati Contabili & Riepilogo IVA")
    st.caption("Aggiungi righe per fatture multi-aliquota o esenti (specificando la Natura es. N1, N2.2, N3.4, N4)")
    
    edited_iva = st.data_editor(
        df_iva,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "aliquota": st.column_config.NumberColumn("Aliquota IVA (%)", min_value=0.0, max_value=100.0, step=1.0, format="%.2f"),
            "imponibile": st.column_config.NumberColumn("Imponibile (€)", step=0.01, format="%.2f €"),
            "imposta": st.column_config.NumberColumn("Imposta (€)", step=0.01, format="%.2f €"),
            "natura": st.column_config.TextColumn("Natura IVA (obbligatoria se IVA 0%)", max_chars=10)
        }
    )

    # Sezione 4: Oneri Accessori & Totale Finale
    col_on1, col_on2, col_on3, col_on4 = st.columns(4)
    with col_on1:
        cassa_previdenza = st.number_input("Cassa Previdenza / Rivalsa (€)", value=float(inv.get("cassa_previdenza", 0.0)), step=0.01)
    with col_on2:
        bollo = st.number_input("Marca da Bollo (€)", value=float(inv.get("bollo", 0.0)), step=2.00)
    with col_on3:
        ritenuta = st.number_input("Ritenuta d'Acconto (€)", value=float(inv.get("ritenuta", 0.0)), step=0.01)
    with col_on4:
        totale_documento = st.number_input("Totale Documento Dichiarato (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01)

    # Submit obbligatorio
    submitted = st.form_submit_button("✅ Conferma Dati e Genera XML SdI", type="primary", use_container_width=True)

# ---------------------------------------------------------
# FASE 3: Validazione Contabile e Generazione XML
# ---------------------------------------------------------
if submitted:
    # 1. Riconversione dei dati editati in dizionario strutturato
    lista_riepilogo = edited_iva.to_dict(orient="records")
    
    # 2. Controllo formale Partite IVA
    segnalazioni_fiscali = []
    if cedente_piva and not valida_partita_iva(cedente_piva):
        segnalazioni_fiscali.append(f"La Partita IVA Cedente '{cedente_piva}' non supera il checksum formale.")
    if cessionario_piva and not valida_partita_iva(cessionario_piva):
        segnalazioni_fiscali.append(f"La Partita IVA Cessionario '{cessionario_piva}' non supera il checksum formale.")

    # 3. Controllo Quadratura Contabile
    quadratura_ok, errori_quadratura = valida_quadratura_completa(
        riepilogo_iva=lista_riepilogo,
        totale_documento=totale_documento,
        ritenuta=ritenuta,
        bollo=bollo,
        cassa_previdenza=cassa_previdenza
    )

    tutti_gli_errori = segnalazioni_fiscali + errori_quadratura
    st.session_state["validation_report"] = (quadratura_ok and len(segnalazioni_fiscali) == 0, tutti_gli_errori)

    # Strutturazione payload finale per il generatore XML
    dati_validati = {
        "tipo_documento": tipo_documento,
        "numero_documento": numero_documento,
        "data_documento": data_documento.strftime("%Y-%m-%d"),
        "codice_destinatario": codice_destinatario,
        "regime_fiscale": regime_fiscale_default,
        "cedente_denominazione": cedente_denominazione,
        "cedente_piva": cedente_piva,
        "cedente_cf": cedente_cf if cedente_cf else cedente_piva,
        "cedente_indirizzo": cedente_indirizzo,
        "cedente_cap": cedente_cap,
        "cedente_comune": cedente_comune,
        "cedente_nazione": cedente_nazione,
        "cessionario_denominazione": cessionario_denominazione,
        "cessionario_piva": cessionario_piva,
        "cessionario_cf": cessionario_cf if cessionario_cf else cessionario_piva,
        "cessionario_indirizzo": cessionario_indirizzo,
        "cessionario_cap": cessionario_cap,
        "cessionario_comune": cessionario_comune,
        "cessionario_nazione": cessionario_nazione,
        "riepilogo_iva": lista_riepilogo,
        "totale_documento": totale_documento,
        "ritenuta": ritenuta,
        "bollo": bollo,
        "cassa_previdenza": cassa_previdenza,
        "linee": [
            {
                "descrizione": f"Rif. Documento n. {numero_documento} - Prestazioni / Merci",
                "prezzo_unitario": sum(r["imponibile"] for r in lista_riepilogo),
                "prezzo_totale": sum(r["imponibile"] for r in lista_riepilogo),
                "aliquota": lista_riepilogo[0]["aliquota"] if lista_riepilogo else 22.0,
                "natura": lista_riepilogo[0].get("natura", "") if lista_riepilogo else ""
            }
        ]
    }

    # Creazione XML
    xml_generato = genera_xml_teamsystem(dati_validati)
    clean_piva = cedente_piva if cedente_piva else "IT99999999999"
    nome_xml = f"IT{clean_piva}_{numero_documento.replace('/', '_')}.xml"
    
    st.session_state["xml_content"] = xml_generato
    st.session_state["xml_filename"] = nome_xml

# ---------------------------------------------------------
# FASE 4: Area di Output e Download
# ---------------------------------------------------------
if st.session_state["xml_content"] is not None:
    st.markdown("---")
    st.subheader("📦 Step 3: Esito Validazione e Download File SdI")
    
    is_valid, lista_errori = st.session_state["validation_report"]
    
    col_rep_sx, col_rep_dx = st.columns([2, 1])
    
    with col_rep_sx:
        if is_valid:
            st.success("✅ **Quadratura Contabile Corretta**: L'imposta e il totale documento coincidono perfettamente con i requisiti SdI!")
        else:
            st.warning("⚠️ **Attenzione: Rilevate incongruenze formali o contabili**")
            for err in lista_errori:
                st.write(f"- {err}")
            st.caption("Il file XML è stato generato con i dati inseriti, ma TeamSystem o SdI potrebbero scartarlo per asimmetria contabile.")

    # Generazione pacchetto ZIP in-memory (io.BytesIO)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Aggiunta file XML
        zip_file.writestr(st.session_state["xml_filename"], st.session_state["xml_content"])
        # Aggiunta PDF/file originale
        uploaded_file.seek(0)
        zip_file.writestr(uploaded_file.name, uploaded_file.read())
    zip_buffer.seek(0)

    # Pulsanti di Download
    with col_rep_dx:
        st.download_button(
            label="💾 Scarica solo XML FatturaPA",
            data=st.session_state["xml_content"],
            file_name=st.session_state["xml_filename"],
            mime="application/xml",
            use_container_width=True
        )
        
        st.download_button(
            label="🗂️ Scarica Pacchetto ZIP (XML + PDF)",
            data=zip_buffer,
            file_name=f"Fattura_{st.session_state['xml_filename'].replace('.xml', '')}.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary"
        )

    # Ispezione del codice XML generato
    with st.expander("🔍 Visualizza Anteprima XML Formattato"):
        st.code(st.session_state["xml_content"], language="xml")
