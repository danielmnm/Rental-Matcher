"""
Yad2 adapter: the structured data on a Yad2 listing page -> a Listing.

Input is the extract the extension (or a test fixture) takes from a
listing page's embedded page data: price, the `additionalDetails` and
`inProperty` blocks, the address, `adType`, the dates and the free-text
description. The poster's name and contact details are never part of it.

The one rule that matters here: a TICKED box is a confirmed yes; an
unticked or missing box is UNKNOWN, never a no. Yad2's form is a set of
optional checkboxes, and the real pages show why "not ticked" can't mean
"no": `includeSecurityRoom` is false on all 20 listings in the test
fixtures, including ones whose own description describes a shelter
("מקלט צמוד לבניין", k678s664), and a missing `includeElevator` sits next
to descriptions that state either answer. A no comes from the text, which
is Phase 2's extractor's job, not from an empty box.

What IS taken as a fact, because Yad2 states it as one:
- `adType`: "private" or "commercial" (a business account: an agency or
  broker) -> `listed_by`.
- Numbers the poster typed: price, rooms, size, floor, the building's top
  floor, the entrance date.
"""

from __future__ import annotations

from .common import parking_from_form  # noqa: E402  (v1.62)

from datetime import date, datetime, timezone
from typing import Any, Optional

from ..commute import valid_pin
from ..schema import (
    SCHEMA_VERSION,
    Area,
    Availability,
    AvailabilityMode,
    ExtractedBy,
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

# Yad2 checkbox -> signal name. Each is CONFIRMED true when ticked, absent
# otherwise.
_TICKED: dict[str, str] = {
    "includeAirconditioner": "air_conditioning",
    "includeBalcony": "balcony",
    "includeElevator": "elevator",
    "includeFurniture": "furniture_box",  # a claim, not a list: see extraction/merge.py
    "isRenovated": "renovated",
    "isPetsAllowed": "pets_allowed",
    "includeSecurityRoom": "mamad",  # a safe room in the apartment
    "includeBuildingShelter": "building_shelter",
    "includeFloorShelter": "floor_shelter",  # v1.53: Yad2 labels it ממ"ק, the floor's safe room (checked on a live page, v1.54)
    "includeBars": "window_bars",
    "isHandicapped": "accessible",
    "isForPartners": "suits_roommates",  # a whole flat that roommates could share -- NOT a room share
    # v1.54: the rest of Yad2's "מה יש בנכס" list, labels checked on a live page (owner ruling: a ticked box
    # is something the poster shows you; before this no code read these four)
    "includeBoiler": "solar_heater",  # דוד שמש
    "includeTornado": "tornado_ac",  # מזגן טורנדו
    "includeWarehouse": "storage",  # מחסן
    "isKitchenKosher": "kosher_kitchen",  # מטבח כשר
    "includePandorDoors": "pandor_doors",  # דלתות פנדור (v1.55: first seen on held-out batch 10; the display check caught it)
}
# Not read: isEarlyAccess and isAssetExclusive aren't on the page's "מה יש בנכס" list; they're
# Yad2's own settings for the ad, not things in the flat.

_RENOVATED_CONDITION_ID = 2  # propertyCondition {"id": 2, "text": "משופץ"}
# Yad2's condition choices, as the saved pages name them
_CONDITIONS = {1: "חדש מקבלן (לא גרו בנכס)", 2: "משופץ", 3: "במצב שמור", 5: "דרוש שיפוץ", 6: "חדש (גרו בנכס)"}
_RENOVATED_OR_NEW = {1, 2, 6}  # new from the builder, renovated, new (lived in)
_NOT_RENOVATED = {3, 5}  # well kept, needs renovation


# Yad2's property type, read by its Hebrew name (the ids aren't published):
# the same types the text question asks about. A plain "דירה" gives nothing.
_PROPERTY_TYPES = (("roof", ("גג", "פנטהאוז", "פנטהאוס")), ("garden", ("דירת גן",)), ("unit", ("יחידת דיור",)),
                   ("house", ("בית פרטי", "קוטג", "דו משפחתי", "דו-משפחתי")), ("duplex", ("דופלקס",)),
                   ("studio", ("סטודיו", "לופט")))


def _apartment_type(text: object) -> Optional[str]:
    if not isinstance(text, str):
        return None
    for kind, names in _PROPERTY_TYPES:
        if any(n in text for n in names):
            return kind
    return None


def _confirmed(value: object, evidence: str) -> Signal:
    return Signal(status=SignalStatus.CONFIRMED, value=value, evidence=evidence, extracted_by=ExtractedBy.RULE)


def _positive(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _pin(extract: dict[str, Any]) -> dict[str, Optional[float]]:
    """lat/lng, or neither: a pin at (0, 0) is a missing one, not a place."""
    c = extract.get("coords") or {}
    pin = valid_pin(c.get("lat"), c.get("lon")) if isinstance(c, dict) else None  # the one rule (commute.valid_pin)
    return {"lat": pin[0], "lng": pin[1]} if pin else {}


def _date(value: object) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def structured_signals(extract: dict[str, Any], as_of: date) -> dict[str, Signal]:
    """The signals Yad2's structured fields support. Confirmations only
    (an unticked box isn't a no; see the module docstring), except the
    property's condition, a required choice that can say "not renovated"."""
    details = extract.get("additionalDetails") or {}
    in_property = extract.get("inProperty") or {}
    signals: dict[str, Signal] = {}

    for field, name in _TICKED.items():
        if in_property.get(field) is True:
            signals[name] = _confirmed(True, f"Yad2: {field} ticked")
    if "air_conditioning" not in signals and "tornado_ac" in signals:  # v1.54: a Tornado A/C is an air conditioner
        signals["air_conditioning"] = _confirmed(True, "Yad2: includeTornado ticked (מזגן טורנדו)")
    if "balcony" not in signals and isinstance(details.get("balconiesCount"), int) and details["balconiesCount"] > 0:
        signals["balcony"] = _confirmed(True, f"Yad2: balconiesCount {details['balconiesCount']}")
    kind = _apartment_type((details.get("property") or {}).get("text"))
    if kind:
        signals["apartment_type"] = _confirmed(kind, f"Yad2: property {details['property']['text']}")
    # The condition is a required choice on Yad2's form, not a box: picking
    # "well kept" or "needs renovation" says the place isn't renovated, so
    # that's a no (the one no this module reads). A ticked isRenovated box
    # still wins: it's a direct claim.
    condition = details.get("propertyCondition") or {}
    cid = condition.get("id")
    if "renovated" not in signals and isinstance(cid, int) and not isinstance(cid, bool):
        name = condition.get("text") or _CONDITIONS.get(cid, f"id {cid}")
        if cid in _RENOVATED_OR_NEW:
            signals["renovated"] = _confirmed(True, f"Yad2: condition {name}")
        elif cid in _NOT_RENOVATED:
            signals["renovated"] = _confirmed(False, f"Yad2: condition {name} (not renovated)")

    # Either a safe room or a building shelter: the "protected space" a
    # renter can reach in an alert. Kept apart too, for users who want a
    # safe room specifically.
    shelters = [n for n in ("mamad", "building_shelter", "floor_shelter") if n in signals]
    if shelters:
        signals["protected_space"] = _confirmed(True, "Yad2: " + " and ".join(shelters))

    # Parking: Yad2 says there's a space, not whether it's deeded (tabu)
    # or shared, so this is the LOWER bound of the tier scale (3 deeded, 2
    # shared, 1 street). Underrating is the safe direction.
    # v1.53: and only a LOWER bound: the space may well be the flat's own (owner ruling: a ticked box
    # is "almost always parking in tabu or in the building"). Scoring makes that a check for
    # someone who needs their own, never a reason to hide (the card test found 125 hidden so).
    # v1.62: the rule lives in adapters/common.py, shared by every site
    spaces = details.get("parkingSpacesCount")
    signals.update(parking_from_form("Yad2", spaces if isinstance(spaces, int) and not isinstance(spaces, bool) else None,
                                     ticked=in_property.get("includeParking") is True))

    # v1.53: Yad2's own distance to the nearest public shelter (metaData.shelterDistance),
    # shown on its page as "מקלט במרחק 349 מ'". A public shelter, not the building's.
    meters = extract.get("shelterDistance")
    if isinstance(meters, (int, float)) and not isinstance(meters, bool) and meters >= 0:
        signals["public_shelter_m"] = _confirmed(float(meters), f"Yad2: nearest public shelter {meters:g} m away")

    # Availability as days from `as_of` (default: move in as soon as possible): 0 if
    # immediate or already past.
    entrance = _date(details.get("entranceDate"))
    if in_property.get("isImmediateEntrance") is True:
        signals["days_until_available"] = _confirmed(0.0, "Yad2: immediate entrance")
    elif entrance is not None:
        days = max(0, (entrance - as_of).days)
        flexible = " (flexible)" if details.get("isEnterDateFlexible") is True else ""
        signals["days_until_available"] = _confirmed(float(days), f"Yad2: entrance {entrance.isoformat()}{flexible}")
    return signals


def _availability(extract: dict[str, Any]) -> Optional[Availability]:
    details = extract.get("additionalDetails") or {}
    if (extract.get("inProperty") or {}).get("isImmediateEntrance") is True:
        return Availability(mode=AvailabilityMode.IMMEDIATE)
    if details.get("isEnterDateFlexible") is True:
        return Availability(mode=AvailabilityMode.FLEXIBLE)
    entrance = _date(details.get("entranceDate"))
    return Availability(mode=AvailabilityMode.DATE, on_date=entrance) if entrance else None


def _site_costs(extract: dict[str, Any]) -> Optional[RecurringCosts]:
    """v1.53: Yad2's own fee fields: `propertyTax`, shown on its page as "ארנונה (לחודשיים)" (for two
    months, so half of it a month), and `houseCommittee`, "ועד בית (לחודש)". A token amount (some
    posters type 1 to get past the field) is no amount. None when neither is filled in."""
    def amount(v: object, least: float) -> Optional[float]:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= least else None
    tax, vaad = amount(extract.get("propertyTax"), 20), amount(extract.get("houseCommittee"), 10)
    if tax is None and vaad is None:
        return None
    return RecurringCosts(arnona_monthly=tax / 2 if tax is not None else None, vaad_bayit_monthly=vaad)


def to_listing(extract: dict[str, Any], pulled_at: Optional[datetime] = None) -> Listing:
    """One Yad2 extract -> a canonical Listing. Raises ValueError for an
    extract with no item data (a removed listing) or no usable price."""
    if "error" in extract or extract.get("price") is None:
        raise ValueError(f"Yad2 item {extract.get('id')!r} has no listing data: {extract.get('error', 'no price')}")
    if extract.get("id") in (None, "") or isinstance(extract.get("id"), bool):  # v1.28: not a KeyError, not "None"
        raise ValueError("Yad2 item with no id")
    item_id = str(extract["id"])
    pulled_at = pulled_at or datetime.now(timezone.utc)
    details = extract.get("additionalDetails") or {}
    price = _positive(extract.get("price"))
    if price is None:
        raise ValueError(f"Yad2 item {item_id!r} has no usable price: {extract.get('price')!r}")
    adtype = {"private": ListedBy.PRIVATE, "commercial": ListedBy.AGENCY}.get(extract.get("adType", ""))
    floor = extract.get("floor")
    top = details.get("buildingTopFloor")
    created = _date((extract.get("dates") or {}).get("createdAt"))
    description = extract.get("description")
    return Listing(
        schema_version=SCHEMA_VERSION,
        id=f"yad2:{item_id}",
        source=Source.YAD2,
        source_listing_id=item_id,
        area=Area(
            city=extract.get("city") or "unknown",
            neighborhood=extract.get("neighborhood"),
            street=extract.get("street"),
            **_pin(extract),
        ),
        price=Price(amount=price, currency="ILS"),
        rooms=_positive(details.get("roomsCount")),
        size_m2=_positive(details.get("squareMeterBuild")) or _positive(details.get("squareMeter")),
        floor=floor if isinstance(floor, int) and not isinstance(floor, bool) else None,
        total_floors=top if isinstance(top, int) and not isinstance(top, bool) and top > 0 else None,
        listed_by=adtype,
        recurring_costs=_site_costs(extract),
        availability=_availability(extract),
        posted_at=created,
        pulled_at=pulled_at,
        raw_excerpt=description if isinstance(description, str) and description.strip() else None,
        links=[Link.model_validate({"label": "Yad2", "url": extract.get("source_url") or f"https://www.yad2.co.il/realestate/item/{item_id}"})],
        signals=structured_signals(extract, pulled_at.date()),
        status=ListingStatus.CANDIDATE,
    )
