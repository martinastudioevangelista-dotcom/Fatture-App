# Funzione adattiva che interroga extractor.py senza possibilità di mismatch di parametri
def esegui_estrazione_protetta(extractor_fn, file_bytes, uploaded_file_obj):
    import inspect
    try:
        sig = inspect.signature(extractor_fn)
        num_params = len(sig.parameters)
    except Exception:
        num_params = 2

    # Tentativo 1: Due parametri (file_bytes, filename)
    if num_params >= 2:
        try:
            return extractor_fn(file_bytes, uploaded_file_obj.name)
        except TypeError:
            pass

    # Tentativo 2: Un solo parametro (file_bytes)
    try:
        return extractor_fn(file_bytes)
    except TypeError:
        pass

    # Tentativo 3: Un solo parametro (oggetto UploadedFile di Streamlit)
    uploaded_file_obj.seek(0)
    return extractor_fn(uploaded_file_obj)
