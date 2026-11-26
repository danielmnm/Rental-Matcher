"""
The local helper (rental_matcher/server.py), over real HTTP on 127.0.0.1,
with Oct 20's real data: the plan it gives the extension is the funnel's,
and the results it scores are the pipeline's.
"""

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from rental_matcher import server
from rental_matcher.funnel import route_key

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
PREFS = ROOT / "tests" / "fixtures" / "prefs_frozen.json"
EXT = "chrome-extension://abcdefghijklmnop"


def pin_routes_from(rows, km_by_id, signal="bike_minutes", speed_kmh=20.0):
    """Routes per pin key, the way the browser sends them (the first listing's route at a shared pin)."""
    out = {}
    for r in rows:
        if r["id"] in km_by_id and r.get("lat") is not None:
            out.setdefault(route_key(r), {"m": km_by_id[r["id"]] * 1000, "s": km_by_id[r["id"]] / speed_kmh * 3600})
    return {signal: out}


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve(PREFS, port=0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None, origin=EXT, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if body is not None else "GET",
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        if origin:
            req.add_header("Origin", origin)
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_only_the_extension_on_this_machine_may_call(self):
        self.assertEqual(self.call("/health")[0], 200)
        self.assertEqual(self.call("/health", origin=None)[0], 200)  # a local script, no browser
        for origin in ("https://www.yad2.co.il", "https://evil.example", "null"):
            code, body = self.call("/config", origin=origin)
            self.assertEqual(code, 403, origin)
            self.assertIn("only the Rental Matcher extension", body["error"])
        self.assertEqual(self.call("/config", host=f"evil.example:{self.port}")[0], 403)  # DNS rebinding
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/plan", method="OPTIONS")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 403)  # no CORS preflight passes, so no web page can POST JSON here

    def test_bad_requests_are_said_plainly(self):
        self.assertEqual(self.call("/plan", {"rows": "x"})[0], 400)
        self.assertEqual(self.call("/score", {"extracts": [{}]})[0], 400)
        self.assertEqual(self.call("/nope", {})[0], 404)
        self.assertEqual(self.call("/drives", {"signal": "bike_minutes", "pins": {"a": [32, 34.7]}})[0], 400)  # not a car commute
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/plan", method="POST", data=b"[1,")
        req.add_header("Origin", EXT)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 400)

    def test_config(self):
        code, c = self.call("/config")
        self.assertEqual(code, 200)
        self.assertEqual(c["search_filters"], {"maxPrice": "5450"})
        self.assertEqual(c["commutes"], [{"signal": "bike_minutes", "label": "Work (example pin)",
                                          "mode": "ebike", "speed_kmh": 20.0, "profile": "bike", "anchor": [32.075400, 34.774900]}])
        self.assertIsInstance(c["tomtom"], bool)
        self.assertNotIn("key", json.dumps(c).lower().replace("tomtom", ""))

    def test_the_plan_is_the_funnels(self):
        from rental_matcher.funnel import plan
        from rental_matcher.sources import dedupe
        from rental_matcher.scoring import PreferenceSet
        rows = json.loads((FIX / "yad2_search_batyam_2026-10-20" / "rows.json").read_text(encoding="utf-8"))["rows"]
        km = json.loads((FIX / "yad2_search_batyam_2026-10-20" / "routes_citycenter38.json").read_text(encoding="utf-8"))["bike_minutes"]
        code, first = self.call("/plan", {"rows": rows})
        self.assertEqual(code, 200)
        # v1.38 merged 21 of the 881 as second posts in one building (860 planned). v1.63: a merge needs both addresses, and
        # this pull was saved before search rows kept the street, so all 881 are planned (a duplicate, never a wrong merge)
        self.assertEqual((first["rows"], len(first["fetch"]), len(first["pins"])), (881, 340, 279))
        rows = dedupe(rows)[0]
        self.assertTrue(set(first["pins"]).issubset({route_key(r) for r in rows if r.get("lat") is not None}))
        pr = pin_routes_from(rows, km)
        code, second = self.call("/plan", {"rows": rows, "pin_routes": pr})
        self.assertEqual(code, 200)
        self.assertNotIn("pins", second)
        # the same plan the funnel makes from those routes by listing id
        prefs = PreferenceSet.load(PREFS)
        by_id = {r["id"]: {"km": pr["bike_minutes"][route_key(r)]["m"] / 1000, "source": "OSRM"}
                 for r in rows if r.get("lat") is not None and route_key(r) in pr["bike_minutes"]}
        self.assertEqual(second["fetch"], plan(rows, prefs, routes={"bike_minutes": by_id}).fetch)
        self.assertEqual(len(second["fetch"]), 204)  # one route per ~10 m pin gives the same as one per listing (205 before v1.38 merged posts, 201 before v1.39; 200 with v1.38-v1.62 merges, which v1.63 makes only with both addresses)
        self.assertEqual(second["rows"], len(second["fetch"]) + len(second["skipped"]))
        self.assertEqual(sum(second["skipped_by_reason"].values()), len(second["skipped"]))
        self.assertEqual(second["skipped_by_reason"]["Monthly rent (ILS)"], 112)  # 112 before v1.38, 108 v1.38-v1.62 (posts merged); 112 again: this pull has no streets
        self.assertEqual(second["skipped_by_reason"]["No price given"], 10)

    def test_scores_are_the_pipelines(self):
        live = FIX / "yad2_live_2026-10-20"
        xs = json.loads((live / "extracts.json").read_text(encoding="utf-8"))
        km = json.loads((live / "routes_citycenter38.json").read_text(encoding="utf-8"))["bike_minutes"]
        rows = [{"id": x["id"], "lat": x["coords"]["lat"], "lng": x["coords"]["lon"]} for x in xs]
        code, out = self.call("/score", {"extracts": xs, "pin_routes": pin_routes_from(rows, km)})
        self.assertEqual(code, 200)
        shown = [r["id"] for r in out["results"] if not r["excluded"]]
        # TestLivePull's ten, in its order
        self.assertEqual(shown, ["7w5nv0p7", "t8n0ghu0", "2a5m0b7a", "idoewwx4", "f9gz3aqq", "clp32ctv", "44gzb3qw", "1dqm0ykv", "igj5zw99", "9aq4ffmq"])
        self.assertEqual((out["shown"], out["hidden"], len(out["skipped"])), (10, 49, 1))
        top = out["results"][0]
        self.assertEqual(top["url"], "https://www.yad2.co.il/realestate/item/7w5nv0p7")
        self.assertEqual(top["commutes"]["bike_minutes"]["status"], "confirmed")
        self.assertIn("(OSRM)", top["commutes"]["bike_minutes"]["evidence"])
        self.assertEqual(top["commutes"]["bike_minutes"]["short"], "E-bike to the example work pin: 10 min")
        self.assertNotIn("description", json.dumps(out))  # the listing text isn't sent back

    def test_drives_keep_the_key_here(self):
        car_prefs = json.loads(PREFS.read_text(encoding="utf-8"))
        car_prefs["commutes"].append({"signal": "commute_minutes", "label": "work", "lat": 32.0754, "lng": 34.7749, "mode": "car"})
        car_prefs["preferences"].append({"name": "drive", "label": "Drive to work (min)", "field": "signal:commute_minutes",
                                         "kind": "at_most", "relevance": 10, "limit": 25})
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.json"
            p.write_text(json.dumps(car_prefs), encoding="utf-8")
            reply = {"routes": [{"summary": {"lengthInMeters": 6400, "travelTimeInSeconds": 1300,
                                             "noTrafficTravelTimeInSeconds": 560, "historicTrafficTravelTimeInSeconds": 1250}}]}
            seen = []
            httpd = server.serve(p, port=0, get=lambda u: (seen.append(u), reply)[1])
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                port, self.port = self.port, httpd.server_address[1]
                with mock.patch.dict(os.environ, {"TOMTOM_API_KEY": "SECRET-KEY"}):
                    code, out = self.call("/drives", {"signal": "commute_minutes", "pins": {"a": [32.02, 34.78]}})
                    self.assertEqual(self.call("/config")[1]["tomtom"], True)
                    code2, _ = self.call("/drives", {"signal": "commute_minutes", "pins": {str(i): [32, 34.7] for i in range(26)}})
            finally:
                self.port = port
                httpd.shutdown()
                httpd.server_close()
        self.assertEqual(code, 200)
        self.assertEqual(out["drives"]["a"]["peak_s"], 1250.0)
        self.assertEqual(code2, 400)  # bounded: TomTom's free tier is the user's
        self.assertTrue(all("SECRET-KEY" in u for u in seen))  # used for TomTom...
        self.assertNotIn("SECRET-KEY", json.dumps(out))  # ...never sent back


if __name__ == "__main__":
    unittest.main()
