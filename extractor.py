# extractor.py - Motore di Estrazione Fiscale Chirurgico
import re
import json
import fitz  # PyMuPDF
from datetime import datetime

def pulisci_cifra(s) -> float:
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    try:
        t = str(s).strip().replace("€", "").replace(" ", "")
        if "," in t and "." in t:
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif "," in t:
            t = t.replace(",", ".")
        return round(float(t), 2)
    except Exception:
        return 0.0

def estrai_indirizzo_cap_comune(testo_blocco: str) -> tuple:
    """Estrae Via, CAP, Comune e Provincia da un blocco di testo anagrafico."""
    indirizzo = ""
    cap = "00100"
    comune = "Roma"
    prov = "RM"

    righe = [r.strip() for r in testo_blocco.split("\n") if r.strip()]
    
    # 1. Cerca riga con CAP (5 cifre) e Provincia es: 80141 Napoli (NA) oppure 80126 NAPOLI (NA)
    for riga in righe:
        m_cap = re.search(r"\b(\d{5})\b\s+([A-Za-z\s']+?)(?:\s*\(([A-Z]{2})\)|\s+([A-Z]{2})\b|$)", riga)
        if m_cap:
            cap = m_cap.group(1)
            comune = m_cap.group(2).strip().title()
            prov = (m_cap.group(3) or m_cap.group(4) or "RM").upper()
            break

    # 2. Cerca riga con Indirizzo (Via, Viale, Corso, Piazza, ecc.)
    for riga in righe:
        if re.search(r"\b(via|viale|corso|piazza|strada|localit[àa]|vicolo)\b", riga, re.IGNORECASE):
            # Se la riga contiene anche il CAP, ripulisci
            indirizzo = re.sub(r"-\s*\d{5}.*", "", riga).strip()
            indirizzo = re.sub(r"\b\d{5}\b.*", "", indirizzo).strip()
            break

    if not indirizzo and len(righe) > 1:
        indirizzo = righe[1]

    return indirizzo[:60], cap, comune[:60], prov

def parser_locale_fattura(testo: str) -> dict:
    """Parser locale per fatture italiane con intestazione fornitore e box destinatario."""
    # 1. Ricerca Partite IVA (11 cifre) reali
    pivas = re.findall(r"\b(\d{11})\b", testo)
    
    # 2. Cerca specificamente P.IVA con etichetta
    piva_fornitore = ""
    piva_cliente = ""

    # Ricerca P.IVA cliente nel box Destinatario / Spett.le
    m_dest = re.search(r"(?:destinatario|destinazione|spett\.?le)[\s\S]{1,400}?(?:p\.?\s*iva|c\.?\s*f\.?)[\s:]*([0-9]{11})", testo, re.IGNORECASE)
    if m_dest:
        piva_cliente = m_dest.group(1)

    m_ced = re.search(r"(?:c\.?f\.?\/p\.?\s*iva|p\.?\s*iva|partita\s*iva)[\s:]*([0-9]{11})", testo, re.IGNORECASE)
    if m_ced and m_ced.group(1) != piva_cliente:
        piva_fornitore = m_ced.group(1)

    # Fallback assegnazione P.IVA
    if not piva_fornitore and pivas:
        piva_fornitore = pivas[0]
    if not piva_cliente:
        for p in pivas:
            if p != piva_fornitore:
                piva_cliente = p
                break

    # 3. Denominazione Fornitore (Cedente)
    # Cerca la ragione sociale in testata (prima del box Destinatario)
    m_rag_ced = re.search(r"([A-Za-z0-9\s.,&'\-]{3,70}(?:S\.?A\.?S\.?|S\.?R\.?L\.?|S\.?P\.?A\.?|S\.?N\.?C\.?)[A-Za-z0-9\s.,&'\-]*)", testo[:1000], re.IGNORECASE)
    if m_rag_ced:
        ced_nome = m_rag_ced.group(1).strip()
    else:
        righe = [r.strip() for r in testo.split("\n") if len(r.strip()) > 3]
        ced_nome = righe[0] if righe else "FORNITORE"

    # Indirizzo Fornitore
    ced_via, ced_cap, ced_com, ced_prov = estrai_indirizzo_cap_comune(testo[:800])

    # 4. Denominazione e Indirizzo Cliente (Destinatario)
    cess_nome = "CLIENTE STUDIO"
    cess_via = "Via Cliente 1"
    cess_cap = "00100"
    cess_com = "Roma"
    cess_prov = "RM"

    m_box_dest = re.search(r"Destinatario\s*\n+([^\n]+)([\s\S]*?)(?=Fattura|Codice|Quantit|nr\.|$)", testo, re.IGNORECASE)
    if m_box_dest:
        cess_nome = m_box_dest.group(1).strip()
        corpo_dest = m_box_dest.group(2)
        cess_via, cess_cap, cess_com, cess_prov = estrai_indirizzo_cap_comune(corpo_dest)
    else:
        # Alternativa con keyword Spett.le
        m_spett = re.search(r"Spett\.?le\s*\n+([^\n]+)([\s\S]*?)(?=Fattura|Codice|Quantit|$)", testo, re.IGNORECASE)
        if m_spett:
            cess_nome = m_spett.group(1).strip()
            cess_via, cess_cap, cess_com, cess_prov = estrai_indirizzo_cap_comune(m_spett.group(2))

    # 5. Estremi Fattura (Numero e Data)
    # Es: "Fattura nr. 237/2025 del 24/04/2025"
    num_doc = "1"
    data_doc = datetime.today().strftime("%Y-%m-%d")
    
    m_num_data = re.search(r"(?:fattura\s+nr\.?|nr\.?|fattura\s+n\.?)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)\s*(?:del)?\s*([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])", testo, re.IGNORECASE)
    if m_num_data:
        num_doc = m_num_data.group(1).strip()
        d_raw = m_num_data.group(2).replace("/", "-").replace(".", "-").split("-")
        data_doc = f"{d_raw[2]}-{d_raw[1].zfill(2)}-{d_raw[0].zfill(2)}"
    else:
        m_num = re.search(r"(?:fattura|doc|num|n°)\s*[:.\s]?\s*([A-Za-z0-9/\-_]+)", testo, re.IGNORECASE)
        if m_num:
            num_doc = m_num.group(1).strip()

    # 6. Sezione Contabile (Imponibile, Imposta, Totale)
    # Es: "Imponibile 22% € 162,29", "Imposta € 35,71", "Tot. documento € 198,00"
    imponibile = 0.0
    imposta = 0.0
    totale = 0.0
    aliquota = 22.0

    m_imp = re.search(r"Imponibile(?:\s*22%)?\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_imp:
        imponibile = pulisci_cifra(m_imp.group(1))

    m_iva = re.search(r"Imposta\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_iva:
        imposta = pulisci_cifra(m_iva.group(1))

    m_tot = re.search(r"(?:Tot\.?\s*documento|Totale\s*documento|Totale\s*fattura)\s*[:€\s]*([\d.,]+)", testo, re.IGNORECASE)
    if m_tot:
        totale = pulisci_cifra(m_tot.group(1))

    if totale == 0.0 and (imponibile > 0 or imposta > 0):
        totale = round(imponibile + imposta, 2)

    # 7. Pagamento (CONSPAY)
    # Es: "Pagamento: Carta di pagamento", "Scadenze: 24/04/2025 € 198,00"
    metodo_pag = "MP05"
    if re.search(r"carta\s+di\s+pagamento|carta\s+di\s+credito|pos|bancomat", testo, re.IGNORECASE):
        metodo_pag = "MP08"
    elif re.search(r"bonifico", testo, re.IGNORECASE):
        metodo_pag = "MP05"
    elif re.search(r"riba|ricevuta\s+bancaria", testo, re.IGNORECASE):
        metodo_pag = "MP12"
    elif re.search(r"contanti", testo, re.IGNORECASE):
        metodo_pag = "MP01"

    data_scadenza = data_doc
    m_scad = re.search(r"Scadenze?:\s*([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])", testo, re.IGNORECASE)
    if m_scad:
        d_sc = m_scad.group(1).replace("/", "-").replace(".", "-").split("-")
        data_scadenza = f"{d_sc[2]}-{d_sc[1].zfill(2)}-{d_sc[0].zfill(2)}"

    m_iban = re.search(r"\b(IT\d{2}[A-Z]\d{10}[0-9A-Z]{12})\b", testo.replace(" ", "").upper())
    iban_doc = m_iban.group(1) if m_iban else ""

    return {
        "tipo_documento": "TD01",
        "numero_documento": num_doc,
        "data_documento": data_doc,
        "cedente_denominazione": ced_nome,
        "cedente_paese": "IT",
        "cedente_piva": piva_fornitore,
        "cedente_indirizzo": ced_via,
        "cedente_cap": ced_cap,
        "cedente_comune": ced_com,
        "cedente_provincia": ced_prov,
        "cessionario_denominazione": cess_nome,
        "cessionario_paese": "IT",
        "cessionario_piva": piva_cliente,
        "cessionario_cf": "",
        "cessionario_indirizzo": cess_via,
        "cessionario_cap": cess_cap,
        "cessionario_comune": cess_com,
        "cessionario_provincia": cess_prov,
        "imponibile": imponibile,
        "aliquota_prevalente": aliquota,
        "imposta": imposta,
        "totale_documento": totale,
        "natura": "",
        "iban": iban_doc,
        "data_scadenza": data_scadenza,
        "modalita_pagamento": metodo_pag
    }

def estrai_con_gemini(file_bytes: bytes, filename: str, api_key: str, testo: str) -> tuple:
    """Interroga Gemini con prompt mirato. Ritorna (dati: dict, errore: str)."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""
        Estrai i dati fiscali da questa fattura italiana per il software TeamSystem CONSPAY.
        Testo fattura:
        {testo[:6000]}

        Regole ferree:
        - CEDENTE (Fornitore): chi emette (es. Cavit S.A.S.). Estrai nome, P.IVA (11 cifre), indirizzo, CAP, comune e provincia (2 lettere).
        - CESSIONARIO (Cliente): chi riceve, sotto 'Destinatario' o 'Spett.le' (es. CASAZEN S.R.L.). Estrai nome, P.IVA, indirizzo, CAP, comune e provincia.
        - DOCUMENTO: numero fattura (es. 237/2025) e data (YYYY-MM-DD).
        - CONTABILITA: imponibile, aliquota IVA, imposta IVA, totale documento.
        - PAGAMENTO: modalita (se carta di pagamento metti MP08, se bonifico MP05), data scadenza e IBAN.

        Rispondi ESCLUSIVAMENTE con un JSON con questi campi:
        {{
          "cedente_denominazione": "", "cedente_paese": "IT", "cedente_piva": "", "cedente_indirizzo": "", "cedente_cap": "", "cedente_comune": "", "cedente_provincia": "NA",
          "cessionario_denominazione": "", "cessionario_paese"
