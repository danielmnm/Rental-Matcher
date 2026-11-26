"""Phase 3: the duplicate matcher v1.64 (frozen at tag dedup-v1.64-frozen before the pull), measured on a fresh sample. As measured.

352 Komo listings (Komo batch 3; those already in batch 1 or 2 left out) against 8,390 Yad2 rows from 116 filtered searches,
every result page (Nov 10). Two blind labelers, A's files hashed and moved away before B started, judged 317 pairs: all 190 joins,
all 27 "possibly the same" links, 100 of the 456 closest pairs left apart (seeded). They agreed on 314; a disagreement is unsure.
"""
import importlib.util
import json
import math
import unittest
from collections import Counter
from pathlib import Path

E = Path(__file__).resolve().parent / "eval" / "dedup3"
_spec = importlib.util.spec_from_file_location("sources_v164", E / "sources_v164.py")
_v164 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v164)


def _j(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _gold(d):
    key, a, b = _j(d / "key.json"), _j(d / "labels_a.json"), _j(d / "labels_b.json")
    return key, {k: (a[k]["answer"] if a[k]["answer"] == b[k]["answer"] else "unsure") for k in key}, sum(a[k]["answer"] == b[k]["answer"] for k in key)


def _wilson_hi(k, n, z=1.96):
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


class TestDedup3AsMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key, cls.gold, cls.agree = _gold(E)
        cls.rows = _j(E / "rows.json")
        cls.t = Counter((cls.key[k]["part"], cls.gold[k]) for k in cls.key)

    def test_the_matcher_reproduces_its_verdicts(self):
        for pid, v in self.key.items():
            k, y = self.rows[v["komo"]], self.rows["yad2:" + v["yad2"]]
            self.assertEqual((_v164.same_apartment(k, y), _v164.maybe_same(k, y)), (v["merged"], v["maybe"]), pid)
        self.assertEqual(Counter(v["part"] for v in self.key.values()), {"merged": 190, "maybe": 27, "near": 100})
        self.assertEqual(self.agree, 314)

    def test_wrong_joins(self):
        """0 of 190 (upper bound 2.0%). Pooled with dedup 2 (v1.63, whose joins v1.64 keeps): 0 of 340, upper bound 1.12%,
        just over the 1% budget: about 40 more labeled joins with none wrong would show it."""
        self.assertEqual((self.t[("merged", "same")], self.t[("merged", "different")], self.t[("merged", "unsure")]), (190, 0, 0))
        k2, g2, _ = _gold(E.parent / "dedup2")
        s2 = sum(1 for k in k2 if k2[k]["part"] == "merged" and g2[k] == "same")
        d2 = sum(1 for k in k2 if k2[k]["part"] == "merged" and g2[k] == "different")
        self.assertEqual((s2, d2), (150, 0))
        self.assertAlmostEqual(_wilson_hi(0, 340), 0.0112, places=4)

    def test_twins_found(self):
        """91% of the real twins joined (budget 80%: met); with the "possibly the same" links, all of them. None of the 100
        sampled near-misses was a twin."""
        joined, linked, near = self.t[("merged", "same")], self.t[("maybe", "same")], self.t[("near", "same")]
        self.assertEqual((linked, self.t[("maybe", "different")], self.t[("maybe", "unsure")]), (19, 5, 3))
        self.assertEqual((near, self.t[("near", "different")], self.t[("near", "unsure")]), (0, 89, 11))
        self.assertAlmostEqual(joined / (joined + linked), 0.91, places=2)


if __name__ == "__main__":
    unittest.main()
