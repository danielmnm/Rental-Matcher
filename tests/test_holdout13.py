"""Held-out batch 13, measured with the rules frozen at v1.59.1 (tag rules-v1.59.1-frozen, 2ffd47f).

280 listings fetched Nov 5 after the freeze, from ten cities no batch or census had used (Ra'anana, Hod HaSharon,
Kiryat Motzkin, Kiryat Yam, Nof HaGalil, Safed, Kiryat Ono, Or Yehuda, Sderot, Arad); none among the 640 or an earlier
batch. Saved by the browser as one file, checked by its SHA-256. 6 dropped as not homes (3 before labeling; 3 offices
or commercial spaces both labelers flagged). Two blind labelers in private folders: 2954/3014 exact, 0 conflicts.
The frozen run was saved before any labels existed. Pinned as measured; nothing fitted on it.
"""
import json
import unittest
from pathlib import Path

from rental_matcher.extraction.rules import combine
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


class TestHeldOutBatch13(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        cls.gold = load("holdout13/gold.json")["gold"]
        run = load("runs/2026-11-05_rules_v1591_frozen_on_holdout13.json")
        cls.md5 = run["_rules_md5"]
        cls.frozen = {k: v for k, v in run.items() if not k.startswith("_")}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout13_2026-11-05")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(cls.frozen[k], {}) for k in tg}, PREFS)

    def test_the_batch_is_fresh(self):
        from rental_matcher.extraction.evaluate import gold_set
        self.assertEqual(len(self.gold), 274)
        self.assertEqual(len(self.frozen), 277)  # saved before 3 non-homes were dropped
        self.assertLessEqual(set(self.gold), set(self.frozen))
        self.assertFalse(set(self.gold) & set(gold_set()))
        self.assertEqual(self.md5, "ebeb2ed73208c8cc0b008b8834780437")

    def test_the_text(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage
        t = score(self.gold, self.frozen)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold), (14, 686, 727))
        self.assertEqual(settled_coverage(self.gold, self.frozen)["ALL"], (636, 674))

    def test_the_card(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage, settled_credit, universal_bar, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        self.assertEqual((len(self.cg), t.wrong, t.correct_definite, t.definite_gold), (263, 12, 1569, 1604))
        self.assertEqual(settled_coverage(self.cg, self.ca)["ALL"], (1457, 1492))
        self.assertAlmostEqual(settled_credit(self.cg, self.ca)["ALL"][0], 1464.0, places=0)  # 98.1%
        self.assertEqual(sorted(w.split("/")[1].split(":")[0] for w in t.wrong_items),
                         ["apartment_type"] * 2 + ["furniture"] * 7 + ["parking", "protected_space", "room_share"])
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in wrongly_hidden(self.cg, self.ca).items()},
                         {"room_share": ["qd7596s1"], "parking": ["voq00a0b"]})
        failed = [c for c, ok in universal_bar(self.cg, self.ca, partial=True) if not ok]
        self.assertEqual(len(failed), 5)  # 12 wrong, 2 hidden, under 95%: parking 31/35, apartment type 66/70, furniture 98/113


if __name__ == "__main__":
    unittest.main()
