"""v1.43: the Gemini test asks only for listings its last run of the same prompt didn't have."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import run_gemini_test as r
from rental_matcher.extraction import gemini

RUNS = Path(__file__).resolve().parent / "eval" / "runs"


class TestGeminiRunContinues(unittest.TestCase):
    def test_new_listings_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(RUNS / "2026-10-20_gemini_b8_p9e70d1.json", tmp)
            f = r.run_file(tmp)
            d = json.loads(f.read_text(encoding="utf-8"))
            texts = json.loads((RUNS.parent / "yad2_texts.json").read_text(encoding="utf-8"))
            missing = [k for k in texts if k not in d]
            self.assertEqual(len(missing), 187 + 177)  # held-out batches 7 and 8
            self.assertFalse(d["_complete"])
            self.assertTrue(gemini.resumable(d, "auto"))  # gemini.main resumes it: only the new ones are asked
            self.assertEqual(r.run_file(tmp), f)  # and the next run goes on with the same file

    def test_held_out_is_batch_8(self):  # v1.50 (batch 7 until then)
        self.assertEqual(r.HELD_OUT[1], "yad2_holdout8_2026-10-28")


if __name__ == "__main__":
    unittest.main()
