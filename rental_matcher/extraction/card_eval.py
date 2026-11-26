"""
v1.52: score what the CARD shows, not only what the text says.

Until v1.51 every accuracy number in Phase 2 scored the text reader alone:
the rules (and Gemini) against what two labelers read in the description.
But a card is built from more than the text. Yad2's own form comes first
(the boxes a poster ticks, "private" or "commercial" for the account), and
the text fills in and refines it (pipeline.build_listing, extraction/merge).
Owner ruling, Oct 29: the test should measure how accurately the card gives the
user what the listing provides, boxes included -- not count against us what
a poster left out.

So this module scores the card the product actually builds:

- `card_answers(extract, text_answers)`: the listing exactly as
  pipeline.build_listing builds it (the same adapter, the same merge), with
  the text answers given (a frozen rules run, or rules + Gemini), turned
  back into one answer per question so the same scorer can grade it.
- `card_gold(text_gold, extract)`: what the listing provides, from two
  sources that don't depend on any reader: the labelers' reading of the
  text, and the boxes (the poster's own entries, read mechanically). Where
  only one says something, that's the truth. Where both do, the text can
  narrow the box (a ticked parking box is "the building's or the flat's
  own"; "חניה בטאבו" makes it the flat's own). Where they contradict each
  other, the listing contradicts itself, and the right card is a check;
  except parking, where the text wins when it says where (v1.56, owner ruling:
  "חניה בכביש" with the box ticked is street parking).

What a box says, as truth (each the poster's own entry on Yad2's form):
- AC, elevator, balcony, safe room or building shelter ticked -> yes.
  An unticked box is not a no (yad2.py explains why).
- Parking ticked or a space count -> the building's or the flat's own
  (owner ruling: "almost always parking in tabu or in the building").
- The property type ("דירת גן", "דופלקס"...) -> that type.
- A "commercial" account -> a broker (agents must show their license there);
  "private" -> no broker.
- The furniture box: a claim, not a list (owners tick it for one chair), so
  it adds nothing definite to what the text lists.

Standard library only for the gold; card_answers imports the pipeline.
"""

from __future__ import annotations

from typing import Any

from .evaluate import NOT_STATED, UNCLEAR, _abstentions
from .questions import BY_ID, PLACES_PARKING as _PLACES_IT, QUESTIONS

# a box's reading, as the answers it leaves possible (parking: a lower bound the text can narrow)
_BOX_ANSWERS = {
    "air_conditioning": {True: {"yes"}},
    "elevator": {True: {"yes"}},
    "balcony": {True: {"yes"}},
    "protected_space": {True: {"yes"}},
    "parking": {2.0: {"building", "deeded"}},
}


# the box and the text name different things that can both be true of one listing:
# - apartment type: Yad2's form takes one type; a roof duplex is both.
# - broker: a business account ("commercial") that says "ללא דמי תיווך" -- an agency that waives
#   the fee. The account says who listed it, the text that there's no fee: the card says both.
_BOTH_TRUE = {"apartment_type"}


def normalized(extract: dict[str, Any]) -> dict[str, Any]:
    """A saved extract in the shape the live extension sends. The exports from
    v1.40 on keep the property type at the top ("property": "דירת גן"); the
    live page data has it under additionalDetails."""
    x = dict(extract)
    prop = x.get("property")
    details = dict(x.get("additionalDetails") or {})
    if isinstance(prop, str) and "property" not in details:
        details["property"] = {"text": prop}
        x["additionalDetails"] = details
    return x


def site_listing(extract: dict[str, Any]) -> Any:
    """v1.62 (Phase 3): the listing as its own site's adapter reads it (pipeline.ADAPTERS, the product's own map):
    Yad2's form for a Yad2 extract, Komo's feature list for a Komo one. Before, every extract went through Yad2's."""
    from ..pipeline import ADAPTERS
    source = str(extract.get("source") or "yad2")
    adapter = ADAPTERS.get(source)
    if adapter is None:
        raise ValueError(f"listing {extract.get('id')!r} comes from a site we don't read: {source!r}")
    return adapter.to_listing(normalized(extract) if source == "yad2" else extract)


def box_facts(extract: dict[str, Any]) -> dict[str, set[str]]:
    """What the site's own form says, per question, as the answers it leaves possible."""
    from ..schema import ListedBy, SignalStatus
    listing = site_listing(extract)
    out: dict[str, set[str]] = {}
    from ..adapters.common import INFERRED
    for qid, reading in _BOX_ANSWERS.items():
        s = listing.signals.get(BY_ID[qid].signal)
        if s is not None and INFERRED in (s.evidence or ""):
            continue  # v1.62: worked out by the adapter (a tall building's elevator), not the form's word: never part of the answer key
        if s is not None and s.status == SignalStatus.CONFIRMED and s.value in reading:
            out[qid] = set(reading[s.value])
    kind = listing.signals.get("apartment_type")
    if kind is not None and kind.status == SignalStatus.CONFIRMED and kind.value in BY_ID["apartment_type"].answers:
        out["apartment_type"] = {kind.value}
    by = {ListedBy.AGENCY: "broker", ListedBy.PRIVATE: "no_broker"}.get(listing.listed_by)
    if by:
        out["broker"] = {by}
    c = listing.recurring_costs  # v1.53: Yad2's own fee fields (their values: fee_value below)
    for qid, v in (("arnona", c.arnona_monthly if c else None), ("vaad_bayit", c.vaad_bayit_monthly if c else None)):
        if v is not None:
            out[qid] = {"amount"}
    return out


def fee_value(extract: dict[str, Any], qid: str) -> Any:
    c = site_listing(extract).recurring_costs
    v = (c.arnona_monthly if qid == "arnona" else c.vaad_bayit_monthly) if c else None
    return int(v) if v is not None and v == int(v) else v


def card_gold(text_gold: dict[str, dict[str, Any]], extract: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """(gold for the card, {question: what the box did}) for one listing.
    What the box did: "added" (the text says nothing), "narrowed" (both
    say it, the text more precisely), "agreed", or "contradicts" (the
    listing says two things; the card should show a check)."""
    boxes = box_facts(extract)
    gold = {qid: dict(g) for qid, g in text_gold.items()}
    how: dict[str, str] = {}
    # v1.53, the owner's reading of Yad2's form: no box and a silent text read as "none comes with it"
    # (pipeline._form_absences). The listing doesn't say so in words, so the truth is still "not
    # stated": that reading is accepted, never required, and can't count as a listing wrongly hidden.
    form = extract.get("inProperty")
    if isinstance(form, dict) and form:
        details = extract.get("additionalDetails") or {}
        absent = {}
        if form.get("includeParking") is not True and not details.get("parkingSpacesCount"):
            absent["parking"] = {"none", "street"}
        if (isinstance(extract.get("shelterDistance"), (int, float))
                and not any(form.get(b) is True for b in ("includeSecurityRoom", "includeBuildingShelter", "includeFloorShelter"))):
            absent["protected_space"] = {"no"}
        for qid, also in absent.items():
            g = gold.get(qid)
            if g is not None and g.get("answer") == NOT_STATED and not (set(g["acceptable"]) - {NOT_STATED, UNCLEAR}):
                gold[qid] = {**g, "acceptable": sorted(set(g["acceptable"]) | {UNCLEAR} | also)}
                how[qid] = "absent"
    # v1.62: the owner's ruling (Nov 5, Nov 8) applied to a fact the site's form STATES: a building of 6+ floors has an
    # elevator. Accepted, never required (the text-only labelers couldn't see the floors field); the adapter's own
    # inference stays out of the key (box_facts), so this is the ruling at work, not the reader grading itself
    from ..adapters.common import ELEVATOR_FLOORS
    tall = site_listing(extract).total_floors
    g = gold.get("elevator")
    if isinstance(tall, int) and tall >= ELEVATOR_FLOORS and g is not None and not (set(g["acceptable"]) - {NOT_STATED, UNCLEAR}):
        gold["elevator"] = {**g, "acceptable": sorted(set(g["acceptable"]) | {"yes"})}
        how["elevator"] = "ruling: building height"
    for qid in ("arnona", "vaad_bayit"):  # v1.53: Yad2's fee fields, an amount: the text agrees, adds, or not
        if qid not in boxes or qid not in gold:
            continue
        g, v = gold[qid], fee_value(extract, qid)
        boxes.pop(qid)
        if g.get("answer") == "amount" and g.get("value") == v:
            how[qid] = "agreed"
        elif NOT_STATED in _abstentions(set(g["acceptable"])):
            gold[qid] = {**g, "answer": "amount", "acceptable": ["amount"], "value": v, "box": ["amount"]}
            how[qid] = "added"
        elif g.get("answer") == "included":
            # v1.57 (owner ruling, Nov 2): "המחיר כולל ארנונה + וועד" with Yad2's fee fields filled in: the field is the
            # fee's amount, the text says the rent covers it. Both hold, and "included" is what the tenant pays.
            gold[qid] = {**g, "box": ["amount"]}
            how[qid] = "text wins"
        else:
            gold[qid] = {**g, "answer": UNCLEAR, "acceptable": [UNCLEAR], "box": ["amount"]}
            how[qid] = "contradicts"
    for qid, said in boxes.items():
        g = gold.get(qid)
        if g is None:
            continue
        acceptable = _abstentions(set(g["acceptable"]))
        definite = acceptable - {NOT_STATED, UNCLEAR}
        if not definite:  # the text says nothing (or nothing clear): the box is what the listing provides
            if g.get("answer") == UNCLEAR and acceptable == {NOT_STATED, UNCLEAR} and g.get("evidence"):
                # the text speaks to it and doesn't settle it: a check still fits, and so does the box
                gold[qid] = {**g, "answer": sorted(said)[0], "acceptable": sorted(said | {UNCLEAR}), "box": sorted(said)}
                how[qid] = "added"
                continue
            gold[qid] = {**g, "answer": sorted(said)[0] if len(said) == 1 else _lowest(qid, said),
                         "acceptable": sorted(said), "evidence": "(Yad2's form)", "box": sorted(said)}
            how[qid] = "added"
        elif definite & said:
            keep = definite & said  # the readings of the text the box allows ("doesn't say" is gone: the box says)
            gold[qid] = {**g, "answer": g["answer"] if g["answer"] in keep else sorted(keep)[0],
                         "acceptable": sorted(keep), "box": sorted(said)}
            how[qid] = "agreed" if keep == said else "narrowed"
        elif NOT_STATED in acceptable:  # one reading of the text says nothing: the box, or a check
            gold[qid] = {**g, "answer": sorted(said)[0], "acceptable": sorted(said | {UNCLEAR}), "box": sorted(said)}
            how[qid] = "added"
        elif qid in _BOTH_TRUE:
            # Yad2's one property type and the text's can both be true: "דופלקס גג" is a duplex
            # AND a roof flat, a garden studio a studio. Either is right, or a check.
            gold[qid] = {**g, "acceptable": sorted(definite | said | {UNCLEAR}), "box": sorted(said)}
            how[qid] = "differs"
        elif qid == "broker":
            # who posted it (the account) and what the text says of a fee are both true: the question is
            # who listed it, so the account is right; the card also says "no broker fee" (v1.53)
            gold[qid] = {**g, "acceptable": sorted(definite | said | {UNCLEAR}), "box": sorted(said)}
            how[qid] = "differs"
        elif qid == "parking" and _PLACES_IT.search(g.get("evidence") or ""):
            # v1.56 (owner ruling, Oct 30): the text is stronger than the box. "חניה בכביש" with the box
            # ticked is street parking: posters tick it for any parking, as they tick "ריהוט" for one chair
            gold[qid] = {**g, "acceptable": sorted(definite), "box": sorted(said)}
            how[qid] = "text wins"
        else:  # the box and the text disagree: the listing contradicts itself
            gold[qid] = {**g, "answer": UNCLEAR, "acceptable": [UNCLEAR], "box": sorted(said),
                         "evidence": f"{g.get('evidence') or ''} | (Yad2's form: {', '.join(sorted(said))})"}
            how[qid] = "contradicts"
    return gold, how


def _lowest(qid: str, said: set[str]) -> str:
    q = BY_ID[qid]
    if q.values and all(isinstance(q.values.get(a), (int, float)) for a in said):
        return min(said, key=lambda a: q.values[a])
    return sorted(said)[0]


def card_answers(extract: dict[str, Any], text_answers: dict[str, dict[str, Any]], prefs: Any) -> dict[str, dict[str, Any]]:
    """What the card shows, per question: the listing built exactly as
    pipeline.build_listing builds it, from these text answers."""
    from ..pipeline import build_listing
    from ..schema import ExtractedBy, ListedBy, SignalStatus
    listing = build_listing(normalized(extract), prefs, text_answers=text_answers)
    out: dict[str, dict[str, Any]] = {}
    for q in QUESTIONS:
        t = text_answers.get(q.id) or {}
        if q.signal is None:
            out[q.id] = dict(t) if t else {"answer": NOT_STATED}
            continue
        s = listing.signals.get(q.signal)
        if s is None:
            out[q.id] = {"answer": NOT_STATED}
            none = listing.signals.get("no_parking_space") if q.id == "parking" else None
            if none is not None and none.status == SignalStatus.CONFIRMED and none.value is True:
                out[q.id] = {"answer": "none", "or": ["street"], "evidence": none.evidence, "source": "rules"}
            continue
        source = "model" if s.extracted_by == ExtractedBy.LLM else "rules"
        if s.status != SignalStatus.CONFIRMED:
            out[q.id] = {"answer": UNCLEAR, "evidence": s.evidence, "source": source}
        elif q.items:
            out[q.id] = {"answer": "items", "items": sorted(s.value or []), "evidence": s.evidence, "source": source}
        else:
            options = [a for a, v in q.values.items() if v == s.value]
            answer = t.get("answer") if t.get("answer") in options else (options[0] if options else "__invalid__")
            out[q.id] = {"answer": answer, "evidence": s.evidence, "source": source}
            floor_only = listing.signals.get("parking_at_least") if q.id == "parking" else None
            if floor_only is not None and floor_only.status == SignalStatus.CONFIRMED and floor_only.value is True:
                out[q.id]["or"] = [a for a, v in q.values.items() if isinstance(v, (int, float)) and v > s.value]  # v1.53
    by = {ListedBy.AGENCY: "broker", ListedBy.PRIVATE: "no_broker"}.get(listing.listed_by)
    if by:
        out["broker"] = {"answer": by, "evidence": "listed by", "source": "rules"}
    costs = listing.recurring_costs  # v1.53: the fees as the card shows them (Yad2's arnona field, then the text)
    for qid, monthly, top in (("vaad_bayit", costs.vaad_bayit_monthly if costs else None, costs.vaad_bayit_monthly_max if costs else None),
                              ("arnona", costs.arnona_monthly if costs else None, costs.arnona_monthly_max if costs else None)):
        if monthly is None:
            continue
        if top is not None:  # v1.59: the text and Yad2's field disagree: the card shows a range, which is a check
            out[qid] = {"answer": UNCLEAR, "evidence": f"fees: {monthly:g}-{top:g}", "source": "rules"}
        elif monthly == 0:
            # v1.62: 0 is "the rent includes it" or "there is none" (Komo batch 1: "אין תשלום ועד בית"); the card says
            # "no separate fee", true of both, and the text's own answer says which one it was
            said = text_answers.get(qid) or {}
            zero = said.get("answer") == "amount" and said.get("value") == 0
            out[qid] = {"answer": "amount", "value": 0, "evidence": "fees", "source": "rules"} if zero else {"answer": "included", "evidence": "fees", "source": "rules"}
        else:
            out[qid] = {"answer": "amount", "value": int(monthly) if monthly == int(monthly) else monthly, "evidence": "fees", "source": "rules"}
    return out


def card_score_inputs(extracts: dict[str, dict[str, Any]], text_gold: dict[str, dict[str, dict[str, Any]]],
                      text_answers: dict[str, dict[str, dict[str, Any]]], prefs: Any
                      ) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, str]]]:
    """For the listings in all three: (card gold, card answers, what the boxes did)."""
    gold, answers, how = {}, {}, {}
    for k, x in extracts.items():
        if k not in text_gold or k not in text_answers:
            continue
        gold[k], how[k] = card_gold(text_gold[k], x)
        answers[k] = card_answers(x, text_answers[k], prefs)
    return gold, answers, how


def load_extracts(*folders: Any) -> dict[str, dict[str, Any]]:
    import json
    from pathlib import Path
    out: dict[str, dict[str, Any]] = {}
    for d in folders:
        for f in sorted(Path(d).glob("*.json")):
            x = json.loads(f.read_text(encoding="utf-8"))
            if "error" in x:
                continue
            try:  # the product drops a listing its adapter can't read (no usable price): so does the test
                site_listing(x)
            except ValueError:
                continue
            out[f.stem] = x
    return out
