// node --test browser/store.test.js   (also run from tests/test_browser_pull.py)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("./store.js");

function memory() {
  const data = {};
  return { data, get: async (k) => ({ [k]: data[k] }), set: async (o) => Object.assign(data, o) };
}

test("time estimates: defaults before any pull, then the user's own averages per search", () => {
  const now = Date.parse("2026-10-21T20:00:00Z");
  const none = S.estimate([], 3, now);
  assert.equal(none.kind, "first");
  assert.equal(none.ms, 600e3); // 3 searches x 200 s: the measured 10 min for 3 cities
  assert.deepEqual(none.measured, { first: false, repeat: false });
  const pulls = [
    { at: now - 3 * 3600e3, kind: "first", complete: true, ms: 540e3, searches: 3 },
    { at: now - 3600e3, kind: "repeat", complete: true, ms: 60e3, searches: 3 },
    { at: now - 1800e3, kind: "repeat", complete: false, ms: 5e3, searches: 3 }, // stopped: not an average
  ];
  const e = S.estimate(pulls, 3, now);
  assert.equal(e.kind, "repeat");
  assert.equal(e.ms, 60e3);
  assert.equal(e.first, 540e3);
  assert.deepEqual(e.measured, { first: true, repeat: true });
  assert.equal(S.estimate(pulls, 3, now + 2 * S.DAY).kind, "first"); // the cache is a day old
});

test("marks: a listing with no call left is forgotten; a call keeps the card", async () => {
  const st = memory();
  const store = S.make(st);
  const x = { id: "a1", price: 4000, street: "רחוב", big: "x".repeat(1000) };
  await store.setMark(x, { status: "viewing", viewingAt: "2026-10-23T18:00" });
  assert.equal(st.data.marks.a1.viewingAt, "2026-10-23T18:00");
  assert.equal(st.data.marks.a1.view.street, "רחוב");
  assert.equal(st.data.marks.a1.view.big, undefined);
  await store.setMark(x, { status: "interested" });
  assert.equal(st.data.marks.a1.viewingAt, null); // no longer a viewing
  await store.setMark(x, { status: null });
  assert.equal(st.data.marks.a1, undefined);
});

test("the log and the pull history keep only the latest", async () => {
  const st = memory();
  const store = S.make(st);
  for (let i = 0; i < 120; i++) await store.logEvent({ kind: "pushback", i });
  for (let i = 0; i < 40; i++) await store.addPull({ at: i });
  assert.equal(st.data.log.length, 100);
  assert.equal(st.data.log[0].i, 20);
  assert.equal(st.data.pulls.length, 30);
});

test("v1.30: a lower rent than last time is a price drop, for two weeks; going back up clears it", async () => {
  const m = memory();
  const st = S.make(m);
  const day = 864e5;
  assert.deepEqual(await st.notePrices([{ id: "a", price: 5000 }, { id: "b", price: 4000 }], 0), {});
  let d = await st.notePrices([{ id: "a", price: 4700 }, { id: "b", price: 4000 }], day);
  assert.deepEqual(d, { a: { was: 5000, now: 4700, at: day } });
  d = await st.notePrices([{ id: "a", price: 4500 }], 2 * day); // dropped again: from the first rent
  assert.deepEqual(d.a, { was: 5000, now: 4500, at: 2 * day });
  d = await st.notePrices([{ id: "a", price: 4900 }], 3 * day);
  assert.equal(d.a, undefined);
  await st.notePrices([{ id: "b", price: 3500 }], 4 * day);
  assert.equal((await st.notePrices([], 20 * day)).b, undefined); // two weeks on: not news any more
});

test("v1.35: listings kept for labeling: text and facts, no contact, no pin, phones blanked; newest first, capped", async () => {
  const m = memory();
  const st = S.make(m);
  const scrub = (s) => s.replace(/05\d-?\d{7}/g, "[phone]");
  const n = await st.keepForLabels({
    a: { id: "a", price: 4000, description: "דירה יפה, 050-1234567", coords: { lat: 32, lon: 34.7 }, customer: { name: "x" }, contactName: "y", inProperty: { isRenovated: true } },
    b: { id: "b", error: "no item data" },
    c: { id: "c", description: "  " },
  }, scrub, 1000);
  assert.equal(n, 1);
  assert.deepEqual(m.data.labelset.a, { id: "a", price: 4000, description: "דירה יפה, [phone]", inProperty: { isRenovated: true }, keptAt: 1000 });
  for (let i = 0; i < 405; i++) await st.keepForLabels({ [`x${i}`]: { id: `x${i}`, description: "t" } }, scrub, 2000 + i);
  assert.equal(Object.keys(m.data.labelset).length, 400);
  assert.ok(!("a" in m.data.labelset)); // the oldest went
  await st.keepForLabels({}, scrub, 2000 + 404 + 31 * 864e5);
  assert.equal(Object.keys(m.data.labelset).length, 0); // and after a month, all of them
});

test("v1.40: what v1.37's \"Neither\" rejected comes back; your own rejections stay", async () => {
  const m = memory();
  const st = S.make(m);
  m.data.marks = {
    a: { status: "rejected", why: "neither", at: 1 },
    b: { status: "rejected", why: "neither", fav: true, at: 1 },
    c: { status: "rejected", at: 1 },
    d: { status: "viewing", at: 1 },
  };
  assert.equal(await st.undoNeither(), 2);
  assert.deepEqual(Object.keys(m.data.marks).sort(), ["b", "c", "d"]);
  assert.deepEqual(m.data.marks.b, { fav: true, at: 1 });
  assert.equal(m.data.marks.c.status, "rejected");
  assert.equal(await st.undoNeither(), 0);
});
