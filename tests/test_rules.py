"""
Tests for the rule-based answerer (rental_matcher/extraction/rules.py).

Most cases are false friends: phrasings that contain the keyword but
must NOT produce that answer. A rule that answers wrong is a bug; a rule
that stays silent only costs coverage, so many cases expect not_stated --
or "unclear" when the rules recognized the trap (an offer, a plan, a
shelter down the street, a contradiction): that's the text's ambiguity,
and it blocks a model from answering over it.
"""

import subprocess
import sys
import unittest
from pathlib import Path

from rental_matcher.extraction.evaluate import gold_set, load, same_questions, score
from rental_matcher.extraction.prompt import ground
from rental_matcher.extraction.rules import answer

EVAL = Path(__file__).resolve().parent / "eval"
NS = "not_stated"
UNCLEAR = "unclear"
UNC = "unclear"  # the rules saw the subject and it doesn't settle it: a check, and no model may answer over it

CASES = [
    # (question, text, expected answer[, expected value])
    ("protected_space", "יש ממ\"ד בדירה", "yes"),
    ("protected_space", "דירה עם ממ״ד", "yes"),
    ("protected_space", "וממד גדול", "yes"),
    ("protected_space", "ללא ממ\"ד", "no"),
    ("protected_space", "דירה וללא ממ\"ד", "no"),
    ("protected_space", "אין בדירה ממ\"ד", NS),  # a word between: unsafe
    ("protected_space", "ממ\"ד: אין", NS),
    ("protected_space", "ממדים גדולים במיוחד", NS),  # "dimensions"
    ("protected_space", "מקלט בבניין", "yes"),
    ("protected_space", "ומקלט מסודר", "yes"),
    ("protected_space", "יש מקלט", "yes"),
    ("protected_space", "קרוב למקלט ציבורי", UNC),
    ("protected_space", "מקלט ציבורי ברחוב", UNC),
    ("protected_space", "לא רחוק ממקלט", UNC),
    # v1.51: bare, it's the building's: every one of the 640 labeled listings that lists one was read so
    ("protected_space", "מקלט", "yes"),
    ("protected_space", "קרוב למקלט", UNC),  # a shelter nearby: a check
    ("protected_space", "צמודה לגן הבנים שיש בו מקלט", NS),  # the kindergarten's
    ("protected_space", "יש מקלט ציבורי קרוב", UNC),
    ("protected_space", "מקלט בבניין הסמוך", UNC),
    ("protected_space", "ליד מקלט בבניין", UNC),
    ("protected_space", "הדירה צמודה למקלט של הבניין", "yes"),
    ("protected_space", "ללא מקלט", "no"),
    ("protected_space", "יש ממ\"ד. ללא מקלט", "yes"),  # a safe room and no shelter: the question is either one
    ("elevator", "קומה 3 ללא מעלית", "no"),
    ("elevator", "קומה 3 וללא מעלית", "no"),
    ("elevator", "בניין עם שתי מעליות", "yes"),
    ("elevator", "קומה 2 עם מעלית שבת", "yes"),
    ("elevator", "יש הכנה למעלית", UNC),
    ("elevator", "אין צורך במעלית, קומת קרקע", UNC),
    ("elevator", "מעלית - אין", NS),
    ("elevator", "אין לנו מעלית", NS),
    ("elevator", "קומה 18, נוף", "yes"),  # no מעלית word at all, but no 18-story building lacks one
    ("elevator", "קומה 6, נוף", "yes"),  # the threshold itself
    ("elevator", "קומה 5, נוף", NS),  # one floor short: too low to assume
    ("elevator", "קומה 2 מתוך 3", NS),  # low floor, low building: unaffected
    ("elevator", "קומה 7 ללא", NS),  # Yad2's no-elevator shorthand, even on a floor that would otherwise qualify
    ("elevator", "קומה 18, הכנה למעלית", UNC),  # a real doubt (planned) still wins over the floor guess
    ("air_conditioning", "מזגן בכל חדר", "yes"),
    ("air_conditioning", "ממוזגת ומוארת", "yes"),
    ("air_conditioning", "ללא מזגנים", "no"),
    ("air_conditioning", "יש הכנה למזגן", UNC),
    ("air_conditioning", "לא ממוזגת", "no"),
    ("parking", "חניה בטאבו", "deeded"),
    ("parking", "לדירה חניה פרטית מקורה", "deeded"),
    ("parking", "חניה מקורה בטאבו", "deeded"),
    ("parking", "חניה צמודה ומקורה", "deeded"),
    ("parking", "חניה משותפת", "building"),
    ("parking", "חניה בבניין", "building"),
    ("parking", "חניה בשפע ברחוב", "street"),
    ("parking", "וגם עם חנייה בשפע", "street"),
    ("parking", "אפשרויות חניה באזור", "street"),
    ("parking", "ללא חניה", "none"),
    ("parking", "ללא חניה צמודה, יש חניה בשפע ברחוב", "street"),  # the denial is of one kind only
    ("parking", "ללא חניה צמודה", NS),
    ("parking", "ללא חניה. חניה בשפע ברחוב", "street"),  # no space of its own; street parking
    ("parking", "ללא חניה. חניה בטאבו", UNC),  # no parking, and a deeded space: contradicts itself
    ("parking", "יש חניה", "building"),  # whose? v1.53: "the building's or your own" (or: deeded), a check only for "your own"
    ("parking", "קרוב לחניון", NS),
    ("parking", "חניה ללא תשלום", "unclear"),  # v1.49: "free" isn't "no parking"; whose isn't said
    ("parking", "חניה לדיירים וחניה בשפע ברחוב", "unclear"),  # v1.49: "לדיירים" may be the apartment's own
    ("parking", "חניה פרטית לדיירים", "deeded"),
    ("parking", "חניה בשפע ברחוב, וגם חניה לפי תור", NS),  # an unread kind might be better
    ("parking", "חנייה חינמית ובשפע במגרש ציבורי", "unclear"),  # v1.49: a lot: the labelers read it two ways
    ("parking", "חניה מקורה", "building"),  # v1.49: covered may be the apartment's own; v1.53: so "building or deeded"
    ("room_share", "דירת 3 חדרים להשכרה", "no"),
    ("room_share", "דירת 3.5 שמורה", "no"),
    ("room_share", "חדר להשכרה בדירת 4 חדרים", "yes"),  # the room count is the flat the room is in (v1.32; v1.28 made it a check)
    ("room_share", "מחפשת שותפה לדירה", "yes"),
    ("room_share", "מחפש שותף לדירת 3 חדרים", "yes"),
    ("room_share", "דירה להשכרה, 3 חדרים, מחפשים שותף", UNCLEAR),  # the whole flat for rent, and a roommate wanted: a check
    ("room_share", "דירה מתאימה לשותפים", "no"),
    ("room_share", "דירת 3 חדרים, שותף יוצא", NS),
    ("room_share", "דירה מהממת", "no"),  # v1.51: an ad that opens with "דירה" offers the flat (137 of 137)
    ("room_share", "בניין שקט. דירה מהממת", NS),
    ("room_share", "דירת 2 קומות", NS),
    ("room_share", "שותפ/ה לדירה מרוהטת", "yes"),
    ("room_share", "דירת שותפים להשכרה ברחוב הרצל", "yes"),  # v1.32: a shared flat is a room in one (the owner saw one get through)
    ("room_share", "להשכרה בדירת שותפים חדר גדול", "yes"),
    ("room_share", "חדר מאסטר מעוצב משופץ ומרוהט בדירת שותפים", "yes"),
    ("room_share", "מתאימה גם לדירת שותפים", NS),  # suits roommates: not a room
    ("room_share", "דירת שותפים משופצת להשכרה, חדרים נוחים. מתאימה לשותפים", UNCLEAR),  # a shared flat, or a whole one for roommates?
    ("room_share", "מתאימה כדירת שותפים, 3 חדרים", "no"),
    ("room_share", "למשפחה או דירת שותפים", NS),
    ("room_share", "דירת 4 חדרים, 2,600 ₪ לחדר", "yes"),  # the rent is per room
    ("room_share", "המחיר לשותף 2,800", "yes"),
    ("room_share", "לכל שותף חוזה בנפרד", "yes"),
    ("room_share", "חנייה משותפת לכל הדיירים", NS),
    ("room_share", "4 מזגנים, מזגן לחדר", NS),  # a number, but not the rent
    ("room_share", "דירת 3 חדרים, 2,600 ש\"ח לחודש לחדר", "yes"),
    ("room_share", "דירת 3 חדרים, 5000 ש\"ח לחודש", "no"),
    ("room_share", "דירה מצוינת לשותפים", "no"),
    ("room_share", "דירה בשטח של 70 מ\"ר", "no"),
    ("room_share", "חדר בדירה של 100 מ\"ר", "yes"),  # a room IN the apartment
    ("balcony", "מרפסת שמש גדולה", "yes"),
    ("balcony", "מרפסת שירות", "service_only"),
    ("balcony", "מרפסת שירות ועוד מרפסת סגורה", "yes"),
    ("balcony", "ללא מרפסת", "no"),
    ("balcony", "ללא מרפסת, יש מרפסת שירות", "service_only"),
    ("balcony", "ללא מרפסת. מרפסת גדולה", UNC),  # contradicts itself
    ("balcony", "מרפסת: אין", NS),
    ("furniture", "דירה מרוהטת", "items", ['says_furnished']),
    ("furniture", "מרוהטת חלקית", "items", ['says_partly_furnished']),
    ("furniture", "כולל ריהוט חלקי", "items", ['says_partly_furnished']),
    ("furniture", "דירה לא מרוהטת", "items", ['says_unfurnished']),
    ("furniture", "ללא ריהוט", "items", ['says_unfurnished']),
    ("furniture", "אפשרות לריהוט חלקי", UNC),
    ("furniture", "יש גם ריהוט חלקי במידת הצורך", UNC),
    ("furniture", "דירה יפה, סלון מרוהט", "items", ['says_partly_furnished']),  # one room: partly
    ("furniture", "ניתן לקבל מרוהטת", UNC),
    ("furniture", "שותפ/ה לדירה מרוהטת", "items", ['says_furnished']),
    ("furniture", "כוללת מרפסת וריהוט מלא ברמה גבוהה", "items", ['says_furnished']),
    ("furniture", "נשאר בדירה ריהוט", "items", ['says_partly_furnished']),
    ("furniture", "אפשרות שיישאר ריהוט", UNC),
    ("furniture", "במידת הצורך נשאר בדירה ריהוט", UNC),  # on request: an offer
    ("broker", "ללא תיווך", "no_broker"),
    ("broker", "וללא דמי תיווך", "no_broker"),
    ("broker", "מתווכים נא לא לפנות", "no_broker"),
    ("broker", "חדש להשכרה בבלעדיות", "broker"),
    ("broker", "דמי תיווך חודש", "broker"),
    ("broker", "ללא תיווך. בבלעדיות", UNCLEAR),  # said both ways
    ("broker", "לא מתיווך.", "no_broker"),
    ("broker", "המתווך לא גובה דמי תיווך", NS),
    ("vaad_bayit", "ועד בית 150 לחודש", "amount", 150),
    ("vaad_bayit", "המחיר כולל מיסי עירייה, מים, גז, ועד, מנוי לכבלים", "included"),
    ("vaad_bayit", "המחיר כולל ארנונה, ועד בית לא כלול", NS),
    ("vaad_bayit", "ועד בית כולל ניקיון", NS),  # the FEE includes cleaning
    ("vaad_bayit", "מים חמים כלולים בדמי ועד בית", UNC),
    ("vaad_bayit", "ועד בית 150, מים חמים כלולים בדמי ועד בית", "amount", 150),  # the amount is given: answered
    ("vaad_bayit", "ועד בית מסודר", NS),  # an orderly committee, not a fee
    ("arnona", "בנוי 90 מ\"ר (בארנונה 117 מטר)", UNC),  # the area it's billed on
    ("arnona", "ארנונה 117 מ\"ר", UNC),
    ("furniture", "אופציה לרהט", UNC),
    ("furniture", "מרוהטת חלקית, אפשרות לריהוט מלא", "items", ['says_partly_furnished']),  # furniture there, more on offer
    ("protected_space", "ללא ממ\"ד, יש מקלט בבניין", "yes"),
    ("protected_space", "יש ממ\"ד. ללא ממ\"ד", UNC),  # one kind said both ways
    # v4, from held-out batch 3's two wrong answers:
    ("furniture", "ניתן לקבל את הדירה מרוהטת קומפלט או ללא ריהוט", UNC),  # the tenant's choice
    ("furniture", "הדירה ללא ריהוט", "items", ['says_unfurnished']),
    ("parking", "חניה ציבורית צמודה לבית", "street"),  # v1.49: "צמודה לבית" is where it is, not whose
    ("parking", "חניה צמודה לדירה", "deeded"),  # the usual phrase for the apartment's own space
    ("parking", "חניה צמודה ופרטית", "deeded"),
    ("vaad_bayit", "המחיר כולל ריהוט ועד היום לא היו בעיות", NS),  # "ועד" = "and until"
    ("vaad_bayit", "ועד בית מסודר", NS),
    ("vaad_bayit", "ועד בית 150 לחודש. המחיר כולל ועד בית", UNCLEAR),  # says both: a human reads it (a check, v1.28)
    ("arnona", "ארנונה 350 לחודש", "amount", 350),
    ("arnona", "ארנונה : 700 ש\"ח לחודשיים.", "amount", 350),
    ("arnona", "ארנונה דו חודשית: 450 ש\"ח", "amount", 225),
    ("arnona", "ארנונה 450", "unclear"),  # period not stated: v1.49, a check a model can't fill in
    ("arnona", "כולל ארנונה", "included"),
    ("arnona", "4200 כולל מים וארנונה", "included"),
    ("arnona", "המחיר כולל מיסי עירייה", "included"),
    ("arnona", "המחיר לא כולל ארנונה", NS),
    ("arnona", "מחיר אטרקטיבי כולל ארנונה", "included"),
    ("arnona", "המחיר אינו כולל ארנונה", NS),
    ("arnona", "ועד בית 300 כולל ארנונה", NS),  # included in the fee, not the rent
    ("arnona", "קומה 3 כולל מעלית", NS),
    ("arnona", "ארנונה 700 לחודשיים לכל שותף", NS),
    # v1.18 (Oct 20): furniture names what's there; AC and fans are never furniture.
    ("furniture", "מזגן + מאוורר בדירה", NS),
    ("furniture", "מוארת ומרוהטת", "items", ["says_furnished"]),
    ("furniture", "מרוהטת: ספה, מיטה זוגית, מקרר ומכונת כביסה", "items", ["bed", "fridge", "says_furnished", "sofa", "washer"]),
    ("furniture", "הדירה מושכרת ללא ריהוט אך משאירה תנור כיריים אינדוקציה וגופי תאורה , ארונות בחדרים", "items",
     ["closets", "oven_stove", "says_unfurnished"]),
    ("furniture", "יש אפשרות להשאיר את המקרר", UNC),
    ("furniture", "ספה ומיטה, אפשרות להשאיר מקרר", "items", ["bed", "sofa"]),  # what's there counts; the offer doesn't
    ("furniture", "חדר נוסף, מתאים לחדר עבודה / משחקים / ארונות", NS),  # a suggested use of a room
    ("furniture", "מטבח חדש עם ארונות", NS),  # kitchen cabinets
    ("furniture", "מקלחת משופצת כולל ארון ומקלחון", NS),  # v1.18.6: the bathroom's cabinet (batch 6)
    ("furniture", "ארון אמבטיה", NS),
    ("furniture", "מקלחת ושירותים, ארונות קיר בכל החדרים", "items", ["closets"]),  # a new clause: real closets
    # v1.18.7 (batch 6, after the Gemini record)
    ("parking", "אין בעיית חנייה", "unclear"),  # "parking is no problem", not "no parking"; v1.49: street or the lot's
    ("parking", "ללא בעיות חניה באזור", "unclear"),  # v1.49: read two ways
    ("parking", "ליד המבנה חנייה גדולה", UNC),  # a lot next to the building: whose? a check
    ("parking", "ליד הבניין חניה ציבורית", "street"),  # ...unless it says
    ("room_share", "מחפשת מחליף/ה! מחליפים לחוזה עד 2027", "no"),  # a lease handover on the whole flat
    ("furniture", "מרפסת שירות עם הכנה למכונת כביסה", NS),
    ("furniture", "2 שידות בחדר שינה ושידת טלוויזיה בסלון", "items", ["cabinet"]),  # a TV stand isn't a TV
    ("furniture", "ללא מקרר", NS),  # the list names what's there
    ("furniture", "דירה מרוהטת, אך ללא ריהוט בחדר השני", UNC),
    ("furniture", "מאובזרת לחלוטין", "items", ["says_equipped"]),
    ("furniture", "מטבח מאובזר", "items", ["says_equipped"]),  # v1.53: the labelers read it so, 8 of 8 (was NS)
    ("furniture", "בדירה נשאר שולחן במרפסת + כסאות", "items", ["table_chairs"]),
    ("apartment_type", "דירת גג בשני קומות", "roof"),
    ("balcony", "דירת גג בשני קומות , ברחוב ללא מוצא", NS),  # a roof apartment isn't a balcony
    ("apartment_type", "דירת גן משופצת", "garden"),
    ("apartment_type", "יחידת דיור בבית פרטי", "unit"),
    ("apartment_type", "בית פרטי כמו בכפר", "house"),
    ("apartment_type", "דופלקס מרווח", "duplex"),
    ("apartment_type", "סטודיו מקסים", "studio"),
    ("apartment_type", "גישה לגג משותף", NS),
    ("apartment_type", "דירת גג עם גינה, כמו דירת גן", UNC),
    # v1.18.1, after held-out batch 4 was recorded: its one wrong answer and four partial lists.
    ("apartment_type", "פנטהואז  דופלקס , 4 חדרים", "roof"),  # a spelling the frozen rules missed (read as duplex)
    ("apartment_type", "וילה מיוחדת ופנימיית", "house"),
    ("furniture", "הדירה מגיע עם ריהוט מלא ומוצרי חשמל", "items", ["says_equipped", "says_furnished"]),
    ("furniture", "שולחן סלון, שידת סלון, שולחן עבודה", "items", ["cabinet", "table_chairs"]),
    ("furniture", "סלון הכולל מערכת ישיבה, תריסים חדשים", "items", ["sofa"]),
    # v1.18.2, from Gemini's held-out errors on batch 4:
    ("vaad_bayit", "מים חמים 24/7 כלול בתשלום הועד !!!", UNC),  # hot water is in the fee; the fee isn't in the rent
    # v1.18.3, after held-out batch 5 was recorded: its three wrong answers.
    ("protected_space", "בדירה אין ממ\"ד אבל המקלט תקני ומסודר מאוד", "yes"),  # "but" ends the negation
    ("protected_space", "אין ממ\"ד בדירה", "no"),
    ("elevator", "דירה ללא מעלית אבל עם מקלט", "no"),
    ("balcony", "המטבח פינת האוכל ומרפסת הכביסה משותפים", "service_only"),
    ("furniture", "המטבח מרוהט ומאובזר בכל מה שנדרש", NS),  # the kitchen's, often shared
    ("furniture", "דירה יפה, סלון מרוהט", "items", ["says_partly_furnished"]),
]


class TestCases(unittest.TestCase):
    def test_each_case(self):
        for case in CASES:
            qid, text, expected = case[:3]
            with self.subTest(qid=qid, text=text):
                got = answer(text)[qid]
                self.assertEqual(got["answer"], expected, got)
                if len(case) > 3:
                    self.assertEqual(got["items" if qid == "furniture" else "value"], case[3], got)

    def test_a_fan_is_a_note_on_the_ac_never_furniture(self):
        got = answer("מזגן + מאוורר בדירה")
        self.assertEqual(got["air_conditioning"]["answer"], "yes")
        self.assertEqual(got["air_conditioning"]["note"], "+fan: מזגן + מאוורר")
        self.assertEqual(got["furniture"]["answer"], NS)
        self.assertEqual(answer("מאוורר תקרה בסלון")["air_conditioning"]["note"], "+fan: מאוורר תקרה")
        for airy in ("דירה מוארת ומאווררת", "חדרים מאווררים", "סלון מאוורר ומרווח"):  # "airy", not a fan
            self.assertNotIn("note", answer(airy)["air_conditioning"], airy)

    def test_every_answer_quotes_the_text(self):
        # v1.42 left held-out batch 7 out until its errors were fixed; v1.49 fixed them
        texts = [c[1] for c in CASES] + list(load(EVAL / "yad2_texts.json").values())
        for text in texts:
            for qid, e in ground(answer(text), text).items():
                self.assertNotIn("problem", e, (text, qid))


HOLDOUT7 = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout7_2026-10-27").glob("*.json")}
HOLDOUT8 = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout8_2026-10-28").glob("*.json")}


class TestOnTheGoldSet(unittest.TestCase):
    def test_no_wrong_answers_on_the_55_listings(self):
        # These are the listings the rules were written against, so coverage
        # here is optimistic; the held-out number is in the README.
        # v1.49: all 463, batch 7 included now that its errors are fixed (TestHeldOutBatch7
        # still pins what the frozen rules did; batch 7 is no longer held out for these rules).
        # v1.51: all 640, batch 8 included now that its errors are fixed (TestHeldOutBatch8 still
        # pins what the frozen rules did; batch 8 is no longer held out for these rules).
        texts = load(EVAL / "yad2_texts.json")
        tallies = score(gold_set(), {k: answer(v) for k, v in texts.items()})
        self.assertEqual(tallies["ALL"].wrong_items, [])


class TestStdlibOnly(unittest.TestCase):
    def test_runs_without_pydantic(self):
        code = ("import sys; sys.modules['pydantic'] = None\n"
                "from rental_matcher.extraction.rules import answer\n"
                "assert answer('ללא מעלית')['elevator']['answer'] == 'no'")
        root = Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable, "-c", code], cwd=root, check=True)


if __name__ == "__main__":
    unittest.main()


class TestCombine(unittest.TestCase):
    def test_agree_keeps_disagree_becomes_a_check_one_side_stands(self):
        from rental_matcher.extraction.rules import combine
        rule = {"elevator": {"answer": "no", "evidence": "ללא מעלית"}, "parking": {"answer": "street", "evidence": "חניה בשפע"},
                "arnona": {"answer": "amount", "value": 350, "evidence": "ארנונה 700 לחודשיים"}}
        model = {"elevator": {"answer": "no", "evidence": "ללא מעלית"}, "parking": {"answer": "deeded", "evidence": "חניה בטאבו"},
                 "balcony": {"answer": "yes", "evidence": "מרפסת"}, "arnona": {"answer": "amount", "value": 700, "evidence": "ארנונה 700"}}
        out = combine(rule, model)
        self.assertEqual((out["elevator"]["answer"], out["elevator"]["source"]), ("no", "both"))
        self.assertEqual((out["balcony"]["answer"], out["balcony"]["source"]), ("yes", "model"))
        self.assertEqual(out["parking"]["answer"], UNC)  # a disagreement is a check, quoting both
        self.assertIn("conflict", out["parking"]["problem"])
        self.assertEqual(out["parking"]["evidence"], "חניה בשפע ... חניה בטאבו")
        self.assertEqual(out["arnona"]["answer"], UNC)  # same answer, different amount: still a conflict
        self.assertEqual(out["furniture"]["answer"], NS)
        self.assertNotIn("source", out["furniture"])

    def test_a_trap_the_rules_saw_is_not_answered_over(self):
        from rental_matcher.extraction.rules import combine
        rule = {"furniture": {"answer": UNC, "evidence": "אופציה לרהט"}, "elevator": {"answer": "yes", "evidence": "מעלית"}}
        model = {"furniture": {"answer": "items", "items": ["says_furnished"], "evidence": "אופציה לרהט"},
                 "elevator": {"answer": UNC, "evidence": "מעלית"}}
        out = combine(rule, model)
        self.assertEqual(out["furniture"]["answer"], UNC)
        self.assertIn("model said 'items'", out["furniture"]["problem"])
        self.assertEqual((out["elevator"]["answer"], out["elevator"]["source"]), ("yes", "rules"))  # rules sure, model unsure


class TestHeldOutBatch4(unittest.TestCase):
    def test_rules_v4_on_batch_4(self):
        # v1.18 (frozen at 8e2ccc9), first held-out run with furniture and
        # apartment_type. One wrong: "פנטהואז דופלקס" read as duplex (that
        # spelling of penthouse wasn't in the pattern). Coverage 80%, lower
        # than batch 3's 89%: furniture lists that missed an item or two
        # count as missed, and these listings were terser.
        ids = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout4_2026-10-20").glob("*.json")}
        answers = load(EVAL / "runs" / "2026-10-20_rules_v4_frozen_on_holdout4.json")
        gold = {k: v for k, v in same_questions(gold_set(), answers).items() if k in ids}
        t = score(gold, answers)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold, t.flagged), (1, 106, 132, 0))


class TestGeminiOnBatch4(unittest.TestCase):
    def test_as_recorded(self):
        # gemini-3.5-flash-lite, prompt 79d194, run Oct 20 by the owner, scored on
        # batch 4 (held out) with the frozen rules -- the saved answers as
        # grounded at the time, not re-grounded under later checks. Gemini
        # alone: 7 wrong; combined: 4 wrong (the frozen rules' penthouse, a
        # ground floor read as a garden apartment, "recruiters don't call" read
        # as no broker, hot water "included in the fee" read as the fee
        # included in the rent), coverage 126/132.
        ids = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout4_2026-10-20").glob("*.json")}
        frozen = load(EVAL / "runs" / "2026-10-20_rules_v4_frozen_on_holdout4.json")
        gem = load(EVAL / "runs" / "2026-10-20_gemini_b8_p79d194.json")
        gold = {k: v for k, v in same_questions(gold_set(), frozen).items() if k in ids}
        from rental_matcher.extraction.rules import combine
        alone, both = score(gold, gem)["ALL"], score(gold, {k: combine(frozen[k], gem[k]) for k in gold})["ALL"]
        self.assertEqual((alone.wrong, alone.correct_definite, both.wrong, both.correct_definite, both.definite_gold), (7, 125, 4, 126, 132))


class TestHeldOutBatch5(unittest.TestCase):
    def test_rules_v5_on_batch_5(self):
        # v1.18.2 (frozen at 536b69e). Three wrong: "אין ממ"ד אבל המקלט
        # תקני" (the negation reached past "but" to the shelter), "מרפסת
        # הכביסה" read as a real balcony (the ה prefix), and a shared
        # kitchen "מרוהט" read as a partly furnished apartment.
        ids = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout5_2026-10-20").glob("*.json")}
        answers = load(EVAL / "runs" / "2026-10-20_rules_v5_frozen_on_holdout5.json")
        gold = {k: v for k, v in same_questions(gold_set(), answers).items() if k in ids}
        t = score(gold, answers)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold, t.flagged), (3, 114, 141, 2))


class TestHeldOutBatch6(unittest.TestCase):
    def test_rules_v6_on_batch_6(self):
        # v1.18.5 (frozen at 8e635b2). One wrong: "מקלחת משופצת כולל ארון"
        # (a cabinet in the shower room) read as closets. Elevator 13/13
        # with no wrong -- including "קומה 7" and "קומה 11/13", which have
        # no מעלית word and were answered by the floor rule, both labelers
        # agreeing -- and "מתאים למשפחות/שותפים" read as a whole apartment.
        ids = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout6_2026-10-20").glob("*.json")}
        answers = load(EVAL / "runs" / "2026-10-20_rules_v6_frozen_on_holdout6.json")
        gold = {k: v for k, v in same_questions(gold_set(), answers).items() if k in ids}
        t = score(gold, answers)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold, t.flagged), (1, 122, 139, 0))
        self.assertEqual(t.wrong_items[0].split(":")[0], "us3zdgy4/furniture")


class TestHeldOutBatch7(unittest.TestCase):
    def test_rules_v142_on_batch_7(self):
        # v1.42 (frozen at 6fd5e81; the rules last changed in v1.39), on 187
        # listings from the owner's Oct 26-27 searches that no rule was written
        # against, answered before any labels existed. 7 wrong at 84%
        # coverage (349/414): four furniture (a niche "for" a washing
        # machine or a table, furniture "offered for sale"), two balconies
        # that were a laundry balcony and balconies only planned, and one
        # room share read from "תו חניה לכל דייר" (a parking permit for
        # every resident). Parking is the weakest question (13/31).
        answers = load(EVAL / "runs" / "2026-10-27_rules_v142_frozen_on_holdout7.json")
        gold = {k: v for k, v in same_questions(gold_set(), answers).items() if k in HOLDOUT7}
        self.assertEqual(len(gold), 187)
        tallies = score(gold, answers)
        t = tallies["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold, t.flagged), (7, 349, 414, 7))
        self.assertEqual(sorted(w.split(":")[0] for w in t.wrong_items), [
            "2oj7a2bi/furniture", "goivkerr/furniture", "hu93jybf/furniture", "m5i3vl5w/furniture",
            "r7hywxro/room_share", "rg8tu1oe/balcony", "y4ts53h8/balcony"])
        self.assertEqual((tallies["parking"].correct_definite, tallies["parking"].definite_gold), (13, 31))


class TestHeldOutBatch8(unittest.TestCase):
    def test_rules_v149_on_batch_8(self):
        # v1.49 (frozen at a6c3fdb), on 177 listings from an isolated search
        # in the built-in browser (Bat Yam, Petah Tikva, Haifa; the owner's own
        # settings untouched), answered before any labels existed. 9 wrong at
        # 80% coverage (391/489): five furniture ("הוספה" read as a sofa, the
        # building's laundry machines, "באופן חלקי", "חדר מרוהט", "חדר
        # עבודה/ארונות"), three apartment types ("דופלקס גג" is a roof flat,
        # "כמו בית פרטי" is not a house), one AC (old units being removed).
        # One listing hidden by a misreading: vryeiy5h from a 3-level parking must-have.
        answers = load(EVAL / "runs" / "2026-10-28_rules_v149_frozen_on_holdout8.json")
        gold = {k: v for k, v in same_questions(gold_set(), answers).items() if k in HOLDOUT8}
        self.assertEqual(len(gold), 177)
        tallies = score(gold, answers)
        t = tallies["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold, t.flagged), (9, 391, 489, 32))
        self.assertEqual(sorted(w.split(":")[0] for w in t.wrong_items), [
            "3frv45t3/air_conditioning", "4ak0syb2/apartment_type", "f2wxhw2w/furniture", "r9qdhynv/apartment_type",
            "rqh1511m/furniture", "v0nhrxgx/furniture", "wa0co3fw/furniture", "wvj5l9bv/apartment_type",
            "xntmde5j/furniture"])
        self.assertEqual((tallies["parking"].correct_definite, tallies["parking"].definite_gold), (31, 64))
        from rental_matcher.extraction.evaluate import wrongly_hidden
        self.assertEqual(wrongly_hidden(gold, answers), {"parking": {"at_least 3.0": ["vryeiy5h"]}})


class TestGeminiOnBatch8(unittest.TestCase):
    def test_as_recorded(self):
        # gemini-3.5-flash-lite, prompt 9e70d1, run Oct 28 on the owner's computer (the 177 new
        # listings only, held-out first), scored on batch 8 with the frozen v1.49 rules.
        # Gemini alone 6 wrong at 97% (475/489); combined 10 wrong at 92% (449/489): where
        # Gemini said nothing, the rules' own errors stand (sofa from "הוספה", the building's
        # laundry, a study's closets, AC, "כמו בית פרטי"), and where the rules were silent,
        # Gemini's stand (two parking lots read as the building's, a vaad, a duplex as a roof).
        # Settled coverage 96% overall; parking 79%, apartment type 86%, furniture 85%.
        frozen = load(EVAL / "runs" / "2026-10-28_rules_v149_frozen_on_holdout8.json")
        gem = load(EVAL / "runs" / "2026-10-28_gemini_b8_p9e70d1_2.json")
        gold = {k: v for k, v in same_questions(gold_set(), frozen).items() if k in HOLDOUT8}
        from rental_matcher.extraction.rules import combine
        alone, both = score(gold, gem)["ALL"], score(gold, {k: combine(frozen[k], gem[k]) for k in gold})["ALL"]
        self.assertEqual((alone.wrong, alone.correct_definite, both.wrong, both.correct_definite, both.definite_gold),
                         (6, 475, 10, 449, 489))
        self.assertEqual(sorted(w.split(":")[0] for w in both.wrong_items), [
            "3frv45t3/air_conditioning", "4pj8wb9w/room_share", "db677elz/apartment_type", "f2wxhw2w/furniture",
            "kcgf8tqt/parking", "mca62tfy/vaad_bayit", "rqh1511m/furniture", "truk0dj2/parking",
            "wa0co3fw/furniture", "wvj5l9bv/apartment_type"])


class TestGeminiOnBatch6(unittest.TestCase):
    def test_as_recorded(self):
        # gemini-3.5-flash-lite, prompt 9e70d1, run Oct 20 by the owner, scored on
        # batch 6 (held out) with the frozen v1.18.5 rules. Gemini alone 2
        # wrong at 97%; combined 3 wrong at 99% (137/139) -- more than the
        # rules' 1 alone: Gemini's two ("מחפשת מחליף/ה!", a lease handover,
        # read as a room share; "ליד המבנה חנייה גדולה", a lot next door, as
        # building parking) landed where the rules were silent, plus the
        # rules' own shower-room cabinet. Fixed after the record as v1.18.7.
        ids = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout6_2026-10-20").glob("*.json")}
        frozen = load(EVAL / "runs" / "2026-10-20_rules_v6_frozen_on_holdout6.json")
        gem = load(EVAL / "runs" / "2026-10-20_gemini_b8_p9e70d1.json")
        gold = {k: v for k, v in same_questions(gold_set(), frozen).items() if k in ids}
        from rental_matcher.extraction.rules import combine
        alone, both = score(gold, gem)["ALL"], score(gold, {k: combine(frozen[k], gem[k]) for k in gold})["ALL"]
        self.assertEqual((alone.wrong, alone.correct_definite, both.wrong, both.correct_definite, both.definite_gold), (2, 135, 3, 137, 139))


class TestGeminiOnBatch5(unittest.TestCase):
    def test_as_recorded(self):
        # gemini-3.5-flash-lite, prompt b4664f, run Oct 20 by the owner, scored on
        # batch 5 (held out) with the frozen rules, as grounded at the time.
        # Gemini alone 5 wrong; combined 1 wrong (an elevator read from
        # "קומה 18"), coverage 135/141.
        #
        # v1.18.5 (2026-10-20): the owner pointed out that "קומה 18" IS good
        # evidence of an elevator -- no building that tall lacks one -- so
        # the gold now accepts "yes" there too (see yad2_adjudications.json).
        # That turns this exact case from wrong to correct on both sides:
        # Gemini alone 4 wrong, combined 0 wrong.
        ids = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout5_2026-10-20").glob("*.json")}
        frozen = load(EVAL / "runs" / "2026-10-20_rules_v5_frozen_on_holdout5.json")
        gem = load(EVAL / "runs" / "2026-10-20_gemini_b8_pb4664f.json")
        gold = {k: v for k, v in same_questions(gold_set(), frozen).items() if k in ids}
        from rental_matcher.extraction.rules import combine
        alone, both = score(gold, gem)["ALL"], score(gold, {k: combine(frozen[k], gem[k]) for k in gold})["ALL"]
        self.assertEqual((alone.wrong, alone.correct_definite, both.wrong, both.correct_definite, both.definite_gold), (4, 138, 0, 135, 141))


class TestCombineLists(unittest.TestCase):
    def test_two_lists_are_merged_and_tagged_by_who_added_what(self):
        from rental_matcher.extraction.rules import combine
        r = {"furniture": {"answer": "items", "items": ["fridge"], "evidence": "מקרר"}}
        out = combine(r, {"furniture": {"answer": "items", "items": ["fridge", "sofa"], "evidence": "מקרר וספה"}})["furniture"]
        self.assertEqual((out["items"], out["source"]), (["fridge", "sofa"], "model"))
        out = combine(r, {"furniture": {"answer": "items", "items": ["fridge"], "evidence": "מקרר"}})["furniture"]
        self.assertEqual((out["items"], out["source"]), (["fridge"], "both"))

    def test_contradicting_claims_become_a_check(self):
        from rental_matcher.extraction.rules import combine
        out = combine({"furniture": {"answer": "items", "items": ["says_unfurnished"], "evidence": "ללא ריהוט"}},
                      {"furniture": {"answer": "items", "items": ["says_furnished"], "evidence": "מרוהטת"}})["furniture"]
        self.assertEqual(out["answer"], UNC)

    def test_the_fan_note_survives_whoever_answers(self):
        from rental_matcher.extraction.rules import combine
        r = answer("מזגן + מאוורר בדירה")
        out = combine(r, {"air_conditioning": {"answer": "yes", "evidence": "מזגן"}})
        self.assertEqual(out["air_conditioning"]["note"], "+fan: מזגן + מאוורר")
        silent = {"air_conditioning": {"answer": NS, "evidence": "", "note": "+fan: מאוורר תקרה"}}  # only the model answers
        out = combine(silent, {"air_conditioning": {"answer": "yes", "evidence": "מיזוג"}})
        self.assertEqual((out["air_conditioning"]["source"], out["air_conditioning"]["note"]), ("model", "+fan: מאוורר תקרה"))


class TestHeldOutRecord(unittest.TestCase):
    """The honest numbers: each rules version scored on listings fetched
    only AFTER it was frozen. The answers are the saved runs, not today's
    rules, so later changes can't rewrite history."""

    def _score(self, run, batch_dir):
        ids = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / batch_dir).glob("*.json")}
        answers = load(EVAL / "runs" / run)
        gold = {k: v for k, v in same_questions(gold_set(), answers).items() if k in ids}
        return score(gold, answers)["ALL"]

    def test_rules_v1_on_batch_1_and_v2_on_batch_2(self):
        # Without the retired "furnished" question (2026-10-20); with it, as
        # recorded at the time: v1 (1, 32, 49), v2 (0, 66, 77).
        v1 = self._score("2026-10-19_rules_frozen_on_holdout1.json", "yad2_holdout_2026-10-19")
        self.assertEqual((v1.wrong, v1.correct_definite, v1.definite_gold), (1, 32, 46))
        v2 = self._score("2026-10-19_rules_v2_frozen_on_holdout2.json", "yad2_holdout2_2026-10-19")
        self.assertEqual((v2.wrong, v2.correct_definite, v2.definite_gold), (0, 63, 72))

    def test_rules_v3_on_batch_3(self):
        # v1.17 (frozen at 1a9192b). Two wrong: "ניתן לקבל ... מרוהטת קומפלט
        # או ללא ריהוט" read as unfurnished (the offer guard didn't cover
        # "ללא ריהוט"), and "חניה ציבורית צמודה לבית" (public parking next to
        # the house) read as deeded because "צמודה" was checked first. The
        # furniture one went with the retired "furnished" question: as
        # recorded at the time, (2, 88, 99, 2).
        v3 = self._score("2026-10-19_rules_v3_frozen_on_holdout3.json", "yad2_holdout3_2026-10-19")
        self.assertEqual((v3.wrong, v3.correct_definite, v3.definite_gold, v3.flagged), (1, 84, 93, 1))
