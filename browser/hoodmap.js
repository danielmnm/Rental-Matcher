/*
 * Rental Matcher: pick neighborhoods on a map (v1.32).
 *
 * Yad2 gives each neighborhood a center and the box it spans (the same
 * list the setup page loads, so the ids are Yad2's own). Yad2 doesn't give
 * outlines, and OpenStreetMap's public query server refused requests from
 * a browser when this was built (Oct 24), so the areas are drawn from
 * Yad2's data: each neighborhood gets the part of the city closer to its
 * center than to any other's (a Voronoi cell), kept inside its own box.
 * They are close to the real borders, not exact, and the page says so.
 *
 * The map is a small one of our own (no library): map tiles from
 * OpenStreetMap France (v1.33; see TILES), placed by the standard Web Mercator
 * math, with the areas drawn over them in SVG. Drag to move, the wheel or
 * +/- to zoom, click an area to pick it or drop it.
 *
 * The geometry is plain functions (tested in node: hoodmap.test.js); the
 * map needs a page.
 */
(function (root) {
  "use strict";

  // ---- geometry -------------------------------------------------------------------------

  const TILE = 256;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  /** Web Mercator: [lng, lat] -> world pixels at zoom z. */
  function project(lng, lat, z) {
    const s = TILE * 2 ** z;
    const sin = Math.sin((clamp(lat, -85, 85) * Math.PI) / 180);
    return [((lng + 180) / 360) * s, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s];
  }

  /** World pixels at zoom z -> [lng, lat]. */
  function unproject(x, y, z) {
    const s = TILE * 2 ** z;
    const lng = (x / s) * 360 - 180;
    const n = Math.PI - (2 * Math.PI * y) / s;
    return [lng, (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))];
  }

  /**
   * Keep the part of a polygon on the side of the line where a*x + b*y <= c
   * (one step of Sutherland-Hodgman).
   */
  function clipHalf(poly, a, b, c) {
    const out = [];
    const inside = (p) => a * p[0] + b * p[1] <= c + 1e-12;
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i];
      const q = poly[(i + 1) % poly.length];
      const pin = inside(p);
      const qin = inside(q);
      if (pin) out.push(p);
      if (pin !== qin) {
        const dp = a * p[0] + b * p[1] - c;
        const dq = a * q[0] + b * q[1] - c;
        const k = dp / (dp - dq);
        out.push([p[0] + k * (q[0] - p[0]), p[1] + k * (q[1] - p[1])]);
      }
    }
    return out;
  }

  function clipRect(poly, [x0, y0, x1, y1]) {
    let p = poly;
    p = clipHalf(p, -1, 0, -x0);
    p = clipHalf(p, 1, 0, x1);
    p = clipHalf(p, 0, -1, -y0);
    p = clipHalf(p, 0, 1, y1);
    return p;
  }

  function area(poly) {
    let s = 0;
    for (let i = 0; i < poly.length; i++) {
      const [x0, y0] = poly[i];
      const [x1, y1] = poly[(i + 1) % poly.length];
      s += x0 * y1 - x1 * y0;
    }
    return Math.abs(s) / 2;
  }

  function centroid(poly) {
    let cx = 0;
    let cy = 0;
    let a = 0;
    for (let i = 0; i < poly.length; i++) {
      const [x0, y0] = poly[i];
      const [x1, y1] = poly[(i + 1) % poly.length];
      const f = x0 * y1 - x1 * y0;
      a += f;
      cx += (x0 + x1) * f;
      cy += (y0 + y1) * f;
    }
    if (Math.abs(a) < 1e-18) return poly[0];
    return [cx / (3 * a), cy / (3 * a)];
  }

  /**
   * The areas, in [lng, lat] rings: hoods [{id, lat, lng, box: [minLng,
   * minLat, maxLng, maxLat]}], city box the same way. A neighborhood
   * without a center gets no area (the list below the map still has it);
   * one whose cell comes out empty gets a dot ({dot: [lng, lat]}).
   * Distances are measured with longitude shrunk by cos(latitude), so
   * "closer" means closer on the ground.
   */
  function cells(hoods, cityBox) {
    const withPin = hoods.filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng));
    if (!withPin.length) return {};
    const lat0 = withPin.reduce((s, h) => s + h.lat, 0) / withPin.length;
    const kx = Math.cos((lat0 * Math.PI) / 180);
    const P = (lng, lat) => [lng * kx, lat];
    const B = (b) => [b[0] * kx, b[1], b[2] * kx, b[3]];
    const pts = withPin.map((h) => P(h.lng, h.lat));
    // the city's box, or the boxes of all its neighborhoods, a little larger
    let cb = cityBox && cityBox.every(Number.isFinite) ? B(cityBox) : null;
    if (!cb) {
      const xs = withPin.flatMap((h) => (h.box ? [h.box[0], h.box[2]] : [h.lng])).map((v) => v * kx);
      const ys = withPin.flatMap((h) => (h.box ? [h.box[1], h.box[3]] : [h.lat]));
      cb = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }
    const pad = 0.002;
    cb = [cb[0] - pad, cb[1] - pad, cb[2] + pad, cb[3] + pad];
    const out = {};
    withPin.forEach((h, i) => {
      let poly = [[cb[0], cb[1]], [cb[2], cb[1]], [cb[2], cb[3]], [cb[0], cb[3]]];
      const [px, py] = pts[i];
      for (let j = 0; j < pts.length && poly.length; j++) {
        if (j === i) continue;
        const [qx, qy] = pts[j];
        if (Math.abs(qx - px) < 1e-9 && Math.abs(qy - py) < 1e-9) continue; // two names for one place: they share
        // closer to p than to q: (q - p) . x <= (|q|^2 - |p|^2) / 2
        poly = clipHalf(poly, qx - px, qy - py, (qx * qx + qy * qy - px * px - py * py) / 2);
      }
      // and inside its own box, a little larger (Yad2's boxes are tight)
      if (h.box && h.box.every(Number.isFinite) && poly.length) {
        const b = B(h.box);
        const m = Math.max(0.0015, 0.25 * Math.max(b[2] - b[0], b[3] - b[1]));
        poly = clipRect(poly, [b[0] - m, b[1] - m, b[2] + m, b[3] + m]);
      }
      if (poly.length >= 3 && area(poly) > 1e-10) {
        out[h.id] = { ring: poly.map(([x, y]) => [x / kx, y]), label: (() => { const c = centroid(poly); return [c[0] / kx, c[1]]; })() };
      } else out[h.id] = { dot: [h.lng, h.lat] };
    });
    return out;
  }

  /** The zoom and center that fit a box into w x h pixels. */
  function fit(box, w, h) {
    for (let z = 17; z >= 3; z--) {
      const [x0, y1] = project(box[0], box[1], z);
      const [x1, y0] = project(box[2], box[3], z);
      if (x1 - x0 <= w - 40 && y1 - y0 <= h - 40) return { z, center: [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] };
    }
    return { z: 3, center: [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] };
  }

  // ---- the map ----------------------------------------------------------------------------

  // v1.33: OpenStreetMap France's tiles. CARTO's free tiles answer "API key required", and
  // openstreetmap.org's "access blocked", to a page that sends no Referer (an extension's pages
  // don't); OSM France's serve it, with the same data. Its humanitarian style is the fallback.
  const TILES = (z, x, y) => `https://${"abc"[(x + y) % 3]}.tile.openstreetmap.fr/osmfr/${z}/${x}/${y}.png`;
  const TILES_2 = (z, x, y) => `https://${"abc"[(x + y) % 3]}.tile.openstreetmap.fr/hot/${z}/${x}/${y}.png`;
  /**
   * v1.41: a tint for each area so no two neighbors share one: areas that share a corner of
   * their outlines are neighbors; the busiest are colored first (greedy). {id -> tint index}
   */
  function tints(shapes) {
    const ids = Object.keys(shapes).map(Number);
    const near = new Map(ids.map((id) => [id, new Set()]));
    const key = (p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
    const at = new Map();
    for (const id of ids) {
      const ring = shapes[id].ring;
      if (!ring) continue;
      for (const p of ring) {
        const k = key(p);
        if (!at.has(k)) at.set(k, new Set());
        at.get(k).add(id);
      }
    }
    for (const set of at.values()) for (const a of set) for (const b of set) if (a !== b) near.get(a).add(b);
    const out = new Map();
    for (const id of ids.slice().sort((a, b) => near.get(b).size - near.get(a).size || a - b)) {
      const used = new Set(Array.from(near.get(id)).map((n) => out.get(n)).filter((v) => v != null));
      let c = 0;
      while (used.has(c)) c++;
      out.set(id, c);
    }
    return out;
  }

  // v1.41: soft tints so neighboring areas read apart (an area's tint stays as you zoom and pan)
  const TINTS = ["#64748b", "#f59e0b", "#10b981", "#a855f7", "#ef4444", "#14b8a6", "#eab308", "#ec4899"];
  const CSS = `
  .hm { position: relative; height: 420px; border: 1px solid #d0d7de; border-radius: 12px; overflow: hidden; background: #eef1f5;
    touch-action: none; user-select: none; cursor: grab; margin-top: 8px; direction: ltr; }
  .hm.drag { cursor: grabbing; }
  .hm-tiles, .hm svg { position: absolute; left: 0; top: 0; }
  .hm-tiles img { position: absolute; width: 256px; height: 256px; max-width: none; }
  /* v1.41: the street map goes quiet (grey, faded) so the areas are what you see; each area has its own
     tint and a solid border, a picked one is blue with a thick edge, and the names sit on labels */
  .hm-tiles { filter: grayscale(1) contrast(.8) brightness(1.08); opacity: .7; }
  .hm path { fill: var(--c, #8a94a3); fill-opacity: .2; stroke: #1f2a44; stroke-width: 1.4; stroke-opacity: .7; cursor: pointer;
    stroke-linejoin: round; transition: fill-opacity .12s, stroke-width .12s; }
  .hm path:hover { fill-opacity: .42; stroke-width: 2.6; stroke-opacity: 1; }
  .hm path.on { fill: #1f6feb; fill-opacity: .48; stroke: #0b3d91; stroke-width: 2.8; stroke-opacity: 1; }
  .hm path.on:hover { fill-opacity: .6; }
  .hm circle { fill: var(--c, #8a94a3); fill-opacity: .5; stroke: #1f2a44; stroke-width: 1.5; cursor: pointer; }
  .hm circle.on { fill: #1f6feb; fill-opacity: 1; stroke: #0b3d91; }
  .hm g.lb { pointer-events: none; }
  .hm g.lb rect { fill: rgba(255,255,255,.93); stroke: #6e7781; stroke-width: .7; }
  .hm g.lb text { font: 600 11.5px system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; fill: #1d2125; text-anchor: middle;
    dominant-baseline: central; }
  .hm g.lb.on rect { fill: #1f6feb; stroke: #0b3d91; }
  .hm g.lb.on text { fill: #fff; font-weight: 700; }
  .hm-zoom { position: absolute; top: 10px; inset-inline-end: 10px; display: flex; flex-direction: column; gap: 4px; z-index: 2; }
  .hm-zoom button { width: 30px; height: 30px; border: 1px solid #d0d7de; border-radius: 8px; background: #fff; font-size: 17px; cursor: pointer; }
  .hm-attr { position: absolute; bottom: 0; right: 0; background: rgba(255,255,255,.8); font-size: 10px; padding: 1px 5px; color: #57606a; z-index: 2; }
  .hm-attr a { color: inherit; }
  .hm-tip { position: absolute; z-index: 3; background: #1d2125; color: #fff; font-size: 12px; padding: 3px 8px; border-radius: 6px;
    pointer-events: none; white-space: nowrap; transform: translate(-50%, -130%); }
  .hm-tip[hidden] { display: none; }
  `;

  /**
   * opts: {hoods [{id, he, en, lat, lng, box}], cityBox, picked (a Set, kept
   * up to date), name(h), onChange(), attribution}. Returns {redraw(),
   * destroy()}.
   */
  function create(doc, container, opts) {
    const win = doc.defaultView;
    const ns = "http://www.w3.org/2000/svg";
    if (!doc.getElementById("hm-css")) {
      const st = doc.createElement("style");
      st.id = "hm-css";
      st.textContent = CSS;
      doc.head.append(st);
    }
    const shapes = cells(opts.hoods, opts.cityBox);
    const byId = new Map(opts.hoods.map((h) => [h.id, h]));
    const tintOf = tints(shapes);
    const box = opts.cityBox && opts.cityBox.every(Number.isFinite) ? opts.cityBox : (() => {
      const pts = opts.hoods.filter((h) => Number.isFinite(h.lat));
      return [Math.min(...pts.map((h) => h.lng)), Math.min(...pts.map((h) => h.lat)), Math.max(...pts.map((h) => h.lng)), Math.max(...pts.map((h) => h.lat))];
    })();
    const wrap = doc.createElement("div");
    wrap.className = "hm";
    const tiles = doc.createElement("div");
    tiles.className = "hm-tiles";
    const svg = doc.createElementNS(ns, "svg");
    const tip = doc.createElement("div");
    tip.className = "hm-tip";
    tip.hidden = true;
    const zoom = doc.createElement("div");
    zoom.className = "hm-zoom";
    const zin = doc.createElement("button");
    const zout = doc.createElement("button");
    zin.type = zout.type = "button";
    zin.textContent = "+";
    zout.textContent = "−";
    zoom.append(zin, zout);
    const attr = doc.createElement("div");
    attr.className = "hm-attr";
    attr.textContent = opts.attribution || "© OpenStreetMap contributors · tiles OSM France";
    wrap.append(tiles, svg, zoom, attr, tip);
    container.append(wrap);

    const W = () => wrap.clientWidth || 600;
    const H = () => wrap.clientHeight || 420;
    let { z, center } = fit(box, W(), H());
    let c = project(center[0], center[1], z); // the center, in world pixels
    const toScreen = (lng, lat) => {
      const [x, y] = project(lng, lat, z);
      return [x - c[0] + W() / 2, y - c[1] + H() / 2];
    };

    function drawTiles() {
      tiles.replaceChildren();
      const n = 2 ** z;
      const x0 = Math.floor((c[0] - W() / 2) / TILE);
      const y0 = Math.floor((c[1] - H() / 2) / TILE);
      const x1 = Math.floor((c[0] + W() / 2) / TILE);
      const y1 = Math.floor((c[1] + H() / 2) / TILE);
      for (let x = x0; x <= x1; x++) {
        for (let y = y0; y <= y1; y++) {
          if (y < 0 || y >= n) continue;
          const img = doc.createElement("img");
          img.alt = "";
          img.draggable = false;
          img.referrerPolicy = "no-referrer";
          const tx = ((x % n) + n) % n;
          img.src = TILES(z, tx, y);
          img.addEventListener("error", () => { if (!img.dataset.again) { img.dataset.again = "1"; img.src = TILES_2(z, tx, y); } }, { once: true });
          img.style.left = `${x * TILE - c[0] + W() / 2}px`;
          img.style.top = `${y * TILE - c[1] + H() / 2}px`;
          tiles.append(img);
        }
      }
    }

    function drawShapes() {
      svg.setAttribute("width", W());
      svg.setAttribute("height", H());
      svg.replaceChildren();
      const labels = [];
      // the picked ones drawn last, so their thick edge isn't covered by a neighbor's
      const order = Object.entries(shapes).sort(([a], [b]) => Number(opts.picked.has(Number(a))) - Number(opts.picked.has(Number(b))));
      for (const [id, s] of order) {
        const h = byId.get(Number(id));
        const on = opts.picked.has(h.id);
        let el;
        if (s.ring) {
          el = doc.createElementNS(ns, "path");
          el.setAttribute("d", `M${s.ring.map(([lng, lat]) => toScreen(lng, lat).map((v) => v.toFixed(1)).join(",")).join("L")}Z`);
        } else {
          el = doc.createElementNS(ns, "circle");
          const [x, y] = toScreen(s.dot[0], s.dot[1]);
          el.setAttribute("cx", x);
          el.setAttribute("cy", y);
          el.setAttribute("r", 7);
        }
        el.setAttribute("class", on ? "on" : "");
        el.style.setProperty("--c", TINTS[tintOf.get(h.id) % TINTS.length]);
        el.dataset.id = String(h.id);
        el.setAttribute("role", "checkbox");
        el.setAttribute("aria-checked", String(on));
        el.setAttribute("aria-label", opts.name(h));
        svg.append(el);
        const [lx, ly] = s.ring ? toScreen(s.label[0], s.label[1]) : (() => { const p = toScreen(s.dot[0], s.dot[1]); return [p[0], p[1] - 11]; })();
        // v1.41: every area that's big enough on screen gets its name; where names would overlap,
        // picked areas and bigger areas win (the rest show theirs on hover, or after zooming in)
        let size = 1e9;
        if (s.ring) {
          const xs = s.ring.map(([lng, lat]) => toScreen(lng, lat)[0]);
          const ys = s.ring.map(([lng, lat]) => toScreen(lng, lat)[1]);
          const w = Math.max(...xs) - Math.min(...xs);
          const hgt = Math.max(...ys) - Math.min(...ys);
          size = w * hgt;
          if (w < 26 || hgt < 14) continue;
        }
        const text = opts.name(h);
        labels.push({ x: lx, y: ly, text: (on ? "✓ " : "") + (text.length > 20 ? `${text.slice(0, 19)}…` : text), on, size });
      }
      // the names over the areas, on labels, never on top of each other
      const placed = [];
      labels.sort((a, b) => Number(b.on) - Number(a.on) || b.size - a.size);
      const free = (b) => !placed.some((p) => b[0] < p[2] + 2 && b[2] > p[0] - 2 && b[1] < p[3] + 2 && b[3] > p[1] - 2);
      for (const l of labels) {
        const w = l.text.length * 6.4 + 12;
        // at the area's middle, or just above or below it when another name is there
        let box = null;
        for (const dy of [0, -20, 20]) {
          const b = [l.x - w / 2, l.y + dy - 9, l.x + w / 2, l.y + dy + 9];
          if (b[2] < 0 || b[0] > W() || b[3] < 0 || b[1] > H()) continue;
          if (free(b)) { box = b; l.y += dy; break; }
        }
        if (!box) continue;
        placed.push(box);
        const g = doc.createElementNS(ns, "g");
        g.setAttribute("class", l.on ? "lb on" : "lb");
        const r = doc.createElementNS(ns, "rect");
        r.setAttribute("x", box[0]);
        r.setAttribute("y", box[1]);
        r.setAttribute("width", w);
        r.setAttribute("height", 18);
        r.setAttribute("rx", 5);
        const t = doc.createElementNS(ns, "text");
        t.setAttribute("x", l.x);
        t.setAttribute("y", l.y);
        t.textContent = l.text;
        g.append(r, t);
        svg.append(g);
      }
    }

    const redraw = () => { drawTiles(); drawShapes(); };

    function zoomTo(nz, at) {
      nz = clamp(nz, 10, 18);
      if (nz === z) return;
      const sx = at ? at[0] : W() / 2;
      const sy = at ? at[1] : H() / 2;
      // keep the point under the pointer where it is
      const ll = unproject(c[0] + sx - W() / 2, c[1] + sy - H() / 2, z);
      z = nz;
      const p = project(ll[0], ll[1], z);
      c = [p[0] - sx + W() / 2, p[1] - sy + H() / 2];
      redraw();
    }
    zin.addEventListener("click", () => zoomTo(z + 1));
    zout.addEventListener("click", () => zoomTo(z - 1));
    wrap.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = wrap.getBoundingClientRect();
      zoomTo(z + (e.deltaY < 0 ? 1 : -1), [e.clientX - r.left, e.clientY - r.top]);
    }, { passive: false });

    // drag to move; a click without a drag picks
    let drag = null;
    wrap.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".hm-zoom")) return;
      drag = { x: e.clientX, y: e.clientY, c: c.slice(), moved: false, target: e.target };
      wrap.setPointerCapture(e.pointerId);
    });
    wrap.addEventListener("pointermove", (e) => {
      const t = e.target && e.target.dataset && e.target.dataset.id ? byId.get(Number(e.target.dataset.id)) : null;
      if (!drag) {
        tip.hidden = !t;
        if (t) {
          const r = wrap.getBoundingClientRect();
          tip.textContent = opts.name(t);
          tip.style.left = `${e.clientX - r.left}px`;
          tip.style.top = `${e.clientY - r.top}px`;
        }
        return;
      }
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
      if (!drag.moved) return;
      wrap.classList.add("drag");
      tip.hidden = true;
      c = [drag.c[0] - dx, drag.c[1] - dy];
      redraw();
    });
    const end = (e) => {
      if (!drag) return;
      const d = drag;
      drag = null;
      wrap.classList.remove("drag");
      if (d.moved) return;
      const hit = doc.elementFromPoint(e.clientX, e.clientY);
      const id = hit && hit.dataset && hit.dataset.id ? Number(hit.dataset.id) : null;
      if (id == null) return;
      if (opts.picked.has(id)) opts.picked.delete(id);
      else opts.picked.add(id);
      drawShapes();
      if (opts.onChange) opts.onChange(id);
    };
    wrap.addEventListener("pointerup", end);
    wrap.addEventListener("pointercancel", () => { drag = null; wrap.classList.remove("drag"); });
    wrap.addEventListener("pointerleave", () => { tip.hidden = true; });
    const ro = win.ResizeObserver ? new win.ResizeObserver(() => redraw()) : null;
    if (ro) ro.observe(wrap);
    redraw();
    return {
      redraw: drawShapes,
      destroy() {
        if (ro) ro.disconnect();
        wrap.remove();
      },
      get zoom() { return z; },
    };
  }

  const api = { tints, CSS, project, unproject, clipHalf, clipRect, area, centroid, cells, fit, create };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalHoodMap = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
