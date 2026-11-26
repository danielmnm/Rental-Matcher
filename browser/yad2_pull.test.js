// node --test browser/   (also run from tests/test_browser_pull.py)
"use strict";
const nodeTest = require("node:test");
const NO_SAMPLES = !require("node:fs").existsSync(require("node:path").join(__dirname, "..", "tests", "fixtures"));
// Tests that read the unpublished listing samples are skipped when they are missing (they contain third parties' contact details).
const test = (name, fn) => nodeTest(name, { timeout: 20000 }, async (t) => {
  try { return await fn(t); }
  catch (e) { if (NO_SAMPLES && /ENOENT[^\n]*fixtures|fixtures[^\n]*ENOENT/.test(String(e && e.message) + " " + String(e && e.path) + " " + String(e && e.code))) return t.skip("needs the local listing samples (not published)"); throw e; }
}); // a pull that never ends is a failure
const assert = require("node:assert/strict");
const P = require("./yad2_pull.js");

const FAST = { minGapMs: 2, slowGapMs: 6, backoffMs: 1, maxBlocks: 2 }; // maxBlocks 2: test the slow-down too

// ---- a fake Yad2 -------------------------------------------------------------

function item(id, over = {}) {
  return Object.assign(
    {
      token: id, adType: "private", price: 4200, statusId: 1,
      address: {
        city: { id: "6600", text: "בת ים" }, neighborhood: { id: 821, text: "תל גיבורים" }, street: { id: "1", text: "הפרדס" },
        house: { number: 30, floor: 2 }, coords: { lat: 32.03247, lon: 34.76512 },
      },
      additionalDetails: {
        roomsCount: 3, squareMeter: 60, squareMeterBuild: 62, buildingTopFloor: 4, entranceDate: "2026-11-01T00:00:00",
        property: { id: 1, text: "דירה" }, propertyCondition: { id: 2, text: "משופץ" }, propertyGroup: { id: 1 },
      },
      inProperty: { includeAirconditioner: true, includeSecurityRoom: false },
      dates: { createdAt: "2026-10-16T23:04:03", updatedAt: "2026-10-21T07:10:54" },
      metaData: { coverImage: "c.jpg", images: ["a.jpg"], description: `דירה ${id} עם ממ"ד. דני כהן 054-1234567` },
      customer: { name: "דני כהן", id: 77, isVirtualPhoneNumber: true },
      searchText: "דני כהן 054-1234567",
    },
    over
  );
}

function itemPage(id, data = item(id)) {
  const nd = { props: { pageProps: { dehydratedState: { queries: [{ queryKey: ["item", id], state: { data } }] } } } };
  return `<html><head><script id="__NEXT_DATA__" type="application/json">${JSON.stringify(nd)}</script></head></html>`;
}

function searchPage(items, totalPages, total) {
  const data = { private: items, agency: [], platinum: [], pagination: { total, totalPages } };
  const nd = { props: { pageProps: { dehydratedState: { queries: [{ queryKey: ["realestate", "rent-feed", {}], state: { data } }] } } } };
  return `<script id="__NEXT_DATA__" type="application/json">${JSON.stringify(nd)}</script>`;
}

/** fetch(url) -> handler(id or url) gives {status, body} or throws; records concurrency. */
function fakeFetch(handler, { delay = () => 1 } = {}) {
  const log = { inFlight: 0, maxInFlight: 0, calls: [], flight: [], at: [] };
  const fn = async (url) => {
    log.calls.push(url);
    log.inFlight++;
    log.flight.push(log.inFlight); // how many were in flight when this one started
    log.at.push(Date.now());
    log.maxInFlight = Math.max(log.maxInFlight, log.inFlight);
    try {
      await new Promise((r) => setTimeout(r, delay(url)));
      const id = decodeURIComponent(url.split("/item/")[1] || "");
      const { status = 200, body = "" } = await handler(id || url, url);
      return { status, url, text: async () => body };
    } finally {
      log.inFlight--;
    }
  };
  return { fn, log };
}

const ids = (n) => Array.from({ length: n }, (_, i) => `id${String(i).padStart(3, "0")}`);

// ---- privacy -----------------------------------------------------------------------

test("phone numbers and the poster's name are blanked, nothing else", () => {
  const cases = [
    ["call 054-1234567 now", "call [phone] now"],
    ["0541234567", "[phone]"],
    ["054 123 4567", "[phone]"],
    ["+972-54-1234567", "[phone]"],
    ["972541234567", "[phone]"],
    ["03-5551234", "[phone]"],
    ["wa.me/972541234567", "wa.me/[phone]"],
    ["אפס חמש שתיים אחת אחת שתיים שלוש ארבע חמש שש", "[phone]"],
    ["zero five four one two three four five six seven", "[phone]"],
    ["לפלאפון 050 מספר 5792223  ולציין", "לפלאפון [phone]  ולציין"],  // v1.53 (census, Oct 29)
    ["ווצאפ למס 052.6003707", "ווצאפ למס [phone]"],  // v1.57 (batch 11, Nov 2): dots between the digits
  ];
  for (const [a, b] of cases) assert.equal(P.scrub(a), b, a);
  // not phones: prices, dates, sizes, floors, a short count of words
  const keep = "מחיר 5,000 ש\"ח, כניסה 01-11-2026, כניסה 01.10.2026, 75 מ\"ר, קומה 3 מתוך 8, שלושה חדרים, 2 חניות, טל' בפרטי, חמש דקות מהים";
  assert.equal(P.scrub(keep), keep);
  assert.equal(P.scrub("לפנות לדני כהן בלבד", "דני כהן"), "לפנות ל[name] בלבד");
  assert.equal(P.scrub("רחוב הרצל", "הרצל כהן"), "רחוב הרצל"); // only the full name, never a part of it
  assert.equal(P.scrub("לפנות לדני  כהן", "דני כהן"), "לפנות ל[name]"); // however it's spaced
  // a one-word name is often a word: Oct 21, poster "אור" (light) in "plenty of natural light"
  assert.equal(P.scrub("משופצת עם שפע אור טבעי", "אור"), "משופצת עם שפע אור טבעי");
  assert.equal(P.scrub("דירה מוארת", "דירה"), "דירה מוארת");
  // control characters go, newlines stay
  assert.equal(P.scrub("רסקו ב\u0096 בת ים\nשורה", null), "רסקו ב  בת ים\nשורה");
  assert.equal(P.scrub(null), null);
});

test("an extract has the adapter's shape and no contact data", () => {
  const x = P.toExtract(item("ab12"), "ab12");
  assert.deepEqual(Object.keys(x), ["id", "adType", "price", "floor", "city", "neighborhood", "street", "coords",
    "additionalDetails", "inProperty", "dates", "description", "source_url"]);
  assert.deepEqual(x.additionalDetails, item("ab12").additionalDetails); // every structured fact, as Yad2 gave it
  assert.equal(x.floor, 2);
  assert.deepEqual(x.coords, { lat: 32.03247, lon: 34.76512 });
  assert.equal(x.description, 'דירה ab12 עם ממ"ד. [name] [phone]');
  const s = JSON.stringify(x);
  for (const bad of ["customer", "דני", "1234567", "searchText", "isVirtualPhoneNumber"]) assert.ok(!s.includes(bad), bad);
  // an empty field stays empty: floor unknown is null, never 0
  const bare = P.toExtract(item("z", { address: {}, additionalDetails: {}, metaData: {} }), "z");
  assert.equal(bare.floor, null);
  assert.equal(bare.coords, undefined);
  assert.equal(bare.description, null);
});

test("v1.53: Yad2's fee fields, the poster's furniture list and the shelter distance are kept", () => {
  const page = item("f1", { propertyTax: 900, houseCommittee: 250, furnitureInfo: "מקרר ומיטה, לפרטים 054-1234567",
    metaData: { description: "דירה", shelterDistance: 180 } });
  const x = P.toExtract(page, "f1");
  assert.equal(x.propertyTax, 900);
  assert.equal(x.houseCommittee, 250);
  assert.equal(x.furnitureInfo, "מקרר ומיטה, לפרטים [phone]"); // scrubbed like the description
  assert.equal(x.shelterDistance, 180);
  // an empty or zero field isn't a fact
  const bare = P.toExtract(item("f2", { propertyTax: 0, furnitureInfo: "  ", metaData: {} }), "f2");
  for (const k of ["propertyTax", "houseCommittee", "furnitureInfo", "shelterDistance"]) assert.ok(!(k in bare), k);
});

test("the browser extract keeps every fact the saved extracts have (1661 real listings)", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const root = path.join(__dirname, "..", "tests", "fixtures");
  let n = 0;
  for (const dir of fs.readdirSync(root).filter((d) => d.startsWith("yad2") && !d.includes("search") && !d.includes("reread"))) {
    for (const f of fs.readdirSync(path.join(root, dir)).filter((f) => f.endsWith(".json") && !f.startsWith("routes"))) {
      const data = JSON.parse(fs.readFileSync(path.join(root, dir, f), "utf8"));
      for (const x of Array.isArray(data) ? data : [data]) {
        if (!x || !x.additionalDetails || !x.inProperty) continue;
        // the item page those facts came from, as Yad2 serves it
        const page = { token: x.id, adType: x.adType, price: x.price, additionalDetails: x.additionalDetails, inProperty: x.inProperty,
          address: { house: { floor: x.floor }, coords: x.coords }, metaData: {}, dates: x.dates };
        const got = P.toExtract(page, x.id);
        assert.deepEqual(got.additionalDetails, x.additionalDetails, `${dir}/${f}`);
        assert.deepEqual(got.inProperty, x.inProperty, `${dir}/${f}`);
        n++;
      }
    }
  }
  assert.equal(n, 1661); // every saved extract that has Yad2's structured block (161, + batch 9's 147 on Oct 29, + batch 10's 261 on Oct 30, + batch 11's 263 on Nov 2, + batch 12's 277 on Nov 3, + batch 13's 274 on Nov 5, + batch 14's 278 on Nov 6)
});

test("a page is only used for the listing it was asked for", () => {
  const nd = P.nextData(itemPage("aaa"));
  assert.ok(P.itemData(nd, "aaa"));
  assert.equal(P.itemData(nd, "bbb"), null);
  const lying = P.nextData(itemPage("aaa", item("bbb"))); // query says aaa, data says bbb
  assert.equal(P.itemData(lying, "aaa"), null);
  assert.equal(P.nextData("<html>nothing</html>"), null);
  assert.equal(P.nextData('<script id="__NEXT_DATA__">{broken</script>'), null);
});

test("pushbacks are recognized, listings that mention a robot aren't", () => {
  assert.ok(P.looksBlocked(429, ""));
  assert.ok(P.looksBlocked(403, itemPage("a")));
  assert.ok(P.looksBlocked(200, "<html>Please complete the captcha</html>"));
  assert.ok(!P.looksBlocked(200, itemPage("a", item("a", { metaData: { description: "שואב רובוט, captcha" } }))));
  assert.ok(!P.looksBlocked(404, "not found"));
});

// ---- the pool ------------------------------------------------------------------------

test("parallel: capped in flight, paced, and the same result as one at a time", async () => {
  const list = ids(40);
  const page = async (id) => ({ body: itemPage(id) });
  const jitter = () => 1 + Math.floor(Math.random() * 12); // pages finish out of order
  const par = fakeFetch(page, { delay: jitter });
  const a = await P.fetchItems(list, { ...FAST, minGapMs: 3, concurrency: 4, fetch: par.fn });
  const seq = fakeFetch(page, { delay: jitter });
  const b = await P.fetchItems(list, { ...FAST, concurrency: 1, fetch: seq.fn });
  assert.ok(par.log.maxInFlight <= 4 && par.log.maxInFlight >= 2, `in flight ${par.log.maxInFlight}`);
  assert.equal(seq.log.maxInFlight, 1);
  const strip = (r) => Object.fromEntries(Object.entries(r.results).map(([k, v]) => [k, [v.status, v.extract]]));
  assert.deepEqual(strip(a), strip(b)); // concurrency changes the speed, not one fact
  for (const id of list) assert.equal(a.results[id].extract.id, id);
  assert.equal(a.stats.ok, 40);
  // requests start at least minGapMs apart however many are in flight
  const lim = P.makeLimiter({ ...FAST, minGapMs: 8, concurrency: 4, fetch: fakeFetch(page).fn });
  await P.runQueue(ids(10), (id) => lim.get(P.ITEM_URL(id)), lim);
  const s = lim.stats.starts;
  for (let i = 1; i < s.length; i++) assert.ok(s[i] - s[i - 1] >= 7, `gap ${s[i] - s[i - 1]}`);
});

test("errors are retried, then reported; nothing is dropped", async () => {
  const tries = {};
  const f = fakeFetch(async (id) => {
    tries[id] = (tries[id] || 0) + 1;
    if (id === "flaky" && tries[id] < 2) return { status: 500 };
    if (id === "dead") return { status: 500 };
    if (id === "gone") return { status: 404 };
    if (id === "empty") return { body: "<html>no data</html>" };
    if (id === "other") return { body: itemPage("other", item("someoneelse")) };
    if (id === "net" && tries[id] < 2) throw new Error("reset");
    return { body: itemPage(id) };
  });
  const asked = ["ok1", "flaky", "dead", "gone", "empty", "other", "net", "ok1"];
  const r = await P.fetchItems(asked, { ...FAST, retries: 2, fetch: f.fn });
  const st = Object.fromEntries(Object.entries(r.results).map(([k, v]) => [k, v.status]));
  assert.deepEqual(st, { ok1: "ok", flaky: "ok", dead: "failed", gone: "removed", empty: "failed", other: "removed", net: "ok" });
  assert.equal(r.results.dead.error, "HTTP 500");
  assert.equal(r.results.dead.attempts, 3);
  assert.equal(r.results.empty.error, "the page had no listing data");
  assert.equal(r.stats.asked, 7); // the repeated id once
  assert.equal(r.stats.ok + r.stats.removed + r.stats.failed + r.stats.stopped, r.stats.asked);
  // what the pipeline gets: extracts, plus {id, error} for a removed one (skipped with its reason); failed ones are listed apart
  const xs = P.extractsOf(r.results, asked.slice(0, 7));
  assert.deepEqual(xs.map((x) => x.error || "page"), ["page", "page", "no item data", "no item data", "page"]);
});

test("by default the first pushback stops the pull, at the proven pace", async () => {
  assert.equal(P.DEFAULTS.concurrency, 1);
  assert.ok(P.DEFAULTS.minGapMs >= 1170); // ~0.85 pages a second never drew Yad2's bot check; 4 a second did
  assert.equal(P.DEFAULTS.maxBlocks, 1);
  let n = 0;
  const f = fakeFetch(async (id) => (++n === 3 ? { body: "<html>Radware Bot Manager Captcha validate.perfdrive.com</html>" } : { body: itemPage(id) }));
  const r = await P.fetchItems(ids(8), { minGapMs: 2, backoffMs: 1, fetch: f.fn });
  assert.equal(f.log.calls.length, 3); // not one request after the check page
  assert.equal(r.stats.ok, 2);
  assert.equal(r.stats.stopped, 6);
  assert.ok(r.stats.stoppedBecause.includes("a check page"));
});

test("Yad2 pushing back slows the pull to one at a time, then stops it; nothing is forced", async () => {
  let n = 0;
  const f = fakeFetch(async (id) => (++n >= 6 ? { status: 429 } : { body: itemPage(id) }));
  const r = await P.fetchItems(ids(30), { ...FAST, concurrency: 4, maxBlocks: 2, fetch: f.fn });
  assert.ok(r.stats.stoppedBecause && r.stats.stoppedBecause.includes("HTTP 429"));
  assert.ok(f.log.calls.length < 14, `${f.log.calls.length} requests`); // it stopped, it didn't keep knocking
  assert.equal(r.stats.ok, 5);
  assert.equal(r.stats.ok + r.stats.stopped, 30); // every listing accounted for
  for (const v of Object.values(r.results)) if (v.status === "stopped") assert.ok(v.error.includes("nothing was forced"));
  // one pushback, then fine: it finishes, one at a time (slow pages) and at the slower pace (fast pages)
  for (const [delay, slowGapMs] of [[40, 15], [1, 70]]) {
    let k = 0;
    let pushedAt = null;
    const g = fakeFetch(async (id) => {
      if (++k !== 3) return { body: itemPage(id) };
      pushedAt = Date.now();
      return { status: 503 };
    }, { delay: () => delay });
    const ok = await P.fetchItems(ids(12), { ...FAST, slowGapMs, concurrency: 4, fetch: g.fn });
    assert.equal(ok.stats.ok, 12);
    assert.equal(ok.stats.pushbacks, 1);
    assert.equal(ok.stats.stoppedBecause, null);
    const after = g.log.flight.filter((_, i) => g.log.at[i] > pushedAt);
    assert.ok(after.length >= 6 && after.every((x) => x === 1), `in flight: ${g.log.flight}`);
    const at = g.log.at.filter((t) => t > pushedAt);
    for (let i = 1; i < at.length; i++) assert.ok(at[i] - at[i - 1] >= slowGapMs - 3, `gap ${at[i] - at[i - 1]}`);
    if (delay === 40) assert.equal(Math.max(...g.log.flight.slice(0, 4)), 4); // it was parallel before
  }
  // a bot-check page counts as a pushback, never as a listing
  const h = fakeFetch(async () => ({ body: "<html>captcha</html>" }));
  const c = await P.fetchItems(ids(3), { ...FAST, concurrency: 1, fetch: h.fn });
  assert.equal(c.stats.ok, 0);
  assert.ok(c.stats.stoppedBecause.includes("a check page"));
});

test("the user can stop a pull: what was read is kept, the rest is listed", async () => {
  let n = 0;
  const f = fakeFetch(async (id) => ({ body: itemPage(id) }));
  const r = await P.fetchItems(ids(10), { ...FAST, concurrency: 1, fetch: f.fn, onResult: () => n++, shouldStop: () => n >= 3 });
  assert.equal(r.stats.ok, 3);
  assert.equal(r.stats.stopped, 7);
  assert.equal(r.stats.stoppedBecause, "stopped by you");
  assert.equal(f.log.calls.length, 3);
});

test("results arrive as they're ready, best first when one at a time", async () => {
  const seen = [];
  const f = fakeFetch(async (id) => ({ body: itemPage(id) }));
  await P.fetchItems(["c", "a", "b"], { ...FAST, concurrency: 1, fetch: f.fn, onResult: (id) => seen.push(id) });
  assert.deepEqual(seen, ["c", "a", "b"]);
});

// ---- the cache ------------------------------------------------------------------------

test("a cached listing is reused only if unchanged and recent", async () => {
  const cache = P.memoryCache();
  const rowA = item("a");
  const fps = { a: P.fingerprint(rowA), b: P.fingerprint(item("b")) };
  let t = 1_000_000;
  const now = () => t;
  const f = fakeFetch(async (id) => ({ body: itemPage(id) }));
  const first = await P.fetchItems(["a", "b", "c"], { ...FAST, cache, fingerprints: fps, fetch: f.fn, now, sleep: async () => {} });
  assert.equal(first.stats.fromCache, 0);
  assert.equal(await cache.size(), 2); // c had no fingerprint: never cached, can't be checked later
  f.log.calls.length = 0;
  t += 3600e3; // an hour later, nothing changed
  const again = await P.fetchItems(["a", "b", "c"], { ...FAST, cache, fingerprints: fps, fetch: f.fn, now, sleep: async () => {} });
  assert.deepEqual(f.log.calls.map((u) => u.split("/item/")[1]), ["c"]);
  assert.equal(again.stats.fromCache, 2);
  assert.deepEqual(again.results.a.extract, first.results.a.extract);
  assert.equal(again.results.a.fetchedAt, first.results.a.fetchedAt); // the user is told when it was read
  // the price dropped: the row's fingerprint changed, so it's opened again
  f.log.calls.length = 0;
  const cheaper = { ...fps, a: P.fingerprint(item("a", { price: 3900 })) };
  await P.fetchItems(["a", "b"], { ...FAST, cache, fingerprints: cheaper, fetch: f.fn, now, sleep: async () => {} });
  assert.deepEqual(f.log.calls.map((u) => u.split("/item/")[1]), ["a"]);
  // too old: opened again even though nothing visible changed (the text may have been edited)
  f.log.calls.length = 0;
  t += 25 * 3600e3; // past the default day
  await P.fetchItems(["b"], { ...FAST, cache, fingerprints: fps, fetch: f.fn, now, sleep: async () => {} });
  assert.equal(f.log.calls.length, 1);
});

test("the fingerprint sees an edit the funnel or the user would care about", () => {
  const base = P.fingerprint(item("a"));
  const edits = [
    { price: 4000 }, { adType: "commercial" },
    { address: { ...item("a").address, house: { number: 30, floor: 3 } } },
    { address: { ...item("a").address, coords: { lat: 32.1, lon: 34.7 } } },
    { additionalDetails: { ...item("a").additionalDetails, roomsCount: 4 } },
    { additionalDetails: { ...item("a").additionalDetails, squareMeter: 70 } },
    { metaData: { ...item("a").metaData, images: ["a.jpg", "b.jpg"] } },
    { tags: [{ name: "חדש" }] },
  ];
  for (const e of edits) assert.notEqual(P.fingerprint(item("a", e)), base, JSON.stringify(e));
  assert.equal(P.fingerprint(item("a", { dates: { updatedAt: "later" } })), base); // a bump alone isn't an edit
});

// ---- search pages --------------------------------------------------------------------

test("search: pages read in parallel, repeats once, a listing that moved isn't missed", async () => {
  const mk = (id, price = 4000) => ({ token: id, adType: "private", price, address: { house: { floor: 1 }, coords: { lat: 32, lon: 34.7 } },
    additionalDetails: { roomsCount: 3, squareMeter: 60, property: { text: "דירה" } }, metaData: { squareMeterBuild: 65 } });
  const Y = "https://img.yad2.co.il/Pic/202610/22/2_1/o/";
  const withPhotos = (x) => Object.assign(x, { metaData: Object.assign(x.metaData, { coverImage: Y + "c.jpeg",
    images: [Y + "c.jpeg", Y + "2.jpeg", "https://evil.example/x.jpeg", "javascript:alert(1)", Y + "3.webp"] }) });
  let reads = 0;
  const pages = (pass) => ({
    1: [withPhotos(mk("a")), mk("b"), mk("promo")],
    2: [mk("c"), mk("promo")], // a promoted listing shown twice
    3: pass === 1 ? [mk("d")] : [mk("d"), mk("e")], // e moved from page 2 to 3 while page 3 was read
  });
  const f = fakeFetch(async (_, url) => {
    const p = Number(/page=(\d+)/.exec(url)[1]);
    reads++;
    return { body: searchPage(pages(reads <= 3 ? 1 : 2)[p], 3, 6) };
  });
  const r = await P.searchRows("/realestate/rent?city=6600&maxPrice=5450", { ...FAST, fetch: f.fn });
  assert.deepEqual(r.rows.map((x) => x.id).sort(), ["a", "b", "c", "d", "e", "promo"]);
  assert.equal(r.stats.passes, 2);
  assert.equal(r.stats.seen, 6);
  assert.ok(f.log.calls.every((u) => u.includes("maxPrice=5450&page=")));
  const a = r.rows.find((x) => x.id === "a");
  assert.deepEqual({ ...a, fp: undefined }, { id: "a", adType: "private", price: 4000, floor: 1, lat: 32, lng: 34.7, rooms: 3,
    size_m2: 65, property: "דירה", city: null, hood: null, hood_name: null, street: null,
    photos: [Y + "c.jpeg", Y + "2.jpeg", Y + "3.webp"], fp: undefined }); // cover first, once; only Yad2's image server
  assert.deepEqual(r.rows.find((x) => x.id === "b").photos, []);
  assert.ok(a.fp);
});

test("v1.57: a page in Yad2's current shape (the ordinary listings under \"yad2\") is read whole", async () => {
  // Nov 2: a live Ashdod page carried 40 listings under "yad2", 3 platinum, 3 trio, 1 kingOfTheHar, 6 leadingBroker
  // and new projects under "yad1" (not rentals by a poster), and no "private" or "agency" at all
  const mk = (id) => ({ token: id, price: 4000, address: {}, additionalDetails: {}, metaData: {} });
  const data = { yad2: [mk("y1"), mk("y2")], yad1: { listing: [mk("project")] }, platinum: [mk("p1")], trio: [], booster: [],
    kingOfTheHar: [], leadingBroker: [mk("b1")], pagination: { total: 4, totalPages: 1 }, lookalike: [] };
  const nd = { props: { pageProps: { dehydratedState: { queries: [{ queryKey: ["realestate-rent-feed", {}], state: { data } }] } } } };
  const body = `<script id="__NEXT_DATA__" type="application/json">${JSON.stringify(nd)}</script>`;
  const f = fakeFetch(async () => ({ body }));
  const r = await P.searchRows("/realestate/rent?city=0070", { ...FAST, fetch: f.fn });
  assert.deepEqual(r.rows.map((x) => x.id).sort(), ["b1", "p1", "y1", "y2"]);
});

// ---- routes -------------------------------------------------------------------------------

test("routes: 60 pins a request, 1.1 s apart, and a routed pin isn't asked again", async () => {
  const pins = Object.fromEntries(Array.from({ length: 130 }, (_, i) => [`k${i}`, [32 + i / 1000, 34.7]]));
  const waits = [];
  const urls = [];
  const fetch = async (url) => {
    urls.push(url);
    const n = url.split("driving/")[1].split("?")[0].split(";").length - 1;
    const row = [0].concat(Array.from({ length: n }, (_, i) => 1000 + i));
    return { status: 200, text: async () => JSON.stringify({ code: "Ok", distances: [row], durations: [row.map((x) => x / 4)] }) };
  };
  const cache = P.memoryCache();
  const opts = { fetch, cache, sleep: async (ms) => waits.push(ms) };
  const a = await P.routeTable(pins, [32.075400, 34.774900], "bike", opts);
  assert.equal(a.stats.requests, 3);
  assert.deepEqual(waits, [1100, 1100]);
  assert.ok(urls[0].includes("/routed-bike/table/v1/driving/34.7749,32.0754;34.7,32;"));
  assert.equal(a.routes.k0.m, 1000);
  const b = await P.routeTable(pins, [32.075400, 34.774900], "bike", opts);
  assert.equal(b.stats.requests, 0);
  assert.equal(b.stats.fromCache, 130);
  const c = await P.routeTable(pins, [32.075400, 34.774900], "car", opts); // another profile isn't the same route
  assert.equal(c.stats.requests, 3);
  // a failed table leaves its pins unrouted (a check later), never guessed
  const bad = await P.routeTable({ x: [32, 34.7] }, [32, 34.8], "bike", { fetch: async () => ({ text: async () => "<html>" }) });
  assert.deepEqual(bad.routes, {});
  assert.equal(bad.stats.errors.length, 1);
  // a table that doesn't have one entry per pin isn't trusted: none of it is used
  const short = await P.routeTable({ x: [32, 34.7], y: [32.1, 34.7] }, [32, 34.8], "bike",
    { fetch: async () => ({ text: async () => JSON.stringify({ code: "Ok", distances: [[0, 900]], durations: [[0, 200]] }) }) });
  assert.deepEqual(short.routes, {});
  assert.ok(short.stats.errors[0].includes("not one entry per pin"));
});

test("a short search address is read where Yad2 redirects it, with our parameters kept", async () => {
  const { rebase } = P;
  assert.equal(rebase("/realestate/rent?city=6600&maxPrice=5450", "https://www.yad2.co.il/realestate/rent/tel-aviv-area?area=11&city=6600"),
    "/realestate/rent/tel-aviv-area?city=6600&maxPrice=5450&area=11");
  assert.equal(rebase("/realestate/rent/tel-aviv-area?area=11&city=6600", "https://www.yad2.co.il/realestate/rent/tel-aviv-area?area=11&city=6600&page=1"), null);
  assert.equal(rebase("/realestate/rent?city=6600", "https://validate.perfdrive.com/x"), null);
  const asked = [];
  const fetch = async (url) => {
    asked.push(url);
    const page = Number(new URL(url, "https://www.yad2.co.il").searchParams.get("page"));
    const html = `<script id="__NEXT_DATA__" type="application/json">${JSON.stringify({ props: { pageProps: { dehydratedState: { queries: [
      { queryKey: ["realestate-rent-feed", {}], state: { data: { private: [{ token: `t${page}`, price: 4000, address: {} }], agency: [],
        pagination: { total: 2, totalPages: 2 } } } }] } } } })}</script>`;
    const final = url.startsWith("/realestate/rent?") ? "https://www.yad2.co.il/realestate/rent/tel-aviv-area?area=11&" + url.split("?")[1] : "https://www.yad2.co.il" + url;
    return { status: 200, url: final, text: async () => html };
  };
  const out = await P.searchRows("/realestate/rent?city=6600&maxPrice=5450", { fetch, minGapMs: 0, sleep: async () => {} });
  assert.deepEqual(out.rows.map((r) => r.id).sort(), ["t1", "t2"]);
  assert.equal(asked[1], "/realestate/rent/tel-aviv-area?city=6600&maxPrice=5450&area=11&page=2");
});

test("v1.63: a search row keeps its street and house number; a short city code gets Yad2's four digits", async () => {
  const P = require("./yad2_pull.js");
  const it = { token: "z1", price: 5000, address: { city: { text: "אשדוד" }, neighborhood: { id: 1, text: "רובע א" }, street: { text: "הרצל" },
    house: { floor: 2, number: 12 } }, additionalDetails: { roomsCount: 3 }, metaData: {} };
  assert.equal(P.toRow(it).street, "הרצל 12");
  assert.equal(P.toRow({ ...it, address: { ...it.address, house: { floor: 2 } } }).street, "הרצל");
  assert.equal(P.toRow({ ...it, address: { city: { text: "אשדוד" } } }).street, null);
  assert.equal(P.cityCode("/realestate/rent?city=70&minRooms=3"), "/realestate/rent?city=0070&minRooms=3");
  assert.equal(P.cityCode("/realestate/rent?city=70"), "/realestate/rent?city=0070");
  assert.equal(P.cityCode("/realestate/rent?city=5000&page=2"), "/realestate/rent?city=5000&page=2");
  assert.equal(P.cityCode("/realestate/rent/south?area=21&city=0070"), "/realestate/rent/south?area=21&city=0070");
});
