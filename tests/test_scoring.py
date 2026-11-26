"""
Tests for rental_matcher.scoring (Phase 1).

Properties over randomly generated listings and preference sets, then the
Phase 1 exit criterion from the Master Plan: the engine reproduces the
manual accept/reject calls on the existing cards.
"""

import copy
import json
import random
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from rental_matcher.schema import Area, ExtractedBy, Listing, Price, Signal, SignalStatus, Source
from rental_matcher.scoring import PreferenceSet, rank, score_listing

ROOT = Path(__file__).resolve().parent.parent
FROZEN_PREFS = ROOT / "tests" / "fixtures" / "prefs_frozen.json"
FROZEN_OCT_13 = ROOT / "preferences" / "history" / "frozen-2026-10-13.json"

BOOL_SIGNALS = ["balcony", "parking", "mamad", "elevator"]


def _listing(rng: random.Random, i: int) -> Listing:
    signals = {}
    for name in BOOL_SIGNALS:
        state = rng.choice(["missing", "unknown", "true", "false"])
        if state == "unknown":
            signals[name] = Signal(status=rng.choice([SignalStatus.UNKNOWN, SignalStatus.UNCONFIRMED]))
        elif state in ("true", "false"):
            signals[name] = Signal(status=SignalStatus.CONFIRMED, value=state == "true")
    if rng.random() < 0.7:
        signals["bike_minutes"] = Signal(status=SignalStatus.CONFIRMED, value=float(rng.randint(3, 35)))
    return Listing(
        id=f"t:{i}",
        source=Source.YAD2,
        source_listing_id=str(i),
        area=Area(city="Bat Yam"),
        price=Price(amount=rng.randint(2500, 6500), currency="ILS"),
        size_m2=rng.choice([None, float(rng.randint(25, 110))]),
        floor=rng.choice([None, 0, 1, 2, 3, 4, 5]),
        pulled_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        signals=signals,
    )


def _price_overrides(rng: random.Random) -> list[dict]:
    """None, one or several loosening overrides, in random order, some
    moving only the limit, some only the ideal, some both."""
    pool = [
        {"when_signal": "balcony", "limit": 5000},
        {"when_signal": "parking", "limit": 4800, "ideal": 4200},
        {"when_signal": "elevator", "ideal": 4300},
        {"when_signal": "mamad", "limit": rng.choice([4600, 5200])},
    ]
    return rng.sample(pool, rng.randint(0, len(pool)))


def _relevance(rng: random.Random, top: int = 10) -> int:
    return 10 if top == 10 and rng.random() < 0.35 else rng.randint(1, min(top, 9))


def _prefs(rng: random.Random, top: int = 10) -> PreferenceSet:
    """A random preference set: every kind, dealbreakers and soft ones,
    overrides in any order, tolerances and falloffs. `top` < 10 keeps
    every relevance soft (for the ratio property)."""
    r = lambda: _relevance(rng, top)  # noqa: E731
    prefs = [
        {"name": "price", "label": "Price", "field": "price", "kind": "ranged", "relevance": r(),
         "ideal": 4000, "limit": 4500, "overrides": _price_overrides(rng)},
        {"name": "floor_cap", "label": "Floor cap", "field": "floor", "kind": "at_most", "relevance": r(),
         "limit": 2, "overrides": [{"when_signal": "elevator", "limit": 100}] if rng.random() < 0.6 else []},
        {"name": "size_floor", "label": "Size floor", "field": "size_m2", "kind": "at_least", "relevance": r(),
         "limit": 40},
        {"name": "bike", "label": "Bike", "field": "signal:bike_minutes", "kind": "ranged", "relevance": r(),
         "ideal": 10, "limit": 20},
        {"name": "size", "label": "Size", "field": "size_m2", "kind": "ranged", "relevance": r(),
         "ideal": 70, "limit": 40},
    ]
    for name in BOOL_SIGNALS:
        prefs.append({"name": name, "label": name, "field": f"signal:{name}", "kind": "yes_no",
                      "relevance": r(), "wants": rng.random() < 0.8})
    for p in prefs:
        if p["kind"] == "yes_no":
            continue
        if rng.random() < 0.5:
            p["tolerance"] = {"price": 450, "floor_cap": 1, "size_floor": 5}.get(p["name"], 3)
        if p["relevance"] < 10 and rng.random() < 0.3:
            p["falloff"] = {"price": 1000, "floor_cap": 2, "size_floor": 10}.get(p["name"], 5)
    return PreferenceSet.model_validate({"owner": "test", "preferences": prefs})


def _resolutions(listing: Listing, rng: random.Random) -> Listing:
    """Settle every unknown boolean signal at random, as a real answer would."""
    resolved = listing.model_copy(deep=True)
    for name in BOOL_SIGNALS:
        s = resolved.signals.get(name)
        if s is None or s.status != SignalStatus.CONFIRMED:
            resolved.signals[name] = Signal(status=SignalStatus.CONFIRMED, value=rng.random() < 0.5)
    return resolved


def _scores(s):
    return (s.match_low, s.match_expected, s.match_high)


class TestScoreProperties(unittest.TestCase):
    N = 3_000

    def test_bounds_and_order(self):
        rng = random.Random(1)
        for i in range(self.N):
            s = score_listing(_listing(rng, i), _prefs(rng))
            if s.match_low is not None:
                self.assertTrue(0 <= s.match_low <= s.match_expected <= s.match_high <= 100, s)

    def test_any_real_answer_lands_inside_the_range(self):
        # The range is a promise: once the unknowns are answered, the
        # score falls between low and high.
        rng = random.Random(2)
        for i in range(self.N):
            listing, prefs = _listing(rng, i), _prefs(rng)
            s = score_listing(listing, prefs)
            if s.match_low is None:
                continue
            resolved = score_listing(_resolutions(listing, rng), prefs)
            self.assertGreaterEqual(resolved.match_low, s.match_low - 1e-6, (listing, prefs))
            self.assertLessEqual(resolved.match_high, s.match_high + 1e-6, (listing, prefs))

    def test_cheaper_is_never_worse(self):
        rng = random.Random(3)
        for i in range(self.N):
            listing, prefs = _listing(rng, i), _prefs(rng)
            cheaper = listing.model_copy(deep=True)
            cheaper.price = Price(amount=max(1, listing.price.amount - rng.randint(1, 800)), currency="ILS")
            a, b = score_listing(listing, prefs), score_listing(cheaper, prefs)
            if a.match_low is not None:
                self.assertGreaterEqual(b.match_low, a.match_low - 1e-6)
                self.assertGreaterEqual(b.match_expected, a.match_expected - 1e-6)
            self.assertLessEqual(len(b.exclusion_reasons), len(a.exclusion_reasons))

    def test_only_the_ratios_of_soft_relevance_matter(self):
        rng = random.Random(4)
        for i in range(1_000):
            listing, prefs = _listing(rng, i), _prefs(rng, top=4)
            doubled = copy.deepcopy(prefs)
            for d in doubled.preferences:
                d.relevance *= 2
            self.assertEqual(_scores(score_listing(listing, prefs)), _scores(score_listing(listing, doubled)))

    def test_relaxing_a_dealbreaker_never_hides_more(self):
        # Relevance is strictness: turning a 10 into a 9 can only show more.
        rng = random.Random(7)
        for i in range(self.N):
            listing, prefs = _listing(rng, i), _prefs(rng)
            relaxed = copy.deepcopy(prefs)
            for p in relaxed.preferences:
                if p.relevance == 10:
                    p.relevance = 9
            a, b = score_listing(listing, prefs), score_listing(listing, relaxed)
            self.assertLessEqual(len(b.exclusion_reasons), len(a.exclusion_reasons), (listing, prefs))
            if not a.excluded:
                self.assertFalse(b.excluded)

    def test_a_dealbreaker_tolerance_only_turns_hiding_into_checks(self):
        rng = random.Random(6)
        for i in range(self.N):
            listing, prefs = _listing(rng, i), _prefs(rng)
            strict = copy.deepcopy(prefs)
            for p in strict.preferences:
                if p.relevance == 10:
                    p.tolerance = p.tolerance_note = None
            a, b = score_listing(listing, prefs), score_listing(listing, strict)
            self.assertEqual(_scores(a), _scores(b))
            self.assertLessEqual(len(a.exclusion_reasons), len(b.exclusion_reasons))
            if not b.excluded:
                self.assertFalse(a.excluded)

    def test_a_soft_criterion_without_a_tolerance_never_hides(self):
        rng = random.Random(8)
        for i in range(self.N):
            listing, prefs = _listing(rng, i), _prefs(rng)
            soft_names = {p.label for p in prefs.preferences if p.relevance < 10 and p.tolerance is None}
            for reason in score_listing(listing, prefs).exclusion_reasons:
                self.assertNotIn(reason.split(":")[0], soft_names, reason)

    def test_never_excluded_on_missing_data(self):
        rng = random.Random(5)
        for i in range(self.N):
            listing, prefs = _listing(rng, i), _prefs(rng)
            s = score_listing(listing, prefs)
            for reason in s.exclusion_reasons:
                self.assertNotIn("not stated", reason)


class TestFrozenRules(unittest.TestCase):
    def setUp(self):
        self.prefs = PreferenceSet.load(FROZEN_PREFS)
        self.base = Listing(
            id="t:1", source=Source.YAD2, source_listing_id="1", area=Area(city="Bat Yam"),
            price=Price(amount=4200, currency="ILS"), size_m2=60, floor=2,
            pulled_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
            signals={"bike_minutes": Signal(status=SignalStatus.CONFIRMED, value=15.0)},
        )

    def _with(self, **changes):
        listing = self.base.model_copy(deep=True)
        for key, value in changes.items():
            if key in Listing.model_fields:
                setattr(listing, key, value)
            elif value is None:
                listing.signals[key] = Signal(status=SignalStatus.UNKNOWN)
            else:
                listing.signals[key] = Signal(status=SignalStatus.CONFIRMED, value=value)
        return score_listing(listing, self.prefs)

    def _price(self, amount):
        return Price(amount=amount, currency="ILS")

    def test_price_is_soft_negotiable_up_to_450_over(self):
        # Relevance 7: past the limit (4,500, or 5,000 with a balcony) the
        # listing is still shown, flagged and scored lower -- up to 450 over;
        # beyond that it's hidden.
        s = self._with(price=self._price(4800))  # balcony unknown
        self.assertFalse(s.excluded)
        self.assertEqual(s.flags, ["Monthly rent (ILS): 4800 is past the limit of 4500; over budget, negotiable, "
                                   "within it if balcony is confirmed"])
        s = self._with(price=self._price(4800), balcony=False)
        self.assertEqual(s.flags, ["Monthly rent (ILS): 4800 is past the limit of 4500; over budget, negotiable"])
        price = next(r for r in s.results if r.name == "price")
        self.assertAlmostEqual(price.satisfaction, (4950 - 4800) / (4950 - 4000))  # 0 at the outer edge
        self.assertEqual(self._with(price=self._price(4800), balcony=True).flags, [])
        self.assertEqual(self._with(price=self._price(5000), balcony=False).exclusion_reasons,
                         ["Monthly rent (ILS): 5000 is past the limit of 4500 (tolerance 450)"])
        s = self._with(price=self._price(5200))  # visible only on the balcony's 5,000 limit
        self.assertFalse(s.excluded)
        self.assertIn("Monthly rent (ILS): 5200 is past the limit of 4500; over budget, negotiable, "
                      "shown only if balcony is confirmed", s.checks)
        self.assertFalse(self._with(price=self._price(5400), balcony=True).excluded)
        self.assertEqual(self._with(price=self._price(5500), balcony=True).exclusion_reasons,
                         ["Monthly rent (ILS): 5500 is past the limit of 5000 (tolerance 450)"])

    def test_floor_depends_on_the_elevator(self):
        # Dealbreaker: max floor 2 without an elevator; 3 only for an
        # exceptional apartment; any floor with an elevator.
        self.assertFalse(self._with(floor=2, elevator=False).excluded)
        s = self._with(floor=3, elevator=False)
        self.assertFalse(s.excluded)
        self.assertIn("Floor (max 2 without an elevator): 3 is past the limit of 2; only for an exceptional apartment", s.checks)
        s = self._with(floor=3)  # elevator unknown
        self.assertIn("Floor (max 2 without an elevator): 3 passes only if elevator is confirmed; "
                      "otherwise only for an exceptional apartment", s.checks)
        self.assertTrue(self._with(floor=4, elevator=False).excluded)
        self.assertFalse(self._with(floor=4, elevator=True).excluded)
        s = self._with(floor=7)  # elevator unknown: a check, never a guess
        self.assertFalse(s.excluded)
        self.assertIn("Floor (max 2 without an elevator): 7 passes only if elevator is confirmed", s.checks)

    def test_dealbreakers(self):
        for change in ({"size_m2": 39}, {"floor": 0}, {"roommate_listing": True}, {"protected_space": False},
                       {"air_conditioning": False}, {"parking_level": 0}, {"bike_minutes": 16.0}):
            with self.subTest(change=change):
                self.assertTrue(self._with(**change).excluded)
        self.assertFalse(self._with(size_m2=40, bike_minutes=15.0, parking_level=1).excluded)

    def test_unstated_dealbreakers_are_checks(self):
        s = self._with()
        self.assertFalse(s.excluded)
        # mamad, roommates, A/C and parking aren't stated on the base listing
        self.assertEqual(len(s.checks), 4, s.checks)

    def test_only_graded_criteria_are_weighted(self):
        weighted = {r.name for r in self._with().results if r.weight is not None}
        # the e-bike commute is graded since v1.26 (ranged: full marks at 7 min); A/C, shelter etc. stay pure filters
        self.assertEqual(weighted, {"price", "bike_minutes", "parking", "balcony", "elevator", "entry_timing", "renovated", "furniture"})
        self.assertAlmostEqual(sum(r.weight for r in self._with().results if r.weight is not None), 1.0)

    def test_parking_tiers(self):
        scores = {level: next(r.satisfaction for r in self._with(parking_level=level).results if r.name == "parking")
                  for level in (1, 2, 3)}
        self.assertEqual(scores, {1: 0.0, 2: 0.5, 3: 1.0})

    def test_worked_example_from_the_extension_plan(self):
        # The Extension Plan's worked example, pinned to its OWN four-rating
        # preference set so it stays valid as my.json grows: ₪4,300, 15
        # min, balcony confirmed, parking unknown, ratings price 9 / bike 8 /
        # balcony 7 / parking 5 -> 9+8+7+5 = 29 points.
        prefs = PreferenceSet.model_validate({"format_version": 2, "owner": "t", "preferences": [
            {"name": "price", "label": "Price", "field": "price", "kind": "ranged",
             "relevance": 9, "ideal": 4000, "limit": 4500,
             "overrides": [{"when_signal": "balcony", "limit": 5000}]},
            {"name": "bike", "label": "Bike", "field": "signal:bike_minutes", "kind": "ranged",
             "relevance": 8, "ideal": 10, "limit": 20},
            {"name": "balcony", "label": "Balcony", "field": "signal:balcony", "kind": "yes_no",
             "relevance": 7, "wants": True},
            {"name": "parking", "label": "Parking", "field": "signal:parking", "kind": "yes_no",
             "relevance": 5, "wants": True},
        ]})
        listing = self.base.model_copy(deep=True)
        listing.price = Price(amount=4300, currency="ILS")
        listing.signals["balcony"] = Signal(status=SignalStatus.CONFIRMED, value=True)
        s = score_listing(listing, prefs)
        price = (5000 - 4300) / (5000 - 4000)  # balcony confirmed: the limit is 5,000
        known = (9 * price + 8 * 0.5 + 7 * 1) / 29
        self.assertAlmostEqual(s.match_low, round(100 * known, 1), places=1)
        self.assertAlmostEqual(s.match_high, round(100 * (known + 5 / 29), 1), places=1)
        self.assertEqual(s.unknown, ["Parking"])


def _one(pref: dict, listing: Listing) -> "ScoredListing":
    return score_listing(listing, PreferenceSet.model_validate({"format_version": 2, "owner": "t", "preferences": [pref]}))


def _valid(*prefs: dict) -> PreferenceSet:
    return PreferenceSet.model_validate({"format_version": 2, "owner": "t", "preferences": list(prefs)})


def _flat(price: int, floor=None, **signals) -> Listing:
    return Listing(
        id="t:r", source=Source.YAD2, source_listing_id="r", area=Area(city="Bat Yam"),
        price=Price(amount=price, currency="ILS"), floor=floor,
        pulled_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        signals={k: v if isinstance(v, Signal) else Signal(status=SignalStatus.CONFIRMED, value=v)
                 for k, v in signals.items()},
    )


UNKNOWN = Signal(status=SignalStatus.UNKNOWN)


class TestRelevance(unittest.TestCase):
    """Relevance is strictness: 10 hides past the limit, 1-9 shows and
    scores lower (v1.12)."""

    BIKE = {"name": "bike", "label": "Bike", "field": "signal:bike_minutes", "kind": "at_most", "limit": 15}

    def test_soft_line_falls_off_to_zero_at_double_the_limit(self):
        for minutes, sat in ((14.0, 1.0), (15.0, 1.0), (22.5, 0.5), (30.0, 0.0), (40.0, 0.0)):
            s = _one({**self.BIKE, "relevance": 6}, _flat(4000, bike_minutes=minutes))
            with self.subTest(minutes=minutes):
                self.assertFalse(s.excluded)
                self.assertEqual(s.results[0].satisfaction, sat)
                self.assertEqual(bool(s.flags), minutes > 15)
        s = _one({**self.BIKE, "relevance": 6}, _flat(4000, bike_minutes=18.0))
        self.assertEqual(s.flags, ["Bike: 18 is past the limit of 15; scored lower"])

    def test_explicit_falloff_and_at_least_default(self):
        s = _one({**self.BIKE, "relevance": 6, "falloff": 5}, _flat(4000, bike_minutes=17.5))
        self.assertEqual(s.results[0].satisfaction, 0.5)
        size = {"name": "size", "label": "Size", "field": "size_m2", "kind": "at_least", "relevance": 6, "limit": 40}
        listing = _flat(4000)
        listing.size_m2 = 30.0  # default zero point for a minimum: half the limit (20)
        self.assertEqual(_one(size, listing).results[0].satisfaction, 0.5)

    def test_dealbreaker_line_hides_and_is_not_weighted(self):
        s = _one({**self.BIKE, "relevance": 10}, _flat(4000, bike_minutes=18.0))
        self.assertEqual(s.exclusion_reasons, ["Bike: 18 is past the limit of 15"])
        self.assertIsNone(s.results[0].weight)
        self.assertIsNone(s.match_low)  # nothing graded: no percentage at all

    def test_soft_yes_no_never_hides(self):
        balcony = {"name": "balcony", "label": "Balcony", "field": "signal:balcony", "kind": "yes_no", "wants": True}
        self.assertTrue(_one({**balcony, "relevance": 10}, _flat(4000, balcony=False)).excluded)
        s = _one({**balcony, "relevance": 9}, _flat(4000, balcony=False))
        self.assertFalse(s.excluded)
        self.assertEqual(s.match_low, 0.0)
        self.assertEqual(_one({**balcony, "relevance": 9}, _flat(4000)).checks, [])  # unstated soft: no check

    def test_a_dealbreaker_with_a_gradient_is_weighted(self):
        parking = {"name": "p", "label": "Parking", "field": "signal:parking_level", "kind": "ranged",
                   "relevance": 10, "ideal": 3, "limit": 1}
        s = _one(parking, _flat(4000, parking_level=2))
        self.assertEqual((s.results[0].weight, s.match_low), (1.0, 50.0))

    def test_format_1_files_still_load(self):
        old = {"owner": "t", "preferences": [
            {"name": "a", "label": "a", "field": "price", "kind": "ranged", "must_have": True, "importance": 9,
             "ideal": 1, "limit": 2},
            {"name": "b", "label": "b", "field": "signal:b", "kind": "yes_no", "importance": 10, "wants": True},
            {"name": "c", "label": "c", "field": "signal:c", "kind": "yes_no", "must_have": True, "wants": True},
        ]}
        prefs = PreferenceSet.model_validate(old)
        self.assertEqual([p.relevance for p in prefs.preferences], [10, 9, 10])  # importance 10 can't become a dealbreaker
        self.assertEqual(prefs.format_version, 2)
        undeclared = {"owner": "t", "preferences": [
            {"name": "a", "label": "a", "field": "signal:a", "kind": "yes_no", "relevance": 10, "wants": True}]}
        self.assertEqual(PreferenceSet.model_validate(undeclared).preferences[0].relevance, 10)  # read as format 2
        with self.assertRaises(ValidationError):  # declared format 1 must not use relevance
            PreferenceSet.model_validate({**undeclared, "format_version": 1})
        with self.assertRaises(ValidationError):  # format 1 still needs one or the other
            PreferenceSet.model_validate({"owner": "t", "preferences": [
                {"name": "a", "label": "a", "field": "signal:a", "kind": "yes_no", "wants": True}]})


class TestSecondReviewOfV112(unittest.TestCase):
    """The review of the relevance rewrite. Each test failed before its fix."""

    def test_format_1_soft_line_at_or_below_zero_still_loads(self):
        prefs = PreferenceSet.model_validate({"owner": "t", "preferences": [
            {"name": "f", "label": "Floor", "field": "floor", "kind": "at_least", "importance": 5, "limit": 0}]})
        self.assertEqual((prefs.preferences[0].relevance, prefs.preferences[0].falloff), (5, 1))

    def test_format_1_must_have_is_read_as_the_old_model_read_it(self):
        for lax in (1, "true", "yes", True):
            prefs = PreferenceSet.model_validate({"owner": "t", "preferences": [
                {"name": "p", "label": "P", "field": "price", "kind": "at_most", "must_have": lax,
                 "importance": 5, "limit": 4500}]})
            self.assertEqual(prefs.preferences[0].relevance, 10, lax)
        with self.assertRaises(ValidationError):
            PreferenceSet.model_validate({"owner": "t", "preferences": [
                {"name": "p", "label": "P", "field": "price", "kind": "at_most", "must_have": "maybe",
                 "importance": 5, "limit": 4500}]})

    def test_a_corrupt_override_condition_is_reported(self):
        price = {"name": "p", "label": "Price", "field": "price", "kind": "at_most", "relevance": 10, "limit": 4500,
                 "overrides": [{"when_signal": "balcony", "limit": 5000}]}
        self.assertIn("balcony: unexpected value 'yes'", _one(price, _flat(4800, balcony="yes")).checks)
        self.assertEqual(_one(price, _flat(4000, balcony="yes")).checks, ["balcony: unexpected value 'yes'"])
        self.assertEqual(_one(price, _flat(4000, balcony=True)).checks, [])

    def test_a_huge_integer_is_unexpected_not_a_crash(self):
        floor = {"name": "f", "label": "Floor", "field": "floor", "kind": "at_most", "relevance": 5, "limit": 2}
        self.assertEqual(_one(floor, _flat(4000, floor=10**400)).checks[0][:24], "Floor: unexpected value ")

    def test_a_value_exactly_at_the_band_edge_is_inside(self):
        rooms = {"name": "r", "label": "Rooms", "field": "rooms", "kind": "at_least", "relevance": 10,
                 "limit": 1.1, "tolerance": 1.0}
        listing = _flat(4000)
        listing.rooms = 0.1  # 1.1 - 1.0 is 0.10000000000000009 in floating point
        self.assertFalse(_one(rooms, listing).excluded)
        listing.rooms = 0.09
        self.assertTrue(_one(rooms, listing).excluded)


class TestConfigValidation(unittest.TestCase):
    def _bad(self, **pref):
        base = {"name": "x", "label": "x", "field": "price", "kind": "ranged", "relevance": 5, "ideal": 1, "limit": 2}
        base.update(pref)
        with self.assertRaises(ValidationError):
            _valid(base)

    def test_rejects_inconsistent_preferences(self):
        self._bad(ideal=2, limit=2)
        self._bad(kind="yes_no")  # yes/no with ideal/limit and no `wants`
        self._bad(relevance=None)
        self._bad(relevance=0)
        self._bad(relevance=11)
        self._bad(field="price_per_m2")
        self._bad(overrides=[{"when_signal": "balcony", "ideal": 3, "limit": 1}])  # flips direction
        self._bad(surprise=True)
        self._bad(must_have=True)  # format 1 keys aren't allowed in a format 2 file
        with self.assertRaises(ValidationError):
            PreferenceSet.model_validate({"format_version": 3, "owner": "t", "preferences": [
                {"name": "x", "label": "x", "field": "price", "kind": "ranged", "relevance": 5, "ideal": 1, "limit": 2}]})

    def test_frozen_files_load(self):
        PreferenceSet.load(FROZEN_PREFS)
        PreferenceSet.load(FROZEN_OCT_13)

    def test_rejects_inconsistent_thresholds_tolerances_and_falloffs(self):
        cap = {"name": "x", "label": "x", "field": "floor", "kind": "at_most", "relevance": 10, "limit": 2}
        for bad in ({"ideal": 1},                                      # a threshold has no ideal
                    {"limit": None},                                   # ...but needs a limit
                    {"wants": True},
                    {"overrides": [{"when_signal": "elevator", "ideal": 5}]},
                    {"overrides": [{"when_signal": "elevator", "limit": 1}]},  # tightens an at_most
                    {"tolerance": 0}, {"tolerance": -1},
                    {"tolerance_note": "exception"},                           # a note with no tolerance
                    {"tolerance": 1, "tolerance_note": "  "},
                    {"falloff": 2},                                            # a dealbreaker has no falloff
                    {"relevance": 5, "falloff": 0},
                    {"relevance": 5, "limit": 0}):                             # no relative default from 0
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                _valid({**cap, **bad})
        floor_min = {**cap, "name": "z", "kind": "at_least", "limit": 1}
        with self.assertRaises(ValidationError):  # raising an at_least limit tightens it
            _valid({**floor_min, "overrides": [{"when_signal": "elevator", "limit": 3}]})
        for extra in ({"tolerance": 1}, {"falloff": 1}):  # nothing ranged on yes/no
            with self.assertRaises(ValidationError):
                _valid({"name": "y", "label": "y", "field": "signal:y", "kind": "yes_no", "relevance": 10,
                        "wants": True, **extra})
        _valid({**cap, "tolerance": 1, "overrides": [{"when_signal": "elevator", "limit": 100}]}, floor_min)
        _valid({**cap, "relevance": 5, "limit": 0, "falloff": 1})


class TestDiffReviewRegressions(unittest.TestCase):
    """One test per finding of the Phase 1 diff review. Each failed
    against the code before the fix."""

    PRICE = {"name": "price", "label": "Price", "field": "price", "kind": "ranged",
             "relevance": 10, "ideal": 4000, "limit": 4500}

    def test_several_confirmed_overrides_dont_depend_on_order(self):
        # Before: the last matching override won, so listing order decided.
        a = {"when_signal": "balcony", "limit": 5000}
        b = {"when_signal": "parking", "limit": 4700}
        listing = _flat(4900, balcony=True, parking=True)
        for order in ([a, b], [b, a]):
            s = _one({**self.PRICE, "overrides": order}, listing)
            self.assertFalse(s.excluded, order)
            self.assertIn("limit 5000", s.results[0].detail)

    def test_ideal_and_limit_from_different_overrides_combine(self):
        ov = [{"when_signal": "balcony", "limit": 5000}, {"when_signal": "parking", "ideal": 4400}]
        s = _one({**self.PRICE, "overrides": ov}, _flat(4400, balcony=True, parking=True))
        self.assertEqual(s.results[0].satisfaction, 1.0)

    def test_tightening_overrides_are_rejected(self):
        for ov in ({"when_signal": "balcony", "limit": 4200},
                   {"when_signal": "balcony", "ideal": 3800},
                   {"when_signal": "balcony", "ideal": 3800, "limit": 5000}):
            with self.assertRaises(ValidationError, msg=ov):
                _valid({**self.PRICE, "overrides": [ov]})
        higher = {"name": "size", "label": "Size", "field": "size_m2", "kind": "ranged",
                  "relevance": 5, "ideal": 70, "limit": 40}
        with self.assertRaises(ValidationError):  # higher-is-better: raising the limit tightens
            _valid({**higher, "overrides": [{"when_signal": "balcony", "limit": 50}]})
        _valid({**higher, "overrides": [{"when_signal": "balcony", "limit": 35}]})

    def test_yes_no_must_read_a_signal(self):
        with self.assertRaises(ValidationError):
            _valid({"name": "x", "label": "x", "field": "floor", "kind": "yes_no", "relevance": 5, "wants": True})

    def test_wrong_type_confirmed_value_is_reported_not_hidden(self):
        yes_no = {"name": "balcony", "label": "Balcony", "field": "signal:balcony", "kind": "yes_no",
                  "relevance": 10, "wants": True}
        s = _one(yes_no, _flat(4000, balcony="yes"))
        self.assertFalse(s.excluded)
        self.assertEqual(s.checks, ["Balcony: unexpected value 'yes'"])
        self.assertEqual(_one({**yes_no, "relevance": 3}, _flat(4000, balcony="yes")).checks,
                         ["Balcony: unexpected value 'yes'"])  # soft too: corrupt data always surfaces
        bike = {"name": "bike", "label": "Bike", "field": "signal:bike_minutes", "kind": "ranged",
                "relevance": 10, "ideal": 10, "limit": 20}
        s = _one(bike, _flat(4000, bike_minutes="15 min"))
        self.assertEqual(s.checks, ["Bike: unexpected value '15 min'"])
        s = _one(bike, _flat(4000, bike_minutes=True))  # a bool is not a number
        self.assertEqual(s.checks, ["Bike: unexpected value True"])

    def test_non_finite_is_not_a_number_and_never_scores_full(self):
        # A non-finite confirmed value can only come from a buggy extractor
        # (the schema forbids inf/NaN). It must never be scored: -inf on a
        # lower-is-better metric used to read as a perfect commute (100%).
        from rental_matcher.scoring import _number
        for bad in (float("inf"), float("-inf"), float("nan"), True):
            self.assertIsNone(_number(bad))
        bike = {"name": "bike", "label": "Bike", "field": "signal:bike_minutes", "kind": "ranged",
                "relevance": 10, "ideal": 10, "limit": 20}
        for corrupt in (float("inf"), float("-inf")):
            listing = _flat(4000)
            listing.signals["bike_minutes"] = Signal.model_construct(status=SignalStatus.CONFIRMED, value=corrupt)
            s = _one(bike, listing)
            self.assertFalse(s.excluded, corrupt)  # never silently excluded or passed
            self.assertEqual(s.checks, [f"Bike: unexpected value {corrupt!r}"], corrupt)
            self.assertIsNone(s.results[0].satisfaction, corrupt)  # never 1.0
            self.assertEqual((s.match_low, s.match_high), (0.0, 100.0), corrupt)

    def test_check_names_only_the_conditions_that_rescue(self):
        ov = [{"when_signal": "balcony", "limit": 5000}, {"when_signal": "parking", "limit": 4700}]
        s = _one({**self.PRICE, "overrides": ov}, _flat(4900, balcony=UNKNOWN, parking=UNKNOWN))
        self.assertEqual(s.checks, ["Price: 4900 passes only if balcony is confirmed"])
        s = _one({**self.PRICE, "overrides": ov}, _flat(4600, balcony=UNKNOWN, parking=UNKNOWN))
        self.assertEqual(s.checks, ["Price: 4600 passes only if balcony or parking is confirmed"])

    def test_config_validation_gaps(self):
        base = {"name": "x", "label": "x", "field": "price", "kind": "ranged", "relevance": 5, "ideal": 1, "limit": 2}
        for bad in ({"relevance": True}, {"relevance": "5"}, {"relevance": 5.0},
                    {"overrides": [{"when_signal": "balcony"}]},
                    {"overrides": [{"when_signal": "balcony", "limit": 3}, {"when_signal": "balcony", "limit": 4}]},
                    {"overrides": [{"when_signal": "bal cony", "limit": 3}]},
                    {"label": "   "}, {"field": "signal: "}, {"field": "signal:"}, {"name": "has space"}):
            with self.assertRaises(ValidationError, msg=bad):
                _valid({**base, **bad})
        with self.assertRaises(ValidationError):
            _valid(base, base)


class TestPhase1ExitCriterion(unittest.TestCase):
    """Master Plan, Phase 1: 'Engine reproduces today's manual accept/reject
    calls on the 22 existing cards.' The legacy tracker marked 21 cards as
    passing (good=true); the 22nd (ho-uzj7unmh, 21 min by bike) was never
    marked. Under the rules that held then (Oct 13, frozen in
    preferences/history/) the engine keeps exactly the 21. the test user's rules
    have since changed (bike <= 15 min, parking and A/C required), so the
    current file is NOT expected to match these old calls."""

    def test_reproduces_the_manual_calls(self):
        legacy = json.loads((ROOT / "data" / "legacy_raw.json").read_text(encoding="utf-8"))
        manual = {
            f"yad2:{item['key'].split('-', 1)[1]}": item.get("good") is True
            for items in legacy.values()
            for item in items
        }
        listings = [Listing.model_validate(r) for r in json.loads((ROOT / "data" / "listings.json").read_text(encoding="utf-8"))]
        engine = {s.listing_id: not s.excluded for s in rank(listings, PreferenceSet.load(FROZEN_OCT_13))}
        self.assertEqual(engine, manual)
        self.assertEqual(sum(engine.values()), 21)


if __name__ == "__main__":
    unittest.main()


class TestAiOnlyAnswersDontHide(unittest.TestCase):
    """A value only the language model read (rules silent, no ticked box)
    scores, but can't hide a listing by itself: on a dealbreaker it's a
    check that quotes what the AI relied on. Same value from the rules (or
    agreed by them) hides as before."""

    ELEVATOR = {"name": "elevator", "label": "Elevator", "field": "signal:elevator", "kind": "yes_no", "wants": True, "relevance": 10}
    PARKING = {"name": "parking", "label": "Parking", "field": "signal:parking_level", "kind": "at_least", "limit": 2, "relevance": 10}

    def _sig(self, value, by):
        return Signal(status=SignalStatus.CONFIRMED, value=value, evidence="text: קומה רביעית ללא עמודים", extracted_by=by)

    def test_yes_no_dealbreaker(self):
        ai = _one(self.ELEVATOR, _flat(4000, elevator=self._sig(False, ExtractedBy.LLM)))
        self.assertFalse(ai.excluded)
        self.assertEqual(len(ai.checks), 1)
        self.assertIn("read only by the AI", ai.checks[0])
        self.assertIn("ללא עמודים", ai.checks[0])
        ruled = _one(self.ELEVATOR, _flat(4000, elevator=self._sig(False, ExtractedBy.RULE)))
        self.assertTrue(ruled.excluded)

    def test_ranged_dealbreaker(self):
        ai = _one(self.PARKING, _flat(4000, parking_level=self._sig(1.0, ExtractedBy.LLM)))
        self.assertFalse(ai.excluded)
        self.assertTrue(any("read only by the AI" in c for c in ai.checks))
        self.assertTrue(_one(self.PARKING, _flat(4000, parking_level=self._sig(1.0, ExtractedBy.RULE))).excluded)

    def test_an_ai_only_yes_still_counts_but_is_marked_verify(self):
        s = _one(self.ELEVATOR, _flat(4000, elevator=self._sig(True, ExtractedBy.LLM)))
        self.assertEqual((s.excluded, s.results[0].status), (False, "met"))
        self.assertEqual(len(s.checks), 1)
        self.assertIn("verify before relying on it", s.checks[0])
        s = _one(self.ELEVATOR, _flat(4000, elevator=self._sig(True, ExtractedBy.RULE)))
        self.assertEqual(s.checks, [])

    def test_an_ai_only_pass_on_a_ranged_dealbreaker_is_marked_verify(self):
        s = _one(self.PARKING, _flat(4000, parking_level=self._sig(3.0, ExtractedBy.LLM)))
        self.assertEqual((s.excluded, len(s.checks)), (False, 1))
        self.assertIn("verify before relying on it", s.checks[0])

    def test_an_unclear_signal_is_a_check_that_quotes_the_listing(self):
        unclear = Signal(status=SignalStatus.UNCONFIRMED, evidence="text, unclear: יש הכנה למעלית", extracted_by=ExtractedBy.RULE)
        s = _one(self.ELEVATOR, _flat(4000, elevator=unclear))
        self.assertFalse(s.excluded)
        self.assertEqual(s.checks, ["Elevator: unclear (text, unclear: יש הכנה למעלית)"])


class TestAiCantLoosen(unittest.TestCase):
    """A balcony raises the budget to 5,000, but not a balcony only the AI
    read ("דירת גג" taken for one): that's a check, not a pass."""

    PRICE = {"name": "price", "label": "Rent", "field": "price", "kind": "ranged", "relevance": 7, "ideal": 4000,
             "limit": 4500, "overrides": [{"when_signal": "balcony", "limit": 5000}]}

    def _balcony(self, by):
        return Signal(status=SignalStatus.CONFIRMED, value=True, evidence="text: דירת גג", extracted_by=by)

    def test_an_ai_only_condition_doesnt_raise_the_limit(self):
        ai = _one(self.PRICE, _flat(4900, balcony=self._balcony(ExtractedBy.LLM)))
        rule = _one(self.PRICE, _flat(4900, balcony=self._balcony(ExtractedBy.RULE)))
        self.assertEqual(rule.flags, [])  # within the raised limit
        self.assertTrue(any("balcony" in c for c in ai.checks + ai.flags), (ai.checks, ai.flags))
        self.assertLess(ai.results[0].satisfaction, rule.results[0].satisfaction)


class TestHasItems(unittest.TestCase):
    FURNITURE = {"name": "furniture", "label": "Furniture", "field": "signal:furniture", "kind": "has_items",
                 "relevance": 3, "items": ["bed", "sofa", "fridge", "washer"]}

    def _r(self, items):
        s = _one(self.FURNITURE, _flat(4000, **({"furniture": items} if items is not None else {})))
        return s, s.results[0]

    def test_named_items_score_their_share_and_the_rest_is_unknown(self):
        s, r = self._r(["fridge", "sofa", "closets", "says_furnished"])
        self.assertEqual((r.satisfaction, r.status), (0.5, "partly met"))
        self.assertEqual((s.match_low, s.match_high), (50.0, 100.0))  # the bed and washer aren't said to be missing
        self.assertEqual(r.detail, "has sofa, fridge (2 of 4 wanted; the rest not stated); built in: closets; says furnished")

    def test_unfurnished_means_the_rest_is_missing(self):
        s, r = self._r(["says_unfurnished", "oven_stove"])
        self.assertEqual((s.match_low, s.match_high, r.satisfaction), (0.0, 0.0, 0.0))

    def test_a_claim_with_no_items_is_a_range_not_a_pass(self):
        s, r = self._r(["says_furnished"])
        self.assertEqual((s.match_low, s.match_high), (0.0, 100.0))
        self.assertIn("says furnished", r.detail)

    def test_nothing_said_is_unknown_and_not_a_check(self):
        s, r = self._r(None)
        self.assertEqual((r.satisfaction, s.checks), (None, []))

    def test_it_cant_be_a_dealbreaker_or_carry_ranged_fields(self):
        for bad in ({"relevance": 10}, {"items": []}, {"wants": True}, {"limit": 3}):
            with self.assertRaises(ValueError, msg=bad):
                _valid({**self.FURNITURE, **bad})
        with self.assertRaises(ValueError):
            _valid({**TestAiOnlyAnswersDontHide.ELEVATOR, "items": ["bed"]})


class TestFanNote(unittest.TestCase):
    AC = {"name": "ac", "label": "A/C", "field": "signal:air_conditioning", "kind": "yes_no", "wants": True, "relevance": 10}

    def test_ac_with_a_fan_is_met_with_a_note_and_a_check(self):
        fan = Signal(status=SignalStatus.CONFIRMED, value=True, evidence="text: מזגן + מאוורר", extracted_by=ExtractedBy.RULE)
        ac = Signal(status=SignalStatus.CONFIRMED, value=True, evidence="text: מזגן", extracted_by=ExtractedBy.RULE)
        s = _one(self.AC, _flat(4000, air_conditioning=ac, fan=fan))
        self.assertEqual((s.excluded, s.results[0].status, s.results[0].detail), (False, "met", "yes (+fan)"))
        self.assertEqual(len(s.checks), 1)
        self.assertIn("+fan (text: מזגן + מאוורר)", s.checks[0])
        self.assertEqual(_one(self.AC, _flat(4000, air_conditioning=ac)).checks, [])
