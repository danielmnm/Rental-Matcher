"""
Tests for the canonical schema.

These aren't just "does it import" checks -- they verify the specific
design decisions in the Master Plan, and the fixes from two rounds of
external review, actually hold:
  - Signal is a real tagged union (unknown/confirmed/contradicted are all
    valid and distinguishable, not silently collapsed to a bool).
  - signals is genuinely open -- a brand-new preference key works with no
    schema change.
  - raw_excerpt enforces the memory-budget rule by truncating, not
    rejecting the whole record.
  - round-tripping through JSON doesn't lose or corrupt data.
  - numeric fields reject nonsensical values (zero/negative price, rooms,
    size; floor exceeding total_floors).
  - Area.neighborhood is optional, but city/id/source_listing_id reject
    empty or whitespace-only strings.
  - pulled_at requires a timezone-aware datetime.
  - phone numbers normalize to E.164, so local and international forms of
    the same number produce the same string.
  - Availability's on_date is required exactly when mode == "date".

Uses the standard-library `unittest` rather than pytest, since this
environment's network access for installing packages is intermittent and
unittest ships with Python -- a deliberate, low-dependency choice for a
project meant to be portable.
"""

import json
import random
import re
import unittest
from datetime import date, datetime, timezone

from pydantic import ValidationError

from rental_matcher.export_schema import OUTPUT_PATH, history_path, render
from rental_matcher.migrations import LATEST_VERSION
from rental_matcher.schema import (
    SCHEMA_VERSION,
    Area,
    Availability,
    AvailabilityMode,
    Contact,
    Link,
    ListedBy,
    Listing,
    ListingStatus,
    Price,
    RecurringCosts,
    Signal,
    SignalStatus,
    Source,
)


def _minimal_listing(**overrides) -> Listing:
    base = dict(
        id="yad2:abc123",
        source=Source.YAD2,
        source_listing_id="abc123",
        area=Area(city="Tel Aviv", neighborhood="City Center"),
        price=Price(amount=4500, currency="ILS"),
        pulled_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return Listing(**base)


class TestListingBasics(unittest.TestCase):
    def test_minimal_listing_is_valid(self):
        listing = _minimal_listing()
        self.assertEqual(listing.schema_version, SCHEMA_VERSION)
        self.assertEqual(listing.status, ListingStatus.CANDIDATE)

    def test_missing_required_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            Listing(source=Source.YAD2, source_listing_id="x")

    def test_schema_version_is_stamped_on_every_record(self):
        listing = _minimal_listing()
        dumped = listing.model_dump(mode="json")
        self.assertIn("schema_version", dumped)
        self.assertEqual(dumped["schema_version"], SCHEMA_VERSION)

    def test_apartment_id_defaults_to_none_until_dedup_runs(self):
        listing = _minimal_listing()
        self.assertIsNone(listing.apartment_id)
        with_dedup = _minimal_listing(apartment_id="apt:tel-aviv:citycenter:someones-phone")
        self.assertEqual(with_dedup.apartment_id, "apt:tel-aviv:citycenter:someones-phone")


class TestSignalIsARealTaggedUnion(unittest.TestCase):
    def test_distinguishes_unknown_from_false(self):
        """
        This is the actual bug the new schema fixes: the old tracker's
        `balcony: true` boolean couldn't represent "we don't know"
        separately from "confirmed absent." A Signal must be able to.
        """
        listing = _minimal_listing(signals={"balcony": Signal(status=SignalStatus.UNKNOWN)})
        self.assertEqual(listing.signals["balcony"].status, SignalStatus.UNKNOWN)
        self.assertIsNone(listing.signals["balcony"].value)

        confirmed_absent = _minimal_listing(
            signals={
                "balcony": Signal(
                    status=SignalStatus.CONFIRMED,
                    value=False,
                    evidence="Listing text says 'no balcony'",
                )
            }
        )
        self.assertIs(confirmed_absent.signals["balcony"].value, False)
        self.assertNotEqual(confirmed_absent.signals["balcony"].status, SignalStatus.UNKNOWN)

    def test_signals_map_is_open_for_arbitrary_preferences(self):
        """
        A brand-new user preference (pet_friendly) must work with zero
        schema changes -- that's the entire point of signals being a
        dict, not named fields.
        """
        listing = _minimal_listing(
            signals={
                "pet_friendly": Signal(status=SignalStatus.CONFIRMED, value=True),
                "elevator": Signal(status=SignalStatus.CONFIRMED, value=False),
            }
        )
        self.assertIs(listing.signals["pet_friendly"].value, True)
        self.assertIs(listing.signals["elevator"].value, False)


class TestRawExcerptTruncatesRatherThanRejects(unittest.TestCase):
    """A second external review flagged that hard-failing on an
    over-length raw_excerpt would abort a whole ingestion batch over one
    field. Fixed by truncating with a visible marker instead -- the
    memory bound still holds, but the cut is auditable rather than
    silently hiding whatever upstream bug produced too much text."""

    def test_a_non_string_excerpt_is_a_validation_error(self):
        # Review 11: len() on an int raised a bare TypeError, which a caller
        # catching ValidationError doesn't expect.
        for bad in (5, ["x"] * 700, {"a": 1}):
            with self.subTest(bad=type(bad).__name__), self.assertRaises(ValidationError):
                _minimal_listing(raw_excerpt=bad)

    def test_short_excerpt_is_unchanged(self):
        listing = _minimal_listing(raw_excerpt="short and fine")
        self.assertEqual(listing.raw_excerpt, "short and fine")

    def test_exactly_at_the_limit_is_unchanged(self):
        listing = _minimal_listing(raw_excerpt="x" * 600)
        self.assertEqual(listing.raw_excerpt, "x" * 600)

    def test_over_length_excerpt_is_truncated_not_rejected(self):
        listing = _minimal_listing(raw_excerpt="x" * 2000)  # e.g. a full post by mistake
        self.assertLessEqual(len(listing.raw_excerpt), 600)
        self.assertTrue(listing.raw_excerpt.endswith("[truncated]"))

    def test_json_schema_still_exports_a_max_length(self):
        # A fifth external review caught that raw_excerpt's Field() had
        # lost its max_length constraint, which doesn't change this
        # model's own (already-truncated) behavior at all -- the
        # mode="before" truncation validator above always runs first --
        # but DOES mean the exported JSON Schema carried no bound for a
        # Phase 6 consumer in another language validating raw text
        # before it ever reaches this truncation logic. Restored.
        schema = Listing.model_json_schema()
        excerpt_schema = schema["properties"]["raw_excerpt"]
        # Optional[str] with a Field constraint exports as anyOf[{string
        # branch with maxLength}, {null branch}] rather than a bare
        # maxLength key directly on the property.
        string_branch = next(
            branch for branch in excerpt_schema["anyOf"] if branch.get("type") == "string"
        )
        self.assertEqual(string_branch["maxLength"], 600)


class TestNumericConstraints(unittest.TestCase):
    """An external review caught that price/rooms/size had no positivity
    constraints -- zero or negative values silently passed before."""

    def test_zero_or_negative_price_is_rejected(self):
        with self.assertRaises(ValidationError):
            Price(amount=0)
        with self.assertRaises(ValidationError):
            Price(amount=-100)

    def test_zero_or_negative_rooms_is_rejected(self):
        with self.assertRaises(ValidationError):
            _minimal_listing(rooms=0)
        with self.assertRaises(ValidationError):
            _minimal_listing(rooms=-1)

    def test_zero_or_negative_size_is_rejected(self):
        with self.assertRaises(ValidationError):
            _minimal_listing(size_m2=0)

    def test_total_floors_must_be_positive_but_floor_itself_may_not_be(self):
        # total_floors=0 makes no sense for a building that exists
        with self.assertRaises(ValidationError):
            _minimal_listing(total_floors=0)
        # floor 0 (ground) and negative floors (basement) are real and valid
        listing = _minimal_listing(floor=0, total_floors=4)
        self.assertEqual(listing.floor, 0)
        basement = _minimal_listing(floor=-1, total_floors=4)
        self.assertEqual(basement.floor, -1)


class TestFloorWithinBuilding(unittest.TestCase):
    """A second external review caught that floor and total_floors were
    never cross-checked -- floor=8 in a 3-floor building validated
    silently, a common scraper misparse (room/building number read as
    floor). Deliberately does NOT require floor >= 0: basements are real
    and already supported -- that part of the suggested fix was a
    regression and was not applied."""

    def test_floor_exceeding_total_floors_is_rejected(self):
        with self.assertRaises(ValidationError):
            _minimal_listing(floor=8, total_floors=3)

    def test_floor_equal_to_total_floors_is_fine(self):
        listing = _minimal_listing(floor=4, total_floors=4)
        self.assertEqual(listing.floor, 4)

    def test_basement_floor_is_still_allowed(self):
        listing = _minimal_listing(floor=-1, total_floors=6)
        self.assertEqual(listing.floor, -1)

    def test_floor_without_total_floors_is_unconstrained(self):
        listing = _minimal_listing(floor=57)  # no total_floors to check against
        self.assertEqual(listing.floor, 57)


class TestIdentifierFieldsRejectBlank(unittest.TestCase):
    """A second external review caught that Area.city, Listing.id, and
    Listing.source_listing_id had no min_length, so whitespace-only
    values passed validation."""

    def test_whitespace_only_required_text_fails_the_json_schema_too(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        area = Draft202012Validator({"$defs": schema["$defs"], **schema["$defs"]["Area"]})
        self.assertFalse(area.is_valid({"city": "   "}))
        self.assertTrue(area.is_valid({"city": "Bat Yam"}))

    def test_blank_city_is_rejected(self):
        with self.assertRaises(ValidationError):
            Area(city=" ")
        with self.assertRaises(ValidationError):
            Area(city="")

    def test_blank_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            _minimal_listing(id="   ")

    def test_blank_source_listing_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            _minimal_listing(source_listing_id="")

    def test_surrounding_whitespace_is_trimmed_not_just_tolerated(self):
        area = Area(city="  Tel Aviv  ")
        self.assertEqual(area.city, "Tel Aviv")


class TestAreaIsPermissive(unittest.TestCase):
    """An external review caught that a required `neighborhood` would
    reject real listings (Facebook posts especially) that only name a
    street or nothing at all."""

    def test_neighborhood_is_optional(self):
        area = Area(city="Tel Aviv")
        self.assertIsNone(area.neighborhood)

    def test_street_and_house_number_are_available(self):
        area = Area(city="Tel Aviv", street="Levinsky", house_number="42")
        self.assertEqual(area.street, "Levinsky")
        self.assertEqual(area.house_number, "42")


class TestAreaTextFieldsCoerceBlankToNone(unittest.TestCase):
    """A fourth external review caught that 'optional' had been
    implemented as `Optional[str]` for neighborhood/street/house_number,
    not `Optional[NonEmptyStr]` -- so None correctly meant "not known,"
    but "" or " " ALSO validated as a second, unintended way of saying
    the same thing. That second spelling breaks dedup: street="" and
    street=None are the same real-world fact but not the same string,
    so exact-match comparison would treat them as different addresses.
    v1.4 fixed this by REJECTING "" outright (`Optional[NonEmptyStr]`).

    A fifth external review then caught the other side of that fix:
    rejecting "" outright hard-fails record creation for upstream JSON
    APIs/scrapers that routinely emit "" for an empty optional field, which
    isn't malformed input -- it's just another, common way of saying "not
    known." v1.5 replaces the outright rejection with a `mode="before"`
    coercion (`OptionalNonEmptyStr`) so "" and " " are silently normalized
    to None -- the single correct value -- rather than erroring. These
    tests were renamed and rewritten from "...RejectBlankNotJustNone" to
    reflect that behavior change; `street=""` is no longer a
    ValidationError, by design."""

    def test_blank_neighborhood_coerces_to_none(self):
        self.assertIsNone(Area(city="Tel Aviv", neighborhood="").neighborhood)
        self.assertIsNone(Area(city="Tel Aviv", neighborhood="   ").neighborhood)

    def test_blank_street_coerces_to_none(self):
        self.assertIsNone(Area(city="Tel Aviv", street="").street)

    def test_blank_house_number_coerces_to_none(self):
        self.assertIsNone(Area(city="Tel Aviv", house_number=" ").house_number)

    def test_none_is_still_the_correct_way_to_say_not_known(self):
        area = Area(city="Tel Aviv", neighborhood=None, street=None, house_number=None)
        self.assertIsNone(area.neighborhood)
        self.assertIsNone(area.street)
        self.assertIsNone(area.house_number)

    def test_non_blank_values_are_unaffected(self):
        area = Area(city="Tel Aviv", neighborhood="City Center", street="Levinsky", house_number="42")
        self.assertEqual(area.neighborhood, "City Center")
        self.assertEqual(area.street, "Levinsky")
        self.assertEqual(area.house_number, "42")


class TestPriceCurrencyIsARealIsoCode(unittest.TestCase):
    """A fourth external review caught that Price.currency only checked
    LENGTH (exactly 3 characters), not content -- "123" and "AAA"
    validated just as happily as "ILS". Now a Literal of real ISO 4217
    codes, which also means the exported JSON Schema gets a real
    `enum` instead of a length-only constraint another language's
    validator can't meaningfully check against."""

    def test_recognized_code_is_accepted(self):
        self.assertEqual(Price(amount=100, currency="USD").currency, "USD")

    def test_lowercase_is_normalized_not_rejected(self):
        # Convenience, not a widening of what's accepted: 'ils' means
        # the same thing as 'ILS' and shouldn't force every caller to
        # remember exact case.
        self.assertEqual(Price(amount=100, currency="ils").currency, "ILS")

    def test_digits_are_rejected(self):
        with self.assertRaises(ValidationError):
            Price(amount=100, currency="123")

    def test_three_letters_that_are_not_a_real_code_are_rejected(self):
        with self.assertRaises(ValidationError):
            Price(amount=100, currency="AAA")

    def test_json_schema_exports_a_real_enum(self):
        schema = Price.model_json_schema()
        currency_enum = schema["properties"]["currency"]["enum"]
        self.assertIn("ILS", currency_enum)
        self.assertIn("USD", currency_enum)
        self.assertNotIn("AAA", currency_enum)

    def test_iso_code_tuple_is_derived_from_the_literal_not_the_reverse(self):
        # A fifth external review caught that `Literal[_ISO_4217_CURRENCY_CODES]`
        # (a tuple VARIABLE passed into Literal[...]) works at runtime but
        # is invalid under PEP 586 for a static type checker -- confirmed
        # directly with `mypy --strict`, not just asserted. Fixed by
        # spelling the codes directly inside Literal[...] and deriving
        # the tuple FROM it via get_args(), the reverse of before. This
        # test can't run mypy itself, but it does confirm the derived
        # tuple still contains the same codes the runtime Literal checks
        # against, so the two can never drift apart silently.
        from rental_matcher.schema import _ISO_4217_CURRENCY_CODES, Currency
        from typing import get_args

        self.assertEqual(_ISO_4217_CURRENCY_CODES, get_args(Currency))
        self.assertIn("ILS", _ISO_4217_CURRENCY_CODES)
        self.assertIn("USD", _ISO_4217_CURRENCY_CODES)
        self.assertEqual(len(_ISO_4217_CURRENCY_CODES), len(set(_ISO_4217_CURRENCY_CODES)))


class TestAreaCoordinateBounds(unittest.TestCase):
    """A third external review caught that Area.lat/lng had no range
    bounds -- lat=200 or lng=-400 validated silently, even though
    neither is a coordinate that exists on Earth."""

    def test_in_range_coordinates_are_accepted(self):
        area = Area(city="Tel Aviv", lat=32.05, lng=34.77)
        self.assertEqual(area.lat, 32.05)

    def test_out_of_range_latitude_is_rejected(self):
        with self.assertRaises(ValidationError):
            Area(city="Tel Aviv", lat=200)
        with self.assertRaises(ValidationError):
            Area(city="Tel Aviv", lat=-91)

    def test_out_of_range_longitude_is_rejected(self):
        with self.assertRaises(ValidationError):
            Area(city="Tel Aviv", lng=-400)
        with self.assertRaises(ValidationError):
            Area(city="Tel Aviv", lng=181)


class TestLinkUrlValidation(unittest.TestCase):
    """A third external review caught that Link.url was a plain `str`,
    so garbage (an empty string, a bare filename) validated as a "link,"
    and the exported JSON Schema had no `format: "uri"` for another
    language's validator to check against either. Now AnyUrl."""

    def test_a_real_url_is_accepted(self):
        link = Link(label="Yad2", url="https://www.yad2.co.il/item/abc123")
        self.assertEqual(str(link.url), "https://www.yad2.co.il/item/abc123")

    def test_garbage_is_rejected(self):
        with self.assertRaises(ValidationError):
            Link(label="Yad2", url="not a url")
        with self.assertRaises(ValidationError):
            Link(label="Yad2", url="")

    def test_json_schema_exports_uri_format(self):
        schema = Listing.model_json_schema()
        link_schema = schema["$defs"]["Link"]
        self.assertEqual(link_schema["properties"]["url"]["format"], "uri")


class TestMatchScoreBounds(unittest.TestCase):
    """A third external review caught that match_score had no bounds at
    all, which left its scale undefined (a -40 or a 4000 both
    validated). Fixed with an explicit 0-100 percentage convention,
    documented on the field itself since Phase 1 is the first code that
    will actually populate it."""

    def test_in_range_score_is_accepted(self):
        listing = _minimal_listing(match_score=72.5)
        self.assertEqual(listing.match_score, 72.5)

    def test_out_of_range_score_is_rejected(self):
        with self.assertRaises(ValidationError):
            _minimal_listing(match_score=-1)
        with self.assertRaises(ValidationError):
            _minimal_listing(match_score=101)


class TestInvariantsReflectedOrDocumentedInJsonSchema(unittest.TestCase):
    """A third external review caught that the exported JSON Schema
    silently dropped two Python-only invariants, leaving a non-Python
    consumer with no way to know they existed. The fix differs per
    invariant, because they're not the same kind of constraint:
    Availability's mode/on_date rule compares a field to a literal
    constant, which standard JSON Schema CAN express (if/then/else);
    Listing's floor<=total_floors rule compares two sibling fields'
    values to each other, which it CANNOT (that needs a $data-style
    same-document reference, not in the core spec) -- so that one is
    explicitly documented via $comment instead of falsely implied to be
    enforced."""

    def test_availability_invariant_is_expressed_as_if_then_else(self):
        schema = Availability.model_json_schema()
        self.assertEqual(schema["if"]["properties"]["mode"]["const"], "date")
        self.assertIn("on_date", schema["then"]["required"])
        self.assertEqual(schema["else"]["properties"]["on_date"]["type"], "null")

    def test_floor_invariant_is_documented_as_not_portably_expressible(self):
        schema = Listing.model_json_schema()
        comment = schema.get("$comment", "")
        self.assertIn("floor", comment)
        self.assertIn("total_floors", comment)


class TestPulledAtRequiresTimezone(unittest.TestCase):
    """A naive datetime silently serializes/compares incorrectly across
    machines in different timezones -- this must be caught at validation,
    not discovered later as a scheduling bug."""

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValidationError):
            _minimal_listing(pulled_at=datetime(2026, 10, 17, 10, 0, 0))  # no tzinfo

    def test_aware_datetime_is_accepted(self):
        listing = _minimal_listing(pulled_at=datetime.now(timezone.utc))
        self.assertIsNotNone(listing.pulled_at.tzinfo)


class TestContactPhoneNormalization(unittest.TestCase):
    """A second external review caught that stripping formatting wasn't
    enough: '0541234567' and '+972541234567' are the same number but
    stayed different strings, which breaks exact-match dedup. Both now
    normalize to the same E.164 string."""

    def test_local_format_converts_to_e164(self):
        c = Contact(name="Landlord", phone="(054) 123-4567")
        self.assertEqual(c.phone, "+972541234567")

    def test_international_format_is_preserved_as_e164(self):
        c = Contact(phone="+972 54 123 4567")
        self.assertEqual(c.phone, "+972541234567")

    def test_local_and_international_forms_of_the_same_number_match(self):
        local = Contact(phone="054-123-4567")
        intl = Contact(phone="+972-54-123-4567")
        self.assertEqual(local.phone, intl.phone)

    def test_local_landline_format_converts_to_e164(self):
        # Israeli landline: trunk '0' + 8 digits (0X-XXXXXXX).
        c = Contact(phone="03-1234567")
        self.assertEqual(c.phone, "+97231234567")


class TestContactPhoneLengthValidation(unittest.TestCase):
    """A third external review caught that the v1.2 normalizer converted
    ANY '0...'-prefixed string to '+972' + the rest, with no length
    check -- so a truncated or mistyped number like '054-123' silently
    produced a plausible-looking but invalid E.164 string ('+97254123').
    A local-format number now must have exactly 9 digits after the trunk
    '0' (mobile) or 8 (landline) to be converted; anything else falls
    back to the same 'ambiguous, don't guess a country code' behavior
    already used for numbers with no leading trunk '0' at all."""

    def test_truncated_mobile_number_is_not_guessed_into_e164(self):
        c = Contact(phone="054-123")
        self.assertEqual(c.phone, "054123")
        self.assertFalse(c.phone.startswith("+"))

    def test_wrong_length_local_number_falls_back_to_cleaned_digits(self):
        c = Contact(phone="0-1-2-3-4-5")  # 6 digits, neither 8 nor 9
        self.assertEqual(c.phone, "012345")

    def test_valid_9_digit_mobile_remainder_still_converts(self):
        c = Contact(phone="0541234567")
        self.assertEqual(c.phone, "+972541234567")

    def test_valid_8_digit_landline_remainder_still_converts(self):
        c = Contact(phone="031234567")
        self.assertEqual(c.phone, "+97231234567")


class TestContactPhoneInternationalTrunkZeroBug(unittest.TestCase):
    """A fourth external review caught a real dedup-breaking bug: a
    number written as "+972-054-1234567" (country code AND the local
    trunk '0' together -- a common user mistake, but a common one)
    started with '+' and was returned completely unchanged, producing
    "+9720541234567" -- a DIFFERENT string than "+972541234567", which
    is what the exact same number normalizes to when entered in pure
    local form. That silently broke exact-match phone dedup for exactly
    the numbers most likely to appear both ways in real data."""

    def test_plus_972_with_trunk_zero_converges_with_local_form(self):
        intl_with_trunk_zero = Contact(phone="+972-054-1234567")
        local = Contact(phone="054-1234567")
        self.assertEqual(intl_with_trunk_zero.phone, local.phone)
        self.assertEqual(intl_with_trunk_zero.phone, "+972541234567")

    def test_correct_plus_972_with_no_trunk_zero_is_unaffected(self):
        # Must NOT be altered by the new check -- there's no trunk '0'
        # here to strip in the first place.
        c = Contact(phone="+972 54 123 4567")
        self.assertEqual(c.phone, "+972541234567")

    def test_plus_972_zero_with_wrong_length_remainder_is_left_alone(self):
        c = Contact(phone="+972-0-123")  # not a real number either way
        # Tightened by the fifth-review rewrite: previously this only
        # asserted the result didn't start with "+972541" (a weak check
        # that would also have passed for the old, buggy "+9720123").
        # Now asserted directly: an untrustworthy-length result never
        # masquerades as E.164 at all, regardless of which digits it has.
        self.assertFalse(c.phone.startswith("+"))
        self.assertEqual(c.phone, "9720123")

    def test_bare_plus_signs_with_no_digits_are_not_a_phone_number(self):
        """A fourth external review also caught that a standalone '+'
        (or '+++') survived as a "normalized phone number," because the
        old guard only checked for a fully EMPTY string, not a string
        with a '+' but no actual digits."""
        self.assertIsNone(Contact(phone="+++").phone)
        self.assertIsNone(Contact(phone="+").phone)
        self.assertIsNone(Contact(phone="+-+").phone)


class TestContactPhoneAdditionalCountryCodeSpellings(unittest.TestCase):
    """A fifth external review caught that the length-checked trunk-zero
    handling (above) only ever ran for the '+972' and '+972 + redundant
    0' shapes, leaving three other common real-world spellings of the
    same country code unvalidated and non-convergent with the rest:
    a truncated '+972' number with no redundant 0, a bare '972...'
    prefix with no '+' at all (as WhatsApp links commonly give it), and
    the '00' international dialing prefix ('00972...'). All three now
    go through the same national-number extraction and 8/9-digit length
    check as the other shapes."""

    def test_truncated_plus_972_without_trunk_zero_is_not_guessed_into_e164(self):
        # "+972-54-123" -- only 5 digits after the country code, no
        # redundant trunk zero to strip. Previously this fell straight
        # through to `if digits_and_plus.startswith("+"): return
        # digits_and_plus`, producing the invalid-looking-valid
        # "+97254123". Now caught by the same length check as every
        # other Israeli-country-code shape.
        c = Contact(phone="+972-54-123")
        self.assertEqual(c.phone, "97254123")
        self.assertFalse(c.phone.startswith("+"))

    def test_embedded_plus_character_does_not_survive(self):
        # A malformed input with a '+' embedded mid-string, not just
        # leading -- the old `replace("+", "", 1)`-free regex kept every
        # '+' it found, so this used to come back looking like (invalid)
        # E.164: "+972+541234567".
        # v1.6: an embedded "+" is now treated as formatting noise (like a
        # dash), not as a reason to distrust the number. v1.5's version of
        # this test only passed by coincidence -- see
        # TestPhoneNormalizationInvariant for the inputs it missed.
        c = Contact(phone="+972+541234567")
        self.assertEqual(c.phone, "+972541234567")

    def test_bare_972_prefix_with_no_plus_normalizes_to_e164(self):
        # WhatsApp links and some scrapers give the country code with no
        # '+' at all.
        c = Contact(phone="972541234567")
        self.assertEqual(c.phone, "+972541234567")

    def test_00972_international_dialing_prefix_normalizes_to_e164(self):
        c = Contact(phone="00972541234567")
        self.assertEqual(c.phone, "+972541234567")

    def test_all_five_spellings_of_the_same_number_converge(self):
        spellings = [
            "054-1234567",
            "+972-54-1234567",
            "+972-054-1234567",
            "972541234567",
            "00972541234567",
        ]
        normalized = {Contact(phone=s).phone for s in spellings}
        self.assertEqual(normalized, {"+972541234567"})


class TestAvailabilityInvariant(unittest.TestCase):
    """A second external review caught that mode=DATE with on_date=None
    passed validation -- a state that claims a date exists without
    saying what it is."""

    def test_date_mode_without_on_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            Availability(mode=AvailabilityMode.DATE, on_date=None)

    def test_date_mode_with_on_date_is_fine(self):
        a = Availability(mode=AvailabilityMode.DATE, on_date=date(2026, 12, 1))
        self.assertEqual(a.on_date, date(2026, 12, 1))

    def test_non_date_mode_with_an_on_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            Availability(mode=AvailabilityMode.IMMEDIATE, on_date=date(2026, 12, 1))

    def test_immediate_mode_with_no_date_is_fine(self):
        a = Availability(mode=AvailabilityMode.IMMEDIATE)
        self.assertIsNone(a.on_date)


class TestOptionalTextFieldsCoerceBlankToNone(unittest.TestCase):
    """A fifth external review caught that Contact.name, Listing.apartment_id,
    and Listing.pull_round still used plain `Optional[str]`, unlike Area's
    text fields -- so "" was accepted and stored as a different value than
    None, the exact gap v1.4 had already closed for Area. Fixed with the
    same `OptionalNonEmptyStr` coercion used there (not a hard rejection,
    which would hard-fail scraper ingestion whenever an upstream API sends
    "" for an empty optional field -- see schema.py's `_blank_to_none`)."""

    def test_contact_name_blank_coerces_to_none(self):
        self.assertIsNone(Contact(name="", phone=None).name)
        self.assertIsNone(Contact(name="   ", phone=None).name)
        self.assertEqual(Contact(name="Landlord", phone=None).name, "Landlord")

    def test_apartment_id_blank_coerces_to_none(self):
        listing = _minimal_listing(apartment_id="")
        self.assertIsNone(listing.apartment_id)

    def test_pull_round_blank_coerces_to_none(self):
        listing = _minimal_listing(pull_round="   ")
        self.assertIsNone(listing.pull_round)
        non_blank = _minimal_listing(pull_round="2026-09-14")
        self.assertEqual(non_blank.pull_round, "2026-09-14")


class TestNewOptionalFields(unittest.TestCase):
    def test_recurring_costs_and_availability_round_trip(self):
        listing = _minimal_listing(
            recurring_costs=RecurringCosts(arnona_monthly=350, vaad_bayit_monthly=120),
            listed_by=ListedBy.AGENCY,
            contact=Contact(name="Agent", phone="054-0000000"),
            availability=Availability(mode=AvailabilityMode.DATE, on_date=date(2026, 12, 1)),
        )
        dumped = listing.model_dump_json()
        restored = Listing.model_validate_json(dumped)
        self.assertEqual(restored.recurring_costs.arnona_monthly, 350)
        self.assertEqual(restored.listed_by, ListedBy.AGENCY)
        self.assertEqual(restored.availability.on_date, date(2026, 12, 1))

    def test_recurring_costs_rejects_negative(self):
        with self.assertRaises(ValidationError):
            RecurringCosts(arnona_monthly=-10)


class TestRoundTrip(unittest.TestCase):
    def test_round_trip_through_json_preserves_data(self):
        original = _minimal_listing(
            rooms=2.5,
            floor=3,
            size_m2=60.0,
            posted_at=date(2026, 9, 1),
            signals={"balcony": Signal(status=SignalStatus.CONFIRMED, value=True, evidence="has a balcony")},
            notes=["note one", "note two"],
        )
        dumped = original.model_dump_json()
        restored = Listing.model_validate_json(dumped)
        self.assertEqual(restored, original)


def _random_phone_like(rng: random.Random) -> str:
    """Phone-ish strings: real prefixes, wrong lengths, and the punctuation
    seen in the wild ('+' included, anywhere)."""
    prefix = rng.choice(["", "0", "+", "+972", "972", "00972", "+9720", "+1", "+44", "00", "05", "03"])
    body = "".join(rng.choice("0123456789") for _ in range(rng.randint(0, 13)))
    out = prefix + body
    for _ in range(rng.randint(0, 3)):
        i = rng.randint(0, len(out))
        out = out[:i] + rng.choice(["-", " ", "+", "(", ")", ".", "/"]) + out[i:]
    return out


_ISRAELI_E164 = re.compile(r"\+972(?:[57]\d{8}|[23489]\d{7})")


class TestPhoneNormalizationInvariant(unittest.TestCase):
    """Property tests over 20,000 generated inputs, replacing v1.5's
    example-only tests -- which each tested one reviewer-supplied input
    and missed every neighbor of it ("+972+31234567", "03+1234567",
    "+1+2125551234" all still produced a '+' mid-string)."""

    def test_output_shape_invariant(self):
        rng = random.Random(1)
        for _ in range(20_000):
            raw = _random_phone_like(rng)
            out = Contact(phone=raw).phone
            if out is None:
                # None only when there's no digit, or when something other
                # than phone punctuation sits between digits (v1.8: which
                # digits form the number would be a guess).
                digit_positions = [i for i, ch in enumerate(raw) if ch.isdigit()]
                if digit_positions and len(raw) <= 64:
                    core = raw[digit_positions[0] : digit_positions[-1] + 1]
                    ambiguous = (
                        re.search(r"[^0-9\s+\-().]", core)
                        or re.search(r"\s-\s|\.\s", core)
                        or raw.count("(") != raw.count(")")
                    )
                    self.assertTrue(ambiguous, raw)
                continue
            # Either real E.164 (a "+", then a NON-ZERO digit, 7-15 digits
            # in all) or bare untrusted digits. v1.6 checked only "+ then
            # digits", so its own generator produced 159 "+0..." outputs
            # per 20,000 inputs and the test still passed.
            self.assertRegex(out, r"^(?:\+[1-9]\d{6,14}|\d+)$", raw)
            if out.startswith("+972"):
                self.assertRegex(out, _ISRAELI_E164, raw)

    def test_text_between_digits_means_no_phone(self):
        for raw in ["Box 12, tel: 054-1234567", "Phone (x2): 054-1234567", "#1: 054-1234567", "054-1234567 / 03-1234567"]:
            with self.subTest(raw=raw):
                self.assertIsNone(Contact(phone=raw).phone)

    def test_v1_8_diff_review_cases(self):
        for raw in ["Apt #4 - 054-1234567", "1. 054-1234567", "1) 054-1234567", "1 " * 40]:
            with self.subTest(raw=raw):
                self.assertIsNone(Contact(phone=raw).phone)
        for raw in ["+(0)54-1234567", "(0)54-123-4567", "054\u20131234567", "(054) 123-4567"]:
            with self.subTest(raw=raw):
                self.assertEqual(Contact(phone=raw).phone, "+972541234567")

    def test_long_input_is_fast(self):
        # The v1.8 draft's extension regex took 48 s on this input.
        import time

        for raw in ["12345678#" * 4000, "1 " * 10000]:
            start = time.perf_counter()
            Contact(phone=raw)
            self.assertLess(time.perf_counter() - start, 0.5)

    def test_normalization_is_idempotent(self):
        # Migrations re-validate stored records, so a stored value must
        # survive a second pass unchanged.
        rng = random.Random(2)
        for _ in range(20_000):
            once = Contact(phone=_random_phone_like(rng)).phone
            self.assertEqual(Contact(phone=once).phone, once)

    def test_the_review_cases(self):
        cases = {
            "+972+31234567": "+97231234567",
            "03+1234567": "+97231234567",
            "+1+2125551234": "+12125551234",
            "054+123456": "054123456",  # 8 digits: a landline's length but a mobile prefix
            "+054-123-4567": "+972541234567",  # stray "+" on a local number
            "+00972-54-123-4567": "+972541234567",
            "0044 20 7946 0958": "+442079460958",
            "+٩٧٢٥٤١٢٣٤٥٦٧": "+972541234567",  # Arabic-Indic digits
            "+１２１２５５５１２３４": "+12125551234",  # fullwidth digits
            "\u200e+1 212 555 1234": "+12125551234",  # leading LRM bidi mark
            "+44 20 7946 0958 x12": "+442079460958",  # extension dropped, not folded in
            "+44 (0) 20 7946 0958": "+442079460958",  # bracketed trunk 0
            "(+1) 212-555-0100": "+12125550100",
            "054-1234567 שלוחה 3": "+972541234567",
            "tel: 054-1234567": "+972541234567",  # a label in front is fine
            "054-1234567 #12": "+972541234567",  # trailing extension
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(Contact(phone=raw).phone, expected)


class TestSignalValuePresentExactlyWhenConfirmed(unittest.TestCase):
    def test_confirmed_requires_a_value(self):
        with self.assertRaises(ValidationError):
            Signal(status=SignalStatus.CONFIRMED)

    def test_confirmed_false_is_how_a_stated_absence_is_recorded(self):
        self.assertIs(Signal(status=SignalStatus.CONFIRMED, value=False).value, False)

    def test_every_other_status_forbids_a_value(self):
        for status in (SignalStatus.UNKNOWN, SignalStatus.UNCONFIRMED, SignalStatus.CONFLICTING):
            with self.subTest(status=status):
                with self.assertRaises(ValidationError):
                    Signal(status=status, value=True)
                self.assertIsNone(Signal(status=status).value)

    def test_blank_evidence_is_none(self):
        self.assertIsNone(Signal(evidence="   ").evidence)


class TestSignalModelAndJsonSchemaAgree(unittest.TestCase):
    """Differential test: the value-iff-confirmed rule is implemented twice
    (Signal._value_iff_confirmed in Python, an if/then/else in the exported
    JSON Schema), so the two must accept exactly the same signals. v1.6
    had only the Python half."""

    def test_every_status_and_value_combination(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator({"$defs": schema["$defs"], **schema["$defs"]["Signal"]})
        statuses = [None, "confirmed", "unconfirmed", "conflicting", "unknown"]
        values = ["<absent>", None, True, False, 0, "x"]
        for status in statuses:
            for value in values:
                signal = {} if status is None else {"status": status}
                if value != "<absent>":
                    signal["value"] = value
                try:
                    Signal.model_validate(signal)
                    python_ok = True
                except ValidationError:
                    python_ok = False
                with self.subTest(signal=signal):
                    self.assertEqual(validator.is_valid(signal), python_ok)


class TestRemainingTextFields(unittest.TestCase):
    def test_blank_link_label_is_rejected(self):
        for label in ("", "   "):
            with self.assertRaises(ValidationError):
                Link(label=label, url="https://www.yad2.co.il/item/abc")

    def test_blank_notes_are_dropped_not_stored(self):
        listing = _minimal_listing(notes=["first", "", "   ", "second"])
        self.assertEqual(listing.notes, ["first", "second"])


class TestExportedSchemaIsNotStale(unittest.TestCase):
    """Fails if schema.py changed but `python -m rental_matcher.export_schema`
    wasn't re-run -- the check the fifth review wanted and the sixth
    review rightly pointed out was missing."""

    def test_current_schema_file_matches_the_model(self):
        self.assertEqual(OUTPUT_PATH.read_text(encoding="utf-8"), render())

    def test_current_version_snapshot_exists_and_matches(self):
        self.assertEqual(history_path(SCHEMA_VERSION).read_text(encoding="utf-8"), render())

    def test_migration_chain_ends_at_the_schema_version(self):
        self.assertEqual(LATEST_VERSION, SCHEMA_VERSION)

    def test_naive_pulled_at_fails_the_json_schema_without_format_checking(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        pulled_at = Draft202012Validator(schema["properties"]["pulled_at"])  # no format checker
        self.assertFalse(pulled_at.is_valid("2026-10-17T10:00:00"))
        self.assertTrue(pulled_at.is_valid("2026-10-17T10:00:00Z"))
        self.assertTrue(pulled_at.is_valid("2026-10-17T10:00:00+03:00"))

    def test_unknown_keys_and_infinity_are_rejected(self):
        with self.assertRaises(ValidationError):
            Price(amount=float("inf"), currency="ILS")
        with self.assertRaises(ValidationError):
            Price(amount=100, currency="ILS", typo_field=1)
        schema = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertIs(schema["additionalProperties"], False)

    def test_schema_file_is_valid_json_schema(self):
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(json.loads(OUTPUT_PATH.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
