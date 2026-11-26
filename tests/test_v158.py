"""v1.58: what batch 11 (held out under v1.57) taught, fitted after it was measured.

The families: kitchen and electrical cabinets read as closets, "ספת/שולחן טלוויזיה" read as a TV or a table,
"אינה מרוהטת" and "לא כולל מוצרי חשמל" read as furnished/equipped, furniture for sale read as partly
furnished, and one-offs (a shelter nearby, a balcony option, "ללא מעלות", a shared balcony, the roof's floor).
Batch 11 is in-sample from here: its pins below are not a held-out result.
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
    def test_kitchen_and_electrical_cabinets_are_not_closets(self):
        self.assertNotIn("closets", _items("מטבח גדול עם שפע של ארונות ואבזור מלא: מדיח כלים, מקרר"))
        self.assertNotIn("closets", _items("ארונות חשמל הוחלפו הכל חדש"))
        self.assertIn("closets", _items("יש ארונות מטבח וארון גדול בחדר"))  # the room's closet still counts
        self.assertIn("closets", _items("פירוט ריהוט: מטבח מאובזר קומפלט חדר כושר שתי ארונות בשתי חדרים"))

    def test_a_cabinet_is_singular_closets_plural(self):
        self.assertIn("cabinet", _items("פירוט ריהוט: מיטה זוגית, שידה וארונית"))
        self.assertIn("closets", _items("פירוט ריהוט: 10 מיטות ארוניות שולחן וכיסאות"))

    def test_tv_furniture_is_not_a_tv_or_a_table(self):
        self.assertNotIn("tv", _items("פירוט ריהוט: מיטה, ספת טלוויזיה, מקרר"))
        self.assertNotIn("table_chairs", _items("פירוט ריהוט: מיטה, שולחן לטלוויזיה, מקרר"))

    def test_denied_furniture_and_appliances(self):
        self.assertIn("says_unfurnished", _items("הדירה אינה מרוהטת"))
        self.assertNotIn("says_equipped", _items("מרוהטת, לא כולל מוצרי חשמל"))
        self.assertNotIn("says_partly_furnished", _items("חלק מהריהוט למכירה. ארון בגדים"))

    def test_more_ways_to_say_furnished_or_equipped(self):
        self.assertIn("says_furnished", _items("יש ריהוט קופלט"))
        self.assertIn("says_equipped", _items("הדירה מרוהטת קומפלט וציוד חשמלי כל הבית"))
        self.assertIn("says_equipped", _items("דירת גג מצויידת קומפלט"))
        self.assertIn("oven_stove", _items("מקרר, מיטה, 2 ארונות, מכונת כביסה, אינדוקציה"))
        self.assertTrue({"bed", "washer"} <= _items("מרוהטת קומפלט מקרר מכונתכביסה ארון ניטה זוגית"))
        self.assertNotIn("says_equipped", _items("שידה במקלחת.\nמוצרי חשמל - טלויזיה, מקרר"))  # a list's heading
        self.assertIn("says_equipped", _items("מרוהטת קומפלט!\nכולל מוצרי חשמל: מזגן, מקרר"))

    def test_one_offs(self):
        self.assertNotEqual(_a("קרובה לממד", "protected_space")["answer"], "yes")
        self.assertNotEqual(_a("אפשרות לסידור פינת ישיבה או מרפסת", "balcony")["answer"], "yes")
        self.assertEqual(_a("16 מדרגות ללא מעלות לא מתאים למי שצריך מעלית", "elevator")["answer"], "no")
        self.assertEqual(_a("מרפסת וגינה משותפות, מקלט בסמוך", "balcony")["answer"], "unclear")
        self.assertNotEqual(_a("וכן מגוון דירות של 4 ו 5 חדרים עם נוף,מרפסת סוכה", "balcony")["answer"], "yes")
        self.assertNotEqual(_a("הדירה בקומה 5 (בקומה 6 גג הבניין)", "elevator")["answer"], "yes")
        self.assertEqual(_a("- דו משפחתי 6 חדרים\n- 3 מפלסים", "apartment_type")["answer"], "house")
        self.assertNotEqual(_a("2 כיווני אוויר, חניה בשפע במקום", "parking")["answer"], "street")


class TestBatch11InSample(unittest.TestCase):
    """Batch 11 after v1.58: 0 wrong on the card and every question at 95% or more. One listing is still hidden:
    lj4mlmq9 says "חניה בבניין" and Yad2's box only says parking is included; the labelers allowed a deeded spot,
    the card reads building. Left open: making "בבניין" two-way costs facts on the 640 (README)."""

    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        from rental_matcher.extraction.evaluate import widen
        cls.gold, texts = widen(load("holdout11/gold.json")["gold"], load("holdout11/adjudications.json")["adjudications"]), load("holdout11/texts.json")  # v1.59.1: with the owner's parking ruling
        cls.ans = {k: answer(texts[k]) for k in cls.gold}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout11_2026-11-02")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(cls.ans[k], {}) for k in tg}, PREFS)

    def test_text(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage
        t = score(self.gold, self.ans)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold), (0, 695, 735))  # v1.59: 693
        self.assertEqual(settled_coverage(self.gold, self.ans)["ALL"], (656, 689))  # v1.59.1: with the owner's parking ruling (655, 688 before)

    def test_card(self):
        from rental_matcher.extraction.evaluate import score, settled_credit, universal_bar, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        self.assertEqual((len(self.cg), t.wrong, t.correct_definite, t.definite_gold), (257, 0, 1585, 1604))  # v1.59: 1584
        self.assertAlmostEqual(settled_credit(self.cg, self.ca)["ALL"][0], 1485.8, places=0)  # 1484.8 before the owner's parking ruling
        right, n = settled_credit(self.cg, self.ca)["furniture"]
        self.assertGreaterEqual(right / n, 0.95)
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in wrongly_hidden(self.cg, self.ca).items()},
                         {})  # v1.59.1: lj4mlmq9 "חניה בבניין" is the building's, not deeded (owner ruling): nothing hidden
        failed = [c for c, ok in universal_bar(self.cg, self.ca, partial=True) if not ok]
        self.assertEqual(len(failed), 0)  # the whole Card test bar, in-sample


if __name__ == "__main__":
    unittest.main()


class TestHeldOutBatch12(unittest.TestCase):
    """277 listings fetched Nov 3 after the rules were frozen (tag rules-v1.58-frozen, 66f9931), from ten cities no batch
    or census had used (Herzliya, Kfar Saba, Rishon LeZion, Tiberias, Eilat, Kiryat Gat, Akko, Kiryat Ata, Dimona,
    Bnei Brak); none among the 640 or an earlier batch. The browser saved the pull as one file, checked by its SHA-256.
    Two blind labelers in private folders: 2987/3047 exact, 3046/3047 compatible (the one conflict kept both answers).
    The frozen run was saved before any labels existed. Pinned as measured; nothing fitted on it."""

    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        cls.gold, cls.texts = load("holdout12/gold.json")["gold"], load("holdout12/texts.json")
        cls.frozen = {k: v for k, v in load("runs/2026-11-03_rules_v158_frozen_on_holdout12.json").items() if not k.startswith("_")}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout12_2026-11-03")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(cls.frozen[k], {}) for k in tg}, PREFS)

    def test_the_frozen_run_is_what_the_frozen_rules_say(self):
        from rental_matcher.extraction.evaluate import gold_set
        self.assertEqual(len(self.gold), 277)
        self.assertFalse(set(self.gold) & set(gold_set()))
        # v1.59 fitted on this batch (tests/test_v159.py): the frozen run is the record of what v1.58 said
        self.assertNotEqual({k: answer(self.texts[k]) for k in self.gold}, self.frozen)

    def test_the_text(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage
        t = score(self.gold, self.frozen)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold), (16, 739, 793))
        self.assertEqual(settled_coverage(self.gold, self.frozen)["ALL"], (695, 744))

    def test_the_card(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage, settled_credit, universal_bar, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        # as measured at v1.58: 12 wrong. The frozen run is scored here with v1.59's card, which shows a range where
        # the ad and Yad2's field disagree on the vaad (a check, not a wrong answer): 11
        self.assertEqual((len(self.cg), t.wrong, t.correct_definite, t.definite_gold), (270, 11, 1599, 1650))
        self.assertEqual(settled_coverage(self.cg, self.ca)["ALL"], (1508, 1558))
        self.assertAlmostEqual(settled_credit(self.cg, self.ca)["ALL"][0], 1520.5, places=0)  # 97.6%
        self.assertEqual(sorted(w.split("/")[1].split(":")[0] for w in t.wrong_items),
                         ["apartment_type"] * 3 + ["furniture"] * 6 + ["room_share"] * 2)
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in wrongly_hidden(self.cg, self.ca).items()},
                         {"room_share": ["4gn95utr", "vo5vq8q1", "wkwjyaso"], "parking": ["axx11t41"]})
        failed = [c for c, ok in universal_bar(self.cg, self.ca, partial=True) if not ok]
        self.assertEqual(len(failed), 5)  # 12 wrong (11 with v1.59's range), 4 hidden, under 95%: parking 31/34, apartment type 79/86, furniture 115.5/130
