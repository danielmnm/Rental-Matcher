"""
v1.32: the compare-two tuning (rental_matcher/calibrate.py), the expected
satisfaction it fits (`ScoredListing.sat`), and saving the weights it
suggests (setup.reweigh).
"""

import json
import random
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rental_matcher import calibrate, setup
from rental_matcher.native import answer
from rental_matcher.pipeline import build_listing
from rental_matcher.scoring import PreferenceSet, score_listing

ROOT = Path(__file__).resolve().parents[1]
PREFS = ROOT / "tests" / "fixtures" / "prefs_frozen.json"
LIVE = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"


def _scored():
    prefs = PreferenceSet.load(PREFS)
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    out = []
    for x in json.loads((LIVE / "extracts.json").read_text(encoding="utf-8")):
        try:
            s = score_listing(build_listing(x, prefs, routes={}, pulled_at=now), prefs)
        except ValueError:
            continue
        if s.match_expected is not None and not s.excluded:
            out.append(s)
    return prefs, out


class TestExpectedSatisfaction(unittest.TestCase):
    def test_the_expected_match_is_the_weighted_sum_of_sat(self):
        prefs, scored = _scored()
        self.assertGreater(len(scored), 10)
        for s in scored:
            total = sum(r.weight * s.sat[r.name] for r in s.results if r.weight)
            self.assertAlmostEqual(100 * total, s.match_expected, delta=0.15, msg=s.listing_id)
            self.assertTrue(all(0 <= v <= 1 for v in s.sat.values()))


class TestTune(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefs, cls.scored = _scored()
        cls.names = [p.name for p in cls.prefs.preferences if p.weighted]

    def picks(self, true, n, seed=1):
        """A user whose weights are `true`: picks between listings the current ranking finds close."""
        rnd = random.Random(seed)

        def r(s, w):
            return sum(w[k] * s.sat.get(k, 0.5) for k in self.names) / sum(w.values()) * (1 - (s.fail_risk or 0))
        now = {p.name: p.points for p in self.prefs.preferences if p.weighted}
        cand = [(a, b) for i, a in enumerate(self.scored) for b in self.scored[i + 1:] if abs(r(a, now) - r(b, now)) < 0.08]
        rnd.shuffle(cand)
        return [{"a": {"sat": a.sat, "fail": a.fail_risk}, "b": {"sat": b.sat, "fail": b.fail_risk},
                 "pick": "a" if r(a, true) > r(b, true) else "b"} for a, b in cand[:n]]

    def test_it_learns_what_the_user_cares_about(self):
        true = {p.name: p.points for p in self.prefs.preferences if p.weighted}
        true.update(balcony=10, price=2)  # this user cares about a balcony far more than the rent
        out = calibrate.tune(self.prefs, {"pairs": self.picks(true, 30)})
        self.assertTrue(out["enough"])
        got = {c["name"]: (c["before"], c["after"]) for c in out["criteria"]}
        self.assertGreater(got["balcony"][1], got["balcony"][0])
        self.assertLess(got["price"][1], got["price"][0])
        self.assertGreater(out["held_out"], out["before"])  # better on picks it didn't see
        self.assertTrue(out["suggest"])
        self.assertTrue(all(1 <= c["after"] <= 10 for c in out["criteria"]))

    def test_a_user_the_weights_already_fit_keeps_them(self):
        now = {p.name: p.points for p in self.prefs.preferences if p.weighted}
        out = calibrate.tune(self.prefs, {"pairs": self.picks(now, 20, seed=3)})
        self.assertEqual(out["before"], 1.0)
        self.assertFalse(out["suggest"])  # nothing beats agreeing every time

    def test_too_few_picks_and_bad_input(self):
        out = calibrate.tune(self.prefs, {"pairs": self.picks({n: 5 for n in self.names}, 3)})
        self.assertFalse(out["enough"])
        self.assertFalse(out["suggest"])
        junk = [{"a": {"sat": {"price": "x"}}, "b": {"sat": {}}, "pick": "a"}, {"pick": "same"}, {"a": 1, "b": 2, "pick": "b"}, "x"]
        out = calibrate.tune(self.prefs, {"pairs": junk})
        self.assertEqual(out["picks"], 1)  # only the one with two readable sides; unreadable values count as even
        with self.assertRaises(calibrate.CalibrationError):
            calibrate.tune(self.prefs, {"pairs": "nope"})

    def test_through_the_native_host(self):
        r = answer({"path": "/calibrate", "body": {"pairs": "nope"}}, PREFS)
        self.assertEqual(r["status"], 400)
        r = answer({"path": "/calibrate", "body": {"pairs": []}}, PREFS)
        self.assertEqual((r["status"], r["body"]["picks"]), (200, 0))


class TestReweigh(unittest.TestCase):
    def test_saves_the_weights_with_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "prefs.json"
            p.write_text(PREFS.read_text(encoding="utf-8"), encoding="utf-8")
            r = setup.reweigh(p, {"weights": {"balcony": 9, "price": 3}})
            self.assertTrue(r["saved"])
            raw = json.loads(p.read_text(encoding="utf-8"))
            by = {x["name"]: x for x in raw["preferences"]}
            self.assertEqual((by["balcony"]["weight"], by["price"]["weight"]), (9, 3))
            self.assertEqual(len(list((Path(tmp) / ".backups").glob("*.json"))), 1)
            self.assertEqual(PreferenceSet.load(p).preferences[0].points, 3)
            for bad in ({"weights": {"nope": 3}}, {"weights": {"balcony": 11}}, {"weights": {"balcony": True}}, {"weights": {}}, None):
                with self.assertRaises(setup.SetupError):
                    setup.reweigh(p, bad)


if __name__ == "__main__":
    unittest.main()
