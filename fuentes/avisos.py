"""
Avisos meteorológicos de AEMET (Meteoalerta) para la isla de Tenerife.

Endpoint: /api/avisos_cap/ultimoelaborado/area/65   (65 = Canarias)
  → devuelve la URL de "datos": un .tar con un XML CAP 1.2 por aviso (a veces un único XML).
Cada <info> trae nivel (verde/amarillo/naranja/rojo), fenómeno, zona (areaDesc), onset y expires.
Se filtran las zonas cuyo nombre contiene "Tenerife" (Norte, Área metropolitana, Cumbres,
Este-sur-oeste y sus litorales) y los avisos que no han caducado.
"""
import io
import tarfile
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .comun import http_get, http_json

BASE = "https://opendata.aemet.es/opendata/api"
AREA_CANARIAS = "65"
URL_WEB = "https://www.aemet.es/es/eltiempo/prediccion/avisos?k=coo"
NS = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}
NIVELES = ["verde", "amarillo", "naranja", "rojo"]


def _fecha(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _xmls(raw):
    """El fichero de datos puede ser un tar (con o sin gzip) o un XML suelto."""
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as tar:
            for m in tar.getmembers():
                if m.isfile() and m.name.lower().endswith(".xml"):
                    yield tar.extractfile(m).read()
        return
    except tarfile.TarError:
        pass
    if raw.lstrip().startswith(b"<"):
        yield raw


def _parse(xml, ahora):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    if (root.findtext("c:status", "", NS) or "").lower() != "actual":
        return []
    if (root.findtext("c:msgType", "", NS) or "").lower() == "cancel":
        return []
    out = []
    for info in root.findall("c:info", NS):
        if not (info.findtext("c:language", "es", NS) or "es").lower().startswith("es"):
            continue
        par = {p.findtext("c:valueName", "", NS): p.findtext("c:value", "", NS)
               for p in info.findall("c:parameter", NS)}
        nivel = (par.get("AEMET-Meteoalerta nivel") or "").strip().lower()
        if nivel not in NIVELES[1:]:
            continue
        inicio = _fecha(info.findtext("c:onset", "", NS) or info.findtext("c:effective", "", NS))
        fin = _fecha(info.findtext("c:expires", "", NS))
        if fin and fin <= ahora:
            continue
        fen = par.get("AEMET-Meteoalerta fenomeno") or info.findtext("c:event", "", NS) or ""
        fen = fen.split(";")[1] if ";" in fen else fen
        for area in info.findall("c:area", NS):
            zona = area.findtext("c:areaDesc", "", NS) or ""
            if "tenerife" not in zona.lower():
                continue
            out.append({
                "nivel": nivel, "fenomeno": fen.strip(), "zona": zona.strip(),
                "inicio": inicio.isoformat(timespec="minutes") if inicio else None,
                "fin": fin.isoformat(timespec="minutes") if fin else None,
                "activo": bool((inicio is None or inicio <= ahora) and (fin is None or fin > ahora)),
                "texto": (info.findtext("c:description", "", NS) or "").strip()[:400],
            })
    return out


def resumen(avisos, ahora=None, url=URL_WEB, error=None):
    ahora = ahora or datetime.now(timezone.utc)
    vistos, unicos = set(), []
    for a in avisos:
        k = (a["zona"], a["fenomeno"], a["nivel"], a["inicio"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(a)
    unicos.sort(key=lambda a: (-NIVELES.index(a["nivel"]), a["inicio"] or ""))
    maxi = lambda lst: max((NIVELES.index(a["nivel"]) for a in lst), default=0)
    return {
        "ok": error is None,
        "error": error,
        "nivel": NIVELES[maxi(unicos)] if error is None else None,          # máximo en vigor o previsto
        "nivel_ahora": NIVELES[maxi([a for a in unicos if a["activo"]])] if error is None else None,
        "avisos": unicos,
        "url": url,
        "actualizado": ahora.isoformat(timespec="seconds"),
    }


def descargar(api_key, url_web=URL_WEB, area=AREA_CANARIAS):
    """Devuelve el resumen de avisos de Tenerife. Nunca lanza: si falla, ok=False."""
    ahora = datetime.now(timezone.utc)
    try:
        if not api_key or api_key.startswith("PON_AQUI"):
            raise RuntimeError("falta la API key de AEMET")
        try:
            meta = http_json(f"{BASE}/avisos_cap/ultimoelaborado/area/{area}",
                             headers={"api_key": api_key, "cache-control": "no-cache"}, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code == 404:                  # "no hay datos que satisfagan esos criterios"
                return resumen([], ahora, url_web)
            raise
        if meta.get("estado") == 404:          # AEMET responde 404 cuando no hay ningún aviso emitido
            return resumen([], ahora, url_web)
        if meta.get("estado") != 200 or "datos" not in meta:
            raise RuntimeError(f"AEMET estado={meta.get('estado')}: {meta.get('descripcion')}")
        raw = http_get(meta["datos"], timeout=60)
        avisos = [a for x in _xmls(raw) for a in _parse(x, ahora)]
        return resumen(avisos, ahora, url_web)
    except Exception as e:  # noqa: BLE001 — el visor debe seguir publicándose
        return resumen([], ahora, url_web, error=str(e)[:200])
