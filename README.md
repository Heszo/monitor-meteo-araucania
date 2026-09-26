# MetGeo Araucanía

Monitor meteorológico de la Región de La Araucanía.

**App en línea: [metgeo-araucania.streamlit.app](https://metgeo-araucania.streamlit.app/)** ·
por Bruno Herrera · MetGeo Spa ([github.com/Heszo](https://github.com/Heszo))

App Streamlit que junta en un solo lugar lo **observado** en todas las estaciones públicas de La Araucanía
y lo **pronosticado** por 7 modelos globales y un super-ensamble de 143 miembros, para lluvia, temperatura,
humedad, viento, ráfagas, dirección del viento y presión. Sirve para ver qué viene y, sobre todo,
para **comparar modelos entre sí y contra la observación**. Es la versión regional de
[MetGeo Concepción](https://github.com/Heszo/monitor-meteo-concepcion): mismos modelos y vistas, otra red.

Se actualiza sola y no necesita claves ni base de datos: las observaciones se descargan al abrir la app
(caché de 15 minutos) y los pronósticos los publica cada hora una GitHub Action (ver más abajo).

## Vistas

| Vista | Qué muestra |
|---|---|
| **Home** | Portada: qué es el proyecto, las condiciones de ahora, lo que viene en 24 h y los próximos 3 días, accesos a cada vista, cómo funciona, fuentes y advertencias. |
| **Comparar modelos** | Una variable a la vez en el sitio elegido: los 7 modelos, la banda p10–p90 del super-ensamble y lo observado. Debajo, una tabla con sesgo, MAE, RMSE y correlación de cada modelo en las horas ya ocurridas. La lluvia se dibuja como histograma horario. |
| **Lluvia** | Mapa satelital con el acumulado observado por estación, histograma horario (mediana y p10–p90 del ensamble contra el observado por grupo o estación), acumulado y tarjetas de lluvia esperada cada 6 h con ráfaga. |
| **Meteograma** | Las 6 variables apiladas en un mismo eje de tiempo, para un modelo o la mediana de los modelos elegidos. |
| **Mapa de estaciones** | Última medición (o lluvia acumulada en las últimas N horas) de cada estación sobre imagen satelital. |

Los modelos se consultan en las coordenadas del sitio elegido arriba, en «Sitio» (se puede escribir
para buscar entre las 72 estaciones).

## La red: 72 sitios

- **71 estaciones VIPNet** (DGA/MOP): todas las de la región que hoy entregan datos. Miden cada 30 min
  lluvia (66), temperatura (55), humedad (46) y viento (10).
- **METAR SCQP** (aeropuerto La Araucanía, Freire): la única estación de la región que publica METAR,
  y la única fuente pública de ráfagas, dirección del viento y presión. Maquehue (SCTC) ya no informa.

Se agrupan por longitud en **costa** (16, al oeste de 72,85° O, con la cordillera de Nahuelbuta),
**valle** (29) y **cordillera** (27, al este de 72,1° O).

Control de calidad (verificado el 26/09/2026 con una semana de datos):
- Se descartan los valores fuera de rango físico (lluvia < 0 o > 40 mm en 30 min, temperatura fuera de
  −25…45 °C, etc.): por ejemplo −18 mm en Villarrica, 82 mm en media hora en Llafenco o 560 °C en Malalcahuello.
- No se usan los sensores que esa semana informaban datos fijos o nulos: pluviómetros en 0 mientras
  alrededor caían ~150 mm (Tranamán, Pailahueque, Quitratúe, Chanlelfu, Río Truful, Río Cruces ante
  Loncoche), humedad fija en 100 % (Río Huichahue, Puesco, Lago Caburgua, Gorbea, Licán Ray) o en
  35–47 % con lluvia (Río Truful) y viento fijo en 81 km/h (Quitratúe). Esas estaciones siguen en la
  red con sus demás variables; Río Cruces ante Loncoche, que solo mide lluvia, queda fuera.
- Río Cautín en Almagro y Río Trafampulli en Rinconada están en el catálogo pero no entregan datos.

## Fuentes (todas públicas)

| Fuente | Variables | Cobertura |
|---|---|---|
| [VIPNet](https://vipnet.mop.gob.cl) (DGA/MOP) | lluvia (66 estaciones), temperatura (55), humedad (46), viento (10) | toda la región, cada 30 min |
| [METAR SCQP](https://aviationweather.gov/data/api/) (aeropuerto La Araucanía, NOAA Aviation Weather Center) | temperatura, humedad, viento, ráfaga, dirección, presión QNH | aeropuerto, cada hora |
| [Open-Meteo Forecast](https://open-meteo.com/en/docs) | GFS, IFS, ICON, GEM, GSM, UM, ARPEGE | 1–7 días atrás y 1–7 días hacia adelante |
| [Open-Meteo Ensemble](https://open-meteo.com/en/docs/ensemble-api) | GEFS (31) + IFS-ENS (51) + ICON-EPS (40) + GEPS (21) | ídem |
| Esri World Imagery | imagen satelital de los mapas y de la portada | — |

Advertencias:
- Observaciones preliminares, sin control de calidad oficial (solo el filtro descrito arriba).
- El viento de VIPNet es la media horaria de lecturas instantáneas cada 30 min: es más ruidoso que el del METAR.
- Los METAR informan ráfaga solo cuando es significativa.
- Los días pasados de Open-Meteo son pronósticos de corto plazo de corridas recientes, no reanálisis;
  la verificación compara un punto de grilla con una estación, así que incluye error de representatividad.
- El super-ensamble se calcula por celdas de 0,5° (ver abajo): estaciones cercanas comparten la misma banda.
- Es una herramienta de divulgación: no reemplaza los avisos de SENAPRED ni de la DMC.
- Open-Meteo es gratuito para uso no comercial.

## Cómo se actualizan los pronósticos

Open-Meteo gratuito limita las consultas por dirección IP (5000 por hora, 10 000 por día) y la IP de
Streamlit Community Cloud es compartida con muchas otras apps: consultado desde ahí suele responder
`429 Too Many Requests`. Por eso:

1. La GitHub Action [`pronosticos.yml`](.github/workflows/pronosticos.yml) corre cada hora (minuto 17),
   ejecuta `actualiza_pronosticos.py` (7 días atrás y 7 adelante) y publica 4 archivos parquet más
   `meta.json` en la rama [`datos`](../../tree/datos). La rama se reescribe en cada corrida, sin
   historial, así el repositorio no crece.
2. La app lee esa copia. Si falta o tiene más de 3 horas, consulta Open-Meteo en vivo (con reintentos);
   si tampoco responde, muestra un aviso y sigue mostrando las observaciones.

Con 72 sitios hay que cuidar la cuota. Open-Meteo cuenta cada miembro del ensamble como una variable,
así que el super-ensamble de un sitio (143 miembros × 6 variables × 14 días) pesa unas 85 consultas:
pedirlo en los 72 sitios agota el límite horario en una sola corrida. Por eso:

- Los **7 modelos** se piden en las coordenadas de **cada estación** (~5 consultas por sitio).
- El **super-ensamble** se pide una vez por **celda de 0,5°** (el tamaño de sus grillas), en la estación
  más cercana al centro de la celda: 19 nodos en vez de 72 (`NODO` en `fuentes.py`).
- Open-Meteo acepta varias coordenadas en una misma consulta: se piden lotes de 8 puntos.

Una corrida tarda unos 3 minutos: los lotes del ensamble van de a uno, separados por un minuto, para
no pasar el límite de 600 consultas por minuto.

Para forzar una actualización: pestaña *Actions* → *Actualizar pronósticos* → *Run workflow*.
GitHub pausa las Actions programadas de un repositorio público tras 60 días sin actividad; si pasa,
basta reactivarla desde la misma pestaña.

## Estructura

```
app.py                     punto de entrada: st.App que mantiene la caché caliente
streamlit_app.py           navegación (st.navigation), controles y encabezado
app_pages/                 una página por vista: presentación, comparar, lluvia, meteograma, mapa
comun.py                   cargas con caché y utilidades compartidas por las páginas
fuentes.py                 descarga y ordena los datos; catálogo de variables, modelos, estaciones y nodos
actualiza_pronosticos.py   baja los pronósticos de todos los sitios (lo corre la GitHub Action)
tests/                     pruebas de humo con st.testing.AppTest
.github/workflows/         Actions: pronósticos cada hora y pruebas en cada push
.streamlit/                tema, archivos estáticos y configuración de la caché
static/                    imagen de portada (Esri World Imagery) y logos de MetGeo, servidos en app/static/
requirements.txt           dependencias
```

## Velocidad

- Las cargas usan caché con `ttl` de 15 minutos y `refresh_mode="background"`: cuando una entrada
  vence, el visitante recibe al instante la versión anterior y la nueva se baja por detrás.
- `app.py` envuelve la app en `st.App` y, desde el servidor, toca esas cargas al arrancar y cada 5
  minutos, así que la caché está caliente aunque nadie haya entrado en horas. Bajar las 4 variables de
  las 71 estaciones VIPNet toma ~25 s (12 consultas en paralelo).
- Las claves de caché no dependen de los controles: siempre se pide la ventana máxima (7 días) y se
  recorta en la página.
- Solo se ejecuta la página abierta.

## Enlaces compartibles

El sitio, los días, la variable y la estación elegida quedan en la URL, así que se puede compartir una
vista exacta; por ejemplo
`/comparar?sitio=Pucón+(DGA)&variable=Precipitación&pasado=5`.

## Agregar o quitar estaciones

Editar `SITIOS` en `fuentes.py` (`vars` = variables que mide cada una). El catálogo completo de VIPNet
sale de `POST https://vipnet.mop.gob.cl/v1/vipnet/estaciones` con `{"tipoEstacion": 0}`; las de
La Araucanía son las que traen `region` o `regionEstacion` igual a 9. La serie de una estación sale de
`POST https://vipnet.mop.gob.cl/v1/vipnet/estacion/valores` con
`{"codigoEstacion", "tipoEstacion", "fetchHour", "fetchDay", "hoursRange"}`
(tipos: 0 lluvia, 1 temperatura, 4 humedad, 5 viento en km/h). Los nodos del ensamble se recalculan solos.

## Correr en tu computador

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Pruebas: `cd tests && python -m pytest -q`.

Para usar una copia local de los pronósticos (por ejemplo, recién generada con
`python actualiza_pronosticos.py salida`), definir `MONITOR_DATOS=salida` antes de lanzar la app.

## Publicar

1. Crear el repositorio `Heszo/monitor-meteo-araucania` en GitHub y subir la rama `main`
   (la app lee los pronósticos de su rama `datos`; si el repositorio tiene otro nombre, cambiar `REPO`
   en `fuentes.py`).
2. En *Settings* → *Actions* → *General*, dar permiso de escritura a `GITHUB_TOKEN` y lanzar a mano
   *Actualizar pronósticos* una vez para crear la rama `datos`.
3. En [share.streamlit.io](https://share.streamlit.io): *Create app* → este repositorio, rama `main`,
   archivo `app.py`, URL `metgeo-araucania.streamlit.app` → *Deploy*.

La app se duerme tras unos días sin visitas; la Action la visita en cada corrida para mantenerla despierta.

## Autoría y licencia

Bruno Herrera · MetGeo Spa · [github.com/Heszo](https://github.com/Heszo). Código bajo licencia [MIT](LICENSE).
Logos de MetGeo Spa: todos los derechos reservados, no incluidos en la licencia MIT.
Imagen de portada: Esri World Imagery (Esri, Maxar, Earthstar Geographics y la comunidad de usuarios SIG).
