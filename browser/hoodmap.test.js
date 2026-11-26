// node --test browser/hoodmap.test.js: the map's geometry (v1.32)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const H = require("./hoodmap.js");

// Ramat HaSharon, as Yad2's neighborhood list gave it on Oct 24, 2026: centers, and boxes of the size it gave
const GIV = [[1642, 32.071207, 34.81282, 0.0099, 0.0064], [355, 32.077748, 34.80815, 0.0138, 0.0048], [1643, 32.069401, 34.804938, 0.0074, 0.0067],
  [991512, 32.071212, 34.816636, 0.0035, 0.0042], [991510, 32.073766, 34.804648, 0.0079, 0.0034], [991511, 32.063112, 34.807217, 0.007, 0.0068],
  [230709, 32.07868, 34.82022, 0.0015, 0.0009], [991509, 32.07991, 34.79982, 0.0035, 0.0032], [1485, 32.077929, 34.817191, 0.0056, 0.0052],
  [1644, 32.076065, 34.803735, 0.0042, 0.0017], [1641, 32.079997, 34.798287, 0.0214, 0.0233], [245, 32.066503, 34.812654, 0.0083, 0.0033],
  [1481, 32.075027, 34.813631, 0.0101, 0.0043], [1488, 32.062489, 34.814165, 0.0112, 0.008]]
  .map(([id, lat, lng, w, h]) => ({ id, lat, lng, box: [lng - w / 2, lat - h / 2, lng + w / 2, lat + h / 2] }));
const CITY = [34.797974, 32.058479, 34.820881, 32.081775];

// is a point inside a ring (even-odd)
function inside([x, y], ring) {
  let c = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

test("Web Mercator there and back", () => {
  const [x, y] = H.project(34.8, 32.07, 14);
  const [lng, lat] = H.unproject(x, y, 14);
  assert.ok(Math.abs(lng - 34.8) < 1e-9 && Math.abs(lat - 32.07) < 1e-9);
  assert.deepEqual(H.project(-180, 0, 0).map(Math.round), [0, 128]);
});

test("clipping a square by a half-plane and a rectangle", () => {
  const sq = [[0, 0], [2, 0], [2, 2], [0, 2]];
  assert.equal(H.area(H.clipHalf(sq, 1, 0, 1)), 2); // x <= 1
  assert.equal(H.area(H.clipRect(sq, [1, 1, 3, 3])), 1);
  assert.deepEqual(H.clipHalf(sq, 1, 0, -1), []); // nothing left
  assert.deepEqual(H.centroid(sq), [1, 1]);
});

test("every Ramat HaSharon neighborhood gets an area around its own center, and the areas don't overlap", () => {
  const c = H.cells(GIV, CITY);
  assert.equal(Object.keys(c).length, GIV.length);
  for (const h of GIV) {
    assert.ok(c[h.id].ring, `${h.id} has an area`);
    assert.ok(inside([h.lng, h.lat], c[h.id].ring), `${h.id}'s center is inside its area`);
    for (const o of GIV) if (o.id !== h.id) assert.ok(!inside([o.lng, o.lat], c[h.id].ring), `${o.id}'s center isn't in ${h.id}'s area`);
  }
  // a point between two centers belongs to the nearer one
  const a = GIV.find((h) => h.id === 1642);
  const b = GIV.find((h) => h.id === 991512);
  const near = [a.lng + 0.3 * (b.lng - a.lng), a.lat + 0.3 * (b.lat - a.lat)];
  assert.ok(inside(near, c[1642].ring) && !inside(near, c[991512].ring));
});

test("no center, no area; two names for one place share it; nothing at all, nothing drawn", () => {
  const c = H.cells([{ id: 1, lat: 32.07, lng: 34.8 }, { id: 2, lat: 32.07, lng: 34.8 }, { id: 3, lat: NaN, lng: NaN }, { id: 4, lat: 32.08, lng: 34.81 }], null);
  assert.ok(c[1].ring && c[2].ring && c[4].ring);
  assert.equal(c[3], undefined);
  assert.deepEqual(H.area(c[1].ring), H.area(c[2].ring));
  assert.deepEqual(H.cells([], null), {});
});

test("the city fits the map", () => {
  const f = H.fit(CITY, 700, 420);
  assert.equal(f.z, 14);
  const [x0, y1] = H.project(CITY[0], CITY[1], f.z);
  const [x1, y0] = H.project(CITY[2], CITY[3], f.z);
  assert.ok(x1 - x0 <= 660 && y1 - y0 <= 380);
});

test("v1.41: neighbors never share a tint", () => {
  const M = require("./hoodmap.js");
  const hoods = [];
  for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) hoods.push({ id: 100 + i * 5 + j, lat: 32.0 + i * 0.01, lng: 34.75 + j * 0.01 });
  const shapes = M.cells(hoods, null);
  const tint = M.tints(shapes);
  assert.equal(tint.size, Object.keys(shapes).length);
  const key = (p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
  const ids = Object.keys(shapes).map(Number);
  let pairs = 0;
  for (const a of ids) for (const b of ids) {
    if (a >= b || !shapes[a].ring || !shapes[b].ring) continue;
    const sa = new Set(shapes[a].ring.map(key));
    if (shapes[b].ring.some((p) => sa.has(key(p)))) {
      pairs++;
      assert.notEqual(tint.get(a), tint.get(b), `${a} and ${b} touch`);
    }
  }
  assert.ok(pairs > 10);
  assert.ok(Math.max(...tint.values()) < 8); // the eight tints are enough
});
