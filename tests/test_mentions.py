"""
Tests for rental_matcher.mentions: flags carry the words, never a verdict.
"""

import json
import unittest
from pathlib import Path

from rental_matcher.costs import parse_recurring_costs
from rental_matcher.listed_by import detect_listed_by
from rental_matcher.mentions import brokerage_mention, recurring_costs_mention
from rental_matcher.schema import ExtractedBy, SignalStatus

EVAL = Path(__file__).resolve().parent / "phase2_eval_cases.json"


class TestBrokerageMention(unittest.TestCase):
    def test_broker_words_and_licenses_are_flagged(self):
        for text in ["ללא תיווך", "דמי תיווך חודש", "והמתווך יחזור אליך", "מתווכת מורשית", "בתיווך משרד רימקס",
                     "רישיון תיווך מס' 31245", "רשיון 312456", "Broker: N/A", "Brokers welcome", "תיווך?",
                     "licence no. 12345", "real estate office", "Merkaz HaNadlan brokerage",
                     # review of v1.12: license formats and agent words it missed
                     "רישיון מס': 312345", "מספר רישיון: 312345", "רשיון מס. 312345", "מס' רישיון 31245",
                     "License No: 12345", "Lic. #12345", 'סוכן נדל"ן', "סוכנת נדלן", 'משרד נדל"ן אנגלו סכסון',
                     'יועץ נדל"ן', "agency fee", "broker's fee"]:
            with self.subTest(text=text):
                flag = brokerage_mention([text])
                self.assertIsNotNone(flag)
                self.assertEqual((flag.status, flag.value, flag.extracted_by),
                                 (SignalStatus.UNCONFIRMED, None, ExtractedBy.RULE))
                self.assertEqual(flag.evidence, text)

    def test_words_that_only_look_like_broker_words_are_not(self):
        # מתווכחים is "arguing" ("לא מתווכחים" = "no haggling"); review 11.
        for text in ["לא מתווכחים על המחיר", "המחיר סופי, לא מתווכחים", "מתווכחים על המחיר", "התווכחנו",
                     "Travel agency downstairs", "עמוד התווך", "דירה יפה, 3 חדרים", "רישיון רכב",
                     "stockbroker", "סוכן ביטוח", "משרד עורכי דין", "משרד בבית"]:
            with self.subTest(text=text):
                self.assertIsNone(brokerage_mention([text]))

    def test_evidence_keeps_long_texts_short_and_all_mentions(self):
        long = "דירה " * 50 + "ללא תיווך" + " יפה" * 50 + " רישיון תיווך מס' 4567"
        flag = brokerage_mention([long, "no broker", "no broker"])
        self.assertIn("ללא תיווך", flag.evidence)
        self.assertIn("4567", flag.evidence)
        self.assertEqual(flag.evidence.count("no broker"), 1)  # de-duplicated
        self.assertLessEqual(len(flag.evidence), 400)

    def test_nothing_and_junk(self):
        self.assertIsNone(brokerage_mention([]))
        self.assertIsNone(brokerage_mention([None, 5, ""]))  # type: ignore[list-item]


class TestRecurringCostsMention(unittest.TestCase):
    def test_the_qualifier_stays_in_the_evidence(self):
        # Cutting at the comma would drop exactly what decides the amount.
        for text in ["ועד בית 200, אחת לחודשיים", "ועד בית 100, כלול בשכירות", "לשותף: ועד בית 100",
                     "vaad bayit 1200, paid annually", "ארנונה 800 לחודשיים"]:
            with self.subTest(text=text):
                self.assertEqual(recurring_costs_mention([text]).evidence, text)

    def test_a_late_qualifier_in_a_medium_text_is_kept(self):
        text = ("ועד בית 200 ש\"ח, כולל ניקיון חדר מדרגות פעמיים בשבוע, גינון, תאורה בלובי ובחניון, "
                "ותחזוקת מעלית שבועית, משולם אחת לחודשיים")
        self.assertLessEqual(len(text), 160)
        # past the 90-character window that follows the keyword
        self.assertGreater(text.index("לחודשיים") - text.index("ועד בית") - len("ועד בית"), 90)
        self.assertEqual(recurring_costs_mention([text]).evidence, text)

    def test_a_qualifier_before_the_keyword_is_kept_and_windows_merge(self):
        text = ("דירה מקסימה ומוארת בקומה שנייה עם נוף פתוח לפארק, מטבח משודרג וחדר רחצה חדש לגמרי, "
                "קרוב לתחבורה ציבורית. בעל הבית משלם בעצמו את התשלומים הבאים: ועד בית 150 וגם ארנונה 400 לחודש")
        self.assertGreater(len(text), 160)
        evidence = recurring_costs_mention([text]).evidence
        self.assertIn("בעל הבית משלם", evidence)  # who pays decides what 150 means
        self.assertNotIn(" | ", evidence)  # the two mentions overlap: one piece
        self.assertNotIn("נוף פתוח", evidence)  # but only from the sentence start
        # Two mentions whose windows overlap but differ come out as one piece.
        filler = "דירה גדולה ומוארת עם מטבח משודרג ומרפסת שמש פונה לגינה ירוקה ושקטה "
        text = "ועד בית 150 לחודש " + filler + "ארנונה 400 לחודש " + filler * 2
        evidence = recurring_costs_mention([text]).evidence
        self.assertEqual((evidence.count("ועד בית"), evidence.count("ארנונה"), evidence.count(" | ")), (1, 1, 0))

    def test_no_cost_words_no_flag(self):
        self.assertIsNone(recurring_costs_mention(["דירה יפה, 3 חדרים, 4500 ש\"ח"]))


class TestPhase2EvalCases(unittest.TestCase):
    """The labeled cases Phase 2 is measured against. Here: the file is
    well formed, and every case is caught by its flag, so a reader always
    gets to see the words, whatever the parser made of them."""

    def setUp(self):
        self.cases = json.loads(EVAL.read_text(encoding="utf-8"))["cases"]

    def test_well_formed(self):
        self.assertGreaterEqual(len(self.cases), 20)
        for case in self.cases:
            self.assertEqual(set(case), {"field", "text", "expected", "why", "found_by"})
            self.assertIn(case["field"], {"listed_by", "vaad_bayit_monthly", "arnona_monthly"})

    def test_every_cost_case_is_flagged(self):
        for case in self.cases:
            if case["field"] != "listed_by":
                self.assertIsNotNone(recurring_costs_mention([case["text"]]), case["text"])

    def test_broker_flag_fires_exactly_when_a_broker_word_is_there(self):
        no_broker_word = {"לא מתווכחים על המחיר", "המחיר סופי, לא מתווכחים", "מתווכחים על המחיר", "Travel agency downstairs"}
        for case in self.cases:
            if case["field"] == "listed_by":
                self.assertEqual(brokerage_mention([case["text"]]) is None, case["text"] in no_broker_word, case["text"])


def baseline_accuracy() -> tuple[int, int]:
    """(correct, total) for the Phase 0 regex parsers on the eval cases --
    the number Phase 2's extractor has to beat. Not an assertion: the
    parsers are known to fail some of these; that's why they're here."""
    cases = json.loads(EVAL.read_text(encoding="utf-8"))["cases"]
    correct = 0
    for case in cases:
        if case["field"] == "listed_by":
            got = detect_listed_by([case["text"]])
            got = got.value if got is not None else None
        else:
            costs = parse_recurring_costs([case["text"]])
            got = getattr(costs, case["field"]) if costs is not None else None
        correct += got == case["expected"]
    return correct, len(cases)


if __name__ == "__main__":
    unittest.main()
