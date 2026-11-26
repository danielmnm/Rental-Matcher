"""Komo and Madlan (v1.27): the adapters, one apartment on two sites, and
the helper's answers with listings from all three sites.

The extracts are what browser/sites.js read from pages saved on Oct 22, 2026
(tests/fixtures/sites_2026-10-22/parsed.json; parse.js makes it again, and
the last test checks it's current when Node is installed)."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from rental_matcher.adapters import komo, madlan
from rental_matcher.pipeline import build_listing
from rental_matcher.schema import ListedBy, SignalStatus, Source
from rental_matcher.scoring import PreferenceSet
from rental_matcher.server import do_plan, do_score
from rental_matcher.sources import dedupe, same_apartment

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "sites_2026-10-22"
PARSED = json.loads((FX / "parsed.json").read_text(encoding="utf-8"))
WHEN = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


class TestKomo(unittest.TestCase):
    def test_listing_page(self):
        x = komo.to_listing(PARSED["komo_item"], WHEN)
        self.assertEqual((x.id, x.source, x.source_listing_id), ("komo:4943180", Source.KOMO, "4943180"))
        self.assertEqual((x.price.amount, x.rooms, x.floor, x.total_floors, x.size_m2), (5400, 4, 1, 3, 75))
        self.assertEqual((x.area.city, x.area.neighborhood, x.area.lat), ("בת ים", "שכונה לדוגמה", None))
        s = x.signals
        for name in ("elevator", "air_conditioning", "window_bars", "accessible", "pets_allowed", "furniture_box"):
            self.assertIs(s[name].value, True, name)
            self.assertEqual(s[name].status, SignalStatus.CONFIRMED)
        self.assertNotIn("mamad", s)  # shown unticked: unknown, not a no
        self.assertIs(s["renovated"].value, False)  # "במצב טוב": well kept, not renovated
        self.assertEqual(s["parking_level"].value, 2.0)
        self.assertEqual(s["days_until_available"].value, (date(2026, 11, 1) - WHEN.date()).days)
        self.assertEqual(str(x.links[0].url), "https://www.komo.co.il/code/nadlan/details/?modaaNum=4943180")
        self.assertTrue(x.raw_excerpt.startswith("להשכרה לטווח ארוך"))

    def test_results_row_and_no_price(self):
        rows = {r["id"]: r for r in PARSED["komo_rows"]}
        x = komo.to_listing(rows["komo:4943744"], WHEN)
        self.assertEqual((x.price.amount, x.area.neighborhood, x.area.street), (4950, "אגרובנק", "אליהו קראוזה"))
        with self.assertRaisesRegex(ValueError, "no usable price"):
            komo.to_listing(rows["komo:4930130"], WHEN)

    def test_floor_above_the_building_drops_the_building(self):
        x = komo.to_listing(dict(PARSED["komo_item"], floor=5, floors=3), WHEN)
        self.assertEqual((x.floor, x.total_floors), (5, None))


class TestMadlan(unittest.TestCase):
    def test_results_row(self):
        rows = {r["id"]: r for r in PARSED["madlan_rows"]}
        x = madlan.to_listing(rows["madlan:jC721dhbyHL"], WHEN)
        self.assertEqual((x.id, x.source, x.listed_by), ("madlan:jC721dhbyHL", Source.MADLAN, ListedBy.AGENCY))
        self.assertAlmostEqual(x.area.lat, 32.0224, places=3)
        self.assertEqual(x.signals, {})  # a results row: the numbers and the pin, no features
        roof = madlan.to_listing(rows["madlan:LhvqWyJ8NMq"], WHEN)
        self.assertEqual(roof.signals["apartment_type"].value, "roof")

    def test_listing_page(self):
        x = madlan.to_listing({**PARSED["madlan_rows"][1], "amenities": {"elevator": True, "secureRoom": True, "balcony": False},
                               "condition": "renovated", "availability": "immediate", "parking": 1,
                               "description": "דירה יפה"}, WHEN)
        s = x.signals
        self.assertIs(s["elevator"].value, True)
        self.assertIs(s["mamad"].value, True)
        self.assertIs(s["protected_space"].value, True)
        self.assertNotIn("balcony", s)  # false: unknown
        self.assertIs(s["renovated"].value, True)
        self.assertEqual(s["days_until_available"].value, 0.0)
        self.assertEqual(s["parking_level"].value, 2.0)


class TestSameApartment(unittest.TestCase):
    # v1.63: both give the address (Yad2's search rows carry the street since v1.63; a merge needs it on both sides)
    Y = {"id": "Y1", "price": 4950, "rooms": 3, "size_m2": 80, "floor": 1, "city": "בת ים", "hood_name": "אגרובנק", "street": "אליהו קראוזה 13",
         "lat": 32.0, "lng": 34.7}
    K = {"id": "komo:4943744", "source": "komo", "url": "https://www.komo.co.il/code/nadlan/details/?modaaNum=4943744", "price": 4950,
         "rooms": 3, "size_m2": 80, "floor": 1, "city": "בת ים", "hood_name": "אגרובנק", "street": "קראוזה 13", "lat": None, "lng": None}

    def test_kept_once_with_a_link_and_its_rent(self):
        rows, also = dedupe([self.K, self.Y])
        self.assertEqual([r["id"] for r in rows], ["Y1"])
        self.assertEqual(also, {"Y1": [{"source": "komo", "name": "Komo", "id": "komo:4943744", "url": self.K["url"], "price": 4950.0,
                                       "same_site": False, "size_m2": 80.0}]})

    def test_the_v127_agrobank_link(self):
        """v1.29: a Yad2 listing in Agrobank with no size took a Komo listing from another
        neighborhood (same rent, rooms and floor) as its twin, so its Komo link opened a different apartment."""
        yad2 = dict(self.Y, size_m2=None)
        elsewhere = dict(self.K, hood_name="שכונה לדוגמה", street="אילת 5")
        self.assertFalse(same_apartment(yad2, elsewhere))
        self.assertFalse(same_apartment(yad2, self.K))  # no size to compare: not enough to call it the same flat
        self.assertFalse(same_apartment(self.Y, elsewhere))  # everything agrees but the address

    def test_a_cheaper_copy_is_still_the_same_flat(self):
        self.assertTrue(same_apartment(self.Y, dict(self.K, price=4700)))  # 5% apart: one owner, two asking rents
        self.assertFalse(same_apartment(self.Y, dict(self.K, price=4000)))  # 24% apart: not the same offer

    def test_near_misses_stay_apart(self):
        for change in ({"size_m2": 90}, {"rooms": 3.5}, {"floor": 2}, {"city": "בת ים"}, {"floor": None}, {"hood_name": None, "street": None},
                       {"street": "קראוזה 15"}, {"street": "קראוזה"}, {"street": "הרצל 13"}):
            other = dict(self.K, **change)
            self.assertFalse(same_apartment(self.Y, other), change)
        # v1.38: the same site twice is one apartment only in one building (pins within 50 m)
        self.assertTrue(same_apartment(self.Y, dict(self.Y, id="Y2")))
        self.assertFalse(same_apartment(self.Y, dict(self.Y, id="Y2", lat=32.001)))  # ~110 m: a neighbor
        self.assertTrue(same_apartment(self.Y, dict(self.Y, id="Y2", lat=None, lng=None)))  # v1.63: the same address is enough
        self.assertFalse(same_apartment(self.Y, dict(self.Y, id="Y2", lat=None, lng=None, street=None)))  # no address: can't tell
        far = dict(self.K, id="madlan:a", source="madlan", lat=32.01, lng=34.7)  # ~1.1 km away
        self.assertFalse(same_apartment(self.Y, far))
        self.assertTrue(same_apartment(self.Y, dict(far, lat=32.001)))  # ~110 m: the same building, near enough

    def test_madlan_kept_over_komo(self):
        m = dict(self.Y, id="madlan:a", source="madlan", street="אליהו קראוזה 13")
        rows, also = dedupe([self.K, m])
        self.assertEqual([r["id"] for r in rows], ["madlan:a"])
        self.assertEqual(list(also), ["madlan:a"])


class TestHelperWithAllSites(unittest.TestCase):
    def test_plan_and_score(self):
        rows = PARSED["komo_rows"] + PARSED["madlan_rows"]
        rows = [dict(r, lat=32.01, lng=34.77, approx=True) if r["id"] == "komo:4943180" else r for r in rows]
        p = do_plan({"rows": rows}, PREFS)
        self.assertEqual(p["rows"], 26)
        self.assertNotIn("32.01,34.77", p.get("pins", {}))  # an approximate pin isn't routed or used to rule out
        self.assertEqual(p["skipped"]["komo:4930130"][0].split(":")[0], "Komo item '4930130' has no usable price")
        item = dict(PARSED["komo_item"], lat=32.01, lng=34.77)
        out = do_score({"extracts": [item] + PARSED["madlan_rows"],
                        "pin_routes": {c.signal: {"32.01,34.77": {"m": 1000, "s": 200}} for c in PREFS.commutes}}, PREFS)
        by = {r["id"]: r for r in out["results"]}
        k = by["komo:4943180"]
        self.assertEqual((k["source"], k["approx"], k["url"]), ("komo", True, "https://www.komo.co.il/code/nadlan/details/?modaaNum=4943180"))
        for t in k["trips"]:
            self.assertIsNone(t["minutes"])  # an estimate from the neighborhood, never a routed time
        self.assertEqual(by["madlan:jC721dhbyHL"]["source"], "madlan")
        self.assertFalse(by["madlan:jC721dhbyHL"]["approx"])

    def test_routes_are_found_by_the_extracts_id(self):
        x = dict(PARSED["madlan_rows"][1])
        signal = PREFS.commutes[0].signal
        listing = build_listing(x, PREFS, routes={signal: {x["id"]: {"km": 2.0, "source": "OSRM"}}}, pulled_at=WHEN)
        self.assertEqual(listing.signals[signal].status, SignalStatus.CONFIRMED)

    def test_unknown_site_is_refused(self):
        with self.assertRaisesRegex(ValueError, "a site we don't read"):
            build_listing({"id": "x", "source": "craigslist", "price": 1}, PREFS, pulled_at=WHEN)  # v1.66: Facebook is read now (view-only)


@unittest.skipUnless(shutil.which("node"), "Node.js isn't installed")
class TestParsedIsCurrent(unittest.TestCase):
    def test_parse_js_gives_the_same(self):
        r = subprocess.run(["node", str(FX / "parse.js")], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(r.stdout), PARSED)


if __name__ == "__main__":
    unittest.main()
