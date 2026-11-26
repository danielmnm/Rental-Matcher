"""
v1.52: the accuracy test scores what the CARD shows (Yad2's own form first,
then the text), not only the text reader. Owner ruling, Oct 29: "our job is to take
the information from these sites accurately with all details provided".

Only the measurement changed: the product builds cards exactly as before
(pipeline.build_listing's new `text_answers` is for the test, and its default
is the old path). What the new test found is pinned here, to be fixed in step 2.
"""

import json
import unittest
from pathlib import Path

from rental_matcher.extraction.card_eval import box_facts, card_answers, card_gold, card_score_inputs, load_extracts
from rental_matcher.extraction.evaluate import gold_set, load, same_questions, score, settled_coverage, wrongly_hidden
from rental_matcher.extraction.rules import combine
from rental_matcher.scoring import PreferenceSet

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "eval"
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


def _x(**over):
    base = {"id": "t1", "adType": "private", "price": 4800, "rooms": 3, "property": "דירה", "inProperty": {},
            "description": "דירת 3 חדרים"}
    return {**base, **over}


def _g(answer, acceptable=None, evidence=""):
    return {"answer": answer, "acceptable": acceptable or [answer], "evidence": evidence}


class TestWhatTheListingProvides(unittest.TestCase):
    def test_a_box_adds_what_the_text_leaves_out(self):
        gold, how = card_gold({"air_conditioning": _g("not_stated")}, _x(inProperty={"includeAirconditioner": True}))
        self.assertEqual((gold["air_conditioning"]["acceptable"], how["air_conditioning"]), (["yes"], "added"))

    def test_an_unticked_box_says_nothing(self):
        gold, how = card_gold({"elevator": _g("not_stated")}, _x(inProperty={"includeElevator": False}))
        self.assertEqual((gold["elevator"]["acceptable"], how), (["not_stated"], {}))

    def test_a_ticked_parking_box_is_the_buildings_or_the_flats_own(self):
        gold, _ = card_gold({"parking": _g("not_stated")}, _x(inProperty={"includeParking": True}))
        self.assertEqual(gold["parking"]["acceptable"], ["building", "deeded"])
        # ... and the text can say which
        gold, how = card_gold({"parking": _g("deeded", evidence="חניה בטאבו")}, _x(inProperty={"includeParking": True}))
        self.assertEqual((gold["parking"]["acceptable"], how["parking"]), (["deeded"], "narrowed"))

    def test_a_listing_that_contradicts_itself_needs_a_check(self):
        # the box says a balcony, the text a service balcony only; parking ticked, the text street parking only
        gold, how = card_gold({"balcony": _g("service_only")}, _x(inProperty={"includeBalcony": True}))
        self.assertEqual((gold["balcony"]["acceptable"], how["balcony"]), (["unclear"], "contradicts"))
        gold, how = card_gold({"parking": _g("street")}, _x(inProperty={"includeParking": True}))
        self.assertEqual(how["parking"], "contradicts")

    def test_the_account_type_is_who_posted(self):
        gold, how = card_gold({"broker": _g("not_stated")}, _x(adType="commercial"))
        self.assertEqual((gold["broker"]["acceptable"], how["broker"]), (["broker"], "added"))
        gold, _ = card_gold({"broker": _g("not_stated")}, _x(adType="private"))
        self.assertEqual(gold["broker"]["acceptable"], ["no_broker"])
        # a business account that says "ללא דמי תיווך": the fee is the text's word (or a check)
        gold, how = card_gold({"broker": _g("no_broker", evidence="ללא דמי תיווך")}, _x(adType="commercial"))
        self.assertEqual((sorted(gold["broker"]["acceptable"]), how["broker"]), (["broker", "no_broker", "unclear"], "differs"))  # v1.53: who posted it, and no fee: both true

    def test_one_property_type_and_another_can_both_be_true(self):
        gold, how = card_gold({"apartment_type": _g("roof", evidence="דופלקס גג")}, _x(property="דופלקס"))
        self.assertEqual(how["apartment_type"], "differs")
        self.assertTrue({"roof", "duplex"} <= set(gold["apartment_type"]["acceptable"]))

    def test_the_saved_shape_is_read_like_the_live_one(self):
        self.assertEqual(box_facts(_x(property="דירת גן"))["apartment_type"], {"garden"})


class TestTheCardIsThePipelines(unittest.TestCase):
    def test_card_answers_come_from_build_listing(self):
        x = _x(inProperty={"includeAirconditioner": True, "includeParking": True}, adType="commercial",
               description="דירת 3 חדרים, חניה בטאבו, ללא מעלית")
        text = combine({"parking": {"answer": "deeded", "evidence": "חניה בטאבו"},
                        "elevator": {"answer": "no", "evidence": "ללא מעלית"}}, {})
        got = card_answers(x, text, PREFS)
        self.assertEqual(got["air_conditioning"]["answer"], "yes")  # the box
        self.assertEqual(got["parking"]["answer"], "deeded")  # the text narrows the box
        self.assertEqual(got["elevator"]["answer"], "no")  # the text
        self.assertEqual(got["broker"]["answer"], "broker")  # the account

    def test_the_product_path_is_unchanged_without_text_answers(self):
        from rental_matcher.pipeline import build_listing
        x = _x(description="דירת 3 חדרים, ללא מעלית")
        a = build_listing(x, PREFS).signals["elevator"]
        self.assertEqual((a.status.value, a.value), ("confirmed", False))


def _held(fixtures, run):
    ids = {f.stem for f in (ROOT / "tests" / "fixtures" / fixtures).glob("*.json")}
    frozen = load(EVAL / "runs" / run)
    tg = {k: v for k, v in same_questions(gold_set(), frozen).items() if k in ids}
    return card_score_inputs(load_extracts(ROOT / "tests" / "fixtures" / fixtures), tg, {k: combine(frozen[k], {}) for k in tg}, PREFS)


class TestHeldOutCards(unittest.TestCase):
    """Batches 7 and 8 again, with the rules frozen for each, scored on the card.
    Text test then: batch 7 7 wrong at 84%, batch 8 9 wrong at 80%."""

    def test_batch_7(self):
        cg, ca, _ = _held("yad2_holdout7_2026-10-27", "2026-10-27_rules_v142_frozen_on_holdout7.json")
        t = score(cg, ca)["ALL"]
        # v1.52: 10 wrong, 775/809, 23 hidden; v1.53's card fixes (a ticked parking box is "the
        # building's or your own"; Yad2's fee fields): what's left is the frozen rules' own misreadings
        self.assertEqual((len(cg), t.wrong, t.correct_definite, t.definite_gold), (187, 7, 778, 814))  # v1.54: +4 A/C facts from the Tornado box (מזגן טורנדו), all on the card
        h = wrongly_hidden(cg, ca)
        self.assertEqual({q: {r: len(v) for r, v in by.items()} for q, by in h.items()},
                         {"parking": {"at_least 2.0": 2}, "room_share": {"value False": 1}})

    def test_batch_8(self):
        cg, ca, how = _held("yad2_holdout8_2026-10-28", "2026-10-28_rules_v149_frozen_on_holdout8.json")
        t = score(cg, ca)["ALL"]
        # v1.52: 23 wrong, 897/955, 60 hidden (a ticked parking box read as "the building's" hid them from
        # anyone who needs their own; 7 agency accounts that say "no fee"; 9 "בטאבו" under the box).
        # v1.53 fixed all three; what's left are the frozen rules' own misreadings.
        self.assertEqual((len(cg), t.wrong, t.correct_definite, t.definite_gold), (175, 7, 902, 960))  # v1.54: +1 A/C fact from the Tornado box; v1.56: +1 street parking (the text beats the box)
        got, of = settled_coverage(cg, ca)["ALL"]
        self.assertEqual((got, of), (851, 909))  # v1.54: +1 settled A/C fact from the Tornado box; v1.56: +1 street parking
        self.assertEqual({q: {r: len(v) for r, v in by.items()} for q, by in wrongly_hidden(cg, ca).items()},
                         {"parking": {"at_least 3.0": 1}})  # vryeiy5h: the frozen rules' "\n\nבבניין"
        added = sum(1 for by in how.values() for w in by.values() if w == "added")
        self.assertEqual(added, 464)  # the boxes added most of what the card knows (v1.54: +1, the Tornado box)
        wrong = sorted(w.split(":")[0] for w in t.wrong_items)
        self.assertEqual(sorted(w.split("/")[1] for w in wrong), ["apartment_type"] * 2 + ["furniture"] * 5)


if __name__ == "__main__":
    unittest.main()
