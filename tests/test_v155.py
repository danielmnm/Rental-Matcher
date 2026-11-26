"""
v1.55: learning from every misreading (owner ruling, Oct 30).

- "A furniture list should be considered partial if what you are describing is missing one
  furniture": a list that names 5 of 6 items earns 5/6 of a fact (`settled_credit`), not nothing.
  A list that names something the listing doesn't have is still wrong.
- "Keep learning from the wrong answers so the same wrong answer could not repeat itself":
  - tests/eval/lessons.json: every misreading held-out batch 9 found, with the words and why. The
    ones fixed must stay right; the ones left open must never become a wrong answer.
  - tests/eval/right_facts.json: every settled fact the rules read right, on the 640 labeled
    listings and on batch 9. A fix for one phrasing can't quietly break another.
- Step 1: the phrase families batch 9 showed (furniture's general words and spellings, whose
  parking, whole flat or room, property type, fees, agencies), each kept only where the 640 stay
  at 0 wrong and 0 hidden. Batch 9 is now studied, so it can't be the proof: batch 10 is.
"""

import json
import unittest
from pathlib import Path

from rental_matcher.extraction.evaluate import (gold_set, widen, partial_lists, score, settled, settled_coverage,
                                                settled_credit, universal_bar, wrongly_hidden, _entry)
from rental_matcher.extraction.rules import answer

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "eval"


def _load(name):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


SETS = {
    "yad2": (gold_set(), _load("yad2_texts.json")),
    "holdout9": (_load("holdout9/gold.json")["gold"], _load("holdout9/texts.json")),
    # v1.56: in-sample from here; with the owner's review on top of the blind labels (evaluate.widen)
    "holdout10": (widen(_load("holdout10/gold.json")["gold"], _load("holdout10/adjudications.json")["adjudications"]), _load("holdout10/texts.json")),
    "holdout11": (widen(_load("holdout11/gold.json")["gold"], _load("holdout11/adjudications.json")["adjudications"]), _load("holdout11/texts.json")),  # v1.59.1: the owner's parking ruling;  # v1.58: in-sample from here
    "holdout12": (widen(_load("holdout12/gold.json")["gold"], _load("holdout12/adjudications.json")["adjudications"]), _load("holdout12/texts.json")),  # v1.59
    "holdout13": (_load("holdout13/gold.json")["gold"], _load("holdout13/texts.json")),  # v1.60: in-sample from here
    "holdout14": (widen(_load("holdout14/gold.json")["gold"], _load("holdout14/adjudications.json")["adjudications"]), _load("holdout14/texts.json")),  # v1.61: in-sample from here
    "komo1": (widen(_load("komo1/gold.json")["gold"], _load("komo1/adjudications.json")["adjudications"]), _load("komo1/texts.json")),  # v1.62: Komo, in-sample from here
    "komo2": (widen(_load("komo2/gold.json")["gold"], _load("komo2/adjudications.json")["adjudications"]), _load("komo2/texts.json")),  # v1.64: in-sample from here
    "komo3": (widen(_load("komo3/gold.json")["gold"], _load("komo3/adjudications.json")["adjudications"]), _load("komo3/texts.json")),  # v1.65: in-sample from here, with the owner's "דירה" ruling
    "komo4": (widen(_load("komo4/gold.json")["gold"], _load("komo4/adjudications.json")["adjudications"]), _load("komo4/texts.json")),  # v1.68: in-sample from here
}


def _a(text, q):
    return answer(text).get(q, {})


def _silent(text, q):
    return _a(text, q).get("answer") in (None, "not_stated")


class TestPartialLists(unittest.TestCase):
    GOLD = {"x": {"furniture": {"answer": "items", "acceptable": ["items"], "items": ["bed", "sofa", "tv"],
                                "allowed_items": ["bed", "sofa", "tv"]}}}

    def test_a_list_missing_an_item_earns_its_share(self):
        ans = {"x": {"furniture": {"answer": "items", "items": ["bed", "sofa"]}}}
        self.assertEqual(settled_coverage(self.GOLD, ans)["ALL"], (0, 1))  # the old reading: nothing
        right, n = settled_credit(self.GOLD, ans)["ALL"]
        self.assertAlmostEqual(right, 2 / 3)
        self.assertEqual(partial_lists(self.GOLD, ans), ["x/furniture: missing tv"])

    def test_an_item_the_listing_doesnt_have_is_still_wrong(self):
        ans = {"x": {"furniture": {"answer": "items", "items": ["bed", "sofa", "fridge"]}}}
        self.assertEqual(settled_credit(self.GOLD, ans)["ALL"], (0.0, 1))
        self.assertEqual(score(self.GOLD, ans)["ALL"].wrong, 1)

    def test_the_bar_can_be_read_either_way(self):
        ans = {"x": {"furniture": {"answer": "items", "items": ["bed", "sofa"]}}}
        old = dict(universal_bar(self.GOLD, ans))
        new = dict(universal_bar(self.GOLD, ans, partial=True))
        self.assertTrue(any("0/1" in k for k in old))
        self.assertTrue(any("0.7/1" in k for k in new))


class TestLessons(unittest.TestCase):
    """Every misreading a held-out batch found stays fixed, or at least never turns into a wrong answer."""

    def test_every_lesson(self):
        data = _load("lessons.json")
        self.assertGreaterEqual(len(data["lessons"]), 601)  # + Komo 4's 3 parking places (v1.68); + Komo 3's 72 (v1.65); batch 9's 56 + 10's 59 + 11's 42 + 12's 59 + 13's 42 + 14's 50 + Komo 1's 37 (v1.62) + Komo 2's 181 (v1.64; its 7 furniture misreadings wait for the furniture pass)
        for les in data["lessons"]:
            gold, texts = SETS[les["set"]]
            lid, q = les["listing"], les["question"]
            got = answer(texts[lid]).get(q, {})
            t = score({lid: {q: gold[lid][q]}}, {lid: {q: got}})[q]
            with self.subTest(f"{lid}/{q}: {les['why']}"):
                self.assertEqual(t.wrong, 0, f"a wrong answer again: {got}")
                if les["now"] == "right":
                    self.assertEqual(t.correct_definite, 1, f"read as {got}, the labelers: {gold[lid][q].get('answer')}")

    def test_the_three_wrong_answers_dont_come_back(self):
        texts = SETS["holdout9"][1]
        self.assertNotIn("tv", _a(texts["e4ywfxdp"], "furniture").get("items", []))  # "מזנון טלוויזיה"
        self.assertNotEqual(_a(texts["w0jbcwlw"], "apartment_type").get("answer"), "unit")  # "אפשרות ליחידת דיור"
        self.assertNotEqual(_a(texts["ylqqmxus"], "balcony").get("answer"), "yes")  # another flat's balcony


class TestRightFactsStayRight(unittest.TestCase):
    """A per-fact ratchet: a count can rise while one fact quietly breaks; this can't."""

    def test_every_fact_read_right_stays_right(self):
        data = _load("right_facts.json")
        facts = data["facts"]
        self.assertGreaterEqual(len(facts), 7588)  # v1.68: + Komo batch 4; v1.65: + Komo batch 3 (6892); v1.64: + Komo batch 2 (6426); v1.62: + Komo batch 1 (5849) (v1.61: 5285, v1.60: 4630, v1.59: 3988, v1.58: 3261, v1.56: 2608)
        self.assertFalse(set(facts) & set(data.get("retired", {})))
        self.assertEqual(set(data.get("retired", {})), {"yad2/w2yf4r3a/parking", "yad2/8t86adyv/parking"})  # each one explained in the README
        answers = {name: {} for name in SETS}
        broken = []
        for key in facts:
            name, lid, q = key.split("/")
            gold, texts = SETS[name]
            if lid not in answers[name]:
                answers[name][lid] = answer(texts[lid])
            got = _entry(answers[name], lid, q)
            if not score({lid: {q: gold[lid][q]}}, {lid: {q: got}})[q].correct_definite:
                broken.append(f"{key}: now {got.get('answer')} {got.get('items') or ''}")
        self.assertEqual(broken, [])

    def test_the_640_still_have_no_wrong_answers_and_hide_nothing(self):
        gold, texts = SETS["yad2"]
        ans = {k: answer(texts[k]) for k in gold if k in texts}
        self.assertEqual(score(gold, ans)["ALL"].wrong, 0)
        self.assertEqual(wrongly_hidden(gold, ans), {})
        got, of = settled_coverage(gold, ans)["ALL"]
        self.assertGreaterEqual(got, 1578)  # of 1610 (v1.53: 1577, v1.59: 1579, v1.60: 1578: "חניה בשפע סמוך לבניין" is a floor now, decision 0001)


class TestNewPhrasings(unittest.TestCase):
    """Each family, and the look-alikes it must not catch."""

    def test_furniture_general_words(self):
        self.assertEqual(_a("דירה יפה.\n\nפירוט ריהוט: מרוהטת קומפלט", "furniture")["items"], ["says_furnished"])
        self.assertIn("says_furnished", _a("שופצה לפני כשנה מרוהטת קומפלט מטבח כפרי", "furniture")["items"])
        self.assertIn("says_furnished", _a("היחידה כוללת ריהוט (ארונות, מיטות)", "furniture")["items"])
        self.assertIn("says_furnished", _a("יחידת דיור משופצת כולל תכולה מלאה", "furniture")["items"])
        self.assertEqual(_a("הדירה ריקה מריהוט", "furniture")["items"], ["says_unfurnished"])
        self.assertEqual(_a("1-room apartment, fully furnished", "furniture")["items"], ["says_furnished"])
        self.assertIn("says_equipped", _a("3 שירותים, 2מקלחות מרוהט, ומאובזר, וממוזג", "furniture")["items"])
        self.assertIn("says_equipped", _a("מטבח גדול ומאובזר מקרר חדש", "furniture")["items"])
        self.assertTrue(_silent("מומלץ ביטוח תכולה מלאה", "furniture"))  # contents insurance

    def test_furniture_items_and_spellings(self):
        items = _a("ריהוט: 2 אורנות + כריים + שלוחן וכסא, טלבזיה, קומדה, מיטת ספה, 2 מדיחים", "furniture")["items"]
        for i in ("closets", "oven_stove", "table_chairs", "tv", "cabinet", "bed", "dishwasher"):
            self.assertIn(i, items)
        self.assertNotIn("tv", _a("מקרר, מזנון טלוויזיה, ארון", "furniture")["items"])
        self.assertNotIn("fridge", _a("מיקרו, כיריים, מקרר יין", "furniture")["items"])

    def test_a_laundry_room_is_the_flats_unless_the_building_is_named(self):
        self.assertIn("dryer", _a("חדר כביסה עם מכונת כביסה ומייבש", "furniture")["items"])
        self.assertNotEqual(_a("בבניין יש חדר כביסה עם מכונות כביסה וייבוש", "furniture").get("answer"), "items")

    def test_a_dining_corner_is_a_table_only_in_the_furniture_field(self):
        self.assertIn("table_chairs", _a("דירה.\n\nפירוט ריהוט: סלון\nפינת אוכל\nמיטות", "furniture")["items"])
        self.assertTrue(_silent("סלון מרווח ופינת אוכל גדולה", "furniture"))

    def test_parking(self):
        self.assertEqual(_a("יש מעלית וחניה מקורה לדירה.", "parking")["answer"], "deeded")
        self.assertEqual(_a("2 חניות תת קרעיות צמודות", "parking")["answer"], "deeded")
        self.assertEqual(_a("חניה בכניסה לבניין .", "parking")["answer"], "building")

    def test_whole_flat_or_room(self):
        self.assertEqual(_a("בקיצור דירה מציאה\nמתאים גם לשותפים גם לזוג", "room_share")["answer"], "no")
        self.assertEqual(_a("דירת חמד מוארת וממוזגת", "room_share")["answer"], "no")
        self.assertEqual(_a("להשכרה מפרטי בזבוטינסקי נתניה דירה גדולה מאד ויפה", "room_share")["answer"], "no")
        self.assertEqual(_a("1-room apartment in the city center", "room_share")["answer"], "no")
        self.assertEqual(_a("יש שותף בדירה. חדר שקט להשכרה בדירה מטופחת", "room_share")["answer"], "yes")

    def test_property_type(self):
        self.assertEqual(_a("להשכרה דירת מיניפנטהאוס", "apartment_type")["answer"], "roof")
        self.assertEqual(_a("נוף.\n140 מ\"ר.\n2 קומות.\n5 חדרי שינה.", "apartment_type")["answer"], "duplex")
        self.assertTrue(_silent("בניין של 2 קומות בלבד", "apartment_type"))  # the building, not the flat
        self.assertEqual(_a("בית על מגרש חצי דונם", "apartment_type")["answer"], "house")
        self.assertNotEqual(_a("בית מרווח, עם אפשרות ליחידת דיור נפרדת", "apartment_type").get("answer"), "unit")
        self.assertEqual(_a("יחידת דיור, חדר גדול", "apartment_type")["answer"], "unit")

    def test_balcony(self):
        self.assertEqual(_a("מרפסת לא סוכה", "balcony")["answer"], "yes")
        self.assertTrue(_silent("מרפסת: לא", "balcony"))  # still a denial (dropped), not a yes
        self.assertEqual(_a("בפרויקט אקא פרימיום חדר מגורים מרפסת סוכה", "balcony")["answer"], "yes")
        self.assertNotEqual(_a("דירת חדר ( יש גם דירה נוספת עם מרפסת בתוספת מחיר )", "balcony").get("answer"), "yes")

    def test_fees_and_agencies(self):
        self.assertEqual(_a("ללא תיווך / וועד 180 לחודש", "vaad_bayit")["value"], 180)
        self.assertEqual(_a("ועד 60 ש\"ח לחודש.", "vaad_bayit")["value"], 60)
        self.assertTrue(_silent("הכניסה מ-1 ועד 12 בחודש", "vaad_bayit"))  # "and until"
        self.assertEqual(_a("המחיר כלל ארנונה וועד בית.", "arnona")["answer"], "included")
        self.assertEqual(_a("התשלום כולל כל התשלומים , גם ועד בית, חוץ מחשמל", "vaad_bayit")["answer"], "included")
        self.assertEqual(_a("רימקס יוניברס רחובות מציגים:", "broker")["answer"], "broker")
        self.assertEqual(_a("תיווך 1000ש\"ח", "broker")["answer"], "broker")
        self.assertEqual(_a("לא מעוניין בשרותי תיווך!!", "broker")["answer"], "no_broker")
        self.assertEqual(_a("quiet location, no brokerage fee", "broker")["answer"], "no_broker")


class TestCensusOct30(unittest.TestCase):
    """Step 2: 90 new, unlabeled listings (Ra'anana, Hod Hasharon; Oct 30), read against the rules before the freeze.
    Each family was kept only where the 640 stay at 0 wrong and 0 hidden."""

    def test_census_families(self):
        self.assertEqual(_a("להשכרה מפרטי. דירה מרווחת מוארת ושקטה", "broker")["answer"], "no_broker")
        self.assertEqual(_a("יוצאת לשכירות ישירות מבעלי הדירה", "broker")["answer"], "no_broker")
        self.assertEqual(_a("לא להתקשר בשבת\nלא לתיווך !!!", "broker")["answer"], "no_broker")
        self.assertEqual(_a("*מתווכים - נא לא לפנות*\nדירת 5 חדרים", "broker")["answer"], "no_broker")
        self.assertEqual(_a("מיזוג אויר\nשיווק [name] נדלן", "broker")["answer"], "broker")
        self.assertEqual(_a("נכס מספר: 6998, בשכונת ציר החינוך", "broker")["answer"], "broker")
        self.assertEqual(_a("להשכרה מפרטי. דירה מרווחת מוארת ושקטה", "room_share")["answer"], "no")
        self.assertEqual(_a("בית יוקרתי להשכרה. 7 חדרי שינה פלוס חדר קולנוע", "room_share")["answer"], "no")
        self.assertEqual(_a("חדר עם חדר אמבטיה פרטי בתוך דירה מרווחת. מתאים לשותפה.", "room_share")["answer"], "yes")
        self.assertNotEqual(_a("חדר וחצי להשכרה במרכז העיר", "room_share").get("answer"), "yes")  # a 1.5-room flat
        self.assertEqual(_a("מרפסת, מ''מד ומרפסת שרות", "protected_space")["answer"], "yes")
        self.assertEqual(_a("יש מגרש חניה, מזגנים", "parking")["answer"], "building")
        self.assertEqual(_a("דירת גן 4 חדרים בתוספת מרפסת גינה", "balcony")["answer"], "yes")

    def test_census_traps(self):
        self.assertIn("dishwasher", _a("מדיח כלים ותנור כפול בילט-אין, בית כנסת ממול", "furniture")["items"])  # built-in, not "- אין"
        self.assertIn("closets", _a("מקלחת מזגן ארון בגדים מקרר", "furniture")["items"])
        self.assertIn("washer", _a("מיקרו-גל, מדיח כלים, מ. כביסה, מייבש", "furniture")["items"])
        self.assertEqual(_a("וילה יוקרתית. כוללת 6 חדרי שינה, מרתף ענק + שתי יחידות דיור נפרדות", "apartment_type")["answer"], "house")
        self.assertTrue(_silent("דירה גדולה, משופצת ונעימה, מרווחת. מעל בית פרטי.", "apartment_type"))
        self.assertTrue(_silent("ארנונה ,מיים וועד בית 600 שקל", "vaad_bayit"))  # one amount for three things


class TestHeldOutBatch10(unittest.TestCase):
    """Step 3: 261 listings fetched after the rules were frozen (f059055), from six cities no batch or census had used
    (Modiin, Ashkelon, Hadera, Rosh HaAyin, Ness Ziona, Yavne). Two blind labelers in private folders: 2817/2871
    exact, 2871/2871 compatible. Pinned as measured; kept apart from the in-sample files; nothing fitted on it."""

    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        cls.gold = _load("holdout10/gold.json")["gold"]
        cls.texts = _load("holdout10/texts.json")
        cls.frozen = {k: v for k, v in _load("runs/2026-10-30_rules_v155_frozen_on_holdout10.json").items() if not k.startswith("_")}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout10_2026-10-30")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        prefs = __import__("rental_matcher.scoring", fromlist=["PreferenceSet"]).PreferenceSet.load(
            ROOT / "tests" / "fixtures" / "prefs_frozen.json")
        from rental_matcher.extraction.rules import combine
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(cls.frozen[k], {}) for k in tg}, prefs)
        # the owner's manual review, kept apart from the blind labels (adjudications.json)
        tg2 = widen(tg, _load("holdout10/adjudications.json")["adjudications"])
        cls.rg, cls.ra, _ = card_score_inputs(ex, tg2, {k: combine(cls.frozen[k], {}) for k in tg2}, prefs)

    def test_the_frozen_run_is_on_record(self):
        # what the frozen v1.55 rules said (f059055); v1.56 learned from this batch, so today's rules differ
        self.assertEqual(len(self.gold), 261)
        self.assertEqual(set(self.frozen), set(self.gold))
        self.assertNotEqual({k: answer(self.texts[k]) for k in self.gold}, self.frozen)

    def test_the_text(self):
        t = score(self.gold, self.frozen)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold), (15, 669, 734))
        self.assertEqual(settled_coverage(self.gold, self.frozen)["ALL"], (622, 680))
        self.assertAlmostEqual(settled_credit(self.gold, self.frozen)["ALL"][0], 634.2, places=1)

    def test_after_owners_review(self):
        """His review on top of the blind labels: the Ashkelon listing (fully equipped, TV channels included: a TV is
        expected) and the room "בקומת קרקע-עם חצר" (a garden flat, Nov 2). With v1.57's fee rule, 8 wrong; the bar
        is still not met. The blind-label numbers stay as measured (README)."""
        t = score(self.rg, self.ra)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold), (8, 1600, 1650))  # re-scored under v1.56's parking rule and v1.57's fee rule
        self.assertAlmostEqual(settled_credit(self.rg, self.ra)["furniture"][0], 88.25, places=2)
        self.assertGreater(len([c for c, ok in universal_bar(self.rg, self.ra, partial=True) if not ok]), 0)

    def test_the_card(self):
        t = score(self.cg, self.ca)["ALL"]
        # As measured on Oct 30: 12 wrong, 1596/1644, settled 1483/1531, 1495.2 with partial lists (97.7%).
        # v1.56 changed the card test's rule for one case (owner ruling: when the text places the parking on the street,
        # it beats Yad2's ticked box), so 4 street facts the old rule called a check are now settled street facts.
        # The frozen run still got them wrong. v1.57 (owner ruling, Nov 2): "המחיר כולל ארנונה + וועד" with Yad2's fee fields
        # filled in is "included", not a check, so 2 of the 12 were right: 10 wrong, re-scored (blind labels, no review).
        self.assertEqual((len(self.cg), t.wrong, t.correct_definite, t.definite_gold), (253, 10, 1599, 1650))
        self.assertEqual(settled_coverage(self.cg, self.ca)["ALL"], (1486, 1537))
        right, n = settled_credit(self.cg, self.ca)["ALL"]
        self.assertAlmostEqual(right, 1498.25, places=1)
        hidden = wrongly_hidden(self.cg, self.ca)
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in hidden.items()},
                         {"room_share": ["1hkr3p7f"], "apartment_type": ["6buf0eoq"], "parking": ["gkv7k0iy"]})
        failed = [c for c, ok in universal_bar(self.cg, self.ca, partial=True) if not ok]
        self.assertEqual(len(failed), 5)  # 10 wrong (re-scored), 3 hidden, parking 34/40, room share 164/175, furniture 87.2/97


if __name__ == "__main__":
    unittest.main()
