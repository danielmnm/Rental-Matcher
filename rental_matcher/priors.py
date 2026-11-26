"""
What an unstated fact usually turns out to be (v1.23).

A listing that doesn't tick Yad2's box for something, and whose text
doesn't say either, used to count as a coin flip in the match (half met),
so a listing silent on four things scored "37-100%". Here the odds are
measured instead, on the listings two people labeled by hand
(tests/eval/yad2_gold.json) together with their Yad2 boxes: among listings
whose box for the thing is NOT ticked, what does the text say, when it
says? For example, an unticked elevator box with a text that mentions the
elevator says "no elevator" 20 times out of 20.

    python -m rental_matcher.priors     # re-measure and rewrite priors.json

What this is and isn't, stated:
- It estimates "box not ticked, text silent" from "box not ticked, text
  says". A listing with an amenity is likelier to mention it than one
  without, so for amenities (parking, balcony) it leans generous.
- It's one region's listings (one city and nearby, Oct 18-20, 2026), and some
  samples are small; each says its n. Laplace smoothing (+1 per outcome)
  keeps 0 of 20 from becoming "never".
- It only ever estimates the match. It never decides anything: an unstated
  must-have is still a check, never a hide, whatever its odds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
STORED = Path(__file__).with_name("priors.json")

# signal: (gold question, Yad2 boxes, structured count field, {answer: value})
MEASURED: dict[str, tuple[str, tuple[str, ...], Optional[str], dict[str, Any]]] = {
    "elevator": ("elevator", ("includeElevator",), None, {"yes": True, "no": False}),
    "balcony": ("balcony", ("includeBalcony",), "balconiesCount", {"yes": True, "no": False, "service_only": False}),
    "protected_space": ("protected_space", ("includeSecurityRoom", "includeBuildingShelter"), None, {"yes": True, "no": False}),
    "air_conditioning": ("air_conditioning", ("includeAirconditioner",), None, {"yes": True, "no": False}),
    "parking_level": ("parking", ("includeParking",), "parkingSpacesCount",
                      {"deeded": 3.0, "building": 2.0, "street": 1.0, "none": 0.0}),
    "roommate_listing": ("room_share", (), None, {"yes": True, "no": False}),
}


def _extracts() -> dict[str, dict[str, Any]]:
    """The newest saved extract with Yad2's boxes, per listing."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted((ROOT / "tests" / "fixtures").glob("yad2*/*.json")):
        if f.parent.name.startswith(("yad2_search", "yad2_reread", "yad2_holdout7", "yad2_holdout8", "yad2_holdout9", "yad2_holdout10", "yad2_holdout11", "yad2_holdout12", "yad2_holdout13", "yad2_holdout14", "komo_batch")) or f.name.startswith("routes"):
            continue  # v1.43/v1.50: held-out batches join the odds with their fixes (re-measuring now would change every score);
            # v1.57: batch 11 re-fetched 14 of the labeled listings, which would otherwise replace their older copies here
        for x in extracts_in(json.loads(f.read_text(encoding="utf-8"))):
            if "inProperty" in x:
                out[x["id"]] = x
    return out


def extracts_in(data: Any) -> list[dict[str, Any]]:
    """The extracts in a fixture file: a list, one extract, or {id: extract}
    (v1.28: the last was skipped). Keys starting with "_" are notes."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and x.get("id")]
    if isinstance(data, dict) and data.get("id"):
        return [data]
    if isinstance(data, dict):
        return [{"id": k, **v} if "id" not in v else v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)]
    return []


def measure() -> dict[str, Any]:
    gold = json.loads((ROOT / "tests" / "eval" / "yad2_gold.json").read_text(encoding="utf-8"))["gold"]
    extracts = _extracts()
    ids = sorted(i for i in gold if i in extracts)
    signals: dict[str, Any] = {}
    for signal, (question, boxes, count_field, values) in MEASURED.items():
        counts: dict[str, int] = {}
        for i in ids:
            x = extracts[i]
            boxes_on = any((x.get("inProperty") or {}).get(b) is True for b in boxes)
            count = (x.get("additionalDetails") or {}).get(count_field) if count_field else None
            if boxes_on or (isinstance(count, int) and not isinstance(count, bool) and count > 0):
                continue  # the box says: not the case this estimates
            said = ((gold[i].get(question) or {}).get("answer"))
            if said in values:
                key = json.dumps(values[said])
                counts[key] = counts.get(key, 0) + 1
        outcomes = sorted({json.dumps(v) for v in values.values()})
        n = sum(counts.values())
        dist = {k: round((counts.get(k, 0) + 1) / (n + len(outcomes)), 4) for k in outcomes}
        signals[signal] = {"dist": dist, "n": n, "counts": {k: counts.get(k, 0) for k in outcomes}}
    return {
        "_about": ("Odds for a fact a listing leaves unstated (box not ticked, text silent), measured on "
                   f"{len(ids)} hand-labeled Yad2 listings (Oct 18-20, 2026) as what the text says when the box "
                   "isn't ticked, +1 per outcome. Written by `python -m rental_matcher.priors`; a test checks "
                   "it matches a fresh measurement."),
        "listings": len(ids),
        "signals": signals,
    }


_loaded: Optional[dict[str, list[tuple[Any, float]]]] = None


def load(path: Path = STORED) -> dict[str, list[tuple[Any, float]]]:
    """{signal: [(value, probability), ...]} from the stored measurement."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s: [(json.loads(k), p) for k, p in d["dist"].items()] for s, d in data["signals"].items()}


def sample_sizes(path: Path = STORED) -> dict[str, int]:
    return {s: d["n"] for s, d in json.loads(path.read_text(encoding="utf-8"))["signals"].items()}


def default() -> dict[str, list[tuple[Any, float]]]:
    global _loaded
    if _loaded is None:
        _loaded = load()
    return _loaded


def main() -> int:
    STORED.write_text(json.dumps(measure(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {STORED.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
