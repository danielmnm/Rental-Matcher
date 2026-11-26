"""
v1.50: held-out batch 8 (177 listings from an isolated search in Claude's own
browser: Bat Yam, Petah Tikva, Haifa; the owner's settings untouched), measured
on the frozen v1.49 rules and on Gemini. The numbers themselves are pinned in
test_rules.py (TestHeldOutBatch8, TestGeminiOnBatch8).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_gemini_test as r  # noqa: E402
from rental_matcher.extraction.prompt import prompt_id  # noqa: E402


class TestSecondRunOfTheDay(unittest.TestCase):
    def _write(self, path, complete, **extra):
        path.write_text(json.dumps({"_complete": complete, **extra}), encoding="utf-8")

    def test_an_unfinished_second_run_is_continued(self):
        # Oct 28: the first run of the day was finished, so the batch-8 run went to "..._2.json";
        # had it stopped halfway, the next start must continue that file, not begin a third
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d)
            tag = f"_gemini_b{r.BATCH}_p{prompt_id()}"
            self._write(runs / f"2026-10-28{tag}.json", True)
            self._write(runs / f"2026-10-28{tag}_2.json", False)
            self.assertEqual(r.run_file(runs).name, f"2026-10-28{tag}_2.json")

    def test_newest_first_by_date_then_number(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d)
            tag = f"_gemini_b{r.BATCH}_p{prompt_id()}"
            for name in (f"2026-10-27{tag}.json", f"2026-10-28{tag}.json", f"2026-10-28{tag}_2.json",
                         f"2026-10-28{tag}_10.json"):
                self._write(runs / name, True)
            self.assertEqual([f.name for f in r._runs_of(runs, tag)], [
                f"2026-10-28{tag}_10.json", f"2026-10-28{tag}_2.json", f"2026-10-28{tag}.json", f"2026-10-27{tag}.json"])

    def test_a_set_aside_run_is_never_continued(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d)
            tag = f"_gemini_b{r.BATCH}_p{prompt_id()}"
            self._write(runs / f"2026-10-27{tag}_set-aside-3.8-flash-in-sample.json", False)
            self.assertEqual(r._runs_of(runs, tag), [])


class TestBatch8IsInTheSet(unittest.TestCase):
    def test_held_out_is_batch_8_and_kept_out_of_the_priors(self):
        self.assertEqual(r.HELD_OUT[1], "yad2_holdout8_2026-10-28")
        self.assertEqual(len(r.held_out_ids()), 177)
        from rental_matcher import priors
        src = (ROOT / "rental_matcher" / "priors.py").read_text(encoding="utf-8")
        self.assertIn("yad2_holdout8", src)
        del priors

    def test_the_saved_gemini_run_answers_every_listing(self):
        run = json.loads((ROOT / "tests" / "eval" / "runs" / "2026-10-28_gemini_b8_p9e70d1_2.json").read_text(encoding="utf-8"))
        texts = json.loads((ROOT / "tests" / "eval" / "yad2_texts.json").read_text(encoding="utf-8"))
        self.assertTrue(run["_complete"])
        self.assertEqual(run["_model"], "gemini-3.5-flash-lite")
        self.assertEqual(set(texts) - set(run), set())


if __name__ == "__main__":
    unittest.main()
