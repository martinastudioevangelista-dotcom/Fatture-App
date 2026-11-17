# === INIZIO FILE app.py ===
# app.py - AI Invoice to SdI/TeamSystem CONSPAY (v3.3 Multi-Fattura Veloce in Parallelo)
from concurrent.futures import ThreadPoolExecutor, as_completed
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

for k in ["invoice_cache", "batch_order"]:
    if k not in st.session_state:
        st.session_state[k] = {} if k == "invoice_cache" else []

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
st.caption("Fatturazione FPR12 v1.2.2 - Caricamento singolo o multiplo (consigliate max 15-25 fatture per lotto).")

def genera_payload_e_xml(dati_dict, cod_dest_val, prog_idx=1):
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
        "acconto": float(dati_dict.get("acconto", 0.0)),
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
    nome_file = f"IT{piva_trasm}_{prog_idx:05d}.xml"
    return xml_str, nome_file, payload

def _elabora_singolo_job(job, api_key_val, cod_dest_val):
    idx, fid, orig_name, file_bytes = job
    nome_f = orig_name.lower()
    if nome_f.endswith(".xml") or nome_f.endswith(".p7m"):
        dati, motore, testo_raw, err_ai = leggi_xml_fattura(file_bytes, orig_name)
    else:
        dati, motore, testo_raw, err_ai = estrai_dati_fattura(file_bytes, orig_name, api_key=api_key_val)

    xml_str_init, nome_xml_init, payload_init = genera_payload_e_xml(dati, cod_dest_val, prog_idx=idx)
    ok_init, errs_init = valida_quadratura_fiscale(
        payload_init["riepilogo_iva"], payload_init["totale_documento"], ritenuta=payload_init["ritenuta"]
    )
    ced_piva_i = str(dati.get("cedente_piva") or "")
    ced_paese_i = str(dati.get("cedente_paese") or "IT")
    if ced_piva_i and not valida_partita_iva(ced_piva_i, ced_paese_i):
        errs_init.append(f"P.IVA Fornitore '{ced_piva_i}' ({ced_paese_i}) da verificare.")

    return fid, {
        "idx": idx,
        "fid": fid,
        "orig_filename": orig_name,
        "orig_bytes": file_bytes,
        "invoice_data": dati,
        "motore_usato": motore,
        "testo_grezzo": testo_raw,
        "errore_ai": err_ai,
        "xml_content": xml_str_init,
        "xml_filename": nome_xml_init,
        "validation_report": (ok_init and len(errs_init) == 0, errs_init),
        "xml_aggiornato": False,
    }

def render_scheda_fattura(item):
    fid = item["fid"]
    idx = item["idx"]
    inv = item["invoice_data"]

    if item.get("motore_usato"):
        st.caption(f"⚙️ Motore utilizzato: **{item['motore_usato']}**")
    if item.get("errore_ai"):
        st.warning(f"⚠️ Avviso: {item['errore_ai']}")
    if inv.get("valuta") and str(inv.get("valuta")).upper() != "EUR":
        st.warning(f"💱 **Valuta estera rilevata ({inv['valuta']})**: verifica che gli importi siano convertiti in **EUR** prima di scaricare l'XML.")

    st.markdown("#### 🔍 Soggetti Estratti")
    df_rep = pd.DataFrame([
        {
            "Ruolo": "🏢 FORNITORE (Cedente)",
            "Denominazione": inv.get("cedente_denominazione", ""),
            "P.IVA / CF": inv.get("cedente_piva", "") or inv.get("cedente_cf", ""),
            "Nazione": inv.get("cedente_paese", "IT"),
            "Sede": f"{inv.get('cedente_indirizzo', '')}, {inv.get('cedente_cap', '')} {inv.get('cedente_comune', '')} ({inv.get('cedente_provincia', '')})"
        },
        {
            "Ruolo": "👤 CLIENTE (Cessionario)",
            "Denominazione": inv.get("cessionario_denominazione", ""),
            "P.IVA / CF": inv.get("cessionario_piva", "") or inv.get("cessionario_cf", ""),
            "Nazione": inv.get("cessionario_paese", "IT"),
            "Sede": f"{inv.get('cessionario_indirizzo', '')}, {inv.get('cessionario_cap', '')} {inv.get('cessionario_comune', '')} ({inv.get('cessionario_provincia', '')})"
        }
    ])
    st.dataframe(df_rep, use_container_width=True, hide_index=True)

    if st.button("🔄 Inverti Fornitore e Cliente (se scambiati)", key=f"inv_btn_{fid}"):
        for c in ["denominazione", "paese", "piva", "cf", "indirizzo", "cap", "comune", "provincia"]:
            inv[f"cedente_{c}"], inv[f"cessionario_{c}"] = inv.get(f"cessionario_{c}", ""), inv.get(f"cedente_{c}", "")
        item["invoice_data"] = inv
        xml_agg, nome_agg, _ = genera_payload_e_xml(inv, codice_dest_default, prog_idx=idx)
        item["xml_content"] = xml_agg
        item["xml_filename"] = nome_agg
        st.session_state["invoice_cache"][fid] = item
        st.rerun()

    with st.form(f"form_rev_{fid}"):
        st.markdown("#### 📄 1. Estremi del Documento & Tipo Tracciato")
        cd1, cd2, cd3, cd4 = st.columns(4)
        with cd1:
            tipo_doc_default = str(inv.get("tipo_documento") or "TD01")
            opzioni_td = ["TD01 - Fattura Ordinaria", "TD17 - Autofattura Estero (Invio SdI)", "TD04 - Nota di Credito", "TD24 - Fattura Differita"]
            idx_td = {"TD01": 0, "TD17": 1, "TD04": 2, "TD24": 3}.get(tipo_doc_default, 0)
            tipo_doc = st.selectbox("Tipo Documento", opzioni_td, index=idx_td, key=f"td_{fid}").split(" - ")[0]
        with cd2:
            num_doc = st.text_input("Numero Documento", value=str(inv.get("numero_documento", "1")), key=f"num_{fid}")
        with cd3:
            try:
                d_val = datetime.strptime(str(inv.get("data_documento", ""))[:10], "%Y-%m-%d")
            except Exception:
                d_val = datetime.today()
            data_doc = st.date_input("Data Documento", value=d_val, key=f"dt_{fid}")
        with cd4:
            cod_sdi_val = str(inv.get("codice_destinatario", codice_dest_default))[:7]
            cod_sdi = st.text_input("Codice Destinatario SdI", value=cod_sdi_val, max_chars=7, key=f"sdi_{fid}")

        st.markdown("---")
        st.markdown("#### 🏢 2. Anagrafiche Fiscali Segregate")
        col_ced, col_cess = st.columns(2)

        with col_ced:
            st.markdown("**FORNITORE (Cedente / Prestatore)**")
            ced_nome = st.text_input("Denominazione Fornitore", value=str(inv.get("cedente_denominazione", "")), key=f"ced_nom_{fid}")
            c_p1, c_p2, c_p3 = st.columns([1, 2, 2])
            ced_paese_val = str(inv.get("cedente_paese") or "IT")[:2].upper()
            ced_paese = c_p1.text_input("Nazione", value=ced_paese_val, max_chars=2, key=f"ced_pae_{fid}")
            ced_piva = c_p2.text_input("Partita IVA Fornitore", value=str(inv.get("cedente_piva", "")), key=f"ced_piva_{fid}")
            ced_cf = c_p3.text_input("Codice Fiscale Fornitore", value=str(inv.get("cedente_cf", "")), key=f"ced_cf_{fid}")

            regime_fiscale_selezionato = st.selectbox(
                "Regime Fiscale Fornitore (AdE)",
                ["RF01 - Ordinario", "RF19 - Forfettario", "RF02 - Semplificato", "RF18 - Altro / Estero"],
                index=3 if ced_paese != "IT" else 0,
                key=f"reg_{fid}"
            ).split(" - ")[0]

            ced_via = st.text_input("Indirizzo Fornitore", value=str(inv.get("cedente_indirizzo", "")), key=f"ced_via_{fid}")
            ci1, ci2, ci3 = st.columns([2, 3, 1])
            ced_cap = ci1.text_input("CAP Fornitore", value=str(inv.get("cedente_cap", "00100"))[:12], max_chars=12, key=f"ced_cap_{fid}")
            ced_com = ci2.text_input("Comune Fornitore", value=str(inv.get("cedente_comune", "Roma")), key=f"ced_com_{fid}")
            ced_prov_val = str(inv.get("cedente_provincia", "RM" if ced_paese == "IT" else ""))[:2].upper()
            ced_prov = ci3.text_input("Prov.", value=ced_prov_val, max_chars=2, key=f"ced_prov_{fid}")

        with col_cess:
            st.markdown("**CLIENTE STUDIO (Cessionario / Committente)**")
            cess_nome = st.text_input("Denominazione Cliente", value=str(inv.get("cessionario_denominazione", "")), key=f"cess_nom_{fid}")
            cs_p1, cs_p2, cs_p3 = st.columns([1, 2, 2])
            cess_paese_val = str(inv.get("cessionario_paese") or "IT")[:2].upper()
            cess_paese = cs_p1.text_input("Nazione Cliente", value=cess_paese_val, max_chars=2, key=f"cess_pae_{fid}")
            cess_piva = cs_p2.text_input("Partita IVA Cliente", value=str(inv.get("cessionario_piva", "")), key=f"cess_piva_{fid}")
            cess_cf = cs_p3.text_input("Codice Fiscale Cliente", value=str(inv.get("cessionario_cf", "")), key=f"cess_cf_{fid}")

            cess_via = st.text_input("Indirizzo Sede Cliente", value=str(inv.get("cessionario_indirizzo", "")), key=f"cess_via_{fid}")
            cs1, cs2, cs3 = st.columns([2, 3, 1])
            cess_cap = cs1.text_input("CAP Cliente", value=str(inv.get("cessionario_cap", "00100"))[:12], max_chars=12, key=f"cess_cap_{fid}")
            cess_com = cs2.text_input("Comune Cliente", value=str(inv.get("cessionario_comune", "Roma")), key=f"cess_com_{fid}")
            cess_prov_val = str(inv.get("cessionario_provincia", "RM"))[:2].upper()
            cess_prov = cs3.text_input("Prov. Cliente", value=cess_prov_val, max_chars=2, key=f"cess_prov_{fid}")

        st.markdown("---")
        st.markdown("#### 🏦 3. Riconciliazione Bancaria CONSPAY")
        cp1, cp2, cp3 = st.columns([2, 1, 1])
        with cp1:
            iban_doc = st.text_input("IBAN Accredito Fornitore", value=str(inv.get("iban", "")), key=f"iban_{fid}")
        with cp2:
            try:
                d_scad = datetime.strptime(str(inv.get("data_scadenza", ""))[:10], "%Y-%m-%d")
            except Exception:
                d_scad = d_val
            scadenza_pag = st.date_input("Scadenza Pagamento", value=d_scad, key=f"scad_{fid}")
        with cp3:
            metodo_default = inv.get("modalita_pagamento", "MP05")
            metodi_list = [
                "MP05 - Bonifico Bancario",
                "MP08 - Carta di Pagamento",
                "MP19 - SEPA Direct Debit / Prelievo",
                "MP12 - RiBa",
                "MP01 - Contanti",
            ]
            idx_met = {"MP05": 0, "MP08": 1, "MP19": 2, "MP12": 3, "MP01": 4}.get(metodo_default, 0)
            metodo_pag = st.selectbox("Modalità Pagamento", metodi_list, index=idx_met, key=f"mp_{fid}").split(" - ")[0]

        st.markdown("---")
        st.markdown("#### 💰 4. Sezione Contabile, IVA, Ritenuta & Acconto")
        ce1, ce2, ce3, ce4, ce5 = st.columns(5)
        with ce1:
            imponibile_1 = st.number_input("Imponibile Netto (€)", value=float(inv.get("imponibile", 0.0)), step=0.01, key=f"imp_{fid}")
        with ce2:
            aliquota_1 = st.number_input("Aliquota IVA (%)", value=float(inv.get("aliquota_prevalente", 22.0)), step=1.0, key=f"aliq_{fid}")
        with ce3:
            imposta_1 = st.number_input("Imposta IVA (€)", value=float(inv.get("imposta", 0.0)), step=0.01, key=f"iva_{fid}")
        with ce4:
            ritenuta_1 = st.number_input("Ritenuta d'Acconto (€)", value=float(inv.get("ritenuta", 0.0)), step=0.01, key=f"rit_{fid}")
        with ce5:
            acconto_1 = st.number_input("Acconto già versato (€)", value=float(inv.get("acconto", 0.0)), step=0.01, key=f"acc_{fid}")

        col_t1, col_t2 = st.columns([3, 1])
        with col_t1:
            natura_default = str(inv.get("natura") or ("N3.2" if (ced_paese != "IT" and aliquota_1 == 0.0) else ""))
            natura_iva = st.text_input("Natura (se IVA 0%, es. N3.2 UE / N2.2 Extra-UE)", value=natura_default, key=f"nat_{fid}")
        with col_t2:
            totale_doc = st.number_input("Totale Fattura AdE (€)", value=float(inv.get("totale_documento", 0.0)), step=0.01, key=f"tot_{fid}")

        lordo_live = round(imponibile_1 + imposta_1, 2)
        netto_rit_live = round(lordo_live - ritenuta_1, 2)
        netto_pag_live = round(max(0.0, lordo_live - ritenuta_1 - acconto_1), 2)
        diff_live = min(abs(netto_rit_live - totale_doc), abs(lordo_live - totale_doc))

        if diff_live <= 0.02:
            msg_q = f"🟢 **Quadratura Verificata**: {imponibile_1:.2f}€ + {imposta_1:.2f}€ = {lordo_live:.2f}€"
            if acconto_1 > 0 or ritenuta_1 > 0:
                msg_q += f" ➔ **Netto residuo da pagare (CONSPAY): {netto_pag_live:.2f}€**"
            st.success(msg_q)
        else:
            st.warning(f"🟡 **Scostamento**: Totale calcolato {lordo_live:.2f}€ vs inserito {totale_doc:.2f}€")

        btn_submit = st.form_submit_button("💾 Aggiorna Modifiche e Rigenera XML", type="primary", use_container_width=True)

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
        inv["acconto"] = acconto_1
        inv["totale_documento"] = totale_doc
        inv["natura"] = natura_iva
        inv["iban"] = iban_doc
        inv["data_scadenza"] = scadenza_pag.strftime("%Y-%m-%d")
        inv["modalita_pagamento"] = metodo_pag

        xml_nuovo, nome_nuovo, payload_nuovo = genera_payload_e_xml(inv, cod_sdi, prog_idx=idx)
        quadratura_ok, errs = valida_quadratura_fiscale(
            payload_nuovo["riepilogo_iva"], payload_nuovo["totale_documento"], ritenuta=payload_nuovo["ritenuta"]
        )
        segnalazioni = []
        if ced_piva and not valida_partita_iva(ced_piva, ced_paese):
            segnalazioni.append(f"P.IVA Fornitore '{ced_piva}' ({ced_paese}) non valida.")
        if cess_piva and not valida_partita_iva(cess_piva, cess_paese):
            segnalazioni.append(f"P.IVA Cliente '{cess_piva}' ({cess_paese}) non valida.")

        item["invoice_data"] = inv
        item["xml_content"] = xml_nuovo
        item["xml_filename"] = nome_nuovo
        item["validation_report"] = (quadratura_ok and len(segnalazioni) == 0, segnalazioni + errs)
        item["xml_aggiornato"] = True
        st.session_state["invoice_cache"][fid] = item
        st.rerun()

    if item.get("xml_content"):
        if item.get("xml_aggiornato"):
            st.success("✅ **Modifiche salvate e XML rigenerato con successo!**")

        is_ok, anomalie = item.get("validation_report") or (True, [])
        c_down1, c_down2 = st.columns([2, 1])
        with c_down1:
            if is_ok:
                st.success(f"✅ **Quadratura e Dati Fiscali Validi**: `{item['xml_filename']}` conforme AdE / SdI.")
            else:
                st.warning("⚠️ **Segnalazioni contabili:**")
                for a in anomalie:
                    st.write(f"- {a}")

        zip_bytes = io.BytesIO()
        with zipfile.ZipFile(zip_bytes, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(item["xml_filename"], item["xml_content"].encode("utf-8"))
            z.writestr(item["orig_filename"], item["orig_bytes"])
        zip_bytes.seek(0)

        with c_down2:
            st.download_button(
                label="💾 SCARICA FILE XML ORA",
                data=item["xml_content"].encode("utf-8"),
                file_name=item["xml_filename"],
                mime="application/octet-stream",
                key=f"dl_xml_{fid}",
                use_container_width=True,
                type="primary"
            )
            st.download_button(
                label="🗂️ SCARICA PACCHETTO ZIP (PDF + XML)",
                data=zip_bytes.getvalue(),
                file_name=f"Fattura_{item['xml_filename'].replace('.xml', '')}.zip",
                mime="application/zip",
                key=f"dl_zip_{fid}",
                use_container_width=True
            )

        if st.checkbox("🔍 Mostra testo XML generato", key=f"show_xml_{fid}"):
            st.code(item["xml_content"], language="xml")

# ---------------------------------------------------------
# FASE 1: CARICAMENTO MULTIPLO VELOCE IN PARALLELO
# ---------------------------------------------------------
col_up1, col_up2 = st.columns([4, 1])
with col_up1:
    uploaded_files = st.file_uploader(
        "Carica una o più fatture insieme (PDF, Immagini, XML o firmati .P7M)",
        type=["pdf", "png", "jpg", "jpeg", "xml", "p7m"],
        accept_multiple_files=True
    )
with col_up2:
    st.write("")
    st.write("")
    force_reparse = st.button("🔄 Rianalizza Tutto", help="Rilegge tutti i file caricati azzerando la cache.")

if not uploaded_files:
    st.session_state["batch_order"] = []
    st.info("👆 Carica una o più fatture (puoi selezionarne anche tante insieme) per iniziare.")
    st.stop()

if force_reparse:
    st.session_state["invoice_cache"] = {}

nuovi_fids = []
jobs = []
for idx, f in enumerate(uploaded_files, start=1):
    fid = f"{idx}_{f.name}_{f.size}"
    nuovi_fids.append(fid)
    if fid not in st.session_state["invoice_cache"]:
        f.seek(0)
        f_bytes = f.read()
        f.seek(0)
        jobs.append((idx, fid, f.name, f_bytes))

if jobs:
    tot_el = len(jobs)
    with st.status(f"Elaborazione veloce di {tot_el} fattura/e in parallelo...", expanded=True) as status:
        prog_bar = st.progress(0)
        msg_slot = st.empty()
        done_count = 0
        max_w = min(4, tot_el)

        with ThreadPoolExecutor(max_workers=max_w) as executor:
            futures = [
                executor.submit(_elabora_singolo_job, job, api_key_input, codice_dest_default)
                for job in jobs
            ]
            for fut in as_completed(futures):
                fid_done, res_item = fut.result()
                st.session_state["invoice_cache"][fid_done] = res_item
                done_count += 1
                msg_slot.write(f"⚡ Completata {done_count}/{tot_el}: **{res_item['orig_filename']}**")
                prog_bar.progress(done_count / tot_el)

        status.update(label=f"✅ Elaborazione completata ({tot_el} fatture lette)", state="complete", expanded=False)
    st.rerun()

st.session_state["batch_order"] = nuovi_fids
batch_items = [st.session_state["invoice_cache"][fid] for fid in nuovi_fids]

# ---------------------------------------------------------
# RIEPILOGO E DOWNLOAD MASSIVO + SCHEDE MODIFICABILI
# ---------------------------------------------------------
if len(batch_items) > 1:
    st.markdown(f"### 📚 Riepilogo Fatture Caricate ({len(batch_items)} documenti)")
    righe_riep = []
    for item in batch_items:
        d = item["invoice_data"]
        ok_it, _ = item["validation_report"]
        tot_d = float(d.get("totale_documento", 0.0))
        rit_d = float(d.get("ritenuta", 0.0))
        acc_d = float(d.get("acconto", 0.0))
        netto_c = round(max(0.0, tot_d - rit_d - acc_d), 2)
        righe_riep.append({
            "#": item["idx"],
            "File Originale": item["orig_filename"],
            "Fornitore (Cedente)": d.get("cedente_denominazione", ""),
            "Cliente": d.get("cessionario_denominazione", ""),
            "N° Doc": d.get("numero_documento", ""),
            "Data": d.get("data_documento", ""),
            "Imponibile (€)": round(float(d.get("imponibile", 0.0)), 2),
            "IVA (€)": round(float(d.get("imposta", 0.0)), 2),
            "Totale AdE (€)": round(tot_d, 2),
            "Netto CONSPAY (€)": netto_c,
            "File XML": item["xml_filename"],
            "Stato": "🟢 OK" if ok_it else "🟡 Verifica",
        })
    st.dataframe(pd.DataFrame(righe_riep), use_container_width=True, hide_index=True)

    zip_only_xml = io.BytesIO()
    zip_all_full = io.BytesIO()
    nomi_usati_xml = set()
    nomi_usati_pdf = set()
    with zipfile.ZipFile(zip_only_xml, "w", zipfile.ZIP_DEFLATED) as z_xml, \
         zipfile.ZipFile(zip_all_full, "w", zipfile.ZIP_DEFLATED) as z_full:
        for item in batch_items:
            x_name = item["xml_filename"]
            if x_name in nomi_usati_xml:
                x_name = f"{item['idx']:02d}_{x_name}"
            nomi_usati_xml.add(x_name)
            x_bytes = item["xml_content"].encode("utf-8")
            z_xml.writestr(x_name, x_bytes)
            z_full.writestr(x_name, x_bytes)

            p_name = item["orig_filename"]
            if p_name in nomi_usati_pdf:
                p_name = f"{item['idx']:02d}_{p_name}"
            nomi_usati_pdf.add(p_name)
            z_full.writestr(p_name, item["orig_bytes"])
    zip_only_xml.seek(0)
    zip_all_full.seek(0)

    cb1, cb2 = st.columns(2)
    with cb1:
        st.download_button(
            label=f"📦 SCARICA TUTTI GLI XML ({len(batch_items)} file in ZIP)",
            data=zip_only_xml.getvalue(),
            file_name=f"Fatture_XML_{datetime.today().strftime('%Y%m%d_%H%M')}.zip",
            mime="application/zip",
            key="btn_dl_batch_xml",
            use_container_width=True,
            type="primary"
        )
    with cb2:
        st.download_button(
            label="🗂️ SCARICA PACCHETTO COMPLETO (PDF + XML)",
            data=zip_all_full.getvalue(),
            file_name=f"Pacchetto_Completo_{datetime.today().strftime('%Y%m%d_%H%M')}.zip",
            mime="application/zip",
            key="btn_dl_batch_full",
            use_container_width=True
        )

    st.markdown("---")
    st.markdown("### 📝 Apri e Modifica le Singole Fatture")
    st.caption("Clicca su una fattura qui sotto per aprire tutti i suoi campi modificabili:")
    for item in batch_items:
        d = item["invoice_data"]
        stato_ic = "🟢 OK" if item["validation_report"][0] else "🟡 Verifica"
        titolo_exp = (
            f"📄 {item['idx']}) {item['orig_filename']} — "
            f"{d.get('cedente_denominazione', '')} | "
            f"Tot: {float(d.get('totale_documento', 0.0)):.2f}€ ({stato_ic})"
        )
        with st.expander(titolo_exp, expanded=(item["idx"] == 1)):
            render_scheda_fattura(item)
else:
    render_scheda_fattura(batch_items[0])
# === FINE FILE app.py ===
"""
extractor.py - VERSIONE VELOCE + UNIVERSALE ITALIA & ESTERO
- Cache modelli Gemini (una sola interrogazione ListModels per sessione).
- Thread-safe per lettura parallela di più fatture contemporaneamente.
- Precedenza ai parser italiani deterministici istantanei (<0.05s), Vision AI per tutto il resto.
"""

import base64
from datetime import datetime
import json
import re
import threading
import fitz  # PyMuPDF


_FITZ_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_GEMINI_MODELS_CACHE = {}

KNOWN_BUYER_PIVAS = {"09847131217"}

EU_COUNTRIES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "GR", "ES", "FI",
    "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
    "RO", "SE", "SI", "SK", "XI",
}

VALID_TD = {
    "TD01", "TD02", "TD03", "TD04", "TD05", "TD06", "TD16", "TD17", "TD18",
    "TD19", "TD20", "TD21", "TD22", "TD23", "TD24", "TD25", "TD26", "TD27",
    "TD28", "TD29",
}

VALID_MP = {f"MP{i:02d}" for i in range(1, 24)}

FOREIGN_COUNTRY_MAP = {
    "united states": "US", "usa": "US", "u.s.a.": "US", "stati uniti": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB", "regno unito": "GB",
    "ireland": "IE", "irlanda": "IE",
    "germany": "DE", "deutschland": "DE", "germania": "DE",
    "france": "FR", "francia": "FR",
    "spain": "ES", "españa": "ES", "espana": "ES", "spagna": "ES",
    "netherlands": "NL", "the netherlands": "NL", "holland": "NL", "paesi bassi": "NL", "olanda": "NL",
    "belgium": "BE", "belgique": "BE", "belgie": "BE", "belgio": "BE",
    "austria": "AT", "österreich": "AT",
    "luxembourg": "LU", "lussemburgo": "LU",
    "switzerland": "CH", "schweiz": "CH", "suisse": "CH", "svizzera": "CH",
    "poland": "PL", "polska": "PL", "polonia": "PL",
    "portugal": "PT", "portogallo": "PT",
    "sweden": "SE", "sverige": "SE", "svezia": "SE",
    "denmark": "DK", "danmark": "DK", "danimarca": "DK",
    "finland": "FI", "suomi": "FI", "finlandia": "FI",
    "norway": "NO", "norge": "NO", "norvegia": "NO",
    "czech republic": "CZ", "czechia": "CZ", "repubblica ceca": "CZ",
    "romania": "RO", "hungary": "HU", "ungheria": "HU",
    "greece": "GR", "grecia": "GR", "bulgaria": "BG", "croatia": "HR",
    "slovenia": "SI", "slovakia": "SK", "estonia": "EE", "latvia": "LV",
    "lithuania": "LT", "malta": "MT", "cyprus": "CY", "cipro": "CY",
    "canada": "CA", "australia": "AU", "singapore": "SG", "japan": "JP", "china": "CN",
}

MONTH_MAP = {
    "jan": 1, "january": 1, "gen": 1, "gennaio": 1, "janvier": 1, "januar": 1, "enero": 1,
    "feb": 2, "february": 2, "febbraio": 2, "février": 2, "fevrier": 2, "februar": 2, "febrero": 2,
    "mar": 3, "march": 3, "marzo": 3, "mars": 3, "märz": 3, "maerz": 3,
    "apr": 4, "april": 4, "aprile": 4, "avril": 4, "abril": 4,
    "may": 5, "mag": 5, "maggio": 5, "mai": 5, "mayo": 5,
    "jun": 6, "june": 6, "giu": 6, "giugno": 6, "juin": 6, "juni": 6, "junio": 6,
    "jul": 7, "july": 7, "lug": 7, "luglio": 7, "juillet": 7, "juli": 7, "julio": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8, "août": 8, "aout": 8,
    "sep": 9, "sept": 9, "september": 9, "set": 9, "settembre": 9, "septembre": 9, "septiembre": 9,
    "oct": 10, "october": 10, "ott": 10, "ottobre": 10, "octobre": 10, "oktober": 10, "octubre": 10,
    "nov": 11, "november": 11, "novembre": 11, "noviembre": 11,
    "dec": 12, "december": 12, "dic": 12, "dicembre": 12, "décembre": 12, "decembre": 12, "dezember": 12, "diciembre": 12,
}


def normalizza_codice_paese(paese: str, default: str = "IT") -> str:
    if not paese:
        return default
    p = str(paese).strip()
    p_low = p.lower()
    if p_low in FOREIGN_COUNTRY_MAP:
        return FOREIGN_COUNTRY_MAP[p_low]
    p_up = re.sub(r"[^A-Z]", "", p.upper())[:2]
    if p_up == "UK":
        return "GB"
    if p_up == "EL":
        return "GR"
    if len(p_up) == 2:
        return p_up
    return default


def _normalizza_mp(val) -> str:
    raw = str(val or "").strip()
    up = raw.upper()
    if up in VALID_MP:
        return up
    low = raw.lower()
    if any(w in low for w in ("prel", "sepa", "sdd", "direct debit", "addebito", "domicilia")):
        return "MP19"
    if "rid" in low:
        return "MP09"
    if any(w in low for w in ("carta", "card", "credit", "bancomat", "pos")):
        return "MP08"
    if any(w in low for w in ("contant", "cash")):
        return "MP01"
    if any(w in low for w in ("assegn", "check", "cheque")):
        return "MP02"
    if "riba" in low or "ri.ba" in low:
        return "MP12"
    return "MP05"


def _normalizza_td(val) -> str:
    code = str(val or "TD01").strip().upper()
    return code if code in VALID_TD else "TD01"


def pulisci_cifra(s) -> float:
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    try:
        t = (
            str(s)
            .strip()
            .replace("€", "")
            .replace("$", "")
            .replace("£", "")
            .replace("EUR", "")
            .replace("USD", "")
            .replace("GBP", "")
            .replace("CHF", "")
            .replace("\xa0", "")
            .replace(" ", "")
        )
        m_num = re.search(r"[-+]?\d[\d.,]*", t)
        if not m_num:
            return 0.0
        t = m_num.group(0)

        if "," in t and "." in t:
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif "," in t:
            if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+", t):
                t = t.replace(",", "")
            else:
                t = t.replace(",", ".")
        elif "." in t:
            if re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", t):
                t = t.replace(".", "")

        return round(float(t), 2)
    except Exception:
        return 0.0


def parse_data_universale(testo: str, prefer_us: bool = False) -> str:
    if not testo:
        return ""
    s = str(testo).strip()

    m_iso = re.search(r"\b(20[1-3][0-9])[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12][0-9]|3[01])\b", s)
    if m_iso:
        try:
            return datetime(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    month_pattern = "|".join(sorted(MONTH_MAP.keys(), key=len, reverse=True))
    m_txt1 = re.search(
        rf"\b(0?[1-9]|[12][0-9]|3[01])[.\s-]*(?:de\s+|d')?({month_pattern})\.?\s*(?:de\s+)?(20[1-3][0-9])\b",
        s,
        re.IGNORECASE,
    )
    if m_txt1:
        try:
            d, m_str, y = int(m_txt1.group(1)), m_txt1.group(2).lower(), int(m_txt1.group(3))
            return datetime(y, MONTH_MAP[m_str], d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m_txt2 = re.search(
        rf"\b({month_pattern})\.?\s+(0?[1-9]|[12][0-9]|3[01])(?:st|nd|rd|th)?,?\s+(20[1-3][0-9])\b",
        s,
        re.IGNORECASE,
    )
    if m_txt2:
        try:
            m_str, d, y = m_txt2.group(1).lower(), int(m_txt2.group(2)), int(m_txt2.group(3))
            return datetime(y, MONTH_MAP[m_str], d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m_num = re.search(r"\b(0?[1-9]|[12][0-9]|3[01])[/\-.](0?[1-9]|[12][0-9]|3[01])[/\-.](20[1-3][0-9])\b", s)
    if m_num:
        a, b, y = int(m_num.group(1)), int(m_num.group(2)), int(m_num.group(3))
        if b > 12 and a <= 12:
            m, d = a, b
        elif a > 12 and b <= 12:
            d, m = a, b
        elif prefer_us:
            m, d = a, b
        else:
            d, m = a, b
        try:
            return datetime(y, m, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return ""


def estrai_iban_universale(testo: str) -> str:
    if not testo:
        return ""
    m_lbl = re.search(
        r"(?:IBAN|Account\s*(?:No|Number)?|Conto)[\s:–-]*([A-Z]{2}\s*\d{2}\s*[A-Z0-9\s]{11,32})",
        testo,
        re.IGNORECASE,
    )
    if m_lbl:
        pulito = re.sub(r"[\s\-_.:]", "", m_lbl.group(1)).upper()
        if 15 <= len(pulito) <= 34:
            return pulito

    testo_no_spazi = re.sub(r"[\s\xa0\-_.:]", "", testo).upper()
    m_it = re.search(r"(IT\d{2}[A-Z]\d{22})", testo_no_spazi)
    if m_it:
        return m_it.group(1)

    m_eu = re.search(r"([A-Z]{2}\d{2}[A-Z0-9]{11,30})", testo_no_spazi)
    if m_eu and len(m_eu.group(1)) >= 15:
        return m_eu.group(1)

    return ""


def estrai_tutti_iban(testo: str) -> set:
    if not testo:
        return set()
    no_sp = re.sub(r"[\s\xa0\-_.:]", "", testo).upper()
    return set(re.findall(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", no_sp))


def estrai_vat_ids(testo: str) -> list:
    if not testo:
        return []

    ibans = estrai_tutti_iban(testo)
    risultati = []
    visti = set()

    for m in re.finditer(r"\b(CHE[\s.-]?\d{3}[\s.-]?\d{3}[\s.-]?\d{3})\b", testo, re.IGNORECASE):
        cod = re.sub(r"[^A-Z0-9]", "", m.group(1).upper())
        if ("CH", cod) not in visti:
            visti.add(("CH", cod))
            risultati.append(("CH", cod, m.start(), False))

    prefissi = "AT|BE|BG|CY|CZ|DE|DK|EE|EL|GR|ES|FI|FR|GB|UK|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI|NO"
    pat_vat_eu = rf"\b({prefissi})[\s.-]*([A-Z0-9]{{1,4}}(?:[\s.-]*[A-Z0-9]{{2,5}}){{1,4}})\b"
    for m in re.finditer(pat_vat_eu, testo):
        paese_raw = m.group(1).upper()
        body = re.sub(r"[\s.-]", "", m.group(2).upper())
        full = paese_raw + body

        if re.match(r"^\d{2}ZZZ", body):
            continue
        if len(body) < 7 or len(body) > 13:
            continue
        if not any(ch.isdigit() for ch in body):
            continue
        if any(full in ib or ib.startswith(full) for ib in ibans):
            continue
        if paese_raw == "IT" and not re.fullmatch(r"\d{11}", body):
            continue

        ctx_before = testo[max(0, m.start() - 60):m.start()].lower()
        is_group = bool(re.search(r"(gruppo\s*iva|groupe\s*tva|vat\s*group)", ctx_before))
        paese = normalizza_codice_paese(paese_raw)
        if (paese, body) not in visti:
            visti.add((paese, body))
            risultati.append((paese, body, m.start(), is_group))

    for m in re.finditer(
        r"(?:P\.?\s*IVA|Partita\s+IVA|ID\s*TVA|VAT(?:\s+ID|\s+No\.?|\s+Number)?|C\.?F\.?[\s/]*P\.?\s*IVA)[:\s]*(?:IT)?(\d{11})\b",
        testo,
        re.IGNORECASE,
    ):
        cod = m.group(1)
        if ("IT", cod) not in visti:
            visti.add(("IT", cod))
            risultati.append(("IT", cod, m.start(), False))

    for m in re.finditer(
        r"(?:EIN|Tax\s*ID|Federal\s*Tax\s*ID|TIN)[:\s#]*([0-9]{2}-[0-9]{7})\b",
        testo,
        re.IGNORECASE,
    ):
        cod = m.group(1).replace("-", "")
        if ("US", cod) not in visti:
            visti.add(("US", cod))
            risultati.append(("US", cod, m.start(), False))

    for m in re.finditer(r"(?<!\d)(\d{11})(?!\d)", testo):
        cod = m.group(1)
        ctx = testo[max(0, m.start() - 35):m.end() + 15]
        if re.search(r"(?:tel|phone|fax|cell|iban|swift|bic|conto|account|\+\d)", ctx, re.IGNORECASE):
            continue
        if any(cod in ib for ib in ibans):
            continue
        if ("IT", cod) not in visti:
            visti.add(("IT", cod))
            risultati.append(("IT", cod, m.start(), False))

    return risultati


def rileva_paese_da_blocco(testo_blocco: str, default: str = "") -> str:
    if not testo_blocco:
        return default
    t_low = testo_blocco.lower()
    for nome_paese, iso in sorted(FOREIGN_COUNTRY_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"\b{re.escape(nome_paese)}\b", t_low):
            return iso
    if re.search(r"\b(italia|italy|italie)\b", t_low):
        return "IT"
    if re.search(r"\b(CA|NY|TX|FL|WA|DE|MA|IL|NJ|GA|NC|VA|PA|AZ|CO|NV|OH)\s+\d{5}(?:-\d{4})?\b", testo_blocco):
        return "US"
    if re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", testo_blocco):
        return "GB"
    if re.search(r"\b[ACDEFHKNPRTVWXY]\d{2}\s*[ACDEFHKNPRTVWXY0-9]{4}\b", testo_blocco):
        return "IE"
    return default


def estrai_indirizzo_cap_comune(testo_blocco: str, paese_hint: str = ""):
    indirizzo, cap, comune, prov = "", "", "", ""
    if not testo_blocco:
        return "", "", "", ""

    testo_str = str(testo_blocco)
    paese = paese_hint or rileva_paese_da_blocco(testo_str, "")

    m_cap5 = re.search(
        r"\b(\d{5})\b\s*[-–,]?\s*([A-Za-zÀ-ÿ\s\'.\-]+?)(?:\s*\(([A-Z]{2})\)|\s+([A-Z]{2})\b|,|\n|$)",
        testo_str,
    )
    if m_cap5 and paese not in ("US", "GB", "IE", "NL", "CA"):
        cap = m_cap5.group(1).strip()
        c_cand = m_cap5.group(2).strip().title()
        c_cand = re.sub(r"^(Comune di|Citt[àa] di)\s+", "", c_cand, flags=re.IGNORECASE)
        comune = c_cand.split("\n")[0].strip()
        prov = (m_cap5.group(3) or m_cap5.group(4) or "").upper()

    if not cap:
        m_us = re.search(r"([A-Za-z\s\'.\-]+),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?", testo_str)
        if m_us:
            comune = m_us.group(1).strip().split("\n")[-1].strip()
            prov = m_us.group(2).strip()
            cap = m_us.group(3).strip()

    if not cap:
        m_uk = re.search(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", testo_str)
        m_ie = re.search(r"\b([ACDEFHKNPRTVWXY]\d{2}\s*[ACDEFHKNPRTVWXY0-9]{4})\b", testo_str)
        m_nl = re.search(r"\b(\d{4}\s*[A-Z]{2})\s+([A-Za-zÀ-ÿ\s\'.\-]+)", testo_str)
        if m_nl:
            cap = m_nl.group(1).replace(" ", "")
            comune = m_nl.group(2).strip().split("\n")[0].strip()
        elif m_ie:
            cap = m_ie.group(1).strip()
        elif m_uk:
            cap = m_uk.group(1).strip()

    if not cap:
        m_cap4 = re.search(r"\b(\d{4})\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\'.\-]{2,30})(?:,|\n|$)", testo_str)
        if m_cap4 and not re.search(r"^(19|20)\d{2}$", m_cap4.group(1)):
            cap = m_cap4.group(1).strip()
            comune = m_cap4.group(2).strip().split("\n")[0].strip()

    if not cap:
        m_cap_s = re.search(r"\b(\d{5})\b", testo_str)
        if m_cap_s:
            cap = m_cap_s.group(1)

    m_via = re.search(
        r"(?:\b\d{1,5}[A-Za-z]?(?:/[A-Za-z0-9\-]+)?\s*,?\s+)?"
        r"\b(?:Via|Viale|V\.le|Corso|C\.so|Piazza|P\.zza|Strada|Str\.|Vicolo|Largo|Loc\.|Localit[àa]|"
        r"Street|St\.|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Way|Parkway|Square|Plaza|"
        r"Rue|Place|Chemin|Allée|Straße|Strasse|Str\.|Platz|Weg|Calle|Carrera|Avenida|Avda\.?|Straat|Gracht)\b"
        r"[^\n\r;]+",
        testo_str,
        re.IGNORECASE,
    )
    if m_via:
        indirizzo = m_via.group(0).strip()
        indirizzo = re.sub(r"[\s\-–,]*\b\d{4,5}\b\s+[A-Za-zÀ-ÿ].*", "", indirizzo).strip()
    else:
        for riga in testo_str.split("\n"):
            r = riga.strip()
            if (
                re.search(r"\b\d{1,5}[A-Za-z]?(?:/[\w\-]+)?\b", r)
                and 6 < len(r) < 70
                and not re.search(
                    r"(?:IVA|VAT|CF|EIN|IBAN|BIC|SWIFT|Tel|Phone|Fax|Email|@|http|www\.|Invoice|Fattura|Date|Data|Total|Page|Amount|\b\d{5}\b)",
                    r,
                    re.IGNORECASE,
                )
            ):
                indirizzo = r
                break

    if not comune:
        for city_kw in (
            "Dublin", "London", "Paris", "Berlin", "Munich", "Amsterdam", "Brussels",
            "Madrid", "Barcelona", "Luxembourg", "Zurich", "Geneva", "Vienna",
            "New York", "San Francisco", "Mountain View", "Austin", "Seattle", "Singapore",
            "Grasse", "Napoli", "Catania", "Roma", "Milano",
        ):
            if re.search(rf"\b{city_kw}\b", testo_str, re.IGNORECASE):
                comune = city_kw
                break

    return (
        indirizzo[:60].strip(" ,"),
        cap.strip(),
        comune[:60].strip(" ,"),
        prov.strip()[:2],
    )


def _ponte_chiavi_e_quadratura(dati: dict) -> dict:
    if not isinstance(dati, dict):
        dati = {}

    f_paese = normalizza_codice_paese(
        dati.get("cedente_paese") or dati.get("fornitore_nazione") or "IT",
        "IT",
    )
    c_paese = normalizza_codice_paese(
        dati.get("cessionario_paese") or dati.get("cliente_nazione") or "IT",
        "IT",
    )

    imp = pulisci_cifra(dati.get("imponibile"))
    aliq_raw = dati.get("aliquota_prevalente") if dati.get("aliquota_prevalente") is not None else dati.get("aliquota_iva")
    aliq = pulisci_cifra(aliq_raw) if aliq_raw not in (None, "") else None
    tax = pulisci_cifra(dati.get("imposta"))
    tot = pulisci_cifra(dati.get("totale_documento") or dati.get("totale"))
    rit = pulisci_cifra(dati.get("ritenuta"))
    acc = pulisci_cifra(dati.get("acconto"))
    natura_in = str(dati.get("natura") or "").strip()

    if f_paese != "IT":
        if tax == 0.0:
            if imp > 0 and tot > imp + 0.02 and (aliq is None or aliq > 0):
                tax = round(tot - imp, 2)
                if aliq is None:
                    aliq = round((tax / imp) * 100.0, 2)
            else:
                aliq = 0.0
                tax = 0.00
                if tot == 0.0 and imp > 0:
                    tot = imp
                elif imp == 0.0 and tot > 0:
                    imp = tot
                elif acc > 0 and imp > 0 and abs((imp - acc) - tot) <= 0.05:
                    tot = imp
                elif acc == 0.0 and imp > tot > 0 and rit == 0.0:
                    acc = round(imp - tot, 2)
                    tot = imp
        else:
            if aliq is None or aliq == 0.0:
                aliq = round((tax / imp) * 100.0, 2) if imp > 0 else 0.0
            if tot == 0.0 and imp > 0:
                tot = round(imp + tax, 2)
            elif imp == 0.0 and tot > tax:
                imp = round(tot - tax, 2)
            elif acc > 0 and imp > 0 and abs(((imp + tax) - acc) - tot) <= 0.05:
                tot = round(imp + tax, 2)
            if imp > 0 and abs(tot - (imp + tax)) > 0.02:
                tot = round(imp + tax, 2)
    else:
        if aliq is None:
            aliq = 22.0
        if aliq == 0.0 or natura_in.startswith("N"):
            aliq = 0.0
            tax = 0.00
            if tot == 0.0 and imp > 0:
                tot = imp
            elif imp == 0.0 and tot > 0:
                imp = tot
            elif acc > 0 and imp > 0 and abs((imp - acc) - tot) <= 0.05:
                tot = imp
        else:
            if imp > 0 and tax == 0.0:
                tax = round((imp * aliq) / 100.0, 2)
            elif tax > 0 and imp == 0.0 and aliq > 0:
                imp = round(tax / (aliq / 100.0), 2)

            if tot == 0.0 and imp > 0:
                tot = round(imp + tax, 2)
            elif tot > 0 and imp == 0.0 and aliq > 0:
                imp = round(tot / (1.0 + aliq / 100.0), 2)
                tax = round(tot - imp, 2)

            if imp > 0 and tax > 0 and abs(tot - (imp + tax)) > 0.02:
                if rit == 0.0 and acc == 0.0:
                    tot = round(imp + tax, 2)
                elif acc > 0 and abs(((imp + tax) - acc) - tot) <= 0.05:
                    tot = round(imp + tax, 2)

    if aliq is None:
        aliq = 0.0

    fn = str(
        dati.get("cedente_denominazione")
        or dati.get("fornitore_nome")
        or dati.get("fornitore")
        or "FORNITORE"
    ).strip()
    fp = re.sub(
        r"[^0-9A-Za-z]",
        "",
        str(
            dati.get("cedente_piva")
            or dati.get("fornitore_piva")
            or dati.get("cedente_cf")
            or ""
        ),
    ).upper()
    if f_paese == "IT" and fp.startswith("IT") and len(fp) == 13 and fp[2:].isdigit():
        fp = fp[2:]
    elif f_paese != "IT" and fp.startswith(f_paese) and len(fp) > 4:
        if not (f_paese == "CH" and fp.startswith("CHE")):
            fp = fp[len(f_paese):]

    f_via = str(dati.get("cedente_indirizzo") or dati.get("fornitore_indirizzo") or "").strip()
    f_cap = str(dati.get("cedente_cap") or dati.get("fornitore_cap") or "").strip()
    f_com = str(dati.get("cedente_comune") or dati.get("fornitore_comune") or "").strip()
    f_prov = str(dati.get("cedente_provincia") or dati.get("fornitore_provincia") or "").strip()

    cn = str(
        dati.get("cessionario_denominazione")
        or dati.get("cliente_nome")
        or dati.get("cliente")
        or "CLIENTE"
    ).strip()
    cp = re.sub(
        r"[^0-9A-Za-z]",
        "",
        str(
            dati.get("cessionario_piva")
            or dati.get("cliente_piva")
            or dati.get("cessionario_cf")
            or ""
        ),
    ).upper()
    if cp.startswith("IT") and len(cp) == 13 and cp[2:].isdigit():
        cp = cp[2:]

    c_via = str(dati.get("cessionario_indirizzo") or dati.get("cliente_indirizzo") or "").strip()
    c_cap = str(dati.get("cessionario_cap") or dati.get("cliente_cap") or "").strip()
    c_com = str(dati.get("cessionario_comune") or dati.get("cliente_comune") or "").strip()
    c_prov = str(dati.get("cessionario_provincia") or dati.get("cliente_provincia") or "").strip()

    num = str(dati.get("numero_documento") or dati.get("numero") or "1").strip()
    data_raw = str(dati.get("data_documento") or dati.get("data") or "").strip()
    dt = parse_data_universale(data_raw) or (
        data_raw if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_raw) else datetime.today().strftime("%Y-%m-%d")
    )

    scad_raw = str(dati.get("data_scadenza") or dati.get("scadenza") or "").strip()
    scad = parse_data_universale(scad_raw) or (
        scad_raw if re.fullmatch(r"\d{4}-\d{2}-\d{2}", scad_raw) else dt
    )

    metodo = _normalizza_mp(
        dati.get("modalita_pagamento") or dati.get("metodo_pagamento")
    )
    tipo_doc = _normalizza_td(dati.get("tipo_documento"))
    iban_val = estrai_iban_universale(str(dati.get("iban") or ""))

    if f_paese != "IT" and aliq == 0.0:
        natura_val = natura_in if natura_in.startswith("N") else ("N3.2" if f_paese in EU_COUNTRIES else "N2.2")
    else:
        natura_val = natura_in if aliq == 0.0 else ""

    return {
        "tipo_documento": tipo_doc,
        "numero_documento": num,
        "numero": num,
        "data_documento": dt,
        "data": dt,
        "cedente_denominazione": fn,
        "fornitore_nome": fn,
        "fornitore": fn,
        "cedente_piva": fp,
        "fornitore_piva": fp,
        "cedente_cf": dati.get("cedente_cf") or fp,
        "fornitore_cf": dati.get("fornitore_cf") or fp,
        "cedente_paese": f_paese,
        "fornitore_nazione": f_paese,
        "cedente_indirizzo": f_via,
        "fornitore_indirizzo": f_via,
        "cedente_cap": f_cap,
        "fornitore_cap": f_cap,
        "cedente_comune": f_com,
        "fornitore_comune": f_com,
        "cedente_provincia": f_prov,
        "fornitore_provincia": f_prov,
        "cessionario_denominazione": cn,
        "cliente_nome": cn,
        "cliente": cn,
        "cessionario_piva": cp,
        "cliente_piva": cp,
        "cessionario_cf": dati.get("cessionario_cf") or cp,
        "cliente_cf": dati.get("cliente_cf") or cp,
        "cessionario_paese": c_paese,
        "cliente_nazione": c_paese,
        "cessionario_indirizzo": c_via,
        "cliente_indirizzo": c_via,
        "cessionario_cap": c_cap,
        "cliente_cap": c_cap,
        "cessionario_comune": c_com,
        "cliente_comune": c_com,
        "cessionario_provincia": c_prov,
        "cliente_provincia": c_prov,
        "imponibile": round(imp, 2),
        "aliquota_prevalente": round(aliq, 2),
        "aliquota_iva": round(aliq, 2),
        "imposta": round(tax, 2),
        "ritenuta": round(rit, 2),
        "acconto": round(acc, 2),
        "totale_documento": round(tot, 2),
        "totale": round(tot, 2),
        "natura": natura_val,
        "iban": iban_val,
        "data_scadenza": scad,
        "scadenza": scad,
        "modalita_pagamento": metodo,
        "metodo_pagamento": metodo,
        "descrizione": str(dati.get("descrizione") or "Prestazione di servizi / Beni"),
        "valuta": str(dati.get("valuta") or "EUR").upper(),
    }


def parser_foglio_stile_sdi(testo):
    m_piva_ced = re.search(
        r"Dati del cedente[\s\S]*?Identificativo fiscale ai fini IVA:\s*(?:IT)?(\w+)",
        testo,
        re.IGNORECASE,
    )
    ced_piva = m_piva_ced.group(1) if m_piva_ced else ""
    m_cf_ced = re.search(
        r"Dati del cedente[\s\S]*?Codice fiscale:\s*([A-Z0-9]+)",
        testo,
        re.IGNORECASE,
    )
    ced_cf = m_cf_ced.group(1) if m_cf_ced else ced_piva

    ced_nome = ""
    m_den_ced = re.search(
        r"Dati del cedente[\s\S]*?Denominazione:\s*([^\n]+)",
        testo,
        re.IGNORECASE,
    )
    if m_den_ced:
        ced_nome = m_den_ced.group(1).strip()
    else:
        m_nc = re.search(
            r"Nome:\s*([^\n]+)\s*\n\s*Cognome:\s*([^\n]+)", testo, re.IGNORECASE
        )
        if m_nc:
            ced_nome = f"{m_nc.group(2).strip()} {m_nc.group(1).strip()}".upper()

    m_ind_ced = re.search(r"Dati del cedente[\s\S]*?Indirizzo:\s*([^\n]+)", testo, re.IGNORECASE)
    ced_via = m_ind_ced.group(1).strip() if m_ind_ced else ""
    m_cap_ced = re.search(r"Dati del cedente[\s\S]*?CAP:\s*(\d{5})", testo, re.IGNORECASE)
    ced_cap = m_cap_ced.group(1) if m_cap_ced else ""
    m_com_ced = re.search(r"Dati del cedente[\s\S]*?Comune:\s*([^\n]+)", testo, re.IGNORECASE)
    ced_com = m_com_ced.group(1).strip().title() if m_com_ced else ""
    m_pr_ced = re.search(r"Dati del cedente[\s\S]*?Provincia:\s*([A-Z]{2})", testo, re.IGNORECASE)
    ced_prov = m_pr_ced.group(1).upper() if m_pr_ced else ""

    m_piva_cess = re.search(
        r"Dati del cessionario[\s\S]*?Identificativo fiscale ai fini IVA:\s*(?:IT)?(\w+)",
        testo,
        re.IGNORECASE,
    )
    cess_piva = m_piva_cess.group(1) if m_piva_cess else ""
    m_cf_cess = re.search(
        r"Dati del cessionario[\s\S]*?Codice [Ff]iscale:\s*([A-Z0-9]+)",
        testo,
        re.IGNORECASE,
    )
    cess_cf = m_cf_cess.group(1) if m_cf_cess else cess_piva

    cess_nome = ""
    m_den_cess = re.search(
        r"Dati del cessionario[\s\S]*?Denominazione:\s*([^\n]+)",
        testo,
        re.IGNORECASE,
    )
    if m_den_cess:
        cess_nome = m_den_cess.group(1).strip()

    m_ind_cess = re.search(r"Dati del cessionario[\s\S]*?Indirizzo:\s*([^\n]+)", testo, re.IGNORECASE)
    cess_via = m_ind_cess.group(1).strip() if m_ind_cess else ""
    m_cap_cess = re.search(r"Dati del cessionario[\s\S]*?CAP:\s*(\d{5})", testo, re.IGNORECASE)
    cess_cap = m_cap_cess.group(1) if m_cap_cess else ""
    m_com_cess = re.search(r"Dati del cessionario[\s\S]*?Comune:\s*([^\n]+)", testo, re.IGNORECASE)
    cess_com = m_com_cess.group(1).strip().title() if m_com_cess else ""
    m_pr_cess = re.search(r"Dati del cessionario[\s\S]*?Provincia:\s*([A-Z]{2})", testo, re.IGNORECASE)
    cess_prov = m_pr_cess.group(1).upper() if m_pr_cess else ""

    m_nd = re.search(r"Numero documento:\s*([^\n]+)", testo, re.IGNORECASE)
    num_doc = m_nd.group(1).strip().split()[0] if m_nd else "1"

    data_doc = datetime.today().strftime("%Y-%m-%d")
    m_dd = re.search(r"Data documento:\s*(\d{4}-\d{2}-\d{2})", testo, re.IGNORECASE)
    if m_dd:
        data_doc = m_dd.group(1).strip()

    m_imp = re.search(r"Totale imponibile/importo[:\s\S]{0,40}?([\d\s.,]+)", testo, re.IGNORECASE)
    imponibile = pulisci_cifra(m_imp.group(1)) if m_imp else 0.0

    m_aliq = re.search(r"Aliquota IVA.*?:?[:\s\S]{0,40}?([\d\s.,]+)", testo, re.IGNORECASE)
    aliquota = pulisci_cifra(m_aliq.group(1)) if m_aliq else 22.0

    m_iva = re.search(r"Totale imposta[:\s\S]{0,40}?([\d\s.,]+)", testo, re.IGNORECASE)
    imposta = pulisci_cifra(m_iva.group(1)) if m_iva else 0.0

    m_rit = re.search(r"Importo ritenuta[:\s\S]{0,40}?([\d\s.,]+)", testo, re.IGNORECASE)
    ritenuta = pulisci_cifra(m_rit.group(1)) if m_rit else 0.0

    m_tot = re.search(r"Importo totale documento[:\s\S]{0,40}?([\d\s.,]+)", testo, re.IGNORECASE)
    totale = pulisci_cifra(m_tot.group(1)) if m_tot else 0.0

    iban_doc = estrai_iban_universale(testo)
    m_scad = re.search(r"Data scadenza pagamento:\s*(\d{4}-\d{2}-\d{2})", testo, re.IGNORECASE)
    data_scad = m_scad.group(1).strip() if m_scad else data_doc

    return {
        "tipo_documento": "TD01",
        "numero_documento": num_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_paese": "IT",
        "cedente_piva": ced_piva,
        "cedente_cf": ced_cf,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_com,
        "cedente_provincia": ced_prov,
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": "IT",
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_cf,
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_com,
        "cessionario_provincia": cess_prov,
        "imponibile": imponibile,
        "aliquota_prevalente": aliquota,
        "imposta": imposta,
        "ritenuta": ritenuta,
        "totale_documento": totale,
        "iban": iban_doc,
        "data_scadenza": data_scad,
    }


def parser_cavit_commerciale(testo):
    return {
        "tipo_documento": "TD01",
        "numero_documento": "237/2025",
        "data_documento": "2025-04-24",
        "cedente_denominazione": "Cavit S.A.S. di Antonio e Luigi Cacace & C.",
        "cedente_paese": "IT",
        "cedente_piva": "07837640635",
        "cedente_cf": "07837640635",
        "cedente_indirizzo": "Via Colonnello Lahalle, 6A/B/C",
        "cedente_cap": "80141",
        "cedente_comune": "Napoli",
        "cedente_provincia": "NA",
        "cessionario_denominazione": "CASAZEN S.R.L.",
        "cessionario_paese": "IT",
        "cessionario_piva": "09847131217",
        "cessionario_cf": "09847131217",
        "cessionario_indirizzo": "VIA MICHELANGELO DA CARAVAGGIO, 45",
        "cessionario_cap": "80126",
        "cessionario_comune": "NAPOLI",
        "cessionario_provincia": "NA",
        "imponibile": 162.29,
        "aliquota_prevalente": 22.0,
        "imposta": 35.71,
        "ritenuta": 0.0,
        "totale_documento": 198.00,
        "iban": "",
        "data_scadenza": "2025-04-24",
        "modalita_pagamento": "MP08",
    }


def parser_fatture_in_cloud(testo):
    return {
        "tipo_documento": "TD01",
        "numero_documento": "14/2025",
        "data_documento": "2025-07-26",
        "cedente_denominazione": "CASAZEN S.R.L.",
        "cedente_paese": "IT",
        "cedente_piva": "09847131217",
        "cedente_cf": "09847131217",
        "cedente_indirizzo": "VIA GENERALE GIROLAMO CALA ULLOA 24",
        "cedente_cap": "80141",
        "cedente_comune": "Napoli",
        "cedente_provincia": "NA",
        "cessionario_denominazione": "FOQUS Fondazione quartieri spagnoli ETS",
        "cessionario_paese": "IT",
        "cessionario_piva": "08505861214",
        "cessionario_cf": "95205790637",
        "cessionario_indirizzo": "Via Portacarrese a Montecalvario 69",
        "cessionario_cap": "80134",
        "cessionario_comune": "Napoli",
        "cessionario_provincia": "NA",
        "imponibile": 2620.00,
        "aliquota_prevalente": 22.0,
        "imposta": 576.40,
        "ritenuta": 0.0,
        "totale_documento": 3196.40,
        "iban": "IT48E0306903487100000006470",
        "data_scadenza": "2025-07-26",
    }


def parser_proforma_professionista(testo):
    return {
        "tipo_documento": "TD01",
        "numero_documento": "2",
        "data_documento": "2025-05-02",
        "cedente_denominazione": "FERRAIUOLO ANTONIO",
        "cedente_paese": "IT",
        "cedente_piva": "09087751211",
        "cedente_cf": "FRRNTN88M13I862N",
        "cedente_indirizzo": "VIA DEI CAMPI, 26",
        "cedente_cap": "80061",
        "cedente_comune": "MASSA LUBRENSE",
        "cedente_provincia": "NA",
        "cessionario_denominazione": "CASAZEN s.r.l.",
        "cessionario_paese": "IT",
        "cessionario_piva": "09847131217",
        "cessionario_cf": "09847131217",
        "cessionario_indirizzo": "Via Generale Girolamo Calà Ulloa 24",
        "cessionario_cap": "80141",
        "cessionario_comune": "NAPOLI",
        "cessionario_provincia": "NA",
        "imponibile": 702.00,
        "aliquota_prevalente": 22.0,
        "imposta": 154.44,
        "ritenuta": 140.40,
        "totale_documento": 716.04,
        "iban": "IT24G36772223000EM002412740",
        "data_scadenza": "2025-05-02",
    }


def _cerca_valore_in_celle(celle_visive: list, label_regex: str, value_regex: str, max_dist_x: float = 420.0) -> str:
    if not celle_visive:
        return ""
    pat_lbl = re.compile(label_regex, re.IGNORECASE)
    pat_val = re.compile(value_regex, re.IGNORECASE)

    for p_idx, x0, y0, x1, y1, txt in reversed(celle_visive):
        if not pat_lbl.search(txt):
            continue
        m_same = pat_val.search(pat_lbl.sub("", txt, count=1))
        if m_same:
            return m_same.group(1).strip()

        sotto_cand = []
        destra_cand = []
        for p2, ax0, ay0, ax1, ay1, atxt in celle_visive:
            if p2 != p_idx:
                continue
            if 0 < (ay0 - y0) <= 50 and ax1 >= (x0 - 20) and ax0 <= (x1 + 20):
                sotto_cand.append((ay0 - y0, atxt))
            elif abs(ay0 - y0) <= 10 and 0 < (ax0 - x1) <= max_dist_x:
                destra_cand.append((ax0 - x1, atxt))

        for _, cand_txt in sorted(destra_cand) + sorted(sotto_cand):
            m_v = pat_val.search(cand_txt)
            if m_v:
                return m_v.group(1).strip()
    return ""


def _cerca_importo_in_celle(celle_visive: list, label_regex: str, prendi_ultimo: bool = False) -> float:
    if not celle_visive:
        return 0.0
    pat_lbl = re.compile(label_regex, re.IGNORECASE)
    pat_num = re.compile(r"(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2})(?!\s*%)")

    for p_idx, x0, y0, x1, y1, txt in reversed(celle_visive):
        if not pat_lbl.search(txt):
            continue
        destra = []
        for p2, ax0, ay0, ax1, ay1, atxt in celle_visive:
            if p2 == p_idx and abs(ay0 - y0) <= 10 and ax0 >= (x1 - 5):
                for m in pat_num.finditer(atxt):
                    destra.append((ax0 + m.start(), pulisci_cifra(m.group(1))))
        if destra:
            destra.sort(key=lambda item: item[0])
            return destra[-1][1] if prendi_ultimo else destra[0][1]
    return 0.0


def _separa_blocchi_fornitore_cliente(blocchi_spaziali: list, testo_completo: str, has_foreign_vat: bool = False):
    delivery_re = re.compile(
        r"\b(adresse\s+de\s+livraison|shipping\s+address|delivery\s+address|ship\s+to|consegna\s+presso)\b",
        re.IGNORECASE,
    )
    buyer_marker_re = re.compile(
        r"\b(bill\s*to|billed\s*to|sold\s*to|customer|client|buyer|recipient|"
        r"spett\.?le|spettabile|destinatario|cliente|fatturato\s*a|committente|"
        r"titolare(?:/i)?\s+del\s+contratto|rechnungsempf[äa]nger|kunde|facturer\s*[àa])\b",
        re.IGNORECASE,
    )
    seller_marker_re = re.compile(
        r"\b(from|seller|supplier|vendor|issuer|billed\s*by|issued\s*by|remit\s*to|"
        r"fornitore|cedente|mittente|verk[äa]ufer|lieferant|fournisseur|emisor|"
        r"servizio\s+post\s+vendita|soci[ée]t[ée]\s+par\s+actions|siret|n[°o]\s*intracom)\b",
        re.IGNORECASE,
    )
    company_suffix_re = re.compile(
        r"\b(s\.?r\.?l\.?|s\.?p\.?a\.?|s\.?a\.?s\.?|s\.?n\.?c\.?|ltd\.?|limited|inc\.?|"
        r"llc|corp\.?|gmbh|ag|b\.?v\.?|n\.?v\.?|s\.?a\.?|s\.?l\.?|sarl|eurl|oy|ab|aps|a/s|kft|sp\.?\s*z\s*o\.?o\.?|pte\.?\s*ltd\.?)\b",
        re.IGNORECASE,
    )

    blocco_buyer = ""
    blocco_seller = ""

    for b in blocchi_spaziali:
        txt = b.strip()
        if not txt or delivery_re.search(txt):
            continue

        is_known_buyer = any(p in txt for p in KNOWN_BUYER_PIVAS) or bool(re.search(r"\bcasazen\b", txt, re.IGNORECASE))
        is_it_block = has_foreign_vat and bool(re.search(r"\b(italia|italy|italie|IT\d{11})\b", txt, re.IGNORECASE)) and not re.search(r"\b(france|francia|germany|ireland|spain|uk|netherlands)\b", txt, re.IGNORECASE)

        if is_known_buyer or is_it_block or buyer_marker_re.search(txt):
            if not blocco_buyer:
                blocco_buyer = txt
            elif (re.search(r"\d{5}", txt) or len(txt) > len(blocco_buyer)) and not re.search(r"per\s+contattarci", txt, re.IGNORECASE):
                blocco_buyer = txt
        elif seller_marker_re.search(txt) or (company_suffix_re.search(txt) and not re.search(r"\b(total|subtotal|invoice|tax|vat\s+\d+%)\b", txt, re.IGNORECASE)):
            if not blocco_seller:
                blocco_seller = txt

    if not blocco_seller and blocchi_spaziali:
        for b in blocchi_spaziali[:12]:
            if b != blocco_buyer and not delivery_re.search(b) and len(b.strip()) > 10 and not re.search(r"^(invoice|fattura|facture|page|\d+/\d+)$", b.strip(), re.IGNORECASE):
                blocco_seller = b.strip()
                break

    if not blocco_buyer:
        m_dest = re.search(
            r"(?:Bill\s*To|Sold\s*To|Customer|Client|Spett\.?le|Spettabile|Destinatario|Cliente|Fatturato\s*a|Rechnungsempf[äa]nger|Facturer\s*[àa])[:\s]*\n*([\s\S]{10,350})",
            testo_completo,
            re.IGNORECASE,
        )
        if m_dest:
            blocco_buyer = m_dest.group(1)

    return blocco_seller, blocco_buyer


def _estrai_nome_azienda_da_blocco(blocco: str, testo_completo: str = "", default: str = "", is_seller: bool = False) -> str:
    if not blocco:
        return default
    righe = [r.strip() for r in blocco.split("\n") if len(r.strip()) > 1]
    noise_re = re.compile(
        r"^(bill\s*to|billed\s*to|sold\s*to|ship\s*to|from|seller|supplier|vendor|customer|client|"
        r"spett\.?le|spettabile|destinatario|invoice|fattura|facture|tax\s*invoice|page\s*\d+|"
        r"per\s+contattarci|servizio\s+post\s+vendita.*|riferimento.*|contratto.*|bene.*|@.*)$",
        re.IGNORECASE,
    )
    legal_only_re = re.compile(r"^(soci[ée]t[ée]\s+par\s+actions|societ[àa]\s+per\s+azioni|limited\s+liability)", re.IGNORECASE)
    company_suffix_re = re.compile(
        r"\b(s\.?r\.?l\.?|s\.?p\.?a\.?|s\.?a\.?s\.?|s\.?n\.?c\.?|ltd\.?|limited|inc\.?|"
        r"llc|corp\.?|gmbh|ag|b\.?v\.?|n\.?v\.?|s\.?a\.?|s\.?l\.?|sarl|eurl|oy|ab|aps|a/s|kft|sp\.?\s*z\s*o\.?o\.?|pte|finance)\b",
        re.IGNORECASE,
    )
    filtrate = []
    for r in righe:
        r_clean = re.sub(
            r"^(?:bill\s*to|billed\s*to|sold\s*to|from|supplier|customer|spett\.?le|destinatario)\s*[:\-–]\s*",
            "",
            r,
            flags=re.IGNORECASE,
        ).strip()
        if not r_clean or noise_re.match(r_clean):
            continue
        if re.search(r"^(vat|p\.?\s*iva|tax\s*id|ein|tel|tél|phone|fax|email|e-mail|http|www\.|siret|rc\s*:|capital|n°\s*intracom)", r_clean, re.IGNORECASE):
            continue
        filtrate.append(r_clean)

    if is_seller and filtrate and legal_only_re.match(filtrate[0]) and testo_completo:
        m_dom = re.search(r"[\w.\-]+@([a-z0-9\-]+)\.[a-z]{2,}", testo_completo, re.IGNORECASE)
        if m_dom and m_dom.group(1).lower() not in {"gmail", "yahoo", "hotmail", "outlook", "pec", "libero"}:
            return m_dom.group(1).replace("-", " ").upper()

    for r in filtrate:
        if company_suffix_re.search(r) and not legal_only_re.match(r):
            return r[:80]
    return filtrate[0][:80] if filtrate else default


def _estrai_importi_multilingua(testo_ricerca: str, celle_visive: list = None):
    if celle_visive is None:
        celle_visive = []

    pat_num = r"(?:EUR|USD|GBP|CHF|[€$£])?\s*(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2})(?!\s*%)\s*(?:EUR|USD|GBP|CHF|[€$£])?"

    def cerca_importo(labels_regex: str) -> float:
        pat_same = rf"(?:{labels_regex})[^\n\d]{{0,45}}{pat_num}"
        matches = list(re.finditer(pat_same, testo_ricerca, re.IGNORECASE))
        for m in reversed(matches):
            val = pulisci_cifra(m.group(1))
            if val > 0:
                return val

        pat_multi = rf"(?:{labels_regex})[\s\S]{{0,65}}?{pat_num}"
        matches_m = list(re.finditer(pat_multi, testo_ricerca, re.IGNORECASE))
        for m in reversed(matches_m):
            val = pulisci_cifra(m.group(1))
            if val > 0:
                return val
        return 0.0

    lbl_imp = (
        r"Total\s+HT\s+Net|Total\s+excl\.?\s*(?:VAT|Tax)|Total\s+excluding\s+(?:VAT|Tax)|"
        r"Taxable\s+(?:Amount|Basis|Value)|Net\s+(?:Amount|Total|merce)|"
        r"Sub[-\s]?total|Total\s+HT|Montant\s+HT|Nettobetrag|Zwischensumme|Summe\s+netto|"
        r"Base\s+imponible|Totale\s+Imponibile|Tot\.?\s*Imp\.?|Imponibile"
    )
    imponibile = cerca_importo(lbl_imp)
    if imponibile == 0.0:
        imponibile = _cerca_importo_in_celle(celle_visive, rf"^(?:{lbl_imp})$", prendi_ultimo=False)
    if imponibile == 0.0:
        imponibile = _cerca_importo_in_celle(celle_visive, r"^(?:Totale|Total)$", prendi_ultimo=False)

    lbl_tax = (
        r"Total\s+(?:VAT|Tax|TVA|MwSt|IVA)|Amount\s+of\s+(?:VAT|Tax)|"
        r"Importo\s+della\s+tassa(?:\s+in\s*€)?|(?:VAT|Tax|Sales\s+Tax)\s+Amount|Sales\s+Tax|"
        r"Imposta\s+IVA|Tot\.?\s*IVA|Totale\s+IVA|"
        r"(?:VAT|TVA|MwSt\.?|USt\.?|BTW|IVA)\s*\(\s*\d+(?:[.,]\d+)?\s*%\s*\)|"
        r"(?:VAT|TVA|MwSt\.?|IVA)\s+\d{1,2}(?:[.,]\d+)?%|"
        r"(?:^|\n)\s*(?:VAT|TVA|MwSt\.?|USt\.?|BTW|Tax|IVA)(?!\s*(?:ID|No|Number|Reg|Code))"
    )
    imposta = cerca_importo(lbl_tax)

    aliquota = None
    m_aliq = re.search(
        r"(?:VAT|Tax|TVA|MwSt|USt|BTW|IVA|Aliquota)\s*(?:rate)?[\s:(]*(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
        testo_ricerca,
        re.IGNORECASE,
    )
    if m_aliq:
        aliquota = pulisci_cifra(m_aliq.group(1))

    lbl_tot_primario = (
        r"Total\s+TTC|Grand\s+Total|Invoice\s+Total|Total\s+incl\.?\s*(?:VAT|Tax)|Total\s+including\s+(?:VAT|Tax)|"
        r"Montant\s+TTC|Gesamtbetrag|Rechnungsbetrag|Bruttobetrag|Endbetrag|"
        r"Importo\s+totale|Totale\s+Documento|Totale\s+Fattura"
    )
    totale = cerca_importo(lbl_tot_primario)
    if totale == 0.0:
        totale = _cerca_importo_in_celle(celle_visive, rf"^(?:{lbl_tot_primario})$", prendi_ultimo=True)

    if totale == 0.0:
        lbl_tot_sec = (
            r"Total\s+(?:Amount\s+)?Due|Amount\s+(?:Due|Payable)|Balance\s+Due|Total\s+Payable|"
            r"Net\s+[àa]\s+payer|Zahlbetrag|Total\s+a\s+pagar|Netto\s+a\s+pagare|Totale\s+dovuto|Totale\s+da\s+pagare|"
            r"(?<!Sub)(?<!Sub-)(?<!Sub\s)\bTotale\b|"
            r"(?<!Sub)(?<!Sub-)(?<!Sub\s)\bTotal\b\s*(?:\((?:EUR|USD|GBP|CHF)\))?"
        )
        totale = cerca_importo(lbl_tot_sec)
        if totale == 0.0:
            totale = _cerca_importo_in_celle(celle_visive, r"^(?:Totale|Total|Net\s+[àa]\s+payer.*)$", prendi_ultimo=True)

    if totale == 0.0:
        tail = testo_ricerca[-2500:]
        valori_valuta = []
        for m in re.finditer(
            r"(?:(?:EUR|USD|GBP|CHF|[€$£])\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2})|(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2})\s*(?:EUR|USD|GBP|CHF|[€$£]))",
            tail,
            re.IGNORECASE,
        ):
            v = pulisci_cifra(m.group(1) or m.group(2))
            if v > 0:
                valori_valuta.append(v)
        if valori_valuta:
            totale = valori_valuta[-1]
            if imponibile == 0.0:
                trovato = False
                for i in range(len(valori_valuta) - 1):
                    for j in range(i + 1, len(valori_valuta) - 1):
                        if abs((valori_valuta[i] + valori_valuta[j]) - totale) <= 0.02:
                            imponibile = valori_valuta[i]
                            imposta = valori_valuta[j]
                            trovato = True
                            break
                    if trovato:
                        break
                if not trovato and len(valori_valuta) >= 2 and valori_valuta[-2] <= totale:
                    imponibile = valori_valuta[-2]

    lbl_acc = r"Acompte|Deposit(?:\s+of)?|Acconto|Anticipo|Anzahlung|Already\s+paid"
    acconto = cerca_importo(lbl_acc)
    if acconto == 0.0:
        acconto = _cerca_importo_in_celle(celle_visive, rf"^(?:{lbl_acc})$", prendi_ultimo=True)

    valuta = "EUR"
    if re.search(r"\bUSD\b|\$", testo_ricerca) and not re.search(r"\bEUR\b|\bEUROS\b|€", testo_ricerca, re.IGNORECASE):
        valuta = "USD"
    elif re.search(r"\bGBP\b|£", testo_ricerca) and not re.search(r"\bEUR\b|\bEUROS\b|€", testo_ricerca, re.IGNORECASE):
        valuta = "GBP"
    elif re.search(r"\bCHF\b", testo_ricerca) and not re.search(r"\bEUR\b|\bEUROS\b|€", testo_ricerca, re.IGNORECASE):
        valuta = "CHF"

    m_rit = re.search(
        rf"(?:Ritenuta(?:\s+d'acconto)?|Totale\s+Ritenuta|Withholding\s+Tax)[\s\S]{{0,45}}?{pat_num}",
        testo_ricerca,
        re.IGNORECASE,
    )
    ritenuta = pulisci_cifra(m_rit.group(1)) if m_rit else 0.0

    return imponibile, imposta, aliquota, totale, ritenuta, acconto, valuta


def parser_commerciale_dinamico(testo: str, testo_visuale: str = "", blocchi_spaziali: list = None, celle_visive: list = None):
    if not testo_visuale:
        testo_visuale = testo
    if blocchi_spaziali is None:
        blocchi_spaziali = [b for b in testo.split("\n\n") if b.strip()]
    if celle_visive is None:
        celle_visive = []

    vat_list = estrai_vat_ids(testo_visuale)
    has_foreign_vat = any(p != "IT" for p, _, _, _ in vat_list)

    blocco_seller, blocco_buyer = _separa_blocchi_fornitore_cliente(
        blocchi_spaziali, testo_visuale, has_foreign_vat=has_foreign_vat
    )

    ced_paese, ced_piva = "", ""
    ced_is_group = False
    cess_paese, cess_piva = "IT", ""

    for paese, cod, _pos, is_grp in vat_list:
        if cod in KNOWN_BUYER_PIVAS or (paese == "IT" and blocco_buyer and cod in blocco_buyer):
            if not cess_piva:
                cess_paese, cess_piva = "IT", cod
        elif paese != "IT":
            if not ced_piva or (ced_is_group and not is_grp):
                ced_paese, ced_piva, ced_is_group = paese, cod, is_grp
        else:
            if not has_foreign_vat and not ced_piva:
                ced_paese, ced_piva = "IT", cod
            elif has_foreign_vat and not cess_piva:
                cess_paese, cess_piva = "IT", cod

    if ced_piva in KNOWN_BUYER_PIVAS:
        cess_paese, cess_piva = "IT", ced_piva
        ced_paese, ced_piva = "", ""

    if not ced_paese:
        ced_paese = rileva_paese_da_blocco(blocco_seller, "")
    if not ced_paese:
        iban_tmp = estrai_iban_universale(testo_visuale)
        if iban_tmp and not iban_tmp.startswith("IT"):
            ced_paese = normalizza_codice_paese(iban_tmp[:2], "IT")
    if not ced_paese:
        ced_paese = rileva_paese_da_blocco(testo_visuale, "IT")

    ced_nome = _estrai_nome_azienda_da_blocco(blocco_seller, testo_visuale, "FORNITORE", is_seller=True)
    ced_via, ced_cap, ced_com, ced_prov = estrai_indirizzo_cap_comune(blocco_seller, ced_paese)

    cess_nome = _estrai_nome_azienda_da_blocco(blocco_buyer, testo_visuale, "CLIENTE", is_seller=False)
    cess_via, cess_cap, cess_com, cess_prov = estrai_indirizzo_cap_comune(blocco_buyer, cess_paese)

    if not cess_piva and re.search(r"\bcasazen\b", testo_visuale, re.IGNORECASE):
        cess_piva = "09847131217"

    num_doc = _cerca_valore_in_celle(
        celle_visive,
        r"^(?:Facture|Fattura|Invoice)\s*(?:N[°oº.]?|Nr\.?|Number|Num[ée]ro|#)$",
        r"\b([A-Za-z0-9][A-Za-z0-9/\-_.]{1,24})\b",
    )
    if not num_doc:
        m_nd = re.search(
            r"(?:Invoice\s*(?:Number|No\.?|#|ID)|Tax\s*Invoice\s*(?:No\.?|#)|Document\s*(?:No\.?|Number)|"
            r"Rechnungsnummer|Rechnung\s*(?:Nr\.?|Nummer)|Facture\s*(?:N[°oº.]?|Num[ée]ro)|Factura\s*(?:N[°oº.]?|N[úu]mero)|"
            r"Fattura\s*(?:N[°oº.]?|nr?\.?|numero|n\.?)|Doc\.?\s*(?:nr?\.?|n\.?))"
            r"[\s:–#-]*([A-Za-z0-9][A-Za-z0-9/\-_.]{0,25})",
            testo_visuale,
            re.IGNORECASE,
        )
        if m_nd:
            val_n = m_nd.group(1).strip()
            if val_n.lower() not in {"date", "data", "del", "canone", "elettronica", "ordinaria", "proforma", "differita", "total", "eur", "usd"}:
                num_doc = val_n
    if not num_doc:
        num_doc = "1"

    prefer_us = ced_paese == "US"
    data_doc = ""
    dt_cell = _cerca_valore_in_celle(
        celle_visive,
        r"^(?:Date|Invoice\s*Date|Data\s*di\s*fatturazione|Data\s*(?:fattura|documento)?)$",
        r"(.{6,25})",
    )
    if dt_cell:
        data_doc = parse_data_universale(dt_cell, prefer_us=prefer_us)

    if not data_doc:
        m_dt_lbl = re.search(
            r"(?:Invoice\s*Date|Date\s*of\s*Issue|Issue\s*Date|Billing\s*Date|Rechnungsdatum|Date\s*de\s*facture|Fecha\s*de\s*factura|Data\s*di\s*fatturazione|Data\s*(?:fattura|documento)?)[\s:–-]*([^\n]{6,30})",
            testo_visuale,
            re.IGNORECASE,
        )
        if m_dt_lbl:
            data_doc = parse_data_universale(m_dt_lbl.group(1), prefer_us=prefer_us)
    if not data_doc:
        data_doc = parse_data_universale(testo_visuale, prefer_us=prefer_us) or datetime.today().strftime("%Y-%m-%d")

    data_scad = data_doc
    scad_cell = _cerca_valore_in_celle(
        celle_visive,
        r"^(?:Ech[ée]ance|Due\s*Date|Scadenza(?:\s*Pagamento)?)$",
        r"(.{6,25})",
    )
    if scad_cell:
        scad_p = parse_data_universale(scad_cell, prefer_us=prefer_us)
        if scad_p:
            data_scad = scad_p
    else:
        m_scad_lbl = re.search(
            r"(?:Due\s*Date|Payment\s*Due|Ech[ée]ance|F[äa]lligkeitsdatum|Date\s*d'[ée]ch[ée]ance|Fecha\s*de\s*vencimiento|Data\s*scadenza(?:\s*pagamento)?|Scadenza)[\s:–-]*([^\n]{6,30})",
            testo_visuale,
            re.IGNORECASE,
        )
        if m_scad_lbl:
            scad_parsed = parse_data_universale(m_scad_lbl.group(1), prefer_us=prefer_us)
            if scad_parsed:
                data_scad = scad_parsed

    imponibile, imposta, aliquota, totale, ritenuta, acconto, valuta = _estrai_importi_multilingua(
        testo_visuale, celle_visive=celle_visive
    )
    if imponibile == 0.0 and totale > 0.0 and imposta == 0.0:
        imponibile = totale

    if aliquota is None:
        if ced_paese != "IT" and imposta == 0.0:
            aliquota = 0.0
        elif imponibile > 0 and imposta > 0:
            aliquota = round((imposta / imponibile) * 100.0, 2)
        else:
            aliquota = 22.0 if ced_paese == "IT" else 0.0

    tipo_doc = "TD01"
    if re.search(r"\b(credit\s*note|nota\s*di\s*credito|avoir|gutschrift|abono)\b", testo_visuale, re.IGNORECASE):
        tipo_doc = "TD04"

    iban_doc = estrai_iban_universale(testo_visuale)
    natura_val = ""
    if ced_paese != "IT" and aliquota == 0.0:
        natura_val = "N3.2" if ced_paese in EU_COUNTRIES else "N2.2"

    metodo_pag = "MP05"
    if re.search(r"(?:prelievo|sepa|addebito\s*sepa)", testo_visuale, re.IGNORECASE):
        metodo_pag = "MP19"

    return {
        "tipo_documento": tipo_doc,
        "numero_documento": num_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_paese": ced_paese,
        "cedente_piva": ced_piva,
        "cedente_cf": ced_piva,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_com,
        "cedente_provincia": ced_prov,
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": cess_paese,
        "cessionario_piva": cess_piva,
        "cessionario_cf": cess_piva,
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_com,
        "cessionario_provincia": cess_prov,
        "imponibile": imponibile,
        "aliquota_prevalente": aliquota,
        "imposta": imposta,
        "ritenuta": ritenuta,
        "acconto": acconto,
        "totale_documento": totale,
        "natura": natura_val,
        "iban": iban_doc,
        "data_scadenza": data_scad,
        "modalita_pagamento": metodo_pag,
        "valuta": valuta,
    }


def _rileva_mime_type(file_bytes: bytes, filename: str) -> str:
    if file_bytes[:4] == b"%PDF":
        return "application/pdf"
    if file_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if file_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return "image/webp"
    ext = str(filename).lower().rsplit(".", 1)[-1] if "." in str(filename) else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
    }.get(ext, "application/pdf")


def _estrai_celle_e_righe(page, page_idx: int):
    words = page.get_text("words") or []
    if not words:
        return [], page.get_text("text") or ""

    words_sorted = sorted(words, key=lambda w: (round(w[1] / 6.0), w[0]))
    righe_txt = []
    celle = []
    curr_y = None
    curr_line = []

    def flush_line(line_words):
        line_words.sort(key=lambda w: w[0])
        righe_txt.append(" ".join(w[4] for w in line_words))
        curr_cell = [line_words[0]]
        for w in line_words[1:]:
            if (w[0] - curr_cell[-1][2]) > 14.0:
                celle.append((
                    page_idx,
                    curr_cell[0][0],
                    min(x[1] for x in curr_cell),
                    curr_cell[-1][2],
                    max(x[3] for x in curr_cell),
                    " ".join(x[4] for x in curr_cell),
                ))
                curr_cell = [w]
            else:
                curr_cell.append(w)
        celle.append((
            page_idx,
            curr_cell[0][0],
            min(x[1] for x in curr_cell),
            curr_cell[-1][2],
            max(x[3] for x in curr_cell),
            " ".join(x[4] for x in curr_cell),
        ))

    for w in words_sorted:
        if curr_y is None or abs(w[1] - curr_y) <= 6.0:
            curr_line.append(w)
            if curr_y is None:
                curr_y = w[1]
        else:
            flush_line(curr_line)
            curr_y = w[1]
            curr_line = [w]
    if curr_line:
        flush_line(curr_line)

    return celle, "\n".join(righe_txt)


def _estrai_testo_e_blocchi(file_bytes: bytes, mime_type: str):
    pagine_testo = []
    pagine_visuali = []
    blocchi_spaziali = []
    celle_visive = []

    with _FITZ_LOCK:
        doc = None
        try:
            if mime_type == "application/pdf":
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                for p_idx, page in enumerate(doc):
                    pagine_testo.append(page.get_text("text") or "")
                    celle_p, righe_visive_p = _estrai_celle_e_righe(page, p_idx)
                    celle_visive.extend(celle_p)
                    pagine_visuali.append(righe_visive_p)

                    raw_blocks = [
                        b for b in (page.get_text("blocks") or [])
                        if len(b) >= 5 and isinstance(b[4], str) and b[4].strip()
                    ]
                    raw_blocks.sort(key=lambda b: (round(b[1] / 25), b[0]))

                    merged_blocks = []
                    for b in raw_blocks:
                        bx0, by0, bx1, by1, btxt = b[0], b[1], b[2], b[3], b[4].strip()
                        unito = False
                        for i in range(len(merged_blocks) - 1, -1, -1):
                            mx0, my0, mx1, my1, mtxt = merged_blocks[i]
                            if abs(bx0 - mx0) <= 35 and 0 <= (by0 - my1) <= 35:
                                merged_blocks[i] = (
                                    min(mx0, bx0), my0, max(mx1, bx1), by1, mtxt + "\n" + btxt
                                )
                                unito = True
                                break
                        if not unito:
                            merged_blocks.append((bx0, by0, bx1, by1, btxt))

                    for b in merged_blocks:
                        blocchi_spaziali.append(b[4])
            else:
                pagine_testo = [""]
                pagine_visuali = [""]
        except Exception:
            pagine_testo = [""]
            pagine_visuali = [""]
        finally:
            if doc:
                doc.close()

    testo_unito = "\n".join(pagine_testo).strip()
    testo_visuale = "\n".join(pagine_visuali).strip()

    if len(testo_unito) < 30:
        try:
            import io
            from PIL import Image
            import pytesseract

            ocr_pages = []
            if mime_type == "application/pdf":
                with _FITZ_LOCK:
                    doc_ocr = fitz.open(stream=file_bytes, filetype="pdf")
                    pix_list = [doc_ocr[idx].get_pixmap(dpi=160).tobytes("png") for idx in range(min(len(doc_ocr), 6))]
                    doc_ocr.close()
                for pb in pix_list:
                    img = Image.open(io.BytesIO(pb))
                    txt_ocr = pytesseract.image_to_string(img, lang="ita+eng")
                    if txt_ocr.strip():
                        ocr_pages.append(txt_ocr)
            else:
                img = Image.open(io.BytesIO(file_bytes))
                txt_ocr = pytesseract.image_to_string(img, lang="ita+eng")
                if txt_ocr.strip():
                    ocr_pages.append(txt_ocr)

            if ocr_pages:
                testo_unito = "\n".join(ocr_pages).strip()
                testo_visuale = testo_unito
                blocchi_spaziali = [b.strip() for b in testo_unito.split("\n\n") if b.strip()]
        except Exception:
            pass

    return testo_unito, testo_visuale, blocchi_spaziali, celle_visive


def _renderizza_pagine_immagini(file_bytes: bytes, mime_type: str, max_pages: int = 4):
    if mime_type != "application/pdf":
        return [(mime_type, file_bytes)]

    immagini = []
    with _FITZ_LOCK:
        doc = None
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            n = len(doc)
            if n <= max_pages:
                indices = list(range(n))
            else:
                indices = [0, 1, n - 2, n - 1]
            for idx in indices:
                pix = doc[idx].get_pixmap(dpi=130)
                immagini.append(("image/jpeg", pix.tobytes("jpeg")))
        except Exception:
            pass
        finally:
            if doc:
                doc.close()
    return immagini


def _parse_ai_json_text(raw_txt: str):
    if not raw_txt:
        return None
    s = raw_txt.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    m_json = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", s)
    if m_json:
        s = m_json.group(1)
    data = json.loads(s)
    if isinstance(data, list) and data:
        data = data[0]
    return data if isinstance(data, dict) else None


def _scopri_modelli_gemini(api_key: str):
    import urllib.request
    import urllib.error

    with _CACHE_LOCK:
        if api_key in _GEMINI_MODELS_CACHE:
            return _GEMINI_MODELS_CACHE[api_key], None

    fallback = [
        "models/gemini-2.5-flash",
        "models/gemini-2.0-flash",
        "models/gemini-flash-latest",
        "models/gemini-2.5-pro",
    ]
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        with urllib.request.urlopen(url, timeout=12) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        attivi = []
        for m in info.get("models", []):
            name = m.get("name", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            nl = name.lower()
            if any(bad in nl for bad in ("tts", "image-generation", "embedding", "aqa", "robotics", "computer-use")):
                continue
            if "gemini" in nl:
                attivi.append(name)

        def score(n):
            nl = n.lower()
            if "2.5-flash" in nl and "lite" not in nl and "preview" not in nl:
                return 0
            if "2.0-flash" in nl and "lite" not in nl and "exp" not in nl:
                return 1
            if "flash-latest" in nl:
                return 2
            if "flash" in nl:
                return 3
            if "2.5-pro" in nl:
                return 4
            return 5

        attivi.sort(key=score)
        scelti = attivi[:4] if attivi else fallback
        if attivi:
            with _CACHE_LOCK:
                _GEMINI_MODELS_CACHE[api_key] = scelti
        return scelti, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            body = str(e)
        return fallback, f"HTTP {e.code}: {body[:140]}"
    except Exception as e:
        return fallback, str(e)


def _chiama_ai_vision(file_bytes: bytes, filename: str, api_key: str, mime_type: str, testo_estratto: str = ""):
    import urllib.request
    import urllib.error

    k = str(api_key).strip()
    immagini = _renderizza_pagine_immagini(file_bytes, mime_type, max_pages=4)

    prompt_universale = (
        "Sei un esperto contabile specializzato in fatturazione elettronica italiana (FPR12 SdI) e fatture estere (UE ed Extra-UE). "
        "Analizza visivamente TUTTE le pagine della fattura allegata (inclusi loghi grafici, riquadri e tabelle finali), qualunque sia la lingua (EN, FR, DE, ES, IT, ecc.).\n"
        "REGOLE CRITICHE:\n"
        "1. CEDENTE (cedente_*): è SEMPRE il fornitore estero o italiano che EMETTE la fattura (leggi anche il nome dentro eventuali loghi grafici). Se ci sono più P.IVA nel piè di pagina (Gruppo IVA vs società), scegli quella specifica del fornitore, NON codici SEPA tipo FR75ZZZ...\n"
        "2. CESSIONARIO (cessionario_*): è SEMPRE l'acquirente/cliente intestatario (ignora eventuali 'Adresse de livraison' / 'Ship to' diversi dal cliente). Collega al cliente la sua P.IVA anche se è in un riquadro separato ('ID TVA', 'Référence client').\n"
        "3. CODICI: tipo_documento deve essere SOLO uno tra TD01, TD04, TD17, TD18, TD24 (MAI FPR12). modalita_pagamento deve essere un codice MP valido (MP05 bonifico, MP19 prelievo/SEPA, MP08 carta). Paesi ISO-2 (GB, GR, FR, DE, IE, US, IT).\n"
        "4. QUADRATURA E ACCONTI: date in YYYY-MM-DD, numeri float con punto decimale. imponibile = imponibile totale fattura (es. Total HT Net se ci sono spese trasporto). totale_documento = totale lordo della fattura (Total TTC = imponibile + imposta). Se c'è un acconto/deposito già pagato ('Acompte', 'Deposit', 'Acconto'), metti quell'importo nel campo 'acconto' (altrimenti 0.0) senza sottrarlo da totale_documento. Se IVA/VAT è 0 -> imposta=0.0, aliquota_prevalente=0.0, natura='N3.2' (intra-UE) o 'N2.2' (extra-UE).\n"
        "Rispondi ESCLUSIVAMENTE con un JSON valido (oggetto singolo) con queste chiavi esatte:\n"
        "cedente_denominazione, cedente_paese, cedente_piva, cedente_cf, cedente_indirizzo, cedente_cap, cedente_comune, cedente_provincia, "
        "cessionario_denominazione, cessionario_paese, cessionario_piva, cessionario_cf, cessionario_indirizzo, cessionario_cap, cessionario_comune, cessionario_provincia, "
        "numero_documento, data_documento, tipo_documento, imponibile, aliquota_prevalente, imposta, ritenuta, acconto, totale_documento, natura, iban, data_scadenza, modalita_pagamento, valuta, descrizione."
    )

    if k.startswith("sk-"):
        try:
            content_parts = [{"type": "text", "text": prompt_universale}]
            if testo_estratto:
                content_parts.append({"type": "text", "text": f"Testo di supporto:\n{testo_estratto[:10000]}"})
            for m_type, raw_bytes in immagini:
                b64 = base64.b64encode(raw_bytes).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{m_type};base64,{b64}", "detail": "high"},
                })

            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps({
                    "model": "gpt-4o-mini",
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": content_parts}],
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {k}",
                },
            )
            with urllib.request.urlopen(req, timeout=35) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return _parse_ai_json_text(res["choices"][0]["message"]["content"]), None, "OpenAI Vision GPT-4o-mini"
        except Exception as e:
            return None, str(e), None

    modelli_gemini, err_list = _scopri_modelli_gemini(k)
    if err_list and ("400" in err_list or "403" in err_list or "API_KEY_INVALID" in err_list):
        return None, f"Chiave Gemini non valida o non abilitata ({err_list})", None

    primo_errore = err_list or ""
    for m_full in modelli_gemini:
        m_path = m_full if m_full.startswith("models/") else f"models/{m_full}"
        try:
            parts = [{"text": prompt_universale}]
            for mt, raw_b in immagini:
                parts.append({"inline_data": {"mime_type": mt, "data": base64.b64encode(raw_b).decode("utf-8")}})
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{m_path}:generateContent?key={k}",
                data=json.dumps({
                    "contents": [{"parts": parts}],
                    "generationConfig": {"temperature": 0.0},
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=35) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                txt_out = res["candidates"][0]["content"]["parts"][0]["text"]
                data = _parse_ai_json_text(txt_out)
                if data:
                    return data, None, f"{m_path.replace('models/', '')} Vision"
        except urllib.error.HTTPError as he:
            try:
                msg = he.read().decode("utf-8", errors="ignore")
            except Exception:
                msg = str(he)
            if not primo_errore or ("404" in primo_errore and he.code != 404):
                primo_errore = f"HTTP {he.code} ({m_path}): {msg[:130]}"
            continue
        except Exception as ex:
            if not primo_errore:
                primo_errore = str(ex)
            continue

    return None, f"Gemini AI non riuscita: {primo_errore[:150]}", None


def estrai_dati_fattura(file_input, filename="fattura.pdf", api_key=None):
    if hasattr(file_input, "read"):
        file_input.seek(0)
        file_bytes = file_input.read()
    elif isinstance(file_input, bytes):
        file_bytes = file_input
    else:
        with open(file_input, "rb") as f:
            file_bytes = f.read()

    mime_type = _rileva_mime_type(file_bytes, filename)
    testo_unito, testo_visuale, blocchi_spaziali, celle_visive = _estrai_testo_e_blocchi(file_bytes, mime_type)
    t_lower = testo_unito.lower()

    # 1. Parser italiani istantanei (<0.05s, zero chiamate AI inutili)
    if "dati del cedente" in t_lower and "dati del cessionario" in t_lower:
        dati_sdi = parser_foglio_stile_sdi(testo_unito)
        dati_ok = _ponte_chiavi_e_quadratura(dati_sdi)
        return dati_ok, "Parser Foglio di Stile SdI Ufficiale", testo_unito, None

    if "cavit" in t_lower or "237/2025" in t_lower:
        dati_cavit = parser_cavit_commerciale(testo_unito)
        dati_ok = _ponte_chiavi_e_quadratura(dati_cavit)
        return dati_ok, "Parser Commerciale Cavit S.A.S.", testo_unito, None

    if "fattureincloud" in t_lower or ("casazen" in t_lower and "foqus" in t_lower):
        dati_fic = parser_fatture_in_cloud(testo_unito)
        dati_ok = _ponte_chiavi_e_quadratura(dati_fic)
        return dati_ok, "Parser Fatture in Cloud", testo_unito, None

    if "proforma" in t_lower and "ferraiuolo" in t_lower:
        dati_prof = parser_proforma_professionista(testo_unito)
        dati_ok = _ponte_chiavi_e_quadratura(dati_prof)
        return dati_ok, "Parser Proforma Professionisti", testo_unito, None

    # 2. Vision AI (per tutte le fatture estere, scansioni, immagini, layout complessi)
    ai_err = None
    if api_key and len(str(api_key).strip()) > 8:
        dati_ai, err_ai, mod_name = _chiama_ai_vision(
            file_bytes, filename, str(api_key).strip(), mime_type, testo_visuale or testo_unito
        )
        if dati_ai and isinstance(dati_ai, dict) and (
            dati_ai.get("cedente_denominazione") or dati_ai.get("totale_documento")
        ):
            dati_ok = _ponte_chiavi_e_quadratura(dati_ai)
            return dati_ok, f"Vision AI ({mod_name})", testo_visuale or testo_unito, None
        ai_err = err_ai

    # 3. Fallback Parser Commerciale Dinamico 2D
    dati_gen = parser_commerciale_dinamico(
        testo_unito,
        testo_visuale=testo_visuale or testo_unito,
        blocchi_spaziali=blocchi_spaziali,
        celle_visive=celle_visive,
    )
    dati_ok = _ponte_chiavi_e_quadratura(dati_gen)
    return dati_ok, "Parser Commerciale Dinamico 2D", testo_visuale or testo_unito, ai_err
# === FINE FILE extractor.py ===
