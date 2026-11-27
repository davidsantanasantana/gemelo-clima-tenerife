"""
Gemelo digital climático de Tenerife — servidor local.

  python gemelo.py            → arranca en http://localhost:8765 (modo según config.ini)
  python gemelo.py --demo     → datos sintéticos, sin clave ni conexión a las fuentes
  python gemelo.py --sin-navegador

El servidor:
  · sirve el visor web (carpeta web/)
  · expone una API JSON local (/api/...)
  · si [programador] interno = si: descarga cada hora y consolida cada día.
Solo depende de la biblioteca estándar de Python (≥ 3.9).
"""
import csv
import io
import json
import os
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

import colector  # noqa: E402
from almacen import VARIABLES, iso_hora, ahora_utc  # noqa: E402
from fuentes.comun import en_tenerife, http_get  # noqa: E402
from fuentes import avisos  # noqa: E402

# Servidores de cartografía permitidos para la lectura de capacidades WMS (CNIG/IGN y GRAFCAN)
HOSTS_WMS = ("www.ign.es", "ign.es", "servicios.idee.es", "wms-mapa-lidar.idee.es", "www.idee.es",
             "idecan1.grafcan.es", "idecan2.grafcan.es", "idecan3.grafcan.es")
_cache_capas = {}


def capas_wms(url):
    """Lee GetCapabilities y devuelve las capas con nombre [{nombre, titulo}] (con caché)."""
    host = urlparse(url).hostname or ""
    if host not in HOSTS_WMS:
        raise ValueError(f"servidor no permitido: {host}")
    if url in _cache_capas:
        return _cache_capas[url]
    sep = "&" if "?" in url else "?"
    raw = http_get(url + sep + "SERVICE=WMS&REQUEST=GetCapabilities", timeout=40, reintentos=2)
    raiz = ET.fromstring(raw)
    capas = []
    for capa in raiz.iter():
        if not capa.tag.endswith("Layer"):
            continue
        nombre = titulo = None
        hijas = 0
        for h in capa:
            t = h.tag.rsplit("}", 1)[-1]
            if t == "Name":
                nombre = (h.text or "").strip()
            elif t == "Title":
                titulo = (h.text or "").strip()
            elif t == "Layer":
                hijas += 1
        if nombre:
            capas.append({"nombre": nombre, "titulo": titulo, "hoja": hijas == 0})
    _cache_capas[url] = capas
    return capas

WEB = os.path.join(RAIZ, "web")
_lock_tarea = threading.Lock()
ESTADO_PROG = {"proxima_actualizacion": None, "en_curso": False, "ultimo_resultado": None}
AVISOS_CACHE = {"t": 0, "d": None}


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


# ----------------------------------------------------------------------------- tareas en segundo plano
def lanzar_actualizacion(cfg, alm):
    if not _lock_tarea.acquire(blocking=False):
        return False

    def run():
        ESTADO_PROG["en_curso"] = True
        try:
            ESTADO_PROG["ultimo_resultado"] = colector.actualizar(cfg, alm, log=log)
        except Exception as e:  # pragma: no cover
            log(f"actualización fallida: {e}")
        finally:
            ESTADO_PROG["en_curso"] = False
            _lock_tarea.release()
    threading.Thread(target=run, daemon=True).start()
    return True


def programador(cfg, alm):
    minuto = int(cfg["programador"].get("minuto_actualizacion", "40"))
    hh, mm = [int(x) for x in cfg["programador"].get("hora_consolidacion", "00:50").split(":")]
    ultima_hora = None
    ultimo_dia = None
    while True:
        ahora = datetime.now()
        prox = ahora.replace(minute=minuto, second=0, microsecond=0)
        if prox <= ahora:
            prox += timedelta(hours=1)
        ESTADO_PROG["proxima_actualizacion"] = prox.astimezone().isoformat(timespec="minutes")
        clave_hora = ahora.strftime("%Y%m%d%H")
        if ahora.minute >= minuto and clave_hora != ultima_hora:
            ultima_hora = clave_hora
            lanzar_actualizacion(cfg, alm)
        if (ahora.hour, ahora.minute) >= (hh, mm) and ultimo_dia != ahora.date():
            ultimo_dia = ahora.date()
            try:
                colector.consolidar(cfg, (date.today() - timedelta(days=1)).isoformat(), alm, log=log)
            except Exception as e:
                log(f"consolidación fallida: {e}")
        time.sleep(20)


# ----------------------------------------------------------------------------- HTTP
def crear_manejador(cfg, alm):
    horas_visor = int(cfg["general"].get("horas_visor", "72"))

    def estaciones_isla():
        colector.isla(cfg, log)
        return [e for e in alm.estaciones() if en_tenerife(e["lat"], e["lon"])]

    class Manejador(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=WEB, **k)

        def log_message(self, fmt, *args):   # silencio para peticiones normales
            if not self.path.startswith("/api/") or "error" in fmt.lower():
                return

        def _json(self, obj, code=200):
            data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if urlparse(self.path).path == "/api/actualizar":
                return self._json({"lanzada": lanzar_actualizacion(cfg, alm)})
            self._json({"error": "no encontrado"}, 404)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/config":
                    return self._json({"modo": cfg["general"].get("modo"), "horas_visor": horas_visor,
                                       "variables": VARIABLES})
                if u.path == "/api/estado":
                    e = alm.estado()
                    e.update(ESTADO_PROG)
                    e["modo"] = cfg["general"].get("modo")
                    return self._json(e)
                if u.path == "/api/isla":
                    isla = colector.isla(cfg, log)
                    if not isla.disponible:
                        return self._json({"error": "contorno no disponible"}, 404)
                    return self._json(isla.geojson)
                if u.path == "/api/avisos":
                    if time.time() - AVISOS_CACHE["t"] > 900:      # como mucho cada 15 min
                        AVISOS_CACHE["d"] = avisos.descargar(cfg["aemet"].get("api_key", ""),
                                                             cfg["aemet"].get("url_avisos", avisos.URL_WEB))
                        AVISOS_CACHE["t"] = time.time()
                    return self._json(AVISOS_CACHE["d"])
                if u.path == "/api/wms_capas":
                    return self._json(capas_wms(q["url"]))
                if u.path == "/api/estaciones":
                    return self._json(estaciones_isla())
                if u.path == "/api/ventana":
                    h = min(int(q.get("horas", horas_visor)), 24 * 31)
                    ests = estaciones_isla()
                    ids = {e["id"] for e in ests}
                    obs = [o for o in alm.ventana(h) if o["estacion_id"] in ids]
                    return self._json({"estaciones": ests, "obs": obs,
                                       "generado": iso_hora(ahora_utc())})
                if u.path == "/api/serie":
                    dias = min(int(q.get("dias", 7)), 3660)
                    desde_dt = ahora_utc() - timedelta(days=dias)
                    if dias > 31:
                        return self._json({"escala": "diaria",
                                           "datos": alm.serie_diaria(q["id"], desde_dt.strftime("%Y-%m-%d"))})
                    return self._json({"escala": "horaria", "datos": alm.serie(q["id"], iso_hora(desde_dt))})
                if u.path == "/api/csv":
                    dias = min(int(q.get("dias", 30)), 3660)
                    filas = alm.serie(q["id"], iso_hora(ahora_utc() - timedelta(days=dias)))
                    buf = io.StringIO()
                    w = csv.writer(buf, delimiter=";")
                    w.writerow(["fecha_utc"] + VARIABLES)
                    for f in filas:
                        w.writerow([f["fecha"]] + [f.get(v) for v in VARIABLES])
                    data = buf.getvalue().encode("utf-8-sig")
                    nombre = q["id"].replace(":", "_") + f"_{dias}d.csv"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{nombre}"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            except KeyError as e:
                return self._json({"error": f"falta parámetro {e}"}, 400)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            if u.path.startswith("/api/"):
                return self._json({"error": "no encontrado"}, 404)
            return super().do_GET()

    return Manejador


def main():
    demo_flag = "--demo" in sys.argv
    cfg = colector.cargar_config(demo_flag)
    alm = colector.abrir(cfg)
    puerto = int(cfg["general"].get("puerto", "8765"))
    modo = cfg["general"].get("modo")
    log(f"Gemelo climático de Tenerife — modo {modo.upper()} — BD: {colector.rutas(cfg)['db']}")

    colector.isla(cfg, log)            # contorno de Tenerife (GRAFCAN), se cachea en datos/
    # primera carga al arrancar (en segundo plano para no retrasar el visor)
    lanzar_actualizacion(cfg, alm)
    if colector._si(cfg["programador"].get("interno", "si")):
        threading.Thread(target=programador, args=(cfg, alm), daemon=True).start()
        log("Programador interno activo: descarga horaria + consolidación diaria")

    srv = ThreadingHTTPServer(("127.0.0.1", puerto), crear_manejador(cfg, alm))
    url = f"http://localhost:{puerto}"
    log(f"Visor disponible en {url}   (Ctrl+C para salir)")
    if "--sin-navegador" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("Detenido.")


if __name__ == "__main__":
    main()
