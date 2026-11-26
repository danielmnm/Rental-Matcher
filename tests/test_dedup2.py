"""Phase 3: the duplicate matcher v1.63 (frozen at tag dedup-v1.63-frozen before the pull), measured on a fresh sample. As measured.

289 Komo listings (Komo batch 2) against 3,899 Yad2 rows from 112 filtered searches, every result page (Nov 9). Two blind
labelers, A's files hashed and moved away before B started, judged 288 pairs: all 151 the matcher joined, all 37 it linked as
"possibly the same", and 100 of the 505 closest pairs it did neither with, drawn with a fixed seed. They agreed on 284;
a disagreement counts as unsure.
"""
import json
import math
import unittest
from collections import Counter
from pathlib import Path

import importlib.util

E = Path(__file__).resolve().parent / "eval" / "dedup2"
# the matcher as measured (tag dedup-v1.63-frozen), not today's
_spec = importlib.util.spec_from_file_location("sources_v163", E / "sources_v163.py")
_v163 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v163)
same_apartment, maybe_same = _v163.same_apartment, _v163.maybe_same


def _j(name):
    return json.loads((E / name).read_text(encoding="utf-8"))


def _wilson_hi(k, n, z=1.96):
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


class TestDedup2AsMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key, a, b, cls.rows = _j("key.json"), _j("labels_a.json"), _j("labels_b.json"), _j("rows.json")
        cls.agree = sum(a[k]["answer"] == b[k]["answer"] for k in cls.key)
        cls.gold = {k: (a[k]["answer"] if a[k]["answer"] == b[k]["answer"] else "unsure") for k in cls.key}
        cls.t = Counter((cls.key[k]["part"], cls.gold[k]) for k in cls.key)

    def test_the_matcher_reproduces_its_verdicts(self):
        for pid, v in self.key.items():
            k, y = self.rows[v["komo"]], self.rows["yad2:" + v["yad2"]]
            self.assertEqual((same_apartment(k, y), maybe_same(k, y)), (v["merged"], v["maybe"]), pid)
        self.assertEqual(Counter(v["part"] for v in self.key.values()), {"merged": 151, "maybe": 37, "near": 100})
        self.assertEqual(self.agree, 284)

    def test_wrong_joins(self):
        """0 of 150 joins are two different flats (1 unsure). Under 1% at the point estimate, but 150 can't show it: the
        95% upper bound is 2.5% (decision 0002: "not shown yet"); with no errors it takes about 380 joins."""
        same, wrong = self.t[("merged", "same")], self.t[("merged", "different")]
        self.assertEqual((same, wrong, self.t[("merged", "unsure")]), (150, 0, 1))
        self.assertAlmostEqual(_wilson_hi(wrong, same + wrong), 0.025, places=3)

    def test_twins_found(self):
        """About 68% of real twins joined (budget 80%), 79% joined or linked as "possibly the same"."""
        pull = _j("pull.json")
        found, linked, near = self.t[("merged", "same")], self.t[("maybe", "same")], self.t[("near", "same")]
        self.assertEqual((linked, self.t[("maybe", "different")], self.t[("maybe", "unsure")]), (26, 5, 6))
        self.assertEqual((near, self.t[("near", "different")], self.t[("near", "unsure")]), (9, 78, 13))
        missed = near / pull["near_sampled"] * pull["near_total"]
        self.assertAlmostEqual(found / (found + linked + missed), 0.68, places=2)
        self.assertAlmostEqual((found + linked) / (found + linked + missed), 0.79, places=2)

    def test_why_twins_were_missed(self):
        """8 of the 9 sampled twins it kept apart are in a city Komo writes "קריית" and Yad2 "קרית" (Kiryat Ata, Kiryat Gat),
        so the city didn't match; 7 of them have the same address and facts besides."""
        cities = Counter((self.rows[v["komo"]]["city"], self.rows["yad2:" + v["yad2"]]["city"]) for k, v in self.key.items()
                         if v["part"] == "near" and self.gold[k] == "same" and self.rows[v["komo"]]["city"] != self.rows["yad2:" + v["yad2"]]["city"])
        self.assertEqual(sum(cities.values()), 8)


if __name__ == "__main__":
    unittest.main()
