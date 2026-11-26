"""
Phase 1: the deterministic scoring engine.

A user's PreferenceSet (loaded from JSON, see preferences/) turns a Listing
into a ScoredListing: hidden or shown (with reasons), what still needs
checking by hand, what's shown despite a soft limit, and a match
percentage shown as an honest range.

Every criterion has one RELEVANCE, 1-10, set by the user (format 2,
v1.12): how strict it is. Until v1.26 it was also the weight; now a
must-have's weight is its own (see WEIGHT below):

- 10 is a DEALBREAKER. Past the limit, the listing is hidden, with the
  reason. If the listing doesn't say, it's KEPT with a "check" note --
  never hidden on a guess. A dealbreaker with nothing to grade (yes/no,
  or a bare at_most / at_least line) is a pure filter: every listing that
  passes it scores the same on it, so weighting it would only flatten the
  score. A dealbreaker with a gradient (a ranged one, like parking tiers
  or a commute with an ideal) is also weighted, by its gradient.
- 1-9 is SOFT. Past the limit the listing is still shown, with a flag,
  and its satisfaction keeps falling until it reaches 0 at the limit plus
  `falloff`. An optional `tolerance` sets an outer edge: past the limit
  plus the tolerance, a soft criterion hides the listing too (a
  negotiable budget, but not unlimited).
- WEIGHT = points / sum of everyone's points (v1.26). A criterion's points
  are its `weight` (0-9) if the user set one; otherwise a soft criterion's
  relevance, and MUST_HAVE_POINTS (5) for a must-have with a gradient.
  Being a must-have and counting in the match are separate questions: a
  must-have hides what fails it, and only its gradient (own parking over
  street parking, a shorter ride) counts toward the match.
- HAS_ITEMS reads a list signal (the furniture the text names) against
  the items wanted: satisfaction is the share named; an unnamed item is
  unknown (the high end of the range counts it), unless the text says the
  apartment is unfurnished. Never a dealbreaker: a list that doesn't name
  the bed doesn't say there's no bed.
- A dealbreaker only the AI read gets a check either way: one it fails
  can't hide the listing, one it passes is marked "verify".
- SATISFACTION runs 0 to 1: yes/no scores 1 or 0; ranged is linear from
  the ideal (1) to its zero point; a line (at_most / at_least) scores 1
  inside it.
- UNKNOWN is never guessed as a fact. The match is a range: low counts
  every unknown as unmet, high as met. `expected` and the LIKELY range
  (v1.23) use the measured odds for an unstated fact (rental_matcher/priors:
  e.g. an elevator a listing doesn't mention is there ~5% of the time), or
  even odds where there's no measurement: the expected match, and the 10th
  to 90th percentile of what it could turn out to be. FAIL RISK is the
  chance an unstated must-have turns out to fail. Odds only ever estimate
  the match and order the list; they never hide or pass anything.
- An OVERRIDE loosens a criterion's ideal and/or limit when a signal is
  confirmed true (the budget rises to 5,000 with a balcony) -- by a rule
  or a ticked box: a True only the AI read is treated as unknown, so a
  model's guess can't loosen a rule. Overrides may
  only loosen, and when several apply the most generous values win, so
  their order never matters. If a condition is unknown and only it would
  keep a listing visible, the result is a check, not a hidden listing.
- A TOLERANCE on a dealbreaker is an exception band: past the limit but
  inside the band, the listing is kept with a check ("floor 3: only for an
  exceptional apartment"). It never changes the score.

Values come from the listing: "price", "size_m2", "rooms", "floor", or
"signal:<name>" for anything in the open signals map. A signal counts as
known only when its status is CONFIRMED.

Format 1 files (`must_have` + `importance`, before v1.12) still load:
a must-have becomes relevance 10; anything else keeps its importance,
capped at 9 so it can't silently become a dealbreaker. That conversion is
exact for what is hidden or shown; scores can differ, since a format 1
must-have could carry a separate weight.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from itertools import product
from typing import Any, Callable, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, ValidationError, field_validator, model_validator

from .schema import ExtractedBy, Listing, SignalStatus
from .commute import Commute

_LISTING_FIELDS = ("price", "size_m2", "rooms", "floor")


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


_SIGNAL_NAME = r"[A-Za-z0-9_]+"


class Override(_Config):
    when_signal: str = Field(pattern=rf"^{_SIGNAL_NAME}$", description="Applies when this signal is CONFIRMED true.")
    ideal: Optional[float] = None
    limit: Optional[float] = None

    @model_validator(mode="after")
    def _changes_something(self) -> "Override":
        if self.ideal is None and self.limit is None:
            raise ValueError(f"override on {self.when_signal!r} changes neither ideal nor limit")
        return self


DEALBREAKER = 10
# A must-have's gradient counts like a middling nice-to-have unless the user
# says otherwise (v1.26). Before, it counted 10, the most of anything, so an
# unstated parking tier swung a listing by a quarter of its match.
MUST_HAVE_POINTS = 5


class Preference(_Config):
    name: str = Field(pattern=rf"^{_SIGNAL_NAME}$")
    label: str = Field(pattern=r"\S", description="How the preference is shown to the user.")
    field: str = Field(description='"price", "size_m2", "rooms", "floor", or "signal:<name>".')
    kind: Literal["yes_no", "ranged", "at_most", "at_least", "has_items"]
    # StrictInt: "5" or true must not quietly become a relevance.
    relevance: StrictInt = Field(ge=1, le=10, description="1-9 soft, 10 dealbreaker.")
    # yes_no
    wants: Optional[bool] = None
    # has_items: the ids wanted from a list signal (furniture)
    items: Optional[list[str]] = Field(default=None, min_length=1)
    # ranged: lower is better when ideal < limit, higher is better when ideal > limit
    # at_most / at_least: a line at `limit`, no ideal
    ideal: Optional[float] = None
    limit: Optional[float] = None
    tolerance: Optional[float] = Field(
        default=None, gt=0,
        description="Dealbreaker: an exception band past the limit (kept with a check). "
        "Soft: the outer edge past the limit beyond which the listing is hidden.",
    )
    tolerance_note: Optional[str] = Field(default=None, pattern=r"\S", description="Shown with the check or flag.")
    falloff: Optional[float] = Field(
        default=None, gt=0, description="Soft only: how far past the limit satisfaction reaches 0."
    )
    overrides: list[Override] = Field(default_factory=list)
    # v1.26: how much this counts in the match, 0-9, apart from whether it's a
    # must-have. Unset: a soft criterion counts its relevance; a must-have
    # with a gradient (ranged) counts MUST_HAVE_POINTS; any other must-have
    # is a pure filter (0). 0: never in the match, only hides or flags.
    weight: Optional[StrictInt] = Field(default=None, ge=0, le=10)  # v1.30: the setup page's 1-10 scale

    @property
    def dealbreaker(self) -> bool:
        return self.relevance == DEALBREAKER

    @property
    def points(self) -> int:
        """This criterion's share of the match, before normalizing."""
        if self.weight is not None:
            return self.weight
        if not self.dealbreaker:
            return self.relevance
        return MUST_HAVE_POINTS if self.kind == "ranged" else 0

    @property
    def weighted(self) -> bool:
        """A criterion with no points is a pure filter."""
        return self.points > 0

    @field_validator("field")
    @classmethod
    def _known_field(cls, v: str) -> str:
        if v in _LISTING_FIELDS or re.fullmatch(rf"signal:{_SIGNAL_NAME}", v):
            return v
        raise ValueError(f"unknown field {v!r}")

    @model_validator(mode="after")
    def _consistent(self) -> "Preference":
        if len({o.when_signal for o in self.overrides}) != len(self.overrides):
            raise ValueError(f"{self.name}: two overrides on the same signal")
        if self.tolerance_note is not None and self.tolerance is None:
            raise ValueError(f"{self.name}: `tolerance_note` without a `tolerance`")
        if self.items is not None and self.kind != "has_items":
            raise ValueError(f"{self.name}: `items` is only for a has_items preference")
        if self.kind == "has_items":
            if (self.items is None or self.wants is not None or self.ideal is not None or self.limit is not None
                    or self.overrides or self.tolerance is not None or self.falloff is not None):
                raise ValueError(f"{self.name}: a has_items preference needs `items` and nothing else")
            if not self.field.startswith("signal:"):
                raise ValueError(f"{self.name}: a has_items preference must read a signal, not {self.field!r}")
            if self.dealbreaker:
                # A list that doesn't name the bed doesn't say there's no bed.
                raise ValueError(f"{self.name}: a has_items preference can't be a dealbreaker: an item the text "
                                 "doesn't name isn't known to be missing")
            return self
        if self.kind == "yes_no":
            if (self.wants is None or self.ideal is not None or self.limit is not None or self.overrides
                    or self.tolerance is not None or self.falloff is not None):
                raise ValueError(f"{self.name}: a yes/no preference needs `wants` and nothing ranged")
            if not self.field.startswith("signal:"):
                raise ValueError(f"{self.name}: a yes/no preference must read a signal, not {self.field!r}")
            return self
        if self.falloff is not None and self.dealbreaker:
            raise ValueError(f"{self.name}: a dealbreaker hides past its limit, so `falloff` doesn't apply")
        if self.kind == "ranged":
            if self.wants is not None or self.ideal is None or self.limit is None:
                raise ValueError(f"{self.name}: a ranged preference needs `ideal` and `limit`, not `wants`")
            for ideal, limit in [(self.ideal, self.limit)] + [
                (o.ideal if o.ideal is not None else self.ideal, o.limit if o.limit is not None else self.limit)
                for o in self.overrides
            ]:
                if ideal == limit:
                    raise ValueError(f"{self.name}: ideal and limit can't be equal")
                if (ideal < limit) != (self.ideal < self.limit):
                    raise ValueError(f"{self.name}: an override can't flip which direction is better")
        else:
            if self.wants is not None or self.ideal is not None or self.limit is None:
                raise ValueError(f"{self.name}: a threshold needs `limit` only, not `ideal` or `wants`")
            if any(o.ideal is not None for o in self.overrides):
                raise ValueError(f"{self.name}: a threshold has no ideal for an override to change")
            if not self.dealbreaker and self.falloff is None and self.tolerance is None and self.limit <= 0:
                raise ValueError(
                    f"{self.name}: a soft threshold at {self.limit:g} needs an explicit `falloff` "
                    "(the default is relative to a positive limit)"
                )
        lower_is_better = _lower_is_better(self)
        for o in self.overrides:
            for new, base in ((o.ideal, self.ideal), (o.limit, self.limit)):
                if new is not None and base is not None and (new < base if lower_is_better else new > base):
                    raise ValueError(
                        f"{self.name}: the override on {o.when_signal!r} tightens the preference; "
                        "overrides may only loosen it"
                    )
        return self


_LAX_BOOL: TypeAdapter[bool] = TypeAdapter(bool)


def _from_format_1(data: dict) -> dict:
    """Format 1 (must_have + importance) -> format 2 (relevance). See the
    module docstring for what the conversion keeps. `must_have` is read the
    way format 1's model read it (Pydantic's lax bool: 1, "true", "yes"),
    so a file that hid a listing still hides it; anything else is an error."""
    converted = dict(data)
    converted["format_version"] = 2
    prefs = []
    for raw in data.get("preferences", []):
        if not isinstance(raw, dict):
            prefs.append(raw)
            continue
        pref = {k: v for k, v in raw.items() if k not in ("must_have", "importance")}
        importance = raw.get("importance")
        try:
            must_have = _LAX_BOOL.validate_python(raw.get("must_have", False))
        except ValidationError as e:
            raise ValueError(f"preference {raw.get('name')!r}: must_have {raw.get('must_have')!r} is not a boolean") from e
        if not must_have and raw.get("kind") in ("at_most", "at_least") and "falloff" not in raw \
                and "tolerance" not in raw and isinstance(raw.get("limit"), (int, float)) and raw["limit"] <= 0:
            # Format 1 scored a soft line all-or-nothing; format 2's default
            # falloff is relative to a positive limit, so give it one unit.
            pref["falloff"] = 1
        if must_have:
            pref["relevance"] = DEALBREAKER
        elif isinstance(importance, int) and not isinstance(importance, bool):
            pref["relevance"] = min(importance, DEALBREAKER - 1)
        else:
            pref["relevance"] = importance  # invalid either way; let validation say so
        prefs.append(pref)
    converted["preferences"] = prefs
    return converted


class Search(_Config):
    """A rentals search the extension runs on a pull, as the site's own
    address bar shows it (v1.24): one per city or area the user looks in."""

    source: Literal["yad2"] = "yad2"
    label: str = Field(min_length=1)
    label_he: Optional[str] = None  # the same name in Hebrew (v1.26), for a Hebrew screen
    path: str = Field(pattern=r"^/realestate/rent(/[a-z0-9-]+)?\?[A-Za-z0-9=&_.,-]+$")
    # v1.26: only these neighborhoods of the city (Yad2's ids). Yad2 filters one
    # neighborhood per search; for several, the city is read once and kept to them.
    hoods: list[StrictInt] = Field(default_factory=list)
    # v1.33: their names, and where every neighborhood of the city is ([id, lat, lng]), so a
    # listing can be kept to them even when Yad2's search rows don't carry the neighborhood's id
    hood_names: list[str] = Field(default_factory=list)
    centers: list[tuple[StrictInt, float, float]] = Field(default_factory=list)
    # v1.67: Yad2 serves this place on another site (Ma'ale Adumim and Ariel on yad-il.co.il, Nov 19), which a pull run
    # from a Yad2 tab can't read: the pull says so instead of showing a failed page
    elsewhere: Optional[Literal["yad-il.co.il"]] = None


class PreferenceSet(_Config):
    format_version: Literal[2] = 2
    owner: str = Field(min_length=1)
    note: str = ""
    preferences: list[Preference] = Field(min_length=1)
    # Places the user wants to be close to; each fills the signal its
    # preference reads (see commute.py). Optional: older files have none.
    commutes: list[Commute] = Field(default_factory=list)
    # Where to look. Optional: without them, a pull reads the search open in the tab.
    searches: list[Search] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data: object) -> object:
        """Format 1 is `format_version: 1`, or no version and no preference
        using `relevance` (every file before v1.12). A file that uses
        `relevance` without declaring a version is read as format 2."""
        if not isinstance(data, dict):
            return data
        version = data.get("format_version")
        prefs = data.get("preferences")
        uses_relevance = isinstance(prefs, list) and any(isinstance(p, dict) and "relevance" in p for p in prefs)
        if version == 1 or (version is None and not uses_relevance):
            return _from_format_1(data)
        return data

    @model_validator(mode="after")
    def _unique_names(self) -> "PreferenceSet":
        names = [p.name for p in self.preferences]
        if len(names) != len(set(names)):
            raise ValueError("preference names must be unique")
        signals = [c.signal for c in self.commutes]
        if len(signals) != len(set(signals)):
            raise ValueError("two commutes fill the same signal")
        return self

    @classmethod
    def load(cls, path: Union[str, Path]) -> "PreferenceSet":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


Status = Literal["met", "partly met", "not met", "unknown"]


class PreferenceResult(_Config):
    name: str
    label: str
    relevance: int
    dealbreaker: bool
    weight: Optional[float]  # share of the match, 0-1; None if not scored
    satisfaction: Optional[float]  # 0-1; None if unknown
    status: Status
    detail: str


class Note(_Config):
    """One check, flag or reason, as data (v1.26), for a card in any language.
    kind: what it does (hides, needs a look, shown past a soft limit).
    reason: unstated, unclear, unexpected, verify (only the AI read it), no
    (a must-have the listing doesn't have), past (past the limit), over (past
    a soft limit), needs (fine only if `needs` is confirmed), exception (in
    the must-have's exception band), companion (a fan next to the A/C)."""

    name: str
    kind: Literal["flag", "check", "exclude"]
    reason: str
    value: Any = None
    limit: Optional[float] = None
    needs: list[str] = Field(default_factory=list)
    companion: Optional[str] = None


class UnknownImpact(_Config):
    """An unstated fact and what it can do to the match."""
    signals: list[str]  # what's unstated (a "?<preference>" has no measured odds)
    labels: list[str]  # the preferences it moves
    worth: float  # points of the match (0-100) between its worst and best outcome
    odds: Optional[list[tuple[Any, float]]] = None  # measured odds of each value, if any
    n: Optional[int] = None  # how many labeled listings the odds come from


class ScoredListing(_Config):
    listing_id: str
    excluded: bool  # hidden
    exclusion_reasons: list[str]
    checks: list[str]  # things to verify by hand before trusting the result
    flags: list[str]  # shown, but past a soft limit
    match_low: Optional[float]  # 0-100; None when nothing is weighted
    match_high: Optional[float]
    match_expected: Optional[float]
    unknown: list[str]  # labels of weighted preferences with no data
    results: list[PreferenceResult]
    match_likely_low: Optional[float] = None  # 10th percentile of what the match could turn out to be
    match_likely_high: Optional[float] = None  # 90th percentile
    fail_risk: Optional[float] = None  # 0-1: the chance an unstated must-have turns out to fail
    fail_risk_from: list[str] = Field(default_factory=list)  # which must-haves, with their odds
    fail_risk_parts: list[tuple[str, float]] = Field(default_factory=list)  # (must-have's label, chance it fails)
    notes: list[Note] = Field(default_factory=list)  # checks, flags and reasons as data
    unknowns: list[UnknownImpact] = Field(default_factory=list)  # biggest first
    sat: dict[str, float] = Field(default_factory=dict)  # v1.32: each weighted criterion's expected satisfaction, 0-1

    @property
    def rank_value(self) -> float:
        """What the list is ordered by: the expected match, times the chance
        every must-have holds."""
        return (self.match_expected or 0.0) * (1.0 - (self.fail_risk or 0.0))


def _lower_is_better(pref: Preference) -> bool:
    if pref.kind == "at_most":
        return True
    if pref.kind == "at_least":
        return False
    assert pref.ideal is not None and pref.limit is not None
    return pref.ideal < pref.limit


# v1.53: a signal whose value is only a lower bound when this one is set: (its name, what to ask)
# v1.53: a signal that caps an unknown value: (its name, the most the value can be, what it says)
_AT_MOST = {"parking_level": ("no_parking_space", 1.0, "no parking space comes with it (Yad2: חניות ללא)")}
_AT_LEAST = {"parking_level": ("parking_at_least", "the listing doesn't say whose parking it is (the street's, the building's or the apartment's own); ask")}  # v1.61: the old wording fit only Yad2's ticked box


def _value(listing: Listing, field: str) -> tuple[bool, object]:
    """(known, value). Known = a listing field that's set, or a signal
    that's CONFIRMED (its value may still be the wrong type)."""
    if field == "price":
        return True, listing.price.amount
    if field in ("size_m2", "rooms", "floor"):
        value = getattr(listing, field)
        return value is not None, value
    signal = listing.signals.get(field.removeprefix("signal:"))
    if signal is None or signal.status != SignalStatus.CONFIRMED:
        return False, None
    return True, signal.value


def _ai_only(listing: Listing, field: str) -> Optional[str]:
    """The evidence of a CONFIRMED signal that only the language model read
    (no rule, no ticked box agreed), else None. Such a value scores and
    flags, but never hides a listing on its own: a model that misreads
    "ללא עמודים" as "no elevator" mustn't make a good apartment vanish."""
    if not field.startswith("signal:"):
        return None
    signal = listing.signals.get(field.removeprefix("signal:"))
    if signal is None or signal.status != SignalStatus.CONFIRMED or signal.extracted_by != ExtractedBy.LLM:
        return None
    return signal.evidence or "?"


def _unclear_detail(listing: Listing, field: str) -> Optional[str]:
    """For an unknown signal that's unknown because the listing is unclear
    or contradicts itself: what it says, so the check points at the words."""
    if not field.startswith("signal:"):
        return None
    signal = listing.signals.get(field.removeprefix("signal:"))
    if signal is None or signal.status not in (SignalStatus.UNCONFIRMED, SignalStatus.CONFLICTING) or not signal.evidence:
        return None
    return f"unclear ({signal.evidence})"


def _signal_state(listing: Listing, name: str) -> Optional[bool]:
    """True/False when CONFIRMED with a boolean value; None otherwise. A
    True only the AI read counts as unknown: a model's guess may not
    loosen a rule (a guessed balcony must not raise the budget), so such a
    listing gets a check ("passes only if balcony is confirmed")."""
    signal = listing.signals.get(name)
    if signal is None or signal.status != SignalStatus.CONFIRMED or not isinstance(signal.value, bool):
        return None
    if signal.value is True and signal.extracted_by == ExtractedBy.LLM:
        return None
    return signal.value


# A signal that qualifies another one when both are there: "+fan" next to the
# air conditioning, since a fan can stand in for an A/C a room doesn't have.
_COMPANIONS = {"air_conditioning": ("fan", "+fan", "a fan may stand in for an A/C a room doesn't have: ask which rooms have one")}

# has_items: ids that are general claims, and ids that are built in rather
# than furniture. Shown, never counted as a wanted item unless asked for.
_CLAIMS = {"says_furnished": "says furnished", "says_partly_furnished": "says partly furnished",
           "says_unfurnished": "says unfurnished", "says_equipped": "says it comes with appliances"}
_BUILT_IN = ("closets", "oven_stove")


def _items_detail(named: set[str], have: list[str], wanted: list[str]) -> str:
    parts = [f"has {', '.join(have)}" if have else "names none of them"]
    parts[0] += f" ({len(have)} of {len(wanted)} wanted" + ("" if len(have) == len(wanted) else "; the rest not stated") + ")"
    other = sorted(i for i in named if i not in have and i not in _CLAIMS and i not in _BUILT_IN)
    built = sorted(i for i in named if i in _BUILT_IN and i not in have)
    if other:
        parts.append(f"also {', '.join(other)}")
    if built:
        parts.append(f"built in: {', '.join(built)}")
    parts.extend(text for claim, text in _CLAIMS.items() if claim in named)
    return "; ".join(parts)


def _number(value: object) -> Optional[float]:
    """A finite number, or None. A non-finite value (inf, -inf, NaN) can't
    come from a valid listing -- the schema forbids it (allow_inf_nan=False)
    -- and can't be scored coherently: +/-inf would land at 0% or 100%
    depending only on its sign and the preference's direction, so a corrupt
    -inf bike time would read as a perfect commute. It's treated like any
    other unexpected confirmed value: not a number, surfaced as a check."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)  # an int too big for a float raises OverflowError
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _combine(pref: Preference, overrides: list[Override]) -> tuple[Optional[float], float]:
    """Base ideal/limit loosened by every given override: the most generous
    ideal and limit win. Satisfaction never decreases as either loosens,
    so this is the best these conditions can do, in any order. A
    threshold has no ideal (None)."""
    assert pref.limit is not None
    pick = max if _lower_is_better(pref) else min
    limit = pick([pref.limit] + [o.limit for o in overrides if o.limit is not None])
    if pref.ideal is None:
        return None, limit
    return pick([pref.ideal] + [o.ideal for o in overrides if o.ideal is not None]), limit


def _override_states(pref: Preference, listing: Listing) -> tuple[list[Override], list[Override]]:
    """(overrides that apply, overrides whose condition is unknown). A
    condition confirmed with a non-boolean value counts as unknown; it is
    reported separately (see `_corrupt_conditions`)."""
    applying, unknown = [], []
    for o in pref.overrides:
        state = _signal_state(listing, o.when_signal)
        if state is True:
            applying.append(o)
        elif state is None:
            unknown.append(o)
    return applying, unknown


def _corrupt_conditions(prefs: PreferenceSet, listing: Listing) -> list[str]:
    """Override conditions confirmed with a value that isn't a boolean
    ("yes"): treated as unknown, and surfaced so the extractor can be fixed."""
    found: dict[str, object] = {}
    for pref in prefs.preferences:
        for o in pref.overrides:
            signal = listing.signals.get(o.when_signal)
            if signal is not None and signal.status == SignalStatus.CONFIRMED and not isinstance(signal.value, bool):
                found.setdefault(o.when_signal, signal.value)
    return [f"{name}: unexpected value {value!r}" for name, value in found.items()]


def _ranged_satisfaction(value: float, ideal: float, zero: float) -> float:
    position = (zero - value) / (zero - ideal)  # 1 at ideal, 0 at the zero point, either direction
    return min(1.0, max(0.0, position))


_EPSILON = 1e-9


def _within(value: float, limit: float, lower_is_better: bool) -> bool:
    """Inclusive, with a relative epsilon: 1.1 - 1.0 is 0.10000000000000009
    in floating point, and a value exactly at an edge must count as inside."""
    slack = _EPSILON * max(1.0, abs(limit))
    return value <= limit + slack if lower_is_better else value >= limit - slack


def _shift(limit: float, by: float, lower_is_better: bool) -> float:
    """`limit` moved `by` in the loosening direction."""
    return limit + by if lower_is_better else limit - by


def _falloff(pref: Preference) -> float:
    """Soft criteria: how far past the limit satisfaction reaches 0. An
    explicit `falloff` wins, then the tolerance (so a soft criterion hits 0
    at its outer edge), then a default: a ranged one at its limit (as it
    always has), a line at double its limit (at_most) or half of it
    (at_least). Fixed from the base limit, so loosening an override moves
    the zero point with the limit and satisfaction never drops."""
    if pref.falloff is not None:
        return pref.falloff
    if pref.tolerance is not None:
        return pref.tolerance
    if pref.kind == "ranged":
        return 0.0
    assert pref.limit is not None and pref.limit > 0
    return pref.limit if pref.kind == "at_most" else pref.limit / 2


def _satisfaction(pref: Preference, value: float, ideal: Optional[float], limit: float) -> float:
    lower = _lower_is_better(pref)
    if ideal is not None:
        zero = limit if pref.dealbreaker else _shift(limit, _falloff(pref), lower)
        return _ranged_satisfaction(value, ideal, zero)
    if _within(value, limit, lower):
        return 1.0
    if pref.dealbreaker:
        return 0.0
    return max(0.0, 1.0 - abs(value - limit) / _falloff(pref))


def _rescuers(pref: Preference, value: float, applying: list[Override], unknown: list[Override], by: float) -> list[str]:
    """Unknown conditions that would, each on its own, admit `value` (with
    the limit moved `by`). Admission depends only on the limit, and the
    combined limit is the single most generous one, so whenever all the
    unknowns together admit `value`, at least one of them does alone."""
    lower = _lower_is_better(pref)
    names = [o.when_signal for o in unknown if _within(value, _shift(_combine(pref, applying + [o])[1], by, lower), lower)]
    assert names
    return names


Outcome = Literal["flag", "check", "exclude"]


def _past_limit_outcome(
    pref: Preference, value: float, applying: list[Override], unknown: list[Override]
) -> tuple[Outcome, str, dict[str, Any]]:
    """What happens to a listing whose value is past the limit that holds
    given what's known: hidden, kept with a check, or (soft) shown with a
    flag. Never hidden if an unknown condition could keep it visible."""
    lower = _lower_is_better(pref)
    tolerance = pref.tolerance or 0.0
    limit = _combine(pref, applying)[1]
    best_limit = _combine(pref, applying + unknown)[1]
    in_band_now = tolerance > 0 and _within(value, _shift(limit, tolerance, lower), lower)
    in_band_best = tolerance > 0 and _within(value, _shift(best_limit, tolerance, lower), lower)
    head = f"{pref.label}: {value:g}"

    if pref.dealbreaker:
        note = pref.tolerance_note or "kept as an exception"
        if _within(value, best_limit, lower):
            needs = _rescuers(pref, value, applying, unknown, 0.0)
            message = f"{head} passes only if {' or '.join(needs)} is confirmed"
            if in_band_now:
                message += f"; otherwise {note}"
            return "check", message, {"reason": "needs", "needs": needs, "limit": limit}
        if in_band_best:
            message = f"{head} is past the limit of {limit:g}; {note}"
            needs = [] if in_band_now else _rescuers(pref, value, applying, unknown, tolerance)
            if needs:
                message += f", only if {' or '.join(needs)} is confirmed"
            return "check", message, {"reason": "exception", "needs": needs, "limit": limit}
    else:
        note = pref.tolerance_note or "scored lower"
        if tolerance == 0 or in_band_now:
            message = f"{head} is past the limit of {limit:g}; {note}"
            needs = _rescuers(pref, value, applying, unknown, 0.0) if _within(value, best_limit, lower) else []
            if needs:
                message += f", within it if {' or '.join(needs)} is confirmed"
            return "flag", message, {"reason": "over", "needs": needs, "limit": limit}
        if in_band_best:
            needs = _rescuers(pref, value, applying, unknown, tolerance)
            return "check", (
                f"{head} is past the limit of {limit:g}; {note}, shown only if "
                f"{' or '.join(needs)} is confirmed"
            ), {"reason": "over", "needs": needs, "limit": limit}
    past = f"{best_limit:g}" + (f" (tolerance {tolerance:g})" if tolerance else "")
    return "exclude", f"{head} is past the limit of {past}", {"reason": "past", "needs": [], "limit": best_limit}


Dist = list[tuple[Any, float]]
EVEN: Dist = [(True, 0.5), (False, 0.5)]
Priors = dict[str, Dist]


def _odds(listing: Listing, signal: str, priors: Priors) -> tuple[Dist, bool]:
    """(odds for an unknown signal, measured?). The measured odds are for a
    listing that's silent on it; one that says something unclear or
    contradictory gets even odds."""
    if signal in priors and signal not in listing.signals:
        return priors[signal], True
    return EVEN, False


def _rescue_risk(pref: Preference, listing: Listing, value: Optional[float], priors: Priors) -> Optional[float]:
    """A must-have whose known value is past the limit that holds, kept only
    because an unknown override could still admit it ("floor 4, fine if
    there's an elevator"): the chance that none of those overrides holds.
    None when it isn't such a case, or an override's odds aren't measured
    (v1.28: this risk used to be 0)."""
    if not pref.dealbreaker or value is None or pref.limit is None or pref.kind not in ("ranged", "at_most", "at_least"):
        return None
    applying, unknown = _override_states(pref, listing)
    if not unknown:
        return None
    lower, tolerance = _lower_is_better(pref), pref.tolerance or 0.0
    if _within(value, _shift(_combine(pref, applying)[1], tolerance, lower), lower):
        return None  # kept whatever the overrides say
    rescuers = {o.when_signal for o in unknown if _within(value, _shift(_combine(pref, applying + [o])[1], tolerance, lower), lower)}
    if not rescuers:
        return None
    none_hold = 1.0
    for name in sorted(rescuers):
        odds, measured = _odds(listing, name, priors)
        if not measured:
            return None
        none_hold *= sum(p for v, p in odds if v is not True)
    return none_hold


def _outlook(listing: Listing, prefs: PreferenceSet, results: list[PreferenceResult], priors: Priors,
             n_of: dict[str, int]) -> dict[str, Any]:
    """Expected match, likely range, fail risk and what each unknown is worth."""
    const = 0.0
    pieces: list[tuple[list[str], float, Callable[[dict[str, Any]], float], str]] = []  # (deps, weight, satisfaction, label)
    piece_names: list[str] = []  # v1.32: the preference each piece belongs to
    exp_sat: dict[str, float] = {}  # v1.32: each weighted criterion's expected satisfaction, 0-1
    dists: dict[str, Dist] = {}
    measured: set[str] = set()

    def need(name: str) -> str:
        if name not in dists:
            dists[name], m = _odds(listing, name, priors)
            if m:
                measured.add(name)
        return name

    risk: list[tuple[str, str, float]] = []
    for pref, r in zip(prefs.preferences, results):
        signal = pref.field.removeprefix("signal:") if pref.field.startswith("signal:") else None
        known, raw = _value(listing, pref.field)
        if known and (rescue := _rescue_risk(pref, listing, _number(raw), priors)):
            risk.append((f"?{pref.name}", pref.label, rescue))
        if r.weight is None:
            # a must-have that counts 0 in the match still has a chance of failing (v1.28: only yes/no ones did)
            if pref.dealbreaker and r.satisfaction is None and not known and signal:
                odds, m = _odds(listing, signal, priors)
                if m and pref.kind == "yes_no":
                    risk.append((signal, pref.label, sum(p for v, p in odds if v != pref.wants)))
                elif m and pref.kind in ("ranged", "at_most", "at_least") and pref.limit is not None:
                    limit = _combine(pref, _override_states(pref, listing)[0])[1]
                    lower = _lower_is_better(pref)
                    risk.append((signal, pref.label, sum(p for v, p in odds if (n := _number(v)) is None or not _within(n, limit, lower))))
            continue
        w = r.weight
        if r.satisfaction is None:
            if pref.kind == "yes_no" and signal:
                dep = need(signal)
                pieces.append(([dep], w, lambda a, d=dep, want=pref.wants: 1.0 if a[d] == want else 0.0, pref.label))
                piece_names.append(pref.name)
            elif pref.kind in ("ranged", "at_most", "at_least") and signal and _odds(listing, signal, priors)[1]:
                dep = need(signal)
                applying, _ = _override_states(pref, listing)
                ideal, limit = _combine(pref, applying)
                pieces.append(([dep], w, lambda a, d=dep, p=pref, i=ideal, lim=limit: _satisfaction(p, float(a[d]), i, lim), pref.label))
                piece_names.append(pref.name)
                if pref.dealbreaker:
                    lower = _lower_is_better(pref)
                    risk.append((dep, pref.label, sum(p for v, p in dists[dep] if not _within(float(v), limit, lower))))
            else:
                dep = f"?{pref.name}"
                dists[dep] = EVEN
                pieces.append(([dep], w, lambda a, d=dep: 1.0 if a[d] else 0.0, pref.label))
                piece_names.append(pref.name)
            continue
        if pref.kind == "has_items":
            best = 1.0 if r.satisfaction < 1.0 and "says_unfurnished" not in set(raw or []) else r.satisfaction
            if best > r.satisfaction:
                dep = f"?{pref.name}"
                dists[dep] = EVEN
                pieces.append(([dep], w, lambda a, d=dep, lo=r.satisfaction, hi=best: hi if a[d] else lo, pref.label))
                piece_names.append(pref.name)
            else:
                const += w * r.satisfaction
                exp_sat[pref.name] = r.satisfaction
            continue
        applying, unknown_overrides = _override_states(pref, listing)
        value = _number(raw)
        if unknown_overrides and value is not None:
            deps = [need(o.when_signal) for o in unknown_overrides]

            def sat(a: dict[str, Any], p=pref, v=value, ap=applying, un=unknown_overrides) -> float:
                return _satisfaction(p, v, *_combine(p, ap + [o for o in un if a[o.when_signal] is True]))

            pieces.append((deps, w, sat, pref.label))

            piece_names.append(pref.name)
        else:
            const += w * r.satisfaction
            exp_sat[pref.name] = r.satisfaction

    # each piece's expected satisfaction, over its own unknowns (v1.32: for the compare-two tuning)
    for (deps, _, f, _), name in zip(pieces, piece_names):
        names = sorted(set(deps))
        exp_sat[name] = round(sum(math.prod(p for _, p in combo) * f({n: v for n, (v, _) in zip(names, combo)})
                              for combo in product(*(dists[n] for n in names))), 4)

    # group pieces that share an unknown (a balcony moves both the balcony
    # score and the budget), so their outcomes move together
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    for deps, *_ in pieces:
        for d in deps[1:]:
            parent[find(d)] = find(deps[0])
    groups: dict[str, list] = {}
    for piece in pieces:
        groups.setdefault(find(piece[0][0]), []).append(piece)

    total: dict[float, float] = {round(const, 9): 1.0}
    impacts: list[UnknownImpact] = []
    for members in groups.values():
        names = sorted({d for deps, *_ in members for d in deps})
        outcomes: dict[float, float] = {}
        for combo in product(*(dists[n] for n in names)):
            a = {n: v for n, (v, _) in zip(names, combo)}
            prob = math.prod(p for _, p in combo)
            value = round(sum(w * f(a) for _, w, f, _ in members), 9)
            outcomes[value] = outcomes.get(value, 0.0) + prob
        merged: dict[float, float] = {}
        for t, pt in total.items():
            for v, pv in outcomes.items():
                k = round(t + v, 9)
                merged[k] = merged.get(k, 0.0) + pt * pv
        total = merged
        real = [n for n in names if n in measured]
        impacts.append(UnknownImpact(
            signals=names, labels=[label for *_, label in members],
            worth=round(100 * (max(outcomes) - min(outcomes)), 1),
            odds=dists[real[0]] if len(real) == 1 and len(names) == 1 else None,
            n=n_of.get(real[0]) if len(real) == 1 and len(names) == 1 else None))

    points = sorted(total.items())
    expected = sum(v * p for v, p in points)

    def quantile(q: float) -> float:
        acc = 0.0
        for v, p in points:
            acc += p
            if acc >= q - 1e-9:
                return v
        return points[-1][0]

    fail = 1.0 - math.prod(1.0 - p for _, _, p in risk) if risk else 0.0
    return {
        "expected": round(100 * expected, 1),
        "likely_low": round(100 * quantile(0.1), 1),
        "likely_high": round(100 * quantile(0.9), 1),
        "fail_risk": round(fail, 3),
        "fail_risk_from": [f"{label}: holds only if something unstated does ({round(100 * p)}% of listings like it don't)" if dep.startswith("?")
                           else f"{label}: not stated ({round(100 * p)}% of listings like it don't have it)" for dep, label, p in risk if p > 0],
        "fail_risk_parts": [(label, round(p, 3)) for _, label, p in risk if p > 0],
        "unknowns": sorted(impacts, key=lambda u: -u.worth),
        "sat": exp_sat,
    }


def score_listing(listing: Listing, prefs: PreferenceSet, priors: Optional[Priors] = None) -> ScoredListing:
    results: list[PreferenceResult] = []
    excluded_reasons: list[str] = []
    checks: list[str] = []
    flags: list[str] = []
    notes: list[Note] = []  # the same, as data (v1.26): what each check, flag and reason is about

    def note(kind: Outcome, pref: Preference, reason: str, value: Any = None, **kw: Any) -> None:
        notes.append(Note(name=pref.name, kind=kind, reason=reason, value=value, **kw))

    weighted = [p for p in prefs.preferences if p.weighted]
    total = sum(p.points for p in weighted)
    best_satisfaction: dict[str, float] = {}  # satisfaction if every unknown override holds

    for pref in prefs.preferences:
        weight = pref.points / total if pref.weighted else None
        known, raw = _value(listing, pref.field)
        satisfaction: Optional[float] = None
        status: Status = "unknown"

        if pref.kind == "has_items":
            assert pref.items is not None
            if known and isinstance(raw, list) and all(isinstance(i, str) for i in raw):
                named = set(raw)
                have = [i for i in pref.items if i in named]
                satisfaction = len(have) / len(pref.items)
                # An item the text doesn't name is unknown, not missing --
                # unless it says the apartment is unfurnished.
                best_satisfaction[pref.name] = satisfaction if "says_unfurnished" in named else 1.0
                status = "met" if satisfaction == 1.0 else "not met" if satisfaction == 0.0 else "partly met"
                detail = _items_detail(named, have, pref.items)
            else:
                detail = "not stated" if not known else f"unexpected value {raw!r}"
                if not known:
                    detail = _unclear_detail(listing, pref.field) or detail
                else:
                    checks.append(f"{pref.label}: {detail}")
                    note("check", pref, "unexpected")
        elif pref.kind == "yes_no":
            if known and isinstance(raw, bool):
                satisfaction = 1.0 if raw == pref.wants else 0.0
                status = "met" if satisfaction == 1.0 else "not met"
                detail = "yes" if raw else "no"
                if pref.wants is False:
                    # The label names what the user wants ("Whole apartment
                    # (not a room share)"), the signal the opposite
                    # (roommate_listing). A bare "no" read as "not a whole
                    # apartment" in the first live run (Oct 20), so answer
                    # the label and show the signal's own value beside it.
                    signal = pref.field.removeprefix("signal:").replace("_", " ")
                    detail = f"{'no' if raw else 'yes'} ({signal}: {detail})"
            else:
                # A confirmed value of the wrong type ("yes", 1) is reported
                # as such, not as "not stated", so it can be fixed upstream.
                detail = "not stated" if not known else f"unexpected value {raw!r}"
                if not known:
                    detail = _unclear_detail(listing, pref.field) or detail
            ai_only = _ai_only(listing, pref.field)
            companion = _COMPANIONS.get(pref.field.removeprefix("signal:"))
            if companion and status == "met" and raw is True and _signal_state(listing, companion[0]) is True:
                name, tag, why = companion
                detail += f" ({tag})"
                checks.append(f"{pref.label}: yes, {tag} ({listing.signals[name].evidence}); {why}")
                note("check", pref, "companion", companion=name)
            if pref.dealbreaker and status == "met" and ai_only:
                checks.append(f"{pref.label}: {detail}, read only by the AI ({ai_only}); verify before relying on it")
                note("check", pref, "verify", raw)
            if pref.dealbreaker and status == "not met" and ai_only:
                checks.append(f"{pref.label}: {detail}, read only by the AI ({ai_only}); verify before ruling it out")
                note("check", pref, "verify", raw)
            elif pref.dealbreaker and status == "not met":
                excluded_reasons.append(f"{pref.label}: {detail}")
                note("exclude", pref, "no", raw)
            elif status == "unknown" and (pref.dealbreaker or known):
                # Unstated on a dealbreaker, or a corrupt value on anything:
                # both need a human.
                checks.append(f"{pref.label}: {detail}")
                note("check", pref, "unexpected" if known else "unclear" if detail != "not stated" else "unstated")
        else:
            lower = _lower_is_better(pref)
            value = _number(raw) if known else None
            applying, unknown_overrides = _override_states(pref, listing)
            ideal, limit = _combine(pref, applying)  # what holds given what's known
            best_ideal, best_limit = _combine(pref, applying + unknown_overrides)  # if all unknowns hold
            below = _AT_MOST.get(pref.field.removeprefix("signal:"))
            if value is None and below and not known and not lower and _signal_state(listing, below[0]) is True \
                    and pref.dealbreaker and limit > below[1]:
                # v1.53: Yad2's form says no space comes with the flat ("חניות: ללא"), the text says nothing:
                # it can't be the building's or the flat's own, whatever the street offers
                detail = below[2]
                excluded_reasons.append(f"{pref.label}: {detail}")
                note("exclude", pref, "no", None, limit=limit)
            elif value is None:
                detail = "not stated" if not known else f"unexpected value {raw!r}"
                if not known:
                    detail = _unclear_detail(listing, pref.field) or detail
                if pref.dealbreaker or known:
                    # Unstated on a dealbreaker, or a corrupt value on anything:
                    # both need a human.
                    checks.append(f"{pref.label}: {detail}")
                    note("check", pref, "unexpected" if known else "unclear" if detail != "not stated" else "unstated")
            else:
                satisfaction = _satisfaction(pref, value, ideal, limit)
                best = _satisfaction(pref, value, best_ideal, best_limit)
                best_satisfaction[pref.name] = best
                status = "met" if satisfaction == 1.0 else "not met" if satisfaction == 0.0 else "partly met"
                detail = f"{value:g} (" + (f"ideal {ideal:g}, " if ideal is not None else "") + f"limit {limit:g})"
                if best != satisfaction:
                    names = ", ".join(o.when_signal for o in unknown_overrides)
                    detail += f"; up to {best:.2f} if {names} is confirmed"
                if pref.dealbreaker and _within(value, limit, lower) and (ai_only := _ai_only(listing, pref.field)):
                    checks.append(f"{pref.label}: {detail}, read only by the AI ({ai_only}); verify before relying on it")
                    note("check", pref, "verify", value)
                if not _within(value, limit, lower):
                    outcome, message, info = _past_limit_outcome(pref, value, applying, unknown_overrides)
                    ai_only = _ai_only(listing, pref.field)
                    floor_only = _AT_LEAST.get(pref.field.removeprefix("signal:"))
                    if outcome == "exclude" and not lower and floor_only and _signal_state(listing, floor_only[0]) is True:
                        # v1.53: the value is only a lower bound (Yad2's parking box: "there's parking", not
                        # whose); the real one may meet the limit, so it's a question, never a reason to hide
                        outcome, message = "check", f"{pref.label}: {floor_only[1]}"
                        info = dict(info, reason="unclear")
                    if outcome == "exclude" and ai_only:
                        outcome, message = "check", f"{message}, read only by the AI ({ai_only}); verify before ruling it out"
                        info = dict(info, reason="verify")
                    {"exclude": excluded_reasons, "check": checks, "flag": flags}[outcome].append(message)
                    note(outcome, pref, info["reason"], value, limit=info["limit"], needs=info["needs"])

        results.append(
            PreferenceResult(
                name=pref.name,
                label=pref.label,
                relevance=pref.relevance,
                dealbreaker=pref.dealbreaker,
                weight=weight,
                satisfaction=satisfaction,
                status=status,
                detail=detail,
            )
        )

    checks.extend(c for c in _corrupt_conditions(prefs, listing) if c not in checks)

    low = high = expected = None
    unknown_labels: list[str] = []
    from . import priors as _priors  # the measured odds (rental_matcher/priors.json)

    odds = _priors.default() if priors is None else priors
    outlook: dict[str, Any] = _outlook(listing, prefs, results, odds, _priors.sample_sizes() if priors is None else {})
    if not weighted:  # only must-haves that count 0: no match number, but still the chance one fails (v1.28)
        outlook = {k: outlook[k] for k in ("fail_risk", "fail_risk_from", "fail_risk_parts")}
    if weighted:
        low = high = 0.0
        for pref, result in zip(prefs.preferences, results):
            if result.weight is None:
                continue
            if result.satisfaction is None:
                unknown_labels.append(pref.label)
                high += result.weight
            else:
                best = best_satisfaction.get(pref.name, result.satisfaction)
                low += result.weight * result.satisfaction
                high += result.weight * best
        low, high = (round(100 * x, 1) for x in (low, high))
        expected = outlook["expected"]

    return ScoredListing(
        listing_id=listing.id,
        excluded=bool(excluded_reasons),
        exclusion_reasons=excluded_reasons,
        checks=checks,
        flags=flags,
        match_low=low,
        match_high=high,
        match_expected=expected,
        unknown=unknown_labels,
        results=results,
        match_likely_low=outlook.get("likely_low"),
        match_likely_high=outlook.get("likely_high"),
        fail_risk=outlook.get("fail_risk"),
        fail_risk_from=outlook.get("fail_risk_from", []),
        fail_risk_parts=outlook.get("fail_risk_parts", []),
        notes=notes,
        unknowns=outlook.get("unknowns", []),
        sat={k: round(v, 4) for k, v in outlook.get("sat", {}).items()},
    )


def rank(listings: list[Listing], prefs: PreferenceSet, priors: Optional[Priors] = None) -> list[ScoredListing]:
    """Shown listings first, best first: the expected match times the
    chance every must-have holds (ties: higher low end first, then id for a
    stable order); hidden listings last."""
    scored = [score_listing(listing, prefs, priors) for listing in listings]
    return sorted(
        scored,
        key=lambda s: (
            s.excluded,
            -(s.rank_value if s.match_expected is not None else -1),
            -(s.match_low if s.match_low is not None else -1),
            s.listing_id,
        ),
    )
