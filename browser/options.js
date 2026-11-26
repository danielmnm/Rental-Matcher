/*
 * Rental Matcher: the setup page (v1.30), in English or Hebrew. It edits
 * the preferences file the helper reads (preferences/<you>.json) the way a
 * person thinks about a search: cities and neighborhoods, places to get to,
 * a budget, must-haves and how much everything else counts. Saving sends
 * the whole file to the helper, which checks it and keeps the previous
 * version (rental_matcher/setup.py). A first visit starts with the quick
 * setup (wizard.html), which can be skipped to come straight here.
 *
 * v1.30: every setting says what it does in a sentence under it; importance
 * is 1-10 in words; the budget is a two-handle range (its low end hides
 * listings that are too cheap to be what you want); "worth paying more
 * for" replaces the one-off "with a balcony" budget; the raw file is gone.
 */
"use strict";
const root = globalThis;

const $ = (id) => document.getElementById(id);
const I = RentalI18n;
const t = I.t;
const { el, iso, helper, MUST, MUST_POINTS, SEARCH_PATH, JAFFA, TLV, yad2Where, loadHoods } = RentalSetup;
const clone = (o) => JSON.parse(JSON.stringify(o));
const SPEED = { ebike: 20, bike: 14, walk: 5 };
const MODES = ["ebike", "bike", "walk", "car"];
const FIELD_TOPIC = {
  price: "rent", size_m2: "size", rooms: "rooms", "signal:parking_level": "parking", "signal:balcony": "balcony",
  "signal:elevator": "elevator", "signal:air_conditioning": "ac", "signal:protected_space": "shelter", "signal:roommate_listing": "whole",
  "signal:days_until_available": "movein", "signal:renovated": "renovated", "signal:furniture": "furniture", "signal:pets_allowed": "pets",
  "signal:accessible": "accessible", "signal:has_photos": "photos", "signal:housing_unit": "unit", "signal:short_lease": "lease",
};
const BASICS = new Set(["rent", "size", "rooms", "floor_ground", "floor_high", "movein"]);
const FURNITURE = ["sofa", "bed", "table_chairs", "cabinet", "fridge", "washer", "dryer", "dishwasher", "microwave", "tv"];

let info = { catalog: [] };
let model = null; // the preferences being edited
let saved = ""; // the file as last loaded or saved
let cities = []; // [code, hebrew, english]
const cityPick = new Map(); // datalist text -> {code, he, en, preset}


// ---- what a preference is about --------------------------------------------------------

function commuteOf(p) {
  return (model.commutes || []).find((c) => p.field === `signal:${c.signal}`);
}

function topicOf(p) {
  const c = commuteOf(p);
  if (c) return { topic: "commute", place: c.label.split(" (")[0], mode: c.mode };
  if (p.field === "floor") return { topic: p.kind === "at_least" ? "floor_ground" : "floor_high" };
  if (p.field === "price" && p.kind === "at_least") return { topic: "rent_min" };
  return { topic: FIELD_TOPIC[p.field] || "custom", label: p.label };
}

// ---- must-have, and how much it counts --------------------------------------------------

function defaultPoints(p) {
  return p.relevance === MUST ? (p.kind === "ranged" ? MUST_POINTS : 0) : p.relevance;
}

// a must-have where better still counts: a range (a shorter trip, a cheaper rent); a line or a yes/no just passes or not
const graded = (p) => p.kind === "ranged";

/** Must-have (a switch) and how important (1-10, in words). A yes/no must-have has nothing to weigh. */
function importance(p, also) {
  const linked = [p].concat(also || []);
  const wrap = el("div", { class: "imp" });
  const must = el("input", { type: "checkbox", role: "switch" });
  must.checked = p.relevance === MUST;
  // v1.33: "Must-have", with what it does in small print under it
  const mustLbl = el("label", { class: "must" }, must, el("span", { class: "sw", "aria-hidden": "true" }),
    el("span", { class: "must-t" }, el("b", { text: t("su_must") }), el("small", { text: t("su_must_hint") })));
  const r = el("input", { type: "range", min: 1, max: 10, step: 1, "aria-label": t("su_counts") });
  const val = el("b", { class: "val" });
  const rowTitle = el("span", { class: "imp-t" });
  const row = el("div", { class: "imp-row" }, rowTitle,
    el("div", { class: "imp-scale" }, el("small", { text: t("su_imp_lo") }), r, el("small", { text: t("su_imp_hi") })), val);
  const pts = () => (p.weight != null ? p.weight : defaultPoints(p));
  const show = () => {
    const isMust = must.checked;
    row.hidden = isMust && !graded(p);
    rowTitle.textContent = isMust ? t("su_imp_better") : t("su_counts");
    const v = Math.max(1, Math.min(10, pts() || (isMust ? MUST_POINTS : 5)));
    r.value = v;
    r.style.setProperty("--fill", `${((v - 1) / 9) * 100}%`);
    val.textContent = t("imp_of", { n: v, w: t(`imp_${v}`) });
    mustLbl.classList.toggle("on", isMust);
  };
  must.addEventListener("change", () => {
    for (const q of linked) {
      const v = Math.max(1, Math.min(10, (q.weight != null ? q.weight : defaultPoints(q)) || 5));
      if (must.checked) {
        q.relevance = MUST;
        if (graded(q)) q.weight = v;
        else delete q.weight;
      } else {
        q.relevance = Math.min(9, v);
        q.weight = v;
      }
    }
    show();
    changed();
  });
  r.addEventListener("input", () => {
    const v = Number(r.value);
    for (const q of linked) {
      q.weight = v;
      if (q.relevance !== MUST) q.relevance = Math.min(9, v);
    }
    show();
    changed();
  });
  show();
  if (p.kind !== "has_items") wrap.append(mustLbl);
  wrap.append(row);
  return wrap;
}

// ---- "what this does", under every setting ------------------------------------------------

let effects = []; // [element, () => sentence]

function effect(fn) {
  const e = el("p", { class: "effect" });
  effects.push([e, fn]);
  return e;
}

function refreshEffects() {
  for (const [e, fn] of effects) {
    let text = "";
    try {
      text = fn() || "";
    } catch (err) {
      text = "";
    }
    e.textContent = text;
    e.hidden = !text;
  }
}

const money = (n) => I.money(n);
const isMust = (p) => p && p.relevance === MUST;
const PK = { 3: "pk_3", 2: "pk_2", 1: "pk_1", 0: "pk_0" };

function effectOf(p) {
  const tp = topicOf(p).topic;
  if (p.kind === "yes_no") return t(isMust(p) ? "ef_hide_without" : "ef_rank_with");
  if (p.kind === "has_items") return t("ef_items");
  if (tp === "size") {
    const line = t(isMust(p) ? "ef_size_must" : "ef_size_soft", { limit: I.num(p.limit) });
    return p.kind === "ranged" && p.ideal != null ? `${line} ${t("ef_size_ideal", { ideal: I.num(p.ideal) })}` : line;
  }
  if (tp === "rooms") return t(isMust(p) ? "ef_rooms_must" : "ef_rooms_soft", { limit: I.num(p.limit) });
  if (tp === "rent_min") return t(isMust(p) ? "ef_min_must" : "ef_min_soft", { limit: money(p.limit) });
  if (tp === "movein") {
    const ideal = !p.ideal ? t("ef_now") : t("ef_within", { n: p.ideal });
    return t(isMust(p) ? "ef_movein_must" : "ef_movein_soft", { ideal, limit: p.limit });
  }
  if (tp === "parking" && p.kind === "ranged") {
    const must = isMust(p) && p.limit > 0;
    return t(must ? "ef_parking_must" : "ef_parking_soft", { ideal: t(PK[p.ideal] || "pk_3"), limit: t(PK[p.limit] || "pk_0").toLowerCase() });
  }
  if (tp === "commute") {
    if (p.kind === "ranged" && p.ideal != null) return t(isMust(p) ? "ef_commute_must" : "ef_commute_soft", { ideal: p.ideal, limit: p.limit });
    return p.limit != null ? t(isMust(p) ? "ef_commute_line" : "ef_line_soft", { limit: t("min", { n: p.limit }) }) : "";
  }
  if ((p.kind === "at_most" || p.kind === "at_least") && p.limit != null) return t(isMust(p) ? "ef_line_must" : "ef_line_soft", { limit: I.num(p.limit) });
  return "";
}

function rentEffect(p) {
  const min = minRent();
  const tol = p.tolerance || 0;
  const hides = isMust(p) || tol > 0;
  let s = p.ideal != null ? t("ef_rent", { ideal: money(p.ideal), max: money(p.limit) }) : "";
  if (tol > 0) s += t("ef_rent_tol", { max: money(p.limit), hide: money(p.limit + tol) });
  s += hides ? t("ef_rent_hide", { hide: money(p.limit + tol) }) : t("ef_rent_soft", { max: money(p.limit) });
  if (min && min.limit > 0) s += t("ef_rent_min", { min: money(min.limit) });
  for (const o of p.overrides || []) {
    if (o.limit != null && WORTH.includes(o.when_signal)) s += t("ef_rent_worth", { what: worthName(o.when_signal), to: money(o.limit) });
  }
  return s.trim();
}

function num(obj, key, label, opts) {
  const i = el("input", { type: "number", step: "any", value: obj[key] == null ? "" : obj[key], placeholder: (opts && opts.placeholder) || "" });
  i.addEventListener("input", () => {
    if (i.value === "") delete obj[key];
    else obj[key] = Number(i.value);
    if (opts && opts.then) opts.then();
    changed();
  });
  return el("label", { class: "f" }, el("span", { text: label }), i);
}

function choice(obj, key, label, values, prefix) {
  const s = el("select", {});
  for (const v of values) s.append(el("option", { value: v, text: t(`${prefix}${v}`), selected: Number(obj[key]) === v }));
  if (!values.includes(Number(obj[key])) && obj[key] != null) s.prepend(el("option", { value: obj[key], text: String(obj[key]), selected: true }));
  s.addEventListener("change", () => {
    obj[key] = Number(s.value);
    changed();
  });
  return el("label", { class: "f" }, el("span", { text: label }), s);
}

function removeBtn(ps) {
  return el("button", { class: "btn small danger", text: t("remove"), onclick: () => {
    model.preferences = model.preferences.filter((x) => !ps.includes(x));
    render();
    changed();
  } });
}

// ---- the budget: a two-handle range, a "perfect" price, a little over, worth paying more for ------

const RENT_MAX = 12000;
const RENT_STEP = 100;
// features one may pay more for: yes/no facts a listing states (the override's condition)
const WORTH = ["balcony", "elevator", "air_conditioning", "protected_space", "renovated", "pets_allowed", "accessible"];
const WORTH_TOPIC = { balcony: "balcony", elevator: "elevator", air_conditioning: "ac", protected_space: "shelter", renovated: "renovated",
  pets_allowed: "pets", accessible: "accessible" };
const worthName = (signal) => I.topicTitle({ topic: WORTH_TOPIC[signal] || "custom", label: signal });
const minRent = () => model.preferences.find((x) => x.field === "price" && x.kind === "at_least");

function setMinRent(v) {
  let m = minRent();
  if (!v || v <= 0) {
    if (m) model.preferences = model.preferences.filter((x) => x !== m);
    return;
  }
  if (!m) {
    m = { name: "rent_min", label: "Minimum rent (ILS)", field: "price", kind: "at_least", relevance: MUST, limit: v };
    model.preferences.push(m);
  }
  m.limit = v;
}

function rentItem(p) {
  const item = el("div", { class: "item rent" });
  item.append(el("div", { class: "item-h" }, el("b", { text: t("su_budget") }), el("button", { class: "btn small danger", text: t("remove"), onclick: () => {
    model.preferences = model.preferences.filter((x) => x !== p && x !== minRent());
    render();
    changed();
  } })));
  if (p.kind !== "ranged" || p.ideal == null) {
    p.kind = "ranged";
    p.ideal = Math.max(0, (p.limit || 5000) - 500);
  }
  // the range: from (hides cheaper) - up to (the most you'd pay)
  const lo = el("input", { type: "range", min: 0, max: RENT_MAX, step: RENT_STEP, class: "lo", "aria-label": t("su_budget_from") });
  const hi = el("input", { type: "range", min: 0, max: RENT_MAX, step: RENT_STEP, class: "hi", "aria-label": t("su_budget_to") });
  const fill = el("div", { class: "fill" });
  const loN = el("input", { type: "number", min: 0, step: RENT_STEP });
  const hiN = el("input", { type: "number", min: 0, step: RENT_STEP });
  const loNote = el("small", { class: "muted" });
  const draw = () => {
    const m = minRent();
    const a = m ? m.limit : 0;
    const b = p.limit;
    lo.value = a;
    hi.value = Math.min(b, RENT_MAX);
    if (document.activeElement !== loN) loN.value = a || "";
    if (document.activeElement !== hiN) hiN.value = b;
    loN.placeholder = t("su_budget_none");
    loNote.textContent = a ? "" : t("su_budget_none");
    fill.style.insetInlineStart = `${(Math.min(a, RENT_MAX) / RENT_MAX) * 100}%`;
    fill.style.insetInlineEnd = `${100 - (Math.min(b, RENT_MAX) / RENT_MAX) * 100}%`;
  };
  const setHi = (v) => {
    const m = minRent();
    v = Math.max(v, (m ? m.limit : 0) + RENT_STEP);
    const delta = v - p.limit;
    for (const o of p.overrides || []) if (o.limit != null) o.limit += delta; // "+₪500 for a balcony" moves with the budget
    p.limit = v;
    if (p.ideal >= v) p.ideal = Math.max(0, v - 250);
    if (document.activeElement !== ideal) ideal.value = p.ideal;
  };
  const setLo = (v) => setMinRent(Math.min(v, p.limit - RENT_STEP));
  lo.addEventListener("input", () => { setLo(Number(lo.value)); draw(); changed(); });
  hi.addEventListener("input", () => { setHi(Number(hi.value)); draw(); changed(); });
  loN.addEventListener("change", () => { setLo(Number(loN.value) || 0); draw(); changed(); });
  hiN.addEventListener("change", () => { if (Number(hiN.value) > 0) setHi(Number(hiN.value)); draw(); changed(); });
  const dual = el("div", { class: "dual" }, el("div", { class: "track" }), fill, lo, hi);
  const ends = el("div", { class: "fields" },
    el("label", { class: "f" }, el("span", { text: t("su_budget_from") }), el("div", { class: "money" }, el("i", { text: "₪" }), loN)),
    el("label", { class: "f" }, el("span", { text: t("su_budget_to") }), el("div", { class: "money" }, el("i", { text: "₪" }), hiN)));
  // perfect price
  const ideal = el("input", { type: "number", min: 0, step: 50, value: p.ideal });
  ideal.addEventListener("input", () => {
    const v = Number(ideal.value);
    if (ideal.value !== "" && v >= 0 && v < p.limit) p.ideal = v;
    changed();
  });
  const perfect = el("label", { class: "inline" }, el("span", { text: t("su_rent_perfect") }), ideal);
  // a little over budget
  const overOn = el("input", { type: "checkbox" });
  overOn.checked = (p.tolerance || 0) > 0;
  const over = el("input", { type: "number", min: 0, step: 50, value: p.tolerance || Math.round((p.limit * 0.1) / 50) * 50 });
  const overF = el("label", { class: "inline" }, el("span", { text: t("su_over_up_to") }), over);
  const syncOver = () => {
    overF.hidden = !overOn.checked;
    if (overOn.checked) p.tolerance = Math.max(0, Number(over.value) || 0);
    else delete p.tolerance;
  };
  overOn.addEventListener("change", () => { syncOver(); changed(); });
  over.addEventListener("input", () => { syncOver(); changed(); });
  syncOver();
  const overRow = el("div", { class: "row" }, el("label", { class: "c" }, overOn, el("span", { text: t("su_over_ok") })), overF);
  // worth paying more for
  const worth = el("div", { class: "worth" });
  const drawWorth = () => {
    worth.replaceChildren(el("b", { text: t("su_worth") }), el("p", { class: "muted", text: t("su_worth_lead") }));
    p.overrides = (p.overrides || []).filter((o) => o.when_signal);
    for (const o of p.overrides) {
      if (!WORTH.includes(o.when_signal) || o.limit == null) continue;
      const sel = el("select", {});
      for (const w of WORTH) sel.append(el("option", { value: w, text: worthName(w), selected: o.when_signal === w }));
      sel.addEventListener("change", () => { o.when_signal = sel.value; changed(); });
      const more = el("input", { type: "number", min: 0, step: 50, value: o.limit - p.limit });
      more.addEventListener("input", () => { o.limit = p.limit + Math.max(0, Number(more.value) || 0); changed(); });
      worth.append(el("div", { class: "row worth-row" }, sel, el("span", { class: "muted", text: t("su_worth_more") }), more,
        el("button", { class: "btn small danger", text: "×", title: t("remove"), onclick: () => {
          p.overrides = p.overrides.filter((x) => x !== o);
          drawWorth();
          changed();
        } })));
    }
    const used = new Set(p.overrides.map((o) => o.when_signal));
    const next = WORTH.find((w) => !used.has(w));
    if (next) {
      worth.append(el("button", { class: "btn small", text: t("su_worth_add"), onclick: () => {
        p.overrides.push({ when_signal: next, limit: p.limit + 500 });
        drawWorth();
        changed();
      } }));
    }
  };
  drawWorth();
  draw();
  item.append(dual, ends, perfect, overRow, worth, effect(() => rentEffect(p)), importance(p));
  return item;
}

function prefItem(p) {
  const tp = topicOf(p);
  const item = el("div", { class: "item" });
  item.append(el("div", { class: "item-h" }, el("b", {}, iso(I.topicTitle(tp))), removeBtn([p])));
  const fields = el("div", { class: "fields" });
  if (tp.topic === "rent_min") fields.append(num(p, "limit", t("su_budget_from")));
  else if (tp.topic === "size") {
    fields.append(num(p, "limit", t("su_size_min")));
    if (p.kind === "ranged") fields.append(num(p, "ideal", t("su_size_ideal"))); // v1.39: bigger is better, up to this
  }
  else if (tp.topic === "rooms") fields.append(num(p, "limit", t("su_rooms_min")));
  else if (tp.topic === "movein") {
    fields.append(choice(p, "ideal", t("su_movein_ideal"), [0, 14, 30, 60], "mv_"), choice(p, "limit", t("su_movein_latest"), [30, 45, 60, 90, 180], "mv_"));
  } else if (tp.topic === "parking" && p.kind === "ranged") {
    fields.append(choice(p, "ideal", t("su_pk_ideal"), [3, 2, 1], "pk_"), choice(p, "limit", t("su_pk_min"), [2, 1, 0], "pk_"));
  } else if (p.kind === "has_items") {
    const boxes = el("div", { class: "boxes" });
    for (const id of FURNITURE) {
      const cb = el("input", { type: "checkbox" });
      cb.checked = (p.items || []).includes(id);
      cb.addEventListener("change", () => {
        const set = new Set(p.items || []);
        if (cb.checked) set.add(id);
        else set.delete(id);
        p.items = Array.from(set);
        changed();
      });
      boxes.append(el("label", {}, cb, I.feature({ key: `item_${id}` })));
    }
    fields.append(boxes);
  } else if (p.kind === "ranged") fields.append(num(p, "ideal", t("su_ideal")), num(p, "limit", t("su_limit")));
  else if (p.kind === "at_most" || p.kind === "at_least") fields.append(num(p, "limit", t("su_limit")), num(p, "tolerance", t("su_tol"), { placeholder: t("su_none_ph") }));
  if (fields.childNodes.length) item.append(fields);
  item.append(effect(() => effectOf(p)), importance(p));
  return item;
}

/** The two floor rules as one setting: ground floor or not, and how high without an elevator. */
function floorItem(ground, high) {
  const item = el("div", { class: "item" });
  item.append(el("div", { class: "item-h" }, el("b", { text: t("su_floor") }), removeBtn([ground, high].filter(Boolean))));
  const ok = el("input", { type: "checkbox" });
  ok.checked = !ground;
  ok.addEventListener("change", () => {
    if (ok.checked) model.preferences = model.preferences.filter((x) => x !== ground);
    else model.preferences.push({ name: "not_ground_floor", label: "Floor (not ground)", field: "floor", kind: "at_least", relevance: high ? high.relevance : MUST, limit: 1 });
    render();
    changed();
  });
  const fields = el("div", { class: "fields" });
  fields.append(el("label", { class: "c" }, ok, el("span", { text: t("su_floor_ground") })));
  if (high) {
    fields.append(num(high, "limit", t("su_floor_max")));
    const elev = el("input", { type: "checkbox" });
    const o = (high.overrides || []).find((x) => x.when_signal === "elevator");
    elev.checked = !!(o && o.limit >= 50);
    elev.addEventListener("change", () => {
      high.overrides = (high.overrides || []).filter((x) => x.when_signal !== "elevator");
      if (elev.checked) high.overrides.push({ when_signal: "elevator", limit: 100 });
      changed();
    });
    fields.append(el("label", { class: "c" }, elev, el("span", { text: t("su_floor_elev") })));
  }
  item.append(fields);
  item.append(effect(() => {
    let e = ground ? t("ef_ground_hidden") : t("ef_ground_ok");
    if (high && high.limit != null) {
      const o = (high.overrides || []).find((x) => x.when_signal === "elevator");
      e += ` ${t("ef_high", { limit: high.limit })}${o && o.limit >= 50 ? t("ef_high_elev") : ""}`;
    }
    return e;
  }));
  if (high) item.append(importance(high, ground ? [ground] : []));
  else if (ground) item.append(importance(ground));
  return item;
}

// ---- where to look ---------------------------------------------------------------------------

const searchName = (s) => (I.lang === "he" ? s.label_he || s.label : s.label);

// v1.33: the searches grouped by city, each a card that says what's in it: the whole city or its
// neighborhoods by name, with "Edit on the map" and "Remove"
const cityOf = (s) => { const m = /[?&]city=(\d+)/.exec(s.path || ""); return m ? Number(m[1]) : null; };
const hoodOf = (s) => { const m = /[?&]neighborhood=(\d+)/.exec(s.path || ""); return m ? Number(m[1]) : null; };

function places() {
  const out = [];
  const by = new Map();
  for (const s of model.searches || []) {
    const code = cityOf(s);
    if (code == null) { out.push({ code: null, searches: [s] }); continue; }
    if (!by.has(code)) { const g = { code, searches: [] }; by.set(code, g); out.push(g); }
    by.get(code).searches.push(s);
  }
  for (const g of out) {
    g.whole = g.searches.some((s) => hoodOf(s) == null && !(s.hoods || []).length);
    g.ids = g.whole ? [] : Array.from(new Set(g.searches.flatMap((s) => (hoodOf(s) != null ? [hoodOf(s)] : s.hoods || []))));
    g.names = g.whole ? [] : g.searches.flatMap((s) => (hoodOf(s) != null ? [searchName(s)] : (I.lang === "he" ? s.hood_names : null) || []));
  }
  return out;
}

function cityHe(code) {
  for (const e of cityPick.values()) if (e.code === code && !e.preset) return e.he;
  return null;
}

function cityName(code, fallback) {
  for (const e of cityPick.values()) if (e.code === code && !e.preset) return I.lang === "he" ? e.he : e.en;
  return fallback;
}

function renderSearches() {
  const box = $("searches");
  box.replaceChildren();
  const list = places();
  if (!list.length) box.append(el("span", { class: "muted", text: t("su_none") }));
  for (const g of list) {
    const card = el("div", { class: "place" });
    const title = g.code == null ? searchName(g.searches[0]) : cityName(g.code, searchName(g.searches[0]).replace(/\s*\(\d+\)$/, ""));
    const what = g.code == null ? t("su_link") : g.whole ? t("su_whole_city")
      : g.names.length ? `${t("su_n_hoods", { n: g.ids.length })}: ${g.names.slice(0, 8).join(", ")}${g.names.length > 8 ? ` ${t("su_and_more", { n: g.names.length - 8 })}` : ""}`
        : t("su_n_hoods", { n: g.ids.length });
    const head = el("div", { class: "place-h" }, el("b", {}, iso(title)));
    if (g.code != null) head.append(el("button", { class: "btn small", text: `🗺 ${t("su_edit_map")}`, onclick: () => editCity(g) }));
    head.append(el("button", { class: "btn small", text: t("remove"), onclick: async () => {
      model.searches = (model.searches || []).filter((s) => !g.searches.includes(s));
      const he = g.code != null ? cityHe(g.code) : null;
      if (he) drops.push({ city: he, hoods: null });
      render();
      changed(); // v1.37: saved by itself, and its listings go
    } }));
    const acts = el("div", { class: "place-h" });
    for (const b of Array.from(head.querySelectorAll("button"))) acts.append(b);
    card.append(head, el("div", { class: "muted small", text: what }), acts);
    box.append(card);
  }
}

/** Open a saved city on the map, its neighborhoods picked; saving replaces what was there. */
async function editCity(g) {
  let entry = null;
  for (const e of cityPick.values()) if (e.code === g.code && !e.preset) entry = e;
  entry = entry || { code: g.code, en: searchName(g.searches[0]), he: g.searches[0].label_he || searchName(g.searches[0]) };
  await openHoods(entry, { picked: g.ids });
  $("hoodbox").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadCities() {
  cities = await RentalSetup.loadCities();
  fillCities();
  if (model) renderSearches(); // v1.34: the cards' city names, now that the list is here (if the file is in)
}

// Tel Aviv and Jaffa are one city on Yad2 but two places to live: offered apart too
function fillCities() {
  const dl = $("cities");
  dl.replaceChildren();
  cityPick.clear();
  for (const [text, entry] of RentalSetup.cityEntries(cities, I.lang)) {
    cityPick.set(text, entry);
    dl.append(el("option", { value: text }));
  }
}

async function pickCity() {
  const v = $("city").value.trim();
  const msg = $("citymsg");
  const entry = RentalSetup.findCity(cityPick, v);
  if (!entry) {
    if (v) {
      msg.className = "chosen no";
      msg.textContent = t("su_pick_city");
    }
    return;
  }
  msg.textContent = "";
  $("city").value = "";
  // v1.37: picking a city adds it (the whole city, or the preset's part) and opens its map; every
  // click there applies at once and the page saves itself: no "Add", no second "Save"
  const g = places().find((x) => x.code === entry.code);
  await openHoods(entry, g ? { picked: g.ids } : { fresh: true });
}

async function openHoods(entry, how) {
  const box = $("hoodbox");
  box.hidden = false;
  box.replaceChildren(el("b", {}, iso(I.lang === "he" ? entry.he : entry.en)), el("div", { class: "muted", text: t("su_hoods_loading") }));
  let hoods = [];
  try {
    hoods = await loadHoods(entry.code);
  } catch (e) {
    hoods = [];
  }
  hoodPicker(entry, hoods, how || {});
}

function hoodPicker(entry, hoods, how) {
  const box = $("hoodbox");
  // v1.33: nothing picked when the map opens (a saved city opens with its own); a preset
  // ("Tel Aviv without Jaffa") is the "whole" choice, and a button below
  const picked = new Set(how.picked || []);
  const presetIds = entry.preset === "jaffa" ? hoods.filter((h) => JAFFA.has(h.id)) : entry.preset === "no_jaffa" ? hoods.filter((h) => !JAFFA.has(h.id)) : [];
  let mode = picked.size ? "pick" : "all";
  const name = (h) => (I.lang === "he" ? h.he : h.en);
  hoods.sort((a, b) => name(a).localeCompare(name(b), I.lang === "he" ? "he" : "en"));
  const all = el("input", { type: "radio", name: "hm" });
  const some = el("input", { type: "radio", name: "hm" });
  const filter = el("input", { type: "search", placeholder: t("su_hood_filter") });
  const list = el("div", { class: "hoodlist" });
  // v1.32: the map: click the neighborhoods you'd live in
  const mapBox = el("div", { class: "hoodmap" });
  const count = el("span", { class: "muted" });
  let map = null;
  // v1.37: every change is applied to the searches straight away (and so saved)
  let applyTimer = null;
  const apply = () => {
    clearTimeout(applyTimer);
    applyTimer = setTimeout(() => {
      const chosen = mode === "all" ? presetIds : hoods.filter((h) => picked.has(h.id));
      setCity(entry, chosen, hoods);
    }, 250);
  };
  const sync = () => {
    const names = hoods.filter((h) => picked.has(h.id)).map(name);
    count.textContent = mode !== "pick" ? t("su_whole_now") : names.length ? `${t("su_map_picked", { n: names.length })}: ${names.join(", ")}` : t("su_map_none");
    if (map) map.redraw();
  };
  const draw = () => {
    all.checked = mode === "all";
    some.checked = mode === "pick";
    list.hidden = mode !== "pick";
    tools.hidden = mode !== "pick";
    list.replaceChildren();
    const q = filter.value.trim().toLowerCase();
    for (const h of hoods.filter((h) => !q || h.he.includes(q) || h.en.toLowerCase().includes(q))) {
      const cb = el("input", { type: "checkbox" });
      cb.checked = picked.has(h.id);
      cb.addEventListener("change", () => {
        if (cb.checked) picked.add(h.id);
        else picked.delete(h.id);
        sync();
        apply();
      });
      list.append(el("label", {}, cb, iso(name(h))));
    }
    sync();
  };
  const changeAll = (f) => () => { f(); draw(); apply(); };
  all.addEventListener("change", changeAll(() => { mode = "all"; }));
  some.addEventListener("change", changeAll(() => { mode = "pick"; }));
  filter.addEventListener("input", draw);
  const tools = el("div", { class: "row", style: "margin-top:8px" }, filter,
    el("button", { class: "btn small", text: t("su_select_all"), onclick: changeAll(() => hoods.forEach((h) => picked.add(h.id))) }),
    el("button", { class: "btn small", text: t("su_select_none"), onclick: changeAll(() => picked.clear()) }));
  if (entry.code === TLV) {
    tools.append(el("button", { class: "btn small", text: t("su_tlv_no_jaffa"), onclick: changeAll(() => {
      picked.clear();
      hoods.filter((h) => !JAFFA.has(h.id)).forEach((h) => picked.add(h.id));
    }) }), el("button", { class: "btn small", text: t("su_jaffa"), onclick: changeAll(() => {
      picked.clear();
      hoods.filter((h) => JAFFA.has(h.id)).forEach((h) => picked.add(h.id));
    }) }));
  }
  const done = el("button", { class: "btn primary", text: t("done"), onclick: () => { box.hidden = true; } });
  const onMap = hoods.some((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng)) && root.RentalHoodMap;
  box.replaceChildren(el("b", {}, iso(I.lang === "he" ? entry.he : entry.en)),
    el("div", { class: "row", style: "margin-top:6px" }, el("label", { class: "c" }, all, el("span", { text: entry.preset ? t("su_all_of", { x: t(entry.preset === "jaffa" ? "su_jaffa" : "su_tlv_no_jaffa") }) : t("su_whole_city") })),
      hoods.length ? el("label", { class: "c" }, some, el("span", { text: t(onMap ? "su_pick_hoods_map" : "su_pick_hoods") })) : el("span", { class: "muted", text: t("su_hoods_failed") })),
    ...(onMap ? [el("div", { class: "muted small", text: t("su_map_note") }), mapBox] : []),
    el("div", { class: "row", style: "margin-top:8px" }, count), tools, list, el("div", { class: "row", style: "margin-top:10px" }, done));
  if (onMap) {
    map = RentalHoodMap.create(document, mapBox, { hoods, cityBox: hoods.cityBox, picked, name,
      onChange: () => {
        if (mode !== "pick") mode = "pick";
        draw();
        apply();
      } });
  }
  draw();
  if (how.fresh) setCity(entry, presetIds, hoods); // a new city: searched (whole) from the moment it's picked
}

const PER_HOOD = 12; // up to this many neighborhoods: a Yad2 search each; more: the city once, kept to them
const basePaths = new Map(); // city code -> where Yad2 keeps its rentals (asked once a visit)

/**
 * A city's searches, from what's picked: the whole city ([]), or its neighborhoods. Replaces what
 * the city had; the neighborhoods left out drop out of the last search's listings when it's saved.
 */
async function setCity(entry, hoods, all) {
  const msg = $("citymsg");
  const label = I.lang === "he" ? entry.he : entry.en;
  if (!basePaths.has(entry.code)) basePaths.set(entry.code, await yad2Where(entry.code));
  const where = basePaths.get(entry.code);
  const base = where.path;
  const out = [];
  if (!hoods.length) out.push({ source: "yad2", label: entry.en, label_he: entry.he, path: base });
  else if (hoods.length <= PER_HOOD) {
    // one neighborhood per search: Yad2 filters it, so only its pages are read (v1.33: up to 12)
    for (const h of hoods) out.push({ source: "yad2", label: h.en, label_he: h.he, path: `${base}&neighborhood=${h.id}` });
  } else {
    // many: the city is read once and kept to them
    const preset = hoods.every((h) => JAFFA.has(h.id)) && entry.code === TLV ? ["Jaffa", "יפו"]
      : entry.code === TLV && hoods.every((h) => !JAFFA.has(h.id)) ? ["Tel Aviv", "תל אביב"] : null;
    // v1.33: with their names and every center of the city, so the rows can be kept to them without Yad2's ids
    const centers = RentalSetup.centersOf(all);
    out.push({ source: "yad2", label: preset ? preset[0] : `${entry.en} (${hoods.length})`, label_he: preset ? preset[1] : `${entry.he} (${hoods.length})`,
      path: base, hoods: hoods.map((h) => h.id).sort((a, b) => a - b), hood_names: hoods.map((h) => h.he || h.en).filter(Boolean), centers });
  }
  if (where.elsewhere) for (const s of out) s.elsewhere = where.elsewhere; // v1.67: Yad2 serves this place on another site
  const chosen = new Set(hoods.map((h) => h.id));
  const left = hoods.length ? (all || []).filter((h) => !chosen.has(h.id)).map((h) => h.he).filter(Boolean) : [];
  if (left.length) drops.push({ city: entry.he, hoods: left });
  model.searches = (model.searches || []).filter((s) => cityOf(s) !== entry.code).concat(out);
  msg.className = "chosen ok";
  msg.textContent = hoods.length ? `${label} · ${t("su_n_hoods", { n: hoods.length })}` : t("su_added", { x: label });
  renderSearches();
  changed();
}

function addLink() {
  const msg = $("citymsg");
  let u;
  try {
    u = new URL($("link").value.trim());
  } catch (e) {
    msg.className = "chosen no";
    msg.textContent = t("su_not_link");
    return;
  }
  u.searchParams.delete("page");
  const path = u.pathname + u.search;
  if (u.hostname !== "www.yad2.co.il" || !SEARCH_PATH.test(path)) {
    msg.className = "chosen no";
    msg.textContent = t("su_link_bad");
    return;
  }
  const label = $("linklabel").value.trim() || t("su_my_search");
  model.searches = model.searches || [];
  model.searches.push({ source: "yad2", label, label_he: label, path });
  $("link").value = "";
  $("linklabel").value = "";
  msg.className = "chosen ok";
  msg.textContent = t("su_added", { x: label });
  render();
  changed();
}

// ---- places ----------------------------------------------------------------------------------

function newSignal() {
  const used = new Set([...(model.commutes || []).map((c) => c.signal), ...model.preferences.map((p) => p.name)]);
  for (let i = 1; ; i++) if (!used.has(`commute_${i}_minutes`)) return `commute_${i}_minutes`;
}

const MODE_EN = { ebike: "E-bike", bike: "Bike", walk: "Walk", car: "Car" };

function commuteItem(c) {
  const p = model.preferences.find((x) => x.field === `signal:${c.signal}`);
  const name0 = c.label.split(" (")[0];
  const addr0 = (c.label.match(/\((.*)\)$/) || [])[1] || "";
  const item = el("div", { class: "item" });
  const name = el("input", { value: name0, placeholder: t("su_name_ph") });
  const update = () => {
    const nm = name.value.trim() || t("su_place");
    c.label = (c._address != null ? c._address : addr0) ? `${nm} (${c._address != null ? c._address : addr0})` : nm;
    if (p) p.label = `${MODE_EN[c.mode] || c.mode} time to ${nm} (min)`;
    changed();
  };
  name.addEventListener("input", update);
  item.append(el("div", { class: "item-h" }, el("b", { text: t("su_place") }), el("button", { class: "btn small danger", text: t("remove"), onclick: () => {
    model.commutes = model.commutes.filter((x) => x !== c);
    model.preferences = model.preferences.filter((x) => x !== p);
    render();
    changed();
  } })));
  const addr = el("input", { class: "wide", value: addr0, placeholder: t("su_address_ph") });
  const chosen = el("div", { class: "chosen ok" });
  const showChosen = (label) => {
    chosen.className = "chosen ok";
    chosen.replaceChildren(document.createTextNode("✓ "), iso(label), document.createTextNode(` (${c.lat.toFixed(4)}, ${c.lng.toFixed(4)})`));
  };
  if (c.lat != null) showChosen(addr0 || c.label);
  else {
    chosen.className = "chosen no";
    chosen.textContent = t("su_find_first");
  }
  const picks = el("div", { class: "picks" });
  const find = el("button", { class: "btn", text: t("su_find"), onclick: async () => {
    picks.replaceChildren(el("span", { class: "muted", text: t("su_looking") }));
    const r = await helper("/places", { q: addr.value });
    picks.replaceChildren();
    if (!r || !r.ok) return picks.append(el("span", { class: "muted", text: (r && r.body && r.body.error) || t("su_lookup_failed") }));
    if (!r.body.places.length) return picks.append(el("span", { class: "muted", text: t("su_nothing") }));
    for (const pl of r.body.places) {
      picks.append(el("button", { class: "pick", onclick: () => {
        c.lat = pl.lat;
        c.lng = pl.lng;
        c._address = pl.label;
        addr.value = pl.label;
        picks.replaceChildren();
        showChosen(pl.label);
        update();
      } }, iso(pl.label)));
    }
    picks.append(el("span", { class: "muted", text: t("su_from", { src: r.body.source }) }));
  } });
  const mode = el("select", {});
  for (const k of MODES) mode.append(el("option", { value: k, text: t(`mode_${k}`), selected: c.mode === k }));
  const speed = el("input", { type: "number", step: "any", value: c.speed_kmh || "" });
  const when = el("select", {}, el("option", { value: "peak", text: t("su_rush"), selected: c.at !== "typical" }),
    el("option", { value: "typical", text: t("su_offpeak"), selected: c.at === "typical" }));
  const speedF = el("label", { class: "f" }, el("span", { text: t("su_speed") }), speed);
  const whenF = el("label", { class: "f" }, el("span", { text: t("su_time") }), when);
  const showMode = () => {
    speedF.hidden = c.mode === "car";
    whenF.hidden = c.mode !== "car";
    speed.placeholder = SPEED[c.mode] ? t("su_usual", { n: SPEED[c.mode] }) : "";
  };
  mode.addEventListener("change", () => {
    c.mode = mode.value;
    if (c.mode === "car") delete c.speed_kmh;
    else delete c.at;
    showMode();
    update();
  });
  speed.addEventListener("input", () => {
    if (speed.value === "") delete c.speed_kmh;
    else c.speed_kmh = Number(speed.value);
    changed();
  });
  when.addEventListener("change", () => {
    c.at = when.value;
    changed();
  });
  showMode();
  item.append(el("div", { class: "fields" }, el("label", { class: "f" }, el("span", { text: t("su_name") }), name),
    el("label", { class: "f", style: "flex:1" }, el("span", { text: t("su_address") }), el("div", { class: "row" }, addr, find))));
  item.append(chosen, picks);
  const f2 = el("div", { class: "fields", style: "margin-top:10px" }, el("label", { class: "f" }, el("span", { text: t("su_by") }), mode), speedF, whenF);
  if (p) {
    // full marks up to `ideal`, hidden past `limit`: a shorter trip counts more
    const toRanged = () => {
      if (p.ideal != null && p.limit != null && p.ideal < p.limit) p.kind = "ranged";
      else {
        delete p.ideal;
        p.kind = "at_most";
      }
    };
    f2.append(num(p, "ideal", t("su_full_marks"), { then: toRanged }), num(p, "limit", t("su_at_most"), { then: toRanged }));
  }
  item.append(f2);
  if (p) item.append(effect(() => effectOf(p)), importance(p));
  return item;
}

function addCommute() {
  const signal = newSignal();
  const c = { signal, label: t("su_place"), lat: null, lng: null, mode: "ebike" };
  model.commutes = model.commutes || [];
  model.commutes.push(c);
  model.preferences.push({ name: signal, label: `E-bike time to ${c.label} (min)`, field: `signal:${signal}`, kind: "ranged", relevance: MUST, ideal: 10, limit: 20 });
  render();
  changed();
}

// ---- page ------------------------------------------------------------------------------------

function render() {
  effects = [];
  renderSearches();
  const cs = $("commutes");
  cs.replaceChildren();
  for (const c of model.commutes || []) cs.append(commuteItem(c));
  if (!(model.commutes || []).length) cs.append(el("p", { class: "muted", text: t("su_no_places") }));
  const basics = $("basics");
  const feats = $("features");
  basics.replaceChildren();
  feats.replaceChildren();
  const ground = model.preferences.find((p) => topicOf(p).topic === "floor_ground");
  const high = model.preferences.find((p) => topicOf(p).topic === "floor_high");
  let floorDone = false;
  const budget = model.preferences.find((p) => topicOf(p).topic === "rent");
  for (const p of model.preferences.slice()) {
    const tp = topicOf(p).topic;
    if (tp === "commute") continue;
    if (tp === "rent") {
      basics.append(rentItem(p));
      continue;
    }
    if (tp === "rent_min" && budget) continue; // the budget's low end, shown with it
    if (tp === "floor_ground" || tp === "floor_high") {
      if (!floorDone) basics.append(floorItem(ground, high));
      floorDone = true;
      continue;
    }
    (BASICS.has(tp) ? basics : feats).append(prefItem(p));
  }
  const add = $("addpref");
  add.replaceChildren(el("option", { value: "", text: t("su_add_pref") }));
  const have = new Set(model.preferences.map((p) => p.name));
  for (const c of info.catalog) {
    if (have.has(c.name) || (c.name === "not_ground_floor" && (ground || high))) continue;
    const tp = topicOf(c);
    add.append(el("option", { value: c.name, text: tp.topic === "floor_high" ? t("su_floor_max") : I.topicTitle(tp) }));
  }
  refreshEffects();
}

/** The file as it's saved: no setup-page notes. */
function clean(m) {
  const out = clone(m);
  for (const c of out.commutes || []) delete c._address;
  return out;
}

// v1.37: the page saves itself, a moment after each change; there is no Save button to remember
let saveTimer = null;
let saving = false;
let saveAgain = false;
let opened = null; // the file as the page opened it, for "Undo my changes"

function changed() {
  const now = JSON.stringify(clean(model), null, 2) + "\n";
  const dirty = now !== saved;
  const msg = $("msg");
  refreshEffects();
  $("revert").hidden = !opened || now === opened;
  if (!dirty) {
    if (!saving && msg.className !== "err") {
      msg.className = "muted";
      msg.textContent = t("su_all_saved");
    }
    return;
  }
  msg.className = "muted";
  msg.textContent = t("su_saving");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(autosave, 700);
}

async function autosave() {
  if (saving) {
    saveAgain = true;
    return;
  }
  saving = true;
  try {
    await save();
  } finally {
    saving = false;
    if (saveAgain) {
      saveAgain = false;
      autosave();
    }
  }
}

/** The drops that still hold: a neighborhood picked again since, or a city searched whole again, isn't dropped. */
function dropsNow(list) {
  const norm = (x) => String(x || "").replace(/[^\u05d0-\u05eaA-Za-z0-9]/g, "");
  return list.map((d) => {
    const mine = (model.searches || []).filter((s) => norm(cityHe(cityOf(s))) === norm(d.city));
    if (!mine.length) return d; // the city isn't searched at all
    if (mine.some((s) => hoodOf(s) == null && !(s.hoods || []).length)) return null; // the whole city is
    if (d.hoods === null) return null;
    const names = mine.flatMap((s) => (hoodOf(s) != null ? [s.label_he] : s.hood_names || [])).filter(Boolean);
    const hoods = d.hoods.filter((h) => !names.some((n) => RentalSites.sameHood(n, h)));
    return hoods.length ? { city: d.city, hoods } : null;
  }).filter(Boolean);
}

// v1.36: places taken out since the last save: [{city, hoods: null | [names]}] (RentalSetup.pruneTo)
const drops = [];

async function save() {
  const msg = $("msg");
  const missing = (model.commutes || []).filter((c) => c.lat == null || c.lng == null);
  if (missing.length) {
    msg.className = "err";
    msg.textContent = t("su_find_addr_first", { x: missing.map((c) => c.label.split(" (")[0]).join(", ") });
    return;
  }
  msg.className = "";
  msg.textContent = t("su_saving");
  const prefs = clean(model);
  const r = await helper("/saveprefs", { prefs });
  if (!r || !r.ok) {
    msg.className = "err";
    msg.textContent = (r && r.body && r.body.error) || t("su_no_helper");
    return;
  }
  if (!r.body.saved) {
    msg.className = "err";
    msg.textContent = t("su_not_saved", { e: r.body.errors.join("; ") });
    return;
  }
  saved = JSON.stringify(prefs, null, 2) + "\n";
  msg.className = "muted";
  msg.textContent = t("su_all_saved");
  // v1.36: the places taken out go from the last search's listings too (and their marks)
  if (drops.length) {
    const d = dropsNow(drops.splice(0));
    const { results, marks = {} } = await chrome.storage.local.get(["results", "marks"]);
    const p = RentalSetup.pruneTo(results, marks, d, RentalSites.sameHood);
    if (p.removed.length) {
      await chrome.storage.local.set({ results: p.results, marks: p.marks });
      msg.textContent += ` ${t("su_pruned", { n: p.removed.length })}`;
    }
  }
  return true;
}

const STARTER = RentalSetup.STARTER;

async function load() {
  const r = await helper("/prefs");
  if (!r || !r.ok) {
    const box = $("loaderr");
    box.hidden = false;
    box.textContent = (r && r.body && r.body.error) || t("su_no_helper");
    return;
  }
  info = r.body;
  model = r.body.prefs ? clone(r.body.prefs) : clone(STARTER);
  if (!r.body.prefs) {
    for (const name of ["price", "size", "no_roommates", "mamad"]) {
      const c = clone(info.catalog.find((x) => x.name === name));
      delete c.group;
      model.preferences.push(c);
    }
  }
  model.searches = model.searches || [];
  model.commutes = model.commutes || [];
  saved = r.body.prefs ? JSON.stringify(clean(model), null, 2) + "\n" : "";
  opened = saved || null;
  render();
  changed();
}

// ---- language --------------------------------------------------------------------------------

function words() {
  I.apply(document);
  $("lang").textContent = I.lang === "he" ? "English" : "עברית";
  fillCities();
  if (model) {
    render();
    changed();
  }
}

$("city").addEventListener("change", pickCity);
$("city").addEventListener("keydown", (e) => { if (e.key === "Enter") pickCity(); });
$("addlink").addEventListener("click", addLink);
$("addcommute").addEventListener("click", addCommute);
$("addprefbtn").addEventListener("click", () => {
  const c = info.catalog.find((x) => x.name === $("addpref").value);
  if (!c) return;
  const p = clone(c);
  delete p.group;
  model.preferences.push(p);
  if (p.name === "floor_without_elevator" && !model.preferences.some((x) => x.name === "not_ground_floor")) {
    const g = clone(info.catalog.find((x) => x.name === "not_ground_floor"));
    delete g.group;
    model.preferences.push(g);
  }
  render();
  changed();
});
$("revert").addEventListener("click", () => {
  if (opened) model = JSON.parse(opened);
  render();
  changed();
});
$("results").addEventListener("click", () => chrome.tabs.create({ url: chrome.runtime.getURL("results.html") }));
$("tour").addEventListener("click", () => { location.href = chrome.runtime.getURL("wizard.html"); });
$("lang").addEventListener("click", async () => {
  const { ui = {} } = await chrome.storage.local.get("ui");
  ui.lang = I.lang === "he" ? "en" : "he";
  await chrome.storage.local.set({ ui });
});
chrome.storage.onChanged.addListener((c) => {
  if (c.ui && c.ui.newValue && c.ui.newValue.lang && c.ui.newValue.lang !== I.lang) {
    I.setLang(c.ui.newValue.lang);
    words();
  }
});
window.addEventListener("beforeunload", (e) => {
  if (model && saved && JSON.stringify(clean(model), null, 2) + "\n" !== saved) e.preventDefault();
});

// other sites: on unless turned off, saved as soon as it's ticked (they aren't part of the preferences file)
async function sources() {
  const { sources: on = {} } = await chrome.storage.local.get("sources");
  for (const site of ["komo", "madlan"]) {
    const box = $(`src-${site}`);
    box.checked = on[site] !== false;
    box.onchange = async () => {
      const { sources: now = {} } = await chrome.storage.local.get("sources");
      await chrome.storage.local.set({ sources: Object.assign({}, now, { [site]: box.checked }) });
    };
  }
}

// v1.40: on unless turned off; a setting of this browser, not of the preferences file
async function photoSwitch() {
  const { ui = {} } = await chrome.storage.local.get("ui");
  const box = $("nophotos");
  box.checked = ui.hideNoPhotos !== false;
  box.onchange = async () => {
    const { ui: now = {} } = await chrome.storage.local.get("ui");
    await chrome.storage.local.set({ ui: Object.assign({}, now, { hideNoPhotos: box.checked }) });
  };
}

(async () => {
  await I.load(chrome.storage.local);
  words();
  await sources();
  await photoSwitch();
  await loadCities();
  await load();
  const { ui = {} } = await chrome.storage.local.get("ui");
  if (!ui.onboarded) location.replace(chrome.runtime.getURL("wizard.html")); // a first visit starts with the quick setup
})();
