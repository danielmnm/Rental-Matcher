"""
A pull that only opens the listings that could matter (v1.20).

Opening a listing's own page is the slow step of a pull: ~1.2 s each at a
polite pace, so all 881 rentals in one city would take ~17 minutes. But
Yad2's search results already carry, for every listing, the numbers most
dealbreakers read: price, floor, size, rooms, property type and the map
pin. So a pull goes:

1. Search with the user's price cap applied by Yad2 itself (`maxPrice`),
   so there are fewer result pages to read. Only the price: it's a field
   every listing has. A checkbox filter (elevator, shelter...) would drop
   listings that say it in their text without ticking the box, and a
   floor or size filter would drop listings that leave the field empty --
   both would hide something on a guess.
2. Route every pin at once (one batched OSRM table request per ~60 pins,
   a fraction of a second each).
3. Score each search row with the REAL scorer (pipeline.build_listing on
   the row): it hides only on confirmed values, so a row it hides would
   be hidden from the full page too -- the full page has the same price,
   floor, size and pin. Those rows are skipped, with the reason.
4. Open the survivors best-first (by the match they could still reach),
   so the first results land in seconds and the list fills in while the
   user reads; `budget` caps how many are opened now.

Nothing here touches a network: rows, routes and the plan are data, like
the rest of the pipeline. The browser does the fetching.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .commute import lower_bound_minutes, valid_pin
from .pipeline import Routes, build_listing
from .scoring import PreferenceSet, ScoredListing, rank

# Yad2 property types that aren't a home to rent: nobody filtering for an
# apartment wants a storage room, a parking space or a plot of land.
NOT_HOMES = frozenset({"מחסן", "חניה", "מגרשים"})

# Measured on Oct 20, 2026 (one city, a polite 0.7 s between Yad2 requests):
SEARCH_PAGE_S = 1.35  # 25 pages of ~36 rows in 33.7 s
ITEM_PAGE_S = 1.17  # 60 item pages in 70.2 s
# That pace (~0.85 pages a second) is also the ceiling: on Oct 21, 4 pages a
# second drew Yad2's bot check within ~45 s (browser/yad2_pull.js). Pages in
# parallel don't beat it, so a pull is faster only by opening fewer pages:
# this funnel, and the browser's cache of listings already read (`cached`).
# One OSRM table request for up to ~60 pins on the free public server:
# 0.1-0.3 s when it's quiet, but 30 back-to-back requests that evening
# averaged ~9.5 s each. Its policy is one request a second and "no heavy
# use", so a pull routes only the pins still in play (pins_to_route), once
# each; a pin never moves, so a later pull can reuse its route.
ROUTE_REQUEST_S = 0.35
ROUTE_REQUEST_SLOW_S = 9.5
ROWS_PER_PAGE = 36
PINS_PER_ROUTE_REQUEST = 60


def row_extract(row: dict[str, Any]) -> dict[str, Any]:
    """A search row in the adapter's extract shape. Row keys: id, adType,
    price, floor, lat, lng, rooms, size_m2 (Yad2's squareMeterBuild if the
    row has it, else squareMeter -- the adapter's own order), property.
    A Komo or Madlan row (v1.27) is already in its adapter's shape."""
    if row.get("source") in ("komo", "madlan"):
        return dict(row)
    details: dict[str, Any] = {}
    if row.get("rooms") is not None:
        details["roomsCount"] = row["rooms"]
    if row.get("size_m2") is not None:
        details["squareMeterBuild"] = row["size_m2"]
    if row.get("property"):
        details["property"] = {"text": row["property"]}
    x: dict[str, Any] = {"id": row["id"], "adType": row.get("adType"), "price": row.get("price"),
                         "floor": row.get("floor"), "additionalDetails": details, "city": row.get("city")}
    pin = valid_pin(row.get("lat"), row.get("lng"))
    if pin:
        x["coords"] = {"lat": pin[0], "lon": pin[1]}
    return x


def price_cap(prefs: PreferenceSet) -> Optional[float]:
    """The highest rent any listing could have and still be shown: the
    price preference's highest limit (any override included) plus its
    tolerance. A dealbreaker hides past that; so does a soft preference
    with a tolerance (its outer edge). None when nothing hides on price."""
    for p in prefs.preferences:
        lower = p.kind == "at_most" or (p.kind == "ranged" and p.ideal is not None and p.limit is not None and p.ideal < p.limit)
        if p.field != "price" or not lower or p.limit is None or not (p.dealbreaker or p.tolerance):
            continue
        limits = [p.limit] + [o.limit for o in p.overrides if o.limit is not None]
        return max(limits) + (p.tolerance or 0)
    return None


def price_floor(prefs: PreferenceSet) -> Optional[float]:
    """The lowest rent any listing could have and still be shown: a
    must-have minimum rent (v1.30: the budget's low end), or None."""
    floors = [p.limit for p in prefs.preferences
              if p.field == "price" and p.kind == "at_least" and p.dealbreaker and p.limit is not None and not p.overrides]
    return max(floors) if floors else None


def search_filters(prefs: PreferenceSet) -> dict[str, str]:
    """Yad2 search URL parameters that are safe to apply server-side."""
    out: dict[str, str] = {}
    cap = price_cap(prefs)
    if cap is not None:
        out["maxPrice"] = str(int(math.floor(cap)))
    low = price_floor(prefs)
    if low is not None and low > 0:
        out["minPrice"] = str(int(math.ceil(low)))
    return out


@dataclass
class Plan:
    fetch: list[str]  # listing ids to open now, best first
    later: list[str]  # survivors past the budget, best first
    skipped: dict[str, list[str]]  # id -> why it can't be shown
    rows: int
    first: list[ScoredListing] = field(default_factory=list)  # the row-level scores, survivors only

    @property
    def survivors(self) -> int:
        return len(self.fetch) + len(self.later)


def _upper_line(p: Any) -> bool:
    """A limit that's an upper bound: at_most, or ranged with lower better."""
    return p.limit is not None and (p.kind == "at_most" or (p.kind == "ranged" and p.ideal is not None and p.ideal < p.limit))


def _commute_skips(row: dict[str, Any], prefs: PreferenceSet, routes: Optional[Routes]) -> list[str]:
    """A commute that can't come in under the limit: a bike/walk pin whose
    route -- or, unrouted, its straight line, which no route beats -- is
    already too long at the user's speed; a drive past the limit even on
    an empty road (traffic only adds)."""
    reasons = []
    pin = valid_pin(row.get("lat"), row.get("lng"))
    lat, lng = pin if pin else (None, None)
    for c in prefs.commutes:
        route = ((routes or {}).get(c.signal) or {}).get(str(row["id"]))
        try:
            bound = lower_bound_minutes(lat, lng, c, route)
        except ValueError:  # a route that doesn't hold up (v1.28): bound it as if unrouted, don't sink the plan
            route = None
            bound = lower_bound_minutes(lat, lng, c, None)
        for p in prefs.preferences:
            if p.field == f"signal:{c.signal}" and p.dealbreaker and _upper_line(p) and bound is not None:
                # the row can't tell which overrides will apply, so the most generous
                # limit any of them allows, as scoring would keep it with a check (v1.28)
                best = max([p.limit] + [o.limit for o in p.overrides if o.limit is not None])
                edge = best + (p.tolerance or 0)
                if bound > edge + 1e-9 * max(1.0, abs(edge)):
                    why = "even with no traffic" if c.mode == "car" else "by route" if route is not None else "in a straight line"
                    reasons.append(f"{p.label}: at least {bound:.0f} min {why}, past the limit of {best:g}")
    return reasons


def plan(rows: Iterable[dict[str, Any]], prefs: PreferenceSet, *, routes: Optional[Routes] = None,
         budget: Optional[int] = None, pulled_at: Optional[datetime] = None) -> Plan:
    pulled_at = pulled_at or datetime.now(timezone.utc)
    skipped: dict[str, list[str]] = {}
    listings = []
    seen: set[str] = set()
    n = 0
    for row in rows:
        rid = str(row.get("id") or "")
        if not rid or rid in seen:  # Yad2 repeats promoted listings across pages
            continue
        seen.add(rid)
        n += 1
        if row.get("property") in NOT_HOMES:
            skipped[rid] = [f"not a home: {row['property']}"]
            continue
        if reasons := _commute_skips(row, prefs, routes):
            skipped[rid] = reasons
            continue
        try:
            listings.append(build_listing(row_extract(row), prefs, routes=routes, pulled_at=pulled_at))
        except ValueError as e:  # no price: the adapter would skip its full page too
            skipped[rid] = [str(e)]
    scored = rank(listings, prefs)
    survivors = []
    for s in scored:
        rid = s.listing_id.removeprefix("yad2:")
        if s.excluded:
            skipped[rid] = s.exclusion_reasons
        else:
            survivors.append(s)
    # best first: the highest match each could still reach, then the expected one
    survivors.sort(key=lambda s: (-(s.match_high or 0), -(s.match_expected or 0), s.listing_id))
    ids = [s.listing_id.removeprefix("yad2:") for s in survivors]
    cut = len(ids) if budget is None else budget
    return Plan(fetch=ids[:cut], later=ids[cut:], skipped=skipped, rows=n, first=survivors)


def pins_to_route(rows: Iterable[dict[str, Any]], prefs: PreferenceSet, *, pulled_at: Optional[datetime] = None,
                  grid: int = 4) -> dict[str, list[float]]:
    """The pins worth routing: only rows still in play without routes (a
    straight line already rules out the rest), one per ~10 m (`grid`
    decimals) since many listings share a building or an agency's default
    pin. Key -> [lat, lng]; route_key(row) finds a row's key."""
    rows = list(rows)
    keep = set(plan(rows, prefs, pulled_at=pulled_at).fetch)
    pins: dict[str, list[float]] = {}
    for r in rows:
        pin = valid_pin(r.get("lat"), r.get("lng"))
        if str(r.get("id")) in keep and pin:
            pins.setdefault(route_key(r, grid), [round(pin[0], grid), round(pin[1], grid)])
    return pins


def route_key(row: dict[str, Any], grid: int = 4) -> str:
    return f"{round(row['lat'], grid)},{round(row['lng'], grid)}"


def wait_seconds(rows: int, fetch: int, *, pins: Optional[int] = None, routed: bool = True,
                 route_s: float = ROUTE_REQUEST_S, cached: int = 0, cached_pins: int = 0) -> float:
    """How long a pull of `rows` search rows that routes `pins` pins (all
    rows by default) and opens `fetch` item pages takes, from the measured
    step times above. `cached` of the pages and `cached_pins` of the pins
    were read on an earlier pull and still hold, so they cost nothing."""
    if not 0 <= cached <= fetch:
        raise ValueError("cached must be between 0 and fetch")
    pages = math.ceil(rows / ROWS_PER_PAGE)
    n = (rows if pins is None else pins) - cached_pins
    if n < 0:
        raise ValueError("cached_pins can't exceed the pins routed")
    route = math.ceil(n / PINS_PER_ROUTE_REQUEST) * route_s if routed else 0.0
    return pages * SEARCH_PAGE_S + route + (fetch - cached) * ITEM_PAGE_S
