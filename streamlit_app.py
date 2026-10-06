"""
MetGeo Araucanía: monitor meteorológico de La Araucanía. Lluvia,
temperatura, humedad, viento y presión, observados (VIPNet DGA/MOP y METAR
del aeropuerto La Araucanía) y pronosticados por 7 modelos globales y un super-ensamble
de 143 miembros. Página principal: marca, navegación y encabezado; cada
vista vive en app_pages/ y los controles en comun.controles().

Se lanza con `streamlit run app.py` (app.py envuelve este script en st.App
para mantener la caché caliente); `streamlit run streamlit_app.py` también
funciona, sin ese precalentamiento.
"""
import streamlit as st

import comun as C

st.set_page_config(page_title="MetGeo Araucanía · monitor meteorológico", page_icon=str(C.LOGO_SOLO),
                   layout="wide")
st.logo(str(C.LOGO_COMPLETO), icon_image=str(C.LOGO_SOLO), size="large")
st.html(C.CSS_MAPAS)  # esquinas redondeadas y filete de los mapas

INICIO = st.Page("app_pages/presentacion.py", title="Home", icon=":material/home:", default=True)
pagina = st.navigation([
    INICIO,
    st.Page("app_pages/comparar.py", title="Comparar modelos", icon=":material/stacked_line_chart:"),
    st.Page("app_pages/lluvia.py", title="Lluvia", icon=":material/water_drop:"),
    st.Page("app_pages/meteograma.py", title="Meteograma", icon=":material/monitoring:"),
    st.Page("app_pages/mapa.py", title="Mapa de estaciones", icon=":material/map:"),
    st.Page("app_pages/superficie.py", title="Mapas de superficie", icon=":material/air:"),
], position="top")

# La portada pone sus controles debajo de la presentación; el resto, arriba de todo.
if pagina.title != INICIO.title:
    st.title(pagina.title, icon=pagina.icon, anchor=False)
    c = C.controles()
    C.metricas_ahora(c)
    st.space("small")

pagina.run()

if pagina.title != INICIO.title:  # la portada ya trae su propia firma
    st.space("large")
    with st.container(horizontal=True, horizontal_alignment="center", gap="small"):
        st.link_button("metgeo.cl", C.METGEO, icon=":material/public:")
        st.link_button("Suscríbete al newsletter", C.NEWSLETTER, icon=":material/mail:", type="primary")
    st.caption(f"MetGeo Araucanía · Bruno Herrera · [Instagram]({C.INSTAGRAM}) · [LinkedIn]({C.LINKEDIN})",
               text_alignment="center")
