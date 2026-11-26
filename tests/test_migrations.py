"""
Tests for rental_matcher.migrations -- the schema-version migration chain
(v1.0 -> v1.1 -> v1.2 -> v1.3 -> v1.4 -> v1.5), which exists specifically
to prove the Master Plan's claim that a breaking/additive schema change
can be a migration function rather than a rewrite.
"""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from rental_matcher.migrations import (
    _MIGRATIONS,
    LATEST_VERSION,
    migrate_to_latest,
    migrate_v1_0_to_v1_1,
    migrate_v1_1_to_v1_2,
    migrate_v1_2_to_v1_3,
    migrate_v1_3_to_v1_4,
    migrate_v1_4_to_v1_5,
    migrate_v1_5_to_v1_6,
)
from rental_matcher.schema import Listing

# A hand-built v1.0-shaped record -- exactly the shape produced before the
# first external review prompted v1.1 (no apartment_id, total_floors,
# listed_by, contact, recurring_costs, availability; neighborhood always
# present).
V1_0_RECORD = {
    "schema_version": "1.0",
    "id": "yad2:abc123",
    "source": "yad2",
    "source_listing_id": "abc123",
    "area": {"city": "Tel Aviv", "neighborhood": "City Center", "lat": None, "lng": None},
    "price": {"amount": 4500.0, "currency": "ILS"},
    "rooms": 2.0,
    "floor": 2,
    "size_m2": 55.0,
    "posted_at": "2026-09-01",
    "pulled_at": "2026-09-01T10:00:00Z",
    "pull_round": None,
    "raw_excerpt": None,
    "links": [],
    "signals": {"balcony": {"status": "confirmed", "value": True, "evidence": None, "extracted_by": "manual", "checked_at": None}},
    "notes": ["a v1.0-era note"],
    "match_score": None,
    "status": "candidate",
}


class TestMigrateV1_0ToV1_1(unittest.TestCase):
    def test_rejects_wrong_source_version(self):
        with self.assertRaises(ValueError):
            migrate_v1_0_to_v1_1({**V1_0_RECORD, "schema_version": "0.9"})

    def test_bumps_schema_version(self):
        upgraded = migrate_v1_0_to_v1_1(V1_0_RECORD)
        self.assertEqual(upgraded["schema_version"], "1.1")

    def test_fills_new_fields_with_none_not_guesses(self):
        upgraded = migrate_v1_0_to_v1_1(V1_0_RECORD)
        self.assertIsNone(upgraded["apartment_id"])
        self.assertIsNone(upgraded["total_floors"])
        self.assertIsNone(upgraded["listed_by"])
        self.assertIsNone(upgraded["contact"])
        self.assertIsNone(upgraded["recurring_costs"])
        self.assertIsNone(upgraded["availability"])
        self.assertIsNone(upgraded["area"]["street"])
        self.assertIsNone(upgraded["area"]["house_number"])

    def test_preserves_every_v1_0_field(self):
        upgraded = migrate_v1_0_to_v1_1(V1_0_RECORD)
        self.assertEqual(upgraded["id"], V1_0_RECORD["id"])
        self.assertEqual(upgraded["price"], V1_0_RECORD["price"])
        self.assertEqual(upgraded["notes"], V1_0_RECORD["notes"])
        self.assertEqual(upgraded["area"]["neighborhood"], "City Center")

    def test_upgraded_record_is_internally_consistent_at_v1_1(self):
        """A one-step upgrade's result should describe itself as v1.1,
        even though the installed Listing model has since moved to v1.2
        -- model_validate is only exercised with the FULL chain below,
        since a lone v1.1 record won't satisfy v1.2-only validators like
        Availability's on_date invariant unless they were already true."""
        upgraded = migrate_v1_0_to_v1_1(V1_0_RECORD)
        self.assertEqual(upgraded["schema_version"], "1.1")
        self.assertEqual(upgraded["area"]["neighborhood"], "City Center")


class TestMigrateV1_1ToV1_2(unittest.TestCase):
    V1_1_RECORD = {**migrate_v1_0_to_v1_1(V1_0_RECORD)}

    def test_rejects_wrong_source_version(self):
        with self.assertRaises(ValueError):
            migrate_v1_1_to_v1_2({**self.V1_1_RECORD, "schema_version": "1.0"})

    def test_bumps_schema_version_only(self):
        upgraded = migrate_v1_1_to_v1_2(self.V1_1_RECORD)
        self.assertEqual(upgraded["schema_version"], "1.2")
        # no fields added or removed -- v1.2 only tightens validation
        without_version = {k: v for k, v in self.V1_1_RECORD.items() if k != "schema_version"}
        upgraded_without_version = {k: v for k, v in upgraded.items() if k != "schema_version"}
        self.assertEqual(without_version, upgraded_without_version)


class TestMigrateV1_2ToV1_3(unittest.TestCase):
    V1_2_RECORD = {**migrate_v1_1_to_v1_2(migrate_v1_0_to_v1_1(V1_0_RECORD))}

    def test_rejects_wrong_source_version(self):
        with self.assertRaises(ValueError):
            migrate_v1_2_to_v1_3({**self.V1_2_RECORD, "schema_version": "1.1"})

    def test_bumps_schema_version_only(self):
        upgraded = migrate_v1_2_to_v1_3(self.V1_2_RECORD)
        self.assertEqual(upgraded["schema_version"], "1.3")
        # no fields added or removed -- v1.3 only tightens validation
        # (and one field's type: Link.url) -- never reshapes a record
        without_version = {k: v for k, v in self.V1_2_RECORD.items() if k != "schema_version"}
        upgraded_without_version = {k: v for k, v in upgraded.items() if k != "schema_version"}
        self.assertEqual(without_version, upgraded_without_version)


class TestMigrateV1_3ToV1_4(unittest.TestCase):
    V1_3_RECORD = {
        **migrate_v1_2_to_v1_3(migrate_v1_1_to_v1_2(migrate_v1_0_to_v1_1(V1_0_RECORD)))
    }

    def test_rejects_wrong_source_version(self):
        with self.assertRaises(ValueError):
            migrate_v1_3_to_v1_4({**self.V1_3_RECORD, "schema_version": "1.2"})

    def test_bumps_schema_version_only(self):
        upgraded = migrate_v1_3_to_v1_4(self.V1_3_RECORD)
        self.assertEqual(upgraded["schema_version"], "1.4")
        # no fields added or removed -- v1.4 only tightens validation
        # (Area's text fields, Price.currency) -- never reshapes a record
        without_version = {k: v for k, v in self.V1_3_RECORD.items() if k != "schema_version"}
        upgraded_without_version = {k: v for k, v in upgraded.items() if k != "schema_version"}
        self.assertEqual(without_version, upgraded_without_version)


class TestMigrateV1_4ToV1_5(unittest.TestCase):
    V1_4_RECORD = {
        **migrate_v1_3_to_v1_4(
            migrate_v1_2_to_v1_3(migrate_v1_1_to_v1_2(migrate_v1_0_to_v1_1(V1_0_RECORD)))
        )
    }

    def test_rejects_wrong_source_version(self):
        with self.assertRaises(ValueError):
            migrate_v1_4_to_v1_5({**self.V1_4_RECORD, "schema_version": "1.3"})

    def test_bumps_schema_version_only(self):
        upgraded = migrate_v1_4_to_v1_5(self.V1_4_RECORD)
        self.assertEqual(upgraded["schema_version"], "1.5")
        # no fields added or removed -- v1.5 only tightens/coerces
        # existing optional text fields (see this module's docstring for
        # why that doesn't need active value-level coercion here) --
        # never reshapes a record
        without_version = {k: v for k, v in self.V1_4_RECORD.items() if k != "schema_version"}
        upgraded_without_version = {k: v for k, v in upgraded.items() if k != "schema_version"}
        self.assertEqual(without_version, upgraded_without_version)

    def test_a_v1_4_record_with_blank_optional_text_fields_still_validates(self):
        """The specific concern a fifth external review raised about this
        step: unlike v1.3 -> v1.4 (which started REJECTING blank Area
        text fields), could a v1.4-valid record with some other blank
        optional field -- apartment_id, contact.name, pull_round, all
        still plain `Optional[str]` under v1.4 -- now fail validation
        under v1.5's `OptionalNonEmptyStr`? Checked directly: no, because
        that type COERCES blank to None rather than rejecting it."""
        record = dict(self.V1_4_RECORD)
        record["apartment_id"] = ""
        record["pull_round"] = "   "
        record["contact"] = {"name": "", "phone": None}
        upgraded = migrate_v1_4_to_v1_5(record)
        listing = Listing.model_validate(upgraded)
        self.assertIsNone(listing.apartment_id)
        self.assertIsNone(listing.pull_round)
        self.assertIsNone(listing.contact.name)


class TestFullChainAgainstCurrentModel(unittest.TestCase):
    def test_v1_0_record_migrates_all_the_way_to_a_valid_current_listing(self):
        """The actual proof: a record from the OLDEST schema version, run
        through the full chain, must satisfy the CURRENT Listing model
        with no further changes."""
        latest = migrate_to_latest(V1_0_RECORD)
        listing = Listing.model_validate(latest)
        self.assertEqual(listing.schema_version, LATEST_VERSION)
        self.assertEqual(listing.area.neighborhood, "City Center")
        # none of v1.2's new validators should break a record that was
        # already well-formed under v1.0/v1.1's looser rules
        self.assertIsNone(listing.availability)
        self.assertIsNone(listing.total_floors)

    def test_migrate_to_latest_is_idempotent_once_current(self):
        upgraded = migrate_to_latest(V1_0_RECORD)
        twice = migrate_to_latest(upgraded)
        self.assertEqual(upgraded, twice)

    def test_migrate_to_latest_with_no_path_raises(self):
        with self.assertRaises(ValueError):
            migrate_to_latest({**V1_0_RECORD, "schema_version": "0.1"})

    def test_migrate_to_latest_can_start_from_v1_1_too(self):
        v1_1_record = migrate_v1_0_to_v1_1(V1_0_RECORD)
        latest = migrate_to_latest(v1_1_record)
        self.assertEqual(latest["schema_version"], LATEST_VERSION)


HISTORY_DIR = Path(__file__).resolve().parent.parent / "schema" / "history"


def _validator(version: str) -> Draft202012Validator:
    schema = json.loads((HISTORY_DIR / f"listing.schema.v{version}.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _schema_errors(record: dict, version: str) -> list[str]:
    return [f"{list(e.path)}: {e.message}" for e in _validator(version).iter_errors(record)]


def _walk_chain(record: dict):
    """Yield (version, record) for the input and every step after it."""
    yield record["schema_version"], record
    while record["schema_version"] in _MIGRATIONS:
        record = _MIGRATIONS[record["schema_version"]][1](record)
        yield record["schema_version"], record


class TestEveryStepConformsToItsOwnJsonSchema(unittest.TestCase):
    """The sixth review's catch: a record stamped "1.x" must satisfy the 1.x
    JSON Schema as a plain document -- for a non-Python consumer there is
    no Pydantic to coerce "" into None afterward. Checked against frozen
    per-version schema snapshots (schema/history/), recovered from git
    for 1.0-1.5."""

    def test_clean_v1_0_record_conforms_at_every_version(self):
        for version, record in _walk_chain(V1_0_RECORD):
            with self.subTest(version=version):
                self.assertEqual(_schema_errors(record, version), [])

    def test_dirty_v1_3_record_is_normalized_by_the_step_that_tightened_it(self):
        dirty = migrate_v1_2_to_v1_3(migrate_v1_1_to_v1_2(migrate_v1_0_to_v1_1(V1_0_RECORD)))
        dirty["area"].update({"street": "", "house_number": "   "})
        dirty["price"]["currency"] = "ils"
        self.assertEqual(_schema_errors(dirty, "1.3"), [])  # legal at 1.3
        for version, record in _walk_chain(dirty):
            with self.subTest(version=version):
                self.assertEqual(_schema_errors(record, version), [])
        self.assertIsNone(record["area"]["street"])
        self.assertEqual(record["price"]["currency"], "ILS")

    def test_dirty_v1_4_record_is_normalized(self):
        dirty = copy.deepcopy(TestMigrateV1_4ToV1_5.V1_4_RECORD)
        dirty.update({"apartment_id": "", "pull_round": "   ", "contact": {"name": "", "phone": None}})
        self.assertEqual(_schema_errors(dirty, "1.4"), [])  # legal at 1.4
        for version, record in _walk_chain(dirty):
            with self.subTest(version=version):
                self.assertEqual(_schema_errors(record, version), [])

    def test_final_output_also_satisfies_the_model(self):
        for _, record in _walk_chain(V1_0_RECORD):
            pass
        Listing.model_validate(record)


class TestMigrationsNeverMutateTheirInput(unittest.TestCase):
    def test_no_step_mutates_nested_state(self):
        for version, (_, step) in _MIGRATIONS.items():
            record = next(r for v, r in _walk_chain(V1_0_RECORD) if v == version)
            record = copy.deepcopy(record)
            record["area"]["street"] = ""
            before = copy.deepcopy(record)
            upgraded = step(record)
            with self.subTest(step=step.__name__):
                self.assertEqual(record, before)
                self.assertIsNot(upgraded["area"], record["area"])
                self.assertIsNot(upgraded["signals"], record["signals"])

    def test_migrate_to_latest_does_not_mutate_its_input(self):
        before = copy.deepcopy(V1_0_RECORD)
        migrate_to_latest(V1_0_RECORD)
        self.assertEqual(V1_0_RECORD, before)


class TestMigrateV1_5ToV1_6(unittest.TestCase):
    V1_5_RECORD = {
        **migrate_v1_4_to_v1_5(TestMigrateV1_4ToV1_5.V1_4_RECORD),
    }

    def _with_signal(self, signal: dict) -> dict:
        record = copy.deepcopy(self.V1_5_RECORD)
        record["signals"] = {"balcony": signal}
        return record

    def test_rejects_wrong_source_version(self):
        with self.assertRaises(ValueError):
            migrate_v1_5_to_v1_6({**self.V1_5_RECORD, "schema_version": "1.4"})

    def test_contradicted_without_value_becomes_confirmed_false(self):
        record = self._with_signal({"status": "contradicted", "value": None, "evidence": "no balcony"})
        signal = migrate_v1_5_to_v1_6(record)["signals"]["balcony"]
        self.assertEqual((signal["status"], signal["value"]), ("confirmed", False))

    def test_contradicted_false_becomes_confirmed_false(self):
        record = self._with_signal({"status": "contradicted", "value": False})
        signal = migrate_v1_5_to_v1_6(record)["signals"]["balcony"]
        self.assertEqual((signal["status"], signal["value"]), ("confirmed", False))

    def test_contradicted_with_any_other_value_refuses_to_guess(self):
        with self.assertRaises(ValueError):
            migrate_v1_5_to_v1_6(self._with_signal({"status": "contradicted", "value": "3 dogs max"}))

    def test_blank_evidence_and_notes_are_normalized(self):
        record = self._with_signal({"status": "unknown", "value": None, "evidence": "  "})
        record["notes"] = ["kept", "", "  "]
        upgraded = migrate_v1_5_to_v1_6(record)
        self.assertIsNone(upgraded["signals"]["balcony"]["evidence"])
        self.assertEqual(upgraded["notes"], ["kept"])
        self.assertEqual(_schema_errors(upgraded, "1.6"), [])

    def test_ambiguous_signals_raise_instead_of_emitting_an_invalid_record(self):
        for signal in [
            {"status": "unknown", "value": True},
            {"status": "unconfirmed", "value": "x"},
            {"status": "confirmed", "value": None},
            {"status": "confirmed"},
        ]:
            with self.subTest(signal=signal):
                with self.assertRaises(ValueError):
                    migrate_v1_5_to_v1_6(self._with_signal(signal))

    def test_blank_link_label_raises(self):
        record = copy.deepcopy(self.V1_5_RECORD)
        record["links"] = [{"label": "  ", "url": "https://www.yad2.co.il/item/abc"}]
        with self.assertRaises(ValueError):
            migrate_v1_5_to_v1_6(record)


# Values the steps touch, including every one some version's model
# accepted but its JSON Schema didn't.
_TEXT_VALUES = ["", "   ", "City Center", None]
_CURRENCIES = ["ILS", "ils", " usd ", "Eur"]
_SIGNALS = [
    {"status": s, "value": v, "evidence": e}
    for s in ["confirmed", "unconfirmed", "contradicted", "conflicting", "unknown"]
    for v in [None, True, False, "x"]
    for e in [None, "", "  ", "quote"]
]


def _statuses_at(version: str) -> list[str]:
    schema = json.loads((HISTORY_DIR / f"listing.schema.v{version}.json").read_text(encoding="utf-8"))
    return schema["$defs"]["SignalStatus"]["enum"]


def _mutated(base: dict, rng) -> dict:
    """Only produces inputs legal at the base's own version: a status that
    version doesn't have yet would make the input invalid, and the
    property says nothing about invalid inputs."""
    record = copy.deepcopy(base)
    statuses = _statuses_at(base["schema_version"])
    for key in ("neighborhood", "street", "house_number"):
        record["area"][key] = rng.choice(_TEXT_VALUES)
    record["price"]["currency"] = rng.choice(_CURRENCIES)
    for key in ("apartment_id", "pull_round"):
        record[key] = rng.choice(_TEXT_VALUES)
    record["contact"] = rng.choice([None, {"name": rng.choice(_TEXT_VALUES), "phone": None}])
    record["notes"] = [rng.choice(["note", "", "  "]) for _ in range(rng.randint(0, 3))]
    legal_signals = [sig for sig in _SIGNALS if sig["status"] in statuses]
    record["signals"] = {f"s{i}": dict(rng.choice(legal_signals)) for i in range(rng.randint(0, 3))}
    record["links"] = [
        {"label": rng.choice(["Yad2", "", " "]), "url": "https://www.yad2.co.il/item/abc"}
        for _ in range(rng.randint(0, 2))
    ]
    return record


class TestNoStepEverEmitsAnInvalidRecord(unittest.TestCase):
    """Property, over randomly mutated inputs from EVERY source version:
    each step either raises ValueError or returns a record valid at its
    target version (frozen JSON Schema), and the final output also
    satisfies the model. v1.7's first version of this test only started
    from 1.3; an independent review then showed 1.1->1.2 through 1.3->1.4
    still emitting records their own target schema rejects."""

    def _bases(self):
        return {v: r for v, r in _walk_chain(V1_0_RECORD) if v != LATEST_VERSION}

    def _mutate_older_fields(self, record: dict, rng) -> None:
        record["area"]["city"] = rng.choice(["Tel Aviv", "Tel Aviv", "", "  "])
        record["id"] = rng.choice(["yad2:abc123", "yad2:abc123", ""])
        record["floor"], record["total_floors"] = rng.choice([(2, None), (2, 5), (5, 3), (-1, 3)])
        record["area"]["lat"] = rng.choice([None, 32.06, 200.0])
        record["match_score"] = rng.choice([None, 55, 4000])
        record["availability"] = rng.choice([
            None, {"mode": "immediate", "on_date": None}, {"mode": "date", "on_date": "2026-12-01"},
            {"mode": "date", "on_date": None}, {"mode": "immediate", "on_date": "2026-12-01"},
        ])
        record["contact"] = rng.choice([None, {"name": "x", "phone": rng.choice(
            ["054-1234567", "+972-054-1234567", "+054-123-4567", "00972541234567", "054-123", None])}])
        # Before 1.4 the model took any exactly-3-character string, unstripped.
        legal = ["ILS", "ils", "usd", "AAA"] if record["schema_version"] in ("1.1", "1.2", "1.3") else _CURRENCIES
        record["price"]["currency"] = rng.choice(legal)

    def test_every_step_from_every_version(self):
        import random

        rng = random.Random(5)
        bases = self._bases()
        for _ in range(3_000):
            source = rng.choice(sorted(bases))
            record = copy.deepcopy(bases[source])
            if source not in ("1.0", "1.1", "1.2"):
                record = _mutated(record, rng)
            if source != "1.0":
                self._mutate_older_fields(record, rng)
            target, step = _MIGRATIONS[source]
            try:
                upgraded = step(record)
            except ValueError:
                continue
            self.assertEqual(_schema_errors(upgraded, target), [], (source, record))
            if target == LATEST_VERSION:
                Listing.model_validate(upgraded)

    def test_malformed_shapes_raise_value_error_or_nothing_else(self):
        """Steps must fail with ValueError, never TypeError/AttributeError,
        when a field has an unexpected shape."""
        import random

        rng = random.Random(6)
        bases = self._bases()
        junk = [None, [], {}, "x", 0, 3.5, ["a"], {"k": "v"}]
        keys = ["area", "price", "contact", "signals", "notes", "links", "availability", "floor", "total_floors", "match_score", "id"]
        for _ in range(2_000):
            source = rng.choice(sorted(bases))
            record = copy.deepcopy(bases[source])
            for key in rng.sample(keys, rng.randint(1, 3)):
                record[key] = copy.deepcopy(rng.choice(junk))
            try:
                _MIGRATIONS[source][1](record)
            except ValueError:
                pass

    def test_constraints_no_rule_covers_still_raise(self):
        """Second independent review: rooms/size/price > 0 (1.1), a non-blank
        link URL (1.3) and raw_excerpt length (1.5) had no rule. Every step
        now checks its output against the target schema, so an uncovered
        constraint raises instead of passing through."""
        with self.assertRaises(ValueError):
            migrate_v1_0_to_v1_1({**V1_0_RECORD, "rooms": 0})
        v1_2 = migrate_to_latest(V1_0_RECORD, target_version="1.2")
        with self.assertRaises(ValueError):
            migrate_v1_2_to_v1_3({**v1_2, "links": [{"label": "yad2", "url": ""}]})
        v1_4 = migrate_to_latest(V1_0_RECORD, target_version="1.4")
        upgraded = migrate_v1_4_to_v1_5({**v1_4, "raw_excerpt": "x" * 700})
        self.assertLessEqual(len(upgraded["raw_excerpt"]), 600)  # fixable, so fixed

    def test_formats_are_checked_and_output_is_the_models_canonical_form(self):
        """Eighth review: jsonschema skips 'date-time'/'uri' unless optional
        packages are installed (only 'date' is checked in this environment),
        so malformed timestamps and URLs used to migrate cleanly."""
        latest = migrate_to_latest({**V1_0_RECORD, "area": {**V1_0_RECORD["area"], "city": "  Tel Aviv  "}})
        self.assertEqual(latest["area"]["city"], "Tel Aviv")  # stripped, like the model
        self.assertEqual(latest, Listing.model_validate(latest).model_dump(mode="json"))
        previous = {**copy.deepcopy(latest), "schema_version": "1.7"}
        for bad in (
            {"pulled_at": "not-a-date"},
            {"pulled_at": "2026-10-17T10:00:00"},  # naive: no offset
            {"posted_at": "2026-13-45"},
            {"links": [{"label": "Yad2", "url": "not a url"}]},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _MIGRATIONS["1.7"][1]({**copy.deepcopy(previous), **bad})

    def test_last_step_refuses_rather_than_drops_unknown_keys(self):
        latest = migrate_to_latest(V1_0_RECORD)
        previous = {**copy.deepcopy(latest), "schema_version": "1.7", "extra": "keep me"}
        with self.assertRaises(ValueError):
            _MIGRATIONS["1.7"][1](previous)

    def test_seventh_review_chain_cases(self):
        v1_1 = migrate_v1_0_to_v1_1(V1_0_RECORD)
        with self.assertRaises(ValueError):
            migrate_v1_1_to_v1_2({**v1_1, "id": ""})
        with self.assertRaises(ValueError):
            migrate_v1_1_to_v1_2({**v1_1, "floor": 5, "total_floors": 3})
        upgraded = migrate_to_latest({**v1_1, "contact": {"name": "x", "phone": "054-1234567"}})
        self.assertEqual(upgraded["contact"]["phone"], "+972541234567")
        v1_5 = migrate_to_latest(V1_0_RECORD, target_version="1.5")
        with self.assertRaises(ValueError):  # 0 == False, but 0 isn't a boolean "no"
            migrate_v1_5_to_v1_6({**v1_5, "signals": {"s": {"status": "contradicted", "value": 0}}})

    def test_already_at_target_is_validated_not_returned_unchecked(self):
        # A record already stamped at the target must still be validated, not
        # passed straight through. A clean latest record round-trips; a
        # corrupt one raises.
        latest = migrate_to_latest(V1_0_RECORD)
        self.assertEqual(migrate_to_latest(copy.deepcopy(latest)), latest)
        with self.assertRaises(ValueError):
            migrate_to_latest({**copy.deepcopy(latest), "id": ""})

    def test_boolean_floor_is_rejected_cleanly_not_compared_as_int(self):
        # bool is a subclass of int; a boolean floor must not be compared as
        # 1/0 and give a misleading "floor True is above total_floors" error.
        v1_1 = migrate_v1_0_to_v1_1(V1_0_RECORD)
        with self.assertRaises(ValueError) as cm:
            migrate_v1_1_to_v1_2({**v1_1, "floor": True, "total_floors": 0})
        # It's rejected as the wrong type, not with a nonsense comparison
        # ("floor True is above total_floors 0") from treating bool as int.
        self.assertNotIn("is above total_floors", str(cm.exception))

    def test_nan_and_inf_are_refused_at_every_version(self):
        # Review 11: NaN/inf passed the frozen schemas at intermediate
        # targets (every NaN comparison is false), so the output wasn't JSON.
        for key, value, target in (("rooms", float("nan"), "1.5"), ("size_m2", float("inf"), "1.3"),
                                   ("rooms", float("-inf"), "1.1"), ("price", {"amount": float("nan"), "currency": "ILS"}, "1.8")):
            with self.subTest(key=key, value=value, target=target), self.assertRaises(ValueError):
                migrate_to_latest({**copy.deepcopy(V1_0_RECORD), key: value}, target_version=target)

    def test_only_valueerror_escapes_for_bad_data(self):
        # Review 11: mixed key types crashed the error sort (TypeError), and
        # deep nesting crashed deepcopy (RecursionError).
        with self.assertRaises(ValueError):
            migrate_to_latest({**copy.deepcopy(V1_0_RECORD), "signals": {1: {"status": "x"}, "b": {"status": "y"}}})
        deep: list = []
        cur = deep
        for _ in range(3000):
            nxt: list = []
            cur.append(nxt)
            cur = nxt
        with self.assertRaises(ValueError):
            migrate_to_latest({**copy.deepcopy(V1_0_RECORD), "signals": {"s": {"status": "confirmed", "value": deep}}})

    def test_non_dict_and_backward_target_raise_valueerror(self):
        for bad in (None, [], 5, "x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    migrate_to_latest(bad)
        with self.assertRaises(ValueError):  # forward-only
            migrate_to_latest(migrate_to_latest(V1_0_RECORD, target_version="1.5"), target_version="1.2")
        with self.assertRaises(ValueError):
            migrate_to_latest(V1_0_RECORD, target_version="9.9")

if __name__ == "__main__":
    unittest.main()
