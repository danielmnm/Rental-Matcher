/*
 * Rental Matcher: the browser side of a Yad2 pull (v1.21).
 *
 * Runs in a Yad2 tab (same origin, so it reads pages the way the user's
 * own browser does) and in Node for the tests. Python stays the brain:
 * funnel.plan() decides WHICH listings to open; this file only reads
 * pages, fast and carefully.
 *
 * The pace is Yad2's, not ours. On Oct 21, 2026 a test at 4 pages a
 * second (4 in flight) was sent to Yad2's bot check ("Radware Bot
 * Manager") after ~45 s; the pulls before it, at ~0.85 pages a second, never
 * were. Several requests in flight only make a pull faster by raising that
 * rate, so the default is the proven pace: one request at a time, starts
 * >= 1.2 s apart. `concurrency` stays for slow pages (it can't raise the
 * rate past 1 / minGapMs). A pull is fast by opening fewer pages: the
 * funnel (funnel.py) and the cache below. And it never fights the site:
 *
 *  - If Yad2 pushes back (HTTP 403/429/503, or a bot-check page instead of
 *    a listing), the pull STOPS (after `maxBlocks` pushbacks: 1 by default;
 *    with more, it first drops to one at a time and slows down). It never
 *    tries to get past a check. What's left is reported as unopened, never
 *    dropped, and with a cache, everything read so far is already saved.
 *  - Every page is checked before it's used: HTTP 200, the page's own data
 *    present, and that data is for the listing that was asked for (its
 *    token matches the id). Results are keyed by id, so the order requests
 *    finish in can't mix two listings up.
 *  - A page that fails is retried (with backoff); one that still fails is
 *    reported as failed with the reason, and the user gets its link.
 *  - Contact data never leaves the page data: the extract has no poster
 *    name or phone field, and phone numbers (digits or spelled out) and the
 *    poster's own name are blanked inside the description.
 *
 * Cache (optional): a listing read before is reused only if its search-row
 * fingerprint (price, floor, rooms, size, property, address, pin, photos,
 * tags) is unchanged AND it was read less than `maxAgeMs` ago (a day by
 * default: an edit to the text alone doesn't show on the search row).
 * Anything else is opened again. Routes are cached by pin: a pin never moves.
 */
(function (root) {
  "use strict";

  // v1.57 (Nov 2): Yad2 renamed the feed's main group: the 40 ordinary listings a page carries now come
  // under "yad2" ("private" and "agency" are gone). Without it a search read only the paid slots
  // (platinum, trio, ...), a handful a page. The old names stay in case a page still sends them.
  const SEARCH_GROUPS = ["yad2", "private", "agency", "platinum", "kingOfTheHar", "trio", "booster", "leadingBroker"];
  const ITEM_URL = (id) => `https://www.yad2.co.il/realestate/item/${encodeURIComponent(id)}`;
  const PUSHBACK = new Set([403, 429, 503]);
  const BOT_CHECK = /captcha|perimeterx|px-captcha|radware|shieldsquare|perfdrive|are you a (?:human|robot)|access denied/i;
  const OSRM = "https://routing.openstreetmap.de";

  const DEFAULTS = {
    concurrency: 1, // pages in flight at once
    minGapMs: 1200, // between request starts, across all workers: the proven pace (see above)
    slowGapMs: 3000, // the pace after a pushback, if maxBlocks > 1
    retries: 2, // per page, for errors that aren't a pushback
    backoffMs: 2000, // x attempt
    maxBlocks: 1, // pushbacks before the pull stops: the first one
    maxAgeMs: 24 * 3600 * 1000, // a cached listing older than this is opened again
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---- page data -------------------------------------------------------

  function nextData(html) {
    const m = /<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/.exec(html || "");
    if (!m) return null;
    try {
      return JSON.parse(m[1]);
    } catch (e) {
      return null;
    }
  }

  function queries(nd) {
    const s = nd && nd.props && nd.props.pageProps && nd.props.pageProps.dehydratedState;
    return (s && Array.isArray(s.queries) && s.queries) || [];
  }

  function looksBlocked(status, html) {
    if (PUSHBACK.has(status)) return true;
    const h = html || "";
    return h.indexOf("__NEXT_DATA__") < 0 && BOT_CHECK.test(h);
  }

  /** The item's data on its own page, only if it's the listing asked for. */
  function itemData(nd, id) {
    for (const q of queries(nd)) {
      const k = q.queryKey || [];
      const d = q.state && q.state.data;
      if (k[0] === "item" && String(k[1]) === id && d && typeof d === "object" && String(d.token) === id) return d;
    }
    return null;
  }

  // ---- privacy -----------------------------------------------------------

  const HEB = "(?<![\\u0590-\\u05FF])";
  const HEB_END = "(?![\\u0590-\\u05FF])";
  const DIGIT_WORDS = ["שמונה", "שתיים", "שניים", "ארבע", "שלוש", "שתים", "שלש", "אפס", "אחת", "אחד", "חמש", "שבע", "תשע", "שש"];
  const EN_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
  const WORD = `(?:${HEB}ו?(?:${DIGIT_WORDS.join("|")})${HEB_END}|\\b(?:${EN_WORDS.join("|")})\\b)`;
  const SPELLED = new RegExp(`${WORD}(?:[\\s,\\-]+${WORD}){6,}`, "gi");
  // an Israeli number: 0 or (+)972, then 8-9 more digits, single spaces or dashes between
  const DIGITS = /(?<!\d)(?:\+?972[-.\s]?|0)(?:\d[-.\s]?){7,8}\d(?!\d)/g; // v1.57: dots too ("052.6003707", batch 11)
  // v1.53: a mobile prefix, a word or two, then the number: "050 מספר 5792223" (census, Oct 29)
  const SPLIT = /(?<!\d)(?:\+?972[-\s]?|0)(?:5\d|7\d)[\s\-]+(?:[^\d\s]{1,8}[\s\-]+){1,2}\d{3}[\s\-]?\d{4}(?!\d)/g;

  function escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // control characters a description sometimes carries (U+0096 for a dash, say); not newlines or tabs
  const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/g;

  /**
   * Phone numbers (digits or spelled out) -> [phone]; the poster's own name
   * -> [name], but only a name of two words or more. On Oct 21 a poster
   * named "אור" (also the word for light) turned "שפע אור טבעי" (plenty of
   * natural light) into "שפע [name] טבעי". A one-word name is too often an
   * ordinary word, and blanking it would change what the listing says.
   */
  function scrub(text, posterName) {
    if (typeof text !== "string") return text == null ? null : text;
    let t = text.replace(CONTROL, " ").replace(SPLIT, "[phone]").replace(DIGITS, "[phone]").replace(SPELLED, "[phone]");
    const name = typeof posterName === "string" ? posterName.trim().replace(/\s+/g, " ") : "";
    const words = name.split(" ").filter((w) => w.length >= 2);
    if (words.length >= 2) t = t.replace(new RegExp(escapeRe(name).replace(/ /g, "\\s+"), "g"), "[name]");
    return t;
  }

  // ---- shapes ------------------------------------------------------------

  const txt = (o) => (o && typeof o.text === "string" ? o.text : null);

  /** An item page's data -> the extract rental_matcher/adapters/yad2.py reads. */
  function toExtract(d, id) {
    const a = d.address || {};
    const ad = d.additionalDetails || {};
    const md = d.metaData || {};
    // Yad2's structured facts, all of them (parkingSpacesCount, balconiesCount,
    // isEnterDateFlexible...): the adapter reads more than a few. Nothing in
    // this block is about the poster.
    const details = JSON.parse(JSON.stringify(ad));
    const x = {
      id,
      adType: d.adType == null ? null : d.adType,
      price: d.price == null ? null : d.price,
      floor: a.house && a.house.floor != null ? a.house.floor : null,
      city: txt(a.city),
      neighborhood: txt(a.neighborhood),
      street: txt(a.street),
    };
    if (a.coords && typeof a.coords.lat === "number" && typeof a.coords.lon === "number") {
      x.coords = { lat: a.coords.lat, lon: a.coords.lon };
    }
    x.additionalDetails = details;
    x.inProperty = Object.assign({}, d.inProperty || {});
    if (d.dates && d.dates.createdAt) x.dates = { createdAt: d.dates.createdAt };
    x.description = scrub(md.description == null ? null : md.description, d.customer && d.customer.name);
    // v1.53: more of Yad2's own fields: the fees it shows ("ארנונה (לחודשיים)", "ועד בית (לחודש)"), the poster's
    // furniture list ("פירוט ריהוט") and its distance to the nearest public shelter ("מקלט במרחק 349 מ'")
    if (typeof d.propertyTax === "number" && d.propertyTax > 0) x.propertyTax = d.propertyTax;
    if (typeof d.houseCommittee === "number" && d.houseCommittee > 0) x.houseCommittee = d.houseCommittee;
    if (typeof d.furnitureInfo === "string" && d.furnitureInfo.trim()) x.furnitureInfo = scrub(d.furnitureInfo, d.customer && d.customer.name);
    if (typeof md.shelterDistance === "number" && md.shelterDistance >= 0) x.shelterDistance = md.shelterDistance;
    x.source_url = ITEM_URL(id);
    return x;
  }

  /** What, on a search row, would change if the listing were edited. */
  function fingerprint(it) {
    const a = it.address || {};
    const ad = it.additionalDetails || {};
    const md = it.metaData || {};
    const h = a.house || {};
    const c = a.coords || {};
    return JSON.stringify([
      it.price, it.adType, h.floor, h.number, ad.roomsCount, ad.squareMeter, md.squareMeterBuild,
      ad.property && ad.property.id, a.street && a.street.id, a.neighborhood && a.neighborhood.id,
      c.lat, c.lon, md.coverImage, md.images || [], (it.tags || []).map((t) => t && t.name),
    ]);
  }

  /** A search row in funnel.py's row shape, plus its fingerprint. */
  /** A listing's photos as Yad2 lists them: addresses on its image server, cover first, at most 20. */
  function photosOf(md) {
    const list = [].concat(md.coverImage ? [md.coverImage] : [], Array.isArray(md.images) ? md.images : []);
    const ok = (u) => typeof u === "string" && /^https:\/\/img\.yad2\.co\.il\/Pic\/[A-Za-z0-9_/.-]+\.(?:jpe?g|png|webp)$/i.test(u);
    return Array.from(new Set(list.filter(ok))).slice(0, 20);
  }

  function toRow(it) {
    const a = it.address || {};
    const ad = it.additionalDetails || {};
    const md = it.metaData || {};
    const c = a.coords || {};
    const pin = typeof c.lat === "number" && typeof c.lon === "number";
    return {
      id: String(it.token),
      adType: it.adType == null ? null : it.adType,
      price: it.price == null ? null : it.price,
      floor: a.house && a.house.floor != null ? a.house.floor : null,
      lat: pin ? c.lat : null,
      lng: pin ? c.lon : null,
      rooms: ad.roomsCount == null ? null : ad.roomsCount,
      size_m2: md.squareMeterBuild != null ? md.squareMeterBuild : ad.squareMeter == null ? null : ad.squareMeter,
      property: ad.property && typeof ad.property.text === "string" ? ad.property.text : null,
      city: txt(a.city),
      hood: a.neighborhood && a.neighborhood.id != null ? Number(a.neighborhood.id) : null,
      hood_name: txt(a.neighborhood), // to match Komo's and Madlan's listings to the same neighborhood
      // v1.63: the street and house number, which the search already sends: the duplicate matcher compares the address
      // first, and never merges two listings without one (it joined different flats when it had only the neighborhood)
      street: [txt(a.street), a.house && a.house.number != null ? String(a.house.number) : null].filter((v) => v).join(" ") || null,
      photos: photosOf(md), // v1.31: the listing's photo addresses (Yad2 sends them with the search; nothing extra is read)
      fp: fingerprint(it),
    };
  }

  function feed(nd) {
    for (const q of queries(nd)) {
      if (JSON.stringify(q.queryKey || []).indexOf("rent-feed") >= 0 && q.state && q.state.data) return q.state.data;
    }
    return null;
  }

  // ---- pacing --------------------------------------------------------------

  function makeLimiter(opts) {
    const o = Object.assign({}, DEFAULTS, opts);
    const fetchFn = o.fetch || (root.fetch && root.fetch.bind(root));
    const now = o.now || (() => Date.now());
    const wait = o.sleep || sleep;
    const lim = {
      concurrency: o.concurrency,
      gap: o.minGapMs,
      stopped: null,
      slowed: false,
      inRow: 0,
      active: 0,
      stats: { requests: 0, pushbacks: 0, retries: 0, starts: [] },
      o,
      now,
      sleep: wait,
    };
    // One request starts at a time, at least lim.gap after the one before it
    // ACTUALLY started (not after when it was scheduled), at the pace in
    // force when its turn comes -- so a slow-down applies to everything queued.
    let chain = Promise.resolve();
    let last = -Infinity;
    function gate() {
      const turn = chain.then(async () => {
        // and never more in flight than allowed NOW (a slow-down also holds back
        // requests that were already waiting their turn)
        while (lim.active >= lim.concurrency && !lim.stopped) await wait(Math.max(5, lim.gap / 10));
        const w = last + lim.gap - now();
        if (w > 0) await wait(w);
        last = now();
        lim.active++;
      });
      chain = turn;
      return turn;
    }
    /** One GET. {status, html, url, ms, error, blocked}. A pushback slows
     * the whole pull down and, after maxBlocks in a row, stops it. */
    lim.get = async function (url) {
      await gate();
      if (!lim.stopped && o.shouldStop && o.shouldStop()) lim.stopped = "stopped by you";
      if (lim.stopped) {
        lim.active--;
        return { stopped: true };
      }
      const slowAtStart = lim.slowed;
      lim.stats.requests++;
      lim.stats.starts.push(now());
      const t0 = now();
      let status = 0, html = "", final = url, error = null;
      try {
        const r = await fetchFn(url, { credentials: "same-origin", redirect: "follow" });
        status = r.status;
        final = r.url || url;
        html = await r.text();
      } catch (e) {
        error = "network error";
      }
      lim.active--;
      const res = { status, html, url: final, ms: now() - t0, error, blocked: false };
      if (!error && looksBlocked(status, html)) {
        res.blocked = true;
        lim.stats.pushbacks++;
        // what Yad2 said, for the pull log: never the page itself
        lim.pushback = { status, checkPage: !PUSHBACK.has(status), what: /\/realestate\/item\//.test(url) ? "listing" : "search page",
          request: lim.stats.requests, gapMs: lim.gap, at: now() };
        if (!lim.slowed) {
          // the first pushback: one request at a time, slower, for the rest of the pull
          lim.slowed = true;
          lim.inRow = 1;
          lim.concurrency = 1;
          lim.gap = Math.max(lim.gap, o.slowGapMs);
        } else if (slowAtStart) {
          lim.inRow++; // only pushbacks at the slow pace count toward stopping
        }
        if (lim.inRow >= o.maxBlocks) {
          lim.stopped = `Yad2 asked us to slow down (HTTP ${status}${PUSHBACK.has(status) ? "" : ", a check page"}), so the pull stopped; nothing was forced`;
        } else {
          await wait(o.backoffMs * lim.inRow);
        }
      } else if (!error) {
        lim.inRow = 0;
      }
      return res;
    };
    return lim;
  }

  /** Run handle(item) over items with up to lim.concurrency in flight.
   * Returns the items never started (the pull stopped). */
  async function runQueue(items, handle, lim) {
    const queue = items.slice();
    const max = lim.concurrency;
    async function worker(w) {
      while (queue.length && !lim.stopped && w < lim.concurrency) {
        await handle(queue.shift());
      }
    }
    await Promise.all(Array.from({ length: Math.max(1, max) }, (_, w) => worker(w)));
    if (!lim.stopped && queue.length) await worker(0); // a worker that stepped down left work
    return queue;
  }

  // ---- item pages ------------------------------------------------------------

  /**
   * Open listings' pages. ids: best first (funnel.plan's order).
   * opts: concurrency, minGapMs, ..., cache ({get, set}), fingerprints ({id: fp}),
   *       onResult(id, result) for showing results as they arrive.
   * Returns {results: {id: {status, extract?, error?, fetchedAt, fromCache, attempts}}, stats}.
   * status: "ok" | "removed" (Yad2 has no data for it) | "failed" | "stopped".
   */
  async function fetchItems(ids, opts) {
    const lim = makeLimiter(opts || {});
    const o = lim.o;
    const t0 = lim.now();
    const results = {};
    const seen = new Set();
    const queue = [];
    const done = (id, r) => {
      results[id] = r;
      if (o.onResult) o.onResult(id, r);
    };
    for (const raw of ids) {
      const id = String(raw);
      if (seen.has(id)) continue;
      seen.add(id);
      const fp = o.fingerprints && o.fingerprints[id];
      const hit = o.cache && fp ? await o.cache.get(id) : null;
      if (hit && hit.fp === fp && hit.extract && lim.now() - hit.fetchedAt <= o.maxAgeMs) {
        done(id, { status: "ok", extract: hit.extract, fetchedAt: hit.fetchedAt, fromCache: true, attempts: 0 });
      } else {
        queue.push(id);
      }
    }
    async function open(id) {
      let attempt = 0;
      for (;;) {
        attempt++;
        const r = await lim.get(ITEM_URL(id));
        if (r.stopped) return done(id, { status: "stopped", error: lim.stopped, fromCache: false, attempts: attempt - 1 });
        if (r.blocked) {
          if (lim.stopped) return done(id, { status: "stopped", error: lim.stopped, fromCache: false, attempts: attempt });
          attempt--; // a pushback isn't this page's fault; maxBlocks bounds it
          continue;
        }
        let error = r.error;
        if (!error && (r.status === 404 || r.status === 410)) {
          return done(id, { status: "removed", error: "no item data", fromCache: false, attempts: attempt });
        }
        if (!error && r.status === 200) {
          const nd = nextData(r.html);
          if (nd) {
            const d = itemData(nd, id);
            const fetchedAt = lim.now();
            if (!d) return done(id, { status: "removed", error: "no item data", fromCache: false, attempts: attempt });
            const extract = toExtract(d, id);
            const fp = o.fingerprints && o.fingerprints[id];
            if (o.cache && fp) await o.cache.set(id, { fp, fetchedAt, extract });
            return done(id, { status: "ok", extract, fetchedAt, fromCache: false, attempts: attempt });
          }
          error = "the page had no listing data";
        } else if (!error) {
          error = `HTTP ${r.status}`;
        }
        if (attempt > o.retries) return done(id, { status: "failed", error, fromCache: false, attempts: attempt });
        lim.stats.retries++;
        await lim.sleep(o.backoffMs * attempt);
      }
    }
    const left = await runQueue(queue, open, lim);
    for (const id of left) done(id, { status: "stopped", error: lim.stopped, fromCache: false, attempts: 0 });
    const count = (s) => Object.values(results).filter((r) => r.status === s).length;
    return {
      results,
      stats: {
        asked: seen.size,
        fromCache: Object.values(results).filter((r) => r.fromCache).length,
        ok: count("ok"),
        removed: count("removed"),
        failed: count("failed"),
        stopped: count("stopped"),
        requests: lim.stats.requests,
        retries: lim.stats.retries,
        pushbacks: lim.stats.pushbacks,
        pushback: lim.pushback || null,
        stoppedBecause: lim.stopped,
        ms: lim.now() - t0,
      },
    };
  }

  /** In the shape pipeline.py reads: an extract, or {id, error} to skip. */
  function extractsOf(results, order) {
    const ids = order || Object.keys(results);
    return ids.filter((id) => results[id] && results[id].status !== "stopped" && results[id].status !== "failed")
      .map((id) => (results[id].status === "ok" ? results[id].extract : { id, error: results[id].error || "no item data" }));
  }

  // ---- search pages ------------------------------------------------------------

  /**
   * Every row of a Yad2 search. base: a search path with its query, e.g.
   * "/realestate/rent/tel-aviv-area?area=11&city=6600&maxPrice=5450".
   * Page 1 says how many pages there are; the rest are read in parallel.
   * Yad2 says how many listings match (pagination.total); if a read sees
   * fewer (listings move between pages while they're read), every page is
   * read once more and the two reads are joined, so a listing that moved
   * isn't missed.
   */
  /**
   * Where Yad2 actually serves a search: a short address like
   * /realestate/rent?city=6600 is redirected to its region's page
   * (/realestate/rent/tel-aviv-area?area=11&city=6600). The rest of the
   * pages are read there, with our own parameters kept, so each page is
   * one request, not two. null: no change (or not a Yad2 rentals page).
   */
  function rebase(base, finalUrl) {
    let b, f;
    try {
      b = new URL(base, "https://www.yad2.co.il");
      f = new URL(finalUrl, "https://www.yad2.co.il");
    } catch (e) {
      return null;
    }
    if (f.hostname !== "www.yad2.co.il" || !/^\/realestate\/rent(\/|$)/.test(f.pathname)) return null;
    const params = new URLSearchParams(b.search);
    params.delete("page");
    for (const [k, v] of f.searchParams) if (k !== "page" && !params.has(k)) params.set(k, v);
    const out = `${f.pathname}?${params.toString()}`;
    const was = `${b.pathname}?${(() => { const q = new URLSearchParams(b.search); q.delete("page"); return q.toString(); })()}`;
    return out === was ? null : out;
  }

  /** v1.63: Yad2 writes city codes with four digits: "city=70" (Ashdod) returns an empty page with no error; "city=0070" works. */
  function cityCode(path) {
    return String(path || "").replace(/([?&]city=)(\d{1,3})(?=&|#|$)/, (m, k, d) => k + d.padStart(4, "0"));
  }

  async function searchRows(base, opts) {
    base = cityCode(base);
    const lim = makeLimiter(opts || {});
    const t0 = lim.now();
    const rows = new Map();
    let sep = base.indexOf("?") >= 0 ? "&" : "?";
    let pages = 0, total = null;
    const failed = new Set();
    async function read(p) {
      for (let attempt = 1; ; attempt++) {
        const r = await lim.get(`${base}${sep}page=${p}`);
        if (r.stopped) return null;
        if (p === 1 && !r.blocked && r.url) {
          const moved = rebase(base, r.url);
          if (moved) {
            base = moved;
            sep = "&";
          }
        }
        if (r.blocked) {
          if (lim.stopped) return null;
          attempt--;
          continue;
        }
        const f = !r.error && r.status === 200 ? feed(nextData(r.html)) : null;
        if (f) {
          for (const g of SEARCH_GROUPS) for (const it of Array.isArray(f[g]) ? f[g] : []) {
            if (it && it.token != null && !rows.has(String(it.token))) rows.set(String(it.token), toRow(it));
          }
          failed.delete(p);
          return f;
        }
        if (attempt > lim.o.retries) {
          failed.add(p);
          return null;
        }
        lim.stats.retries++;
        await lim.sleep(lim.o.backoffMs * attempt);
      }
    }
    const first = await read(1);
    if (!first) {
      return { rows: [], stats: { pages: 0, passes: 1, total: null, seen: 0, failedPages: [1], requests: lim.stats.requests,
        pushbacks: lim.stats.pushbacks, pushback: lim.pushback || null, stoppedBecause: lim.stopped, ms: lim.now() - t0 } };
    }
    const n = (first.pagination && first.pagination.totalPages) || 1;
    total = first.pagination && first.pagination.total;
    const rest = Array.from({ length: Math.max(0, n - 1) }, (_, i) => i + 2);
    await runQueue(rest, read, lim);
    pages = n;
    let passes = 1;
    if (!lim.stopped && typeof total === "number" && rows.size < total) {
      passes = 2;
      await runQueue(Array.from({ length: n }, (_, i) => i + 1), read, lim);
    }
    return {
      rows: Array.from(rows.values()),
      stats: {
        pages, passes, total, seen: rows.size, failedPages: Array.from(failed).sort((a, b) => a - b), requests: lim.stats.requests,
        pushbacks: lim.stats.pushbacks, pushback: lim.pushback || null, stoppedBecause: lim.stopped, ms: lim.now() - t0,
      },
    };
  }

  // ---- routes ----------------------------------------------------------------

  /**
   * Routed distance (m) and time (s) from `anchor` [lat, lng] to each pin
   * {key: [lat, lng]}, by OSRM's public server: one table request per 60
   * pins, at least 1.1 s apart (its policy: one request a second). With a
   * cache, a pin already routed for this anchor and profile isn't asked again.
   */
  async function routeTable(pins, anchor, profile, opts) {
    const o = Object.assign({ perRequest: 60, gapMs: 1100, cache: null }, opts || {});
    const fetchFn = o.fetch || (root.fetch && root.fetch.bind(root));
    const wait = o.sleep || sleep;
    const tag = `${profile}|${anchor[0].toFixed(5)},${anchor[1].toFixed(5)}|`;
    const out = {};
    const todo = [];
    for (const [k, p] of Object.entries(pins)) {
      const hit = o.cache ? await o.cache.get(tag + k) : null;
      if (hit && typeof hit.m === "number" && typeof hit.s === "number") out[k] = { m: hit.m, s: hit.s, fromCache: true };
      else todo.push([k, p]);
    }
    let requests = 0;
    const errors = [];
    for (let i = 0; i < todo.length; i += o.perRequest) {
      if (requests) await wait(o.gapMs);
      const chunk = todo.slice(i, i + o.perRequest);
      const coords = [[anchor[0], anchor[1]]].concat(chunk.map((c) => c[1])).map((p) => `${p[1]},${p[0]}`).join(";");
      const url = `${OSRM}/routed-${profile}/table/v1/driving/${coords}?sources=0&annotations=distance,duration`;
      requests++;
      let j = null;
      try {
        const r = await fetchFn(url);
        j = JSON.parse(await r.text());
      } catch (e) {
        j = null;
      }
      const n1 = chunk.length + 1;
      if (!j || j.code !== "Ok" || !Array.isArray(j.distances) || !Array.isArray(j.durations) ||
          !Array.isArray(j.distances[0]) || !Array.isArray(j.durations[0]) || j.distances[0].length !== n1 || j.durations[0].length !== n1) {
        errors.push(`request ${requests}: no table, or not one entry per pin`);
        continue; // those pins stay unrouted: a check, never a hide
      }
      for (let n = 0; n < chunk.length; n++) {
        const m = j.distances[0][n + 1], s = j.durations[0][n + 1];
        if (typeof m !== "number" || typeof s !== "number") continue;
        out[chunk[n][0]] = { m, s, fromCache: false };
        if (o.cache) await o.cache.set(tag + chunk[n][0], { m, s });
      }
    }
    return { routes: out, stats: { pins: Object.keys(pins).length, fromCache: Object.keys(pins).length - todo.length, requests, errors } };
  }

  // ---- caches ----------------------------------------------------------------

  function memoryCache() {
    const m = new Map();
    return {
      get: async (k) => (m.has(k) ? JSON.parse(m.get(k)) : null),
      set: async (k, v) => void m.set(k, JSON.stringify(v)),
      clear: async () => m.clear(),
      size: async () => m.size,
    };
  }

  /** A cache in this browser's IndexedDB (stays on this computer). */
  function idbCache(store) {
    const name = "rental-matcher-cache";
    let db = null;
    const open = () =>
      db ||
      (db = new Promise((res, rej) => {
        const r = root.indexedDB.open(name, 2); // 2 (v1.25): + searches
        r.onupgradeneeded = () => {
          for (const s of ["listings", "routes", "searches"]) if (!r.result.objectStoreNames.contains(s)) r.result.createObjectStore(s);
        };
        r.onsuccess = () => res(r.result);
        r.onerror = () => rej(r.error);
      }));
    const tx = (mode, f) =>
      open().then(
        (db) =>
          new Promise((res, rej) => {
            const t = db.transaction(store, mode);
            const q = f(t.objectStore(store));
            t.oncomplete = () => res(q && q.result);
            t.onerror = () => rej(t.error);
          })
      );
    return {
      get: (k) => tx("readonly", (s) => s.get(k)).then((v) => (v === undefined ? null : v)),
      set: (k, v) => tx("readwrite", (s) => s.put(v, k)).then(() => undefined),
      clear: () => tx("readwrite", (s) => s.clear()).then(() => undefined),
      size: () => tx("readonly", (s) => s.count()),
    };
  }

  const api = {
    DEFAULTS, ITEM_URL, nextData, itemData, looksBlocked, scrub, toExtract, toRow, fingerprint, feed,
    makeLimiter, runQueue, fetchItems, extractsOf, searchRows, cityCode, rebase, routeTable, memoryCache, idbCache,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalPull = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
