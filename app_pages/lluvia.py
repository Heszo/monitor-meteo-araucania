"""Lluvia: mapa del acumulado observado, histograma horario, acumulado y tarjetas de 6 h."""
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

ESCALA_LLUVIA = [(25, "#FFF3B0"), (50, "#B8E186"), (75, "#41B6C4"), (100, "#2C7FB8"), (150, "#8856A7"),
                 (np.inf, "#E7298A")]
NIVELES_6H = [(10, "débil", "#9DBFDD"), (25, "moderada", "#6FA3D2"), (np.inf, "fuerte", "#1F4E8C")]
AZUL = "#1F5A96"

lluvia_obs, av = C.vipnet_seguro("precipitacion")
avisos.extend(av)
activas = [s for s in F.SITIOS if s["id"] in lluvia_obs]
ahora_h = pd.Timestamp(ahora).floor("h")
ini = t0
obs_ll = {i: o[o.index > ini] for i, o in lluvia_obs.items()}
tot = {i: float(o.sum()) for i, o in obs_ll.items()}
P = recorta(pron["pp"])
P = P[P.index > ini] if P is not None else None
R = pron["raf6h"]

st.caption(f"Lluvia observada desde el {DIAS[ini.weekday()]} {ini:%d/%m %H:%M} (inicio de la ventana; "
           f"se cambia con «Días hacia atrás») y pronóstico del super-ensamble en {sitio['nombre']}.")
c = st.columns(4)
rango = lambda v: "—" if not v else (f"{min(v):.0f}–{max(v):.0f}" if len(v) > 1 else f"{v[0]:.0f}")  # noqa: E731
c[0].metric("Observado* región (mm)", rango([tot[s["id"]] for s in activas]),
            help="Mínimo y máximo entre las estaciones de la región.")
c[1].metric(f"Observado* comuna {sitio['comuna']} (mm)",
            rango([tot[s["id"]] for s in activas if s["comuna"] == sitio["comuna"]]))
c[2].metric(f"Observado* {sitio['nombre']} (mm)",
            f"{tot[sitio['id']]:.0f}" if sitio["id"] in tot else "—")
if P is not None and not P.empty:
    resto = P[P.index > ahora_h].sum().values
    r10, r50, r90 = np.percentile(resto, [10, 50, 90])
    c[3].metric(f"Faltan desde las {ahora_h:%H} h (mm)", f"{r50:.0f}", f"rango {r10:.0f}–{r90:.0f}",
                delta_color="off", help=f"Lluvia pronosticada de aquí al fin del horizonte ({futuro} días).")

# La estación elegida aquí es el «Sitio» de toda la app: al cambiarla cambian también el pronóstico y las
# tarjetas de arriba. Se elige pinchando el mapa en cualquier parte (la estación más cercana o, en «Por comuna»,
# la comuna pinchada) o en el botón de la estación, con buscador.
# Si el sitio no mide lluvia, no se destaca ninguna estación: se muestra su comuna.
elegida = sitio["id"] if sitio["id"] in lluvia_obs else None
CON_LLUVIA = [s["id"] for s in activas]


def mas_cercana(lat, lon, ids):
    k = np.cos(np.radians(lat))  # un grado de longitud mide menos que uno de latitud
    return min(ids, key=lambda i: (F.SITIO[i]["lat"] - lat) ** 2 + ((F.SITIO[i]["lon"] - lon) * k) ** 2)


def al_pinchar():
    """Callback del mapa (corre antes del script, así los controles de arriba ya ven el sitio nuevo). Una
    estación pinchada pasa a ser el sitio; un punto de la grilla invisible ("@comuna|lat|lon") elige la estación
    con lluvia más cercana, dentro de la comuna pinchada si la vista es «Por comuna»."""
    puntos = st.session_state["mapa_lluvia"].selection.points
    if not puntos:
        return
    d = puntos[0].get("customdata")
    d = d[0] if isinstance(d, list) else d
    if d in F.SITIO:
        st.session_state["sitio"] = d
    elif isinstance(d, str) and d.startswith("@"):
        comuna_p, la, lo = d[1:].split("|")
        ids = CON_LLUVIA
        if st.session_state.get("lluvia_vista") == "Por comuna":
            ids = [i for i in CON_LLUVIA if F.SITIO[i]["comuna"] == comuna_p] or CON_LLUVIA
            if ids is CON_LLUVIA:
                st.toast(f"{comuna_p} no tiene estaciones de lluvia: se eligió la más cercana.")
        st.session_state["sitio"] = mas_cercana(float(la), float(lo), ids)


def al_elegir():
    if st.session_state["lluvia_estacion"]:
        st.session_state["sitio"] = st.session_state["lluvia_estacion"]


def al_elegir_comuna():
    """Otra comuna: el sitio pasa a ser su primera estación con lluvia."""
    st.session_state["sitio"] = next(s["id"] for s in activas if s["comuna"] == st.session_state["lluvia_comuna"])


# La vista se lee aquí (el control se dibuja más abajo, sobre los gráficos) porque el mapa también depende de
# ella. La comuna en foco es la de la estación elegida (o la del sitio, si no mide lluvia).
vista = (st.session_state.get("lluvia_vista") or "Estación") if elegida else "Por comuna"
destacada = elegida if vista == "Estación" else None  # None: se destaca el promedio de la comuna
com = sitio["comuna"]
COLOR_COMUNA = "#E6A100"
COLOR_ESTACION = "#B5179E"
ids_com = [s["id"] for s in activas if s["comuna"] == com]
unidades = {f"comuna {com}": (ids_com, COLOR_COMUNA)} if ids_com else {}


col_mapa, col_graf = st.columns([5, 7], gap="medium")
with col_mapa:
    st.markdown("**Acumulado observado\\*** · pincha el mapa o elige abajo")
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        # dos selectores: la comuna (la del sitio) y, dentro de ella, la estación; la estación vuelve a
        # «Selecciona» después de elegir, porque ya se ve en el mapa y en «Sitio»
        comunas = sorted({s["comuna"] for s in activas})
        st.session_state["lluvia_comuna"] = com if com in comunas else None
        st.selectbox("Comuna", comunas, key="lluvia_comuna", on_change=al_elegir_comuna, placeholder="Comuna",
                     width=170, help="Al cambiar de comuna, el sitio pasa a ser su primera estación con lluvia.")
        st.session_state["lluvia_estacion"] = None
        st.selectbox("Estación", sorted(ids_com, key=lambda i: F.SITIO[i]["nombre"]), key="lluvia_estacion",
                     format_func=lambda i: F.SITIO[i]["nombre"], on_change=al_elegir, placeholder="Selecciona",
                     width=200, help=f"Estaciones con lluvia de la comuna {com}.")
        C.elige_mapa_base()
    mm = [tot[s["id"]] for s in activas]
    ids = [s["id"] for s in activas]
    lat, lon = [s["lat"] for s in activas], [s["lon"] for s in activas]
    fmap = go.Figure()
    # grilla invisible para pinchar en cualquier parte; sin puntos junto a las estaciones, para no taparlas
    G = C.grilla_comunas()
    lejos = np.min([(G.lat - F.SITIO[i]["lat"]) ** 2 + (G.lon - F.SITIO[i]["lon"]) ** 2 for i in ids], axis=0) > .03 ** 2
    G = G[lejos]
    fmap.add_trace(go.Scattermap(lat=G.lat, lon=G.lon, mode="markers", hovertext=G.comuna,
                                 hovertemplate="%{hovertext}<extra></extra>",
                                 marker=dict(size=7, color="rgba(255,255,255,0.01)"),
                                 customdata=[f"@{c}|{la:.3f}|{lo:.3f}" for c, la, lo in zip(G.comuna, G.lat, G.lon)]))
    if elegida:  # halo de la estación elegida, del color del texto del mapa base (se ve en ambos)
        fmap.add_trace(go.Scattermap(lat=[F.SITIO[elegida]["lat"]], lon=[F.SITIO[elegida]["lon"]], mode="markers",
                                     marker=dict(size=14, color=C.texto_mapa()), customdata=[elegida],
                                     hoverinfo="none"))
    fmap.add_trace(go.Scattermap(
        lat=lat, lon=lon, mode="markers+text", customdata=ids,
        marker=dict(size=10, color=[next(cc for lim, cc in ESCALA_LLUVIA if v < lim) for v in mm]),
        text=[f"{v:.0f}" for v in mm], textposition="middle right", textfont=dict(color=C.texto_mapa(), size=10),
        hovertext=[f"{s['nombre']} ({s['comuna']})<br>{v:.0f} mm" for s, v in zip(activas, mm)],
        hovertemplate="%{hovertext}<extra></extra>"))
    # al pinchar, Plotly atenúa los puntos no seleccionados y les borra la etiqueta: aquí todos se ven igual
    fmap.update_traces(unselected=dict(marker=dict(opacity=1)), selected=dict(marker=dict(opacity=1)))
    capas = C.resalta_comuna(com) if vista == "Por comuna" else []
    fmap.update_layout(map=C.mapa(zoom=6.9, capas_extra=capas), margin=dict(l=0, r=0, t=0, b=0), height=520,
                       showlegend=False, clickmode="event+select")
    C.grafico(fmap, "lluvia_mapa", key="mapa_lluvia", boton="resetViewMap", on_select=al_pinchar,
              selection_mode="points")
    st.caption(f"Mapa base: {C.credito_mapa()}.")
    if not elegida:
        st.caption(f":material/info: {sitio['nombre']} no mide lluvia: se muestra su comuna ({com}).")

# promedio de la comuna y, encima, la estación elegida (en «Estación», el promedio solo si la comuna tiene más
# de una estación: con una sola repetiría la misma serie)
curvas = [(f"{u} (promedio {len(ids)} est.)" if len(ids) > 1 else f"{u} ({F.SITIO[ids[0]]['nombre']})", ids, col)
          for u, (ids, col) in unidades.items()]
curvas_prom = [cv for cv in curvas if not destacada or len(cv[1]) > 1]


def ensamble_unidades():
    """({unidad: miembros horarios}, hora de la copia): el super-ensamble de cada unidad (la comuna),
    promedio miembro a miembro de la lluvia pronosticada en sus estaciones. Sale de la copia publicada (trae
    todas las estaciones); sin ella, {}."""
    try:
        generado, pub = C.carga_publicados()
    except Exception:  # noqa: BLE001
        return {}, None
    out = {}
    for u, (ids, _) in unidades.items():
        pps = [pub[i]["pp"] for i in ids if i in pub and pub[i]["pp"] is not None]
        if pps:
            m = recorta(sum(pps) / len(pps))
            out[u] = m[m.index > ini]
    return out, generado.tz_convert(F.ZONA)


def tenue(hexa, a):
    """'#RRGGBB' -> 'rgba(r,g,b,a)' para la banda de la comuna."""
    return f"rgba({int(hexa[1:3], 16)},{int(hexa[3:5], 16)},{int(hexa[5:7], 16)},{a})"


with col_graf:
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.segmented_control("Ver", ["Estación", "Por comuna"], default="Estación", required=True,
                             key="lluvia_vista", label_visibility="collapsed", disabled=not elegida,
                             help="«Por comuna»: las estaciones de la comuna de la estación elegida y su "
                                  "super-ensamble.")
    PG, PG_HORA = ({}, None) if destacada else ensamble_unidades()
    if P is None or P.empty:
        st.warning("El super-ensamble no respondió; los datos se renuevan solos cada hora.")
    else:
        q = F.percentiles(P)
        fa = go.Figure()
        fa.add_trace(go.Scatter(x=q.index, y=q.p90, line=dict(width=0, shape="vh"), showlegend=False,
                                hoverinfo="skip"))
        fa.add_trace(go.Scatter(x=q.index, y=q.p10, line=dict(width=0, shape="vh"), fill="tonexty",
                                fillcolor="rgba(157,191,221,.55)", name="pronóstico p10–p90", hoverinfo="skip"))
        fa.add_trace(go.Bar(x=q.index - pd.Timedelta(minutes=30), y=q.p50, width=3.6e6 * 0.85,
                            marker_color=AZUL, opacity=.85, name=f"pronóstico {sitio['nombre']} (mediana)"))
        for g, m in PG.items():
            qg = F.percentiles(m)
            fa.add_trace(go.Scatter(x=qg.index - pd.Timedelta(minutes=30), y=qg.p50, mode="lines",
                                    line=dict(color=unidades[g][1], width=1.6, dash="dash"),
                                    name=f"pronóstico {g} (mediana)"))
        for nombre, ids, colg in curvas_prom:
            tab = pd.concat([obs_ll[i] for i in ids], axis=1, sort=True)
            fa.add_trace(go.Scatter(x=tab.index - pd.Timedelta(minutes=30), y=tab.mean(axis=1), mode="lines",
                                    line=dict(color=colg, width=1.4 if destacada else 2.4,
                                              dash="dot" if destacada else "solid"),
                                    opacity=.8 if destacada else 1, name=f"observado* {nombre}"))
        if destacada:
            o = obs_ll[destacada]
            fa.add_trace(go.Scatter(x=o.index - pd.Timedelta(minutes=30), y=o, mode="lines",
                                    line=dict(color=COLOR_ESTACION, width=3.2),
                                    name=f"observado* {F.SITIO[destacada]['nombre']}"))
        linea_ahora(fa, ahora_h)
        fa.update_layout(title="Precipitación por hora (mm)", height=360, margin=dict(l=10, r=10, t=40, b=10),
                         bargap=0, legend=dict(orientation="h", y=-.3, yanchor="top"), hovermode="x unified")
        fa.update_xaxes(**EJE_T)
        C.grafico(fa, "lluvia_horaria", key="hist_lluvia")

        A = F.percentiles(P.fillna(0).cumsum())
        fb = go.Figure()
        fb.add_trace(go.Scatter(x=np.r_[A.index, A.index[::-1]], y=np.r_[A.p90, A.p10[::-1]], fill="toself",
                                fillcolor="rgba(157,191,221,.55)", line=dict(width=0),
                                name="pronóstico p10–p90", hoverinfo="skip"))
        fb.add_trace(go.Scatter(x=A.index, y=A.p50, line=dict(color=AZUL, width=3),
                                name=f"pronóstico {sitio['nombre']} (mediana)"))
        totales = [f"{sitio['nombre']} {A.p50.iloc[-1]:.0f} mm ({A.p10.iloc[-1]:.0f}–{A.p90.iloc[-1]:.0f})"]
        for g, m in PG.items():  # ensamble de la comuna: banda tenue y mediana a trazos
            Ag = F.percentiles(m.fillna(0).cumsum())
            colg = unidades[g][1]
            fb.add_trace(go.Scatter(x=np.r_[Ag.index, Ag.index[::-1]], y=np.r_[Ag.p90, Ag.p10[::-1]],
                                    fill="toself", fillcolor=tenue(colg, .13), line=dict(width=0),
                                    legendgroup=g, showlegend=False, hoverinfo="skip"))
            fb.add_trace(go.Scatter(x=Ag.index, y=Ag.p50, line=dict(color=colg, width=2, dash="dash"),
                                    legendgroup=g, name=f"pronóstico {g} (mediana, p10–p90)"))
            totales.append(f"{g} {Ag.p50.iloc[-1]:.0f} ({Ag.p10.iloc[-1]:.0f}–{Ag.p90.iloc[-1]:.0f})")
        for nombre, ids, colg in curvas:
            for i in ids:
                o = obs_ll[i]
                fb.add_trace(go.Scatter(x=[ini, *o.index], y=[0, *o.cumsum()], name=F.SITIO[i]["nombre"],
                                        line=dict(color=COLOR_ESTACION if i == destacada else colg,
                                                  width=3.2 if i == destacada else 1.2),
                                        opacity=1 if i == destacada else .3, showlegend=False))
            if not destacada:  # acumulado promedio de la comuna
                m = pd.concat([obs_ll[i] for i in ids], axis=1, sort=True).mean(axis=1).fillna(0).cumsum()
                fb.add_trace(go.Scatter(x=[ini, *m.index], y=[0, *m], line=dict(color=colg, width=3.2),
                                        name=f"observado* {nombre}"))
        # la estación destacada encima de las demás
        fb.data = sorted(fb.data, key=lambda t: t.name == F.SITIO.get(destacada, {}).get("nombre"))
        linea_ahora(fb, ahora_h)
        fb.update_layout(title=dict(text="Acumulado desde el inicio (mm)",
                                    subtitle=dict(text="pronóstico total: " + " · ".join(totales))),
                         height=380 if not destacada else 290, margin=dict(l=10, r=10, t=60, b=10),
                         showlegend=not destacada, legend=dict(orientation="h", y=-.3, yanchor="top"),
                         hovermode="x unified")
        fb.update_xaxes(**EJE_T)
        C.grafico(fb, "lluvia_acumulada", key="acum_lluvia")
        if PG:
            st.caption(f"Ensamble de la comuna: promedio, miembro a "
                       f"miembro, del super-ensamble en sus estaciones (copia publicada a las "
                       f"{PG_HORA:%d/%m %H:%M}). El de {sitio['nombre']}: {origen_pron or 'no disponible'}.")

if P is not None and not P.empty:
    st.markdown("**Lluvia esperada cada 6 horas** (mediana del pronóstico; rango p10–p90)")
    html = ['<div style="display:flex;flex-wrap:wrap;gap:8px">']
    b0 = max(ini, ahora_h - pd.Timedelta(hours=24)).floor("6h")  # 24 h de pasado + todo el pronóstico
    fin = P.index.max()
    while b0 < fin:
        b1 = b0 + pd.Timedelta(hours=6)
        m = (P.index > b0) & (P.index <= b1)
        q10, q50, q90 = np.percentile(P[m].sum().values, [10, 50, 90])
        rf = None
        if R is not None and b0 in R.index:
            rf = float(R.loc[b0])
        pasado_b, actual = b1 <= ahora_h, b0 <= ahora_h < b1
        color = next(cc for lim, _, cc in NIVELES_6H if q50 < lim)
        obs_txt = ""
        if pasado_b:
            v = [float(lluvia_obs[i][(lluvia_obs[i].index > b0) & (lluvia_obs[i].index <= b1)].sum())
                 for i in ids_com]
            if v:
                obs_txt = (f'<span style="color:{COLOR_COMUNA}">{com} {min(v):.0f}'
                           f'{"–%.0f" % max(v) if round(min(v)) != round(max(v)) else ""}</span>')
        fin_h = "24" if b1.hour == 0 else f"{b1:%H}"
        html.append(
            f'<div style="flex:1 1 92px;max-width:130px;border:{"2px solid " + ROJO if actual else "1px solid #D6D2CA"};'
            f'border-radius:10px;padding:8px 6px;text-align:center;opacity:{.55 if pasado_b else 1};'
            f'font-family:sans-serif">'
            f'<div style="font-weight:700">{DIAS[b0.weekday()].capitalize()} {b0.day}</div>'
            f'<div style="font-size:12px;color:#666">{b0:%H}–{fin_h} h</div>'
            f'<div style="font-size:26px;font-weight:800;color:{color}">{q50:.0f}</div>'
            f'<div style="font-size:11px;color:#666">mm · {q10:.0f}–{q90:.0f}</div>'
            f'<div style="font-size:11px;margin-top:4px;font-weight:700">{obs_txt}</div>'
            + (f'<div style="font-size:11px;color:#5B4B8A">ráfaga {rf:.0f} km/h</div>'
               if rf is not None and not np.isnan(rf) and not pasado_b else "")
            + (f"<div style='font-size:10px;color:white;background:{ROJO};border-radius:4px;margin-top:4px'>"
               "AHORA</div>" if actual else "")
            + "</div>")
        b0 = b1
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption("Ráfaga: mediana del máximo del bloque entre los miembros que la informan (GEFS e IFS-ENS). "
               "Intensidad descriptiva (débil < 10, moderada 10–25, fuerte > 25 mm en 6 h): no reemplaza los "
               "avisos de SENAPRED y la DMC. * Observado: VIPNet (DGA/MOP), datos preliminares.")
