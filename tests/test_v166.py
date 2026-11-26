"""v1.66 (Nov 19): Facebook, view-only. A rental post the user selected and kept from the right-click menu is read like any
other site's listing; nothing on Facebook is fetched (browser/background.js keepFacebookPost, browser/sites.js facebookPost)."""
import json
import re
import unittest
from pathlib import Path

from rental_matcher import server
from rental_matcher.adapters import facebook
from rental_matcher.scoring import PreferenceSet
from rental_matcher.sources import dedupe

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
# an invented post, in the shape sites.js facebookPost produces (not a real one: no poster's text is kept in the repo)
POST = {"id": "facebook:987654321", "source": "facebook", "url": "https://www.facebook.com/groups/123456/posts/987654321",
        "price": 5200, "rooms": 3, "size_m2": 70, "floor": 2, "city": None,
        "description": "להשכרה במרכז העיר! דירת 3 חדרים, 70 מ\"ר, קומה 2 עם מעלית וממ\"ד\nמחיר: 5,200 ש\"ח לחודש\nחניה בבניין"}


class TestFacebookViewOnly(unittest.TestCase):
    def test_the_listing(self):
        x = facebook.to_listing(POST)
        self.assertEqual((x.source.value, x.price.amount, x.rooms, x.size_m2, x.floor, x.area.city), ("facebook", 5200, 3, 70, 2, "unknown"))
        self.assertEqual(str(x.links[0].url), POST["url"])
        with self.assertRaises(ValueError):
            facebook.to_listing(dict(POST, price=None))
        self.assertEqual(facebook.to_listing(dict(POST, url=None)).links, [])

    def test_scored_from_its_text(self):
        r = server.do_score({"extracts": [POST]}, PREFS)["results"][0]
        self.assertEqual((r["id"], r["url"]), ("facebook:987654321", POST["url"]))
        keys = {f["key"] for f in r["feature_keys"]}
        self.assertTrue({"elevator", "parking_building"} <= keys, keys)

    def test_a_post_is_the_last_copy_kept(self):
        y = {"id": "y1", "source": "yad2", "city": "תל אביב יפו", "street": "הרצל 12", "rooms": 3, "floor": 2, "size_m2": 70, "price": 5200}
        rows, also = dedupe([dict(POST, city="תל אביב יפו", street="הרצל 12"), y])
        self.assertEqual([r["id"] for r in rows], ["y1"])
        self.assertEqual(also["y1"][0]["name"], "Facebook")

    def test_nothing_runs_on_facebook_by_itself(self):
        m = json.loads((ROOT / "browser" / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(any("facebook" in h for h in m["host_permissions"]))  # no standing access to Facebook
        self.assertFalse(any("facebook" in u for cs in m["content_scripts"] for u in cs["matches"]))  # no script on its pages
        self.assertIn("contextMenus", m["permissions"])
        bg = (ROOT / "browser" / "background.js").read_text(encoding="utf-8")
        self.assertIn('contexts: ["selection"]', bg)  # only when the user selected text and chose the menu item
        self.assertIsNone(re.search(r"fetch\([^)]*facebook", bg))


if __name__ == "__main__":
    unittest.main()
