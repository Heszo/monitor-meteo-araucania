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
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
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
# vista de los mapas: toda la región, de Angol a Puesco y de la costa a la cordillera
MAPA = dict(style="white-bg", center=dict(lat=-38.65, lon=-72.3),
            layers=[dict(sourcetype="raster", source=[F.ESRI], below="traces")])


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


def calienta_caches():
    """La llama app.py al arrancar y cada pocos minutos: con las entradas frescas es
    casi gratis; con las vencidas dispara su refresco en segundo plano."""
    for f, args in [(carga_publicados, ()), (carga_metar, ()), *[(carga_vipnet, (v,)) for v in VARS_VIPNET]]:
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


def linea_ahora(fig, ahora, xref="x", yref="paper"):
    """add_shape en vez de add_vline: add_vline falla con Timestamps de pandas."""
    x = pd.Timestamp(ahora).isoformat()
    fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, xref=xref, yref=yref,
                  line=dict(color=ROJO, width=1.4, dash="dot"))


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
        st.caption(f"Ahora en {F.etiqueta(sitio)} · última medición a las {h:%H:%M} del {h:%d/%m} "
                   "(hora de Chile). «—»: sin medición de esa variable en esta estación.")
    else:
        st.caption(f"Sin mediciones recientes de {F.etiqueta(sitio)}.")
    # fila horizontal: se reparte en varias líneas sola en pantallas angostas
    with st.container(horizontal=True, gap="small"):
        for nombre, valor, delta, icono in tarjetas:
            st.metric(nombre, valor, delta, delta_color="off", delta_arrow="off", border=True,
                      icon=f":material/{icono}:")


# ------------------------------------------------------------------ controles
def controles():
    """Barra de controles (reemplaza a la barra lateral): el sitio a la vista y el resto dentro de
    "Ajustes". Arma y devuelve el contexto de la corrida. Sitio y días quedan en la URL para
    compartir la vista; modelos y banda se conservan al cambiar de página."""
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        sitio_id = st.selectbox("Sitio", [s["id"] for s in F.SITIOS], format_func=lambda i: F.etiqueta(F.SITIO[i]),
                                key="sitio", bind="query-params", width=360,
                                help="Escribe para buscar entre las estaciones. Los modelos se consultan en las coordenadas del sitio elegido.")
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
