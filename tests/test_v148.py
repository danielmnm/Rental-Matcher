"""
v1.48: the tests read a frozen copy of the owner's preferences
(tests/fixtures/prefs_frozen.json), not the live preferences/my.json.

The live file is his: the extension's settings page rewrites it whenever he
changes a budget or a search, and many tests pinned numbers from it (a price
cap of 5,450, say). Once he raised his budget, the suite failed on his own
machine and in every zip made after it, for no fault in the code. The frozen
copy is the file as those tests were written against; the live one only has
to stay loadable.
"""

import unittest
from pathlib import Path

from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]


class TestPreferencesFiles(unittest.TestCase):
    def test_the_live_preferences_still_load(self):
        live = ROOT / "preferences" / "my.json"
        if live.is_file():  # a fresh clone of someone else's may have none
            self.assertTrue(PreferenceSet.load(live).preferences)

    def test_the_frozen_copy_loads(self):
        self.assertTrue(PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json").preferences)


if __name__ == "__main__":
    unittest.main()


class TestHeldOutFirst(unittest.TestCase):
    """v1.48: the Gemini run asks for the held-out batch before the rest."""

    def test_the_held_out_listings_come_first_and_nothing_is_lost(self):
        import json
        import sys
        sys.path.insert(0, str(ROOT))
        import run_gemini_test as r
        texts = json.loads((ROOT / "tests" / "eval" / "yad2_texts.json").read_text(encoding="utf-8"))
        ordered = r.held_out_first(texts)
        ids = r.held_out_ids()
        self.assertEqual(len(ids), 177)  # v1.50: batch 8
        self.assertEqual(set(ordered), set(texts))
        self.assertEqual(set(list(ordered)[:len(ids)]), ids)
        self.assertTrue(all(ordered[k] == texts[k] for k in texts))

    def test_a_partial_run_reports_how_far_it_got(self):
        import io
        import json
        import sys
        from contextlib import redirect_stdout
        sys.path.insert(0, str(ROOT))
        import run_gemini_test as r
        gold = json.loads((ROOT / "tests" / "eval" / "yad2_gold.json").read_text(encoding="utf-8"))["gold"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertFalse(r.held_out_report({}, gold))
        self.assertIn("answered 0 of", buf.getvalue())


class TestGeminiOnBatch7(unittest.TestCase):
    """v1.48: the record of Gemini (gemini-3.5-flash-lite, the Oct 20 run's
    model, continued) on held-out batch 7, scored against the rules frozen at
    v1.42. Pinned so a later change can't quietly rewrite it."""

    def test_the_numbers(self):
        import json
        import sys
        sys.path.insert(0, str(ROOT))
        import run_gemini_test as r
        from rental_matcher.extraction.evaluate import same_questions, score
        from rental_matcher.extraction.prompt import ground
        from rental_matcher.extraction.rules import combine
        load = lambda p: json.loads(p.read_text(encoding="utf-8"))
        texts = load(ROOT / "tests" / "eval" / "yad2_texts.json")
        run = load(ROOT / "tests" / "eval" / "runs" / "2026-10-28_gemini_b8_p9e70d1.json")
        self.assertEqual((run["_model"], run["_complete"]), ("gemini-3.5-flash-lite", True))
        answers = {k: ground(v, texts[k]) for k, v in run.items() if not k.startswith("_")}
        gold = load(ROOT / "tests" / "eval" / "yad2_gold.json")["gold"]
        frozen = load(ROOT / "tests" / "eval" / "runs" / "2026-10-27_rules_v142_frozen_on_holdout7.json")
        held = {k: v for k, v in same_questions(gold, frozen).items() if k in r.held_out_ids("yad2_holdout7_2026-10-27")}
        self.assertEqual(len(held), 187)
        g = score(held, answers)["ALL"]
        both = score(held, {k: combine(frozen[k], answers[k]) for k in held})["ALL"]
        # Oct 28 (v1.48's checks): Gemini 7 wrong at 394/414, with the frozen rules 10 wrong at 403/414.
        # Every run is grounded again under today's checks: since v1.49 a quote of kitchen cabinets
        # can't carry "closets" and "חדר שירות" can't carry a service balcony, which drops two of
        # Gemini's wrong answers (with the frozen rules, one: hu93jybf stays wrong on the rules'
        # own "washer"). Coverage is the same: neither was a right answer.
        self.assertEqual((g.wrong, g.correct_definite, g.definite_gold), (5, 394, 414))
        self.assertEqual((both.wrong, both.correct_definite, both.definite_gold), (9, 403, 414))
