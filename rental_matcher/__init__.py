"""rental_matcher: the canonical listing schema, scoring engine and Phase 2
extraction. The schema names below load on first use (PEP 562), so the
standard-library-only parts -- the Phase 2 extraction runner and scorer --
run on a Python without Pydantic installed."""

from __future__ import annotations

from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "Area",
    "Availability",
    "AvailabilityMode",
    "Contact",
    "ExtractedBy",
    "ListedBy",
    "Link",
    "Listing",
    "ListingStatus",
    "Price",
    "RecurringCosts",
    "Signal",
    "SignalStatus",
    "Source",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import schema

        return getattr(schema, name)
    raise AttributeError(f"module 'rental_matcher' has no attribute {name!r}")
