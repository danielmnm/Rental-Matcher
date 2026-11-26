"""Phase 3, step 1: a new area and a new commute destination by settings alone, no code.

The claim (owner ruling, Nov 7): the tool already works for any area. The held-out batches pulled listings from 54 cities
without a code change; this pins it as a test, so it stays true. Kiryat Shmona is used because no code file names it:
its listings (batch 14) are scored against a search for it and a second commute destination, both added only to the
settings file.
"""
import copy
import json
import re
import unittest
from pathlib import Path

from rental_matcher import server
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
CITY = "קרית שמונה"


def _settings():
    raw = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
    raw = copy.deepcopy(raw)
    raw["searches"] = [{"source": "yad2", "label": "Kiryat Shmona", "label_he": CITY, "path": "/realestate/rent?city=2800"}]
    raw["commutes"].append({"signal": "car_minutes_telhai", "label": "Tel-Hai College", "lat": 33.2353, "lng": 35.5806,
                            "mode": "car", "at": "peak"})
    raw["preferences"].append({"name": "telhai", "label": "Drive to Tel-Hai College (min)", "field": "signal:car_minutes_telhai",
                               "kind": "ranged", "relevance": 6, "ideal": 10, "limit": 25})
    return PreferenceSet.model_validate(raw)


class TestANewAreaBySettingsAlone(unittest.TestCase):
    def test_no_code_names_the_city(self):
        code = [p for p in (ROOT / "rental_matcher").rglob("*.py")] + [p for p in (ROOT / "browser").glob("*.js")]
        for p in code:
            self.assertNotIn(CITY, p.read_text(encoding="utf-8"), p.name)
        cities = json.loads((ROOT / "browser" / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
        self.assertIn(CITY, {c[1] for c in cities})  # it is offered in setup, from the official list (data, not code)

    def test_its_listings_score_with_a_second_commute(self):
        prefs = _settings()
        self.assertEqual([c.signal for c in prefs.commutes], ["bike_minutes", "car_minutes_telhai"])
        fx = ROOT / "tests" / "fixtures" / "yad2_holdout14_2026-11-06"
        extracts = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(fx.glob("*.json"))]
        extracts = [x for x in extracts if x.get("city") == CITY]
        self.assertGreaterEqual(len(extracts), 25)
        out = server.do_score({"extracts": extracts}, prefs)
        self.assertEqual(len(out["results"]), len(extracts))
        self.assertFalse(out.get("skipped"))
        # the new destination is part of every card: an answer, or a check that names it ("not stated" without a pin)
        for r in out["results"]:
            said = json.dumps(r, ensure_ascii=False)
            self.assertTrue(re.search(r"Tel-Hai College", said), r.get("id"))


if __name__ == "__main__":
    unittest.main()


class TestTheGraderReadsEachSitesOwnForm(unittest.TestCase):
    """v1.62: the card test reads a listing's form through its own site's adapter (Komo's feature list for a Komo
    listing), as the product does; it used to send every extract through Yad2's."""

    def test_a_komo_listing(self):
        from rental_matcher.extraction.card_eval import box_facts, site_listing
        item = json.loads((ROOT / "tests" / "fixtures" / "sites_2026-10-22" / "parsed.json").read_text(encoding="utf-8"))["komo_item"]
        listing = site_listing(item)
        self.assertEqual(listing.source.value, "komo")
        boxes = box_facts(item)
        ticked = {k for k, v in (item.get("ticked") or {}).items() if v}
        if "mamad" in ticked:
            self.assertEqual(boxes.get("protected_space"), {"yes"})
        if "air_conditioning" in ticked:
            self.assertEqual(boxes.get("air_conditioning"), {"yes"})

    def test_an_unknown_site_is_refused(self):
        from rental_matcher.extraction.card_eval import site_listing
        with self.assertRaises(ValueError):
            site_listing({"id": "x1", "source": "craigslist", "price": 4000})
