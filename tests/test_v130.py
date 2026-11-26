"""v1.30: the budget's low end (a minimum rent), and importance on a 1-10 scale."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rental_matcher import funnel, server, setup
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parent.parent
RAW = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
WHEN = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
MIN = {"name": "rent_min", "label": "Minimum rent (ILS)", "field": "price", "kind": "at_least", "relevance": 10, "limit": 3000}


def with_min(**kw):
    raw = copy.deepcopy(RAW)
    raw["preferences"].append(dict(MIN, **kw))
    return raw


class TestMinimumRent(unittest.TestCase):
    def test_search_asks_yad2_for_it(self):
        prefs = PreferenceSet.model_validate(with_min())
        self.assertEqual(funnel.search_filters(prefs), {"maxPrice": "5450", "minPrice": "3000"})
        self.assertNotIn("minPrice", funnel.search_filters(PreferenceSet.model_validate(RAW)))

    def test_too_cheap_is_left_out_and_named(self):
        prefs = PreferenceSet.model_validate(with_min())
        rows = [{"id": "cheap", "price": 2000, "rooms": 3, "size_m2": 70, "floor": 1, "city": "בת ים"},
                {"id": "ok", "price": 4000, "rooms": 3, "size_m2": 70, "floor": 1, "city": "בת ים"}]
        out = server.do_plan({"rows": rows}, prefs)
        self.assertIn("cheap", out["skipped"])
        self.assertNotIn("ok", out["skipped"])
        self.assertEqual(out["skipped_by_topic"].get("rent_min"), 1)
        self.assertEqual(server.pref_table(prefs)["rent_min"]["topic"], "rent_min")

    def test_a_suggestion_can_lower_it(self):
        prefs = PreferenceSet.model_validate(with_min())
        self.assertIn(("rent_min", {"limit": 2750, "by": 250}), server._relaxations(prefs))


class TestImportance(unittest.TestCase):
    def test_ten_is_allowed_and_saved(self):
        raw = copy.deepcopy(RAW)
        next(p for p in raw["preferences"] if p["name"] == "balcony")["weight"] = 10
        self.assertEqual(next(p for p in PreferenceSet.model_validate(raw).preferences if p.name == "balcony").points, 10)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            path.write_text(json.dumps(RAW), encoding="utf-8")
            self.assertTrue(setup.save(path, with_min())["saved"])
            self.assertTrue(setup.save(path, raw)["saved"])
            raw["preferences"][0]["weight"] = 11
            self.assertFalse(setup.save(path, raw)["saved"])


if __name__ == "__main__":
    unittest.main()
