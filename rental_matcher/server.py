"""
The local helper the browser extension talks to (v1.22).

The extension reads Yad2 in the user's own browser; this decides what to
read and scores what was read, with the same code as everything else here
(funnel.plan, pipeline.run). It runs on the user's computer, listens on
127.0.0.1 only, and keeps nothing: every request carries its own data, and
the answer goes straight back to the extension.

    python -m rental_matcher.server [--prefs preferences/my.json] [--port 8765]

    GET  /config   the parts of the preferences a pull needs: the price cap
                   for the search, and each commute (anchor, routing profile)
    POST /plan     {rows, pin_routes?, drives?} -> which listings to open,
                   best first, and which are skipped and why. Without
                   pin_routes it also says which pins to route. Rows may
                   come from Yad2, Komo and Madlan: one apartment posted on
                   two of them is planned once (`also` names the other copy).
    POST /score    {extracts, pin_routes?, drives?} -> ranked results to show
    POST /drives   {signal, pins: {id: [lat, lng]}} -> TomTom drive times for
                   a car commute, with the user's own key (.tomtom_key), which
                   never leaves this process

Who may call it: browser extensions only. A web page's requests carry its
origin, and any origin other than an extension's is refused, so a site the
user visits can't use the helper. The Host header must be this machine.
Preferences are read on every request, so an edit to the file counts from
the next pull without a restart.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import re
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from . import calibrate, traffic
from .commute import car_times, valid_pin
from .funnel import pins_to_route, plan, route_key, search_filters, wait_seconds
from .pipeline import build_listing
from .scoring import PreferenceSet, rank
from .sources import dedupe, maybe_twins

PORT = 8765
MAX_BODY = 32 * 1024 * 1024
MAX_DRIVES = 25  # pins per /drives request: TomTom's free tier is 2 requests per listing
PROFILE = {"bike": "bike", "ebike": "bike", "walk": "foot", "car": "car"}  # OSRM's public profiles
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://")


class BadRequest(ValueError):
    pass


def config(prefs: PreferenceSet) -> dict[str, Any]:
    return {
        "search_filters": search_filters(prefs),
        "commutes": [{"signal": c.signal, "label": c.label, "mode": c.mode, "speed_kmh": c.speed,
                      "profile": PROFILE[c.mode], "anchor": [c.lat, c.lng]} for c in prefs.commutes],
        "tomtom": _has_tomtom(),
        "searches": [{"label": x.label, "label_he": x.label_he, "path": x.path, "hoods": x.hoods, "hood_names": x.hood_names,
                      "centers": [list(c) for c in x.centers], **({"elsewhere": x.elsewhere} if x.elsewhere else {})}
                     for x in prefs.searches if x.source == "yad2"],
        "prefs": pref_table(prefs),
    }


def _has_tomtom() -> bool:
    try:
        traffic.api_key()
        return True
    except traffic.TrafficError:
        return False


def _pin(x: dict[str, Any]) -> Optional[dict[str, float]]:
    """A row's or an extract's pin as a row-shaped {lat, lng}."""
    pin = valid_pin(x.get("lat"), x.get("lng"))
    if pin is None:
        c = x.get("coords") or {}
        pin = valid_pin(c.get("lat"), c.get("lon")) if isinstance(c, dict) else None
    return {"lat": pin[0], "lng": pin[1]} if pin else None  # (0, 0), NaN, out of range: no pin (v1.28)


def routes_by_id(items: list[dict[str, Any]], prefs: PreferenceSet, pin_routes: Optional[dict[str, Any]],
                 drives: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The pipeline's routes ({signal: {listing id: km or drive}}) from routes
    the browser got per pin ({signal: {pin key: {m, s}}}), plus TomTom drives
    by listing id, which take the place of OSRM's free-flow-only drive."""
    out: dict[str, dict[str, Any]] = {}
    for c in prefs.commutes:
        per_pin = (pin_routes or {}).get(c.signal) or {}
        per_id: dict[str, Any] = {}
        for x in items:
            if x.get("approx"):
                continue  # a neighborhood's middle, not the apartment: its commute stays an estimate
            pin = _pin(x)
            r = per_pin.get(route_key(pin)) if pin else None
            if not isinstance(r, dict) or any(isinstance(r.get(k), bool) or not isinstance(r.get(k), (int, float))
                                              or not math.isfinite(r[k]) for k in ("m", "s")):
                continue  # True/False aren't metres (v1.28), nor is NaN
            if r["m"] < 0 or r["s"] < 0:
                raise BadRequest(f"a route can't be negative: {r}")
            if c.mode == "car":
                per_id[str(x["id"])] = {"km": round(r["m"] / 1000, 2), "free_flow_s": float(r["s"]), "source": "OSRM, no traffic"}
            else:
                per_id[str(x["id"])] = {"km": round(r["m"] / 1000, 3), "source": "OSRM"}
        for lid, d in ((drives or {}).get(c.signal) or {}).items():
            if c.mode == "car" and isinstance(d, dict):
                per_id[str(lid)] = d
        out[c.signal] = per_id
    return out


def _rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("rows")
    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("id") for r in rows):
        raise BadRequest("rows: a list of search rows, each with an id")
    return rows


def _reason_group(reason: str) -> str:
    """'Floor (not ground): 0 ...' -> 'Floor (not ground)'; a listing with no usable price -> one group."""
    if "no usable price" in reason or "has no listing data" in reason:
        return "No price given"
    return reason.split(":")[0]


REJECTED = "You rejected it"


def _skip_ids(body: dict[str, Any]) -> set[str]:
    skip = body.get("skip") or []
    if not isinstance(skip, list) or not all(isinstance(i, str) for i in skip):
        raise BadRequest("skip: a list of listing ids")
    return set(skip)


def do_plan(body: dict[str, Any], prefs: PreferenceSet) -> dict[str, Any]:
    skip = _skip_ids(body)
    prefer = body.get("prefer") or []
    if not isinstance(prefer, list) or not all(isinstance(i, str) for i in prefer):
        raise BadRequest("prefer: a list of listing ids")
    rows, also = dedupe(_rows(body), prefer)
    # v1.38: "Not for me" on any copy of an apartment is "Not for me" on the copy shown
    skip = skip | {kid for kid, others in also.items() if any(o["id"] in skip for o in others)}
    # an approximate pin (a neighborhood's middle) can't rule a listing out on its commute
    rows = [{k: v for k, v in r.items() if k not in ("lat", "lng")} if r.get("approx") else r for r in rows]
    rejected = [str(r["id"]) for r in rows if str(r["id"]) in skip]
    rows = [r for r in rows if str(r["id"]) not in skip]  # the user said no: not opened, not routed
    now = datetime.now(timezone.utc)
    # routed once the browser has answered, even with nothing to route ({}) (v1.28: {} was "not yet")
    routed = body.get("pin_routes") is not None or body.get("drives") is not None
    routes = routes_by_id(rows, prefs, body.get("pin_routes"), body.get("drives")) if routed else None
    p = plan(rows, prefs, routes=routes, budget=body.get("budget"), pulled_at=now)
    skipped = dict(p.skipped)
    for i in rejected:
        skipped[i] = [REJECTED]
    why = Counter(_reason_group(reasons[0]) for reasons in skipped.values() if reasons)
    out: dict[str, Any] = {
        "rows": p.rows + len(rejected), "fetch": p.fetch, "later": p.later, "skipped": skipped,
        "skipped_by_reason": dict(why.most_common()),
        "skipped_by_topic": _by_topic(skipped, prefs),
        "estimate_s": round(wait_seconds(p.rows, len(p.fetch), routed=False), 1),
        "also": also,
        "maybe": maybe_twins(rows),  # v1.63: the same address on another site, the floor or size disagreeing: linked, not merged
    }
    if not routed:
        pins = pins_to_route(rows, prefs, pulled_at=now)
        out["pins"] = pins  # {pin key: [lat, lng]}: route these, then plan again with pin_routes
    return out


def _by_topic(skipped: dict[str, list[str]], prefs: PreferenceSet) -> dict[str, int]:
    """How many were left out for each reason, by preference name ("price"),
    or "rejected" / "other" (not a home, no price)."""
    labels = sorted(((p.label, p.name) for p in prefs.preferences), key=lambda t: -len(t[0]))
    out: Counter = Counter()
    for reasons in skipped.values():
        first = reasons[0] if reasons else ""
        if first == REJECTED:
            out["rejected"] += 1
            continue
        out[next((name for label, name in labels if first.startswith(label + ":")), "other")] += 1
    return dict(out.most_common())


# ---- how to see more listings (v1.26) -------------------------------------------------

def _upper(p: Any) -> bool:
    return p.limit is not None and (p.kind == "at_most" or (p.kind == "ranged" and p.ideal is not None and p.ideal < p.limit))


def _relaxations(prefs: PreferenceSet) -> list[tuple[str, dict[str, Any]]]:
    """Each way to loosen one thing that hides listings: (preference name, change)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for p in prefs.preferences:
        hides = p.dealbreaker or p.tolerance is not None
        if not hides or p.kind == "has_items":
            continue
        t = topic(p, prefs)["topic"]
        if p.kind == "yes_no" or (t == "parking" and p.limit):
            out.append((p.name, {"relevance": 7} if p.kind == "yes_no" else {"limit": 0}))
            continue
        if p.limit is None:
            continue
        steps = {"rent": (250, 500), "rent_min": (250, 500), "commute": (3, 5), "size": (5, 10), "rooms": (0.5, 1), "floor_ground": (1,),
                 "floor_high": (1, 2), "movein": (15, 30)}.get(t, ())
        for d in steps:
            new = p.limit + d if _upper(p) else max(0, p.limit - d)
            out.append((p.name, {"limit": new, "by": d}))
    return out


def _apply(raw: dict[str, Any], name: str, change: dict[str, Any]) -> dict[str, Any]:
    """The preferences file with one preference loosened."""
    data = json.loads(json.dumps(raw))
    for p in data["preferences"]:
        if p["name"] != name:
            continue
        if "relevance" in change:
            p["relevance"] = change["relevance"]
        if "limit" in change:
            by = change.get("by")
            if by and p.get("overrides"):  # the budget with a balcony moves with the budget
                up = p.get("ideal") is None or p["ideal"] < p["limit"] if p.get("kind") == "ranged" else p.get("kind") == "at_most"
                for o in p["overrides"]:
                    if o.get("limit") is not None:
                        o["limit"] = o["limit"] + by if up else o["limit"] - by
            p["limit"] = change["limit"]
    return data


def do_suggest(body: dict[str, Any], prefs: PreferenceSet, raw: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Ways to loosen one preference and how many more listings each would
    let through: the rows left out before opening, and the listings hidden
    after reading. Counted by running the same funnel and scoring again."""
    rows = _rows(body)
    skip = _skip_ids(body)
    rows = [r for r in rows if str(r["id"]) not in skip]
    extracts = [x for x in (body.get("extracts") or []) if isinstance(x, dict) and x.get("id") and str(x["id"]) not in skip]
    now = datetime.now(timezone.utc)
    raw = raw if raw is not None else prefs.model_dump(exclude_none=True)
    routes = routes_by_id(rows, prefs, body.get("pin_routes"), body.get("drives")) if body.get("pin_routes") else None
    base = plan(rows, prefs, routes=routes, pulled_at=now)
    left_out = [r for r in rows if str(r["id"]) in base.skipped]

    def shown(pr: PreferenceSet) -> set[str]:
        if not extracts:
            return set()
        r = routes_by_id(extracts, pr, body.get("pin_routes"), body.get("drives"))
        listings = []
        for x in extracts:
            try:
                listings.append(build_listing(x, pr, routes=r, pulled_at=now))
            except ValueError:
                continue
        return {s.listing_id for s in rank(listings, pr) if not s.excluded}

    shown0 = shown(prefs)
    found: dict[str, dict[str, Any]] = {}
    for name, change in _relaxations(prefs):
        try:
            relaxed = PreferenceSet.model_validate(_apply(raw, name, change))
        except Exception:  # noqa: BLE001 -- a change the model refuses isn't offered
            continue
        more_rows = len(plan(left_out, relaxed, routes=routes, pulled_at=now).fetch) if left_out else 0
        more_read = len(shown(relaxed) - shown0)
        n = more_rows + more_read
        if n < 2:
            continue
        p = next(x for x in prefs.preferences if x.name == name)
        best = found.get(name)
        if best is None or n > best["count"] * 1.5:  # the smaller step, unless the bigger one finds many more
            found[name] = dict(topic(p, prefs), name=name, change={k: v for k, v in change.items() if k != "by"},
                               by=change.get("by"), was=p.limit, now=change.get("limit"), count=n,
                               to_check=more_rows, shown=more_read)
    out = sorted(found.values(), key=lambda s: -s["count"])[:4]
    return {"suggestions": out}


MODE_LABEL = {"bike": "Bike", "ebike": "E-bike", "walk": "Walk", "car": "Drive"}
PARKING_NAMES = {3.0: "its own space", 2.0: "building parking", 1.0: "street parking only", 0.0: "no parking"}


def _odds_text(u: Any) -> Optional[str]:
    """What listings like it turned out to have, in words, or None without a measurement."""
    if not u.odds:
        return None
    if all(isinstance(v, bool) for v, _ in u.odds):
        p = dict(u.odds).get(True, 0.0)
        return f"about {round(100 * p)}% of listings like it have it (from {u.n} labeled)"
    if u.signals == ["parking_level"]:
        parts = [f"{PARKING_NAMES.get(float(v), v)} {round(100 * p)}%" for v, p in sorted(u.odds, key=lambda t: -t[1])]
        return f"listings like it: {', '.join(parts)} (from {u.n} labeled)"
    return None


# What a listing confirms, as the bubbles on its card: (signal, value) -> words.
FEATURE_WORDS: dict[str, Any] = {
    "air_conditioning": {True: "Air conditioning"},
    "mamad": {True: "Mamad"},
    "building_shelter": {True: "Building shelter"},
    "balcony": {True: "Balcony", False: "No balcony"},
    "elevator": {True: "Elevator", False: "No elevator"},
    "parking_level": {3.0: "Own parking", 2.0: "Building parking", 1.0: "Street parking", 0.0: "No parking"},
    "renovated": {True: "Renovated", False: "Not renovated"},
    "pets_allowed": {True: "Pets allowed"},
    "accessible": {True: "Accessible"},
    "window_bars": {True: "Window bars"},
    "roommate_listing": {True: "Room in a share", False: "Whole apartment"},
    "housing_unit": {True: "A unit in someone's home"},
    "short_lease": {True: "A short stay"},
    "furniture_for_sale": {True: "Furniture for sale, not included"},
    "no_broker_fee": {True: "Agency listing, no broker fee"},  # v1.53
    "no_parking_space": {True: "No parking space with it"},
    "suits_roommates": {True: "Suits roommates"},
    "apartment_type": {"garden": "Garden apartment", "roof": "Rooftop", "house": "House", "studio": "Studio"},
    # v1.54: every box on the site's form has a bubble (owner ruling: a ticked box is the poster showing you)
    "floor_shelter": {True: "Floor safe room (ממ\"ק)"},
    "solar_heater": {True: "Solar water heater"},
    "tornado_ac": {True: "Tornado A/C"},
    "storage": {True: "Storage room"},
    "kosher_kitchen": {True: "Kosher kitchen"},
    "pandor_doors": {True: "Pandor doors"},  # v1.55
}
ITEM_WORDS = {"sofa": "Sofa", "bed": "Bed", "table_chairs": "Table and chairs", "cabinet": "Storage furniture",
              "fridge": "Fridge", "washer": "Washing machine", "dryer": "Dryer", "dishwasher": "Dishwasher",
              "microwave": "Microwave", "tv": "TV", "closets": "Closets", "oven_stove": "Oven / stove",
              "says_furnished": "Furnished", "says_partly_furnished": "Partly furnished", "says_unfurnished": "Unfurnished",
              "says_equipped": "Appliances"}
# Signals that feed another one's preference: a mamad or a building shelter is a protected space.
FEEDS = {"mamad": "protected_space", "building_shelter": "protected_space", "floor_shelter": "protected_space"}


def _special_feature(signal: str, v: Any, x: Any) -> Optional[Any]:
    """v1.53: bubbles that need more than one signal or carry a number: ({key...}, words), False
    to show nothing for this signal, or None when it isn't one of these."""
    if signal == "parking_at_least":
        return False  # said by parking_level's own bubble
    if signal == "parking_level":
        at_least = x.signals.get("parking_at_least")
        if at_least is not None and at_least.status.value == "confirmed" and at_least.value is True:
            return {"key": "parking_any"}, "Parking (whose isn't said)"
        return None
    if signal == "public_shelter_m" and isinstance(v.value, (int, float)):
        return {"key": "public_shelter", "m": float(v.value)}, f"Public shelter {v.value:g} m away"
    if signal == "furniture_box":
        # v1.54, owner ruling: posters tick "ריהוט" for one chair, so the text is stronger than the box. When the
        # text says what's there (or that it's unfurnished), that's the card; when it doesn't, the box shows
        # as a maybe, never a match (merge leaves furniture unconfirmed, so no furniture must-have counts it)
        said = x.signals.get("furniture")
        if v.value is not True or (said is not None and said.status.value == "confirmed"):
            return False
        return {"key": "maybe_furnished"}, "Might be furnished (Yad2 box, no items listed)"
    return None


def _shelter_note(x: Any) -> Optional[dict[str, Any]]:
    """v1.53: nothing (no box on Yad2's form, no word in the text) says the flat has a safe room or the
    building a shelter: the card says so (pipeline._form_absences), next to Yad2's public-shelter distance."""
    own = x.signals.get("protected_space")
    if own is not None and own.status.value == "confirmed" and own.value is False:
        return {"key": "no_building_shelter", "tone": "info"}
    return None


def _features(s: Any, x: Any, prefs: PreferenceSet) -> list[dict[str, str]]:
    """What the listing confirms, each with how it sits with the user's
    preferences: "good" (meets one), "weak" (within the limit, but not what
    was hoped for), "bad" (fails one: the listing is hidden for it) or
    "info" (no preference reads it)."""
    status = {r.name: (r.status, r.label) for r in s.results}
    by_signal: dict[str, str] = {}
    for p in prefs.preferences:
        if p.field.startswith("signal:"):
            by_signal.setdefault(p.field.removeprefix("signal:"), p.name)

    def tone(signal: str) -> str:
        name = by_signal.get(signal) or by_signal.get(FEEDS.get(signal, ""))
        st, label = status.get(name, (None, None)) if name else (None, None)
        if st is None or st == "unknown":
            return "info"
        if any(r.startswith(label) for r in s.exclusion_reasons):
            return "bad"
        return "good" if st == "met" else "weak"

    out: list[dict[str, str]] = []
    for signal, v in x.signals.items():
        if v.status.value != "confirmed" or v.value is None:
            continue
        if signal == "furniture" and isinstance(v.value, list):
            for item in v.value:
                word = ITEM_WORDS.get(item)
                if word:
                    wanted = any(p.kind == "has_items" and item in (p.items or []) for p in prefs.preferences)
                    out.append({"label": word, "tone": "good" if wanted else "info"})
            continue
        if signal == "days_until_available" and isinstance(v.value, (int, float)):
            out.append({"label": "Available now" if v.value <= 0 else f"Available in {v.value:g} days", "tone": tone(signal)})
            continue
        if (special := _special_feature(signal, v, x)) is not None:
            if special:
                out.append({"label": special[1], "tone": tone(signal)})
            continue
        words = FEATURE_WORDS.get(signal, {})
        key = float(v.value) if signal == "parking_level" and isinstance(v.value, (int, float)) else v.value
        try:
            word = words.get(key)
        except TypeError:
            word = None
        if word:
            out.append({"label": word, "tone": tone(signal)})
    if _shelter_note(x) is not None:
        out.append({"label": "No safe room or building shelter marked", "tone": "info"})
    order = {"good": 0, "weak": 1, "bad": 2, "info": 3}
    return sorted(out, key=lambda f: order[f["tone"]])


SIGNAL_NAMES = {"parking_level": "Parking", "protected_space": "A shelter", "roommate_listing": "Whole apartment or room share",
                "days_until_available": "The entry date", "furniture": "Furniture", "air_conditioning": "Air conditioning",
                "balcony": "A balcony", "elevator": "An elevator", "renovated": "Renovation", "pets_allowed": "Pets",
                "accessible": "Accessibility", "mamad": "A mamad", "building_shelter": "A building shelter",
                "housing_unit": "Whether it's a unit in someone's home", "short_lease": "How long the lease is"}


def _what(u: Any, prefs: PreferenceSet) -> str:
    """What an unknown is, in words: "A balcony", not the preferences it moves."""
    names = []
    for sig in u.signals:
        if sig.startswith("?"):
            p = next((p for p in prefs.preferences if p.name == sig[1:]), None)
            names.append(p.label.split(" (")[0] if p else sig[1:])
        else:
            c = next((c for c in prefs.commutes if c.signal == sig), None)
            names.append(f"The commute to {c.label.split(' (')[0]}" if c else SIGNAL_NAMES.get(sig, sig.replace("_", " ").capitalize()))
    return " and ".join(dict.fromkeys(names))


# ---- the card as data (v1.26): the extension words it, in English or Hebrew --------

FIELD_TOPIC = {"price": "rent", "size_m2": "size", "rooms": "rooms",
               "signal:parking_level": "parking", "signal:balcony": "balcony", "signal:elevator": "elevator",
               "signal:air_conditioning": "ac", "signal:protected_space": "shelter", "signal:mamad": "shelter",
               "signal:building_shelter": "shelter", "signal:roommate_listing": "whole", "signal:days_until_available": "movein",
               "signal:renovated": "renovated", "signal:furniture": "furniture", "signal:pets_allowed": "pets",
               "signal:accessible": "accessible", "signal:has_photos": "photos", "signal:housing_unit": "unit", "signal:short_lease": "lease"}


def topic(p: Any, prefs: PreferenceSet) -> dict[str, Any]:
    """What a preference is about, for words in any language: a topic key,
    and for a commute the place (the user's own name for it)."""
    for c in prefs.commutes:
        if p.field == f"signal:{c.signal}":
            return {"topic": "commute", "place": c.label.split(" (")[0], "mode": c.mode}
    if p.field == "floor":
        return {"topic": "floor_ground" if p.kind == "at_least" else "floor_high"}
    if p.field == "price" and p.kind == "at_least":
        return {"topic": "rent_min"}  # v1.30: the low end of the budget
    return {"topic": FIELD_TOPIC.get(p.field, "custom"), "label": p.label}


def pref_table(prefs: PreferenceSet) -> dict[str, Any]:
    """Every preference by name: its topic, and what it asks for."""
    out = {}
    for p in prefs.preferences:
        out[p.name] = dict(topic(p, prefs), must=p.dealbreaker, kind=p.kind, limit=p.limit, ideal=p.ideal,
                           tolerance=p.tolerance, items=p.items, wants=p.wants)
    return out


FEATURE_KEYS: dict[str, Any] = {
    "air_conditioning": {True: "ac"}, "mamad": {True: "mamad"}, "building_shelter": {True: "building_shelter"},
    "balcony": {True: "balcony", False: "no_balcony"}, "elevator": {True: "elevator", False: "no_elevator"},
    "parking_level": {3.0: "parking_own", 2.0: "parking_building", 1.0: "parking_street", 0.0: "parking_none"},
    "renovated": {True: "renovated", False: "not_renovated"}, "pets_allowed": {True: "pets"}, "accessible": {True: "accessible"},
    "window_bars": {True: "bars"}, "roommate_listing": {True: "room_share", False: "whole"}, "housing_unit": {True: "housing_unit"}, "short_lease": {True: "short_lease"},
    "furniture_for_sale": {True: "furniture_for_sale"}, "no_broker_fee": {True: "agency_no_fee"}, "no_parking_space": {True: "no_parking_space"},
    "suits_roommates": {True: "suits_roommates"}, "has_photos": {False: "no_photos"}, "apartment_type": {"garden": "garden", "roof": "roof", "house": "house", "studio": "studio"},
    "floor_shelter": {True: "floor_shelter"}, "solar_heater": {True: "solar_heater"}, "tornado_ac": {True: "tornado_ac"},
    "storage": {True: "storage"}, "kosher_kitchen": {True: "kosher_kitchen"},  # v1.54
    "pandor_doors": {True: "pandor_doors"},  # v1.55
}


def _feature_keys(features: list[dict[str, str]], s: Any, x: Any, prefs: PreferenceSet) -> list[dict[str, Any]]:
    """The same bubbles as _features, keyed for translation."""
    tone_of = {f["label"]: f["tone"] for f in features}
    out = []
    for signal, v in x.signals.items():
        if v.status.value != "confirmed" or v.value is None:
            continue
        if signal == "furniture" and isinstance(v.value, list):
            for item in v.value:
                if item in ITEM_WORDS:
                    out.append({"key": f"item_{item}", "tone": tone_of.get(ITEM_WORDS[item], "info")})
            continue
        if signal == "days_until_available" and isinstance(v.value, (int, float)):
            word = "Available now" if v.value <= 0 else f"Available in {v.value:g} days"
            out.append({"key": "available", "days": float(v.value), "tone": tone_of.get(word, "info")})
            continue
        if (special := _special_feature(signal, v, x)) is not None:
            if special:
                out.append({**special[0], "tone": tone_of.get(special[1], "info")})
            continue
        words = FEATURE_KEYS.get(signal, {})
        key = float(v.value) if signal == "parking_level" and isinstance(v.value, (int, float)) else v.value
        try:
            k = words.get(key)
        except TypeError:
            k = None
        w = FEATURE_WORDS.get(signal, {}).get(key) if k else None
        if k:
            out.append({"key": k, "tone": tone_of.get(w, "info")})
    if (note := _shelter_note(x)) is not None:
        out.append(note)
    order = {"good": 0, "weak": 1, "bad": 2, "info": 3}
    return sorted(out, key=lambda f: order[f["tone"]])


def _minutes_from(evidence: Optional[str]) -> Optional[float]:
    m = re.search(r"about ([\d.]+) min", evidence or "")
    return float(m.group(1)) if m else None


def _commute_list(x: Any, prefs: PreferenceSet) -> list[dict[str, Any]]:
    out = []
    for c in prefs.commutes:
        v = x.signals.get(c.signal)
        if v is None:
            continue
        confirmed = v.status.value == "confirmed" and isinstance(v.value, (int, float))
        trip = {"signal": c.signal, "place": c.label.split(" (")[0], "mode": c.mode,
                "minutes": float(v.value) if confirmed else None, "about": None if confirmed else _minutes_from(v.evidence),
                "traffic": "traffic" in (v.evidence or "")}
        # v1.37: a drive is a range, not one number: the usual time and rush hour's
        car = car_times(v.evidence) if c.mode == "car" else None
        if car:
            trip.update(car)
            if trip["about"] is None and not confirmed:
                trip["about"] = float(car["usual"])
        out.append(trip)
    return out


def _ask_about(signals: list[str], prefs: PreferenceSet) -> list[str]:
    """What to ask about, as preference names: the unstated facts themselves
    (a balcony), not every preference they move (the budget with a balcony)."""
    out = []
    for sig in signals:
        if sig.startswith("?"):
            out.append(sig[1:])
            continue
        p = next((p for p in prefs.preferences if p.field == f"signal:{sig}"), None)
        if p is None and sig in FEEDS:
            p = next((p for p in prefs.preferences if p.field == f"signal:{FEEDS[sig]}"), None)
        if p is not None:
            out.append(p.name)
    return list(dict.fromkeys(out))


def _fit(expected: Optional[float]) -> str:
    if expected is None:
        return "basic"
    return "great" if expected >= 70 else "good" if expected >= 55 else "fair" if expected >= 40 else "basic"


def _view(s: Any, x: Any, prefs: PreferenceSet, approx: bool = False) -> dict[str, Any]:
    commutes = {}
    for c in prefs.commutes:
        v = x.signals.get(c.signal)
        if v is None:
            continue
        place = c.label.split(" (")[0]
        confirmed = v.status.value == "confirmed" and v.value is not None
        commutes[c.signal] = {"value": v.value, "status": v.status.value, "evidence": v.evidence,
                              "short": f"{MODE_LABEL[c.mode]} to {place}: {v.value:g} min" if confirmed else None}
    by_label = {p.label: p.name for p in prefs.preferences}
    features = _features(s, x, prefs)
    days = x.signals.get("days_until_available")
    return {
        # v1.26, for the cards: data, worded by the extension in the user's language
        "fit": _fit(s.match_expected), "source": x.source.value,
        # v1.27: Komo gives no pin; its place (and so its commute) may be the neighborhood's middle
        "approx": approx,
        "feature_keys": _feature_keys(features, s, x, prefs),
        "notes": [n.model_dump() for n in s.notes],
        "asks": [{"names": [by_label.get(lbl, lbl) for lbl in u.labels], "signals": u.signals, "worth": round(u.worth, 1),
                  "about": _ask_about(u.signals, prefs)} for u in s.unknowns],
        "risks": [{"name": by_label.get(label, label), "pct": round(100 * p)} for label, p in s.fail_risk_parts],
        "trips": _commute_list(x, prefs),
        "available_in": float(days.value) if days and days.status.value == "confirmed" and isinstance(days.value, (int, float)) else None,
        "match_likely_low": s.match_likely_low, "match_likely_high": s.match_likely_high,
        "fail_risk": s.fail_risk, "fail_risk_from": s.fail_risk_from,
        "risk_parts": [{"label": label.split(" (")[0], "full": label, "pct": round(100 * p)} for label, p in s.fail_risk_parts],
        "features": features,
        "unknowns": [{"labels": u.labels, "what": _what(u, prefs), "signals": u.signals, "worth": u.worth, "odds": _odds_text(u)}
                     for u in s.unknowns],
        # Yad2's bare token (as always); "komo:N" / "madlan:X" for the others
        "id": x.source_listing_id if x.source.value == "yad2" else x.id,
        "url": str(x.links[0].url) if x.links else None, "price": x.price.amount,
        # v1.28: the monthly fees the text gives (0: in the rent; None: not said)
        "costs": ({"vaad_bayit": x.recurring_costs.vaad_bayit_monthly, "arnona": x.recurring_costs.arnona_monthly,
                    "vaad_bayit_max": x.recurring_costs.vaad_bayit_monthly_max, "arnona_max": x.recurring_costs.arnona_monthly_max}
                  if x.recurring_costs else None),
        # v1.57 (owner ruling): what Yad2 shows as "סה״כ תשלום חודשי": the rent plus the building fee plus the arnona
        # a month, only when both fees are known (in the rent counts as 0)
        "total_monthly": _total_monthly(x),
        "rooms": x.rooms, "floor": x.floor, "size_m2": x.size_m2, "street": x.area.street,
        # v1.64: the floor a site's form gave but we don't trust (Komo's "14 of 14" is often the building's height)
        "floor_said": _floor_said(x),
        "neighborhood": x.area.neighborhood, "city": x.area.city, "listed_by": x.listed_by.value if x.listed_by else None,
        "excluded": s.excluded, "reasons": s.exclusion_reasons, "flags": s.flags, "checks": s.checks,
        "match_low": s.match_low, "match_high": s.match_high, "match_expected": s.match_expected, "commutes": commutes,
        # v1.32: each criterion's expected satisfaction, for tuning the weights from the user's picks
        "sat": s.sat,
    }


def _floor_said(x: Any) -> Optional[int]:
    sig = (x.signals or {}).get("floor_said")
    return int(sig.value) if x.floor is None and sig is not None and isinstance(sig.value, (int, float)) else None


def _total_monthly(x: Any) -> Optional[float]:
    """v1.57: the rent, the building fee and the arnona (a month) together, as Yad2's own "סה״כ תשלום חודשי"
    box adds them (4,300 + 100 + 500/2 = 4,650 on a live Ashdod listing, Nov 2). None unless both fees are known."""
    c = x.recurring_costs
    if c is None or c.vaad_bayit_monthly is None or c.arnona_monthly is None or x.price is None or c.vaad_bayit_monthly_max is not None or c.arnona_monthly_max is not None:
        return None
    return round(x.price.amount + c.vaad_bayit_monthly + c.arnona_monthly)


def do_score(body: dict[str, Any], prefs: PreferenceSet) -> dict[str, Any]:
    extracts = body.get("extracts")
    if not isinstance(extracts, list) or not all(isinstance(x, dict) and x.get("id") for x in extracts):
        raise BadRequest("extracts: a list of listing extracts (Yad2, Komo, Madlan), each with an id")
    now = datetime.now(timezone.utc)
    routes = routes_by_id(extracts, prefs, body.get("pin_routes"), body.get("drives"))
    listings, skipped = [], []
    approx = {str(x.get("id")) for x in extracts if x.get("approx")}  # "komo:N", the listing's own id
    for x in extracts:
        try:
            listings.append(build_listing(x, prefs, routes=routes, pulled_at=now))
        except ValueError as e:
            skipped.append({"id": str(x.get("id")), "why": str(e)})
    ranked = rank(listings, prefs)
    by_id = {x.id: x for x in listings}
    results = [_view(s, by_id[s.listing_id], prefs, s.listing_id in approx) for s in ranked]
    return {"shown": sum(not r["excluded"] for r in results), "hidden": sum(r["excluded"] for r in results),
            "results": results, "skipped": skipped}


def do_calibrate(body: dict[str, Any], prefs: PreferenceSet) -> dict[str, Any]:
    """v1.32: the user's picks between two listings -> how well the weights agree, and better ones if there are."""
    try:
        return calibrate.tune(prefs, body)
    except calibrate.CalibrationError as e:
        raise BadRequest(str(e)) from None


def do_drives(body: dict[str, Any], prefs: PreferenceSet, get: Optional[traffic.Get] = None) -> dict[str, Any]:
    c = next((c for c in prefs.commutes if c.signal == body.get("signal") and c.mode == "car"), None)
    if c is None:
        raise BadRequest("signal: a car commute in the preferences")
    pins = body.get("pins")
    if not isinstance(pins, dict) or not pins:
        raise BadRequest("pins: {listing id: [lat, lng]}")
    if len(pins) > MAX_DRIVES:
        raise BadRequest(f"at most {MAX_DRIVES} pins a request")
    if not all(isinstance(v, (list, tuple)) and len(v) == 2 and valid_pin(v[0], v[1]) for v in pins.values()):
        raise BadRequest("pins: {listing id: [lat, lng]}, each a real place")  # v1.28: was a 500
    try:
        key = traffic.api_key()
    except traffic.TrafficError:
        return {"available": False, "drives": {}, "errors": {}}
    drives, errors = traffic.drives({str(k): v for k, v in pins.items()}, (c.lat, c.lng), key,
                                    peak_at=traffic.next_departure("tue", "08:00"),
                                    typical_at=traffic.next_departure("tue", "11:00"), get=get)
    return {"available": True, "drives": drives, "errors": errors}


def make_handler(prefs_path: Path, get: Optional[traffic.Get] = None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RentalMatcher"

        def log_message(self, fmt: str, *args: Any) -> None:  # one short line, never a body
            sys.stderr.write(f"{self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}\n")

        def _send(self, code: int, payload: Any) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            origin = self.headers.get("Origin")
            if origin and not origin.startswith(EXTENSION_ORIGINS):
                self._send(403, {"error": "only the Rental Matcher extension may call this"})
                return False
            port = self.server.server_address[1]
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:  # no DNS rebinding
                self._send(403, {"error": "wrong host"})
                return False
            return True

        def do_OPTIONS(self) -> None:  # no CORS for web pages: a preflight is always refused
            self._send(403, {"error": "only the Rental Matcher extension may call this"})

        def do_GET(self) -> None:
            if not self._allowed():
                return
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if self.path == "/config":
                return self._handle(lambda prefs: config(prefs))
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._allowed():
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "Content-Length must be a number"})
            if n < 0:  # v1.28: a negative length read to the end, past MAX_BODY
                return self._send(400, {"error": "Content-Length must be a number"})
            if n > MAX_BODY:
                return self._send(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "a JSON object, please"})
            if self.path in ("/prefs", "/saveprefs", "/places", "/relax", "/reweigh"):
                from .native import answer  # the same setup handling as the native host
                r = answer({"path": self.path, "body": body}, prefs_path, get)
                return self._send(r["status"], r["body"])
            handlers = {"/plan": do_plan, "/score": do_score, "/drives": lambda b, p: do_drives(b, p, get), "/calibrate": do_calibrate}
            h = handlers.get(self.path)
            if h is None:
                return self._send(404, {"error": "not found"})
            self._handle(lambda prefs: h(body, prefs))

        def _handle(self, f: Any) -> None:
            try:
                prefs = PreferenceSet.load(prefs_path)
            except Exception as e:  # noqa: BLE001 -- say what's wrong with the file, keep serving
                return self._send(500, {"error": f"the preferences file can't be read: {e}"})
            try:
                self._send(200, f(prefs))
            except BadRequest as e:
                self._send(400, {"error": str(e)})
            except traffic.TrafficError as e:  # built without the URL: no key in it
                self._send(502, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 -- answer, don't drop the connection
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def serve(prefs_path: Path, port: int = PORT, get: Optional[traffic.Get] = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(prefs_path, get))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Rental Matcher's local helper for the browser extension")
    ap.add_argument("--prefs", default="preferences/my.json")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args(argv)
    prefs_path = Path(a.prefs).resolve()
    PreferenceSet.load(prefs_path)  # a broken file is reported now, not on the first pull
    httpd = serve(prefs_path, a.port)
    print(f"Rental Matcher helper on http://127.0.0.1:{a.port} (preferences: {prefs_path.name}).")
    print("Leave this window open while you pull; Ctrl+C stops it.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
