"""
The funnel (rental_matcher/funnel.py), car commutes and typical traffic
(commute.py, traffic.py).
"""

import io
import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from rental_matcher.adapters.yad2 import to_listing
from rental_matcher.commute import Commute, Drive, commute_signal, lower_bound_minutes
from rental_matcher.funnel import NOT_HOMES, plan, price_cap, row_extract, search_filters, wait_seconds
from rental_matcher.schema import SignalStatus
from rental_matcher.scoring import PreferenceSet
from rental_matcher import traffic

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
WHEN = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)
WORK = (32.075400, 34.774900)
CAR = Commute(signal="commute_minutes", label="work", lat=WORK[0], lng=WORK[1], mode="car")


def _row(**over):
    base = {"id": "r1", "adType": "private", "price": 4200, "floor": 2, "lat": 32.02232, "lng": 34.78094,
            "rooms": 3, "size_m2": 70, "property": "דירה", "city": "בת ים"}
    base.update(over)
    return base


def _driver_prefs(limit=30, at="peak"):
    data = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
    data["commutes"] = [{"signal": "commute_minutes", "label": "work", "lat": WORK[0], "lng": WORK[1], "mode": "car", "at": at}]
    for p in data["preferences"]:
        if p["name"] == "bike_minutes":
            p.update(name="commute_minutes", label="Drive to work (min)", field="signal:commute_minutes", limit=limit)
    return PreferenceSet.model_validate(data)


class TestCar(unittest.TestCase):
    def _listing(self):
        return to_listing({"id": "c1", "adType": "private", "price": 4200, "coords": {"lat": 32.02232, "lon": 34.78094}}, WHEN)

    def test_typical_traffic_is_the_signal_at_the_users_hour(self):
        d = Drive(free_flow_s=540, typical_s=780, peak_s=1260, source="TomTom typical traffic, departing 08:00 and 11:00")
        s = commute_signal(self._listing(), CAR, d)
        self.assertEqual((s.status, s.value), (SignalStatus.CONFIRMED, 21.0))  # rush hour by default
        self.assertIn("about 13 min in typical traffic, 21 min at rush hour", s.evidence)
        self.assertIn("an estimate", s.evidence)
        off_peak = Commute(**{**CAR.model_dump(), "at": "typical"})
        self.assertEqual(commute_signal(self._listing(), off_peak, d.model_dump()).value, 13.0)

    def test_free_flow_alone_is_a_check(self):
        s = commute_signal(self._listing(), CAR, {"free_flow_s": 529})  # 8.8 min on an empty road
        self.assertEqual((s.status, s.value), (SignalStatus.UNCONFIRMED, None))
        self.assertIn("traffic not checked; roughly 12-19 min in typical traffic, 19-26 at rush hour", s.evidence)
        self.assertIn("9 min with no traffic", s.evidence)

    def test_a_bad_drive_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            commute_signal(self._listing(), CAR, {"typical_s": 600})  # no peak, no free flow
        with self.assertRaises(ValueError):
            commute_signal(self._listing(), CAR, 5.2)  # a bike distance where a drive belongs

    def test_lower_bounds(self):
        bike = Commute(signal="b", label="x", lat=WORK[0], lng=WORK[1], mode="ebike")
        self.assertEqual(lower_bound_minutes(None, None, bike, 5.0), 15.0)  # a route is exact
        self.assertGreater(lower_bound_minutes(32.02232, 34.78094, bike), 0)  # the straight line bounds it
        self.assertAlmostEqual(lower_bound_minutes(None, None, CAR, {"free_flow_s": 1200}), 18.0)  # 20 min x 0.9
        self.assertIsNone(lower_bound_minutes(32.0, 34.7, CAR))  # no drive: no bound for a car

    def test_rush_hour_hides_free_flow_never_does(self):
        prefs = _driver_prefs(limit=25)
        from rental_matcher.pipeline import run
        x = [{"id": "a", "adType": "private", "price": 4200, "floor": 2, "coords": {"lat": 32.02232, "lon": 34.78094},
              "additionalDetails": {"squareMeterBuild": 70}, "description": "דירה עם ממ\"ד ומרפסת"}]
        slow = {"commute_minutes": {"a": {"free_flow_s": 600, "typical_s": 1000, "peak_s": 1800}}}  # 30 min at rush hour
        self.assertTrue(run(x, prefs, routes=slow, pulled_at=WHEN)[0][0].excluded)
        light = {"commute_minutes": {"a": {"free_flow_s": 1600}}}  # 27 min on an empty road: past 25 only x0.9 = 24
        ranked = run(x, prefs, routes=light, pulled_at=WHEN)[0]
        self.assertFalse(ranked[0].excluded)
        self.assertTrue(any("no traffic" in c for c in ranked[0].checks), ranked[0].checks)


class TestTraffic(unittest.TestCase):
    REPLY = {"routes": [{"summary": {"lengthInMeters": 6400, "travelTimeInSeconds": 1300, "noTrafficTravelTimeInSeconds": 560,
                                     "historicTrafficTravelTimeInSeconds": 1250}}]}

    def test_two_departures_make_one_drive(self):
        calls = []

        def get(url):
            calls.append(url)
            r = json.loads(json.dumps(self.REPLY))
            if "T11:00" in url:
                r["routes"][0]["summary"]["historicTrafficTravelTimeInSeconds"] = 800
            return r

        d = traffic.drive((32.02, 34.78), WORK, "KEY", peak_at="2026-10-27T08:00:00", typical_at="2026-10-27T11:00:00", get=get)
        self.assertEqual((d["km"], d["free_flow_s"], d["peak_s"], d["typical_s"]), (6.4, 560.0, 1250.0, 800.0))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("computeTravelTimeFor=all" in u and "travelMode=car" in u for u in calls))
        Drive.model_validate(d)  # it's what commute.py reads

    def test_errors_never_carry_the_key(self):
        def get(url):
            raise traffic.TrafficError("TomTom HTTP 403")

        out, errors = traffic.drives({"a": [32.0, 34.7]}, WORK, "SECRET-KEY", peak_at="x", typical_at="y", get=get, pause=0)
        self.assertEqual(out, {})
        self.assertNotIn("SECRET-KEY", json.dumps(errors))

    def test_a_real_http_error_never_carries_the_key(self):
        import io
        import urllib.error
        from unittest import mock
        url = traffic.route_url((32.0, 34.7), WORK, "2026-10-27T08:00:00", "SECRET-KEY")

        def refuse(u, timeout=None):
            raise urllib.error.HTTPError(u, 403, f"Forbidden {u}", {}, io.BytesIO(b"bad key SECRET-KEY"))

        with mock.patch("urllib.request.urlopen", refuse):
            with self.assertRaises(traffic.TrafficError) as e:
                traffic._http_get(url)
        self.assertNotIn("SECRET-KEY", str(e.exception))
        self.assertTrue(e.exception.__suppress_context__)  # "from None": the HTTPError (and its URL) isn't chained

    def test_next_departure_is_the_coming_weekday(self):
        self.assertEqual(traffic.next_departure("tue", "08:00", today=date(2026, 10, 20)), "2026-10-27T08:00:00")  # a Tuesday: next week's
        self.assertEqual(traffic.next_departure("sun", "17:30", today=date(2026, 10, 20)), "2026-10-25T17:30:00")

    def test_a_bike_route_is_its_length_at_the_riders_speed(self):
        urls = []

        def get(url):
            urls.append(url)
            return {"routes": [{"summary": {"lengthInMeters": 4730, "travelTimeInSeconds": 1150}}]}

        out, errors = traffic.bikes({"a": [32.02, 34.78]}, WORK, "KEY", get=get, pause=0)
        self.assertEqual((out, errors), ({"a": {"km": 4.73, "tomtom_s": 1150.0}}, {}))
        self.assertIn("travelMode=bicycle&traffic=false", urls[0])
        self.assertNotIn("departAt", urls[0])  # no traffic for a bike: one request, no hour
        # the same route, two riders: the speed is the user's, not TomTom's
        listing = to_listing({"id": "b1", "adType": "private", "price": 4200, "coords": {"lat": 32.02, "lon": 34.78}}, WHEN)
        for mode, minutes_ in (("bike", 20.3), ("ebike", 14.2)):
            c = Commute(signal="bike_minutes", label="work", lat=WORK[0], lng=WORK[1], mode=mode)
            self.assertEqual(commute_signal(listing, c, routed_km=out["a"]["km"]).value, minutes_)
        bad, errors = traffic.bikes({"b": [32.0, 34.7]}, WORK, "SECRET-KEY", get=lambda u: {"routes": [{"summary": {}}]}, pause=0)
        self.assertEqual((bad, errors), ({}, {"b": "TomTom reply has no route length"}))

    def test_the_command_writes_what_the_pipeline_reads(self):
        import os
        import tempfile
        from unittest import mock
        replies = {"bicycle": {"routes": [{"summary": {"lengthInMeters": 3400, "travelTimeInSeconds": 900}}]},
                   "car": self.REPLY}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"TOMTOM_API_KEY": "SECRET-KEY"}), \
                mock.patch.object(traffic, "_http_get", lambda u: replies["bicycle" if "travelMode=bicycle" in u else "car"]), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as said:
            pins = Path(d) / "pins.json"
            pins.write_text(json.dumps({"a": [32.02, 34.78]}), encoding="utf-8")
            for mode in ("bicycle", "car"):
                traffic.main([str(pins), "--to", "32.075400,34.774900", "--mode", mode, "--out", str(Path(d) / f"{mode}.json")])
            bike_out = json.loads((Path(d) / "bicycle.json").read_text(encoding="utf-8"))
            car_out = json.loads((Path(d) / "car.json").read_text(encoding="utf-8"))
            written = (Path(d) / "bicycle.json").read_text(encoding="utf-8") + (Path(d) / "car.json").read_text(encoding="utf-8")
        self.assertEqual(bike_out, {"bike_minutes": {"a": 3.4}, "_tomtom_bicycle_s": {"a": 900.0}})
        self.assertEqual(set(car_out), {"commute_minutes"})
        self.assertEqual(said.getvalue(), "1 bike routes, 0 errors\n1 drives, 0 errors\n")
        self.assertNotIn("SECRET-KEY", written + said.getvalue())

    def test_the_key_file_is_gitignored(self):
        self.assertIn(".tomtom_key", (ROOT / ".gitignore").read_text(encoding="utf-8").split())


class TestFunnel(unittest.TestCase):
    def test_price_cap_and_server_filters(self):
        self.assertEqual(price_cap(PREFS), 5450)  # 5,000 with a balcony + 450 tolerance
        self.assertEqual(search_filters(PREFS), {"maxPrice": "5450"})

    def test_a_row_reads_like_its_page(self):
        x = to_listing(row_extract(_row()), WHEN)
        self.assertEqual((x.price.amount, x.floor, x.size_m2, x.rooms, x.area.lat), (4200, 2, 70, 3, 32.02232))

    def test_only_certain_hides_are_skipped(self):
        rows = [_row(id="ok"), _row(id="ground", floor=0), _row(id="tiny", size_m2=30), _row(id="dear", price=6000),
                _row(id="nofloor", floor=None), _row(id="nosize", size_m2=None), _row(id="store", property="מחסן"),
                _row(id="noprice", price=0), _row(id="ok")]  # a repeat (Yad2 shows promoted ones twice)
        p = plan(rows, PREFS, pulled_at=WHEN)
        self.assertEqual(p.rows, 8)
        self.assertEqual(set(p.skipped), {"ground", "tiny", "dear", "store", "noprice"})
        self.assertEqual(set(p.fetch), {"ok", "nofloor", "nosize"})  # unknown is never a reason to skip
        self.assertIn("store", [k for k, v in p.skipped.items() if v[0].startswith("not a home")])

    def test_too_far_by_route_or_by_straight_line(self):
        far = [_row(id="far", lat=32.06894, lng=34.82336)]  # Negba, Ramat Gan: 5.3 km straight, 6.6 by route
        self.assertIn("far", plan(far, PREFS, routes={"bike_minutes": {"far": 6.6}}, pulled_at=WHEN).skipped)
        unrouted = plan(far, PREFS, pulled_at=WHEN)  # even the straight line is 16 min at 20 km/h
        self.assertIn("in a straight line", unrouted.skipped["far"][0])
        near = [_row(id="near", lat=32.03247, lng=34.76512)]  # Tel Giborim: 2.7 km straight, could go either way by route
        self.assertEqual(plan(near, PREFS, pulled_at=WHEN).fetch, ["near"])  # an estimate never skips
        self.assertIn("near", plan(near, PREFS, routes={"bike_minutes": {"near": 5.5}}, pulled_at=WHEN).skipped)

    def test_a_car_drive_past_the_limit_on_an_empty_road_is_skipped(self):
        prefs = _driver_prefs(limit=25)
        rows = [_row(id="far"), _row(id="near")]
        routes = {"commute_minutes": {"far": {"free_flow_s": 2400}, "near": {"free_flow_s": 600}}}
        p = plan(rows, prefs, routes=routes, pulled_at=WHEN)
        self.assertIn("far", p.skipped)
        self.assertEqual(p.fetch, ["near"])

    def test_budget_and_order(self):
        rows = [_row(id="small", size_m2=41), _row(id="nice", size_m2=90, price=3900)]
        p = plan(rows, PREFS, budget=1, pulled_at=WHEN)
        self.assertEqual((p.fetch, p.later), (["nice"], ["small"]))

    def test_wait_model(self):
        self.assertAlmostEqual(wait_seconds(881, 0), 25 * 1.35 + 15 * 0.35)
        self.assertAlmostEqual(wait_seconds(36, 10, routed=False), 1.35 + 11.7)
        # a repeat pull: the listings and pins read before cost nothing, the search is always fresh
        first = wait_seconds(507, 205, pins=281)
        same_day = wait_seconds(507, 205, pins=281, cached=205, cached_pins=281)
        next_day = wait_seconds(507, 205, pins=281, cached=175, cached_pins=260)  # 30 new or changed
        self.assertAlmostEqual(first / 60, 4.4, places=1)
        self.assertAlmostEqual(same_day, 15 * 1.35)  # ~20 s: just the search pages
        self.assertAlmostEqual(next_day, 15 * 1.35 + 0.35 + 30 * 1.17)  # ~56 s
        for bad in ({"cached": 206}, {"cached": -1}, {"cached_pins": 282}):
            with self.assertRaises(ValueError):
                wait_seconds(507, 205, pins=281, **bad)

    def test_not_homes(self):
        self.assertEqual(NOT_HOMES, {"מחסן", "חניה", "מגרשים"})


class TestFunnelOnRealPulls(unittest.TestCase):
    """The funnel on Oct 20's real data: every Bat Yam rental on Yad2's
    search (881 rows, routed), and the 60 fully read listings, whose
    page-level result says whether a row skip was ever wrong."""

    @classmethod
    def setUpClass(cls):
        f = ROOT / "tests" / "fixtures" / "yad2_search_batyam_2026-10-20"
        cls.rows = json.loads((f / "rows.json").read_text(encoding="utf-8"))["rows"]
        routes = json.loads((f / "routes_citycenter38.json").read_text(encoding="utf-8"))
        cls.bike = {"bike_minutes": routes["bike_minutes"]}

    def test_batyam(self):
        self.assertEqual(len(self.rows), 881)
        under_cap = [r for r in self.rows if r["price"] and r["price"] <= price_cap(PREFS)]
        self.assertEqual(len(under_cap), 507)  # what Yad2's own maxPrice filter leaves to read
        self.assertEqual(len(plan(self.rows, PREFS, pulled_at=WHEN).fetch), 340)  # straight lines only (v1.39: 2 garden apartments Yad2 put on floor 1 are the ground floor)
        routed = plan(self.rows, PREFS, routes=self.bike, pulled_at=WHEN)
        self.assertEqual(len(routed.fetch), 204)  # 205 before v1.39 (one garden apartment)
        self.assertEqual(plan(under_cap, PREFS, routes=self.bike, pulled_at=WHEN).fetch, routed.fetch)
        # 17.8 min to open every listing; 4.4 to open what's left; 47 s to the first 20
        self.assertAlmostEqual(wait_seconds(881, 881) / 60, 17.8, places=1)
        self.assertAlmostEqual(wait_seconds(507, 205) / 60, 4.4, places=1)
        self.assertLess(wait_seconds(507, 20), 48)

    def test_no_row_skip_was_ever_wrong(self):
        from rental_matcher.pipeline import run
        live = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"
        xs = json.loads((live / "extracts.json").read_text(encoding="utf-8"))
        routes = json.loads((live / "routes_citycenter38.json").read_text(encoding="utf-8"))

        def row(x):
            d = x["additionalDetails"]
            return {"id": x["id"], "adType": x["adType"], "price": x["price"], "floor": x["floor"], "lat": x["coords"]["lat"],
                    "lng": x["coords"]["lon"], "rooms": d.get("roomsCount"), "size_m2": d.get("squareMeterBuild") or d.get("squareMeter"),
                    "property": (d.get("property") or {}).get("text"), "city": x["city"]}

        p = plan([row(x) for x in xs], PREFS, routes=routes, pulled_at=WHEN)
        ranked, _, _ = run(xs, PREFS, routes=routes, pulled_at=WHEN)
        shown = {s.listing_id.removeprefix("yad2:") for s in ranked if not s.excluded}
        self.assertFalse(set(p.skipped) & shown)  # nothing the full read shows was skipped
        self.assertEqual((len(p.skipped), len(p.fetch)), (50, 10))  # 60 pages -> 10
        self.assertEqual(set(p.fetch), shown)  # and here every page opened was a result


class TestRoutingLoad(unittest.TestCase):
    def test_only_pins_still_in_play_are_routed_once_each(self):
        from rental_matcher.funnel import pins_to_route, route_key
        rows = json.loads((ROOT / "tests" / "fixtures" / "yad2_search_batyam_2026-10-20" / "rows.json").read_text(encoding="utf-8"))["rows"]
        pins = pins_to_route(rows, PREFS, pulled_at=WHEN)
        self.assertEqual(len(pins), 279)  # of 881 rows (281 before v1.39 read garden apartments as the ground floor): 5 table requests instead of 15
        by_id = {r["id"]: r for r in rows}
        self.assertTrue(all(route_key(by_id[i]) in pins for i in plan(rows, PREFS, pulled_at=WHEN).fetch))
        # quiet server vs the evening's slow one, for the 507 rows under the price cap
        fast = wait_seconds(507, 205, pins=281)
        slow = wait_seconds(507, 205, pins=281, route_s=9.5)
        self.assertLess(slow - fast, 50)


class TestCarCalibration(unittest.TestCase):
    """Oct 21, 2026: TomTom typical traffic (a free key, run on the owner's
    machine) for 30 Bat Yam pins spread from the nearest to the farthest
    drive, to the example work pin, departing Tuesday 08:00 and 11:00, against the
    OSRM free-flow times the funnel uses."""

    @classmethod
    def setUpClass(cls):
        f = ROOT / "tests" / "fixtures"
        cls.tt = json.loads((f / "tomtom_calibration" / "tomtom.json").read_text(encoding="utf-8"))["commute_minutes"]
        cls.osrm = json.loads((f / "yad2_search_batyam_2026-10-20" / "routes_citycenter38.json").read_text(encoding="utf-8"))["car_free_flow_s"]

    def test_the_sample(self):
        pins = json.loads((ROOT / "tests" / "fixtures" / "tomtom_calibration" / "pins.json").read_text(encoding="utf-8"))
        self.assertEqual(set(self.tt), set(pins))
        self.assertEqual(len(self.tt), 30)
        for d in self.tt.values():
            self.assertEqual(d["source"], "TomTom typical traffic, departing 08:00 and 11:00")
            self.assertGreater(d["peak_s"], d["typical_s"])  # rush hour is slower everywhere
            self.assertGreaterEqual(d["typical_s"], d["free_flow_s"])

    def test_the_funnel_never_skips_a_drive_wrongly(self):
        from rental_matcher.commute import FREE_FLOW_MARGIN
        for k, d in self.tt.items():
            bound = lower_bound_minutes(None, None, CAR, {"free_flow_s": self.osrm[k]})
            self.assertLessEqual(bound * 60, d["free_flow_s"], k)  # even TomTom's empty road is slower
            self.assertLessEqual(bound * 60, d["typical_s"], k)
        worst = min(d["free_flow_s"] / self.osrm[k] for k, d in self.tt.items())
        self.assertGreater(worst, 1.0)  # OSRM was never slower than TomTom's no-traffic time
        self.assertLess(FREE_FLOW_MARGIN, worst)

    def test_the_estimate_ranges_are_this_data(self):
        from rental_matcher.commute import CAR_PEAK_X, CAR_TYPICAL_X
        typ = [d["typical_s"] / self.osrm[k] for k, d in self.tt.items()]
        peak = [d["peak_s"] / self.osrm[k] for k, d in self.tt.items()]
        self.assertEqual(CAR_TYPICAL_X, (round(min(typ), 2), round(max(typ), 2)))
        self.assertEqual(CAR_PEAK_X, (round(min(peak), 2), round(max(peak), 2)))
        # what a user would be told without TomTom: pin -> work is not "6-14 min"
        self.assertAlmostEqual(min(d["peak_s"] for d in self.tt.values()) / 60, 15.6, places=1)
        self.assertAlmostEqual(max(d["peak_s"] for d in self.tt.values()) / 60, 29.4, places=1)


class TestBikeCalibration(unittest.TestCase):
    """Oct 21, 2026: TomTom's bicycle routes (a free key, the owner's machine) for
    the same 30 Bat Yam pins, pin -> the example work pin, against the OSRM bike
    routes (the example work pin -> pin) the pipeline uses."""

    @classmethod
    def setUpClass(cls):
        f = ROOT / "tests" / "fixtures"
        tt = json.loads((f / "tomtom_calibration" / "tomtom_bike.json").read_text(encoding="utf-8"))
        cls.tt, cls.tt_s = tt["bike_minutes"], tt["_tomtom_bicycle_s"]
        cls.osrm = json.loads((f / "yad2_search_batyam_2026-10-20" / "routes_citycenter38.json").read_text(encoding="utf-8"))["bike_minutes"]

    def test_the_two_routers_mostly_agree(self):
        import statistics
        self.assertEqual(len(self.tt), 30)
        r = [self.tt[k] / self.osrm[k] for k in self.tt]
        self.assertAlmostEqual(statistics.median(r), 0.99, places=2)
        self.assertEqual((round(min(r), 2), round(max(r), 2)), (0.85, 1.11))
        self.assertEqual(sum(0.94 <= x <= 1.06 for x in r), 22)  # 22 of 30 within 6%
        # the far pins are where they part: TomTom found up to 1.3 km shorter
        self.assertAlmostEqual(min(self.tt[k] - self.osrm[k] for k in self.tt), -1.31, places=2)

    def test_tomtoms_own_bike_time_is_an_ebike_pace(self):
        import statistics
        kmh = [self.tt[k] / (self.tt_s[k] / 3600) for k in self.tt]
        self.assertAlmostEqual(statistics.median(kmh), 19.3, places=1)  # Google's regular bike was ~14
        self.assertGreater(min(kmh), 16.0)

    def test_near_the_limit_the_shortest_route_decides(self):
        from rental_matcher.commute import shortest_routes
        from rental_matcher.pipeline import combine_routes
        ebike = PREFS.commutes[0]
        over = lambda km: km / ebike.speed * 60 > 15  # noqa: E731
        flips = sorted(k for k in self.tt if over(self.osrm[k]) != over(self.tt[k]))
        self.assertEqual(flips, ["31xdl8bn", "dixq4al5", "g2gtbq6k"])  # OSRM: just over 15 min; TomTom: under
        both = shortest_routes({"OSRM": {"bike_minutes": self.osrm}, "TomTom bicycle": {"bike_minutes": self.tt}})["bike_minutes"]
        self.assertEqual(both["dixq4al5"], {"km": 4.68, "source": "TomTom bicycle (OSRM 5.01 km)"})
        self.assertFalse(any(over(both[k]["km"]) for k in flips))  # with both, none of the three is hidden
        listing = to_listing({"id": "dixq4al5", "adType": "private", "price": 4200, "coords": {"lat": 32.02, "lon": 34.78}}, WHEN)
        s = commute_signal(listing, ebike, both["dixq4al5"])
        self.assertEqual(s.value, 14.0)
        self.assertIn("routed 4.68 km (TomTom bicycle (OSRM 5.01 km))", s.evidence)
        self.assertEqual(lower_bound_minutes(None, None, ebike, both["dixq4al5"]), 14.0)
        # the pipeline's --routes given twice does the same, and keeps a car drive from its one source
        car = {"commute_minutes": {"dixq4al5": {"free_flow_s": 500, "typical_s": 800, "peak_s": 1300}}}
        merged = combine_routes({"osrm": {"bike_minutes": {"dixq4al5": 5.01}, **car},
                                 "tomtom_bike": {"bike_minutes": {"dixq4al5": 4.68}, "_tomtom_bicycle_s": {"dixq4al5": 880.0}}})
        self.assertEqual(merged["bike_minutes"]["dixq4al5"]["km"], 4.68)
        self.assertEqual(merged["commute_minutes"], car["commute_minutes"])
        self.assertNotIn("_tomtom_bicycle_s", merged)
        with self.assertRaises(ValueError):
            shortest_routes({"a": {"bike_minutes": {"x": -1}}})


if __name__ == "__main__":
    unittest.main()
