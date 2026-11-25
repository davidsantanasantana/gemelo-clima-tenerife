"""
Contorno de la isla de Tenerife.

Fuente: GRAFCAN, "Islas y municipios" (línea de costa del Mapa Topográfico Integrado de Canarias),
publicado en opendata.sitcan.es. Se descarga una sola vez, se extrae Tenerife, se simplifica
(Douglas-Peucker, ~15 m) y se guarda en datos/tenerife.geojson.

Si prefieres tu propio contorno, deja en datos/tenerife.geojson un GeoJSON en EPSG:4326
(o en UTM 28N: se detecta y convierte) y no se volverá a descargar.

Se usa para: recortar estaciones (solo las de Tenerife), enmascarar el mapa y la superficie
interpolada, y dibujar el borde de la isla en el visor.
"""
import json
import math
import os

from fuentes.comun import BBOX_TENERIFE, http_json, normaliza_nombre, utm_a_geo

URLS = [
    "https://opendata.sitcan.es/upload/unidades-administrativas/gobcan_unidades-administrativas_islas.geojson",
    "https://opendata.sitcan.es/upload/unidades-administrativas/gobcan_unidades-administrativas_islas-generalizadas.geojson",
    "https://datos.canarias.es/catalogos/estadisticas/dataset/24d0ed91-1ce1-47e3-8b4c-44cf843fec28/"
    "resource/b3f12117-e4fd-4b8c-a31f-a93a1a8a020d/download/islas_20170101.json",
]


# ----------------------------------------------------------------------------- geometría
def _a_geo(anillo):
    if anillo and abs(anillo[0][0]) > 180:        # UTM 28N (REGCAN95/WGS84)
        return [list(reversed(utm_a_geo(x, y, 28))) for x, y, *_ in anillo]
    return [[x, y] for x, y, *_ in anillo]


def _area(anillo):
    return abs(sum(anillo[i][0] * anillo[i + 1][1] - anillo[i + 1][0] * anillo[i][1]
                   for i in range(len(anillo) - 1))) / 2


def _dp(pts, tol):
    """Douglas-Peucker iterativo. Los anillos cerrados se parten por el vértice más alejado."""
    if len(pts) < 4:
        return pts
    if pts[0] == pts[-1]:
        x0, y0 = pts[0]
        k = max(range(len(pts)), key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
        if 0 < k < len(pts) - 1:
            return _dp(pts[:k + 1], tol)[:-1] + _dp(pts[k:], tol)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    pila = [(0, len(pts) - 1)]
    while pila:
        a, b = pila.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        n = math.hypot(dx, dy) or 1e-12
        dmax, imax = 0, None
        for i in range(a + 1, b):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + bx * ay - by * ax) / n
            if d > dmax:
                dmax, imax = d, i
        if imax is not None and dmax > tol:
            keep[imax] = True
            pila += [(a, imax), (imax, b)]
    return [p for p, k in zip(pts, keep) if k]


def _poligonos(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def _es_tenerife(feat):
    for v in (feat.get("properties") or {}).values():
        if isinstance(v, str) and normaliza_nombre(v) in ("TENERIFE", "ISLADETENERIFE"):
            return True
    return False


def _centro_en_bbox(feat):
    b = BBOX_TENERIFE
    for pol in _poligonos(feat.get("geometry") or {}):
        anillo = _a_geo(pol[0])
        lon = sum(p[0] for p in anillo) / len(anillo)
        lat = sum(p[1] for p in anillo) / len(anillo)
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            return True
    return False


def descargar_contorno(ruta_destino, log=print):
    ultimo_error = None
    for url in URLS:
        try:
            gj = http_json(url, timeout=60, reintentos=1)
        except Exception as e:
            ultimo_error = e
            continue
        feats = gj.get("features", [])
        sel = [f for f in feats if _es_tenerife(f)] or [f for f in feats if _centro_en_bbox(f)]
        if not sel:
            continue
        polis = []
        for f in sel:
            for pol in _poligonos(f["geometry"]):
                ext = _a_geo(pol[0])
                if _area(ext) < 2e-7:                   # descarta roques diminutos (< ~0,2 ha)
                    continue
                polis.append([_dp(ext, 0.00015)])        # ~15 m
        if not polis:
            continue
        polis.sort(key=lambda p: -_area(p[0]))
        salida = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"nombre": "Tenerife", "fuente": "GRAFCAN", "url": url},
            "geometry": {"type": "MultiPolygon", "coordinates": polis}}]}
        os.makedirs(os.path.dirname(ruta_destino), exist_ok=True)
        with open(ruta_destino, "w", encoding="utf-8") as fh:
            json.dump(salida, fh, separators=(",", ":"))
        log(f"[isla] contorno de Tenerife descargado de GRAFCAN ({sum(len(p[0]) for p in polis)} vértices)")
        return salida
    raise RuntimeError(f"no se pudo descargar el contorno de Tenerife: {ultimo_error}")


# ----------------------------------------------------------------------------- consulta
class Isla:
    def __init__(self, ruta):
        self.ruta = ruta
        self.geojson = None
        self.anillos = []          # anillos exteriores [[lon, lat], ...]

    def cargar(self, log=print):
        if not os.path.exists(self.ruta):
            try:
                descargar_contorno(self.ruta, log)
            except Exception as e:
                log(f"[isla] {e}. Se usa la caja de Tenerife como recorte provisional.")
                return False
        with open(self.ruta, encoding="utf-8") as fh:
            gj = json.load(fh)
        anillos = []
        for f in gj.get("features", [gj] if gj.get("type") == "Feature" else []):
            for pol in _poligonos(f.get("geometry") or {}):
                anillos.append(_a_geo(pol[0]))
        if not anillos:
            log("[isla] el fichero de contorno no contiene polígonos")
            return False
        self.anillos = anillos
        self.geojson = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"nombre": "Tenerife"},
            "geometry": {"type": "MultiPolygon", "coordinates": [[a] for a in anillos]}}]}
        return True

    @property
    def disponible(self):
        return bool(self.anillos)

    @staticmethod
    def _dentro(anillo, lon, lat):
        c = False
        j = len(anillo) - 1
        for i in range(len(anillo)):
            xi, yi = anillo[i]
            xj, yj = anillo[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                c = not c
            j = i
        return c

    @staticmethod
    def _dist_m(anillo, lon, lat):
        kx = 111320 * math.cos(math.radians(lat))
        ky = 110540
        dmin = float("inf")
        for i in range(len(anillo) - 1):
            ax, ay = (anillo[i][0] - lon) * kx, (anillo[i][1] - lat) * ky
            bx, by = (anillo[i + 1][0] - lon) * kx, (anillo[i + 1][1] - lat) * ky
            dx, dy = bx - ax, by - ay
            t = max(0, min(1, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1e-9)))
            dmin = min(dmin, math.hypot(ax + t * dx, ay + t * dy))
        return dmin

    def contiene(self, lat, lon, tolerancia_m=500):
        """True si el punto está en Tenerife (o a menos de `tolerancia_m` de la costa:
        algunas estaciones de puerto/faro quedan sobre la línea de costa)."""
        if lat is None or lon is None:
            return False
        if not self.anillos:
            b = BBOX_TENERIFE
            return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]
        if any(self._dentro(a, lon, lat) for a in self.anillos):
            return True
        return any(self._dist_m(a, lon, lat) <= tolerancia_m for a in self.anillos)
