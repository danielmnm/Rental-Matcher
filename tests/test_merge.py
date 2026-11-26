"""Tests for merging structured (Yad2) and text signals."""

import unittest

from rental_matcher.extraction.merge import merge, text_signals
from rental_matcher.schema import ExtractedBy, Signal, SignalStatus


def _yes(value=True, evidence="Yad2: ticked"):
    return Signal(status=SignalStatus.CONFIRMED, value=value, evidence=evidence, extracted_by=ExtractedBy.RULE)


class TestTextSignals(unittest.TestCase):
    def test_answers_map_to_signal_values(self):
        s = text_signals({"elevator": {"answer": "no", "evidence": "ללא מעלית"},
                          "parking": {"answer": "street", "evidence": "חניה בשפע"},
                          "room_share": {"answer": "no", "evidence": "דירת 3 חדרים"},
                          "balcony": {"answer": "service_only", "evidence": "מרפסת שירות"},
                          "furniture": {"answer": "unclear"}, "broker": {"answer": "no_broker"},
                          "air_conditioning": {"answer": "not_stated"}})
        self.assertEqual({k: v.value for k, v in s.items()},
                         {"elevator": False, "parking_level": 1.0, "roommate_listing": False, "balcony": False, "furniture": None})
        self.assertTrue(all(v.extracted_by == ExtractedBy.LLM and v.evidence.startswith("text") for v in s.values()))


class TestMerge(unittest.TestCase):
    def test_agreement_confirms_with_both_as_evidence(self):
        m = merge({"elevator": _yes()}, {"elevator": _yes(evidence="text: מעלית")})
        self.assertEqual((m["elevator"].status, m["elevator"].value), (SignalStatus.CONFIRMED, True))
        self.assertIn("text: מעלית", m["elevator"].evidence)

    def test_disagreement_is_a_conflict_not_a_pick(self):
        m = merge({"elevator": _yes()}, {"elevator": _yes(False, "text: ללא מעלית")})
        self.assertEqual((m["elevator"].status, m["elevator"].value), (SignalStatus.CONFLICTING, None))
        self.assertIn("ללא מעלית", m["elevator"].evidence)

    def test_text_fills_what_structure_leaves_unknown(self):
        m = merge({"air_conditioning": _yes()}, {"protected_space": _yes(evidence="text: מקלט צמוד לבניין")})
        self.assertEqual(set(m), {"air_conditioning", "protected_space"})

    def test_parking_text_refines_a_lower_bound_or_conflicts(self):
        lower = {"parking_level": _yes(2.0)}
        self.assertEqual(merge(lower, {"parking_level": _yes(3.0, "text: חניה צמודה")})["parking_level"].value, 3.0)
        self.assertEqual(merge(lower, {"parking_level": _yes(2.0, "text: חנייה בבניין")})["parking_level"].value, 2.0)
        # v1.56 (owner ruling): a text that places it on the street wins over the ticked box; "בשפע" alone doesn't
        street = merge(lower, {"parking_level": _yes(1.0, "text: חניה ברחוב")})["parking_level"]
        self.assertEqual((street.status, street.value), (SignalStatus.CONFIRMED, 1.0))
        self.assertIn("ticked", street.evidence)
        self.assertEqual(merge(lower, {"parking_level": _yes(1.0, "text: חניה בשפע")})["parking_level"].status,
                         SignalStatus.CONFLICTING)

    def test_inputs_are_not_mutated(self):
        s = {"elevator": _yes()}
        merge(s, {"elevator": _yes(False, "text: no")})
        self.assertEqual(s["elevator"].value, True)


if __name__ == "__main__":
    unittest.main()


class TestUnclearAndWhoReadIt(unittest.TestCase):
    def test_unclear_is_unconfirmed_with_the_words(self):
        s = text_signals({"elevator": {"answer": "unclear", "evidence": "יש הכנה למעלית", "source": "rules"}})
        self.assertEqual((s["elevator"].status, s["elevator"].value), (SignalStatus.UNCONFIRMED, None))
        self.assertIn("יש הכנה למעלית", s["elevator"].evidence)

    def test_source_sets_extracted_by(self):
        s = text_signals({"elevator": {"answer": "no", "evidence": "ללא מעלית", "source": "both"},
                          "balcony": {"answer": "yes", "evidence": "מרפסת", "source": "model"},
                          "air_conditioning": {"answer": "yes", "evidence": "מזגנים", "source": "rules"}})
        self.assertEqual({k: v.extracted_by for k, v in s.items()},
                         {"elevator": ExtractedBy.RULE, "balcony": ExtractedBy.LLM, "air_conditioning": ExtractedBy.RULE})

    def test_unclear_text_never_unsays_a_ticked_box(self):
        unclear = text_signals({"elevator": {"answer": "unclear", "evidence": "מעלית?"}})
        m = merge({"elevator": _yes()}, unclear)
        self.assertEqual((m["elevator"].status, m["elevator"].value), (SignalStatus.CONFIRMED, True))
        m = merge({"parking_level": _yes(2.0)}, text_signals({"parking": {"answer": "unclear", "evidence": "חניה"}}))
        self.assertEqual(m["parking_level"].value, 2.0)


class TestFurnitureAndFan(unittest.TestCase):
    def test_a_list_is_confirmed_with_its_items(self):
        s = text_signals({"furniture": {"answer": "items", "items": ["sofa", "fridge"], "evidence": "ספה ומקרר", "source": "rules"},
                          "apartment_type": {"answer": "roof", "evidence": "דירת גג", "source": "rules"}})
        self.assertEqual((s["furniture"].status, s["furniture"].value), (SignalStatus.CONFIRMED, ["fridge", "sofa"]))
        self.assertEqual(s["apartment_type"].value, "roof")

    def test_the_yad2_box_alone_is_a_claim_not_a_list(self):
        m = merge({"furniture_box": _yes(evidence="Yad2: includeFurniture ticked")}, {})
        self.assertEqual((m["furniture"].status, m["furniture"].value), (SignalStatus.UNCONFIRMED, None))
        self.assertIn("the text doesn't say what's there", m["furniture"].evidence)

    def test_next_to_a_text_list_the_box_is_only_noted(self):
        t = text_signals({"furniture": {"answer": "items", "items": ["fridge"], "evidence": "מקרר", "source": "rules"}})
        m = merge({"furniture_box": _yes(evidence="Yad2: includeFurniture ticked")}, t)
        self.assertEqual((m["furniture"].status, m["furniture"].value), (SignalStatus.CONFIRMED, ["fridge"]))
        self.assertIn("includeFurniture", m["furniture"].evidence)

    def test_a_fan_note_becomes_a_fan_signal(self):
        s = text_signals({"air_conditioning": {"answer": "yes", "evidence": "מזגן", "source": "rules", "note": "+fan: מזגן + מאוורר"}})
        self.assertEqual((s["air_conditioning"].value, s["fan"].value, s["fan"].evidence), (True, True, "text: מזגן + מאוורר"))
