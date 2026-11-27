"""
Ciclo en la nube (GitHub Actions) del gemelo climático de Tenerife — versión SIN histórico.

  python nube.py ciclo      → lo que ejecuta GitHub cada hora:
      1. lee los datos que ya están publicados en la web (data/ventana.json), si existen
      2. descarga AEMET (ventana móvil ~12 h) y AgroCabildo (últimas horas)
      3. junta ambos, se queda con las últimas HORAS_VISOR horas y genera el sitio (_site/)

No se guarda NADA en el repositorio: el «estado» entre ejecuciones es la propia web publicada.
Así no hay commits ni conflictos. El histórico completo, si se quiere, lo lleva el gemelo local
del PC (gemelo.py).

Variables de entorno: AEMET_API_KEY (secreto del repositorio), URL_PUBLICADA (la da el workflow).
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

import colector  # noqa: E402
from almacen import VARIABLES, Almacen, iso_hora, ahora_utc  # noqa: E402
from fuentes.comun import en_tenerife, http_get  # noqa: E402
from fuentes import avisos  # noqa: E402

DATOS = os.path.join(RAIZ, "datos")
SITIO = os.path.join(RAIZ, "_site")
HORAS_VISOR = 24           # horas que muestra la app publicada (sube a 72 o 168 si quieres más)

FONDOS_WMS = [
    "https://www.ign.es/wms-inspire/ign-base", "https://www.ign.es/wms-inspire/mapa-raster",
    "https://www.ign.es/wms-inspire/pnoa-ma", "https://servicios.idee.es/wms-inspire/mdt",
    "https://idecan2.grafcan.es/ServicioWMS/MTI", "https://idecan1.grafcan.es/ServicioWMS/OrtoExpress",
    "https://idecan1.grafcan.es/ServicioWMS/MDSombras",
]


def log(msg):
    print(f"{datetime.now(timezone.utc):%H:%M:%S}Z  {msg}", flush=True)


def _num(x):
    if x in (None, "", "None"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


# ----------------------------------------------------------------------------- sitio estático
def _escribir_json(ruta, obj):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def _redondear(v):
    return None if v is None else round(v, 2)


def capas_wms():
    from gemelo import capas_wms as leer
    salida = {}
    for url in FONDOS_WMS:
        try:
            salida[url] = leer(url)
        except Exception as e:
            log(f"[wms] {url}: {e}")
    return salida


def generar_sitio(alm, cfg):
    if os.path.exists(SITIO):
        shutil.rmtree(SITIO)
    shutil.copytree(os.path.join(RAIZ, "web"), SITIO)
    version = ahora_utc().strftime("%Y%m%d%H%M")
    # marca de versión en el service worker (fuerza la actualización de la app instalada)
    sw = os.path.join(SITIO, "sw.js")
    with open(sw, encoding="utf-8") as f:
        txt = f.read().replace("__VERSION__", version)
    with open(sw, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(os.path.join(SITIO, "config.js"), "w", encoding="utf-8") as f:
        f.write(f"window.GEMELO = {{ estatico: true, version: '{version}', horasVisor: {HORAS_VISOR} }};\n")

    d = os.path.join(SITIO, "data")
    isla = colector.isla(cfg, log)
    ests = [e for e in alm.estaciones() if en_tenerife(e["lat"], e["lon"])]
    ids = {e["id"] for e in ests}
    obs = [{k: _redondear(v) if k in VARIABLES else v for k, v in o.items()}
           for o in alm.ventana(HORAS_VISOR) if o["estacion_id"] in ids]
    _escribir_json(os.path.join(d, "ventana.json"),
                   {"estaciones": ests, "obs": obs, "generado": iso_hora(ahora_utc())})
    est = alm.estado()
    ahora = ahora_utc()
    prox = ahora.replace(minute=25, second=0, microsecond=0)
    if prox <= ahora:
        prox += timedelta(hours=1)
    est.update({"modo": "nube", "en_curso": False, "proxima_actualizacion": prox.isoformat(),
                "publicado": ahora.isoformat(timespec="seconds")})
    _escribir_json(os.path.join(d, "estado.json"), est)
    if isla.disponible:
        _escribir_json(os.path.join(d, "isla.geojson"), isla.geojson)
    _escribir_json(os.path.join(d, "wms_capas.json"), capas_wms())
    av = avisos.descargar(cfg["aemet"].get("api_key", ""), cfg["aemet"].get("url_avisos", avisos.URL_WEB))
    _escribir_json(os.path.join(d, "avisos.json"), av)
    log(f"[avisos] {'nivel ' + av['nivel'] + ', ' + str(len(av['avisos'])) + ' avisos' if av['ok'] else 'ERROR ' + str(av['error'])}")
    log(f"[sitio] {len(ests)} estaciones, {len(obs)} obs en ventana → {os.path.relpath(SITIO, RAIZ)}/")


# ----------------------------------------------------------------------------- ciclo
def recuperar_publicado(alm, url_base):
    """Carga en la base temporal lo que ya está publicado (estado de la ejecución anterior)."""
    if not url_base:
        log("[publicado] sin URL de la web: se empieza de cero")
        return
    url_base = url_base.rstrip("/")
    try:
        prev = json.loads(http_get(f"{url_base}/data/ventana.json?t={int(ahora_utc().timestamp())}",
                                   timeout=60, reintentos=2).decode("utf-8"))
        alm.guardar_estaciones(prev.get("estaciones", []))
        alm.guardar_obs(prev.get("obs", []))
        log(f"[publicado] {len(prev.get('estaciones', []))} estaciones y {len(prev.get('obs', []))} obs recuperadas de la web")
    except Exception as e:
        log(f"[publicado] no se pudo leer la versión publicada ({e}); se empieza de cero")
    ruta_isla = os.path.join(DATOS, "tenerife.geojson")
    if not os.path.exists(ruta_isla):              # contorno: el ya publicado evita depender de GRAFCAN
        try:
            raw = http_get(f"{url_base}/data/isla.geojson", timeout=60, reintentos=1)
            json.loads(raw.decode("utf-8"))
            os.makedirs(DATOS, exist_ok=True)
            with open(ruta_isla, "wb") as f:
                f.write(raw)
        except Exception:
            pass


def ciclo():
    cfg = colector.cargar_config()
    cfg["general"]["modo"] = "real"
    cfg["general"]["carpeta_datos"] = DATOS
    tmp = tempfile.mkdtemp()
    alm = Almacen(os.path.join(tmp, "historico.sqlite"))
    recuperar_publicado(alm, os.environ.get("URL_PUBLICADA", ""))
    colector.isla(cfg, log)
    colector.actualizar(cfg, alm, log=log)
    generar_sitio(alm, cfg)


def solo_sitio():
    """Prueba local: genera _site/ a partir de lo publicado en URL_PUBLICADA (o vacío)."""
    cfg = colector.cargar_config()
    cfg["general"]["carpeta_datos"] = DATOS
    tmp = tempfile.mkdtemp()
    alm = Almacen(os.path.join(tmp, "historico.sqlite"))
    recuperar_publicado(alm, os.environ.get("URL_PUBLICADA", ""))
    generar_sitio(alm, cfg)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ciclo"
    {"ciclo": ciclo, "sitio": solo_sitio}[cmd]()
