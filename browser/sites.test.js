// node --test browser/   (also run from tests/test_browser_pull.py)
// Komo and Madlan pages (sites.js), on pages saved on Oct 22, 2026, and the pull's other-sites stage (runner.js).
"use strict";
const nodeTest = require("node:test");
const NO_SAMPLES = !require("node:fs").existsSync(require("node:path").join(__dirname, "..", "tests", "fixtures"));
// Tests that read the unpublished listing samples are skipped when they are missing (they contain third parties' contact details).
const test = (name, fn) => nodeTest(name, { timeout: 20000 }, async (t) => {
  try { return await fn(t); }
  catch (e) { if (NO_SAMPLES && /ENOENT[^\n]*fixtures|fixtures[^\n]*ENOENT/.test(String(e && e.message) + " " + String(e && e.path) + " " + String(e && e.code))) return t.skip("needs the local listing samples (not published)"); throw e; }
});
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const S = require("./sites.js");
const R = require("./runner.js");

const FX = path.join(__dirname, "..", "tests", "fixtures", "sites_2026-10-22");
const page = (f) => fs.readFileSync(path.join(FX, f), "utf8");

// ---- Komo --------------------------------------------------------------------------------

test("Komo's results page: every listing once, its facts, and no price when Komo shows 0", () => {
  const { rows, total } = S.komoRows(page("komo_search_batyam.html"));
  assert.equal(total, 161);
  assert.equal(rows.length, 21);
  assert.equal(new Set(rows.map((r) => r.id)).size, 21);
  const r = rows.find((x) => x.id === "komo:4943744");
  assert.deepEqual(
    { price: r.price, rooms: r.rooms, size: r.size_m2, floor: r.floor, city: r.city, hood: r.hood_name, street: r.street, url: r.url },
    { price: 4950, rooms: 3, size: 80, floor: 1, city: "בת ים", hood: "אגרובנק", street: "אליהו קראוזה",
      url: "https://www.komo.co.il/code/nadlan/details/?modaaNum=4943744" });
  assert.equal(r.lat, null); // Komo gives no pin
  assert.equal(rows.find((x) => x.id === "komo:4930130").price, null);
  assert.equal(rows.find((x) => x.id === "komo:4943180").street, null); // "לא צוין": not given
});

test("Komo: a title with no neighborhood keeps its street as a street", () => {
  const html = `<div class="contant"><a href="/code/nadlan/details/?modaaNum=77">x</a><h2 class="title">תל אביב יפו, אפטר יעקב 6</h2>
    <div class="price">5,000&nbsp;&#8362;</div><div class="description">דירה 2.0 חדרים (50 מ&quot;ר)<br>קומה:קרקע מתוך 3<div class="mFooterAction"></div></div></div>`;
  const [r] = S.komoRows(html).rows;
  assert.deepEqual([r.city, r.hood_name, r.street, r.floor, r.size_m2], ["תל אביב יפו", null, "אפטר יעקב 6", 0, 50]);
});

test("Komo's listing page: the ticked features, the numbers, the text without phone numbers", () => {
  const x = S.komoItem(page("komo_item_4943180.html"), "4943180", { price: 5400, lat: 32.02, lng: 34.77, approx: true });
  assert.equal(x.id, "komo:4943180");
  assert.deepEqual([x.price, x.rooms, x.floor, x.size_m2, x.floors, x.parking, x.arnona], [5400, 4, 1, 75, 3, 1, 1000]);
  assert.deepEqual([x.city, x.neighborhood, x.condition, x.entry], ["בת ים", "שכונה לדוגמה", "במצב טוב", "01/11/2026"]);
  assert.equal(x.ticked.elevator, true);
  assert.equal(x.ticked.mamad, false); // shown but not ticked: unknown, not a no (the adapter reads it so)
  assert.equal(x.ticked.pets_allowed, true);
  assert.equal(x.ticked.storage, false);
  assert.match(x.description, /^להשכרה לטווח ארוך/);
  assert.ok(!/הסבר על הריהוט/.test(x.description));
  assert.equal(x.approx, true); // the pin came from the neighborhood, never from Komo
  assert.equal(S.komoItem("<html>not a listing</html>", "1", null), null);
});

test("phone numbers are taken out of any text we keep", () => {
  assert.equal(S.scrub("call 050-1234567 or 03 1234567, +972 52 123 4567"), "call [phone] or [phone], [phone]");
  assert.equal(S.scrub("4 rooms, 75 m2, 1/11/2026"), "4 rooms, 75 m2, 1/11/2026");
});

test("v1.31 photos: Komo's row photo, its listing's gallery (not the similar listings'), Madlan's without floor plans", () => {
  const { rows } = S.komoRows(page("komo_search_batyam.html"));
  assert.ok(rows.every((r) => r.photos.length === 1));
  assert.equal(new Set(rows.map((r) => r.photos[0])).size, rows.length); // each its own
  assert.deepEqual(rows.find((x) => x.id === "komo:4943744").photos,
    ["https://www.komo.co.il/api/modaot/tmunot/showPic/list/?picNum=33680664&luachNum=2"]);
  // a box with no photo doesn't take the next box's
  const two = `<div id="modaaRowDv1"></div><div class="contant"><a href="/code/nadlan/details/?modaaNum=1">x</a></div>
    <div id="modaaRowDv2"><img src="/api/modaot/tmunot/showPic/list/?picSize=s&amp;picNum=9"></div><div class="contant"><a href="/code/nadlan/details/?modaaNum=2">y</a></div>`;
  assert.deepEqual(S.komoRows(two).rows.map((r) => r.photos.length), [0, 1]);
  const pic = (n) => `<img src="/api/modaot/tmunot/showPic/list/?picNum=${n}&luachNum=2">`;
  const item = page("komo_item_4943180.html").replace("מודעות דומות", `${pic(11)}${pic(12)}${pic(11)}מודעות דומות${pic(99)}`);
  const g = S.komoItem(item, "4943180", { photos: ["row"] });
  assert.deepEqual(g.photos.map((u) => /picNum=(\d+)/.exec(u)[1]), ["11", "12"]);
  assert.deepEqual(S.komoItem(page("komo_item_4943180.html"), "4943180", { photos: ["row"] }).photos, ["row"]); // no gallery: the row's
  const m = S.madlanRows(page("madlan_search_batyam.html")).rows;
  assert.equal(m[0].photos.length, 3);
  assert.ok(m[0].photos.every((u) => u.startsWith("https://images2.madlan.co.il/t:nonce:v=2;resize:width=640/bulletins/")));
});

test("v1.31 photos: the cards show what the readers make, and nothing else", () => {
  const C = require("./cards.js");
  const made = [].concat(...S.komoRows(page("komo_search_batyam.html")).rows.map((r) => r.photos),
    ...S.madlanRows(page("madlan_search_batyam.html")).rows.map((r) => r.photos), ["https://img.yad2.co.il/Pic/202610/22/2_1/o/x.jpeg"]);
  assert.deepEqual(C.safePhotos(made), made.slice(0, 20));
  const bad = ["http://img.yad2.co.il/Pic/a.jpeg", "https://img.yad2.co.il.evil.io/Pic/a.jpeg", "javascript:alert(1)", "data:image/png;base64,AA",
    "https://www.komo.co.il/api/modaot/tmunot/showPic/list/?picNum=1&luachNum=2&x=\"", "https://images2.madlan.co.il/t:nonce:v=2;resize:width=640/bulletins/a b.jpg", 7, null];
  assert.deepEqual(C.safePhotos(bad), []);
  assert.equal(C.safePhotos(Array(30).fill(made[0])).length, 20);
  assert.deepEqual(C.safePhotos("https://img.yad2.co.il/Pic/a.jpeg"), []); // a list only
});

// ---- Madlan ------------------------------------------------------------------------------

test("Madlan's results page: the rentals in its server data (not new projects), with pins", () => {
  const { rows, total } = S.madlanRows(page("madlan_search_batyam.html")); // has a bare `undefined`, as Madlan's pages do
  assert.equal(total, 258);
  assert.deepEqual(rows.map((r) => r.id), ["madlan:LhvqWyJ8NMq", "madlan:ZJTkE9wTVBE", "madlan:jC721dhbyHL", "madlan:TCQQpzwstTa",
    "madlan:Glkst6d0Syk"]);
  const r = rows[2];
  assert.deepEqual([r.price, r.rooms, r.size_m2, r.floor, r.city, r.hood_name, r.street, r.adType],
    [5400, 4, 80, 1, "בת ים", "שכונה לדוגמה", "י\"א באדר 24", "commercial"]);
  assert.ok(Math.abs(r.lat - 32.0224) < 1e-3 && Math.abs(r.lng - 34.7682) < 1e-3);
  assert.equal(rows[0].property, "דירת גג");
  assert.equal(rows[3].property, "פנטהאוז"); // penthouseapp
  assert.equal(S.madlanRows("<html>a bot check</html>"), null);
});

test("Madlan's listing page (its shape, built here): amenities, condition, text; no contact details", () => {
  const p = { id: "abc", type: "bulletin", dealType: "unitRent", price: 6000, beds: 3, area: 70, floor: "2", floors: 4,
    locationPoint: { lat: 32.01, lng: 34.77 }, addressDetails: { city: "בת ים", neighbourhood: "שכונה לדוגמה", streetName: "הרצל", streetNumber: "5" },
    amenities: { elevator: true, parking: false, secureRoom: true, note: "x" }, generalCondition: "renovated", availabilityType: "immediate",
    description: "דירה מקסימה, לפרטים 054-1234567", poc: { type: "private", phone: "0541234567", name: "someone" } };
  const html = `<script>window.__SSR_HYDRATED_CONTEXT__=${JSON.stringify({ reduxInitialState: { domainData: { bulletinsByIds: { data: { poiByIds: [p] } } } } })};</script>`;
  const x = S.madlanItem(html);
  assert.equal(x.id, "madlan:abc");
  assert.deepEqual(x.amenities, { elevator: true, parking: false, secureRoom: true });
  assert.deepEqual([x.floor, x.floors, x.condition, x.availability, x.adType], [2, 4, "renovated", "immediate", "private"]);
  assert.equal(x.description, "דירה מקסימה, לפרטים [phone]");
  assert.ok(!JSON.stringify(x).includes("someone") && !JSON.stringify(x).includes("0541234567"));
});

test("readPage: which page of which site, and nothing from any other page", () => {
  assert.equal(S.readPage("https://www.komo.co.il/code/nadlan/apartments-for-rent.asp?nehes=1&cityName=x", page("komo_search_batyam.html")).rows.length, 21);
  assert.equal(S.readPage("https://www.komo.co.il/code/nadlan/details/?modaaNum=4943180", page("komo_item_4943180.html")).item.id, "komo:4943180");
  assert.equal(S.readPage("https://www.madlan.co.il/for-rent/בת ים-ישראל", page("madlan_search_batyam.html")).rows.length, 5);
  assert.equal(S.readPage("https://www.madlan.co.il/listings/x", "<html>Madlan's bot check</html>"), null);
  assert.equal(S.readPage("https://evil.example/code/nadlan/details/?modaaNum=1", page("komo_item_4943180.html")), null);
});

// ---- places --------------------------------------------------------------------------------

test("neighborhood names compare loosely, and a pinless listing goes to its neighborhood's middle", () => {
  assert.ok(S.sameHood("שכונת התקווה", "התקווה"));
  assert.ok(S.sameHood("נווה-שאנן", "נווה שאנן"));
  assert.ok(S.sameHood("הצפון הישן", "הצפון הישן - החלק הצפוני"));
  assert.ok(!S.sameHood("נווה צדק", "נווה שאנן"));
  const yad2 = [{ city: "בת ים", hood_name: "שכונה לדוגמה", lat: 32.02, lng: 34.76 }, { city: "בת ים", hood_name: "שכונה לדוגמה", lat: 32.04, lng: 34.78 },
    { city: "בת ים", hood_name: "אגרובנק", lat: 32.03, lng: 34.77 }]; // one pin isn't a middle
  const c = S.hoodCentroids(yad2);
  assert.deepEqual(c, { "בת ים|שכונה לדוגמה": [32.03, 34.77] });
  const placed = S.placeApprox({ id: "komo:1", city: "בת ים", hood_name: "שכונה לדוגמה", lat: null, lng: null }, c);
  assert.deepEqual([placed.lat, placed.lng, placed.approx], [32.03, 34.77, true]);
  assert.equal(S.placeApprox({ id: "komo:2", city: "בת ים", hood_name: "אגרובנק", lat: null }, c).lat, null);
});

// ---- Komo, fetched -------------------------------------------------------------------------

function fakeKomo(opts = {}) {
  const log = [];
  const get = async (url) => {
    log.push(url);
    if (opts.wall) return { status: 200, url: "https://account.komo.co.il/login", text: "<html>sign in</html>" };
    if (url.includes("apartments-for-rent")) return { status: 200, url, text: page("komo_search_batyam.html") };
    const n = /modaaNum=(\d+)/.exec(url)[1];
    if (opts.pushbackAt && log.length === opts.pushbackAt) return { status: 429, url, text: "" };
    if (n === opts.gone) return { status: 404, url, text: "" };
    return { status: 200, url, text: page("komo_item_4943180.html").replace(/4943180/g, n) };
  };
  return { get, log };
}

test("komoSearch: the first page; a sign-in page or a pushback says so", async () => {
  const k = await S.komoSearch("בת ים", 5450, fakeKomo().get);
  assert.equal(k.rows.length, 21);
  assert.equal(S.komoSearchUrl("בת ים", 5450.5), "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp?nehes=1&cityName=%D7%97%D7%95%D7%9C%D7%95%D7%9F&toPrice=5450");
  assert.equal((await S.komoSearch("בת ים", 0, fakeKomo({ wall: true }).get)).wall, true);
  assert.equal((await S.komoSearch("בת ים", 0, async (u) => ({ status: 403, url: u, text: "" }))).pushback, true);
});

test("komoItems: one at a time with a gap, cached ones free, the first pushback stops the rest", async () => {
  let clock = 0;
  const waits = [];
  const sleep = async (ms) => { waits.push(ms); clock += ms; };
  const now = () => clock;
  const store = new Map([["komo:1", { fp: "f1", fetchedAt: 0, extract: { id: "komo:1", cached: true } }]]);
  const cache = { get: async (k) => store.get(k) || null, set: async (k, v) => { store.set(k, v); } };
  const rows = { "komo:1": { fp: "f1" }, "komo:2": { fp: "f2" }, "komo:3": { fp: "f3" }, "komo:4": { fp: "f4" }, "komo:5": { fp: "f5" } };
  const got = {};
  const web = fakeKomo({ gone: "3", pushbackAt: 3 });
  const st = await S.komoItems(["komo:1", "komo:2", "komo:3", "komo:4", "komo:5"],
    { get: web.get, rows, gapMs: 1500, cache, now, sleep, onResult: (id, r) => { got[id] = r.status + (r.fromCache ? "/cache" : ""); } });
  assert.deepEqual(got, { "komo:1": "ok/cache", "komo:2": "ok", "komo:3": "removed", "komo:4": "stopped", "komo:5": "stopped" });
  assert.equal(st.stoppedBecause, "komo_pushback");
  assert.equal(st.requests, 3);
  assert.deepEqual(waits, [1500, 1500]); // between requests, not before the first
  assert.equal(store.get("komo:2").extract.price, 5400);
});

// ---- the pull's other-sites stage ------------------------------------------------------------

function fakeYad2() {
  const rows = [
    { id: "Y1", price: 4500, rooms: 3, size_m2: 70, floor: 2, city: "בת ים", hood: 1, hood_name: "שכונה לדוגמה", lat: 32.02, lng: 34.76, fp: "a" },
    { id: "Y2", price: 4950, rooms: 3, size_m2: 80, floor: 1, city: "בת ים", hood: 2, hood_name: "אגרובנק", lat: 32.03, lng: 34.77, fp: "b" },
    { id: "Y3", price: 4700, rooms: 3, size_m2: 75, floor: 3, city: "בת ים", hood: 2, hood_name: "אגרובנק", lat: 32.031, lng: 34.7749, fp: "c" },
  ];
  return {
    ITEM_URL: (id) => `https://www.yad2.co.il/realestate/item/${id}`,
    searchRows: async () => ({ rows, stats: { seen: rows.length, pages: 1, requests: 1, failedPages: [] } }),
    routeTable: async () => ({ routes: {}, stats: { errors: [] } }),
    fetchItems: async (ids, o) => {
      for (const id of ids) o.onResult(id, { status: "ok", extract: { id, coords: { lat: 32, lon: 34.7 } }, fetchedAt: 1, fromCache: false });
      return { stats: { requests: ids.length, stoppedBecause: null } };
    },
  };
}

function helper(also) {
  const calls = [];
  const call = async (p, body) => {
    calls.push([p, body]);
    if (p === "/config") return { ok: true, body: { search_filters: { maxPrice: "5450" }, commutes: [], tomtom: false,
      searches: [{ label: "Bat Yam", label_he: "בת ים", path: "/realestate/rent?city=6600" }], prefs: {} } };
    if (p === "/plan") return { ok: true, body: { rows: body.rows.length, fetch: body.rows.map((r) => r.id).filter((id) => /^(Y|komo:4943|madlan:)/.test(id)),
      later: [], skipped: {}, skipped_by_reason: {}, also: also || {} } };
    if (p === "/score") return { ok: true, body: { results: body.extracts.map((x) => ({ id: x.id, excluded: false })), shown: body.extracts.length, hidden: 0 } };
    return { ok: false, status: 404, body: {} };
  };
  return { call, calls };
}

test("a pull adds Komo's first page for the same city, the user's own Madlan finds, and links the same apartment", async () => {
  const web = fakeKomo();
  const h = helper({ Y2: [{ source: "komo", name: "Komo", id: "komo:4943744", url: "https://www.komo.co.il/code/nadlan/details/?modaaNum=4943744" }] });
  const madlan = { id: "madlan:m1", source: "madlan", url: "https://www.madlan.co.il/listings/m1", price: 4000, rooms: 3, city: "בת ים",
    hood_name: "שכונה לדוגמה", lat: 32.02, lng: 34.76, fp: "m", seenAt: 1000 };
  const far = Object.assign({}, madlan, { id: "madlan:m2", city: "בת ים" }); // another city: not this search's
  const s = await R.runPull({
    P: fakeYad2(), call: h.call, S, siteGet: web.get, siteGapMs: 0, now: () => 2000, sleep: async () => {}, suggest: false,
    pool: { rows: { [madlan.id]: madlan, [far.id]: far }, items: { "madlan:m1": { extract: Object.assign({}, madlan, { amenities: { elevator: true } }), seenAt: 1000 } } },
  });
  assert.equal(s.error, null);
  assert.equal(web.log.filter((u) => u.includes("apartments-for-rent")).length, 1); // Bat Yam, once
  assert.match(web.log[0], /cityName=%D7%97%D7%95%D7%9C%D7%95%D7%9F&toPrice=5450/);
  const planned = h.calls.find((c) => c[0] === "/plan")[1].rows;
  assert.equal(planned.filter((r) => r.source === "komo").length, 21);
  assert.ok(planned.some((r) => r.id === "madlan:m1"));
  assert.ok(!planned.some((r) => r.id === "madlan:m2"));
  // a Komo listing in a neighborhood Yad2 knows two pins in sits at their middle, marked approximate
  const agro = planned.find((r) => r.id === "komo:4943744");
  assert.deepEqual([agro.lat, agro.lng, agro.approx], [32.0305, 34.7705, true]);
  // Madlan isn't fetched: the page the user opened is the extract
  const scored = h.calls.filter((c) => c[0] === "/score").pop()[1].extracts;
  assert.deepEqual(scored.find((x) => x.id === "madlan:m1").amenities, { elevator: true });
  assert.ok(web.log.every((u) => u.startsWith("https://www.komo.co.il/")));
  assert.ok(web.log.some((u) => /modaaNum=4943180/.test(u)));
  assert.deepEqual(s.results.find((x) => x.id === "Y2").also.map((a) => a.source), ["komo"]);
  assert.deepEqual(s.bySource, { yad2: 3, komo: 21, madlan: 1, facebook: 0 });
});

test("a pull with Komo and Madlan turned off reads Yad2 only", async () => {
  const web = fakeKomo();
  const h = helper();
  const s = await R.runPull({ P: fakeYad2(), call: h.call, S, siteGet: web.get, siteGapMs: 0, sleep: async () => {}, suggest: false,
    sources: { komo: false, madlan: false }, pool: { rows: { "madlan:m1": { id: "madlan:m1", source: "madlan", city: "בת ים", seenAt: Date.now() } }, items: {} } });
  assert.equal(s.error, null);
  assert.equal(web.log.length, 0);
  assert.ok(h.calls.find((c) => c[0] === "/plan")[1].rows.every((r) => !r.source));
});

test("Komo asking to sign in stops Komo, not the pull", async () => {
  const h = helper();
  const s = await R.runPull({ P: fakeYad2(), call: h.call, S, siteGet: fakeKomo({ wall: true }).get, siteGapMs: 0, sleep: async () => {}, suggest: false });
  assert.equal(s.error, null);
  assert.equal(s.sites.komo.stopped, "komo_wall");
  assert.deepEqual(s.message, { key: "m_komo_wall" });
  assert.equal(s.results.length, 3);
});

// ---- the card's big button: the cheapest copy (cards.js) ------------------------------------

test("the place opens the cheapest copy: Yad2 unless another site asks less", () => {
  const C = require("./cards.js");
  const yad2 = "https://www.yad2.co.il/realestate/item/abc123";
  const komo = "https://www.komo.co.il/code/nadlan/details/?modaaNum=4943744";
  const madlan = "https://www.madlan.co.il/listings/Xy1";
  const go = (x) => C.bestOffer(x).best.url;
  assert.equal(go({ source: "yad2", url: yad2, price: 5000, also: [{ source: "komo", url: komo, price: 4800 }] }), komo);
  assert.equal(go({ source: "yad2", url: yad2, price: 5000, also: [{ source: "komo", url: komo, price: 5000 }] }), yad2); // a tie: Yad2
  assert.equal(go({ source: "madlan", url: madlan, price: 5000, also: [{ source: "komo", url: komo, price: 5000 }] }), madlan); // its own
  assert.equal(go({ source: "yad2", url: yad2, price: 5000, also: [{ source: "komo", url: komo, price: null }] }), yad2); // no rent: not cheaper
  assert.equal(go({ source: "yad2", url: yad2, price: 5000, also: [{ source: "komo", url: "https://evil.example/x", price: 1 }] }), yad2);
  assert.equal(C.bestOffer({ source: "yad2", url: "javascript:alert(1)", price: 1 }).best, null);
});

test("v1.38: a second post on the same site is a link too, and the cheaper post opens", () => {
  const C = require("./cards.js");
  const a = "https://www.yad2.co.il/realestate/item/a1";
  const b = "https://www.yad2.co.il/realestate/item/b2";
  const { offers, best } = C.bestOffer({ source: "yad2", url: a, price: 4300, also: [{ source: "yad2", url: b, price: 4200, same_site: true }] });
  assert.equal(offers.length, 2);
  assert.equal(best.url, b);
});

test("v1.38: a trip saved before v1.37 gets its minutes from its evidence, not a dash", () => {
  const C = require("./cards.js");
  assert.deepEqual(C.timesFrom("drive to HIT: traffic not checked; roughly 20-31 min in typical traffic, 32-44 at rush hour (an estimate)"),
    { usual: 26, worst: 44, estimate: true });
  assert.deepEqual(C.timesFrom("drive to HIT: about 24 min in typical traffic, 41 min at rush hour; an estimate"), { usual: 24, worst: 41, estimate: false });
  assert.deepEqual(C.timesFrom("not routed; estimate from the map: about 18.5 min (ebike)"), { about: 18.5 });
  assert.deepEqual(C.timesFrom(undefined), {});
});

// ---- v1.30: a good deal ---------------------------------------------------------------------

test("a good deal: 12% under the usual rent for the same rooms in the same neighborhood, else the city", () => {
  const row = (id, price, hood, rooms = 3, city = "בת ים") => ({ id, price, rooms, city, hood_name: hood });
  const agro = [4800, 5000, 5000, 5100, 5200].map((p, i) => row(`a${i}`, p, "אגרובנק"));
  const deals = R.dealsOf([...agro, row("cheap", 4300, "אגרובנק"), row("fair", 4700, "אגרובנק"), row("other", 4300, "שכונה לדוגמה", 4)]);
  assert.deepEqual(Object.keys(deals), ["cheap"]); // 4300 vs a median of 5000; 4700 is only 6% under; "other" has no peers
  assert.deepEqual(deals.cheap, { median: 5000, n: 7, scope: "hood", rooms: 3, place: "אגרובנק" });
  // too few in the neighborhood: the city decides, with at least 9
  const city = [5000, 5100, 4900, 5200, 5000, 5300, 4800, 5050].map((p, i) => row(`c${i}`, p, `h${i}`));
  const d2 = R.dealsOf([...city, row("x", 4200, "גבעת בת ים")]);
  assert.equal(d2.x.scope, "city");
  assert.equal(R.dealsOf([row("y", 0, "x"), { id: "z", price: 3000 }]).y, undefined); // no rent, no rooms: never a deal
});

test("v1.30: the search gets the budget's low end too, the higher of the two minimums", () => {
  assert.equal(R.withFilters("/realestate/rent?city=6600", { maxPrice: "5450", minPrice: "3000" }), "/realestate/rent?city=6600&maxPrice=5450&minPrice=3000");
  assert.equal(R.withFilters("/realestate/rent?city=6600&minPrice=3500", { minPrice: "3000" }), "/realestate/rent?city=6600&minPrice=3500");
  assert.equal(R.withFilters("/realestate/rent?city=6600&minPrice=2000", { minPrice: "3000" }), "/realestate/rent?city=6600&minPrice=3000");
});

// ---- v1.40: listings with no photos, and "Missing a listing?" --------------------------------

test("v1.40: no photos means Yad2 or Madlan sent none; Komo's unread photos don't count", () => {
  const C = require("./cards.js");
  const pic = "https://img.yad2.co.il/Pic/202610/22/2_1/o/x.jpeg";
  assert.equal(C.photoless({ source: "yad2", photos: [] }), true);
  assert.equal(C.photoless({ photos: undefined }), true); // Yad2 by default
  assert.equal(C.photoless({ source: "yad2", photos: [pic] }), false);
  assert.equal(C.photoless({ source: "yad2", photos: ["javascript:alert(1)"] }), true); // nothing it can show
  assert.equal(C.photoless({ source: "komo", photos: [], photos_state: "unread" }), false);
  assert.equal(C.photoless({ source: "komo", photos: [], photos_state: "none" }), true);
  assert.equal(C.photoless({ source: "madlan", photos: [] }), true);
  assert.equal(C.hidesPhotoless({}), true); // on by default
  assert.equal(C.hidesPhotoless(undefined), true);
  assert.equal(C.hidesPhotoless({ hideNoPhotos: false }), false);
});

test("v1.40: \"Missing a listing?\" says what the last search did with it", () => {
  const kept = {
    finishedAt: 5,
    results: [{ id: "aaaaaaa1" }, { id: "bbbbbbb2", excluded: true, reasons: ["Rooms: 1 is past the limit of 2"] }],
    merged: { ccccccc3: "aaaaaaa1" },
    skippedRows: { ddddddd4: ["E-bike time to Work (min): 17 is past the limit of 15"] },
    skippedInfo: { ddddddd4: { id: "ddddddd4", price: 4800, hood: "רמת הטייסים" } },
    notOpened: [{ id: "eeeeeee5" }],
    outside: { fffffff6: "שפירא" },
    searches: [{ label: "Tel Aviv", total: 1200, seen: 1200, kept: 400 }],
  };
  const ask = (x) => R.explain(x, kept, { ggggggg7: { status: "rejected" } });
  assert.deepEqual(ask("https://www.yad2.co.il/realestate/item/aaaaaaa1"), { kind: "shown", id: "aaaaaaa1", rank: 1 });
  assert.equal(ask("bbbbbbb2").kind, "hidden");
  assert.deepEqual(ask("ccccccc3"), { kind: "merged", id: "ccccccc3", into: "aaaaaaa1" });
  const sk = ask("https://www.yad2.co.il/realestate/item/tel-aviv-area/ddddddd4?opened-from=feed");
  assert.equal(sk.kind, "skipped");
  assert.match(sk.reasons[0], /E-bike/);
  assert.equal(sk.row.hood, "רמת הטייסים");
  assert.equal(ask("eeeeeee5").kind, "unread");
  assert.deepEqual(ask("fffffff6"), { kind: "outside", id: "fffffff6", hood: "שפירא" });
  assert.equal(ask("ggggggg7").kind, "rejected");
  const un = ask("hhhhhhh8");
  assert.equal(un.kind, "unseen");
  assert.deepEqual(un.searches[0], { label: "Tel Aviv", label_he: undefined, path: undefined, total: 1200, seen: 1200, kept: 400 });
  assert.equal(ask("not a link at all").kind, "bad_link");
  assert.equal(R.listingId("https://www.komo.co.il/code/nadlan/details/?modaaNum=4943744"), "komo:4943744");
});

// ---- v1.41: send listings to someone without the extension -----------------------------------

test("v1.41: the lists to send: each listing once, in the first list it's in, never a rejected one", () => {
  const Sh = require("./share.js");
  const xs = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d", excluded: true }, { id: "e" }];
  const marks = { a: { fav: true, status: "interested" }, b: { status: "viewing", viewingAt: "2026-10-30T18:00" }, c: { status: "viewing", viewingAt: "2026-10-28T10:00" },
    e: { status: "rejected" } };
  const got = Sh.pick(xs, marks, ["fav", "interested", "viewing", "all"]);
  assert.deepEqual(got.map((g) => [g.group, g.listings.map((x) => x.id)]), [["fav", ["a"]], ["viewing", ["c", "b"]]]); // soonest viewing first
  assert.deepEqual(Sh.pick(xs, marks, ["all"]).map((g) => g.listings.map((x) => x.id)), [["a", "b", "c"]]); // not hidden, not rejected
});

test("v1.41: the page and the text carry the cards' facts, escaped, with safe links and photos only", async () => {
  const Sh = require("./share.js");
  const C = require("./cards.js");
  const I = require("./i18n.js");
  I.setLang("en");
  const x = { id: "abc123xy", source: "yad2", url: "https://www.yad2.co.il/realestate/item/abc123xy", price: 4800, rooms: 2.5, size_m2: 60, floor: 2,
    street: "<script>alert(1)</script>", neighborhood: "יד אליהו", city: "תל אביב יפו",
    photos: ["https://img.yad2.co.il/Pic/202610/22/2_1/o/x.jpeg", "javascript:alert(1)"],
    trips: [{ signal: "bike_minutes", place: "Work", mode: "ebike", minutes: 12 }],
    feature_keys: [{ key: "balcony", tone: "good" }, { key: "no_elevator", tone: "bad" }] };
  const bad = { id: "zzzzzzz1", source: "yad2", url: "https://evil.example/x", price: 4000, photos: [] };
  const groups = [{ group: "fav", listings: [x, bad] }];
  // v1.46: html() fetches photos to embed them; a fetch that always fails (no
  // network here) falls back to the remote address, exactly like before.
  const offline = async () => { throw new Error("offline (test)"); };
  const ctx = { I, C, marks: { abc123xy: { fav: true } }, title: "For Noa", at: Date.parse("2026-10-27T10:00:00Z"), fetch: offline };
  const page = await Sh.html(groups, ctx);
  assert.ok(page.startsWith("<!doctype html>"));
  assert.ok(!page.includes("<script"), "no scripts, and listing text is escaped");
  assert.ok(page.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(page.includes('src="https://img.yad2.co.il/Pic/202610/22/2_1/o/x.jpeg"'));
  assert.ok(!page.includes("javascript:"));
  assert.ok(page.includes('href="https://www.yad2.co.il/realestate/item/abc123xy"'));
  assert.ok(!page.includes("evil.example"));
  assert.ok(page.includes("For Noa") && page.includes("₪4,800") && page.includes("12 min"));
  assert.ok(page.includes("Balcony") && !page.includes("No elevator")); // the good tags only
  const txt = Sh.text(groups, ctx);
  assert.match(txt, /^For Noa\n\n\*★ Favorites\* \(2\)/);
  assert.ok(txt.includes("• ₪4,800 · 2.5 rooms · 60 m² · floor 2"));
  assert.ok(txt.includes("https://www.yad2.co.il/realestate/item/abc123xy") && !txt.includes("evil.example"));
  I.setLang("he");
  assert.ok((await Sh.html(groups, ctx)).includes('dir="rtl"'));
  I.setLang("en");
});

test("v1.62: Komo's typographic codes are decoded (Komo batch 1: \"&rsquo;\")", () => {
  const S = require("./sites.js");
  assert.equal(S.decode("שכונה א&rsquo; &ndash; קרוב&hellip; &#x5D0;"), "שכונה א’ – קרוב… א");
});

test("v1.66: a Facebook post the user selected becomes an extract; nothing else is taken", () => {
  const S = require("./sites.js");
  const text = "להשכרה במרכז העיר! דירת 3 חדרים, 70 מ\"ר, קומה 2 עם מעלית\nמחיר: 5,200 ש\"ח לחודש + ועד בית 150\nלפרטים 050-1234567 דני";
  const x = S.facebookPost({ text, url: "https://www.facebook.com/groups/123456/posts/987654321/?comment_id=1" });
  assert.equal(x.id, "facebook:987654321");
  assert.equal(x.url, "https://www.facebook.com/groups/123456/posts/987654321");
  assert.deepEqual([x.price, x.rooms, x.size_m2, x.floor], [5200, 3, 70, 2]);  // the rent, not the building fee
  assert.ok(!/050/.test(x.description) && /\[phone\]/.test(x.description));
  assert.equal(S.facebookPost({ text: "מוסר ספה", url: "https://www.facebook.com/groups/1/posts/2" }), null);  // too short to be a post
  const m = S.facebookPost({ text: "יחידת דיור 2 חדרים להשכרה, קומת קרקע, 3800 שח כולל ארנונה", url: "https://www.facebook.com/marketplace/item/555/" });
  assert.deepEqual([m.id, m.url, m.price, m.floor], ["facebook:555", "https://www.facebook.com/marketplace/item/555", 3800, 0]);
  const feed = S.facebookPost({ text: "דירה להשכרה ברמת השרון 4 חדרים 6500 ₪ פנויה מיד", url: "https://www.facebook.com/" });
  assert.match(feed.id, /^facebook:[0-9a-z]+$/);  // not one post's page: an id from the text, and no link
  assert.equal(feed.url, null);
  assert.equal(S.facebookPost({ text: "דירה למכירה 4 חדרים במחיר 2,450,000 ₪ במרכז העיר", url: "" }).price, null);  // a sale price isn't a rent
});

test("v1.68: a Madlan balcony or storage room listed only in its areas is counted", () => {
  const p = { id: "abc", type: "bulletin", dealType: "unitRent", price: 4500, beds: 3, addressDetails: { city: "חיפה" },
    amenities: { balcony: null, storage: null, elevator: true, additionalAreas: { balconyAreas: [20], warehouseAreas: [null], gardenAreas: [], balconiesArea: null, storeroomArea: null } } };
  const ctx = { reduxInitialState: { domainData: { bulletinsByIds: { data: { poiByIds: [p] } } } } };
  const x = S.madlanItem(`<script>window.__SSR_HYDRATED_CONTEXT__=${JSON.stringify(ctx)}</script>`);
  assert.deepEqual(x.areas, { balcony: 1, storage: 1, garden: 0 }); // a storage room with no size still counts
  assert.equal(x.amenities.elevator, true);
  assert.equal("additionalAreas" in x.amenities, false);
});
