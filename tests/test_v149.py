"""
v1.49: the reading fixes after held-out batch 7, and a pass bar that holds for
every user, not only for The first test user's must-haves.

Batch 7 can no longer be a fair test of these rules: its errors are what they
were written from. The honest number comes from a fresh batch 8.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rental_matcher.extraction.rules import answer, furniture, furniture_for_sale
from rental_matcher.pipeline import build_listing
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
WHEN = datetime(2026, 10, 28, tzinfo=timezone.utc)
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


def _x(**over):
    base = {"id": "t1", "adType": "private", "price": 4800, "floor": 2, "city": "תל אביב יפו", "neighborhood": "יד אליהו",
            "street": "דרך ההגנה", "additionalDetails": {"roomsCount": 2, "squareMeterBuild": 50, "property": {"text": "דירה"}},
            "inProperty": {"includeAirconditioner": True}, "description": "דירת 2 חדרים, קומה 2, מרפסת"}
    return {**base, **over}


def _items(text):
    a = furniture(text)
    return (a or {}).get("answer"), sorted((a or {}).get("items", []))


class TestFurniture(unittest.TestCase):
    def test_a_place_for_something_is_not_the_thing(self):
        # batch 7: hu93jybf, m5i3vl5w, 2oj7a2bi
        self.assertEqual(_items("סלון ופינת אוכל מרווחים. נישה נסתרת למכונת כביסה."), (None, []))
        self.assertEqual(_items("חדר רחצה מרווח עם מיקום למכונות כביסה, יש ריהוט מלא בדירה"), ("items", ["says_furnished"]))
        self.assertEqual(_items("בסלון נישה בה אפשר להעמיד שולחן ומחשב. חדר שינה עם ארון קיר."), ("items", ["closets"]))
        self.assertEqual(_items("מטבח עם מקום למקרר"), (None, []))

    def test_the_thing_itself_still_counts(self):
        self.assertEqual(_items("כולל מכונת כביסה ומקרר"), ("items", ["fridge", "washer"]))
        self.assertEqual(_items("כיריים אינדוקציה, קולט אדים ומקרר"), ("items", ["fridge", "oven_stove"]))

    def test_for_sale_is_not_included(self):
        # batch 7: goivkerr. "למכירה" used to read as a stove ("כירה")
        self.assertEqual(_items("רוב הריהוט ומוצרי החשמל מוצעים למכירה"), ("unclear", []))
        self.assertEqual(_items("חלק מהריהוט ניתן לרכישה מול השוכרת הקודמת"), ("unclear", []))
        # what isn't for sale still comes with it
        self.assertEqual(_items("כולל מקרר ומכונת כביסה. הספה והטלוויזיה למכירה."), ("items", ["fridge", "washer"]))

    def test_for_sale_is_its_own_fact(self):
        for text in ("רוב הריהוט ומוצרי החשמל מוצעים למכירה", "חלק מהריהוט ניתן לרכישה מול השוכרת הקודמת",
                     "המשכיר מוכר את הספה"):
            self.assertEqual((furniture_for_sale(text) or {}).get("answer"), "yes", text)
        for text in ("דירה למכירה", "מקום מוכר וטוב, כולל מקרר", "ממ\"ד מוכר", "כולל ריהוט מלא"):
            self.assertIsNone(furniture_for_sale(text), text)

    def test_the_card_says_for_sale(self):
        s = build_listing(_x(description="דירת 2 חדרים. רוב הריהוט מוצע למכירה."), PREFS, pulled_at=WHEN).signals
        self.assertIs(s["furniture_for_sale"].value, True)
        self.assertNotIn("furniture_for_sale", build_listing(_x(), PREFS, pulled_at=WHEN).signals)
        from rental_matcher.server import FEATURE_KEYS, FEATURE_WORDS
        self.assertIn("furniture_for_sale", FEATURE_KEYS)
        self.assertIn("furniture_for_sale", FEATURE_WORDS)


class TestParkingPhraseBook(unittest.TestCase):
    def _p(self, text):
        return answer(text)["parking"]["answer"]

    def test_settled_phrasings(self):
        for text, kind in (("חניה בטאבו", "deeded"), ("חניה בטבו- יש", "deeded"), ("חניה פרטית", "deeded"),
                           ("חניה משותפת לדיירי הבניין", "building"), ("חניה רובוטית", "building"),
                           ("חניה ע\"ב מקום פנוי", "building"), ("יש חנייה עם שער רק לדיירי הבניין בלבד", "building"),
                           ("חניה בשפע ברחוב", "street"), ("חניה כחול לבן גדולה חינם לתושבי ר\"ג", "street"),
                           ("חניה באפור במפרץ", "street"), ("חניה ציבורית צמודה לבית ופנויה", "street"),
                           ("שפע של חנייה!! ברחוב", "street"), ("שפע חניה באזור + תו חניה לכל דייר", "street")):
            self.assertEqual(self._p(text), kind, text)

    def test_two_way_phrasings_are_a_check(self):
        # the labelers read these as the building's OR the apartment's own (or the street's OR
        # the lot's): a definite answer would hide the listing from someone the other suits
        # v1.53: the first kind is now said as such: "building" with or=["deeded"], which a user who
        # needs their own space still gets as a check, and one who needs any space doesn't
        for text in ("יש חניה", "כולל חניה", "2 חניות", "מעלית וחניה", "חניה מקורה", "חנייה תת-קרקעית", "חניה לדיירים"):
            self.assertEqual((self._p(text), answer(text)["parking"].get("or")), ("building", ["deeded"]), text)
        for text in ("חניה חופשית במגרש גדול צמוד לבניין", "יש תו חניה", "אין בעיית חנייה"):
            self.assertEqual(self._p(text), "unclear", text)

    def test_not_parking_or_not_a_denial(self):
        self.assertEqual(self._p("פלוס חניה\nללא תיווך! מפרטי."), "building")  # the denial is the next line's (v1.53: or deeded)
        self.assertEqual(self._p("ללא מעלית עם חניה משותפת לדיירי הבניין"), "building")  # "עם" ends the "ללא"
        self.assertEqual(self._p("ללא חניה"), "none")
        self.assertEqual(self._p("קרוב לחניון"), "not_stated")


class TestOtherBatch7Fixes(unittest.TestCase):
    def test_balconies_planned_or_gone(self):
        text = "מטבח מרווח עם מרפסת שירות. תוך כשנה הבניין צפוי להתחיל בנייה של מרפסות וממדים"
        self.assertEqual(answer(text)["balcony"]["answer"], "service_only")
        self.assertEqual(answer("מרפסת כביסה נוחה. סלון גדול ( מרפסת נפתחה להרחבת הסלון)")["balcony"]["answer"], "service_only")
        self.assertEqual(answer("הבניין צפוי לעבור תמ\"א עם מרפסות")["balcony"]["answer"], "unclear")
        self.assertEqual(answer("מרפסת שמש גדולה")["balcony"]["answer"], "yes")

    def test_a_parking_permit_per_resident_is_not_rent_per_person(self):
        self.assertNotEqual(answer("דירת 3 חדרים. שפע חניה באזור + תו חניה לכל דייר")["room_share"]["answer"], "yes")
        self.assertEqual(answer("חדר להשכרה, 2600 ₪ לחדר")["room_share"]["answer"], "yes")

    def test_fees(self):
        self.assertEqual(answer("ארנונה: 800 ש\"ח | אין ועד בית")["arnona"]["answer"], "unclear")  # per month or two?
        self.assertEqual(answer("ארנונה 700 שח לחודשיים")["arnona"]["answer"], "amount")
        got = answer("ארנונה זולה.ללא וועד בית.")["vaad_bayit"]
        self.assertEqual((got["answer"], got.get("value")), ("amount", 0))

    def test_a_yard_on_the_top_floor_is_a_check(self):
        self.assertEqual(answer("דירת 2 חדרים בקומה אחרונה, עם חצר פרטית מגודרת")["apartment_type"]["answer"], "unclear")
        self.assertEqual(answer("דירת גן עם חצר")["apartment_type"]["answer"], "garden")

    def test_grounding_refuses_kitchen_cabinets_and_a_service_room(self):
        from rental_matcher.extraction.prompt import ground
        text = "ארונות מטבח עליונים ותחתונים. חדר שירות"
        got = ground({"furniture": {"answer": "items", "items": ["closets"], "evidence": "ארונות מטבח עליונים ותחתונים."},
                      "balcony": {"answer": "service_only", "evidence": "חדר שירות"}}, text)
        self.assertEqual(got["furniture"]["answer"], "not_stated")
        self.assertEqual(got["balcony"]["answer"], "not_stated")
        self.assertEqual(ground({"protected_space": {"answer": "yes", "evidence": "מיקלט לביניין"}}, "יש מיקלט לביניין")
                         ["protected_space"]["answer"], "yes")


class TestTheBarForEveryUser(unittest.TestCase):
    """Owner ruling (Oct 27): "another user may not have a must have or has another must have and
    settings so i want your testing to be universal"."""

    def setUp(self):
        self.texts = json.loads((ROOT / "tests" / "eval" / "yad2_texts.json").read_text(encoding="utf-8"))
        self.gold = json.loads((ROOT / "tests" / "eval" / "yad2_gold.json").read_text(encoding="utf-8"))["gold"]

    def test_must_haves_come_from_the_settings_catalog(self):
        from rental_matcher.extraction.evaluate import requirements
        from rental_matcher.extraction.questions import BY_ID
        self.assertEqual(requirements(BY_ID["parking"]), [("at_least", 1.0), ("at_least", 2.0), ("at_least", 3.0)])
        self.assertEqual(requirements(BY_ID["room_share"]), [("value", False)])  # "no roommates"
        self.assertEqual(requirements(BY_ID["apartment_type"]), [("is_not", "unit")])  # feeds "not a unit"
        self.assertEqual(requirements(BY_ID["furniture"]), [])  # an item is never a must-have
        # a criterion added to the catalog is tested without touching this file
        extra = [{"field": "signal:elevator", "kind": "yes_no", "wants": False}]
        self.assertEqual(requirements(BY_ID["elevator"], extra), [("value", False)])

    def test_no_listing_is_hidden_by_a_misreading_on_all_463(self):
        from rental_matcher.extraction.evaluate import score, wrongly_hidden
        # v1.51: all 640 now, batch 8 included (its errors are fixed)
        self.assertEqual(len(self.gold), 640)
        rules = {k: answer(v) for k, v in self.texts.items()}
        self.assertEqual(wrongly_hidden(self.gold, rules), {})
        self.assertEqual(score(self.gold, rules)["ALL"].wrong, 0)  # in-sample: what these rules were written from

    def test_it_catches_a_hide(self):
        from rental_matcher.extraction.evaluate import wrongly_hidden
        gold = {"x": {"elevator": {"answer": "yes", "acceptable": ["yes"], "evidence": "מעלית"},
                      "parking": {"answer": "building", "acceptable": ["building", "deeded"], "evidence": "חניה"}}}
        said = {"x": {"elevator": {"answer": "no", "evidence": "x"}, "parking": {"answer": "building", "evidence": "חניה"}}}
        self.assertEqual(wrongly_hidden(gold, said), {"elevator": {"value True": ["x"]}, "parking": {"at_least 3.0": ["x"]}})
        # the same answers from the AI alone can't hide a listing (scoring.py), so they don't count ...
        ai = {"x": {q: {**e, "source": "model"} for q, e in said["x"].items()}}
        self.assertEqual(wrongly_hidden(gold, ai), {})
        # ... and a check never hides
        self.assertEqual(wrongly_hidden(gold, {"x": {"parking": {"answer": "unclear", "evidence": "חניה"}}}), {})

    def test_settled_facts(self):
        from rental_matcher.extraction.evaluate import settled
        self.assertTrue(settled({"acceptable": ["building"]}))
        self.assertFalse(settled({"acceptable": ["building", "deeded"]}))  # read two ways: a check is right
        self.assertFalse(settled({"acceptable": ["yes", "not_stated"]}))


if __name__ == "__main__":
    unittest.main()
