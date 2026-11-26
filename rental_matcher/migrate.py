"""
One-off migration: convert the legacy tracker's per-neighborhood JS arrays
(exported to data/legacy_raw.json) into the canonical Listing schema
(current version -- see SCHEMA_VERSION in schema.py).

This is the Phase 0 exit criterion from the Master Plan: "all current
listings re-expressed in the schema; old trackers deprecated." It is also
the first real test of the schema against real data, which is the point --
the owner's test search is the proving ground for the universal tool, not the
other way around.

Known, stated limitations of this migration (logged here rather than
hidden):

- The legacy data has no per-listing "when did we pull this" timestamp, so
  `pulled_at` is backfilled to the migration run time for every record.
  This is a real gap, not a rounding error -- flagged so nobody mistakes
  it for a true historical pull time later.
- The legacy "flags" field mixes several kinds of human notes (hard-rule
  checks, price history, scheduling notes). Rather than guess which flag
  text is which, all of it is carried into `notes` verbatim. Two kinds of
  mention are also FLAGGED, with the words as evidence (see mentions.py):
  brokerage (`signals.brokerage_mentioned`) and vaad bayit / arnona
  (`signals.recurring_costs_mentioned`). Until v1.12 these were read into
  `listed_by` and `recurring_costs` as facts; every review found phrasings
  that gave wrong ones, so those fields now stay unset until a source
  states them in structured form, or Phase 2's measured extractor does.
- The legacy data never captured contact info or availability -- those
  fields are left `None` (genuinely unknown), not guessed. Street,
  house number, and neighborhood ARE captured, by parsing the legacy
  `addr` field (`_parse_address`) -- a third external review caught that
  a previous version of this migration ignored `addr` entirely and
  substituted a hardcoded, English, city-level name for every listing's
  neighborhood regardless of what the real address said.
- All legacy records are Yad2-sourced; there is nothing to migrate for
  Facebook or other sources yet.

Usage:
    python -m rental_matcher.migrate
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .mentions import brokerage_mention, recurring_costs_mention
from .schema import (
    SCHEMA_VERSION,
    Area,
    ExtractedBy,
    Link,
    Listing,
    ListingStatus,
    Price,
    Signal,
    SignalStatus,
    Source,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEGACY_RAW_PATH = DATA_DIR / "legacy_raw.json"
OUTPUT_PATH = DATA_DIR / "listings.json"

# Only the city: the neighborhood is no longer hardcoded here. A previous
# version of this migration used a static area-key -> {city, neighborhood}
# table, which silently overwrote every listing's REAL sub-neighborhood
# (from the legacy `addr` field -- e.g. "תל גיבורים", "גרין ועם" for
# Holon, "נגבה" for Ramat Gan) with the same city-level English name for
# every record in that area. The city is still a fair static lookup
# (the first test search is scoped to exactly these four cities/areas and the
# legacy tracker never varied it), but the neighborhood is real,
# per-listing data that `_parse_address` below now actually reads.
AREA_TO_CITY = {
    "yadeliyahu": "Tel Aviv",
    "holon": "Holon",
    "givatayim": "Givatayim",
    "ramatgan": "Ramat Gan",
}

# Field parsers follow the same rule as costs.py: one unambiguous number,
# or None. A number must contain a digit (the old "[\d.]+" matched the
# lone "." in "approx. 65 m²" and float(".") raised); a unit token that
# contains a digit ("m2") is removed first so its "2" isn't read as the
# value; and a field with two numbers ("2 rooms, 65 m²") or an unhandled
# notation ("3,5" decimal comma) gives None rather than a guess.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_UNIT_WITH_DIGIT_RE = re.compile(r"\b(?:m2|sqm2?)\b|m²|מ[\"״]ר", re.IGNORECASE)
_FLOOR_RE = re.compile(r"-?\d+")


def _single_number(raw: str) -> float | None:
    # "2½" -> "2.5", a lone "½" -> "0.5" (it used to become ".5" and read as 5).
    text = re.sub(r"(?<=\d)½", ".5", raw).replace("½", "0.5")
    numbers = _NUMBER_RE.findall(text)
    if len(numbers) != 1:
        return None
    # "3,5" (a decimal comma) or "3,5,7": a comma touching the number that
    # isn't a thousands separator means the notation is unclear.
    if re.search(r"\d,\d", text):
        return None
    return _positive_number(float(numbers[0]))

# Matches a parenthetical aside anywhere in the legacy `addr` text -- e.g.
# "(different unit, same building as ho-8raxcjyc)" or a bracketed aside
# standing in for a missing street name, "(street listed as Neve Yaakov)".
# Non-greedy over anything but ')' so it still matches correctly when the
# aside itself contains a comma (the first example above does).
_ADDR_PAREN_RE = re.compile(r"\(([^)]*)\)")
# A trailing "<name> <number>" at the end of the street portion of an
# address, e.g. "שדרות קוגל 18" -> ("שדרות קוגל", "18"). Hebrew house
# numbers are occasionally suffixed with a single Hebrew letter (e.g.
# "18א"), hence the optional [א-ת] -- not seen in the current live data,
# but the pattern costs nothing to support now.
_TRAILING_HOUSE_NUMBER_RE = re.compile(r"^(.*\S)\s+(\d+[א-ת]?)$")
_UNIT_DETAIL = r"(?:דירה|קומה|כניסה|apt\.?|apartment|unit|floor|entrance)\s*[\w\-]{1,4}"
_UNIT_DETAIL_RE = re.compile(_UNIT_DETAIL, re.IGNORECASE)
_TRAILING_UNIT_DETAIL_RE = re.compile(rf"\s+({_UNIT_DETAIL})$", re.IGNORECASE)

def _positive_number(raw: object) -> float | None:
    """A numeric legacy value (int/float), as opposed to a string. Finite
    and positive, or None: float(10**400) overflows, and inf isn't a size."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        value = float(raw)
    except OverflowError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def _parse_rooms(raw: str | int | float | None) -> float | None:
    if isinstance(raw, (int, float)):
        return _positive_number(raw)
    if not raw or not isinstance(raw, str):
        return None
    return _single_number(raw)


# A legacy price string may hold digits, thousands commas, spaces and the
# shekel sign or its abbreviations -- nothing else. "5k", "-5000", "$1,500",
# "1,500 USD" and "5.500" (period thousands, or 5.5?) are all refused rather
# than turned into a plausible-looking wrong price in ILS.
_PRICE_RE = re.compile(r"\s*(?:₪\s*)?(\d{1,3}(?:,\d{3})+|\d+)\s*(?:₪|ש[\"״']?ח|nis|ils)?\s*", re.IGNORECASE)


def _parse_price(raw: object) -> float | None:
    if isinstance(raw, (int, float)):
        return _positive_number(raw)
    if not isinstance(raw, str):
        return None
    m = _PRICE_RE.fullmatch(raw)
    return _positive_number(int(m.group(1).replace(",", ""))) if m else None


def _parse_posted(raw: object) -> date | None:
    """ISO dates only; anything else ("10/08/25" is ambiguous between
    day-first and month-first) becomes None rather than a guess."""
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _parse_floor(raw: str | int | float | None) -> int | None:
    # Legacy data stores floors as strings, but an int (including 0, the
    # ground floor) must not be dropped by a truthiness check or crash .search.
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else None
    if re.search(r"[A-Za-zא-ת][-־]\d", raw):
        # "ה-2" ("the 2nd"), "ב-3" ("on the 3rd"): the hyphen joins a Hebrew
        # prefix to the number; it isn't a minus sign. Read as -2 before
        # v1.12. Checked on the raw text, before "מינוס" becomes "-", so
        # "במינוס 1" ("in minus 1") still reads as -1.
        return None
    text = raw.replace("\u2212", "-")  # Unicode minus sign
    text = re.sub(r"מינוס\s*", " -", text)
    if re.search(r"[A-Za-zא-ת]\d", text):
        return None  # "B1", "P2": a basement/parking label, not a signed floor
    numbers = _FLOOR_RE.findall(text)
    return int(numbers[0]) if len(numbers) == 1 else None


def _parse_size(raw: str | int | float | None) -> float | None:
    if isinstance(raw, (int, float)):
        return _positive_number(raw)
    if not raw or not isinstance(raw, str):
        return None
    if re.search(r"sq\.?\s*ft|square\s+feet|ft²|ft2|\bft\b|רגל", raw, re.IGNORECASE):
        return None  # a different unit; Listing.size_m2 is square meters
    text = _UNIT_WITH_DIGIT_RE.sub(" ", raw)
    return _single_number(_THOUSANDS_RE.sub("", text))


def _balcony_evidence(flags: list[str]) -> str | None:
    """The flag that justifies a legacy `balcony: true`, quoted as evidence.
    Hebrew "מרפסת" counts on its own -- not just the English word or the 🚬
    marker the legacy tracker happened to add alongside it."""
    for f in flags:
        if "balcony" in f.lower() or "מרפסת" in f or "🚬" in f:
            return f
    return None


def _parse_address(addr: str | None) -> tuple[str | None, str | None, str | None, list[str]]:
    """Split the legacy tracker's single free-text `addr` field into
    (street, house_number, neighborhood, extra_notes).

    The legacy field mixes a street-and-number with a neighborhood name,
    comma-separated, and sometimes an inline parenthetical aside that is
    neither a street nor a neighborhood -- e.g. "(different unit, same
    building as ho-8raxcjyc)", or a bracketed aside standing in for a
    missing street name entirely: "(street listed as Neve Yaakov)". A
    static area -> neighborhood lookup (the previous approach, see
    AREA_TO_CITY above) threw all of this away and substituted a
    hardcoded city-level name instead, so every listing's real
    sub-neighborhood was silently overwritten. This parses the real text
    instead of assuming a fixed shape.

    Parenthetical asides are returned as `extra_notes` (usually empty)
    rather than silently discarded -- "different unit, same building as
    X" is real, useful information even though it doesn't fit any
    structured field.
    """
    if not addr:
        return None, None, None, []

    extra_notes: list[str] = []

    def _capture(match: re.Match) -> str:
        extra_notes.append(f"Address annotation: {match.group(1).strip()}")
        return ""

    cleaned = _ADDR_PAREN_RE.sub(_capture, addr)

    parts = [part.strip() for part in cleaned.split(",")]
    # "הרצל 12 דירה 4": a trailing unit detail inside the street part would
    # otherwise be read as street "הרצל 12 דירה", house number "4".
    unit_in_street = _TRAILING_UNIT_DETAIL_RE.search(parts[0])
    if unit_in_street:
        extra_notes.append(f"Address detail: {unit_in_street.group(1)}")
        parts[0] = parts[0][: unit_in_street.start()].strip()
    street_raw = parts[0] or None
    neighborhood: str | None = None
    if len(parts) == 2:
        if _UNIT_DETAIL_RE.fullmatch(parts[1]):
            extra_notes.append(f"Address detail: {parts[1]}")
        else:
            neighborhood = parts[1] or None
    elif len(parts) > 2:
        # "הרצל 12, דירה 4, נווה צדק": the middle parts are unit details,
        # not part of the neighborhood. Recognized ones go to notes and the
        # last part is the neighborhood; anything unrecognized means the
        # shape isn't understood, so no neighborhood is guessed.
        middle = parts[1:-1]
        if all(_UNIT_DETAIL_RE.fullmatch(part) for part in middle):
            neighborhood = parts[-1] or None
            extra_notes.extend(f"Address detail: {part}" for part in middle)
        else:
            extra_notes.append(f"Address (unparsed tail): {', '.join(parts[1:])}")

    street, house_number = street_raw, None
    if street_raw:
        m = _TRAILING_HOUSE_NUMBER_RE.match(street_raw)
        if m:
            street, house_number = m.group(1).strip(), m.group(2)

    return street, house_number, neighborhood, extra_notes


def migrate_record(area_key: str, legacy: dict) -> Listing:
    city = AREA_TO_CITY.get(area_key)
    if city is None:
        raise ValueError(f"unknown legacy area key {area_key!r}; add it to AREA_TO_CITY")
    price = _parse_price(legacy.get("price"))
    if price is None:
        raise ValueError(f"legacy record {legacy.get('key')!r} has no usable price: {legacy.get('price')!r}")
    key = legacy["key"]
    source_listing_id = key.split("-", 1)[1] if "-" in key else key

    links = [
        Link(label=label, url=url) for label, url in legacy.get("links", [])
    ]

    signals: dict[str, Signal] = {}
    if legacy.get("balcony") is True:
        signals["balcony"] = Signal(
            status=SignalStatus.CONFIRMED,
            value=True,
            evidence=_balcony_evidence(legacy.get("flags", [])),
            extracted_by=ExtractedBy.MANUAL,
        )
    else:
        signals["balcony"] = Signal(status=SignalStatus.UNKNOWN)

    flags = legacy.get("flags", [])
    street, house_number, neighborhood, address_notes = _parse_address(legacy.get("addr"))

    notes = list(flags) + address_notes
    if legacy.get("good") is True:
        notes.append("Migrated from legacy tracker: passed hard-rule filtering (good=true).")
    bike = legacy.get("bike")
    if bike:
        # Kept as a note (the original wording) AND, when it's exactly "<n>
        # min", as the structured signal Phase 1 scoring reads. It's a
        # per-user fact (minutes to THIS user's commute anchor), which is
        # why it lives in the open `signals` map, not a fixed field.
        notes.append(f"Bike commute time (from legacy tracker): {bike}")
        minutes = re.fullmatch(r"\s*(\d+)\s*min\s*", str(bike))
        if minutes:
            signals["bike_minutes"] = Signal(
                status=SignalStatus.CONFIRMED,
                value=float(minutes.group(1)),
                evidence=str(bike),
                extracted_by=ExtractedBy.MANUAL,
            )

    for name, flag in (("brokerage_mentioned", brokerage_mention(flags)),
                       ("recurring_costs_mentioned", recurring_costs_mention(flags))):
        if flag is not None:
            signals[name] = flag

    posted_at = _parse_posted(legacy.get("posted"))
    if posted_at is None and legacy.get("posted"):
        notes.append(f"Posted date (unparsed, from legacy tracker): {legacy.get('posted')}")

    return Listing(
        schema_version=SCHEMA_VERSION,
        id=f"yad2:{source_listing_id}",
        source=Source.YAD2,
        source_listing_id=source_listing_id,
        apartment_id=None,  # no cross-platform dedup has run yet
        area=Area(
            city=city,
            neighborhood=neighborhood,
            street=street,
            house_number=house_number,
        ),
        price=Price(amount=price, currency="ILS"),
        recurring_costs=None,  # free text is flagged, not read as a fact (see mentions.py)
        rooms=_parse_rooms(legacy.get("rooms")),
        floor=_parse_floor(legacy.get("floor")),
        total_floors=None,  # not captured by the legacy tracker
        size_m2=_parse_size(legacy.get("size")),
        listed_by=None,  # likewise; a brokerage mention is a flag
        contact=None,  # not captured by the legacy tracker
        availability=None,  # not captured by the legacy tracker
        posted_at=posted_at,
        pulled_at=datetime.now(timezone.utc),
        pull_round=legacy.get("pullRound"),
        raw_excerpt=None,
        links=links,
        signals=signals,
        notes=notes,
        match_score=None,
        status=ListingStatus.CANDIDATE,
    )


def summarize(migrated: list[Listing]) -> str:
    """Build the human-readable per-neighborhood/agency-count summary
    `main()` prints after a migration run. Pulled out of `main()` into
    its own function for two reasons: it's then testable without
    touching the filesystem, and that test is what caught the bug
    documented below.

    A fourth external review caught that the original inline version of
    this -- `for k, v in sorted(by_area.items())` -- crashes with
    `TypeError: '<' not supported between instances of 'NoneType' and
    'str'` the first time ANY listing has `neighborhood=None`. That
    can't happen in the current 22-listing dataset (every real address
    here has a neighborhood), but `Area.neighborhood` is deliberately
    Optional *by design* (see its docstring -- Facebook posts often
    don't name one), so this was a live crash waiting for exactly the
    kind of record this schema was built to accept. Fixed by sorting on
    `k or ""` instead of `k` directly, so a missing neighborhood sorts
    first instead of crashing.
    """
    by_area: dict[str | None, int] = {}
    brokerage_count = 0
    for m in migrated:
        by_area[m.area.neighborhood] = by_area.get(m.area.neighborhood, 0) + 1
        if "brokerage_mentioned" in m.signals:
            brokerage_count += 1

    lines = [f"  {k or '(no neighborhood)'}: {v}" for k, v in sorted(by_area.items(), key=lambda kv: kv[0] or "")]
    lines.append(f"  brokerage mentioned (flag, see mentions.py): {brokerage_count}")
    return "\n".join(lines)


def main() -> None:
    with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
        legacy_by_area = json.load(f)

    migrated: list[Listing] = []
    for area_key, items in legacy_by_area.items():
        for item in items:
            migrated.append(migrate_record(area_key, item))

    OUTPUT_PATH.write_text(
        json.dumps([m.model_dump(mode="json") for m in migrated], indent=2, ensure_ascii=False)
        + "\n"
    )
    print(f"Migrated {len(migrated)} listings -> {OUTPUT_PATH}")
    print(summarize(migrated))


if __name__ == "__main__":
    main()
