/*
 * Rental Matcher: every listing in one place (v1.31: shelves or a grid,
 * quick filters, simple or detailed cards; v1.32: named by what they do,
 * "Picks for you" and "Every listing", with Simple/Detailed at the top and
 * the filters folded under one button). The last search's
 * listings, plus every listing you marked, even after it left the search.
 * Favorite, Interested, Viewing scheduled (with a date), Reject: a rejected
 * listing disappears here and on the panel, and isn't opened again.
 * Statistics: what the searches found, how long they take, and Yad2's
 * requests to slow down, in plain words.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const I = RentalI18n;
const t = I.t;
const store = RentalStore.make(chrome.storage.local);
$("cards-css").textContent = RentalCards.CSS;

const TABS = [["all", "rs_all"], ["fav", "rs_fav"], ["interested", "rs_interested"], ["viewing", "rs_viewing"], ["rejected", "rs_rejected"], ["hidden", "rs_hidden"]];
let tab = "all";
// v1.32: "picks" (the shelves, the default), "every" (the grid) or "stats"
let view = "picks";
let detail = false;
let chips = new Set();
let shelf = null; // "see all" of one shelf: the grid with that shelf's rule
let data = { results: null, marks: {}, pulls: [], log: [], seen: {} };

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = String(text);
  return e;
};
const iso = (text) => {
  const b = el("bdi", null, text);
  b.dir = "auto";
  return b;
};

function tripMin(x) {
  const vs = (x.trips || []).map((v) => (v.minutes != null ? v.minutes : v.about)).filter((v) => typeof v === "number");
  return vs.length ? Math.max(...vs) : Infinity;
}

function listings() {
  const res = (data.results && data.results.results) || [];
  const byId = new Map(res.map((x) => [x.id, Object.assign({ inPull: true }, x)]));
  for (const [id, m] of Object.entries(data.marks)) {
    if (!byId.has(id) && m.view) byId.set(id, Object.assign({ inPull: false }, m.view));
  }
  const all = Array.from(byId.values());
  // v1.40: listings with no photos are left out everywhere, unless the setup page's switch is off
  data.photoless = RentalCards.hidesPhotoless(data.ui) ? all.filter(RentalCards.photoless).length : 0;
  return data.photoless ? all.filter((x) => !RentalCards.photoless(x)) : all;
}

function inTab(x, k) {
  const m = data.marks[x.id] || {};
  if (k === "rejected") return m.status === "rejected";
  if (m.status === "rejected") return false;
  if (k === "all") return !x.excluded;
  if (k === "hidden") return !!x.excluded;
  if (k === "fav") return !!m.fav;
  return m.status === k;
}

// the quick filters: from your own settings and what the listings have
function chipDefs(all) {
  const prefs = (data.results && data.results.prefs) || {};
  const rent = Object.values(prefs).find((p) => p.topic === "rent");
  const trip = Object.values(prefs).find((p) => p.topic === "commute" && (p.ideal != null || p.limit != null));
  const has = (key) => (x) => (x.feature_keys || []).some((f) => f.key === key || (key === "parking" && /^parking_(own|building)$/.test(f.key)));
  const defs = [];
  if (rent && rent.ideal) defs.push(["cheap", `${t("rs_up_to")} ${I.money(rent.ideal)}`, (x) => x.price <= rent.ideal]);
  if (trip) {
    const n = trip.ideal != null ? trip.ideal : trip.limit;
    defs.push(["near", `${{ ebike: "🛵", bike: "🚲", walk: "🚶", car: "🚗" }[trip.mode] || "📍"} ${t("rs_within_min", { n })}`, (x) => tripMin(x) <= n]);
  }
  for (const [k, key] of [["balcony", "balcony"], ["parking", "parking"], ["elevator", "elevator"], ["shelter", "mamad"], ["ac", "ac"], ["renovated", "renovated"]]) {
    const f = has(key);
    if (all.some(f)) defs.push([k, `${RentalCards.ICONS[key === "parking" ? "parking_own" : key] || ""} ${I.feature({ key: key === "parking" ? "parking_own" : key }).replace(/^Own parking$/, t("rs_parking"))}`, f]);
  }
  const fresh = new Set((data.results && data.results.newIds) || []);
  defs.push(["new", `✨ ${t("new_badge")}`, (x) => fresh.has(x.id)], ["deal", `🏷️ ${t("b_deal")}`, (x) => !!x.deal], ["photos", `📷 ${t("rs_with_photos")}`, (x) => RentalCards.safePhotos(x.photos).length > 0]);
  return defs;
}

function cardOf(x, fresh, prefs) {
  const wrap = el("div");
  wrap.append(RentalCards.render(document, x, { I, prefs, mark: data.marks[x.id], isNew: fresh.has(x.id), detail,
    onMark: (y, patch) => store.setMark(y, patch) }));
  if (!x.inPull) wrap.append(el("div", "gone", t("gone")));
  return wrap;
}

// the shelves: [key, title, subtitle, rule, order]
function shelfDefs(fresh) {
  const prefs = (data.results && data.results.prefs) || {};
  const trip = Object.values(prefs).find((p) => p.topic === "commute");
  const rank = new Map(((data.results && data.results.results) || []).map((x, i) => [x.id, i]));
  const byRank = (a, b) => (rank.has(a.id) ? rank.get(a.id) : 1e9) - (rank.has(b.id) ? rank.get(b.id) : 1e9);
  return [
    ["new", `✨ ${t("sh_new")}`, t("sh_new_x"), (x) => fresh.has(x.id), byRank],
    ["drop", `↓ ${t("sh_drop")}`, t("sh_drop_x"), (x) => !!x.drop, (a, b) => (b.drop.was - b.drop.now) - (a.drop.was - a.drop.now)],
    ["deal", `🏷️ ${t("sh_deal")}`, t("sh_deal_x"), (x) => !!x.deal, (a, b) => (a.price - a.deal.median) - (b.price - b.deal.median)],
    ["saved", `♥ ${t("sh_saved")}`, t("sh_saved_x"), (x) => !!(data.marks[x.id] || {}).fav, byRank],
    ["best", `⭐ ${t("sh_best")}`, t("sh_best_x"), () => true, byRank],
    ["near", `${{ ebike: "🛵", bike: "🚲", walk: "🚶", car: "🚗" }[(trip || {}).mode] || "📍"} ${trip ? t("sh_near", { place: trip.place }) : t("sh_near_any")}`, t("sh_near_x"),
      (x) => tripMin(x) < Infinity, (a, b) => tripMin(a) - tripMin(b)],
    ["cheap", `💰 ${t("sh_cheap")}`, t("sh_cheap_x"), (x) => typeof x.price === "number", (a, b) => a.price - b.price],
  ];
}

function renderList() {
  const all = listings();
  const fresh = new Set((data.results && data.results.newIds) || []);
  const prefs = (data.results && data.results.prefs) || {};
  for (const b of $("detail").children) b.classList.toggle("on", (b.dataset.d === "1") === detail);
  // quick filters
  const defs = chipDefs(all.filter((x) => !x.excluded));
  for (const k of Array.from(chips)) if (!defs.some(([d]) => d === k)) chips.delete(k);
  $("filt").textContent = `☰ ${chips.size ? t("rs_filters_n", { n: chips.size }) : t("rs_filters")}`;
  $("filt").classList.toggle("on", chips.size > 0);
  $("chips").hidden = !(chipsOpen || chips.size);
  $("chips").replaceChildren(...defs.map(([k, label]) => {
    const b = el("button", `fchip${chips.has(k) ? " on" : ""}`, label);
    b.addEventListener("click", () => { if (chips.has(k)) chips.delete(k); else chips.add(k); renderList(); });
    return b;
  }));
  const pass = (x) => defs.every(([k, , f]) => !chips.has(k) || f(x));
  const q = $("q").value.trim().toLowerCase();
  const text = (x) => !q || [x.street, x.neighborhood, x.city].join(" ").toLowerCase().includes(q);
  const list = $("list");
  list.replaceChildren();
  const gridMode = view === "every" || !!shelf;
  $("tabs").hidden = !gridMode;
  $("sort").hidden = !gridMode;

  if (!gridMode) {
    // the shelves: the listings you'd look at, by what makes them worth a look
    const pool = all.filter((x) => inTab(x, "all") && pass(x) && text(x));
    if (!pool.length) list.append(el("div", "empty", data.results ? t("rs_empty") : t("rs_none")));
    for (const [key, title, sub, rule, order] of shelfDefs(fresh)) {
      const items = pool.filter(rule).sort(order);
      if (!items.length) continue;
      const sec = el("section", "shelf");
      const h = el("div", "shelf-h");
      h.append(el("h2", null, title));
      const see = el("button", "seeall", `${t("sh_all", { n: items.length })} →`);
      see.addEventListener("click", () => { shelf = key; render(); window.scrollTo({ top: 0 }); });
      h.append(see);
      const row = el("div", `row${detail ? " detailed" : ""}`);
      for (const x of items.slice(0, 12)) row.append(cardOf(x, fresh, prefs));
      sec.append(h, el("p", null, sub), row);
      list.append(sec);
    }
  } else {
    const tabs = $("tabs");
    tabs.replaceChildren();
    for (const [k, key] of TABS) {
      const b = el("button", `tab${k === tab ? " on" : ""}`, t(key));
      b.append(el("b", null, all.filter((x) => inTab(x, k)).length));
      b.addEventListener("click", () => { tab = k; renderList(); });
      tabs.append(b);
    }
    const sh = shelf ? shelfDefs(fresh).find((d) => d[0] === shelf) : null;
    let xs = all.filter((x) => inTab(x, sh ? "all" : tab) && pass(x) && text(x) && (!sh || sh[3](x)));
    if (sh) xs = xs.sort(sh[4]);
    else {
      const key = {
        match: (x) => -(x.match_expected || 0),
        price: (x) => x.price || Infinity,
        commute: tripMin,
        marked: (x) => -((data.marks[x.id] || {}).at || 0),
      }[$("sort").value];
      xs = xs.slice().sort((a, b) => key(a) - key(b));
    }
    if (sh) {
      const crumb = el("div", "crumb");
      const back = el("button", "btn", `← ${t("sh_back")}`);
      back.addEventListener("click", () => { shelf = null; render(); });
      crumb.append(back, el("b", null, sh[1]));
      list.append(crumb);
    }
    if (!xs.length) list.append(el("div", "empty", data.results ? t("rs_empty") : t("rs_none")));
    else {
      const g = el("div", `grid${detail ? " detailed" : ""}`);
      for (const x of xs) g.append(cardOf(x, fresh, prefs));
      list.append(g);
    }
    if (!sh && tab === "hidden") list.append(notOpened(q));
  }
  // ways to see more: one line, the options on hover (v1.32)
  const line = tab === "all" ? RentalCards.moreLine(document, I, data.results && data.results.suggestions, async (x) => {
    const r = await chrome.runtime.sendMessage({ type: "helper", path: "/relax", body: { name: x.name, change: x.change } });
    return { ok: !!(r && r.ok && r.body.saved), text: (r && r.body && r.body.error) || "" };
  }) : null;
  const nophoto = data.photoless ? el("div", "muted", t("rs_photoless", { n: data.photoless })) : null;
  $("more").replaceChildren(...(line ? [line] : []), ...(nophoto ? [nophoto] : []));
  // the viewings, soonest first
  const v = Object.entries(data.marks).filter(([, m]) => m.status === "viewing")
    .sort(([, a], [, b]) => String(a.viewingAt || "~").localeCompare(String(b.viewingAt || "~")));
  const box = $("viewings");
  box.hidden = !v.length;
  box.replaceChildren(el("h2", null, t("rs_viewings")));
  const vl = el("ul");
  for (const [, m] of v) {
    const li = el("li");
    li.append(el("b", null, m.viewingAt ? I.date(m.viewingAt, true) : t("rs_no_date")), " · ");
    li.append(iso([m.view && m.view.street, m.view && m.view.city].filter(Boolean).join(", ")));
    if (m.view && m.view.price) li.append(el("span", "muted", ` · ${I.money(m.view.price)}`));
    vl.append(li);
  }
  box.append(vl);
}

/**
 * v1.40: the listings the search saw but didn't open, because the search page alone showed a
 * must-have fails (too far, over the rent, the ground floor...), each with its reason and a link.
 */
function notOpened(q) {
  const r = data.results || {};
  const info = r.skippedInfo || {};
  const rows = Object.entries(r.skippedRows || {}).filter(([id]) => info[id])
    .map(([id, why]) => Object.assign({ why: why || [] }, info[id]))
    .filter((x) => !q || [x.hood, x.city].join(" ").toLowerCase().includes(q));
  const box = el("section", "panelbox notopened");
  box.append(el("h2", null, t("rs_notopened", { n: rows.length })), el("p", "muted", t("rs_notopened_x")));
  if (!rows.length) return box;
  const topic = (w) => String(w).split(":")[0];
  const byTopic = {};
  for (const x of rows) (byTopic[topic(x.why[0] || "?")] = byTopic[topic(x.why[0] || "?")] || []).push(x);
  for (const [name, xs] of Object.entries(byTopic).sort((a, b) => b[1].length - a[1].length)) {
    const d = el("details");
    d.append(el("summary", null, `${name} (${xs.length})`));
    const tb = el("table");
    for (const x of xs.sort((a, b) => (a.price || 0) - (b.price || 0))) {
      const tr = el("tr");
      const place = [x.hood, x.city].filter(Boolean).join(", ");
      const facts = [x.price ? I.money(x.price) : "", x.rooms ? `${I.num(x.rooms, 1)} ${t("rooms_short")}` : "", x.size_m2 ? `${x.size_m2} m²` : "",
        x.floor != null ? `${t("floor_short")} ${x.floor}` : ""].filter(Boolean).join(" · ");
      const why = el("td", "muted", x.why.join("; "));
      const link = el("td");
      if (x.url && RentalCards.SAFE_LINK.test(x.url)) {
        const a = el("a", null, `${t("open_on", { site: t(`site_${x.source || "yad2"}`) })} ↗`);
        a.href = x.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        link.append(a);
      }
      tr.append(el("td", null, facts), el("td", null, place), why, link);
      tb.append(tr);
    }
    d.append(tb);
    box.append(d);
  }
  return box;
}

/**
 * v1.41: send listings to someone without the extension: pick the lists, then a page to send
 * (one HTML file), text to paste, or the system's share menu. Made here; sent only by you.
 */
function openShare() {
  const dlg = $("sharebox");
  const all = listings();
  const S = RentalShare;
  const counts = Object.fromEntries(S.GROUPS.map((g) => [g, S.pick(all, data.marks, [g]).reduce((a, x) => a + x.listings.length, 0)]));
  const marked = counts.fav + counts.interested + counts.viewing > 0;
  const boxes = {};
  dlg.replaceChildren(el("h2", null, t("sx_title_dlg")), el("p", "muted", t("sx_x")));
  for (const g of S.GROUPS) {
    const l = el("label", "c");
    const b = el("input");
    b.type = "checkbox";
    b.checked = counts[g] > 0 && (marked ? g !== "all" : g === "all");
    b.disabled = !counts[g];
    boxes[g] = b;
    l.append(b, el("span", null, t({ fav: "rs_fav", interested: "rs_interested", viewing: "rs_viewing", all: "sx_all" }[g])), el("b", null, counts[g]));
    dlg.append(l);
  }
  const name = el("input");
  name.type = "text";
  name.value = t("sx_title");
  dlg.append(el("div", "muted", t("sx_name")), name);
  const done = el("div", "done");
  const chosen = () => S.pick(all, data.marks, S.GROUPS.filter((g) => boxes[g].checked));
  const ctx = () => ({ I, C: RentalCards, marks: data.marks, title: name.value.trim() || t("sx_title"), at: Date.now() });
  const count = (gs) => gs.reduce((a, x) => a + x.listings.length, 0);
  const file = async () => {
    const page = await S.html(chosen(), ctx()); // v1.46: embeds photos, so it's not instant
    const stamp = new Date().toISOString().slice(0, 10);
    return new File([page], `apartments-${stamp}.html`, { type: "text/html" });
  };
  const acts = el("div", "acts");
  const dl = el("button", "btn primary", t("sx_page"));
  dl.addEventListener("click", async () => {
    const gs = chosen();
    if (!count(gs)) return void (done.textContent = t("sx_pick"));
    done.textContent = t("sx_building");
    const f = await file();
    const a = el("a");
    a.href = URL.createObjectURL(f);
    a.download = f.name;
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    done.textContent = t("sx_page_done", { n: count(gs) });
  });
  const cp = el("button", "btn", t("sx_text"));
  cp.addEventListener("click", async () => {
    const gs = chosen();
    if (!count(gs)) return void (done.textContent = t("sx_pick"));
    try {
      await navigator.clipboard.writeText(S.text(gs, ctx()));
      done.textContent = t("sx_text_done", { n: count(gs) });
    } catch (e) {
      done.textContent = t("e_generic", { detail: String(e && e.message || e) });
    }
  });
  acts.append(dl, cp);
  // the system's own share menu, where the browser offers one for files (Windows, phones)
  try {
    if (navigator.canShare && navigator.canShare({ files: [new File(["x"], "x.html", { type: "text/html" })] })) {
      const sh = el("button", "btn", t("sx_system"));
      sh.addEventListener("click", async () => {
        const gs = chosen();
        if (!count(gs)) return void (done.textContent = t("sx_pick"));
        done.textContent = t("sx_building");
        try {
          await navigator.share({ files: [await file()], title: ctx().title });
          done.textContent = "";
        } catch (e) { /* cancelled, or the share sheet closed on its own */ }
      });
      acts.append(sh);
    }
  } catch (e) { /* no share menu here */ }
  const close = el("button", "btn", t("close"));
  close.addEventListener("click", () => dlg.close());
  acts.append(close);
  dlg.append(acts, done, el("p", "muted", t("sx_privacy")));
  dlg.showModal();
}

/** v1.40: "Missing a listing?" Paste its link; the answer says what the last search did with it. */
function finder() {
  const box = el("div", "panelbox");
  box.id = "finder";
  box.append(el("h2", null, t("fd_title")), el("p", "muted", t("fd_x")));
  const row = el("div", "fdrow");
  const input = el("input");
  input.type = "url";
  input.dir = "ltr";
  input.placeholder = "https://www.yad2.co.il/realestate/item/...";
  const go = el("button", "btn primary", t("fd_go"));
  const out = el("div", "fdout");
  const run = () => out.replaceChildren(...answer(RentalRunner.explain(input.value, data.results, data.marks)));
  go.addEventListener("click", run);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  row.append(input, go);
  box.append(row, out);
  return box;
}

function answer(a) {
  const p = (text, cls) => el("p", cls || null, text);
  switch (a.kind) {
    case "bad_link": return [p(t("fd_bad"), "err")];
    case "rejected": return [p(t("fd_rejected"))];
    case "shown": return [p(t("fd_shown", { n: a.rank }))];
    case "hidden": return [p(t("fd_hidden")), ...a.reasons.map((r) => p(`• ${r}`, "muted"))];
    case "merged": return [p(t("fd_merged"))];
    case "skipped": return [p(t("fd_skipped")), ...a.reasons.map((r) => p(`• ${r}`, "muted"))];
    case "unread": return [p(t("fd_unread"))];
    case "outside": return [p(t("fd_outside", { hood: a.hood || "?" }))];
    default: {
      const out = [p(t("fd_unseen", { when: a.at ? I.when(a.at) : "?" }))];
      for (const s of a.searches || []) {
        const name = I.lang === "he" ? s.label_he || s.label : s.label;
        out.push(p(`• ${name}: ${t("fd_cover", { total: s.total == null ? "?" : I.num(s.total, 0), seen: I.num(s.seen || 0, 0) })}`, "muted"));
      }
      return out;
    }
  }
}

/** v1.40: what each search covered: Yad2's own count, what was read, what's in your neighborhoods. */
function coverage() {
  const r = data.results || {};
  const sec = el("div", "panelbox");
  sec.append(el("h2", null, t("cv_title")), el("p", "muted", t("cv_x")));
  const tb = el("table");
  const hr = el("tr");
  for (const k of ["cv_search", "cv_total", "cv_seen", "cv_kept"]) hr.append(el("th", null, t(k)));
  tb.append(hr);
  for (const s of r.searches || []) {
    const tr = el("tr");
    const short = typeof s.total === "number" && typeof s.seen === "number" && s.seen < s.total;
    tr.append(el("td", null, I.lang === "he" ? s.label_he || s.label : s.label), el("td", null, s.total == null ? "–" : I.num(s.total, 0)),
      el("td", short ? "warn" : null, `${I.num(s.seen || 0, 0)}${short ? ` ⚠` : ""}${s.failed ? ` · ${t("cv_failed", { n: s.failed })}` : ""}`),
      el("td", null, s.kept == null ? "–" : I.num(s.kept, 0)));
    tb.append(tr);
  }
  sec.append(tb);
  return sec;
}

function stat(value, label, small) {
  const d = el("div", "stat");
  d.append(el("b", null, value), el("span", null, label));
  if (small) d.append(el("small", null, small));
  return d;
}

function renderStats() {
  const box = $("stats");
  box.replaceChildren(finder());
  if (data.results && (data.results.searches || []).length) box.append(coverage());
  const r = data.results;
  const shown = r ? (r.results || []).filter((x) => !x.excluded) : [];
  const grid = el("div", "stats");
  const rows = r && r.plan ? r.plan.rows : 0;
  grid.append(stat(I.num(rows, 0), t("ss_checked")), stat(I.num(shown.length, 0), t("ss_matches")),
    stat(I.num(((r && r.newIds) || []).length, 0), t("ss_new")));
  if (shown.length) grid.append(stat(I.money(shown.reduce((a, x) => a + (x.price || 0), 0) / shown.length), t("ss_rent")));
  const places = {};
  for (const x of shown) for (const v of x.trips || []) {
    const m = v.minutes != null ? v.minutes : v.about;
    if (typeof m === "number") (places[v.place] = places[v.place] || []).push(m);
  }
  for (const [place, ms] of Object.entries(places)) {
    grid.append(stat(t("min", { n: I.num(ms.reduce((a, b) => a + b, 0) / ms.length, 0) }), t("ss_commute", { place: `\u2068${place}\u2069` })));
  }
  const marks = Object.values(data.marks);
  grid.append(stat(I.num(marks.filter((m) => m.fav).length, 0), t("ss_favs")), stat(I.num(marks.filter((m) => m.status === "viewing").length, 0), t("ss_viewings")));
  const week = data.pulls.filter((p) => Date.now() - p.at < 7 * 864e5).length;
  grid.append(stat(I.num(week, 0), t("ss_week")));
  const e = RentalStore.estimate(data.pulls, (data.pulls.slice(-1)[0] || {}).searches || 1, Date.now());
  grid.append(stat(I.duration(e.first), t("ss_first"), e.measured.first ? "" : t("pp_est").trim()),
    stat(I.duration(e.repeat), t("ss_repeat"), e.measured.repeat ? "" : t("pp_est").trim()));
  // reading by hand: a glance at each listing in the search, and a proper read of each one opened
  const opened = data.pulls.reduce((a, p) => a + (p.opened || 0), 0);
  const glanced = data.pulls.reduce((a, p) => a + (p.rows || 0), 0);
  const saved = glanced * 10e3 + opened * 90e3 - data.pulls.reduce((a, p) => a + (p.ms || 0), 0);
  if (data.pulls.length) grid.append(stat(I.duration(Math.max(0, saved)), t("ss_saved"), t("ss_saved_note", { t: I.duration(glanced * 10e3 + opened * 90e3) })));
  box.append(grid);

  // v1.27: where this search's matches came from
  const by = {};
  for (const x of shown) by[x.source || "yad2"] = (by[x.source || "yad2"] || 0) + 1;
  if (Object.keys(by).length) {
    const sec = el("div", "panelbox");
    sec.append(el("h2", null, t("ss_sources")));
    const g = el("div", "stats");
    for (const site of ["yad2", "komo", "madlan"]) if (by[site]) g.append(stat(I.num(by[site], 0), t("ss_from", { site: t(`site_${site}`) })));
    sec.append(g);
    box.append(sec);
  }

  if (data.pulls.length) {
    const sec = el("div", "panelbox");
    sec.append(el("h2", null, t("ss_recent")));
    const tb = el("table");
    const hr = el("tr");
    for (const k of ["ss_when", "ss_took", "ss_listings", "ss_opened", "ss_matches", "ss_result"]) hr.append(el("th", null, t(k)));
    tb.append(hr);
    for (const p of data.pulls.slice().reverse().slice(0, 15)) {
      const tr = el("tr");
      for (const c of [`${I.when(p.at)} · ${t(p.kind === "repeat" ? "ss_kind_repeat" : "ss_kind_first")}`, I.duration(p.ms), I.num(p.rows || 0, 0),
        I.num(p.opened || 0, 0), I.num(p.shown || 0, 0), t(p.complete ? "ss_complete" : "ss_stopped")]) tr.append(el("td", null, c));
      tb.append(tr);
    }
    sec.append(tb);
    box.append(sec);
  }
  // v1.35: the listings searches read, as a file to label (no names, no phone numbers)
  const lab = el("div", "panelbox");
  const n = Object.keys(data.labelset || {}).length;
  lab.append(el("h2", null, t("ss_label_title")), el("p", "muted", t("ss_label_x")));
  const dl = el("button", "btn", t("ss_label_dl", { n }));
  dl.disabled = !n;
  dl.addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ about: "Rental Matcher: listings searches read, for labeling. Text and the site's own facts only; no names or phone numbers.",
      exported: new Date().toISOString(), listings: Object.values(data.labelset || {}) }, null, 1)], { type: "application/json" });
    const a = el("a");
    a.href = URL.createObjectURL(blob);
    a.download = `rental-matcher-listings-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  });
  lab.append(dl);
  box.append(lab);
  const log = el("div", "panelbox");
  log.append(el("h2", null, t("ss_log")));
  const entries = data.log.slice().reverse().slice(0, 30);
  if (!entries.length) log.append(el("div", "muted", t("ss_log_empty")));
  const ul = el("ul");
  for (const x of entries) {
    const what = x.kind === "pushback" ? t("lg_pushback", { what: t(x.what === "listing" ? "lg_what_listing" : "lg_what_search") })
      : x.kind === "check shown" ? t(x.again ? "lg_check_again" : "lg_check")
        : x.kind === "no check shown" ? t("lg_nocheck") : x.kind === "check completed" ? t("lg_solved") : x.kind;
    ul.append(el("li", null, `${I.when(x.at)} · ${what}`));
  }
  log.append(ul);
  box.append(log);
}

function render() {
  I.apply(document);
  $("lang").textContent = I.lang === "he" ? "English" : "עברית";
  const sort = $("sort");
  const cur = sort.value || "match";
  sort.replaceChildren();
  for (const k of ["match", "price", "commute", "marked"]) {
    const o = el("option", null, t(`sort_${k}`));
    o.value = k;
    o.selected = k === cur;
    sort.append(o);
  }
  const r = data.results;
  $("sub").textContent = r && r.finishedAt ? t("rs_last", { when: I.when(r.finishedAt), n: I.num(r.plan ? r.plan.rows : 0, 0) }) : "";
  for (const [id, k, x] of [["v-picks", "rs_picks", "rs_picks_x"], ["v-every", "rs_every", "rs_every_x"], ["v-stats", "rs_stats_v", "rs_stats_x"]]) {
    const b = $(id);
    b.replaceChildren(document.createTextNode(t(k)), el("small", null, t(x)));
    b.classList.toggle("on", b.dataset.v === (shelf ? "every" : view));
  }
  const listing = view !== "stats";
  $("listings").hidden = !listing;
  $("bar").hidden = !listing;
  $("detail").hidden = !listing;
  $("stats").hidden = listing;
  if (listing) renderList();
  else {
    $("chips").hidden = true;
    renderStats();
  }
}

async function load() {
  if (!undone) {
    undone = true;
    await store.undoNeither(); // v1.40: listings v1.37's "Neither" rejected come back (also on update)
  }
  const o = await chrome.storage.local.get(["results", "marks", "pulls", "log", "ui", "labelset"]);
  const ui = o.ui || {};
  if (!loaded && (ui.layout === "grid" || ui.layout === "shelves") && view !== "stats") view = ui.layout === "grid" ? "every" : "picks";
  loaded = true;
  detail = !!ui.detail;
  data = { results: o.results || null, marks: o.marks || {}, pulls: o.pulls || [], log: o.log || [], labelset: o.labelset || {}, ui };
  render();
}

$("q").addEventListener("input", renderList);
$("tune").addEventListener("click", () => { location.href = "compare.html"; });
$("share").addEventListener("click", () => openShare());
$("find").addEventListener("click", () => {
  view = "stats";
  shelf = null;
  render();
  const i = document.querySelector("#finder input");
  if (i) { i.scrollIntoView({ block: "center" }); i.focus(); }
});
$("sort").addEventListener("change", renderList);
$("setup").addEventListener("click", () => chrome.runtime.openOptionsPage());
$("pull").addEventListener("click", () => chrome.runtime.sendMessage({ type: "pull" }));
let loaded = false;
let undone = false;
let chipsOpen = false;
$("filt").addEventListener("click", () => { chipsOpen = !chipsOpen; renderList(); });
$("views").addEventListener("click", (e) => {
  const b = e.target.closest("button.view");
  if (!b) return;
  view = b.dataset.v;
  shelf = null;
  if (view !== "stats") saveUi({ layout: view === "every" ? "grid" : "shelves" });
  render();
});
const saveUi = async (patch) => {
  const { ui = {} } = await chrome.storage.local.get("ui");
  await chrome.storage.local.set({ ui: Object.assign(ui, patch) });
};
$("detail").addEventListener("click", (e) => {
  const d = e.target.dataset && e.target.dataset.d;
  if (d == null) return;
  detail = d === "1";
  saveUi({ detail });
  renderList();
});
$("lang").addEventListener("click", async () => {
  const { ui = {} } = await chrome.storage.local.get("ui");
  ui.lang = I.lang === "he" ? "en" : "he";
  await chrome.storage.local.set({ ui });
});
chrome.storage.onChanged.addListener((c, area) => {
  if (area !== "local") return;
  if (c.ui && c.ui.newValue && c.ui.newValue.lang && c.ui.newValue.lang !== I.lang) {
    I.setLang(c.ui.newValue.lang);
    render();
  }
  if (c.results || c.marks || c.pulls || c.log || c.ui) load();
});
if (location.hash === "#stats") view = "stats";
I.load(chrome.storage.local).then(load);
