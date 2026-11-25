"""
Conector AgroCabildo — API Meteo del Cabildo de Tenerife
Documentación: https://datos.tenerife.es/api/meteo/latest/docs   (OpenAPI 3, sin clave)

Endpoints usados (verificados el 23-11-2026):
  GET /stations                                   → 68 estaciones (id_weatherstation, name, place,
                                                    latitude, longitude, altitude, date_uninstall…)
  GET /stations/{id}/sensors                      → sensores de la estación (id_weatherstationsensor,
                                                    sensor_alias: WSP, WDR, TEMP, HUM, RAIN, RAD)
  GET /readings/station/{id}/sensor/{sid}/from/{AAAA-MM-DD}/to/{AAAA-MM-DD}/{page}
                                                  → valores DIEZMINUTALES, 10 días por página;
                                                    página inexistente = 404. El dato llega con
                                                    ~2-10 min de retraso. 'to' es la fecha de corte
                                                    (00:00), así que para incluir hoy se pide to=mañana.
  GET /readings/summarized/station/{id}/year/{año}→ valores DIARIOS (mean, min, max, total) por sensor

Valores: se usa validated_value si existe; si no (dato reciente sin validar), observation_value.
Las fechas vienen sin zona; en invierno coinciden con UTC. Si en verano el ciclo diario aparece
desplazado una hora respecto a AEMET, ajusta [agrocabildo] desfase_horas en config.ini.

Agregación a escala HORARIA (marca = fin del intervalo):
  TEMP→ta (media) y tamax/tamin, HUM→hr (media), RAIN→prec (suma), WSP→vv (media) y vmax
  (máximo de las medias diezminutales: no hay sensor de racha), WDR→dv (media vectorial), RAD→rad.
"""
import json
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError

from .comun import en_tenerife, http_json, media_direccion, normaliza_nombre, num
from almacen import iso_hora

FUENTE = "AGROCABILDO"
API = "https://datos.tenerife.es/api/meteo/latest"
HILOS = 6                     # peticiones simultáneas (sé amable con el servidor del Cabildo)


# ----------------------------------------------------------------------------- utilidades
def _api(ruta, timeout=30, reintentos=2):
    return http_json(API + ruta, timeout=timeout, reintentos=reintentos)


def variable_de_sensor(alias, nombre=""):
    a = normaliza_nombre(alias)
    n = normaliza_nombre(nombre)
    t = a + "|" + n
    if any(x in t for x in ("SUELO", "SOIL", "HOJA", "LEAF", "INV", "AGUA", "BATER", "BATT")):
        return None
    if a.startswith("TEMP") or "TEMPERATURA" in n:
        return "tamax" if "MAX" in t else "tamin" if "MIN" in t else "ta"
    if a.startswith("HUM") or a in ("HR", "RH") or "HUMEDAD" in n:
        return "hr"
    if a.startswith(("RAIN", "PREC", "LLUV", "PLUV")) or "PRECIPITACION" in n:
        return "prec"
    if a.startswith(("WDR", "DIR")) or "DIRECCION" in n:
        return "dv"
    if a.startswith(("WSP", "VEL", "WS")) or "VELOCIDAD" in n:
        return "vmax" if ("MAX" in t or "RACHA" in t or "GUST" in t) else "vv"
    if a.startswith(("RAD", "SOL", "GSR")) or "RADIACION" in n:
        return "rad"
    if a.startswith(("PRES", "BAR")) or "PRESION" in n:
        return "pres"
    return None


def _parse_fecha(s, desfase_h=0.0):
    d = datetime.fromisoformat(str(s).strip().replace("Z", "")[:19])
    return (d + timedelta(hours=desfase_h)).replace(tzinfo=timezone.utc)


def _valor(v):
    x = num(v.get("validated_value"))
    return x if x is not None else num(v.get("observation_value"))


# ----------------------------------------------------------------------------- catálogo
def estaciones():
    """Estaciones activas de AgroCabildo en Tenerife (dicts normalizados)."""
    salida = []
    for s in _api("/stations").get("stations", []):
        if s.get("date_uninstall"):
            continue
        lat, lon = num(s.get("latitude")), num(s.get("longitude"))
        if not en_tenerife(lat, lon):
            continue
        cod = str(s["id_weatherstation"])
        lugar = (s.get("place") or s.get("locality") or "").strip()
        lugar = re.sub(r"\s+", " ", lugar).title() if lugar.isupper() or lugar.islower() else re.sub(r"\s+", " ", lugar)
        nombre = f"{lugar} ({s.get('name', cod)})" if lugar else s.get("name", cod)
        salida.append({"id": f"AGRO:{cod}", "fuente": FUENTE, "codigo": cod, "nombre": nombre,
                       "lat": lat, "lon": lon, "alt": num(s.get("altitude"))})
    return salida


def sensores(cat, ruta_cache, max_dias=7, log=print):
    """{codigo_estacion: [(id_sensor, alias, nombre), ...]} con caché en disco (se renueva semanalmente)."""
    if os.path.exists(ruta_cache) and time.time() - os.path.getmtime(ruta_cache) < max_dias * 86400:
        with open(ruta_cache, encoding="utf-8") as f:
            cache = json.load(f)
        if all(e["codigo"] in cache for e in cat):
            return cache

    def uno(e):
        try:
            j = _api(f"/stations/{e['codigo']}/sensors", timeout=20)
            ss = (j.get("stations") or [{}])[0].get("sensors", [])
            return e["codigo"], [(str(s["id_weatherstationsensor"]), s.get("sensor_alias", ""),
                                  s.get("sensor_name", "")) for s in ss
                                 if (s.get("installation_type") or "Aire") == "Aire"]
        except Exception:
            return e["codigo"], None

    with ThreadPoolExecutor(HILOS) as ex:
        res = dict(ex.map(uno, cat))
    cache = {k: v for k, v in res.items() if v}
    if cache:
        with open(ruta_cache, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        log(f"[AGROCABILDO] catálogo de sensores: {sum(len(v) for v in cache.values())} sensores en {len(cache)} estaciones")
    return cache


# ----------------------------------------------------------------------------- lecturas diezminutales
def _lecturas(codigo, sid, desde, hasta, todas_paginas=False):
    """Lista de (fecha_str, valor) de un sensor entre dos fechas (AAAA-MM-DD, 'hasta' excluida)."""
    out, pagina = [], 1
    while True:
        try:
            j = _api(f"/readings/station/{codigo}/sensor/{sid}/from/{desde}/to/{hasta}/{pagina}",
                     timeout=30, reintentos=2)
        except HTTPError as e:
            if e.code == 404:          # no hay (más) páginas / sin datos
                break
            raise
        vals = []
        for s in (j.get("readings") or {}).get("sensors", []):
            vals += s.get("values", [])
        out += [(v["observation_date"], _valor(v)) for v in vals if v.get("observation_date")]
        if not todas_paginas or not vals:
            break
        pagina += 1
    return out


def _descargar(cat, sens, desde, hasta, desfase, todas_paginas, log, etiqueta):
    """Descarga en paralelo todas las parejas estación-sensor útiles y agrega a horario."""
    trabajos = [(e["codigo"], sid, alias, nom) for e in cat for sid, alias, nom in sens.get(e["codigo"], [])
                if variable_de_sensor(alias, nom)]
    muestras = defaultdict(list)          # codigo → [(alias, nombre, fecha, valor)]
    errores = [0]
    hechos = [0]
    lock = threading.Lock()
    t0 = time.time()

    def uno(t):
        cod, sid, alias, nom = t
        if errores[0] >= 15 and hechos[0] == 0:     # el servicio no responde: no insistir
            return
        try:
            lect = _lecturas(cod, sid, desde, hasta, todas_paginas)
            with lock:
                muestras[cod] += [(alias, nom, f, v) for f, v in lect]
                hechos[0] += 1
        except Exception:
            with lock:
                errores[0] += 1

    with ThreadPoolExecutor(HILOS) as ex:
        list(ex.map(uno, trabajos))
    log(f"[AGROCABILDO] {etiqueta}: {hechos[0]}/{len(trabajos)} series descargadas"
        f"{f', {errores[0]} con error' if errores[0] else ''} ({time.time() - t0:.0f} s)")
    if not hechos[0]:
        raise RuntimeError(f"la API Meteo del Cabildo no devolvió datos ({errores[0]} errores)")
    return agregar_horario(muestras, desfase)


def agregar_horario(muestras_por_estacion, desfase_h=0.0):
    registros = []
    for cod, muestras in muestras_por_estacion.items():
        cubos = defaultdict(lambda: defaultdict(list))
        for alias, nom, fecha, valor in muestras:
            var = variable_de_sensor(alias, nom)
            if var is None or valor is None:
                continue
            try:
                d = _parse_fecha(fecha, desfase_h)
            except ValueError:
                continue
            cubos[iso_hora(d)][var].append(valor)
        for fecha, vs in cubos.items():
            r = {"estacion_id": f"AGRO:{cod}", "fecha": fecha, "fuente": FUENTE}
            if vs.get("ta"):
                r["ta"] = round(sum(vs["ta"]) / len(vs["ta"]), 1)
                r["tamax"], r["tamin"] = round(max(vs["ta"]), 1), round(min(vs["ta"]), 1)
            if vs.get("hr"):
                r["hr"] = round(sum(vs["hr"]) / len(vs["hr"]))
            if vs.get("prec"):
                r["prec"] = round(sum(vs["prec"]), 1)
            if vs.get("vv"):
                r["vv"] = round(sum(vs["vv"]) / len(vs["vv"]), 1)
                r["vmax"] = round(max(vs["vv"]), 1)
            if vs.get("dv"):
                r["dv"] = media_direccion(vs["dv"])
            if vs.get("rad"):
                r["rad"] = round(sum(vs["rad"]) / len(vs["rad"]))
            if vs.get("pres"):
                r["pres"] = round(sum(vs["pres"]) / len(vs["pres"]), 1)
            registros.append(r)
    return registros


def descargar_tiempo_real(cfg, carpeta, horas=None, log=print):
    """Últimas `horas` horas de todas las estaciones. Devuelve (estaciones, registros horarios)."""
    desfase = float(cfg.get("desfase_horas", "0") or 0)
    horas = horas or int(cfg.get("horas_tiempo_real", "6") or 6)
    ahora = datetime.now(timezone.utc)
    cat = estaciones()
    sens = sensores(cat, os.path.join(carpeta, "agrocabildo_sensores.json"), log=log)
    desde = (ahora - timedelta(hours=horas + 1 + abs(desfase))).date().isoformat()
    hasta = (ahora + timedelta(days=1)).date().isoformat()
    regs = _descargar(cat, sens, desde, hasta, desfase, False, log, f"últimas {horas} h")
    limite = iso_hora(ahora - timedelta(hours=horas + 1))
    return cat, [r for r in regs if r["fecha"] >= limite]


def backfill(desde, hasta, carpeta, desfase=0.0, log=print):
    """Histórico diezminutal → horario entre dos fechas (AAAA-MM-DD; 'hasta' incluida)."""
    cat = estaciones()
    sens = sensores(cat, os.path.join(carpeta, "agrocabildo_sensores.json"), log=log)
    h = (date.fromisoformat(hasta) + timedelta(days=1)).isoformat()
    return cat, _descargar(cat, sens, desde, h, desfase, True, log, f"{desde} → {hasta}")


# ----------------------------------------------------------------------------- resúmenes diarios oficiales
def diarios(anio, carpeta, log=print):
    """Valores diarios del año (endpoint 'summarized'): filas para la tabla resumen_diario."""
    cat = estaciones()
    sens = sensores(cat, os.path.join(carpeta, "agrocabildo_sensores.json"), log=log)

    def uno(e):
        alias_de = {sid: (a, n) for sid, a, n in sens.get(e["codigo"], [])}
        try:
            j = _api(f"/readings/summarized/station/{e['codigo']}/year/{anio}", timeout=60)
        except Exception:
            return []
        dias = defaultdict(dict)
        for s in (j.get("summarized") or {}).get("sensors", []):
            var = variable_de_sensor(*alias_de.get(str(s.get("id_weatherstationsensor")), ("", "")))
            if not var:
                continue
            for d in s.get("dates", []):
                v = (d.get("values") or [{}])[0]
                dias[d["observation_date"][:10]][var] = v
        filas = []
        for dia, vs in dias.items():
            t, hr, p = vs.get("ta", {}), vs.get("hr", {}), vs.get("prec", {})
            w, rd = vs.get("vv", {}), vs.get("rad", {})
            filas.append({"estacion_id": e["id"], "dia": dia, "tmed": num(t.get("mean")),
                          "tmax": num(t.get("max")), "tmin": num(t.get("min")), "hrmed": num(hr.get("mean")),
                          "prec": num(p.get("total")) if num(p.get("total")) is not None else num(p.get("max")),
                          "vvmed": num(w.get("mean")), "racha": num(w.get("max")),
                          "radmed": num(rd.get("mean")), "n_horas": 24})
        return filas

    with ThreadPoolExecutor(HILOS) as ex:
        res = [f for lote in ex.map(uno, cat) for f in lote]
    return cat, res


def endpoints_api():
    """Para `colector.py explorar-cabildo`: lista los endpoints publicados."""
    spec = _api("/openapi.json")
    return [{"ruta": r, "resumen": op.get("summary", ""), "descripcion": op.get("description", ""),
             "parametros": [p.get("name") for p in op.get("parameters", [])]}
            for r, ops in spec.get("paths", {}).items() for m, op in ops.items() if m == "get"]
