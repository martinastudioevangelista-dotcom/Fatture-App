# app.py - AI Invoice to SdI/TeamSystem CONSPAY (Gestione Fornitori Esteri & Human-in-the-Loop)
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

# Import protetto
try:
    from extractor import estrai_dati_fattura
    from validator import valida_quadratura_completa, valida_partita_iva_internazionale
    from xml_generator import genera_xml_teamsystem
except BaseException as e:
    st.error(f"Errore di inizializzazione moduli: {e}")
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

# Sidebar
with st.sidebar:
    st.title("⚙️ Motore & Regime")
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
    api_key_input = st.text_input("Google Gemini API Key", value=secret_key, type="password")
    if api_key_input and len(api_key_input.strip()) > 10:
        st.success("🟢 IA Gemini Attiva (Supporto Fornitori UE)")
    else:
        st.warning("🟡 Modalità Locale (Solo Regex)")

    st.divider()
    codice_dest_default = st.text_input("Codice SdI Destinatario", value="0000000", max_chars=7)
    regime_fiscale_default = st.selectbox(
        "Regime Fiscale Fornitore",
        options=["RF01 - Ordinario", "RF19 - Forfettario", "RF02 - Semplificato"],
        index=0
    ).split(" - ")[0]
    salva_drive = st.checkbox("Archivia su Google Drive", value=True)

# Testata
st.title("🧾 AI Invoice to SdI / TeamSystem CONSPAY")
st.caption("Fatturazione FPR12 v1.2.2 - Gestione Rigida Cedente (Fornitori Esteri/Nazionali) vs Cessionario (Cliente Studio).")

# Upload
uploaded_file = st.file_uploader("Carica fattura (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state["last_file_id"] != file_id:
        with st.status("Analisi e separazione dei ruoli anagrafici...", expanded=True) as status:
            file_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            dati, motore, testo_raw = estrai_dati_fattura(file_bytes, uploaded_file.name, api_key=api_key_input)
            st.session_state["invoice_data"] = dati
            st.session_state["motore_usato"] = motore
            st.session_state["testo_grezzo"] = testo_raw
            st.session_state["last_file_id"] = file_id
            st.session_state["xml_content"] = None
            st.session_state["xml_filename"] = None
            st.session_state["validation_report"] = None
            status.update(label=f"✅ Analisi completata con: {motore}", state="complete", expanded=False)

if st.session_state["invoice_data"] is None:
    st.info("👆 Carica una fattura per visualizzare i soggetti contabili.")
    st.stop()

inv = st.session_state["invoice_data"]

# ---------------------------------------------------------
# CONTROLLO VISIVO RAPIDO CON st.data_editor E SWAP
# ---------------------------------------------------------
st.markdown("### 🔍 Verifica Rapida Soggetti Estratti (Human-in-the-Loop)")

df_confronto = pd.DataFrame([
    {
        "Ruolo": "🏢 FORNITORE (Cedente / Emittente)",
        "Denominazione": inv.get("cedente_denominazione", ""),
        "Paese": inv.get("cedente_paese", "IT"),
        "P.IVA / Identificativo": inv.get("cedente_piva", ""),
        "Comune / Sede": f"{inv.get('cedente_comune', '')} ({inv.get('cedente_nazione', '')})"
    },
    {
        "Ruolo": "👤 CLIENTE STUDIO (Cessionario / Ricevente)",
        "Denominazione": inv.get("cessionario_denominazione", ""),
        "Paese": inv.get("cessionario_paese", "IT"),
        "P.IVA / Identificativo": inv.get("cessionario_piva", "") or inv.get("cessionario_cf", ""),
        "Comune / Sede": f"{inv.get('cessionario_comune', '')} ({inv.get('cessionario_nazione', '')})"
    }
])

st.data_editor(df_confronto, use_container_width=True, disabled=True)

# Pulsante di swap per inversione istantanea con 1 clic
col_inv1, col_inv2 = st.columns([1, 4])
with col_inv1:
    if st.button("🔄 Inverti Fornitore e Cliente", help="Clicca qui se l'OCR ha scambiato chi emette e chi riceve la fattura"):
        # Scambia i campi nel session_state
        c_nome, c_paese, c_piva, c_ind, c_cap, c_com, c_prov = (
            inv["cedente_denominazione"], inv.get("cedente_paese", "IT"), inv["cedente_piva"],
            inv.get("cedente_indirizzo", ""), inv.get("cedente_cap", ""), inv.get("cedente_comune", ""), inv.get("cedente_provincia", "")
        )
        inv["cedente_denominazione"], inv["cedente_paese"], inv["cedente_piva"], inv["cedente_indirizzo"], inv["cedente_cap"], inv["cedente_comune"], inv["cedente_provincia"] = (
            inv["cessionario_denominazione"], inv.get("cessionario_paese", "IT"), inv["cessionario_piva"],
            inv.get("cessionario_indirizzo", ""), inv.get("cessionario_cap", ""), inv.get("cessionario_comune", ""), inv.get("cessionario_provincia", "")
        )
        inv["cessionario_denominazione"], inv["cessionario_paese"], inv["cessionario_piva"], inv["cessionario_indirizzo"], inv["cessionario_cap"], inv["cessionario_comune"], inv["cessionario_provincia"] = (
            c_nome, c_paese, c_piva, c_ind, c_cap, c_com, c_prov
        )
        st.session_state["invoice_data"] = inv
        st.rerun()

st.markdown("---")

# ---------------------------------------------------------
# FORM DI DETTAGLIO EDITABILE
# ---------------------------------------------------------
with st.form("form_revisione_rigida"):
    st.markdown("#### 📄 1. Estremi Fattura & Codice SdI Destinatario")
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
    st.markdown("#### 🏢 2. Anagrafiche Segregate (Fornitore Emittente vs Cliente Studio)")
    col_ced, col_cess = st.columns(2)
    
    with col_ced:
        st.markdown("**FORNITORE (Cedente/Prestatore - Chi emette)**")
        ced_nome = st.text_input("Denominazione Fornitore (es. SGB/CGI Finance)", value=str(inv.get("cedente_denominazione", "")))
        
        c_p1, c_p2 = st.columns([1, 3])
        with c_p1:
            ced_paese = st.text_input("Paese", value=str(inv.get("cedente_paese", "IT"))[:2].upper(), max_chars=2, help="Es. FR per Francia, IT per Italia")
        with c_p2:
            ced_piva = st.text_input("Partita IVA Fornitore (senza prefisso paese)", value=str(inv.get("cedente_piva", "")))
            
        ced_via = st.text_input("Indirizzo Fornitore", value=str(inv.get("cedente_indirizzo", "Via Sede 1")))
        ci1, ci2, ci3 = st.columns([2, 3, 1])
        ced_cap = ci1.text_input("CAP Fornitore", value=str(inv.get("cedente_cap", "00100")), max_chars=5)
        ced_comune = ci2.text_input("Comune Fornitore", value=str(inv.get("cedente_comune", "Roma")))
        ced_prov = ci3.text_input("Prov.", value=str(inv.get("cedente_provincia", ""))[:2].upper(), max_chars=2, help="Lasciare vuoto se fornitore estero (non IT)")

    with col_cess:
        st.markdown("**CLIENTE STUDIO (Cessionario/Committente - Chi riceve)**")
        cess_nome = st.text_input("Denominazione Cliente Studio", value=str(inv.get("cessionario_denominazione", "")))
        
        cs_p1, cs_p2 = st.columns([1, 3])
        with cs_p1:
            cess_paese = st.text_input("Paese Cliente", value=str(inv.get("cessionario_paese", "IT"))[:2].upper(), max_chars=2)
        with cs_p2:
            cess_piva = st.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")))
            
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
        iban_doc = st.text_input("IBAN Accredito Fornitore", value=str(inv.get("iban", "")), help="Mappato nel nodo 2.4 DatiPagamento per l'estratto conto CONSPAY.")
    with cp2:
        try:
            d_scad = datetime.strptime(str(inv.get("data_scadenza", ""))[:10], "%Y-%m-%d")
        except Exception:
            d_scad = d_val
        scadenza_pag = st.date_input("Scadenza Pagamento", value=d_scad)
    with cp3:
        metodo_pag = st.selectbox("Metodo Pagamento", ["MP05 - Bonifico Bancario", "MP08 - Carta", "MP12 - RiBa", "MP01 - Contanti"], index=0).split(" - ")[0]

    st.markdown("---")
    st.markdown("#### 💰 4. Sezione Contabile & Natura IVA (N3.2 per Fornitori Esteri UE)")
    ce1, ce2, ce3, ce4 = st.columns(4)
    with ce1:
        imponibile_1 = st.number_input("Imponibile Netto (€)", value=float(inv.get("imponibile", 0.0)), step=0.01)
    with ce2:
        default_aliq = 0.0 if ced_paese != "IT" else float(inv.get("aliquota_prevalente", 22.0))
        aliquota_1 = st.number_input("Aliquota IVA (%)", value=default_aliq, step=1.0)
    with ce3:
        default_natura = "N3.2" if (ced_paese != "IT" or aliquota_1 == 0.0) else str(inv.get("natura", ""))
        natura_iva = st.text_input("Natura IVA (N3.2 obbligatoria per UE)", value=default_natura)
    with ce4:
        imposta_1 = st.number_input("Imposta IVA (€)", value=0.0 if aliquota_1 == 0.0 else float(inv.get("imposta", 0.0)), step=0.01)

    totale_doc = st.number_input("Totale Documento Fattura (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01)

    btn_submit = st.form_submit_button("✅ Conferma Dati e Genera XML FPR12 per CONSPAY", type="primary", use_container_width=True)

# ---------------------------------------------------------
# GENERAZIONE E DOWNLOAD
# ---------------------------------------------------------
if btn_submit:
    righe_iva = [{
        "aliquota": aliquota_1, 
        "imponibile": imponibile_1, 
        "imposta": imposta_1, 
        "natura": natura_iva.strip().upper()
    }]
    
    segnalazioni = []
    if ced_piva and not valida_partita_iva_internazionale(ced_piva, ced_paese):
        segnalazioni.append(f"P.IVA Fornitore '{ced_piva}' ({ced_paese}) non conforme allo standard del paese.")
    if cess_piva and not valida_partita_iva_internazionale(cess_piva, cess_paese):
        segnalazioni.append(f"P.IVA Cliente '{cess_piva}' ({cess_paese}) non conforme all'algoritmo di controllo.")

    quadratura_ok, errs = valida_quadratura_completa(riepilogo_iva=righe_iva, totale_documento=totale_doc)
    st.session_state["validation_report"] = (quadratura_ok and len(segnalazioni) == 0, segnalazioni + errs)

    payload = {
        "tipo_documento": tipo_doc,
        "numero_documento": num_doc,
        "data_documento": data_doc.strftime("%Y-%m-%d"),
        "codice_destinatario": cod_sdi,
        "regime_fiscale": regime_fiscale_default,
        "cedente_denominazione": ced_nome,
        "cedente_paese": ced_paese,
        "cedente_piva": ced_piva,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_comune,
        "cedente_provincia": ced_prov if ced_paese == "IT" else "",
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": cess_paese,
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
            "descrizione": f"Prestazioni/Merci fattura n. {num_doc}",
            "prezzo_totale": imponibile_1,
            "aliquota": aliquota_1,
            "natura": natura_iva.strip().upper() if aliquota_1 == 0.0 else ""
        }]
    }

    xml_text = genera_xml_teamsystem(payload)
    base_file = f"{ced_paese}{ced_piva}_{num_doc.replace('/', '_')}"
    st.session_state["xml_content"] = xml_text
    st.session_state["xml_filename"] = f"{base_file}.xml"

    if salva_drive and GDRIVE_OK:
        with st.spinner("Archiviazione su Google Drive in corso..."):
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
            st.success("✅ **Tracciato Conforme FPR12**: Ruoli segregati correttamente, nodi CONSPAY e Natura N3.2 validati.")
        else:
            st.warning("⚠️ **Verifiche di quadratura:**")
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

    with st.expander("🔍 Ispezione Tracciato XML FPR12"):
        st.code(st.session_state["xml_content"], language="xml")
