"""v1.57 (Nov 2): the owner's review of v1.56, Yad2's renamed search feed, and the total a month."""

import json
import unittest
from pathlib import Path

from rental_matcher.pipeline import build_listing
from rental_matcher.scoring import PreferenceSet
from rental_matcher.server import _total_monthly

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "yad2_holdout10_2026-10-30"
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


def _listing(lid, **change):
    ex = json.loads((FIX / f"{lid}.json").read_text(encoding="utf-8"))
    ex.update(change)
    return build_listing(ex, PREFS)


class TestTotalMonthly(unittest.TestCase):
    def test_rent_plus_both_fees_as_yad2_adds_them(self):
        # Yad2's own box on a live listing (Nov 2): 4,300 + 100 + 500/2 = 4,650; here 4,200 + 100 + 560/2
        x = _listing("3so5kb61")
        self.assertEqual((x.price.amount, x.recurring_costs.vaad_bayit_monthly, x.recurring_costs.arnona_monthly), (4200, 100, 280))
        self.assertEqual(_total_monthly(x), 4580)

    def test_only_when_both_fees_are_known(self):
        x = _listing("3so5kb61", houseCommittee=None)  # the text doesn't give the building fee either
        self.assertIsNone(x.recurring_costs.vaad_bayit_monthly)
        self.assertIsNone(_total_monthly(x))

    def test_in_the_rent_counts_as_nothing(self):
        x = _listing("5om9y8zw")  # "המחיר כולל ארנונה + וועד", Yad2's fee fields filled in
        self.assertEqual((x.recurring_costs.arnona_monthly, x.recurring_costs.vaad_bayit_monthly), (0, 0))
        self.assertEqual(_total_monthly(x), x.price.amount)


if __name__ == "__main__":
    unittest.main()


class TestHeldOutBatch11(unittest.TestCase):
    """263 listings fetched Nov 2 after the rules were frozen (fe7fa79, v1.57), from eight cities no batch or census had
    used (Ashdod, Ramat HaSharon, Lod, Ramla, Nahariya, Karmiel, Afula, Beit Shemesh). Yad2's bot check stopped the first pull;
    the rest came at a slower pace. Two blind labelers in private folders: 2836/2893 exact, 2893/2893 compatible.
    Pinned as measured; nothing fitted on it."""

    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        from rental_matcher.extraction.rules import combine
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        cls.gold, cls.texts = load("holdout11/gold.json")["gold"], load("holdout11/texts.json")
        cls.frozen = {k: v for k, v in load("runs/2026-11-02_rules_v157_frozen_on_holdout11.json").items() if not k.startswith("_")}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "yad2_holdout11_2026-11-02")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(cls.frozen[k], {}) for k in tg}, PREFS)

    def test_the_frozen_run_is_what_the_frozen_rules_say(self):
        from rental_matcher.extraction.rules import answer
        self.assertEqual(len(self.gold), 263)
        now = {k: answer(self.texts[k]) for k in self.gold}
        # v1.58 fitted on this batch (tests/test_v158.py), so the rules now read some of it differently; the frozen run
        # is the record of what v1.57 said, and these pins stay on it
        self.assertEqual(set(now), set(self.frozen))
        self.assertNotEqual(now, self.frozen)

    def test_the_text(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage
        t = score(self.gold, self.frozen)["ALL"]
        self.assertEqual((t.wrong, t.correct_definite, t.definite_gold), (16, 676, 735))
        self.assertEqual(settled_coverage(self.gold, self.frozen)["ALL"], (636, 688))

    def test_the_card(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage, settled_credit, universal_bar, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        self.assertEqual((len(self.cg), t.wrong, t.correct_definite, t.definite_gold), (257, 12, 1569, 1604))
        self.assertEqual(settled_coverage(self.cg, self.ca)["ALL"], (1462, 1496))
        self.assertAlmostEqual(settled_credit(self.cg, self.ca)["ALL"][0], 1472.9, places=1)  # 98.5%
        self.assertEqual(sorted(w.split("/")[1].split(":")[0] for w in t.wrong_items),
                         ["balcony", "elevator"] + ["furniture"] * 9 + ["protected_space"])
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in wrongly_hidden(self.cg, self.ca).items()},
                         {"parking": ["lj4mlmq9", "v5w8mq19"]})
        failed = [c for c, ok in universal_bar(self.cg, self.ca, partial=True) if not ok]
        self.assertEqual(len(failed), 3)  # 12 wrong, 2 hidden, furniture 77.9/92; every other question at 97% or more

    def test_without_the_14_already_labeled(self):
        """14 of the 263 were among the 640 labeled listings (Ramat HaSharon ads still up from October): not unseen.
        Without them the result is the same: all 12 wrong answers and both hidden listings are on fresh ones."""
        from rental_matcher.extraction.evaluate import gold_set, score, settled_credit
        seen = set(gold_set())
        self.assertEqual(len(seen & set(self.gold)), 14)
        cg = {k: v for k, v in self.cg.items() if k not in seen}
        ca = {k: self.ca[k] for k in cg}
        t = score(cg, ca)["ALL"]
        self.assertEqual((len(cg), t.wrong), (243, 12))
        right, n = settled_credit(cg, ca)["furniture"]
        self.assertEqual((round(right, 1), n), (70.0, 84))
