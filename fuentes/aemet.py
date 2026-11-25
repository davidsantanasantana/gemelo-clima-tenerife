"""
Conector AEMET OpenData.

Endpoint usado: /api/observacion/convencional/todas
  → observación horaria (sin validar) de TODAS las estaciones de España para las últimas
    ~12 h (ventana móvil). Se filtra a Tenerife por coordenadas.

IMPORTANTE: como la ventana es de ~12 h, el histórico se alimenta en cada ejecución horaria
(con deduplicación por estación+hora). Una sola descarga diaria dejaría huecos de ~12 h.

Petición en dos pasos: la API devuelve {"estado", "datos": <url>, "metadatos": <url>} y
después se descarga la URL de "datos" (codificada en ISO-8859-15).
Clave gratuita: https://opendata.aemet.es/centrodedescargas/altaUsuario
"""
from datetime import datetime, timezone

from .comun import en_tenerife, http_json, num
from almacen import iso_hora

BASE = "https://opendata.aemet.es/opendata/api"
FUENTE = "AEMET"

# campo AEMET → variable normalizada
MAPA = {"ta": "ta", "tamax": "tamax", "tamin": "tamin", "hr": "hr", "prec": "prec",
        "vv": "vv", "dv": "dv", "vmax": "vmax", "dmax": "dmax", "pres": "pres"}


def _parse_fint(s):
    s = s.strip().replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"fecha AEMET no reconocida: {s}")


def _peticion(ruta, api_key):
    meta = http_json(f"{BASE}{ruta}", headers={"api_key": api_key, "cache-control": "no-cache"},
                     timeout=30)
    estado = meta.get("estado")
    if estado != 200 or "datos" not in meta:
        raise RuntimeError(f"AEMET respondió estado={estado}: {meta.get('descripcion')}")
    return http_json(meta["datos"], encoding="latin-1", timeout=90)


def descargar(api_key):
    """Devuelve (estaciones, registros) normalizados para Tenerife."""
    if not api_key or api_key.startswith("PON_AQUI"):
        raise RuntimeError("Falta la API key de AEMET en config.ini")
    datos = _peticion("/observacion/convencional/todas", api_key)
    estaciones, registros = {}, []
    for d in datos:
        lat, lon = num(d.get("lat")), num(d.get("lon"))
        if not en_tenerife(lat, lon):
            continue
        idema = str(d.get("idema"))
        eid = f"AEMET:{idema}"
        estaciones[eid] = {"id": eid, "fuente": FUENTE, "codigo": idema,
                           "nombre": (d.get("ubi") or idema).strip().title(),
                           "lat": lat, "lon": lon, "alt": num(d.get("alt"))}
        try:
            fecha = iso_hora(_parse_fint(d["fint"]))
        except (KeyError, ValueError):
            continue
        r = {"estacion_id": eid, "fecha": fecha, "fuente": FUENTE}
        for k, v in MAPA.items():
            r[v] = num(d.get(k))
        # Presión: AEMET da 'pres' en la estación; útil para tendencias
        registros.append(r)
    return list(estaciones.values()), registros
