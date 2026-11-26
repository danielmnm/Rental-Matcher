"""Phase 3, step 4: Madlan sample 1, the card's amenity facts against what each Madlan page displayed. In-sample.

41 listing pages (Tel Aviv and Haifa, Nov 19-25), stopped short of the planned 98 because Madlan's bot check came after every 1-2
pages (decision 0004). The answer key is each page's own checklist ('מפרט מלא': an icon ticked or grey), not a labeler. The
description's facts weren't labeled for Madlan: the rules that read them are the ones measured on Yad2 and Komo.

As first read (v1.67, the adapter's names unconfirmed): 103 of the 166 facts the pages showed were on the card, 0 wrong. The
balcony was missed 19 times of 20, every storage room (14) and window bars (14), and 16 shelters (a floor's or the building's).
v1.68 reads Madlan's own names; the same 41 pages: 166 of 166, 0 wrong. Fixed on these pages, so it's in-sample: a lookup of
field names, not a reading rule, but still measured on what it was fixed for.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestMadlanSample1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([sys.executable, "tests/eval/madlan1/score.py"], cwd=ROOT, capture_output=True, text=True, check=True)
        cls.s = json.loads(r.stdout)

    def test_the_sample(self):
        self.assertEqual(self.s["listings"], 41)

    def test_every_fact_the_page_showed_is_on_the_card(self):
        self.assertEqual(self.s["total"], {"page_yes": 166, "read": 166, "card_yes_page_no": 0})
        self.assertEqual(self.s["misses"], [])
        b = self.s["by_fact"]
        self.assertEqual((b["balcony"]["page_yes"], b["storage"]["page_yes"], b["window_bars"]["page_yes"], b["protected_space"]["page_yes"]),
                         (20, 14, 14, 27))
        self.assertEqual(b["elevator"]["inferred_ok"], 1)  # a 6+ floor building: the owner's elevator ruling, not on the page's checklist


    def test_madlans_own_names(self):
        from datetime import date
        from rental_matcher.adapters import madlan
        sig = madlan.structured_signals({"amenities": {"grating": True, "unitPetsAllowed": True, "miklat": True, "isFurnished": True},
                                         "areas": {"balcony": 2, "storage": 0}}, date(2026, 11, 25))
        for name in ("window_bars", "pets_allowed", "building_shelter", "protected_space", "furniture_box", "balcony"):
            self.assertIn(name, sig, name)
        self.assertNotIn("storage", sig)
        self.assertNotIn("mamad", sig)  # the building's shelter isn't the flat's safe room


if __name__ == "__main__":
    unittest.main()
