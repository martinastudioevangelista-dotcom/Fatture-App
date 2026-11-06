# validator.py - Validazione Fiscale FPR12 e Normativa IVA Intra-UE
import re
from typing import List, Dict, Tuple

def valida_partita_iva_internazionale(piva: str, paese: str = "IT") -> bool:
    """Verifica P.IVA italiane (formula di Luhn) o estere comunitarie (VIES/UE)."""
    piva = re.sub(r"[^A-Za-z0-9]", "", str(piva)).upper()
    paese = str(paese).strip().upper() if paese else "IT"
    
    if not piva:
        return False

    # 1. Partita IVA Italiana
    if paese == "IT":
        if len(piva) != 11 or not piva.isdigit():
            return False
        s = 0
        for i in range(10):
            c = int(piva[i])
            if i % 2 == 1:
                c *= 2
                if c > 9:
                    c -= 9
            s += c
        controllo = (10 - (s % 10)) % 10
        return controllo == int(piva[10])

    # 2. Fornitori Comunitari (es. Francia FR: 11 caratteri; Germania DE: 9 cifre)
    if paese == "FR":
        return len(piva) == 11
    if paese == "DE":
        return len(piva) == 9 and piva.isdigit()
    
    # Standard generale estero UE: tra 4 e 15 caratteri alfanumerici
    return 4 <= len(piva) <= 15

def valida_codice_destinatario(sdi: str) -> bool:
    """Il codice destinatario SdI deve essere esattamente di 7 caratteri alfanumerici."""
    sdi = str(sdi).strip()
    return len(sdi) == 7 and bool(re.match(r"^[A-Za-z0-9]{7}$", sdi))

def valida_quadratura_completa(
    riepilogo_iva: List[Dict], 
    totale_documento: float,
    ritenuta: float = 0.0,
    bollo: float = 0.0,
    cassa_previdenza: float = 0.0
) -> Tuple[bool, List[str]]:
    """Verifica coerenza contabile, con supporto a Natura N3.2 per Fornitori UE."""
    errori = []
    totale_imponibile = 0.0
    totale_imposta = 0.0

    for idx, rigo in enumerate(riepilogo_iva, start=1):
        imponibile = round(float(rigo.get("imponibile", 0.0)), 2)
        aliquota = float(rigo.get("aliquota", 0.0))
        imposta_dichiarata = round(float(rigo.get("imposta", 0.0)), 2)
        natura = str(rigo.get("natura", "")).strip().upper()

        if aliquota == 0.0:
            if not natura:
                errori.append(f"Rigo {idx}: Aliquota 0% priva di Natura IVA obbligatoria (es. N3.2 per Fornitori UE).")
            if imposta_dichiarata != 0.0:
                errori.append(f"Rigo {idx}: Con Natura {natura} l'imposta IVA deve essere 0.00€ (rilevati {imposta_dichiarata}€).")
        else:
            imposta_calcolata = round((imponibile * aliquota) / 100.0, 2)
            if abs(imposta_calcolata - imposta_dichiarata) > 0.02:
                errori.append(
                    f"Rigo {idx}: IVA al {aliquota}% disallineata: calcolata {imposta_calcolata}€ vs dichiarata {imposta_dichiarata}€."
                )

        totale_imponibile += imponibile
        totale_imposta += imposta_dichiarata

    # Chiusura documento
    totale_teorico = round(totale_imponibile + totale_imposta + cassa_previdenza + bollo, 2)
    diff = min(abs(totale_teorico - totale_documento), abs((totale_teorico - ritenuta) - totale_documento))

    if diff > 0.05:
        errori.append(
            f"Quadratura fallita: Totale calcolato ({totale_teorico:.2f}€) non coincide con il Totale Documento ({totale_documento:.2f}€)."
        )

    return (len(errori) == 0), errori

# ALIAS DI COMPATIBILITÀ BIDIREZIONALE PER EVITARE QUALSIASI IMPORTERROR
valida_partita_iva = valida_partita_iva_internazionale
