# extractor.py - Versione ad alte prestazioni (Anti-Freeze / Zero Timeout)
import re
import io
import fitz  # PyMuPDF
import json
from datetime import datetime
import streamlit as st

def parse_importo(val_str: str) -> float:
    """Converte formati contabili italiani o internazionali in float sicuro."""
    if not val_str:
        return 0.0
    val_str = str(val_str).strip().replace("€", "").replace(" ", "")
    if "," in val_str and "." in val_str:
        if val_str.rfind(",") > val_str.rfind("."):
            val_str = val_str.replace(".", "").replace(",", ".")
        else:
            val_str = val_str.replace(",", "")
    elif "," in val_str:
        val_str = val_str.replace(",", ".")
    try:
        return round(float(val_str), 2)
    except ValueError:
        return 0.0

def trova_tripletta_ottimizzata(numeri: list) -> tuple:
    """
    Scansione istantanea limitata ai migliori candidati (max 35 numeri).
    Complessità circoscritta a < 1.000 combinazioni (< 0.01 sec).
    """
    if not numeri:
        return None, None, None, 22.0

    # Considera solo numeri contabili verosimili, ordinati in senso decrescente
    candidati = sorted(list(set(n for n in numeri if 0.50 <= n < 500_000.0)), reverse=True)[:35]
    aliquote_reali = [22.0, 10.0, 5.0, 4.0]

    for c in candidati:  # Totale
        for a in candidati:  # Imponibile
            if a >= c:
                continue
            b = round(c - a, 2)  # IVA presunta
            if b <= 0.05:
                continue
            
            # Calcolo aliquota corrispondente
            rapporto = round((b / a) * 100.0, 1)
            for aliq in aliquote_reali:
                if abs(rapporto - aliq) <= 0.4:
                    return a, b, c, aliq

    return None, None, None, 22.0

def estrai_con_pymupdf(file_bytes: bytes) -> dict:
    """Estrazione testuale ultra-rapida da stream PDF."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return None

    testo_completo = ""
    # Analizza massimo le prime 3 pagine per evitare blocchi su fascicoli lunghi
    for i in range(min(len(doc), 3)):
        testo_completo += doc[i].get_text("text") + "\n"

    # Se il testo è quasi assente (< 40 caratteri), è una scansione raster
    if len(testo_completo.strip()) < 40:
        return None

    # 1. Partite IVA (11 cifre)
    piva_matches = re.findall(r"\b([0-9]{11})\b", testo_completo)
    piva_uniche = list(dict.fromkeys(piva_matches))
    cedente_piva = piva_uniche[0] if len(piva_uniche) > 0 else ""
    cessionario_piva = piva_uniche[1] if len(piva_uniche) > 1 else ""

    # 2. Data Documento
    date_patterns = [
        r"\b([0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[2-3][0-9])\b",
        r"\b((?:20)[2-3][0-9][/\-.][0-1]?[0-9][/\-.][0-3]?[0-9])\b"
    ]
    data_doc = datetime.today().strftime(
