"""
Drive times with typical traffic, for a car commute (commute.py).

Free and keyless first: OSRM's car profile gives a free-flow drive (no
traffic) for every pin in one batched table request, in the browser, like
the bike routes. That's enough to skip listings that are too far even on
an empty road (funnel.py), but not to tell a user how long the drive
takes at 8 in the morning.

For that, TomTom's Routing API (free tier: 20,000 routes a month, no
credit card) answers "how long does this drive take, departing Tuesday
08:00" from its historical traffic. Two departures per listing -- a
rush-hour one and an off-peak one -- give the range a user sees: "about
18 min in typical traffic, 27 min at rush hour; an estimate". Only the
listings that survive the funnel are routed, so a pull costs tens of
requests, not hundreds.

The key is the user's own, on their machine: TOMTOM_API_KEY or a
`.tomtom_key` file next to the repo (gitignored). TomTom takes it in the
URL, so every error raised here is built without the URL, and nothing
prints or saves it.

    python -m rental_matcher.traffic PINS.json --to 32.0754,34.7749 --out ROUTES.json
        [--signal commute_minutes] [--peak 08:00] [--typical 11:00] [--day tue]

PINS: {listing id: [lat, lng]}. ROUTES: {signal: {id: {free_flow_s,
typical_s, peak_s, km, source}}}, the pipeline's --routes input.

By bike (`--mode bicycle`, one request per listing): TomTom's bicycle
route. TomTom has one bicycle mode, with no traffic and no way to set a
speed, so what's kept is the route's length. The rider's own speed
(commute.py: `bike` 14 km/h, `ebike` 20 km/h, or their own `speed_kmh`)
turns it into minutes, exactly as with OSRM's bike routes. TomTom's own
time is saved beside it (`_tomtom_bicycle_s`), to compare, not to use.

    python -m rental_matcher.traffic PINS.json --to 32.0754,34.7749 --mode bicycle --out ROUTES.json
        [--signal bike_minutes]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

API = "https://api.tomtom.com/routing/1/calculateRoute"
KEY_FILE = Path(__file__).resolve().parents[1] / ".tomtom_key"
DAYS = {"sun": 6, "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5}

Get = Callable[[str], dict[str, Any]]


class TrafficError(RuntimeError):
    pass


def api_key() -> str:
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    for path in (KEY_FILE, Path.cwd() / ".tomtom_key"):
        if not key and path.is_file():
            key = path.read_text(encoding="utf-8-sig").strip()
    if not key:
        raise TrafficError("no key: set TOMTOM_API_KEY or create .tomtom_key next to the repo")
    return key


def next_departure(day: str, hhmm: str, today: Optional[date] = None) -> str:
    """The next `day` (strictly after today) at `hhmm`, local time, as
    TomTom's departAt (no offset: TomTom reads it in the origin's zone)."""
    today = today or date.today()
    ahead = (DAYS[day] - today.weekday()) % 7 or 7
    d = today + timedelta(days=ahead)
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m).strftime("%Y-%m-%dT%H:%M:%S")


def route_url(origin: tuple[float, float], dest: tuple[float, float], depart_at: str, key: str) -> str:
    (a, b), (c, d) = origin, dest
    return (f"{API}/{a:.6f},{b:.6f}:{c:.6f},{d:.6f}/json?key={key}&travelMode=car&traffic=true"
            f"&routeType=fastest&computeTravelTimeFor=all&departAt={depart_at}")


def bike_url(origin: tuple[float, float], dest: tuple[float, float], key: str) -> str:
    (a, b), (c, d) = origin, dest
    return f"{API}/{a:.6f},{b:.6f}:{c:.6f},{d:.6f}/json?key={key}&travelMode=bicycle&traffic=false&routeType=fastest"


def _http_get(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        # never str(e) or the URL: both carry the key
        raise TrafficError(f"TomTom HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise TrafficError("TomTom unreachable") from None


def _summary(reply: dict[str, Any]) -> dict[str, Any]:
    try:
        return reply["routes"][0]["summary"]
    except (KeyError, IndexError, TypeError):
        raise TrafficError("TomTom reply has no route summary") from None


def drive(listing_pin: tuple[float, float], work: tuple[float, float], key: str, *, peak_at: str, typical_at: str,
          get: Optional[Get] = None) -> dict[str, Any]:
    """Home -> work at the two departure times: a Drive's fields."""
    get = get or _http_get
    peak = _summary(get(route_url(listing_pin, work, peak_at, key)))
    typical = _summary(get(route_url(listing_pin, work, typical_at, key)))
    def seconds(s: dict[str, Any], *keys: str) -> Optional[float]:
        for k in keys:  # the first that's a real duration
            v = s.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0:
                return float(v)
        return None

    free_s = seconds(peak, "noTrafficTravelTimeInSeconds")
    # historic = TomTom's typical traffic for that weekday and hour
    peak_s = seconds(peak, "historicTrafficTravelTimeInSeconds", "travelTimeInSeconds")
    typical_s = seconds(typical, "historicTrafficTravelTimeInSeconds", "travelTimeInSeconds")
    if free_s is None and (peak_s is None or typical_s is None):  # v1.28: like bike(), a reply with no times is an error
        raise TrafficError("TomTom reply has no travel times")
    meters = peak.get("lengthInMeters")
    return {
        "km": round(meters / 1000, 2) if isinstance(meters, (int, float)) and not isinstance(meters, bool) and meters >= 0 else None,
        "free_flow_s": free_s, "peak_s": peak_s, "typical_s": typical_s,
        "source": f"TomTom typical traffic, departing {peak_at[11:16]} and {typical_at[11:16]}",
    }


def drives(pins: dict[str, list[float]], work: tuple[float, float], key: str, *, peak_at: str, typical_at: str,
           get: Optional[Get] = None, pause: float = 0.25) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """(drives by listing id, errors by listing id). One listing's error
    doesn't stop the rest; a missing drive is just a check later."""
    out: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for i, (lid, pin) in enumerate(pins.items()):
        try:
            out[lid] = drive((pin[0], pin[1]), work, key, peak_at=peak_at, typical_at=typical_at, get=get)
        except TrafficError as e:
            errors[lid] = str(e)
        if pause and i < len(pins) - 1:
            time.sleep(pause)  # TomTom's free tier allows 5 requests a second
    return out, errors


def bike(listing_pin: tuple[float, float], work: tuple[float, float], key: str, *, get: Optional[Get] = None) -> dict[str, Any]:
    """Home -> work by bicycle: the route's km, and TomTom's own seconds."""
    s = _summary((get or _http_get)(bike_url(listing_pin, work, key)))
    if not isinstance(s.get("lengthInMeters"), (int, float)) or s["lengthInMeters"] < 0:
        raise TrafficError("TomTom reply has no route length")
    t = s.get("travelTimeInSeconds")
    return {"km": round(s["lengthInMeters"] / 1000, 2), "tomtom_s": float(t) if isinstance(t, (int, float)) else None}


def bikes(pins: dict[str, list[float]], work: tuple[float, float], key: str, *, get: Optional[Get] = None,
          pause: float = 0.25) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """(bike routes by listing id, errors by listing id), like drives()."""
    out: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for i, (lid, pin) in enumerate(pins.items()):
        try:
            out[lid] = bike((pin[0], pin[1]), work, key, get=get)
        except TrafficError as e:
            errors[lid] = str(e)
        if pause and i < len(pins) - 1:
            time.sleep(pause)
    return out, errors


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Drive times with typical traffic (TomTom free tier)")
    ap.add_argument("pins")
    ap.add_argument("--to", required=True, help="work: lat,lng")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="car", choices=["car", "bicycle"])
    ap.add_argument("--signal", help="default: commute_minutes (car), bike_minutes (bicycle)")
    ap.add_argument("--day", default="tue", choices=sorted(DAYS))
    ap.add_argument("--peak", default="08:00")
    ap.add_argument("--typical", default="11:00")
    a = ap.parse_args(argv)
    lat, lng = (float(x) for x in a.to.split(","))
    pins = json.loads(Path(a.pins).read_text(encoding="utf-8"))
    if a.mode == "bicycle":
        got, errors = bikes(pins, (lat, lng), api_key())
        result: dict[str, Any] = {a.signal or "bike_minutes": {k: v["km"] for k, v in got.items()},
                                  "_tomtom_bicycle_s": {k: v["tomtom_s"] for k, v in got.items()}}
        what = "bike routes"
    else:
        got, errors = drives(pins, (lat, lng), api_key(), peak_at=next_departure(a.day, a.peak),
                             typical_at=next_departure(a.day, a.typical))
        result = {a.signal or "commute_minutes": got}
        what = "drives"
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(got)} {what}, {len(errors)} errors")
    for lid, err in errors.items():
        print(f"  {lid}: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
