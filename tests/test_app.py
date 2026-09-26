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

PAGINAS = ["presentacion", "comparar", "lluvia", "meteograma", "mapa"]
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
    at = abre("lluvia", sitio="pucon")
    at.selectbox(key="estacion").set_value("Pucón").run()
    assert errores(at) == []


def test_catalogo():
    ids = [s["id"] for s in F.SITIOS]
    assert len(ids) == len(set(ids))
    assert set(F.NODO) == set(ids) and set(F.NODO.values()) <= set(ids)
    for s in F.SITIOS:
        assert s["grupo"] in F.GRUPOS and set(s["vars"]) <= set(F.VARIABLES), s["id"]
