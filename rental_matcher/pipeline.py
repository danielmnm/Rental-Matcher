"""
The whole path for one listing, end to end: what a source page says ->
a scored, ranked result for one user.

    Yad2 extract ---- adapters/yad2.to_listing ---------> structured facts + ticked boxes
    its description - extraction/rules.answer ---------> text answers (free, instant)
                      + saved model answers (optional) -> combined: a disagreement is a check
                      extraction/merge ------------------> one set of signals
    the user's places - commute.commute_signal ---------> e.g. e-bike minutes to work
                      scoring.rank ----------------------> hidden / shown, checks, flags, match range

Nothing here calls a network: model answers and routed distances are
inputs, fetched where the network and the user's key live (the browser,
the owner's machine) and saved, like the Yad2 data itself. So a run is
repeatable, and a test can run the whole thing.

    python -m rental_matcher.pipeline EXTRACTS.json [--prefs preferences/my.json]
        [--model RUN.json] [--routes ROUTES.json] [--out RESULTS.json]

EXTRACTS: a JSON list (or {id: extract}) of Yad2 extracts, the shape the
adapter reads. RUN: a saved Gemini run (run_gemini_test.py writes them).
ROUTES: {commute signal: {listing source id: routed km}}.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from .adapters import facebook, komo, madlan, yad2
from .commute import commute_signal, shortest_routes
from .extraction.merge import merge, text_signals
from .extraction.prompt import ground
from .extraction.rules import answer as rule_answer
from .extraction.rules import combine
from .extraction.rules import furniture_for_sale, ground_level, housing_unit, short_lease
from .schema import ExtractedBy, ListedBy, Listing, RecurringCosts, Signal, SignalStatus
from .scoring import PreferenceSet, ScoredListing, rank

Routes = dict[str, dict[str, Any]]  # commute signal -> source listing id -> routed km (bike, walk) or a Drive (car)


# an extract's "source" -> its adapter (none given: Yad2, the first source)
ADAPTERS = {"yad2": yad2, "komo": komo, "madlan": madlan, "facebook": facebook}  # v1.66: Facebook posts the user kept


def build_listing(extract: dict[str, Any], prefs: PreferenceSet, *, model: Optional[dict[str, Any]] = None,
                  routes: Optional[Routes] = None, pulled_at: Optional[datetime] = None,
                  text_answers: Optional[dict[str, Any]] = None) -> Listing:
    """One extract (Yad2, Komo or Madlan) -> a Listing with every signal the user's
    preferences read. `model`: this listing's saved model answers, grounded
    here against its own text (idempotent), so an ungrounded saved run
    can't slip a guess through."""
    adapter = ADAPTERS.get(str(extract.get("source") or "yad2"))
    if adapter is None:
        raise ValueError(f"listing {extract.get('id')!r} comes from a site we don't read: {extract.get('source')!r}")
    listing = adapter.to_listing(extract, pulled_at)
    text = listing.raw_excerpt or ""
    full = extract.get("description") if isinstance(extract.get("description"), str) else text
    # v1.53: Yad2's "פירוט ריהוט" field (furnitureInfo, "מקרר ומכונת כביסה"): the poster's own list of
    # the furniture, read like the description
    info = extract.get("furnitureInfo")
    if isinstance(info, str) and info.strip():
        full = f"{full}\n\nפירוט ריהוט: {info.strip()}"
    model_answers = ground(model, full) if model else {}
    # combine() tags each answer with who gave it; untagged answers would be
    # read as the model's (less trusted), so rules-only runs go through it too.
    # v1.52 `text_answers`: the text read already (a frozen rules run, combined or not), so the
    # card test scores this very path with the reading that was frozen (extraction/card_eval)
    answers = combine(rule_answer(full), model_answers) if text_answers is None else text_answers
    signals = merge(listing.signals, text_signals(answers))
    _form_absences(extract, signals, full)
    for c in prefs.commutes:
        # routes are keyed by the extract's id: Yad2's bare token, or "komo:N" / "madlan:X"
        km = ((routes or {}).get(c.signal) or {}).get(str(extract.get("id") or listing.source_listing_id))
        try:
            s = commute_signal(listing, c, km)
        except ValueError:  # a route or drive that doesn't hold up (v1.28): unrouted, not a lost listing
            s = commute_signal(listing, c, None)
        if s is not None:
            signals[c.signal] = s
    unit = _housing_unit(full, signals.get("apartment_type"), extract)
    if unit is not None:
        signals["housing_unit"] = unit
    # v1.39: what the listing says about its term: "the text offers a short stay" or not
    short = short_lease(full)
    signals["short_lease"] = Signal(status=SignalStatus.CONFIRMED, value=bool(short), extracted_by=ExtractedBy.RULE,
                                    evidence=short["evidence"] if short else "the text doesn't offer a short stay")
    # v1.49: furniture or appliances offered for sale: they don't come with it, and the card says so
    sale = furniture_for_sale(full)
    if sale:
        signals["furniture_for_sale"] = Signal(status=SignalStatus.CONFIRMED, value=True, extracted_by=ExtractedBy.RULE,
                                               evidence=sale["evidence"])
    # v1.33: whether the listing has photos, as the site's own data says (the extension counts them:
    # `photo_count`, None when it couldn't tell); a listing without photos tends to be one to be careful with
    pc = extract.get("photo_count")
    if isinstance(pc, int) and not isinstance(pc, bool) and pc >= 0:
        signals["has_photos"] = Signal(status=SignalStatus.CONFIRMED, value=pc > 0, extracted_by=ExtractedBy.RULE,
                                       evidence=f"{pc} photos in the listing" if pc else "the listing has no photos")
    update: dict[str, Any] = {"signals": signals}
    floor = _floor_said(full, listing.floor, signals.get("apartment_type"), _site_property(extract))
    if floor != listing.floor:
        update["floor"] = floor
    # v1.28: what the text says about the fees and a broker (the questions with
    # no signal of their own), unless the site said it in a field of its own
    costs = text_costs(answers)
    site = listing.recurring_costs  # v1.53: Yad2's own arnona field; the text fills in the rest
    if costs is not None and site is None:
        update["recurring_costs"] = costs
    elif costs is not None and site is not None:
        def one(a: Optional[float], b: Optional[float]) -> tuple[Optional[float], Optional[float]]:
            # (the amount, the higher amount if the two disagree). v1.57 (owner ruling): the text saying the rent
            # includes it wins over the field's amount (the field is the fee, not a charge). v1.59 (owner ruling):
            # when the text and the field give different amounts, a range, not silence
            if b == 0:
                return 0.0, None
            if a is None:
                return b, None
            if b is None or abs(a - b) < 1:
                return a, None
            return min(a, b), max(a, b)
        arn, vaad = one(site.arnona_monthly, costs.arnona_monthly), one(site.vaad_bayit_monthly, costs.vaad_bayit_monthly)
        update["recurring_costs"] = RecurringCosts(arnona_monthly=arn[0], arnona_monthly_max=arn[1],
                                                   vaad_bayit_monthly=vaad[0], vaad_bayit_monthly_max=vaad[1])
    said = answers.get("broker") or {}
    by = {"no_broker": ListedBy.PRIVATE, "broker": ListedBy.AGENCY}.get(str(said.get("answer")))
    if by is not None and listing.listed_by is None:
        update["listed_by"] = by
    elif by == ListedBy.PRIVATE and listing.listed_by == ListedBy.AGENCY:
        # v1.53: an agency's account that says "ללא דמי תיווך": the agency posted it, and there's no
        # fee. The card says both (the card test found 10 that said only "agency").
        signals["no_broker_fee"] = Signal(status=SignalStatus.CONFIRMED, value=True, extracted_by=_reader_of(said),
                                          evidence=f"text: {said.get('evidence') or 'no broker fee'}")
    return listing.model_copy(update=update)


# v1.53: any word for it, read or not: the absence rules only apply when the text never mentions it
_PARKING_WORD = re.compile(r"חני|חנ[\"״]|חניון|רכב")
_SHELTER_WORD = re.compile(r"מי?קלט|ממ[\"״']?ד|ממד|מרחב\s+מוגן|מוגן")


def _form_absences(extract: dict[str, Any], signals: dict[str, Signal], text: str = "") -> None:
    """v1.53, the owner's reading of Yad2's form (Oct 29), for a Yad2 listing whose form data we have,
    when neither a box nor the text says anything:
    - no parking box and no space count ("חניות: ללא" on the page): no space comes with the flat
      ("usually listings will tick parking if there is one": 81% of the labeled listings whose text
      describes their own or the building's parking ticked it). Street parking may still exist.
    - no safe-room and no shelter box, so Yad2's page shows "מקלט במרחק 349 מ'" (its distance to the
      nearest public shelter) where it would show "נכס עם ממ"ד" or "מקלט בבניין": no safe room or
      building shelter (93% of the labeled listings whose text says there's one ticked a box). Only
      when that distance came with the listing (the extension reads it from v1.53), i.e. the page
      showed that bubble.
    The text always wins: any word for it in the text, even one the rules can't read, keeps these
    rules out (they would otherwise hide a listing the rules misread: the card test caught that)."""
    form = extract.get("inProperty")
    if str(extract.get("source") or "yad2") != "yad2" or not isinstance(form, dict) or not form:
        return
    details = extract.get("additionalDetails") or {}
    if ("parking_level" not in signals and form.get("includeParking") is not True and not details.get("parkingSpacesCount")
            and not _PARKING_WORD.search(text or "")):
        signals["no_parking_space"] = Signal(status=SignalStatus.CONFIRMED, value=True, extracted_by=ExtractedBy.RULE,
                                             evidence="Yad2: no parking marked (חניות: ללא), and the text doesn't mention any")
    near = extract.get("shelterDistance")
    if (isinstance(near, (int, float)) and not isinstance(near, bool) and near >= 0
            and "protected_space" not in signals and not _SHELTER_WORD.search(text or "")
            and not any(form.get(b) is True for b in ("includeSecurityRoom", "includeBuildingShelter", "includeFloorShelter"))):
        signals["protected_space"] = Signal(status=SignalStatus.CONFIRMED, value=False, extracted_by=ExtractedBy.RULE,
                                            evidence=f"Yad2: no safe room or building shelter marked (nearest public shelter {near:g} m away), and the text doesn't mention one")


def _reader_of(entry: dict[str, Any]) -> ExtractedBy:
    return ExtractedBy.RULE if entry.get("source") in ("rules", "both") else ExtractedBy.LLM


def _floor_said(text: str, floor: Optional[int], kind: Optional[Signal], prop: Optional[str]) -> Optional[int]:
    """v1.39: the floor, unless the listing says outright it's lower: a basement ("מרתף/ פרטר" on
    Yad2, "חצי קומה מתחת לאדמה") is -1, the ground floor or a garden apartment 0. the owner's Oct 26
    search had "קומת קרקע" in the text with the floor field at 1. A house's own floors don't count."""
    if kind is not None and kind.status == SignalStatus.CONFIRMED and kind.value == "house":
        return floor
    said = ground_level(text)
    low = -1 if (said and said["answer"] == "below") or (prop and "מרתף" in prop) else (
        0 if said or (prop and "דירת גן" in prop) else None)
    if low is not None and (floor is None or floor > low):
        return low
    return floor


def _site_property(extract: dict[str, Any]) -> Optional[str]:
    """The kind of home the site files the listing under ("דירה", "יחידת דיור"), if it says."""
    details = extract.get("additionalDetails")
    p = details.get("property") if isinstance(details, dict) else extract.get("property")
    p = p.get("text") if isinstance(p, dict) else p
    return p.strip() if isinstance(p, str) and p.strip() else None


def _housing_unit(text: str, kind: Optional[Signal], extract: dict[str, Any]) -> Optional[Signal]:
    """v1.39: whether the home is a unit in someone else's (a housing unit, a flat inside a
    private house, a divided apartment). The text's own words come first: a "דירה" on Yad2
    is the default choice, and "בבית פרטי" in the text says more. Then a unit as the site or
    the text names the kind of home. Then the site's kind, when it names one: not a unit."""
    said = housing_unit(text)
    if said and said["answer"] == "yes":
        return Signal(status=SignalStatus.CONFIRMED, value=True, extracted_by=ExtractedBy.RULE, evidence=said["evidence"])
    if kind is not None and kind.status == SignalStatus.CONFIRMED and kind.value == "unit":
        return Signal(status=SignalStatus.CONFIRMED, value=True, extracted_by=kind.extracted_by, evidence=kind.evidence)
    if said and said["answer"] == "no":
        return Signal(status=SignalStatus.CONFIRMED, value=False, extracted_by=ExtractedBy.RULE, evidence=said["evidence"])
    prop = _site_property(extract)
    if prop:
        site = {"komo": "Komo", "madlan": "Madlan"}.get(str(extract.get("source") or "yad2"), "Yad2")
        return Signal(status=SignalStatus.CONFIRMED, value=False, extracted_by=ExtractedBy.RULE,
                      evidence=f"{site}: listed as {prop}, and the text doesn't say it's part of someone's home")
    return None


def _monthly(entry: Optional[dict[str, Any]]) -> Optional[float]:
    """A fee answer -> its monthly amount: 0 when it's in the rent, None when
    unsaid or unclear (never 0 for "unknown": no arnona is never true)."""
    entry = entry or {}
    if entry.get("answer") == "included":
        return 0.0
    v = entry.get("value")
    if entry.get("answer") == "amount" and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0:
        return float(v)
    return None


def text_costs(answers: dict[str, dict[str, Any]]) -> Optional[RecurringCosts]:
    vaad, arnona = _monthly(answers.get("vaad_bayit")), _monthly(answers.get("arnona"))
    if vaad is None and arnona is None:
        return None
    return RecurringCosts(vaad_bayit_monthly=vaad, arnona_monthly=arnona)


def run(extracts: Iterable[dict[str, Any]], prefs: PreferenceSet, *, model_run: Optional[dict[str, Any]] = None,
        routes: Optional[Routes] = None, pulled_at: Optional[datetime] = None) -> tuple[list[ScoredListing], list[Listing], list[str]]:
    """(ranked results, the listings they were scored from, skipped).
    A listing the adapter can't read (removed, no price) is skipped with its
    reason, not fatal: one dead link shouldn't sink a pull."""
    pulled_at = pulled_at or datetime.now(timezone.utc)
    listings: list[Listing] = []
    skipped: list[str] = []
    for x in extracts:
        try:
            listings.append(build_listing(x, prefs, model=(model_run or {}).get(str(x.get("id"))),
                                          routes=routes, pulled_at=pulled_at))
        except ValueError as e:
            skipped.append(str(e))
    return rank(listings, prefs), listings, skipped


def _load(path: Union[str, Path]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _extracts(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        return [{"id": k, **v} if "id" not in v else v for k, v in data.items() if not k.startswith("_")]
    return list(data)


def report(ranked: list[ScoredListing], listings: list[Listing]) -> str:
    by_id = {x.id: x for x in listings}
    lines: list[str] = []
    shown = [s for s in ranked if not s.excluded]
    lines.append(f"{len(shown)} shown, {len(ranked) - len(shown)} hidden")
    for s in ranked:
        x = by_id[s.listing_id]
        where = ", ".join(p for p in (x.area.street, x.area.neighborhood, x.area.city) if p)
        match = f"{s.match_low:.0f}-{s.match_high:.0f}%" if s.match_low is not None and s.match_high is not None else "n/a"
        head = "HIDDEN " if s.excluded else ""
        lines.append(f"\n{head}{x.source_listing_id}  ₪{x.price.amount:,.0f}  {where}  match {match}")
        for r in s.exclusion_reasons:
            lines.append(f"    ✗ {r}")
        for f in s.flags:
            lines.append(f"    ! {f}")
        for c in s.checks:
            lines.append(f"    ? {c}")
    return "\n".join(lines)


_DRIVE_KEYS = {"free_flow_s", "typical_s", "peak_s"}


def combine_routes(by_router: dict[str, Routes]) -> Routes:
    """Several route files -> one. Bike/walk distances: the shortest any
    router found (commute.shortest_routes). Drives: the first file's, since
    a drive's times come from one router's own traffic. Keys starting
    with "_" (a router's side notes, e.g. its own bike times) are dropped."""
    if len(by_router) == 1:
        (only,) = by_router.values()
        return {k: v for k, v in only.items() if not k.startswith("_")}
    distances: dict[str, Routes] = {}
    drives: Routes = {}
    for name, routes in by_router.items():
        for sig, per_id in routes.items():
            if sig.startswith("_"):
                continue
            for i, r in (per_id or {}).items():
                if isinstance(r, dict) and _DRIVE_KEYS & set(r):
                    drives.setdefault(sig, {}).setdefault(i, r)
                else:
                    distances.setdefault(name, {}).setdefault(sig, {})[i] = r
    out: Routes = shortest_routes(distances) if distances else {}
    for sig, per_id in drives.items():
        out.setdefault(sig, {}).update(per_id)
    return out


def load_routes(paths: list[str]) -> Routes:
    """Route files -> one set of routes, each file named by its path: two
    files called routes.json in different folders stay two routers (v1.28:
    keyed by the bare name, the second replaced the first)."""
    return combine_routes({str(Path(f)): _load(f) for f in paths})


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("extracts")
    ap.add_argument("--prefs", default="preferences/my.json")
    ap.add_argument("--model", help="a saved model run (e.g. tests/eval/runs/...gemini...json)")
    ap.add_argument("--routes", action="append",
                    help='{"bike_minutes": {"<yad2 id>": km, ...}}; give it more than once (OSRM and TomTom, say) '
                         'and each bike/walk listing gets the shortest route any of them found')
    ap.add_argument("--out", help="write the ranked results as JSON here")
    a = ap.parse_args(argv)
    prefs = PreferenceSet.load(a.prefs)
    ranked, listings, skipped = run(_extracts(_load(a.extracts)), prefs,
                                    model_run=_load(a.model) if a.model else None,
                                    routes=load_routes(a.routes) if a.routes else None)
    print(report(ranked, listings))
    for s in skipped:
        print(f"skipped: {s}", file=sys.stderr)
    if a.out:
        Path(a.out).write_text(json.dumps([s.model_dump(mode="json") for s in ranked], ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
