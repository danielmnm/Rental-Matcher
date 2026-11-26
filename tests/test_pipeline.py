"""
The end-to-end path (rental_matcher/pipeline.py) and the commute signal
(rental_matcher/commute.py) it adds.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from rental_matcher.adapters.yad2 import to_listing
from rental_matcher.commute import Commute, certainly_past, commute_signal, minutes, straight_line_km
from rental_matcher.pipeline import build_listing, run
from rental_matcher.schema import ExtractedBy, SignalStatus
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
WORK_PIN = (32.075400, 34.774900)  # example pin (Dizengoff Center)
WHEN = datetime(2026, 10, 20, tzinfo=timezone.utc)


def _x(**over):
    """A Yad2 extract in the adapter's shape; tests override what they need."""
    base = {"id": "t1", "adType": "private", "price": 4200, "floor": 2, "city": "בת ים", "neighborhood": "תל גיבורים",
            "street": "הפרדס", "additionalDetails": {"roomsCount": 3, "squareMeterBuild": 60},
            "inProperty": {"includeAirconditioner": True}, "description": "דירת 3 חדרים עם ממ\"ד, מרפסת וחניה בטאבו",
            "coords": {"lat": 32.03247, "lon": 34.76512}}
    base.update(over)
    return base


class TestCommute(unittest.TestCase):
    EBIKE = Commute(signal="bike_minutes", label="the example work pin", lat=WORK_PIN[0], lng=WORK_PIN[1], mode="ebike")

    def test_a_route_is_confirmed_at_the_users_speed(self):
        s = commute_signal(to_listing(_x(), WHEN), self.EBIKE, routed_km=4.0)
        self.assertEqual((s.status, s.value, s.extracted_by), (SignalStatus.CONFIRMED, 12.0, ExtractedBy.RULE))
        self.assertIn("routed 4.00 km", s.evidence)

    def test_no_route_is_only_an_estimate_and_no_pin_is_nothing(self):
        s = commute_signal(to_listing(_x(), WHEN), self.EBIKE)
        self.assertEqual((s.status, s.value), (SignalStatus.UNCONFIRMED, None))  # a check, never a hide
        self.assertIn("estimate", s.evidence)
        self.assertIsNone(commute_signal(to_listing(_x(coords=None), WHEN), self.EBIKE))
        with self.assertRaises(ValueError):
            commute_signal(to_listing(_x(), WHEN), self.EBIKE, routed_km=-1)

    def test_the_regular_bike_speed_matches_google_on_the_calibration_points(self):
        # Oct 20, from the example work pin: (routed km, Google Maps bike minutes)
        bike = Commute(signal="b", label="x", lat=0, lng=0, mode="bike")
        for km, google in ((3.89, 15), (3.40, 16), (4.37, 19), (6.60, 28)):
            self.assertLessEqual(abs(minutes(km, bike.speed) - google), 2.0, km)

    def test_settings_are_checked(self):
        with self.assertRaises(ValidationError):
            Commute(signal="b", label="x", lat=0, lng=0, mode="scooter")  # car is a mode since v1.20
        with self.assertRaises(ValidationError):
            Commute(signal="b", label="x", lat=0, lng=0, mode="bike", speed_kmh=0)
        data = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
        data["commutes"] = data["commutes"] * 2
        with self.assertRaises(ValidationError):
            PreferenceSet.model_validate(data)

    def test_ebike_commute_to_work_pin(self):
        (c,) = PREFS.commutes
        self.assertEqual((c.signal, c.mode, c.speed, (c.lat, c.lng)), ("bike_minutes", "ebike", 20.0, WORK_PIN))
        self.assertAlmostEqual(straight_line_km(*WORK_PIN, 32.03247, 34.76512), 2.70, places=1)

    def test_the_adapter_keeps_the_pin_and_drops_a_bad_one(self):
        self.assertEqual((to_listing(_x(), WHEN).area.lat, to_listing(_x(), WHEN).area.lng), (32.03247, 34.76512))
        for bad in ({"lat": 0, "lon": 0}, {"lat": 95, "lon": 34.7}, {"lat": True, "lon": 34.7}, {"lat": 32.0}):
            a = to_listing(_x(coords=bad), WHEN).area
            self.assertEqual((a.lat, a.lng), (None, None), bad)


class TestPipeline(unittest.TestCase):
    def test_every_stage_lands_on_the_listing(self):
        x = build_listing(_x(), PREFS, routes={"bike_minutes": {"t1": 3.4}}, pulled_at=WHEN)
        sig = x.signals
        self.assertEqual(sig["bike_minutes"].value, 10.2)  # 3.4 km at 20 km/h
        self.assertEqual(sig["air_conditioning"].value, True)  # the ticked box
        self.assertEqual(sig["parking_level"].value, 3.0)  # the text: "חניה בטאבו"
        # rules-only answers are the rules' (trusted), not mistaken for the model's
        self.assertEqual(sig["protected_space"].extracted_by, ExtractedBy.RULE)

    def test_a_saved_model_answer_is_grounded_again_here(self):
        made_up = {"elevator": {"answer": "yes", "evidence": "יש מעלית"}}  # not in the text
        real = {"elevator": {"answer": "yes", "evidence": "קומה 18"}}
        self.assertNotIn("elevator", build_listing(_x(), PREFS, model=made_up, pulled_at=WHEN).signals)
        x = build_listing(_x(description="דירת 3 חדרים, קומה 18, נוף לים"), PREFS, model=real, pulled_at=WHEN)
        self.assertEqual(x.signals["elevator"].value, True)

    def test_a_pull_ranks_hides_and_skips(self):
        xs = [_x(id="good"), _x(id="ground", floor=0), {"id": "gone", "error": "no item data"}]
        ranked, listings, skipped = run(xs, PREFS, routes={"bike_minutes": {"good": 3.4, "ground": 3.4}}, pulled_at=WHEN)
        self.assertEqual([(s.listing_id, s.excluded) for s in ranked], [("yad2:good", False), ("yad2:ground", True)])
        self.assertEqual(len(listings), 2)
        self.assertEqual(len(skipped), 1)

    def test_too_far_is_hidden_only_on_a_route(self):
        far = [_x(id="far", coords={"lat": 32.06894, "lon": 34.82336})]  # Negba, Ramat Gan
        routed, _, _ = run(far, PREFS, routes={"bike_minutes": {"far": 6.6}}, pulled_at=WHEN)  # 19.8 min
        self.assertTrue(routed[0].excluded)
        guessed, _, _ = run(far, PREFS, pulled_at=WHEN)
        self.assertFalse(guessed[0].excluded)  # an estimate is a check, not a reason to hide
        self.assertTrue(any("estimate" in c for c in guessed[0].checks), guessed[0].checks)

    def test_the_saved_full_listings_run_without_errors(self):
        files = sorted((ROOT / "tests" / "fixtures" / "yad2").glob("*.json")) + sorted((ROOT / "tests" / "fixtures" / "yad2_2026-10-19").glob("*.json"))
        xs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        ranked, listings, skipped = run(xs, PREFS, pulled_at=WHEN)
        self.assertEqual((len(ranked), len(skipped)), (55, 2))  # the two removed listings are skipped, not fatal
        self.assertTrue(all(any("E-bike" in c for c in s.checks) for s in ranked))  # no pins saved: a check each

    def test_a_wants_no_check_answers_the_label(self):
        # "Whole apartment (not a room share): no" read as the opposite of
        # what the AI meant (roommate_listing: no) in the first live run.
        model = {"room_share": {"answer": "no", "evidence": "דירה נחמדה"}}
        ranked, _, _ = run([_x(description="בניין שקט. דירה נחמדה עם ממ\"ד ומרפסת")], PREFS, model_run={"t1": model},
                           routes={"bike_minutes": {"t1": 3.4}}, pulled_at=WHEN)
        check = next(c for c in ranked[0].checks if c.startswith("Whole apartment"))
        self.assertIn("Whole apartment (not a room share): yes (roommate listing: no), read only by the AI", check)


LIVE = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"


class TestLivePull(unittest.TestCase):
    """The first live end-to-end run (Oct 20, 2026): 60 Bat Yam rentals off
    Yad2's search, each item page's facts and description, and a real bike
    route (OSRM, one table request) from the example work pin to each pin.
    Pinned so a change to any stage shows up as a changed result."""

    @classmethod
    def setUpClass(cls):
        cls.xs = json.loads((LIVE / "extracts.json").read_text(encoding="utf-8"))
        cls.routes = json.loads((LIVE / "routes_citycenter38.json").read_text(encoding="utf-8"))
        cls.when = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)

    def test_routed_result(self):
        ranked, _, skipped = run(self.xs, PREFS, routes=self.routes, pulled_at=self.when)
        shown = [s.listing_id.removeprefix("yad2:") for s in ranked if not s.excluded]
        self.assertEqual((len(ranked), len(shown), len(skipped)), (59, 10, 1))  # 3e8quo5i: price 0 (on request)
        # v1.23: ordered by the expected match times the chance every must-have holds
        # v1.28: 9aq4ffmq (floor 4, no elevator stated) is kept only if it has one, and 20 of 20
        # such listings that said didn't: a 96% risk now counts, so it goes last (still shown)
        self.assertEqual(shown, ["7w5nv0p7", "t8n0ghu0", "2a5m0b7a", "idoewwx4", "f9gz3aqq", "clp32ctv", "44gzb3qw", "1dqm0ykv", "igj5zw99", "9aq4ffmq"])
        only_far = [s for s in ranked if s.excluded and all(r.startswith("E-bike") for r in s.exclusion_reasons)]
        self.assertEqual(len(only_far), 12)

    def test_without_routes_distance_never_hides(self):
        ranked, _, _ = run(self.xs, PREFS, pulled_at=self.when)
        self.assertEqual(sum(not s.excluded for s in ranked), 22)
        self.assertFalse(any(r.startswith("E-bike") for s in ranked for r in s.exclusion_reasons))

    def test_the_straight_line_prefilter_only_skips_what_a_route_would_hide(self):
        ebike = PREFS.commutes[0]
        skip = {x["id"] for x in self.xs if certainly_past(x["coords"]["lat"], x["coords"]["lon"], ebike, 15)}
        self.assertEqual(len(skip), 17)
        km = self.routes["bike_minutes"]
        self.assertTrue(all(minutes(km[i], ebike.speed) > 15 for i in skip))  # every skip is past on its real route
        ranked, _, _ = run(self.xs, PREFS, routes=self.routes, pulled_at=self.when)
        shown = {s.listing_id.removeprefix("yad2:") for s in ranked if not s.excluded}
        self.assertFalse(skip & shown)  # skipping them loses nothing the user would see

    def test_a_room_share_the_rules_read_is_hidden(self):
        ranked, _, _ = run(self.xs, PREFS, routes=self.routes, pulled_at=self.when)
        s = next(s for s in ranked if s.listing_id == "yad2:3z89a9tu")  # ₪1,850, a room
        self.assertTrue(any(r.startswith("Whole apartment") for r in s.exclusion_reasons), s.exclusion_reasons)


if __name__ == "__main__":
    unittest.main()
