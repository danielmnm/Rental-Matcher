// node --test browser/   (also run from tests/test_browser_pull.py)
"use strict";
const nodeTest = require("node:test");
const test = (name, fn) => nodeTest(name, { timeout: 20000 }, fn);
const assert = require("node:assert/strict");
const P = require("./yad2_pull.js");
const R = require("./runner.js");

const FAST = { minGapMs: 1, backoffMs: 1 };

function nd(queries) {
  return `<script id="__NEXT_DATA__" type="application/json">${JSON.stringify({ props: { pageProps: { dehydratedState: { queries } } } })}</script>`;
}
const row = (id, lat) => ({ token: id, adType: "private", price: 4000, address: { house: { floor: 2 }, coords: { lat, lon: 34.77 } },
  additionalDetails: { roomsCount: 3, squareMeter: 60, property: { text: "דירה" } }, metaData: {} });
const item = (id, lat) => ({ ...row(id, lat), metaData: { description: `listing ${id}` }, inProperty: {} });

/** A fake Yad2 + OSRM: 7 listings over 2 search pages. */
function fakeWeb(opts = {}) {
  const listings = Array.from({ length: 7 }, (_, i) => [`L${i}`, 32 + i / 100]);
  const log = { search: 0, items: [], osrm: 0 };
  const fetch = async (url) => {
    let status = 200, body = "";
    if (url.includes("routing.openstreetmap.de")) {
      log.osrm++;
      const n = url.split("driving/")[1].split("?")[0].split(";").length - 1;
      const d = [0, ...Array.from({ length: n }, (_, i) => 3000 + i)];
      body = JSON.stringify({ code: "Ok", distances: [d], durations: [d.map((x) => x / 5)] });
    } else if (url.includes("/item/")) {
      const id = url.split("/item/")[1];
      log.items.push(id);
      if (opts.pushbackAt && log.items.length === opts.pushbackAt) status = 429;
      else if (id === opts.gone) status = 404;
      else if (id === opts.broken) status = 500;
      else body = nd([{ queryKey: ["item", id], state: { data: item(id, listings.find((l) => l[0] === id)[1]) } }]);
    } else {
      log.search++;
      const page = Number(/page=(\d+)/.exec(url)[1]);
      const rows = listings.slice((page - 1) * 4, page * 4).map(([id, lat]) => row(id, lat));
      body = nd([{ queryKey: ["realestate", "rent-feed"], state: { data: { private: rows, pagination: { total: 7, totalPages: 2 } } } }]);
    }
    return { status, url, text: async () => body };
  };
  return { fetch, log };
}

/** A toy helper: skips L6 by "price", opens the rest best-first by id; scores everything as shown but removed ones. */
function toyHelper() {
  const calls = [];
  const call = async (path, body) => {
    calls.push([path, body]);
    if (path === "/config") {
      return { ok: true, body: { search_filters: { maxPrice: "5450" }, tomtom: false,
        commutes: [{ signal: "bike_minutes", mode: "ebike", profile: "bike", anchor: [32.0754, 34.7749] }] } };
    }
    if (path === "/plan") {
      const ids = body.rows.map((r) => r.id).filter((id) => id !== "L6");
      const out = { rows: body.rows.length, fetch: ids, later: [], skipped: { L6: ["Monthly rent (ILS): too high"] },
        skipped_by_reason: { "Monthly rent (ILS)": 1 } };
      if (!body.pin_routes || !Object.keys(body.pin_routes).length) {
        out.pins = Object.fromEntries(body.rows.map((r) => [`${r.lat},${r.lng}`, [r.lat, r.lng]]));
      }
      return { ok: true, body: out };
    }
    if (path === "/score") {
      const results = body.extracts.filter((x) => !x.error).map((x) => ({ id: x.id, excluded: false }));
      return { ok: true, body: { results, shown: results.length, hidden: 0, skipped: [] } };
    }
    return { ok: false, status: 404, body: { error: "not found" } };
  };
  return { call, calls };
}

test("the user's search keeps its filters, gets our price cap (the lower one), loses its page", () => {
  assert.equal(R.withFilters("/realestate/rent/tel-aviv-area?area=11&city=6600&page=3", { maxPrice: "5450" }),
    "/realestate/rent/tel-aviv-area?area=11&city=6600&maxPrice=5450");
  assert.equal(R.withFilters("/realestate/rent?city=6600&maxPrice=4000", { maxPrice: "5450" }), "/realestate/rent?city=6600&maxPrice=4000");
  assert.equal(R.withFilters("/realestate/rent?maxPrice=9000&elevator=1", { maxPrice: "5450" }), "/realestate/rent?maxPrice=5450&elevator=1");
  assert.equal(R.withFilters("/realestate/rent", {}), "/realestate/rent");
  assert.ok(R.isRentSearch("/realestate/rent/tel-aviv-area"));
  assert.ok(!R.isRentSearch("/realestate/forsale"));
});

test("a whole pull: search, plan, route, plan, read best first, scores as pages arrive", async () => {
  const web = fakeWeb();
  const h = toyHelper();
  const updates = [];
  const cache = { listings: P.memoryCache(), routes: P.memoryCache() };
  const run = (extra = {}) => R.runPull({ searchPath: "/realestate/rent?city=6600", pathname: "/realestate/rent", call: h.call, P, cache,
    pullOpts: { ...FAST, fetch: web.fetch }, onUpdate: (s) => updates.push(JSON.parse(JSON.stringify(s))), ...extra });
  // the routing step's own fetch is the global one: give it the fake
  const realFetch = globalThis.fetch;
  globalThis.fetch = web.fetch;
  try {
    const s = await run();
    assert.equal(s.error, null);
    assert.equal(s.stage, "done");
    assert.equal(web.log.search, 2);
    assert.ok(h.calls[1][1].rows.every((r) => r.fp)); // rows carry their fingerprint
    assert.equal(h.calls.filter(([p]) => p === "/plan").length, 2);
    assert.ok(h.calls.filter(([p]) => p === "/plan").every(([, b]) => Array.isArray(b.prefer))); // v1.38: marked ids, for merging posts
    assert.ok(Object.keys(h.calls[2][1].pin_routes.bike_minutes).length === 7); // routes went into the second plan
    assert.deepEqual(web.log.items, ["L0", "L1", "L2", "L3", "L4", "L5"]); // the plan's order; L6 never opened
    assert.equal(s.shown, 6);
    assert.deepEqual(s.skippedByReason, { "Monthly rent (ILS)": 1 });
    // v1.40: what each search covered, and the facts of the one not opened, for "Not a fit" and "Missing a listing?"
    assert.equal(s.searches[0].kept, s.searches[0].seen);
    const skippedIds = Object.keys(s.skippedRows);
    assert.deepEqual(Object.keys(s.skippedInfo), skippedIds);
    assert.match(s.skippedInfo[skippedIds[0]].url, /^https:\/\/www\.yad2\.co\.il\/realestate\/item\//);
    assert.equal(R.explain(s.skippedInfo[skippedIds[0]].url, s, {}).kind, "skipped");
    assert.ok(s.firstResultAt !== null);
    const growing = updates.filter((u) => u.stage === "read").map((u) => u.results.length);
    assert.ok(growing.includes(1) && growing.indexOf(1) < growing.lastIndexOf(6)); // results showed up as they came
    assert.ok(h.calls.find(([p]) => p === "/score")[1].extracts.length < 6); // the first score didn't wait for all pages
    // the same pull again: nothing opened, nothing routed
    web.log.items.length = 0;
    const osrm = web.log.osrm;
    const again = await run();
    assert.deepEqual(web.log.items, []);
    assert.equal(web.log.osrm, osrm);
    assert.equal(again.read.fromCache, 6);
    assert.equal(again.shown, 6);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("removed, broken and unopened listings are all accounted for", async () => {
  const realFetch = globalThis.fetch;
  for (const opts of [{ gone: "L2", broken: "L3" }, { pushbackAt: 4 }]) {
    const web = fakeWeb(opts);
    globalThis.fetch = web.fetch;
    try {
      const s = await R.runPull({ searchPath: "/realestate/rent", call: toyHelper().call, P, pullOpts: { ...FAST, fetch: web.fetch, retries: 1 } });
      const r = s.read;
      assert.equal(r.ok + r.removed + r.failed + r.stopped, 6, JSON.stringify(r));
      if (opts.gone) {
        assert.deepEqual([r.removed, r.failed], [1, 1]);
        assert.deepEqual(s.notOpened.map((x) => [x.id, x.why]), [["L3", "HTTP 500"]]);
        assert.equal(s.notOpened[0].url, "https://www.yad2.co.il/realestate/item/L3");
      } else {
        assert.equal(r.ok, 3);
        assert.equal(r.stopped, 3);
        assert.ok(s.message.includes("Yad2 asked us to slow down"));
        assert.equal(s.shown, 3); // what was read before it stopped is still shown
        assert.equal(s.notOpened.length, 3);
      }
    } finally {
      globalThis.fetch = realFetch;
    }
  }
});

test("no helper, or the wrong page: said plainly, nothing fetched", async () => {
  const web = fakeWeb();
  const down = async () => ({ ok: false, status: 0, body: { error: "The Rental Matcher helper isn't running." } });
  const s = await R.runPull({ searchPath: "/realestate/rent", call: down, P, pullOpts: { ...FAST, fetch: web.fetch } });
  assert.equal(s.error, "The Rental Matcher helper isn't running.");
  assert.equal(web.log.search, 0);
  const w = await R.runPull({ searchPath: "/", pathname: "/", call: toyHelper().call, P, pullOpts: { ...FAST, fetch: web.fetch } });
  assert.deepEqual(w.error, { key: "m_no_searches" }); // worded by i18n.js, in the user's language
});

test("the preferences' searches: each read in turn, every listing once", async () => {
  const web = fakeWeb();
  const realFetch = globalThis.fetch;
  globalThis.fetch = web.fetch;
  const h = toyHelper();
  const call = async (path, body) => {
    const r = await h.call(path, body);
    if (path === "/config") r.body.searches = [{ label: "Bat Yam", path: "/realestate/rent/a?city=1" }, { label: "Ramat HaSharon", path: "/realestate/rent/b?city=2" }];
    return r;
  };
  try {
    const s = await R.runPull({ searchPath: "/", pathname: "/", call, P, pullOpts: { ...FAST, fetch: web.fetch } }); // any Yad2 page will do
    assert.equal(s.error, null);
    assert.equal(web.log.search, 4); // 2 pages each
    assert.deepEqual(s.searches.map((x) => [x.label, x.path, x.seen]),
      [["Bat Yam", "/realestate/rent/a?city=1&maxPrice=5450", 7], ["Ramat HaSharon", "/realestate/rent/b?city=2&maxPrice=5450", 7]]);
    assert.equal(s.search.seen, 7); // the same 7 listings both times (the fake has one city): once each
    assert.equal(h.calls.find(([p]) => p === "/plan")[1].rows.length, 7);
    assert.ok(R.isCheck("Yad2 asked us to slow down (HTTP 429), so the pull stopped; nothing was forced"));
    assert.ok(!R.isCheck("stopped by you"));
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("stop means stop", async () => {
  const web = fakeWeb();
  const realFetch = globalThis.fetch;
  globalThis.fetch = web.fetch;
  let read = 0;
  try {
    const s = await R.runPull({ searchPath: "/realestate/rent", call: toyHelper().call, P, pullOpts: { ...FAST, fetch: web.fetch },
      onUpdate: (st) => { read = st.read.done; }, shouldStop: () => read >= 2 });
    assert.equal(s.read.ok, 2);
    assert.deepEqual(s.message, { key: "m_stopped" });
    assert.equal(web.log.items.length, 2);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("v1.33: a neighborhoods search keeps its rows by id, else by name, else by the nearest center; never to nothing", () => {
  const S = require("./sites.js");
  const R2 = require("./runner.js");
  const x = { hoods: [205, 848], hood_names: ["מרכז העיר", "נווה צדק"], centers: [[205, 32.0565, 34.7705], [848, 32.061, 34.765], [197, 32.113, 34.8]] };
  const rows = [{ id: "a", hood: 205 }, { id: "b", hood: 197 }, { id: "c", hood: null, hood_name: "נווה צדק" }];
  let f = R2.hoodFilter(x, rows, S);
  assert.deepEqual(rows.filter(f.keep).map((r) => r.id), ["a", "c"]);
  // no ids in the rows: by name, then by the nearest center
  const bare = [{ id: "a", hood_name: "מרכז העיר" }, { id: "b", hood_name: "רמת אביב" }, { id: "c", lat: 32.06, lng: 34.766 }, { id: "d", lat: 32.11, lng: 34.8 }, { id: "e" }];
  f = R2.hoodFilter(x, bare, S);
  assert.deepEqual(bare.filter(f.keep).map((r) => r.id), ["a", "c", "e"]); // e: nothing to tell by, kept
  assert.equal(f.unsure, false);
  // ids from another list (none match) and nothing else saved: all kept, and the search says so
  f = R2.hoodFilter({ hoods: [1, 2] }, [{ id: "a", hood: 7 }, { id: "b", hood: 8 }], S);
  assert.equal(f.unsure, true);
  assert.deepEqual([{ id: "a" }, { id: "b" }].filter(f.keep).length, 2);
  assert.equal(R2.hoodFilter({ hoods: [] }, rows, S).keep(rows[1]), true);
});

test("v1.34: photos: Yad2 and Madlan say none outright; Komo's none is 'not read'; an old cached row can't tell", () => {
  const R2 = require("./runner.js");
  assert.equal(R2.countPhotos({ photos: [] }, null), 0); // Yad2's feed: none
  assert.equal(R2.countPhotos({ source: "madlan", photos: [] }, null), 0);
  assert.equal(R2.countPhotos({ source: "komo", photos: [] }, null), null);
  assert.equal(R2.countPhotos({ source: "komo", photos: [] }, { source: "komo", photos: ["a", "b"] }), 2); // its gallery
  assert.equal(R2.countPhotos({ id: "x" }, { id: "x" }), null); // cached before v1.31
  assert.equal(R2.countPhotos({ photos: ["a"] }, { photos: [] }), 1);
});

test("v1.67: a search Yad2 serves on another site is named in the message and never fetched", async () => {
  const web = fakeWeb();
  const h = toyHelper();
  const call = async (path, body) => {
    if (path === "/config") {
      const r = await h.call(path, body);
      r.body.searches = [{ label: "Bat Yam", path: "/realestate/rent?city=6600" },
        { label: "Ma'ale Adumim", label_he: "מעלה אדומים", path: "/realestate/rent?city=3616", elsewhere: "yad-il.co.il" }];
      return r;
    }
    return h.call(path, body);
  };
  const seen = [];
  const fetch = async (url) => { seen.push(url); return web.fetch(url); };
  const realFetch = globalThis.fetch;
  globalThis.fetch = fetch;
  try {
    const s = await R.runPull({ call, P, cache: { listings: P.memoryCache(), routes: P.memoryCache() }, pullOpts: { ...FAST, fetch } });
    assert.equal(s.stage, "done");
    assert.ok(!seen.some((u) => /city=3616/.test(u)));
    assert.deepEqual(s.message, { key: "m_elsewhere", params: { x: "Ma'ale Adumim", site: "yad-il.co.il" } });
    assert.equal(s.shown, 6); // the other search ran as usual
  } finally {
    globalThis.fetch = realFetch;
  }
});
