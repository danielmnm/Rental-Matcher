/*
 * Rental Matcher: one pull, start to finish (v1.27).
 *
 *   the user's Yad2 search -> every row (yad2_pull.searchRows)
 *   -> Komo's newest listings in the same cities (its first page, the one
 *      anyone can see), and what the user opened on Komo and Madlan himself
 *      (sites.js; Madlan is never fetched: it answers fetches with a bot check)
 *   -> the helper's plan (which listings could still be shown)
 *   -> routes for the pins still in play (OSRM, cached by pin)
 *   -> the plan again, with routes: what to open, best first
 *   -> open them (cached ones cost nothing), scoring again as they arrive
 *   -> for a car commute with a TomTom key: drive times for what's shown
 *
 * Everything that decides (which listings to skip, how they score) is the
 * helper's (rental_matcher/server.py, the same code as the tests). This
 * file only moves data and keeps the user informed: every listing ends up
 * shown, hidden with its reasons, skipped without opening with its
 * reasons, or listed as not opened, with a link. None just disappears.
 */
(function (root) {
  "use strict";

  /** The user's search, with our price cap: the lower of theirs and ours. No page number. */
  function withFilters(path, filters) {
    const [p, q = ""] = String(path).split("?");
    const params = new URLSearchParams(q);
    params.delete("page");
    for (const [k, v] of Object.entries(filters || {})) {
      if (k === "maxPrice") {
        const mine = Number(params.get("maxPrice"));
        params.set("maxPrice", String(params.has("maxPrice") && mine > 0 ? Math.min(mine, Number(v)) : Number(v)));
      } else if (k === "minPrice") {  // v1.30: the higher of the two minimums
        const mine = Number(params.get("minPrice"));
        params.set("minPrice", String(params.has("minPrice") && mine > 0 ? Math.max(mine, Number(v)) : Number(v)));
      } else if (!params.has(k)) {
        params.set(k, v);
      }
    }
    const s = params.toString();
    return s ? `${p}?${s}` : p;
  }

  function isRentSearch(pathname) {
    return /^\/realestate\/rent(\/|$)/.test(pathname || "");
  }

  const SITE = (id) => (/^(komo|madlan|facebook):/.exec(String(id)) || [null, "yad2"])[1];
  const cityKey = (c) => String(c || "").replace(/[-–]/g, " ").replace(/\s+/g, " ").trim();

  /** Where a search looks, from its own Yad2 rows: the city most of them are in, and for a neighborhood search, their names. */
  function areaOf(x, rows) {
    const count = {};
    for (const r of rows) if (r.city) count[cityKey(r.city)] = (count[cityKey(r.city)] || 0) + 1;
    const city = Object.keys(count).sort((a, b) => count[b] - count[a])[0] || null;
    const byHood = (x.hoods && x.hoods.length) || /[?&]neighborhood=/.test(x.path || "");
    return { city, hoods: byHood ? Array.from(new Set(rows.map((r) => r.hood_name).filter(Boolean))) : null };
  }

  /**
   * v1.33: which of a search's rows are in its neighborhoods. By Yad2's
   * neighborhood id when the rows carry one; else by name; else by the
   * nearest neighborhood center (the search keeps every center of the
   * city). If none of that can tell, or the ids leave nothing at all (ids
   * from another list), the rows are all kept and the search says so,
   * rather than showing nothing.
   */
  function hoodFilter(x, rows, S) {
    if (!x.hoods || !x.hoods.length) return { keep: () => true, unsure: false };
    const ids = new Set(x.hoods.map(Number));
    const names = x.hood_names || [];
    const centers = (x.centers || []).filter((c) => Array.isArray(c) && c.length === 3 && c.every(Number.isFinite));
    const same = (a, b) => (S && S.sameHood ? S.sameHood(a, b) : String(a).trim() === String(b).trim());
    const kx = Math.cos((32 * Math.PI) / 180);
    const nearest = (r) => {
      let best = null;
      let d0 = Infinity;
      for (const [id, lat, lng] of centers) {
        const d = ((r.lng - lng) * kx) ** 2 + (r.lat - lat) ** 2;
        if (d < d0) { d0 = d; best = id; }
      }
      return best;
    };
    const byOther = (r) => {
      if (r.hood_name && names.length) return names.some((n) => same(n, r.hood_name));
      if (centers.length && Number.isFinite(r.lat) && Number.isFinite(r.lng)) return ids.has(nearest(r));
      return null; // can't tell
    };
    const byId = rows.some((r) => r.hood != null) && rows.some((r) => r.hood != null && ids.has(Number(r.hood)));
    const keep = (r) => {
      if (byId && r.hood != null) return ids.has(Number(r.hood));
      const v = byOther(r);
      return v == null ? true : v;
    };
    const unsure = !byId && !names.length && !centers.length;
    return { keep: unsure ? () => true : keep, unsure };
  }

  /**
   * v1.33: how many photos the site's own data lists for a listing (0: none in it), or null when we
   * can't tell (a row cached before v1.31). v1.34: Komo's photos are read off its HTML, so finding
   * none there is "not read", not "none"; Yad2's feed and Madlan's data say so outright.
   */
  function countPhotos(row, x) {
    const n = (o) => (o && Array.isArray(o.photos) && (o.photos.length || (o.source || "yad2") !== "komo") ? o.photos.length : null);
    const a = n(x);
    const b = n(row);
    return a == null && b == null ? null : Math.max(a || 0, b || 0);
  }

  /** {city: null (all of it) | [neighborhood names]} -> is this row in it? */
  function inArea(areas, row, S) {
    const k = cityKey(row.city);
    if (!(k in areas)) return false;
    const hoods = areas[k];
    return hoods == null || (!!row.hood_name && hoods.some((h) => S.sameHood(h, row.hood_name)));
  }

  /**
   * Listings from the other sites, for the same places: Komo's first page
   * per city (fetched by the background: public pages only, a polite pace,
   * stopped by the first pushback), plus what the user opened on Komo and
   * Madlan in the last few days (the pool content_sites.js keeps).
   */
  async function otherRows(o, state, areas, yad2Rows, maxPrice) {
    const S = o.S;
    const on = Object.assign({ komo: true, madlan: true, facebook: true }, o.sources || {});
    const now = o.now || (() => Date.now());
    const sleep = o.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
    const out = new Map();
    const take = (r) => {
      // v1.66: a Facebook post the user chose to keep is in, wherever it is (a post rarely names a city the way a site does)
      if (!on[r.source] || (r.source !== "facebook" && !inArea(areas, r, S)) || out.has(r.id)) return;
      out.set(r.id, r);
    };
    const pool = o.pool || {};
    for (const r of Object.values(pool.rows || {})) if (now() - (r.seenAt || 0) <= (o.poolMs || 3 * 864e5)) take(r);
    state.sites = { komo: { cities: 0, rows: 0, stopped: null }, madlan: { rows: 0 }, pool: out.size };
    if (on.komo && o.siteGet) {
      let last = -Infinity;
      for (const city of Object.keys(areas)) {
        if (o.shouldStop && o.shouldStop()) break;
        const wait = last + (o.siteGapMs == null ? 1500 : o.siteGapMs) - now();
        if (wait > 0) await sleep(wait);
        last = now();
        state.searching = city;
        state.searchingHe = city;
        o.emit();
        const k = await S.komoSearch(city, maxPrice, o.siteGet);
        state.requests++;
        state.sites.komo.cities++;
        if (k.wall || k.pushback) {
          state.sites.komo.stopped = k.wall ? "komo_wall" : "komo_pushback";
          break;
        }
        for (const r of k.rows) take(r);
      }
    }
    const centroids = S.hoodCentroids(yad2Rows);
    const rows = Array.from(out.values()).map((r) => (r.source === "komo" ? S.placeApprox(r, centroids) : r));
    state.sites.komo.rows = rows.filter((r) => r.source === "komo").length;
    state.sites.madlan.rows = rows.filter((r) => r.source === "madlan").length;
    state.sites.facebook = { rows: rows.filter((r) => r.source === "facebook").length };
    return rows;
  }

  async function runPull(o) {
    const P = o.P;
    const now = o.now || (() => Date.now());
    const t0 = now();
    const state = {
      stage: "starting", message: null, error: null, search: null, plan: null,
      read: { asked: 0, done: 0, ok: 0, fromCache: 0, removed: 0, failed: 0, stopped: 0 },
      results: [], shown: 0, hidden: 0, skippedRows: {}, skippedByReason: {}, notOpened: [], readAt: {}, stoppedBecause: null, outside: {},
      startedAt: t0, firstResultAt: null, elapsed: 0, eta: null, pushback: null, requests: 0, searchesFromCache: 0,
    };
    const opened = []; // when each listing that wasn't cached finished: for the time left
    const emit = () => {
      state.elapsed = now() - t0;
      state.eta = timeLeft();
      if (o.onUpdate) o.onUpdate(state);
    };
    function timeLeft() {
      if (state.stage !== "read") return null;
      const left = state.read.asked - state.read.done;
      if (left <= 0) return 0;
      const n = opened.length;
      const per = n >= 3 ? (opened[n - 1] - opened[0]) / (n - 1) : (o.perItemMs || 2500);
      return Math.round(left * per);
    }
    const pace = Object.assign({}, o.pullOpts || {}, { shouldStop: o.shouldStop });
    const call = async (path, body) => {
      const r = await o.call(path, body);
      if (!r || !r.ok) throw new Error((r && r.body && r.body.error) || `the helper answered ${r ? r.status : "nothing"}`);
      return r.body;
    };
    try {
      const cfg = await call("/config");
      // where to look: the preferences' searches; without any, the search open in this tab
      state.prefs = cfg.prefs || {};
      let searches = (cfg.searches || []).map((x) => ({ label: x.label, label_he: x.label_he, path: x.path, hoods: x.hoods || [],
        hood_names: x.hood_names || [], centers: x.centers || [], elsewhere: x.elsewhere || null }));
      if (!searches.length) {
        if (!o.searchPath || (o.pathname && !isRentSearch(o.pathname))) {
          state.stage = "done";
          state.error = { key: "m_no_searches" };
          return emit(), state;
        }
        searches = [{ label: "this search", path: o.searchPath }];
      }
      state.stage = "search";
      state.searches = searches.map((x) => ({ label: x.label, label_he: x.label_he, hoods: x.hoods, hood_names: x.hood_names, centers: x.centers,
        path: withFilters(x.path, cfg.search_filters), seen: null, elsewhere: x.elsewhere || null }));
      emit();
      const byId = new Map();
      const searchCache = o.cache && o.cache.searches;
      const stats = { pages: 0, requests: 0, seen: 0, failedPages: [] };
      const unsureHoods = [];
      const away = [];
      for (const x of state.searches) {
        // v1.67: Yad2 serves this place on another site (yad-il.co.il), which a Yad2 tab can't read: said, not read
        if (x.elsewhere) {
          away.push(x);
          continue;
        }
        state.searching = x.label;
        state.searchingHe = x.label_he || x.label;
        // several neighborhoods: the city is read once and kept to them (v1.33: hoodFilter)
        emit();
        // after Yad2's check, a search read in the last half hour isn't read again
        const kept = o.reuseSearchMs && searchCache ? await searchCache.get(x.path) : null;
        if (kept && Array.isArray(kept.rows) && now() - kept.at <= o.reuseSearchMs) {
          x.seen = kept.rows.length;
          x.total = typeof kept.total === "number" ? kept.total : null;
          x.fromCache = true;
          state.searchesFromCache++;
          const f = hoodFilter(x, kept.rows, o.S);
          if (f.unsure) unsureHoods.push(x.label);
          x.kept = kept.rows.filter(f.keep).length; // v1.40: in the chosen neighborhoods
          for (const r of kept.rows) if (f.keep(r) && !byId.has(r.id)) byId.set(r.id, r);
          for (const r of kept.rows) if (!f.keep(r)) state.outside[r.id] = r.hood_name || "";
          x.area = areaOf(x, kept.rows.filter(f.keep));
          continue;
        }
        const s = await P.searchRows(x.path, pace);
        x.seen = s.stats.seen;
        x.total = typeof s.stats.total === "number" ? s.stats.total : null; // v1.40: what Yad2 says matches
        x.failed = s.stats.failedPages.length;
        stats.pages += s.stats.pages;
        stats.requests += s.stats.requests;
        state.requests += s.stats.requests;
        stats.failedPages.push(...s.stats.failedPages.map((p) => `${x.label} ${p}`));
        const f = hoodFilter(x, s.rows, o.S);
        if (f.unsure) unsureHoods.push(x.label);
        x.kept = s.rows.filter(f.keep).length;
        for (const r of s.rows) if (f.keep(r) && !byId.has(r.id)) byId.set(r.id, r);
        for (const r of s.rows) if (!f.keep(r)) state.outside[r.id] = r.hood_name || ""; // v1.40: for "Missing a listing?"
        x.area = areaOf(x, s.rows.filter(f.keep));
        if (s.stats.stoppedBecause) {
          state.search = Object.assign(stats, { seen: byId.size, stoppedBecause: s.stats.stoppedBecause });
          state.stage = "done";
          state.message = s.stats.stoppedBecause;
          state.stoppedBecause = s.stats.stoppedBecause;
          state.pushback = s.stats.pushback || null;
          return emit(), state;
        }
        if (searchCache && !s.stats.failedPages.length) await searchCache.set(x.path, { rows: s.rows, at: now(), total: x.total });
      }
      state.search = Object.assign(stats, { seen: byId.size });
      if (away.length) {
        state.message = { key: "m_elsewhere", params: { x: away.map((x) => x.label).join(", "), site: away[0].elsewhere } };
      } else if (stats.failedPages.length) {
        state.message = { key: "m_pages_failed", params: { pages: stats.failedPages.join(", ") } };
      } else if (unsureHoods.length) {
        state.message = { key: "m_hoods_unsure", params: { x: unsureHoods.join(", ") } };
      } else {
        // v1.40: Yad2 says how many match; fewer read than that is a gap to show, not to hide
        const short = state.searches.filter((x) => typeof x.total === "number" && typeof x.seen === "number" && x.seen < x.total * 0.97);
        if (short.length) state.message = { key: "m_read_short", params: { x: short.map((x) => `${x.label} (${x.seen}/${x.total})`).join(", ") } };
      }
      const yad2Rows = Array.from(byId.values());
      let extra = [];
      if (o.S) {
        // every place the searches cover: a city, or some of its neighborhoods (a whole-city search wins)
        const areas = {};
        for (const x of state.searches) {
          const a = x.area;
          if (!a || !a.city) continue;
          if (a.hoods == null || areas[a.city] === null) areas[a.city] = null;
          else if (a.hoods.length) areas[a.city] = Array.from(new Set((areas[a.city] || []).concat(a.hoods)));
        }
        state.stage = "sites";
        extra = await otherRows(Object.assign({}, o, { emit }), state, areas, yad2Rows, Number((cfg.search_filters || {}).maxPrice) || 0);
        for (const x of state.searches) delete x.area;
      }
      state.searching = null;
      const rows = yad2Rows.concat(extra);
      state.bySource = { yad2: yad2Rows.length, komo: state.sites ? state.sites.komo.rows : 0, madlan: state.sites ? state.sites.madlan.rows : 0,
        facebook: state.sites && state.sites.facebook ? state.sites.facebook.rows : 0 };
      state.stage = "plan";
      emit();
      const skip = (o.skip || []).map(String);
      const prefer = (o.prefer || []).map(String);
      const first = await call("/plan", { rows, skip, prefer });
      const pinRoutes = {};
      const routeErrors = [];
      if (first.pins && Object.keys(first.pins).length) {
        state.stage = "route";
        emit();
        for (const c of cfg.commutes) {
          const r = await P.routeTable(first.pins, c.anchor, c.profile, { cache: o.cache && o.cache.routes, fetch: pace.fetch });
          pinRoutes[c.signal] = Object.fromEntries(Object.entries(r.routes).map(([k, v]) => [k, { m: v.m, s: v.s }]));
          routeErrors.push(...r.stats.errors);
        }
      }
      if (routeErrors.length) {
        state.message = { key: "m_routes_failed" };
      }
      const plan = await call("/plan", { rows, pin_routes: pinRoutes, skip, prefer });
      const also = plan.also || {};
      const maybe = plan.maybe || {}; // v1.63: the same address on another site, the floor or size disagreeing: linked, never merged
      // v1.63 (owner ruling): a merged apartment is scored at its cheapest rent; the card still says which copy asks what
      const cheapest = (id, own) => {
        const ps = [own].concat((also[id] || []).map((o) => o.price)).filter((p) => typeof p === "number" && p > 0);
        return ps.length ? Math.min(...ps) : own;
      };
      const deals = dealsOf(rows);
      const rowPhotos = Object.fromEntries(rows.filter((r) => r.photos && r.photos.length).map((r) => [r.id, r.photos]));
      const photosOf = (id) => (extracts[id] && Array.isArray(extracts[id].photos) && extracts[id].photos.length ? extracts[id].photos : rowPhotos[id]);
      // v1.33: how many photos the site's own data lists (0: none in the listing), or null when we can't tell
      // (a row cached before v1.31, or a site page that didn't say). The helper scores it; the card says which.
      const rowById0 = Object.fromEntries(rows.map((r) => [r.id, r]));
      const photoCount = (id) => countPhotos(rowById0[id], extracts[id]);
      state.plan = { rows: plan.rows, open: plan.fetch.length, skipped: Object.keys(plan.skipped).length };
      state.skippedRows = plan.skipped;
      // v1.40: what the search knew about each listing it didn't open, so "Not a fit" can list them and
      // "Missing a listing?" can say why; and the posts merged into another (v1.38)
      state.skippedInfo = {};
      for (const id of Object.keys(plan.skipped)) {
        const r = rowById0[id];
        if (r && (plan.skipped[id] || [])[0] !== "You rejected it") state.skippedInfo[id] = rowFacts(r, P);
      }
      state.merged = {};
      for (const [kept, others] of Object.entries(also)) for (const a of others) state.merged[a.id] = kept;
      state.skippedByReason = plan.skipped_by_reason;
      state.skippedByTopic = plan.skipped_by_topic || {};
      state.read.asked = plan.fetch.length;
      state.stage = "read";
      emit();

      const fingerprints = Object.fromEntries(rows.map((r) => [r.id, r.fp]));
      const extracts = {};
      let scoring = null;
      let dirty = false;
      let drives = {};
      const rescore = () => {
        if (scoring) {
          dirty = true;
          return scoring;
        }
        scoring = (async () => {
          try {
            do {
              dirty = false;
              const out = await call("/score", { extracts: Object.values(extracts).map((x) => Object.assign({}, x, { photo_count: photoCount(x.id),
                price: cheapest(x.id, x.price) })),
                pin_routes: pinRoutes, drives });
              // the same apartment on another site: a link to that copy too
              // v1.32: a listing that may be a room in a shared flat isn't a "good deal" for a whole apartment
              const roomish = (x) => (x.notes || []).some((n) => ((state.prefs || {})[n.name] || {}).topic === "whole");
              const own = (id) => (extracts[id] ? extracts[id].price : null);
              state.results = out.results.map((x) => Object.assign(x, also[x.id] ? { also: also[x.id] } : {}, maybe[x.id] ? { maybe: maybe[x.id] } : {},
                typeof own(x.id) === "number" && own(x.id) !== x.price ? { price_own: own(x.id) } : {}, deals[x.id] && !roomish(x) ? { deal: deals[x.id] } : {},
                photosOf(x.id) ? { photos: photosOf(x.id) } : {}, { photos_state: photoCount(x.id) == null ? "unread" : photoCount(x.id) ? "some" : "none" }));
              state.shown = out.shown;
              state.hidden = out.hidden;
              if (out.shown && state.firstResultAt == null) state.firstResultAt = now() - t0;
              emit();
            } while (dirty);
          } finally {
            scoring = null;
          }
        })();
        return scoring;
      };
      const rowById = Object.fromEntries(rows.map((x) => [x.id, x]));
      const onResult = (id, res) => {
          state.read.done++;
          if (!res.fromCache) opened.push(now());
          if (res.status === "ok") {
            state.read.ok++;
            if (res.fromCache) state.read.fromCache++;
            extracts[id] = res.extract;
            state.readAt[id] = res.fetchedAt;
          } else if (res.status === "removed") {
            state.read.removed++;
            extracts[id] = { id, error: res.error || "no item data" };
          } else {
            state.read[res.status]++;
            state.notOpened.push({ id, url: SITE(id) === "yad2" ? P.ITEM_URL(id) : (rowById[id] || {}).url, why: res.error });
          }
          // score early (the first results fast), then every few pages
          if (res.status === "ok" && (state.read.ok <= 3 || state.read.ok % 5 === 0)) {
            rescore().catch(() => { state.message = { key: "m_score_retry" }; });
          }
          else emit();
      };
      const want = { yad2: [], komo: [], madlan: [], facebook: [] };
      for (const id of plan.fetch) want[SITE(id)].push(id);
      const pool = (o.pool && o.pool.items) || {};
      // Madlan and Facebook are never fetched: a page the user opened (a post he kept), or else what its results page said
      for (const id of want.madlan.concat(want.facebook)) {
        const kept = pool[id];
        onResult(id, { status: "ok", extract: kept ? kept.extract : rowById[id], fetchedAt: kept ? kept.seenAt : now(), fromCache: true });
      }
      // Komo: a listing page the user opened counts as read; the rest are fetched, alongside Yad2's (another site)
      const komoLeft = [];
      for (const id of want.komo) {
        const kept = pool[id];
        if (kept && kept.extract) {
          const x = Object.assign({}, kept.extract);
          const row = rowById[id] || {};
          if (x.lat == null && row.lat != null) Object.assign(x, { lat: row.lat, lng: row.lng });
          onResult(id, { status: "ok", extract: x, fetchedAt: kept.seenAt, fromCache: true });
        } else komoLeft.push(id);
      }
      const [r, k] = await Promise.all([
        P.fetchItems(want.yad2, Object.assign({}, pace, { cache: o.cache && o.cache.listings, fingerprints, onResult })),
        komoLeft.length && o.S && o.siteGet
          ? o.S.komoItems(komoLeft, { get: o.siteGet, rows: rowById, gapMs: o.siteGapMs, shouldStop: o.shouldStop, cache: o.cache && o.cache.listings,
            onResult, now, sleep: o.sleep })
          : Promise.resolve({ requests: 0, stoppedBecause: null }),
      ]);
      state.requests += k.requests;
      if (k.stoppedBecause === "komo_pushback" && state.sites) state.sites.komo.stopped = "komo_pushback";
      state.stoppedBecause = r.stats.stoppedBecause || null;
      if (state.sites && state.sites.komo.stopped && !state.message) state.message = { key: `m_${state.sites.komo.stopped}` };
      state.pushback = r.stats.pushback || null;
      state.requests += r.stats.requests;
      if (r.stats.stoppedBecause) state.message = r.stats.stoppedBecause === "stopped by you" ? { key: "m_stopped" } : r.stats.stoppedBecause;
      await rescore();

      // a car commute: TomTom's typical-traffic drive for what's shown, with the user's own key
      const cars = cfg.commutes.filter((c) => c.mode === "car");
      if (cars.length && cfg.tomtom && !r.stats.stoppedBecause) {
        state.stage = "traffic";
        emit();
        for (const c of cars) {
          const shown = state.results.filter((x) => !x.excluded && pinOf(extracts[x.id])).slice(0, 50);
          for (let i = 0; i < shown.length; i += 25) {
            const pins = Object.fromEntries(shown.slice(i, i + 25).map((x) => [x.id, pinOf(extracts[x.id])]));
            const d = await call("/drives", { signal: c.signal, pins });
            if (!d.available) break;
            drives[c.signal] = Object.assign(drives[c.signal] || {}, d.drives);
          }
        }
        drives = Object.assign({}, drives);
        await rescore();
      }
      // ways to see more: loosen one thing at a time, counted by the helper
      if (!r.stats.stoppedBecause && o.suggest !== false) {
        state.stage = "suggest";
        emit();
        try {
          const sg = await call("/suggest", { rows, extracts: Object.values(extracts), pin_routes: pinRoutes, drives, skip });
          state.suggestions = sg.suggestions || [];
        } catch (e) {
          state.suggestions = [];
        }
      }
      // v1.35: what was read, for labeling (store.keepForLabels)
      if (o.onExtracts) {
        try {
          await o.onExtracts(extracts);
        } catch (e) { /* only a convenience */ }
      }
      state.stage = "done";
      emit();
      return state;
    } catch (e) {
      state.stage = "done";
      state.error = String((e && e.message) || e);
      emit();
      return state;
    }
  }

  // v1.30: "Good deal": clearly under the usual rent for the same number of rooms in the same neighborhood
  // (at least 5 others), or else the same city (at least 8), among everything this search read
  const DEAL_BELOW = 0.12;
  const hoodOf = (r) => String(r.hood_name || "").replace(/^(?:שכונת|שכ['׳]?)\s*/, "").replace(/["'״׳]/g, "").replace(/[-–\s]+/g, " ").trim();
  function dealsOf(rows) {
    const groups = {};
    const keyOf = (r, scope) => `${scope}|${cityKey(r.city)}|${scope === "hood" ? hoodOf(r) : ""}|${Math.round(r.rooms * 2) / 2}`;
    const ok = (r) => typeof r.price === "number" && r.price > 0 && typeof r.rooms === "number" && r.rooms > 0 && r.city;
    for (const r of rows || []) {
      if (!ok(r)) continue;
      for (const scope of hoodOf(r) ? ["hood", "city"] : ["city"]) (groups[keyOf(r, scope)] = groups[keyOf(r, scope)] || []).push(r.price);
    }
    const median = (xs) => {
      const v = xs.slice().sort((a, b) => a - b);
      const m = v.length >> 1;
      return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
    };
    const out = {};
    for (const r of rows || []) {
      if (!ok(r)) continue;
      for (const [scope, least] of [["hood", 6], ["city", 9]]) {
        if (scope === "hood" && !hoodOf(r)) continue;
        const g = groups[keyOf(r, scope)] || [];
        if (g.length < least) continue; // itself and enough others
        const m = median(g);
        if (r.price <= m * (1 - DEAL_BELOW)) {
          out[r.id] = { median: Math.round(m), n: g.length, scope, rooms: Math.round(r.rooms * 2) / 2, place: scope === "hood" ? r.hood_name : r.city };
        }
        break; // the neighborhood decides when it has enough listings
      }
    }
    return out;
  }

  /** A listing's own pin as [lat, lng]: Yad2's coords, or Madlan's lat/lng; never an approximate one. */
  function pinOf(x) {
    if (!x || x.approx) return null;
    if (x.coords && typeof x.coords.lat === "number" && typeof x.coords.lon === "number") return [x.coords.lat, x.coords.lon];
    if (typeof x.lat === "number" && typeof x.lng === "number") return [x.lat, x.lng];
    return null;
  }

  /** Did the pull stop because Yad2 pushed back (a check page, 403/429/503)? */
  function isCheck(stoppedBecause) {
    return /Yad2 asked us to slow down/.test(stoppedBecause || "");
  }

  /** v1.40: the few facts a search row gives, kept for a listing that wasn't opened. */
  function rowFacts(r, P) {
    const site = (r.source || "yad2");
    return { id: r.id, source: site, price: r.price, rooms: r.rooms, size_m2: r.size_m2, floor: r.floor, city: r.city,
      hood: r.hood_name || null, url: r.url || (site === "yad2" && P && P.ITEM_URL ? P.ITEM_URL(r.id) : null),
      photo: Array.isArray(r.photos) && r.photos.length ? r.photos[0] : null };
  }

  /** v1.40: a listing's id from what the user pastes: a Yad2, Komo or Madlan link, or a bare Yad2 token. */
  function listingId(text) {
    const s = String(text || "").trim();
    let m = s.match(/yad2\.co\.il\/(?:realestate\/)?item\/(?:[a-z-]+\/)*([A-Za-z0-9]+)/);
    if (m) return m[1];
    m = s.match(/komo\.co\.il\/.*[?&]modaaNum=(\d+)/);
    if (m) return `komo:${m[1]}`;
    m = s.match(/madlan\.co\.il\/listings\/([A-Za-z0-9_-]+)/);
    if (m) return `madlan:${m[1]}`;
    return /^[A-Za-z0-9]{6,12}$/.test(s) ? s : null;
  }

  /**
   * v1.40: why a listing is or isn't in your listings, from what the last search kept.
   * {kind: "bad_link" | "rejected" | "shown" | "hidden" | "merged" | "skipped" | "unread" | "unseen", ...}
   */
  function explain(text, kept, marks) {
    const id = listingId(text);
    if (!id) return { kind: "bad_link" };
    const k = kept || {};
    if ((marks || {})[id] && marks[id].status === "rejected") return { kind: "rejected", id };
    const res = k.results || [];
    const shown = res.filter((x) => !x.excluded);
    const i = shown.findIndex((x) => x.id === id);
    if (i >= 0) return { kind: "shown", id, rank: i + 1 };
    const hid = res.find((x) => x.id === id);
    if (hid) return { kind: "hidden", id, reasons: hid.reasons || [] };
    if ((k.merged || {})[id]) return { kind: "merged", id, into: k.merged[id] };
    if ((k.skippedRows || {})[id]) return { kind: "skipped", id, reasons: k.skippedRows[id], row: (k.skippedInfo || {})[id] || null };
    if ((k.notOpened || []).some((x) => x.id === id)) return { kind: "unread", id };
    if (Object.prototype.hasOwnProperty.call(k.outside || {}, id)) return { kind: "outside", id, hood: k.outside[id] || null };
    return { kind: "unseen", id, searches: (k.searches || []).map((x) => ({ label: x.label, label_he: x.label_he, path: x.path,
      total: x.total, seen: x.seen, kept: x.kept })), at: k.finishedAt || null };
  }

  const api = { rowFacts, listingId, explain, countPhotos, hoodFilter, withFilters, isRentSearch, isCheck, runPull, areaOf, inArea, pinOf, dealsOf };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalRunner = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
