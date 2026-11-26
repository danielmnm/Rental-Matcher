/*
 * Rental Matcher: share listings with someone who doesn't have the extension (v1.41; "Share" since v1.42).
 *
 * From the results page you pick which lists to send (favorites, interested, viewing
 * scheduled, every match) and how: a page to send (one HTML file, opens in any browser,
 * phone included), text to paste (WhatsApp, email), or the system's own share menu.
 *
 * Nothing leaves the computer unless the user sends it: the file is made here, in the
 * browser. It carries what the cards show (rent, rooms, size, floor, place, the trips,
 * the features) and the links to each listing. Listing text is the sites' own and is
 * escaped; links and photos pass the same checks the cards use.
 *
 * Photos are fetched and embedded as "data:" URIs (v1.46), not left as links to the
 * sites' own image servers: an HTML file opened on a phone from WhatsApp or Messages is
 * usually shown in a sandboxed preview (iOS Quick Look) that loads nothing remote, so a
 * page that only linked to photos looked broken there. A photo that can't be fetched
 * when the page is built keeps its remote address instead -- nothing is lost, it just
 * needs a connection, like before.
 */
(function (root) {
  "use strict";

  const GROUPS = ["fav", "interested", "viewing", "all"];
  const MODE_ICON = { ebike: "🛵", bike: "🚲", walk: "🚶", car: "🚗" };

  /** The listings in each chosen group, each listing once (in the first group it's in), best first. */
  function pick(listings, marks, groups) {
    const m = (x) => (marks || {})[x.id] || {};
    const rules = {
      fav: (x) => !!m(x).fav,
      interested: (x) => m(x).status === "interested",
      viewing: (x) => m(x).status === "viewing",
      all: (x) => !x.excluded,
    };
    const used = new Set();
    const out = [];
    for (const g of GROUPS) {
      if (!(groups || []).includes(g)) continue;
      let xs = listings.filter((x) => m(x).status !== "rejected" && rules[g](x) && !used.has(x.id));
      if (g === "viewing") xs = xs.sort((a, b) => String(m(a).viewingAt || "~").localeCompare(String(m(b).viewingAt || "~")));
      for (const x of xs) used.add(x.id);
      if (xs.length) out.push({ group: g, listings: xs });
    }
    return out;
  }

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  function trip(v, x, I, C) {
    const t = I.t;
    let w = v;
    if (v.minutes == null && v.about == null && v.usual == null && C && C.timesFrom) {
      w = Object.assign({}, v, C.timesFrom(((x.commutes || {})[v.signal] || {}).evidence));
    }
    let time = null;
    if (w.mode === "car" && w.usual != null && w.worst != null) time = t(w.estimate ? "trip_car_est" : "trip_car", { u: I.num(w.usual, 0), w: I.num(w.worst, 0) });
    else if (w.minutes != null) time = t("min", { n: I.num(w.minutes, 0) });
    else if (w.about != null) time = t("trip_about", { n: I.num(w.about, 0) });
    if (!time) return null;
    return `${MODE_ICON[w.mode] || "📍"} ${time} ${t("to_place", { place: v.place })}`;
  }

  /** The words of one listing: what the cards show, as plain strings. */
  function facts(x, I, C, mark) {
    const t = I.t;
    const place = [x.street, x.neighborhood, x.city].filter(Boolean).join(", ");
    const line = [x.rooms ? `${I.num(x.rooms, 1)} ${t("rooms_short")}` : "", x.size_m2 ? `${I.num(x.size_m2, 0)} m²` : "",
      x.floor != null ? `${t("floor_short")} ${x.floor}` : ""].filter(Boolean).join(" · ");
    const trips = (x.trips || []).map((v) => trip(v, x, I, C)).filter(Boolean);
    const good = (x.feature_keys || []).filter((f) => f.tone === "good").map((f) => `${(C && C.ICONS && C.ICONS[f.key]) || "✓"} ${I.feature(f)}`);
    const offer = C && C.bestOffer ? C.bestOffer(x) : { best: null, offers: [] };
    const url = offer.best ? offer.best.url : C && C.SAFE_LINK && C.SAFE_LINK.test(x.url) ? x.url : null;
    const photos = C && C.safePhotos ? C.safePhotos(x.photos) : [];
    const m = mark || {};
    const when = m.status === "viewing" && m.viewingAt ? I.date(m.viewingAt, true) : null;
    return { price: typeof x.price === "number" && x.price > 0 ? I.money(x.price) : "", place, line, trips, good, url, photos, when,
      fav: !!m.fav, site: x.source || "yad2" };
  }

  const groupTitle = (g, I) => I.t({ fav: "rs_fav", interested: "rs_interested", viewing: "rs_viewing", all: "sx_all" }[g]);

  /** Text to paste: a WhatsApp or email message. */
  function text(groups, ctx) {
    const { I, C, marks } = ctx;
    const out = [ctx.title || I.t("sx_title")];
    for (const { group, listings } of groups) {
      out.push("", `*${groupTitle(group, I)}* (${listings.length})`);
      for (const x of listings) {
        const f = facts(x, I, C, (marks || {})[x.id]);
        out.push("", `• ${[f.price, f.line].filter(Boolean).join(" · ")}`);
        if (f.place) out.push(`  ${f.place}`);
        if (f.when) out.push(`  📅 ${f.when}`);
        for (const tr of f.trips) out.push(`  ${tr}`);
        if (f.url) out.push(`  ${f.url}`);
      }
    }
    return out.join("\n");
  }

  const CSS = `*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1d2125;background:#f6f7f9}
main{max-width:980px;margin:0 auto;padding:20px 16px 48px}h1{font-size:22px;margin:0 0 4px}.sub{color:#6e7781;margin:0 0 18px}
h2{font-size:17px;margin:26px 0 10px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.ph{aspect-ratio:16/10;background:#eef1f5;display:flex;overflow-x:auto;scroll-snap-type:x mandatory}
.ph img{flex:0 0 100%;width:100%;height:100%;object-fit:cover;scroll-snap-align:start}.ph .none{margin:auto;color:#8a94a3;font-size:13px}
.in{padding:12px 14px;display:flex;flex-direction:column;gap:4px;flex:1}.price{font-size:20px;font-weight:700}
.line{color:#3d444d}.place{font-weight:600}.muted{color:#6e7781;font-size:13px}.tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.tag{background:#e9f7ef;color:#1a7f37;border-radius:999px;padding:2px 8px;font-size:12px}.when{color:#9a3412;font-weight:600}
.fav{color:#d1242f}a.go{margin-top:auto;padding-top:8px;color:#1f6feb;font-weight:600;text-decoration:none}
footer{margin-top:30px;color:#8a94a3;font-size:12px}`;

  /** bytes -> a base64 "data:" URI: Buffer in Node (tests), btoa in the browser. */
  function toDataURL(bytes, mime) {
    let b64;
    if (typeof Buffer !== "undefined") {
      b64 = Buffer.from(bytes).toString("base64");
    } else {
      let binary = "";
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      b64 = btoa(binary);
    }
    return `data:${mime || "application/octet-stream"};base64,${b64}`;
  }

  const EMBED_TIMEOUT = 8000; // ms per photo: one slow or hanging fetch can't stall the whole export
  const EMBED_CONCURRENCY = 8;

  /** One photo, fetched and turned into a "data:" URI; null (never thrown) on any failure. */
  async function embedOne(url, fetchImpl) {
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = ctl ? setTimeout(() => ctl.abort(), EMBED_TIMEOUT) : null;
    try {
      const res = await fetchImpl(url, ctl ? { signal: ctl.signal } : undefined);
      if (!res || !res.ok) return null;
      const bytes = new Uint8Array(await res.arrayBuffer());
      const mime = (res.headers && res.headers.get && res.headers.get("content-type")) || "image/jpeg";
      return toDataURL(bytes, mime);
    } catch (e) {
      return null; // CORS, offline, timeout, a bad photo: the remote URL is still a fine fallback
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  /**
   * v1.46: every photo embedded as a "data:" URI so the exported page needs no
   * network to show them -- the gap that made shared pages look broken on an
   * iPhone, where WhatsApp and Messages preview an HTML attachment (Quick
   * Look) without loading anything remote. A photo that can't be fetched (no
   * network right now, a dead link) keeps its normal address instead, so
   * nothing is lost if this computer has no connection either.
   */
  async function embedPhotos(urls, fetchImpl) {
    const f = fetchImpl || (typeof fetch !== "undefined" ? fetch : null);
    const out = new Map();
    if (!f) { urls.forEach((u) => out.set(u, u)); return out; }
    const queue = urls.slice();
    const workers = Array.from({ length: Math.max(1, Math.min(EMBED_CONCURRENCY, queue.length)) }, async () => {
      let u;
      while ((u = queue.shift()) !== undefined) out.set(u, (await embedOne(u, f)) || u);
    });
    await Promise.all(workers);
    return out;
  }

  /** A page to send: one HTML file, no scripts, that opens anywhere -- including
   * offline, since its photos are embedded, not linked (v1.46). */
  async function html(groups, ctx) {
    const { I, C, marks } = ctx;
    const t = I.t;
    const n = groups.reduce((a, g) => a + g.listings.length, 0);
    const title = ctx.title || t("sx_title");
    const rows = groups.map(({ group, listings }) => ({ group, facts: listings.map((x) => facts(x, I, C, (marks || {})[x.id])) }));
    const shown = (f) => f.photos.slice(0, 8);
    const urls = [...new Set(rows.flatMap((g) => g.facts.flatMap(shown)))];
    const embedded = await embedPhotos(urls, ctx.fetch);
    let someStillRemote = false;
    const parts = [];
    for (const { group, facts: fs } of rows) {
      parts.push(`<h2>${esc(groupTitle(group, I))} (${fs.length})</h2><div class="grid">`);
      for (const f of fs) {
        const ph = f.photos.length
          ? shown(f).map((u) => {
              const src = embedded.get(u) || u;
              if (src === u) someStillRemote = true; // couldn't be embedded: still needs a connection
              return `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(src)}" alt="">`;
            }).join("")
          : `<span class="none">${esc(t("ph_none"))}</span>`;
        parts.push(`<article class="card"><div class="ph">${ph}</div><div class="in">`
          + `<div class="price">${esc(f.price)}${f.fav ? ' <span class="fav">♥</span>' : ""}</div>`
          + (f.line ? `<div class="line">${esc(f.line)}</div>` : "")
          + (f.place ? `<div class="place"><bdi>${esc(f.place)}</bdi></div>` : "")
          + (f.when ? `<div class="when">📅 ${esc(f.when)}</div>` : "")
          + f.trips.map((tr) => `<div class="muted"><bdi>${esc(tr)}</bdi></div>`).join("")
          + (f.good.length ? `<div class="tags">${f.good.slice(0, 8).map((g) => `<span class="tag">${esc(g)}</span>`).join("")}</div>` : "")
          + (f.url ? `<a class="go" href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">${esc(t("open_on", { site: t(`site_${f.site}`) }))} ↗</a>` : "")
          + "</div></article>");
      }
      parts.push("</div>");
    }
    const lang = I.lang === "he" ? "he" : "en";
    return `<!doctype html><html lang="${lang}" dir="${lang === "he" ? "rtl" : "ltr"}"><head><meta charset="utf-8">`
      + `<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">`
      + `<title>${esc(title)}</title><style>${CSS}</style></head><body><main>`
      + `<h1>${esc(title)}</h1><p class="sub">${esc(t("sx_sub", { n, when: I.date(ctx.at || Date.now(), false) }))}</p>`
      + (someStillRemote ? `<p class="sub">📶 ${esc(t("sx_photo_note"))}</p>` : "")
      + parts.join("") + `<footer>${esc(t("sx_footer"))}</footer></main></body></html>`;
  }

  const api = { GROUPS, pick, text, html, facts, esc, embedPhotos, toDataURL };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalShare = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
