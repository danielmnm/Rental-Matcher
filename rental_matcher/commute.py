"""
Commute time to a place the user names, as a signal the scoring engine
reads (`bike_minutes` for the example user: e-bike to the example work pin).

Where the minutes come from, in order of trust:
1. A routed distance (a real bike route, fetched where the network allows
   it -- the browser, like the Yad2 data) at the user's own speed. That's
   a CONFIRMED signal: a deterministic computation from a route and a
   stated speed.
2. No route, but the listing has coordinates: a straight-line estimate,
   as an UNCONFIRMED signal. Scoring treats it as unknown, so a dealbreaker
   becomes a check quoting the estimate -- a guess never hides a listing.
3. No coordinates: no signal at all (a plain "not stated" check).

Why the speed is the user's and the distance is the route's: on Oct 20
the old tracker's per-neighborhood bike times turned out to be 1-13 min
off Google Maps' own (Negba, Ramat Gan: "15 min" vs Google's 28). Times
read by hand off a map drift; a route distance and a stated speed don't.
Calibration, four Google Maps bike readings from the example work pin against the
routed (OSRM bike profile) distance to the same point:

    Yad LaBanim 24, Yad Eliyahu   3.89 km routed   Google 15 min
    HaPardes 39, Tel Giborim      3.40 km          Google 16 min (fastest of 3)
    Sokolov 25, Green V'Am        4.37 km          Google 19 min
    Aminadav, Negba (Ramat Gan)   6.60 km          Google 28 min

Google's regular-bike times work out to ~14 km/h over the routed
distances (12.8-15.6). An e-bike is faster; 20 km/h is the default
assumption (Israeli e-bikes are assisted to 25 km/h; lights and junctions
take the rest). Both are the user's to change.

By car (v1.20), the minutes depend on the hour, so a drive carries up to
three times: free-flow (no traffic; OSRM's car profile, free, batched like
the bike table), and typical-weekday-traffic times for a peak and an
off-peak departure (TomTom's free tier, fetched on the user's machine with
their own key: see traffic.py). The signal is the time at the hour the
user commutes (`at`, rush hour by default) and its evidence always shows
both and says it's an estimate from typical traffic. With only the
free-flow time it's a check, never a hide: traffic only adds to it.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .schema import ExtractedBy, Listing, Signal, SignalStatus

# car: only for a straight-line estimate, shown as a check (a city average
# with lights and junctions); a drive's real minutes come from a route.
DEFAULT_SPEED_KMH = {"bike": 14.0, "ebike": 20.0, "walk": 4.5, "car": 30.0}

# OSRM's free-flow car time isn't a physical bound the way a straight line
# is for distance: a driver can beat its modelled speeds a little at an
# empty hour. So a drive is called certainly too long only when even 10%
# faster than free-flow would be past the limit.
FREE_FLOW_MARGIN = 0.9
# Checked Oct 21, 2026 against TomTom on 30 sample pins -> the example work pin
# (tests/fixtures/tomtom_calibration): TomTom's own no-traffic time was
# 1.01-1.85x OSRM's free-flow, so OSRM is optimistic and the 0.9 margin is
# safe with room to spare (typical traffic was never under 1.33x).

# What OSRM's free-flow time becomes with traffic, on those same 30 routes
# (TomTom typical traffic for a Tuesday): 11:00 and 08:00. One corridor, so
# only ever an estimate shown as a check; TomTom's own times confirm.
CAR_TYPICAL_X = (1.33, 2.18)
CAR_PEAK_X = (2.11, 2.93)

# A straight line understates a street route. Over the four calibration
# points the routed distance was 1.18-1.49x the straight line (mean 1.3);
# 1.3 is the estimate's factor, and it's only ever shown as an estimate
# (a check), never used to hide a listing.
DETOUR = 1.3


class Commute(BaseModel):
    """One place a user wants to be close to. `signal` is the name the
    scoring engine reads (a preference with field `signal:<signal>`)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    signal: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    label: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    mode: Literal["bike", "ebike", "walk", "car"]
    speed_kmh: Optional[float] = Field(default=None, gt=0, le=60)
    # car only: which hour the minutes are for. A work commute is at rush
    # hour; "typical" is an off-peak weekday drive.
    at: Literal["peak", "typical"] = "peak"

    @property
    def speed(self) -> float:
        return self.speed_kmh or DEFAULT_SPEED_KMH[self.mode]


def valid_pin(lat: Any, lng: Any) -> Optional[tuple[float, float]]:
    """(lat, lng) if they're a real place, else None: numbers (not
    booleans), finite, in range, and not (0, 0), which is how a missing pin
    shows up (yad2._pin). One rule for every place that reads a pin (v1.28:
    the funnel and the helper measured (0, 0) as a spot ~4,800 km away)."""
    def ok(v: Any, bound: float) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= bound
    if not (ok(lat, 90) and ok(lng, 180)) or (lat == 0 and lng == 0):
        return None
    return float(lat), float(lng)


def straight_line_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance (haversine), in km."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def minutes(km: float, speed_kmh: float) -> float:
    return round(km / speed_kmh * 60, 1)


class Drive(BaseModel):
    """One routed drive, in seconds. `free_flow_s` is no traffic; `peak_s`
    and `typical_s` are typical-weekday-traffic times for a rush-hour and
    an off-peak departure, with `source` saying whose (e.g. "TomTom
    typical traffic, Tue 08:00 / 11:00")."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    km: Optional[float] = Field(default=None, ge=0)
    free_flow_s: Optional[float] = Field(default=None, ge=0)
    typical_s: Optional[float] = Field(default=None, ge=0)
    peak_s: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = None


Route = Union[float, int, Drive, dict]  # km or {"km", "source"} (bike, walk), or a Drive (car)


def _km(route: Any, listing_id: str) -> tuple[float, Optional[str]]:
    """A bike/walk route: (km, who routed it). A bare number, or
    {"km": ..., "source": ...} from shortest_routes()."""
    km, source = (route.get("km"), route.get("source")) if isinstance(route, dict) else (route, None)
    if not (isinstance(km, (int, float)) and not isinstance(km, bool) and math.isfinite(km) and km >= 0):
        raise ValueError(f"{listing_id}: routed distance must be a non-negative number, got {route!r}")
    return float(km), source if isinstance(source, str) and source else None


def shortest_routes(by_router: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Bike/walk routes from more than one router -> the shortest per
    listing, saying who found it and what the others said. A route that
    exists can't be shorter than the shortest one a router found, so near
    the limit this never hides a listing one router puts under it. (Oct
    21: TomTom's bike routes for 30 sample pins were 0.85-1.11x OSRM's, and
    3 of the 30 sat on opposite sides of a 15-minute e-bike limit.)
    by_router: {router name: {signal: {listing id: km}}}. Car drives aren't
    merged here: their times come from one source with its own traffic."""
    out: dict[str, dict[str, Any]] = {}
    signals = {sig for routes in by_router.values() for sig in routes}
    for sig in sorted(signals):
        ids = {i for routes in by_router.values() for i in (routes.get(sig) or {})}
        merged: dict[str, Any] = {}
        for i in sorted(ids):
            found = [(_km(routes[sig][i], i)[0], name) for name, routes in by_router.items() if i in (routes.get(sig) or {})]
            found.sort()
            km, name = found[0]
            others = "; ".join(f"{n} {k:.2f} km" for k, n in found[1:])
            merged[i] = {"km": km, "source": name + (f" ({others})" if others else "")}
        out[sig] = merged
    return out


def _drive(route: Any, listing_id: str) -> Drive:
    try:
        return route if isinstance(route, Drive) else Drive.model_validate(route)
    except Exception as e:  # noqa: BLE001 -- a bad saved route is the caller's data error
        raise ValueError(f"{listing_id}: a car route must be a drive (free_flow_s, typical_s, peak_s): {e}") from None


def lower_bound_minutes(lat: Optional[float], lng: Optional[float], commute: Commute,
                        route: Optional[Route] = None) -> Optional[float]:
    """Minutes the commute can't come in under, or None if nothing bounds
    it. Bike/walk: the routed distance (or the straight line, which no
    route beats) at the user's speed. Car: the free-flow drive (traffic
    only adds), with FREE_FLOW_MARGIN; no drive, no bound."""
    if commute.mode == "car":
        if route is None:
            return None
        d = _drive(route, "route")
        return d.free_flow_s / 60 * FREE_FLOW_MARGIN if d.free_flow_s is not None else None
    if route is not None:
        return minutes(_km(route, "route")[0], commute.speed)
    if lat is None or lng is None:
        return None
    return minutes(straight_line_km(lat, lng, commute.lat, commute.lng), commute.speed)


def certainly_past(lat: float, lng: float, commute: Commute, limit_minutes: float) -> bool:
    """True when a pin is too far for `limit_minutes` whatever the route: a
    street route is never shorter than the straight line, so if even the
    straight line takes longer, no route can come in under the limit.

    For a pull: Yad2's search results already carry each pin, so this
    skips the item page (the slow, ~1.2 s step) of a listing that could
    only ever be hidden for distance. Pass the limit plus any tolerance.
    On Oct 20's live pull it skipped 17 of 60 at 15 min by e-bike, and all
    17 were past the limit on their real routes."""
    return minutes(straight_line_km(lat, lng, commute.lat, commute.lng), commute.speed) > limit_minutes


def _car_signal(listing: Listing, commute: Commute, d: Drive) -> Signal:
    to = f"drive to {commute.label}"
    if d.peak_s is not None and d.typical_s is not None:
        peak, typical = round(d.peak_s / 60), round(d.typical_s / 60)
        value = float(peak if commute.at == "peak" else typical)
        source = f" ({d.source})" if d.source else ""
        return Signal(status=SignalStatus.CONFIRMED, value=value, extracted_by=ExtractedBy.RULE,
                      evidence=f"{to}: about {typical} min in typical traffic, {peak} min at rush hour; "
                               f"an estimate from typical traffic{source}, a given day can differ")
    if d.free_flow_s is not None:
        m = d.free_flow_s / 60
        (tl, th), (pl, ph) = CAR_TYPICAL_X, CAR_PEAK_X
        return Signal(status=SignalStatus.UNCONFIRMED, extracted_by=ExtractedBy.RULE,
                      evidence=f"{to}: traffic not checked; roughly {round(m * tl)}-{round(m * th)} min in typical "
                               f"traffic, {round(m * pl)}-{round(m * ph)} at rush hour (an estimate: the route server's "
                               f"{round(m)} min with no traffic, scaled as on routes checked against TomTom)")
    raise ValueError(f"{listing.id}: a drive needs free_flow_s, or typical_s and peak_s")


_CAR_TRAFFIC = re.compile(r"about (\d+) min in typical traffic, (\d+) min at rush hour")
_CAR_ESTIMATE = re.compile(r"roughly (\d+)-(\d+) min in typical traffic, (\d+)-(\d+) at rush hour")


def car_times(evidence: Optional[str]) -> Optional[dict[str, Any]]:
    """v1.37: a car signal's minutes for a card, from the evidence _car_signal writes: the usual
    drive and the rush-hour one (the worst a weekday usually gets), and whether it's an estimate.
    TomTom's: typical traffic and 08:00 traffic. Without TomTom: the middle of the typical range
    and the top of the rush-hour range, from the no-traffic drive scaled as on checked routes."""
    m = _CAR_TRAFFIC.search(evidence or "")
    if m:
        return {"usual": int(m.group(1)), "worst": int(m.group(2)), "estimate": False}
    m = _CAR_ESTIMATE.search(evidence or "")
    if m:
        a, b, _, d = (int(g) for g in m.groups())
        return {"usual": round((a + b) / 2), "worst": d, "estimate": True}
    return None


def commute_signal(listing: Listing, commute: Commute, routed_km: Optional[Route] = None) -> Optional[Signal]:
    """The commute signal for one listing: confirmed from a route, an
    estimate (unconfirmed) from coordinates, or None with neither. For a
    car, `routed_km` is a Drive (or its dict): confirmed only with
    typical-traffic times; free-flow alone is a check."""
    how = f"{commute.mode} at {commute.speed:g} km/h to {commute.label}"
    if commute.mode == "car" and routed_km is not None:
        return _car_signal(listing, commute, _drive(routed_km, listing.id))
    if routed_km is not None:
        km, source = _km(routed_km, listing.id)
        m = minutes(km, commute.speed)
        by = f" ({source})" if source else ""
        return Signal(status=SignalStatus.CONFIRMED, value=m, evidence=f"routed {km:.2f} km{by}, {how}: {m:g} min",
                      extracted_by=ExtractedBy.RULE)
    if listing.area.lat is None or listing.area.lng is None:
        return None
    km = straight_line_km(listing.area.lat, listing.area.lng, commute.lat, commute.lng) * DETOUR
    return Signal(status=SignalStatus.UNCONFIRMED,
                  evidence=f"not routed; estimate from the map: about {minutes(km, commute.speed):g} min ({how})",
                  extracted_by=ExtractedBy.RULE)
