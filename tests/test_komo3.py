"""Phase 3: held-out Komo batch 3, the reading rules frozen at v1.64 before it was fetched (Nov 10). As measured.

352 listings from Komo's first results page in 20 cities; 347 with text; 115 already seen (Komo batch 1 or 2, or the same text in
an earlier Yad2 batch) and 2 for sale, so the held-out score counts 230 (218 that the product's adapter can read). Labelers A and
B blind, A's files hashed and moved away before B started; 3747/3817 exact.

What dominates the result: on 65 listings whose text opens with "דירה ..." (a renovated flat, a flat for one or two), the rules
answer "a whole flat" and both labelers this time answered "not stated". In every earlier labeled set the same opening was a whole
flat: 111 of 112 in the 640, and 281 of 284 across held-out batches 13, 14 and Komo 1 and 2. That is a change in the labelers'
convention, not a new misreading. the owner's ruling (Nov 11, after reviewing all 65): a whole flat, as before; applied as
adjudications on top of the blind labels and reported beside the as-measured result.
"""
import json
import unittest
from pathlib import Path

from rental_matcher.extraction.rules import combine
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


def _load(name):
    return json.loads((ROOT / "tests" / "eval" / name).read_text(encoding="utf-8"))


def _cards(batch, run, fixture, adjudicated=True):
    from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
    from rental_matcher.extraction.evaluate import widen
    gold = _load(f"{batch}/gold.json")["gold"]
    if adjudicated:
        gold = widen(gold, _load(f"{batch}/adjudications.json")["adjudications"])
    seen = set(_load(f"{batch}/overlap.json"))
    drop = {k.replace(":", "_") for k in _load(f"{batch}/dropped.json")}
    r = _load(f"runs/{run}")
    frozen = {k: v for k, v in r.items() if not k.startswith("_")}
    ex = load_extracts(ROOT / "tests" / "fixtures" / fixture)
    tg = {k: v for k, v in gold.items() if k not in seen and k not in drop and k in ex}
    cg, ca, _ = card_score_inputs(ex, tg, {k: combine(frozen[k], {}) for k in tg}, PREFS)
    return cg, ca, r["_rules_md5"], frozen


RUN = "2026-11-10_rules_v164_frozen_on_komo3.json"


class TestKomoBatch3AsMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cg, cls.ca, cls.md5, cls.frozen = _cards("komo3", RUN, "komo_batch3_2026-11-10", adjudicated=False)  # as measured: the blind labels

    def test_the_sample(self):
        self.assertEqual(len(_load("komo3/texts.json")), 347)
        self.assertEqual((len(_load("komo3/overlap.json")), len(self.cg)), (115, 218))
        self.assertEqual(self.md5, "63e87b0729fbccdbc8472bf17d64c1e9")

    def test_card_test_v2(self):
        from rental_matcher.extraction.evaluate import answer_counts, score, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        wrong = sorted(w.split("/")[1].split(":")[0] for w in t.wrong_items)
        self.assertEqual(wrong, ["furniture"] * 2 + ["room_share"] * 65)
        counts = answer_counts(self.cg, self.ca)
        self.assertEqual(sum(w for q, (_, w) in counts.items() if q not in ("furniture", "room_share")), 0)
        # "במתחם חניון ציבורי": the rules read street parking; one labeler allowed the building's
        self.assertEqual(wrongly_hidden(self.cg, self.ca), {"parking": {"at_least 2.0": ["komo_4959692"]}})

    def test_with_owners_ruling(self):
        """the owner's ruling (Nov 11): "דירה ..." is a whole flat. The 65 aren't wrong; 2 furniture misreadings remain."""
        from rental_matcher.extraction.evaluate import score
        self.assertEqual(len(_load("komo3/adjudications.json")["adjudications"]), 67)  # the 65 the owner reviewed + 2 of the same kind the card left open
        cg, ca, _, _ = _cards("komo3", RUN, "komo_batch3_2026-11-10")
        t = score(cg, ca)["ALL"]
        self.assertEqual(sorted(w.split("/")[1].split(":")[0] for w in t.wrong_items), ["furniture", "furniture"])

    def test_pooled_komo_batches_1_to_3(self):
        """Decision 0002: Komo's three held-out batches pooled, each graded by its own frozen run (v1.61, v1.63, v1.64) and
        today's card, with the owner's rulings applied as adjudications. Komo's card isn't shown to meet the bar yet."""
        from rental_matcher.extraction.evaluate import pooled_budgets
        from tests.test_komo2 import _cards as cards12
        sets = [cards12("komo1", "2026-11-07_rules_v161_frozen_on_komo1.json", "komo_batch1_2026-11-07", adjudicated=True)[:2],
                cards12("komo2", "2026-11-09_rules_v163_frozen_on_komo2.json", "komo_batch2_2026-11-09", adjudicated=True)[:2],
                _cards("komo3", RUN, "komo_batch3_2026-11-10")[:2]]
        rows = dict(c.split(": ", 1) for c, _ in pooled_budgets(sets))
        verdicts = {c.split(":")[0]: v for c, v in pooled_budgets(sets)}
        self.assertTrue(rows["facts that can hide or rank"].startswith("5/2004 wrong"))  # 0.25%, 95% CI 0.11-0.58%
        self.assertEqual(verdicts["facts that can hide or rank"], "not shown yet")
        self.assertEqual(verdicts["furniture"], "over")  # 11/301, 3.7%
        self.assertEqual(verdicts["apartment_type"], "over")  # 1/25
        for q in ("elevator", "air_conditioning", "room_share"):
            self.assertEqual(verdicts[q], "met", q)


if __name__ == "__main__":
    unittest.main()
