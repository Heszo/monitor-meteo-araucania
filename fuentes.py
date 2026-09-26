"""
Descarga y ordena los datos del monitor: observaciones (VIPNet DGA/MOP y
METAR del aeropuerto La Araucanía) y pronósticos (7 modelos deterministas y el
super-ensamble de 143 miembros, ambos vía Open-Meteo).

Todas las series quedan en hora local de Chile (America/Santiago), sin zona
horaria, en pasos horarios. El valor de la hora T es:
- lluvia: lo caído en la hora que TERMINA en T (misma convención que Open-Meteo);
- el resto: el valor instantáneo más cercano a T (media de la hora que termina en T
  para las estaciones VIPNet, que miden cada 30 min).
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ZONA = ZoneInfo("America/Santiago")
UA = {"User-Agent": "monitor-meteo-araucania (divulgación; github.com/Heszo)"}
URL_VIPNET = "https://vipnet.mop.gob.cl/v1/vipnet/estacion/valores"
URL_METAR = "https://aviationweather.gov/api/data/metar"
URL_OM = "https://api.open-meteo.com/v1/forecast"
URL_ENS = "https://ensemble-api.open-meteo.com/v1/ensemble"
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

# ------------------------------------------------------------------ catálogo
# clave: dict(nombre, unidad, om = variable de Open-Meteo, vipnet = tipoEstacion,
#            metar = columna del METAR, ens = si el super-ensamble la trae)
VARIABLES = {
    "temperatura": dict(nombre="Temperatura", unidad="°C", om="temperature_2m", vipnet=1,
                        metar="temperatura", decimales=1),
    "humedad": dict(nombre="Humedad relativa", unidad="%", om="relative_humidity_2m", vipnet=4,
                    metar="humedad", decimales=0),
    "viento": dict(nombre="Viento medio (10 m)", unidad="km/h", om="wind_speed_10m", vipnet=5,
                   metar="viento", decimales=0),
    "rafaga": dict(nombre="Ráfaga (10 m)", unidad="km/h", om="wind_gusts_10m", vipnet=None,
                   metar="rafaga", decimales=0),
    "direccion": dict(nombre="Dirección del viento", unidad="°", om="wind_direction_10m", vipnet=None,
                      metar="direccion", decimales=0, sin_ensamble=True),
    "presion": dict(nombre="Presión al nivel del mar", unidad="hPa", om="pressure_msl", vipnet=None,
                    metar="presion", decimales=1),
    "precipitacion": dict(nombre="Precipitación", unidad="mm/h", om="precipitation", vipnet=0,
                          metar=None, decimales=1),
}

MODELOS = {
    "gfs_seamless": ("GFS", "NOAA", "#1f77b4"),
    "ecmwf_ifs025": ("IFS", "ECMWF", "#d62728"),
    "icon_seamless": ("ICON", "DWD", "#2ca02c"),
    "gem_seamless": ("GEM", "Canadá", "#9467bd"),
    "jma_seamless": ("GSM", "JMA", "#8c564b"),
    "ukmo_seamless": ("UM", "UK Met Office", "#e377c2"),
    "meteofrance_seamless": ("ARPEGE", "Météo-France", "#ff7f0e"),
}
ENSAMBLES = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless", "gem_global"]  # 31+51+40+21 = 143

# Sitios: el METAR del aeropuerto La Araucanía (SCQP, Freire; el único de la región que informa) y
# todas las estaciones VIPNet de La Araucanía que entregan datos (catálogo con región 9, verificado el
# 26/09/2026). "vars" = variables que mide cada una; se omiten los sensores que esa semana informaban
# valores imposibles: pluviómetros en 0 con ~150 mm alrededor (Tranamán, Pailahueque, Quitratúe,
# Chanlelfu, Río Truful, Río Cruces ante Loncoche), humedad fija en 100 % (Río Huichahue, Puesco,
# Lago Caburgua, Gorbea, Licán Ray) o en 35-47 % con lluvia (Río Truful) y viento fijo en 81 km/h
# (Quitratúe). Río Cautín en Almagro y Río Trafampulli no entregan datos. Grupos por longitud:
# costa (oeste de 72,85° O, incluye la cordillera de Nahuelbuta), valle y cordillera (este de 72,1° O).
SITIOS = [
    dict(id="aeropuerto", nombre="Aeropuerto La Araucanía", fuente="metar", codigo="SCQP",
         lat=-38.9250, lon=-72.6480, alt=100, grupo="valle",
         vars=["temperatura", "humedad", "viento", "rafaga", "direccion", "presion"]),
    dict(id="parque_nahuelbuta", nombre="Parque Nahuelbuta", fuente="vipnet", codigo="08358005-4",
         lat=-37.8232, lon=-72.9606, alt=1177, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_puren_en_tranaman", nombre="Río Purén en Tranamán", fuente="vipnet", codigo="09101001-1",
         lat=-38.0194, lon=-73.0123, alt=90, grupo="costa", vars=["precipitacion"]),
    dict(id="tranaman", nombre="Tranamán", fuente="vipnet", codigo="09101003-8",
         lat=-38.0214, lon=-73.0065, alt=78, grupo="costa", vars=["temperatura", "humedad"]),
    dict(id="lumaco", nombre="Lumaco", fuente="vipnet", codigo="09102003-3",
         lat=-38.1635, lon=-72.9021, alt=60, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="bajo_yupehue", nombre="Bajo Yupehue", fuente="vipnet", codigo="09000001-2",
         lat=-38.5536, lon=-73.4856, alt=139, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="carahue", nombre="Carahue", fuente="vipnet", codigo="09151001-4",
         lat=-38.7128, lon=-73.1476, alt=77, grupo="costa", vars=["precipitacion"]),
    dict(id="nueva_imperial", nombre="Nueva Imperial", fuente="vipnet", codigo="09150003-5",
         lat=-38.7464, lon=-72.9553, alt=23, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="boroa", nombre="Boroa", fuente="vipnet", codigo="09129016-2",
         lat=-38.7689, lon=-72.8778, alt=41, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="puerto_saavedra", nombre="Puerto Saavedra", fuente="vipnet", codigo="09153001-5",
         lat=-38.7931, lon=-73.3959, alt=5, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="puerto_dominguez", nombre="Puerto Domínguez", fuente="vipnet", codigo="09200002-8",
         lat=-38.8972, lon=-73.2539, alt=13, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_tolten_en_teodoro_schmidt", nombre="Río Toltén en Teodoro Schmidt", fuente="vipnet", codigo="09437002-7",
         lat=-39.0143, lon=-73.0829, alt=15, grupo="costa", vars=["precipitacion"]),
    dict(id="teodoro_schmidt", nombre="Teodoro Schmidt", fuente="vipnet", codigo="09438001-4",
         lat=-39.0251, lon=-73.0793, alt=13, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="faja_maisan", nombre="Faja Maisan", fuente="vipnet", codigo="09436002-1",
         lat=-39.0875, lon=-72.9306, alt=57, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="porma", nombre="Porma", fuente="vipnet", codigo="09300001-3",
         lat=-39.1270, lon=-73.2672, alt=12, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="tolten", nombre="Toltén", fuente="vipnet", codigo="09439001-K",
         lat=-39.1763, lon=-73.1621, alt=5, grupo="costa", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="posta_esperanza", nombre="Posta Esperanza", fuente="vipnet", codigo="09500001-0",
         lat=-39.3136, lon=-73.1911, alt=14, grupo="costa", vars=["temperatura", "precipitacion"]),
    dict(id="angol_la_mona", nombre="Angol (La Mona)", fuente="vipnet", codigo="08358002-K",
         lat=-37.7792, lon=-72.6372, alt=113, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="rio_mininco_en_longitudinal", nombre="Río Mininco en Longitudinal", fuente="vipnet", codigo="08343001-K",
         lat=-37.8632, lon=-72.3925, alt=125, grupo="valle", vars=["precipitacion"]),
    dict(id="rio_rehue_en_quebrada_culen", nombre="Río Rehue en Quebrada Culén", fuente="vipnet", codigo="08356001-0",
         lat=-37.9414, lon=-72.8061, alt=65, grupo="valle", vars=["humedad", "precipitacion"]),
    dict(id="rio_malleco_en_collipulli", nombre="Río Malleco en Collipulli", fuente="vipnet", codigo="08351001-3",
         lat=-37.9647, lon=-72.4357, alt=153, grupo="valle", vars=["precipitacion"]),
    dict(id="ercilla_vida_nueva", nombre="Ercilla (Vida Nueva)", fuente="vipnet", codigo="08353001-4",
         lat=-38.0448, lon=-72.4603, alt=262, grupo="valle", vars=["precipitacion"]),
    dict(id="pailahueque", nombre="Pailahueque", fuente="vipnet", codigo="09104006-9",
         lat=-38.1267, lon=-72.3189, alt=376, grupo="valle", vars=["temperatura", "humedad"]),
    dict(id="las_mercedes_victoria", nombre="Las Mercedes (Victoria)", fuente="vipnet", codigo="09104003-4",
         lat=-38.2461, lon=-72.2288, alt=421, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="traiguen", nombre="Traiguén", fuente="vipnet", codigo="09105002-1",
         lat=-38.2561, lon=-72.6535, alt=234, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="galvarino", nombre="Galvarino", fuente="vipnet", codigo="09113003-3",
         lat=-38.4102, lon=-72.7838, alt=40, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="perquenco", nombre="Perquenco", fuente="vipnet", codigo="09112000-3",
         lat=-38.4185, lon=-72.3773, alt=290, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="quillen", nombre="Quillén", fuente="vipnet", codigo="09111002-4",
         lat=-38.4641, lon=-72.3867, alt=285, grupo="valle", vars=["precipitacion"]),
    dict(id="lautaro", nombre="Lautaro", fuente="vipnet", codigo="09124001-7",
         lat=-38.5254, lon=-72.4435, alt=200, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_cholchol_en_cholchol", nombre="Río Cholchol en Cholchol", fuente="vipnet", codigo="09116001-3",
         lat=-38.6077, lon=-72.8474, alt=20, grupo="valle", vars=["precipitacion"]),
    dict(id="vilcun", nombre="Vilcún", fuente="vipnet", codigo="09131002-3",
         lat=-38.6738, lon=-72.2210, alt=290, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_cautin_en_cajon", nombre="Río Cautín en Cajón", fuente="vipnet", codigo="09129002-2",
         lat=-38.6866, lon=-72.5027, alt=130, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="pueblo_nuevo_temuco", nombre="Pueblo Nuevo (Temuco)", fuente="vipnet", codigo="09129005-7",
         lat=-38.7127, lon=-72.5560, alt=119, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="temuco_centro", nombre="Temuco Centro", fuente="vipnet", codigo="09129006-5",
         lat=-38.7425, lon=-72.5897, alt=122, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="padre_las_casas", nombre="Padre Las Casas", fuente="vipnet", codigo="09132002-9",
         lat=-38.8358, lon=-72.4786, alt=117, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="rio_huichahue_en_faja_24000", nombre="Río Huichahue en Faja 24000", fuente="vipnet", codigo="09134001-1",
         lat=-38.8540, lon=-72.2850, alt=150, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="freire", nombre="Freire", fuente="vipnet", codigo="09135003-3",
         lat=-38.9597, lon=-72.6085, alt=100, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_allipen_en_los_laureles", nombre="Río Allipén en Los Laureles", fuente="vipnet", codigo="09404001-9",
         lat=-39.0073, lon=-72.2300, alt=190, grupo="valle", vars=["precipitacion"]),
    dict(id="rio_tolten_en_coipue", nombre="Río Toltén en Coipué", fuente="vipnet", codigo="09423001-2",
         lat=-39.0805, lon=-72.4524, alt=200, grupo="valle", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="gorbea", nombre="Gorbea", fuente="vipnet", codigo="09434003-9",
         lat=-39.1064, lon=-72.6786, alt=94, grupo="valle", vars=["temperatura", "viento", "precipitacion"]),
    dict(id="quitratue", nombre="Quitratúe", fuente="vipnet", codigo="09433003-3",
         lat=-39.1541, lon=-72.6568, alt=90, grupo="valle", vars=["temperatura", "humedad"]),
    dict(id="villarrica", nombre="Villarrica", fuente="vipnet", codigo="09420003-2",
         lat=-39.2177, lon=-72.2945, alt=210, grupo="valle", vars=["precipitacion"]),
    dict(id="loncoche", nombre="Loncoche", fuente="vipnet", codigo="10130001-3",
         lat=-39.3719, lon=-72.6175, alt=120, grupo="valle", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="lican_ray", nombre="Licán Ray", fuente="vipnet", codigo="10106003-9",
         lat=-39.3859, lon=-72.2240, alt=275, grupo="valle", vars=["temperatura", "precipitacion"]),
    dict(id="chanlelfu", nombre="Chanlelfu", fuente="vipnet", codigo="09420004-0",
         lat=-39.4650, lon=-72.3750, alt=345, grupo="valle", vars=["temperatura", "humedad", "viento"]),
    dict(id="rio_biobio_en_llanquen", nombre="Río Biobío en Llanquén", fuente="vipnet", codigo="08307002-1",
         lat=-38.2009, lon=-71.2989, alt=767, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="laguna_malleco", nombre="Laguna Malleco", fuente="vipnet", codigo="08350002-6",
         lat=-38.2152, lon=-71.8112, alt=894, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rari_ruca", nombre="Rari-Ruca", fuente="vipnet", codigo="09123002-K",
         lat=-38.4250, lon=-72.0108, alt=440, grupo="cordillera", vars=["precipitacion"]),
    dict(id="rio_cautin_en_rari_ruca", nombre="Río Cautín en Rari-Ruca", fuente="vipnet", codigo="09123001-1",
         lat=-38.4300, lon=-72.0104, alt=425, grupo="cordillera", vars=["precipitacion"]),
    dict(id="curacautin", nombre="Curacautín", fuente="vipnet", codigo="09122001-6",
         lat=-38.4475, lon=-71.8961, alt=535, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="lonquimay", nombre="Lonquimay", fuente="vipnet", codigo="08304004-1",
         lat=-38.4549, lon=-71.3749, alt=931, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="malalcahuello", nombre="Malalcahuello", fuente="vipnet", codigo="09120003-1",
         lat=-38.4709, lon=-71.5711, alt=950, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="liucura_lonquimay", nombre="Liucura (Lonquimay)", fuente="vipnet", codigo="08301001-0",
         lat=-38.6454, lon=-71.0910, alt=1034, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="cherquenco", nombre="Cherquenco", fuente="vipnet", codigo="09130001-K",
         lat=-38.6825, lon=-72.0021, alt=500, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="conguillio", nombre="Conguillío", fuente="vipnet", codigo="09400002-5",
         lat=-38.7736, lon=-71.6347, alt=719, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="icalma", nombre="Icalma", fuente="vipnet", codigo="08300001-5",
         lat=-38.8145, lon=-71.2806, alt=1160, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_truful_en_camino_internacional", nombre="Río Truful en Camino Internacional", fuente="vipnet", codigo="09400000-9",
         lat=-38.8392, lon=-71.6561, alt=520, grupo="cordillera", vars=["temperatura"]),
    dict(id="tricauco", nombre="Tricauco", fuente="vipnet", codigo="09401001-2",
         lat=-38.8440, lon=-71.5513, alt=520, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="cunco", nombre="Cunco", fuente="vipnet", codigo="09403001-3",
         lat=-38.9297, lon=-72.0155, alt=380, grupo="cordillera", vars=["precipitacion"]),
    dict(id="los_laureles", nombre="Los Laureles", fuente="vipnet", codigo="09404002-7",
         lat=-38.9971, lon=-72.0448, alt=260, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="pitrunco", nombre="Pitrunco", fuente="vipnet", codigo="09405011-1",
         lat=-39.0506, lon=-72.0883, alt=334, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="llanqui_llanqui", nombre="Llanqui Llanqui", fuente="vipnet", codigo="09405010-3",
         lat=-39.0644, lon=-71.7667, alt=507, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="termas_rio_blanco", nombre="Termas Río Blanco", fuente="vipnet", codigo="09415001-9",
         lat=-39.1050, lon=-71.6186, alt=732, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="lago_tinquilco", nombre="Lago Tinquilco", fuente="vipnet", codigo="09416002-2",
         lat=-39.1726, lon=-71.7319, alt=850, grupo="cordillera", vars=["precipitacion"]),
    dict(id="lago_caburgua", nombre="Lago Caburgua", fuente="vipnet", codigo="09417001-K",
         lat=-39.1880, lon=-71.7717, alt=480, grupo="cordillera", vars=["temperatura", "precipitacion"]),
    dict(id="quinenahuin", nombre="Quiñenahuín", fuente="vipnet", codigo="09411002-5",
         lat=-39.2183, lon=-71.4356, alt=659, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="rio_liucura_en_liucura", nombre="Río Liucura en Liucura", fuente="vipnet", codigo="09416001-4",
         lat=-39.2605, lon=-71.8269, alt=402, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="pucon", nombre="Pucón", fuente="vipnet", codigo="09420002-4",
         lat=-39.2893, lon=-71.9264, alt=230, grupo="cordillera", vars=["temperatura", "humedad", "viento", "precipitacion"]),
    dict(id="llafenco", nombre="Llafenco", fuente="vipnet", codigo="09414002-1",
         lat=-39.3326, lon=-71.8181, alt=360, grupo="cordillera", vars=["precipitacion"]),
    dict(id="parque_nacional_villarrica", nombre="Parque Nacional Villarrica", fuente="vipnet", codigo="09420019-9",
         lat=-39.3497, lon=-71.9695, alt=800, grupo="cordillera", vars=["temperatura", "precipitacion"]),
    dict(id="curarrehue", nombre="Curarrehue", fuente="vipnet", codigo="09412002-0",
         lat=-39.3650, lon=-71.5823, alt=420, grupo="cordillera", vars=["temperatura", "humedad", "precipitacion"]),
    dict(id="puesco_aduana", nombre="Puesco (Aduana)", fuente="vipnet", codigo="09412003-9",
         lat=-39.5335, lon=-71.5561, alt=620, grupo="cordillera", vars=["temperatura", "precipitacion"]),
]
SITIO = {s["id"]: s for s in SITIOS}

# Nodos del super-ensamble. En Open-Meteo cada miembro cuenta como una variable, así que el ensamble de
# un sitio (143 miembros × 6 variables × 14 días) pesa ~85 consultas de la cuota gratuita: pedirlo para
# los ~70 sitios cada hora agota el límite de 5000 por hora. Como sus grillas son de 0,25–0,5°, se pide
# una vez por celda de 0,5° en la estación más cercana al centro de la celda (el "nodo"), y las demás
# estaciones de la celda lo comparten. Los 7 modelos deterministas sí se piden en cada estación.
PASO_NODO = 0.5


def _nodos():
    celdas = {}
    for s in SITIOS:
        celdas.setdefault((round(s["lat"] / PASO_NODO), round(s["lon"] / PASO_NODO)), []).append(s)
    nodo = {}
    for (i, j), ss in celdas.items():
        rep = min(ss, key=lambda s: (s["lat"] - i * PASO_NODO) ** 2 + (s["lon"] - j * PASO_NODO) ** 2)
        nodo.update({s["id"]: rep["id"] for s in ss})
    return nodo


NODO = _nodos()  # id de sitio -> id de la estación cuyo ensamble usa
GRUPOS = {"costa": "#00797C", "valle": "#E0701A", "cordillera": "#6B3FA0"}
SIGLA = {"metar": "DMC", "vipnet": "DGA"}  # quién opera la estación, para las etiquetas


def etiqueta(s):
    """'Santa Juana (DGA)': nombre del sitio y, entre paréntesis, la sigla de la fuente."""
    return f"{s['nombre']} ({SIGLA[s['fuente']]})"


def ahora_local():
    return datetime.now(ZONA).replace(tzinfo=None)


def a_local(utc):
    """DatetimeIndex/Series UTC (con o sin tz) -> hora de Chile sin zona."""
    t = pd.DatetimeIndex(pd.to_datetime(utc, utc=True))
    return t.tz_convert(ZONA).tz_localize(None)


# ------------------------------------------------------------------ VIPNet
# Rango físico por tipoEstacion (lluvia en mm cada 30 min): fuera de él, el dato se descarta. Filtra
# picos sueltos como los -18 mm de Villarrica, los 82 mm en media hora de Llafenco o los 560 °C de
# Malalcahuello vistos en septiembre de 2026.
LIMITES = {0: (0, 40), 1: (-25, 45), 4: (1, 100), 5: (0, 200)}


def vipnet(codigo, tipo, horas):
    """Serie cruda (cada 30 min) de una estación VIPNet: DataFrame[hora, valor], sin los valores
    fuera de LIMITES."""
    t = ahora_local()  # la API arma la ventana en hora chilena
    cuerpo = {"codigoEstacion": codigo, "tipoEstacion": tipo, "fetchHour": t.hour,
              "fetchDay": f"{t:%Y-%m-%d}", "hoursRange": int(horas)}
    r = requests.post(URL_VIPNET, json=cuerpo, headers=UA, timeout=30)
    r.raise_for_status()
    d = r.json().get("data", [])
    if not d:
        return pd.DataFrame(columns=["hora", "valor"])
    df = pd.DataFrame({"hora": a_local([x["fecha"]["$date"] for x in d]),
                       "valor": [np.nan if x.get("instantaneo") is None else float(x["instantaneo"])
                                 for x in d]})
    lo, hi = LIMITES.get(tipo, (-np.inf, np.inf))
    df.loc[(df.valor < lo) | (df.valor > hi), "valor"] = np.nan
    return df.sort_values("hora").drop_duplicates("hora").reset_index(drop=True)


def a_horaria(df, variable):
    """Pasa una serie cruda a horaria (hora que termina en T). Lluvia: suma,
    solo horas completas; resto: media de la hora."""
    if df.empty:
        return pd.Series(dtype=float)
    g = df.groupby(df.hora.dt.ceil("h"))["valor"]
    if variable != "precipitacion":
        return g.mean()
    paso = df.hora.diff().median()
    por_hora = max(int(round(pd.Timedelta(hours=1) / paso)), 1) if pd.notna(paso) else 1
    tab = g.agg(["sum", "count"])
    return tab.loc[tab["count"] >= por_hora, "sum"]


def vipnet_variable(variable, horas):
    """{id_sitio: Series horaria} para todas las estaciones VIPNet que miden
    'variable', descargadas en paralelo. Devuelve también la lista de avisos."""
    tipo = VARIABLES[variable]["vipnet"]
    sitios = [s for s in SITIOS if s["fuente"] == "vipnet" and variable in s["vars"]]

    def una(s):
        try:
            return s["id"], a_horaria(vipnet(s["codigo"], tipo, horas), variable), None
        except Exception as ex:  # noqa: BLE001
            return s["id"], None, f"{s['nombre']}: {str(ex)[:120]}"

    with ThreadPoolExecutor(max_workers=12) as pool:
        res = list(pool.map(una, sitios))
    series = {i: s for i, s, _ in res if s is not None and not s.empty}
    avisos = [a for _, _, a in res if a]
    avisos += [f"{SITIO[i]['nombre']}: sin datos de {VARIABLES[variable]['nombre'].lower()}"
               for i, s, a in res if a is None and (s is None or s.empty)]
    return series, avisos


# ------------------------------------------------------------------ METAR
def humedad_relativa(t, td):
    """Magnus (Alduchov y Eskridge, 1996)."""
    a, b = 17.625, 243.04
    return 100 * np.exp(a * td / (b + td)) / np.exp(a * t / (b + t))


def metar(estacion="SCQP", horas=72):
    """METAR/SPECI de una estación: DataFrame horario (hora local) con
    temperatura, humedad, viento, ráfaga, dirección y presión (QNH)."""
    r = requests.get(URL_METAR, params={"ids": estacion, "format": "json", "hours": int(horas)},
                     headers=UA, timeout=30)
    r.raise_for_status()
    d = r.json()
    if not d:
        return pd.DataFrame()

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return np.nan  # p. ej. dirección "VRB"

    df = pd.DataFrame({
        "hora": a_local(pd.to_datetime([x["obsTime"] for x in d], unit="s")),
        "tipo": [x.get("metarType") for x in d],
        "temperatura": [num(x.get("temp")) for x in d],
        "rocio": [num(x.get("dewp")) for x in d],
        "viento": [num(x.get("wspd")) * 1.852 for x in d],
        "rafaga": [num(x.get("wgst")) * 1.852 for x in d],
        "direccion": [num(x.get("wdir")) for x in d],
        "presion": [num(x.get("altim")) for x in d],
        "texto": [x.get("rawOb", "") for x in d],
    })
    df["humedad"] = humedad_relativa(df.temperatura, df.rocio)
    # viento calmo: la dirección no tiene sentido
    df.loc[df.viento == 0, "direccion"] = np.nan
    # a la hora más cercana; entre METAR y SPECI de la misma hora, gana el METAR
    df["hora_redonda"] = df.hora.dt.round("h")
    df = (df.sort_values(["hora_redonda", "tipo"])
          .drop_duplicates("hora_redonda", keep="first")
          .set_index("hora_redonda").sort_index())
    df.index.name = "hora"
    return df


# ------------------------------------------------------------------ Open-Meteo
# Open-Meteo gratuito limita las consultas por IP. En Streamlit Community Cloud la IP es compartida
# con otras apps y suele estar agotada (HTTP 429), así que la app lee los pronósticos que una GitHub
# Action publica cada hora en la rama "datos" (ver actualiza_pronosticos.py) y solo consulta en vivo
# si esa copia falta o está vieja.
REPO = "Heszo/monitor-meteo-araucania"
URL_PUBLICADOS = os.environ.get("MONITOR_DATOS", f"https://raw.githubusercontent.com/{REPO}/datos")  # URL o carpeta
DIAS_PUBLICADOS = 7  # pasado y futuro guardados en la copia publicada (el máximo de la barra lateral)


class OpenMeteoError(RuntimeError):
    pass


def _get_json(url, params, intentos=4, timeout=60):
    """GET con reintentos ante 429, errores 5xx, cortes y respuestas que no son JSON."""
    ultimo = ""
    for k in range(intentos):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
            else:
                r.raise_for_status()
                return r.json()
        except (requests.Timeout, requests.ConnectionError, ValueError) as ex:
            ultimo = type(ex).__name__
        except requests.HTTPError as ex:  # 4xx distinto de 429: no tiene sentido reintentar
            raise OpenMeteoError(f"{url.split('/')[2]}: {ex.response.status_code} {ex.response.text[:200]}") from None
        if k < intentos - 1:
            time.sleep(2 * 2 ** k)
    raise OpenMeteoError(f"{url.split('/')[2]}: {ultimo} tras {intentos} intentos")


def _params(puntos, variables, pasado, futuro):
    """Parámetros para uno o varios puntos [(lat, lon), ...]: Open-Meteo acepta listas separadas por
    coma y responde una lista en el mismo orden, así una consulta sirve para un lote de sitios."""
    return dict(latitude=",".join(f"{la:.4f}" for la, _ in puntos),
                longitude=",".join(f"{lo:.4f}" for _, lo in puntos), hourly=",".join(variables),
                past_days=int(pasado), forecast_days=int(futuro), timezone="America/Santiago",
                wind_speed_unit="kmh")


def _por_punto(respuesta):
    """Lista con el bloque "hourly" de cada punto (con un solo punto Open-Meteo no devuelve lista)."""
    return [r["hourly"] for r in (respuesta if isinstance(respuesta, list) else [respuesta])]


def _serie(valores):
    return np.array([np.nan if x is None else x for x in valores], float)


def deterministas(puntos, pasado, futuro):
    """Por cada punto, {variable: DataFrame(tiempo x modelo)} de los 7 modelos deterministas."""
    oms = [v["om"] for v in VARIABLES.values()]
    salida = []
    for h in _por_punto(_get_json(URL_OM, _params(puntos, oms, pasado, futuro) | {"models": ",".join(MODELOS)},
                                  timeout=120)):
        t = pd.to_datetime(h["time"])
        uno = {}
        for clave, v in VARIABLES.items():
            cols = {m: _serie(h[f"{v['om']}_{m}"]) for m in MODELOS if f"{v['om']}_{m}" in h}
            uno[clave] = pd.DataFrame({m: x for m, x in cols.items() if np.isfinite(x).any()}, index=t)
        salida.append(uno)
    return salida


def ensamble(puntos, pasado, futuro):
    """Por cada punto, {variable: DataFrame(tiempo x miembro)} del super-ensamble (los 4
    centros juntos). La dirección se omite: sus percentiles no tienen sentido.
    Si un centro no responde se sigue con los demás; si no responde ninguno, error."""
    claves = [k for k, v in VARIABLES.items() if not v.get("sin_ensamble")]
    oms = [VARIABLES[k]["om"] for k in claves]

    def uno(modelo):
        try:
            return modelo, _por_punto(_get_json(URL_ENS, _params(puntos, oms, pasado, futuro) | {"models": modelo},
                                                timeout=180))
        except OpenMeteoError:
            return modelo, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        respuestas = [(m, hs) for m, hs in pool.map(uno, ENSAMBLES) if hs]
    if not respuestas:
        raise OpenMeteoError("ensemble-api.open-meteo.com: ningún centro respondió")
    salida = []
    for i in range(len(puntos)):
        t = pd.to_datetime(respuestas[0][1][i]["time"])
        por_var = {}
        for clave, om in zip(claves, oms):
            cols = {}
            for modelo, hs in respuestas:
                for k, valores in hs[i].items():
                    if k == om or k.startswith(om + "_member"):
                        serie = _serie(valores)
                        if np.isfinite(serie).any():
                            cols[f"{modelo}:{k}"] = serie
            por_var[clave] = pd.DataFrame(cols, index=t)
        salida.append(por_var)
    return salida


def percentiles(miembros, qs=(10, 50, 90)):
    if miembros is None or miembros.empty:
        return None
    return pd.DataFrame({f"p{q}": np.nanpercentile(miembros.values, q, axis=1) for q in qs},
                        index=miembros.index)


def resumen_pronostico(det, ens):
    """Lo que la app usa de un sitio: deterministas, percentiles del ensamble
    por variable, los miembros de lluvia (para acumulados y bloques) y la
    ráfaga de cada bloque de 6 h (mediana entre miembros del máximo del bloque)."""
    raf = ens.get("rafaga")
    raf6h = None
    if raf is not None and not raf.empty:
        raf6h = raf.resample("6h", origin="start_day", closed="right", label="left").max().median(axis=1)
    return {"det": det, "pct": {k: percentiles(v) for k, v in ens.items()},
            "pp": ens.get("precipitacion"), "raf6h": raf6h}


def pronostico_lote(puntos, pasado, futuro, exige_ensamble=True):
    """Resumen de cada punto [(lat, lon), ...], en vivo y con una consulta por fuente para todo el
    lote. Con exige_ensamble=False, si el ensamble no responde se devuelven igual los 7 modelos
    (sin banda ni miembros de lluvia)."""
    det = deterministas(puntos, pasado, futuro)
    try:
        ens = ensamble(puntos, pasado, futuro)
    except OpenMeteoError:
        if exige_ensamble:
            raise
        ens = [{} for _ in puntos]
    return [resumen_pronostico(d, e) for d, e in zip(det, ens)]


def pronostico_vivo(lat, lon, pasado, futuro, exige_ensamble=True):
    """Resumen de un sitio en vivo."""
    return pronostico_lote([(lat, lon)], pasado, futuro, exige_ensamble)[0]


# --- copia publicada: 4 tablas parquet con columnas "sitio|variable|serie". Las tablas del ensamble
# (pct, pp, raf6h) se guardan una vez por nodo; meta.json dice qué nodo usa cada sitio.
def guarda_pronosticos(por_sitio, carpeta, generado, nodo=None):
    import json
    from pathlib import Path

    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    nodo = {sid: (nodo or {}).get(sid, sid) for sid in por_sitio}
    tablas = {"det": {}, "pct": {}, "pp": {}, "raf6h": {}}
    hechos = set()
    for sid, r in por_sitio.items():
        for var, df in r["det"].items():
            for c in df:
                tablas["det"][f"{sid}|{var}|{c}"] = df[c]
        e = nodo[sid]
        if e in hechos:
            continue
        hechos.add(e)
        for var, df in r["pct"].items():
            if df is not None:
                for c in df:
                    tablas["pct"][f"{e}|{var}|{c}"] = df[c]
        if r["pp"] is not None:
            for c in r["pp"]:
                tablas["pp"][f"{e}|precipitacion|{c}"] = r["pp"][c]
        if r["raf6h"] is not None:
            tablas["raf6h"][f"{e}|rafaga|p50"] = r["raf6h"]
    for nombre, cols in tablas.items():
        pd.DataFrame(cols).astype("float32").to_parquet(carpeta / f"{nombre}.parquet", compression="zstd")
    (carpeta / "meta.json").write_text(json.dumps({"generado": generado, "sitios": sorted(por_sitio),
                                                   "nodos": nodo}))


def _desarma(df):
    """{sitio: {variable: DataFrame(tiempo x serie)}} desde columnas 'sitio|variable|serie'."""
    salida = {}
    for col in df.columns:
        sid, var, serie = col.split("|", 2)
        salida.setdefault(sid, {}).setdefault(var, {})[serie] = df[col].astype(float)
    return {sid: {v: pd.DataFrame(c) for v, c in vs.items()} for sid, vs in salida.items()}


def lee_pronosticos(base=URL_PUBLICADOS):
    """(generado, {sitio: resumen}) desde la copia publicada (URL o carpeta)."""
    import io
    import json
    from pathlib import Path

    def lee(nombre):
        if str(base).startswith("http"):
            r = requests.get(f"{base}/{nombre}", headers=UA, timeout=30)
            r.raise_for_status()
            return r.content
        return (Path(base) / nombre).read_bytes()

    meta = json.loads(lee("meta.json"))
    t = {n: _desarma(pd.read_parquet(io.BytesIO(lee(f"{n}.parquet")))) for n in ("det", "pct", "pp", "raf6h")}
    por_sitio = {}
    for sid in meta["sitios"]:
        e = meta.get("nodos", {}).get(sid, sid)
        pp = t["pp"].get(e, {}).get("precipitacion")
        raf = t["raf6h"].get(e, {}).get("rafaga")
        por_sitio[sid] = {"det": t["det"].get(sid, {}), "pct": t["pct"].get(e, {}), "pp": pp,
                          "raf6h": raf["p50"] if raf is not None else None}
    return pd.Timestamp(meta["generado"]), por_sitio


# ------------------------------------------------------------------ verificación
def diferencia(pron, obs, variable):
    """Diferencia pronóstico - observado; la dirección se toma en el círculo
    (-180, 180]."""
    d = pron - obs
    if variable == "direccion":
        d = (d + 180) % 360 - 180
    return d


def verificacion(modelos_df, obs, variable, hasta):
    """Métricas de cada modelo contra la observación en las horas ya
    ocurridas (<= hasta): n, sesgo, MAE, RMSE, correlación."""
    filas = []
    obs = obs[(obs.index <= hasta)].dropna()
    for m in modelos_df.columns:
        par = pd.concat([modelos_df[m], obs], axis=1, join="inner").dropna()
        if len(par) < 3:
            continue
        d = diferencia(par.iloc[:, 0], par.iloc[:, 1], variable)
        corr = par.iloc[:, 0].corr(par.iloc[:, 1]) if variable != "direccion" else np.nan
        filas.append(dict(modelo=m, n=len(par), sesgo=d.mean(), mae=d.abs().mean(),
                          rmse=float(np.sqrt((d ** 2).mean())), r=corr))
    return pd.DataFrame(filas).sort_values("mae") if filas else pd.DataFrame()


def cardinal(grados):
    if grados is None or np.isnan(grados):
        return "—"
    nombres = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return nombres[int((grados + 11.25) // 22.5) % 16]
