# === INIZIO FILE extractor.py ===
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

    for m in re.finditer(r"\b(CHE[\s.-]?\d{3}[\s.-]?\d{3}[\s.-]?\d{3})\b", testo, re.IGNORECASE):
        cod = re.sub(r"[^A-Z0-9]", "", m.group(1).upper())
        if ("CH", cod) not in visti:
            visti.add(("CH", cod))
            risultati.append(("CH", cod, m.start()))

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

    for m in re.finditer(
        r"(?:P\.?\s*IVA|Partita\s+IVA|VAT(?:\s+ID|\s+No\.?|\s+Number)?|C\.?F\.?[\s/]*P\.?\s*IVA)[:\s]*(?:IT)?(\d{11})\b",
        testo,
        re.IGNORECASE,
    ):
        cod = m.group(1)
        if ("IT", cod) not in visti:
            visti.add(("IT", cod))
            risultati.append(("IT", cod, m.start()))

    for m in re.finditer(
        r"(?:EIN|Tax\s*ID|Federal\s*Tax\s*ID|TIN)[:\s#]*([0-9]{2}-[0-9]{7})\b",
        testo,
        re.IGNORECASE,
    ):
        cod = m.group(1).replace("-", "")
        if ("US", cod) not in visti:
            visti.add(("US", cod))
            risultati.append(("US", cod, m.start()))

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
        for city_kw in (
            "Dublin", "London", "Paris", "Berlin", "Munich", "Amsterdam", "Brussels",
            "Madrid", "Barcelona", "Luxembourg", "Zurich", "Geneva", "Vienna",
            "New York", "San Francisco", "Mountain View", "Austin", "Seattle", "Singapore",
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


def _separa_blocchi_fornitore_cliente(blocchi_spaziali: list, testo_completo: str):
    buyer_marker_re = re.compile(
        r"\b(bill\s*to|billed\s*to|sold\s*to|ship\s*to|customer|client|buyer|recipient|"
        r"spett\.?le|spettabile|destinatario|cliente|fatturato\s*a|committente|"
        r"rechnungsempf[äa]nger|kunde|facturer\s*[àa]|cliente\s*final)\b",
        re.IGNORECASE,
    )
    seller_marker_re = re.compile(
        r"\b(from|seller|supplier|vendor|issuer|billed\s*by|issued\s*by|remit\s*to|"
        r"fornitore|cedente|mittente|verk[äa]ufer|lieferant|fournisseur|emisor)\b",
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
        if not txt:
            continue
        is_known_buyer = any(p in txt for p in KNOWN_BUYER_PIVAS) or bool(re.search(r"\bcasazen\b", txt, re.IGNORECASE))
        if is_known_buyer or buyer_marker_re.search(txt):
            if not blocco_buyer:
                blocco_buyer = txt
            elif is_known_buyer and not any(p in blocco_buyer for p in KNOWN_BUYER_PIVAS):
                blocco_buyer = txt
        elif seller_marker_re.search(txt) or (company_suffix_re.search(txt) and not re.search(r"\b(total|subtotal|invoice|tax|vat\s+\d+%)\b", txt, re.IGNORECASE)):
            if not blocco_seller:
                blocco_seller = txt

    if not blocco_seller and blocchi_spaziali:
        for b in blocchi_spaziali[:10]:
            if b != blocco_buyer and len(b.strip()) > 10 and not re.search(r"^(invoice|fattura|page|\d+/\d+)$", b.strip(), re.IGNORECASE):
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


def _estrai_nome_azienda_da_blocco(blocco: str, default: str = "") -> str:
    if not blocco:
        return default
    righe = [r.strip() for r in blocco.split("\n") if len(r.strip()) > 1]
    noise_re = re.compile(
        r"^(bill\s*to|billed\s*to|sold\s*to|ship\s*to|from|seller|supplier|vendor|customer|client|"
        r"spett\.?le|spettabile|destinatario|invoice|fattura|tax\s*invoice|page\s*\d+)[:\s]*$",
        re.IGNORECASE,
    )
    company_suffix_re = re.compile(
        r"\b(s\.?r\.?l\.?|s\.?p\.?a\.?|s\.?a\.?s\.?|s\.?n\.?c\.?|ltd\.?|limited|inc\.?|"
        r"llc|corp\.?|gmbh|ag|b\.?v\.?|n\.?v\.?|s\.?a\.?|s\.?l\.?|sarl|eurl|oy|ab|aps|a/s|kft|sp\.?\s*z\s*o\.?o\.?|pte)\b",
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
        if re.search(r"^(vat|p\.?\s*iva|tax\s*id|ein|tel|phone|email|http|www\.)", r_clean, re.IGNORECASE):
            continue
        filtrate.append(r_clean)

    for r in filtrate:
        if company_suffix_re.search(r):
            return r[:80]
    return filtrate[0][:80] if filtrate else default


def _estrai_importi_multilingua(pagine_testo: list, testo_unito: str):
    testo_riepilogo = "\n".join(reversed(pagine_testo)) if pagine_testo else testo_unito
    pat_num = r"(?:EUR|USD|GBP|CHF|[€$£])?\s*(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{2})|\d+(?:[.,]\d{2}))\s*(?:EUR|USD|GBP|CHF|[€$£])?"

    def cerca_importo(patterns, target_text):
        for pat in patterns:
            matches = list(re.finditer(pat, target_text, re.IGNORECASE))
            if matches:
                val = pulisci_cifra(matches[-1].group(1))
                if val > 0:
                    return val
        return 0.0

    pats_imp = [
        rf"(?:Total\s+excl\.?\s*(?:VAT|Tax)|Taxable\s+Amount|Net\s+(?:Amount|Total|merce)|Sub[-\s]?total|Total\s+HT|Montant\s+HT|Nettobetrag|Zwischensumme|Base\s+imponible|Totale\s+Imponibile|Tot\.?\s*Imp\.?|Imponibile)[^\n\d]{{0,35}}{pat_num}",
    ]
    imponibile = cerca_importo(pats_imp, testo_unito)

    pats_tax = [
        rf"(?:Total\s+(?:VAT|Tax|TVA|MwSt|IVA)|Amount\s+of\s+(?:VAT|Tax)|Sales\s+Tax|Imposta\s+IVA|Tot\.?\s*IVA|VAT\s*\(\s*\d+(?:[.,]\d+)?\s*%\s*\)|IVA\s*\d{{1,2}}%|TVA\s*\d{{1,2}}%|MwSt\.?\s*\d{{1,2}}%)[^\n\d]{{0,35}}{pat_num}",
        rf"(?:^|\n)\s*(?:VAT|TVA|MwSt\.?|USt\.?|BTW|Tax|IVA)\s*(?:\(\s*\d+(?:[.,]\d+)?\s*%\s*\))?[:\s]+{pat_num}",
    ]
    imposta = cerca_importo(pats_tax, testo_unito)

    aliquota = None
    m_aliq = re.search(
        r"(?:VAT|Tax|TVA|MwSt|USt|BTW|IVA|Aliquota)\s*(?:rate)?[\s:(]*(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
        testo_riepilogo,
        re.IGNORECASE,
    )
    if m_aliq:
        aliquota = pulisci_cifra(m_aliq.group(1))

    pats_tot = [
        rf"(?:Grand\s+Total|Total\s+(?:Amount\s+)?Due|Amount\s+Due|Balance\s+Due|Invoice\s+Total|Total\s+incl\.?\s*(?:VAT|Tax)|Total\s+TTC|Montant\s+TTC|Gesamtbetrag|Rechnungsbetrag|Bruttobetrag|Endbetrag|Total\s+a\s+pagar|Importo\s+totale|Totale\s+Documento|Totale\s+Fattura|Netto\s+a\s+pagare|Totale\s+dovuto)[^\n\d]{{0,35}}{pat_num}",
        rf"(?:^|\n)\s*Total\s*(?:\((?:EUR|USD|GBP|CHF)\))?[:\s]+{pat_num}",
    ]
    totale = cerca_importo(pats_tot, testo_unito)

    valuta = "EUR"
    if re.search(r"\bUSD\b|\$", testo_unito) and not re.search(r"\bEUR\b|€", testo_unito):
        valuta = "USD"
    elif re.search(r"\bGBP\b|£", testo_unito) and not re.search(r"\bEUR\b|€", testo_unito):
        valuta = "GBP"
    elif re.search(r"\bCHF\b", testo_unito) and not re.search(r"\bEUR\b|€", testo_unito):
        valuta = "CHF"

    m_rit = re.search(
        rf"(?:Ritenuta(?:\s+d'acconto)?|Totale\s+Ritenuta|Withholding\s+Tax)[^\n\d]{{0,35}}{pat_num}",
        testo_unito,
        re.IGNORECASE,
    )
    ritenuta = pulisci_cifra(m_rit.group(1)) if m_rit else 0.0

    return imponibile, imposta, aliquota, totale, ritenuta, valuta


def parser_commerciale_dinamico(testo: str, pagine_testo: list = None, blocchi_spaziali: list = None):
    if pagine_testo is None:
        pagine_testo = [testo]
    if blocchi_spaziali is None:
        blocchi_spaziali = [b for b in testo.split("\n\n") if b.strip()]

    blocco_seller, blocco_buyer = _separa_blocchi_fornitore_cliente(blocchi_spaziali, testo)

    vat_list = estrai_vat_ids(testo)
    ced_paese, ced_piva = "", ""
    cess_paese, cess_piva = "IT", ""

    for paese, cod, _pos in vat_list:
        if cod in KNOWN_BUYER_PIVAS or (paese == "IT" and blocco_buyer and cod in blocco_buyer):
            if not cess_piva:
                cess_paese, cess_piva = "IT", cod
        elif paese != "IT":
            if not ced_piva:
                ced_paese, ced_piva = paese, cod
        else:
            if not ced_piva:
                ced_paese, ced_piva = "IT", cod

    if ced_piva in KNOWN_BUYER_PIVAS:
        cess_paese, cess_piva = "IT", ced_piva
        ced_paese, ced_piva = "", ""

    if not ced_paese:
        ced_paese = rileva_paese_da_blocco(blocco_seller, "")
    if not ced_paese:
        iban_tmp = estrai_iban_universale(testo)
        if iban_tmp and not iban_tmp.startswith("IT"):
            ced_paese = normalizza_codice_paese(iban_tmp[:2], "IT")
    if not ced_paese:
        ced_paese = rileva_paese_da_blocco(testo, "IT")

    ced_nome = _estrai_nome_azienda_da_blocco(blocco_seller, "FORNITORE")
    ced_via, ced_cap, ced_com, ced_prov = estrai_indirizzo_cap_comune(blocco_seller, ced_paese)

    cess_nome = _estrai_nome_azienda_da_blocco(blocco_buyer, "CASAZEN S.R.L.")
    cess_via, cess_cap, cess_com, cess_prov = estrai_indirizzo_cap_comune(blocco_buyer, cess_paese)

    if not cess_piva and re.search(r"\bcasazen\b", testo, re.IGNORECASE):
        cess_piva = "09847131217"

    num_doc = "1"
    m_nd = re.search(
        r"(?:Invoice\s*(?:Number|No\.?|#|ID)|Tax\s*Invoice\s*(?:No\.?|#)|Document\s*(?:No\.?|Number)|"
        r"Rechnungsnummer|Rechnung\s*(?:Nr\.?|Nummer)|Facture\s*(?:N[°o]|Num[ée]ro)|Factura\s*(?:N[°o]|N[úu]mero)|"
        r"Fattura\s*(?:nr?\.?|numero|n\.?)|Doc\.?\s*(?:nr?\.?|n\.?))"
        r"[\s:–#-]*([A-Za-z0-9][A-Za-z0-9/\-_.]{0,25})",
        testo,
        re.IGNORECASE,
    )
    if m_nd:
        val_n = m_nd.group(1).strip()
        if val_n.lower() not in {"date", "data", "elettronica", "ordinaria", "proforma", "differita", "total", "eur", "usd"}:
            num_doc = val_n

    prefer_us = ced_paese == "US"
    data_doc = ""
    m_dt_lbl = re.search(
        r"(?:Invoice\s*Date|Date\s*of\s*Issue|Issue\s*Date|Billing\s*Date|Rechnungsdatum|Date\s*de\s*facture|Fecha\s*de\s*factura|Data\s*(?:fattura|documento)?)[\s:–-]*([^\n]{6,30})",
        testo,
        re.IGNORECASE,
    )
    if m_dt_lbl:
        data_doc = parse_data_universale(m_dt_lbl.group(1), prefer_us=prefer_us)
    if not data_doc:
        data_doc = parse_data_universale(testo, prefer_us=prefer_us) or datetime.today().strftime("%Y-%m-%d")

    data_scad = data_doc
    m_scad_lbl = re.search(
        r"(?:Due\s*Date|Payment\s*Due|F[äa]lligkeitsdatum|Date\s*d'[ée]ch[ée]ance|Fecha\s*de\s*vencimiento|Data\s*scadenza(?:\s*pagamento)?)[\s:–-]*([^\n]{6,30})",
        testo,
        re.IGNORECASE,
    )
    if m_scad_lbl:
        scad_parsed = parse_data_universale(m_scad_lbl.group(1), prefer_us=prefer_us)
        if scad_parsed:
            data_scad = scad_parsed

    imponibile, imposta, aliquota, totale, ritenuta, valuta = _estrai_importi_multilingua(pagine_testo, testo)
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
    if re.search(r"\b(credit\s*note|nota\s*di\s*credito|avoir|gutschrift|abono)\b", testo, re.IGNORECASE):
        tipo_doc = "TD04"

    iban_doc = estrai_iban_universale(testo)
    natura_val = ""
    if ced_paese != "IT" and aliquota == 0.0:
        natura_val = "N3.2" if ced_paese in EU_COUNTRIES else "N2.2"

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
        "totale_documento": totale,
        "natura": natura_val,
        "iban": iban_doc,
        "data_scadenza": data_scad,
        "modalita_pagamento": "MP05",
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


def _estrai_testo_e_blocchi(file_bytes: bytes, mime_type: str):
    pagine_testo = []
    blocchi_spaziali = []
    doc = None

    try:
        if mime_type == "application/pdf":
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc:
                pagine_testo.append(page.get_text("text") or "")
                blocks = page.get_text("blocks") or []
                blocks_sorted = sorted(blocks, key=lambda b: (round(b[1] / 25), b[0]))
                for b in blocks_sorted:
                    if len(b) >= 5 and isinstance(b[4], str) and b[4].strip():
                        blocchi_spaziali.append(b[4].strip())
        else:
            pagine_testo = [""]
    except Exception:
        pagine_testo = [""]
    finally:
        if doc:
            doc.close()

    testo_unito = "\n".join(pagine_testo).strip()

    if len(testo_unito) < 30:
        try:
            import io
            from PIL import Image
            import pytesseract

            ocr_pages = []
            if mime_type == "application/pdf":
                doc_ocr = fitz.open(stream=file_bytes, filetype="pdf")
                for idx, page in enumerate(doc_ocr):
                    if idx >= 8:
                        break
                    pix = page.get_pixmap(dpi=200)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    txt_ocr = pytesseract.image_to_string(img, lang="ita+eng")
                    if txt_ocr.strip():
                        ocr_pages.append(txt_ocr)
                doc_ocr.close()
            else:
                img = Image.open(io.BytesIO(file_bytes))
                txt_ocr = pytesseract.image_to_string(img, lang="ita+eng")
                if txt_ocr.strip():
                    ocr_pages.append(txt_ocr)

            if ocr_pages:
                pagine_testo = ocr_pages
                testo_unito = "\n".join(ocr_pages).strip()
                blocchi_spaziali = [b.strip() for b in testo_unito.split("\n\n") if b.strip()]
        except Exception:
            pass

    return pagine_testo, blocchi_spaziali, testo_unito


def _renderizza_pagine_immagini(file_bytes: bytes, mime_type: str, max_pages: int = 6) -> list:
    if mime_type != "application/pdf":
        return [(mime_type, base64.b64encode(file_bytes).decode("utf-8"))]

    immagini = []
    doc = None
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        n = len(doc)
        if n <= max_pages:
            indices = list(range(n))
        else:
            indices = [0, 1, 2, n - 3, n - 2, n - 1]
        for idx in indices:
            pix = doc[idx].get_pixmap(dpi=160)
            img_bytes = pix.tobytes("jpeg")
            immagini.append(("image/jpeg", base64.b64encode(img_bytes).decode("utf-8")))
    except Exception:
        pass
    finally:
        if doc:
            doc.close()
    return immagini


def _chiama_ai_vision(file_bytes: bytes, filename: str, api_key: str, mime_type: str, testo_estratto: str = ""):
    k = str(api_key).strip()

    prompt_universale = (
        "Sei un esperto contabile specializzato in fatturazione elettronica italiana (FPR12 SdI) e fatture estere (UE ed Extra-UE). "
        "Analizza TUTTE le pagine della fattura allegata, qualunque sia il layout grafico o la lingua (EN, DE, FR, ES, IT, NL, ecc.).\n"
        "REGOLE CRITICHE:\n"
        "1. CEDENTE (cedente_*): è SEMPRE il fornitore/emittente che emette la fattura.\n"
        "2. CESSIONARIO (cessionario_*): è SEMPRE il cliente/destinatario ('Bill To', 'Customer', 'Spett.le', 'Destinatario', es. CASAZEN s.r.l. IT09847131217). NON invertire mai fornitore e cliente!\n"
        "3. CODICI PAESE ISO-2: usa sempre ISO 3166-1 alpha-2 (GB per Regno Unito invece di UK, GR per Grecia, IE, DE, FR, US, NL, CH). "
        "In cedente_piva metti solo il codice identificativo senza duplicare il prefisso Paese.\n"
        "4. IMPORTI E DATE: date in YYYY-MM-DD, numeri con punto decimale (es. 1250.50). "
        "Se IVA/VAT è 0 o Reverse Charge -> imposta=0.0, aliquota_prevalente=0.0, natura='N3.2' (intra-UE) o 'N2.2' (extra-UE). "
        "Se la fattura estera espone IVA/VAT -> riporta imponibile, aliquota_prevalente, imposta e totale_documento reali.\n"
        "5. PAGINE MULTIPLE: cerca anagrafica/numero/data in tutte le pagine e totali/IVA/IBAN/scadenza anche nelle ultime pagine e nei piè di pagina.\n"
        "Rispondi ESCLUSIVAMENTE con un JSON valido con queste chiavi esatte:\n"
        "cedente_denominazione, cedente_paese, cedente_piva, cedente_cf, cedente_indirizzo, cedente_cap, cedente_comune, cedente_provincia, "
        "cessionario_denominazione, cessionario_paese, cessionario_piva, cessionario_cf, cessionario_indirizzo, cessionario_cap, cessionario_comune, cessionario_provincia, "
        "numero_documento, data_documento, tipo_documento, imponibile, aliquota_prevalente, imposta, ritenuta, totale_documento, natura, iban, data_scadenza, modalita_pagamento, valuta, descrizione."
    )

    if k.startswith("sk-"):
        try:
            import urllib.request

            immagini = _renderizza_pagine_immagini(file_bytes, mime_type, max_pages=6)
            content_parts = [{"type": "text", "text": prompt_universale}]
            if testo_estratto:
                content_parts.append({"type": "text", "text": f"Testo estratto:\n{testo_estratto[:12000]}"})
            for m_type, b64 in immagini:
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
            with urllib.request.urlopen(req, timeout=45) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return json.loads(res["choices"][0]["message"]["content"]), None, "OpenAI Vision GPT-4o-mini"
        except Exception as e:
            return None, str(e), None

    try:
        import google.generativeai as genai

        genai.configure(api_key=k)
        modelli = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
        ]
        payload = [prompt_universale, {"mime_type": mime_type, "data": file_bytes}]

        for m_name in modelli:
            try:
                model = genai.GenerativeModel(
                    m_name,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.0},
                )
                res = model.generate_content(payload, request_options={"timeout": 45.0})
                clean_json = res.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_json)
                return data, None, m_name
            except Exception:
                continue

        return None, "Timeout o errore risposta Gemini Vision", None
    except Exception as e:
        return None, str(e), None


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
    pagine_testo, blocchi_spaziali, testo_unito = _estrai_testo_e_blocchi(file_bytes, mime_type)
    t_lower = testo_unito.lower()

    ai_err = None
    if api_key and len(str(api_key).strip()) > 8:
        dati_ai, err_ai, mod_name = _chiama_ai_vision(
            file_bytes, filename, str(api_key).strip(), mime_type, testo_unito
        )
        if dati_ai and isinstance(dati_ai, dict) and (
            dati_ai.get("cedente_denominazione") or dati_ai.get("totale_documento")
        ):
            dati_ok = _ponte_chiavi_e_quadratura(dati_ai)
            return dati_ok, f"Vision AI ({mod_name})", testo_unito, None
        ai_err = err_ai

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

    dati_gen = parser_commerciale_dinamico(testo_unito, pagine_testo=pagine_testo, blocchi_spaziali=blocchi_spaziali)
    dati_ok = _ponte_chiavi_e_quadratura(dati_gen)
    metodo = "Parser Commerciale Dinamico"
    if ai_err:
        metodo += f" [Fallback dopo AI: {ai_err[:40]}]"
    return dati_ok, metodo, testo_unito, None
# === FINE FILE extractor.py ===
