// node --test browser/i18n.test.js   (also run from tests/test_browser_pull.py)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const I = require("./i18n.js");

test("every word exists in both languages, with the same blanks", () => {
  const en = Object.keys(I.S.en).sort(), he = Object.keys(I.S.he).sort();
  assert.deepEqual(he.filter((k) => I.S.en[k] == null), [], "Hebrew keys missing in English");
  assert.deepEqual(en.filter((k) => I.S.he[k] == null), [], "English keys missing in Hebrew");
  const blanks = (s) => (String(s).match(/\{\w+\}/g) || []).sort().join();
  for (const k of en) assert.equal(blanks(I.S.he[k]), blanks(I.S.en[k]), `blanks differ in ${k}`);
  for (const k of en) if (k !== "app" && !/^(sec|min|h_min|w_custom|ask_about)$/.test(k) && I.S.he[k] && /[a-z]{4,}/.test(I.S.he[k].replace(/Rental Matcher|install\.bat|JSON|AI|\{\w+\}/g, ""))) {
    assert.fail(`untranslated English in Hebrew ${k}: ${I.S.he[k]}`);
  }
});

test("notes become sentences in both languages", () => {
  const prefs = {
    price: { topic: "rent", must: false, limit: 4500 }, parking: { topic: "parking", must: true },
    floor_without_elevator: { topic: "floor_high", must: true, limit: 2 }, bike: { topic: "commute", place: "Work", mode: "ebike", must: true, limit: 15 },
    no_roommates: { topic: "whole", must: true },
  };
  for (const l of ["en", "he"]) {
    I.setLang(l);
    const s = [
      I.note({ name: "price", reason: "over", value: 5000, limit: 4500, needs: ["balcony"] }, prefs.price),
      I.note({ name: "parking", reason: "unstated" }, prefs.parking),
      I.note({ name: "floor_without_elevator", reason: "needs", value: 3, needs: ["elevator"] }, prefs.floor_without_elevator),
      I.note({ name: "bike", reason: "past", value: 18, limit: 15 }, prefs.bike),
      I.note({ name: "no_roommates", reason: "no", value: true }, prefs.no_roommates),
    ];
    for (const x of s) assert.ok(x && !/\{\w+\}|undefined|null|NaN/.test(x), `${l}: ${x}`);
    if (l === "en") {
      assert.equal(s[0], "₪500 over your ₪4,500 budget; within budget if it has a balcony");
      assert.equal(s[2], "Floor 3 is fine only if there's an elevator. Ask.");
    } else {
      assert.equal(s[0], "500 ₪ מעל התקציב שלך (4,500 ₪); בתוך התקציב אם יש מרפסת");
    }
  }
  I.setLang("en");
});

test("suggestions and features in words", () => {
  I.setLang("en");
  assert.equal(I.suggestion({ topic: "rent", now: 4750 }), "Raise your rent limit to ₪4,750");
  assert.equal(I.suggestion({ topic: "commute", mode: "ebike", now: 18 }), "Allow up to 18 min by e-bike");
  assert.equal(I.feature({ key: "parking_own" }), "Own parking");
  assert.equal(I.feature({ key: "available", days: 0 }), "Available now");
  I.setLang("he");
  assert.equal(I.suggestion({ topic: "commute", mode: "ebike", now: 18 }), "לאפשר עד 18 דק' באופניים חשמליים");
  assert.equal(I.feature({ key: "item_sofa" }), "ספה");
  assert.equal(I.dir(), "rtl");
  I.setLang("en");
});
