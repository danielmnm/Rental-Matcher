"""
Tests for the Yad2 adapter, on 20 real listing pages saved Oct 18, 2026
(tests/fixtures/yad2; the poster's name and contact details were never
saved, and phone numbers in descriptions are blanked).
"""

import json
import re
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from rental_matcher.adapters.yad2 import structured_signals, to_listing
from rental_matcher.schema import ListedBy, Listing, SignalStatus

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yad2"
AS_OF = datetime(2026, 10, 18, tzinfo=timezone.utc)


def _extracts() -> dict[str, dict]:
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(FIXTURES.glob("*.json"))}


def _listings() -> dict[str, Listing]:
    return {k: to_listing(x, AS_OF) for k, x in _extracts().items() if "error" not in x}


class TestFixtures(unittest.TestCase):
    def test_twenty_live_two_removed(self):
        extracts = _extracts()
        self.assertEqual(len(extracts), 22)
        removed = {k for k, x in extracts.items() if "error" in x}
        self.assertEqual(removed, {"x5zoqq0y", "3pzt8w1y"})
        for k in removed:
            with self.assertRaises(ValueError):
                to_listing(extracts[k], AS_OF)

    def test_no_personal_contact_data_was_saved(self):
        for k, x in _extracts().items():
            self.assertFalse({"customer", "searchText", "token"} & set(x), k)
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", json.dumps(x, ensure_ascii=False)), k)


class TestTickedMeansYesUntickedMeansUnknown(unittest.TestCase):
    def test_the_adapter_never_says_no(self):
        # Yad2's form defaults includeSecurityRoom to false: it's false on
        # all 20, including listings whose text describes a shelter.
        # the one no: the property's condition, a required choice ("well kept" = not renovated)
        for k, listing in _listings().items():
            for name, signal in listing.signals.items():
                self.assertEqual(signal.status, SignalStatus.CONFIRMED, (k, name))
                if signal.value is False:
                    self.assertEqual(name, "renovated", k)
                    self.assertIn("(not renovated)", signal.evidence)

    def test_an_unticked_safe_room_is_unknown(self):
        self.assertTrue(all(x["inProperty"].get("includeSecurityRoom") is False
                            for x in _extracts().values() if "error" not in x))
        self.assertTrue(all("mamad" not in l.signals for l in _listings().values()))
        k678 = _listings()["k678s664"]  # text: "מקלט צמוד לבניין", box not ticked
        self.assertNotIn("protected_space", k678.signals)

    def test_protected_space_is_a_safe_room_or_a_building_shelter(self):
        listings = _listings()
        self.assertIn("protected_space", listings["s2614l93"].signals)
        self.assertNotIn("protected_space", listings["qo6mc683"].signals)
        self.assertEqual(structured_signals({"inProperty": {"includeSecurityRoom": True}}, AS_OF.date())["protected_space"].value, True)

    def test_suits_roommates_is_not_a_room_share(self):
        for k in ("uzj7unmh", "k678s664", "1mlutq6h", "7b0umktb"):
            signals = _listings()[k].signals
            self.assertIn("suits_roommates", signals, k)
            self.assertNotIn("roommate_listing", signals, k)


class TestStructuredFacts(unittest.TestCase):
    def test_ad_type_is_the_source_stating_who_listed_it(self):
        listings = _listings()
        # Agree with the old tracker's notes / the descriptions' own words.
        self.assertEqual(listings["2n3u1zl7"].listed_by, ListedBy.AGENCY)
        self.assertEqual(listings["8raxcjyc"].listed_by, ListedBy.PRIVATE)  # "ללא תיווך"
        self.assertEqual(listings["s2614l93"].listed_by, ListedBy.PRIVATE)  # "ללא תיווך! (מתווכים נא לא לפנות)"
        self.assertEqual(sum(l.listed_by == ListedBy.AGENCY for l in listings.values()), 7)

    def test_parking_is_a_lower_bound(self):
        self.assertEqual(_listings()["s2614l93"].signals["parking_level"].value, 2.0)
        self.assertEqual(sum("parking_level" in l.signals for l in _listings().values()), 1)

    def test_days_until_available(self):
        listings = _listings()
        self.assertEqual(listings["qo6mc683"].signals["days_until_available"].value, 0.0)  # immediate
        self.assertEqual(listings["8raxcjyc"].signals["days_until_available"].value, 28.0)  # Nov 15
        self.assertEqual(listings["1mlutq6h"].signals["days_until_available"].value, 0.0)  # Oct 1, already past

    def test_numbers_and_round_trip(self):
        listing = _listings()["7b0umktb"]
        self.assertEqual((listing.price.amount, listing.rooms, listing.size_m2, listing.floor, listing.total_floors),
                         (4200, 2.5, 70, 2, 3))
        for listing in _listings().values():
            self.assertEqual(Listing.model_validate(listing.model_dump(mode="json")), listing)

    def test_odd_inputs(self):
        with self.assertRaises(ValueError):
            to_listing({"id": "x", "price": 0}, AS_OF)
        with self.assertRaises(ValueError):
            to_listing({"id": "x", "price": True}, AS_OF)
        s = structured_signals({"inProperty": {"includeParking": "yes", "includeBalcony": 1},
                                "additionalDetails": {"parkingSpacesCount": True, "entranceDate": "garbage"}}, date(2026, 10, 18))
        self.assertEqual(s, {})  # only real True / real counts count


if __name__ == "__main__":
    unittest.main()


SECOND = Path(__file__).resolve().parent / "fixtures" / "yad2_2026-10-19"
AS_OF_2 = datetime(2026, 10, 19, tzinfo=timezone.utc)


class TestSecondBatch(unittest.TestCase):
    """35 more live Bat Yam listings from the owner's saved search, Oct 19, kept
    in their own folder so the Oct 18 expectations above stay fixed."""

    def setUp(self):
        self.extracts = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(SECOND.glob("*.json"))}

    def test_thirty_five_live_none_shared_with_the_first_batch(self):
        self.assertEqual(len(self.extracts), 35)
        self.assertFalse(set(self.extracts) & set(_extracts()))
        for k, x in self.extracts.items():
            self.assertNotIn("error", x, k)
            self.assertFalse({"customer", "searchText", "token"} & set(x), k)
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", json.dumps(x, ensure_ascii=False)), k)

    def test_the_adapter_still_never_says_no(self):
        for k, x in self.extracts.items():
            for name, signal in to_listing(x, AS_OF_2).signals.items():
                if signal.value is False:  # only the condition can say no
                    self.assertEqual((name, x["additionalDetails"]["propertyCondition"]["id"] in (3, 5)), ("renovated", True), k)

    def test_a_ticked_safe_room_is_confirmed(self):
        ticked = {k for k, x in self.extracts.items() if x["inProperty"].get("includeSecurityRoom")}
        self.assertEqual(ticked, {"2a5m0b7a"})  # text: "חשוב לציין שיש ממד"
        self.assertTrue(to_listing(self.extracts["2a5m0b7a"], AS_OF_2).signals["protected_space"].value)

    def test_eval_texts_are_the_descriptions_verbatim(self):
        texts = json.loads((Path(__file__).resolve().parent / "eval" / "yad2_texts.json").read_text(encoding="utf-8"))
        holdout = {f.stem: json.loads(f.read_text(encoding="utf-8")) for d in (HOLDOUT, HOLDOUT2, HOLDOUT3, HOLDOUT4, HOLDOUT5, HOLDOUT6, HOLDOUT7, HOLDOUT8) for f in sorted(d.glob("*.json"))}
        for k, x in {**_extracts(), **self.extracts, **holdout}.items():
            if "error" not in x:
                self.assertEqual(texts[k], x["description"], k)
        self.assertEqual(len(texts), 640)


HOLDOUT = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout_2026-10-19"
HOLDOUT2 = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout2_2026-10-19"
HOLDOUT3 = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout3_2026-10-19"
HOLDOUT4 = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout4_2026-10-20"
HOLDOUT5 = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout5_2026-10-20"
HOLDOUT6 = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout6_2026-10-20"
HOLDOUT7 = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout7_2026-10-27"
HOLDOUT8 = Path(__file__).resolve().parent / "fixtures" / "yad2_holdout8_2026-10-28"


class TestHoldoutBatch(unittest.TestCase):
    """31 more listings fetched AFTER the rule-based answerer was frozen
    (commit fde6165), to measure it on text it was never written against."""

    def test_thirty_live_no_contact_data_none_seen_before(self):
        x = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(HOLDOUT.glob("*.json"))}
        self.assertEqual(len(x), 31)
        self.assertEqual({k for k, v in x.items() if "error" in v}, {"3cd45fmo"})
        seen = set(_extracts()) | {f.stem for f in SECOND.glob("*.json")}
        self.assertFalse(set(x) & seen)
        for k, v in x.items():
            self.assertFalse({"customer", "searchText", "token", "address", "metaData"} & set(v), k)
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", json.dumps(v, ensure_ascii=False)), k)
            if "error" not in v:
                to_listing(v, AS_OF_2)


class TestHoldoutBatch2(unittest.TestCase):
    """32 more, fetched after rules v2 were frozen (commit 81f5df8). 16 were
    saved with the description and a few fields only."""

    def test_thirty_two_no_contact_data_no_names_none_seen_before(self):
        x = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(HOLDOUT2.glob("*.json"))}
        self.assertEqual(len(x), 32)
        seen = set(_extracts()) | {f.stem for d in (SECOND, HOLDOUT) for f in d.glob("*.json")}
        self.assertFalse(set(x) & seen)
        for k, v in x.items():
            text = json.dumps(v, ensure_ascii=False)
            self.assertFalse({"customer", "searchText", "token", "address", "metaData"} & set(v), k)
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", text), k)
        self.assertIn("[name]", x["ejbgeysr"]["description"])  # an agent's personal name, removed


class TestHoldoutBatch3(unittest.TestCase):
    """33 more (Bat Yam, page 3), fetched after v1.17 -- rules v3, the prompt
    with "unclear", the veto -- was frozen (commit 1a9192b). Saved with the
    description and a few fields only."""

    def test_thirty_three_no_contact_data_no_names_none_seen_before(self):
        x = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(HOLDOUT3.glob("*.json"))}
        self.assertEqual(len(x), 33)
        seen = set(_extracts()) | {f.stem for d in (SECOND, HOLDOUT, HOLDOUT2) for f in d.glob("*.json")}
        self.assertFalse(set(x) & seen)
        for k, v in x.items():
            text = json.dumps(v, ensure_ascii=False)
            self.assertEqual(set(v), {"id", "adType", "price", "rooms", "description", "fetched_at", "source_url", "_saved"}, k)
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", text), k)
        self.assertTrue(x["kra8kee3"]["description"].endswith("לפנות ל[name]"))  # the owner's first name, removed


class TestFurnitureBoxAndType(unittest.TestCase):
    def test_the_furniture_box_is_its_own_claim_and_the_type_is_read_by_name(self):
        s = structured_signals({"inProperty": {"includeFurniture": True},
                                "additionalDetails": {"property": {"id": 99, "text": "דירת גג/ פנטהאוז"}}}, date(2026, 10, 20))
        self.assertNotIn("furnished", s)  # a ticked box isn't "furnished": owners tick it for one chair
        self.assertTrue(s["furniture_box"].value)
        self.assertEqual(s["apartment_type"].value, "roof")
        self.assertNotIn("apartment_type", structured_signals({"additionalDetails": {"property": {"id": 1, "text": "דירה"}}}, date(2026, 10, 20)))


class TestHoldoutBatch4(unittest.TestCase):
    """38 more (Bat Yam, Ramat Gan, Ramat HaSharon; a warehouse and a shop left
    out), fetched after v1.18 was frozen (commit 8e2ccc9). Saved with the
    description, Yad2's property type and its checkboxes: no poster or
    contact data."""

    def setUp(self):
        self.x = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(HOLDOUT4.glob("*.json"))}

    def test_thirty_eight_no_contact_data_no_names_none_seen_before(self):
        self.assertEqual(len(self.x), 38)
        seen = set(_extracts()) | {f.stem for d in (SECOND, HOLDOUT, HOLDOUT2, HOLDOUT3) for f in d.glob("*.json")}
        self.assertFalse(set(self.x) & seen)
        for k, v in self.x.items():
            self.assertEqual(set(v), {"id", "adType", "price", "rooms", "property", "inProperty", "description",
                                      "fetched_at", "source_url", "_saved"}, k)
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", json.dumps(v, ensure_ascii=False)), k)
        self.assertTrue(self.x["yyarmwwi"]["description"].endswith("שיווק [name]-נכסים"))  # an agent's first name, removed

    def test_a_ticked_furniture_box_over_a_silent_text_is_only_a_claim(self):
        # the owner's point, in the data: the box is ticked on listings whose text
        # names no furniture at all.
        from rental_matcher.extraction.merge import merge, text_signals
        from rental_matcher.extraction.rules import answer
        silent = [k for k, v in self.x.items() if v["inProperty"].get("includeFurniture")
                  and answer(v["description"])["furniture"]["answer"] == "not_stated"]
        self.assertIn("f8dpmv42", silent)
        for k in silent:
            v = self.x[k]
            s = merge(structured_signals({"inProperty": v["inProperty"], "additionalDetails": {"property": {"text": v["property"]}}},
                                         date(2026, 10, 20)), text_signals(answer(v["description"])))
            self.assertEqual(s["furniture"].status, SignalStatus.UNCONFIRMED, k)

    def test_yad2s_property_type_agrees_with_the_text_on_roof_apartments(self):
        roofs = {k for k, v in self.x.items() if v["property"] == "גג/ פנטהאוז"}
        self.assertEqual(len(roofs), 6)


class TestHoldoutBatch5(unittest.TestCase):
    """42 more (Bat Yam, Ramat Gan, Ramat HaSharon), fetched after v1.18.2 was
    frozen (commit 536b69e). Same fields as batch 4."""

    def test_forty_two_no_contact_data_no_names_none_seen_before(self):
        x = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(HOLDOUT5.glob("*.json"))}
        self.assertEqual(len(x), 42)
        seen = set(_extracts()) | {f.stem for d in (SECOND, HOLDOUT, HOLDOUT2, HOLDOUT3, HOLDOUT4) for f in d.glob("*.json")}
        self.assertFalse(set(x) & seen)
        for k, v in x.items():
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", json.dumps(v, ensure_ascii=False)), k)
        # an agent's full name, an agency named for a person (twice), an owner's first name: removed
        self.assertIn("ביקור - [name], שיווק", x["vpfyna4w"]["description"])
        self.assertTrue(x["5jadp0mm"]["description"].endswith("שיווק [name]-נכסים"))
        self.assertIn("צוות [name] נכסים", x["p44lnhi3"]["description"])
        self.assertIn("ואחזור - [name].", x["3tjrka1h"]["description"])


class TestHoldoutBatch6(unittest.TestCase):
    """46 more (Bat Yam, Ramat Gan, Ramat HaSharon), fetched after v1.18.5 was
    frozen (commit 8e635b2). Same fields as batch 5."""

    def test_forty_six_no_contact_data_no_names_none_seen_before(self):
        x = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(HOLDOUT6.glob("*.json"))}
        self.assertEqual(len(x), 46)
        seen = set(_extracts()) | {f.stem for d in (SECOND, HOLDOUT, HOLDOUT2, HOLDOUT3, HOLDOUT4, HOLDOUT5) for f in d.glob("*.json")}
        self.assertFalse(set(x) & seen)
        for k, v in x.items():
            self.assertIsNone(re.search(r"(?:\+?972|0)(?:[\s-]?\d){8,9}", json.dumps(v, ensure_ascii=False)), k)
        self.assertIn("[phone]", x["p8ecoqd3"]["description"])  # blanked in the browser, before it was copied
        self.assertIn("\n\n[name]-\n", x["jllfmzv4"]["description"])  # the poster's first name: removed
