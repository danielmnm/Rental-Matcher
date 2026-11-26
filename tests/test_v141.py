"""v1.41: "Neither" in Teach it your taste teaches the fit instead of rejecting listings."""

import unittest

from rental_matcher import calibrate
from tests import test_v132 as v132


def side(price, balcony):
    return {"sat": {"price": price, "balcony": balcony}, "fail": 0}


class TestNeitherTeaches(unittest.TestCase):
    def test_both_rank_below_the_pick_before_them(self):
        good, a, b = side(0.9, 1.0), side(0.2, 0.0), side(0.3, 0.0)
        raw = [{"a": good, "b": side(0.5, 0.5), "pick": "a"}, {"a": a, "b": b, "pick": "neither"}, {"a": a, "b": b, "pick": "same"}]
        got = calibrate._pairs(raw, ["price", "balcony"])
        self.assertEqual(len(got), 3)  # the pick, and each side of "Neither" against it; "Can't decide" says nothing
        for sa, _, sb, _, y in got[1:]:
            self.assertEqual((sa, y), ([0.9, 1.0], 1.0))
        self.assertEqual([g[2] for g in got[1:]], [[0.2, 0.0], [0.3, 0.0]])

    def test_neither_first_uses_the_first_pick_after_it(self):
        raw = [{"a": side(0.1, 0.1), "b": side(0.2, 0.2), "pick": "neither"}, {"a": side(0.4, 0.4), "b": side(0.8, 0.9), "pick": "b"}]
        got = calibrate._pairs(raw, ["price", "balcony"])
        self.assertEqual([g[0] for g in got[1:]], [[0.8, 0.9], [0.8, 0.9]])

    def test_no_pick_at_all_teaches_nothing(self):
        self.assertEqual(calibrate._pairs([{"a": side(0.1, 0.1), "b": side(0.2, 0.2), "pick": "neither"}], ["price", "balcony"]), [])

    def test_it_counts_in_the_fit(self):
        prefs, scored = v132._scored()
        ok = [s for s in scored if s.sat]
        picks = [{"a": {"sat": x.sat, "fail": x.fail_risk}, "b": {"sat": y.sat, "fail": y.fail_risk}, "pick": "a"} for x, y in zip(ok[:6], ok[6:12])]
        neither = [{"a": {"sat": x.sat, "fail": x.fail_risk}, "b": {"sat": y.sat, "fail": y.fail_risk}, "pick": "neither"} for x, y in zip(ok[12:14], ok[14:16])]
        self.assertEqual(calibrate.tune(prefs, {"pairs": picks})["picks"], 6)
        self.assertEqual(calibrate.tune(prefs, {"pairs": picks + neither})["picks"], 10)  # 2 x 2 more comparisons


if __name__ == "__main__":
    unittest.main()
