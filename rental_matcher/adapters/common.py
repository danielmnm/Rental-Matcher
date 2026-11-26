"""
v1.62 (Phase 3): rules that must mean the same on every site, in one place.

Komo batch 1 found the cost of keeping them per adapter: Yad2's adapter learned in v1.53 that a parking space the
site's form mentions is only a floor ("there's parking; whose isn't said"), which scoring turns into a check instead
of a reason to hide. Komo's and Madlan's adapters each had their own copy of the parking rule and never got it, so
59 of 234 Komo listings would have vanished for a user who needs their own space. Each adapter now calls these, and
tests/test_v162.py checks that every adapter agrees.
"""

from __future__ import annotations

from typing import Optional

from ..schema import ExtractedBy, Signal, SignalStatus

# Owner ruling (Nov 5, Nov 8): a building this tall has an elevator (the text rule's threshold, rules.ELEVATOR_FLOOR_THRESHOLD)
ELEVATOR_FLOORS = 6
# A fact the adapter works out rather than reads off the site's form. The card shows it; the card test must not treat
# it as the form's word, or the answer key would accept the reader's own inference (card_eval.box_facts skips these).
INFERRED = "(inferred)"


def _confirmed(value, evidence: str) -> Signal:
    return Signal(status=SignalStatus.CONFIRMED, value=value, evidence=evidence, extracted_by=ExtractedBy.RULE)


def parking_from_form(site: str, spaces: Optional[int], ticked: bool = False) -> dict[str, Signal]:
    """A site's form says there's parking (a ticked box or a count): the building's at least, maybe the flat's own.
    The level is the lower bound (2: shared) and `parking_at_least` says it's only a floor."""
    if not ticked and not (isinstance(spaces, int) and not isinstance(spaces, bool) and spaces > 0):
        return {}
    said = f"{spaces} parking" if isinstance(spaces, int) and spaces > 0 else "parking included"
    return {
        "parking_level": _confirmed(2.0, f"{site}: {said} (deeded or shared not stated; read as shared)"),
        "parking_at_least": _confirmed(True, f"{site}: there's parking; whose isn't said"),
    }


def elevator_from_height(site: str, floors_in_building: Optional[int]) -> dict[str, Signal]:
    """A building of ELEVATOR_FLOORS or more floors has an elevator (the owner's ruling, applied to a site's own
    "floors in the building" field the way the text rule applies it to "קומה 2 מתוך 8")."""
    if isinstance(floors_in_building, int) and not isinstance(floors_in_building, bool) and ELEVATOR_FLOORS <= floors_in_building <= 60:
        return {"elevator": _confirmed(True, f"{site}: {floors_in_building} floors in the building, too tall to lack an elevator {INFERRED}")}
    return {}


# v1.64 (Komo batch 2): 85 of 289 Komo listings give their floor as the building's number of floors ("14 מתוך 14").
# On the real twins the labelers found, Yad2 gave the same floor in 53 of 67 such cases and a different one in 14 (21%),
# against 0 of 118 when Komo's floor was below the top. So a floor equal to the building's height (3 floors or more) is
# unknown: a check on the card ("floor 14? check"), never a reason to hide, and not a fact to join two listings by.
FLOOR_IS_HEIGHT_MIN = 3


def floor_from_form(floor: Optional[int], floors_in_building: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    """(the floor to use, the floor the form said when it isn't used)."""
    if (isinstance(floor, int) and isinstance(floors_in_building, int) and floors_in_building >= FLOOR_IS_HEIGHT_MIN
            and floor == floors_in_building):
        return None, floor
    return floor, None
