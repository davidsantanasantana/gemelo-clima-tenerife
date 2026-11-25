/* =====================================================================
   Gemelo climático de Tenerife — visor
   ===================================================================== */
(function () {
  "use strict";
  const G = window.Graficos;
  const LAPSE = 0.0065;              // °C/m (atmósfera estándar)
  const MS_H = 36e5;

  // ------------------------------------------------------------------ variables y escalas
  const RAMPAS = {
    temp: ["#2a2f86", "#2f6fd0", "#3fb6d6", "#8fe0a6", "#efe26a", "#f4a641", "#e0553a", "#9e1a58"],
    hr: ["#8a5426", "#d6ab68", "#e9e2b7", "#9fd3c0", "#4aa6c8", "#20589a"],
    prec: ["#c9ecf7", "#6ab8ea", "#2f6ad3", "#5a3bc4", "#b33bb3", "#f05a9a"],
    viento: ["#e8f2f1", "#a6dcc6", "#5fbf9b", "#f0d264", "#ef8a3a", "#c8303f", "#7d1844"],
    pres: ["#3b2a6b", "#3b5f9e", "#2f9c95", "#7cc76b", "#e4dd5a"],
    rad: ["#1d2142", "#5b2f7a", "#a63e7c", "#ec6a45", "#f7b843", "#fff3b0"],
  };
  const VARS = {
    ta:     { n: "Temperatura", u: "°C", r: "temp", dom: [-2, 32], dec: 1, sup: true, lapse: true },
    hr:     { n: "Humedad", u: "%", r: "hr", dom: [10, 100], dec: 0, sup: true },
    prec:   { n: "Precip. 1 h", u: "mm", r: "prec", dom: [0, 15], dec: 1, sup: true, raiz: true, umbral: 0.1 },
    prec24: { n: "Precip. 24 h", u: "mm", r: "prec", dom: [0, 80], dec: 1, sup: true, raiz: true, umbral: 0.1 },
    vv:     { n: "Viento medio", u: "km/h", r: "viento", dom: [0, 60], dec: 0, sup: true, k: 3.6 },
    vmax:   { n: "Racha", u: "km/h", r: "viento", dom: [0, 100], dec: 0, sup: true, k: 3.6 },
    pres:   { n: "Presión est.", u: "hPa", r: "pres", dom: [760, 1025], dec: 1, sup: false },
    rad:    { n: "Radiación", u: "W/m²", r: "rad", dom: [0, 1000], dec: 0, sup: true },
  };
  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const RGB = Object.fromEntries(Object.entries(RAMPAS).map(([k, v]) => [k, v.map(hex)]));

  function colorRGB(vari, v) {
    const c = VARS[vari], ramp = RGB[c.r];
    let t = (v - c.dom[0]) / (c.dom[1] - c.dom[0]);
    t = Math.max(0, Math.min(1, t));
    if (c.raiz) t = Math.sqrt(t);
    const p = t * (ramp.length - 1), i = Math.min(ramp.length - 2, Math.floor(p)), f = p - i;
    const a = ramp[i], b = ramp[i + 1];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }
  const css = rgb => `rgb(${rgb.map(Math.round).join(",")})`;
  const fmt = (vari, v) => v == null ? "—" : v.toFixed(VARS[vari].dec).replace(".", ",");

  // ------------------------------------------------------------------ estado
  const S = {
    vari: "ta", idx: 0, horas: [], porHora: new Map(), porEst: new Map(), est: new Map(),
    fuentesOcultas: new Set(), jugando: null, ultimaAct: null, ultimaObs: null,
    sel: null, diasCajon: 7, modo: "real", horasVisor: 72,
  };
  const $ = id => document.getElementById(id);

  // ------------------------------------------------------------------ acceso a datos
  // Modo local (gemelo.py): API /api/...   ·   Modo nube/app (GitHub Pages): JSON en data/
  const EST = !!(window.GEMELO && window.GEMELO.estatico);
  const json = (u, opc) => fetch(u, opc).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
  const fresco = u => `${u}?t=${Date.now()}`;               // evita cachés intermedias
  const cacheSeries = new Map();
  const DATOS = {
    config: () => EST ? Promise.resolve({ horas_visor: window.GEMELO.horasVisor || 72 }) : json("/api/config"),
    estado: () => EST ? json(fresco("data/estado.json")) : json("/api/estado"),
    ventana: h => EST ? json(fresco("data/ventana.json")) : json(`/api/ventana?horas=${h}`),
    isla: () => EST ? json("data/isla.geojson") : json("/api/isla"),
    capas: url => EST ? json("data/wms_capas.json").then(m => m[url] || []) : json(`/api/wms_capas?url=${encodeURIComponent(url)}`),
    async serie(id, dias) {
      if (!EST) return json(`/api/serie?id=${encodeURIComponent(id)}&dias=${dias}`);
      let s = cacheSeries.get(id);
      if (!s) { s = await json(fresco(`data/series/${id.replace(":", "_")}.json`)); cacheSeries.set(id, s); }
      const lim = Date.now() - dias * 864e5;
      if (dias > 31) return { escala: "diaria", datos: s.diaria.filter(r => Date.parse(r.dia + "T12:00:00Z") >= lim) };
      const h = s.horaria, datos = [];
      h.fecha.forEach((f, i) => {
        if (Date.parse(f) < lim) return;
        const r = { fecha: f };
        for (const k in h) if (k !== "fecha") r[k] = h[k][i];
        datos.push(r);
      });
      return { escala: "horaria", datos };
    },
  };
  async function descargarCSV(id, dias) {
    const r = await DATOS.serie(id, dias);
    const cols = r.escala === "diaria" ? ["dia", "tmed", "tmax", "tmin", "hrmed", "prec", "vvmed", "racha", "radmed"]
      : ["fecha", "ta", "tamax", "tamin", "hr", "prec", "vv", "dv", "vmax", "dmax", "pres", "rad"];
    const txt = "\ufeff" + cols.join(";") + "\n" + r.datos.map(f => cols.map(c => f[c] ?? "").join(";")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([txt], { type: "text/csv" }));
    a.download = `${id.replace(":", "_")}_${dias}d_${r.escala}.csv`;
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ------------------------------------------------------------------ mapa
  const mapa = L.map("mapa", { zoomControl: true, minZoom: 8, maxZoom: 16, preferCanvas: false,
    zoomSnap: 1 }).setView([28.29, -16.58], 10);
  mapa.getContainer().classList.add("atenuado");
  mapa.createPane("superficie").style.zIndex = 350;

  // ---- Fondos WMS oficiales: CNIG/IGN y GRAFCAN. Los nombres de capa se confirman leyendo
  //      GetCapabilities a través del servidor local (/api/wms_capas); si falla se usa el preferido.
  const FONDOS = {
    ign_base:   { n: "IGN Base", g: "CNIG / IGN", url: "https://www.ign.es/wms-inspire/ign-base", capas: ["IGNBaseTodo"], fmt: "image/png", atr: "© CNIG – Instituto Geográfico Nacional (CC BY 4.0)" },
    ign_mtn:    { n: "Mapa ráster MTN", g: "CNIG / IGN", url: "https://www.ign.es/wms-inspire/mapa-raster", capas: ["mtn_rasterizado"], fmt: "image/png", atr: "© CNIG – Instituto Geográfico Nacional (CC BY 4.0)" },
    ign_pnoa:   { n: "Ortofoto PNOA máx. actualidad", g: "CNIG / IGN", url: "https://www.ign.es/wms-inspire/pnoa-ma", capas: ["OI.OrthoimageCoverage"], fmt: "image/jpeg", atr: "PNOA © CNIG – Instituto Geográfico Nacional (CC BY 4.0)" },
    ign_mdt:    { n: "Relieve (MDT)", g: "CNIG / IGN", url: "https://servicios.idee.es/wms-inspire/mdt", capas: ["Relieve", "EL.GridCoverage"], fmt: "image/png", atr: "MDT © CNIG – Instituto Geográfico Nacional (CC BY 4.0)" },
    gc_mti:     { n: "Mapa Topográfico Integrado", g: "GRAFCAN", url: "https://idecan2.grafcan.es/ServicioWMS/MTI", capas: ["WMS_MTI", "MTI"], fmt: "image/png", atr: "© GRAFCAN – IDECanarias" },
    gc_orto:    { n: "OrtoExpress", g: "GRAFCAN", url: "https://idecan1.grafcan.es/ServicioWMS/OrtoExpress", capas: ["ortoexpress"], fmt: "image/jpeg", atr: "OrtoExpress © GRAFCAN – IDECanarias" },
    gc_sombras: { n: "Sombreado del relieve", g: "GRAFCAN", url: "https://idecan1.grafcan.es/ServicioWMS/MDSombras", capas: ["WMS_HS", "sombras"], fmt: "image/png", atr: "© GRAFCAN – IDECanarias" },
  };
  const ATR_EXTRA = " · Contorno insular: GRAFCAN · MDT para interpolación: AWS Terrain Tiles · Datos: AEMET, AgroCabildo (Cabildo de Tenerife)";
  let capaFondo = null, limitesIsla = null;

  async function resolverCapa(f) {
    if (f.resuelta) return f.resuelta;
    try {
      const capas = await DATOS.capas(f.url).catch(() => []);
      if (Array.isArray(capas) && capas.length) {
        const low = capas.map(c => c.nombre.toLowerCase());
        const pref = f.capas.find(c => low.includes(c.toLowerCase()));
        f.resuelta = pref ? capas[low.indexOf(pref.toLowerCase())].nombre : capas[0].nombre;
        return f.resuelta;
      }
    } catch { }
    return f.capas[0];
  }

  async function ponerFondo(k) {
    const f = FONDOS[k];
    const capa = await resolverCapa(f);
    if (capaFondo) mapa.removeLayer(capaFondo);
    capaFondo = L.tileLayer.wms(f.url, {
      layers: capa, format: f.fmt, transparent: false, version: "1.1.1", styles: "",
      attribution: f.atr + ATR_EXTRA, className: "capa-fondo", maxZoom: 19,
      bounds: limitesIsla || undefined,
    }).addTo(mapa);
    capaFondo.on("tileerror", () => $("sel-fondo").classList.add("con-error"));
    capaFondo.on("load", () => $("sel-fondo").classList.remove("con-error"));
  }

  function construirSelectorFondo() {
    const sel = $("sel-fondo");
    const grupos = {};
    for (const [k, f] of Object.entries(FONDOS)) (grupos[f.g] = grupos[f.g] || []).push(`<option value="${k}">${f.n}</option>`);
    sel.innerHTML = Object.entries(grupos).map(([g, o]) => `<optgroup label="${g}">${o.join("")}</optgroup>`).join("");
    sel.value = "ign_base";
  }

  // ---- Contorno de Tenerife: máscara exterior (oculta mar y resto de islas) + borde
  mapa.createPane("mascara").style.zIndex = 340;
  mapa.createPane("borde").style.zIndex = 430;
  mapa.getPane("borde").style.pointerEvents = "none";
  let anillosIsla = null;         // [[ [lat, lon], ... ], ...]
  async function cargarIsla() {
    let anillos;
    try {
      const gj = await DATOS.isla();
      anillos = gj.features.flatMap(f => (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates)
        .map(pol => pol[0].map(([lon, lat]) => [lat, lon])));
    } catch {
      anillos = [[[27.98, -16.95], [28.62, -16.95], [28.62, -16.10], [27.98, -16.10]]];   // provisional
      mostrarAviso("No se pudo cargar el contorno de Tenerife (GRAFCAN): se recorta por rectángulo.");
    }
    anillosIsla = anillos;
    const mundo = [[-89, -179], [-89, 179], [89, 179], [89, -179]];
    L.polygon([mundo, ...anillos], { pane: "mascara", stroke: false, fillColor: "#0d1117", fillOpacity: 1, interactive: false }).addTo(mapa);
    L.polygon(anillos, { pane: "borde", fill: false, color: "#e6edf3", weight: 1.6, opacity: .9, interactive: false }).addTo(mapa);
    L.polygon(anillos, { pane: "borde", fill: false, color: "#000", weight: 4, opacity: .35, interactive: false }).addTo(mapa).bringToBack();
    const b = L.latLngBounds(anillos.flat());
    limitesIsla = b.pad(0.04);
    mapa.setMaxBounds(b.pad(0.25));
    mapa.fitBounds(b, { padding: [10, 10] });
    mapa.setMinZoom(Math.max(8, mapa.getZoom() - 1));
  }
  function mostrarAviso(t) { const av = $("aviso"); av.textContent = t; av.classList.remove("oculto"); setTimeout(() => av.classList.add("oculto"), 8000); }

  // ------------------------------------------------------------------ DEM (Terrarium) para máscara, lapse rate y sombreado
  const DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
  const demCache = new Map();
  let demDisponible = true;
  function obtenerDEM(z, x, y) {
    const k = `${z}/${x}/${y}`;
    if (demCache.has(k)) return demCache.get(k);
    const p = new Promise(res => {
      if (!demDisponible) return res(null);
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        try {
          const c = document.createElement("canvas"); c.width = c.height = 256;
          const cx = c.getContext("2d"); cx.drawImage(img, 0, 0);
          const d = cx.getImageData(0, 0, 256, 256).data, e = new Float32Array(65536);
          for (let i = 0; i < 65536; i++) e[i] = d[i * 4] * 256 + d[i * 4 + 1] + d[i * 4 + 2] / 256 - 32768;
          res(e);
        } catch (err) { demDisponible = false; res(null); }
      };
      img.onerror = () => res(null);
      img.src = DEM_URL.replace("{z}", z).replace("{x}", x).replace("{y}", y);
    });
    demCache.set(k, p);
    return p;
  }

  // ------------------------------------------------------------------ capa de superficie interpolada
  const CapaSuperficie = L.GridLayer.extend({
    createTile(coords, done) {
      const tile = document.createElement("canvas");
      tile.width = tile.height = 256;
      obtenerDEM(coords.z, coords.x, coords.y).then(dem => {
        try { pintarTesela(tile, coords, dem); } catch (e) { console.error(e); }
        done(null, tile);
      });
      return tile;
    },
  });
  const superficie = new CapaSuperficie({ pane: "superficie", opacity: 0.72, maxNativeZoom: 13, minZoom: 8, updateWhenZooming: false, keepBuffer: 1 });
  superficie.addTo(mapa);

  function puntosActuales() {
    const out = [];
    for (const e of S.est.values()) {
      if (S.fuentesOcultas.has(e.fuente)) continue;
      const r = valor(e.id, S.idx, S.vari);
      if (r.v == null) continue;
      out.push({ e, v: r.v });
    }
    return out;
  }

  function pintarTesela(tile, coords, dem) {
    const cfg = VARS[S.vari];
    if (!$("chk-superficie").checked || !cfg.sup) return;
    const pts = puntosActuales();
    if (pts.length < 3) return;
    const z = coords.z, ox = coords.x * 256, oy = coords.y * 256;
    const lapse = cfg.lapse && $("chk-lapse").checked;
    const relieve = $("chk-relieve").checked && dem;
    const P = pts.map(p => {
      const q = mapa.project([p.e.lat, p.e.lon], z);
      return { x: q.x - ox, y: q.y - oy, v: lapse ? p.v + LAPSE * (p.e.alt || 0) : p.v, alt: p.e.alt || 0 };
    });
    const ctx = tile.getContext("2d");
    const img = ctx.createImageData(256, 256), D = img.data;
    const paso = z >= 12 ? 2 : 4;
    const latC = mapa.unproject([ox + 128, oy + 128], z).lat;
    const mpp = 156543.03392 * Math.cos(latC * Math.PI / 180) / Math.pow(2, z);   // m/píxel
    const radioPx = 12000 / mpp;   // sin DEM: no extrapolar más de 12 km
    const Lpx = 15000 / mpp;
    const az = 315 * Math.PI / 180, alt = 45 * Math.PI / 180;
    for (let py = 0; py < 256; py += paso) {
      for (let px = 0; px < 256; px += paso) {
        const cx = px + paso / 2, cy = py + paso / 2;
        let elev = null;
        if (dem) {
          elev = dem[(cy | 0) * 256 + (cx | 0)];
          if (!anillosIsla && elev <= 0.5) continue;     // mar (si no hay contorno insular)
          if (elev < 0) elev = 0;
        }
        let sw = 0, sv = 0, sa = 0, dmin = Infinity;
        for (let i = 0; i < P.length; i++) {
          const dx = P[i].x - cx, dy = P[i].y - cy;
          const d2 = dx * dx + dy * dy + 1;
          if (d2 < dmin) dmin = d2;
          const w = Math.exp(-Math.sqrt(d2) / Lpx) / d2;   // IDW (p=2) con decaimiento a ~15 km
          sw += w; sv += w * P[i].v; sa += w * P[i].alt;
        }
        if (!dem && !anillosIsla && Math.sqrt(dmin) > radioPx) continue;
        if (!(sw > 0)) continue;
        let v = sv / sw;
        if (lapse) v -= LAPSE * (elev != null ? elev : sa / sw);
        if (cfg.umbral && v < cfg.umbral) continue;
        let [r, g, b] = colorRGB(S.vari, v);
        if (relieve) {
          const xa = Math.max(0, cx - paso) | 0, xb = Math.min(255, cx + paso) | 0;
          const ya = Math.max(0, cy - paso) | 0, yb = Math.min(255, cy + paso) | 0;
          const dzdx = (dem[(cy | 0) * 256 + xb] - dem[(cy | 0) * 256 + xa]) / ((xb - xa) * mpp);
          const dzdy = (dem[yb * 256 + (cx | 0)] - dem[ya * 256 + (cx | 0)]) / ((yb - ya) * mpp);
          const pend = Math.atan(1.6 * Math.hypot(dzdx, dzdy));
          const asp = Math.atan2(dzdy, -dzdx);
          let sh = Math.sin(alt) * Math.cos(pend) + Math.cos(alt) * Math.sin(pend) * Math.cos(az - Math.PI / 2 - asp);
          sh = 0.55 + 0.6 * Math.max(0, sh);
          r *= sh; g *= sh; b *= sh;
        }
        for (let yy = py; yy < py + paso; yy++) {
          for (let xx = px; xx < px + paso; xx++) {
            const o = (yy * 256 + xx) * 4;
            D[o] = r; D[o + 1] = g; D[o + 2] = b; D[o + 3] = 255;
          }
        }
      }
    }
    if (!anillosIsla) { ctx.putImageData(img, 0, 0); return; }
    // recorte exacto a la línea de costa de Tenerife
    const tmp = document.createElement("canvas"); tmp.width = tmp.height = 256;
    tmp.getContext("2d").putImageData(img, 0, 0);
    ctx.save(); ctx.beginPath();
    for (const an of anillosIsla) {
      an.forEach((ll, i) => { const q = mapa.project(ll, z); i ? ctx.lineTo(q.x - ox, q.y - oy) : ctx.moveTo(q.x - ox, q.y - oy); });
      ctx.closePath();
    }
    ctx.clip(); ctx.drawImage(tmp, 0, 0); ctx.restore();
  }

  // ------------------------------------------------------------------ datos
  function valor(id, idx, vari) {
    const lista = S.porEst.get(id);
    if (!lista || !S.horas.length) return { v: null };
    const t = S.horas[idx];
    if (vari === "prec24") {
      let s = 0, n = 0;
      for (const o of lista) {
        if (o.t > t - 24 * MS_H && o.t <= t && o.prec != null) { s += o.prec; n++; }
      }
      return n ? { v: s, n } : { v: null };
    }
    const k = VARS[vari].k || 1;
    const o = S.porHora.get(t)?.get(id);
    if (o && o[vari] != null) return { v: o[vari] * k, dv: o.dv };
    if (idx === S.horas.length - 1) {                // tiempo real: último dato en 3 h
      for (let j = lista.length - 1; j >= 0; j--) {
        const p = lista[j];
        if (p.t < t - 3 * MS_H) break;
        if (p.t <= t && p[vari] != null) return { v: p[vari] * k, dv: p.dv, viejo: true, t: p.t };
      }
    }
    return { v: null };
  }

  async function cargarVentana(irAlFinal) {
    const r = await DATOS.ventana(S.horasVisor);
    const estabaAlFinal = irAlFinal || S.idx >= S.horas.length - 1;
    S.est = new Map(r.estaciones.map(e => [e.id, e]));
    S.porHora = new Map(); S.porEst = new Map();
    const set = new Set();
    for (const o of r.obs) {
      o.t = Date.parse(o.fecha);
      set.add(o.t);
      if (!S.porHora.has(o.t)) S.porHora.set(o.t, new Map());
      S.porHora.get(o.t).set(o.estacion_id, o);
      if (!S.porEst.has(o.estacion_id)) S.porEst.set(o.estacion_id, []);
      S.porEst.get(o.estacion_id).push(o);
    }
    S.horas = [...set].sort((a, b) => a - b);
    const rng = $("rng-tiempo");
    rng.max = Math.max(0, S.horas.length - 1);
    if (estabaAlFinal) S.idx = S.horas.length - 1;
    S.idx = Math.min(S.idx, S.horas.length - 1);
    rng.value = S.idx;
    construirFiltroFuentes();
    construirMarcadores();
    const ultH = S.horas[S.horas.length - 1];
    $("st-activas").textContent = ultH ? `${S.porHora.get(ultH)?.size || 0} / ${S.est.size}` : "—";
    render();
    if (S.sel) abrirCajon(S.sel, true);
  }

  // ------------------------------------------------------------------ marcadores
  const capaMarc = L.layerGroup().addTo(mapa);
  const marcadores = new Map();
  function construirMarcadores() {
    capaMarc.clearLayers(); marcadores.clear();
    for (const e of S.est.values()) {
      const m = L.marker([e.lat, e.lon], { icon: L.divIcon({ className: "", html: "" }), riseOnHover: true });
      m.on("click", () => abrirCajon(e.id));
      m.bindTooltip("", { direction: "top", offset: [0, -8] });
      marcadores.set(e.id, m);
    }
  }

  function flechaSVG(dir, color) {
    // dirección meteorológica = de dónde viene → la flecha apunta hacia donde va
    return `<svg class="fl" viewBox="-16 -16 32 32"><g transform="rotate(${(dir + 180) % 360})">
      <path d="M0,-13 L5,-3 L1.6,-4 L1.6,9 L-1.6,9 L-1.6,-4 L-5,-3 Z" fill="${color}" stroke="#000" stroke-width=".8" opacity=".95"/></g></svg>`;
  }

  function renderMarcadores() {
    const etiquetas = $("chk-etiquetas").checked;
    const flechas = $("chk-flechas").checked && (S.vari === "vv" || S.vari === "vmax");
    for (const [id, m] of marcadores) {
      const e = S.est.get(id);
      if (S.fuentesOcultas.has(e.fuente)) { capaMarc.removeLayer(m); continue; }
      capaMarc.addLayer(m);
      const r = valor(id, S.idx, S.vari);
      const sin = r.v == null;
      const col = sin ? "#555" : css(colorRGB(S.vari, r.v));
      const cls = ["mk", e.fuente === "AGROCABILDO" ? "agro" : "", sin ? "sin" : "", r.viejo ? "viejo" : ""].join(" ");
      let html = `<div class="${cls}">`;
      if (flechas && !sin && r.dv != null && r.v > 1) html += flechaSVG(r.dv, col);
      else html += `<div class="p" style="background:${col}"></div>`;
      if (etiquetas && !sin) html += `<div class="val">${fmt(S.vari, r.v)}</div>`;
      html += "</div>";
      m.setIcon(L.divIcon({ className: "", html, iconSize: [0, 0] }));
      const hace = r.viejo ? ` <span style="color:#e3a33b">(${G.fmtHora.format(r.t)})</span>` : "";
      m.setTooltipContent(`<b>${e.nombre}</b> <span style="color:#8b98a8">· ${e.fuente} · ${Math.round(e.alt ?? 0)} m</span><br>${VARS[S.vari].n}: <b>${fmt(S.vari, r.v)} ${VARS[S.vari].u}</b>${hace}`);
    }
  }

  // ------------------------------------------------------------------ paneles
  function construirSelector() {
    for (const cont of [$("selector-variable"), $("chips")]) {
      cont.innerHTML = "";
      for (const [k, c] of Object.entries(VARS)) {
        const b = document.createElement("button");
        b.textContent = c.n; b.dataset.v = k;
        b.onclick = () => { S.vari = k; render(true); b.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" }); };
        cont.appendChild(b);
      }
    }
  }

  function construirFiltroFuentes() {
    const fuentes = [...new Set([...S.est.values()].map(e => e.fuente))].sort();
    const cont = $("filtro-fuentes");
    cont.innerHTML = "Fuentes: " + fuentes.map(f => {
      const n = [...S.est.values()].filter(e => e.fuente === f).length;
      return `<label><input type="checkbox" data-f="${f}" ${S.fuentesOcultas.has(f) ? "" : "checked"}> ${f} <small>(${n})</small></label>`;
    }).join(" ");
    cont.querySelectorAll("input").forEach(i => i.onchange = () => {
      i.checked ? S.fuentesOcultas.delete(i.dataset.f) : S.fuentesOcultas.add(i.dataset.f);
      render(true);
    });
  }

  function renderLeyenda() {
    const c = VARS[S.vari], ramp = RAMPAS[c.r];
    const marcas = [0, .25, .5, .75, 1].map(t => {
      const tt = c.raiz ? t * t : t;
      return c.dom[0] + (c.dom[1] - c.dom[0]) * tt;
    });
    let nota = "";
    if (S.vari === "ta" && $("chk-lapse").checked) nota = "Superficie reducida con −6,5 °C/km sobre el MDT";
    if (!c.sup) nota = "Sin superficie: la presión en estación depende de la cota";
    if (S.vari === "vmax" || S.vari === "vv") nota = "AgroCabildo: racha ≈ máx. de medias diezminutales";
    $("leyenda").innerHTML = `<b>${c.n}</b> <span style="color:#8b98a8">(${c.u})</span>
      <div class="barra" style="background:linear-gradient(90deg,${ramp.join(",")})"></div>
      <div class="marcas">${marcas.map(v => `<span>${Math.round(v)}</span>`).join("")}</div>
      ${nota ? `<div style="color:#8b98a8;margin-top:4px;font-size:10.5px">${nota}</div>` : ""}
      <div style="color:#8b98a8;margin-top:4px;font-size:10.5px">● AEMET &nbsp; ■ AgroCabildo</div>`;
  }

  function renderKPIs() {
    const c = VARS[S.vari];
    const pts = puntosActuales();
    const cont = $("kpis");
    if (!pts.length) { cont.innerHTML = `<div class="kpi" style="grid-column:span 2"><div class="t">Sin datos</div></div>`; return; }
    const max = pts.reduce((a, b) => b.v > a.v ? b : a), min = pts.reduce((a, b) => b.v < a.v ? b : a);
    const media = pts.reduce((s, p) => s + p.v, 0) / pts.length;
    const k = (t, v, d) => `<div class="kpi"><div class="t">${t}</div><div class="v">${v}</div><div class="d" title="${d}">${d}</div></div>`;
    const u = `<small>${c.u}</small>`;
    let h = k("Máximo", `${fmt(S.vari, max.v)} ${u}`, `${max.e.nombre} · ${Math.round(max.e.alt ?? 0)} m`);
    if (S.vari.startsWith("prec")) {
      const conLluvia = pts.filter(p => p.v >= 0.1).length;
      h += k("Con precipitación", `${conLluvia} <small>/ ${pts.length}</small>`, "estaciones ≥ 0,1 mm");
    } else {
      h += k("Mínimo", `${fmt(S.vari, min.v)} ${u}`, `${min.e.nombre} · ${Math.round(min.e.alt ?? 0)} m`);
    }
    h += k("Media de la red", `${fmt(S.vari, media)} ${u}`, "media simple de estaciones");
    h += k("Estaciones con dato", `${pts.length} <small>/ ${[...S.est.values()].filter(e => !S.fuentesOcultas.has(e.fuente)).length}</small>`, "en la hora seleccionada");
    cont.innerHTML = h;
  }

  function renderPerfil() {
    const pts = puntosActuales();
    const opc = { etiquetaX: VARS[S.vari].u, unidad: VARS[S.vari].u, alClic: p => abrirCajon(p.id) };
    if (S.vari === "ta" && pts.length > 2) {
      const t0 = pts.reduce((s, p) => s + p.v + LAPSE * (p.e.alt || 0), 0) / pts.length;
      opc.lineaRef = [[+(t0).toFixed(1), 0], [+(t0 - LAPSE * 3700).toFixed(1), 3700]];
    }
    G.perfil($("perfil"), pts.map(p => ({ x: +p.v.toFixed(VARS[S.vari].dec), y: p.e.alt, id: p.e.id,
      color: css(colorRGB(S.vari, p.v)), nombre: p.e.nombre, fuente: p.e.fuente })), opc);
  }

  function renderTiempo() {
    const t = S.horas[S.idx];
    if (t == null) { $("lbl-tiempo").textContent = "sin datos"; return; }
    const n = S.porHora.get(t)?.size || 0;
    const fin = S.idx === S.horas.length - 1;
    $("lbl-tiempo").innerHTML = `${G.fmtCompleto.format(t)} <small>h. canaria · ${n} est.${fin ? " · último" : ""}</small>`;
  }

  let temporizadorSup = null;
  function render(cambioVariable) {
    document.querySelectorAll("#selector-variable button, #chips button").forEach(b => b.classList.toggle("activo", b.dataset.v === S.vari));
    $("fila-lapse").style.display = S.vari === "ta" ? "" : "none";
    renderTiempo(); renderMarcadores(); renderLeyenda(); renderKPIs(); renderPerfil();
    clearTimeout(temporizadorSup);
    temporizadorSup = setTimeout(() => superficie.redraw(), cambioVariable ? 0 : 60);
  }

  // ------------------------------------------------------------------ cajón de estación
  async function abrirCajon(id, silencioso) {
    S.sel = id;
    const e = S.est.get(id);
    if (!e) return;
    document.body.classList.remove("panel-abierto");
    $("cajon").classList.remove("oculto");
    setTimeout(() => mapa.invalidateSize(), 50);
    $("cajon-cab").innerHTML = `<h2>${e.nombre}</h2><div class="meta">${e.fuente} · código ${e.codigo} · ${Math.round(e.alt ?? 0)} m · ${e.lat.toFixed(4)}, ${e.lon.toFixed(4)}</div>`;
    const ult = (S.porEst.get(id) || []).slice(-1)[0];
    const celdas = [["ta", "Temp."], ["hr", "Humedad"], ["prec24", "Prec. 24 h"], ["vv", "Viento"], ["vmax", "Racha"], ["pres", "Presión"]];
    $("cajon-actual").innerHTML = celdas.map(([v, t]) => {
      const r = valor(id, S.horas.length - 1, v);
      return `<div><div class="t">${t}</div><div class="v">${fmt(v, r.v)} <small style="font-size:11px;color:#8b98a8">${VARS[v].u}</small></div></div>`;
    }).join("") + (ult ? `<div style="grid-column:span 3;font-size:11px;color:#8b98a8">Último registro: ${G.fmtCompleto.format(ult.t)} (h. canaria)${ult.dv != null ? ` · dir. viento ${Math.round(ult.dv)}°` : ""}</div>` : "");
    $("btn-csv").onclick = ev => { ev.preventDefault(); descargarCSV(id, Math.max(S.diasCajon, 1)); };
    if (!silencioso) document.querySelectorAll(".rango button").forEach(b => b.classList.toggle("activo", +b.dataset.dias === S.diasCajon));
    let r;
    try { r = await DATOS.serie(id, S.diasCajon); } catch { r = { escala: "horaria", datos: [] }; }
    if (S.sel !== id) return;
    const diaria = r.escala === "diaria";
    const T = f => diaria ? Date.parse(f.dia + "T12:00:00Z") : Date.parse(f.fecha);
    const d = r.datos, paso = diaria ? 864e5 : MS_H;
    const s = (campo, k = 1) => d.map(f => [T(f), f[campo] == null ? null : +(f[campo] * k).toFixed(1)]);
    const op = { pasoMs: paso, escalaDiaria: diaria };
    if (diaria) {
      G.serieTemporal($("g-temp"), [
        { nombre: "Máx.", color: "#e0553a", datos: s("tmax"), unidad: "°C" },
        { nombre: "Media", color: "#efe26a", datos: s("tmed"), unidad: "°C" },
        { nombre: "Mín.", color: "#3fb6d6", datos: s("tmin"), unidad: "°C" }], op);
      G.serieTemporal($("g-hr"), [{ nombre: "HR media", color: "#4aa6c8", datos: s("hrmed"), unidad: "%" }], { ...op, minY: 0, maxY: 100 });
      G.serieTemporal($("g-prec"), [{ nombre: "Precipitación", color: "#6ab8ea", datos: s("prec"), unidad: "mm", tipo: "barras" }], { ...op, desdeCero: true, maxY: 1 });
      G.serieTemporal($("g-viento"), [
        { nombre: "Media", color: "#5fbf9b", datos: s("vvmed", 3.6), unidad: "km/h" },
        { nombre: "Racha", color: "#ef8a3a", datos: s("racha", 3.6), unidad: "km/h" }], { ...op, desdeCero: true });
    } else {
      G.serieTemporal($("g-temp"), [{ nombre: "Temperatura", color: "#f4a641", datos: s("ta"), unidad: "°C" }], op);
      G.serieTemporal($("g-hr"), [{ nombre: "HR", color: "#4aa6c8", datos: s("hr"), unidad: "%" }], { ...op, minY: 0, maxY: 100 });
      let acum = 0;
      const acumulada = d.map(f => { acum += f.prec || 0; return [T(f), +acum.toFixed(1)]; });
      G.serieTemporal($("g-prec"), [
        { nombre: "Horaria", color: "#6ab8ea", datos: s("prec"), unidad: "mm", tipo: "barras" },
        { nombre: "Acumulada", color: "#b33bb3", datos: acumulada, unidad: "mm", grosor: 1.2, discontinua: true }], { ...op, desdeCero: true, maxY: 1 });
      G.serieTemporal($("g-viento"), [
        { nombre: "Medio", color: "#5fbf9b", datos: s("vv", 3.6), unidad: "km/h", flechas: d.map(f => [T(f), f.dv, f.vv]) },
        { nombre: "Racha", color: "#ef8a3a", datos: s("vmax", 3.6), unidad: "km/h" }], { ...op, desdeCero: true, alto: 150 });
    }
  }
  $("btn-cerrar").onclick = () => { S.sel = null; $("cajon").classList.add("oculto"); setTimeout(() => mapa.invalidateSize(), 50); };
  document.querySelectorAll(".rango button").forEach(b => b.onclick = () => {
    S.diasCajon = +b.dataset.dias;
    document.querySelectorAll(".rango button").forEach(x => x.classList.toggle("activo", x === b));
    abrirCajon(S.sel, true);
  });

  // ------------------------------------------------------------------ estado / sondeo
  function edad(iso) { return iso ? (Date.now() - Date.parse(iso)) / MS_H : Infinity; }
  async function sondearEstado() {
    let e;
    try { e = await DATOS.estado(); } catch { $("st-ultimo").textContent = "sin conexión"; return; }
    S.modo = e.modo;
    const ins = $("insignia-modo");
    ins.textContent = e.modo === "demo" ? "demo · datos sintéticos" : e.modo === "nube" ? "tiempo real · nube" : "tiempo real";
    ins.className = "insignia " + (e.modo === "demo" ? "demo" : "real");
    $("st-ultimo").textContent = e.ultima_obs ? G.fmtCompleto.format(Date.parse(e.ultima_obs)) : "—";
    $("st-proxima").textContent = e.en_curso ? "descargando…" : (e.proxima_actualizacion ? (EST ? "≈ " : "") + G.fmtHora.format(Date.parse(e.proxima_actualizacion)) : "manual");
    // chips por fuente
    const errores = {};
    for (const r of [...e.registro].reverse()) if (r.tarea === "actualizar") errores[r.fuente] = r.ok ? null : r.mensaje;
    const fuentes = new Set([...Object.keys(e.ultima_obs_por_fuente || {}), ...Object.keys(errores)]);
    $("st-fuentes").innerHTML = [...fuentes].map(f => {
      const h = edad(e.ultima_obs_por_fuente?.[f]);
      const cls = errores[f] ? "ko" : h < 3 ? "ok" : h < 24 ? "viejo" : "ko";
      const t = errores[f] ? `Último intento con error: ${errores[f]}` : `Último dato hace ${h.toFixed(1)} h`;
      return `<span class="chip ${cls}" title="${t.replace(/"/g, "'")}">${f}</span>`;
    }).join("");
    const av = $("aviso");
    if (!e.n_obs) {
      const err = Object.entries(errores).filter(([, m]) => m).map(([f, m]) => `${f}: ${m}`).join(" · ");
      av.innerHTML = e.en_curso
        ? `Descargando los primeros datos… (ver detalle en la ventana de gemelo.py)${err ? "<br>" + err : ""}`
        : `Sin datos todavía. ${err || "Revisa config.ini (API key de AEMET)."}`;
      av.classList.remove("oculto");
    } else av.classList.add("oculto");
    $("btn-actualizar").classList.toggle("girando", !!e.en_curso);
    const firma = e.ultima_actualizacion + "|" + e.ultima_obs + "|" + e.n_obs;
    if (firma !== S.ultimaAct) {
      const primera = S.ultimaAct == null;
      S.ultimaAct = firma;
      await cargarVentana(primera);
    }
  }

  // ------------------------------------------------------------------ controles
  $("rng-tiempo").oninput = ev => { S.idx = +ev.target.value; render(); };
  $("btn-ahora").onclick = () => { S.idx = S.horas.length - 1; $("rng-tiempo").value = S.idx; render(); };
  $("btn-play").onclick = () => {
    if (S.jugando) { clearInterval(S.jugando); S.jugando = null; $("btn-play").textContent = "▶"; return; }
    if (S.idx >= S.horas.length - 1) S.idx = Math.max(0, S.horas.length - 25);
    $("btn-play").textContent = "❚❚";
    S.jugando = setInterval(() => {
      if (S.idx >= S.horas.length - 1) { $("btn-play").click(); return; }
      S.idx++; $("rng-tiempo").value = S.idx; render();
    }, 700);
  };
  ["chk-superficie", "chk-lapse", "chk-relieve", "chk-etiquetas", "chk-flechas"].forEach(id => $(id).onchange = () => render(true));
  $("rng-opacidad").oninput = ev => superficie.setOpacity(+ev.target.value);
  $("sel-fondo").onchange = ev => ponerFondo(ev.target.value);
  $("chk-gris").onchange = ev => mapa.getContainer().classList.toggle("atenuado", ev.target.checked);
  $("btn-panel").onclick = () => document.body.classList.toggle("panel-abierto");
  $("panel-cerrar").onclick = () => document.body.classList.remove("panel-abierto");
  mapa.on("click", () => document.body.classList.remove("panel-abierto"));
  if (EST) {
    $("btn-actualizar").textContent = "⟳";
    $("btn-actualizar").title = "Recargar datos";
  }
  $("btn-actualizar").onclick = async () => {
    if (EST) { S.ultimaAct = null; cacheSeries.clear(); await sondearEstado(); return; }
    $("btn-actualizar").classList.add("girando");
    await fetch("/api/actualizar", { method: "POST" });
    setTimeout(sondearEstado, 4000);
  };
  document.addEventListener("keydown", ev => {
    if (ev.target.tagName === "INPUT" && ev.target.type !== "range") return;
    if (ev.key === "ArrowLeft") { S.idx = Math.max(0, S.idx - 1); $("rng-tiempo").value = S.idx; render(); }
    if (ev.key === "ArrowRight") { S.idx = Math.min(S.horas.length - 1, S.idx + 1); $("rng-tiempo").value = S.idx; render(); }
  });

  // ------------------------------------------------------------------ arranque
  if (EST && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(e => console.warn("SW", e));
  }
  // al volver a la app (p. ej. desde segundo plano en el móvil) se comprueba si hay datos nuevos
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sondearEstado(); });

  (async function iniciar() {
    construirSelector();
    construirSelectorFondo();
    await cargarIsla();
    ponerFondo("ign_base");
    try {
      const c = await DATOS.config();
      S.horasVisor = c.horas_visor || 72;
    } catch { }
    await sondearEstado();
    // comprueba cada minuto si hay datos nuevos (cada 15 s mientras aún no haya ninguno)
    const bucle = () => sondearEstado().finally(() => setTimeout(bucle, S.horas.length ? 60 * 1000 : 15 * 1000));
    setTimeout(bucle, 15 * 1000);
  })();
})();
