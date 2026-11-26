"""Phase 3: the duplicate matcher v1.66 (frozen at tag dedup-v1.66-frozen before the pull; its matching code is v1.64's), measured
on a fourth fresh sample. As measured.

352 Komo listings from 20 cities no earlier batch used (Komo batch 4; those already in batches 1 to 3 left out) against 1,118 Yad2
rows from 109 filtered searches, every result page (Nov 19; Ma'ale Adumim and Ariel read on yad-il.co.il, where Yad2 sends them).
Two blind labelers, A's files hashed and moved away before B started, judged 362 pairs: all 219 joins, all 43 "possibly the same"
links, 100 of the 511 closest pairs left apart (seeded). They agreed on 350; a disagreement is unsure.
"""
import importlib.util
import json
import math
import unittest
from collections import Counter
from pathlib import Path

E = Path(__file__).resolve().parent / "eval" / "dedup4"
_spec = importlib.util.spec_from_file_location("sources_v166", E / "sources_v166.py")
_v166 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v166)


def _j(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _gold(d):
    key, a, b = _j(d / "key.json"), _j(d / "labels_a.json"), _j(d / "labels_b.json")
    return key, {k: (a[k]["answer"] if a[k]["answer"] == b[k]["answer"] else "unsure") for k in key}, sum(a[k]["answer"] == b[k]["answer"] for k in key)


def _wilson_hi(k, n, z=1.96):
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


class TestDedup4AsMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key, cls.gold, cls.agree = _gold(E)
        cls.rows = _j(E / "rows.json")
        cls.t = Counter((cls.key[k]["part"], cls.gold[k]) for k in cls.key)

    def test_the_matcher_reproduces_its_verdicts(self):
        for pid, v in self.key.items():
            k, y = self.rows[v["komo"]], self.rows["yad2:" + v["yad2"]]
            self.assertEqual((_v166.same_apartment(k, y), _v166.maybe_same(k, y)), (v["merged"], v["maybe"]), pid)
        self.assertEqual(Counter(v["part"] for v in self.key.values()), {"merged": 219, "maybe": 43, "near": 100})
        self.assertEqual(self.agree, 350)

    def test_the_matching_code_is_v164s(self):
        """So the earlier fresh samples pool with this one: v1.65 and v1.66 changed only the source names and ranks."""
        old = (E.parent / "dedup3" / "sources_v164.py").read_text(encoding="utf-8")
        new = (E / "sources_v166.py").read_text(encoding="utf-8")
        for fn in ("def same_apartment", "def maybe_same", "def same_address", "def _city"):
            body = lambda s: s[s.index(fn):s.index("\ndef ", s.index(fn) + 1)]
            self.assertEqual(body(old), body(new), fn)

    def test_wrong_joins(self):
        """0 of 217 (2 unsure: the form and the poster's own text give different house numbers, so the labelers couldn't tell).
        Pooled with the v1.63 and v1.64 samples (the same matching code): 0 of 557, upper bound 0.68%, inside the 1% budget:
        met (decision 0002). Counting the 2 unsure as wrong: 2 of 559, upper bound 1.3%, not shown."""
        self.assertEqual((self.t[("merged", "same")], self.t[("merged", "different")], self.t[("merged", "unsure")]), (217, 0, 2))
        same = 217
        for d in ("dedup3", "dedup2"):
            k2, g2, _ = _gold(E.parent / d)
            self.assertEqual(sum(1 for k in k2 if k2[k]["part"] == "merged" and g2[k] == "different"), 0, d)
            same += sum(1 for k in k2 if k2[k]["part"] == "merged" and g2[k] == "same")
        self.assertEqual(same, 557)
        self.assertLess(_wilson_hi(0, same), 0.01)
        self.assertAlmostEqual(_wilson_hi(0, same), 0.0068, places=4)
        self.assertGreater(_wilson_hi(2, same + 2), 0.01)

    def test_twins_found(self):
        """About 90% of the real twins joined (budget 80%: met). 15 more are linked as "possibly the same"; 2 of the 100 sampled
        near-misses were twins (about 10 of the 511)."""
        joined, linked, near = self.t[("merged", "same")], self.t[("maybe", "same")], self.t[("near", "same")]
        self.assertEqual((linked, self.t[("maybe", "different")], self.t[("maybe", "unsure")]), (15, 22, 6))
        self.assertEqual((near, self.t[("near", "different")], self.t[("near", "unsure")]), (2, 84, 14))
        missed = near / 100 * 511
        self.assertAlmostEqual(joined / (joined + linked + missed), 0.896, places=3)


if __name__ == "__main__":
    unittest.main()
