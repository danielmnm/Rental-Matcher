"""Phase 3: held-out Komo batch 4, the reading rules frozen at v1.66 before it was fetched (Nov 19). As measured.

352 listings from Komo's first results page in 20 cities no earlier batch used; 350 with text; 18 already seen (an earlier Komo or
Yad2 batch), so 322 card listings: the first Komo batch over the 250 a batch needs. Labelers A and B blind, A's files hashed and
moved away before B started; 3747/3850 exact, 11 conflicts kept both answers.

As with batch 3, the labelers answered "not stated" for room share on texts that call the place a flat ("דירה ...") and say
nothing about a room: 95 of them. the owner's standing ruling (Nov 11) says that's a whole apartment; it's applied as adjudications
on top of the blind labels and reported beside the as-measured result. 8 more texts call the place a unit, a studio or a house:
the ruling's words don't cover them, so they stay as labeled, for the owner to rule on.
"""
import unittest

from tests.test_komo2 import _cards as cards12
from tests.test_komo3 import _cards

RUN = "2026-11-19_rules_v166_frozen_on_komo4.json"
FIX = "komo_batch4_2026-11-19"


def _wrong(cg, ca):
    from rental_matcher.extraction.evaluate import score
    return sorted(w.split("/")[0] + "/" + w.split("/")[1].split(":")[0] for w in score(cg, ca)["ALL"].wrong_items)


class TestKomoBatch4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cg, cls.ca, cls.md5, _ = _cards("komo4", RUN, FIX, adjudicated=False)
        cls.cgr, cls.car, _, _ = _cards("komo4", RUN, FIX, adjudicated=True)

    def test_the_sample(self):
        self.assertEqual(len(self.cg), 322)
        self.assertEqual(self.md5, "f0a66cbec174cb8af9c6076423120cad")

    def test_as_measured(self):
        from rental_matcher.extraction.evaluate import wrongly_hidden
        w = _wrong(self.cg, self.ca)
        self.assertEqual(sum(x.endswith("/room_share") for x in w), 103)
        self.assertEqual(sum(x.endswith("/parking") for x in w), 3)
        self.assertEqual(sum(x.endswith("/furniture") for x in w), 2)
        self.assertEqual(len(w), 108)
        self.assertEqual(wrongly_hidden(self.cg, self.ca), {})

    def test_with_owners_ruling(self):
        """13 of 880 wrong on facts that can hide or rank (1.5%): 8 texts the ruling doesn't cover (a unit, a studio, a house),
        2 real shared flats read as whole ("נשאר מקום לשוכר שלישי, בדירה ל-3 שותפים"; "מתפנים בקרוב 3 חדרים"), and 3 parking
        places. Parking read 41 of 55 settled facts (74.5%); 0 listings hidden."""
        from rental_matcher.extraction.evaluate import bar_v2, wrongly_hidden
        self.assertEqual(len(self.__class__.cgr), 322)
        w = _wrong(self.cgr, self.car)
        self.assertIn("komo_4941711/room_share", w)
        self.assertIn("komo_4791737/room_share", w)
        self.assertEqual(sum(x.endswith("/room_share") for x in w), 10)
        self.assertEqual(len(w), 15)
        self.assertEqual(wrongly_hidden(self.cgr, self.car), {})
        failed = [c.split(":")[0].split(" (")[0] for c, ok in bar_v2(self.cgr, self.car) if not ok]
        self.assertEqual(len(failed), 5, failed)

    def test_pooled_batches_1_to_4(self):
        """Decision 0002, with the owner's rulings: facts that can hide or rank 18 of 2,884 (0.62%): over the 0.5% budget."""
        from rental_matcher.extraction.evaluate import pooled_budgets
        sets = [cards12("komo1", "2026-11-07_rules_v161_frozen_on_komo1.json", "komo_batch1_2026-11-07", adjudicated=True)[:2],
                cards12("komo2", "2026-11-09_rules_v163_frozen_on_komo2.json", "komo_batch2_2026-11-09", adjudicated=True)[:2],
                _cards("komo3", "2026-11-10_rules_v164_frozen_on_komo3.json", "komo_batch3_2026-11-10")[:2], (self.cgr, self.car)]
        rows = {c.split(":")[0]: (c, v) for c, v in pooled_budgets(sets)}
        self.assertTrue(rows["facts that can hide or rank"][0].split(": ", 1)[1].startswith("18/2884 wrong"))
        self.assertEqual(rows["facts that can hide or rank"][1], "over")
        self.assertEqual(rows["furniture"][1], "over")
        for q in ("elevator", "air_conditioning", "protected_space", "balcony"):
            self.assertEqual(rows[q][1], "met", q)


if __name__ == "__main__":
    unittest.main()
