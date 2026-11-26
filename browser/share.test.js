// node --test browser/share.test.js: sharing listings as a page or as text (v1.41-v1.46)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("./share.js");
const I = require("./i18n.js");
const C = require("./cards.js");

I.setLang("en");

const listing = (id, extra) => Object.assign({
  id, source: "yad2", price: 4500, rooms: 3, size_m2: 60, floor: 2,
  street: "Herzl 1", neighborhood: "City Center", city: "Tel Aviv",
  url: `https://www.yad2.co.il/realestate/item/${id}`,
  trips: [], feature_keys: [], photos: [], also: [],
}, extra || {});

test("pick: all listings except excluded ones, each once", () => {
  const xs = [listing("a"), listing("b"), listing("c", { excluded: true }), listing("d")];
  const groups = S.pick(xs, {}, ["all"]);
  assert.deepEqual(groups[0].listings.map((x) => x.id), ["a", "b", "d"]);
});

test("pick: favorites and interested are their own groups; a rejected listing is left out everywhere", () => {
  const xs = [listing("a"), listing("b"), listing("c", { excluded: true }), listing("d")];
  const marks = { a: { fav: true }, b: { status: "interested" }, d: { status: "rejected" } };
  const groups = S.pick(xs, marks, ["fav", "interested", "all"]);
  const byGroup = Object.fromEntries(groups.map((g) => [g.group, g.listings.map((x) => x.id)]));
  assert.deepEqual(byGroup.fav, ["a"]);
  assert.deepEqual(byGroup.interested, ["b"]);
  // "a" and "b" are already placed above; "c" is excluded; "d" is rejected -- "all" is empty, not a duplicate list
  assert.equal(byGroup.all, undefined);
});

test("text: a WhatsApp-ready summary, with each listing's link", () => {
  const out = S.text(S.pick([listing("a")], {}, ["all"]), { I, C, marks: {} });
  assert.match(out, /yad2\.co\.il\/realestate\/item\/a/);
  assert.match(out, /₪4,500/);
});

test("embedPhotos: a fetchable photo becomes a data: URI; a failing one keeps its address", async () => {
  const ok = "https://img.yad2.co.il/Pic/ok.jpg";
  const bad = "https://img.yad2.co.il/Pic/bad.jpg";
  const fakeFetch = async (url) => {
    if (url === bad) throw new Error("network down");
    return { ok: true, headers: { get: () => "image/jpeg" }, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  };
  const out = await S.embedPhotos([ok, bad], fakeFetch);
  assert.match(out.get(ok), /^data:image\/jpeg;base64,/);
  assert.equal(out.get(bad), bad); // couldn't fetch it now: the remote link still works once there's a connection
});

test("embedPhotos: an HTTP error also falls back, and nothing throws or hangs", async () => {
  const url = "https://img.yad2.co.il/Pic/missing.jpg";
  const out = await S.embedPhotos([url], async () => ({ ok: false, status: 404 }));
  assert.equal(out.get(url), url);
});

test("toDataURL: round-trips bytes as base64", () => {
  const url = S.toDataURL(new Uint8Array([72, 105]), "image/png"); // "Hi"
  assert.equal(url, "data:image/png;base64,SGk=");
});

test("html: embeds a fetchable photo and adds no 'needs a connection' note", async () => {
  const withPhoto = listing("a", { photos: ["https://img.yad2.co.il/Pic/one.jpg"] });
  const fakeFetch = async () => ({ ok: true, headers: { get: () => "image/png" }, arrayBuffer: async () => new Uint8Array([9]).buffer });
  const page = await S.html(S.pick([withPhoto], {}, ["all"]), { I, C, marks: {}, fetch: fakeFetch });
  assert.match(page, /<img loading="lazy" referrerpolicy="no-referrer" src="data:image\/png;base64,/);
  assert.ok(!page.includes(S.esc(I.t("sx_photo_note")))); // nothing stayed remote, so no note is needed
});

test("html: a photo that can't be fetched keeps its address, and the page says a connection is needed", async () => {
  const withPhoto = listing("a", { photos: ["https://img.yad2.co.il/Pic/one.jpg"] });
  const page = await S.html(S.pick([withPhoto], {}, ["all"]), { I, C, marks: {}, fetch: async () => { throw new Error("offline"); } });
  assert.match(page, /src="https:\/\/img\.yad2\.co\.il\/Pic\/one\.jpg"/); // fell back to the remote address
  assert.ok(page.includes(S.esc(I.t("sx_photo_note"))));
});

test("html: no photos at all needs no fetch and no note", async () => {
  const page = await S.html(S.pick([listing("a")], {}, ["all"]), {
    I, C, marks: {}, fetch: async () => { throw new Error("should never be called"); },
  });
  assert.ok(!page.includes(S.esc(I.t("sx_photo_note"))));
  assert.ok(page.includes(S.esc(I.t("ph_none"))));
});
