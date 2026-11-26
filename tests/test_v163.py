"""v1.63 (Nov 9): the duplicate matcher compares the address first, and never merges two listings without one.

the owner's ruling after the first duplicate measurement (tests/test_dedup1.py: 32 of 125 joins were two different flats, all
on a different street or house number): two separate listings becoming one is the worst case; a duplicate is tolerable.
So a merge needs both addresses (street and house number) to agree; the rooms, floor, size and rent are compared after.
When the address and rooms agree but the floor or size doesn't, the two stay apart and each links the other. A merged
apartment shows, and is scored at, its cheapest rent, with a link to every copy.
"""
import json
import unittest
from pathlib import Path

from rental_matcher.scoring import PreferenceSet
from rental_matcher.server import do_plan
from rental_matcher.sources import address, dedupe, maybe_same, maybe_twins, same_address, same_apartment

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / "tests" / "eval" / "dedup1"
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")

Y = {"id": "y1", "source": "yad2", "city": "בת ים", "hood_name": "מפדה אזרחי", "street": "זאב יעבץ 4", "rooms": 4, "floor": 1,
     "size_m2": 98, "price": 5500, "lat": 32.01, "lng": 34.78}
K = {"id": "komo:1", "source": "komo", "url": "https://www.komo.co.il/code/nadlan/details/?modaaNum=1", "city": "בת ים",
     "hood_name": "מפדה", "street": "יעבץ 4", "rooms": 4, "floor": 1, "size_m2": 98, "price": 5500, "lat": None, "lng": None,
     "approx": True}


class TestTheAddressFirst(unittest.TestCase):
    def test_the_same_street_written_two_ways(self):
        """From the labeled batch: the same address as each site writes it."""
        for a, b in [("קול משה 8", "משה קול 8"), ("שד ירושלים 103", "שדרות ירושלים 103"), ("לוחמי הגיטו 6", "לוחמי הגטו 6"),
                     ("קורצ'ק יאנוש 4", "יאנוש קורצ'אק 4"), ("בר יוחאי 22", "שמעון בר יוחאי 22"), ("יעבץ 4", "זאב יעבץ 4"),
                     ("קצנלסון יצחק 10", "יצחק קצנלסון 10"), ("החי\"ם 14", "החים 14"), ("ביאליק 12", "חיים נחמן ביאליק 12"),
                     ("הגלבוע 44", "גלבוע 44"), ("ינאי 6", "ינאי 6"), ("יאיר 15", "יאיר אברהם שטרן 15")]:
            self.assertTrue(same_address(a, b), (a, b))

    def test_different_addresses(self):
        for a, b in [("שיק 6", "זלמן שז\"ר 41"), ("אמנון ליפקין שחק 8", "אמנון ליפקין שחק 12"), ("עמק איילון 15", "יגאל אלון 46"),
                     ("הרצל 12", "הרצליה 12"), ("בלפור 1", "חיים נחמן ביאליק 90"), ("הגליל 6", "הגליל 6א"),
                     ("איילון 15", "יגאל אלון 15"),  # alike without their vowels, and a word left out: not trusted
                     ("יגאל אלון 46", "יגאל אלון"), ("יגאל אלון", "יגאל אלון"),  # no house number on one side or both
                     ("", "הרצל 3"), (None, None)]:
            self.assertFalse(same_address(a, b), (a, b))
        self.assertEqual(address("שד עובד בן עמי 2"), (("עובד", "בן", "עמי"), "2"))

    def test_no_merge_without_both_addresses(self):
        self.assertTrue(same_apartment(K, Y))
        for change in ({"street": None}, {"street": "יעבץ"}, {"street": "יעבץ 6"}, {"street": "הרצל 4"}):
            self.assertFalse(same_apartment(dict(K, **change), Y), change)
        # same site: the same address is one flat posted twice; a pin further than one building away says otherwise
        self.assertTrue(same_apartment(Y, dict(Y, id="y2")))
        self.assertFalse(same_apartment(Y, dict(Y, id="y2", lat=32.012)))
        self.assertFalse(same_apartment(Y, dict(Y, id="y2", street=None)))

    def test_facts_still_have_to_agree(self):
        for change in ({"floor": 2}, {"rooms": 3}, {"size_m2": 94}, {"price": 7000}, {"city": "בת ים"}, {"size_m2": None}):
            self.assertFalse(same_apartment(dict(K, **change), Y), change)
        self.assertTrue(same_apartment(dict(K, size_m2=100, price=5200), Y))  # 2 m² and 6% apart: the same flat

    def test_none_of_the_labeled_wrong_joins_is_joined(self):
        """The measured batch, in-sample (these pairs shaped the rule, so this is a check, not proof): none of the 80 pairs
        the labelers called two different flats is joined; 96 of the 102 they called one flat are."""
        key = json.loads((E / "key.json").read_text(encoding="utf-8"))
        lab = json.loads((E / "labels_a.json").read_text(encoding="utf-8"))
        rows = json.loads((E / "rows.json").read_text(encoding="utf-8"))
        joined = {pid: same_apartment(rows[v["komo"]], rows["yad2:" + v["yad2"]]) for pid, v in key.items()}
        self.assertEqual(sum(joined[p] for p in key if lab[p]["answer"] == "different"), 0)
        self.assertEqual(sum(joined[p] for p in key if lab[p]["answer"] == "unsure"), 0)
        self.assertEqual(sum(joined[p] for p in key if lab[p]["answer"] == "same"), 96)


class TestDisagreementsAreLinkedNotMerged(unittest.TestCase):
    def test_floor_or_size_disagreeing(self):
        for change in ({"floor": 6}, {"size_m2": 94}, {"size_m2": 140}):
            k = dict(K, **change)
            self.assertFalse(same_apartment(k, Y))
            self.assertTrue(maybe_same(k, Y), change)
        self.assertFalse(maybe_same(dict(K, rooms=3, floor=6), Y))  # different rooms too: no link
        self.assertFalse(maybe_same(dict(K, street="יעבץ 6", floor=6), Y))  # another address: no link
        self.assertFalse(maybe_same(K, Y))  # the same flat is merged, not linked

    def test_both_cards_link_the_other(self):
        k = dict(K, floor=6)
        out = maybe_twins([Y, k, dict(Y, id="y9", street="הרצל 1")])
        self.assertEqual(sorted(out), ["komo:1", "y1"])
        self.assertEqual((out["y1"][0]["id"], out["y1"][0]["floor"]), ("komo:1", 6.0))
        self.assertEqual((out["komo:1"][0]["id"], out["komo:1"][0]["floor"]), ("y1", 1.0))
        plan = do_plan({"rows": [Y, k]}, PREFS)
        self.assertIn("y1", plan["maybe"])


class TestTheCheapestCopy(unittest.TestCase):
    def test_kept_row_is_planned_at_the_cheapest_rent(self):
        rows, also = dedupe([dict(K, price=5200), Y])
        self.assertEqual([r["id"] for r in rows], ["y1"])  # Yad2 kept: it has a pin and a full page
        self.assertEqual((rows[0]["price"], rows[0]["price_own"]), (5200.0, 5500))
        self.assertEqual(also["y1"][0]["price"], 5200.0)
        self.assertEqual(Y["price"], 5500)  # the input row isn't changed
        rows, _ = dedupe([dict(K, price=5800), Y])
        self.assertEqual(rows[0]["price"], 5500)
        self.assertNotIn("price_own", rows[0])


try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "Playwright isn't installed")
class TestTheCard(unittest.TestCase):
    def render(self, x, detail):
        i18n = (ROOT / "browser" / "i18n.js").read_text(encoding="utf-8")
        cards = (ROOT / "browser" / "cards.js").read_text(encoding="utf-8")
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page()
            page.set_content("<html><body><div id=r></div></body></html>")
            page.add_script_tag(content=i18n)
            page.add_script_tag(content=cards)
            out = page.evaluate("""([x, detail]) => {
                const I = window.RentalI18n; I.setLang("en");
                const c = window.RentalCards.render(document, x, { I, detail });
                document.getElementById("r").append(c);
                return { text: c.innerText, links: [...c.querySelectorAll("a")].map((a) => [a.href, a.innerText]) };
            }""", [x, detail])
            b.close()
        return out

    def test_a_merged_apartment_and_a_possible_twin(self):
        x = {"id": "y1", "url": "https://www.yad2.co.il/realestate/item/y1", "price": 5200, "price_own": 5500, "fit": "good",
             "city": "בת ים", "street": "זאב יעבץ 4", "rooms": 4, "floor": 1, "size_m2": 98, "notes": [], "asks": [], "trips": [],
             "also": [{"source": "komo", "name": "Komo", "id": "komo:1", "url": "https://www.komo.co.il/code/nadlan/details/?modaaNum=1",
                       "price": 5200, "same_site": False, "size_m2": 100}],
             "maybe": [{"source": "madlan", "name": "Madlan", "id": "madlan:a", "url": "https://www.madlan.co.il/listings/a",
                        "price": 5400, "floor": 6, "size_m2": 98}]}
        out = self.render(x, True)
        self.assertIn("98–100 m²", out["text"])  # the copies disagree on the size: a range
        self.assertIn("₪5,200", out["text"])  # the cheapest copy's rent
        self.assertIn("₪300", out["text"])  # "cheaper on Komo" by the difference from this copy's own rent
        maybe = [t for u, t in out["links"] if "madlan" in u]
        self.assertTrue(maybe and "Possibly the same apartment" in maybe[0] and "floor 6 there, 1 here" in maybe[0], out["links"])
        self.assertTrue(any("komo" in u for u, _ in out["links"]))


if __name__ == "__main__":
    unittest.main()
