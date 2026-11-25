"""
Fuente de DEMOSTRACIÓN: datos sintéticos plausibles para probar el gemelo sin API key.
NO son observaciones reales. Las posiciones son aproximadas.

Modelo sencillo: gradiente térmico -6.5 °C/km, ciclo diurno mayor en cumbre/sur,
alisio del NE, mar de nubes (HR alta) en la vertiente norte entre 600-1500 m,
aire seco por encima de la inversión, y episodios de llovizna en el norte.
"""
import math
import random
import zlib
from datetime import datetime, timedelta, timezone

from almacen import iso_hora

FUENTE = "DEMO"

# nombre, lat, lon, alt, vertiente (N/S/C)
_EST = [
    ("Santa Cruz (demo)", 28.463, -16.255, 35, "S"),
    ("Los Rodeos (demo)", 28.477, -16.330, 620, "N"),
    ("La Laguna (demo)", 28.487, -16.316, 550, "N"),
    ("Tacoronte (demo)", 28.478, -16.412, 500, "N"),
    ("Anaga - Cruz del Carmen (demo)", 28.531, -16.280, 920, "N"),
    ("Puerto de la Cruz (demo)", 28.414, -16.548, 25, "N"),
    ("La Orotava (demo)", 28.390, -16.523, 390, "N"),
    ("Aguamansa (demo)", 28.358, -16.498, 1050, "N"),
    ("Icod de los Vinos (demo)", 28.367, -16.720, 230, "N"),
    ("Buenavista del Norte (demo)", 28.373, -16.858, 110, "N"),
    ("Santiago del Teide (demo)", 28.296, -16.815, 940, "S"),
    ("Guía de Isora (demo)", 28.210, -16.780, 580, "S"),
    ("Adeje (demo)", 28.122, -16.726, 280, "S"),
    ("Tenerife Sur (demo)", 28.047, -16.561, 60, "S"),
    ("Granadilla (demo)", 28.120, -16.577, 650, "S"),
    ("Vilaflor (demo)", 28.157, -16.636, 1400, "S"),
    ("Arico (demo)", 28.165, -16.480, 550, "S"),
    ("Güímar (demo)", 28.315, -16.410, 290, "S"),
    ("Candelaria (demo)", 28.354, -16.371, 30, "S"),
    ("Izaña (demo)", 28.309, -16.499, 2371, "C"),
    ("Las Cañadas (demo)", 28.222, -16.628, 2150, "C"),
    ("La Esperanza (demo)", 28.440, -16.380, 1050, "N"),
    ("Teno Alto (demo)", 28.343, -16.880, 760, "N"),
    ("Fasnia (demo)", 28.236, -16.437, 420, "S"),
]


def estaciones():
    return [{"id": f"DEMO:{i:02d}", "fuente": FUENTE, "codigo": f"{i:02d}", "nombre": n,
             "lat": la, "lon": lo, "alt": float(a)} for i, (n, la, lo, a, _) in enumerate(_EST, 1)]


def _obs(i, est, t):
    n, la, lo, z, vert = est
    rnd = random.Random(zlib.crc32(f"{i}|{t.isoformat()}".encode()))
    dia = t.timetuple().tm_yday + t.year * 400
    hora_local = (t.hour + t.minute / 60)                     # Canarias = UTC en invierno
    fase = math.cos(2 * math.pi * (hora_local - 14.5) / 24)
    # sinóptico lento (episodio de alisio fuerte / borrasca)
    sin1 = math.sin(2 * math.pi * (dia + t.hour / 24) / 5.3)
    sin2 = math.sin(2 * math.pi * (dia + t.hour / 24) / 3.1 + 1)
    amp = 2.5 + (4.5 if vert == "C" else 3.0 if vert == "S" else 1.8) * min(z, 1500) / 1500
    base = 19.8 - 6.5 * z / 1000 + (1.2 if vert == "S" else 0) + 1.2 * sin1
    inversion = 1400 + 250 * sin2
    if z > inversion:
        base += 3.0 * min(1, (z - inversion) / 400)           # aire más cálido sobre la inversión
    ta = base + amp * fase + rnd.gauss(0, 0.4)
    # humedad
    if vert == "N" and 500 < z < inversion:
        hr = 88 - 12 * fase + rnd.gauss(0, 3)
    elif z > inversion:
        hr = 25 + 10 * sin2 - 8 * fase + rnd.gauss(0, 4)
    else:
        hr = 70 - 10 * fase + rnd.gauss(0, 4)
    hr = max(5, min(100, hr))
    # viento (alisio NE; aceleración en Güímar/sur-este y en cumbre)
    fuerza = 6 + 3 * sin1
    fac = 1.6 if n.startswith(("Güímar", "Candelaria", "Arico", "Tenerife Sur", "Fasnia")) else 1.0
    fac = 2.0 if vert == "C" else fac
    fac = 0.6 if vert == "N" and z < 600 else fac
    vv = max(0.0, fuerza * fac * (0.8 + 0.3 * fase) + rnd.gauss(0, 0.8))
    dv = (35 + 25 * sin2 + rnd.gauss(0, 15)) % 360
    if vert == "C" and z > inversion:
        dv = (300 + rnd.gauss(0, 20)) % 360                     # flujo del NO en altura
    vmax = vv * (1.5 + rnd.random() * 0.5)
    # precipitación: llovizna en el norte cuando hay mar de nubes y alisio fuerte
    prec = 0.0
    if vert == "N" and 300 < z < inversion and sin1 > 0.55 and rnd.random() < 0.35:
        prec = round(rnd.expovariate(1 / 0.6), 1)
    if sin2 < -0.85 and rnd.random() < 0.5:                     # episodio general
        prec += round(rnd.expovariate(1 / (1.5 if vert == "N" else 0.8)), 1)
    rad = max(0.0, 950 * math.cos(2 * math.pi * (hora_local - 13.3) / 24) ** 3
              if 7 <= hora_local <= 19.5 else 0.0) * (0.45 if hr > 85 else 1.0)
    pres = 1013.5 * (1 - 2.25577e-5 * z) ** 5.25588 + 3 * sin1
    return {"ta": round(ta, 1), "tamax": round(ta + 0.4, 1), "tamin": round(ta - 0.4, 1),
            "hr": round(hr), "prec": prec, "vv": round(vv, 1), "dv": round(dv),
            "vmax": round(vmax, 1), "dmax": round((dv + rnd.gauss(0, 10)) % 360),
            "pres": round(pres, 1), "rad": round(rad)}


def descargar(horas=12, hasta=None):
    hasta = (hasta or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    ests = estaciones()
    regs = []
    for h in range(horas):
        t = hasta - timedelta(hours=h)
        for i, e in enumerate(_EST, 1):
            r = _obs(i, e, t)
            r.update({"estacion_id": f"DEMO:{i:02d}", "fecha": iso_hora(t), "fuente": FUENTE})
            regs.append(r)
    return ests, regs
