"""
Lo que comparten todas las páginas: cargas con caché, el contexto de la
corrida (sitio, ventana, datos) y utilidades de gráficos.

Las cargas usan ttl + refresh_mode="background": cuando una entrada vence,
el visitante recibe al instante la versión anterior y la nueva se baja por
detrás. Además app.py (st.App) las toca cada pocos minutos desde el
servidor, así que casi nadie espera una descarga. Para que eso funcione las
claves de caché son fijas: se pide siempre la ventana máxima y se recorta
después.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import fuentes as F

RAIZ = Path(__file__).resolve().parent
LOGO_COMPLETO = RAIZ / "static" / "logo_completo.png"
LOGO_SOLO = RAIZ / "static" / "logo_solo.png"
NEGRO, ROJO, BANDA = "#111111", "#B5323C", "rgba(120,150,190,.22)"
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
EJE_T = dict(tickformat="%d/%m<br>%H:%M", nticks=8, tickangle=0)
HORAS_OBS = F.DIAS_PUBLICADOS * 24 + 2
VARS_VIPNET = ("precipitacion", "temperatura", "humedad", "viento")
VACIO = {"det": {}, "pct": {}, "pp": None, "raf6h": None}
VIEJO = pd.Timedelta(hours=3)
INSTAGRAM = "https://www.instagram.com/metgeo.spa/"
LINKEDIN = "https://www.linkedin.com/company/metgeo-spa/"
REPO_URL = f"https://github.com/{F.REPO}"
METGEO = "https://metgeo.cl"
NEWSLETTER = "https://metgeo-newsletter.metgeo.workers.dev/"
# límites comunales (BCN, simplificados a ~400 m): se dibujan en todos los mapas para ubicar las estaciones
COMUNAS = json.loads((RAIZ / "static" / "comunas_araucania.geojson").read_text(encoding="utf-8"))
NOMBRES_COMUNAS = [f["properties"]["comuna"] for f in COMUNAS["features"]]
# mapas base: imagen satelital o calles (OpenStreetMap). Cada uno con el color
# de los límites comunales y del texto de las estaciones que se lee bien encima.
BASES = {
    "satelite": dict(nombre="Satélite", teselas=F.ESRI, linea="rgba(255,255,255,.35)", texto="white",
                     credito="Esri World Imagery"),
    "calles": dict(nombre="Calles", teselas=F.OSM, linea="rgba(90,60,120,.35)", texto="#1a1a1a",
                   credito="© colaboradores de OpenStreetMap"),
}


# Esquinas redondeadas y un filete gris para los mapas (MapLibre dibuja un rectángulo de esquinas vivas).
MARCO_MAPA = "rgba(128,128,128,.45)"
CSS_MAPAS = f"""<style>
.stPlotlyChart .maplibregl-map {{ border-radius: 12px; overflow: hidden; box-shadow: 0 0 0 1px {MARCO_MAPA}; }}
</style>"""


def base_actual():
    return st.session_state.get("mapa_base") or "satelite"


def elige_mapa_base():
    """Control «Mapa base»; la elección se comparte entre páginas."""
    return st.segmented_control("Mapa base", list(BASES), default="satelite", required=True, key="mapa_base",
                                persist_state="session", format_func=lambda k: BASES[k]["nombre"])


def mapa(**extra):
    """layout.map con el mapa base elegido y los límites comunales; extra: center, zoom, capas_extra."""
    b = BASES[base_actual()]
    capas = [dict(sourcetype="raster", source=[b["teselas"]], below="traces"),
             dict(sourcetype="geojson", source=COMUNAS, type="line", color=b["linea"], line=dict(width=1),
                  below="traces"), *extra.pop("capas_extra", [])]
    return dict(style="white-bg", center=dict(lat=-38.65, lon=-72.3), layers=capas) | extra


def texto_mapa():
    return BASES[base_actual()]["texto"]


def credito_mapa():
    return BASES[base_actual()]["credito"]


# ------------------------------------------------------------------ cargas con caché
# Las funciones con caché lanzan la excepción (así no se guarda una falla) y quien las
# llama la atrapa.
@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Leyendo los pronósticos publicados…")
def carga_publicados():
    return F.lee_pronosticos()


@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Descargando METAR del aeropuerto La Araucanía…")
def carga_metar():
    return F.metar("SCQP", HORAS_OBS)


@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Descargando estaciones VIPNet…")
def carga_vipnet(variable):
    return F.vipnet_variable(variable, HORAS_OBS)


@st.cache_data(ttl="1h", max_entries=40, show_spinner="Consultando Open-Meteo en vivo…")
def carga_vivo(lat, lon):
    return F.pronostico_vivo(lat, lon, F.DIAS_PUBLICADOS, F.DIAS_PUBLICADOS)


@st.cache_data(ttl="15m", refresh_mode="background", show_spinner="Leyendo la grilla de los mapas de superficie…")
def carga_grilla_publicada():
    return F.lee_grilla()


@st.cache_data(ttl="1h", show_spinner="Consultando la grilla en Open-Meteo en vivo (tarda unos segundos)…")
def carga_grilla_viva():
    return F.grilla()


def grilla():
    """(tabla, origen) de la grilla regional: la copia publicada y, si falta, Open-Meteo en vivo.
    (None, error) si ninguna responde."""
    try:
        return carga_grilla_publicada(), "copia publicada"
    except Exception:  # noqa: BLE001
        pass
    try:
        return carga_grilla_viva(), "Open-Meteo en vivo"
    except Exception as ex:  # noqa: BLE001
        return None, str(ex)


def calienta_caches():
    """La llama app.py al arrancar y cada pocos minutos: con las entradas frescas es
    casi gratis; con las vencidas dispara su refresco en segundo plano."""
    for f, args in [(carga_publicados, ()), (carga_metar, ()), (carga_grilla_publicada, ()),
                    *[(carga_vipnet, (v,)) for v in VARS_VIPNET]]:
        f(*args)


def metar_seguro():
    try:
        return carga_metar()
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def vipnet_seguro(variable):
    try:
        return carga_vipnet(variable)
    except Exception as ex:  # noqa: BLE001
        return {}, [f"VIPNet {variable}: {str(ex)[:120]}"]


def pronostico(s):
    """(pronóstico, origen, error). Primero la copia que publica la GitHub Action cada hora; si
    falta o tiene más de 3 h, Open-Meteo en vivo; si eso también falla, la copia vieja o nada."""
    ahora_utc = pd.Timestamp.now(tz="UTC")
    try:
        generado, pub = carga_publicados()
    except Exception:  # noqa: BLE001
        generado, pub = None, {}
    local = lambda t: t.tz_convert(F.ZONA).strftime("%d/%m %H:%M")  # noqa: E731
    if generado is not None and s["id"] in pub and ahora_utc - generado < VIEJO:
        return pub[s["id"]], f"copia publicada a las {local(generado)}", None
    try:
        return carga_vivo(s["lat"], s["lon"]), "Open-Meteo en vivo", None
    except Exception as ex:  # noqa: BLE001
        if generado is not None and s["id"] in pub:
            return pub[s["id"]], f"copia publicada a las {local(generado)} (desactualizada)", str(ex)
        return VACIO, None, str(ex)


# ------------------------------------------------------------------ contexto de la corrida
def prepara_contexto(sitio_id, pasado, futuro, modelos, con_ensamble):
    """Arma el contexto de esta corrida y lo deja en st.session_state para las páginas."""
    sitio = F.SITIO[sitio_id]
    ahora = F.ahora_local()
    t0 = pd.Timestamp(ahora).floor("h") - pd.Timedelta(days=pasado)
    t_fin = pd.Timestamp(ahora).floor("D") + pd.Timedelta(days=futuro)
    metar = metar_seguro()
    pron, origen, error = pronostico(sitio)
    avisos = []

    def recorta(df):
        if df is None or df.empty:
            return df
        return df[(df.index >= t0) & (df.index < t_fin)]

    def det_var(v):
        return pron["det"].get(v, pd.DataFrame())

    def observado(s, variable):
        """Serie horaria observada de 'variable' en el sitio s (o None), ventana completa."""
        if variable not in s["vars"]:
            return None
        if s["fuente"] == "metar":
            col = F.VARIABLES[variable]["metar"]
            o = metar[col].dropna() if not metar.empty and col in metar else None
        else:
            series, av = vipnet_seguro(variable)
            avisos.extend(av)
            o = series.get(s["id"])
        return None if o is None else o[o.index >= t0]

    c = SimpleNamespace(sitio=sitio, pasado=pasado, futuro=futuro, modelos=modelos, con_ensamble=con_ensamble,
                        ahora=ahora, t0=t0, t_fin=t_fin, metar=metar, pron=pron, det=pron["det"],
                        pct=pron["pct"], origen_pron=origen, error_pron=error, avisos=avisos,
                        recorta=recorta, det_var=det_var, observado=observado)
    st.session_state["_ctx"] = c
    return c


def contexto():
    return st.session_state["_ctx"]


# ------------------------------------------------------------------ utilidades de gráficos y texto
def barra(boton="resetScale2d"):
    return {"displayModeBar": True, "displaylogo": False, "modeBarButtons": [[boton]]}


PIE = ("MetGeo Araucanía · metgeo-araucania.streamlit.app · observado: VIPNet (DGA/MOP) y METAR SCQP "
       "(NOAA AWC) · pronóstico: Open-Meteo")


def exporta(fig, formato, ancho=1400):
    """El gráfico como PNG (a doble resolución) o PDF vectorial, con fondo blanco y la fuente
    arriba a la derecha. Lo dibuja Kaleido con Chrome; en Streamlit Cloud, el chromium de
    packages.txt."""
    f = go.Figure(fig)
    m = f.layout.margin
    arriba = (m.t or 0) + 26
    f.update_layout(template="plotly_white", paper_bgcolor="white", margin=dict(t=arriba))
    f.add_annotation(text=PIE, xref="paper", yref="paper", x=1, y=1, xanchor="right", yanchor="bottom",
                     yshift=arriba - 20, showarrow=False, font=dict(size=10, color="#777"))
    return f.to_image(format=formato, width=ancho, height=(f.layout.height or 500) + 26,
                      scale=2 if formato == "png" else 1)


def grafico(fig, nombre, key=None, boton="resetScale2d", donde=None, **kw):
    """st.plotly_chart y, debajo, botones para guardar el gráfico en PNG o PDF. La imagen se
    genera recién al hacer clic (data diferida), así no cuesta nada mientras nadie la pide.
    'kw' pasa directo a st.plotly_chart (on_select, selection_mode)."""
    donde = donde or st.container()
    with donde:
        st.plotly_chart(fig, config=barra(boton), key=key, **kw)
        c = st.session_state.get("_ctx")
        base = "_".join(filter(None, ["metgeo_araucania", nombre, c and c.sitio["id"],
                                      f"{F.ahora_local():%Y%m%d_%H%M}"]))
        with st.container(horizontal=True, gap="small", horizontal_alignment="right"):
            for formato, mime in (("png", "image/png"), ("pdf", "application/pdf")):
                st.download_button(formato.upper(), lambda formato=formato: exporta(fig, formato),
                                   file_name=f"{base}.{formato}", mime=mime, type="tertiary",
                                   icon=":material/download:", on_click="ignore",
                                   key=f"baja_{key or nombre}_{formato}",
                                   help=f"Guardar este gráfico en {formato.upper()}")


def linea_ahora(fig, ahora, xref="x", yref="paper"):
    """add_shape en vez de add_vline: add_vline falla con Timestamps de pandas."""
    x = pd.Timestamp(ahora).isoformat()
    fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, xref=xref, yref=yref,
                  line=dict(color=ROJO, width=1.4, dash="dot"))


def comuna(nombre):
    """El polígono (GeoJSON) de una comuna."""
    return COMUNAS["features"][NOMBRES_COMUNAS.index(nombre)]


def vista_comuna(nombre, ancho=800, alto=620):
    """Centro y zoom del mapa que encuadran la comuna, con un margen alrededor."""
    lon, lat = np.array(comuna(nombre)["geometry"]["coordinates"][0]).T
    dlon = (lon.max() - lon.min()) * 1.5
    dlat = (lat.max() - lat.min()) * 1.5 / np.cos(np.deg2rad(lat.mean()))  # Mercator estira la latitud
    zoom = min(np.log2(ancho * 360 / (512 * dlon)), np.log2(alto * 360 / (512 * dlat)))
    return dict(center=dict(lat=float(lat.mean()), lon=float(lon.mean())), zoom=float(np.clip(zoom, 6, 11)))


@st.cache_data(show_spinner=False)
def grilla_comunas(paso=0.02):
    """Puntos cada 'paso' grados dentro de la región y la comuna de cada uno (DataFrame lat, lon, comuna).
    Sirve para pinchar el mapa en cualquier parte: Plotly solo informa clics sobre puntos."""
    lon, lat = np.meshgrid(np.arange(-73.55, -70.8, paso), np.arange(-39.65, -37.55, paso))
    lon, lat = lon.ravel(), lat.ravel()
    comuna_de = np.full(lon.size, None, dtype=object)
    for f in COMUNAS["features"]:
        x, y = np.array(f["geometry"]["coordinates"][0]).T
        x0, y0, x1, y1 = x, y, np.roll(x, -1), np.roll(y, -1)
        # rayo hacia el este: dentro si cruza un número impar de lados
        cruza = ((y0[:, None] > lat) != (y1[:, None] > lat)) & (
            lon < (x1 - x0)[:, None] * (lat - y0[:, None]) / np.where(y1 == y0, 1e-12, y1 - y0)[:, None] + x0[:, None])
        comuna_de[cruza.sum(axis=0) % 2 == 1] = f["properties"]["comuna"]
    dentro = comuna_de != None  # noqa: E711
    return pd.DataFrame({"lat": lat[dentro], "lon": lon[dentro], "comuna": comuna_de[dentro]})


def resalta_comuna(nombre):
    """Capas de mapa que rellenan y remarcan una comuna."""
    geo = comuna(nombre)
    return [dict(sourcetype="geojson", source=geo, type="fill", color="rgba(255,214,0,.18)", below="traces"),
            dict(sourcetype="geojson", source=geo, type="line", color="#FFD600", line=dict(width=3),
                 below="traces")]


def fmt(v, dec, unidad=""):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.{dec}f}{(' ' + unidad) if unidad else ''}"


def nombre_modelo(m):
    corto, centro, _ = F.MODELOS[m]
    return f"{corto} ({centro})"


def metricas_ahora(c):
    """Última observación del sitio elegido; lo que el sitio no mide queda en «—»."""
    sitio = c.sitio

    def ultimo(variable):
        """(valor, hora) de la última medición del sitio; (nan, None) si no la mide o no hay dato."""
        o = c.observado(sitio, variable)
        o = None if o is None else o.dropna()
        if o is None or o.empty:
            return np.nan, None
        return float(o.iloc[-1]), o.index[-1]

    horas = []
    tarjetas = []
    for var, nombre, dec, unidad, icono in [
        ("temperatura", "Temperatura", 0, "°C", "thermostat"),
        ("humedad", "Humedad", 0, "%", "humidity_percentage"),
        ("viento", "Viento", 0, "km/h", "air"),
        ("rafaga", "Ráfaga", 0, "km/h", "storm"),
        ("presion", "Presión", 0, "hPa", "speed"),
    ]:
        v, h = ultimo(var)
        if h is not None:
            horas.append(h)
        delta = None
        if var == "viento" and h is not None and "direccion" in sitio["vars"]:
            delta = F.cardinal(ultimo("direccion")[0])
        elif var == "presion" and h is not None:
            p = c.observado(sitio, "presion").dropna()
            hace3 = p[p.index <= h - pd.Timedelta(hours=3)]
            delta = f"{v - hace3.iloc[-1]:+.0f} hPa en 3 h" if len(hace3) else None
        # el METAR informa ráfaga solo cuando es significativa: sin dato con METAR vigente = sin ráfagas
        sin_rafagas = var == "rafaga" and var in sitio["vars"] and np.isnan(v) and not c.metar.empty
        tarjetas.append((nombre, "sin ráfagas" if sin_rafagas else fmt(v, dec, unidad), delta, icono))

    pp = c.observado(sitio, "precipitacion")
    pp24 = np.nan
    if pp is not None and not pp.empty:
        pp24 = pp[pp.index > pp.index.max() - pd.Timedelta(hours=24)].sum()
        horas.append(pp.index.max())
    tarjetas.append(("Lluvia 24 h", fmt(pp24, 1, "mm"), None, "rainy"))

    if horas:
        h = max(horas)
        st.caption(f"Ahora en {F.etiqueta(sitio)}, comuna de {sitio['comuna']} · última medición a las {h:%H:%M} del {h:%d/%m} "
                   "(hora de Chile). «—»: sin medición de esa variable en esta estación.")
    else:
        st.caption(f"Sin mediciones recientes de {F.etiqueta(sitio)}.")
    # fila horizontal: se reparte en varias líneas sola en pantallas angostas
    with st.container(horizontal=True, gap="small"):
        for nombre, valor, delta, icono in tarjetas:
            st.metric(nombre, valor, delta, delta_color="off", delta_arrow="off", border=True,
                      icon=f":material/{icono}:")


# ------------------------------------------------------------------ controles
SITIO_INICIAL = "temuco_centro"


def etiqueta_sitio(i):
    return f"{F.etiqueta(F.SITIO[i])} · {F.SITIO[i]['comuna']}"


def _al_cambiar_comuna():
    """Otra comuna en «Ahora mismo»: el sitio pasa a ser su primera estación (Temuco Centro en Temuco)."""
    ids = [s["id"] for s in F.SITIOS if s["comuna"] == st.session_state["ahora_comuna"]]
    st.session_state["sitio"] = SITIO_INICIAL if SITIO_INICIAL in ids else ids[0]


def controles(por_comuna=False):
    """Barra de controles (reemplaza a la barra lateral): el sitio a la vista y el resto dentro de
    "Ajustes". Arma y devuelve el contexto de la corrida. Sitio y días quedan en la URL para
    compartir la vista; modelos y banda se conservan al cambiar de página. Con 'por_comuna' (el Home)
    se elige primero la comuna y «Sitio» lista solo sus estaciones. Sin otra indicación, Temuco Centro."""
    if "sitio" not in st.session_state:  # primera vez: el de la URL compartida o Temuco Centro
        por_etiqueta = {etiqueta_sitio(s["id"]): s["id"] for s in F.SITIOS}
        st.session_state["sitio"] = por_etiqueta.get(st.query_params.get("sitio"), SITIO_INICIAL)
    ids = [s["id"] for s in F.SITIOS]
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        if por_comuna:
            st.session_state["ahora_comuna"] = F.SITIO[st.session_state["sitio"]]["comuna"]
            comuna = st.selectbox("Comuna", sorted({s["comuna"] for s in F.SITIOS}), key="ahora_comuna",
                                  on_change=_al_cambiar_comuna, width=200,
                                  help="Filtra las estaciones de «Sitio» a las de esta comuna.")
            ids = [i for i in ids if F.SITIO[i]["comuna"] == comuna]
        sitio_id = st.selectbox("Sitio", ids, format_func=etiqueta_sitio, key="sitio", bind="query-params",
                                width=320 if por_comuna else 400,
                                help="Escribe para buscar por estación o por comuna. Los modelos se consultan en "
                                     "las coordenadas del sitio elegido.")
        with st.popover("Ajustes", icon=":material/tune:"):
            pasado = st.slider("Días hacia atrás", 1, F.DIAS_PUBLICADOS, 3, key="pasado", bind="query-params")
            futuro = st.slider("Días de pronóstico", 1, F.DIAS_PUBLICADOS, 5, key="futuro", bind="query-params")
            modelos = st.multiselect("Modelos", list(F.MODELOS), default=list(F.MODELOS), format_func=nombre_modelo,
                                     key="modelos", persist_state="session")
            con_ensamble = st.toggle("Banda del super-ensamble (p10–p90)", value=True, key="banda",
                                     persist_state="session")
            st.caption("Los datos se renuevan solos cada hora.")
        origen = st.empty()
    c = prepara_contexto(sitio_id, pasado, futuro, modelos, con_ensamble)
    origen.caption(f":material/schedule: Pronóstico: {c.origen_pron or 'no disponible'}")
    if c.error_pron and c.origen_pron is None:
        st.warning("No se pudo obtener el pronóstico (Open-Meteo no respondió y todavía no hay copia publicada). "
                   "Se muestran solo las observaciones; vuelve a intentar en unos minutos.  \n"
                   f"Detalle: `{c.error_pron[:160]}`", icon=":material/cloud_off:")
    elif c.error_pron:
        st.caption(f":material/info: Open-Meteo no respondió; se muestra la {c.origen_pron}.")
    return c
