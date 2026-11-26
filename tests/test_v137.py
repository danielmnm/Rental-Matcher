"""v1.37: a drive as a range (the usual time and rush hour's), read from the evidence commute.py writes."""

import unittest
from types import SimpleNamespace

from rental_matcher.commute import CAR_PEAK_X, CAR_TYPICAL_X, Commute, Drive, _car_signal, car_times
from rental_matcher.server import _commute_list


class TestCarTimes(unittest.TestCase):
    def setUp(self):
        self.c = Commute(signal="car_minutes", label="hit (Bat Yam)", lat=32.01, lng=34.77, mode="car")
        self.listing = SimpleNamespace(id="x")

    def test_tomtom_typical_and_rush_hour(self):
        s = _car_signal(self.listing, self.c, Drive(free_flow_s=900, typical_s=24 * 60, peak_s=41 * 60))
        self.assertEqual(car_times(s.evidence), {"usual": 24, "worst": 41, "estimate": False})
        self.assertEqual(s.value, 41.0)  # the score still reads the hour the user commutes (rush hour)

    def test_estimate_from_the_no_traffic_drive(self):
        s = _car_signal(self.listing, self.c, Drive(free_flow_s=15 * 60))
        got = car_times(s.evidence)
        self.assertTrue(got["estimate"])
        self.assertEqual(got["worst"], round(15 * CAR_PEAK_X[1]))  # the top of the rush-hour range
        self.assertEqual(got["usual"], round((round(15 * CAR_TYPICAL_X[0]) + round(15 * CAR_TYPICAL_X[1])) / 2))
        self.assertLess(got["usual"], got["worst"])

    def test_anything_else_is_none(self):
        for ev in (None, "", "routed 3.2 km, ebike at 20 km/h: 10 min", "not routed; estimate from the map: about 20 min"):
            self.assertIsNone(car_times(ev))

    def test_the_card_gets_both(self):
        s = _car_signal(self.listing, self.c, Drive(free_flow_s=15 * 60))
        x = SimpleNamespace(signals={"car_minutes": s})
        prefs = SimpleNamespace(commutes=[self.c])
        trip = _commute_list(x, prefs)[0]
        self.assertEqual((trip["mode"], trip["estimate"]), ("car", True))
        self.assertEqual(trip["about"], trip["usual"])  # the one number, where only one fits, is the usual drive
        self.assertGreater(trip["worst"], trip["usual"])


if __name__ == "__main__":
    unittest.main()
