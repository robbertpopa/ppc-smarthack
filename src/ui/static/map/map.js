/* Neighbourhood map for the operator screen (P4). Contract: README.md in this folder.
 *
 * A small slippy map with no library: OpenStreetMap tiles as images, the neighbourhood outlines
 * and feeders as SVG, houses and neighbourhoods as buttons. With no network the tiles stay empty
 * and everything else still works. It shows only what the screen gives it: it never computes a
 * limit or a status.
 *
 * Houses are always drawn: small dots zoomed out, with a status symbol from HOUSE_ZOOM and sized
 * by kWp when zoomed in. Zoomed out each neighbourhood also gets a name tag at its centre.
 */
(function () {
  "use strict";
  const TILE = 256, Z_MIN = 9, Z_MAX = 17, HOUSE_ZOOM = 12, SVG_NS = "http://www.w3.org/2000/svg";
  const MARK = {ok: "✓", review: "!", blocked: "×", none: ""};
  const WORD = {ok: "model limit", review: "fixed limit", blocked: "blocked by the guard", none: "no limit yet"};
  const RANK = {none: 0, ok: 1, review: 2, blocked: 3};

  const STYLE = `
.stm{position:absolute;inset:0;overflow:hidden;background:var(--soft);touch-action:none;cursor:grab;outline-offset:-3px}
.stm.drag{cursor:grabbing}
.stm img{position:absolute;max-width:none;user-select:none;-webkit-user-drag:none}
.stm svg{position:absolute;left:0;top:0;pointer-events:none}
.stm .mk,.stm .hood,.stm .ctl button,.stm .chips button{font:inherit;color:var(--ink);cursor:pointer}
.stm .mk[hidden],.stm .hood[hidden]{display:none}
.stm .mk{position:absolute;left:0;top:0;width:28px;height:28px;margin:-14px 0 0 -14px;padding:0;border:0;background:transparent;min-height:0;display:flex;align-items:center;justify-content:center}
.stm .mk i{display:flex;align-items:center;justify-content:center;width:var(--d,18px);height:var(--d,18px);border-radius:99px;border:2px solid var(--bg);font:700 10px/1 system-ui,sans-serif;font-style:normal;box-shadow:0 1px 4px #0006}
.stm .mk.ok i{background:var(--ok);color:#fff}.stm .mk.review i{background:var(--rev);color:#17191c}
.stm .mk.blocked i{background:var(--bad);color:#fff;box-shadow:0 0 0 4px color-mix(in srgb,var(--bad) 30%,transparent),0 1px 4px #0006}.stm .mk.none i{background:var(--line2);color:var(--ink)}
.stm .mk[aria-pressed=true] i{outline:3px solid var(--ink);outline-offset:1px}
.stm .hood{position:absolute;left:0;top:0;transform:translate(-50%,-100%);display:flex;flex-direction:row;align-items:center;gap:8px;padding:2px 10px;min-height:30px;border-radius:99px;border:1.5px solid var(--ink);background:var(--bg);font-size:.82rem;line-height:1.25;white-space:nowrap;box-shadow:0 1px 6px #0003}
.stm .hood b{font-weight:600}.stm .hood span{color:var(--muted);font-size:.78rem}
.stm .ctl{position:absolute;top:10px;right:10px;display:flex;flex-direction:column;gap:6px}
.stm .ctl button,.stm .chips button{background:var(--bg);border:1px solid var(--line2);border-radius:8px;min-height:40px;min-width:40px;padding:0 12px;font-weight:500}
.stm .chips{position:absolute;top:10px;left:10px;right:64px;display:flex;flex-wrap:wrap;gap:6px}
.stm .chips button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.stm .attr{position:absolute;right:6px;bottom:4px;font-size:11px;background:color-mix(in srgb,var(--bg) 85%,transparent);padding:1px 6px;border-radius:4px;color:var(--muted)}
.stm .msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:24px;text-align:center;color:var(--muted)}`;

  const world = (lat, lon, z) => {
    const s = TILE * 2 ** z, r = lat * Math.PI / 180;
    return {x: (lon + 180) / 360 * s, y: (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * s};
  };
  const unworld = (x, y, z) => {
    const s = TILE * 2 ** z, n = Math.PI - 2 * Math.PI * y / s;
    return {lat: 180 / Math.PI * Math.atan(Math.sinh(n)), lon: x / s * 360 - 180};
  };
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const svgNode = (tag, attrs) => { const n = document.createElementNS(SVG_NS, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); return n; };

  let S = null; // the one mounted map

  function parse(geo) {
    const hoods = [], pos = {}, feeders = [];
    ((geo && geo.features) || []).forEach(f => {
      const p = f.properties || {}, g = f.geometry || {};
      if (p.kind === "neighbourhood" && g.type === "Polygon") {
        const ring = g.coordinates[0].map(([lon, lat]) => ({lat, lon}));
        hoods.push({id: p.id, name: p.name, ring, ids: [], center: null,
          bounds: {minLat: Math.min(...ring.map(q => q.lat)), maxLat: Math.max(...ring.map(q => q.lat)), minLon: Math.min(...ring.map(q => q.lon)), maxLon: Math.max(...ring.map(q => q.lon))}});
      } else if (p.kind === "feeder" && g.type === "LineString") {
        feeders.push({group: p.neighbourhood, pts: g.coordinates.map(([lon, lat]) => ({lat, lon}))});
      } else if (p.kind === "house" && g.type === "Point") {
        pos[String(p.house_id)] = {lon: g.coordinates[0], lat: g.coordinates[1], group: p.neighbourhood};
      }
    });
    hoods.forEach(h => {
      h.ids = Object.keys(pos).filter(id => pos[id].group === h.id);
      h.center = {lat: (h.bounds.minLat + h.bounds.maxLat) / 2, lon: (h.bounds.minLon + h.bounds.maxLon) / 2};
    });
    return {hoods, pos, feeders};
  }

  function mount(el, host) {
    if (!document.getElementById("stm-style")) { const s = document.createElement("style"); s.id = "stm-style"; s.textContent = STYLE; document.head.append(s); }
    el.replaceChildren();
    const root = node("div", "stm"); root.tabIndex = 0; root.setAttribute("role", "group"); root.setAttribute("aria-label", "Neighbourhood map. Drag to move, plus and minus to zoom.");
    el.append(root);
    const data = parse(host.geo);
    if (!data.hoods.length) {
      root.append(node("p", "msg", "No map geometry yet. Run: python -m src.ui.geo_build --customers <file> --out <ARTIFACT_URI>"));
      S = null; return;
    }
    S = {el, root, host, ...data, z: 11, c: data.hoods[0].center, view: null, focus: null, fitted: false, selected: null,
      kwp: {}, tiles: new Map(), tileLayer: node("div"), svg: svgNode("svg", {}), marks: node("div"), houseEls: {}, hoodEls: {}, chips: node("div", "chips")};
    root.append(S.tileLayer, S.svg, S.marks, S.chips);
    Object.keys(S.pos).forEach(id => {
      const b = node("button", "mk none"); b.type = "button"; b.append(node("i", null, "")); b.dataset.id = id;
      b.setAttribute("aria-pressed", "false"); b.setAttribute("aria-label", "House " + id);
      b.onclick = () => S.host.select(S.selected === id ? null : id);
      b.hidden = true; S.houseEls[id] = b; S.marks.append(b);
    });
    S.hoods.forEach(h => {
      const b = node("button", "hood"); b.type = "button"; b.append(node("b", null, h.name), node("span", null, ""));
      b.onclick = () => focus(h.id); b.hidden = true; S.hoodEls[h.id] = b; S.marks.append(b);
    });
    const all = node("button", null, "All"); all.type = "button"; all.dataset.group = ""; all.onclick = () => focus(null); S.chips.append(all);
    S.hoods.forEach(h => { const c = node("button", null, h.name); c.type = "button"; c.dataset.group = h.id; c.onclick = () => focus(h.id); S.chips.append(c); });
    const ctl = node("div", "ctl");
    [["+", "Zoom in", () => zoomBy(1)], ["−", "Zoom out", () => zoomBy(-1)]].forEach(([t, label, fn]) => { const b = node("button", null, t); b.type = "button"; b.setAttribute("aria-label", label); b.onclick = fn; ctl.append(b); });
    root.append(ctl, node("div", "attr", "© OpenStreetMap contributors"));
    wire(root);
    S.ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => render()) : null;
    if (S.ro) S.ro.observe(root);
    render();
  }

  function wire(root) {
    let drag = null;
    root.addEventListener("pointerdown", e => {
      if (e.button !== 0 || e.target.closest("button")) return;
      drag = {x: e.clientX, y: e.clientY, c: world(S.c.lat, S.c.lon, S.z), moved: false};
      root.setPointerCapture(e.pointerId); root.classList.add("drag");
    });
    root.addEventListener("pointermove", e => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
      S.c = unworld(drag.c.x - dx, drag.c.y - dy, S.z); S.focus = null; render();
    });
    const end = () => { drag = null; root.classList.remove("drag"); };
    root.addEventListener("pointerup", end); root.addEventListener("pointercancel", end);
    root.addEventListener("dblclick", e => { if (!e.target.closest("button")) zoomBy(1, e); });
    root.addEventListener("wheel", e => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoomBy(e.deltaY < 0 ? 1 : -1, e); } }, {passive: false});
    root.addEventListener("keydown", e => {
      if (e.target !== root) return;
      const step = {ArrowLeft: [-80, 0], ArrowRight: [80, 0], ArrowUp: [0, -80], ArrowDown: [0, 80]}[e.key];
      if (step) { const c = world(S.c.lat, S.c.lon, S.z); S.c = unworld(c.x + step[0], c.y + step[1], S.z); S.focus = null; render(); e.preventDefault(); }
      else if (e.key === "+" || e.key === "=") zoomBy(1); else if (e.key === "-") zoomBy(-1); else if (e.key === "0") focus(null);
    });
  }

  function zoomBy(dz, e) {
    const z = Math.min(Math.max(S.z + dz, Z_MIN), Z_MAX);
    if (z === S.z) return;
    const rect = S.root.getBoundingClientRect(), px = e ? e.clientX - rect.left : rect.width / 2, py = e ? e.clientY - rect.top : rect.height / 2;
    const c = world(S.c.lat, S.c.lon, S.z), wx = c.x - rect.width / 2 + px, wy = c.y - rect.height / 2 + py, k = 2 ** (z - S.z);
    S.z = z; S.c = unworld(wx * k - px + rect.width / 2, wy * k - py + rect.height / 2, z); S.focus = null; render();
  }

  function fit(b, pad) {
    const w = S.root.clientWidth, h = S.root.clientHeight;
    let z = Z_MAX;
    for (; z > Z_MIN; z--) {
      const a = world(b.maxLat, b.minLon, z), c = world(b.minLat, b.maxLon, z);
      if (c.x - a.x <= w - 2 * pad && c.y - a.y <= h - 2 * pad - 50) break;
    }
    const a = world(b.maxLat, b.minLon, z), c = world(b.minLat, b.maxLon, z);
    S.z = z; S.c = unworld((a.x + c.x) / 2, (a.y + c.y) / 2 - 25, z);
  }

  function focus(id) {
    if (!S) return;
    const hood = S.hoods.find(h => h.id === id);
    const bounds = hood ? hood.bounds : {
      minLat: Math.min(...S.hoods.map(h => h.bounds.minLat)), maxLat: Math.max(...S.hoods.map(h => h.bounds.maxLat)),
      minLon: Math.min(...S.hoods.map(h => h.bounds.minLon)), maxLon: Math.max(...S.hoods.map(h => h.bounds.maxLon))};
    fit(bounds, 40); S.focus = hood ? hood.id : null; S.fitted = true; render();
  }

  function render() {
    if (!S) return;
    const w = S.root.clientWidth, h = S.root.clientHeight;
    if (!w || !h) return;
    if (!S.fitted) { S.fitted = true; focus(null); return; }
    const z = S.z, c = world(S.c.lat, S.c.lon, z), tlx = c.x - w / 2, tly = c.y - h / 2, n = 2 ** z;
    const at = p => { const q = world(p.lat, p.lon, z); return {x: q.x - tlx, y: q.y - tly}; };
    // Tiles
    const need = new Set();
    for (let tx = Math.floor(tlx / TILE); tx <= Math.floor((tlx + w) / TILE); tx++) {
      for (let ty = Math.max(0, Math.floor(tly / TILE)); ty <= Math.min(n - 1, Math.floor((tly + h) / TILE)); ty++) {
        const key = z + "/" + tx + "/" + ty; need.add(key);
        let img = S.tiles.get(key);
        if (!img) {
          img = node("img"); img.alt = ""; img.draggable = false; img.width = img.height = TILE;
          img.onerror = () => img.remove();
          img.src = "https://tile.openstreetmap.org/" + z + "/" + (((tx % n) + n) % n) + "/" + ty + ".png";
          S.tiles.set(key, img); S.tileLayer.append(img);
        }
        img.style.left = (tx * TILE - tlx) + "px"; img.style.top = (ty * TILE - tly) + "px";
      }
    }
    S.tiles.forEach((img, key) => { if (!need.has(key)) { img.remove(); S.tiles.delete(key); } });
    // Outlines, feeders and names
    const houses = z >= HOUSE_ZOOM, dot = z >= 14 ? 20 : z >= 12 ? 15 : 10;
    S.svg.setAttribute("width", w); S.svg.setAttribute("height", h); S.svg.replaceChildren();
    S.hoods.forEach(hd => {
      const pts = hd.ring.map(p => { const q = at(p); return q.x.toFixed(1) + "," + q.y.toFixed(1); }).join(" ");
      S.svg.append(svgNode("polygon", {points: pts, style: "fill:color-mix(in srgb,var(--ink) " + (S.focus === hd.id ? 10 : 5) + "%,transparent);stroke:var(--ink);stroke-opacity:.45;stroke-width:1.5;stroke-dasharray:6 4"}));
    });
    if (z >= 11) S.feeders.forEach(f => {
      S.svg.append(svgNode("polyline", {points: f.pts.map(p => { const q = at(p); return q.x.toFixed(1) + "," + q.y.toFixed(1); }).join(" "), style: "fill:none;stroke:var(--ink);stroke-opacity:.55;stroke-width:2;stroke-dasharray:2 5;stroke-linecap:round"}));
    });
    // Markers
    S.hoods.forEach(hd => {
      const b = S.hoodEls[hd.id]; b.hidden = houses;
      if (!houses) { const q = at(hd.center); b.style.transform = "translate(" + q.x.toFixed(1) + "px," + (q.y - 8).toFixed(1) + "px) translate(-50%,-100%)"; }
    });
    Object.keys(S.pos).forEach(id => {
      const b = S.houseEls[id], q = at(S.pos[id]), k = Math.min(1, (S.kwp[id] || 5) / 10);
      b.hidden = false; b.style.transform = "translate(" + q.x.toFixed(1) + "px," + q.y.toFixed(1) + "px)";
      b.style.setProperty("--d", (z >= 14 ? Math.round(dot * (0.8 + 0.5 * k)) : dot) + "px");
      b.firstChild.style.fontSize = houses ? "" : "0";
    });
    S.chips.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String((b.dataset.group || null) === S.focus)));
  }

  function update(view) {
    if (!S) return;
    S.view = view;
    const W = Object.assign({}, WORD, view.words || {});
    const byId = Object.fromEntries((view.houses || []).map(h => [String(h.id), h]));
    Object.keys(S.houseEls).forEach(id => {
      const h = byId[id], st = h ? h.status : "none", b = S.houseEls[id];
      b.className = "mk " + st; b.firstChild.textContent = MARK[st];
      b.setAttribute("aria-label", "House " + id + (h ? (h.limit_kw == null ? ", no limit yet" : ", " + h.limit_kw.toFixed(2) + " kilowatts, " + (h.capped ? "contract cap" : W[st])) : ""));
      b.setAttribute("aria-pressed", String(view.selected === id));
      if (h) S.kwp[id] = h.kwp;
      b.title = "House " + id + (h ? " · " + h.kwp.toFixed(1) + " kWp" + (h.limit_kw == null ? "" : " · limit " + h.limit_kw.toFixed(2) + " kW (" + Math.round(100 * h.share) + "%)") + " · " + W[st] : "");
    });
    S.hoods.forEach(hd => {
      const worst = hd.ids.reduce((a, id) => RANK[(byId[id] || {status: "none"}).status] > RANK[a] ? byId[id].status : a, "none");
      const b = S.hoodEls[hd.id]; b.lastChild.textContent = hd.ids.length + " houses " + MARK[worst];
      b.setAttribute("aria-label", hd.name + ", " + hd.ids.length + " houses. Zoom in.");
    });
    if (view.selected !== S.selected) {
      S.selected = view.selected;
      const p = view.selected && S.pos[view.selected];
      if (p) { if (S.z < 14) S.z = 14; S.c = {lat: p.lat, lon: p.lon}; S.focus = p.group; }
    }
    render();
  }

  window.StationMap = {
    mount,
    update,
    focus,
    onShow() { if (S) render(); },
    destroy() { if (S && S.ro) S.ro.disconnect(); S = null; }
  };
})();
