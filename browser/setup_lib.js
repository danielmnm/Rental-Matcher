/*
 * Rental Matcher: what the setup page and the quick setup share (v1.30):
 * building elements, the city list, and where Yad2 keeps a city's rentals.
 */
(function (root) {
  "use strict";

  const TLV = 5000;
  // Yad2's neighborhoods of Tel Aviv-Yafo that are Jaffa (from its own list, Oct 22, 2026)
  const JAFFA = new Set([847, 321, 320, 496, 492, 213, 493, 494, 495]);
  const SEARCH_PATH = /^\/realestate\/rent(\/[a-z0-9-]+)?\?[A-Za-z0-9=&_.,-]+$/;
  const MUST = 10;
  const MUST_POINTS = 5; // rental_matcher/scoring.py MUST_HAVE_POINTS

  const el = (tag, attrs, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v != null && v !== false) e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids) if (c != null) e.append(c);
    return e;
  };
  const iso = (txt) => el("bdi", { dir: "auto", text: txt });
  const helper = (path, body) => chrome.runtime.sendMessage({ type: "helper", path, body });

  /** Israel's cities (CBS list, browser/data/cities.json): [[code, hebrew, english]]. */
  async function loadCities() {
    try {
      const d = await fetch(chrome.runtime.getURL("data/cities.json")).then((r) => r.json());
      return d.cities;
    } catch (e) {
      return [];
    }
  }

  /** The cities as the text a person types, in the page's language, Tel Aviv and Jaffa offered apart. */
  function cityEntries(cities, lang) {
    const out = new Map();
    out.set(lang === "he" ? "תל אביב (בלי יפו) · Tel Aviv" : "Tel Aviv (without Jaffa) · תל אביב", { code: TLV, he: "תל אביב", en: "Tel Aviv", preset: "no_jaffa" });
    out.set(lang === "he" ? "יפו · Jaffa" : "Jaffa · יפו", { code: TLV, he: "יפו", en: "Jaffa", preset: "jaffa" });
    for (const [code, h, en] of cities) out.set(lang === "he" ? `${h}${en ? ` · ${en}` : ""}` : `${en ? `${en} · ` : ""}${h}`, { code, he: h, en: en || h });
    return out;
  }

  function findCity(entries, typed) {
    const v = String(typed || "").trim();
    return entries.get(v) || Array.from(entries.values()).find((e) => e.he === v || (e.en && e.en.toLowerCase() === v.toLowerCase())) || null;
  }

  // v1.67: Yad2 sends some places (Ma'ale Adumim, Ariel: Nov 19) to a separate site, which a pull run from a Yad2 tab can't read
  const ELSEWHERE = { "www.yad-il.co.il": "yad-il.co.il", "yad-il.co.il": "yad-il.co.il" };

  /** Where Yad2 serves a city's rentals: {path, elsewhere}. One page load, now, instead of a redirect on every search. */
  async function yad2Where(code) {
    const short = `/realestate/rent?city=${String(code).padStart(4, "0")}`; // v1.63: Yad2's codes have four digits (Ashdod 0070)
    try {
      const r = await fetch(`https://www.yad2.co.il${short}`, { credentials: "omit" });
      const u = new URL(r.url);
      if (r.ok && u.hostname === "www.yad2.co.il" && SEARCH_PATH.test(u.pathname + u.search)) return { path: u.pathname + u.search, elsewhere: null };
      if (ELSEWHERE[u.hostname]) return { path: short, elsewhere: ELSEWHERE[u.hostname] };
    } catch (e) { /* offline or Yad2 pushed back: the short address works too */ }
    return { path: short, elsewhere: null };
  }

  async function yad2Path(code) {
    return (await yad2Where(code)).path;
  }

  async function loadHoods(code) {
    const r = await fetch(`https://gw.yad2.co.il/address-master/hoods?result_type=extended&limit=2000&city_id=${code}`, { credentials: "omit" });
    if (!r.ok) throw new Error(String(r.status));
    const j = await r.json();
    const num = (v) => (v == null || v === "" ? NaN : Number(v));
    const rows = ((j.data && j.data.data) || []).filter((h) => h.hood_id != null);
    // v1.32: where each one is (its center and the box it spans), for the map
    const out = rows.map((h) => {
      const box = [num(h.hood_min_x), num(h.hood_min_y), num(h.hood_max_x), num(h.hood_max_y)];
      return { id: Number(h.hood_id), he: h.hood_heb, en: h.hood_eng || h.hood_heb, lat: num(h.hood_lat), lng: num(h.hood_lon),
        box: box.every(Number.isFinite) ? box : null };
    });
    const c = rows[0] || {};
    const cityBox = [num(c.city_min_x), num(c.city_min_y), num(c.city_max_x), num(c.city_max_y)];
    out.cityBox = cityBox.every(Number.isFinite) ? cityBox : null;
    return out;
  }

  /** [id, lat, lng] for every neighborhood with a center, rounded to about a meter. */
  function centersOf(hoods) {
    return (hoods || []).filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng))
      .map((h) => [h.id, Math.round(h.lat * 1e5) / 1e5, Math.round(h.lng * 1e5) / 1e5]);
  }

  /** A whole city as a search; Tel Aviv without Jaffa, or Jaffa, as one search kept to their neighborhoods. */
  async function citySearch(entry) {
    const where = await yad2Where(entry.code);
    const path = where.path;
    const away = where.elsewhere ? { elsewhere: where.elsewhere } : {};
    if (!entry.preset) return { source: "yad2", label: entry.en, label_he: entry.he, path, ...away };
    let hoods = [];
    try {
      hoods = await loadHoods(entry.code);
    } catch (e) {
      hoods = [];
    }
    const mine = hoods.filter((h) => (entry.preset === "jaffa" ? JAFFA.has(h.id) : !JAFFA.has(h.id)));
    const ids = mine.map((h) => h.id).sort((a, b) => a - b);
    // v1.33: their names and every center of the city, to keep the rows to them without Yad2's ids
    return { source: "yad2", label: entry.en, label_he: entry.he, path, ...away, hoods: ids, hood_names: mine.map((h) => h.he || h.en).filter(Boolean), centers: centersOf(hoods) };
  }

  const STARTER = { format_version: 2, owner: "me", note: "", preferences: [], commutes: [], searches: [] };

  // ---- v1.36: what goes when an area goes -----------------------------------------------------

  const cityNorm = (s) => String(s || "").replace(/[^\u05d0-\u05eaA-Za-z0-9]/g, "").toLowerCase();

  /**
   * The last search's listings, and the marks on them, without the places taken out of the
   * setup: drops [{city: its name as listings carry it, hoods: null (the whole city) |
   * [neighborhood names no longer searched]}]. Only a listing that is clearly in a dropped
   * place goes (its city, and for neighborhoods its neighborhood's name); one that can't be
   * placed stays. A viewing you booked stays too. -> {results, marks, removed: [ids]}
   */
  function pruneTo(results, marks, drops, sameHood) {
    const out = (x) => !!x && !!x.city && (drops || []).some((d) => cityNorm(d.city) === cityNorm(x.city)
      && (d.hoods === null || (!!x.neighborhood && d.hoods.some((h) => sameHood(h, x.neighborhood)))));
    const list = (results && results.results) || [];
    const removed = list.filter(out).map((x) => x.id);
    const gone = new Set(removed);
    const m = Object.assign({}, marks || {});
    for (const [id, v] of Object.entries(m)) {
      if (v.status === "viewing") continue;
      if (gone.has(id) || out(v.view)) {
        delete m[id];
        if (!gone.has(id)) removed.push(id);
      }
    }
    return { results: results ? Object.assign({}, results, { results: list.filter((x) => !gone.has(x.id)) }) : results, marks: m, removed };
  }

  const api = { TLV, JAFFA, SEARCH_PATH, MUST, MUST_POINTS, STARTER, el, iso, helper, loadCities, cityEntries, findCity, yad2Where, yad2Path, loadHoods, citySearch, centersOf, pruneTo };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalSetup = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
