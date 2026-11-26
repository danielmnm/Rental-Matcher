"""Held-out batch 14: the first batch judged by Card test v2 (decision 0001), with the rules frozen at v1.60
(tag rules-v1.60-frozen, 729c7c4) before it was fetched.

280 listings fetched Nov 6 from ten cities no batch had used (Ramat HaSharon, Yehud-Monosson, Kiryat Bialik, Nesher,
Tirat Carmel, Zichron Yaakov, Pardes Hanna-Karkur, Kiryat Shmona, Gedera, Beit She'an); none among the 640 or an
earlier batch. Saved by the browser as one file, checked by its SHA-256 on both ends. 2 dropped as not homes. Two blind
labelers: 2994/3058 exact, 0 conflicts. The frozen run was saved before any labels existed. Pinned as measured.
"""
import json
import unittest
from pathlib import Path

from rental_matcher.extraction.rules import combine
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


class TestHeldOutBatch14(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        cls.gold = load("holdout14/gold.json")["gold"]
        run = load("runs/2026-11-06_rules_v160_frozen_on_holdout14.json")
        cls.md5 = run["_rules_md5"]
        cls.frozen = {k: v for k, v in run.items() if not k.startswith("_")}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout14_2026-11-06")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(cls.frozen[k], {}) for k in tg}, PREFS)

    def test_the_batch_is_fresh(self):
        from rental_matcher.extraction.evaluate import gold_set
        self.assertEqual((len(self.gold), len(self.frozen)), (278, 279))  # saved before one non-home was dropped
        self.assertLessEqual(set(self.gold), set(self.frozen))
        self.assertFalse(set(self.gold) & set(gold_set()))
        self.assertEqual(self.md5, "d38a10edc3d45698c958dd9d68a7883f")

    def test_card_test_v2_as_measured(self):
        from rental_matcher.extraction.evaluate import answer_counts, bar_v2, wrongly_hidden
        failed = [c.split(" (got")[0] for c, ok in bar_v2(self.cg, self.ca) if not ok]
        self.assertEqual(failed, ["no listing hidden by a misreading, for any must-have", "wrong <= 3.0% on furniture"])
        counts = answer_counts(self.cg, self.ca)
        self.assertEqual(counts["furniture"], (125, 5))  # 4.0%, budget 3%
        rest = [c for q, c in counts.items() if q != "furniture"]
        self.assertEqual((sum(d for d, _ in rest), sum(w for _, w in rest)), (1795, 3))  # 0.17%, budget 0.5%
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in wrongly_hidden(self.cg, self.ca).items()},
                         {"parking": ["yzmx3b2p"]})  # "חניה בבניין": the owner's Nov 5 ruling says building, the labelers allowed deeded

    def test_the_old_bar_for_comparison(self):
        from rental_matcher.extraction.evaluate import score, settled_credit
        t = score(self.cg, self.ca)["ALL"]
        self.assertEqual((len(self.cg), t.wrong), (274, 8))
        self.assertAlmostEqual(settled_credit(self.cg, self.ca)["ALL"][0], 1516.2, places=0)  # 98.1%


if __name__ == "__main__":
    unittest.main()


class TestBatch14WithOwnersRuling(unittest.TestCase):
    """Decision 0002: the frozen run with the owner's standing "בבניין" ruling applied (adjudications.json), reported
    beside the as-measured result, not instead of it."""

    def test_only_furniture_is_over_budget(self):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        from rental_matcher.extraction.evaluate import bar_v2, widen
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        gold = widen(load("holdout14/gold.json")["gold"], load("holdout14/adjudications.json")["adjudications"])
        frozen = {k: v for k, v in load("runs/2026-11-06_rules_v160_frozen_on_holdout14.json").items() if not k.startswith("_")}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout14_2026-11-06")
        tg = {k: v for k, v in gold.items() if k in ex}
        cg, ca, _ = card_score_inputs(ex, tg, {k: combine(frozen[k], {}) for k in tg}, PREFS)
        self.assertEqual([c.split(" (got")[0] for c, ok in bar_v2(cg, ca) if not ok], ["wrong <= 3.0% on furniture"])

    def test_pooled_verdicts_as_measured(self):
        # decision 0002's pooled rule, on the one batch measured under v1.60 so far: the facts that can hide or rank a
        # listing are shown within budget; furniture is over it on the point estimate
        from rental_matcher.extraction.evaluate import pooled_budgets
        t = TestHeldOutBatch14
        t.setUpClass()
        got = dict((c.split(":")[0], v) for c, v in pooled_budgets([(t.cg, t.ca)]))
        self.assertEqual(got["facts that can hide or rank"], "met")
        self.assertEqual(got["furniture"], "over")
        self.assertEqual(got["parking"], "not shown yet")  # 3 of 254: 1.2%, but the interval still reaches past 2%
