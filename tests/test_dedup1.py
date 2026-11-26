"""Phase 3, step 3: does the duplicate matcher join the same apartment across Komo and Yad2, and only that? As measured.

Matcher frozen at tag dedup-v1.62-frozen before the Yad2 rows were pulled (Nov 9). Candidates: for each Komo listing of the
Nov 7 sample, the Yad2 rows its own filtered search returned (same city and rooms, rent within its band, size within 10 m²);
the matcher saw them in the product's shape (a Yad2 search row has no street). Labeled blind by two labelers: all 127 merged
pairs, shuffled with 60 of the 430 closest unmerged pairs (2 per Komo listing), drawn with a fixed seed. The labelers saw both
addresses (Yad2's street comes from the same search feed; the product drops it), the facts, and Komo's text.

Budgets (Master Plan, Phase 3): at most 1% wrong merges (a wrong merge hides a real apartment behind another), at least 80% of
real twins found. Result: both missed. These numbers are pinned as measured; the fix is measured on a fresh pull.
"""
import json
import math
import unittest
from collections import Counter
from pathlib import Path

import importlib.util

E = Path(__file__).resolve().parent / "eval" / "dedup1"
# the matcher as measured (tag dedup-v1.62-frozen), not today's: the measurement stays reproducible after the fix
_spec = importlib.util.spec_from_file_location("sources_v162", E / "tools" / "sources_v162.py")
_v162 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v162)
same_apartment = _v162.same_apartment


def _j(name):
    return json.loads((E / name).read_text(encoding="utf-8"))


def _wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def _product(row):
    return {k: v for k, v in row.items() if k != "street"}  # the product's Yad2 search rows carry no street


class TestDedupMeasuredOnce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key, cls.a, cls.b, cls.rows = _j("key.json"), _j("labels_a.json"), _j("labels_b.json"), _j("rows.json")
        cls.gold = {k: (cls.a[k]["answer"] if cls.a[k]["answer"] == cls.b[k]["answer"] else "disagree") for k in cls.key}
        cls.t = Counter((cls.key[k]["part"], cls.gold[k]) for k in cls.key)

    def test_the_frozen_matcher_reproduces_its_verdicts(self):
        for pid, v in self.key.items():
            got = same_apartment(self.rows[v["komo"]], _product(self.rows["yad2:" + v["yad2"]]))
            self.assertEqual(got, v["merged"], pid)
        self.assertEqual(sum(v["merged"] for v in self.key.values()), 127)

    def test_labels_complete(self):
        for lab in (self.a, self.b):
            self.assertEqual(set(lab), set(self.key))
            self.assertTrue(all(x["answer"] in {"same", "different", "unsure"} for x in lab.values()))
        # the two labelers agreed on every pair (the address decides almost all of them)
        self.assertEqual(Counter(self.gold.values())["disagree"], 0)

    def test_wrong_merges_as_measured(self):
        same, wrong, unsure = self.t[("merged", "same")], self.t[("merged", "different")], self.t[("merged", "unsure")]
        self.assertEqual((same, wrong, unsure), (93, 32, 2))
        lo, hi = _wilson(wrong, same + wrong)
        self.assertAlmostEqual(wrong / (same + wrong), 0.256, places=3)
        self.assertGreater(lo, 0.01)  # over the 1% budget, and not by chance: the whole interval is above it
        causes = Counter(self.a[k]["why"].split(";")[0] for k in self.key if self.key[k]["part"] == "merged" and self.gold[k] == "different")
        self.assertEqual(causes["different street"] + causes["different house number"], 32)

    def test_twins_found_as_measured(self):
        found = self.t[("merged", "same")]
        near_same, near_diff = self.t[("near", "same")], self.t[("near", "different")]
        self.assertEqual((near_same, near_diff, self.t[("near", "unsure")]), (9, 48, 3))
        pull = _j("pull.json")
        missed = near_same / pull["near_sampled"] * pull["near_total"]  # the sample's twin rate, over all 430 closest unmerged pairs
        recall = found / (found + missed)
        self.assertAlmostEqual(recall, 0.59, places=2)
        self.assertLess(recall, 0.80)

    def test_known_twins(self):
        """The 10 Komo/Yad2 repeats found by identical text on Nov 7: of the 8 still online, the matcher joins 3. Two have the
        same address and facts but neighborhood names written differently; three disagree on size or floor between sites."""
        known = _j("known_twins.json")
        live = [x for x in known if x["live"]]
        self.assertEqual(len(live), 8)
        joined = [x for x in live if same_apartment(x["komo_row"], _product(x["yad2_row"]))]
        self.assertEqual(len(joined), 3)


if __name__ == "__main__":
    unittest.main()
