// node --test browser/setup_lib.test.js: what goes when an area goes (v1.36)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const R = require("./setup_lib.js");
const S = require("./sites.js");

test("taking a place out drops its listings and their marks; what can't be placed, and a booked viewing, stay", () => {
  const results = { stage: "done", results: [
    { id: "a", city: "תל אביב יפו", neighborhood: "שפירא" },
    { id: "b", city: "תל אביב יפו", neighborhood: "מרכז העיר" },
    { id: "c", city: "תל אביב יפו", neighborhood: null },
    { id: "d", city: "בת ים", neighborhood: "שכונה לדוגמה" },
    { id: "e", city: "רמת גן", neighborhood: "מרכז העיר" },
  ] };
  const marks = { a: { fav: true, view: { city: "תל אביב יפו", neighborhood: "שפירא" } }, d: { status: "viewing", view: { city: "בת ים" } },
    old: { status: "interested", view: { city: "בת ים", neighborhood: "קריית שרת" } } };
  const p = R.pruneTo(results, marks, [{ city: "תל אביב - יפו", hoods: ["שפירא", "התקווה"] }, { city: "בת ים", hoods: null }], S.sameHood);
  assert.deepEqual(p.results.results.map((x) => x.id), ["b", "c", "e"]); // c: no neighborhood, can't tell: kept
  assert.deepEqual(Object.keys(p.marks), ["d"]); // the viewing stays; Shapira's favorite and Bat Yam's goes
  assert.deepEqual(p.removed.sort(), ["a", "d", "old"]);
  assert.equal(p.results.stage, "done");
  assert.deepEqual(R.pruneTo(results, marks, [], S.sameHood).removed, []);
  assert.deepEqual(R.pruneTo(null, {}, [{ city: "בת ים", hoods: null }], S.sameHood).removed, []);
});

test("v1.67: a place Yad2 serves on another site is marked, not read as an empty search", async () => {
  const real = globalThis.fetch;
  const answer = { 3616: "https://www.yad-il.co.il/realestate/rent/partnership/east?area=90&city=3616",
    8000: "https://www.yad2.co.il/realestate/rent/north-and-valleys?area=20&city=8000" };
  globalThis.fetch = async (url) => ({ ok: true, url: answer[Number(/city=(\d+)/.exec(url)[1])] });
  try {
    assert.deepEqual(await R.yad2Where(3616), { path: "/realestate/rent?city=3616", elsewhere: "yad-il.co.il" });
    assert.deepEqual(await R.yad2Where(8000), { path: "/realestate/rent/north-and-valleys?area=20&city=8000", elsewhere: null });
    assert.equal(await R.yad2Path(8000), "/realestate/rent/north-and-valleys?area=20&city=8000"); // unchanged for the rest
    const s = await R.citySearch({ code: 3616, en: "Ma'ale Adumim", he: "מעלה אדומים" });
    assert.equal(s.elsewhere, "yad-il.co.il");
    assert.equal("elsewhere" in (await R.citySearch({ code: 8000, en: "Safed", he: "צפת" })), false);
  } finally {
    globalThis.fetch = real;
  }
});
