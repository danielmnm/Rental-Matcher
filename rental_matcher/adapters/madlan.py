"""
Madlan adapter: what a Madlan page says -> a Listing.

Madlan is read only from pages the user opens himself (it answers anything
else with a bot check), so an extract is either a listing page
(browser/sites.js madlanItem: amenities, condition, entry date, text) or,
more often, just a row from a results page (price, rooms, size, floor,
the pin). Both come here; a row simply has fewer facts.

As with Yad2 and Komo, an amenity marked true is a confirmed yes and
anything else is unknown. v1.68: the names were checked against the
checklist 41 Madlan pages displayed (Madlan sample 1, Nov 19-25): window
bars are `grating`, pets `unitPetsAllowed`, the shelters `secureRoom`
(the flat's), `mamak` (the floor's) and `miklat` (the building's), and a
balcony, storage room or garden is ticked from its list of areas
(sites.js `areas`), with or without a size.
"""

from __future__ import annotations

from .common import elevator_from_height, parking_from_form  # noqa: E402  (v1.62)

from datetime import date, datetime, timezone
from typing import Any, Optional

from ..commute import valid_pin
from ..schema import (SCHEMA_VERSION, Area, Availability, AvailabilityMode, Link, ListedBy, Listing, ListingStatus, Price, Signal,
                      Source)
from .yad2 import _apartment_type, _confirmed, _date, _positive

_AMENITIES = {
    "elevator": "elevator", "balcony": "balcony", "secureRoom": "mamad", "safeRoom": "mamad", "mamad": "mamad",
    "airConditioner": "air_conditioning", "airConditioning": "air_conditioning", "accessible": "accessible",
    "handicapAccess": "accessible", "bars": "window_bars", "windowBars": "window_bars", "storage": "storage",
    "furniture": "furniture_box", "furnished": "furniture_box", "pets": "pets_allowed", "petsAllowed": "pets_allowed",
    "renovated": "renovated",
    # v1.68: the names Madlan's pages actually use (Madlan sample 1)
    "grating": "window_bars", "unitPetsAllowed": "pets_allowed", "isFurnished": "furniture_box",
    "mamak": "floor_shelter", "miklat": "building_shelter",
}
# v1.68: what the page ticks from its list of areas (sites.js madlanItem `areas`)
_AREAS = {"balcony": "balcony", "storage": "storage"}
_RENOVATED = {"renovated", "asnew", "new"}
_NOT_RENOVATED = {"preserved", "needsrenovation", "torenovate", "forrenovation", "old"}


def structured_signals(x: dict[str, Any], as_of: date) -> dict[str, Signal]:
    signals: dict[str, Signal] = {}
    for key, value in (x.get("amenities") or {}).items():
        name = _AMENITIES.get(key)
        if name and value is True and name not in signals:
            signals[name] = _confirmed(True, f"Madlan: {key}")
    for key, name in _AREAS.items():
        n = (x.get("areas") or {}).get(key)
        if name not in signals and isinstance(n, int) and not isinstance(n, bool) and n > 0:
            signals[name] = _confirmed(True, f"Madlan: {n} {key} listed")
    # v1.62: the shared rules (adapters/common.py)
    signals.update(parking_from_form("Madlan", x.get("parking") if isinstance(x.get("parking"), int) else None,
                                     ticked=(x.get("amenities") or {}).get("parking") is True))
    if "elevator" not in signals:
        signals.update(elevator_from_height("Madlan", x.get("floors") if isinstance(x.get("floors"), int) else None))
    kind = _apartment_type(x.get("property"))
    if kind:
        signals["apartment_type"] = _confirmed(kind, f"Madlan: {x.get('property')}")
    cond = str(x.get("condition") or "").lower()
    if "renovated" not in signals and cond in _RENOVATED:
        signals["renovated"] = _confirmed(True, f"Madlan: condition {x['condition']}")
    elif "renovated" not in signals and cond in _NOT_RENOVATED:
        signals["renovated"] = _confirmed(False, f"Madlan: condition {x['condition']} (not renovated)")
    # as on Yad2: the flat's safe room, the floor's (ממ"ק) or the building's shelter is a protected space (v1.68)
    shelters = [n for n in ("mamad", "floor_shelter", "building_shelter") if n in signals]
    if shelters:
        signals["protected_space"] = _confirmed(True, "Madlan: " + " and ".join(shelters))
    when = _date(x.get("available_date"))
    if str(x.get("availability") or "").lower() == "immediate":
        signals["days_until_available"] = _confirmed(0.0, "Madlan: immediate entry")
    elif when is not None:
        signals["days_until_available"] = _confirmed(float(max(0, (when - as_of).days)), f"Madlan: entry {when.isoformat()}")
    return signals


def to_listing(x: dict[str, Any], pulled_at: Optional[datetime] = None) -> Listing:
    """A Madlan extract (sites.js madlanItem, or a madlanRows row) -> a Listing."""
    n = str(x.get("id") or "").removeprefix("madlan:")
    if not n:
        raise ValueError("Madlan listing with no id")
    price = _positive(x.get("price"))
    if price is None:
        raise ValueError(f"Madlan item {n!r} has no usable price: {x.get('price')!r}")
    pulled_at = pulled_at or datetime.now(timezone.utc)
    floor = x.get("floor") if isinstance(x.get("floor"), int) and not isinstance(x.get("floor"), bool) else None
    floors = x.get("floors") if isinstance(x.get("floors"), int) and not isinstance(x.get("floors"), bool) else None
    if floors is not None and (floors <= 0 or (floor is not None and floor > floors)):
        floors = None
    p = valid_pin(x.get("lat"), x.get("lng"))  # the one rule for a pin (commute.valid_pin)
    pin = {"lat": p[0], "lng": p[1]} if p else {}
    when = _date(x.get("available_date"))
    availability = (Availability(mode=AvailabilityMode.IMMEDIATE) if str(x.get("availability") or "").lower() == "immediate"
                    else Availability(mode=AvailabilityMode.DATE, on_date=when) if when else None)
    description = x.get("description")
    return Listing(
        schema_version=SCHEMA_VERSION,
        id=f"madlan:{n}",
        source=Source.MADLAN,
        source_listing_id=n,
        area=Area(city=x.get("city") or "unknown", neighborhood=x.get("neighborhood") or x.get("hood_name") or None,
                  street=x.get("street") or None, **pin),
        price=Price(amount=price, currency="ILS"),
        rooms=_positive(x.get("rooms")),
        size_m2=_positive(x.get("size_m2")),
        floor=floor,
        total_floors=floors,
        listed_by={"private": ListedBy.PRIVATE, "commercial": ListedBy.AGENCY}.get(x.get("adType") or ""),
        availability=availability,
        pulled_at=pulled_at,
        raw_excerpt=description if isinstance(description, str) and description.strip() else None,
        links=[Link.model_validate({"label": "Madlan", "url": x.get("url") or f"https://www.madlan.co.il/listings/{n}"})],
        signals=structured_signals(x, pulled_at.date()),
        status=ListingStatus.CANDIDATE,
    )
