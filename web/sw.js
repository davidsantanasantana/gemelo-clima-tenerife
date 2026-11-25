/* Service worker del gemelo climático (solo en la versión publicada).
   - Interfaz: se sirve desde caché y se actualiza en segundo plano.
   - Datos (data/*.json): primero red; sin conexión, último dato guardado.
   - Teselas WMS (IGN/GRAFCAN) y MDT: caché limitada para abrir rápido y ver el mapa sin cobertura. */
const VERSION = "__VERSION__";
const C_APP = "app-" + VERSION, C_DATOS = "datos", C_TESELAS = "teselas";
const MAX_TESELAS = 800;
const APP = ["./", "index.html", "estilo.css", "app.js", "graficos.js", "config.js", "manifest.webmanifest",
  "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css", "iconos/icono-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(C_APP).then(c => c.addAll(APP)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("app-") && k !== C_APP).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function recortar(nombre, max) {
  const c = await caches.open(nombre), ks = await c.keys();
  for (let i = 0; i < ks.length - max; i++) await c.delete(ks[i]);
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === location.origin && url.pathname.includes("/data/")) {
    const clave = url.origin + url.pathname;                       // sin ?t=
    e.respondWith(fetch(req).then(r => {
      if (r.ok) { const cp = r.clone(); caches.open(C_DATOS).then(c => c.put(clave, cp)); }
      return r;
    }).catch(() => caches.match(clave)));
    return;
  }
  if (url.origin === location.origin) {
    e.respondWith(caches.match(req, { ignoreSearch: true }).then(hit => {
      const red = fetch(req).then(r => {
        if (r.ok) { const cp = r.clone(); caches.open(C_APP).then(c => c.put(req, cp)); }
        return r;
      }).catch(() => hit);
      return hit || red;
    }));
    return;
  }
  if (/ign\.es|idee\.es|grafcan\.es|elevation-tiles-prod/.test(url.host + url.pathname)) {
    e.respondWith(caches.open(C_TESELAS).then(async c => {
      const hit = await c.match(req);
      if (hit) return hit;
      const r = await fetch(req);
      if (r.ok || r.type === "opaque") { c.put(req, r.clone()); recortar(C_TESELAS, MAX_TESELAS); }
      return r;
    }));
  }
});
