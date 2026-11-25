"""Utilidades compartidas por los conectores: HTTP con reintentos, Tenerife bbox, UTM→geográficas."""
import json
import math
import time
import unicodedata
import urllib.error
import urllib.request

# Caja de Tenerife (excluye La Gomera, Gran Canaria y La Palma)
BBOX_TENERIFE = {"lat_min": 27.98, "lat_max": 28.62, "lon_min": -16.95, "lon_max": -16.10}

UA = "GemeloClimaTenerife/1.0 (+uso local)"


_ISLA = None


def fijar_isla(isla):
    """Registra el contorno de Tenerife (isla.Isla) para el filtrado espacial de estaciones."""
    global _ISLA
    _ISLA = isla


def en_tenerife(lat, lon):
    if lat is None or lon is None:
        return False
    if _ISLA is not None and _ISLA.disponible:
        return _ISLA.contiene(lat, lon)
    b = BBOX_TENERIFE
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]


def http_get(url, headers=None, timeout=60, reintentos=3, espera=5):
    """GET que devuelve bytes. Reintenta en 429/5xx y errores de red."""
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    ultimo = None
    for i in range(reintentos):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code in (429, 500, 502, 503, 504):
                if i < reintentos - 1:
                    time.sleep(espera * (i + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            ultimo = e
            if i < reintentos - 1:
                time.sleep(espera * (i + 1))
    raise ultimo


def http_json(url, headers=None, timeout=60, encoding=None, reintentos=3):
    raw = http_get(url, headers=headers, timeout=timeout, reintentos=reintentos)
    if encoding:
        return json.loads(raw.decode(encoding))
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode("latin-1"))


def num(x):
    """Convierte a float tolerando comas decimales, cadenas vacías y centinelas."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        v = float(x)
    else:
        s = str(x).strip().replace(",", ".")
        if s in ("", "-", "NaN", "nan", "null", "None", "Ip", "ip"):
            return 0.0 if s.lower() == "ip" else None   # Ip = precipitación inapreciable
        try:
            v = float(s)
        except ValueError:
            return None
    if math.isnan(v) or v <= -9990 or v >= 9990:
        return None
    return v


def normaliza_nombre(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.upper() if ch.isalnum())


def utm_a_geo(x, y, huso=28):
    """UTM (WGS84/ETRS89, hemisferio norte) → (lat, lon). Suficiente para posicionar estaciones."""
    a, f = 6378137.0, 1 / 298.257223563
    k0, e2 = 0.9996, f * (2 - f)
    ep2 = e2 / (1 - e2)
    x -= 500000.0
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
          + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(p1) ** 2)
    t1 = math.tan(p1) ** 2
    c1 = ep2 * math.cos(p1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (
        d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(p1)
    lon0 = math.radians((huso - 1) * 6 - 180 + 3)
    return math.degrees(lat), math.degrees(lon0 + lon)


def media_direccion(dirs, pesos=None):
    """Media vectorial de direcciones en grados."""
    sx = sy = 0.0
    for i, d in enumerate(dirs):
        if d is None:
            continue
        w = pesos[i] if pesos and pesos[i] is not None else 1.0
        sx += w * math.sin(math.radians(d))
        sy += w * math.cos(math.radians(d))
    if sx == 0 and sy == 0:
        return None
    return round(math.degrees(math.atan2(sx, sy))) % 360
