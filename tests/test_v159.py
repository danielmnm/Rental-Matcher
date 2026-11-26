"""v1.59: what batch 12 (held out under v1.58) taught, fitted after it was measured.

Families: "X מלבד Y" (everything except Y), kitchen storage and an outdoor kitchen read as closets and
appliances, offered furniture read as there, neighbors' words read as the flat's type ("מתחת לבית פרטי",
"שכונת קוטג'ים", "לפני הפנטאהוז"), "חדר" inside a flat's description read as renting a room, fee lists
with commas or a typo, and the owner's range for a vaad/arnona the ad and Yad2's field disagree on.
Batch 12 is in-sample from here: its pins below are not a held-out result.
"""
import json
import unittest
from pathlib import Path

from rental_matcher.extraction.rules import answer, combine
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


def _a(text, q):
    return answer(text).get(q) or {"answer": "not_stated"}


def _items(text):
    return set(_a(text, "furniture").get("items") or [])


class TestPhrasings(unittest.TestCase):
    def test_everything_except(self):
        self.assertNotIn("tv", _items("פירוט ריהוט: ריהוט מלא מלבד טלוויזיות"))
        self.assertIn("says_furnished", _items("פירוט ריהוט: ריהוט מלא מלבד טלוויזיות"))
        self.assertNotIn("washer", _items("יחידה מרוהט מלבד מכונת כביסה"))
        self.assertIn("closets", _items("הדירה לא מרוהטת למעט ארון בחדר שינה"))  # the exception IS there

    def test_kitchen_storage_sink_and_outdoor_kitchen(self):
        self.assertNotIn("closets", _items("דירה מרוהטת - מיטה זוגית, מקרר. ארונות במטבח"))
        self.assertNotIn("closets", _items("מטבח קבלן עם תוספות ( אי באורך 1.8 מ', וארונות אחסון נוספים ושני כיורים)"))
        self.assertNotIn("closets", _items("אסלה תלויה כיור ארון . תריסים חדשים"))
        self.assertNotIn("says_equipped", _items("מטבח חוץ מאובזר עם משטח שיש וגריל"))
        self.assertIn("closets", _items("דירה מרוהטת, חדר ארונות ומיטה זוגית"))  # a walk-in closet room

    def test_offered_furniture_is_not_there(self):
        t = "פירוט ריהוט: ארון קיר בכל חדר\nאפשרות להשארת ריהוט נוסף כגון חדר שינה, ספה, פינת אוכל, כוורת גדולה"
        self.assertNotIn("sofa", _items(t))
        self.assertNotIn("table_chairs", _items(t))

    def test_more_furniture_words(self):
        self.assertIn("says_furnished", _items("יש בה הכל כל הריהוט"))
        self.assertIn("says_furnished", _items("מסודרת ומרוהטת"))
        self.assertIn("says_unfurnished", _items("דירה ריקה"))
        self.assertIn("says_unfurnished", _items("אין רהיטים, רק ספות"))
        self.assertIn("washer", _items("מיטה,ארון בגדים,ספות, מכונת ,כביסה"))
        self.assertIn("says_equipped", _items("מיטות ארון וכל ציוד החשמל הנדרש"))

    def test_apartment_type_words_about_the_surroundings(self):
        self.assertNotEqual(_a("דירת 2 חדרים, קומת קרקע עם מרפסת, משופצת, מתחת לבית פרטי", "apartment_type")["answer"], "house")
        self.assertNotEqual(_a("בקומה גבוהה בלב שכונת קוטג'ים שקטה", "apartment_type")["answer"], "house")
        self.assertNotEqual(_a("דירת 4 חדרים בקומה הכי גבוהה לפני הפנטאהוז", "apartment_type")["answer"], "roof")
        self.assertEqual(_a("להשכרה דו משפחתי, 5 חדרים.\nיחידת דיור עם כניסה נפרדת שיכולה לשמש כקליניקה", "apartment_type")["answer"], "house")
        self.assertEqual(_a("היחידת הדיור משופצת עם גינה", "apartment_type")["answer"], "unit")

    def test_a_room_word_inside_a_flat(self):
        self.assertNotEqual(_a("יחידת הורים, ארון קיר בכל חדר ומחסן בדירה. מטבח מאובזר", "room_share")["answer"], "yes")
        self.assertNotEqual(_a("דירת 2 חדרים להשכרה חדר וסלון קומה ראשונה", "room_share")["answer"], "yes")
        self.assertEqual(_a("חדר גדול להשכרה בדירה משותפת", "room_share")["answer"], "yes")

    def test_fee_lists(self):
        self.assertEqual(_a("הדירה מרוהטת חלקית, והמחיר כולל, כבלים, ארנונה, ועד בית, מים וחשמל", "arnona")["answer"], "included")
        self.assertEqual(_a("כלול במחיר: מים, ארנונה ואינטרנט (חשמל לפי צריכה)", "arnona")["answer"], "included")
        self.assertEqual(_a("מרוהטת. כולל מים.ארנונה.", "arnona")["answer"], "included")
        self.assertEqual(_a("2700 כוללל ארנונה ומים.", "arnona")["answer"], "included")

    def test_a_buildings_height_is_evidence_of_a_lift(self):
        self.assertEqual(_a("דירת 5 חדרים, קומה 2 מתוך 8.", "elevator")["answer"], "yes")  # v1.59.1: the owner restored the old reading
        self.assertEqual(_a("דירה בקומה 7 ללא מעלית", "elevator")["answer"], "no")

    def test_parking_in_the_building_is_not_deeded(self):
        # Owner ruling (Nov 5): "חניה בבניין" is a space in the building found by availability, like the street with better odds;
        # a deeded or guaranteed space is always said so (צמודה, בטאבו) because it changes the price
        for t in ("חניה בבניין", "שתי חניות בבניין"):
            a = _a(t, "parking")
            self.assertEqual(a["answer"], "building", t)
            self.assertNotIn("deeded", a.get("or", []), t)
        self.assertEqual(_a("חניה צמודה בבניין", "parking")["answer"], "deeded")
        self.assertEqual(_a("חניה בטאבו בבניין", "parking")["answer"], "deeded")


class TestFeeRange(unittest.TestCase):
    """Owner ruling (Nov 5): when the ad's text and Yad2's field give different amounts, the card shows a range."""

    def test_the_text_and_the_field_disagree(self):
        from rental_matcher.extraction.card_eval import card_answers, load_extracts
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout12_2026-11-03")["9b8fxs9s"]  # text: 150, Yad2: 110
        texts = json.loads((ROOT / "tests" / "eval" / "holdout12" / "texts.json").read_text(encoding="utf-8"))
        got = card_answers(ex, combine(answer(texts["9b8fxs9s"]), {}), PREFS)
        self.assertEqual(got["vaad_bayit"]["answer"], "unclear")
        self.assertIn("110-150", got["vaad_bayit"]["evidence"])

    def test_the_model_and_the_screen(self):
        from rental_matcher.schema import RecurringCosts
        c = RecurringCosts(vaad_bayit_monthly=110, vaad_bayit_monthly_max=150)
        self.assertEqual((c.vaad_bayit_monthly, c.vaad_bayit_monthly_max, c.arnona_monthly_max), (110, 150, None))
        self.assertIn("vaad_bayit_max", (ROOT / "rental_matcher" / "server.py").read_text(encoding="utf-8"))
        self.assertIn("costs.vaad_bayit_max", (ROOT / "browser" / "cards.js").read_text(encoding="utf-8"))


class TestBatch12InSample(unittest.TestCase):
    """Batch 12 after v1.59, with the owner's ruling that "מחפשים 3 שותפים" is a shared flat (adjudications.json):
    0 wrong on both tests. v1.59.1 (the owner's rulings of Nov 5): "חניה בבניין" is the building's, not deeded, so nothing is
    hidden any more; "קומה 2 מתוך 8" counts the building's height as evidence of a lift. Parking at 32/35 (91%) is the one
    question under 95%: settled facts the rules leave unread, not wrong ones."""

    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        from rental_matcher.extraction.evaluate import widen
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        cls.gold = widen(load("holdout12/gold.json")["gold"], load("holdout12/adjudications.json")["adjudications"])
        texts = load("holdout12/texts.json")
        cls.ans = {k: answer(texts[k]) for k in cls.gold}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout12_2026-11-03")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(cls.ans[k], {}) for k in tg}, PREFS)

    def test_text(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage
        t = score(self.gold, self.ans)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold), (0, 768, 795))
        self.assertEqual(settled_coverage(self.gold, self.ans)["ALL"], (723, 747))

    def test_card(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage, settled_credit, universal_bar, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        self.assertEqual((len(self.cg), t.wrong, t.correct_definite, t.definite_gold), (270, 0, 1627, 1651))
        self.assertEqual(settled_coverage(self.cg, self.ca)["ALL"], (1537, 1560))
        self.assertAlmostEqual(settled_credit(self.cg, self.ca)["ALL"][0], 1545.7, places=0)
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in wrongly_hidden(self.cg, self.ca).items()},
                         {})  # v1.59.1: "שתי חניות בבניין" is the building's (owner ruling): nothing hidden
        failed = [c for c, ok in universal_bar(self.cg, self.ca, partial=True) if not ok]
        self.assertEqual(len(failed), 1)  # parking at 32/35 (91%) is the one question under 95%


if __name__ == "__main__":
    unittest.main()
