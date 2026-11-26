/*
 * Rental Matcher: what the extension keeps, all in chrome.storage.local on
 * this computer (v1.25). Nothing here leaves it.
 *
 *   marks     {id: {fav, status, viewingAt, at, view}}  the user's calls on
 *             listings; `view` is the card as it was, so a marked listing
 *             stays on the results page after it leaves the search
 *   results   {at, ms, state}          the last pull, for the results page
 *   pulls     [{at, ms, kind, ...}]    the last 30 pulls, for time estimates
 *   log       [{at, kind, ...}]        Yad2's pushbacks and checks, last 100
 */
(function (root) {
  "use strict";

  const MAX_PULLS = 30;
  const MAX_LOG = 100;
  const DAY = 24 * 3600e3;

  function make(storage) {
    const get = async (k, dflt) => {
      const o = await storage.get(k);
      return o[k] === undefined ? dflt : o[k];
    };
    const set = (k, v) => storage.set({ [k]: v });

    async function setMark(x, patch, now) {
      const marks = await get("marks", {});
      const m = Object.assign({}, marks[x.id] || {}, patch, { at: now || Date.now() });
      if (m.status !== "viewing") m.viewingAt = null;
      m.view = slim(x);
      if (!m.fav && !m.status) delete marks[x.id];
      else marks[x.id] = m;
      await set("marks", marks);
      return marks;
    }

    async function logEvent(e) {
      const log = await get("log", []);
      log.push(Object.assign({ at: Date.now() }, e));
      await set("log", log.slice(-MAX_LOG));
    }

    async function addPull(p) {
      const pulls = await get("pulls", []);
      pulls.push(p);
      await set("pulls", pulls.slice(-MAX_PULLS));
    }

    /** Remember when each listing was first seen; returns the ones new in this
     * search (none on the very first search, when everything is new). */
    async function markSeen(ids, now) {
      const seen = await get("seen", {});
      const first = !Object.keys(seen).length;
      const fresh = [];
      for (const id of ids) {
        if (!seen[id]) {
          seen[id] = now || Date.now();
          if (!first) fresh.push(id);
        }
      }
      await set("seen", seen);
      return fresh;
    }

    /**
     * v1.30: each listing's rent the last time a search saw it; a lower rent
     * now is a price drop, shown for two weeks. {id: {was, now, at}}.
     */
    async function notePrices(list, now) {
      now = now || Date.now();
      const prices = await get("prices", {});
      const drops = await get("drops", {});
      for (const x of list || []) {
        if (!x || !x.id || typeof x.price !== "number" || !(x.price > 0)) continue;
        const before = prices[x.id];
        if (before && x.price < before.p) drops[x.id] = { was: drops[x.id] ? Math.max(drops[x.id].was, before.p) : before.p, now: x.price, at: now };
        else if (drops[x.id] && x.price > drops[x.id].now) delete drops[x.id]; // it went back up
        prices[x.id] = { p: x.price, at: now };
      }
      for (const [id, v] of Object.entries(prices)) if (now - v.at > 60 * DAY) delete prices[id];
      for (const [id, v] of Object.entries(drops)) if (now - v.at > 14 * DAY) delete drops[id];
      await set("prices", prices);
      await set("drops", drops);
      return drops;
    }

    /**
     * v1.35: the listings a search read, kept for labeling (so the reading rules can be measured on
     * listings they've never seen): the text and the site's own facts, never a name, a phone number
     * or anything about the poster. The newest LABEL_MAX, for LABEL_DAYS days; downloaded from the
     * results page. scrub: blanks phone numbers in text (sites.js).
     */
    async function keepForLabels(extracts, scrub, now) {
      now = now || Date.now();
      const set0 = await get("labelset", {});
      for (const x of Object.values(extracts || {})) {
        if (!x || !x.id || x.error || typeof x.description !== "string" || !x.description.trim()) continue;
        const out = {};
        for (const [k, v] of Object.entries(x)) if (!CONTACT.test(k)) out[k] = v;
        out.description = scrub ? scrub(x.description) : x.description;
        if (typeof x.furnitureInfo === "string") out.furnitureInfo = scrub ? scrub(x.furnitureInfo) : x.furnitureInfo;
        delete out.coords;
        delete out.lat;
        delete out.lng;
        delete out.photos;
        set0[x.id] = Object.assign(out, { keptAt: now });
      }
      const ids = Object.keys(set0).filter((id) => now - set0[id].keptAt <= LABEL_DAYS * DAY).sort((a, b) => set0[b].keptAt - set0[a].keptAt);
      const keep = new Set(ids.slice(0, LABEL_MAX));
      for (const id of Object.keys(set0)) if (!keep.has(id)) delete set0[id];
      await set("labelset", set0);
      return Object.keys(set0).length;
    }

    /**
     * v1.40: v1.37's "Neither" put both listings in "Not for me", which nobody asked it to do.
     * Those marks are taken back (a listing you rejected yourself, or marked otherwise since, stays).
     */
    async function undoNeither() {
      const marks = await get("marks", {});
      let n = 0;
      for (const [id, m] of Object.entries(marks)) {
        if (m && m.status === "rejected" && m.why === "neither") {
          n++;
          delete m.status;
          delete m.why;
          if (!m.fav) delete marks[id];
        }
      }
      if (n) await set("marks", marks);
      return n;
    }

    return { get, set, setMark, logEvent, addPull, markSeen, notePrices, keepForLabels, undoNeither };
  }

  const LABEL_MAX = 400;
  const LABEL_DAYS = 30;
  const CONTACT = /phone|poc|customer|contact|poster|agent|name|email|whatsapp/i;

  /** A card's data without the bulky parts. */
  function slim(x) {
    const keep = ["id", "url", "price", "rooms", "floor", "size_m2", "street", "neighborhood", "city", "listed_by", "excluded",
      "match_expected", "match_likely_low", "match_likely_high", "match_low", "match_high", "commutes", "features", "risk_parts",
      "unknowns", "flags", "checks", "reasons", "source", "fit", "feature_keys", "notes", "asks", "risks", "trips", "available_in", "approx", "also", "costs", "deal", "drop", "photos", "sat", "fail_risk", "photos_state"];
    const out = {};
    for (const k of keep) if (x[k] !== undefined) out[k] = x[k];
    return out;
  }

  /**
   * How long the next pull should take, from the pulls before it. "repeat":
   * within a day of the last full pull, so the listings read then come from
   * the cache; "first": nothing read in the last day.
   */
  function estimate(pulls, searches, now) {
    const done = (pulls || []).filter((p) => p.complete && p.ms > 0);
    const last = done.length ? done[done.length - 1] : null;
    const kind = last && now - last.at < DAY ? "repeat" : "first";
    const avg = (k) => {
      const xs = done.filter((p) => p.kind === k).slice(-5).map((p) => p.ms / Math.max(1, p.searches || 1));
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
    };
    // before any pull: the first full test pull (3 cities, 954 listings, 172 opened) took 10 min
    const per = { first: avg("first") || 200e3, repeat: avg("repeat") || 45e3 };
    const n = Math.max(1, searches || 1);
    return { kind, ms: Math.round(per[kind] * n), first: Math.round(per.first * n), repeat: Math.round(per.repeat * n),
      measured: { first: avg("first") != null, repeat: avg("repeat") != null } };
  }

  function fmtDuration(ms) {
    const s = Math.round((ms || 0) / 1000);
    if (s < 60) return `${s} s`;
    const m = Math.round(s / 60);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  }

  const api = { make, slim, estimate, fmtDuration, DAY };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalStore = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
