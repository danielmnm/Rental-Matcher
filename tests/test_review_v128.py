"""v1.28: an outside code review of v1.27 (Oct 22, 2026). Each test here
failed on v1.27; the finding it covers is named in its docstring.
"""

from __future__ import annotations

import copy
import http.client
import json
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from rental_matcher import funnel, install, server, setup, traffic
from rental_matcher.adapters import yad2
from rental_matcher.commute import minutes
from rental_matcher.extraction import evaluate, gemini, merge, prompt, rules
from rental_matcher.listed_by import detect_listed_by
from rental_matcher.pipeline import build_listing, combine_routes
from rental_matcher.schema import ExtractedBy, ListedBy, Signal, SignalStatus
from rental_matcher.scoring import PreferenceSet, score_listing

ROOT = Path(__file__).resolve().parent.parent
PREFS_PATH = ROOT / "tests" / "fixtures" / "prefs_frozen.json"
PREFS = PreferenceSet.load(PREFS_PATH)
RAW = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
WHEN = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


def extract(**kw):
    x = {"id": "t1", "price": 4000, "floor": 1, "city": "בת ים", "adType": None,
         "additionalDetails": {"roomsCount": 3, "squareMeterBuild": 70}, "inProperty": {}, "description": ""}
    x.update(kw)
    return x


def prefs_with(change):
    raw = copy.deepcopy(RAW)
    change(raw)
    return PreferenceSet.model_validate(raw)


class TestTextCostsAndBroker(unittest.TestCase):
    """CRITICAL 1: the text's broker / building fee / arnona answers were read, then dropped."""

    def test_costs_and_broker_reach_the_listing(self):
        x = build_listing(extract(description="ועד בית 150 לחודש. ארנונה 600 לחודשיים. ללא תיווך"), PREFS, pulled_at=WHEN)
        self.assertEqual((x.recurring_costs.vaad_bayit_monthly, x.recurring_costs.arnona_monthly), (150, 300))
        self.assertEqual(x.listed_by, ListedBy.PRIVATE)

    def test_included_is_zero_and_unsaid_stays_unknown(self):
        x = build_listing(extract(description="המחיר כולל ועד בית"), PREFS, pulled_at=WHEN)
        self.assertEqual((x.recurring_costs.vaad_bayit_monthly, x.recurring_costs.arnona_monthly), (0.0, None))
        self.assertIsNone(build_listing(extract(description="דירה יפה"), PREFS, pulled_at=WHEN).recurring_costs)

    def test_the_sites_own_field_wins(self):
        x = build_listing(extract(adType="commercial", description="ללא תיווך"), PREFS, pulled_at=WHEN)
        self.assertEqual(x.listed_by, ListedBy.AGENCY)  # Yad2 says a business account posted it

    def test_the_card_gets_the_costs(self):
        out = server.do_score({"extracts": [extract(description="ועד בית 150 לחודש")]}, PREFS)
        self.assertEqual(out["results"][0]["costs"], {"vaad_bayit": 150, "arnona": None, "vaad_bayit_max": None, "arnona_max": None})


class TestNegationAfterAQualifier(unittest.TestCase):
    """CRITICAL 2: "חניה צמודה: אין" read as deeded parking, and the like."""

    def test_denied_after_the_qualifier(self):
        for q, text in (("parking", "חניה צמודה: אין"), ("parking", "חניה בטאבו - אין"), ("protected_space", "מקלט בבניין: אין"),
                        ("balcony", "מרפסת שירות: לא"), ("balcony", "מרפסת שמש - אין")):
            a = rules.answer(text)[q]["answer"]
            self.assertNotIn(a, ("deeded", "building", "yes", "service_only"), text)

    def test_still_read_when_not_denied(self):
        self.assertEqual(rules.answer("חניה צמודה בטאבו")["parking"]["answer"], "deeded")
        self.assertEqual(rules.answer("מקלט בבניין")["protected_space"]["answer"], "yes")
        self.assertEqual(rules.answer("מרפסת שירות")["balcony"]["answer"], "service_only")


class TestElevatorFloor(unittest.TestCase):
    """CRITICAL 3 / HIGH (questions.py): "קומה N ללא" and the grounding check."""

    def test_rules(self):
        self.assertNotEqual(rules.answer("קומה 6 מתוך 8 ללא")["elevator"]["answer"], "yes")
        self.assertNotEqual(rules.answer("קומה 10 ללא")["elevator"]["answer"], "yes")
        self.assertEqual(rules.answer("קומה 7")["elevator"]["answer"], "yes")
        self.assertEqual(rules.answer("קומה 2 מתוך 8")["elevator"]["answer"], "yes")  # an 8-floor building has one (restored v1.59.1, the owner)

    def test_grounding_matches_the_rule(self):
        def grounded(evidence, text):
            return prompt.ground({"elevator": {"answer": "yes", "evidence": evidence}}, text)["elevator"]["answer"]
        self.assertEqual(grounded("קומה 2 מתוך 8", "דירה בקומה 2 מתוך 8"), "yes")
        self.assertEqual(grounded("קומה 02", "דירה בקומה 02"), "not_stated")
        self.assertEqual(grounded("קומה 6 מתוך 8 ללא", "קומה 6 מתוך 8 ללא"), "not_stated")
        self.assertEqual(grounded("קומה 12", "קומה 12"), "yes")


class TestPins(unittest.TestCase):
    """CRITICAL 4: a (0, 0) pin is a missing pin everywhere, not a place in the ocean."""

    def test_zero_pin_isnt_ruled_out_or_routed(self):
        row = {"id": "z", "price": 4000, "rooms": 3, "size_m2": 70, "floor": 1, "lat": 0, "lng": 0, "city": "בת ים"}
        p = funnel.plan([row], PREFS, pulled_at=WHEN)
        self.assertNotIn("bike", " ".join(p.skipped.get("z", [])).lower())
        self.assertEqual(funnel.pins_to_route([row], PREFS, pulled_at=WHEN), {})
        self.assertIsNone(server._pin({"lat": 0, "lng": 0}))
        self.assertIsNone(server._pin({"lat": float("nan"), "lng": 34.7}))
        self.assertIsNone(server._pin({"coords": {"lat": 0, "lon": 0}}))


class TestCommuteSkips(unittest.TestCase):
    """CRITICAL 5: the funnel ruled out by the base limit, ignoring overrides; a bad route crashed the plan."""

    def test_an_override_keeps_it_in_play(self):
        def change(raw):
            p = next(p for p in raw["preferences"] if p["name"] == "bike_minutes")
            p.update(kind="at_most", ideal=None, limit=15, overrides=[{"when_signal": "balcony", "limit": 25}])
        prefs = prefs_with(change)
        speed = prefs.commutes[0].speed
        row = {"id": "o", "price": 4000, "rooms": 3, "size_m2": 70, "floor": 1, "lat": 32.0, "lng": 34.77, "city": "בת ים"}
        km = 20 * speed / 60  # 20 minutes: past 15, within the balcony's 25
        self.assertAlmostEqual(minutes(km, speed), 20, delta=0.6)
        p = funnel.plan([row], prefs, routes={"bike_minutes": {"o": {"km": km}}}, pulled_at=WHEN)
        self.assertNotIn("o", p.skipped)

    def test_a_bad_route_doesnt_sink_the_plan(self):
        row = {"id": "b", "price": 4000, "rooms": 3, "size_m2": 70, "floor": 1, "lat": 32.0, "lng": 34.77, "city": "בת ים"}
        p = funnel.plan([row], PREFS, routes={"bike_minutes": {"b": {"km": "far"}}}, pulled_at=WHEN)
        self.assertEqual(p.rows, 1)


class TestFailRisk(unittest.TestCase):
    """HIGH (scoring): must-haves that count 0 in the match had no fail risk."""

    def test_floor_kept_only_by_an_unstated_elevator(self):
        s = score_listing(yad2.to_listing(extract(floor=4), WHEN), PREFS)
        self.assertFalse(s.excluded)
        labels = [label for label, _ in s.fail_risk_parts]
        self.assertTrue(any(lbl.startswith("Floor") for lbl in labels), s.fail_risk_parts)

    def test_an_at_least_must_have_on_a_measured_signal(self):
        def change(raw):
            p = next(p for p in raw["preferences"] if p["name"] == "parking")
            p.update(kind="at_least", ideal=None, limit=2, weight=0)
        s = score_listing(yad2.to_listing(extract(), WHEN), prefs_with(change))
        self.assertTrue(any(lbl.startswith("Parking") for lbl, _ in s.fail_risk_parts), s.fail_risk_parts)

    def test_only_filters(self):
        def change(raw):
            raw["preferences"] = [p for p in raw["preferences"] if p["name"] in ("mamad", "air_conditioning")]
            for p in raw["preferences"]:
                p["weight"] = 0
        s = score_listing(yad2.to_listing(extract(), WHEN), prefs_with(change))
        self.assertIsNotNone(s.fail_risk)
        self.assertGreater(s.fail_risk, 0)


class TestMergeParking(unittest.TestCase):
    """HIGH (merge): a ticked parking box agreed with by the model became "the model's word only"."""

    def test_agreement_keeps_the_box(self):
        s = {"parking_level": Signal(status=SignalStatus.CONFIRMED, value=2.0, evidence="Yad2: parking", extracted_by=ExtractedBy.RULE)}
        t = {"parking_level": Signal(status=SignalStatus.CONFIRMED, value=2.0, evidence="text: חניה", extracted_by=ExtractedBy.LLM)}
        m = merge.merge(s, t)["parking_level"]
        self.assertEqual((m.extracted_by, m.value), (ExtractedBy.RULE, 2.0))
        self.assertIn("Yad2: parking", m.evidence)
        up = merge.merge(s, {"parking_level": t["parking_level"].model_copy(update={"value": 3.0})})["parking_level"]
        self.assertEqual((up.value, up.extracted_by), (3.0, ExtractedBy.LLM))  # the higher tier is the model's word


class TestCostsHeader(unittest.TestCase):
    """HIGH (costs): "לשנה" anywhere earlier rejected the building fee."""

    def test_an_earlier_sentence_doesnt_count(self):
        self.assertEqual(rules.answer("להשכרה לשנה. ועד בית 150")["vaad_bayit"]["value"], 150)
        self.assertEqual(rules.answer("חוזה לשנה, ועד בית 150 לחודש")["vaad_bayit"]["value"], 150)


class TestServerInput(unittest.TestCase):
    """HIGH (server): empty pin_routes, malformed pins, booleans, Content-Length."""

    ROW = {"id": "r", "price": 4000, "rooms": 3, "size_m2": 70, "floor": 1, "lat": 32.05, "lng": 34.77, "city": "בת ים"}

    def test_empty_routes_still_count_as_routed(self):
        out = server.do_plan({"rows": [self.ROW], "pin_routes": {}}, PREFS)
        self.assertNotIn("pins", out)

    def test_bad_pins_and_booleans(self):
        def car(raw):
            raw["commutes"][0]["mode"] = "car"
        prefs = prefs_with(car)
        for bad in (None, [32.0], [True, False], [0, 0], ["32", "34"]):
            with self.assertRaisesRegex(server.BadRequest, "pins", msg=repr(bad)):
                server.do_drives({"signal": prefs.commutes[0].signal, "pins": {"1": bad}}, prefs)
        routes = server.routes_by_id([self.ROW], PREFS, {"bike_minutes": {funnel.route_key(self.ROW): {"m": True, "s": False}}}, None)
        self.assertEqual(routes["bike_minutes"], {})

    def test_content_length(self):
        httpd = server.serve(PREFS_PATH, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            for bad in ("abc", "-5"):
                c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
                c.putrequest("POST", "/plan")
                c.putheader("Origin", f"chrome-extension://{install.EXTENSION_ID}")
                c.putheader("Content-Length", bad)
                c.endheaders()
                self.assertEqual(c.getresponse().status, 400, bad)
                c.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestListedByColon(unittest.TestCase):
    """MEDIUM (listed_by): "מתווכים: נא לא לפנות"."""

    def test_colon(self):
        self.assertEqual(detect_listed_by(["מתווכים: נא לא לפנות"]), ListedBy.PRIVATE)
        self.assertEqual(detect_listed_by(["Brokers: please do not call"]), ListedBy.PRIVATE)


class TestTrafficDrive(unittest.TestCase):
    """MEDIUM (traffic): a TomTom reply with no times became a drive that sank its listing."""

    def test_no_times_is_an_error(self):
        reply = {"routes": [{"summary": {"lengthInMeters": 5000}}]}
        with self.assertRaises(traffic.TrafficError):
            traffic.drive((32.0, 34.7), (32.05, 34.77), "k", peak_at="2026-10-26T08:00:00", typical_at="2026-10-26T11:00:00",
                          get=lambda u: reply)

    def test_a_bad_drive_from_the_browser_is_ignored(self):
        def change(raw):
            raw["commutes"][0]["mode"] = "car"
        prefs = prefs_with(change)
        out = server.do_score({"extracts": [extract(coords={"lat": 32.0, "lon": 34.77})],
                               "drives": {"bike_minutes": {"t1": {"km": 5, "free_flow_s": None}}}}, prefs)
        self.assertEqual(len(out["results"]), 1)


class TestContradictions(unittest.TestCase):
    """MEDIUM (rules): a text that says both was "not stated", so the model's guess stood unchallenged."""

    def test_unclear(self):
        self.assertEqual(rules.answer("ועד בית 100 לחודש ... ועד בית 200 לחודש")["vaad_bayit"]["answer"], "unclear")
        self.assertEqual(rules.answer("המחיר כולל ועד בית. ועד בית 150 לחודש")["vaad_bayit"]["answer"], "unclear")
        self.assertEqual(rules.answer("ללא תיווך. דמי תיווך חודש")["broker"]["answer"], "unclear")
        self.assertEqual(rules.answer("להשכרה דירת 4 חדרים, מחפשים שותף לחדר")["room_share"]["answer"], "unclear")


class TestGemini(unittest.TestCase):
    """MEDIUM (gemini): an amount without a number; resuming across prompts; an empty probe."""

    def test_amount_needs_a_value(self):
        out = gemini.clean({"vaad_bayit": {"answer": "amount", "evidence": "ועד בית", "value": None}})
        self.assertEqual(out["vaad_bayit"]["answer"], "not_stated")

    def test_nothing_left_to_do(self):
        calls = []
        model, answers = gemini.run_with_fallback({"a": "x"}, "k", ["m1", "m2"], post=lambda *a: calls.append(a),
                                                  done={"a": {"q": 1}})
        self.assertEqual((calls, answers), ([], {"a": {"q": 1}}))

    def test_resume_only_the_same_prompt(self):
        self.assertFalse(gemini.resumable({"_model": "m", "_prompt": "old000", "a": {}}, "m"))
        self.assertTrue(gemini.resumable({"_model": "m", "_prompt": prompt.prompt_id(), "a": {}}, "auto"))
        self.assertFalse(gemini.resumable({"_model": "m", "a": {}}, "auto"))  # from before the prompt was recorded


class TestEvaluate(unittest.TestCase):
    """MEDIUM (evaluate): a partly right list wasn't counted as given; a retired question crashed grading."""

    def test_partial_list_is_given_not_wrong(self):
        gold = {"L": {"furniture": {"answer": "items", "acceptable": ["items"], "items": ["bed", "sofa"], "allowed_items": ["bed", "sofa"]}}}
        run = {"L": {"furniture": {"answer": "items", "items": ["bed"], "evidence": "מיטה"}}}
        t = evaluate.score(gold, run)["furniture"]
        self.assertEqual((t.definite_given, t.wrong, t.correct), (1, 0, 0))

    def test_retired_question(self):
        gold = {"L": {"furnished": {"answer": "yes", "acceptable": ["yes"]}, "elevator": {"answer": "yes", "acceptable": ["yes"]}}}
        run = {"L": {"furnished": {"answer": "yes"}, "elevator": {"answer": "yes", "evidence": "מעלית"}}}
        self.assertEqual(evaluate.score(evaluate.same_questions(gold, run), run)["elevator"].correct, 1)


class TestEdges(unittest.TestCase):
    """MEDIUM: route files with the same name, an extract with no id, {id: extract} fixtures,
    the Windows launcher's code page, a TomTom error in setup's place search."""

    def test_same_stem(self):
        import tempfile
        from rental_matcher.pipeline import load_routes
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for router, km in (("osrm", 3.0), ("tomtom", 2.0)):
                (Path(d) / router).mkdir()
                p = Path(d) / router / "routes.json"
                p.write_text(json.dumps({"bike_minutes": {"1": km}}), encoding="utf-8")
                paths.append(str(p))
            got = load_routes(paths)["bike_minutes"]["1"]
        self.assertEqual(got["km"], 2.0)  # the shortest of the two, not whichever file came last
        self.assertIn("3.00 km", got["source"])  # and the other router is still named

    def test_no_id(self):
        with self.assertRaises(ValueError):
            yad2.to_listing({"price": 4000})

    def test_id_maps(self):
        from rental_matcher import priors
        rows = priors.extracts_in({"x1": {"id": "x1", "inProperty": {}}, "_note": "a note"})
        self.assertEqual([r["id"] for r in rows], ["x1"])

    def test_windows_launcher(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, mock.patch.object(install, "WINDOWS", True):
            text = install.write_launcher(Path(d), "C:\\py\\python.exe", Path("C:\\prefs.json")).read_bytes().decode("utf-8")
        self.assertTrue(text.startswith("@echo off\r\n@chcp 65001 >nul 2>&1\r\n"), text)

    def test_places_falls_back(self):
        def tomtom(url):
            raise traffic.TrafficError("TomTom HTTP 403")
        with mock.patch.object(traffic, "api_key", return_value="k"):
            out = setup.places("מרכז העיר 38", get=tomtom,
                               nominatim_get=lambda u: [{"display_name": "the example work pin", "lat": "32.05", "lon": "34.77"}])
        self.assertEqual((out["source"], len(out["places"])), ("OpenStreetMap", 1))


if __name__ == "__main__":
    unittest.main()
