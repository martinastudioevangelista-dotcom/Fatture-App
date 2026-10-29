import streamlit as st
from extractor import estrai_dati_fattura
from validator import valida_quadratura
from xml_generator import genera_xml_sdi
from gdrive import upload_to_drive

st.set_page_config(page_title="Gestione Fatture AI", layout="wide")

st.title("📄 AI Invoice to SdI/TeamSystem")
st.markdown("Carica un PDF. L'AI estrarrà i dati, validerà la contabilità, creerà l'XML e salverà su Google Drive.")

uploaded_file = st.file_uploader("Carica Fattura (PDF)", type="pdf")

if uploaded_file is not None:
    pdf_bytes = uploaded_file.getvalue()
    
    if st.button("Elabora Fattura"):
        with st.spinner("Estrazione dati tramite IA in corso..."):
            try:
                # 1. Estrazione AI
                dati_estratti = estrai_dati_fattura(pdf_bytes)
                st.success("Dati estratti con successo!")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Dati Rilevati")
                    st.json(dati_estratti)
                
                # 2. Controllo Contabile
                with st.spinner("Controllo quadratura contabile..."):
                    valido, errori = valida_quadratura(dati_estratti)
                
                with col2:
                    st.subheader("Esito Contabile")
                    if valido:
                        st.success("✅ Quadratura matematica corretta.")
                    else:
                        st.error("❌ Rilevati errori di quadratura:")
                        for err in errori:
                            st.write(f"- {err}")
                            
                # Procedi solo se valido
                if valido:
                    # 3. Generazione XML
                    with st.spinner("Generazione XML TeamSystem/SdI..."):
                        xml_output = genera_xml_sdi(dati_estratti)
                        st.download_button("⬇️ Scarica XML", xml_output, file_name="fattura.xml", mime="application/xml")
                        
                    # 4. Upload Google Drive
                    with st.spinner("Archiviazione su Google Drive in corso..."):
                        cliente = dati_estratti["cliente"].get("ragione_sociale", "Sconosciuto")
                        num_doc = dati_estratti["documento"].get("numero", "0")
                        upload_to_drive(pdf_bytes, xml_output, cliente, f"Fattura_{num_doc}")
                        st.success(f"✅ File salvati su Google Drive in: Fatture_App / {cliente}")

            except Exception as e:
                st.error(f"Si è verificato un errore durante l'elaborazione: {str(e)}")
