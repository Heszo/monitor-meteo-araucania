"""
Pruebas de humo de la app con st.testing (sin navegador): cada página, cada
variable y varios sitios deben dibujarse sin excepciones. Usan las fuentes
reales (copia publicada, METAR, VIPNet); si alguna está caída la app debe
seguir sin romperse, que es justamente lo que se prueba.

    python -m pytest -q
"""
import pytest
from streamlit.testing.v1 import AppTest

import fuentes as F

PAGINAS = ["presentacion", "comparar", "lluvia", "meteograma", "mapa", "superficie"]
ENTRADA = "../streamlit_app.py"
TIEMPO = 300  # la primera corrida descarga todo


def abre(pagina="presentacion", **estado):
    at = AppTest.from_file(ENTRADA, default_timeout=TIEMPO)
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    if pagina != "presentacion":
        at.switch_page(f"app_pages/{pagina}.py").run()
    return at


def errores(at):
    return [e.value for e in at.exception]


@pytest.mark.parametrize("pagina", PAGINAS)
def test_cada_pagina(pagina):
    assert errores(abre(pagina)) == []


@pytest.mark.parametrize("sitio", ["aeropuerto", "temuco_centro", "puesco_aduana"])
def test_sitios(sitio):
    for pagina in PAGINAS:
        assert errores(abre(pagina, sitio=sitio)) == [], (sitio, pagina)


def test_cada_variable_en_comparar():
    at = abre("comparar", sitio="temuco_centro")
    for var in F.VARIABLES:
        at.segmented_control(key="variable").set_value(var).run()
        assert errores(at) == [], var
    at.segmented_control(key="variable").set_value("precipitacion").run()
    at.toggle(key="acumulado").set_value(True).run()
    assert errores(at) == []


def test_ventanas_extremas():
    for pasado, futuro in [(1, 1), (F.DIAS_PUBLICADOS, F.DIAS_PUBLICADOS)]:
        for pagina in PAGINAS:
            assert errores(abre(pagina, pasado=pasado, futuro=futuro)) == [], (pasado, futuro, pagina)


def test_presentacion_enlaza_cada_pagina():
    at = abre()
    enlaces = {e.proto.page for e in at.get("page_link")}  # url_path de cada página
    assert set(PAGINAS[1:]) <= enlaces


def test_estacion_en_lluvia():
    """Elegir una estación desde «Estación» la vuelve el sitio de toda la app; «Por comuna» dibuja el
    ensamble de la comuna y cambiar la comuna cambia el sitio."""
    at = abre("lluvia", sitio="temuco_centro")
    at.selectbox(key="lluvia_comuna").set_value("Pucón").run()
    assert errores(at) == []
    assert F.SITIO[at.session_state["sitio"]]["comuna"] == "Pucón"
    at.selectbox(key="lluvia_estacion").set_value("pucon").run()
    assert errores(at) == []
    assert at.session_state["sitio"] == "pucon"
    at.segmented_control(key="lluvia_vista").set_value("Por comuna").run()
    assert errores(at) == []
    at.selectbox(key="lluvia_comuna").set_value("Cunco").run()
    assert errores(at) == []
    assert F.SITIO[at.session_state["sitio"]]["comuna"] == "Cunco"


def test_lluvia_sitio_sin_lluvia():
    """El aeropuerto no mide lluvia: la página muestra su comuna sin romperse."""
    assert errores(abre("lluvia", sitio="aeropuerto")) == []


def test_comuna_en_mapa():
    at = abre("mapa")
    for comuna in ["Temuco", "Renaico"]:  # Renaico no tiene estaciones: se muestra la más cercana
        at.selectbox(key="comuna").set_value(comuna).run()
        assert errores(at) == [], comuna
        assert len(at.dataframe[0].value) >= 1


def test_superficie():
    at = abre("superficie", sitio="aeropuerto")
    for fondo in ["temperatura", "presion", "precipitacion", "rafaga"]:
        at.radio(key="fondo").set_value(fondo).run()
        assert errores(at) == [], fondo
    at.selectbox(key="modelo_mapa").set_value("gfs_seamless").run()
    at.segmented_control(key="mapa_base").set_value("calles").run()
    at.toggle(key="particulas").set_value(False).run()
    assert errores(at) == []
    at.segmented_control(key="periodo_rosa").set_value("futuro").run()
    assert errores(at) == []


def test_catalogo():
    ids = [s["id"] for s in F.SITIOS]
    assert len(ids) == len(set(ids))
    assert set(F.NODO) == set(ids) and set(F.NODO.values()) <= set(ids)
    for s in F.SITIOS:
        assert s["grupo"] in F.GRUPOS and set(s["vars"]) <= set(F.VARIABLES), s["id"]
    import comun as C
    assert {s["comuna"] for s in F.SITIOS} <= set(C.NOMBRES_COMUNAS)
    assert len(C.NOMBRES_COMUNAS) == 32


def test_guardar_graficos():
    import plotly.io as pio

    import comun as C
    at = abre("comparar", sitio="temuco_centro")
    assert {b.label for b in at.get("download_button")} == {"PNG", "PDF"}
    fig = pio.from_json(at.get("plotly_chart")[0].proto.spec)
    assert C.exporta(fig, "pdf")[:5] == b"%PDF-"
    assert C.exporta(fig, "png")[:4] == b"\x89PNG"


def test_ahora_mismo_por_comuna():
    """El Home parte en Temuco Centro; al cambiar la comuna, «Sitio» pasa a una estación de esa comuna."""
    at = abre()
    assert at.session_state["sitio"] == "temuco_centro"
    at.selectbox(key="ahora_comuna").set_value("Pucón").run()
    assert errores(at) == []
    assert F.SITIO[at.session_state["sitio"]]["comuna"] == "Pucón"
    assert len(at.selectbox(key="sitio").options) == sum(s["comuna"] == "Pucón" for s in F.SITIOS)
