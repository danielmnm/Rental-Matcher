"""
v1.51: batch 8's errors fixed, and the rules taught the phrasings the 640
labeled listings use that they couldn't read yet, so the AI has less to fill
in. Every change was checked against all 640: 0 wrong, 0 hidden, before it
stayed. These numbers are in-sample (the rules were written from these
listings); the honest one comes from batch 9.
"""

import json
import unittest
from pathlib import Path

from rental_matcher.extraction.rules import answer, combine

ROOT = Path(__file__).resolve().parents[1]


def _a(text, q):
    got = answer(text)[q]
    return got["answer"], sorted(got.get("items", []))


class TestBatch8Errors(unittest.TestCase):
    def test_hebrew_prefixes(self):
        # "הוספה" (was added) isn't ה+ו+ספה: ו only comes first
        self.assertEqual(_a("לאחרונה הוספה מרפסת שמש לדירה", "furniture"), ("not_stated", []))
        self.assertEqual(_a("כולל ספה ומיטה", "furniture"), ("items", ["bed", "sofa"]))
        self.assertEqual(_a("והספה נשארת", "furniture"), ("items", ["sofa"]))

    def test_old_units_being_removed_are_not_ac(self):
        self.assertEqual(_a("המזגנים שרואים במרפסת זה חלקים ישנים שיפונו מהדירה", "air_conditioning")[0], "unclear")
        self.assertEqual(_a("מזגנים בכל החדרים", "air_conditioning")[0], "yes")

    def test_roof_duplex_and_penthouse(self):
        self.assertEqual(_a("דירת דופלקס גג 4.5 חדרים", "apartment_type")[0], "roof")
        self.assertEqual(_a("להשכרה דופלקס גג ענק", "apartment_type")[0], "roof")
        self.assertEqual(_a("פנטאהוז מהמם", "apartment_type")[0], "roof")
        self.assertEqual(_a("דופלקס ענק", "apartment_type")[0], "duplex")

    def test_like_a_house_is_not_a_house(self):
        self.assertEqual(_a("דירה שהיא כמו בית פרטי. מרחב ופרטיות", "apartment_type")[0], "not_stated")
        self.assertEqual(_a("בית פרטי להשכרה", "apartment_type")[0], "house")

    def test_the_buildings_laundry_is_not_the_flats_washer(self):
        self.assertEqual(_a("בביניין יש חדר כביסה עם מכונות כביסה וייבוש", "furniture")[0], "unclear")
        self.assertEqual(_a("בדירה מכונת כביסה ומקרר", "furniture"), ("items", ["fridge", "washer"]))

    def test_partly_furnished_in_other_words(self):
        self.assertEqual(_a("מרוהטת באופן חלקי.", "furniture"), ("items", ["says_partly_furnished"]))
        self.assertEqual(_a("מרוהטת באופו חלקי.", "furniture"), ("items", ["says_partly_furnished"]))

    def test_a_room_for_closets_is_not_closets(self):
        self.assertEqual(_a("חצי חדר עם חלון לחדר עבודה/ארונות", "furniture")[0], "not_stated")

    def test_a_furnished_room_for_rent_is_furnished(self):
        text = "להשכרה: חדר מרוהט כולל מרפסת פרטית. האמבטיה והמטבח משותפים."
        self.assertEqual(_a(text, "room_share")[0], "yes")
        self.assertEqual(_a(text, "furniture"), ("items", ["says_furnished"]))
        # in a whole flat, a furnished room is still one room
        self.assertEqual(_a("דירת 3 חדרים, חדר מרוהט", "furniture"), ("items", ["says_partly_furnished"]))

    def test_parking_modifiers_stay_on_their_line(self):
        # was "building" from "\n\nבבניין" two lines down: hid vryeiy5h from a must-have of its own space
        # v1.53: "underground", alone, is "the building's or your own": never a reason to hide
        got = answer("חניה תת קרקעית\n\nבבניין יוקרתי חדש")["parking"]
        self.assertEqual((got["answer"], got.get("or")), ("building", ["deeded"]))

    def test_parking_you_can_rent_or_a_public_lot(self):
        self.assertEqual(_a("ניתן לשכור חניה ב 700 שח לחודש מהבניין הסמוך", "parking")[0], "unclear")
        self.assertEqual(_a("חניון ציבורי רחב מאחורי הבניין", "parking")[0], "street")

    def test_a_vaad_that_pays_for_the_pool(self):
        self.assertEqual(_a("בריכה וסאונה בבניין כלולים במיסי וועד הבית.", "vaad_bayit")[0], "unclear")


class TestMorePhrasings(unittest.TestCase):
    def test_shelter(self):
        for text in ("מעלית ומקלט.", "מקלט שמור בבניין", "בבניין קיים מקלט", "מיקלט לביניין!"):
            self.assertEqual(_a(text, "protected_space")[0], "yes", text)
        for text in ("פחות מדקה למקלט ציבורי", "יש מקלט ציבורי ממול", "יש מקלט בחצר הגן"):
            self.assertNotEqual(_a(text, "protected_space")[0], "yes", text)

    def test_broker(self):
        for text in ("תיווך: חודש+מעמ", "מפתחות במשרדנו", "צוות רם נכסים.", "להשכרה מתיווך:", "יועצת ומתווכת נדל\"ן",
                     "להשכרה עם עמלה מופחתת חצי חודש+מעמ"):
            self.assertEqual(_a(text, "broker")[0], "broker", text)
        for text in ("לא למתווכים.", "פרטי לא מתווך.", "ללא עלות תיווך"):
            self.assertEqual(_a(text, "broker")[0], "no_broker", text)
        self.assertEqual(_a("יש עוד נכסים באזור", "broker")[0], "not_stated")

    def test_fees_included(self):
        for text in ("המחיר כולל-ארנונה,מים וחשמל", "דמי השכירות כוללים ארנונה", "הכל כלול (חשמל, מים וארנונה)",
                     "מחיר: 4,750 ש\"ח - כולל ארנונה, מים וועד בית", "המחיר כולל חשבונות (מים,חשמל ,ארנונה )"):
            self.assertEqual(_a(text, "arnona")[0], "included", text)
        self.assertEqual(answer("ארנונה כ 600 ש\"ח לחודש")["arnona"].get("value"), 600)

    def test_whole_flat(self):
        for text in ("להשכרה 4 חד' מרווחת", "דירת שניי חדרים", "בית פרטי להשכרה", "מתאימה ליחיד או זוג שקט בלבד",
                     "דירה עורפית", "לא לשותפים"):
            self.assertEqual(_a(text, "room_share")[0], "no", text)
        self.assertEqual(_a("חדר להשכרה בדירת 4 חד'", "room_share")[0], "yes")

    def test_parking(self):
        for text in ("2 חניות צמודות ומחסן", "2 חניות פרטיות", "חניה + מחסן בטאבו", "חנייה ומחסן צמודים",
                     "לדירה 2 חניות ומחסן", "כולל חניה בטאבו ברחוב בלפור 139"):
            self.assertEqual(_a(text, "parking")[0], "deeded", text)
        self.assertEqual(_a("חניה זמינה ברחוב (אפור)", "parking")[0], "street")
        self.assertEqual(answer("2 חניות")["parking"].get("or"), ["deeded"])  # whose: still a check (v1.53: "building or own")

    def test_outdoor_space_and_type(self):
        for text in ("+גג פתוח כ 60 מטר", "שטח גג פרטי וגדול", "עם שני מרספות", "2 מירפסות נוספות"):
            self.assertEqual(_a(text, "balcony")[0], "yes", text)
        self.assertEqual(_a("דירת גג 5 חדרים", "balcony")[0], "not_stated")  # the type, not a terrace
        self.assertEqual(_a("דירת 3 חדרים בקומת קרקע, עם גינה", "apartment_type")[0], "garden")
        self.assertEqual(_a("דירת קרקע במקום מרכזי. חלון לגינה פנימית", "apartment_type")[0], "not_stated")

    def test_furnished(self):
        for text, items in (("ללא רהוט", ["says_unfurnished"]), ("כולל כל הריהוט", ["says_furnished"]),
                            ("דירה מושכרת עם רהוט", ["says_furnished"]), ("דירות מרוהטות קומפלט", ["says_furnished"])):
            self.assertEqual(_a(text, "furniture"), ("items", items), text)

    def test_elevator(self):
        self.assertEqual(_a("ללא מעלית וללא חניה", "elevator")[0], "no")
        self.assertEqual(_a("דירה בקומה ה7", "elevator")[0], "yes")


class TestTheRatchet(unittest.TestCase):
    """What the rules read on all 640 can't quietly get worse: no wrong answer, no
    listing hidden for any setting, and at least this much read."""

    def test_on_all_640(self):
        from rental_matcher.extraction.evaluate import gold_set, score, settled_coverage, wrongly_hidden
        texts = json.loads((ROOT / "tests" / "eval" / "yad2_texts.json").read_text(encoding="utf-8"))
        gold = gold_set()
        rules = {k: answer(v) for k, v in texts.items()}
        t = score(gold, rules)["ALL"]
        self.assertEqual(t.wrong, 0)
        self.assertEqual(wrongly_hidden(gold, rules), {})
        got, of = settled_coverage(gold, rules)["ALL"]
        self.assertGreaterEqual(got, 1577)  # of 1610 (v1.50: 1428, v1.51: 1561); raise this when it rises
        self.assertEqual(of, 1610)

    def test_with_gemini_fewer_answers_stand_alone(self):
        # in-sample: Gemini's Oct 28 run over the same 640, combined with today's rules
        from rental_matcher.extraction.evaluate import gold_set, score
        from rental_matcher.extraction.prompt import ground
        texts = json.loads((ROOT / "tests" / "eval" / "yad2_texts.json").read_text(encoding="utf-8"))
        gem = json.loads((ROOT / "tests" / "eval" / "runs" / "2026-10-28_gemini_b8_p9e70d1_2.json").read_text(encoding="utf-8"))
        both = {k: combine(answer(v), ground(gem[k], v)) for k, v in texts.items()}
        self.assertLessEqual(score(gold_set(), both)["ALL"].wrong, 2)  # v1.50 rules: 10; v1.59: 2 (rules stay silent where they used to guess; Gemini fills two)


if __name__ == "__main__":
    unittest.main()
