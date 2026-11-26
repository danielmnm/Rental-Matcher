"""v1.34: fixes from a code review of v1.33 (the Python side; the extension's are in browser/*.test.js)."""

import random
import time
import unittest
from pathlib import Path

from rental_matcher import calibrate
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]


class TestCalibrateScale(unittest.TestCase):
    def test_many_picks_stay_quick_and_use_the_latest(self):
        prefs = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
        names = [p.name for p in prefs.preferences if p.weighted]
        rnd = random.Random(0)
        pairs = [{"a": {"sat": {n: rnd.random() for n in names}}, "b": {"sat": {n: rnd.random() for n in names}}, "pick": rnd.choice("ab")}
                 for _ in range(200)]
        t0 = time.time()
        out = calibrate.tune(prefs, {"pairs": pairs})
        self.assertLess(time.time() - t0, 10)  # was leave-one-out over every pick: minutes, with the helper busy
        self.assertEqual(out["picks"], calibrate.MAX_PICKS)
        self.assertTrue(0 <= out["held_out"] <= 1)


if __name__ == "__main__":
    unittest.main()
