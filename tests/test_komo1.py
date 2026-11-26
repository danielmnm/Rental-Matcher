"""Phase 3: held-out Komo batch 1, measured with the rules frozen at v1.61 (tag rules-v1.61-frozen, d4fef76) before it
was fetched. 252 listings from Komo's first results page in 12 cities, Nov 7; 3 with no text dropped; 15 of the 249
repeat an apartment already in an earlier Yad2 batch (the same flat on both sites), so the held-out score counts the
other 234. Two blind labelers with the Yad2 guide: 2684/2739 exact, 3 conflicts kept both answers. Pinned as measured."""
import json
import unittest
from pathlib import Path

from rental_matcher.extraction.rules import combine
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


class TestKomoBatch1AsMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        ev = ROOT / "tests" / "eval"
        load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))
        gold = load("komo1/gold.json")["gold"]
        cls.seen = set(load("komo1/overlap.json"))
        cls.gold = {k: v for k, v in gold.items() if k not in cls.seen}
        run = load("runs/2026-11-07_rules_v161_frozen_on_komo1.json")
        cls.md5 = run["_rules_md5"]
        frozen = {k: v for k, v in run.items() if not k.startswith("_")}
        ex = load_extracts(ROOT / "tests" / "fixtures" / "komo_batch1_2026-11-07")
        tg = {k: v for k, v in cls.gold.items() if k in ex}
        cls.cg, cls.ca, _ = card_score_inputs(ex, tg, {k: combine(frozen[k], {}) for k in tg}, PREFS)

    def test_the_sample(self):
        self.assertEqual((len(self.seen), len(self.gold), len(self.cg)), (15, 234, 234))
        self.assertEqual(self.md5, "1950d30b9bf1cde64eed8e5da6a5e76a")

    def test_card_test_v2(self):
        """The frozen run's answers, graded by today's card (the adapters and the key as of v1.62). As measured with the
        v1.61 card (README): 6 wrong and 59 listings hidden, 59 of them from one cause, Komo's parking count read as
        the building's with no "whose isn't said" floor; v1.62 moved that rule into adapters/common.py for every site."""
        from rental_matcher.extraction.evaluate import answer_counts, bar_v2, score, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        self.assertEqual(sorted(w.split("/")[1].split(":")[0] for w in t.wrong_items), ["furniture", "furniture", "parking"])
        rest = [c for q, c in answer_counts(self.cg, self.ca).items() if q != "furniture"]
        self.assertEqual((sum(d for d, _ in rest), sum(w for _, w in rest)), (719, 1))
        self.assertEqual({q: sorted(x for v in by.values() for x in v) for q, by in wrongly_hidden(self.cg, self.ca).items()},
                         {"parking": ["komo_4957024", "komo_4957776", "komo_4958161"]})  # 2 are the owner's "בבניין" ruling (adjudications.json)
        failed = [c.split(" (got")[0] for c, ok in bar_v2(self.cg, self.ca) if not ok]
        self.assertEqual(failed, ["no listing hidden by a misreading, for any must-have", "settled facts read >= 85.0% on vaad_bayit",
                                  "at least 250 listings"])  # vaad: 3 of 4 settled facts, too few to judge (decision 0002: pooled)


if __name__ == "__main__":
    unittest.main()
