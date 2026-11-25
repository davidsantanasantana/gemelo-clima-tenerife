# Gemelo digital climático de Tenerife

Plataforma local de observación en tiempo real de variables climáticas (temperatura, humedad,
precipitación, viento, racha, presión y radiación) a partir de las redes de **AEMET** y
**AgroCabildo** (Cabildo de Tenerife). Descarga los datos, construye un histórico local y los
muestra en un visor web con mapa, superficie interpolada sobre el relieve, reproducción temporal
y series por estación.

Solo necesita **Python ≥ 3.7** (biblioteca estándar, sin `pip install`) y un navegador.
Leaflet va incluido en `web/vendor/`.

Todo el visor se circunscribe a **Tenerife**: el mapa se encuadra y se limita a la isla, el
exterior (mar y resto de islas) queda enmascarado, se dibuja la línea de costa, la superficie
interpolada se recorta a la costa y solo se muestran estaciones situadas en la isla.

> **App para iPhone y Android:** el mismo visor se puede publicar gratis en GitHub Pages, con
> actualización horaria automática aunque el PC esté apagado, e instalarse en el móvil. Los
> pasos están en **[GUIA_MOVIL.md](GUIA_MOVIL.md)**.

---

## Puesta en marcha

1. **Prueba sin clave (modo demo):** doble clic en `iniciar_demo.bat`
   (o `python gemelo.py --demo`). Se abre `http://localhost:8765` con datos **sintéticos**.
2. **Clave AEMET (gratuita):** https://opendata.aemet.es/centrodedescargas/altaUsuario
   (llega por correo).
3. Copia `config.ini.ejemplo` → `config.ini` y pega la clave **detrás de `api_key = `** en la
   sección `[aemet]` (sin comillas, en una sola línea). También puedes dejar `config.ini` sin
   tocar y definir la variable de entorno `AEMET_API_KEY`.
4. Doble clic en `iniciar_gemelo.bat` (o `python gemelo.py`).

Mientras `gemelo.py` está abierto, el programador interno descarga cada hora (minuto 40 por
defecto) y consolida cada día a las 00:50. El visor comprueba cada minuto si hay datos nuevos y
se refresca solo.

### Histórico con el visor cerrado
Ejecuta una vez `instalar_tareas_windows.bat`: registra en el Programador de tareas
`colector.py actualizar` (cada hora) y `colector.py consolidar` (diaria). En Linux/macOS:

```cron
40 * * * *  cd /ruta/gemelo_tenerife && python3 colector.py actualizar
50 0 * * *  cd /ruta/gemelo_tenerife && python3 colector.py consolidar
```

> **Por qué cada hora y no una vez al día.** El servicio de observación convencional de AEMET
> solo ofrece una ventana móvil de las últimas ~12 h. Con una única descarga diaria quedarían
> huecos de ~12 h. La descarga horaria va acumulando el histórico (sin duplicados), y la
> consolidación diaria genera el fichero del día y el resumen diario. Si el equipo pasa menos de
> ~12 h apagado, no se pierde nada de AEMET.

---

## Qué se guarda (carpeta `datos/`)

| Fichero | Contenido |
|---|---|
| `historico.sqlite` | Base de datos principal: tablas `estaciones`, `obs` (horaria, UTC), `resumen_diario`, `registro` |
| `diario/AAAA/AAAA-MM-DD.csv` | Todas las observaciones horarias del día (separador `;`), generadas cada noche |
| `tenerife.geojson` | Contorno de Tenerife (GRAFCAN), descargado y simplificado la primera vez |
| `agrocabildo_sensores.json` | Catálogo de sensores de AgroCabildo (se renueva semanalmente) |
| `demo.sqlite`, `diario_demo/` | Lo mismo para el modo demo (no se mezcla con los datos reales) |

Variables normalizadas en `obs`: `ta, tamax, tamin` (°C), `hr` (%), `prec` (mm en la hora),
`vv, vmax` (m/s; el visor muestra km/h), `dv, dmax` (°, de dónde sopla), `pres` (hPa en
estación), `rad` (W/m²). Marca horaria = **fin** del intervalo en UTC (`2026-11-23T13:00Z`
resume 12:00–13:00). En invierno UTC coincide con la hora canaria.

Las tablas se abren directamente en QGIS (*Capa → Añadir capa → SpatiaLite/SQLite*, o como texto
delimitado con `lat/lon` desde los CSV diarios).

---

## Fuentes

**AEMET OpenData** — `/api/observacion/convencional/todas`, filtrado por la caja de Tenerife.
Datos horarios sin validar. Estaciones: las que publique AEMET en la isla en cada momento.

**AgroCabildo**: API Meteo del Cabildo de Tenerife (`https://datos.tenerife.es/api/meteo/latest`),
pública y sin clave. Son unas 68 estaciones con datos **diezminutales en tiempo real**, que llegan
con pocos minutos de retraso. Cada estación tiene sensores WSP, WDR, TEMP, HUM, RAIN y RAD.

* El catálogo de estaciones sale de `/stations`. Los sensores de cada estación salen de
  `/stations/{id}/sensors` y se guardan en `datos/agrocabildo_sensores.json`, que se renueva
  cada semana.
* Cada hora se piden las lecturas de las últimas 6 h de cada estación-sensor, unas 400 peticiones
  en paralelo, normalmente en menos de un minuto. La primera vez se piden 72 h para que el visor
  arranque con historia.
* Cada noche se vuelve a pedir el día anterior completo. Así se rellenan los huecos si el equipo
  estuvo apagado y se recogen los valores ya validados.
* Histórico a demanda (diezminutal → horario):
  ```
  python colector.py backfill-agrocabildo --desde 2026-01-01            # hasta hoy
  python colector.py backfill-agrocabildo --desde 2025-01-01 --hasta 2025-12-31
  ```
  La API pagina en bloques de 10 días. Un año completo son unas 15.000 peticiones, así que
  cuenta con bastante tiempo. Para tendencias largas es mejor el siguiente comando.
* Resúmenes **diarios oficiales** (media, mínima, máxima, total), con una petición por estación
  y año:
  ```
  python colector.py diarios-agrocabildo 2020 2021 2022 2023 2024 2025 2026
  ```
  Van a la tabla `resumen_diario`, que es la que usan las gráficas de más de 31 días.

Los valores se agregan a escala horaria: media (T, HR, viento, radiación), suma (precipitación) y
media vectorial (dirección). Se usa el valor validado si existe; si no, el observado. La red no
tiene sensor de racha, así que `vmax` es el máximo de las medias diezminutales y subestima la
racha real.

**Zona horaria:** en invierno las fechas de la API coinciden con UTC. Lo he comprobado: a las 14:42
UTC el último dato era de las 14:40. No he podido comprobar el horario de verano. Si en verano
ves el ciclo diario de AgroCabildo adelantado una hora respecto a AEMET, pon `desfase_horas = -1`.

---

## El visor

* **Mapa** con las estaciones coloreadas por la variable activa (círculo = AEMET,
  cuadrado = AgroCabildo), valores y flechas de viento.
* **Superficie interpolada** (IDW, potencia 2, con decaimiento a ~15 km) recortada a tierra con
  un MDT global (Terrain Tiles de AWS/Mapzen, resolución de decenas de metros) y con sombreado del relieve.
  Para la temperatura, las estaciones se reducen a nivel del mar con −6,5 °C/km, se interpolan
  y se devuelven a la cota de cada píxel. Así el campo de temperatura sigue el relieve en vez de
  mezclar costa y cumbre. **Ojo con la inversión del alisio:** por encima del mar de nubes el
  gradiente real se invierte y esa corrección sobrestima el enfriamiento. El *perfil altitudinal*
  del panel izquierdo enseña cuándo pasa.
* **Línea de tiempo** con las últimas 72 h (`horas_visor`), botón ▶ para reproducirlas y
  flechas ← → del teclado.
* **Ficha de estación** (clic): valores actuales y gráficas de 24 h a 1 año (más de 31 días
  usa el resumen diario), con exportación CSV.
* **Estado de las fuentes** en la cabecera: verde < 3 h, ámbar < 24 h, rojo si hay error o no
  hay datos (pasa el ratón para ver el mensaje).

**Fondos cartográficos (WMS oficiales, libres):**

| Organismo | Servicio | URL |
|---|---|---|
| CNIG / IGN | IGN Base | `https://www.ign.es/wms-inspire/ign-base` |
| CNIG / IGN | Mapa ráster MTN | `https://www.ign.es/wms-inspire/mapa-raster` |
| CNIG / IGN | Ortofoto PNOA máx. actualidad | `https://www.ign.es/wms-inspire/pnoa-ma` |
| CNIG / IGN | Relieve (MDT) | `https://servicios.idee.es/wms-inspire/mdt` |
| GRAFCAN | Mapa Topográfico Integrado | `https://idecan2.grafcan.es/ServicioWMS/MTI` |
| GRAFCAN | OrtoExpress | `https://idecan1.grafcan.es/ServicioWMS/OrtoExpress` |
| GRAFCAN | Sombreado del relieve | `https://idecan1.grafcan.es/ServicioWMS/MDSombras` |

El nombre de la capa de cada servicio se confirma leyendo su `GetCapabilities` a través del
servidor local, así que si GRAFCAN o el IGN renombran una capa el visor sigue funcionando. Por
defecto el fondo se atenúa en grises para que destaquen los datos (casilla desmarcable). Para
añadir otro WMS, edita la tabla `FONDOS` al principio de `web/app.js` (y su host en
`HOSTS_WMS` de `gemelo.py`). Si un servicio falla, el selector de fondo se marca en rojo.

**Contorno insular:** GRAFCAN, *Islas y municipios* (línea de costa del Mapa Topográfico
Integrado), en opendata.sitcan.es. Se descarga y simplifica (~15 m) la primera vez. Para usar
tu propio contorno, guarda un GeoJSON de Tenerife (EPSG:4326 o UTM 28N) como
`datos/tenerife.geojson`. Las estaciones situadas a menos de 500 m de la costa (puertos, faros)
se aceptan.

Los fondos y el MDT se cargan de internet; los datos y el servidor son locales. La API local (`/api/estado`, `/api/ventana?horas=`,
`/api/serie?id=&dias=`, `/api/csv?id=&dias=`) se puede consultar desde Python, R o QGIS.

---

## Limitaciones

* Datos **provisionales/no validados** en ambas redes. No usar para fines oficiales sin
  validar.
* IDW no conoce la orografía (salvo la corrección altitudinal de T). Con unas decenas de estaciones
  representa bien el patrón general, pero no las celdas convectivas pequeñas ni los efectos
  de ladera.
* La presión en estación depende de la cota, por eso no se interpola.

## Ampliaciones fáciles

* Añadir una fuente nueva = un módulo en `fuentes/` que devuelva `(estaciones, registros)` y una
  línea en `colector.actualizar()`. Candidatas: red pluviométrica propia, SiAR (API con token,
  incluye las estaciones de AgroCabildo), GRAFCAN.
* Avisos por correo cuando se superen umbrales (lluvia en 1 h/24 h, rachas).
