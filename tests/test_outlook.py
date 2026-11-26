"""
The match as one honest number (v1.23): the expected match from measured
odds for what a listing leaves unstated (rental_matcher/priors.py), the
likely range around it, the chance a must-have fails, and what each
unknown is worth.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rental_matcher import priors
from rental_matcher.adapters.yad2 import to_listing
from rental_matcher.pipeline import build_listing, run
from rental_matcher.scoring import PreferenceSet, score_listing

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
WHEN = datetime(2026, 10, 20, 20, tzinfo=timezone.utc)


def _x(**over):
    base = {"id": "o1", "adType": "private", "price": 4200, "floor": 1, "city": "בת ים",
            "additionalDetails": {"roomsCount": 3, "squareMeterBuild": 70, "propertyCondition": {"id": 2}},
            "inProperty": {"includeAirconditioner": True, "includeSecurityRoom": True, "includeParking": True,
                           "includeBalcony": True, "includeElevator": True, "isImmediateEntrance": True},
            "description": "דירת 3 חדרים עם ממ\"ד, מעלית, מרפסת וחניה בטאבו, ספה ומקרר", "coords": {"lat": 32.03247, "lon": 34.76512}}
    base.update(over)
    return base


ROUTES = {"bike_minutes": {"o1": 3.4}}


class TestPriors(unittest.TestCase):
    def test_the_stored_odds_are_a_fresh_measurement(self):
        stored = json.loads(priors.STORED.read_text(encoding="utf-8"))
        self.assertEqual(stored, json.loads(json.dumps(priors.measure())))
        self.assertEqual(stored["listings"], 233)

    def test_what_they_say(self):
        p = dict((s, dict(d)) for s, d in priors.load().items())
        self.assertAlmostEqual(p["elevator"][True], 0.0455)  # 0 of 20: an unmentioned elevator is rarely there
        self.assertAlmostEqual(p["balcony"][True], 0.4375)  # 6 of 14 (a service balcony doesn't count)
        self.assertAlmostEqual(p["roommate_listing"][True], 0.0133)  # 2 of 224: room shares say so
        self.assertAlmostEqual(sum(p["parking_level"].values()), 1.0, places=3)
        self.assertEqual(priors.sample_sizes()["protected_space"], 3)  # small, and it says so


class TestOutlook(unittest.TestCase):
    def test_everything_known_is_one_number(self):
        s = score_listing(build_listing(_x(), PREFS, routes=ROUTES, pulled_at=WHEN), PREFS)
        self.assertFalse(s.excluded)
        self.assertEqual(s.unknowns, [])
        self.assertEqual(s.match_low, s.match_high)
        self.assertEqual((s.match_expected, s.match_likely_low, s.match_likely_high), (s.match_low,) * 3)
        self.assertEqual(s.fail_risk, 0.0)

    def test_an_unmentioned_elevator_is_probably_not_there(self):
        ip = dict(_x()["inProperty"])
        del ip["includeElevator"]
        s = score_listing(build_listing(_x(inProperty=ip, description="דירת 3 חדרים עם ממ\"ד, מרפסת וחניה בטאבו, ספה ומקרר"),
                                        PREFS, routes=ROUTES, pulled_at=WHEN), PREFS)
        (u,) = s.unknowns
        self.assertEqual((u.labels, u.n), (["Elevator"], 20))
        w = u.worth
        self.assertAlmostEqual(s.match_expected, s.match_low + w * 0.0455, delta=0.11)  # not low + w/2 (each is rounded to 0.1)
        self.assertLess(s.match_expected - s.match_low, w / 4)

    def test_a_balcony_moves_the_budget_with_it(self):
        ip = dict(_x()["inProperty"])
        del ip["includeBalcony"]
        x = _x(price=4900, inProperty=ip, description="דירת 3 חדרים עם ממ\"ד, מעלית וחניה בטאבו, ספה ומקרר")
        s = score_listing(build_listing(x, PREFS, routes=ROUTES, pulled_at=WHEN), PREFS)
        (u,) = s.unknowns  # one unknown: the balcony and the budget it raises move together
        self.assertEqual(sorted(u.labels), ["Balcony", "Monthly rent (ILS)"])
        self.assertEqual(u.n, 14)
        self.assertEqual((s.match_likely_low, s.match_likely_high), (s.match_low, s.match_high))  # 44/56: both ends likely

    def test_an_unstated_must_have_is_a_risk_not_a_hide(self):
        ip = dict(_x()["inProperty"])
        del ip["includeSecurityRoom"]
        s = score_listing(build_listing(_x(inProperty=ip, description="דירת 3 חדרים, מעלית, מרפסת וחניה בטאבו, ספה ומקרר"),
                                        PREFS, routes=ROUTES, pulled_at=WHEN), PREFS)
        self.assertFalse(s.excluded)
        self.assertAlmostEqual(s.fail_risk, 0.2)  # 1 in 5 like it don't have one (n=3: small)
        self.assertTrue(s.fail_risk_from[0].startswith("Bomb shelter"))
        self.assertAlmostEqual(s.rank_value, s.match_expected * 0.8)

    def test_unclear_gets_even_odds_not_the_measured_ones(self):
        x = _x(description="דירת 3 חדרים עם ממ\"ד, מרפסת וחניה בטאבו, ספה ומקרר. מעלית: לא בטוח")
        ip = dict(x["inProperty"])
        del ip["includeElevator"]
        listing = build_listing({**x, "inProperty": ip}, PREFS, routes=ROUTES, pulled_at=WHEN)
        listing.signals["elevator"] = listing.signals.get("elevator") or None
        from rental_matcher.schema import ExtractedBy, Signal, SignalStatus
        listing.signals["elevator"] = Signal(status=SignalStatus.UNCONFIRMED, evidence="מעלית: לא בטוח", extracted_by=ExtractedBy.RULE)
        s = score_listing(listing, PREFS)
        (u,) = s.unknowns
        self.assertIsNone(u.odds)
        self.assertAlmostEqual(s.match_expected, s.match_low + u.worth / 2, delta=0.11)

    def test_the_condition_says_renovated_or_not(self):
        for cid, want in ((2, True), (1, True), (6, True), (3, False), (5, False)):
            sig = to_listing(_x(additionalDetails={"roomsCount": 3, "propertyCondition": {"id": cid}}), WHEN).signals["renovated"]
            self.assertEqual(sig.value, want, cid)
        boxed = to_listing(_x(additionalDetails={"propertyCondition": {"id": 3}}, inProperty={"isRenovated": True}), WHEN)
        self.assertIs(boxed.signals["renovated"].value, True)  # a ticked box is a direct claim: it wins


class TestOnRealListings(unittest.TestCase):
    def test_the_likely_range_is_much_narrower(self):
        live = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"
        xs = json.loads((live / "extracts.json").read_text(encoding="utf-8"))
        routes = json.loads((live / "routes_citycenter38.json").read_text(encoding="utf-8"))
        shown = [s for s in run(xs, PREFS, routes=routes, pulled_at=WHEN)[0] if not s.excluded]
        old = sum(s.match_high - s.match_low for s in shown) / len(shown)
        new = sum(s.match_likely_high - s.match_likely_low for s in shown) / len(shown)
        self.assertLess(new, 0.75 * old, (old, new))
        for s in shown:
            self.assertLessEqual(s.match_low, s.match_likely_low)
            self.assertLessEqual(s.match_likely_low, s.match_expected)
            self.assertLessEqual(s.match_expected, s.match_likely_high)
            self.assertLessEqual(s.match_likely_high, s.match_high)
            self.assertEqual([u.worth for u in s.unknowns], sorted((u.worth for u in s.unknowns), reverse=True))


if __name__ == "__main__":
    unittest.main()
