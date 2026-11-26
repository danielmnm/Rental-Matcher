"""
Komo adapter: what a Komo listing page (or a results-page row) says -> a Listing.

The extension reads the page (browser/sites.js komoItem / komoRows) and
hands over facts only: never the poster's name or phone. The same rule as
Yad2's form holds for Komo's feature list: a ticked feature is a confirmed
yes, an unticked one is unknown, not a no.

Komo gives no map pin. When the extension knows the neighborhood's middle
(from Yad2 listings in it) it sends that as an approximate pin, marked
`approx`: the commute is then an estimate, never a routed fact.
"""

from __future__ import annotations

from .common import elevator_from_height, floor_from_form, parking_from_form  # noqa: E402  (v1.62)

import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from ..commute import valid_pin
from ..schema import SCHEMA_VERSION, Area, Availability, AvailabilityMode, Link, Listing, ListingStatus, Price, Signal, SignalStatus, Source
from .yad2 import _apartment_type, _confirmed, _positive

# Komo's feature names, as sites.js maps them -> our signals (ticked = confirmed yes)
_TICKED = {
    "mamad": "mamad", "elevator": "elevator", "window_bars": "window_bars", "air_conditioning": "air_conditioning",
    "furniture_box": "furniture_box", "accessible": "accessible", "suits_roommates": "suits_roommates",
    "pets_allowed": "pets_allowed", "renovated": "renovated", "storage": "storage",
    "solar_heater": "solar_heater", "kosher_kitchen": "kosher_kitchen",  # v1.54: sites.js sent these; nothing read them
}
# Komo's condition choice ("מצב הנכס"): new or renovated is a yes; well kept or needing work is a no
_NOT_RENOVATED = ("שמור", "במצב טוב", "דרוש שיפוץ", "דורש שיפוץ", "לשיפוץ")
_RENOVATED = ("משופץ", "חדש")


def _int(v: object) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def _entry(text: object) -> Optional[date]:
    """'01/11/2026' (Komo's dd/mm/yyyy) -> a date."""
    if not isinstance(text, str):
        return None
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not m:
        return None
    try:
        return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None


def structured_signals(x: dict[str, Any], as_of: date) -> dict[str, Signal]:
    signals: dict[str, Signal] = {}
    for key, name in _TICKED.items():
        if (x.get("ticked") or {}).get(key) is True:
            signals[name] = _confirmed(True, f"Komo: {key} ticked")
    if (x.get("ticked") or {}).get("unit") is True:
        signals["apartment_type"] = _confirmed("unit", "Komo: unit ticked")
    else:
        kind = _apartment_type(x.get("property"))
        if kind:
            signals["apartment_type"] = _confirmed(kind, f"Komo: {x['property']}")
    balconies = _int(x.get("balconies"))
    if "balcony" not in signals and balconies and balconies > 0:
        signals["balcony"] = _confirmed(True, f"Komo: {balconies} balconies")
    condition = x.get("condition")
    if "renovated" not in signals and isinstance(condition, str):
        if any(w in condition for w in _NOT_RENOVATED):
            signals["renovated"] = _confirmed(False, f"Komo: condition {condition} (not renovated)")
        elif any(w in condition for w in _RENOVATED):
            signals["renovated"] = _confirmed(True, f"Komo: condition {condition}")
    if "mamad" in signals:
        signals["protected_space"] = _confirmed(True, "Komo: mamad")
    # v1.62: the shared rules (adapters/common.py): a parking count is a floor, as on Yad2; a tall building has a lift
    signals.update(parking_from_form("Komo", _int(x.get("parking"))))
    if "elevator" not in signals:
        signals.update(elevator_from_height("Komo", _int(x.get("floors"))))
    entry = _entry(x.get("entry"))
    if isinstance(x.get("entry"), str) and "מיידי" in x["entry"]:
        signals["days_until_available"] = _confirmed(0.0, "Komo: immediate entry")
    elif entry is not None:
        signals["days_until_available"] = _confirmed(float(max(0, (entry - as_of).days)), f"Komo: entry {entry.isoformat()}")
    return signals


def to_listing(x: dict[str, Any], pulled_at: Optional[datetime] = None) -> Listing:
    """A Komo extract (sites.js komoItem, or a komoRows row) -> a Listing."""
    raw_id = str(x.get("id") or "")
    n = raw_id.removeprefix("komo:")
    if not n:
        raise ValueError("Komo listing with no id")
    price = _positive(x.get("price"))
    if price is None:
        raise ValueError(f"Komo item {n!r} has no usable price: {x.get('price')!r}")
    pulled_at = pulled_at or datetime.now(timezone.utc)
    floor = _int(x.get("floor"))
    floors = _int(x.get("floors"))
    if floors is not None and (floors <= 0 or (floor is not None and floor > floors)):
        floors = None  # "3 קומות" counts differently from the floor number on some listings: don't fail on it
    floor, floor_said = floor_from_form(floor, floors)  # v1.64: "14 of 14" is often the building's height, not the flat's floor
    entry = _entry(x.get("entry"))
    p = valid_pin(x.get("lat"), x.get("lng"))  # the one rule for a pin (commute.valid_pin)
    pin = {"lat": p[0], "lng": p[1]} if p else {}
    description = x.get("description")
    return Listing(
        schema_version=SCHEMA_VERSION,
        id=f"komo:{n}",
        source=Source.KOMO,
        source_listing_id=n,
        area=Area(city=x.get("city") or "unknown", neighborhood=x.get("neighborhood") or x.get("hood_name") or None,
                  street=x.get("street") or None, **pin),
        price=Price(amount=price, currency="ILS"),
        rooms=_positive(x.get("rooms")),
        size_m2=_positive(x.get("size_m2")),
        floor=floor,
        total_floors=floors,
        availability=Availability(mode=AvailabilityMode.DATE, on_date=entry) if entry else None,
        pulled_at=pulled_at,
        raw_excerpt=description if isinstance(description, str) and description.strip() else None,
        links=[Link.model_validate({"label": "Komo", "url": x.get("url") or f"https://www.komo.co.il/code/nadlan/details/?modaaNum={n}"})],
        signals={**structured_signals(x, pulled_at.date()),
                 **({"floor_said": Signal(status=SignalStatus.CONFIRMED, value=float(floor_said),
                                          evidence=f"Komo: floor {floor_said} of {floors} (often the building's height): not used")}
                    if floor_said is not None else {})},
        status=ListingStatus.CANDIDATE,
    )
