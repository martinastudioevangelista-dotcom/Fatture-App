# extractor.py - Motore Fiscale con Anagrafiche Bloccate e Risolutore Contabile Avanzato
import re
import json
import fitz  # PyMuPDF
from datetime import datetime

def pulisci_cifra(s):
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    try:
        t = str(s).strip().replace("€", "").replace(" ", "")
        # Gestione separatori italiani (es. 2.620,00 o 716,04)
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

def estrai_indirizzo_cap_comune(testo_blocco):
    """Logica anagrafica consolidata e bloccata."""
    indirizzo = ""
    cap = "00100"
    comune = "Roma"
    prov = "RM"
    righe = [r.strip() for r in str(testo_blocco).split("\n") if r.strip()]

    for riga in righe:
        m_cap = re.search(r"\b(\d{5})\b\s+([A-Za-z\s']+?)(?:\s*\(([A-Z]{2})\)|\s+([A-Z]{2})\b|$)", riga)
        if m_cap:
            cap = m_cap.group(1)
            comune = m_cap.group(2).strip().title()
            prov = (m_cap.group(3) or m_cap.group(4) or "RM").upper()
            break

    for riga in righe:
        if re.search(r"\b(via|viale|corso|piazza|strada|localit|vicolo)\b", riga, re.IGNORECASE):
            r_pulita = re.sub(r"-\s*\d{5}.*", "", riga).strip()
            r_pulita = re.sub(r"\b\d{5}\b.*", "", r_pulita).strip()
            indirizzo = r_pulita
            break

    if not indirizzo and len(righe) > 1:
        indirizzo = righe[1]

    return indirizzo[:60], cap, comune[:60], prov

# ---------------------------------------------------------
# NUOVO MOTORE CONTABILE AD ALTA PRECISIONE
# ---------------------------------------------------------
def riso
