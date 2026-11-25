"""
Ciclo en la nube (GitHub Actions) del gemelo climático de Tenerife.

  python nube.py ciclo      → lo que ejecuta GitHub cada hora:
      1. reconstruye una base SQLite temporal a partir de los CSV diarios del repositorio
      2. descarga AEMET + AgroCabildo (y, de madrugada, rellena el día anterior de AgroCabildo)
      3. reescribe los CSV diarios de los últimos días y los resúmenes anuales
      4. genera el sitio web estático (_site/) con los JSON que lee la app móvil

  python nube.py sitio      → solo el paso 4 (útil para probar en local)

Persistencia (se guarda en el repositorio, texto plano, mismo formato que el gemelo local):
  datos/historico/AAAA/AAAA-MM-DD.csv   observaciones horarias de cada día (UTC)
  datos/resumen/AAAA.csv                resúmenes diarios por estación
  datos/tenerife.geojson                contorno insular (GRAFCAN)
  datos/agrocabildo_sensores.json       catálogo de sensores de AgroCabildo

Variables de entorno: AEMET_API_KEY (secreto del repositorio), BACKFILL_DESDE (AAAA-MM-DD,
opcional), DIARIOS_ANIOS ("2024 2025", opcional).
"""
import csv
import glob
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

import colector  # noqa: E402
from almacen import VARIABLES, Almacen, iso_hora, ahora_utc  # noqa: E402
from fuentes.comun import en_tenerife, http_get  # noqa: E402

DATOS = os.path.join(RAIZ, "datos")
HIST = os.path.join(DATOS, "historico")
RESUMEN = os.path.join(DATOS, "resumen")
SITIO = os.path.join(RAIZ, "_site")
DIAS_CARGA = 35            # días de CSV que se cargan (≥ 31 para las series horarias de la app)
DIAS_EXPORTA = 4           # días que se reescriben en cada ciclo (cubre las 72 h de la primera descarga)
HORAS_VISOR = 72
COLS_RES = ["estacion_id", "dia", "tmed", "tmax", "tmin", "hrmed", "prec", "vvmed", "racha", "radmed", "n_horas"]

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


# ----------------------------------------------------------------------------- CSV ↔ SQLite
def cargar(alm, dias=DIAS_CARGA):
    hoy = ahora_utc().date()
    ests, obs = {}, []
    for k in range(dias, -1, -1):
        d = hoy - timedelta(days=k)
        ruta = os.path.join(HIST, f"{d.year}", f"{d.isoformat()}.csv")
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter=";"):
                eid = r["estacion_id"]
                if eid not in ests and r.get("lat"):
                    ests[eid] = {"id": eid, "fuente": r.get("fuente") or eid.split(":")[0],
                                 "codigo": eid.split(":", 1)[-1], "nombre": r.get("nombre"),
                                 "lat": _num(r.get("lat")), "lon": _num(r.get("lon")), "alt": _num(r.get("alt"))}
                o = {"estacion_id": eid, "fecha": r["fecha"], "fuente": r.get("fuente")}
                for v in VARIABLES:
                    o[v] = _num(r.get(v))
                obs.append(o)
    alm.guardar_estaciones(ests.values())
    alm.guardar_obs(obs)
    filas = []
    for ruta in sorted(glob.glob(os.path.join(RESUMEN, "*.csv"))):
        with open(ruta, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter=";"):
                filas.append({c: (r[c] if c in ("estacion_id", "dia") else _num(r.get(c))) for c in COLS_RES})
    alm.guardar_resumen(filas)
    log(f"[cargar] {len(ests)} estaciones, {len(obs)} obs horarias de {dias + 1} días, {len(filas)} días-estación de resumen")


def exportar(alm, dias):
    anios = set()
    for d in sorted(set(dias)):
        n, ruta = alm.consolidar_dia(d, HIST)          # CSV del día + resumen diario
        anios.add(d[:4])
        if n:
            log(f"[exportar] {d}: {n} obs → {os.path.relpath(ruta, RAIZ)}")
    os.makedirs(RESUMEN, exist_ok=True)
    with alm._con() as c:
        for a in sorted(anios):
            filas = c.execute(f"SELECT {','.join(COLS_RES)} FROM resumen_diario WHERE dia LIKE ? "
                              "ORDER BY dia, estacion_id", (a + "%",)).fetchall()
            with open(os.path.join(RESUMEN, f"{a}.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(COLS_RES)
                w.writerows(list(r) for r in filas)


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
    # series por estación: horaria (31 días, en columnas) + resumen diario completo
    desde = iso_hora(ahora - timedelta(days=31))
    for e in ests:
        filas = alm.serie(e["id"], desde)
        hor = {"fecha": [f["fecha"] for f in filas]}
        for v in VARIABLES:
            col = [_redondear(f[v]) for f in filas]
            if any(x is not None for x in col):
                hor[v] = col
        dia = alm.serie_diaria(e["id"], "0000")
        _escribir_json(os.path.join(d, "series", e["id"].replace(":", "_") + ".json"),
                       {"id": e["id"], "horaria": hor,
                        "diaria": [{k: _redondear(v) if isinstance(v, float) else v for k, v in r.items()}
                                   for r in dia]})
    log(f"[sitio] {len(ests)} estaciones, {len(obs)} obs en ventana → {os.path.relpath(SITIO, RAIZ)}/")


# ----------------------------------------------------------------------------- ciclo
def ciclo():
    cfg = colector.cargar_config()
    cfg["general"]["modo"] = "real"
    cfg["general"]["carpeta_datos"] = DATOS
    tmp = tempfile.mkdtemp()
    alm = Almacen(os.path.join(tmp, "historico.sqlite"))
    cargar(alm)
    colector.isla(cfg, log)
    colector.actualizar(cfg, alm, log=log)

    ahora = ahora_utc()
    tocados = [(ahora - timedelta(days=k)).date().isoformat() for k in range(DIAS_EXPORTA)]
    # madrugada (UTC 00-02): volver a pedir el día anterior completo a AgroCabildo
    marca = os.path.join(DATOS, "ultimo_relleno.txt")
    ayer = (ahora - timedelta(days=1)).date().isoformat()
    hecho = open(marca).read().strip() if os.path.exists(marca) else ""
    if ahora.hour <= 2 and hecho != ayer and colector._si(cfg["agrocabildo"].get("relleno_diario", "si")):
        colector.rellenar_agrocabildo(cfg, ayer, ayer, alm, log)
        with open(marca, "w") as f:
            f.write(ayer)
    # tareas manuales (lanzadas desde la pestaña Actions con parámetros)
    desde = (os.environ.get("BACKFILL_DESDE") or "").strip()
    if desde:
        colector.rellenar_agrocabildo(cfg, desde, ahora.date().isoformat(), alm, log)
        d0 = date.fromisoformat(desde)
        tocados += [(d0 + timedelta(days=k)).isoformat() for k in range((ahora.date() - d0).days + 1)]
    anios = [int(a) for a in (os.environ.get("DIARIOS_ANIOS") or "").split() if a.isdigit()]
    if anios:
        colector.diarios_agrocabildo(cfg, anios, alm, log)
        with alm._con() as c:
            for (a,) in c.execute("SELECT DISTINCT substr(dia,1,4) FROM resumen_diario"):
                tocados.append(f"{a}-01-01")       # fuerza reescribir el resumen de ese año
    exportar(alm, tocados)
    generar_sitio(alm, cfg)


def solo_sitio():
    cfg = colector.cargar_config()
    cfg["general"]["carpeta_datos"] = DATOS
    tmp = tempfile.mkdtemp()
    alm = Almacen(os.path.join(tmp, "historico.sqlite"))
    cargar(alm)
    generar_sitio(alm, cfg)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ciclo"
    {"ciclo": ciclo, "sitio": solo_sitio}[cmd]()
