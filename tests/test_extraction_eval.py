"""
Tests for the Phase 2 evaluation harness: the questions, the prompt, the
gold set, and the scorer (which had a bug on its first run: coverage over
100%, from counting ambiguous items in the numerator only).
"""

import json
import unittest
from pathlib import Path

from rental_matcher.extraction.evaluate import build_gold, gold_set, load, same_questions, score
from rental_matcher.extraction.prompt import build_prompt, response_schema
from rental_matcher.extraction.questions import NOT_STATED, QUESTIONS

EVAL = Path(__file__).resolve().parent / "eval"


# v1.42: held-out batch 7, measured and not yet fixed. Its gold has two quotes the grounding check
# refuses because of the poster's spelling (yzwqgnju: "מיקלט לביניין", "מירפסת"): a finding for the fix
HOLDOUT7 = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout7_2026-10-27").glob("*.json")}
HOLDOUT8 = {f.stem for f in (Path(__file__).resolve().parent / "fixtures" / "yad2_holdout8_2026-10-28").glob("*.json")}


def _settled(g):
    """A gold item the text settles: no abstention among its acceptable answers."""
    return not ({NOT_STATED, "unclear"} & set(g["acceptable"]))


class TestQuestions(unittest.TestCase):
    def test_every_question_can_say_not_stated(self):
        for q in QUESTIONS:
            self.assertIn(NOT_STATED, q.answers, q.id)
            self.assertNotIn(NOT_STATED, q.values, q.id)  # not_stated never becomes a signal value
            self.assertTrue(set(q.values) <= set(q.answers), q.id)

    def test_schema_closes_every_answer(self):
        schema = response_schema()
        self.assertEqual(set(schema["required"]), {q.id for q in QUESTIONS})
        for q in QUESTIONS:
            self.assertEqual(schema["properties"][q.id]["properties"]["answer"]["enum"], list(q.answers))
        self.assertIn("ללא תיווך", build_prompt("דירה ללא תיווך"))


class TestGold(unittest.TestCase):
    def test_gold_is_the_two_labelers_merged(self):
        a = load(EVAL / "yad2_labels_a.json")["labels"]
        b = load(EVAL / "yad2_labels_b.json")["labels"]
        adjudications = load(EVAL / "yad2_adjudications.json")["adjudications"]
        self.assertEqual(build_gold(a, b, adjudications), gold_set())
        # Without the adjudications that supply a missing number, the builder refuses
        # (an acceptable amount with no number would mark the right one wrong)...
        with self.assertRaisesRegex(ValueError, "no labeler gave the number"):
            build_gold(a, b)
        # ...and an adjudication only widens: with just their numbers, every gold set is a subset.
        plain = build_gold(a, b, [{**adj, "also_ok": []} for adj in adjudications if "value" in adj])
        for lid, by in plain.items():
            for qid, g in by.items():
                self.assertLessEqual(set(g["acceptable"]), set(gold_set()[lid][qid]["acceptable"]))
        self.assertEqual(len(gold_set()), 640)  # v1.42: + held-out batch 7's 187; v1.50: + batch 8's 177
        self.assertEqual(sum(len(v) for v in gold_set().values()), 7040)

    def test_gold_evidence_is_in_the_text(self):
        texts = load(EVAL / "yad2_texts.json")
        for lid, by in gold_set().items():
            for qid, g in by.items():
                if g["answer"] != NOT_STATED and g["evidence"] and "(" not in g["evidence"]:
                    for piece in g["evidence"].split(" ... "):
                        self.assertIn(piece, texts[lid], (lid, qid))

    def test_every_gold_quote_passes_the_grounding_check(self):
        from rental_matcher.extraction.prompt import ground
        texts = load(EVAL / "yad2_texts.json")
        # v1.42: items the text settles; where the gold also accepts a check (batch 7's "ללא תיווח", a
        # typo), the grounding check turning the answer into a check is an answer the gold allows
        missed = []
        for lid, by in gold_set().items():  # v1.49: batch 7 too ("מיקלט", "מירפסת" now pass)
            labeled = {q: {"answer": g["answer"], "evidence": g["evidence"]} for q, g in by.items()
                       if g["answer"] != NOT_STATED and "(" not in g["evidence"] and _settled(g)}
            for q, e in ground(labeled, texts[lid]).items():
                if "problem" in e:
                    missed.append(f"{lid}/{q}")
        # v1.51: batch 8 too ("בקומה ה7" for an elevator, "פנטאהוז" for a roof flat now pass)
        self.assertEqual(missed, [])

    def test_a_real_conflict_is_refused_not_resolved(self):
        a = {"x": {"elevator": {"answer": "yes"}}}
        b = {"x": {"elevator": {"answer": "no"}}}
        with self.assertRaises(ValueError):
            build_gold(a, b)
        with self.assertRaises(ValueError):
            build_gold({"x": {"vaad_bayit": {"answer": "amount", "value": 35}}},
                       {"x": {"vaad_bayit": {"answer": "amount", "value": 53}}})


class TestScorer(unittest.TestCase):
    GOLD = {"x": {
        "elevator": {"answer": "no", "acceptable": ["no"]},                       # definite
        "parking": {"answer": "street", "acceptable": ["building", "not_stated", "street"]},  # ambiguous
        "vaad_bayit": {"answer": "amount", "acceptable": ["amount"], "value": 35},
        **{q.id: {"answer": NOT_STATED, "acceptable": [NOT_STATED]} for q in QUESTIONS
           if q.id not in ("elevator", "parking", "vaad_bayit")},
    }}

    def test_outcomes(self):
        perfect = {"x": {"elevator": {"answer": "no"}, "parking": {"answer": "building"},
                         "vaad_bayit": {"answer": "amount", "value": 35}}}
        t = score(self.GOLD, perfect)["ALL"]
        self.assertEqual((t.wrong, t.missed, t.coverage), (0, 0, 1.0))  # never above 100%
        t = score(self.GOLD, {})["ALL"]
        self.assertEqual((t.wrong, t.missed, t.coverage), (0, 2, 0.0))  # not_stated: missed, never wrong
        t = score(self.GOLD, {"x": {"protected_space": {"answer": "yes"}, "vaad_bayit": {"answer": "amount", "value": 53},
                                    "elevator": {"answer": "maybe"}}})["ALL"]
        self.assertEqual(t.wrong, 3)  # a guess, a wrong amount, an answer outside the closed set

    def test_recorded_runs_score_without_crashing(self):
        for run in sorted((EVAL / "runs").glob("*.json")):
            score(gold_set(), load(run))


if __name__ == "__main__":
    unittest.main()


class TestDefinitionOfDone(unittest.TestCase):
    def test_the_reference_run_meets_the_bar_and_regex_alone_does_not(self):
        from rental_matcher.extraction.evaluate import definition_of_done
        ref = {k: v for k, v in load(EVAL / "runs" / "2026-10-19_claude_in_session.json").items() if not k.startswith("_")}
        gold = same_questions(gold_set(), ref)  # the reference read the first 117, before furniture/apartment_type
        self.assertTrue(all(ok for _, ok in definition_of_done(score(gold, ref), len(gold))))
        self.assertFalse(all(ok for _, ok in definition_of_done(score(gold, {}), len(gold))))
        self.assertFalse(all(ok for _, ok in definition_of_done(score(gold, ref), 20)))

    def test_one_wrong_answer_fails_it(self):
        from rental_matcher.extraction.evaluate import definition_of_done
        ref = {k: dict(v) for k, v in load(EVAL / "runs" / "2026-10-19_claude_in_session.json").items() if not k.startswith("_")}
        gold = same_questions(gold_set(), ref)
        ref["7b0umktb"]["elevator"] = {"answer": "yes", "evidence": "x"}  # the text says ללא מעלית
        checks = dict(definition_of_done(score(gold, ref), len(gold)))
        self.assertFalse(next(ok for c, ok in checks.items() if c.startswith("0 wrong")))


class TestUnclearInGold(unittest.TestCase):
    def test_a_labeler_saying_unclear_is_an_abstention(self):
        from rental_matcher.extraction.evaluate import build_gold
        a = {"x": {"furniture": {"answer": "unclear", "evidence": "אופציה לרהט"}}}
        b = {"x": {"furniture": {"answer": "not_stated"}}}
        gold = build_gold(a, b)  # compatible: both abstain
        for said, wrong, missed in (({"answer": "not_stated"}, 0, 0), ({"answer": "unclear"}, 0, 0),
                                    ({"answer": "items", "items": ["says_partly_furnished"]}, 1, 0)):
            t = score(gold, {"x": {"furniture": said}})["ALL"]
            self.assertEqual((t.wrong, t.missed, t.definite_gold), (wrong, missed, 0), said)
        with self.assertRaises(ValueError):  # a definite answer against an unclear one is a real disagreement
            build_gold(a, {"x": {"furniture": {"answer": "items", "items": ["says_furnished"], "evidence": "אופציה לרהט"}}})


class TestItemLists(unittest.TestCase):
    """furniture is graded on its ids: naming one nobody allowed is wrong
    (an A/C counted as furniture); leaving out a required one is missed."""

    A = {"x": {"furniture": {"answer": "items", "items": ["fridge", "sofa"], "evidence": "מקרר וספה"}}}
    B = {"x": {"furniture": {"answer": "items", "items": ["fridge"], "also_ok_items": ["closets"], "evidence": "מקרר"}}}

    def test_required_is_what_both_named_allowed_is_what_either_did(self):
        g = build_gold(self.A, self.B)["x"]["furniture"]
        self.assertEqual((g["items"], g["allowed_items"]), (["fridge"], ["closets", "fridge", "sofa"]))

    def test_grading(self):
        gold = build_gold(self.A, self.B)
        for items, wrong, missed, correct in ((["fridge"], 0, 0, 1), (["fridge", "sofa", "closets"], 0, 0, 1),
                                              (["fridge", "tv"], 1, 0, 0), (["sofa"], 0, 1, 0), ([], 0, 1, 0)):
            t = score(gold, {"x": {"furniture": {"answer": "items", "items": items}}})["furniture"]
            self.assertEqual((t.wrong, t.missed, t.correct), (wrong, missed, correct), items)

    def test_an_unknown_id_is_refused(self):
        with self.assertRaises(ValueError):
            build_gold({"x": {"furniture": {"answer": "items", "items": ["air_conditioner"]}}}, self.B)

    def test_an_acceptable_amount_needs_its_number(self):
        with self.assertRaisesRegex(ValueError, "no labeler gave the number"):
            build_gold({"x": {"vaad_bayit": {"answer": "unclear", "also_ok": ["amount"]}}},
                       {"x": {"vaad_bayit": {"answer": "unclear"}}})


class TestTheQuoteMustSayIt(unittest.TestCase):
    """A real quote that doesn't mean the answer: the four errors Gemini
    made on held-out batch 4 had real quotes."""

    def test_answers_whose_quote_doesnt_say_them_are_cut(self):
        from rental_matcher.extraction.prompt import ground
        text = "דירה בקומת קרקע. שידת טלוויזיה בסלון, ספה. חברות כ\"א לא להתקשר. דירת גן עם חצר"
        out = ground({"apartment_type": {"answer": "garden", "evidence": "בקומת קרקע"},
                      "furniture": {"answer": "items", "items": ["sofa", "tv", "cabinet"], "evidence": "שידת טלוויזיה ... ספה"},
                      "broker": {"answer": "no_broker", "evidence": "חברות כ\"א לא להתקשר"}}, text)
        self.assertEqual(out["apartment_type"]["answer"], NOT_STATED)
        self.assertIn("unsupported", out["apartment_type"]["problem"])
        self.assertEqual(out["furniture"]["items"], ["sofa", "cabinet"])  # a TV stand isn't a TV
        self.assertEqual(out["broker"]["answer"], NOT_STATED)
        ok = ground({"apartment_type": {"answer": "garden", "evidence": "דירת גן עם חצר"},
                     "furniture": {"answer": "items", "items": ["tv"], "evidence": "שידת טלוויזיה"}}, text)
        self.assertEqual(ok["apartment_type"]["answer"], "garden")
        self.assertEqual(ok["furniture"]["answer"], NOT_STATED)  # nothing left on the list
        self.assertEqual(ground(ok, text), ok)  # idempotent: a saved run can be grounded again

    def test_the_subject_must_be_in_the_quote(self):
        from rental_matcher.extraction.prompt import ground
        text = "קומה רביעית ללא עמודים. קומה 18, נוף. מתאימה לשותפים. קומה 4 ללא"
        out = ground({"elevator": {"answer": "no", "evidence": "ללא עמודים"},  # no pillars, not no elevator
                      "room_share": {"answer": "yes", "evidence": "מתאימה לשותפים"}}, text)
        self.assertEqual((out["elevator"]["answer"], out["room_share"]["answer"]), (NOT_STATED, NOT_STATED))
        # v1.18.5: a floor of 6+ on its own (no מעלית word at all) now grounds a
        # "yes" too -- no building that tall lacks an elevator (see rules.py).
        self.assertEqual(ground({"elevator": {"answer": "yes", "evidence": "קומה 18"}}, text)["elevator"]["answer"], "yes")
        self.assertEqual(ground({"elevator": {"answer": "no", "evidence": "קומה 4 ללא"}}, text)["elevator"]["answer"], "no")
        # a LOW floor on its own still proves nothing either way
        self.assertEqual(ground({"elevator": {"answer": "yes", "evidence": "קומה רביעית ללא עמודים"}}, text)["elevator"]["answer"], NOT_STATED)

    def test_seeking_or_replacing_alone_is_not_a_room(self):
        # v1.18.7: "מחפשת מחליף/ה!" was a whole-flat lease handover (batch 6)
        from rental_matcher.extraction.prompt import ground
        text = "מחפשת מחליף/ה! מושלמת למי שמחפש שקט. מחפשת שותפה לחדר"
        for quote in ("מחפשת מחליף/ה!", "למי שמחפש"):
            self.assertEqual(ground({"room_share": {"answer": "yes", "evidence": quote}}, text)["room_share"]["answer"], NOT_STATED)
        self.assertEqual(ground({"room_share": {"answer": "yes", "evidence": "מחפשת שותפה לחדר"}}, text)["room_share"]["answer"], "yes")

    def test_no_gold_list_is_cut(self):
        from rental_matcher.extraction.prompt import ground
        texts = load(EVAL / "yad2_texts.json")
        cut = []
        for lid, by in gold_set().items():
            for qid, g in by.items():
                if g.get("items") and _settled(g):  # v1.42: batch 7's in8na0ol ("רק להביא בגדים") also accepts unclear
                    out = ground({qid: {"answer": "items", "items": g["items"], "evidence": g["evidence"]}}, texts[lid])[qid]
                    if out.get("items") != g["items"]:
                        cut.append(lid)
        # v1.51: batch 8 too ("חדר שינה קומפלט" is a bed, "מיבש" a dryer)
        self.assertEqual(cut, [])
