"""
Tests for the legacy-data migration, run against the real exported data
in data/legacy_raw.json (the owner's live search, pulled from the published
tracker artifact) -- this is the "dogfood on real data" validation the
Master Plan calls for Phase 0.
"""

import json
import unittest

from rental_matcher.migrate import (
    DATA_DIR,
    LEGACY_RAW_PATH,
    _balcony_evidence,
    _parse_address,
    _parse_floor,
    _parse_rooms,
    _parse_size,
    migrate_record,
    summarize,
)
from rental_matcher.listed_by import detect_listed_by as _detect_listed_by
from rental_matcher.schema import SCHEMA_VERSION, ListedBy, Listing, SignalStatus


class TestMigration(unittest.TestCase):
    def test_legacy_raw_file_present(self):
        self.assertTrue(
            LEGACY_RAW_PATH.exists(),
            "expected data/legacy_raw.json from the live tracker export",
        )

    def test_every_legacy_record_migrates_to_a_valid_listing_at_current_version(self):
        with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
            legacy_by_area = json.load(f)

        count = 0
        for area_key, items in legacy_by_area.items():
            for item in items:
                listing = migrate_record(area_key, item)
                self.assertIsInstance(listing, Listing)
                self.assertEqual(listing.schema_version, SCHEMA_VERSION)
                count += 1

        self.assertEqual(count, 22, "expected the known 22 live listings to migrate")

    def test_balcony_signal_is_confirmed_only_when_legacy_said_so(self):
        with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
            legacy_by_area = json.load(f)

        confirmed = 0
        unknown = 0
        for area_key, items in legacy_by_area.items():
            for item in items:
                listing = migrate_record(area_key, item)
                status = listing.signals["balcony"].status
                if item.get("balcony") is True:
                    self.assertEqual(status, SignalStatus.CONFIRMED)
                    confirmed += 1
                else:
                    self.assertEqual(status, SignalStatus.UNKNOWN)
                    unknown += 1

        self.assertEqual(confirmed, 12)
        self.assertEqual(unknown, 10)

    def test_brokerage_and_costs_are_flagged_not_decided(self):
        """Since v1.12 the migration doesn't turn free text into
        `listed_by` / `recurring_costs` facts: every review found a phrasing
        that gave a wrong one (this record's "no broker (private listing)"
        once read as AGENCY). A mention becomes an UNCONFIRMED flag whose
        evidence is the listing's own words."""
        with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
            legacy_by_area = json.load(f)
        listing_by_key = {item["key"]: migrate_record(area_key, item)
                          for area_key, items in legacy_by_area.items() for item in items}

        self.assertTrue(all(l.listed_by is None and l.recurring_costs is None for l in listing_by_key.values()))
        flagged = {k for k, l in listing_by_key.items() if "brokerage_mentioned" in l.signals}
        self.assertEqual(flagged, {"ho-8raxcjyc", "ye-x5zoqq0y", "ho-2n3u1zl7"})
        private = listing_by_key["ho-8raxcjyc"].signals["brokerage_mentioned"]
        self.assertEqual(private.status, SignalStatus.UNCONFIRMED)
        self.assertIsNone(private.value)
        self.assertIn("no broker (private listing)", private.evidence)  # the reader sees what it says
        costs = listing_by_key["ho-k678s664"].signals["recurring_costs_mentioned"]
        self.assertIn("vaad bayit ₪70/mo", costs.evidence)
        self.assertEqual({k for k, l in listing_by_key.items() if "recurring_costs_mentioned" in l.signals},
                         {"ho-k678s664"})

    def test_migrated_output_file_matches_schema(self):
        output_path = DATA_DIR / "listings.json"
        self.assertTrue(output_path.exists(), "run `python -m rental_matcher.migrate` first")
        data = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 22)
        for record in data:
            listing = Listing.model_validate(record)
            self.assertEqual(listing.schema_version, SCHEMA_VERSION)


class TestAddressParsing(unittest.TestCase):
    """A third external review caught that the previous migration threw
    the legacy `addr` field away entirely and substituted a hardcoded,
    English, city-level name for every listing's neighborhood --
    flattening real sub-neighborhoods like "תל גיבורים" and "גרין ועם"
    (Holon) or "נגבה" (Ramat Gan) into just "Holon" / "Ramat Gan".
    `_parse_address` fixes this by actually reading the field. These
    cases are the exact real addresses from data/legacy_raw.json that
    make the parsing non-trivial -- not synthetic examples."""

    def test_plain_street_and_number_with_neighborhood(self):
        street, house_number, neighborhood, notes = _parse_address(
            "שדרות יד לבנים 24, יד אליהו"
        )
        self.assertEqual(street, "שדרות יד לבנים")
        self.assertEqual(house_number, "24")
        self.assertEqual(neighborhood, "יד אליהו")
        self.assertEqual(notes, [])

    def test_street_with_no_house_number(self):
        street, house_number, neighborhood, notes = _parse_address(
            "דבורה הנביאה, נגבה"
        )
        self.assertEqual(street, "דבורה הנביאה")
        self.assertIsNone(house_number)
        self.assertEqual(neighborhood, "נגבה")

    def test_neighborhood_with_an_internal_slash(self):
        street, house_number, neighborhood, notes = _parse_address(
            "חיים וייצמן, מרכז / קרית עבודה"
        )
        self.assertEqual(street, "חיים וייצמן")
        self.assertEqual(neighborhood, "מרכז / קרית עבודה")

    def test_inline_parenthetical_annotation_is_preserved_as_a_note(self):
        """rg-... : 'גבעתי (corner Dov Hoz), תל גיבורים' -- the aside is
        neither part of the street name nor the neighborhood."""
        street, house_number, neighborhood, notes = _parse_address(
            "גבעתי (corner Dov Hoz), תל גיבורים"
        )
        self.assertEqual(street, "גבעתי")
        self.assertEqual(neighborhood, "תל גיבורים")
        self.assertEqual(notes, ["Address annotation: corner Dov Hoz"])

    def test_parenthetical_annotation_containing_a_comma_is_not_split_on(self):
        """ho-2n3u1zl7: the aside itself contains a comma, which must not
        be mistaken for the street/neighborhood separator."""
        street, house_number, neighborhood, notes = _parse_address(
            "שדרות קוגל 18, גרין ועם (different unit, same building as ho-8raxcjyc)"
        )
        self.assertEqual(street, "שדרות קוגל")
        self.assertEqual(house_number, "18")
        self.assertEqual(neighborhood, "גרין ועם")
        self.assertEqual(
            notes,
            ["Address annotation: different unit, same building as ho-8raxcjyc"],
        )

    def test_address_that_is_entirely_a_parenthetical_standin_for_a_street(self):
        """rg-bf5fdfcb: '(street listed as Neve Yaakov), נגבה' -- the
        parenthetical isn't an aside on a real street name, it IS the
        only information about the street, and should not be reported
        as a literal street value with parentheses still in it."""
        street, house_number, neighborhood, notes = _parse_address(
            "(street listed as Neve Yaakov), נגבה"
        )
        self.assertIsNone(street)
        self.assertEqual(neighborhood, "נגבה")
        self.assertEqual(notes, ["Address annotation: street listed as Neve Yaakov"])

    def test_missing_address_yields_all_none(self):
        self.assertEqual(_parse_address(None), (None, None, None, []))
        self.assertEqual(_parse_address(""), (None, None, None, []))


class TestBikeCommuteTimeIsPreserved(unittest.TestCase):
    """The legacy tracker's 'bike' field (a commute-time estimate) was
    silently dropped by the previous migration -- a real loss given
    that commute-time search is this project's stated core
    differentiator. There's no structured field for it yet (that's
    Phase 1+ scope), so it's preserved as a note instead of discarded."""

    def test_bike_time_appears_as_a_note_on_a_real_record(self):
        with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
            legacy_by_area = json.load(f)
        area_key, item = next(
            (area_key, item)
            for area_key, items in legacy_by_area.items()
            for item in items
            if item["key"] == "ho-8raxcjyc"
        )
        listing = migrate_record(area_key, item)
        self.assertIn(
            f"Bike commute time (from legacy tracker): {item['bike']}",
            listing.notes,
        )


class TestNewKeywordAndPhraseAdditions(unittest.TestCase):
    """A fifth external review caught two missing entries added in this
    file alongside the regex fixes above: the plural Hebrew "brokers"
    keyword (same root cause as the plural-negation fix below --
    singular and plural Hebrew forms aren't substrings of each other),
    and Yad2's standard fee-waiver phrasing."""

    def test_plural_agency_keyword_resolves_agency(self):
        self.assertEqual(
            _detect_listed_by(["משרד מתווכים מוביל, 3 חדרים"]),
            ListedBy.AGENCY,
        )

    def test_standard_yad2_fee_waiver_phrase_resolves_agency(self):
        # Checked directly before this test was written: this phrase
        # already resolved to AGENCY via fallthrough to the bare
        # "תיווך" positive keyword -- not a live misclassification --
        # but it's now matched by an explicit rule instead of an
        # incidental keyword overlap.
        self.assertEqual(
            _detect_listed_by(["דירה להשכרה, ללא דמי תיווך, קומה 3"]),
            ListedBy.AGENCY,
        )


class TestListedByHebrewPluralBrokerNegation(unittest.TestCase):
    """A fourth external review raised 'ללא מתווכים' / 'מתווכים לא
    לפנות' as a false-positive risk, reasoning that the plural
    'מתווכים' contains 'מתווך' as a substring and so would hit the
    POSITIVE keyword check before the negation list got a chance.
    Verified directly: that's not actually true (Hebrew's final-letter
    spelling means 'מתווך', ending in the final-form ך, is NOT a
    literal substring of 'מתווכים', which uses the regular-form כ).
    The real bug was different but just as real: the plural form
    wasn't in EITHER list, so it resolved to unknown (None) instead of
    the PRIVATE signal it actually is. Fixed by adding the plural forms
    to the negation list explicitly."""

    def test_singular_is_not_a_substring_of_plural(self):
        # The exact claim from the review, checked directly rather than
        # taken on faith.
        self.assertNotIn("מתווך", "מתווכים")

    def test_plural_no_brokers_phrase_resolves_private_not_unknown(self):
        self.assertEqual(
            _detect_listed_by(["דירה יפה, ללא מתווכים, קומה 2"]),
            ListedBy.PRIVATE,
        )

    def test_brokers_dont_contact_phrase_resolves_private(self):
        self.assertEqual(
            _detect_listed_by(["דירה להשכרה, מתווכים לא לפנות בבקשה"]),
            ListedBy.PRIVATE,
        )

    def test_before_the_fix_this_phrase_was_unknown_not_misclassified(self):
        """Documents what the bug actually was, not what the review
        guessed it was: without the fix, 'ללא מתווכים' matches NEITHER
        list (confirmed: 'מתווך' isn't in it, and the plural form wasn't
        listed either), so it fell through to unknown -- not AGENCY."""
        positive_keywords = ("agency", "brokerage", "broker", "תיווך", "מתווך")
        self.assertFalse(any(k in "ללא מתווכים".lower() for k in positive_keywords))


class TestSummarizeDoesNotCrashOnMissingNeighborhood(unittest.TestCase):
    """A fourth external review caught that main()'s original inline
    `sorted(by_area.items())` crashes with TypeError the moment any
    listing has neighborhood=None -- which can't happen in the current
    22-listing dataset, but Area.neighborhood is Optional BY DESIGN
    (Facebook posts often omit one), so this was a live crash waiting
    for exactly the kind of record this schema exists to accept."""

    def test_summarize_handles_a_listing_with_no_neighborhood(self):
        with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
            legacy_by_area = json.load(f)
        migrated = [
            migrate_record(area_key, item)
            for area_key, items in legacy_by_area.items()
            for item in items
        ]
        no_neighborhood = migrated[0].model_copy(deep=True)
        no_neighborhood.area.neighborhood = None
        migrated_with_gap = migrated + [no_neighborhood]
        # Must not raise -- this is the actual regression test; the
        # exact formatting is secondary to "doesn't crash."
        output = summarize(migrated_with_gap)
        self.assertIn("(no neighborhood)", output)


class TestListedByFeeWaiverIsNotMisreadAsPrivate(unittest.TestCase):
    """A third external review raised a real ambiguity the v1.2
    negation check doesn't resolve: 'ללא עמלת תיווך' / '0% עמלה' /
    'no agency fee' all describe a fee waived to the TENANT -- the
    agency is still involved, it just isn't charging the renter for it.
    That's AGENCY, not PRIVATE, even though the phrase contains
    negation-adjacent wording. Not present in the live 22-listing
    dataset (confirmed by inspection), so these are constructed
    examples exercising a classification rule that was a real gap in
    the logic regardless."""

    def test_hebrew_fee_waiver_phrase_is_agency_not_private(self):
        self.assertEqual(
            _detect_listed_by(["דירה יפה, ללא עמלת תיווך, קרוב לתחבורה"]),
            ListedBy.AGENCY,
        )

    def test_percent_fee_phrase_is_agency(self):
        self.assertEqual(
            _detect_listed_by(["Agency-managed, 0% עמלה this month only"]),
            ListedBy.AGENCY,
        )

    def test_english_no_agency_fee_phrase_is_agency(self):
        self.assertEqual(
            _detect_listed_by(["Nice apartment, no agency fee for this listing"]),
            ListedBy.AGENCY,
        )

    def test_genuine_no_broker_negation_is_still_private(self):
        """Make sure the fee-waiver check, checked first, didn't break
        the actual no-broker-at-all case the second review already
        fixed."""
        self.assertEqual(
            _detect_listed_by(["no broker (private listing), 10 photos"]),
            ListedBy.PRIVATE,
        )


class TestNumericFieldParsersNeverCrash(unittest.TestCase):
    """v1.0's "[\\d.]+" matched a lone "." in "approx. 65 m²" and float(".")
    raised -- untested for six versions because every test used the real
    data's clean "65 m²" values."""

    def test_review_cases(self):
        self.assertEqual(_parse_size("approx. 65 m²"), 65.0)
        self.assertEqual(_parse_rooms("ca. 3 rooms"), 3.0)
        self.assertIsNone(_parse_rooms("..."))

    def test_arbitrary_text_never_raises(self):
        import random

        rng = random.Random(3)
        alphabet = "0123456789.,- abc~חדרמ\"²/"
        for _ in range(10_000):
            raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
            for parse in (_parse_rooms, _parse_size):
                result = parse(raw)
                self.assertTrue(result is None or result >= 0, (raw, result))


class TestFieldParsersAreConfidentOrSilent(unittest.TestCase):
    """Found by an independent review in v1.7: each returned a wrong number
    rather than None on ordinary messy input."""

    def test_rooms(self):
        self.assertEqual(_parse_rooms("2½ rooms"), 2.5)
        self.assertIsNone(_parse_rooms("3,5 חדרים"))  # was 3.0: decimal comma is ambiguous
        self.assertIsNone(_parse_rooms("0 rooms"))  # was 0.0, which Listing rejects (rooms > 0)

    def test_size(self):
        self.assertEqual(_parse_size("m2: 65"), 65.0)  # was 2.0, the "2" in "m2"
        self.assertIsNone(_parse_size("2 rooms, 65 m²"))  # was 2.0
        self.assertIsNone(_parse_size("1,200 sqft"))  # was 1.0; also a different unit
        self.assertEqual(_parse_size("1,200 m²"), 1200.0)

    def test_floor(self):
        self.assertEqual(_parse_floor(0), 0)  # ground floor, not "missing"
        self.assertIsNone(_parse_floor("Floor 2 of 5"))

    def test_eighth_review_parser_cases(self):
        self.assertEqual(_parse_rooms(3), 3.0)  # numeric legacy values
        self.assertEqual(_parse_size(65), 65.0)
        self.assertIsNone(_parse_rooms(True))
        with self.assertRaises(ValueError):
            migrate_record("nowhere", {"key": "x-1", "price": 4000})
        with self.assertRaises(ValueError):
            migrate_record("holon", {"key": "x-1", "price": None})
        listing = migrate_record("holon", {"key": "x-1", "price": "4,500", "posted": "10/08/25"})
        self.assertEqual(listing.price.amount, 4500.0)
        self.assertIsNone(listing.posted_at)  # day-first vs month-first: not guessed
        self.assertIn("Posted date (unparsed, from legacy tracker): 10/08/25", listing.notes)

    def test_price_is_confident_or_silent(self):
        from rental_matcher.migrate import _parse_price

        for raw in ["5k", "3.5k", "-5000", "5.500", "$1,500", "1,500 USD", [5000], {"amount": 5000}, 10**400, float("inf")]:
            with self.subTest(raw=raw):
                self.assertIsNone(_parse_price(raw))
        for raw in ["4,500", "₪4,500", "4500 ש\"ח", 4500]:
            with self.subTest(raw=raw):
                self.assertEqual(_parse_price(raw), 4500.0)

    def test_second_review_parser_cases(self):
        self.assertEqual(_parse_floor("מינוס 1"), -1)
        # Review 11: "ה-2" ("the 2nd") and "ב-3" ("on the 3rd") read as -2/-3.
        self.assertIsNone(_parse_floor("קומה ה-2"))
        self.assertIsNone(_parse_floor("ב-3"))
        self.assertIsNone(_parse_floor("ב־3"))  # maqaf
        # ...without breaking "במינוס 1" ("in minus 1"), which a first
        # version of that fix did.
        self.assertEqual(_parse_floor("במינוס 1"), -1)
        self.assertEqual(_parse_floor("קומה במינוס 2"), -2)
        self.assertEqual(_parse_floor("-2"), -2)
        self.assertEqual(_parse_floor("\u22121"), -1)  # Unicode minus
        self.assertIsNone(_parse_floor("B1"))
        self.assertIsNone(_parse_floor(3.7))
        self.assertIsNone(_parse_size("65 ft²"))
        self.assertEqual(_parse_rooms("½"), 0.5)
        self.assertEqual(_parse_address("הרצל 12 דירה 4, נווה צדק")[:3], ("הרצל", "12", "נווה צדק"))
        self.assertIsNone(_parse_address("הרצל 12, דירה 4")[2])

    def test_address_middle_parts_are_not_the_neighborhood(self):
        street, number, neighborhood, notes = _parse_address("הרצל 12, דירה 4, נווה צדק")
        self.assertEqual((street, number, neighborhood), ("הרצל", "12", "נווה צדק"))
        self.assertEqual(notes, ["Address detail: דירה 4"])
        self.assertIsNone(_parse_address("הרצל 12, משהו, נווה צדק")[2])


class TestBalconyEvidenceInHebrew(unittest.TestCase):
    def test_hebrew_word_alone_is_enough(self):
        self.assertEqual(_balcony_evidence(["קומה 2", "מרפסת גדולה"]), "מרפסת גדולה")

    def test_no_mention_gives_no_evidence(self):
        self.assertIsNone(_balcony_evidence(["קומה 2", "no parking"]))


if __name__ == "__main__":
    unittest.main()
