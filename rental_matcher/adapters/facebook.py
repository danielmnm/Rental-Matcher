"""
Facebook adapter (v1.66, view-only): a rental post the user selected and kept -> a Listing.

Meta prohibits automated collection and the penalty would land on the user's own account (Extension Plan), so nothing is
fetched: the extension's right-click menu reads only the text the user selected and the page's address
(browser/sites.js facebookPost). A post has no form, so every fact past the rent, rooms, size and floor comes from the text,
read by the same rules as every other site's description; there is no pin, so a commute is "not stated" until a city or an
address is known.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..schema import SCHEMA_VERSION, Area, Link, Listing, ListingStatus, Price, Source
from .yad2 import _positive


def to_listing(x: dict[str, Any], pulled_at: Optional[datetime] = None) -> Listing:
    n = str(x.get("id") or "").removeprefix("facebook:")
    if not n:
        raise ValueError("Facebook post with no id")
    price = _positive(x.get("price"))
    if price is None:
        raise ValueError(f"Facebook post {n!r} has no usable price: {x.get('price')!r}")
    pulled_at = pulled_at or datetime.now(timezone.utc)
    floor = x.get("floor") if isinstance(x.get("floor"), int) and not isinstance(x.get("floor"), bool) else None
    description = x.get("description")
    url = x.get("url")
    return Listing(
        schema_version=SCHEMA_VERSION,
        id=f"facebook:{n}",
        source=Source.FACEBOOK,
        source_listing_id=n,
        area=Area(city=x.get("city") or "unknown", neighborhood=x.get("neighborhood") or x.get("hood_name") or None,
                  street=x.get("street") or None),
        price=Price(amount=price, currency="ILS"),
        rooms=_positive(x.get("rooms")),
        size_m2=_positive(x.get("size_m2")),
        floor=floor,
        pulled_at=pulled_at,
        raw_excerpt=description if isinstance(description, str) and description.strip() else None,
        links=[Link.model_validate({"label": "Facebook", "url": url})] if isinstance(url, str) and url.startswith("https://") else [],
        signals={},
        status=ListingStatus.CANDIDATE,
    )
