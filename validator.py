# validator.py
import re
from typing import Dict, Any, List, Tuple

def valida_partita_iva(piva: str) -> bool:
    """Verifica formale della Partita IVA italiana (11 cifre + algoritmo di Luhn per IT)."""
    piva = re.sub(r"[^0-9]", "", str(piva))
    if len(piva) != 11:
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


def valida_codice_fiscale(cf: str) -> bool:
    """Verifica sintattica del Codice Fiscale italiano ordinario a 16 caratteri."""
    cf = str(cf).strip().upper()
    regex_cf = r"^[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]$"
    return bool(re.match(regex_cf, cf))


def valida_quadratura_completa(
    riepilogo_iva: List[Dict[str, float]], 
    totale_documento: float,
    ritenuta: float = 0.0,
    bollo: float = 0.0,
    cassa_previdenza: float = 0.0
) -> Tuple[bool, List[str]]:
    """Esegue il controllo di quadratura su imponibili, imposte e totale fattura."""
    errori = []
    totale_imponibile = 0.0
    totale_imposta = 0.0

    for idx, rigo in enumerate(riepilogo_iva, start=1):
        imponibile = round(float(rigo.get("imponibile", 0.0)), 2)
        aliquota = float(rigo.get("aliquota", 0.0))
        imposta_dichiarata = round(float(rigo.get("imposta", 0.0)), 2)
        natura = str(rigo.get("natura", "")).strip()

        if aliquota == 0.0:
            if not natura:
                errori.append(f"Rigo {idx}: Aliquota 0% priva di Natura esenzione (es. N1, N2.2, N3, N4).")
            if imposta_dichiarata != 0.0:
                errori.append(f"Rigo {idx}: Aliquota 0% con imposta valorizzata a {imposta_dichiarata:.2f}€.")
        else:
            imposta_calcolata = round((imponibile * aliquota) / 100.0, 2)
            if abs(imposta_calcolata - imposta_dichiarata) > 0.02:
                errori.append(
                    f"Rigo {idx}: Errore IVA {aliquota}%. "
                    f"Dichiarata: {imposta_dichiarata:.2f}€, Calcolata: {imposta_calcolata:.2f}€."
                )

        totale_imponibile += imponibile
        totale_imposta += imposta_dichiarata

    totale_teorico = round(totale_imponibile + totale_imposta + cassa_previdenza + bollo, 2)
    diff_lordo = abs(totale_teorico - totale_documento)
    diff_netto = abs((totale_teorico - ritenuta) - totale_documento)

    if diff_lordo > 0.02 and diff_netto > 0.02:
        errori.append(
            f"Asimmetria Totale: Teorico {totale_teorico:.2f}€ (netto {totale_teorico - ritenuta:.2f}€), "
            f"Dichiarato: {totale_documento:.2f}€."
        )

    return (len(errori) == 0), errori
