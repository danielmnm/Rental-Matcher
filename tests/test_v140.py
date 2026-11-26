"""v1.40: a must-have is locked in "Teach it your taste": never suggested, never changed."""

import json
import tempfile
import unittest
from pathlib import Path

from rental_matcher import calibrate, setup
from rental_matcher.scoring import PreferenceSet
from tests import test_v132 as v132

PREFS = v132.PREFS


class TestLockedMustHaves(unittest.TestCase):
    setUpClass = classmethod(v132.TestTune.setUpClass.__func__)  # the same listings and simulated picks as v1.32's tests
    picks = v132.TestTune.picks

    def test_must_haves_keep_their_weight_whatever_the_picks(self):
        must = {p.name for p in self.prefs.preferences if p.weighted and p.dealbreaker}
        self.assertEqual(must, {"bike_minutes", "parking"})
        true = {p.name: p.points for p in self.prefs.preferences if p.weighted}
        true.update(bike_minutes=1, parking=10, balcony=10)  # picks that would pull both must-haves far off
        out = calibrate.tune(self.prefs, {"pairs": self.picks(true, 30)})
        for c in out["criteria"]:
            self.assertEqual(c["locked"], c["name"] in must)
            if c["locked"]:
                self.assertEqual(c["after"], c["before"], c["name"])
        self.assertGreater({c["name"]: c["after"] for c in out["criteria"]}["balcony"], 7)  # the rest still learn

    def test_too_few_picks_says_which_are_locked(self):
        out = calibrate.tune(self.prefs, {"pairs": []})
        self.assertEqual({c["name"] for c in out["criteria"] if c["locked"]}, {"bike_minutes", "parking"})


class TestReweighRefusesAMustHave(unittest.TestCase):
    def test_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "prefs.json"
            p.write_text(PREFS.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(setup.SetupError) as e:
                setup.reweigh(p, {"weights": {"bike_minutes": 2}})
            self.assertIn("must-have", str(e.exception))
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), json.loads(PREFS.read_text(encoding="utf-8")))  # nothing saved
            self.assertTrue(setup.reweigh(p, {"weights": {"balcony": 9}})["saved"])
            self.assertEqual({x.name: x.points for x in PreferenceSet.load(p).preferences}["balcony"], 9)


if __name__ == "__main__":
    unittest.main()
