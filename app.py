# app.py - AI Invoice to SdI/TeamSystem (Human-in-the-Loop & GDrive Archiving)
import io
import re
import json
import zipfile
import pandas as pd
import streamlit as st
from datetime import datetime

# ---------------------------------------------------------
# Import Moduli di Progetto con protezioni anti-crash
# ---------------------------------------------------------
# 1. Extractor
try:
    from extractor import estrai_dati_fattura
except ImportError:
    try:
        from extractor import extract_data as estrai_dati_fattura
    except ImportError:
        def estrai_dati_fattura(file_bytes, filename):
            return {
                "tipo_documento": "TD01",
                "numero_documento": "1",
                "data_documento": datetime.today().strftime("%Y-%m-%d"),
                "cedente_denominazione": "FORNITORE ESEMPIO",
                "cedente_piva": "00000000000",
                "cessionario_denominazione": "CLIENTE STUDIO",
                "cessionario_piva": "00000000000",
                "imponibile": 0.0,
                "imposta": 0.0,
                "totale_documento": 0.0,
                "riepilogo_iva": [{"aliquota": 22.0, "imponibile": 0.0, "imposta": 0.0, "natura": ""}]
            }

# 2. Validator
try:
    from validator import valida_quadratura_completa, valida_partita_iva, valida_codice_fiscale
except ImportError:
    def valida_partita_iva(piva: str) -> bool:
        p = re.sub(r"[^0-9]", "", str(piva))
        if len(p) != 11:
            return False
        s = sum(int(p[i]) if i % 2 == 0 else ((int(p[i]) * 2) - 9 if int(p[i]) * 2 > 9 else int(p[i]) * 2) for i in range(10))
        return ((10 - (s % 10)) % 10) == int(p[10])

    def valida_codice_fiscale(cf: str) -> bool:
        return bool(re.match(r"^[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]$", str(cf).strip().upper()))

    def valida_quadratura_completa(riepilogo_iva, totale_documento, ritenuta=0.0, bollo=0.0, cassa_previdenza=0.0):
        tot_imp = sum(float(r.get("imponibile", 0.0)) for r in riepilogo_iva)
        tot_iva = sum(float(r.get("imposta", 0.0)) for r in riepilogo_iva)
        calc = round(tot_imp + tot_iva + bollo + cassa_previdenza, 2)
        diff = min(abs(calc - totale_documento), abs((calc - ritenuta) - totale_documento))
        errs = []
        if diff > 0.02:
            errs.append(f"Scostamento tra Totale Calcolato ({calc:.2f}€) e Dichiarato ({totale_documento:.2f}€).")
        return (len(errs) == 0), errs

# 3. XML Generator
try:
    from xml_generator import genera_xml_teamsystem
except ImportError:
    from xml.dom import minidom
    import xml.etree.ElementTree as ET
    def genera_xml_teamsystem(dati):
        root = ET.Element("p:FatturaElettronica", {"versione": "FPR12"})
        return minidom.parseString(ET.tostring(root, "utf-8")).toprettyxml(indent="  ")

# 4. Google Drive
try:
    from gdrive import upload_to_drive
    GDRIVE_AVAILABLE = True
except Exception:
    GDRIVE_AVAILABLE = False
    def upload_to_drive(*args, **kwargs):
        return False, "Modulo gdrive non disponibile o configurazione assente."

# ---------------------------------------------------------
# Configurazione Pagina
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI Invoice to SdI | TeamSystem Bridge",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Gestione Session State
for key in ["invoice_data", "xml_content", "xml_filename", "last_file_id", "validation_report", "gdrive_status"]:
    if key not in st.session_state:
        st.session_state[key] = None

# Sidebar
with st.sidebar:
    st.title("⚙️ Parametri SdI")
    codice_dest_default = st.text_input("Codice Destinatario Default", value="0000000", max_chars=7)
    regime_fiscale_default = st.selectbox(
        "Regime Fiscale Cedente",
        options=["RF01 - Ordinario", "RF19 - Forfettario", "RF02 - Semplificato"],
        index=0
    ).split(" - ")[0]
    
    st.divider()
    st.markdown("### ☁️ Google Drive")
    salva_su_drive = st.checkbox(
        "Archivia su Google Drive alla conferma",
        value=True,
        help="Salva automaticamente PDF e XML nella cartella del cliente su Google Drive."
    )
    if not GDRIVE_AVAILABLE:
        st.caption("⚠️ Google Drive non configurato o secrets mancanti.")

# Header
st.title("🧾 AI Invoice to SdI / TeamSystem")
st.caption("Estrazione ibrida PDF, revisione obbligatoria contabile Human-in-the-Loop e generazione tracciati FPR12.")

# ---------------------------------------------------------
# FASE 1: Upload Documento
# ---------------------------------------------------------
uploaded_file = st.file_uploader(
    "Carica una fattura (PDF o Immagine JPG/PNG)",
    type=["pdf", "png", "jpg", "jpeg"]
)

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state["last_file_id"] != file_id:
        with st.spinner("Estrazione dati contabili in corso..."):
            file_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            st.session_state["invoice_data"] = estrai_dati_fattura(file_bytes, uploaded_file.name)
            st.session_state["last_file_id"] = file_id
            st.session_state["xml_content"] = None
            st.session_state["xml_filename"] = None
            st.session_state["validation_report"] = None
            st.session_state["gdrive_status"] = None
        st.success("Estrazione completata! Verifica i dati nel modulo sottostante.")

if st.session_state["invoice_data"] is None:
    st.info("👆 Carica una fattura per iniziare la revisione.")
    st.stop()

# ---------------------------------------------------------
# FASE 2: Modulo Interattivo Human-in-the-Loop
# ---------------------------------------------------------
st.markdown("---")
st.subheader("✏️ Step 2: Revisione Manuale Obbligatoria")
st.warning("Verifica o modifica qualsiasi campo. Clicca sul pulsante in fondo al modulo per convalidare e generare l'XML.")

inv = st.session_state["invoice_data"]

# Preparazione tabella IVA
initial_iva = inv.get("riepilogo_iva", [])
if not initial_iva:
    initial_iva = [{
        "aliquota": float(inv.get("aliquota_prevalente", 22.0)),
        "imponibile": float(inv.get("imponibile", 0.0)),
        "imposta": float(inv.get("imposta", 0.0)),
        "natura": inv.get("natura", "")
    }]

df_iva = pd.DataFrame(initial_iva)
for col, val in [("aliquota", 22.0), ("imponibile", 0.0), ("imposta", 0.0), ("natura", "")]:
    if col not in df_iva.columns:
        df_iva[col] = val

with st.form("form_revisione_fattura"):
    st.markdown("#### 📄 Dati Documento")
    c_d1, c_d2, c_d3, c_d4 = st.columns(4)
    with c_d1:
        tipo_documento = st.selectbox(
            "Tipo Documento",
            options=["TD01", "TD02", "TD04", "TD24"],
            index=["TD01", "TD02", "TD04", "TD24"].index(inv.get("tipo_documento", "TD01"))
            if inv.get("tipo_documento", "TD01") in ["TD01", "TD02", "TD04", "TD24"] else 0
        )
    with c_d2:
        numero_documento = st.text_input("Numero Fattura", value=str(inv.get("numero_documento", "1")))
    with c_d3:
        raw_date = str(inv.get("data_documento", datetime.today().strftime("%Y-%m-%d")))
        try:
            d_parsed = datetime.strptime(raw_date[:10], "%Y-%m-%d")
        except Exception:
            d_parsed = datetime.today()
        data_documento = st.date_input("Data Fattura", value=d_parsed)
    with c_d4:
        codice_destinatario = st.text_input("Codice SdI", value=str(inv.get("codice_destinatario", codice_dest_default)), max_chars=7)

    st.markdown("---")
    col_ced, col_cess = st.columns(2)
    with col_ced:
        st.markdown("#### 🏢 Fornitore (Cedente/Prestatore)")
        ced_denominazione = st.text_input("Denominazione Fornitore", value=str(inv.get("cedente_denominazione", "")))
        ced_piva = st.text_input("Partita IVA Fornitore", value=str(inv.get("cedente_piva", "")), max_chars=16)
        ced_cf = st.text_input("Codice Fiscale Fornitore", value=str(inv.get("cedente_cf", "")))
        c_i, c_c = st.columns([3, 1])
        ced_indirizzo = c_i.text_input("Indirizzo Fornitore", value=str(inv.get("cedente_indirizzo", "Via Roma 1")))
        ced_cap = c_c.text_input("CAP", value=str(inv.get("cedente_cap", "00100")), max_chars=5)
        c_m, c_n = st.columns([3, 1])
        ced_comune = c_m.text_input("Comune", value=str(inv.get("cedente_comune", "Roma")))
        ced_nazione = c_n.text_input("Nazione", value=str(inv.get("cedente_nazione", "IT")), max_chars=2)

    with col_cess:
        st.markdown("#### 👤 Cliente dello Studio (Cessionario/Committente)")
        cess_denominazione = st.text_input("Denominazione Cliente (Cartella Drive)", value=str(inv.get("cessionario_denominazione", "CLIENTE STUDIO")))
        cess_piva = st.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")), max_chars=16)
        cess_cf = st.text_input("Codice Fiscale Cliente", value=str(inv.get("cessionario_cf", "")))
        cs_i, cs_c = st.columns([3, 1])
        cess_indirizzo = cs_i.text_input("Indirizzo Cliente", value=str(inv.get("cessionario_indirizzo", "Via Studio 10")))
        cess_cap = cs_c.text_input("CAP Cliente", value=str(inv.get("cessionario_cap", "00100")), max_chars=5)
        cs_m, cs_n = st.columns([3, 1])
        cess_comune = cs_m.text_input("Comune Cliente", value=str(inv.get("cessionario_comune", "Roma")))
        cess_nazione = cs_n.text_input("Nazione Cliente", value=str(inv.get("cessionario_nazione", "IT")), max_chars=2)

    st.markdown("---")
    st.markdown("#### 📊 Dettaglio IVA e Aliquote")
    edited_iva = st.data_editor(
        df_iva,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "aliquota": st.column_config.NumberColumn("Aliquota (%)", min_value=0.0, max_value=100.0, step=1.0, format="%.2f"),
            "imponibile": st.column_config.NumberColumn("Imponibile (€)", step=0.01, format="%.2f €"),
            "imposta": st.column_config.NumberColumn("Imposta (€)", step=0.01, format="%.2f €"),
            "natura": st.column_config.TextColumn("Natura IVA (obbligatoria se 0%)", max_chars=10)
        }
    )

    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
    with col_t1:
        cassa = st.number_input("Cassa / Rivalsa (€)", value=float(inv.get("cassa_previdenza", 0.0)), step=0.01)
    with col_t2:
        bollo = st.number_input("Marca da Bollo (€)", value=float(inv.get("bollo", 0.0)), step=2.00)
    with col_t3:
        ritenuta = st.number_input("Ritenuta d'Acconto (€)", value=float(inv.get("ritenuta", 0.0)), step=0.01)
    with col_t4:
        totale_documento = st.number_input("Totale Documento (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01)

    submitted = st.form_submit_button("✅ Conferma Dati e Genera XML SdI", type="primary", use_container_width=True)

# ---------------------------------------------------------
# FASE 3: Validazione Contabile, XML & Google Drive
# ---------------------------------------------------------
if submitted:
    righe_iva = edited_iva.to_dict(orient="records")
    
    # 1. Controlli P.IVA
    segnalazioni = []
    if ced_piva and not valida_partita_iva(ced_piva):
        segnalazioni.append(f"P.IVA Cedente '{ced_piva}' non conforme all'algoritmo formale.")
    if cess_piva and not valida_partita_iva(cess_piva):
        segnalazioni.append(f"P.IVA Cessionario '{cess_piva}' non conforme all'algoritmo formale.")

    # 2. Quadratura Contabile
    quadratura_ok, err_quadratura = valida_quadratura_completa(
        riepilogo_iva=righe_iva,
        totale_documento=totale_documento,
        ritenuta=ritenuta,
        bollo=bollo,
        cassa_previdenza=cassa
    )
    
    st.session_state["validation_report"] = (quadratura_ok and len(segnalazioni) == 0, segnalazioni + err_quadratura)

    tot_imp = sum(float(r.get("imponibile", 0.0)) for r in righe_iva)
    payload_finale = {
        "tipo_documento": tipo_documento,
        "numero_documento": numero_documento,
        "data_documento": data_documento.strftime("%Y-%m-%d"),
        "codice_destinatario": codice_destinatario,
        "regime_fiscale": regime_fiscale_default,
        "cedente_denominazione": ced_denominazione,
        "cedente_piva": ced_piva,
        "cedente_cf": ced_cf if ced_cf else ced_piva,
        "cedente_indirizzo": ced_indirizzo,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_comune,
        "cedente_nazione": ced_nazione,
        "cessionario_denominazione": cess_denominazione,
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf if cess_cf else cess_piva,
        "cessionario_indirizzo": cess_indirizzo,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_comune,
        "cessionario_nazione": cess_nazione,
        "riepilogo_iva": righe_iva,
        "totale_documento": totale_documento,
        "ritenuta": ritenuta,
        "bollo": bollo,
        "cassa_previdenza": cassa,
        "linee": [{
            "descrizione": f"Merci/Servizi documento n. {numero_documento}",
            "prezzo_unitario": tot_imp,
            "prezzo_totale": tot_imp,
            "aliquota": float(righe_iva[0].get("aliquota", 22.0)) if righe_iva else 22.0,
            "natura": righe_iva[0].get("natura", "") if righe_iva else ""
        }]
    }

    xml_text = genera_xml_teamsystem(payload_finale)
    clean_piva_filename = ced_piva.replace("IT", "").strip() if ced_piva else "00000000000"
    base_filename = f"IT{clean_piva_filename}_{numero_documento.replace('/', '_')}"
    
    st.session_state["xml_content"] = xml_text
    st.session_state["xml_filename"] = f"{base_filename}.xml"

    # 3. Archiviazione Google Drive (se abilitata)
    if salva_su_drive:
        with st.spinner("Archiviazione su Google Drive in corso..."):
            uploaded_file.seek(0)
            pdf_bytes = uploaded_file.read()
            success, msg = upload_to_drive(
                pdf_bytes=pdf_bytes,
                xml_string=xml_text,
                nome_cliente=cess_denominazione,
                filename_base=base_filename
            )
            st.session_state["gdrive_status"] = (success, msg)

# ---------------------------------------------------------
# FASE 4: Download & Stato Archiviazione
# ---------------------------------------------------------
if st.session_state["xml_content"] is not None:
    st.markdown("---")
    st.subheader("📦 Step 3: Esito & Download")
    is_valid, errori = st.session_state["validation_report"]

    c_rep1, c_rep2 = st.columns([2, 1])
    with c_rep1:
        if is_valid:
            st.success("✅ **Quadratura e Dati Fiscali Validi:** Nessuna asimmetria contabile riscontrata.")
        else:
            st.warning("⚠️ **Segnalazioni contabili o fiscali:**")
            for err in errori:
                st.write(f"- {err}")

        # Feedback Google Drive
        if st.session_state["gdrive_status"] is not None:
            g_ok, g_msg = st.session_state["gdrive_status"]
            if g_ok:
                st.info(f"☁️ **Google Drive:** {g_msg}")
            else:
                st.warning(f"☁️ **Google Drive (Bypass):** {g_msg}")

    # Pacchetto ZIP in memoria
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(st.session_state["xml_filename"], st.session_state["xml_content"])
        uploaded_file.seek(0)
        z.writestr(uploaded_file.name, uploaded_file.read())
    zip_buf.seek(0)

    with c_rep2:
        st.download_button(
            label="💾 Scarica XML FatturaPA",
            data=st.session_state["xml_content"],
            file_name=st.session_state["xml_filename"],
            mime="application/xml",
            use_container_width=True
        )
        st.download_button(
            label="🗂️ Scarica ZIP (XML + Originale)",
            data=zip_buf,
            file_name=f"Fattura_{st.session_state['xml_filename'].replace('.xml', '')}.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True
        )

    with st.expander("🔍 Ispezione Tracciato XML FPR12"):
        st.code(st.session_state["xml_content"], language="xml")
