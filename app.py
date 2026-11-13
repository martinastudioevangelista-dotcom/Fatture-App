# app.py - AI Invoice to SdI/TeamSystem CONSPAY (Flusso di Aggiornamento e Download Risolto)
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
        if len(p) != 11 or not p.isdigit(): return False
        s = sum(int(p[i]) if i % 2 == 0 else ((int(p[i]) * 2) - 9 if int(p[i]) * 2 > 9 else int(p[i]) * 2) for i in range(10))
        return ((10 - (s % 10)) % 10) == int(p[10])
    return 4 <= len(p) <= 15

def valida_quadratura_fiscale(riepilogo, totale, ritenuta=0.0):
    tot_imp = sum(r["imponibile"] for r in riepilogo)
    tot_iva = sum(r["imposta"] for r in riepilogo)
    lordo_calcolato = round(tot_imp + tot_iva, 2)
    netto_calcolato = round(lordo_calcolato - ritenuta, 2)

    diff_netto = abs(netto_calcolato - totale)
    diff_lordo = abs(lordo_calcolato - totale)

    if diff_netto <= 0.02 or diff_lordo <= 0.02:
        return True, []
    
    return False, [
        f"Asimmetria: Calcolato Netto {netto_calcolato:.2f}€ (Lordo {lordo_calcolato:.2f}€) vs Dichiarato {totale:.2f}€."
    ]

try:
    from extractor import estrai_dati_fattura
except SyntaxError as e:
    st.error(f"❌ Errore sintassi in extractor.py (riga {e.lineno}): {e.text}")
    st.stop()
except BaseException as e:
    st.error(f"❌ Errore in extractor.py: {e}")
    st.stop()

try:
    from xml_reader import leggi_xml_fattura
except Exception:
    def leggi_xml_fattura(*args, **kwargs): return None, "", "", "xml_reader non trovato"

from xml_generator import genera_xml_teamsystem

try:
    from gdrive import upload_to_drive
    GDRIVE_OK = True
except Exception:
    GDRIVE_OK = False
    def upload_to_drive(*args, **kwargs): return False, "Drive non attivo"

# Inizializzazione Session State
for k in ["invoice_data", "xml_content", "xml_filename", "last_file_id", "validation_report", "gdrive_status", "motore_usato", "testo_grezzo", "errore_ai", "xml_aggiornato"]:
    if k not in st.session_state:
        st.session_state[k] = None

# Sidebar
with st.sidebar:
    st.title("⚙️ Impostazioni")
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
    api_key_input = st.text_input("Google Gemini API Key", value=secret_key, type="password")
    if api_key_input and len(api_key_input.strip()) > 10:
        st.success("🟢 Chiave IA Attiva")
    else:
        st.info("ℹ️ Chiave opzionale (Parser Locale Attivo)")

    st.divider()
    codice_dest_default = st.text_input("Codice SdI Destinatario", value="0000000", max_chars=7)
    salva_drive = st.checkbox("Archivia su Google Drive", value=False)

st.title("🧾 AI Invoice to SdI / TeamSystem CONSPAY")
st.caption("Fatturazione FPR12 v1.2.2 - Tracciato ministeriale certificato per Agenzia delle Entrate e TeamSystem.")

# ---------------------------------------------------------
# FASE 1: CARICAMENTO DOCUMENTO
# ---------------------------------------------------------
col_up1, col_up2 = st.columns([4, 1])
with col_up1:
    uploaded_file = st.file_uploader(
        "Carica fattura (PDF, Immagine, XML nativo o firmato .P7M)", 
        type=["pdf", "png", "jpg", "jpeg", "xml", "p7m"]
    )
with col_up2:
    st.write("")
    st.write("")
    force_reparse = st.button("🔄 Rianalizza Documento", help="Rilegge il file azzerando la cache.")

def genera_payload_e_xml(dati_dict, cod_dest_val):
    ced_p = dati_dict.get("cedente_paese", "IT") or "IT"
    cess_p = dati_dict.get("cessionario_piva", "")
    aliq = float(dati_dict.get("aliquota_prevalente", 22.0 if ced_p == "IT" else 0.0))
    imp = float(dati_dict.get("imponibile", 0.0))
    iva = float(dati_dict.get("imposta", 0.0))
    nat = str(dati_dict.get("natura", "N3.2" if (ced_p != "IT" and aliq == 0.0) else ""))

    payload = {
        "tipo_documento": dati_dict.get("tipo_documento", "TD01"),
        "numero_documento": dati_dict.get("numero_documento", "1"),
        "data_documento": dati_dict.get("data_documento", datetime.today().strftime("%Y-%m-%d")),
        "codice_destinatario": cod_dest_val,
        "regime_fiscale": dati_dict.get("regime_fiscale", "RF01" if ced_p == "IT" else "RF18"),
        "cedente_denominazione": dati_dict.get("cedente_denominazione", "FORNITORE"),
        "cedente_paese": ced_p,
        "cedente_piva": dati_dict.get("cedente_piva", ""),
        "cedente_cf": dati_dict.get("cedente_cf", ""),
        "cedente_indirizzo": dati_dict.get("cedente_indirizzo", "Via Sede 1"),
        "cedente_cap": dati_dict.get("cedente_cap", "00100"),
        "cedente_comune": dati_dict.get("cedente_comune", "Roma"),
        "cedente_provincia": dati_dict.get("cedente_provincia", "RM" if ced_p == "IT" else ""),
        "cessionario_denominazione": dati_dict.get("cessionario_denominazione", "CLIENTE STUDIO"),
        "cessionario_paese": dati_dict.get("cessionario_paese", "IT") or "IT",
        "cessionario_piva": cess_p,
        "cessionario_cf": dati_dict.get("cessionario_cf", ""),
        "cessionario_indirizzo": dati_dict.get("cessionario_indirizzo", "Via Studio 10"),
        "cessionario_cap": dati_dict.get("cessionario_cap", "00100"),
        "cessionario_comune": dati_dict.get("cessionario_comune", "Roma"),
        "cessionario_provincia": dati_dict.get("cessionario_provincia", "RM"),
        "imponibile": imp,
        "aliquota_prevalente": aliq,
        "imposta": iva,
        "ritenuta": float(dati_dict.get("ritenuta", 0.0)),
        "totale_documento": float(dati_dict.get("totale_documento", 0.0)),
        "natura": nat,
        "iban": dati_dict.get("iban", ""),
        "data_scadenza": dati_dict.get("data_scadenza", dati_dict.get("data_documento")),
        "modalita_pagamento": dati_dict.get("modalita_pagamento", "MP05"),
        "riepilogo_iva": [{"aliquota": aliq, "imponibile": imp, "imposta": iva, "natura": nat.strip().upper()}],
        "linee": [{
            "descrizione": f"Prestazioni/Merci doc. n. {dati_dict.get('numero_documento', '1')}",
            "prezzo_totale": imp,
            "aliquota": aliq,
            "natura": nat.strip().upper() if aliq == 0.0 else ""
        }]
    }
    xml_str = genera_xml_teamsystem(payload)
    piva_trasm = str(cess_p or ("09847131217" if ced_p != "IT" else "00000000000")).strip().upper()
    if piva_trasm.startswith("IT") and len(piva_trasm) == 13:
        piva_trasm = piva_trasm[2:]
    nome_file = f"IT{piva_trasm}_00001.xml"
    return xml_str, nome_file, payload

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state["last_file_id"] != file_id or force_reparse:
        nome_f = uploaded_file.name.lower()
        with st.status("Acquisizione documento e generazione iniziale XML...", expanded=True) as status:
            file_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            
            if nome_f.endswith(".xml") or nome_f.endswith(".p7m"):
                dati, motore, testo_raw, err_ai = leggi_xml_fattura(file_bytes, uploaded_file.name)
            else:
                dati, motore, testo_raw, err_ai = estrai_dati_fattura(file_bytes, uploaded_file.name, api_key=api_key_input)
            
            st.session_state["invoice_data"] = dati
            st.session_state["motore_usato"] = motore
            st.session_state["testo_grezzo"] = testo_raw
            st.session_state["errore_ai"] = err_ai
            st.session_state["last_file_id"] = file_id
            
            # Generazione automatica iniziale
            xml_str_init, nome_xml_init, payload_init = genera_payload_e_xml(dati, codice_dest_default)
            st.session_state["xml_content"] = xml_str_init
            st.session_state["xml_filename"] = nome_xml_init
            
            # Verifica quadratura iniziale
            ok_init, errs_init = valida_quadratura_fiscale(
                payload_init["riepilogo_iva"], payload_init["totale_documento"], ritenuta=payload_init["ritenuta"]
            )
            st.session_state["validation_report"] = (ok_init, errs_init)
            
            status.update(label=f"✅ Elaborato con successo: {motore}", state="complete", expanded=False)
        st.rerun()

if st.session_state["invoice_data"] is None:
    st.info("👆 Carica una fattura per visualizzare i dati.")
    st.stop()

inv = st.session_state["invoice_data"]

if st.session_state.get("errore_ai"):
    st.warning(f"⚠️ Avviso: {st.session_state['errore_ai']}")

if inv.get("valuta") and str(inv.get("valuta")).upper() != "EUR":
    st.warning(f"💱 **Valuta estera rilevata ({inv['valuta']})**: verifica che gli importi siano convertiti in **EUR** prima di scaricare l'XML per SdI / TeamSystem.")

# ---------------------------------------------------------
# FASE 2: VERIFICA RAPIDA DEI SOGGETTI E INVERSIONE
# ---------------------------------------------------------
st.markdown("### 🔍 Verifica Soggetti Estratti (Human-in-the-Loop)")
df_rep = pd.DataFrame([
    {
        "Ruolo": "🏢 FORNITORE (Cedente - I miei dati per AdE)",
        "Denominazione": inv.get("cedente_denominazione", ""),
        "P.IVA / CF": inv.get("cedente_piva", "") or inv.get("cedente_cf", ""),
        "Nazione Sede": inv.get("cedente_paese", "IT"),
        "Sede": f"{inv.get('cedente_indirizzo', '')}, {inv.get('cedente_cap', '')} {inv.get('cedente_comune', '')} ({inv.get('cedente_provincia', '')})"
    },
    {
        "Ruolo": "👤 CLIENTE STUDIO (Cessionario / Committente)",
        "Denominazione": inv.get("cessionario_denominazione", ""),
        "P.IVA / CF": inv.get("cessionario_piva", "") or inv.get("cessionario_cf", ""),
        "Nazione Sede": inv.get("cessionario_paese", "IT"),
        "Sede": f"{inv.get('cessionario_indirizzo', '')}, {inv.get('cessionario_cap', '')} {inv.get('cessionario_comune', '')} ({inv.get('cessionario_provincia', '')})"
    }
])
st.data_editor(df_rep, use_container_width=True, disabled=True)

if st.button("🔄 Inverti Fornitore e Cliente (se scambiati)"):
    for c in ["denominazione", "paese", "piva", "cf", "indirizzo", "cap", "comune", "provincia"]:
        inv[f"cedente_{c}"], inv[f"cessionario_{c}"] = inv.get(f"cessionario_{c}", ""), inv.get(f"cedente_{c}", "")
    st.session_state["invoice_data"] = inv
    xml_agg, nome_agg, _ = genera_payload_e_xml(inv, codice_dest_default)
    st.session_state["xml_content"] = xml_agg
    st.session_state["xml_filename"] = nome_agg
    st.rerun()

st.markdown("---")

# ---------------------------------------------------------
# FASE 3: MODULO DI REVISIONE E MODIFICA DATI
# ---------------------------------------------------------
with st.form("form_revisione_totale"):
    st.markdown("#### 📄 1. Estremi del Documento & Tipo Tracciato")
    cd1, cd2, cd3, cd4 = st.columns(4)
    with cd1:
        tipo_doc_default = str(inv.get("tipo_documento") or "TD01")
        opzioni_td = ["TD01 - Fattura Ordinaria", "TD17 - Autofattura Estero (Invio SdI)", "TD04 - Nota di Credito", "TD24 - Fattura Differita"]
        idx_td = {"TD01": 0, "TD17": 1, "TD04": 2, "TD24": 3}.get(tipo_doc_default, 0)
        tipo_doc = st.selectbox("Tipo Documento", opzioni_td, index=idx_td).split(" - ")[0]
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
        st.markdown("**FORNITORE (Cedente / Prestatore - 'I miei dati' per AdE)**")
        ced_nome = st.text_input("Denominazione Fornitore", value=str(inv.get("cedente_denominazione", "")))
        
        c_p1, c_p2, c_p3 = st.columns([1, 2, 2])
        with c_p1:
            ced_paese = c_p1.text_input("Nazione", value=str(inv.get("cedente_paese") or "IT")[:2].upper(), max_chars=2, help="Richiesto da AdE (es. IT, FR, DE)")
        with c_p2:
            ced_piva = c_p2.text_input("Partita IVA Fornitore", value=str(inv.get("cedente_piva", "")))
        with c_p3:
            ced_cf = c_p3.text_input("Codice Fiscale Fornitore", value=str(inv.get("cedente_cf", "")))

        regime_fiscale_selezionato = st.selectbox(
            "Regime Fiscale Fornitore (Richiesto da AdE)",
            ["RF01 - Ordinario", "RF19 - Forfettario", "RF02 - Semplificato", "RF18 - Altro / Estero"],
            index=3 if ced_paese != "IT" else 0
        ).split(" - ")[0]

        ced_via = st.text_input("Indirizzo Fornitore", value=str(inv.get("cedente_indirizzo", "")))
        ci1, ci2, ci3 = st.columns([2, 3, 1])
        ced_cap = ci1.text_input("CAP Fornitore", value=str(inv.get("cedente_cap", "00100")), max_chars=12)
        ced_com = ci2.text_input("Comune Fornitore", value=str(inv.get("cedente_comune", "Roma")))
        ced_prov = ci3.text_input("Prov.", value=str(inv.get("cedente_provincia", "RM" if ced_paese == "IT" else ""))[:2].upper(), max_chars=2)

    with col_cess:
        st.markdown("**CLIENTE STUDIO (Cessionario / Committente)**")
        cess_nome = st.text_input("Denominazione Cliente", value=str(inv.get("cessionario_denominazione", "")))
        
        cs_p1, cs_p2, cs_p3 = st.columns([1, 2, 2])
        with cs_p1:
            cess_paese = cs_p1.text_input("Nazione Cliente", value=str(inv.get("cessionario_paese") or "IT")[:2].upper(), max_chars=2)
        with cs_p2:
            cess_piva = cs_p2.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")))
        with cs_p3:
            cess_cf = cs_p3.text_input("Codice Fiscale Cliente", value=str(inv.get("cessionario_cf", "")))

        cess_via = st.text_input("Indirizzo Sede Cliente", value=str(inv.get("cessionario_indirizzo", "")))
        cs1, cs2, cs3 = st.columns([2, 3, 1])
        cess_cap = cs1.text_input("CAP Cliente", value=str(inv.get("cessionario_cap", "00100")), max_chars=5)
        cess_com = cs2.text_input("Comune Cliente", value=str(inv.get("cessionario_comune", "Roma")))
        cess_prov = cs3.text_input("Prov. Cliente", value=str(inv.get("cessionario_provincia", "RM"))[:2].upper(), max_chars=2)

    st.markdown("---")
    st.markdown("#### 🏦 3. Riconciliazione Bancaria CONSPAY")
    cp1, cp2, cp3 = st.columns([2, 1, 1])
    with cp1:
        iban_doc = st.text_input("IBAN Accredito Fornitore", value=str(inv.get("iban", "")), help="Mappato nel blocco DatiPagamento per CONSPAY.")
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
    st.markdown("#### 💰 4. Sezione Contabile, IVA & Ritenuta")
    ce1, ce2, ce3, ce4 = st.columns(4)
    with ce1:
        imponibile_1 = st.number_input("Imponibile Netto (€)", value=float(inv.get("imponibile", 0.0)), step=0.01)
    with ce2:
        aliquota_1 = st.number_input("Aliquota IVA (%)", value=float(inv.get("aliquota_prevalente", 22.0)), step=1.0)
    with ce3:
        imposta_1 = st.number_input("Imposta IVA (€)", value=float(inv.get("imposta", 0.0)), step=0.01)
    with ce4:
        ritenuta_1 = st.number_input("Ritenuta d'Acconto (€)", value=float(inv.get("ritenuta", 0.0)), step=0.01)

    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        natura_default = str(inv.get("natura") or ("N3.2" if (ced_paese != "IT" and aliquota_1 == 0.0) else ""))
        natura_iva = st.text_input("Natura (se IVA 0%, es. N3.2 per Fornitori UE)", value=natura_default)
    with col_t2:
        totale_doc = st.number_input("Totale a Pagare (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01)

    # Feedback Live di Quadratura
    lordo_live = round(imponibile_1 + imposta_1, 2)
    netto_live = round(lordo_live - ritenuta_1, 2)
    diff_live = min(abs(netto_live - totale_doc), abs(lordo_live - totale_doc))

    if diff_live <= 0.02:
        st.success(f"🟢 **Quadratura Verificata**: {imponibile_1:.2f}€ + {imposta_1:.2f}€" + (f" - {ritenuta_1:.2f}€" if ritenuta_1 > 0 else "") + f" = {totale_doc:.2f}€")
    else:
        st.warning(f"🟡 **Scostamento**: Netto calcolato {netto_live:.2f}€ vs inserito {totale_doc:.2f}€")

    btn_submit = st.form_submit_button("💾 Aggiorna Modifiche e Rigenera XML", type="primary", use_container_width=True)

# ---------------------------------------------------------
# FASE 4: AGGIORNAMENTO DATI IN SESSIONE E RIGENERAZIONE
# ---------------------------------------------------------
if btn_submit:
    inv["tipo_documento"] = tipo_doc
    inv["numero_documento"] = num_doc
    inv["data_documento"] = data_doc.strftime("%Y-%m-%d")
    inv["codice_destinatario"] = cod_sdi
    inv["regime_fiscale"] = regime_fiscale_selezionato
    inv["cedente_denominazione"] = ced_nome
    inv["cedente_paese"] = ced_paese if ced_paese else "IT"
    inv["cedente_piva"] = ced_piva
    inv["cedente_cf"] = ced_cf
    inv["cedente_indirizzo"] = ced_via
    inv["cedente_cap"] = ced_cap
    inv["cedente_comune"] = ced_com
    inv["cedente_provincia"] = ced_prov if ced_paese == "IT" else ""
    inv["cessionario_denominazione"] = cess_nome
    inv["cessionario_paese"] = cess_paese if cess_paese else "IT"
    inv["cessionario_piva"] = cess_piva
    inv["cessionario_cf"] = cess_cf
    inv["cessionario_indirizzo"] = cess_via
    inv["cessionario_cap"] = cess_cap
    inv["cessionario_comune"] = cess_com
    inv["cessionario_provincia"] = cess_prov
    inv["imponibile"] = imponibile_1
    inv["aliquota_prevalente"] = aliquota_1
    inv["imposta"] = imposta_1
    inv["ritenuta"] = ritenuta_1
    inv["totale_documento"] = totale_doc
    inv["natura"] = natura_iva
    inv["iban"] = iban_doc
    inv["data_scadenza"] = scadenza_pag.strftime("%Y-%m-%d")
    inv["modalita_pagamento"] = metodo_pag
    
    st.session_state["invoice_data"] = inv

    xml_nuovo, nome_nuovo, payload_nuovo = genera_payload_e_xml(inv, cod_sdi)
    st.session_state["xml_content"] = xml_nuovo
    st.session_state["xml_filename"] = nome_nuovo

    quadratura_ok, errs = valida_quadratura_fiscale(
        payload_nuovo["riepilogo_iva"], payload_nuovo["totale_documento"], ritenuta=payload_nuovo["ritenuta"]
    )
    segnalazioni = []
    if ced_piva and not valida_partita_iva(ced_piva, ced_paese):
        segnalazioni.append(f"P.IVA Fornitore '{ced_piva}' ({ced_paese}) non valida.")
    if cess_piva and not valida_partita_iva(cess_piva, cess_paese):
        segnalazioni.append(f"P.IVA Cliente '{cess_piva}' ({cess_paese}) non valida.")
    
    st.session_state["validation_report"] = (quadratura_ok and len(segnalazioni) == 0, segnalazioni + errs)
    st.session_state["xml_aggiornato"] = True

# ---------------------------------------------------------
# FASE 5: AREA DI DOWNLOAD POST-CONFERMA (SUBITO SOTTO)
# ---------------------------------------------------------
if st.session_state.get("xml_content"):
    st.markdown("---")
    st.subheader("📦 Area di Download File Conforme SdI")
    
    if st.session_state.get("xml_aggiornato"):
        st.success("✅ **Modifiche salvate e XML rigenerato con successo!**")

    is_ok, anomalie = st.session_state.get("validation_report") or (True, [])
    
    c_down1, c_down2 = st.columns([2, 1])
    with c_down1:
        if is_ok:
            st.success(f"✅ **Quadratura e Dati Fiscali Validi**: File `{st.session_state['xml_filename']}` conforme AdE / SdI.")
        else:
            st.warning("⚠️ **Segnalazioni contabili:**")
            for a in anomalie:
                st.write(f"- {a}")

    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(st.session_state["xml_filename"], st.session_state["xml_content"].encode("utf-8"))
        if uploaded_file is not None:
            uploaded_file.seek(0)
            z.writestr(uploaded_file.name, uploaded_file.read())
    zip_bytes.seek(0)

    with c_down2:
        st.download_button(
            label="💾 SCARICA FILE XML ORA",
            data=st.session_state["xml_content"].encode("utf-8"),
            file_name=st.session_state["xml_filename"],
            mime="application/octet-stream",
            key="btn_download_diretto",
            use_container_width=True,
            type="primary"
        )
        st.download_button(
            label="🗂️ SCARICA PACCHETTO ZIP (PDF + XML)",
            data=zip_bytes.getvalue(),
            file_name=f"Fattura_{st.session_state['xml_filename'].replace('.xml', '')}.zip",
            mime="application/zip",
            key="btn_download_zip_diretto",
            use_container_width=True
        )

    with st.expander("🔍 Visualizza e Copia Testo XML"):
        st.code(st.session_state["xml_content"], language="xml")
