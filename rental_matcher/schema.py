"""
Canonical data model for the rental-matching tool.

Design rationale (see the Master Plan doc, "Phase 0 Deep Dive" section, for
the full writeup):

- `Listing` is a product type (plain record): every field on it is one a
  listing either has or doesn't, with no ambiguity about what it means.
  Fields that are deterministic (price, rooms, floor, size, dates) live
  here directly.

- `Signal[T]` is a sum type (tagged union) used for anything extracted by
  reading free text (does this post mention a balcony? does it exclude
  couples?). These are never simply true/false -- they carry a confidence
  state, and that state is a first-class value instead of being silently
  rounded away.

- `Listing.signals` is an open map (`dict[str, Signal]`), not named fields
  (`balcony`, `bike_storage`, ...). A second user with entirely different
  preferences (pet_friendly, elevator, parking) adds a new signal key at
  the data layer; the schema itself never changes for a new preference.
  Tradeoff, stated plainly: because `signals` is heterogeneous (a balcony
  signal's value is a bool, a notice-period signal's value might be an
  int), `Signal.value` can't be given a precise type in the *stored*
  schema without re-introducing named fields and defeating the point.
  `listing.schema.json` will therefore show `value` as loosely typed.
  That's intentional here, not a bug -- the fix is a step later: when the
  verification pipeline (Phase 2) asks an LLM for structured output on a
  *specific* check ("does this mention a balcony?"), that call gets its
  own narrowly-typed response schema (e.g. `{status, value: bool,
  evidence}`), not the generic `Signal[Any]`. The open map is for storage;
  narrow schemas are for extraction.

- `schema_version` is carried on every record so a future breaking change
  is a migration function applied to old records (see `migrations.py`),
  not a rewrite that invalidates them. v1.1 is itself the first proof of
  this: it adds several real-world fields an external review caught
  missing from v1.0 (street/house number, contact info, total floors,
  recurring costs, broker flag, availability, and a separate
  `apartment_id` for cross-platform deduplication) without breaking any
  v1.0 record, because every new field is optional.

Portability: this module is the single source of truth. `export_schema.py`
derives a JSON Schema from it, so any other language/stack (a Phase 6
backend, or a browser-extension frontend calling it over HTTP, say) can
validate against the exact same contract without re-deriving it by hand.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from enum import Enum
from typing import Annotated, Generic, Literal, Optional, TypeVar, get_args

from pydantic import (
    AnyUrl,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.9"

T = TypeVar("T")

# A non-empty, whitespace-trimmed string -- strips first, THEN checks
# min_length, so a value that's whitespace-only (" ") becomes "" and is
# rejected rather than silently accepted. Used for identifier/name fields
# where an empty string is never meaningful (as opposed to None, which
# means "not known" and is a different, valid state).
# The `\S` pattern repeats "non-blank" for the exported JSON Schema: the
# model strips whitespace before checking min_length, but a JSON Schema
# validator can't strip, so " " passed minLength=1 there.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"\S")]


def _blank_to_none(v: object) -> object:
    """A mode='before' coercion, for OPTIONAL text fields only: a blank
    or whitespace-only string is treated the same as an absent value,
    converted to None before NonEmptyStr's own min_length check would
    otherwise reject it outright.

    A fifth external review caught the real tension this resolves:
    v1.4 made Area.neighborhood/street/house_number `Optional[NonEmptyStr]`
    specifically so "" could never be stored as a DIFFERENT way of saying
    "not known" than None (that's what broke dedup). But upstream JSON
    APIs and scrapers routinely emit "" for an empty optional field --
    without this, that ordinary, expected input would hard-fail record
    creation instead of being treated as "not known," which is what it
    actually means. This coercion runs first, so by the time NonEmptyStr
    sees the value, it's either None already or a real, non-blank string
    -- the min_length=1 check never actually has blank input to reject.

    Deliberately NOT folded into `NonEmptyStr` itself: that type is also
    used for REQUIRED fields (e.g. `Area.city`), where a blank input has
    no "not known" to coerce into -- there, rejecting it loudly is the
    correct behavior, not something to silently paper over.
    """
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


# Use this instead of a bare `Optional[NonEmptyStr]` for any optional
# free-text field (an address component, a name, an opaque id) where the
# source data might legitimately send "" to mean "we don't have one" --
# which, empirically, is most of them. See `_blank_to_none` above.
OptionalNonEmptyStr = Annotated[Optional[NonEmptyStr], BeforeValidator(_blank_to_none)]


def _drop_blank_items(v: object) -> object:
    """Same reasoning as _blank_to_none, for a list of free-text notes: a
    blank entry carries no information, so it's dropped rather than either
    stored or allowed to fail the whole record."""
    if isinstance(v, list):
        return [item for item in v if not (isinstance(item, str) and item.strip() == "")]
    return v


NotesList = Annotated[list[NonEmptyStr], BeforeValidator(_drop_blank_items)]

# The active ISO 4217 currency codes this tool is likely to actually see.
# A fourth external review caught that Price.currency only constrained
# LENGTH (3 characters), not content -- "123" or "AAA" validated as
# happily as "ILS". This is deliberately a Literal, not a regex like
# `^[A-Z]{3}$`: a regex would still accept nonsense 3-letter strings that
# merely look like a currency code (the exact complaint), while a
# Literal both rejects anything not on the list AND exports as a proper
# `enum` in the generated JSON Schema, instead of a validator function
# another language's tooling has no way to see. Not claimed to be
# complete -- a real but not-yet-seen currency can be added here when it
# comes up, the same way a new Source gets added to that enum.
#
# The values are spelled out directly inside Literal[...] rather than
# built from a separate tuple constant passed in by variable -- a fifth
# external review caught that `Literal[some_tuple_variable]` works at
# RUNTIME (Pydantic reads it the same either way) but is invalid under
# PEP 586 for a static type checker: confirmed directly by running mypy
# against both forms, not just asserted -- `Literal[_A_TUPLE_VAR]` fails
# with "Parameter 1 of Literal[...] is invalid" under `mypy --strict`,
# while this form passes clean. `_ISO_4217_CURRENCY_CODES` is derived
# FROM the Literal via `get_args`, not the other way around, specifically
# so there's exactly one place (this Literal) that has to stay correct.
Currency = Literal[
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY",
    "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP",
    "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD",
    "GNF", "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR", "ILS", "INR",
    "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF",
    "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL",
    "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR",
    "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR",
    "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR",
    "RON", "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD",
    "SHP", "SLE", "SOS", "SRD", "SSP", "STN", "SYP", "SZL", "THB", "TJS",
    "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX", "USD",
    "UYU", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF", "XPF",
    "YER", "ZAR", "ZMW", "ZWL",
]
_ISO_4217_CURRENCY_CODES = get_args(Currency)


class _StrictModel(BaseModel):
    """Base for every model here. extra="forbid": an unknown key is an
    error, not silently dropped (the last migration step round-trips
    records through the model, and was losing unknown keys). The exported
    JSON Schema says the same with additionalProperties: false.
    allow_inf_nan=False: inf/NaN aren't valid JSON, and "price: inf" isn't
    a price."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SignalStatus(str, Enum):
    """How confident we are in a fact extracted from a listing.

    The status says how sure we are; `Signal.value` says what the fact
    IS. "The listing says there's no balcony" is CONFIRMED with
    value=False, not some separate negative status. Whether that's good
    or bad for a given renter is the scoring engine's call, never the
    signal's -- the same listing is scored for many different users.

    - CONFIRMED: the listing clearly states the value. `value` required.
    - UNCONFIRMED: there's a hint, but not enough to commit to a value
      (a "suitable for roommates" tag the description doesn't back up).
    - CONFLICTING: the listing contradicts itself (the features list
      says balcony, the description says none). No single value.
    - UNKNOWN: nothing in the listing addresses it.

    Only CONFIRMED carries a value; the validator on Signal enforces it.
    CONFLICTING replaced v1.5's CONTRADICTED, which the tests themselves
    used with two incompatible meanings (once with no value as "the
    listing says no", once with value=False) -- see migrations.py.
    """

    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class ExtractedBy(str, Enum):
    RULE = "rule"
    LLM = "llm"
    MANUAL = "manual"


def _signal_json_schema_extra(schema: dict, model: type) -> None:
    """Export the value-iff-CONFIRMED invariant (enforced by
    Signal._value_iff_confirmed) so a non-Python validator enforces it too.
    A missing status means UNKNOWN (the default), so it falls to `else`."""
    schema["if"] = {"properties": {"status": {"const": "confirmed"}}, "required": ["status"]}
    schema["then"] = {"properties": {"value": {"not": {"type": "null"}}}, "required": ["value"]}
    schema["else"] = {"properties": {"value": {"type": "null"}}}


class Signal(_StrictModel, Generic[T]):
    """
    A tagged union representing one fact extracted from a listing's free
    text (balcony mention, roommate-exclusion language, bike storage, ...).

    `status` is the tag (see SignalStatus for what each one means).
    `value` is present exactly when status is CONFIRMED.
    """

    status: SignalStatus = SignalStatus.UNKNOWN
    value: Optional[T] = None
    evidence: OptionalNonEmptyStr = Field(
        default=None,
        description="Short quote or excerpt supporting this signal's status.",
    )
    extracted_by: Optional[ExtractedBy] = None
    checked_at: Optional[date] = None

    model_config = ConfigDict(frozen=False, json_schema_extra=_signal_json_schema_extra)

    @model_validator(mode="after")
    def _value_iff_confirmed(self) -> "Signal[T]":
        if self.status == SignalStatus.CONFIRMED and self.value is None:
            raise ValueError("a CONFIRMED signal must say what was confirmed (value is required)")
        if self.status != SignalStatus.CONFIRMED and self.value is not None:
            raise ValueError(
                f"only a CONFIRMED signal carries a value; got status={self.status.value!r} "
                f"with value={self.value!r}"
            )
        return self


class Source(str, Enum):
    YAD2 = "yad2"
    FACEBOOK = "facebook"
    KOMO = "komo"
    MADLAN = "madlan"
    THE_FINDER = "the_finder"
    OTHER = "other"


class ListingStatus(str, Enum):
    CANDIDATE = "candidate"
    EXCLUDED = "excluded"
    CONTACTED = "contacted"
    REJECTED = "rejected"
    SECURED = "secured"


class ListedBy(str, Enum):
    """Whether the listing comes from the owner directly or an agency.

    Usually a structured fact the source platform states outright (Yad2
    marks this explicitly); where it's only inferable from free text,
    treat it as a `Signal` under `signals["listed_by"]` instead of forcing
    it in here -- this field is for the cases we're confident about.

    Deliberately NOT extended with SUBLET / LEASE_TRANSFER members, even
    though a fourth external review correctly pointed out that a sublet
    (סאבלט) or a lease transfer (מחליף/ה) fits neither PRIVATE nor
    AGENCY cleanly. The review's diagnosis was right; its implied fix
    (add more values to this enum) would have been wrong, because
    "who is listing it" (private person vs. agency) and "what kind of
    tenancy is being offered" (a fresh lease vs. a sublet vs. a lease
    transfer) are two independent facts, not one -- a sublet is
    typically posted by a private individual, so it's PRIVATE *and* a
    sublet, not a third option that can't also be private. Collapsing
    them into one field would make it impossible to represent that
    combination at all. The right place for "is this a sublet" is
    `signals["sublet"]` (or `signals["lease_transfer"]`) -- which needs
    NO schema change, because `signals` was already designed in Phase 0
    to be an open map for exactly this kind of free-text-derived fact.
    No detection rule is added for it yet, on the same "verify against
    real data before writing a rule" standard as everything else in
    migrate.py: the live 22-listing dataset has no sublet or
    lease-transfer example to check a rule against."""

    PRIVATE = "private"
    AGENCY = "agency"


class AvailabilityMode(str, Enum):
    IMMEDIATE = "immediate"
    FLEXIBLE = "flexible"
    DATE = "date"


def _availability_json_schema_extra(schema: dict, model: type["Availability"]) -> None:
    """
    Pydantic's `model_validator` below enforces the mode/on_date invariant
    at the Python layer, but a non-Python consumer of `listing.schema.json`
    (Phase 6, or any tool validating records in another language) only
    sees the exported JSON Schema -- and plain per-field constraints can't
    express "on_date is required iff mode == 'date'" on their own. Unlike
    `Listing.floor <= total_floors` below (a genuine cross-field
    comparison), THIS invariant only compares a field to a literal
    constant, which standard JSON Schema (draft 2020-12) can express with
    a conditional subschema -- so it belongs here, not in the "can't be
    done portably" bucket.
    """
    schema["if"] = {"properties": {"mode": {"const": "date"}}, "required": ["mode"]}
    schema["then"] = {
        "properties": {"on_date": {"type": "string", "format": "date"}},
        "required": ["on_date"],
    }
    schema["else"] = {"properties": {"on_date": {"type": "null"}}}


class Availability(_StrictModel):
    model_config = ConfigDict(json_schema_extra=_availability_json_schema_extra)

    mode: AvailabilityMode
    on_date: Optional[date] = Field(
        default=None,
        description=(
            "Required when mode == DATE, forbidden otherwise (enforced "
            "below, and reflected in the exported JSON Schema via an "
            "if/then/else block -- see _availability_json_schema_extra) "
            "-- without that invariant, mode=DATE with on_date=None is a "
            "state that claims a specific date exists without saying "
            "what it is. Named on_date rather than `date` to avoid "
            "shadowing the `date` type within this class's own annotations."
        ),
    )

    @model_validator(mode="after")
    def _on_date_matches_mode(self) -> "Availability":
        if self.mode == AvailabilityMode.DATE and self.on_date is None:
            raise ValueError("Availability.on_date is required when mode is 'date'")
        if self.mode != AvailabilityMode.DATE and self.on_date is not None:
            raise ValueError(
                f"Availability.on_date must be unset when mode is {self.mode.value!r}, "
                "not a date that the mode doesn't claim to have"
            )
        return self


class Price(_StrictModel):
    amount: float = Field(gt=0)
    currency: Currency = "ILS"

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency_case(cls, v: object) -> object:
        """Convenience only: 'ils' and 'ILS' obviously mean the same
        thing, so this uppercases/trims before the Literal check runs,
        rather than making every caller remember to pass exact case.
        Doesn't widen what's accepted -- 'xyz' still gets rejected, now
        as 'XYZ', by the Literal below either way."""
        if isinstance(v, str):
            return v.strip().upper()
        return v


class RecurringCosts(_StrictModel):
    """Secondary monthly costs on top of base rent. Omitted entirely
    (left as None on Listing) rather than zero-filled when unknown --
    zero would wrongly assert "no arnona," which is never true in
    practice and would distort a true-monthly-cost calculation."""

    arnona_monthly: Optional[float] = Field(default=None, ge=0)
    vaad_bayit_monthly: Optional[float] = Field(default=None, ge=0)
    # v1.59 (owner ruling): when the ad's text and Yad2's field give different amounts, the card shows a range:
    # the *_monthly above is the lower one, this is the higher one.
    arnona_monthly_max: Optional[float] = Field(default=None, ge=0)
    vaad_bayit_monthly_max: Optional[float] = Field(default=None, ge=0)


def _is_israeli_national_number(national: str) -> bool:
    """Israeli national numbers (after +972 / the trunk 0): mobile (5X) and
    VoIP (7X) numbers have 9 digits, landlines (2, 3, 4, 8, 9) have 8. A
    length check alone isn't enough -- "054-123456" has a landline's 8
    digits but a mobile prefix, so it's a truncated mobile, not a number."""
    if national[:1] in ("5", "7"):
        return len(national) == 9
    if national[:1] in ("2", "3", "4", "8", "9"):
        return len(national) == 8
    return False


_PHONE_MAX_LEN = 64
_TRAILING_EXTENSION_RE = re.compile(r"(?i)\s*(?:\b(?:ext|extension|x)\.?|שלוחה|#)\s*\d{1,6}\s*$")


def normalize_phone(v: Optional[str]) -> Optional[str]:
    """Normalize to E.164 when the number can be trusted, else to bare
    digits. Output invariant (property-tested in tests/test_schema.py):
    None (no digits; more than 64 characters; or something other than
    phone punctuation between digits -- text, a spaced dash, ". ", or an
    unbalanced bracket -- so which digits form the number would be a
    guess); or valid-shaped
    E.164 ("+", a non-zero digit, 7-15 digits in
    all), with "+972..." always carrying a national number of the right
    length for its prefix; or, when the number can't be trusted, bare
    digits with no "+" at all.

    Works on DIGITS ONLY, plus one bit of information: whether the
    input began with "+". An earlier version kept every "+" through
    the whole function and measured len() on strings that could still
    contain one, so "+972+31234567" passed an 8/9-length check with a
    "+" inside the national number.
    """
    if v is None:
        return v
    # Unicode digits (Arabic-Indic "٠٥٤", fullwidth "０５４") become ASCII,
    # and invisible bidi marks are dropped, BEFORE anything else: Python's
    # \d matches every script's digits, so "+٩٧٢..." used to pass straight
    # through as "valid" E.164, and a leading LRM hid the "+".
    v = "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in v)
    v = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", v)
    # A phone field holding a pasted paragraph is not a phone number; the
    # cap also keeps every step below cheap.
    if len(v) > _PHONE_MAX_LEN:
        return None
    # Typographic hyphens (en dash, non-breaking hyphen, minus) are hyphens.
    v = re.sub(r"[\u2010-\u2015\u2212\u00ad]", "-", v)
    # A trailing extension ("... x12", "ext. 12", "שלוחה 12", "#12") isn't
    # part of the number -- but only when it FOLLOWS a full number (7+
    # digits). Done with an end-anchored match plus a digit count, not one
    # big backtracking regex (that version was quadratic on long input).
    ext = _TRAILING_EXTENSION_RE.search(v)
    if ext and sum(ch.isdigit() for ch in v[: ext.start()]) >= 7:
        v = v[: ext.start()]
    # Only the stretch from the first digit to the last is the number; a
    # label in front ("tel: ", "טל: ") is ignored. If anything other than
    # phone punctuation sits BETWEEN digits ("Box 12, tel: 054...", "05/631",
    # "054-1234567 / 03-1234567"), which digits form the number is a guess,
    # so there is no phone value at all. (Returning those digits as
    # "untrusted" broke idempotence: they can happen to form a valid local
    # number that a second pass then trusts.)
    # "+44 (0) 20 ..." writes the national trunk 0 in brackets; it's
    # dropped when dialing internationally, so it isn't part of E.164.
    v = re.sub(r"(?<=\d)\s*\(\s*0\s*\)", "", v)  # only after digits: "+(0)54..." is a stray "+"
    first = re.search(r"[0-9]", v)
    if first is None:
        return None
    last = max(i for i, ch in enumerate(v) if ch.isascii() and ch.isdigit())
    core = v[first.start() : last + 1]
    # Also not phone punctuation: a spaced dash or ". " between digit groups
    # ("Apt #4 - 054...", "1. 054..."), or an unmatched bracket ("1) 054").
    if (
        re.search(r"[^0-9\s+\-().]", core)
        or re.search(r"\s-\s|\.\s", core)
        or v.count("(") != v.count(")")
    ):
        return None
    digits = re.sub(r"[^0-9]", "", core)
    # No country code starts with 0, so a "+" in front of a 0 is a stray
    # mark on a local ("+054...") or 00-prefixed ("+00972...") number,
    # not the start of an international one.
    has_leading_plus = re.search(r"\+[\s(]*$", v[: first.start()]) is not None and not digits.startswith("0")

    national: Optional[str] = None
    if has_leading_plus and digits.startswith("972"):
        national = digits[3:]
    elif not has_leading_plus and digits.startswith("00972"):
        national = digits[5:]
    elif not has_leading_plus and digits.startswith("972"):
        national = digits[3:]

    if national is not None:
        # "+972-054-..." (country code plus the local trunk 0) is a
        # common mistake; E.164 has no trunk prefix.
        if national.startswith("0"):
            national = national[1:]
        return "+972" + national if _is_israeli_national_number(national) else digits

    if not has_leading_plus and digits.startswith("00"):
        # "00" is the international dialing prefix from Israel.
        international = digits[2:]
        if 7 <= len(international) <= 15 and not international.startswith("0"):
            return "+" + international
        return digits

    if not has_leading_plus and digits.startswith("0"):
        rest = digits[1:]
        return "+972" + rest if _is_israeli_national_number(rest) else digits

    if has_leading_plus and 7 <= len(digits) <= 15:
        # A non-Israeli international number. E.164: 7-15 digits, and
        # the first can't be 0 (guaranteed above).
        return "+" + digits
    return digits


class Contact(_StrictModel):
    name: OptionalNonEmptyStr = None
    phone: Optional[str] = Field(
        default=None,
        description=(
            "Normalized to E.164 on input (e.g. both '054-123-4567' and "
            "'+972 54 123 4567' become '+972541234567') -- this is the "
            "primary anchor for cross-platform deduplication, so two "
            "representations of the same number must produce the exact "
            "same string, not just similar-looking ones. Currently assumes "
            "an Israeli local number when no country code is present "
            "(leading '0' -> '+972'), since that's the only market this "
            "tool operates in today; a non-Israeli number with no '+' is "
            "ambiguous and is returned digits-only rather than guessed. A "
            "third external review caught that this used to skip length "
            "validation entirely, so a truncated/mistyped number like "
            "'054-123' silently produced a plausible-looking but invalid "
            "'+97254123' -- it now requires exactly 9 digits after the "
            "trunk '0' for a mobile number (05X-XXXXXXX) or 8 for a "
            "landline (0X-XXXXXXX), falling back to the 'ambiguous, don't "
            "guess' branch otherwise, same as a number with no leading 0. "
            "A fifth external review caught that this length check was "
            "only ever wired up for the bare-local and '+972 + redundant "
            "0' shapes, leaving THREE other common real-world shapes "
            "unvalidated and un-converged: a truncated '+972' number with "
            "no redundant 0 ('+972-54-123'), a bare country code with no "
            "'+' at all ('972541234567', as WhatsApp links commonly give "
            "it), and the '00' international dialing prefix "
            "('00972541234567'). All three now go through the same "
            "national-number extraction and 8/9-digit length check as "
            "the other two shapes, so all five spellings of the same "
            "number converge on one E.164 string."
        ),
    )

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, v: Optional[str]) -> Optional[str]:
        return normalize_phone(v)


class Area(_StrictModel):
    city: NonEmptyStr
    neighborhood: OptionalNonEmptyStr = Field(
        default=None,
        description=(
            "Optional: Facebook Marketplace and some Yad2 posts give only "
            "a street or a city, no named neighborhood. Required-by-default "
            "here would reject real, otherwise-usable listings. A fourth "
            "external review caught that 'optional' had been implemented "
            "as 'Optional[str]', not 'optional NonEmptyStr' -- so None "
            "correctly meant 'not known', but '' or ' ' also validated, "
            "silently meaning the same thing as None through a second, "
            "unintended spelling. That second spelling is what breaks "
            "dedup: street='' and street=None are the same real-world "
            "fact ('we don't have one') but are NOT the same string, so "
            "exact-match comparison treats them as different addresses. "
            "A fifth external review then caught the other side of that "
            "fix: plain NonEmptyStr REJECTS '' outright rather than "
            "coercing it, which is right for a required field but wrong "
            "here, since upstream JSON APIs routinely send '' for an "
            "empty optional field -- that's now handled by "
            "OptionalNonEmptyStr (see its definition above)."
        ),
    )
    street: OptionalNonEmptyStr = None
    house_number: OptionalNonEmptyStr = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class Link(_StrictModel):
    label: NonEmptyStr
    url: AnyUrl = Field(
        description=(
            "A real URI, not just any string -- a third external review "
            "caught that a plain `str` here both accepts garbage (empty "
            "string, a bare filename) and exports as an untyped JSON "
            "Schema string with no `format: \"uri\"` for another "
            "language's validator to check against. `AnyUrl` fixes both."
        ),
    )


_RAW_EXCERPT_MAX = 600
_RAW_EXCERPT_TRUNCATION_MARKER = " …[truncated]"


class Listing(_StrictModel):
    """The canonical record for one rental listing, from any source, in
    any city. Nothing in this model may refer to a specific user's
    preferences (no `balcony: bool` field, for instance) -- preference
    facts live in `signals`, keyed by whatever preference a given user
    cares about.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "$comment": (
                "This model also enforces floor <= total_floors (see "
                "_floor_within_building below), but that invariant is NOT "
                "reflected anywhere else in this schema. Unlike "
                "Availability's mode/on_date invariant above, this one "
                "compares two sibling fields' VALUES to each other, not a "
                "field to a literal constant -- expressing that in "
                "standard JSON Schema would need a $data-style "
                "same-document reference, which draft 2020-12 (the draft "
                "this schema targets) does not include in its core spec. "
                "A consumer validating records in another language must "
                "re-implement this specific check itself; this comment "
                "exists so that requirement is visible in the schema "
                "artifact itself, not only in this file's Python source. "
                "FORMATS: validate with format checking ON for 'date', "
                "'date-time' and 'uri' -- most JSON Schema libraries treat "
                "`format` as a no-op annotation by default, and Python's "
                "jsonschema only checks 'date-time'/'uri' when optional "
                "packages are installed. pulled_at also carries a pattern "
                "requiring a timezone offset, so a naive timestamp fails "
                "even without format checking. For URLs, this Python model "
                "(Pydantic AnyUrl) is the reference; RFC 3987 checkers "
                "differ from it at the edges."
            )
        }
    )

    schema_version: str = SCHEMA_VERSION

    id: NonEmptyStr = Field(
        description=(
            "Stable id for THIS SOURCE POST, e.g. hash of source + "
            "source_listing_id. Deliberately distinct from apartment_id "
            "below -- this id must stay stable and unique per post even "
            "before any cross-platform matching has run."
        )
    )
    source: Source
    source_listing_id: NonEmptyStr
    apartment_id: OptionalNonEmptyStr = Field(
        default=None,
        description=(
            "Cross-platform entity id for the physical apartment this post "
            "describes. Null until a deduplication step (Phase 2/3) "
            "resolves two posts -- e.g. the same unit cross-posted to Yad2 "
            "and Facebook -- to the same apartment_id, typically by "
            "matching normalized phone + address + price. Keeping this "
            "separate from `id` means dedup logic can improve later "
            "without ever renaming or merging the post-level record. A "
            "fifth external review noted this still allowed '' -- the "
            "same inconsistent-with-None gap fixed on Area's text fields "
            "in v1.4 -- now closed the same way, via OptionalNonEmptyStr."
        ),
    )

    area: Area
    price: Price
    recurring_costs: Optional[RecurringCosts] = None
    rooms: Optional[float] = Field(default=None, gt=0)
    floor: Optional[int] = None  # may legitimately be 0 (ground) or negative (basement)
    total_floors: Optional[int] = Field(default=None, gt=0)
    size_m2: Optional[float] = Field(default=None, gt=0)
    listed_by: Optional[ListedBy] = None
    contact: Optional[Contact] = None
    availability: Optional[Availability] = None

    posted_at: Optional[date] = None
    pulled_at: AwareDatetime = Field(
        # The model already rejects a naive timestamp; the pattern makes the
        # exported schema reject one too, with or without format checking.
        json_schema_extra={"pattern": r"(?:[Zz]|[+-]\d{2}:\d{2})$"},
    )
    pull_round: OptionalNonEmptyStr = None

    raw_excerpt: Optional[str] = Field(
        default=None,
        max_length=_RAW_EXCERPT_MAX,
        description=(
            "A short excerpt (1-2 sentences) around whatever text justified "
            "a signal -- never the full post or page. Keeping this short is "
            "a deliberate memory-budget decision, not an oversight. An "
            "over-length value is truncated (with a visible marker), not "
            "rejected -- see _truncate_raw_excerpt below for why. The "
            "`max_length` here is NOT redundant with that truncation, even "
            "though the truncation runs first and always brings the stored "
            "Python value within bounds before this constraint ever has "
            "anything to reject (confirmed directly: a mode='before' "
            "validator runs before Field-level constraints, not after). A "
            "fifth external review caught that an earlier version of this "
            "field had no `max_length` at all, which meant the EXPORTED "
            "JSON SCHEMA carried no bound either -- a Phase 6 consumer in "
            "another language, validating raw scraped text before it ever "
            "passes through this truncation logic, would see no limit at "
            "all. `max_length` restores that for the schema artifact, "
            "without changing this model's own behavior one bit."
        ),
    )

    links: list[Link] = Field(default_factory=list)
    signals: dict[str, Signal] = Field(default_factory=dict)
    notes: NotesList = Field(
        default_factory=list,
        description="Free-form human notes carried over from manual review.",
    )

    match_score: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "Percentage scale (0-100), not a 0-1 fraction -- a third "
            "external review correctly noted this had no bounds at all "
            "before, which meant the scale itself was undefined (a -40 or "
            "a 4000 both validated). 0-100 is chosen now and stated "
            "explicitly here because Phase 1's scoring engine is the first "
            "code that will actually populate this field, and it needs a "
            "documented convention to target rather than inventing one."
        ),
    )
    status: ListingStatus = ListingStatus.CANDIDATE

    @field_validator("raw_excerpt", mode="before")
    @classmethod
    def _truncate_raw_excerpt(cls, v: Optional[str]) -> Optional[str]:
        """
        Truncates an over-length excerpt instead of raising, so one
        malformed record (an upstream scraper or LLM call that returned a
        full post instead of a short excerpt) doesn't abort an entire
        ingestion batch over one field. The visible "…[truncated]" marker
        is the compromise: the memory bound is still enforced, but the
        cut is obvious on inspection rather than silently hiding the
        upstream bug that produced an over-length excerpt in the first
        place -- that bug should still get fixed, just not by crashing
        the pipeline.
        """
        # Not a string: pass it on, so type validation rejects it with a
        # ValidationError (len() on an int raised a bare TypeError before v1.12).
        if not isinstance(v, str) or len(v) <= _RAW_EXCERPT_MAX:
            return v
        keep = _RAW_EXCERPT_MAX - len(_RAW_EXCERPT_TRUNCATION_MARKER)
        return v[:keep] + _RAW_EXCERPT_TRUNCATION_MARKER

    @model_validator(mode="after")
    def _floor_within_building(self) -> "Listing":
        """
        Catches a common scraper failure mode: misparsing a room number or
        building number into `floor`. Deliberately does NOT require
        floor >= 0 -- basement units (floor -1, -2) are real in Israeli
        buildings and already explicitly supported; that constraint from
        the external review would have been a regression against a
        decision already made and documented on `floor` above.
        """
        if (
            self.floor is not None
            and self.total_floors is not None
            and self.floor > self.total_floors
        ):
            raise ValueError(
                f"floor ({self.floor}) cannot exceed total_floors ({self.total_floors})"
            )
        return self
