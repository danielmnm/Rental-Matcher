"""Decision 0001 (docs/decisions/0001-phase-2-exit-bar.md): the numbers it rests on, the bar it sets, and the
reader changes it made (v1.60). The baseline figures are recomputed here from the saved frozen runs and labels,
so the decision record can't drift from the data."""
import json
import unittest
from pathlib import Path

from rental_matcher.extraction import rules
from rental_matcher.extraction.evaluate import (BAR_V2_COVERAGE_OVERALL, BAR_V2_COVERAGE_PER_QUESTION, BAR_V2_WRONG_FURNITURE,
                                                BAR_V2_WRONG_OVERALL, BAR_V2_WRONG_PER_QUESTION, _entry, answer_counts, bar_v2,
                                                gold_set, wilson)
from rental_matcher.extraction.questions import QUESTIONS
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "eval"
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
FROZEN = {10: ("2026-10-30_rules_v155_frozen_on_holdout10.json", "yad2_holdout10_2026-10-30"),
          11: ("2026-11-02_rules_v157_frozen_on_holdout11.json", "yad2_holdout11_2026-11-02"),
          12: ("2026-11-03_rules_v158_frozen_on_holdout12.json", "yad2_holdout12_2026-11-03"),
          13: ("2026-11-05_rules_v1591_frozen_on_holdout13.json", "yad2_holdout13_2026-11-05")}


def _load(name):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def _as_measured(b):
    """A batch's card as it was measured: the frozen run, the blind gold (batch 11 without the 14 listings that
    turned out to be among the 640)."""
    from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
    run, fx = FROZEN[b]
    gold = _load(f"holdout{b}/gold.json")["gold"]
    if b == 11:
        g640 = set(gold_set())
        gold = {k: v for k, v in gold.items() if k not in g640}
    frozen = {k: v for k, v in _load(f"runs/{run}").items() if not k.startswith("_")}
    ex = load_extracts(ROOT / "tests" / "fixtures" / fx)
    tg = {k: v for k, v in gold.items() if k in ex}
    cg, ca, _ = card_score_inputs(ex, tg, {k: rules.combine(frozen[k], {}) for k in tg}, PREFS)
    return cg, ca


class TestTheBaseline(unittest.TestCase):
    """The figures in the decision record's Context section."""

    @classmethod
    def setUpClass(cls):
        cls.cards = {b: _as_measured(b) for b in FROZEN}

    def test_wrong_answers_as_measured(self):
        total = [0, 0]
        furniture = [0, 0]
        for cg, ca in self.cards.values():
            for q, (d, w) in answer_counts(cg, ca).items():
                total[0] += d
                total[1] += w
                if q == "furniture":
                    furniture[0] += d
                    furniture[1] += w
        self.assertEqual(tuple(total), (7412, 45))  # 0.61%
        self.assertEqual(tuple(furniture), (442, 28))  # 6.3%
        lo, hi = wilson(total[1], total[0])
        self.assertAlmostEqual(lo, 0.0045, places=4)
        self.assertAlmostEqual(hi, 0.0081, places=4)

    def test_the_labelers_agree_on_99_percent(self):
        from collections import Counter
        pairs = []
        g640 = set(gold_set())
        for b in FROZEN:
            a, bb = _load(f"holdout{b}/labels_a.json"), _load(f"holdout{b}/labels_b.json")
            for lid in _load(f"holdout{b}/gold.json")["gold"]:
                if b == 11 and lid in g640:
                    continue
                for q in QUESTIONS:
                    ea, eb = _entry(a, lid, q.id), _entry(bb, lid, q.id)
                    key = lambda e: (e["answer"], tuple(sorted(e.get("items") or [])), e.get("value"))
                    pairs.append((key(ea), key(eb)))
        po = sum(x == y for x, y in pairs) / len(pairs)
        ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
        pe = sum(ca[k] * cb[k] for k in ca) / len(pairs) ** 2
        self.assertEqual(len(pairs), 11671)
        self.assertAlmostEqual(po, 0.990, places=3)
        self.assertAlmostEqual((po - pe) / (1 - pe), 0.96, places=2)  # Cohen's kappa

    def test_every_batch_as_measured_fails_the_new_bar(self):
        # the new bar isn't one the old results already met: each batch fails it as measured
        fails = {b: [c.split(" (got")[0] for c, ok in bar_v2(*card) if not ok] for b, card in self.cards.items()}
        self.assertEqual(fails[10], ["no listing hidden by a misreading, for any must-have", "wrong <= 3.0% on furniture"])
        self.assertEqual(fails[11], ["no listing hidden by a misreading, for any must-have", "wrong <= 3.0% on furniture",
                                     "settled facts read >= 85.0% on furniture", "at least 250 listings"])
        self.assertEqual(fails[12], ["no listing hidden by a misreading, for any must-have", "wrong <= 2.0% on apartment_type",
                                     "wrong <= 3.0% on furniture"])
        self.assertEqual(fails[13], ["no listing hidden by a misreading, for any must-have", "wrong <= 2.0% on apartment_type",
                                     "wrong <= 3.0% on furniture"])


class TestTheBar(unittest.TestCase):
    def test_the_numbers_are_the_decision_records(self):
        self.assertEqual((BAR_V2_WRONG_OVERALL, BAR_V2_WRONG_PER_QUESTION, BAR_V2_WRONG_FURNITURE), (0.005, 0.02, 0.03))
        self.assertEqual((BAR_V2_COVERAGE_OVERALL, BAR_V2_COVERAGE_PER_QUESTION), (0.90, 0.85))
        text = (ROOT / "docs" / "decisions" / "0001-phase-2-exit-bar.md").read_text(encoding="utf-8")
        for said in ("**0.5%**", "**2%**", "**3%**", "**90%**", "**85%**", "at least 250 listings"):
            self.assertIn(said, text)

    def test_furniture_can_never_hide_a_listing(self):
        # the premise of furniture's looser budget: scoring.py's has_items branch never adds an exclusion
        import inspect
        from rental_matcher import scoring
        src = inspect.getsource(scoring.score_listing)
        branch = src.split('if pref.kind == "has_items":')[1].split('elif pref.kind == "yes_no":')[0]
        self.assertNotIn("excluded_reasons", branch)


def _a(text, q):
    return rules.answer(text).get(q) or {"answer": "not_stated"}


class TestInferredReadingsAreChecks(unittest.TestCase):
    def test_a_bare_room_is_a_check(self):
        self.assertEqual(_a("דירת 4 חדרים חדשה. יש חדר ממד בדירה.", "room_share")["answer"], "unclear")
        self.assertEqual(_a("חדר להשכרה", "room_share")["answer"], "unclear")
        # sharing said: still a room in a shared flat
        for t in ("חדר להשכרה בדירת שותפים", "חדר להשכרה בדירת 4 חדרים", "מתפנה חדר בדירה", "חדר פנוי, מטבח משותף"):
            self.assertEqual(_a(t, "room_share")["answer"], "yes", t)

    def test_plenty_of_parking_at_the_property_is_a_floor(self):
        a = _a("יש חניה בשפע פנויה ליד הכניסה האחורית של הדירה.", "parking")
        self.assertEqual((a["answer"], a.get("or")), ("street", ["building"]))
        # plain abundance, or abundance in the street or area, stays street
        for t in ("חניה בשפע", "חניה בשפע ברחוב", "שפע של חנייה באזור"):
            a = _a(t, "parking")
            self.assertEqual((a["answer"], a.get("or")), ("street", None), t)


class TestBatch13Families(unittest.TestCase):
    def test_furniture(self):
        for t in ("ארונות עליונים מטבח , מיזוג אוויר", "מספר ארונות שירות ומקום אחסון רב.",
                  "פירוט ריהוט: דירה מרווחת סלון גדול פינת אוכל קרוב לתחבורה"):
            self.assertEqual(_a(t, "furniture")["answer"], "not_stated", t)
        self.assertEqual(_a("פירוט ריהוט: נשאר בדירה כל הריהוט חוץ מטלויזיה", "furniture")["items"], ["says_furnished"])
        self.assertNotIn("says_equipped", _a("בסלון יש ספה, אמבטיה מאובזרת עם מכונת כביסה", "furniture")["items"])
        self.assertEqual(_a("בית מרוהט בחלקו", "furniture")["items"], ["says_partly_furnished"])
        for t in ("ארונות בכל החדרים", "מזגן וארון בכל חדר", "פירוט ריהוט: ארון", "מיטה, ארון ושולחן"):
            self.assertIn("closets", _a(t, "furniture").get("items") or [], t)

    def test_one_offs(self):
        self.assertEqual(_a("יחידה יפה מרווחת 2.5 חדרים כניסה נפרדת בבית פרטי", "apartment_type")["answer"], "unit")
        self.assertEqual(_a("יחידת דיור מרוהטת במיקום שקט בבית פרטי כ40 מטר חצר פרטית", "apartment_type")["answer"], "unit")
        self.assertEqual(_a("בית פרטי להשכרה", "apartment_type")["answer"], "house")
        self.assertEqual(_a("קרוב לחניות ובית כנסת", "parking")["answer"], "not_stated")
        self.assertEqual(_a('ממ"ד 5 מטר מהדירה ולא כפי שמופיע', "protected_space")["answer"], "unclear")


if __name__ == "__main__":
    unittest.main()


class TestTheProductDoesWhatTheBarAssumes(unittest.TestCase):
    """The bar counts a floor ("street, maybe the building's") and a check as never hiding; the scorer must agree."""

    def test_plenty_of_parking_by_the_entrance_is_a_check_not_hidden(self):
        from tests.test_v153 import BUILDING, _score, _x
        s = _score(_x(description="דירת 3 חדרים. יש חניה בשפע פנויה ליד הכניסה האחורית של הדירה."), BUILDING)
        self.assertFalse(s.excluded, s.exclusion_reasons)
        # plain "חניה בשפע" is still read as the street's, and a building-parking must-have still hides it
        self.assertTrue(_score(_x(description="דירת 3 חדרים, חניה בשפע ברחוב."), BUILDING).excluded)


class TestBatch14Families(unittest.TestCase):
    """v1.61 (decision 0002, fix forward): what batch 14 found."""

    def test_furniture(self):
        for t in ("מרפסת לכיוון מערב, מחסן למכונת כביסה ומייבש.", "שירותים גדולים עם תשתית למכונת כביסה ומייבש( בלי ארובה",
                  'מזגן 3.5 כ"ס שמקרר את כל הבית.', 'שמורה כחדשה ומאובזרת בתיחכום ונוחות: ממ"ד / תריסים חשמליים'):
            self.assertEqual(_a(t, "furniture")["answer"], "not_stated", t)
        a = _a("פירוט ריהוט: מקרר, כיריים וכיסאות לאי במטבח. לא כלולים: ריהוט הסלון, תנור ומיקרוגל.", "furniture")
        self.assertNotIn("microwave", a["items"])
        # look-alikes that are the items
        self.assertIn("dryer", _a("מקרר, כיריים חשמליים, מיקרוגל ומייבש", "furniture")["items"])
        self.assertIn("says_equipped", _a("דירה מרוהטת ומאובזרת", "furniture")["items"])

    def test_parking_and_type(self):
        self.assertEqual(_a("המון חנייה .תחנת אוטובוס", "parking")["answer"], "street")
        self.assertNotEqual(_a("חניה בשפע: חניה גדולה וצמודה לבניין.", "parking")["answer"], "deeded")
        self.assertNotEqual(_a("בית גדול ומרווח, 5.5 חדרים +מחסן מזווה ענק, ויחידת דיור בת 2 חדרים.", "apartment_type")["answer"], "unit")
        self.assertEqual(_a("יחידת דיור להשכרה", "apartment_type")["answer"], "unit")

    def test_the_parking_check_says_what_it_means(self):
        from tests.test_v153 import BUILDING, _score, _x
        s = _score(_x(description="דירת 3 חדרים. יש חניה בשפע פנויה ליד הכניסה האחורית של הדירה."), BUILDING)
        self.assertFalse(s.excluded)
        self.assertTrue(any("doesn't say whose parking it is" in c for c in s.checks), s.checks)
