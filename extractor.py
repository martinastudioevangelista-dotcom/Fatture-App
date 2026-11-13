"""
extractor.py - VERSIONE UNIVERSALE ITALIA + ESTERO (MULTI-PAGINA & MULTI-LAYOUT)
- Preserva al 100% tutti i parser italiani consolidati (SdI, Cavit, Fatture in Cloud, Proforma, Dinamico IT).
- Estende il riconoscimento a fatture estere UE/Extra-UE su 1 o più pagine e qualsiasi layout grafico.
"""

import base64
from datetime import datetime
import json
import re
import fitz  # PyMuPDF


KNOWN_BUYER_PIVAS = {"09847131217"}

EU_COUNTRIES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "GR", "ES", "FI",
    "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
    "RO", "SE", "SI", "SK", "XI",
}

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

    # 1. VAT Svizzera
    for m in re.finditer(r"\b(CHE[\s.-]?\d{3}[\s.-]?\d{3}[\s.-]?\d{3})\b", testo, re.IGNORECASE):
        cod = re.sub(r"[^A-Z0-9]", "", m.group(1).upper())
        if ("CH", cod) not in visti:
            visti.add(("CH", cod))
            risultati.append(("CH", cod, m.start()))

    # 2. VAT UE / GB / XI / NO con prefisso Paese
    prefissi = "AT|BE|BG|CY|CZ|DE|DK|EE|EL|GR|ES|FI|FR|GB|UK|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI|NO"
    pat_vat_eu = rf"\b({prefissi})[\s.-]*([A-Z0-9]{{1,4}}(?:[\s.-]*[A-Z0-9]{{2,5}}){{1,4}})\b"
    for m in re.finditer(pat_vat_eu, testo):
        paese_raw = m.group(1).upper()
        body = re.sub(r"[\s.-]", "", m.group(2).upper())
        full = paese_raw + body

        if len(body) < 7 or len(body) > 13:
            continue
        if not any(ch.isdigit() for ch in body):
            continue
        if any(full in ib or ib.startswith(full) for ib in ibans):
            continue
        if paese_raw == "IT" and not re.fullmatch(r"\d{11}", body):
            continue

        paese = normalizza_codice_paese(paese_raw)
        if (paese, body) not in visti:
            visti.add((paese, body))
            risultati.append((paese, body, m.start()))

    # 3. P.IVA Italiana con etichetta
    for m in re.finditer(
        r"(?:P\.?\s*IVA|Partita\s+IVA|VAT(?:\s+ID|\s+No\.?|\s+Number)?|C\.?F\.?[\s/]*P\.?\s*IVA)[:\s]*(?:IT)?(\d{11})\b",
        testo,
        re.IGNORECASE,
    ):
        cod = m.group(1)
        if ("IT", cod) not in visti:
            visti.add(("IT", cod))
            risultati.append(("IT", cod, m.start()))

    # 4. US EIN
    for m in re.finditer(
        r"(?:EIN|Tax\s*ID|Federal\s*Tax\s*ID|TIN)[:\s#]*([0-9]{2}-[0-9]{7})\b",
        testo,
        re.IGNORECASE,
    ):
        cod = m.group(1).replace("-", "")
        if ("US", cod) not in visti:
            visti.add(("US", cod))
            risultati.append(("US", cod, m.start()))

    # 5. Fallback compatibile per P.IVA italiane a 11 cifre anche senza etichetta adiacente
    for m in re.finditer(r"(?<!\d)(\d{11})(?!\d)", testo):
        cod = m.group(1)
        ctx = testo[max(0, m.start() - 35):m.end() + 15]
        if re.search(r"(?:tel|phone|fax|cell|iban|swift|bic|conto|account|\+\d)", ctx, re.IGNORECASE):
            continue
        if any(cod in ib for ib in ibans):
            continue
        if ("IT", cod) not in visti:
            visti.add(("IT", cod))
            risultati.append(("IT", cod, m.start()))

    return risultati


def rileva_paese_da_blocco(testo_blocco: str, default: str = "") -> str:
    if not testo_blocco:
        return default
    t_low = testo_blocco.lower()
    for nome_paese, iso in sorted(FOREIGN_COUNTRY_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"\b{re.escape(nome_paese)}\b", t_low):
            return iso
    if re.search(r"\b(italia|italy)\b", t_low):
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
        r"\b(?:Via|Viale|V\.le|Corso|C\.so|Piazza|P\.zza|Strada|Str\.|Vicolo|Largo|Loc\.|Localit[àa]|"
        r"Street|St\.|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Way|Parkway|Square|Plaza|"
        r"Rue|Place|Chemin|Allée|Straße|Strasse|Str\.|Platz|Weg|Calle|Carrera|Avenida|Avda\.?|Straat|Gracht)\b"
        r"[^\n\r;]+",
        testo_str,
        re.IGNORECASE,
    )
    if m_via:
        indirizzo = m_via.group(0).strip()
        indirizzo = re.sub(r"[\s\-–,]*\b\d{4,5}\b.*", "", indirizzo).strip()
    else:
        for riga in testo_str.split("\n"):
            r = riga.strip()
            if (
                re.search(r"\b\d{1,5}[A-Za-z]?(?:/[\w\-]+)?\b", r)
                and 6 < len(r) < 70
                and not re.search(
                    r"(?:IVA|VAT|CF|EIN|IBAN|BIC|SWIFT|Tel|Phone|Fax|Email|@|http|www\.|Invoice|Fattura|Date|Data|Total|Page|Amount)",
                    r,
                    re.IGNORECASE,
                )
            ):
                indirizzo = r
                break

    if not comune:
        for city_kw in ("Dublin", "London", "Paris", "Berlin", "Munich", "Amsterdam", "Brussels", "Madrid", "Barcelona", "Luxembourg", "Zurich", "Geneva", "Vienna", "New York", "San Francisco", "Mountain View", "Austin", "Seattle", "Singapore"):
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
        else:
            if aliq is None or aliq == 0.0:
                aliq = round((tax / imp) * 100.0, 2) if imp > 0 else 0.0
            if tot == 0.0 and imp > 0:
                tot = round(imp + tax, 2)
            elif imp == 0.0 and tot > tax:
                imp = round(tot - tax, 2)
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

    metodo = str(
        dati.get("modalita_pagamento")
        or dati.get("metodo_pagamento")
        or "MP05"
    ).strip()
    iban_val = estrai_iban_universale(str(dati.get("iban") or ""))

    if f_paese != "IT" and aliq == 0.0:
        natura_val = natura_in if natura_in.startswith("N") else ("N3.2" if f_paese in EU_COUNTRIES else "N2.2")
    else:
        natura_val = natura_in if aliq == 0.0 else ""

    return {
        "tipo_documento": str(dati.get("tipo_documento") or "TD01"),
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
        "numero_documento": "2
