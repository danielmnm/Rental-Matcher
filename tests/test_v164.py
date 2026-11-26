"""v1.64 (Nov 10): the families the fresh Komo sample and the second duplicate measurement found (tests/test_komo2.py,
tests/test_dedup2.py), each with the look-alikes it must not catch."""
import json
import unittest
from pathlib import Path

from rental_matcher.adapters import komo
from rental_matcher.adapters.common import floor_from_form
from rental_matcher.extraction.rules import answer
from rental_matcher.sources import maybe_same, same_apartment

ROOT = Path(__file__).resolve().parents[1]


def _a(text, q):
    return answer(text).get(q, {})


class TestCitySpelling(unittest.TestCase):
    """8 of the 9 sampled twins v1.63 missed: Komo writes "קריית", Yad2 "קרית"."""

    K = {"id": "komo:1", "source": "komo", "city": "קריית אתא", "street": "הגורן 3", "rooms": 1.5, "floor": 8, "size_m2": 45, "price": 2200}
    Y = {"id": "y1", "source": "yad2", "city": "קרית אתא", "street": "הגורן 3", "rooms": 1.5, "floor": 8, "size_m2": 45, "price": 2200}

    def test_one_city(self):
        self.assertTrue(same_apartment(self.K, self.Y))
        self.assertTrue(same_apartment(dict(self.K, city="קריית גת"), dict(self.Y, city="קרית גת")))

    def test_other_cities_stay_apart(self):
        self.assertFalse(same_apartment(self.K, dict(self.Y, city="קרית ביאליק")))
        self.assertFalse(same_apartment(dict(self.K, city="אור יהודה"), dict(self.Y, city="יהוד")))


class TestKomoFloorAtTheTop(unittest.TestCase):
    """85 of 289 Komo listings give the building's height as their floor; on real twins that was wrong 14 times in 67,
    and never when the floor was below the top."""

    def test_the_rule(self):
        self.assertEqual(floor_from_form(14, 14), (None, 14))
        self.assertEqual(floor_from_form(4, 4), (None, 4))
        self.assertEqual(floor_from_form(2, 2), (2, None))  # a two-floor house: the top floor is common
        self.assertEqual(floor_from_form(3, 14), (3, None))
        self.assertEqual(floor_from_form(None, 14), (None, None))

    def test_the_listing_has_no_floor_and_says_why(self):
        x = komo.to_listing({"id": "komo:9", "price": 5000, "rooms": 3, "floor": 14, "floors": 14, "city": "בת ים"})
        self.assertIsNone(x.floor)
        self.assertEqual(x.total_floors, 14)
        self.assertEqual(x.signals["floor_said"].value, 14.0)
        self.assertEqual(komo.to_listing({"id": "komo:9", "price": 5000, "floor": 3, "floors": 14, "city": "בת ים"}).floor, 3)

    def test_a_floor_must_have_asks_instead_of_hiding(self):
        from rental_matcher import server
        from rental_matcher.scoring import PreferenceSet
        prefs = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
        out = server.do_score({"extracts": [{"id": "komo:9", "source": "komo", "price": 4000, "rooms": 2, "floor": 0, "floors": 3,
                                              "city": "תל אביב יפו", "description": "דירה"},
                                             {"id": "komo:8", "source": "komo", "price": 4000, "rooms": 2, "floor": 3, "floors": 3,
                                              "city": "תל אביב יפו", "description": "דירה"}]}, prefs)
        by = {r["id"]: r for r in out["results"]}
        self.assertEqual((by["komo:8"]["floor"], by["komo:8"]["floor_said"]), (None, 3))
        self.assertIsNone(by["komo:9"]["floor_said"])

    def test_two_sites_that_agree_still_join(self):
        """The untrusted floor still joins when the other site gives the same one (53 of the 67 twins); when they
        disagree the two are linked, never merged."""
        k = {"id": "komo:1", "source": "komo", "city": "בת ים", "street": "הרצל 46", "rooms": 3, "floor": None, "floor_said": 20,
             "size_m2": 80, "price": 6000}
        y = {"id": "y1", "source": "yad2", "city": "בת ים", "street": "שד הרצל 46", "rooms": 3, "floor": 20, "size_m2": 80, "price": 6000}
        self.assertTrue(same_apartment(k, y))
        self.assertFalse(same_apartment(k, dict(y, floor=46)))
        self.assertTrue(maybe_same(k, dict(y, floor=46)))
        self.assertFalse(same_apartment(dict(k, floor_said=None), y))

    def test_the_search_row_drops_it_too(self):
        import subprocess
        js = """const S = require('./browser/sites.js');
const h = '<div class="contant"><a href="/code/nadlan/details/?modaaNum=77">x</a><h2 class="title">בת ים, רמת הנשיא, הרצל 4</h2>'
  + '<div class="price">5,000</div><div class="description">דירות 3.0 חדרים (80 מ"ר)\\nקומה: 14 מתוך 14<div class="mFooterAction"></div></div>';
const r = S.komoRows(h).rows[0]; console.log(JSON.stringify([r.floor, r.floor_said]));"""
        out = subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(json.loads(out), [None, 14])


class TestReadingFamilies(unittest.TestCase):
    def test_plenty_of_parking_said_other_ways(self):
        for t in ("אזור שקט ושפע חניה", "- שפע של מקומות חניה", "קרובה להכל , חניון בשפע .", "חניה יש בשפע,"):
            self.assertEqual(_a(t, "parking")["answer"], "street", t)
        self.assertEqual(_a("חניה בבניין", "parking")["answer"], "building")
        self.assertEqual(_a("מחסן גדול בקירוב לחניה", "parking").get("answer", "not_stated"), "not_stated")  # near it

    def test_a_studio_layout_isnt_a_studio(self):
        self.assertNotEqual(_a("סטודיו=(סלון+מטבח) + חדר שינה", "apartment_type").get("answer"), "studio")
        self.assertEqual(_a("דירת סטודיו מרוהטת", "apartment_type")["answer"], "studio")

    def test_balcony_furniture_is_a_check(self):
        self.assertEqual(_a("ריהוט סלון / ריהוט מרפסת / וילונות", "balcony")["answer"], "unclear")
        self.assertEqual(_a("מרפסת שמש גדולה", "balcony")["answer"], "yes")

    def test_the_building_fee_in_the_rent(self):
        for t in ("המחיר כולל תשלום לועד הבית.", "(המחיר כולל גם אינטרנט וועד וארנונה וכבלים)",
                  "התשלום לדירה בסך 4000 שקלים כולל תשלום עבור ועד בית אחזקה"):
            self.assertEqual(_a(t, "vaad_bayit")["answer"], "included", t)
        self.assertNotEqual(_a("כולל מים ועד 3 מזגנים", "vaad_bayit").get("answer"), "included")

    def test_an_amount_after_a_dash(self):
        self.assertEqual((_a("ועד בית - 150 ש\"ח בחודש\nמקרר", "vaad_bayit")["answer"], _a("ועד בית - 150 ש\"ח בחודש\nמקרר", "vaad_bayit")["value"]),
                         ("amount", 150))
        got = _a("ארנונה - כ-270 שח לחודשיים, חשמל ומים", "arnona")
        self.assertEqual((got["answer"], got["value"]), ("amount", 135))


if __name__ == "__main__":
    unittest.main()
