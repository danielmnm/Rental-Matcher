"""
Tests for rental_matcher.listed_by.

The soundness property: generated notes from a private listing must never
come back AGENCY, and from an agency listing never PRIVATE. Unknown (None)
is always allowed. Plus the 22 real records and every phrasing an
external review has raised.
"""

import json
import random
import unittest

from rental_matcher.listed_by import detect_listed_by
from rental_matcher.migrate import LEGACY_RAW_PATH
from rental_matcher.schema import ListedBy

PRIVATE_PHRASES = [
    "ללא תיווך", "ללא מתווכים", "בלי תיווך", "אין תיווך", "לא לתיווך", "לא למתווך", "לא למתווכים",
    "מתווכים לא לפנות", "מתווכים נא לא לפנות", "מתווכים לא להתקשר", "מתווכים לא יתקשרו",
    "נא לא לפנות מתווכים", "בבקשה לא להתקשר ממתווכים", "no broker", "no brokers", "no agents please",
    "without an agent", "direct from owner", "broker-free", "brokers please don't call",
    "not through an agency", "non-agency",
]
AGENCY_PHRASES = [
    "משרד תיווך {n}", "משרד מתווכים מוביל", "Agency listing (Merkaz HaNadlan)", "via broker",
    "listed by an agent", "בבלעדיות משרד תיווך", "דמי תיווך חודש", "תיווך: חודש שכירות",
]
FEE_WAIVERS = ["ללא עמלת תיווך", "ללא דמי תיווך", "0% עמלה", "no agency fee", "no broker fee"]
# Agency mentions next to an unrelated negation: the parser may say
# unknown, never PRIVATE.
AGENCY_WITH_OTHER_NEGATION = ["Agency listing not furnished", "broker fee not stated", "משרד תיווך, לא מרוהטת"]
NOISE = [
    "no parking", "לא מרוהטת", "ללא חיות", "{n} rooms", "קומה {n}", "elevator yes",
    "smoking: no", "pets: לא", "Price dropped ₪5,000→₪4,500", "ממ\"ד",
]
# Includes a bare space: it glues "smoking: no" straight onto the next
# item, which is how the "label: no" false positive was found.
JOINERS = [", ", " — ", "; ", " - ", " | ", " "]


def _fill(text: str, rng: random.Random) -> str:
    return text.format(n=rng.randint(1, 9))


def generate(rng: random.Random) -> tuple[list[str], ListedBy]:
    truth = rng.choice([ListedBy.PRIVATE, ListedBy.AGENCY])
    pool = PRIVATE_PHRASES if truth == ListedBy.PRIVATE else AGENCY_PHRASES + FEE_WAIVERS + AGENCY_WITH_OTHER_NEGATION
    flags = []
    for _ in range(rng.randint(1, 3)):
        parts = [_fill(rng.choice(NOISE), rng) for _ in range(rng.randint(0, 3))]
        if rng.random() < 0.7:
            parts.insert(rng.randint(0, len(parts)), _fill(rng.choice(pool), rng))
        if parts:
            flag = parts[0]
            for part in parts[1:]:
                flag += rng.choice(JOINERS) + part
            flags.append(flag)
    return flags, truth


class TestSoundnessProperty(unittest.TestCase):
    def test_never_the_opposite_of_the_truth(self):
        rng = random.Random(11)
        wrong = []
        for _ in range(20_000):
            flags, truth = generate(rng)
            got = detect_listed_by(flags)
            if got is not None and got != truth:
                wrong.append((flags, truth, got))
        self.assertEqual(wrong[:5], [], f"{len(wrong)} wrong classifications")

    def test_is_not_trivially_sound_by_never_answering(self):
        rng = random.Random(12)
        answered = total = 0
        for _ in range(5_000):
            flags, _ = generate(rng)
            total += 1
            answered += detect_listed_by(flags) is not None
        self.assertGreater(answered / total, 0.5)


class TestRealData(unittest.TestCase):
    def test_the_22_real_records(self):
        with LEGACY_RAW_PATH.open(encoding="utf-8") as f:
            legacy = json.load(f)
        got = {
            # The detector on the legacy text: since v1.12 the migration
            # flags brokerage mentions instead of storing this.
            item["key"]: detect_listed_by(item.get("flags", []))
            for area, items in legacy.items()
            for item in items
        }
        self.assertEqual(got.pop("ho-8raxcjyc"), ListedBy.PRIVATE)
        self.assertEqual(got.pop("ye-x5zoqq0y"), ListedBy.AGENCY)
        self.assertEqual(got.pop("ho-2n3u1zl7"), ListedBy.AGENCY)
        self.assertEqual(set(got.values()), {None})


class TestReviewPhrasings(unittest.TestCase):
    def test_seventh_review_false_positives_are_private(self):
        # v1.6 called all four AGENCY. Two were a v1.5 regression: adding
        # plural "מתווכים" as a positive keyword without a pattern-based
        # negation check in front of it.
        for text in ["מתווכים לא להתקשר", "מתווכים נא לא לפנות", "לא לתיווך", "לא למתווך"]:
            with self.subTest(text=text):
                self.assertEqual(detect_listed_by([text]), ListedBy.PRIVATE)

    def test_independent_review_cases(self):
        cases = {
            "מתווכים - נא לא לפנות": ListedBy.PRIVATE,  # separator between broker and "don't contact"
            "Brokers, please don't call": ListedBy.PRIVATE,
            "מתווכים — לא": ListedBy.PRIVATE,
            "דירה מבעלים וללא תיווך": ListedBy.PRIVATE,  # prefixed negation
            "שלא דרך תיווך": ListedBy.PRIVATE,
            "No broker's fee": ListedBy.AGENCY,  # about a fee, not about a broker
            "בלי תיווך לשוכר": ListedBy.AGENCY,
            "לפרטים נא לפנות אל המתווך": ListedBy.AGENCY,  # "אל" = "to", not "don't"
            "Agency listing - no calls after 22:00": ListedBy.AGENCY,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detect_listed_by([text]), expected)

    def test_second_independent_review_cases(self):
        never_private = [
            "תיווך בלעדי מהבעלים",  # "exclusive from the owner" is an agency phrase
            "Exclusive agency listing directly from the owner",
            "משרד תיווך נא לא להתקשר בשבת",  # restricts WHEN to call
            "Agency listing no calls after 22:00",
            "Agent please don't call before 9, text instead",
        ]
        for text in never_private:
            with self.subTest(text=text):
                self.assertNotEqual(detect_listed_by([text]), ListedBy.PRIVATE)
        for text in ["ללא עמלה ישירות מהבעלים", "No broker fee direct from owner"]:
            with self.subTest(text=text):
                self.assertNotEqual(detect_listed_by([text]), ListedBy.AGENCY)
        for text in ["Brokers - no thanks", "מתווכים - לא תודה"]:
            with self.subTest(text=text):
                self.assertEqual(detect_listed_by([text]), ListedBy.PRIVATE)
        self.assertIsNone(detect_listed_by(["Brokers"]))  # a lone word isn't a listing description

    def test_features_list_no_is_private_even_when_singular(self):
        for text in ["מתווך - לא", "Broker: no", "תיווך: אין"]:
            with self.subTest(text=text):
                self.assertEqual(detect_listed_by([text]), ListedBy.PRIVATE)
        self.assertNotEqual(detect_listed_by(["מתווכת - נא לא להתקשר"]), ListedBy.PRIVATE)
        self.assertNotEqual(detect_listed_by(["Agent - no, fee 1 month"]), ListedBy.PRIVATE)

    def test_fee_waivers_are_agency(self):
        for text in FEE_WAIVERS:
            with self.subTest(text=text):
                self.assertEqual(detect_listed_by([text]), ListedBy.AGENCY)

    def test_unrelated_negation_next_to_an_agency_mention_is_unknown(self):
        self.assertIsNone(detect_listed_by(["Agency listing not furnished"]))

    def test_a_label_value_negation_does_not_negate_the_next_word(self):
        self.assertNotEqual(detect_listed_by(["smoking: no Agency listing"]), ListedBy.PRIVATE)
        self.assertNotEqual(detect_listed_by(["pets: לא תיווך: חודש שכירות"]), ListedBy.PRIVATE)

    def test_clauses_that_disagree_give_unknown(self):
        self.assertIsNone(detect_listed_by(["Agency listing — no brokers please"]))


if __name__ == "__main__":
    unittest.main()
