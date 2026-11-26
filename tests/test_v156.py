"""v1.56 (Nov 2): batch 10's misreadings, learned. Every phrasing below was a wrong answer or a miss on
held-out batch 10 (Oct 30); tests/eval/lessons.json holds all 59 of them. Batch 10 is in-sample from here:
its numbers below show the fixes took, not that the rules are good enough (that needs batch 11)."""

import json
import unittest
from pathlib import Path

from rental_matcher.extraction.evaluate import score, settled_coverage, settled_credit, universal_bar, widen, wrongly_hidden
from rental_matcher.extraction.rules import answer, combine

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "eval"


def _a(text, q):
    return answer(text).get(q) or {"answer": "not_stated"}


class TestBatch10Phrasings(unittest.TestCase):
    def test_parking_placed_on_the_street(self):
        for text in ("כניסה נפרדת מהחצר. חניה בכביש, גישה נוחה לחדר.", "בנוסף מפרץ חניה עירוני צמוד לבניין עם זכאות לחניה חינמית.",
                     "נמצאת ברחוב שקט ועורפי מלא חניה, ישנה יציאה"):
            self.assertEqual(_a(text, "parking")["answer"], "street", text)
        self.assertEqual(_a("יש הרבה חניה למטה מתאימה ליחיד", "parking")["answer"], "building")
        self.assertEqual(_a("2 חנויות פרטיות בחניון תת קרקעי", "parking")["answer"], "deeded")  # the typo
        self.assertEqual(_a("2 מטבחים, יש לנכס חנייה מקורה 1, גינה", "parking")["answer"], "deeded")
        for text in ("שער כניסה נפרד דרך החניה.", "נוף פתוח וגם משמת לחניות ולטיולים עם הכלב", "קרוב לחנויות ולתחבורה"):
            self.assertEqual(_a(text, "parking")["answer"], "not_stated", text)

    def test_tv_channels_in_the_price_are_not_a_tv(self):
        for text in ("המחיר כולל- ארנונה, מים, כבלים טלויזיה,", "המחיר כולל ארנונה, מים, אינטרנט וטלוויזיה. חשמל במונה נפרד.",
                     "מאובזרת קומפלט..כולל אינטרנט וערוצי טלביזיה..ארנונה מים"):
            self.assertNotIn("tv", _a(text, "furniture").get("items") or [], text)
        self.assertIn("tv", _a("פירוט ריהוט: 2 טלוויזיות LCD, ספה חדשה, מזנון", "furniture")["items"])
        for text in ("ארון בגדים, מקרר, מכונת כביסה, כיריים חשמליות וטליוייזיה", "מיטה זוגית מקרר ארון שולחן סלון פלזמה",
                     "תנור/נינגה/שייקר/מסחטה/ טלוויזה"):
            self.assertIn("tv", _a(text, "furniture")["items"], text)

    def test_furniture_words(self):
        self.assertEqual(_a("5חד כולל ממד מרוהטת דירה בתנאים של יח דיור", "furniture")["items"], ["says_furnished"])
        self.assertEqual(_a("פירוט ריהוט: נכסים מרוהטים קומפלט ברמה הגבוהה", "furniture")["items"], ["says_furnished"])
        self.assertEqual(_a("פירוט ריהוט: ריהוט איכותי מלא. מאובזר ומוכן למגורים", "furniture")["items"], ["says_equipped", "says_furnished"])
        self.assertIn("says_partly_furnished", _a("פירוט ריהוט: ריהוט מועט, מיטת יחיד", "furniture")["items"])
        self.assertIn("says_partly_furnished", _a("פירוט ריהוט: חלק מריהוט סלון ומרפסת", "furniture")["items"])
        self.assertIn("says_furnished", _a("יחידת בוטיק מאובזרת, חדשה, ממוזגת ומרוהטת.", "furniture")["items"])
        self.assertIn("says_furnished", _a("פירוט ריהוט: בית מרוהט וכולל ספות", "furniture")["items"])
        for text, item in (("מיטה, שידת מיטה, ספת סלון, מקרר", "sofa"), ("חדר מגורים שזלונג + טלויזיה", "sofa"),
                           ("מקרר  הרון   מיטות   מיזנון", "cabinet"), ("ארון בגדים גדול, כוננית על גלגלים", "cabinet"),
                           ("יש ארונות מטבח וארון גדול בחדר", "closets"), ("כיריים חשמליות, מכונה ומייבש כביסה", "washer")):
            self.assertIn(item, _a(text, "furniture")["items"], text)
        self.assertEqual(_a("כוללת מטבח מרווח, ממ\"ד, דוד שמש ופינת כביסה/מייבש.", "furniture")["answer"], "not_stated")
        self.assertNotIn("table_chairs", _a("פירוט ריהוט: ריהוט חלקי; ארון קיר ענק, / ארון מזווה מובנה בקיר פינת אוכל.", "furniture")["items"])

    def test_a_house_with_a_unit_is_a_house(self):
        for text in ("בית פרטי 5 חדרים, בנוי 258 מ\"ר. / בנוסף יחידת דיור נפרדת, 2 חדרים.",
                     "בית פרטי 4 מפלס אחד חזיתי בודד פלוס יחידת דיור חדשה", "להשכרה בית קרקע 6 חדרים / יש יחידת דיור בנוסף",
                     "להשכרה בית מיוחד במינו על מגרש של 920 מ\"ר. / הבית 6 חד + יחידת דיור כ50 מ\"ר"):
            self.assertEqual(_a(text, "apartment_type")["answer"], "house", text)
        self.assertEqual(_a("יחידת דיור, / קומת קרקע עם גינה , 2 חדרים", "apartment_type")["answer"], "unclear")  # both
        self.assertEqual(_a("חדר גדול בקומת קרקע-עם חצר קטנטונת", "apartment_type")["answer"], "garden")  # Owner ruling (Nov 2): that's a garden flat
        for text in ("להשכרה בית פרטי 5 חדרים", "להשכרה בית קרקע 6 חדרים", "בית מגורים צמוד קרקע. חד משפחתי", "בית דו משפחתי בשכונה שקטה"):
            self.assertEqual(_a(text, "apartment_type")["answer"], "house", text)  # Owner ruling (Nov 2): "בית פרטי/קרקע" are a private home's words
        self.assertEqual(_a("בית מגורים צמוד קרקע. חד משפחתי", "room_share")["answer"], "no")

    def test_for_one_person_is_a_whole_home(self):
        for text in ("יחידה מרוהטת. מתאים ליחיד", "השכרה לבן אדם יחיד בלבד", "לבודד/ת בלבד", "מתאימה לאדם אחד.",
                     "יחידת דיור 2500 שח מיועד לאדם יחיד עדיף סטודנט"):
            self.assertEqual(_a(text, "room_share")["answer"], "no", text)
        self.assertEqual(_a("5200 שקל לחודש, אידיאלי לאדם יחיד או לזוג", "room_share")["answer"], "not_stated")  # batch 9's labelers
        self.assertEqual(_a("חדר גדול, דלת כניסה למטבחון מהחדר. כניסה נפרדת מהחצר.", "room_share")["answer"], "unclear")

    def test_the_text_saying_included_beats_the_fee_field(self):
        from rental_matcher.extraction.card_eval import card_gold
        ex = json.loads((ROOT / "tests" / "fixtures" / "yad2_holdout10_2026-10-30" / "5om9y8zw.json").read_text(encoding="utf-8"))
        g = json.loads((EVAL / "holdout10" / "gold.json").read_text(encoding="utf-8"))["gold"]["5om9y8zw"]
        self.assertTrue(ex.get("propertyTax") and ex.get("houseCommittee"))  # Yad2's fee fields hold amounts
        gold, how = card_gold(g, ex)
        for q in ("arnona", "vaad_bayit"):
            self.assertEqual((gold[q]["answer"], how[q]), ("included", "text wins"))

    def test_rent_includes(self):
        for text in ("החשבון כולל ארנונה ומים בצריכה סבירה, חשבון חשמל בנפרד.", "דירת מרתף חדשה להשכרה הכוללת ארנונה לא כולל חשמל ומים",
                     "שכר דירה: 4,500 לחודש (כולל ארנונה, מים ואינטרנט!).", "השכירות כוללת הכל- ארנונה, מים. חשמל תוספת",
                     "מאובזרת קומפלט..כולל אינטרנט וערוצי טלביזיה..ארנונה מים ..מים חמים", "12,000ש\"ח כולל כל החשבונות  \n וועד בית, חשמל, מים וארנונה"):
            self.assertEqual(_a(text, "arnona")["answer"], "included", text)
        self.assertEqual(_a("12,000ש\"ח כולל כל החשבונות  \n וועד בית, חשמל, מים וארנונה", "vaad_bayit")["answer"], "included")
        self.assertEqual(_a("המחיר כולל מים, ארנונה לא כלולה", "arnona")["answer"] == "included", False)

    def test_elevator(self):
        self.assertEqual(_a("2 חניות מקורות  \n אין מעלית שבת  \n תריסים חשמליים", "elevator")["answer"], "unclear")
        self.assertEqual(_a("פנטאוז לבד בקומה 150 מטר עם 2 מרפסות", "elevator")["answer"], "not_stated")


class TestBatch10InSample(unittest.TestCase):
    """The card on batch 10 with today's rules. In-sample: these show the fixes took, nothing more."""

    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        from rental_matcher.scoring import PreferenceSet
        load = lambda n: json.loads((EVAL / n).read_text(encoding="utf-8"))
        gold = widen(load("holdout10/gold.json")["gold"], load("holdout10/adjudications.json")["adjudications"])  # with the owner's review
        texts = load("holdout10/texts.json")
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout10_2026-10-30")
        tg = {k: v for k, v in gold.items() if k in ex}
        cls.text = (gold, {k: answer(texts[k]) for k in gold})
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(answer(texts[k]), {}) for k in tg},
                                              PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json"))

    def test_text(self):
        g, a = self.text
        self.assertEqual(score(g, a)["ALL"].wrong, 0)
        self.assertEqual(settled_coverage(g, a)["ALL"], (664, 680))  # v1.58: 7rdl8a4w "דו משפחתי" (v1.56: 663)

    def test_card(self):
        t = score(self.cg, self.ca)["ALL"]
        # v1.57: the last 2 (5om9y8zw: "המחיר כולל ארנונה + וועד" with Yad2's fee fields filled in) were right, the owner
        # said: the field is the fee's amount, the text says the rent covers it. The card test now agrees.
        self.assertEqual(t.wrong_items, [])
        self.assertEqual(wrongly_hidden(self.cg, self.ca), {})
        self.assertEqual([c for c, ok in universal_bar(self.cg, self.ca, partial=True) if not ok], [])  # in-sample
        right, n = settled_credit(self.cg, self.ca)["ALL"]
        self.assertGreaterEqual(right / n, 0.99)


if __name__ == "__main__":
    unittest.main()
