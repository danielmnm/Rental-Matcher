"""
Tests for rental_matcher.costs.

Three layers, deliberately:
  1. A soundness PROPERTY over thousands of generated notes whose correct
     answer is known by construction (tests/cost_text_generator.py). The
     parser may stay silent; it may never return an amount the text
     doesn't truly state for that field. Run against v1.5's parser, this
     property failed on 18,128 of 30,000 generated cases -- every one of
     v1.5's own 11 example tests had passed.
  2. The real data: all 22 legacy records, end to end.
  3. Named regression examples, including every case from the fifth and
     sixth external reviews, with realistic MULTI-element flag lists
     (the real data's shape) as well as single strings.
"""

import json
import random
import unittest

try:  # run via `unittest discover -s tests` (tests/ is on sys.path)
    from cost_text_generator import generate
except ModuleNotFoundError:  # run as `python -m unittest tests.test_costs`
    from tests.cost_text_generator import generate

from rental_matcher.costs import parse_recurring_costs, split_clauses
from rental_matcher.migrate import LEGACY_RAW_PATH


def _pair(flags):
    r = parse_recurring_costs(flags)
    return None if r is None else (r.vaad_bayit_monthly, r.arnona_monthly)


class TestSoundnessProperty(unittest.TestCase):
    ITERATIONS = 20_000

    def test_never_returns_an_amount_the_text_does_not_state(self):
        rng = random.Random(20261017)
        failures = []
        for _ in range(self.ITERATIONS):
            g = generate(rng)
            r = parse_recurring_costs(g.flags)
            vaad = r.vaad_bayit_monthly if r else None
            arnona = r.arnona_monthly if r else None
            if (vaad is not None and vaad not in g.true_vaad) or (
                arnona is not None and arnona not in g.true_arnona
            ):
                failures.append((g.flags, vaad, arnona, g.true_vaad, g.true_arnona))
        self.assertEqual(failures[:5], [], f"{len(failures)} unsound results")

    def test_is_not_trivially_sound_by_never_extracting(self):
        # Soundness alone is satisfied by `return None`. Require real recall.
        rng = random.Random(7)
        stated = found = 0
        for _ in range(5_000):
            g = generate(rng)
            r = parse_recurring_costs(g.flags)
            stated += bool(g.true_vaad) + bool(g.true_arnona)
            found += (r is not None and r.vaad_bayit_monthly is not None) + (
                r is not None and r.arnona_monthly is not None
            )
        # Recall on this deliberately adversarial generator: ~92% in v1.6,
        # ~79-81% in v1.7. Each soundness fix in v1.7 (a number after the
        # separator, a number BEFORE the keyword, periods in the next
        # clause) refused some answerable cases too. A wrong amount is worse
        # than a missing one, and recall on free text is Phase 2's job (an
        # LLM extractor measured against a labeled set), not more regex.
        self.assertGreater(found / stated, 0.75)

    def test_each_flag_is_parsed_on_its_own(self):
        # Joining flags must never create an extraction neither flag
        # supports alone -- the v1.5 " ".join(flags) bug, as a property.
        rng = random.Random(99)
        for _ in range(5_000):
            flags = generate(rng).flags
            combined = parse_recurring_costs(flags)
            singles = [parse_recurring_costs([f]) for f in flags]
            for attr in ("vaad_bayit_monthly", "arnona_monthly"):
                got = getattr(combined, attr) if combined else None
                if got is not None:
                    self.assertIn(got, {getattr(s, attr) for s in singles if s}, flags)


class TestRealData(unittest.TestCase):
    def test_only_the_one_real_amount_is_extracted(self):
        with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
            legacy = json.load(f)
        extracted = {}
        for area_key, items in legacy.items():
            for item in items:
                # The parser on the legacy text itself: since v1.12 the
                # migration flags cost mentions instead of storing this.
                costs = parse_recurring_costs(item.get("flags", []))
                if costs is not None:
                    extracted[item["key"]] = (costs.vaad_bayit_monthly, costs.arnona_monthly)
        self.assertEqual(extracted, {"ho-k678s664": (70.0, None)})


class TestMultiElementFlags(unittest.TestCase):
    """The sixth review's central catch: every v1.5 example used ONE string
    with commas, but real flags are SEPARATE strings with no trailing
    punctuation, and v1.5 joined them with a space."""

    def test_monthly_marker_does_not_leak_to_the_next_flag(self):
        self.assertEqual(_pair(["vaad bayit ₪70/mo", "arnona ₪700"]), (70.0, None))

    def test_number_does_not_leak_from_the_next_flag(self):
        self.assertIsNone(_pair(["ללא ועד בית", "4 חדרים"]))

    def test_each_field_can_come_from_a_different_flag(self):
        self.assertEqual(_pair(["vaad bayit ₪70/mo", "arnona ₪450/mo"]), (70.0, 450.0))


class TestClauseBoundaries(unittest.TestCase):
    def test_em_dash_separates_clauses(self):
        self.assertEqual(_pair(["vaad bayit ₪70/mo — arnona ₪700"]), (70.0, None))

    def test_hebrew_conjunction_does_not_share_a_marker(self):
        self.assertEqual(_pair(["ועד בית 70 לחודש וארנונה 800 לחודשיים"]), (70.0, None))

    def test_later_keyword_marker_does_not_flow_backward(self):
        self.assertEqual(_pair(["ארנונה 800 וועד בית 70 לחודש"]), (70.0, None))

    def test_thousands_comma_and_decimal_point_are_not_separators(self):
        self.assertEqual(split_clauses("ארנונה 1,200 לחודש"), ["ארנונה 1,200 לחודש"])
        self.assertEqual(_pair(["ארנונה 1,200 לחודש"]), (None, 1200.0))
        self.assertEqual(_pair(["ועד בית 70.5 לחודש"]), (70.5, None))

    def test_other_commas_and_periods_are(self):
        self.assertIsNone(_pair(["ללא ועד בית, 4 חדרים"]))
        self.assertIsNone(_pair(["vaad bayit none, 6 photos"]))


class TestRejections(unittest.TestCase):
    def test_negated_keyword(self):
        self.assertIsNone(_pair(["ללא ועד בית 4 דירות"]))
        self.assertIsNone(_pair(["ללא ועד בית (בניין של 4 דירות)"]))
        self.assertIsNone(_pair(["vaad bayit: none - 6 photos"]))

    def test_lo_kolel_negation_is_not_extracted(self):
        # "לא כולל ..." ("not including ...") used to leak a wrong amount.
        self.assertIsNone(_pair(["לא כולל ועד בית 100 לחודש"]))
        self.assertIsNone(_pair(["לא כולל ארנונה 450 לחודש"]))
        self.assertIsNone(_pair(["דירה משופצת, לא כולל ועד בית 250"]))
        # A real extraction a few words after a bare "לא" elsewhere still works.
        self.assertEqual(_pair(["ועד בית 100 לחודש"]), (100.0, None))

    def test_negation_over_a_joined_pair_covers_both(self):
        # "without arnona and vaad bayit 400": the negation distributes over
        # the conjunction, so 400 belongs to neither (it used to go to vaad).
        for text in ["ללא ארנונה וועד בית 400", "דירה יפה, ללא ארנונה וועד בית 400",
                     "without arnona and vaad bayit 400"]:
            with self.subTest(text=text):
                self.assertIsNone(_pair([text]))
        # A separator ends the negation's scope: the second keyword stands.
        self.assertEqual(_pair(["ללא ועד בית, ארנונה 450 לחודש"]), (None, 450.0))

    def test_period_in_an_earlier_clause_does_not_poison_a_later_one(self):
        # A bi-monthly marker on arnona must not reach across to vaad bayit,
        # which has no monthly-marker requirement. The result must be the
        # same regardless of clause order (it used to depend on it).
        a = _pair(["ארנונה 800 לחודשיים, ועד בית 150"])
        b = _pair(["ועד בית 150, ארנונה 800 לחודשיים"])
        self.assertEqual(a, b)
        self.assertEqual(a, (150.0, None))
        # A real flag-level annual heading still suppresses a bare amount.
        self.assertIsNone(_pair(["Annual: vaad bayit 1200"]))

    def test_number_followed_by_anything_but_currency_or_frequency(self):
        for text in ["ועד בית 4 חדרים", "ועד בית 2 מעליות", "ועד בית 10%",
                     "ארנונה 50 למ\"ר לחודש", "ועד בית 150-200", "ועד בית 150–200 ש\"ח",
                     "ארנונה 2025: 450 לחודש", "ארנונה 1 200 לחודש"]:
            with self.subTest(text=text):
                self.assertIsNone(_pair([text]))

    def test_combined_total_is_not_attributed_to_either_field(self):
        self.assertIsNone(_pair(["ארנונה ועד בית 400 לחודש"]))
        self.assertIsNone(_pair(["vaad bayit + arnona 600/mo"]))

    def test_bi_monthly_arnona_is_never_read_as_monthly(self):
        for text in ["ארנונה 700 לחודשיים", "ארנונה 800 דו-חודשי", "arnona 900 bi-monthly"]:
            with self.subTest(text=text):
                self.assertIsNone(_pair([text]))

    def test_arnona_without_a_monthly_marker_is_ambiguous(self):
        self.assertIsNone(_pair(["דירה יפה, ארנונה 700, קומה 2"]))


class TestAccepted(unittest.TestCase):
    def test_typical_phrasings(self):
        cases = {
            "No parking, elevator yes, A/C yes, 6 photos, vaad bayit ₪70/mo": (70.0, None),
            "דירה יפה, ועד בית 300, קומה 2": (300.0, None),
            "ועד הבית: 250 ש\"ח": (250.0, None),
            "ארנונה 450 לחודש, קרוב לתחבורה": (None, 450.0),
            "Nice place, arnona ₪450/mo, close to transit": (None, 450.0),
            "ארנונה 4500 לחודש": (None, 4500.0),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_pair([text]), expected)

    def test_seventh_review_cases(self):
        self.assertEqual(_pair(["ארנונה 450/חודש"]), (None, 450.0))
        self.assertIsNone(_pair(["vaad bayit ₪0"]))
        self.assertIsNone(_pair(["vaad bayit 0"]))
        self.assertIsNone(_pair(["ארנונה 900 ל-2 חודשים"]))
        # Claimed to split into "1" and "200.50"; checked, it doesn't:
        # the comma's lookahead `\d{3}(?!\d)` is satisfied at the ".".
        self.assertEqual(split_clauses("ארנונה 1,200.50 לחודש"), ["ארנונה 1,200.50 לחודש"])
        self.assertEqual(_pair(["ארנונה 1,200.50 לחודש"]), (None, 1200.5))

    def test_independent_review_cases(self):
        for text in [
            "vaad bayit 1200 - per year", "ועד בית 3600; שנתי", "ועד בית 150 - 200",
            "ארנונה 400 לחודש, לכל שותף", "ועד בית כולל ארנונה 600 לחודש",
            "arnona plus vaad bayit 600/month", "ארנונה, ועד בית 600 לחודש",
            "ארנונה 1.200 לחודש", "ועד בית 70+",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(_pair([text]))
        self.assertEqual(_pair(["ללא ועד בית, ארנונה 450 לחודש"]), (None, 450.0))

    def test_second_independent_review_cases(self):
        for text in [
            "ועד בית 150, לחודשיים", "ועד בית 300 - quarterly", "ועד בית 840, פעם בשנה",
            "70 ש״ח ועד בית 400 ש״ח ארנונה לחודש",  # amounts written before their keywords
            "800 ₪ לחודשיים ארנונה 70 ₪ לחודש ועד בית",
            "ארנונה 200 לחודש, לחדר", "ועד בית 50, לדייר", "Annual: vaad bayit 1200",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(_pair([text]))
        self.assertEqual(_pair(["ועד בית 70 לחודש וארנונה 450 לחודש"]), (70.0, 450.0))

    def test_a_period_word_earlier_in_the_flag(self):
        # Blocks an amount with no frequency of its own; an explicit
        # monthly marker on the amount itself still wins.
        self.assertIsNone(_pair(["Annual: vaad bayit 1200"]))
        self.assertIsNone(_pair(["שנתי: ועד בית 100, קומה 2"]))
        self.assertEqual(_pair(["Annual: vaad bayit 1200 and arnona 400/mo"]), (None, 400.0))

    def test_nothing_found_returns_none_not_an_empty_object(self):
        self.assertIsNone(parse_recurring_costs(["No parking, elevator yes"]))
        self.assertIsNone(parse_recurring_costs([]))


if __name__ == "__main__":
    unittest.main()


class TestBimonthlyArnonaOptIn(unittest.TestCase):
    """candidate_spans(bimonthly_arnona=True), used by the rule-based
    answerer: arnona stated per two months becomes its monthly half. The
    default path (parse_recurring_costs) still refuses it."""

    def test_halved_only_when_the_marker_is_the_amounts_own(self):
        from rental_matcher.costs import candidate_spans
        cases = {
            'ארנונה : 700 ש"ח לחודשיים.': [("arnona", 350.0)],
            'ארנונה דו חודשית: 450 ש"ח': [("arnona", 225.0)],
            "ארנונה 800 לחודשיים, ועד בית 150": [("arnona", 400.0), ("vaad", 150.0)],
            "ארנונה 450 לחודש": [("arnona", 450.0)],
            "ארנונה 450": [],
            "ארנונה דו חודשי 450 לחודש": [],  # two periods: which?
            "ארנונה 700 לחודשיים לכל שותף": [],
            "ארנונה 700 לחודשיים - 750": [],
            "ללא ארנונה 700 לחודשיים": [],
            "ועד בית 100 לחודשיים": [],  # only arnona has the bi-monthly convention
            "ארנונה וועד בית 700 לחודשיים": [],
            "ארנונה דו חודשית 450-500": [],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                got = [(f, a) for f, a, s, e in candidate_spans(text, bimonthly_arnona=True)]
                self.assertEqual(got, expected)
                for f, a, s, e in candidate_spans(text, bimonthly_arnona=True):
                    quoted = text[s:e]  # the evidence: keyword through amount
                    self.assertTrue(quoted.startswith(("ארנונה", "ועד")), quoted)
                    self.assertRegex(quoted, r"\d")
        self.assertIsNone(parse_recurring_costs(['ארנונה : 700 ש"ח לחודשיים.']))
