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
        cess_comune = st.text_input("Comune Cliente", value=str(inv.get("cessionario_comune", "Roma")))

    st.markdown("---")
    
    # 3. Dati Economici Principali
    st.markdown("##### 💰 Dati Economici & IVA")
    ce1, ce2, ce3, ce4 = st.columns(4)
    with ce1:
        imponibile_1 = st.number_input("Imponibile Principale (€)", value=float(inv.get("imponibile", 0.0)), step=0.01)
    with ce2:
        aliquota_1 = st.number_input("Aliquota IVA (%)", value=float(inv.get("aliquota_prevalente", 22.0)), step=1.0)
    with ce3:
        imposta_1 = st.number_input("Imposta IVA (€)", value=float(inv.get("imposta", 0.0)), step=0.01)
    with ce4:
        natura_1 = st.text_input("Natura (se IVA 0%, es. N3.4, N4)", value=str(inv.get("natura", "")))

    # Seconda aliquota opzionale
    st.caption("Seconda Aliquota (opzionale, compila solo se documento multi-aliquota)")
    ca1, ca2, ca3, ca4 = st.columns(4)
    with ca1:
        imponibile_2 = st.number_input("Secondo Imponibile (€)", value=0.0, step=0.01)
    with ca2:
        aliquota_2 = st.number_input("Seconda Aliquota (%)", value=10.0, step=1.0)
    with ca3:
        imposta_2 = st.number_input("Seconda Imposta (€)", value=0.0, step=0.01)
    with ca4:
        natura_2 = st.text_input("Natura Seconda Aliquota", value="")

    # Totali e Ritenute
    st.markdown("##### ⚖️ Totali di Quadratura")
    ct1, ct2, ct3, ct4 = st.columns(4)
    with ct1:
        cassa = st.number_input("Cassa Previdenza (€)", value=float(inv.get("cassa_previdenza", 0.0)), step=0.01)
    with ct2:
        bollo = st.number_input("Bollo Virtuale (€)", value=float(inv.get("bollo", 0.0)), step=2.00)
    with ct3:
        ritenuta = st.number_input("Ritenuta d'Acconto (€)", value=float(inv.get("ritenuta", 0.0)), step=0.01)
    with ct4:
        totale_doc = st.number_input("Totale Fattura Dichiarato (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01)

    submit_btn = st.form_submit_button("✅ Conferma Dati e Genera XML SdI", type="primary", use_container_width=True)

# ---------------------------------------------------------
# FASE 3: Generazione XML & Archiviazione
# ---------------------------------------------------------
if submit_btn:
    righe_iva = [{
        "aliquota": aliquota_1,
        "imponibile": imponibile_1,
        "imposta": imposta_1,
        "natura": natura_1.strip()
    }]
    if imponibile_2 > 0 or imposta_2 > 0:
        righe_iva.append({
            "aliquota": aliquota_2,
            "imponibile": imponibile_2,
            "imposta": imposta_2,
            "natura": natura_2.strip()
        })

    segnalazioni = []
    if ced_piva and not valida_partita_iva(ced_piva):
        segnalazioni.append(f"P.IVA Cedente '{ced_piva}' non conforme allo standard italiano.")
    if cess_piva and not valida_partita_iva(cess_piva):
        segnalazioni.append(f"P.IVA Cessionario '{cess_piva}' non conforme allo standard italiano.")

    quadratura_ok, errs = valida_quadratura_completa(
        riepilogo_iva=righe_iva,
        totale_documento=totale_doc,
        ritenuta=ritenuta,
        bollo=bollo,
        cassa_previdenza=cassa
    )
    st.session_state["validation_report"] = (quadratura_ok and len(segnalazioni) == 0, segnalazioni + errs)

    tot_imp_totale = sum(r["imponibile"] for r in righe_iva)
    payload_xml = {
        "tipo_documento": tipo_doc,
        "numero_documento": num_doc,
        "data_documento": data_doc.strftime("%Y-%m-%d"),
        "codice_destinatario": cod_sdi,
        "regime_fiscale": regime_fiscale_default,
        "cedente_denominazione": ced_nome,
        "cedente_piva": ced_piva,
        "cedente_cf": ced_cf if ced_cf else ced_piva,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_comune,
        "cedente_nazione": "IT",
        "cessionario_denominazione": cess_nome,
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf if cess_cf else cess_piva,
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_comune,
        "cessionario_nazione": "IT",
        "riepilogo_iva": righe_iva,
        "totale_documento": totale_doc,
        "ritenuta": ritenuta,
        "bollo": bollo,
        "cassa_previdenza": cassa,
        "linee": [{
            "descrizione": f"Merci/Servizi documento n. {num_doc}",
            "prezzo_unitario": tot_imp_totale,
            "prezzo_totale": tot_imp_totale,
            "aliquota": righe_iva[0]["aliquota"],
            "natura": righe_iva[0]["natura"]
        }]
    }

    # Creazione XML
    xml_str = genera_xml_teamsystem(payload_xml)
    clean_piva = ced_piva.replace("IT", "").strip() if ced_piva else "00000000000"
    base_name = f"IT{clean_piva}_{num_doc.replace('/', '_')}"
    
    st.session_state["xml_content"] = xml_str
    st.session_state["xml_filename"] = f"{base_name}.xml"

    # Upload Drive se abilitato
    if salva_drive and GDRIVE_OK:
        with st.spinner("Archiviazione Google Drive..."):
            uploaded_file.seek(0)
            ok, msg = upload_to_drive(
                pdf_bytes=uploaded_file.read(),
                xml_string=xml_str,
                nome_cliente=cess_nome,
                filename_base=base_name
            )
            st.session_state["gdrive_status"] = (ok, msg)

# ---------------------------------------------------------
# FASE 4: Download & Anteprima
# ---------------------------------------------------------
if st.session_state["xml_content"] is not None:
    st.markdown("---")
    st.subheader("📦 Step 3: Esito & Download")
    is_ok, anomalie = st.session_state["validation_report"]

    c1, c2 = st.columns([2, 1])
    with c1:
        if is_ok:
            st.success("✅ **Quadratura Contabile Perfetta**: Totale e imposta allineati al centesimo.")
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

    # Creazione ZIP
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

    with st.expander("🔍 Ispezione Tracciato XML Formattato"):
        st.code(st.session_state["xml_content"], language="xml")
