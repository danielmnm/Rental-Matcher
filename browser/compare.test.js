// node --test browser/compare.test.js: choosing pairs to compare (v1.32)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("./compare.js");

const L = (id, m, sat, extra) => Object.assign({ id, match_expected: m, fail_risk: 0, sat }, extra || {});

test("the next pair: close in the ranking, different in what they have, never asked twice", () => {
  const xs = [L("a", 70, { balcony: 1, price: 0.2 }), L("b", 69, { balcony: 0, price: 0.9 }), L("c", 72, { balcony: 1, price: 0.25 }),
    L("d", 20, { balcony: 0, price: 1 }), L("hid", 70, { balcony: 0, price: 1 }, { excluded: true }), L("nosat", 70, {})];
  const first = () => 0; // the best candidate, in its order
  const p = C.nextPair(xs, [], first).map((x) => x.id).sort();
  assert.deepEqual(p, ["a", "b"]); // close (70 vs 69) and different; a-c are close but alike; d is far
  const asked = [{ a: { id: "a" }, b: { id: "b" } }];
  const q = C.nextPair(xs, asked, first).map((x) => x.id).sort();
  assert.notDeepEqual(q, ["a", "b"]);
  assert.ok(!q.includes("hid") && !q.includes("nosat"));
  assert.equal(C.nextPair([xs[0]], [], first), null);
});

test("a pick keeps what the fit needs, and no more", () => {
  const k = C.keep(L("a", 70, { balcony: 1 }, { fail_risk: 0.1, price: 4000, street: "x", photos: ["p"], description: "long" }));
  assert.deepEqual(k, { id: "a", sat: { balcony: 1 }, fail: 0.1, price: 4000, street: "x", city: undefined });
});
