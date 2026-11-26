/*
 * Rental Matcher: the quick setup (v1.30). One question a screen, big
 * buttons, about two minutes: where, the budget, rooms, a place you go to,
 * and what you can't live without. It edits the same preferences file the
 * settings page does (rental_matcher/setup.py checks and saves it), so
 * running it again changes those answers and keeps everything else. It
 * can be skipped at any point, straight to the full settings page.
 */
"use strict";

const I = RentalI18n;
const t = I.t;
const { el, iso, helper, MUST } = RentalSetup;
const $ = (id) => document.getElementById(id);
const clone = (o) => JSON.parse(JSON.stringify(o));

const RENT_MAX = 12000;
const RENT_STEP = 100;
const ROOMS = [1, 1.5, 2, 2.5, 3, 3.5, 4, 5];
const MINUTES = [10, 15, 20, 30, 45, 60];
const MODES = [["ebike", "🛵"], ["bike", "🚲"], ["walk", "🚶"], ["car", "🚗"]];
// what you can't live without: a tile each, and the preference it sets (rental_matcher/setup.py CATALOG names)
const NEEDS = [["mamad", "🛡️"], ["no_roommates", "🏠"], ["air_conditioning", "❄️"], ["parking", "🅿️"], ["balcony", "🌿"],
  ["elevator", "↕️"], ["not_ground_floor", "🏢"], ["pets_allowed", "🐾"], ["renovated", "✨"]];

let info = { catalog: [] };
let model = null;
let had = false; // a preferences file existed before
let cities = [];
let entries = new Map();
let at = 0;

const STEPS = [welcome, where, budget, rooms, place, needs, done];

// ---- the model ------------------------------------------------------------------------------

const pref = (name) => model.preferences.find((p) => p.name === name);
const priceP = () => model.preferences.find((p) => p.field === "price" && p.kind !== "at_least");
const minP = () => model.preferences.find((p) => p.field === "price" && p.kind === "at_least");

function fromCatalog(name) {
  const c = info.catalog.find((x) => x.name === name);
  if (!c) return null;
  const p = clone(c);
  delete p.group;
  return p;
}

// ---- screens --------------------------------------------------------------------------------

function show(i) {
  at = i;
  const dots = $("dots");
  dots.replaceChildren(...STEPS.map((_, j) => el("i", { class: j <= i ? "on" : "" })));
  dots.hidden = i === 0;
  const card = el("div", { class: "card" });
  STEPS[i](card);
  $("step").replaceChildren(card);
  const first = card.querySelector("input, .tile, button.primary");
  if (first && i > 0) first.focus({ preventScroll: true });
}

function nav(card, opts) {
  const n = el("div", { class: "nav" });
  if (at > 0) n.append(el("button", { class: "btn", text: t("back"), onclick: () => show(at - 1) }));
  n.append(el("span", { class: "sp" }));
  if (opts && opts.later) n.append(el("button", { class: "linkbtn", text: t("wz_later"), onclick: () => show(at + 1) }));
  const next = el("button", { class: "btn primary", text: (opts && opts.label) || t("next"), onclick: () => (opts && opts.go ? opts.go() : show(at + 1)) });
  n.append(next);
  card.append(n);
  return next;
}

function welcome(card) {
  card.append(el("div", { class: "hero", text: "🏡" }), el("h1", { text: t("wz_hi") }), el("p", { class: "lead", text: t("wz_hi_x") }));
  nav(card, { label: t("wz_start") });
}

function where(card) {
  card.append(el("h2", { text: t("wz_where") }), el("p", { class: "lead", text: t("wz_where_x") }));
  const input = el("input", { class: "wide", list: "cities", placeholder: t("su_city_ph"), autocomplete: "off" });
  const chips = el("div", { class: "chips" });
  const msg = el("div", { class: "msg" });
  const draw = () => {
    chips.replaceChildren(...model.searches.map((s, i) => el("span", { class: "chip" }, iso(I.lang === "he" ? s.label_he || s.label : s.label),
      el("button", { title: t("remove"), text: "×", onclick: () => { model.searches.splice(i, 1); draw(); } }))));
    next.disabled = !model.searches.length;
  };
  const add = async () => {
    const e = RentalSetup.findCity(entries, input.value);
    if (!e) {
      if (input.value.trim()) msg.textContent = t("su_pick_city");
      return;
    }
    msg.className = "msg";
    msg.textContent = t("su_finding", { x: I.lang === "he" ? e.he : e.en });
    const s = await RentalSetup.citySearch(e);
    const key = (x) => `${x.path}|${(x.hoods || []).join(",")}`;
    if (!model.searches.some((x) => key(x) === key(s))) model.searches.push(s);
    input.value = "";
    msg.className = "msg ok";
    msg.textContent = t("su_added", { x: I.lang === "he" ? e.he : e.en });
    draw();
  };
  input.addEventListener("change", add);
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") add(); });
  card.append(input, msg, chips, el("p", { class: "hint", text: t("wz_where_hint") }));
  const next = nav(card);
  draw();
}

function budget(card) {
  let p = priceP();
  if (!p) {
    p = fromCatalog("price") || { name: "price", label: "Monthly rent (ILS)", field: "price", kind: "ranged", relevance: 8, ideal: 4000, limit: 5000 };
    model.preferences.push(p);
  }
  card.append(el("h2", { text: t("wz_budget") }), el("p", { class: "lead", text: t("wz_budget_x") }));
  const money = el("div", { class: "money" });
  const lo = el("input", { type: "range", min: 0, max: RENT_MAX, step: RENT_STEP, "aria-label": t("su_budget_from") });
  const hi = el("input", { type: "range", min: 0, max: RENT_MAX, step: RENT_STEP, "aria-label": t("su_budget_to") });
  const fill = el("div", { class: "fill" });
  const draw = () => {
    const m = minP();
    const a = m ? m.limit : 0;
    lo.value = a;
    hi.value = Math.min(p.limit, RENT_MAX);
    money.replaceChildren(document.createTextNode(a ? `${I.money(a)} – ${I.money(p.limit)}` : `${t("su_budget_to")} ${I.money(p.limit)}`),
      el("small", { text: ` ${t("a_month")}` }));
    fill.style.insetInlineStart = `${(a / RENT_MAX) * 100}%`;
    fill.style.insetInlineEnd = `${100 - (Math.min(p.limit, RENT_MAX) / RENT_MAX) * 100}%`;
  };
  lo.addEventListener("input", () => {
    const v = Math.min(Number(lo.value), p.limit - RENT_STEP);
    let m = minP();
    if (v <= 0) model.preferences = model.preferences.filter((x) => x !== m);
    else {
      if (!m) model.preferences.push(m = { name: "rent_min", label: "Minimum rent (ILS)", field: "price", kind: "at_least", relevance: MUST, limit: v });
      m.limit = v;
    }
    draw();
  });
  hi.addEventListener("input", () => {
    const m = minP();
    const v = Math.max(Number(hi.value), (m ? m.limit : 0) + RENT_STEP);
    for (const o of p.overrides || []) if (o.limit != null) o.limit += v - p.limit;
    p.limit = v;
    p.kind = "ranged";
    p.ideal = Math.max(0, Math.round((v * 0.9) / 50) * 50); // up to 10% under the top is "perfect"; the settings page can change it
    draw();
  });
  card.append(money, el("div", { class: "dual" }, el("div", { class: "track" }), fill, lo, hi),
    el("div", { class: "ends" }, el("span", { text: I.money(0) }), el("span", { text: I.money(RENT_MAX) })),
    el("p", { class: "hint", text: t("wz_budget_hint") }));
  draw();
  nav(card);
}

function rooms(card) {
  card.append(el("h2", { text: t("wz_rooms") }), el("p", { class: "lead", text: t("wz_rooms_x") }));
  const tiles = el("div", { class: "tiles small" });
  const draw = () => {
    const r = pref("rooms");
    tiles.replaceChildren(el("button", { class: `tile${!r ? " on" : ""}`, onclick: () => set(null) }, el("span", { class: "nm", text: t("wz_any") })),
      ...ROOMS.map((n) => el("button", { class: `tile${r && r.limit === n ? " on" : ""}`, onclick: () => set(n) },
        el("span", { class: "nm", text: n === 5 ? "5+" : I.num(n) }))));
  };
  const set = (n) => {
    let r = pref("rooms");
    if (n == null) model.preferences = model.preferences.filter((x) => x !== r);
    else {
      if (!r) model.preferences.push(r = fromCatalog("rooms") || { name: "rooms", label: "Rooms", field: "rooms", kind: "at_least", relevance: MUST, limit: n });
      r.limit = n;
      r.relevance = MUST;
    }
    draw();
  };
  card.append(tiles);
  draw();
  nav(card);
}

function place(card) {
  card.append(el("h2", { text: t("wz_place") }), el("p", { class: "lead", text: t("wz_place_x") }));
  model.commutes = model.commutes || [];
  let c = model.commutes[0];
  const draft = c ? { name: c.label.split(" (")[0], address: (c.label.match(/\((.*)\)$/) || [])[1] || "", lat: c.lat, lng: c.lng, mode: c.mode,
    limit: (model.preferences.find((p) => p.field === `signal:${c.signal}`) || {}).limit || 20 }
    : { name: "", address: "", lat: null, lng: null, mode: "ebike", limit: 20 };
  const name = el("input", { class: "wide", value: draft.name, placeholder: t("wz_place_name") });
  const addr = el("input", { class: "wide", value: draft.address, placeholder: t("su_address_ph") });
  const picks = el("div", { class: "picks" });
  const chosen = el("div", { class: "msg ok" });
  if (draft.lat != null) chosen.textContent = `✓ ${draft.address || draft.name}`;
  const find = el("button", { class: "btn", text: t("su_find"), onclick: async () => {
    picks.replaceChildren(el("span", { class: "hint", text: t("su_looking") }));
    const r = await helper("/places", { q: addr.value });
    picks.replaceChildren();
    if (!r || !r.ok) return picks.append(el("span", { class: "hint", text: t("su_lookup_failed") }));
    if (!r.body.places.length) return picks.append(el("span", { class: "hint", text: t("su_nothing") }));
    for (const pl of r.body.places) {
      picks.append(el("button", { class: "pick", onclick: () => {
        draft.lat = pl.lat;
        draft.lng = pl.lng;
        draft.address = pl.label;
        addr.value = pl.label;
        picks.replaceChildren();
        chosen.textContent = `✓ ${pl.label}`;
      } }, iso(pl.label)));
    }
  } });
  addr.addEventListener("keydown", (ev) => { if (ev.key === "Enter") find.click(); });
  const modes = el("div", { class: "tiles small" });
  const drawModes = () => modes.replaceChildren(...MODES.map(([m, ic]) => el("button", { class: `tile${draft.mode === m ? " on" : ""}`,
    onclick: () => { draft.mode = m; drawModes(); } }, el("span", { class: "ic", text: ic }), el("span", { class: "nm", text: t(`mode_${m}`) }))));
  const mins = el("div", { class: "tiles small" });
  const drawMins = () => mins.replaceChildren(...MINUTES.map((n) => el("button", { class: `tile${draft.limit === n ? " on" : ""}`,
    onclick: () => { draft.limit = n; drawMins(); } }, el("span", { class: "nm", text: t("min", { n }) }))));
  drawModes();
  drawMins();
  card.append(el("label", { class: "label", text: t("wz_place_what") }), name,
    el("label", { class: "label", text: t("su_address") }), el("div", { class: "row" }, addr, find), chosen, picks,
    el("label", { class: "label", text: t("wz_place_how") }), modes,
    el("label", { class: "label", text: t("wz_place_max") }), mins);
  const msg = el("div", { class: "msg" });
  card.append(msg);
  nav(card, { later: true, go: () => {
    if (draft.lat == null) {
      msg.textContent = t("wz_place_find");
      return;
    }
    const label = `${name.value.trim() || t("su_place")} (${draft.address})`;
    if (!c) {
      const used = new Set([...model.commutes.map((x) => x.signal), ...model.preferences.map((p) => p.name)]);
      let i = 1;
      while (used.has(`commute_${i}_minutes`)) i++;
      c = { signal: `commute_${i}_minutes` };
      model.commutes.unshift(c);
    }
    Object.assign(c, { label, lat: draft.lat, lng: draft.lng, mode: draft.mode });
    if (draft.mode === "car") delete c.speed_kmh;
    let p = model.preferences.find((x) => x.field === `signal:${c.signal}`);
    if (!p) model.preferences.push(p = { name: c.signal, field: `signal:${c.signal}`, relevance: MUST });
    const MODE_EN = { ebike: "E-bike", bike: "Bike", walk: "Walk", car: "Car" };
    Object.assign(p, { label: `${MODE_EN[draft.mode]} time to ${name.value.trim() || "work"} (min)`, kind: "ranged",
      ideal: Math.max(1, Math.round(draft.limit / 2)), limit: draft.limit, relevance: MUST });
    show(at + 1);
  } });
}

function needs(card) {
  card.append(el("h2", { text: t("wz_needs") }), el("p", { class: "lead", text: t("wz_needs_x") }),
    el("div", { class: "legend" }, el("span", {}, el("b", { class: "m", text: t("wz_must") }), document.createTextNode(` ${t("wz_must_x")}`)),
      el("span", {}, el("b", { class: "n", text: t("wz_nice") }), document.createTextNode(` ${t("wz_nice_x")}`))));
  const tiles = el("div", { class: "tiles" });
  const state = (name) => {
    const p = pref(name);
    return !p ? "off" : p.relevance === MUST ? "must" : "nice";
  };
  const cycle = (name) => {
    const s = state(name);
    let p = pref(name);
    if (s === "off") {
      if (!p) model.preferences.push(p = fromCatalog(name));
      if (!p) return;
      p.relevance = MUST;
      delete p.weight;
      if (name === "parking") p.limit = 1;
    } else if (s === "must") {
      p.relevance = 7;
      p.weight = 7;
    } else {
      model.preferences = model.preferences.filter((x) => x !== p);
    }
    draw();
  };
  const draw = () => tiles.replaceChildren(...NEEDS.filter(([n]) => info.catalog.some((c) => c.name === n)).map(([n, ic]) => {
    const s = state(n);
    return el("button", { class: `tile ${s}`, onclick: () => cycle(n), "aria-pressed": s === "off" ? "false" : "true" },
      el("span", { class: "ic", text: ic }), el("span", { class: "nm", text: t(`wz_n_${n}`) }),
      el("span", { class: "st", text: s === "must" ? t("wz_must") : s === "nice" ? t("wz_nice") : "" }));
  }));
  card.append(tiles, el("p", { class: "hint", text: t("wz_needs_hint") }));
  draw();
  nav(card);
}

function done(card) {
  card.append(el("h2", { text: t("wz_done") }), el("p", { class: "lead", text: t("wz_done_x") }));
  const p = priceP();
  const m = minP();
  const r = pref("rooms");
  const c = (model.commutes || [])[0];
  const cp = c && model.preferences.find((x) => x.field === `signal:${c.signal}`);
  const musts = model.preferences.filter((x) => x.relevance === MUST && NEEDS.some(([n]) => n === x.name)).map((x) => t(`wz_n_${x.name}`));
  const nice = model.preferences.filter((x) => x.relevance !== MUST && NEEDS.some(([n]) => n === x.name)).map((x) => t(`wz_n_${x.name}`));
  const line = (k, v) => (v ? el("div", {}, el("b", { text: t(k) }), el("span", {}, typeof v === "string" ? iso(v) : v)) : null);
  card.append(el("div", { class: "summary" },
    line("wz_s_where", model.searches.map((s) => (I.lang === "he" ? s.label_he || s.label : s.label)).join(", ")),
    line("wz_s_budget", p ? (m ? `${I.money(m.limit)} – ${I.money(p.limit)}` : `${t("su_budget_to")} ${I.money(p.limit)}`) : ""),
    line("wz_s_rooms", r ? `${I.num(r.limit)}+` : t("wz_any")),
    line("wz_s_place", c && cp ? `${c.label.split(" (")[0]} · ${t(`mode_${c.mode}`)} · ${t("min", { n: cp.limit })}` : ""),
    line("wz_must", musts.join(", ")), line("wz_nice", nice.join(", "))));
  const msg = el("div", { class: "msg" });
  card.append(msg);
  if (had) card.append(el("p", { class: "hint", text: t("wz_keeps") }));
  nav(card, { label: t("wz_save"), go: async () => {
    msg.className = "msg";
    msg.textContent = t("su_saving");
    const prefs = clone(model);
    for (const x of prefs.commutes || []) delete x._address;
    const res = await helper("/saveprefs", { prefs });
    if (!res || !res.ok || !res.body.saved) {
      msg.textContent = (res && res.body && (res.body.error || (res.body.errors || []).join("; "))) || t("su_no_helper");
      return;
    }
    await onboarded();
    $("dots").hidden = true;
    $("step").replaceChildren(el("div", { class: "card" }, el("div", { class: "hero", text: "🎉" }), el("h1", { text: t("wz_ready") }),
      el("p", { class: "lead", text: t("wz_ready_x") }),
      el("div", { class: "nav" }, el("button", { class: "btn", text: t("wz_settings"), onclick: () => { location.href = chrome.runtime.getURL("options.html"); } }),
        el("span", { class: "sp" }),
        el("button", { class: "btn primary", text: t("wz_find"), onclick: () => chrome.runtime.sendMessage({ type: "pull" }) }))));
  } });
}

async function onboarded() {
  const { ui = {} } = await chrome.storage.local.get("ui");
  ui.onboarded = true;
  await chrome.storage.local.set({ ui });
}

// ---- page -----------------------------------------------------------------------------------

function words() {
  I.apply(document);
  document.title = `${t("app")} · ${t("wz_title")}`;
  $("lang").textContent = I.lang === "he" ? "English" : "עברית";
  entries = RentalSetup.cityEntries(cities, I.lang);
  const dl = $("cities");
  dl.replaceChildren(...Array.from(entries.keys()).map((k) => el("option", { value: k })));
  if (model) show(at);
}

$("skip").addEventListener("click", async () => {
  await onboarded();
  location.href = chrome.runtime.getURL("options.html");
});
$("lang").addEventListener("click", async () => {
  const { ui = {} } = await chrome.storage.local.get("ui");
  ui.lang = I.lang === "he" ? "en" : "he";
  await chrome.storage.local.set({ ui });
  I.setLang(ui.lang);
  words();
});

(async () => {
  await I.load(chrome.storage.local);
  cities = await RentalSetup.loadCities();
  const r = await helper("/prefs");
  if (!r || !r.ok) {
    words();
    $("step").replaceChildren(el("div", { class: "card" }, el("h2", { text: t("su_no_helper") })));
    return;
  }
  info = r.body;
  had = !!r.body.prefs;
  model = had ? clone(r.body.prefs) : clone(RentalSetup.STARTER);
  model.searches = model.searches || [];
  model.commutes = model.commutes || [];
  if (!had) for (const n of ["price", "no_roommates", "mamad"]) { const p = fromCatalog(n); if (p) model.preferences.push(p); }
  words();
})();
