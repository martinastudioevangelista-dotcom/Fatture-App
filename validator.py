def valida_quadratura(dati_json):
    errori = []
    totale_calcolato = 0.0
    
    for riga in dati_json.get("riepilogo_iva", []):
        imponibile = float(riga.get("imponibile", 0))
        aliquota = float(riga.get("aliquota_iva", 0))
        imposta_dichiarata = float(riga.get("imposta", 0))
        
        # Check Imposta
        imposta_calcolata = round(imponibile * (aliquota / 100), 2)
        if abs(imposta_calcolata - imposta_dichiarata) > 0.02: # Tolleranza arrotondamento
            errori.append(f"Errore IVA: calcolata {imposta_calcolata}, dichiarata {imposta_dichiarata} su imponibile {imponibile}")
            
        totale_calcolato += imponibile + imposta_dichiarata
        
    totale_dichiarato = float(dati_json.get("totale_documento", 0))
    
    # Check Totale
    if abs(totale_calcolato - totale_dichiarato) > 0.02:
        errori.append(f"Errore Quadratura: Totale righi ({totale_calcolato}) diverso da Totale Documento ({totale_dichiarato})")
        
    return len(errori) == 0, errori
