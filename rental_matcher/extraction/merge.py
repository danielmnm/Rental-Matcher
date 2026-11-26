"""
Phase 2: merge what a listing's structured fields say with what its text
says into the signals the scoring engine reads.

The adapter's structured signals only ever confirm (a ticked box); the
text can confirm or deny. When both speak:
- they agree -> CONFIRMED, with both as evidence;
- they disagree -> CONFLICTING, no value, both quoted. The scoring engine
  treats that as unknown, which makes a dealbreaker a check: a human looks,
  nothing is silently picked.
Parking is a tier, not a yes/no: the structured value is a LOWER bound
("there's a space"), so a text tier above it refines it. A text tier below
it wins too when it says where (v1.56, owner ruling: the text is stronger than
the box): "חניה בכביש" with the box ticked is street parking; "חניה בשפע"
alone may be the lot's, so that still conflicts.

An "unclear" text answer becomes an UNCONFIRMED signal carrying the words
to look at: no value, so scoring treats it as unknown (a check on a
dealbreaker), but the check can quote what the listing actually said. It
never overrides a ticked box.

Furniture is a list of what the text names (merge doesn't trust a ticked
"furniture" box for more than a claim: owners tick it for one chair). The
box alone gives an UNCONFIRMED furniture signal ("ticked, but the text
doesn't say what's there"); next to a text list it's only noted.

A fan the rules saw becomes its own `fan` signal, so scoring can put
"+fan" next to the air conditioning.

Who read it is kept (`extracted_by`): RULE when the rules gave or agreed
with the answer, LLM when only the model did. Scoring won't let an LLM-only
answer hide a listing by itself.
"""

from __future__ import annotations

from typing import Any

from ..schema import ExtractedBy, Signal, SignalStatus
from .questions import PLACES_PARKING as _PLACES_IT, QUESTIONS, UNCLEAR


def _reader(entry: dict[str, Any]) -> ExtractedBy:
    """combine() tags each answer with its source; an untagged one is
    treated as the model's, the less trusted reader."""
    return ExtractedBy.RULE if entry.get("source") in ("rules", "both") else ExtractedBy.LLM


def text_signals(answers: dict[str, dict[str, Any]]) -> dict[str, Signal]:
    """One listing's text answers -> signals: a mapped answer is CONFIRMED,
    "unclear" is UNCONFIRMED with its quote; not_stated and unmapped
    answers give no signal."""
    out: dict[str, Signal] = {}
    for q in QUESTIONS:
        entry = answers.get(q.id) or {}
        answer = entry.get("answer")
        if q.signal is None:
            continue
        if answer == UNCLEAR:
            out[q.signal] = Signal(status=SignalStatus.UNCONFIRMED, evidence=f"text, unclear: {entry.get('evidence') or '?'}",
                                   extracted_by=_reader(entry))
        elif q.items and answer == "items" and entry.get("items"):
            out[q.signal] = Signal(status=SignalStatus.CONFIRMED, value=sorted(entry["items"]),
                                   evidence=f"text: {entry.get('evidence') or ', '.join(entry['items'])}",
                                   extracted_by=_reader(entry))
        elif answer in q.values:
            out[q.signal] = Signal(
                status=SignalStatus.CONFIRMED,
                value=q.values[answer],
                evidence=f"text: {entry.get('evidence') or answer}",
                extracted_by=_reader(entry),
            )
            if q.signal == "parking_level" and entry.get("or"):
                # v1.53: "יש חניה", "2 חניות": the lowest tier it can mean, and that it's only a floor
                out["parking_at_least"] = Signal(status=SignalStatus.CONFIRMED, value=True,
                                                 evidence=f"text: {entry.get('evidence') or answer} (whose isn't said)",
                                                 extracted_by=_reader(entry))
    note = (answers.get("air_conditioning") or {}).get("note") or ""
    if note.startswith("+fan: "):
        out["fan"] = Signal(status=SignalStatus.CONFIRMED, value=True, evidence=f"text: {note[len('+fan: '):]}",
                            extracted_by=ExtractedBy.RULE)
    return out


BOX = "furniture_box"  # Yad2's "ריהוט" checkbox, as the adapter reads it


def _conflict(a: Signal, b: Signal) -> Signal:
    return Signal(status=SignalStatus.CONFLICTING, evidence=f"{a.evidence} | {b.evidence}", extracted_by=b.extracted_by)


def merge(structured: dict[str, Signal], text: dict[str, Signal]) -> dict[str, Signal]:
    merged = dict(structured)
    for name, t in text.items():
        s = structured.get(name)
        if s is None or s.status != SignalStatus.CONFIRMED:
            merged[name] = t
        elif t.status != SignalStatus.CONFIRMED:
            continue  # unclear text doesn't unsay a ticked box
        elif name == "parking_level" and t.value != s.value:
            # the box says "a space" (the lowest tier it can mean); the text can say more. v1.56 (owner ruling,
            # Oct 30): the text also wins when it says less ("חניה בכביש" with the box ticked): posters
            # tick the box for street parking too, as they tick "ריהוט" for one chair. Only words that
            # place it ("ברחוב", "בכביש", a city bay, a permit): "חניה בשפע" alone may be the lot's (batch 10)
            if t.value > s.value:
                merged[name] = t
            elif t.value == 1.0 and _PLACES_IT.search(t.evidence or ""):
                merged[name] = t.model_copy(update={"evidence": f"{t.evidence} (Yad2's box is ticked; the text says where)"})
            else:
                merged[name] = _conflict(s, t)
        elif t.value == s.value:  # agreeing: still the site's own word, with both quotes (v1.28: parking became "the model's word")
            merged[name] = Signal(status=SignalStatus.CONFIRMED, value=s.value,
                                  evidence=f"{s.evidence} | {t.evidence}", extracted_by=s.extracted_by)
        else:
            merged[name] = _conflict(s, t)
    # v1.53: the box's parking is only a lower bound; once the text says which tier (or contradicts
    # the box), the card goes by that, and "whose isn't said" no longer applies
    if ("parking_at_least" in merged and merged.get("parking_level") is not structured.get("parking_level")
            and "parking_at_least" not in text):  # the text's own "whose isn't said" stands (v1.53)
        merged.pop("parking_at_least")
    box = structured.get(BOX)
    if box is not None and box.status == SignalStatus.CONFIRMED and box.value is True:
        t = text.get("furniture")
        if t is not None and t.status == SignalStatus.CONFIRMED:
            merged["furniture"] = t.model_copy(update={"evidence": f"{t.evidence} | {box.evidence}"})
        else:
            said = f"; {t.evidence}" if t is not None and t.evidence else "; the text doesn't say what's there"
            merged["furniture"] = Signal(status=SignalStatus.UNCONFIRMED, evidence=f"{box.evidence} (a claim, not a list){said}",
                                         extracted_by=box.extracted_by)
    return merged
