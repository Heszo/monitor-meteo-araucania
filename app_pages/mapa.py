"""Mapa de estaciones: última medición de cada estación sobre imagen satelital."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import comun as C
import fuentes as F
from comun import BANDA, DIAS, EJE_T, NEGRO, ROJO, barra, fmt, linea_ahora, nombre_modelo

c = C.contexto()
sitio, pasado, futuro, modelos, con_ensamble = c.sitio, c.pasado, c.futuro, c.modelos, c.con_ensamble
ahora, t0, t_fin, metar, pron, det, pct, avisos = c.ahora, c.t0, c.t_fin, c.metar, c.pron, c.det, c.pct, c.avisos
origen_pron = c.origen_pron
observado, recorta, det_var = c.observado, c.recorta, c.det_var

medibles = ["temperatura", "humedad", "precipitacion", "viento", "rafaga", "presion"]
var_m = st.segmented_control("Variable", medibles, default="temperatura", required=True,
                             format_func=lambda k: F.VARIABLES[k]["nombre"], key="variable_mapa",
                             bind="query-params")
ventana_pp = 24
if var_m == "precipitacion":
    ventana_pp = st.slider("Lluvia acumulada en las últimas … horas", 1, pasado * 24, min(24, pasado * 24))
filas_m = []
for s in F.SITIOS:
    o = observado(s, var_m)
    if o is None or not len(o):
        continue
    if var_m == "precipitacion":
        valor, hora = o[o.index > o.index.max() - pd.Timedelta(hours=ventana_pp)].sum(), o.index.max()
    else:
        o = o.dropna()
        if not len(o):
            continue
        valor, hora = float(o.iloc[-1]), o.index[-1]
    filas_m.append(dict(Estación=s["nombre"].split(" (")[0], Grupo=s["grupo"], lat=s["lat"], lon=s["lon"], valor=valor,
                        Hora=hora, Fuente="METAR" if s["fuente"] == "metar" else "VIPNet"))
Vm = F.VARIABLES[var_m]
unidad_m = "mm" if var_m == "precipitacion" else Vm["unidad"]
if not filas_m:
    st.info("Ninguna estación informó esta variable en la ventana.", icon=":material/sensors_off:")
else:
    dm = pd.DataFrame(filas_m)
    escala = {"temperatura": "RdYlBu_r", "humedad": "YlGnBu", "precipitacion": "Blues",
              "viento": "Viridis", "rafaga": "Viridis", "presion": "Plasma"}[var_m]
    fmap = go.Figure(go.Scattermap(
        lat=dm.lat, lon=dm.lon, mode="markers+text",
        marker=dict(size=13, color=dm.valor, colorscale=escala, showscale=True,
                    colorbar=dict(title=unidad_m, thickness=12)),
        text=[fmt(v, Vm['decimales']) for v in dm.valor], customdata=dm["Estación"],
        textposition="middle right", textfont=dict(color="white", size=11),
        hovertemplate="%{customdata}: %{text} " + unidad_m + "<extra></extra>"))
    fmap.update_layout(map=C.MAPA | dict(zoom=7.2), margin=dict(l=0, r=0, t=0, b=0), height=620)
    col_map, col_tab = st.columns([3, 2])
    C.grafico(fmap, f"mapa_{var_m}", boton="resetViewMap", donde=col_map)
    col_tab.dataframe(dm[["Estación", "Grupo", "valor", "Hora", "Fuente"]]
                      .rename(columns={"valor": f"{Vm['nombre']} ({unidad_m})"}).sort_values("Grupo"),
                      hide_index=True, width="stretch",
                      column_config={"Hora": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                     f"{Vm['nombre']} ({unidad_m})": st.column_config.NumberColumn(
                                         format=f"%.{Vm['decimales']}f")})
    titulo = (f"acumulado de las últimas {ventana_pp} h" if var_m == "precipitacion" else "última medición")
    col_tab.caption(f"{Vm['nombre']}: {titulo}. Imagen: Esri World Imagery.")
