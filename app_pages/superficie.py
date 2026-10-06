"""Mapas de superficie: el viento de los modelos animado sobre la región (partículas con
leaflet-velocity) sobre un campo de fondo, y las rosas de viento de cada modelo contra lo observado.

El mapa recibe de una vez todas las horas del modelo elegido y las recorre en el navegador (barra de
tiempo y botón de reproducir), así que moverse en el tiempo no vuelve a ejecutar la página. El cuadro
del mapa tiene la misma proporción que la grilla y no se puede alejar ni desplazar fuera de ella."""
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import comun as C
import fuentes as F
from comun import DIAS, nombre_modelo

c = C.contexto()
sitio, ahora = c.sitio, c.ahora
ahora_h = pd.Timestamp(ahora).floor("h")

# escalas de color del fondo: (valor, color)
ESCALAS = {
    "viento": [(0, "#6271B7"), (7, "#39619F"), (14, "#4A94A9"), (22, "#4D8D7B"), (29, "#53A553"),
               (36, "#359F35"), (43, "#A79D51"), (54, "#9F7F3A"), (65, "#A16C5C"), (79, "#813A4E"),
               (101, "#AF5088"), (130, "#754A93")],
    "temperatura": [(-10, "#5E3C99"), (-5, "#3B4CC0"), (0, "#2C7BB6"), (5, "#00A6CA"), (10, "#00CCBC"),
                    (15, "#90EB9D"), (20, "#FFFF8C"), (25, "#F9D057"), (30, "#F29E2E"), (35, "#E76818"),
                    (40, "#D7191C")],
    "presion": ["#3B4CC0", "#6F92F3", "#AAC7FD", "#DDDDDD", "#F7B89C", "#E7745B", "#B40426"],  # rango del campo
    "precipitacion": [(0, "#00000000"), (0.1, "#A0D2FF"), (1, "#3C8CE6"), (3, "#1E50B4"), (6, "#8C3CC8"),
                      (10, "#DC28A0"), (20, "#FF0000")],
}
ESCALAS["rafaga"] = ESCALAS["viento"]
FONDOS = ["viento", "rafaga", "temperatura", "presion", "precipitacion"]
PARTICULAS = {"satelite": "rgba(255,255,255,.95)", "calles": "rgba(30,30,50,.9)"}
OPACIDAD = {"satelite": 0.6, "calles": 0.45}  # sobre las calles, más transparente para que se lean
LEAFLET = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist"
VELOCITY = "https://cdn.jsdelivr.net/npm/leaflet-velocity@2.1.4/dist"
# el cuadro va de centro a centro de las celdas de los extremos: ahí hay viento y fondo sin extrapolar
NORTE, SUR = float(F.GRILLA_LAT[0]), float(F.GRILLA_LAT[-1])
OESTE, ESTE = float(F.GRILLA_LON[0]), float(F.GRILLA_LON[-1])


def mercator(lat):
    return np.log(np.tan(np.pi / 4 + np.deg2rad(lat) / 2))


ASPECTO = np.deg2rad(ESTE - OESTE) / (mercator(NORTE) - mercator(SUR))  # ancho / alto del cuadro en pantalla


def rgba(hexa):
    h = hexa.lstrip("#")
    return [int(h[k:k + 2], 16) for k in (0, 2, 4)] + [int(h[6:8], 16) if len(h) == 8 else 255]


def escala_de(fondo, z):
    """La escala del fondo; la de presión se estira al rango del campo (cambia poco dentro de la región)."""
    if fondo != "presion":
        return ESCALAS[fondo]
    lo, hi = np.nanmin(z), np.nanmax(z)
    lo, hi = (990, 1035) if not np.isfinite(lo) else (np.floor(lo) - 1, np.ceil(hi) + 1)
    cols = ESCALAS["presion"]
    return [(round(lo + (hi - lo) * k / (len(cols) - 1), 1), h) for k, h in enumerate(cols)]


def leyenda(escala, unidad):
    lims = [v for v, _ in escala]
    pos = lambda v: 100 * (v - lims[0]) / (lims[-1] - lims[0])  # noqa: E731
    pasos = ", ".join(f"{h} {pos(v):.1f}%" for v, h in escala)
    marcas = "".join(f'<span style="position:absolute;left:{pos(v):.1f}%;transform:translateX(-50%)">{v:g}</span>'
                     for v in lims[::2])
    return (f'<div style="width:240px;font-size:11px"><div style="height:10px;border-radius:3px;'
            f'background:linear-gradient(90deg,{pasos})"></div>'
            f'<div style="position:relative;height:14px;margin-top:2px">{marcas}</div>'
            f'<div style="text-align:right">{unidad}</div></div>')


def lista(a, dec=1):
    """Arreglo -> lista con NaN como None, redondeada (el JSON pesa la mitad)."""
    a = np.round(np.asarray(a, float), dec)
    return [None if np.isnan(x) else float(x) for x in a.ravel()]


def dia_hora(t):
    return f"{DIAS[t.weekday()]} {t:%d/%m %H} h"


PAGINA = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="__LEAFLET__/leaflet.css"><link rel="stylesheet" href="__VELOCITY__/leaflet-velocity.min.css">
<script src="__LEAFLET__/leaflet.js"></script><script src="__VELOCITY__/leaflet-velocity.min.js"></script>
<style>
html,body{margin:0;overflow:hidden;font-family:"Source Sans Pro",sans-serif;color:#31333F}
#m{width:100%;aspect-ratio:__ASPECTO__;border-radius:8px;background:#e8e8e8}
.caja{background:rgba(20,24,32,.8);color:#fff;border-radius:8px;padding:6px 10px;font-size:12px}
.titulo{font-size:13px;font-weight:700}
.barra{display:flex;align-items:center;gap:10px;padding:10px 2px 4px}
.barra button{border:1px solid #d0d0d8;background:#fff;border-radius:8px;width:38px;height:32px;cursor:pointer;
  font-size:15px;color:#004090}
.barra input{flex:1;accent-color:#004090}
.barra span{min-width:150px;font-size:14px;text-align:right}
.leaflet-control-velocity{background:rgba(20,24,32,.8)!important;color:#fff!important;font-size:12px}
</style></head><body>
<div id="m"></div>
<div class="barra"><button id="play" title="Reproducir">&#9654;</button>
<input id="t" type="range" min="0" step="1"><span id="lbl"></span></div>
<script>
const D = __DATOS__;
const B = L.latLngBounds([[D.sur, D.oeste], [D.norte, D.este]]);
const m = L.map("m", {zoomSnap: 0, maxBounds: B, maxBoundsViscosity: 1});
L.tileLayer(D.teselas, {attribution: D.credito + " · límites: BCN · modelos: Open-Meteo", maxZoom: 13}).addTo(m);
function ajusta() {  // el cuadro de la grilla llena el mapa y no se puede alejar más
  m.setMinZoom(0); m.invalidateSize(); m.fitBounds(B, {animate: false}); m.setMinZoom(m.getZoom());
}
ajusta();
new ResizeObserver(ajusta).observe(document.getElementById("m"));

// fondo: interpolación bilineal entre los centros de la grilla, pintada en un canvas
const S = 24, W = (D.nx - 1) * S + 1, H = (D.ny - 1) * S + 1;
const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
const cx = cv.getContext("2d"), img = cx.createImageData(W, H);
function color(v) {
  const e = D.escala;
  if (v === null || isNaN(v)) return [0, 0, 0, 0];
  if (v <= e[0][0]) return e[0][1];
  for (let k = 1; k < e.length; k++) if (v <= e[k][0]) {
    const f = (v - e[k - 1][0]) / (e[k][0] - e[k - 1][0]);
    return e[k][1].map((c, j) => e[k - 1][1][j] + f * (c - e[k - 1][1][j]));
  }
  return e[e.length - 1][1];
}
function hex(v) {
  const c = color(v);
  return "#" + c.slice(0, 3).map(x => Math.round(x).toString(16).padStart(2, "0")).join("");
}
function pinta(i) {
  const z = D.fondo[i];
  for (let py = 0; py < H; py++) {
    const gy = py / S, y0 = Math.floor(gy), y1 = Math.min(y0 + 1, D.ny - 1), fy = gy - y0;
    for (let px = 0; px < W; px++) {
      const gx = px / S, x0 = Math.floor(gx), x1 = Math.min(x0 + 1, D.nx - 1), fx = gx - x0;
      const a = z[y0 * D.nx + x0], b = z[y0 * D.nx + x1], c = z[y1 * D.nx + x0], d = z[y1 * D.nx + x1];
      const v = (a === null || b === null || c === null || d === null) ? null :
        (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
      img.data.set(color(v), (py * W + px) * 4);
    }
  }
  cx.putImageData(img, 0, 0);
  return cv.toDataURL();
}
const fondo = L.imageOverlay(pinta(D.inicio), B, {opacity: D.opacidad}).addTo(m);

L.geoJSON(D.comunas, {style: {color: D.linea, weight: 1, opacity: .8, fill: true, fillOpacity: 0},
  onEachFeature: (f, l) => l.bindTooltip(f.properties.comuna, {sticky: true})}).addTo(m);

function viento(i) {
  const h = {parameterCategory: 2, nx: D.nx, ny: D.ny, lo1: D.oeste, la1: D.norte, lo2: D.este, la2: D.sur,
             dx: D.dx, dy: D.dy, refTime: D.horas[i]};
  return [{header: Object.assign({parameterNumber: 2}, h), data: D.u[i]},
          {header: Object.assign({parameterNumber: 3}, h), data: D.v[i]}];
}
const vel = D.u ? L.velocityLayer({data: viento(D.inicio), displayValues: true, velocityScale: 0.008,
  maxVelocity: 20, particleMultiplier: 1 / 250, lineWidth: 1.6, frameRate: 20, colorScale: [D.particula],
  displayOptions: {velocityType: "Viento", position: "bottomright", emptyString: "sin datos",
                   angleConvention: "meteoCW", speedUnit: "k/h", directionString: "Dirección",
                   speedString: "Velocidad"}}).addTo(m) : null;

const puntos = D.est.map(e => L.circleMarker([e.lat, e.lon], {radius: e.elegida ? 9 : 6,
  color: e.elegida ? "#FFD600" : "#fff", weight: e.elegida ? 3 : 1.5, fillColor: "#222", fillOpacity: .6})
  .bindTooltip("").addTo(m));
function estaciones(i) {
  D.est.forEach((e, k) => {
    const v = e.obs ? e.obs[i] : null, con = v !== null && v !== undefined;
    puntos[k].setStyle({fillColor: con ? hex(v) : "#222", fillOpacity: con ? 1 : .6});
    puntos[k].setTooltipContent("<b>" + e.nombre + "</b><br>" + e.comuna +
      (con ? "<br>observado: " + v.toFixed(D.dec) + " " + D.unidad + (e.dir && e.dir[i] ? " del " + e.dir[i] : "") : ""));
  });
}

const info = L.control({position: "topright"});
info.onAdd = () => L.DomUtil.create("div", "caja"); info.addTo(m);
const ley = L.control({position: "bottomleft"});
ley.onAdd = () => { const d = L.DomUtil.create("div", "caja"); d.innerHTML = D.leyenda; return d; }; ley.addTo(m);

const t = document.getElementById("t"), lbl = document.getElementById("lbl");
t.max = D.horas.length - 1; t.value = D.inicio;
function muestra(i) {
  fondo.setUrl(pinta(i));
  if (vel) vel.setData(viento(i));
  estaciones(i);
  const cuando = i < D.ahora ? "pasado" : i === D.ahora ? "ahora" : "pronóstico";
  info.getContainer().innerHTML = '<div class="titulo">' + D.titulo + "</div>" + D.horas[i] + " · " + cuando;
  lbl.textContent = D.horas[i];
}
muestra(D.inicio);
t.addEventListener("input", () => muestra(+t.value));
let reloj = null;
document.getElementById("play").addEventListener("click", e => {
  if (reloj) { clearInterval(reloj); reloj = null; e.target.innerHTML = "&#9654;"; return; }
  e.target.innerHTML = "&#10074;&#10074;";
  reloj = setInterval(() => { t.value = (+t.value + 1) % D.horas.length; muestra(+t.value); }, 900);
});
</script></body></html>"""


def html_mapa(datos):
    return (PAGINA.replace("__LEAFLET__", LEAFLET).replace("__VELOCITY__", VELOCITY)
            .replace("__ASPECTO__", f"{ASPECTO:.4f}").replace("__DATOS__", json.dumps(datos, ensure_ascii=False, default=float)))


tab_mapa, tab_rosa = st.tabs(["Viento y campos", "Rosas de viento"])

# ------------------------------------------------------------------ mapa
with tab_mapa:
    tabla, origen = C.grilla()
    if tabla is None:
        st.warning("La grilla de los mapas de superficie no está disponible (la GitHub Action todavía no la "
                   f"publica y Open-Meteo no respondió en vivo).  \nDetalle: `{origen[:160]}`",
                   icon=":material/cloud_off:")
    else:
        col_mapa, col_panel = st.columns([1, 1], gap="medium")
        with col_panel:
            fondo = st.radio("Fondo", FONDOS, key="fondo", horizontal=True,
                             format_func=lambda k: F.VARIABLES[k]["nombre"].split(" (")[0])
            modelo = st.selectbox("Modelo", ["mediana", *F.MODELOS], key="modelo_mapa",
                                  format_func=lambda m: "Mediana de los 7 modelos" if m == "mediana"
                                  else nombre_modelo(m))
            with st.container(horizontal=True, vertical_alignment="bottom"):
                C.elige_mapa_base()
                particulas = st.toggle("Partículas de viento", value=True, key="particulas")

        horas, z = F.cubo(tabla, fondo, modelo)
        _, uv = F.cubo(tabla, "uv", modelo)
        desde = int(np.searchsorted(horas, ahora_h - pd.Timedelta(hours=24)))
        horas, z, uv = horas[desde:], z[desde:], uv[:, desde:]
    if tabla is not None and not len(horas):
        st.info("La grilla publicada no cubre las próximas horas.", icon=":material/schedule:")
    elif tabla is not None:
        i_ahora = int(np.clip(np.searchsorted(horas, ahora_h), 0, len(horas) - 1))
        V = F.VARIABLES[fondo]
        unidad = "mm/h" if fondo == "precipitacion" else V["unidad"]
        escala = escala_de(fondo, z)

        # estaciones: lo observado en cada hora ya ocurrida, para pintarlas con la escala del fondo
        est, n_obs = [], 0
        pasadas = horas[horas <= ahora_h]
        for s in F.SITIOS:
            e = dict(lat=s["lat"], lon=s["lon"], nombre=s["nombre"], comuna=s["comuna"], elegida=s["id"] == sitio["id"])
            o = c.observado(s, fondo)
            if o is not None and len(pasadas):
                serie = o.reindex(horas)
                serie[horas > ahora_h] = np.nan
                if serie.notna().any():
                    e["obs"] = lista(serie.values, V["decimales"])
                    n_obs += 1
                    if fondo in ("viento", "rafaga") and "direccion" in s["vars"]:
                        d = c.observado(s, "direccion")
                        if d is not None:
                            e["dir"] = [None if pd.isna(x) else F.cardinal(x) for x in d.reindex(horas).values]
            est.append(e)

        b = C.BASES[C.base_actual()]
        nombre_m = "Mediana de los 7 modelos" if modelo == "mediana" else nombre_modelo(modelo)
        datos = dict(
            norte=NORTE, sur=SUR, oeste=OESTE, este=ESTE, nx=len(F.GRILLA_LON), ny=len(F.GRILLA_LAT), dx=0.2, dy=0.2,
            horas=[dia_hora(t) for t in horas], ahora=i_ahora, inicio=i_ahora,
            fondo=[lista(x) for x in z], escala=[[v, rgba(h)] for v, h in escala],
            u=[lista(x / 3.6) for x in uv[0]] if particulas else None,
            v=[lista(x / 3.6) for x in uv[1]] if particulas else None,
            est=est, unidad=unidad, dec=V["decimales"], leyenda=leyenda(escala, unidad),
            titulo=f"{V['nombre'].split(' (')[0]} · {nombre_m}", teselas=b["teselas"], credito=b["credito"],
            linea=b["linea"], particula=PARTICULAS[C.base_actual()], opacidad=OPACIDAD[C.base_actual()], comunas=C.COMUNAS)
        with col_mapa:
            st.iframe(html_mapa(datos))
        col_panel.caption(
            f"Fondo: {V['nombre'].lower()} ({unidad}) del modelo elegido, en una grilla de 0,2° (~20 km) "
            "interpolada. Partículas: el viento de 10 m del mismo modelo (pasa el cursor para ver velocidad y "
            "dirección). Mueve la barra bajo el mapa o dale ▶ para recorrer las horas, desde 24 h atrás hasta el "
            "fin del pronóstico. "
            + (f"En las horas pasadas, {n_obs} estaciones se pintan con lo que midieron, en la misma escala: si su "
               "color se parece al del fondo, el modelo acertó. " if n_obs else "")
            + f"En amarillo, el sitio elegido arriba. Grilla: {origen}.")

# ------------------------------------------------------------------ rosas de viento
SECTORES = 16
CALMA = 2  # km/h: por debajo, calma (sin dirección)
CLASES = [(CALMA, 10, "#C6DBEF"), (10, 20, "#6BAED6"), (20, 30, "#2171B5"), (30, 45, "#6A51A3"),
          (45, np.inf, "#B5323C")]
CARDINALES = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def rosa(vel, dirc):
    """(frecuencias % [clase × sector], n horas, % calma o variable) de una serie de viento. Las horas
    sin dirección (calma, o viento variable «VRB» del METAR) cuentan en n pero no en ningún sector."""
    par = pd.concat([vel, dirc], axis=1, join="inner")
    par = par[par.iloc[:, 0].notna()]
    n = len(par)
    if not n:
        return None, 0, np.nan
    v, d = par.iloc[:, 0].values, par.iloc[:, 1].values
    sin_dir = (v < CALMA) | np.isnan(d)
    sector = ((np.nan_to_num(d) + 180 / SECTORES) // (360 / SECTORES)).astype(int) % SECTORES
    frec = np.array([[100 * (~sin_dir & (v >= lo) & (v < hi) & (sector == k)).sum() / n for k in range(SECTORES)]
                     for lo, hi, _ in CLASES])
    return frec, n, 100 * sin_dir.sum() / n


with tab_rosa:
    periodo = st.segmented_control("Período", ["pasado", "futuro"], default="pasado", required=True,
                                   key="periodo_rosa",
                                   format_func=lambda p: "Días ya ocurridos (contra lo observado)" if p == "pasado"
                                   else "Próximos días (pronóstico)")
    vel_m, dir_m = c.det_var("viento"), c.det_var("direccion")
    modelos = [m for m in c.modelos if m in vel_m and m in dir_m]
    if periodo == "pasado":
        desde, hasta = c.t0, ahora_h
    else:
        desde, hasta = ahora_h + pd.Timedelta(hours=1), c.t_fin
    en_ventana = lambda s: s[(s.index >= desde) & (s.index <= hasta)]  # noqa: E731

    obs_v = obs_d = None
    if periodo == "pasado" and "direccion" in sitio["vars"]:
        obs_v, obs_d = c.observado(sitio, "viento"), c.observado(sitio, "direccion")
        if obs_v is not None and obs_d is not None:
            obs_v, obs_d = en_ventana(obs_v), en_ventana(obs_d)
    paneles = []
    if obs_v is not None and obs_d is not None and len(obs_d.dropna()):
        # los modelos se comparan en las mismas horas en que hubo observación
        horas_obs = obs_v.dropna().index
        paneles.append(("Observado (METAR)", *rosa(obs_v, obs_d)))
        for m in modelos:
            paneles.append((nombre_modelo(m), *rosa(vel_m[m].reindex(horas_obs), dir_m[m].reindex(horas_obs))))
    else:
        if periodo == "pasado":
            st.info(f"{sitio['nombre']} no mide la dirección del viento: en la región solo la informa el METAR "
                    "del aeropuerto La Araucanía. Se muestran las rosas de los modelos; elige «Aeropuerto La "
                    "Araucanía» en «Sitio» para compararlas con lo observado.", icon=":material/explore_off:")
        for m in modelos:
            paneles.append((nombre_modelo(m), *rosa(en_ventana(vel_m[m]), en_ventana(dir_m[m]))))
    paneles = [p for p in paneles if p[1] is not None]

    if not paneles:
        st.info("Sin datos de viento en este período.", icon=":material/air:")
    else:
        cols = 4
        filas = -(-len(paneles) // cols)
        fig = make_subplots(rows=filas, cols=cols, specs=[[{"type": "polar"}] * cols] * filas,
                            subplot_titles=[f"{n}<br><sup>{h} h · sin dirección {cal:.0f} %</sup>" for n, _, h, cal in paneles],
                            vertical_spacing=0.12 / filas, horizontal_spacing=0.06)
        r_max = max(f.sum(axis=0).max() for _, f, _, _ in paneles)
        for k, (nombre, frec, n, calma) in enumerate(paneles):
            fila, col = k // cols + 1, k % cols + 1
            for (lo, hi, color), fr in zip(CLASES, frec):
                etiqueta = f"{lo}–{hi:.0f} km/h" if np.isfinite(hi) else f"> {lo} km/h"
                fig.add_trace(go.Barpolar(r=fr, theta=CARDINALES, name=etiqueta, marker_color=color,
                                          marker_line=dict(color="white", width=.5), legendgroup=etiqueta,
                                          showlegend=k == 0,
                                          hovertemplate=f"{nombre}<br>%{{theta}} · {etiqueta}: %{{r:.1f}} %"
                                                        "<extra></extra>"), row=fila, col=col)
        fig.update_polars(radialaxis=dict(range=[0, r_max * 1.05], ticksuffix=" %", tickfont=dict(size=9, color="#777"),
                                          angle=45, tickangle=45, nticks=4, showline=False),
                          angularaxis=dict(direction="clockwise", rotation=90, tickfont=dict(size=10)),
                          bargap=0.05)
        fig.update_annotations(font=dict(size=14), yshift=20)
        fig.update_layout(height=340 * filas + 40, barmode="stack", margin=dict(l=30, r=30, t=50, b=60),
                          legend=dict(orientation="h", y=-0.02, yanchor="top", x=0.5, xanchor="center",
                                      title="Velocidad: "))
        texto_p = (f"del {DIAS[desde.weekday()]} {desde:%d/%m %H} h al {DIAS[hasta.weekday()]} {hasta:%d/%m %H} h")
        st.markdown(f"**Rosas de viento en {sitio['nombre']}** ({sitio['comuna']}), {texto_p}")
        C.grafico(fig, f"rosas_{periodo}", key="rosas")

        # resumen: dirección predominante, velocidad media y, contra lo observado, el error de dirección
        err = pd.DataFrame()
        if paneles[0][0].startswith("Observado"):
            err = F.verificacion(dir_m[modelos], obs_d, "direccion", hasta).set_index("modelo") if modelos else err
        resumen = []
        for nombre, frec, n, calma in paneles:
            m = next((x for x in modelos if nombre_modelo(x) == nombre), None)
            v = (obs_v if m is None else en_ventana(vel_m[m])).dropna()
            if m is not None and paneles[0][0].startswith("Observado"):
                v = vel_m[m].reindex(horas_obs).dropna()
            resumen.append({"": nombre, "Dirección predominante": CARDINALES[int(frec.sum(axis=0).argmax())],
                            "Velocidad media (km/h)": v.mean(), "Calma o variable (%)": calma, "Horas": n,
                            "Error medio de dirección (°)": err["mae"].get(m, np.nan) if m and not err.empty
                            else np.nan})
        resumen = pd.DataFrame(resumen)
        if resumen["Error medio de dirección (°)"].isna().all():
            resumen = resumen.drop(columns="Error medio de dirección (°)")
        st.dataframe(resumen, hide_index=True, width="stretch",
                     column_config={k: st.column_config.NumberColumn(format="%.0f") for k in resumen.columns[2:]})
        st.caption("Cada rosa dice de dónde viene el viento y con qué frecuencia (% de las horas), con la velocidad "
                   f"en colores. Calma o variable: menos de {CALMA} km/h, o viento que el METAR informa como variable (VRB), "
                   "sin dirección definida; los modelos siempre dan una. Todas las rosas usan la misma escala. "
                   "Error medio de dirección: diferencia angular media con el METAR en las mismas horas.")
