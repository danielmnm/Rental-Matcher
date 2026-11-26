"""
The helper as Chrome starts it (rental_matcher/native.py) and its one-time
registration (rental_matcher/install.py).
"""

import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rental_matcher import install, native

ROOT = Path(__file__).resolve().parents[1]
PREFS = ROOT / "tests" / "fixtures" / "prefs_frozen.json"
LIVE = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"


def frame(message):
    data = json.dumps(message).encode("utf-8")
    return struct.pack("=I", len(data)) + data


def unframe(stream):
    out = []
    while (m := native.read_message(stream)) is not None:
        out.append(m)
    return out


class TestNativeHost(unittest.TestCase):
    def test_a_conversation_the_way_chrome_has_it(self):
        xs = json.loads((LIVE / "extracts.json").read_text(encoding="utf-8"))
        km = json.loads((LIVE / "routes_citycenter38.json").read_text(encoding="utf-8"))["bike_minutes"]
        from rental_matcher.funnel import route_key
        pin_routes = {"bike_minutes": {}}
        for x in xs:
            pin_routes["bike_minutes"].setdefault(route_key({"lat": x["coords"]["lat"], "lng": x["coords"]["lon"]}),
                                                  {"m": km[x["id"]] * 1000, "s": km[x["id"]] * 180})
        stdin = frame({"id": 1, "path": "/config"}) + frame({"id": 2, "path": "/score", "body": {"extracts": xs, "pin_routes": pin_routes}}) \
            + frame({"id": 3, "path": "/nope"}) + frame({"id": 4, "path": "/plan", "body": {"rows": "x"}})
        # a real process, started the way Chrome starts it (plus the origin Chrome passes)
        r = subprocess.run([sys.executable, "-m", "rental_matcher.native", "--prefs", str(PREFS),
                            f"chrome-extension://{install.EXTENSION_ID}/"], input=stdin, capture_output=True, cwd=ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        replies = {m["id"]: m for m in unframe(io.BytesIO(r.stdout))}
        self.assertEqual(sorted(replies), [1, 2, 3, 4])
        self.assertEqual(replies[1]["body"]["searches"][0], {"label": "Bat Yam", "label_he": "בת ים", "path": "/realestate/rent/tel-aviv-area?area=11&city=6600", "hoods": [], "hood_names": [], "centers": []})
        shown = [x["id"] for x in replies[2]["body"]["results"] if not x["excluded"]]
        self.assertEqual(len(shown), 10)
        self.assertEqual((replies[3]["status"], replies[4]["status"]), (404, 400))
        self.assertEqual(r.stderr, b"")  # nothing leaks out of the conversation

    def test_a_big_answer_goes_in_pieces_chrome_accepts(self):
        out = io.BytesIO()
        reply = {"ok": True, "status": 200, "body": {"blob": "א" * 1_500_000, "quotes": '"' * 600_000}}  # 3 MB of UTF-8, and text that escaping doubles
        native.send(out, 7, reply)
        out.seek(0)
        parts = unframe(out)
        self.assertGreater(len(parts), 1)
        out.seek(0)
        sizes = []
        while head := out.read(4):
            (n,) = struct.unpack("=I", head)
            sizes.append(n)
            out.read(n)
        self.assertTrue(all(n < 1024 * 1024 for n in sizes), sizes)  # Chrome's limit for a host's message
        joined = json.loads("".join(p["data"] for p in sorted(parts, key=lambda p: p["part"])))
        self.assertEqual(joined, {"id": 7, **reply})
        self.assertTrue(all(p["of"] == len(parts) and p["id"] == 7 for p in parts))

    def test_a_broken_preferences_file_is_an_answer_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "p.json"
            bad.write_text("{", encoding="utf-8")
            r = native.answer({"id": 1, "path": "/config"}, bad)
        self.assertEqual(r["status"], 500)
        self.assertIn("can't be read", r["body"]["error"])


class TestInstall(unittest.TestCase):
    def test_registration(self):
        with tempfile.TemporaryDirectory() as d:
            hosts, where = Path(d) / "NativeMessagingHosts", Path(d) / "data"
            written = install.install(PREFS, python="/usr/bin/python3", host_dirs=[hosts], where=where)
            m = json.loads((hosts / f"{install.HOST}.json").read_text(encoding="utf-8"))
            self.assertEqual(m["name"], "com.rental_matcher.helper")
            self.assertEqual(m["type"], "stdio")
            self.assertEqual(m["allowed_origins"], [f"chrome-extension://{install.EXTENSION_ID}/"])  # only our extension
            launcher = Path(m["path"])
            self.assertIn(launcher, written)
            text = launcher.read_text(encoding="utf-8")
            self.assertIn("-m rental_matcher.native --prefs", text)
            self.assertIn(str(PREFS.resolve()), text)
            install.uninstall(host_dirs=[hosts], where=where)
            self.assertFalse((hosts / f"{install.HOST}.json").exists())
            self.assertFalse(launcher.exists())

    def test_the_id_is_the_manifests_key(self):
        import base64
        import hashlib
        key = json.loads((ROOT / "browser" / "manifest.json").read_text(encoding="utf-8"))["key"]
        h = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
        self.assertEqual("".join(chr(ord("a") + int(c, 16)) for c in h), install.EXTENSION_ID)

    def test_this_python_can_run_the_helper(self):
        self.assertIsNone(install.check())


if __name__ == "__main__":
    unittest.main()
