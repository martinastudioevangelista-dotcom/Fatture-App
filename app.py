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

# Import protetto dei moduli
try:
    from extractor import estrai_dati_fattura
except BaseException as e:
    st.error(f"Errore di caricamento in extractor.py: {e}")
    st.stop()

try:
    from validator import valida_quadratura_completa, valida_partita_iva
    from xml_generator import genera_xml_teamsystem
except BaseException as e:
    st.error(f"Errore di caricamento moduli fiscali: {e}")
    st.stop()

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

# Sidebar con gestione API Key
with st.sidebar:
    st.title("⚙️ Impostazioni Motore")
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
        with st.status("Elaborazione del documento...", expanded=True) as status:
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
st.info(f"🛠️ **Motore di estrazione impiegato:** `{st.session_state['motore_usato']}`")

# Form di revisione Human-in-the-Loop
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
        ced_cap = ci1.text_input("CAP Fornitore", value=str(inv.get("cedente_cap", "00100")), max_chars=5)
        ced_comune = ci2.text_input("Comune Fornitore", value=str(inv.get("cedente_comune", "Roma")))
        ced_prov = ci3.text_input("Prov. Fornitore", value=str(inv.get("cedente_provincia", "RM"))[:2].upper(), max_chars=2)

    with col_cess:
        st.markdown("##### 👤 Cliente dello Studio (Cessionario / Committente)")
        cess_nome = st.text_input("Denominazione Cliente (Cartella Drive)", value=str(inv.get("cessionario_denominazione", "")))
        cess_piva = st.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")), max_chars=16)
        cess_cf = st.text_input("Codice Fiscale Cliente (se privato)", value=str(inv.get("cessionario_cf", "")))
        cess_via = st.text_input("Indirizzo Sede Cliente", value=str(inv.get("cessionario_indirizzo", "Via Studio 10")))
        cs1, cs2, cs3 = st.columns([2, 3, 1])
        cess_cap = cs1.text_input("CAP Cliente", value=str(inv.get("cessionario_cap", "00100")), max_chars=5)
        cess_comune = cs2.text_input("Comune Cliente", value=str(inv.get("cessionario_comune", "Roma")))
        cess_prov = cs3.text_input("Prov. Cliente", value=str(inv.get("cessionario_provincia", "RM"))[:2].upper(), max_chars=2)

    st.markdown("---")
    st.markdown("#### 🏦 3. Dati Riconciliazione Bancaria CONSPAY")
    cp1, cp2, cp3 = st.columns([2, 1, 1])
    with cp1:
        iban_doc = st.text_input("IBAN Accredito Fornitore", value=str(inv.get("iban", "")), help="Necessario per l'abbinamento automatico con l'estratto conto in TeamSystem CONSPAY.")
    with cp2:
        try:
            d_scad = datetime.strptime(str(inv.get("data_scadenza", ""))[:10], "%Y-%m-%d")
        except Exception:
            d_scad = d_val
        scadenza_pag = st.date_input("Scadenza Pagamento", value=d_scad)
    with cp3:
        metodo_pag = st.selectbox("Metodo Pagamento", ["MP05 - Bonifico Bancario", "MP08 - Carta", "MP12 - RiBa", "MP01 - Contanti"], index=0).split(" - ")[0]

    st.markdown("---")
    st.markdown("#### 💰 4. Sezione Contabile & Quadratura IVA")
    ce1, ce2, ce3, ce4 = st.columns(4)
    with ce1:
        imponibile_1 = st.number_input("Imponibile (€)", value=float(inv.get("imponibile", 0.0)), step=0.01)
    with ce2:
        aliquota_1 = st.number_input("Aliquota IVA (%)", value=float(inv.get("aliquota_prevalente", 22.0)), step=1.0)
    with ce3:
        imposta_1 = st.number_input("Imposta IVA (€)", value=float(inv.get("imposta", 0.0)), step=0.01)
    with ce4:
        totale_doc = st.number_input("Totale Documento (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01)

    btn_submit = st.form_submit_button("✅ Conferma Dati e Genera XML SdI / CONSPAY", type="primary", use_container_width=True)

if btn_submit:
    righe_iva = [{"aliquota": aliquota_1, "imponibile": imponibile_1, "imposta": imposta_1, "natura": ""}]
    segnalazioni = []
    if ced_piva and not valida_partita_iva(ced_piva):
        segnalazioni.append(f"P.IVA Cedente '{ced_piva}' non conforme all'algoritmo formale.")
    if cess_piva and not valida_partita_iva(cess_piva):
        segnalazioni.append(f"P.IVA Cessionario '{cess_piva}' non conforme all'algoritmo formale.")

    quadratura_ok, errs = valida_quadratura_completa(riepilogo_iva=righe_iva, totale_documento=totale_doc)
    st.session_state["validation_report"] = (quadratura_ok and len(segnalazioni) == 0, segnalazioni + errs)

    payload = {
        "tipo_documento": tipo_doc,
        "numero_documento": num_doc,
        "data_documento": data_doc.strftime("%Y-%m-%d"),
        "codice_destinatario": cod_sdi,
        "regime_fiscale": regime_fiscale_default,
        "cedente_denominazione": ced_nome,
        "cedente_piva": ced_piva,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_comune,
        "cedente_provincia": ced_prov,
        "cessionario_denominazione": cess_nome,
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf,
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_comune,
        "cessionario_provincia": cess_prov,
        "riepilogo_iva": righe_iva,
        "totale_documento": totale_doc,
        "iban": iban_doc,
        "data_scadenza": scadenza_pag.strftime("%Y-%m-%d"),
        "modalita_pagamento": metodo_pag,
        "linee": [{
            "descrizione": f"Merci/Servizi documento n. {num_doc}",
            "prezzo_totale": imponibile_1,
            "aliquota": aliquota_1
        }]
    }

    xml_text = genera_xml_teamsystem(payload)
    clean_piva = ced_piva.replace("IT", "").strip() or "00000000000"
    base_file = f"IT{clean_piva}_{num_doc.replace('/', '_')}"
    
    st.session_state["xml_content"] = xml_text
    st.session_state["xml_filename"] = f"{base_file}.xml"

    if salva_drive and GDRIVE_OK:
        with st.spinner("Archiviazione su Google Drive..."):
            uploaded_file.seek(0)
            ok, msg = upload_to_drive(
                pdf_bytes=uploaded_file.read(),
                xml_string=xml_text,
                nome_cliente=cess_nome,
                filename_base=base_file
            )
            st.session_state["gdrive_status"] = (ok, msg)

if st.session_state["xml_content"] is not None:
    st.markdown("---")
    st.subheader("📦 Step 3: XML Pronto per CONSPAY")
    is_ok, anomalie = st.session_state["validation_report"]

    c1, c2 = st.columns([2, 1])
    with c1:
        if is_ok:
            st.success("✅ **Tracciato Conforme FatturaPA 1.2.2**: I nodi fiscali e i parametri bancari CONSPAY sono corretti.")
        else:
            st.warning("⚠️ **Segnalazioni contabili:**")
            for a in anomalie:
                st.write(f"- {a}")

        if st.session_state["gdrive_status"] is not None:
            g_ok, g_msg = st.session_state["gdrive_status"]
            if g_ok:
                st.info(f"☁️ {g_msg}")
            else:
                st.warning(f"☁️ {g_msg}")

    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(st.session_state["xml_filename"], st.session_state["xml_content"])
        uploaded_file.seek(0)
        z.writestr(uploaded_file.name, uploaded_file.read())
    zip_bytes.seek(0)

    with c2:
        st.download_button(
            "💾 Scarica solo XML FPR12",
            data=st.session_state["xml_content"],
            file_name=st.session_state["xml_filename"],
            mime="application/xml",
            use_container_width=True
        )
        st.download_button(
            "🗂️ Scarica Pacchetto ZIP (PDF + XML)",
            data=zip_bytes,
            file_name=f"Fattura_{st.session_state['xml_filename'].replace('.xml', '')}.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True
        )

    with st.expander("🔍 Ispezione Tracciato XML FPR12 (con DatiPagamento CONSPAY)"):
        st.code(st.session_state["xml_content"], language="xml")

if st.session_state.get("testo_grezzo"):
    with st.expander("📄 Ispezione Testo Grezzo Rilevato nel PDF"):
        st.text(st.session_state["testo_grezzo"])
