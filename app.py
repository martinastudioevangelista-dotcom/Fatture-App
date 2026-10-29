import streamlit as st
import io
import zipfile
from extractor import estrai_dati_fattura
from validator import valida_quadratura
from xml_generator import genera_xml_sdi
from gdrive import upload_to_drive

st.set_page_config(page_title="Gestione Fatture AI", layout="wide")

st.title("📄 AI Invoice to SdI/TeamSystem")
st.markdown("Elaborazione fatture PDF, verifica di quadratura contabile e generazione tracciato XML per TeamSystem.")

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
                        
                    st.markdown("---")
                    st.subheader("📥 Scarica i tuoi file")
                    
                    num_doc = str(dati_estratti["documento"].get("numero", "doc")).replace("/", "_").replace("\\", "_")
                    cliente = dati_estratti["cliente"].get("ragione_sociale", "Cliente").strip() or "Cliente"
                    nome_base = f"Fattura_{num_doc}_{cliente}"
                    
                    col_dl1, col_dl2 = st.columns(2)
                    with col_dl1:
                        st.download_button(
                            label="⬇️ Scarica solo XML (per TeamSystem)",
                            data=xml_output,
                            file_name=f"{nome_base}.xml",
                            mime="application/xml"
                        )
                    
                    # Pacchetto ZIP con PDF originale e XML
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        zip_file.writestr(f"{nome_base}.xml", xml_output.encode("utf-8"))
                        zip_file.writestr(f"{nome_base}.pdf", pdf_bytes)
                    zip_buffer.seek(0)
                    
                    with col_dl2:
                        st.download_button(
                            label="📦 Scarica Pacchetto Completo (PDF + XML in ZIP)",
                            data=zip_buffer,
                            file_name=f"{nome_base}.zip",
                            mime="application/zip"
                        )
                        
                    # 4. Prova caricamento Google Drive in sicurezza (senza bloccare il programma)
                    try:
                        upload_to_drive(pdf_bytes, xml_output, cliente, nome_base)
                        st.success(f"✅ File salvati anche su Google Drive (Fatture_Studio / {cliente})")
                    except Exception:
                        st.info("ℹ️ Archiviazione Google Drive non attiva su questo account Google (richiede Google Workspace con Unità Condivise). Puoi scaricare i file pronti con i pulsanti qui sopra!")

            except Exception as e:
                st.error(f"Si è verificato un errore durante l'elaborazione: {str(e)}")
