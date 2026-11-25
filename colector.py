"""
Colector del gemelo digital climático de Tenerife.

Uso:
  python colector.py actualizar              # descarga de tiempo real (lánzalo cada hora)
  python colector.py consolidar [AAAA-MM-DD] # CSV + resumen del día (por defecto, ayer)
  python colector.py backfill-agrocabildo --desde AAAA-MM-DD [--hasta AAAA-MM-DD]
                                             # histórico diezminutal de AgroCabildo → horario
  python colector.py diarios-agrocabildo [AÑO ...]
                                             # resúmenes diarios oficiales de AgroCabildo
  python colector.py explorar-cabildo        # lista los endpoints de la API Meteo del Cabildo
  python colector.py estado                  # resumen del histórico

Todos los comandos aceptan --demo para trabajar con la base de datos de demostración.
"""
import configparser
import json
import os
import sys
import threading
import time
import traceback
from datetime import date, datetime, timedelta

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

from almacen import Almacen  # noqa: E402
from fuentes import aemet, agrocabildo, comun, demo  # noqa: E402
from isla import Isla  # noqa: E402

_ISLA = None
_ISLA_INTENTO = 0.0


# ----------------------------------------------------------------------------- configuración
def cargar_config(forzar_demo=False):
    cfg = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    ruta = os.path.join(RAIZ, "config.ini")
    if not os.path.exists(ruta):
        ruta = os.path.join(RAIZ, "config.ini.ejemplo")
    try:
        cfg.read(ruta, encoding="utf-8-sig")
    except configparser.Error as e:
        primera = str(e).splitlines()[-1][:60]
        sys.exit(
            "\n*** config.ini está mal formado ***\n"
            f"{type(e).__name__}: {primera}...\n\n"
            "Cada ajuste debe ir dentro de su sección. La clave de AEMET va así:\n\n"
            "    [aemet]\n    activo = si\n    api_key = eyJhbGciOi...(tu clave completa)\n\n"
            "Solución rápida: borra config.ini, vuelve a copiar config.ini.ejemplo como config.ini\n"
            "y pega la clave SOLO detrás de 'api_key = '.\n")
    for sec in ("general", "programador", "aemet", "agrocabildo"):
        if not cfg.has_section(sec):
            cfg.add_section(sec)
    if os.environ.get("AEMET_API_KEY"):
        cfg["aemet"]["api_key"] = os.environ["AEMET_API_KEY"]
    if forzar_demo:
        cfg["general"]["modo"] = "demo"
    return cfg


def rutas(cfg):
    carpeta = cfg["general"].get("carpeta_datos", "datos")
    if not os.path.isabs(carpeta):
        carpeta = os.path.join(RAIZ, carpeta)
    modo = cfg["general"].get("modo", "real")
    nombre = "demo.sqlite" if modo == "demo" else "historico.sqlite"
    return {"carpeta": carpeta, "db": os.path.join(carpeta, nombre),
            "diario": os.path.join(carpeta, "diario_demo" if modo == "demo" else "diario"),
            }


def abrir(cfg):
    return Almacen(rutas(cfg)["db"])


def isla(cfg, log=print):
    """Contorno de Tenerife (se descarga de GRAFCAN la primera vez y queda en datos/)."""
    global _ISLA, _ISLA_INTENTO
    ruta = os.path.join(rutas(cfg)["carpeta"], "tenerife.geojson")
    # si la descarga falló, no se reintenta hasta pasadas 6 h (salvo que aparezca el fichero)
    if (_ISLA is None or not _ISLA.disponible) and (time.time() - _ISLA_INTENTO > 6 * 3600 or os.path.exists(ruta)):
        _ISLA_INTENTO = time.time()
        _ISLA = Isla(ruta)
        _ISLA.cargar(log)
        comun.fijar_isla(_ISLA)
    return _ISLA


def _si(v):
    return str(v).strip().lower() in ("si", "sí", "yes", "true", "1", "on")


# ----------------------------------------------------------------------------- tareas
def actualizar(cfg, alm=None, log=print):
    """Descarga horaria de todas las fuentes activas. Devuelve dict {fuente: n_registros|error}."""
    alm = alm or abrir(cfg)
    isla(cfg, log)
    res = {}
    if cfg["general"].get("modo") == "demo":
        primera = alm.estado()["n_obs"] == 0
        ests, regs = demo.descargar(horas=24 * 10 if primera else 12)
        alm.guardar_estaciones(ests)
        res["DEMO"] = alm.guardar_obs(regs)
        alm.log("actualizar", "DEMO", True, res["DEMO"])
        log(f"[demo] {res['DEMO']} registros sintéticos")
        return res

    tareas = []
    if _si(cfg["aemet"].get("activo", "si")):
        tareas.append(("AEMET", lambda: aemet.descargar(cfg["aemet"].get("api_key", ""))))
    if _si(cfg["agrocabildo"].get("activo", "si")):
        # primera vez: 72 h para que el visor arranque con historia; después, las últimas horas
        horas_agro = None if alm.hay_obs_de("AGRO:") else 72
        tareas.append(("AGROCABILDO", lambda: agrocabildo.descargar_tiempo_real(
            cfg["agrocabildo"], rutas(cfg)["carpeta"], horas_agro, log)))
    def ejecutar(nombre, fn):
        t0 = time.time()
        log(f"[{nombre}] descargando…")
        try:
            ests, regs = fn()
            alm.guardar_estaciones(ests)
            n = alm.guardar_obs(regs)
            res[nombre] = n
            alm.log("actualizar", nombre, True, n, f"{len(ests)} estaciones")
            log(f"[{nombre}] {len(ests)} estaciones, {n} registros horarios ({time.time() - t0:.0f} s)")
        except Exception as e:
            res[nombre] = f"ERROR: {e}"
            alm.log("actualizar", nombre, False, 0, f"{type(e).__name__}: {e}")
            log(f"[{nombre}] ERROR ({time.time() - t0:.0f} s): {e}")

    hilos = [threading.Thread(target=ejecutar, args=t, daemon=True) for t in tareas]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return res


def consolidar(cfg, dia=None, alm=None, log=print):
    alm = alm or abrir(cfg)
    dia = dia or (date.today() - timedelta(days=1)).isoformat()
    n, ruta = alm.consolidar_dia(dia, rutas(cfg)["diario"])
    alm.log("consolidar", "-", True, n, ruta or "sin datos")
    log(f"[consolidar] {dia}: {n} observaciones → {ruta or '(sin datos)'}")
    if (cfg["general"].get("modo") != "demo" and _si(cfg["agrocabildo"].get("activo", "si"))
            and _si(cfg["agrocabildo"].get("relleno_diario", "si"))):
        # vuelve a pedir el día completo a AgroCabildo (rellena huecos si el equipo estuvo apagado)
        rellenar_agrocabildo(cfg, dia, dia, alm, log)
        n, ruta = alm.consolidar_dia(dia, rutas(cfg)["diario"])
    return n, ruta


def rellenar_agrocabildo(cfg, desde, hasta=None, alm=None, log=print):
    alm = alm or abrir(cfg)
    isla(cfg, log)
    hasta = hasta or date.today().isoformat()
    desf = float(cfg["agrocabildo"].get("desfase_horas", "0") or 0)
    log(f"[backfill] AgroCabildo {desde} → {hasta} …")
    try:
        ests, regs = agrocabildo.backfill(desde, hasta, rutas(cfg)["carpeta"], desf, log)
        alm.guardar_estaciones(ests)
        n = alm.guardar_obs(regs)
        alm.log("backfill", "AGROCABILDO", True, n, f"{desde} → {hasta}")
        log(f"[backfill] {n} registros horarios guardados")
    except Exception as e:
        alm.log("backfill", "AGROCABILDO", False, 0, str(e))
        log(f"[backfill] ERROR: {e}")


def diarios_agrocabildo(cfg, anios, alm=None, log=print):
    alm = alm or abrir(cfg)
    isla(cfg, log)
    for anio in anios:
        ests, filas = agrocabildo.diarios(anio, rutas(cfg)["carpeta"], log)
        alm.guardar_estaciones(ests)
        n = alm.guardar_resumen(filas)
        alm.log("diarios", "AGROCABILDO", True, n, f"año {anio}")
        log(f"[diarios] {anio}: {n} días-estación guardados")


def explorar_cabildo():
    print("Endpoints de la API Meteo del Cabildo (https://datos.tenerife.es/api/meteo/latest/docs):\n")
    for e in agrocabildo.endpoints_api():
        print(f"GET {e['ruta']}\n    {e['resumen']}: {e['descripcion']}\n")


# ----------------------------------------------------------------------------- CLI
def main(argv):
    demo_flag = "--demo" in argv
    argv = [a for a in argv if a != "--demo"]
    cfg = cargar_config(demo_flag)
    cmd = argv[1] if len(argv) > 1 else "actualizar"
    try:
        if cmd == "actualizar":
            actualizar(cfg)
        elif cmd == "consolidar":
            consolidar(cfg, argv[2] if len(argv) > 2 else None)
        elif cmd == "backfill-agrocabildo":
            desde = argv[argv.index("--desde") + 1] if "--desde" in argv else \
                (date.today() - timedelta(days=30)).isoformat()
            hasta = argv[argv.index("--hasta") + 1] if "--hasta" in argv else date.today().isoformat()
            rellenar_agrocabildo(cfg, desde, hasta)
            alm = abrir(cfg)
            d = date.fromisoformat(desde)
            while d < min(date.today(), date.fromisoformat(hasta) + timedelta(days=1)):
                alm.consolidar_dia(d.isoformat(), rutas(cfg)["diario"])
                d += timedelta(days=1)
        elif cmd == "diarios-agrocabildo":
            anios = [int(a) for a in argv[2:] if a.isdigit()] or [date.today().year]
            diarios_agrocabildo(cfg, anios)
        elif cmd == "explorar-cabildo":
            explorar_cabildo()
        elif cmd == "estado":
            print(json.dumps(abrir(cfg).estado(), indent=2, ensure_ascii=False))
        else:
            print(__doc__)
            return 2
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
