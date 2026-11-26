"""v1.67 (Nov 25): Yad2 sends some places to a separate site (Ma'ale Adumim and Ariel go to yad-il.co.il; found pulling dedup
round 4, Nov 19). A pull runs in a Yad2 tab and can't read that site, so a search there used to end as an unexplained failed page.
Setup now notes where Yad2 serves the place, and the pull names it in its message instead of fetching it."""
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from rental_matcher import server
from rental_matcher.scoring import PreferenceSet, Search

ROOT = Path(__file__).resolve().parents[1]


class TestElsewhere(unittest.TestCase):
    def test_a_search_says_where_yad2_serves_it(self):
        s = Search(label="Ma'ale Adumim", path="/realestate/rent?city=3616", elsewhere="yad-il.co.il")
        self.assertEqual(s.elsewhere, "yad-il.co.il")
        self.assertIsNone(Search(label="Safed", path="/realestate/rent?city=8000").elsewhere)
        with self.assertRaises(ValidationError):
            Search(label="x", path="/realestate/rent?city=3616", elsewhere="example.com")

    def test_the_helper_passes_it_to_the_pull(self):
        raw = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
        raw["searches"] = [{"source": "yad2", "label": "Ma'ale Adumim", "path": "/realestate/rent?city=3616", "elsewhere": "yad-il.co.il"}]
        cfg = server.config(PreferenceSet.model_validate(raw))
        self.assertEqual(cfg["searches"][0]["elsewhere"], "yad-il.co.il")

    def test_the_extension_may_read_where_yad2_sends_a_place(self):
        m = json.loads((ROOT / "browser" / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("https://www.yad-il.co.il/*", m["host_permissions"])
        self.assertGreaterEqual(tuple(map(int, m["version"].split("."))), (1, 67))
        i18n = (ROOT / "browser" / "i18n.js").read_text(encoding="utf-8")
        self.assertEqual(i18n.count("m_elsewhere:"), 2)  # English and Hebrew


if __name__ == "__main__":
    unittest.main()
