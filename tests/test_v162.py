"""v1.62 (Phase 3): what Komo batch 1 found, fixed forward.

The lesson worth keeping: a rule meant to mean the same on every site lived in each adapter's own copy, and only
Yad2's got the v1.53 fix. The shared rules now live in adapters/common.py, and TestEveryAdapterAgrees fails if a
site's adapter reads them differently, so the next site can't drift the same way."""
import datetime
import json
import unittest
from pathlib import Path

from rental_matcher.adapters import komo, madlan, yad2
from rental_matcher.extraction import rules

ROOT = Path(__file__).resolve().parents[1]
DAY = datetime.date(2026, 11, 8)


def _a(text, q):
    return rules.answer(text).get(q) or {"answer": "not_stated"}


class TestEveryAdapterAgrees(unittest.TestCase):
    def _yad2(self, **kw):
        x = {"id": "t1", "price": 4000, "floor": 1, "city": "בת ים", "additionalDetails": {"roomsCount": 3}, "inProperty": {}, "description": ""}
        x.update(kw)
        return yad2.to_listing(x).signals

    def test_a_parking_space_on_the_form_is_a_floor_on_every_site(self):
        sites = {
            "yad2": self._yad2(inProperty={"includeParking": True}),
            "komo": komo.structured_signals({"parking": 1, "ticked": {}}, DAY),
            "madlan": madlan.structured_signals({"parking": 1, "amenities": {}}, DAY),
        }
        for site, s in sites.items():
            self.assertEqual(s["parking_level"].value, 2.0, site)
            self.assertIs(s["parking_at_least"].value, True, site)  # "whose isn't said": a check, never a reason to hide

    def test_no_parking_on_the_form_says_nothing(self):
        self.assertNotIn("parking_level", komo.structured_signals({"parking": 0, "ticked": {}}, DAY))
        self.assertNotIn("parking_level", madlan.structured_signals({"amenities": {}}, DAY))

    def test_a_tall_building_has_an_elevator(self):
        # the owner's ruling (Nov 5, Nov 8), applied to a site's own "floors in the building" field
        self.assertIs(komo.structured_signals({"floors": 8, "ticked": {}}, DAY)["elevator"].value, True)
        self.assertIs(madlan.structured_signals({"floors": 7, "amenities": {}}, DAY)["elevator"].value, True)
        self.assertNotIn("elevator", komo.structured_signals({"floors": 4, "ticked": {}}, DAY))

    def test_the_shared_rules_are_used_not_copied(self):
        for mod in ("yad2", "komo", "madlan"):
            src = (ROOT / "rental_matcher" / "adapters" / f"{mod}.py").read_text(encoding="utf-8")
            self.assertIn("parking_from_form(", src, mod)
            self.assertNotIn('signals["parking_level"] = _confirmed(2.0', src, mod)


class TestKomoBatch1Families(unittest.TestCase):
    def test_furniture(self):
        a = _a("חדר שינה .ספה.ארונות.כסאות שולחן מ כביסה / חסר מקרר תנור גז", "furniture")
        self.assertFalse({"fridge", "oven_stove"} & set(a["items"]))
        self.assertEqual(_a("חסר מקרר אבל יש תנור", "furniture")["items"], ["oven_stove"])
        self.assertEqual(_a("אין מקרר אבל יש תנור", "furniture")["items"], ["oven_stove"])
        self.assertEqual(_a("מתחם לחדר ארונות, עבור ארונות שרוכשים השוכרים לעצמם.", "furniture")["answer"], "not_stated")

    def test_parking_and_floor(self):
        self.assertEqual(_a("חניה וחנויות בקירבת הבניין.", "parking")["answer"], "not_stated")
        a = _a("5 חדרים בשכונה הכי טובה, עם המון חניה מתחת לבית.", "parking")
        self.assertEqual((a["answer"], a.get("or")), ("street", ["building"]))
        self.assertEqual(_a("חניה בשפע באזור", "parking").get("or"), None)
        self.assertNotEqual(_a("נמצאת בקומה -1 אך נוף של קומה 6", "elevator")["answer"], "yes")
        self.assertEqual(_a("קומה 5 מתוך 7", "elevator")["answer"], "yes")


class TestNoSeparateFee(unittest.TestCase):
    def test_none_and_included_are_told_apart_and_both_read_true(self):
        from rental_matcher.extraction.card_eval import card_answers
        from rental_matcher.scoring import PreferenceSet
        prefs = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
        x = {"id": "t1", "price": 4000, "floor": 1, "city": "בת ים", "additionalDetails": {"roomsCount": 3}, "inProperty": {}}
        none = "דירה יפה. אין תשלום ועד בית."
        got = card_answers({**x, "description": none}, rules.combine(rules.answer(none), {}), prefs)["vaad_bayit"]
        self.assertEqual((got["answer"], got.get("value")), ("amount", 0))
        inc = "דירה יפה. המחיר כולל ועד בית."
        self.assertEqual(card_answers({**x, "description": inc}, rules.combine(rules.answer(inc), {}), prefs)["vaad_bayit"]["answer"], "included")
        i18n = (ROOT / "browser" / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('cost_vaad_in: "No separate building fee"', i18n)  # true of both
        self.assertIn('cost_vaad_in: "אין ועד בית בנפרד"', i18n)


if __name__ == "__main__":
    unittest.main()


class TestTheGraderDoesntGradeItself(unittest.TestCase):
    def test_an_inferred_fact_is_shown_but_isnt_the_forms_word(self):
        from rental_matcher.extraction.card_eval import box_facts
        x = {"id": "komo:1", "source": "komo", "price": 4000, "floors": 8, "ticked": {}, "city": "חיפה"}
        self.assertIs(komo.to_listing(x).signals["elevator"].value, True)  # the card shows it
        self.assertNotIn("elevator", box_facts(x))  # the answer key doesn't take it from the form
        self.assertEqual(box_facts({**x, "ticked": {"elevator": True}}).get("elevator"), {"yes"})  # a ticked box still counts
