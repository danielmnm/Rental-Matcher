"""
Schema migrations, chained by version.

Contract for every step: it takes a record that the version-N Pydantic
model accepted (looser than the version-N JSON Schema: the model strips
and coerces) and EITHER returns a NEW dict (deep copy; the input is never
mutated) that is valid at version N+1 as a plain JSON document, against
that version's frozen schema in schema/history/, OR raises ValueError
naming what it couldn't fix. It never returns an invalid record stamped
with the new version. tests/test_migrations.py checks this as a property
over randomly mutated records, from every source version.

Guaranteed, not just intended: after applying its rules, each step
validates its own output against the target version's frozen schema --
with format checking for 'date', 'date-time' and 'uri' done by this
module's own checkers, since jsonschema's built-in ones silently skip
'date-time' and 'uri' unless optional packages are installed -- and
raises ValueError if anything still fails. The step that reaches the
LATEST version also runs the record through the current Listing model and
returns the model's own JSON form, so the stored record is exactly what
the model would produce (whitespace stripped, values normalized). A rule nobody wrote yet can
therefore only ever cause a loud ValueError, never a silently invalid
record. (An independent review found three constraints -- rooms/size/price
> 0 from 1.1, a non-blank link URL from 1.3, raw_excerpt <= 600 chars from
1.5 -- that no rule covered; this check catches that whole class.)

How: every rule lives in ONE table (_RULES), tagged with the version that
introduced it, and every step applies every rule up to its target
version. Earlier versions of this module applied each rule inside the
step that introduced it, and later steps kept forgetting some (three
external-review findings and one of the author's own were exactly that).
Each rule either FIXES a value when the fix is unambiguous (blank
optional text -> None, currency -> uppercase, phone -> E.164) or RAISES
when it isn't (a blank city, floor above total floors, a signal whose
value contradicts its status). Fixes are idempotent, so applying them
again at every later step is harmless.

Version history (reasoning per round in README.md):
  1.0 -> 1.1  Additive optional fields, filled with None.
  1.1 -> 1.2  Required ids/city non-blank; floor <= total_floors;
              availability on_date iff mode == "date"; phone E.164.
  1.2 -> 1.3  lat/lng and match_score ranges; phone length checks.
  1.3 -> 1.4  Area text non-blank; currency a real ISO 4217 code.
  1.4 -> 1.5  apartment_id / pull_round / contact.name non-blank.
  1.5 -> 1.6  Signal: CONTRADICTED removed, value iff CONFIRMED; blank
              evidence and notes removed; Link.label non-blank.
  1.6 -> 1.7  JSON Schema now states the Signal rule and the "\\S"
              pattern on required text, which 1.6's model already enforced.
  1.7 -> 1.8  JSON Schema: pulled_at must carry a timezone offset (the
              model always required one).
  1.8 -> 1.9  RecurringCosts gains optional arnona_monthly_max and
              vaad_bayit_monthly_max: a range when the ad and Yad2's field
              disagree on a fee (v1.59). Older records stay valid as they are.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import TypeGuard

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import AnyUrl, TypeAdapter, ValidationError

from .schema import (
    _ISO_4217_CURRENCY_CODES,
    _RAW_EXCERPT_MAX,
    _RAW_EXCERPT_TRUNCATION_MARKER,
    Listing,
    normalize_phone,
)

_SCHEMA_HISTORY = Path(__file__).resolve().parent.parent / "schema" / "history"

V1_0 = "1.0"
V1_1 = "1.1"
V1_2 = "1.2"
V1_3 = "1.3"
V1_4 = "1.4"
V1_5 = "1.5"
V1_6 = "1.6"
V1_7 = "1.7"
V1_8 = "1.8"
V1_9 = "1.9"
LATEST_VERSION = V1_9

_ORDER = [V1_0, V1_1, V1_2, V1_3, V1_4, V1_5, V1_6, V1_7, V1_8, V1_9]


def _is_blank(value: object) -> bool:
    return isinstance(value, str) and value.strip() == ""


def _is_num(value: object) -> TypeGuard[float]:
    """A real number: not a bool. `isinstance(True, int)` is True in Python,
    so without this a boolean floor/lat would be compared as 1/0 and give a
    misleading error instead of letting schema validation reject the type.
    (TypeGuard[float] also lets the type checker narrow for the comparisons
    that follow; int is accepted by float there.)"""
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _blank_to_none(container: object, key: str) -> None:
    if isinstance(container, dict) and _is_blank(container.get(key)):
        container[key] = None


def _dict_at(record: dict, key: str) -> dict:
    value = record.get(key)
    return value if isinstance(value, dict) else {}


# --- rules: each takes the (already deep-copied) record and fixes or raises


def _require_nonblank_required_text(record: dict) -> None:
    for where, value in (
        ("id", record.get("id")),
        ("source_listing_id", record.get("source_listing_id")),
        ("area.city", _dict_at(record, "area").get("city")),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where} is required and can't be blank (got {value!r})")


def _require_floor_within_building(record: dict) -> None:
    floor, total = record.get("floor"), record.get("total_floors")
    if _is_num(floor) and _is_num(total) and floor > total:
        raise ValueError(f"floor {floor} is above total_floors {total}")


def _require_availability_invariant(record: dict) -> None:
    availability = record.get("availability")
    if not isinstance(availability, dict):
        return
    has_date = availability.get("on_date") is not None
    if (availability.get("mode") == "date") != has_date:
        raise ValueError(f"availability {availability!r}: on_date is required exactly when mode is 'date'")


def _normalize_phone(record: dict) -> None:
    contact = record.get("contact")
    if isinstance(contact, dict) and isinstance(contact.get("phone"), str):
        contact["phone"] = normalize_phone(contact["phone"])


def _require_ranges(record: dict) -> None:
    area = _dict_at(record, "area")
    for key, low, high in (("lat", -90, 90), ("lng", -180, 180)):
        value = area.get(key)
        if _is_num(value) and not low <= value <= high:
            raise ValueError(f"area.{key}={value} is outside [{low}, {high}]")
    score = record.get("match_score")
    if _is_num(score) and not 0 <= score <= 100:
        raise ValueError(f"match_score={score} is outside [0, 100]")


def _normalize_area_text(record: dict) -> None:
    area = record.get("area")
    for key in ("neighborhood", "street", "house_number"):
        _blank_to_none(area, key)


def _normalize_and_require_currency(record: dict) -> None:
    price = record.get("price")
    if not isinstance(price, dict) or not isinstance(price.get("currency"), str):
        return
    price["currency"] = price["currency"].strip().upper()
    if price["currency"] not in _ISO_4217_CURRENCY_CODES:
        raise ValueError(f"price.currency {price['currency']!r} is not an ISO 4217 code")


def _normalize_optional_ids_and_names(record: dict) -> None:
    _blank_to_none(record, "apartment_id")
    _blank_to_none(record, "pull_round")
    _blank_to_none(record.get("contact"), "name")


def _map_contradicted_signals(record: dict) -> None:
    """CONTRADICTED was never defined; v1.5's own tests used it two ways
    that both mean "the listing says no" (no value, or value=False), so
    both become CONFIRMED/False. Any other value can't be mapped. `is`,
    not `in (None, False)`: 0 == False in Python, and a value of 0 isn't
    a boolean "no"."""
    for name, signal in _dict_at(record, "signals").items():
        if isinstance(signal, dict) and signal.get("status") == "contradicted":
            value = signal.get("value")
            if not (value is None or value is False):
                raise ValueError(
                    f"signal {name!r} is 'contradicted' with value={value!r}; "
                    "only a boolean 'no' can be migrated automatically"
                )
            signal["status"], signal["value"] = "confirmed", False


def _normalize_notes_and_evidence(record: dict) -> None:
    notes = record.get("notes")
    if isinstance(notes, list):
        record["notes"] = [n for n in notes if not _is_blank(n)]
    for signal in _dict_at(record, "signals").values():
        _blank_to_none(signal, "evidence")


def _truncate_raw_excerpt(record: dict) -> None:
    """Same truncation the model applies (Listing._truncate_raw_excerpt)."""
    excerpt = record.get("raw_excerpt")
    if isinstance(excerpt, str) and len(excerpt) > _RAW_EXCERPT_MAX:
        keep = _RAW_EXCERPT_MAX - len(_RAW_EXCERPT_TRUNCATION_MARKER)
        record["raw_excerpt"] = excerpt[:keep] + _RAW_EXCERPT_TRUNCATION_MARKER


def _require_link_labels(record: dict) -> None:
    links = record.get("links")
    for link in links if isinstance(links, list) else []:
        if isinstance(link, dict) and _is_blank(link.get("label")):
            raise ValueError(f"link {link.get('url')!r} has a blank label")


def _require_value_iff_confirmed(record: dict) -> None:
    for name, signal in _dict_at(record, "signals").items():
        if not isinstance(signal, dict):
            continue
        status = signal.get("status", "unknown")
        has_value = signal.get("value") is not None
        if status == "confirmed" and not has_value:
            raise ValueError(f"signal {name!r} is 'confirmed' with no value; one is required")
        if status != "confirmed" and has_value:
            raise ValueError(
                f"signal {name!r} is {status!r} with value={signal['value']!r}; only a "
                "confirmed signal may carry a value, and which one is wrong can't be inferred"
            )


# (version that introduced the rule, rule). Order matters within a step:
# fixes run before the checks that depend on them.
_RULES: list[tuple[str, Callable[[dict], None]]] = [
    (V1_2, _require_nonblank_required_text),
    (V1_2, _require_floor_within_building),
    (V1_2, _require_availability_invariant),
    (V1_2, _normalize_phone),
    (V1_3, _require_ranges),
    (V1_4, _normalize_area_text),
    (V1_4, _normalize_and_require_currency),
    (V1_5, _normalize_optional_ids_and_names),
    (V1_5, _truncate_raw_excerpt),
    (V1_6, _map_contradicted_signals),
    (V1_6, _normalize_notes_and_evidence),
    (V1_6, _require_link_labels),
    (V1_6, _require_value_iff_confirmed),
]


def _apply_rules(record: dict, target: str) -> None:
    for since, rule in _RULES:
        if _ORDER.index(since) <= _ORDER.index(target):
            rule(record)


_FORMATS = FormatChecker(formats=())
_RFC3339_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})")
_URL = TypeAdapter(AnyUrl)


@_FORMATS.checks("date", raises=ValueError)
def _is_date(value: object) -> bool:
    return not isinstance(value, str) or (re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None and bool(date.fromisoformat(value)))


@_FORMATS.checks("date-time", raises=ValueError)
def _is_date_time(value: object) -> bool:
    # RFC 3339 requires an offset; the model's AwareDatetime does too.
    return not isinstance(value, str) or (
        _RFC3339_DATE_TIME.fullmatch(value) is not None and bool(datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00")))
    )


@_FORMATS.checks("uri", raises=ValidationError)
def _is_uri(value: object) -> bool:
    # Same grammar as the model (Pydantic AnyUrl), so they can't disagree.
    return not isinstance(value, str) or bool(_URL.validate_python(value))


@lru_cache(maxsize=None)
def _validator(version: str) -> Draft202012Validator:
    schema = json.loads((_SCHEMA_HISTORY / f"listing.schema.v{version}.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=_FORMATS)


def _require_valid_at(record: dict, version: str) -> None:
    # "Valid as a plain JSON document" first: NaN/inf aren't JSON, and they
    # slip past the schema (every comparison with NaN is false, so even
    # exclusiveMinimum passes). Before v1.12 only the final step's model
    # caught them.
    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ValueError(f"can't produce a valid v{version} record: not a JSON document ({e})") from e
    # str(): paths can mix int and str keys, which can't be compared.
    errors = sorted(_validator(version).iter_errors(record), key=lambda e: [str(p) for p in e.path])
    if errors:
        details = "; ".join(f"{'.'.join(map(str, e.path)) or '(record)'}: {e.message}" for e in errors[:5])
        raise ValueError(f"can't produce a valid v{version} record: {details}")


def _check_version(record: object, expected: str, step_name: str) -> None:
    if not isinstance(record, dict) or record.get("schema_version") != expected:
        got = record.get("schema_version") if isinstance(record, dict) else type(record).__name__
        raise ValueError(f"{step_name} expects a {expected!r} record, got {got!r}")


def _step(source: str, target: str, add_fields: Callable[[dict], None] | None = None) -> Callable[[dict], dict]:
    def migrate(record: dict) -> dict:
        _check_version(record, source, migrate.__name__)
        try:
            upgraded = copy.deepcopy(record)
            upgraded["schema_version"] = target
            if add_fields is not None:
                add_fields(upgraded)
            return _finalize(upgraded, target)
        except RecursionError as e:
            raise ValueError("record is nested too deeply to migrate") from e

    migrate.__name__ = f"migrate_v{source.replace('.', '_')}_to_v{target.replace('.', '_')}"
    return migrate


def _add_v1_1_fields(record: dict) -> None:
    area = record.get("area")
    if not isinstance(area, dict):
        area = record["area"] = {}
    area.setdefault("street", None)
    area.setdefault("house_number", None)
    for key in ("apartment_id", "total_floors", "listed_by", "contact", "recurring_costs", "availability"):
        record.setdefault(key, None)


migrate_v1_0_to_v1_1 = _step(V1_0, V1_1, _add_v1_1_fields)
migrate_v1_1_to_v1_2 = _step(V1_1, V1_2)
migrate_v1_2_to_v1_3 = _step(V1_2, V1_3)
migrate_v1_3_to_v1_4 = _step(V1_3, V1_4)
migrate_v1_4_to_v1_5 = _step(V1_4, V1_5)
migrate_v1_5_to_v1_6 = _step(V1_5, V1_6)
migrate_v1_6_to_v1_7 = _step(V1_6, V1_7)
migrate_v1_7_to_v1_8 = _step(V1_7, V1_8)
migrate_v1_8_to_v1_9 = _step(V1_8, V1_9)

# SOURCE version -> (next version, migration function).
_MIGRATIONS: dict[str, tuple[str, Callable[[dict], dict]]] = {
    V1_0: (V1_1, migrate_v1_0_to_v1_1),
    V1_1: (V1_2, migrate_v1_1_to_v1_2),
    V1_2: (V1_3, migrate_v1_2_to_v1_3),
    V1_3: (V1_4, migrate_v1_3_to_v1_4),
    V1_4: (V1_5, migrate_v1_4_to_v1_5),
    V1_5: (V1_6, migrate_v1_5_to_v1_6),
    V1_6: (V1_7, migrate_v1_6_to_v1_7),
    V1_7: (V1_8, migrate_v1_7_to_v1_8),
    V1_8: (V1_9, migrate_v1_8_to_v1_9),
}


def _finalize(record: dict, target: str) -> dict:
    """The validation a step runs after its rules: fix/raise via the rules,
    check against the frozen target schema, and at the latest version run
    the record through the model so the output is exactly the model's form.
    Shared so a record already at the target is validated too, not returned
    unchecked."""
    _apply_rules(record, target)
    _require_valid_at(record, target)
    if target == LATEST_VERSION:
        try:
            record = Listing.model_validate(record).model_dump(mode="json")
        except ValidationError as e:
            raise ValueError(f"can't produce a valid v{target} record: {e}") from e
        _require_valid_at(record, target)
    return record


def migrate_to_latest(record: dict, target_version: str = LATEST_VERSION) -> dict:
    """Apply whatever chain of steps gets `record` to `target_version`, and
    guarantee the result is valid there (or raise ValueError) -- including
    when `record` is already at the target: it is still validated, never
    returned unchecked. Never mutates `record`."""
    if not isinstance(record, dict):
        raise ValueError(f"record must be a dict, got {type(record).__name__}")
    if target_version not in _ORDER:
        raise ValueError(f"unknown target version {target_version!r}")
    try:
        current = copy.deepcopy(record)
    except RecursionError as e:
        raise ValueError("record is nested too deeply to migrate") from e
    current_version = current.get("schema_version")
    if current_version is None:
        raise ValueError("record has no 'schema_version' to migrate from")
    if current_version not in _ORDER:
        raise ValueError(f"unknown source version {current_version!r}")
    if _ORDER.index(current_version) > _ORDER.index(target_version):
        raise ValueError(
            f"no backward migration from {current_version!r} to {target_version!r}; "
            "migrations only run forward"
        )
    if current_version == target_version:
        try:
            return _finalize(current, target_version)
        except RecursionError as e:
            raise ValueError("record is nested too deeply to migrate") from e
    while current_version != target_version:
        step = _MIGRATIONS.get(current_version)
        if step is None:
            raise ValueError(f"no migration path from {current_version!r} toward {target_version!r}")
        next_version, migration = step
        current = migration(current)
        current_version = current.get("schema_version")
        if current_version != next_version:
            raise RuntimeError(f"{migration.__name__} produced {current_version!r}, expected {next_version!r}")
    return current
