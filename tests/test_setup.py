"""
The setup page's side of the helper (rental_matcher/setup.py, v1.25), the
cards' new parts (features, the must-have risk in words, what's unstated),
and Reject reaching the plan (server.do_plan's skip).
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from rental_matcher import native, setup, traffic
from rental_matcher.scoring import PreferenceSet
from rental_matcher.server import do_plan, do_score

ROOT = Path(__file__).resolve().parents[1]
PREFS = ROOT / "tests" / "fixtures" / "prefs_frozen.json"
LIVE = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"


class TestSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "me.json"
        self.path.write_text(PREFS.read_text(encoding="utf-8"), encoding="utf-8")
        self.data = json.loads(PREFS.read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_valid_file_is_saved_and_the_old_one_kept(self):
        self.data["searches"].append({"source": "yad2", "label": "Tel Aviv", "path": "/realestate/rent?city=5000"})
        r = setup.save(self.path, self.data)
        self.assertTrue(r["saved"])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["searches"][-1]["label"], "Tel Aviv")
        backups = list((self.path.parent / ".backups").glob("me-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), json.loads(PREFS.read_text(encoding="utf-8")))
        PreferenceSet.load(self.path)  # and it loads

    def test_an_invalid_file_is_not_written(self):
        before = self.path.read_text(encoding="utf-8")
        self.data["preferences"][0]["relevance"] = 11
        r = setup.save(self.path, self.data)
        self.assertFalse(r["saved"])
        self.assertTrue(any("relevance" in e for e in r["errors"]), r["errors"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertFalse((self.path.parent / ".backups").exists())

    def test_a_setup_page_field_is_refused(self):
        self.data["preferences"][0]["group"] = "basics"  # the catalog's note must not reach the file
        self.assertFalse(setup.save(self.path, self.data)["saved"])

    def test_saving_the_same_twice_changes_nothing(self):
        setup.save(self.path, self.data)
        r = setup.save(self.path, self.data)
        self.assertEqual((r["saved"], r["unchanged"]), (True, True))

    def test_only_the_last_ten_backups_are_kept(self):
        for i in range(13):
            self.data["note"] = f"edit {i}"
            setup.save(self.path, self.data, now=datetime(2026, 10, 21, 12, 0, i))
        self.assertEqual(len(list((self.path.parent / ".backups").glob("me-*.json"))), setup.KEEP_BACKUPS)

    def test_every_catalog_entry_is_a_valid_preference(self):
        data = dict(self.data, preferences=[{k: v for k, v in t.items() if k != "group"} for t in setup.CATALOG])
        PreferenceSet.model_validate(data)

    def test_the_setup_page_can_read_a_broken_file_to_fix_it(self):
        self.path.write_text("{", encoding="utf-8")
        r = native.answer({"id": 1, "path": "/prefs"}, self.path)
        self.assertEqual(r["status"], 400)
        self.assertIn("isn't valid JSON", r["body"]["error"])
        r = native.answer({"id": 2, "path": "/saveprefs", "body": {"prefs": self.data}}, self.path)
        self.assertTrue(r["body"]["saved"])
        r = native.answer({"id": 3, "path": "/prefs"}, self.path)
        self.assertEqual(r["body"]["prefs"]["owner"], "example")
        self.assertIn("sofa", r["body"]["furniture"])


class TestPlaces(unittest.TestCase):
    def test_tomtom_with_a_key(self):
        asked = []

        def get(url):
            asked.append(url)
            return {"results": [{"position": {"lat": 32.0754001, "lon": 34.7749001},
                                 "address": {"freeformAddress": "Dizengoff 50, Tel Aviv"}, "poi": {"name": "Example Cafe"}}]}

        with mock.patch.object(traffic, "api_key", return_value="KEY"):
            r = setup.places("מרכז העיר 38 תל אביב", get=get)
        self.assertEqual(r, {"source": "TomTom", "places": [{"label": "Example Cafe, Dizengoff 50, Tel Aviv", "lat": 32.075400, "lng": 34.774900}]})
        self.assertIn("countrySet=IL", asked[0])

    def test_openstreetmap_without_a_key(self):
        asked = []

        def get(url):
            asked.append(url)
            return [{"display_name": "50, Dizengoff, Tel Aviv", "lat": "32.0754", "lon": "34.7749"}, {"bad": 1}]

        with mock.patch.object(traffic, "api_key", side_effect=traffic.TrafficError("no key")):
            r = setup.places("Dizengoff 50", nominatim_get=get)
        self.assertEqual(r["source"], "OpenStreetMap")
        self.assertEqual(r["places"], [{"label": "50, Dizengoff, Tel Aviv", "lat": 32.0754, "lng": 34.7749}])
        self.assertIn("countrycodes=il", asked[0])

    def test_nothing_to_look_up(self):
        for q in (None, "", "   ", "x" * 121):
            with self.assertRaises(setup.SetupError):
                setup.places(q, get=lambda u: {}, nominatim_get=lambda u: [])


class TestCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefs = PreferenceSet.load(PREFS)
        cls.xs = json.loads((LIVE / "extracts.json").read_text(encoding="utf-8"))
        cls.out = {r["id"]: r for r in do_score({"extracts": cls.xs}, cls.prefs)["results"]}

    def test_features_say_how_they_sit_with_the_preferences(self):
        f = {d["label"]: d["tone"] for d in self.out["7w5nv0p7"]["features"]}
        self.assertEqual(f["Balcony"], "good")  # wanted, and there
        self.assertEqual(f["Street parking"], "weak")  # within the limit, the least wanted
        self.assertEqual(f["Pets allowed"], "info")  # no preference reads it
        tones = [d["tone"] for d in self.out["7w5nv0p7"]["features"]]
        self.assertEqual(tones, sorted(tones, key=["good", "weak", "bad", "info"].index))

    def test_a_room_share_fails_the_must_have(self):
        bad = [r for r in self.out.values() if any(d["label"] == "Room in a share" for d in r["features"])]
        self.assertTrue(bad)
        self.assertTrue(all(r["excluded"] for r in bad))
        self.assertTrue(all(d["tone"] == "bad" for r in bad for d in r["features"] if d["label"] == "Room in a share"))

    def test_the_risk_and_what_is_unstated_in_words(self):
        r = self.out["t8n0ghu0"]
        self.assertEqual(r["risk_parts"][0]["label"], "Parking")
        self.assertEqual(r["risk_parts"][0]["pct"], 10)
        self.assertIn("Parking", [u["what"] for u in r["unknowns"]])
        balcony = next(r for r in self.out.values() if any(u["what"] == "A balcony" for u in r["unknowns"]))
        self.assertTrue(balcony)


class TestReject(unittest.TestCase):
    def test_a_rejected_listing_is_neither_opened_nor_routed(self):
        prefs = PreferenceSet.load(PREFS)
        rows = json.loads((ROOT / "tests" / "fixtures" / "yad2_search_batyam_2026-10-20" / "rows.json").read_text(encoding="utf-8"))["rows"]
        first = do_plan({"rows": rows}, prefs)
        target = first["fetch"][0]
        again = do_plan({"rows": rows, "skip": [target]}, prefs)
        self.assertNotIn(target, again["fetch"])
        self.assertEqual(again["skipped"][target], ["You rejected it"])
        self.assertEqual(again["skipped_by_reason"].get("You rejected it"), 1)
        self.assertEqual(again["rows"], first["rows"])

    def test_skip_must_be_ids(self):
        from rental_matcher.server import BadRequest
        with self.assertRaises(BadRequest):
            do_plan({"rows": [{"id": "a"}], "skip": "a"}, PreferenceSet.load(PREFS))


if __name__ == "__main__":
    unittest.main()


class TestV126(unittest.TestCase):
    """The match without a must-have's weight, cards as data, and ways to see more."""

    @classmethod
    def setUpClass(cls):
        cls.prefs = PreferenceSet.load(PREFS)
        cls.raw = json.loads(PREFS.read_text(encoding="utf-8"))
        cls.xs = json.loads((LIVE / "extracts.json").read_text(encoding="utf-8"))
        cls.rows = json.loads((ROOT / "tests" / "fixtures" / "yad2_search_batyam_2026-10-20" / "rows.json").read_text(encoding="utf-8"))["rows"]
        cls.out = {r["id"]: r for r in do_score({"extracts": cls.xs}, cls.prefs)["results"]}

    def test_a_must_have_counts_only_by_its_gradient(self):
        p = {x.name: x for x in self.prefs.preferences}
        self.assertEqual(p["parking"].points, 5)  # ranged must-have: 5, not its relevance 10
        self.assertEqual(p["mamad"].points, 0)  # yes/no must-have: a pure filter
        self.assertEqual(p["balcony"].points, 7)  # nice-to-have: its relevance
        weighted = dict(self.raw)
        weighted["preferences"] = [dict(q, weight=9) if q["name"] == "mamad" else q for q in self.raw["preferences"]]
        self.assertEqual({x.name: x for x in PreferenceSet.model_validate(weighted).preferences}["mamad"].points, 9)

    def test_notes_say_what_each_check_is_about(self):
        r = self.out["7w5nv0p7"]
        floor = next(n for n in r["notes"] if n["name"] == "floor_without_elevator")
        self.assertEqual((floor["kind"], floor["reason"], floor["value"], floor["needs"]), ("check", "needs", 3.0, ["elevator"]))
        hidden = next(r for r in self.out.values() if r["excluded"] and any(n["name"] == "price" for n in r["notes"]))
        price = next(n for n in hidden["notes"] if n["name"] == "price")
        self.assertEqual((price["kind"], price["reason"]), ("exclude", "past"))
        self.assertEqual(len(r["notes"]), len(r["checks"]) + len(r["flags"]) + len(r["reasons"]))

    def test_ask_about_the_fact_not_the_budget_it_moves(self):
        r = next(r for r in self.out.values() if any("balcony" in a["signals"] for a in r["asks"]))
        a = next(a for a in r["asks"] if "balcony" in a["signals"])
        self.assertIn("price", a["names"])  # it moves the budget too
        self.assertEqual(a["about"], ["balcony"])  # but what to ask about is the balcony

    def test_the_card_needs_no_english(self):
        from rental_matcher.server import config
        table = config(self.prefs)["prefs"]
        self.assertEqual(table["bike_minutes"]["topic"], "commute")
        self.assertEqual(table["floor_without_elevator"]["topic"], "floor_high")
        self.assertEqual(table["not_ground_floor"]["topic"], "floor_ground")
        r = self.out["t8n0ghu0"]
        self.assertTrue(all("key" in f and "tone" in f for f in r["feature_keys"]))
        self.assertEqual(r["trips"][0]["place"], "the example work pin")
        self.assertIn(r["fit"], ("great", "good", "fair", "basic"))

    def test_left_out_by_topic(self):
        out = do_plan({"rows": self.rows, "skip": [self.rows[0]["id"]]}, self.prefs)
        by = out["skipped_by_topic"]
        self.assertEqual(sum(by.values()), len(out["skipped"]))
        self.assertEqual(by.get("rejected"), 1)
        self.assertIn("price", by)

    def test_ways_to_see_more_are_counted_by_the_same_funnel(self):
        from rental_matcher.server import do_suggest
        out = do_suggest({"rows": self.rows, "extracts": self.xs}, self.prefs, self.raw)["suggestions"]
        self.assertTrue(out)
        self.assertLessEqual(len(out), 4)
        self.assertEqual([s["count"] for s in out], sorted((s["count"] for s in out), reverse=True))
        rent = next(s for s in out if s["topic"] == "rent")
        self.assertEqual(rent["change"], {"limit": rent["now"]})
        self.assertEqual(rent["count"], rent["to_check"] + rent["shown"])

    def test_applying_a_suggestion_loosens_that_one_preference(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "me.json"
            path.write_text(PREFS.read_text(encoding="utf-8"), encoding="utf-8")
            r = setup.relax(path, {"name": "price", "change": {"limit": 4750, "by": 250}})
            self.assertTrue(r["saved"])
            new = json.loads(path.read_text(encoding="utf-8"))
            price = next(p for p in new["preferences"] if p["name"] == "price")
            self.assertEqual(price["limit"], 4750)
            self.assertEqual(price["overrides"][0]["limit"], 5250)  # the budget with a balcony moves with it
            others = [p for p in new["preferences"] if p["name"] != "price"]
            self.assertEqual(others, [p for p in json.loads(PREFS.read_text(encoding="utf-8"))["preferences"] if p["name"] != "price"])
            with self.assertRaises(setup.SetupError):
                setup.relax(path, {"name": "nope", "change": {"limit": 1}})
