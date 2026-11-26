# === INIZIO FILE app.py ===
# app.py - AI Invoice to SdI/TeamSystem CONSPAY (v3.6 Multi-Fattura + Archivio Cliente/Anno/Mese)
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
    from archivio import salva_in_cartella_locale, salva_su_google_drive
    ARCHIVIO_OK = True
    ARCHIVIO_ERR = ""
except Exception as e_arch:
    ARCHIVIO_OK = False
    ARCHIVIO_ERR = str(e_arch)

for k in ["invoice_cache", "batch_order"]:
    if k not in st.session_state:
        st.session_state[k] = {} if k == "invoice_cache" else []

try:
    secrets_dict = dict(st.secrets)
except Exception:
    secrets_dict = {}

with st.sidebar:
    st.title("⚙️ Impostazioni")
    secret_key = secrets_dict.get("GEMINI_API_KEY", "")
    api_key_input = st.text_input("Google Gemini API Key", value=secret_key, type="password")
    if api_key_input and len(api_key_input.strip()) > 10:
        st.success("🟢 Chiave IA Attiva")
    else:
        st.info("ℹ️ Chiave opzionale (Parser Locale Attivo)")

    st.divider()
    codice_dest_default = st.text_input("Codice SdI Destinatario", value="0000000", max_chars=7)

    st.divider()
    st.subheader("📁 Archivio Cliente / Mese")
    modo_archivio = st.radio(
        "Dove salvare le cartelle",
        ["Google Drive (Cloud API)", "Cartella sul PC / Drive Desktop"],
        index=0
    )
    if modo_archivio == "Google Drive (Cloud API)":
        dest_archivio = st.text_input(
            "Cartella Google Drive (Link, ID o Nome)",
            value="Fatture_XML_SdI",
            help="Account: martina.studio.evangelista@gmail.com. Puoi incollare il link della cartella Drive o scrivere un nome."
        )
    else:
        dest_archivio = st.text_input(
            "Percorso cartella sul PC / Mac",
            value="./Archivio_Fatture_XML",
            help="Es. G:/Il mio Drive/Fatture_XML oppure C:/Studio/Fatture"
        )
    precrea_12_mesi = st.checkbox("Crea subito tutti i 12 mesi (Gen–Dic)", value=True)
    salva_anche_pdf = st.checkbox("Salva anche il PDF originale nel mese", value=False)

st.title("🧾 AI Invoice to SdI / TeamSystem CONSPAY")
st.caption("Fatturazione FPR12 v1.2.2 - Lettura Italia/Estero e archiviazione automatica per Cliente e Mese.")

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

def archivia_singolo_item(item):
    if not ARCHIVIO_OK:
        return False, f"Modulo archivio.py non disponibile: {ARCHIVIO_ERR}", False
    d = item["invoice_data"]
    cli_nome = d.get("cessionario_denominazione") or "CLIENTE"
    cli_piva = d.get("cessionario_piva") or d.get("cessionario_cf") or ""
    data_doc = d.get("data_documento") or ""
    pdf_n = item["orig_filename"] if salva_anche_pdf else None
    pdf_b = item["orig_bytes"] if salva_anche_pdf else None

    if modo_archivio == "Google Drive (Cloud API)":
        return salva_su_google_drive(
            drive_destinazione=dest_archivio,
            cliente_nome=cli_nome,
            cliente_piva=cli_piva,
            data_documento=data_doc,
            xml_filename=item["xml_filename"],
            xml_content=item["xml_content"],
            precrea_12_mesi=precrea_12_mesi,
            pdf_filename=pdf_n,
            pdf_bytes=pdf_b,
            secrets_dict=secrets_dict,
        )
    return salva_in_cartella_locale(
        root_path=dest_archivio,
        cliente_nome=cli_nome,
        cliente_piva=cli_piva,
        data_documento=data_doc,
        xml_filename=item["xml_filename"],
        xml_content=item["xml_content"],
        precrea_12_mesi=precrea_12_mesi,
        pdf_filename=pdf_n,
        pdf_bytes=pdf_b,
    )

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
            if st.button("☁️ SALVA IN ARCHIVIO (Cliente/Mese)", key=f"arch_btn_{fid}", use_container_width=True):
                with st.spinner("Salvataggio ordinato per Cliente / Anno / Mese..."):
                    ok_a, msg_a, nuovo_c = archivia_singolo_item(item)
                if ok_a:
                    tag_c = "🆕 Nuovo cliente creato" if nuovo_c else "📂 Cliente esistente riconosciuto"
                    st.success(f"✅ {tag_c}: `{msg_a}`")
                else:
                    st.error(f"❌ {msg_a}")

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
    has_ai_key = bool(api_key_input and len(api_key_input.strip()) > 10)
    max_w = min(3 if has_ai_key else 6, tot_el)

    with st.status(f"Elaborazione veloce di {tot_el} fattura/e...", expanded=True) as status:
        prog_bar = st.progress(0)
        msg_slot = st.empty()
        done_count = 0

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
# RIEPILOGO E DOWNLOAD MASSIVO + ARCHIVIAZIONE + SCHEDE
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
    with zipfile.ZipFile(zip_only_xml, "w", zipfile.ZIP_DEFLATED) as z_xml:
        for item in batch_items:
            x_name = item["xml_filename"]
            if x_name in nomi_usati_xml:
                x_name = f"{item['idx']:02d}_{x_name}"
            nomi_usati_xml.add(x_name)
            z_xml.writestr(x_name, item["xml_content"].encode("utf-8"))

    nomi_usati_xml = set()
    with zipfile.ZipFile(zip_all_full, "w", zipfile.ZIP_DEFLATED) as z_full:
        for item in batch_items:
            x_name = item["xml_filename"]
            if x_name in nomi_usati_xml:
                x_name = f"{item['idx']:02d}_{x_name}"
            nomi_usati_xml.add(x_name)
            z_full.writestr(x_name, item["xml_content"].encode("utf-8"))
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

    if st.button(
        f"☁️ ARCHIVIA TUTTE LE {len(batch_items)} FATTURE PER CLIENTE E MESE ({modo_archivio})",
        key="btn_archivia_batch",
        use_container_width=True
    ):
        with st.status("Archiviazione ordinata per Cliente / Anno / Mese...", expanded=True) as st_arch:
            bar_a = st.progress(0)
            tot_a = len(batch_items)
            tutti_ok = True
            for i_a, item in enumerate(batch_items, start=1):
                ok_a, msg_a, nuovo_c = archivia_singolo_item(item)
                if ok_a:
                    tag_c = "🆕 Nuovo cliente" if nuovo_c else "📂 Cliente esistente"
                    st.write(f"✅ {tag_c} ➔ `{msg_a}`")
                else:
                    tutti_ok = False
                    st.error(f"❌ {item['orig_filename']}: {msg_a}")
                bar_a.progress(i_a / tot_a)
            st_arch.update(
                label="✅ Archiviazione completata!" if tutti_ok else "⚠️ Archiviazione completata con avvisi",
                state="complete" if tutti_ok else "error",
                expanded=True
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
