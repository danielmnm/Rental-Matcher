"""Phase 3: held-out Komo batch 2, the reading rules frozen at v1.63 before it was fetched (Nov 9). As measured.

289 listings from Komo's first results page in 20 cities; 287 with text; 37 already seen (Komo batch 1, or the same text in an
earlier Yad2 batch) and 2 not homes for rent, so the held-out score counts 248 (246 that the product's adapter can read).
Labelers A and B blind, A's files hashed and moved away before B started; 3111/3157 exact, 2 conflicts kept both answers.
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


def _cards(batch, run, fixture, adjudicated=False):
    from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
    from rental_matcher.extraction.evaluate import widen
    gold = _load(f"{batch}/gold.json")["gold"]
    if adjudicated:
        gold = widen(gold, _load(f"{batch}/adjudications.json")["adjudications"])
    seen = set(_load(f"{batch}/overlap.json"))
    drop = {k.replace(":", "_") for k in _load(f"{batch}/dropped.json")} if (ROOT / "tests" / "eval" / batch / "dropped.json").exists() else set()
    r = _load(f"runs/{run}")
    frozen = {k: v for k, v in r.items() if not k.startswith("_")}
    ex = load_extracts(ROOT / "tests" / "fixtures" / fixture)
    tg = {k: v for k, v in gold.items() if k not in seen and k not in drop and k in ex}
    cg, ca, _ = card_score_inputs(ex, tg, {k: combine(frozen[k], {}) for k in tg}, PREFS)
    return cg, ca, r["_rules_md5"]


class TestKomoBatch2AsMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cg, cls.ca, cls.md5 = _cards("komo2", "2026-11-09_rules_v163_frozen_on_komo2.json", "komo_batch2_2026-11-09")

    def test_the_sample(self):
        self.assertEqual(len(_load("komo2/texts.json")), 287)
        self.assertEqual((len(_load("komo2/overlap.json")), len(self.cg)), (37, 246))
        self.assertEqual(self.md5, "f7666a6454c89d868fdda8d8c3bff51f")

    def test_card_test_v2(self):
        from rental_matcher.extraction.evaluate import answer_counts, bar_v2, score, wrongly_hidden
        t = score(self.cg, self.ca)["ALL"]
        wrong = sorted(w.split("/")[1].split(":")[0] for w in t.wrong_items)
        self.assertEqual(wrong, ["apartment_type", "balcony"] + ["furniture"] * 7 + ["parking"] * 2)
        rest = [c for q, c in answer_counts(self.cg, self.ca).items() if q != "furniture"]
        self.assertEqual((sum(d for d, _ in rest), sum(w for _, w in rest)), (729, 4))
        # hidden: "חנייה בבניין" read as the building's (the owner's ruling); one labeler allowed deeded
        self.assertEqual(wrongly_hidden(self.cg, self.ca), {"parking": {"at_least 3.0": ["komo_4958868"]}})
        failed = [c for c, ok in bar_v2(self.cg, self.ca) if not ok]
        self.assertEqual(len(failed), 7, failed)  # hidden 1, hide-or-rank 0.55%, apartment type 1/8, furniture 6.4%,
        # parking read 81.8%, building fee read 50% (5 of 10), 246 < 250 listings

    def test_with_owners_standing_ruling(self):
        from rental_matcher.extraction.evaluate import wrongly_hidden
        cg, ca, _ = _cards("komo2", "2026-11-09_rules_v163_frozen_on_komo2.json", "komo_batch2_2026-11-09", adjudicated=True)
        self.assertEqual(wrongly_hidden(cg, ca), {})

    def test_pooled_with_batch_1(self):
        """Decision 0002: Komo's two held-out batches pooled (batch 1's frozen v1.61 run graded by today's card)."""
        from rental_matcher.extraction.evaluate import pooled_budgets
        c1, a1, _ = _cards("komo1", "2026-11-07_rules_v161_frozen_on_komo1.json", "komo_batch1_2026-11-07")
        verdicts = {c.split(":")[0]: v for c, v in pooled_budgets([(c1, a1), (self.cg, self.ca)])}
        self.assertEqual(verdicts["facts that can hide or rank"], "not shown yet")  # 5/1448, 0.35% (CI 0.15-0.81%)
        self.assertEqual(verdicts["furniture"], "over")  # 9/206, 4.4%
        self.assertEqual(verdicts["apartment_type"], "over")  # 1/18
        for q in ("elevator", "air_conditioning", "room_share"):
            self.assertEqual(verdicts[q], "met", q)


if __name__ == "__main__":
    unittest.main()
