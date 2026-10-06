"""Mapa de estaciones: última medición de cada estación sobre imagen satelital, con los límites
comunales; al elegir una comuna el mapa se acerca a ella y la tabla muestra sus estaciones."""
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
with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    var_m = st.segmented_control("Variable", medibles, default="temperatura", required=True,
                                 format_func=lambda k: F.VARIABLES[k]["nombre"], key="variable_mapa",
                                 bind="query-params")
    TODAS = "Toda la región"
    comuna = st.selectbox("Comuna", [TODAS, *sorted(C.NOMBRES_COMUNAS)], key="comuna", bind="query-params",
                          width=260, help="Acerca el mapa a la comuna y muestra solo sus estaciones en la tabla.")
    C.elige_mapa_base()
comuna = None if comuna == TODAS else comuna
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
    filas_m.append(dict(Estación=s["nombre"].split(" (")[0], Comuna=s["comuna"], lat=s["lat"],
                        lon=s["lon"], valor=valor, Hora=hora, Fuente="METAR" if s["fuente"] == "metar" else "VIPNet"))
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
        text=[fmt(v, Vm['decimales']) for v in dm.valor], customdata=dm[["Estación", "Comuna"]],
        textposition="middle right", textfont=dict(color=C.texto_mapa(), size=11),
        hovertemplate="%{customdata[0]} (%{customdata[1]}): %{text} " + unidad_m + "<extra></extra>"))
    vista = dict(zoom=7.2)
    if comuna:
        vista = C.vista_comuna(comuna) | dict(capas_extra=C.resalta_comuna(comuna))
    fmap.update_layout(map=C.mapa(**vista), margin=dict(l=0, r=0, t=0, b=0), height=620)
    col_map, col_tab = st.columns([3, 2])
    C.grafico(fmap, f"mapa_{var_m}" + (f"_{comuna}" if comuna else ""), boton="resetViewMap", donde=col_map)
    tabla = dm[dm.Comuna == comuna] if comuna else dm
    if comuna and tabla.empty:
        # la estación más cercana al centro de la comuna, para no dejar al usuario sin referencia
        cen = C.vista_comuna(comuna)["center"]
        cerca = dm.iloc[((dm.lat - cen["lat"]) ** 2 + (dm.lon - cen["lon"]) ** 2).argmin()]
        col_tab.info(f"{comuna} no tiene estaciones que midan esta variable. La más cercana es "
                     f"**{cerca['Estación']}** ({cerca['Comuna']}).", icon=":material/location_off:")
        tabla = dm.loc[[cerca.name]]
    col_tab.dataframe(tabla[["Estación", "Comuna", "valor", "Hora", "Fuente"]]
                      .rename(columns={"valor": f"{Vm['nombre']} ({unidad_m})"}).sort_values(["Comuna", "Estación"]),
                      hide_index=True, width="stretch",
                      column_config={"Hora": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                     f"{Vm['nombre']} ({unidad_m})": st.column_config.NumberColumn(
                                         format=f"%.{Vm['decimales']}f")})
    titulo = (f"acumulado de las últimas {ventana_pp} h" if var_m == "precipitacion" else "última medición")
    col_tab.caption(f"{Vm['nombre']}: {titulo}. Líneas: límites comunales (BCN). "
                    f"Mapa base: {C.credito_mapa()}.")
