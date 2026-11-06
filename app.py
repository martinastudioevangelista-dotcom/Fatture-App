# app.py - AI Invoice to SdI/TeamSystem CONSPAY (Supporto Ritenute & Multiformato)
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

def valida_partita_iva(piva: str, paese: str = "IT") -> bool:
    p = str(piva).strip().upper()
    if paese == "IT":
        if len(p) != 11 or not p.isdigit():
            return False
        s = sum(int(p[i]) if i % 2 == 0 else ((int(p[i]) * 2) - 9 if int(p[i]) * 2 > 9 else int(p[i]) * 2) for i in range(10))
        return ((10 - (s % 10)) % 10) == int(p[10])
    return 4 <= len(p) <= 15

def valida_quadratura(riepilogo, totale, ritenuta=0.0):
    tot_calc = sum(r["imponibile"] + r["imposta"] for r in riepilogo)
    diff = min(abs(tot_calc - totale), abs((tot_calc - ritenuta) - totale))
    errs = [f"Differenza totale calcolato ({tot_calc:.2f}€ lordo / {tot_calc - ritenuta:.2f}€ netto) vs dichiarato ({totale:.2f}€)"] if diff > 0.05 else []
    return (len(errs) == 0), errs

try:
    from extractor import estrai_dati_fattura
except SyntaxError as e:
    st.error(f"❌ Errore di sintassi in extractor.py alla riga {e.lineno}: {e.text}")
    st.stop()
except BaseException as e:
    st.error(f"❌ Errore durante il caricamento di extractor.py: {e}")
    st.stop()

try:
    from gdrive import upload_to_drive
    GDRIVE_OK = True
except Exception:
    GDRIVE_OK = False
    def upload_to_drive(*args, **kwargs): return False, "Drive non attivo"

for k in ["invoice_data", "xml_content", "xml_filename", "last_file_id", "validation_report", "gdrive_status", "motore_usato", "testo_grezzo", "errore_ai"]:
    if k not in st.session_state:
        st.session_state[k] = None

with st.sidebar:
    st.title("⚙️ Configurazione")
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
    api_key_input = st.text_input("Google Gemini API Key", value=secret_key, type="password")
    if api_key_input and len(api_key_input.strip()) > 10:
        st.success("🟢 Chiave IA Registrata")
    else:
        st.info("ℹ️ Inserisci la chiave per attivare l'estrazione visiva Gemini")

    st.divider()
    codice_dest_default = st.text_input("Codice SdI Ricevente", value="0000000", max_chars=7)
    salva_drive = st.checkbox("Archivia su Google Drive", value=True)

st.title("🧾 AI Invoice to SdI / TeamSystem CONSPAY")
st.caption("Fatturazione FPR12 v1.2.2 - Gestione automatica fatture commerciali, proforma con ritenuta d'acconto e fatture attive.")

uploaded_file = st.file_uploader("Carica fattura (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state["last_file_id"] != file_id:
        with st.status("Elaborazione e quadratura contabile...", expanded=True) as status:
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
    st.warning(f"⚠️ Avviso Motore AI: {st.session_state['errore_ai']} (Elaborazione eseguita con il parser locale).")

st.markdown("### 🔍 Verifica Soggetti Estratti (Human-in-the-Loop)")
df_rep = pd.DataFrame([
    {
        "Ruolo": "🏢 FORNITORE (Cedente / Emittente)",
        "Denominazione": inv.get("cedente_denominazione", ""),
        "P.IVA / CF": inv.get("cedente_piva", "") or inv.get("cedente_cf", ""),
        "Sede": f"{inv.get('cedente_indirizzo', '')}, {inv.get('cedente_cap', '')} {inv.get('cedente_comune', '')} ({inv.get('cedente_provincia', '')})"
    },
    {
        "Ruolo": "👤 CLIENTE STUDIO (Cessionario / Ricevente)",
        "Denominazione": inv.get("cessionario_denominazione", ""),
        "P.IVA / CF": inv.get("cessionario_piva", "") or inv.get("cessionario_cf", ""),
        "Sede": f"{inv.get('cessionario_indirizzo', '')}, {inv.get('cessionario_cap', '')} {inv.get('cessionario_comune', '')} ({inv.get('cessionario_provincia', '')})"
    }
])
st.data_editor(df_rep, use_container_width=True, disabled=True)

if st.button("🔄 Inverti Fornitore e Cliente (se scambiati)"):
    for c in ["denominazione", "paese", "piva", "cf", "indirizzo", "cap", "comune", "provincia"]:
        inv[f"cedente_{c}"], inv[f"cessionario_{c}"] = inv.get(f"cessionario_{c}", ""), inv.get(f"cedente_{c}", "")
    st.session_state["invoice_data"] = inv
    st.rerun()

st.markdown("---")

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
    col_ced, col_cess = st.columns(2)
    
    with col_ced:
        st.markdown("**FORNITORE (Cedente / Prestatore - Chi emette)**")
        ced_nome = st.text_input("Denominazione Fornitore", value=str(inv.get("cedente_denominazione", "")))
        c_p1, c_p2 = st.columns([1, 3])
        ced_paese = c_p1.text_input("Paese Fornitore", value=str(inv.get("cedente_paese", "IT"))[:2].upper(), max_chars=2)
        ced_piva = c_p2.text_input("Partita IVA Fornitore", value=str(inv.get("cedente_piva", "")))
        ced_cf = st.text_input("Codice Fiscale Fornitore", value=str(inv.get("cedente_cf", "")))
        ced_via = st.text_input("Indirizzo Fornitore", value=str(inv.get("cedente_indirizzo", "")))
        ci1, ci2, ci3 = st.columns([2, 3, 1])
        ced_cap = ci1.text_input("CAP Fornitore", value=str(inv.get("cedente_cap", "00100")), max_chars=5)
        ced_com = ci2.text_input("Comune Fornitore", value=str(inv.get("cedente_comune", "Roma")))
        ced_prov = ci3.text_input("Prov. Fornitore", value=str(inv.get("cedente_provincia", "RM"))[:2].upper(), max_chars=2)

    with col_cess:
        st.markdown("**CLIENTE STUDIO (Cessionario / Committente - Chi riceve)**")
        cess_nome = st.text_input("Denominazione Cliente", value=str(inv.get("cessionario_denominazione", "")))
        cs_p1, cs_p2 = st.columns([1, 3])
        cess_paese = cs_p1.text_input("Paese Cliente", value=str(inv.get("cessionario_paese", "IT"))[:2].upper(), max_chars=2)
        cess_piva = cs_p2.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")))
        cess_cf = st.text_input("Codice Fiscale Cliente", value=str(inv.get("cessionario_cf", "")))
        cess_via = st.text_input("Indirizzo Sede Cliente", value=str(inv.get("cessionario_indirizzo", "")))
        cs1, cs2, cs3 = st.columns([2, 3, 1])
        cess_cap = cs1.text_input("CAP Cliente", value=str(inv.get("cessionario_cap", "00100")), max_chars=5)
        cess_com = cs2.text_input("Comune Cliente", value=str(inv.get("cessionario_comune", "Roma")))
        cess_prov = cs3.text_input("Prov. Cliente", value=str(inv.get("cessionario_provincia", "RM"))[:2].upper(), max_chars=2)

    st.markdown("---")
    st.markdown("#### 🏦 3. Riconciliazione Bancaria CONSPAY")
    cp1, cp2, cp3 = st.columns([2, 1, 1])
    with cp1:
        iban_doc = st.text_input("IBAN Accredito Fornitore", value=str(inv.get("iban", "")), help="Se presente, permette l'aggancio automatico in TeamSystem CONSPAY.")
    with cp2:
        try:
            d_scad = datetime.strptime(str(inv.get("data_scadenza", ""))[:10], "%Y-%m-%d")
        except Exception:
            d_scad = d_val
        scadenza_pag = st.date_input("Scadenza Pagamento", value=d_scad)
    with cp3:
        metodo_default = inv.get("modalita_pagamento", "MP05")
        metodi_list = ["MP05 - Bonifico Bancario", "MP08 - Carta di Pagamento", "MP12 - RiBa", "MP01 - Contanti"]
        idx_met = 1 if metodo_default == "MP08" else 0
        metodo_pag = st.selectbox("Modalità Pagamento", metodi_list, index=idx_met).split(" - ")[0]

    st.markdown("---")
    st.markdown("#### 💰 4. Sezione Contabile, IVA & Ritenuta d'Acconto")
    ce1, ce2, ce3, ce4 = st.columns(4)
    with ce1:
        imponibile_1 = st.number_input("Imponibile (€)", value=float(inv.get("imponibile", 0.0)), step=0.01)
    with ce2:
        aliquota_1 = st.number_input("Aliquota IVA (%)", value=float(inv.get("aliquota_prevalente", 22.0)), step=1.0)
    with ce3:
        imposta_1 = st.number_input("Imposta IVA (€)", value=float(inv.get("imposta", 0.0)), step=0.01)
    with ce4:
        ritenuta_1 = st.number_input("Ritenuta d'Acconto (€)", value=float(inv.get("ritenuta", 0.0)), step=0.01, help="Es. 20% professionisti (detratta dal netto a pagare)")

    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        natura_iva = st.text_input("Natura (se IVA 0%, es. N3.2 per Fornitori UE)", value=str(inv.get("natura", "")))
    with col_t2:
        totale_doc = st.number_input("Totale a Pagare (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01)

    btn_submit = st.form_submit_button("✅ Conferma Dati e Genera XML FPR12 per CONSPAY", type="primary", use_container_width=True)

if btn_submit:
    righe_iva = [{"aliquota": aliquota_1, "imponibile": imponibile_1, "imposta": imposta_1, "natura": natura_iva.strip().upper()}]
    segnalazioni = []
    if ced_piva and not valida_partita_iva(ced_piva, ced_paese):
        segnalazioni.append(f"P.IVA Fornitore '{ced_piva}' ({ced_paese}) non valida.")
    if cess_piva and not valida_partita_iva(cess_piva, cess_paese):
        segnalazioni.append(f"P.IVA Cliente '{cess_piva}' ({cess_paese}) non valida.")

    quadratura_ok, errs = valida_quadratura(righe_iva, totale_doc, ritenuta=ritenuta_1)
    st.session_state["validation_report"] = (quadratura_ok and len(segnalazioni) == 0, segnalazioni + errs)

    payload = {
        "tipo_documento": tipo_doc,
        "numero_documento": num_doc,
        "data_documento": data_doc.strftime("%Y-%m-%d"),
        "codice_destinatario": cod_sdi,
        "regime_fiscale": "RF01",
        "cedente_denominazione": ced_nome,
        "cedente_paese": ced_paese,
        "cedente_piva": ced_piva,
        "cedente_cf": ced_cf,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_com,
        "cedente_provincia": ced_prov if ced_paese == "IT" else "",
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": cess_paese,
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf,
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_com,
        "cessionario_provincia": cess_prov,
        "riepilogo_iva": righe_iva,
        "ritenuta": ritenuta_1,
        "totale_documento": totale_doc,
        "iban": iban_doc,
        "data_scadenza": scadenza_pag.strftime("%Y-%m-%d"),
        "modalita_pagamento": metodo_pag,
        "linee": [{
            "descrizione": f"Prestazioni/Merci doc. n. {num_doc}",
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
        with st.spinner("Archiviazione Google Drive..."):
            uploaded_file.seek(0)
            ok, msg = upload_to_drive(uploaded_file.read(), xml_text, cess_nome, base_file)
            st.session_state["gdrive_status"] = (ok, msg)

if st.session_state["xml_content"] is not None:
    st.markdown("---")
    st.subheader("📦 Step 3: XML Pronto per CONSPAY")
    is_ok, anomalie = st.session_state["validation_report"]

    c1, c2 = st.columns([2, 1])
    with c1:
        if is_ok:
            st.success("✅ **Quadratura e Dati Fiscali Validi**: Documento pronto per l'importazione.")
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

    with st.expander("🔍 Ispezione Tracciato XML FPR12"):
        st.code(st.session_state["xml_content"], language="xml")
