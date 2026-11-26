"""
v1.33: photos as a criterion (`photo_count` -> the has_photos signal), the
neighborhoods a search keeps (names and centers), and the setup catalog.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rental_matcher import server, setup
from rental_matcher.pipeline import build_listing
from rental_matcher.scoring import PreferenceSet, Search, score_listing

ROOT = Path(__file__).resolve().parents[1]
PREFS = ROOT / "tests" / "fixtures" / "prefs_frozen.json"
LIVE = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"
PHOTOS = {"name": "has_photos", "label": "Has photos", "field": "signal:has_photos", "kind": "yes_no", "relevance": 4, "wants": True}


class TestPhotos(unittest.TestCase):
    def setUp(self):
        raw = json.loads(PREFS.read_text(encoding="utf-8"))
        raw["preferences"].append(PHOTOS)
        self.prefs = PreferenceSet.model_validate(raw)
        self.x = json.loads((LIVE / "extracts.json").read_text(encoding="utf-8"))[0]
        self.now = datetime(2026, 10, 24, tzinfo=timezone.utc)

    def score(self, count):
        listing = build_listing(dict(self.x, photo_count=count), self.prefs, routes={}, pulled_at=self.now)
        return listing.signals.get("has_photos"), score_listing(listing, self.prefs)

    def test_none_listed_loses_points_unknown_is_even(self):
        none_sig, none = self.score(0)
        some_sig, some = self.score(6)
        unk_sig, unk = self.score(None)
        self.assertEqual((none_sig.value, some_sig.value, unk_sig), (False, True, None))
        self.assertIn("no photos", none_sig.evidence)
        self.assertLess(none.match_expected, unk.match_expected)
        self.assertLess(unk.match_expected, some.match_expected)
        self.assertEqual(none.excluded, some.excluded)  # a soft criterion: it never hides a listing, only scores it lower
        self.assertFalse(any("photo" in r.lower() for r in none.exclusion_reasons))

    def test_bad_counts_are_ignored(self):
        for bad in (True, -1, "3", 2.5):
            self.assertIsNone(self.score(bad)[0], bad)

    def test_the_card_and_the_setup_page_know_it(self):
        self.assertEqual(server.topic(PreferenceSet.model_validate(dict(json.loads(PREFS.read_text(encoding="utf-8")),
                                                                         preferences=[PHOTOS])).preferences[0], self.prefs)["topic"], "photos")
        self.assertIn("has_photos", [c["name"] for c in setup.CATALOG])


class TestNeighborhoodSearch(unittest.TestCase):
    def test_names_and_centers_are_kept_and_passed_on(self):
        s = Search(label="Tel Aviv (14)", path="/realestate/rent?city=5000", hoods=[205, 848], hood_names=["מרכז העיר", "נווה צדק"],
                   centers=[[205, 32.0565, 34.7705], [848, 32.061, 34.765]])
        raw = json.loads(PREFS.read_text(encoding="utf-8"))
        raw["searches"] = [s.model_dump()]
        cfg = server.config(PreferenceSet.model_validate(raw))
        self.assertEqual(cfg["searches"][0]["hood_names"], ["מרכז העיר", "נווה צדק"])
        self.assertEqual(cfg["searches"][0]["centers"][0], [205, 32.0565, 34.7705])
        with self.assertRaises(ValueError):
            Search(label="x", path="/realestate/rent?city=5000", centers=[[1, "a", 2]])
        old = Search(label="x", path="/realestate/rent?city=5000", hoods=[1])  # a v1.32 search still loads
        self.assertEqual((old.hood_names, old.centers), ([], []))


if __name__ == "__main__":
    unittest.main()
