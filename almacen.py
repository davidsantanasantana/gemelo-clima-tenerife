"""
Almacén local del gemelo digital (SQLite).

Tablas
------
estaciones      : catálogo de estaciones de todas las fuentes (id con prefijo de fuente).
obs             : observaciones HORARIAS normalizadas (UTC), clave (estacion_id, fecha).
resumen_diario  : agregados diarios (UTC) calculados en la consolidación diaria.
registro        : bitácora de ejecuciones del colector (estado del sistema).

Variables normalizadas (todas en unidades SI habituales):
  ta    temperatura del aire (°C)          tamax / tamin  máx./mín. de la hora (°C)
  hr    humedad relativa (%)               prec           precipitación en la hora (mm)
  vv    velocidad media del viento (m/s)   dv             dirección media (° de donde sopla)
  vmax  racha máxima (m/s)                 dmax           dirección de la racha (°)
  pres  presión en la estación (hPa)       rad            radiación solar global (W/m²)
"""
import csv
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

VARIABLES = ["ta", "tamax", "tamin", "hr", "prec", "vv", "dv", "vmax", "dmax", "pres", "rad"]

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS estaciones (
    id      TEXT PRIMARY KEY,
    fuente  TEXT NOT NULL,
    codigo  TEXT,
    nombre  TEXT,
    lat     REAL,
    lon     REAL,
    alt     REAL,
    actualizado TEXT
);
CREATE TABLE IF NOT EXISTS obs (
    estacion_id TEXT NOT NULL,
    fecha       TEXT NOT NULL,          -- 'YYYY-MM-DDTHH:00Z' (UTC, fin del intervalo horario)
    ta REAL, tamax REAL, tamin REAL, hr REAL, prec REAL,
    vv REAL, dv REAL, vmax REAL, dmax REAL, pres REAL, rad REAL,
    fuente TEXT,
    insertado TEXT,
    PRIMARY KEY (estacion_id, fecha)
);
CREATE INDEX IF NOT EXISTS ix_obs_fecha ON obs(fecha);
CREATE TABLE IF NOT EXISTS resumen_diario (
    estacion_id TEXT NOT NULL,
    dia         TEXT NOT NULL,          -- 'YYYY-MM-DD' (UTC = hora canaria en invierno)
    tmed REAL, tmax REAL, tmin REAL, hrmed REAL, prec REAL,
    vvmed REAL, racha REAL, radmed REAL, n_horas INTEGER,
    PRIMARY KEY (estacion_id, dia)
);
CREATE TABLE IF NOT EXISTS registro (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    momento  TEXT,
    tarea    TEXT,
    fuente   TEXT,
    ok       INTEGER,
    n        INTEGER,
    mensaje  TEXT
);
"""

_lock = threading.Lock()


def ahora_utc():
    return datetime.now(timezone.utc)


def iso_hora(dt):
    """Normaliza un datetime (aware o naive=UTC) a la marca horaria 'YYYY-MM-DDTHH:00Z'.
    Los minutos se redondean HACIA ARRIBA al final de la hora (convención AEMET: el dato
    de las 10:00 resume 09:00-10:00)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    if dt.minute or dt.second:
        dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return dt.strftime("%Y-%m-%dT%H:00Z")


class Almacen:
    def __init__(self, ruta_db):
        self.ruta = ruta_db
        os.makedirs(os.path.dirname(os.path.abspath(ruta_db)), exist_ok=True)
        with self._con() as c:
            c.executescript(_ESQUEMA)

    def _con(self):
        c = sqlite3.connect(self.ruta, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    # ------------------------------------------------------------------ escritura
    def guardar_estaciones(self, estaciones):
        """estaciones: iterable de dicts {id, fuente, codigo, nombre, lat, lon, alt}.
        (Sin UPSERT para ser compatible con el SQLite antiguo de algunas instalaciones de Python 3.7.)"""
        t = ahora_utc().isoformat(timespec="seconds")
        filas = [(e["id"], e["fuente"], e.get("codigo"), e.get("nombre"), e.get("lat"),
                  e.get("lon"), e.get("alt"), t) for e in estaciones]
        if not filas:
            return 0
        with _lock, self._con() as c:
            c.executemany("INSERT OR IGNORE INTO estaciones (id,fuente,codigo,nombre,lat,lon,alt,actualizado) "
                          "VALUES (?,?,?,?,?,?,?,?)", filas)
            c.executemany(
                """UPDATE estaciones SET nombre=COALESCE(?, nombre), lat=COALESCE(?, lat),
                   lon=COALESCE(?, lon), alt=COALESCE(?, alt), actualizado=? WHERE id=?""",
                [(f[3], f[4], f[5], f[6], f[7], f[0]) for f in filas])
        return len(filas)

    def guardar_obs(self, registros):
        """registros: iterable de dicts {estacion_id, fecha, fuente, <variables>}.
        Un valor nuevo no nulo sustituye al anterior; un nulo no borra un dato previo."""
        t = ahora_utc().isoformat(timespec="seconds")
        cols = ["estacion_id", "fecha"] + VARIABLES + ["fuente", "insertado"]
        filas = []
        for r in registros:
            filas.append([r["estacion_id"], r["fecha"]] + [r.get(v) for v in VARIABLES]
                         + [r.get("fuente"), t])
        if not filas:
            return 0
        ins = (f"INSERT OR IGNORE INTO obs ({','.join(cols)}) "
               f"VALUES ({','.join('?' * len(cols))})")
        upd = ("UPDATE obs SET " + ", ".join(f"{v}=COALESCE(?, {v})" for v in VARIABLES)
               + ", insertado=? WHERE estacion_id=? AND fecha=?")
        with _lock, self._con() as c:
            c.executemany(ins, filas)
            c.executemany(upd, [f[2:2 + len(VARIABLES)] + [t, f[0], f[1]] for f in filas])
        return len(filas)

    def guardar_resumen(self, filas):
        """Filas de resumen diario (p. ej. los diarios oficiales de AgroCabildo)."""
        cols = ["estacion_id", "dia", "tmed", "tmax", "tmin", "hrmed", "prec", "vvmed", "racha", "radmed", "n_horas"]
        datos = [[f.get(c) for c in cols] for f in filas]
        if not datos:
            return 0
        with _lock, self._con() as c:
            c.executemany(f"INSERT OR REPLACE INTO resumen_diario ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", datos)
        return len(datos)

    def hay_obs_de(self, prefijo):
        with self._con() as c:
            return c.execute("SELECT 1 FROM obs WHERE estacion_id LIKE ? LIMIT 1", (prefijo + "%",)).fetchone() is not None

    def log(self, tarea, fuente, ok, n=0, mensaje=""):
        with _lock, self._con() as c:
            c.execute("INSERT INTO registro (momento,tarea,fuente,ok,n,mensaje) VALUES (?,?,?,?,?,?)",
                      (ahora_utc().isoformat(timespec="seconds"), tarea, fuente, int(bool(ok)), n,
                       (mensaje or "")[:1000]))

    # ------------------------------------------------------------------ lectura
    def estaciones(self, solo_con_coord=True):
        with self._con() as c:
            q = "SELECT * FROM estaciones"
            if solo_con_coord:
                q += " WHERE lat IS NOT NULL AND lon IS NOT NULL"
            return [dict(r) for r in c.execute(q + " ORDER BY fuente, nombre")]

    def ventana(self, horas=48, hasta=None):
        """Todas las observaciones de las últimas `horas` horas (para el mapa y la reproducción)."""
        hasta = hasta or ahora_utc()
        desde = iso_hora(hasta - timedelta(hours=horas))
        with self._con() as c:
            filas = c.execute(
                f"SELECT estacion_id, fecha, {','.join(VARIABLES)} FROM obs "
                "WHERE fecha >= ? ORDER BY fecha", (desde,)).fetchall()
        return [dict(r) for r in filas]

    def serie(self, estacion_id, desde, hasta=None):
        hasta = hasta or "9999"
        with self._con() as c:
            filas = c.execute(
                f"SELECT fecha, {','.join(VARIABLES)} FROM obs WHERE estacion_id=? "
                "AND fecha>=? AND fecha<=? ORDER BY fecha", (estacion_id, desde, hasta)).fetchall()
        return [dict(r) for r in filas]

    def serie_diaria(self, estacion_id, desde):
        with self._con() as c:
            filas = c.execute("SELECT * FROM resumen_diario WHERE estacion_id=? AND dia>=? ORDER BY dia",
                              (estacion_id, desde)).fetchall()
        return [dict(r) for r in filas]

    def estado(self):
        with self._con() as c:
            n_est = c.execute("SELECT COUNT(*) FROM estaciones").fetchone()[0]
            n_obs = c.execute("SELECT COUNT(*) FROM obs").fetchone()[0]
            rango = c.execute("SELECT MIN(fecha), MAX(fecha) FROM obs").fetchone()
            por_fuente = {r[0]: r[1] for r in c.execute(
                "SELECT e.fuente, MAX(o.fecha) FROM obs o JOIN estaciones e ON e.id=o.estacion_id "
                "GROUP BY e.fuente")}
            ult = [dict(r) for r in c.execute(
                "SELECT momento,tarea,fuente,ok,n,mensaje FROM registro ORDER BY id DESC LIMIT 12")]
            ult_ok = c.execute("SELECT MAX(momento) FROM registro WHERE tarea='actualizar' AND ok=1"
                               ).fetchone()[0]
        return {"n_estaciones": n_est, "n_obs": n_obs, "primera_obs": rango[0],
                "ultima_obs": rango[1], "ultima_obs_por_fuente": por_fuente,
                "ultima_actualizacion": ult_ok, "registro": ult}

    # ------------------------------------------------------------------ consolidación diaria
    def consolidar_dia(self, dia, carpeta_csv):
        """Calcula el resumen diario de `dia` ('YYYY-MM-DD', UTC) y exporta un CSV con
        todas las observaciones horarias de ese día. Devuelve (n_obs, ruta_csv)."""
        ini = f"{dia}T01:00Z"   # la hora 01:00 cierra el intervalo 00-01
        d1 = (datetime.strptime(dia, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        fin = f"{d1}T00:00Z"
        with self._con() as c:
            filas = c.execute(
                f"SELECT o.estacion_id, e.fuente, e.nombre, e.lat, e.lon, e.alt, o.fecha, "
                f"{','.join('o.' + v for v in VARIABLES)} FROM obs o "
                "LEFT JOIN estaciones e ON e.id=o.estacion_id "
                "WHERE o.fecha>=? AND o.fecha<=? ORDER BY o.estacion_id, o.fecha",
                (ini, fin)).fetchall()
            resumen = c.execute(
                """SELECT estacion_id, AVG(ta), MAX(COALESCE(tamax, ta)), MIN(COALESCE(tamin, ta)),
                          AVG(hr), SUM(prec), AVG(vv), MAX(COALESCE(vmax, vv)), AVG(rad), COUNT(*)
                   FROM obs WHERE fecha>=? AND fecha<=? GROUP BY estacion_id""",
                (ini, fin)).fetchall()
        with _lock, self._con() as c:
            c.executemany(
                "INSERT OR REPLACE INTO resumen_diario VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(r[0], dia, *[None if x is None else round(x, 2) for x in r[1:9]], r[9])
                 for r in resumen])
        ruta = None
        if filas:
            sub = os.path.join(carpeta_csv, dia[:4])
            os.makedirs(sub, exist_ok=True)
            ruta = os.path.join(sub, f"{dia}.csv")
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(filas[0].keys())
                for r in filas:
                    w.writerow(list(r))
        return len(filas), ruta
