"""
Listings from several sites, as one list: the same apartment posted on
Yad2 and on Komo (or Madlan) is shown once, with links to every copy and
the cheapest one first.

Two rows are the same apartment only when all of these hold (v1.29):
- the city, the number of rooms and the floor are the same, and both
  give them;
- both give a size, within 3 m² (sites round differently);
- the rents are within 15% of each other (one owner can ask different
  rents on different sites, and finding the cheaper copy is the point);
- the place agrees, and at least one place fact can be compared: the
  same neighborhood (named loosely, "שכונת התקווה" = "התקווה"), the same
  street when both give one, and pins within 300 m when both have a real
  one (Komo's approximate pins don't count).

v1.27 matched on the city, the exact rent, the rooms and one of the size
or floor. A Yad2 listing in Agrobank with no size could then take a Komo
listing from another neighborhood as its twin, and its "Komo" link opened
a different apartment. Near misses stay apart: showing a listing twice
is a smaller harm than sending the user to the wrong one.

Which copy is kept (and scored): the one we know most about. Yad2 (a pin
and a full listing page), then Madlan (a pin), then Komo (no pin). The
others are listed in `also`, each with its own rent and link.

v1.38: the same apartment posted more than once on ONE site (an owner who
reposts, two agents with the same flat) is merged too. Yad2's search rows
have no street, so a same-site twin needs every fact that is compared
across sites AND both pins, within 50 m (one building), AND the same
neighborhood when both name one, with the rents within 10%. On the
Oct 20 sample-city pull (881 rows) that folds 21 posts into their twins (of the
23 matching pairs, 20 share the very same pin); at 300 m it would have
been 76 pairs, many of them neighbors. The copy kept is one the user
has already saved or booked (so a merge never moves their mark), else the
one with the most photos, else the first.

v1.63 (Nov 9, the owner's ruling after the first duplicate measurement): the
address comes first. Two rows are the same apartment only when both give
a street AND a house number and they agree (the street compared loosely:
"קצנלסון יצחק" = "יצחק קצנלסון", "שד" = "שדרות", "גיטו" = "גטו"); only
then are the rooms, floor, size (within 3 m²) and rent compared. Without
both addresses they stay apart: a duplicate is a smaller harm than two
apartments merged into one, which hides one of them. Measured before
this (tests/test_dedup1.py): 32 of 125 joins were two different
apartments, all on a different street or house number, because the
product dropped Yad2's street and compared neighborhoods only.

When the address and rooms agree but the floor or the size doesn't, the
two aren't merged (one building has many flats); each card links the
other as "possibly the same apartment", with what the sites say
(`maybe_twins`). The card of a merged apartment shows the cheapest rent,
links every copy, and scores the cheapest rent too (`dedupe` sets it).
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

from .commute import straight_line_km, valid_pin

RANK = {"yad2": 0, "madlan": 1, "komo": 2, "facebook": 3}  # v1.66: a Facebook post has the fewest facts
NAMES = {"yad2": "Yad2", "madlan": "Madlan", "komo": "Komo", "facebook": "Facebook"}
SIZE_SLACK_M2 = 3.0
PRICE_SLACK = 0.15
SAME_SITE_PRICE_SLACK = 0.10
ITEM_URLS = {"yad2": "https://www.yad2.co.il/realestate/item/{id}"}
NEAR_KM = 0.3
SAME_SITE_NEAR_KM = 0.05  # one building: Yad2 pins an address, so two posts of one flat share a pin


def source_of(row: dict[str, Any]) -> str:
    return str(row.get("source") or "yad2")


def _words(v: Any) -> str:
    return " ".join(re.sub(r"[\"'״׳`.,()]", " ", str(v or "")).replace("-", " ").replace("–", " ").split())


def _city(v: Any) -> str:
    """v1.64: "קריית אתא" (Komo) = "קרית אתא" (Yad2): a doubled yod or vav is one letter (Komo batch 2: 8 of the 9
    sampled twins the matcher missed were in Kiryat Ata and Kiryat Gat)."""
    return _words(v).replace("יי", "י").replace("וו", "ו")


def hood_key(name: Any) -> str:
    """A neighborhood's name, compared loosely (the same rule as sites.js hoodKey)."""
    return re.sub(r"^(?:שכונת|שכ)\s+", "", _words(name))


def same_hood(a: Any, b: Any) -> bool:
    x, y = hood_key(a), hood_key(b)
    return bool(x) and bool(y) and (x == y or x.startswith(y + " ") or y.startswith(x + " "))


def _street(v: Any) -> str:
    """A street's name without its house number."""
    return " ".join(w for w in _words(v).split() if not any(ch.isdigit() for ch in w))


_STREET_WORDS = {"רחוב", "רח", "שדרות", "שד", "שדרת", "סמטת", "סמ"}
_HOUSE = re.compile(r"^(\d{1,4})([א-ת])?$")


def _plain(w: str) -> str:
    return w[1:] if len(w) >= 4 and w.startswith("ה") else w  # "הגלבוע" = "גלבוע"


def _letters(w: str) -> str:
    """A word spelled loosely: without its vowel letters (א ו י), so "גיטו" = "גטו" and "קורצק" = "קורצאק"."""
    return re.sub(r"[אוי]", "", _plain(w)) or w


def address(v: Any) -> tuple[tuple[str, ...], Optional[str]]:
    """'שד עובד בן עמי 2' -> (('עובד', 'בן', 'עמי'), '2'): the street's words and the house number."""
    text = re.sub(r"[\"'`׳״]", "", str(v or ""))
    words = re.sub(r"[.,()\-–/]", " ", text).split()
    house = None
    if words and _HOUSE.match(words[-1]):
        house = words.pop()
    return tuple(w for w in words if w not in _STREET_WORDS and not any(c.isdigit() for c in w)), house


def same_address(a: Any, b: Any) -> bool:
    """Both give a street and a house number, and the numbers are the same; and the street's words are the same in any
    order, spelled loosely ("קצנלסון יצחק" = "יצחק קצנלסון", "לוחמי הגיטו" = "לוחמי הגטו"), or one street's words are all
    in the other's as written (a first name left out: "יעבץ" = "זאב יעבץ"). A loose spelling and a left-out word together
    aren't trusted: "איילון" and "יגאל אלון" spell alike without their vowels."""
    (wa, ha), (wb, hb) = address(a), address(b)
    if not wa or not wb or ha is None or hb is None or ha != hb:
        return False
    if len(set(wa)) == len(set(wb)):
        same = {_letters(w) for w in wa} == {_letters(w) for w in wb}
    else:
        small, big = (wa, wb) if len(set(wa)) < len(set(wb)) else (wb, wa)
        same = {_plain(w) for w in small} <= {_plain(w) for w in big}
    short = wa if len(set(wa)) <= len(set(wb)) else wb
    return same and sum(len(w) for w in short) >= 3


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _pin(row: dict[str, Any]) -> Optional[tuple[float, float]]:
    return None if row.get("approx") else valid_pin(row.get("lat"), row.get("lng"))


def same_apartment(a: dict[str, Any], b: dict[str, Any]) -> bool:
    same_site = source_of(a) == source_of(b)
    if same_site and str(a.get("id")) == str(b.get("id")):
        return False  # one post, not two
    if not _city(a.get("city")) or _city(a.get("city")) != _city(b.get("city")):
        return False
    if not same_address(a.get("street"), b.get("street")):
        return False  # v1.63: the address first; without it, no merge
    for key in ("rooms", "floor"):
        x, y = _num(a.get(key)), _num(b.get(key))
        if key == "floor":  # v1.64: a floor the site gave but we don't trust ("14 of 14") still counts when the other site agrees
            x = x if x is not None else _num(a.get("floor_said"))
            y = y if y is not None else _num(b.get("floor_said"))
        if x is None or y is None or x != y:
            return False
    sa, sb = _num(a.get("size_m2")), _num(b.get("size_m2"))
    if sa is None or sb is None or abs(sa - sb) > SIZE_SLACK_M2:
        return False
    pa, pb = _num(a.get("price")), _num(b.get("price"))
    slack = SAME_SITE_PRICE_SLACK if same_site else PRICE_SLACK
    if pa is None or pb is None or pa <= 0 or pb <= 0 or abs(pa - pb) > slack * min(pa, pb):
        return False
    pin_a, pin_b = _pin(a), _pin(b)
    if pin_a and pin_b and straight_line_km(*pin_a, *pin_b) > (SAME_SITE_NEAR_KM if same_site else NEAR_KM):
        return False  # one address can't be two places
    return True


def maybe_same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """The same address and rooms, but the floor or the size disagrees: maybe one flat listed differently on two
    sites, maybe two flats in one building. Never merged; each card links the other (v1.63, the owner)."""
    if source_of(a) == source_of(b) or same_apartment(a, b):
        return False
    if not _city(a.get("city")) or _city(a.get("city")) != _city(b.get("city")) or not same_address(a.get("street"), b.get("street")):
        return False
    ra, rb = _num(a.get("rooms")), _num(b.get("rooms"))
    return ra is not None and ra == rb


def maybe_twins(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """{id: [{source, name, id, url, price, floor, size_m2}] of listings on another site that may be the same flat}."""
    out: dict[str, list[dict[str, Any]]] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:  # only rows with one city and house number can share an address: compare within those
        house = address(r.get("street"))[1]
        if house is not None and _city(r.get("city")):
            groups.setdefault((_city(r.get("city")), house), []).append(r)
    pairs = [(a, b) for g in groups.values() for i, a in enumerate(g) for b in g[i + 1:]]
    for a, b in pairs:
        if maybe_same(a, b):
            for x, y in ((a, b), (b, a)):
                s = source_of(y)
                out.setdefault(str(x["id"]), []).append({"source": s, "name": NAMES.get(s, s), "id": str(y["id"]), "url": _url(y),
                                                          "price": _num(y.get("price")), "floor": _num(y.get("floor")),
                                                          "size_m2": _num(y.get("size_m2"))})
    return out


def _photos(row: dict[str, Any]) -> int:
    p = row.get("photos")
    return len(p) if isinstance(p, list) else 0


def _url(row: dict[str, Any]) -> str:
    u = str(row.get("url") or "")
    if u:
        return u
    pattern = ITEM_URLS.get(source_of(row))
    return pattern.format(id=row["id"]) if pattern else ""


def dedupe(rows: list[dict[str, Any]], prefer: Any = ()) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """(rows with each apartment once, {kept id: [{source, name, id, url, price, same_site}] of its other copies}).
    prefer: ids to keep when they have twins (the ones the user marked)."""
    marked = {str(i) for i in (prefer or ())}
    order = sorted(range(len(rows)), key=lambda i: (RANK.get(source_of(rows[i]), 9), str(rows[i]["id"]) not in marked, -_photos(rows[i]), i))
    kept: list[int] = []
    also: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for i in order:
        r = rows[i]
        if (source_of(r), str(r["id"])) in seen:
            continue  # the same post twice (found by two searches): once is enough
        seen.add((source_of(r), str(r["id"])))
        twin = next((k for k in kept if same_apartment(rows[k], r)), None)
        if twin is None:
            kept.append(i)
            continue
        s = source_of(r)
        also.setdefault(str(rows[twin]["id"]), []).append(
            {"source": s, "name": NAMES.get(s, s), "id": str(r["id"]), "url": _url(r), "price": _num(r.get("price")),
             "same_site": s == source_of(rows[twin]), "size_m2": _num(r.get("size_m2"))})
    kept.sort()
    out = []
    for i in kept:
        r = rows[i]
        prices = [p for p in [_num(r.get("price"))] + [o["price"] for o in also.get(str(r["id"]), [])] if p is not None and p > 0]
        own = _num(r.get("price"))
        if prices and own is not None and min(prices) < own:
            r = dict(r, price=min(prices), price_own=own)  # v1.63 (owner ruling): the apartment is planned and scored at its cheapest rent
        out.append(r)
    return out, also
