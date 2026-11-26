"""
The setup screen's side of the helper (v1.25): read the preferences, save
them, and find a place's coordinates for a commute.

The extension's setup page (browser/options.html) edits the preferences
the way a user thinks about them -- cities, places to commute to, a budget,
must-haves and nice-to-haves -- and saves the whole file through here.
Nothing is written unless the result is a valid PreferenceSet; the file
is replaced in one step (a temp file, then a rename), and the previous
version is kept in preferences/.backups (the last 10).

Places are looked up with TomTom's search (the user's own key, which never
leaves this process) or, without a key, OpenStreetMap's Nominatim, one
lookup per click, as its usage policy asks. Only the text typed into the
setup page is sent.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import ValidationError

from . import traffic
from .scoring import PreferenceSet

KEEP_BACKUPS = 10
Get = Callable[[str], Any]

# What the setup page offers to add, by name. Each is a complete preference
# with a sensible starting point; the page changes the numbers.
CATALOG: list[dict[str, Any]] = [
    {"name": "price", "label": "Monthly rent (ILS)", "field": "price", "kind": "ranged", "relevance": 8,
     "ideal": 4000, "limit": 5000, "group": "basics"},
    {"name": "size", "label": "Size (m²)", "field": "size_m2", "kind": "at_least", "relevance": 7, "limit": 45, "group": "basics"},
    {"name": "rooms", "label": "Rooms", "field": "rooms", "kind": "at_least", "relevance": 7, "limit": 2, "group": "basics"},
    {"name": "not_ground_floor", "label": "Floor (not ground)", "field": "floor", "kind": "at_least", "relevance": 5,
     "limit": 1, "group": "basics"},
    {"name": "floor_without_elevator", "label": "Floor (max 2 without an elevator)", "field": "floor", "kind": "at_most",
     "relevance": 6, "limit": 2, "overrides": [{"when_signal": "elevator", "limit": 100}], "group": "basics"},
    {"name": "entry_timing", "label": "Move-in date (days from now)", "field": "signal:days_until_available", "kind": "ranged",
     "relevance": 4, "ideal": 0, "limit": 45, "group": "basics"},
    {"name": "mamad", "label": "Bomb shelter (mamad or building shelter)", "field": "signal:protected_space", "kind": "yes_no",
     "relevance": 8, "wants": True, "group": "features"},
    {"name": "no_roommates", "label": "Whole apartment (not a room share)", "field": "signal:roommate_listing", "kind": "yes_no",
     "relevance": 10, "wants": False, "group": "features"},
    {"name": "no_housing_unit", "label": "A home of its own (not a unit in someone's house)", "field": "signal:housing_unit",
     "kind": "yes_no", "relevance": 9, "wants": False, "group": "features"},
    {"name": "no_short_lease", "label": "Not a short stay (a few months, a sublet)", "field": "signal:short_lease",
     "kind": "yes_no", "relevance": 8, "wants": False, "group": "features"},
    {"name": "air_conditioning", "label": "Air conditioning", "field": "signal:air_conditioning", "kind": "yes_no",
     "relevance": 7, "wants": True, "group": "features"},
    {"name": "parking", "label": "Parking (own 3 > building 2 > street 1)", "field": "signal:parking_level", "kind": "ranged",
     "relevance": 5, "ideal": 3, "limit": 1, "group": "features"},
    {"name": "balcony", "label": "Balcony", "field": "signal:balcony", "kind": "yes_no", "relevance": 5, "wants": True, "group": "features"},
    {"name": "elevator", "label": "Elevator", "field": "signal:elevator", "kind": "yes_no", "relevance": 4, "wants": True, "group": "features"},
    {"name": "renovated", "label": "Renovated", "field": "signal:renovated", "kind": "yes_no", "relevance": 3, "wants": True, "group": "features"},
    {"name": "pets_allowed", "label": "Pets allowed", "field": "signal:pets_allowed", "kind": "yes_no", "relevance": 6, "wants": True,
     "group": "features"},
    {"name": "accessible", "label": "Accessible", "field": "signal:accessible", "kind": "yes_no", "relevance": 6, "wants": True,
     "group": "features"},
    {"name": "furniture", "label": "Furniture", "field": "signal:furniture", "kind": "has_items", "relevance": 3, "items": ["sofa"],
     "group": "features"},
    # v1.33: a listing without photos tends to be one to be careful with
    {"name": "has_photos", "label": "Has photos", "field": "signal:has_photos", "kind": "yes_no", "relevance": 4, "wants": True,
     "group": "features"},
]

# The furniture and appliances a listing can name (extraction/questions.py).
FURNITURE = {"sofa": "Sofa", "bed": "Bed", "table_chairs": "Table and chairs", "cabinet": "Storage furniture",
             "fridge": "Fridge", "washer": "Washing machine", "dryer": "Dryer", "dishwasher": "Dishwasher",
             "microwave": "Microwave", "tv": "TV"}

MODES = {"ebike": "E-bike", "bike": "Bike", "walk": "Walk", "car": "Car"}


class SetupError(ValueError):
    pass


def read(prefs_path: Path) -> dict[str, Any]:
    """The file as it is, plus what the page needs to edit it."""
    try:
        raw = json.loads(prefs_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = None
    except ValueError as e:
        raise SetupError(f"the preferences file isn't valid JSON: {e}") from None
    return {"prefs": raw, "catalog": CATALOG, "furniture": FURNITURE, "modes": MODES,
            "file": prefs_path.name, "places": _has_key()}


def _has_key() -> str:
    try:
        traffic.api_key()
        return "TomTom"
    except traffic.TrafficError:
        return "OpenStreetMap"


def _errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        where = ".".join(str(p) for p in err.get("loc", ()))
        out.append(f"{where}: {err.get('msg')}" if where else str(err.get("msg")))
    return out


def save(prefs_path: Path, data: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    """Validate, back up the old file, and write the new one in one step."""
    if not isinstance(data, dict):
        raise SetupError("prefs: a preferences object")
    try:
        PreferenceSet.model_validate(data)
    except ValidationError as e:
        return {"saved": False, "errors": _errors(e)}
    except ValueError as e:
        return {"saved": False, "errors": [str(e)]}
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if prefs_path.exists():
        old = prefs_path.read_text(encoding="utf-8")
        if old == text:
            return {"saved": True, "unchanged": True, "backup": None}
        folder = prefs_path.parent / ".backups"
        folder.mkdir(exist_ok=True)
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S-%f")
        backup = folder / f"{prefs_path.stem}-{stamp}.json"
        backup.write_text(old, encoding="utf-8")
        olds = sorted(folder.glob(f"{prefs_path.stem}-*.json"))
        for p in olds[:-KEEP_BACKUPS]:
            p.unlink()
    fd, tmp = tempfile.mkstemp(dir=prefs_path.parent, prefix=".prefs-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, prefs_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return {"saved": True, "unchanged": False, "backup": backup.name if backup else None}


# ---- places -------------------------------------------------------------------

TOMTOM_SEARCH = "https://api.tomtom.com/search/2/search/{q}.json?key={key}&countrySet=IL&limit=5&language=he-IL"
NOMINATIM = "https://nominatim.openstreetmap.org/search?{qs}"
USER_AGENT = "RentalMatcher/1.25 (a personal rental-search tool; one lookup per click)"


def _nominatim_get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "he,en"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SetupError(f"OpenStreetMap answered HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SetupError("OpenStreetMap couldn't be reached") from None


def _clean(q: Any) -> str:
    if not isinstance(q, str) or not q.strip():
        raise SetupError("q: the place to look up")
    q = re.sub(r"\s+", " ", q).strip()
    if len(q) > 120:
        raise SetupError("q: at most 120 characters")
    return q


def places(q: Any, get: Optional[Get] = None, nominatim_get: Optional[Get] = None) -> dict[str, Any]:
    """Up to 5 places in Israel for the text typed: [{label, lat, lng}]."""
    q = _clean(q)
    try:
        key = traffic.api_key()
    except traffic.TrafficError:
        key = None
    out: list[dict[str, Any]] = []
    reply = None
    if key:
        try:
            reply = (get or traffic._http_get)(TOMTOM_SEARCH.format(q=urllib.parse.quote(q, safe=""), key=key))
        except traffic.TrafficError:
            reply = None  # a key TomTom refuses (expired, no Search API): OpenStreetMap instead (v1.28)
    if isinstance(reply, dict):
        for r in reply.get("results", [])[:5]:
            pos, addr = r.get("position") or {}, r.get("address") or {}
            name = (r.get("poi") or {}).get("name")
            label = ", ".join(x for x in (name, addr.get("freeformAddress")) if x)
            if isinstance(pos.get("lat"), (int, float)) and isinstance(pos.get("lon"), (int, float)) and label:
                out.append({"label": label, "lat": round(pos["lat"], 6), "lng": round(pos["lon"], 6)})
        return {"source": "TomTom", "places": out}
    qs = urllib.parse.urlencode({"q": q, "format": "jsonv2", "countrycodes": "il", "limit": 5})
    reply = (nominatim_get or _nominatim_get)(NOMINATIM.format(qs=qs))
    for r in reply if isinstance(reply, list) else []:
        try:
            out.append({"label": str(r["display_name"]), "lat": round(float(r["lat"]), 6), "lng": round(float(r["lon"]), 6)})
        except (KeyError, TypeError, ValueError):
            continue
    return {"source": "OpenStreetMap", "places": out}


def relax(prefs_path: Path, body: Any) -> dict[str, Any]:
    """Loosen one preference the way a suggestion says ({name, change}), and save."""
    from .server import _apply  # the same change the suggestion was counted with
    if not isinstance(body, dict) or not isinstance(body.get("name"), str) or not isinstance(body.get("change"), dict):
        raise SetupError("a suggestion: {name, change}")
    change = {k: v for k, v in body["change"].items() if k in ("limit", "relevance", "by")}
    try:
        raw = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SetupError(f"the preferences file can't be read: {e}") from None
    if not any(p.get("name") == body["name"] for p in raw.get("preferences", [])):
        raise SetupError(f"no preference named {body['name']!r}")
    return save(prefs_path, _apply(raw, body["name"], change))



def reweigh(prefs_path: Path, body: Any) -> dict[str, Any]:
    """v1.32: the weights the compare-two tuning suggested ({weights: {name: 1-10}}), saved like any change (with a backup)."""
    weights = body.get("weights") if isinstance(body, dict) else None
    if not isinstance(weights, dict) or not weights:
        raise SetupError("weights: {criterion name: 1-10}")
    try:
        raw = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SetupError(f"the preferences file can't be read: {e}") from None
    by_name = {p.get("name"): p for p in raw.get("preferences", []) if isinstance(p, dict)}
    for name, w in weights.items():
        if name not in by_name:
            raise SetupError(f"no preference named {name!r}")
        if not isinstance(w, int) or isinstance(w, bool) or not 0 <= w <= 10:
            raise SetupError(f"{name}: a weight is a whole number 0-10")
        if by_name[name].get("relevance") == 10:
            raise SetupError(f"{name} is a must-have: its weight is locked (change it on the setup page)")  # v1.40
        by_name[name]["weight"] = w
    return save(prefs_path, raw)
