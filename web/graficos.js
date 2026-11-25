/* Gráficos SVG ligeros (sin dependencias) para el gemelo climático. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tip = () => document.getElementById("tooltip");

  function el(tag, attrs, padre) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (padre) padre.appendChild(e);
    return e;
  }

  function escalaBonita(min, max, n) {
    if (min === max) { min -= 1; max += 1; }
    const paso0 = (max - min) / n;
    const mag = Math.pow(10, Math.floor(Math.log10(paso0)));
    const paso = [1, 2, 2.5, 5, 10].map(m => m * mag).find(p => p >= paso0);
    const a = Math.floor(min / paso) * paso, b = Math.ceil(max / paso) * paso;
    const marcas = [];
    for (let v = a; v <= b + paso / 2; v += paso) marcas.push(+v.toFixed(6));
    return { min: a, max: b, marcas };
  }

  const fmtHora = new Intl.DateTimeFormat("es-ES", { timeZone: "Atlantic/Canary", hour: "2-digit", minute: "2-digit" });
  const fmtDia = new Intl.DateTimeFormat("es-ES", { timeZone: "Atlantic/Canary", day: "2-digit", month: "short" });
  const fmtCompleto = new Intl.DateTimeFormat("es-ES", { timeZone: "Atlantic/Canary", weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

  function mostrarTip(ev, html) {
    const t = tip(); t.innerHTML = html; t.classList.remove("oculto");
    const w = t.offsetWidth;
    t.style.left = Math.min(ev.clientX + 14, window.innerWidth - w - 8) + "px";
    t.style.top = (ev.clientY + 12) + "px";
  }
  function ocultarTip() { tip().classList.add("oculto"); }

  /**
   * Serie temporal.
   * series: [{nombre, color, datos:[[ms, valor]], tipo:'linea'|'barras', unidad, flechas?:[[ms,dir]]}]
   */
  function serieTemporal(contenedor, series, opc = {}) {
    contenedor.innerHTML = "";
    const W = contenedor.clientWidth || 390, H = opc.alto || 140;
    const m = { t: 8, r: 10, b: 22, l: 36 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H }, contenedor);
    const todos = series.flatMap(s => s.datos.filter(d => d[1] != null));
    if (!todos.length) {
      el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "#8b98a8", "font-size": 12 }, svg).textContent = "Sin datos";
      return;
    }
    const t0 = Math.min(...todos.map(d => d[0])), t1 = Math.max(...todos.map(d => d[0]));
    let vmin = Math.min(...todos.map(d => d[1])), vmax = Math.max(...todos.map(d => d[1]));
    if (opc.desdeCero) vmin = Math.min(0, vmin);
    if (opc.minY != null) vmin = Math.min(vmin, opc.minY);
    if (opc.maxY != null) vmax = Math.max(vmax, opc.maxY);
    const ey = escalaBonita(vmin, vmax, 4);
    const x = t => m.l + (t - t0) / Math.max(1, t1 - t0) * (W - m.l - m.r);
    const y = v => H - m.b - (v - ey.min) / (ey.max - ey.min) * (H - m.t - m.b);
    const g = el("g", { class: "rejilla" }, svg);
    const ge = el("g", { class: "eje" }, svg);
    ey.marcas.forEach(v => {
      el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }, g);
      el("text", { x: m.l - 5, y: y(v) + 3, "text-anchor": "end" }, ge).textContent = v;
    });
    const rango = t1 - t0, diaria = rango > 4 * 864e5;
    const nM = Math.max(2, Math.floor((W - m.l - m.r) / 70));
    for (let i = 0; i <= nM; i++) {
      const t = t0 + rango * i / nM;
      el("text", { x: x(t), y: H - 6, "text-anchor": i === 0 ? "start" : i === nM ? "end" : "middle" }, ge)
        .textContent = diaria ? fmtDia.format(t) : fmtHora.format(t);
    }
    const anchoBarra = Math.max(1, (W - m.l - m.r) / Math.max(1, (t1 - t0) / (opc.pasoMs || 36e5)) * 0.8);
    series.forEach(s => {
      if (s.tipo === "barras") {
        s.datos.forEach(([t, v]) => {
          if (v == null || v <= 0) return;
          el("rect", { x: x(t) - anchoBarra / 2, y: y(v), width: anchoBarra, height: Math.max(0.5, y(ey.min) - y(v)), fill: s.color, opacity: .9 }, svg);
        });
      } else {
        let d = "", pluma = false;
        s.datos.forEach(([t, v], i) => {
          if (v == null) { pluma = false; return; }
          const prev = s.datos[i - 1];
          const salto = prev && (t - prev[0]) > 3 * (opc.pasoMs || 36e5);
          d += (pluma && !salto ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1);
          pluma = true;
        });
        el("path", { d, fill: "none", stroke: s.color, "stroke-width": s.grosor || 1.6, "stroke-dasharray": s.discontinua ? "3 3" : "none", "stroke-linejoin": "round" }, svg);
      }
      if (s.flechas) {
        const cada = Math.max(1, Math.ceil(s.flechas.length / 28));
        s.flechas.forEach(([t, dir, v], i) => {
          if (dir == null || v == null || i % cada) return;
          const gg = el("g", { transform: `translate(${x(t)},${m.t + 6}) rotate(${dir + 180})` }, svg);
          el("path", { d: "M0,-5 L3,3 L0,1 L-3,3 Z", fill: "#9fb3c8" }, gg);
        });
      }
    });
    // interacción
    const guia = el("line", { y1: m.t, y2: H - m.b, stroke: "#5b6b7e", "stroke-dasharray": "2 2", visibility: "hidden" }, svg);
    const capa = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
    capa.addEventListener("mousemove", ev => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * W / r.width;
      const t = t0 + (px - m.l) / (W - m.l - m.r) * (t1 - t0);
      let html = "", tt = null;
      series.forEach(s => {
        let mejor = null;
        for (const d of s.datos) if (!mejor || Math.abs(d[0] - t) < Math.abs(mejor[0] - t)) mejor = d;
        if (mejor) { tt = mejor[0]; html += `<div><span style="color:${s.color}">●</span> ${s.nombre}: <b>${mejor[1] == null ? "—" : mejor[1]}</b> ${s.unidad || ""}</div>`; }
      });
      if (tt == null) return;
      guia.setAttribute("x1", x(tt)); guia.setAttribute("x2", x(tt)); guia.setAttribute("visibility", "visible");
      mostrarTip(ev, `<div style="color:#8b98a8">${diaria && opc.escalaDiaria ? fmtDia.format(tt) : fmtCompleto.format(tt)}</div>` + html);
    });
    capa.addEventListener("mouseleave", () => { guia.setAttribute("visibility", "hidden"); ocultarTip(); });
  }

  /** Dispersión valor–altitud. puntos: [{x: valor, y: alt, color, nombre, fuente}] */
  function perfil(contenedor, puntos, opc = {}) {
    contenedor.innerHTML = "";
    const W = contenedor.clientWidth || 270, H = 220;
    const m = { t: 16, r: 10, b: 30, l: 40 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H }, contenedor);
    const ps = puntos.filter(p => p.x != null && p.y != null);
    if (ps.length < 2) {
      el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "#8b98a8", "font-size": 12 }, svg).textContent = "Sin datos suficientes";
      return;
    }
    const ex = escalaBonita(Math.min(...ps.map(p => p.x)), Math.max(...ps.map(p => p.x)), 4);
    const ey = escalaBonita(0, Math.max(500, ...ps.map(p => p.y)), 4);
    const x = v => m.l + (v - ex.min) / (ex.max - ex.min) * (W - m.l - m.r);
    const y = v => H - m.b - (v - ey.min) / (ey.max - ey.min) * (H - m.t - m.b);
    const g = el("g", { class: "rejilla" }, svg), ge = el("g", { class: "eje" }, svg);
    ey.marcas.forEach(v => { el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }, g); el("text", { x: m.l - 4, y: y(v) + 3, "text-anchor": "end" }, ge).textContent = v; });
    ex.marcas.forEach(v => { el("text", { x: x(v), y: H - m.b + 13, "text-anchor": "middle" }, ge).textContent = v; });
    el("text", { x: W - m.r, y: H - 1, "text-anchor": "end" }, ge).textContent = opc.etiquetaX || "";
    el("text", { x: m.l - 4, y: 9, "text-anchor": "end" }, ge).textContent = "alt. (m)";
    if (opc.lineaRef) {   // gradiente teórico de referencia
      const [a, b] = opc.lineaRef;
      el("path", { d: `M${x(a[0])},${y(a[1])} L${x(b[0])},${y(b[1])}`, stroke: "#6a7a8c", "stroke-dasharray": "4 3", fill: "none" }, svg);
    }
    ps.forEach(p => {
      const c = el(p.fuente === "AGROCABILDO" ? "rect" : "circle",
        p.fuente === "AGROCABILDO" ? { x: x(p.x) - 4, y: y(p.y) - 4, width: 8, height: 8 } : { cx: x(p.x), cy: y(p.y), r: 4.2 }, svg);
      c.setAttribute("fill", p.color); c.setAttribute("stroke", "#0d1117"); c.setAttribute("stroke-width", 1);
      c.style.cursor = "pointer";
      c.addEventListener("mousemove", ev => mostrarTip(ev, `<b>${p.nombre}</b><br>${p.x} ${opc.unidad || ""} · ${Math.round(p.y)} m`));
      c.addEventListener("mouseleave", ocultarTip);
      if (opc.alClic) c.addEventListener("click", () => opc.alClic(p));
    });
  }

  window.Graficos = { serieTemporal, perfil, fmtCompleto, fmtHora, fmtDia };
})();
