"""v1.38: one apartment posted more than once on the same site is shown once."""

import unittest
from pathlib import Path

from rental_matcher.scoring import PreferenceSet
from rental_matcher.server import do_plan
from rental_matcher.sources import dedupe, same_apartment

PREFS = PreferenceSet.load(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "prefs_frozen.json")


def row(id, **kw):
    # the screenshot's listing: יד חרוצים, מונטיפיורי הרכבת, ₪4,300, 1 room, floor 1, 55 m²
    base = {"id": id, "source": "yad2", "city": "תל אביב יפו", "hood_name": "מונטיפיורי, הרכבת", "street": "יד חרוצים 10", "price": 4300,
            "rooms": 1, "floor": 1, "size_m2": 55, "lat": 32.0626, "lng": 34.7853, "photos": ["p"] * 5}
    base.update(kw)
    return base


class TestSameSite(unittest.TestCase):
    def test_three_posts_become_one(self):
        rows = [row("a1", photos=["p"] * 5), row("b2", photos=["p"] * 10, lat=32.0627), row("c3", photos=["p"] * 8, price=4400)]
        kept, also = dedupe(rows)
        self.assertEqual([r["id"] for r in kept], ["b2"])  # the most photos
        self.assertEqual(sorted(o["id"] for o in also["b2"]), ["a1", "c3"])
        for o in also["b2"]:
            self.assertTrue(o["same_site"])
            self.assertEqual(o["url"], f"https://www.yad2.co.il/realestate/item/{o['id']}")  # a link the card can open

    def test_near_misses_stay_apart(self):
        a = row("a")
        for other in (row("b", floor=2), row("b", rooms=2), row("b", size_m2=60), row("b", price=4800),
                      row("b", lat=32.0700), row("b", street="יד חרוצים 12"), row("b", street=None)):  # v1.63: the address decides
            self.assertFalse(same_apartment(a, other), other)

    def test_the_same_post_twice_is_once(self):
        kept, also = dedupe([row("a"), row("a")])
        self.assertEqual(len(kept), 1)
        self.assertEqual(also, {})

    def test_a_marked_copy_is_the_one_kept(self):
        rows = [row("a1", photos=["p"] * 5), row("b2", photos=["p"] * 10)]
        kept, _ = dedupe(rows, prefer=["a1"])
        self.assertEqual([r["id"] for r in kept], ["a1"])

    def test_across_sites_unchanged(self):
        komo = row("komo:1", source="komo", lat=None, lng=None, approx=True, price=4250)
        kept, also = dedupe([komo, row("a1")])
        self.assertEqual([r["id"] for r in kept], ["a1"])
        self.assertFalse(also["a1"][0]["same_site"])

    def test_not_for_me_on_any_copy_hides_the_one_shown(self):
        rows = [row("a1", photos=["p"] * 5), row("b2", photos=["p"] * 10)]
        out = do_plan({"rows": rows, "skip": ["a1"]}, PREFS)
        self.assertIn("b2", out["skipped"])
        self.assertEqual(out["fetch"], [])

    def test_prefer_must_be_ids(self):
        with self.assertRaises(Exception):
            do_plan({"rows": [row("a")], "prefer": [1]}, PREFS)


if __name__ == "__main__":
    unittest.main()
