"""
v1.53: what the card test (v1.52) found, fixed, and more of Yad2's own fields read.

- A ticked parking box is "the building's or the flat's own", a lower bound: a check for someone
  who needs their own space, never a reason to hide (it hid 125 listings over batches 1-8).
- "חניות: ללא" (no box, no count) and a text with no word for parking: no space comes with the
  flat (owner ruling: posters tick it when there is one). Street parking may still exist.
- Yad2 shows "מקלט במרחק N מ'" exactly when neither the safe-room nor the shelter box is ticked
  (checked on live pages, Oct 29: "נכס עם ממ"ד" when the safe-room box is, "מקלט בבניין" when the
  shelter box is). With that and no word in the text: no safe room or building shelter.
- An agency's account that says "ללא דמי תיווך": the card says both.
- Yad2's arnona ("ארנונה (לחודשיים)") and vaad ("ועד בית (לחודש)") fields, and the poster's
  furniture list ("פירוט ריהוט"), read like the description.
- Rules (step 2): phrase families found in 160 new, unlabeled listings (Tel Aviv, Ramat Gan,
  Rishon, Herzliya; Oct 29), each checked against the 640 labeled ones (still 0 wrong, 0 hidden).
  A plain parking mention ("יש חניה", "2 חניות", "חניה תת קרקעית") is "the building's or your own",
  the same lower bound as Yad2's box.
"""

import json
import unittest
from pathlib import Path

from rental_matcher.extraction.rules import answer, combine
from rental_matcher.pipeline import build_listing
from rental_matcher.scoring import PreferenceSet, score_listing

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")


def _prefs(**parking):
    p = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
    for x in p["preferences"]:
        if x["name"] == "parking":
            x.clear()
            x.update({"name": "parking", "label": "Parking", "field": "signal:parking_level", "relevance": 10, **parking})
    return PreferenceSet.model_validate(p)


OWN = _prefs(kind="at_least", limit=3)
BUILDING = _prefs(kind="at_least", limit=2)


def _x(**over):
    base = {"id": "t1", "adType": "private", "price": 4300, "floor": 2, "city": "בת ים", "shelterDistance": 150,
            "additionalDetails": {"roomsCount": 3, "squareMeterBuild": 70, "property": {"text": "דירה"}},
            "inProperty": {"includeAirconditioner": True, "includeSecurityRoom": True},
            "description": "דירת 3 חדרים, מעלית"}
    return {**base, **over}


def _score(x, prefs=PREFS):
    return score_listing(build_listing(x, prefs), prefs)


class TestParking(unittest.TestCase):
    def test_a_ticked_box_is_a_check_for_someone_who_needs_their_own(self):
        x = _x(inProperty={**_x()["inProperty"], "includeParking": True})
        s = _score(x, OWN)
        self.assertFalse(s.excluded)
        self.assertTrue(any("say whose" in c for c in s.checks))
        self.assertFalse(_score(x, BUILDING).excluded)  # and it's enough for the building's

    def test_the_text_says_whose(self):
        tick = {**_x()["inProperty"], "includeParking": True}
        self.assertFalse(_score(_x(inProperty=tick, description="דירת 3 חדרים, חניה בטאבו"), OWN).excluded)
        s = _score(_x(inProperty=tick, description="דירת 3 חדרים, חניה משותפת לדיירי הבניין"), OWN)
        self.assertTrue(s.excluded)  # the building's, said in words: below "your own"

    def test_no_box_and_no_word_is_no_space(self):
        s = _score(_x(), BUILDING)
        self.assertTrue(s.excluded)
        self.assertTrue(any("no parking space" in r for r in s.exclusion_reasons))
        self.assertFalse(_score(_x(), PREFS).excluded)  # street parking may still exist: the owner's "at least street"

    def test_any_word_for_parking_keeps_the_rule_out(self):
        # read or not: a mention the rules can't classify is a check, not "no space"
        for text in ("דירת 3 חדרים, יש חניה", "דירת 3 חדרים, חנייה לפי תור", "דירת 3 חדרים עם מקום לרכב"):
            self.assertFalse(_score(_x(description=text), BUILDING).excluded, text)

    def test_only_yad2_with_its_form(self):
        self.assertFalse(_score(_x(inProperty={}), BUILDING).excluded)


class TestShelter(unittest.TestCase):
    NO_BOX = {"includeAirconditioner": True}

    def test_the_distance_bubble_and_no_word_is_no_shelter(self):
        s = _score(_x(inProperty=self.NO_BOX))
        self.assertTrue(s.excluded)
        l = build_listing(_x(inProperty=self.NO_BOX), PREFS)
        self.assertIs(l.signals["protected_space"].value, False)
        self.assertEqual(l.signals["public_shelter_m"].value, 150)

    def test_the_text_wins(self):
        for text in ("דירת 3 חדרים, הדירה כוללת ממד", "דירת 3 חדרים, מקלט בבניין", "דירת 3 חדרים, ליד המקלט הציבורי"):
            l = build_listing(_x(inProperty=self.NO_BOX, description=text), PREFS)
            self.assertIsNot((l.signals.get("protected_space") or object()).__dict__.get("value", None), False, text)

    def test_a_box_wins(self):
        for box in ("includeSecurityRoom", "includeBuildingShelter", "includeFloorShelter"):
            self.assertIs(build_listing(_x(inProperty={box: True}), PREFS).signals["protected_space"].value, True, box)

    def test_only_when_the_page_showed_the_distance(self):
        x = _x(inProperty=self.NO_BOX)
        del x["shelterDistance"]
        self.assertNotIn("protected_space", build_listing(x, PREFS).signals)


class TestBrokerAndFees(unittest.TestCase):
    def test_an_agency_that_waives_the_fee(self):
        l = build_listing(_x(adType="commercial", description="דירת 3 חדרים, ללא דמי תיווך"), PREFS)
        self.assertEqual(l.listed_by.value, "agency")
        self.assertIs(l.signals["no_broker_fee"].value, True)

    def test_yad2s_fee_fields(self):
        l = build_listing(_x(propertyTax=500, houseCommittee=300), PREFS)
        self.assertEqual((l.recurring_costs.arnona_monthly, l.recurring_costs.vaad_bayit_monthly), (250, 300))
        # a token "1" is no amount; the text fills in what the fields don't say
        l = build_listing(_x(propertyTax=1, description="דירת 3 חדרים, ועד בית 120 ש\"ח לחודש"), PREFS)
        self.assertEqual((l.recurring_costs.arnona_monthly, l.recurring_costs.vaad_bayit_monthly), (None, 120))
        # the field and the text disagree: a range (the owner, v1.59), not a guess
        l = build_listing(_x(houseCommittee=300, description="דירת 3 חדרים, ועד בית 150 ש\"ח לחודש"), PREFS)
        self.assertEqual((l.recurring_costs.vaad_bayit_monthly, l.recurring_costs.vaad_bayit_monthly_max), (150, 300))

    def test_the_posters_furniture_list_is_read(self):
        l = build_listing(_x(furnitureInfo="מקרר ומכונת כביסה"), PREFS)
        self.assertEqual(l.signals["furniture"].value, ["fridge", "washer"])


class TestTheCard(unittest.TestCase):
    def test_the_bubbles(self):
        from rental_matcher.server import _feature_keys, _features
        x = build_listing(_x(inProperty={"includeAirconditioner": True, "includeParking": True}, adType="commercial",
                             description="דירת 3 חדרים, ללא דמי תיווך"), PREFS)
        s = score_listing(x, PREFS)
        keys = {f["key"] for f in _feature_keys(_features(s, x, PREFS), s, x, PREFS)}
        self.assertTrue({"parking_any", "public_shelter", "no_building_shelter", "agency_no_fee"} <= keys, keys)
        self.assertNotIn("parking_building", keys)


# (question, text, what the rules read: an answer, ("items", [...]) or ("building", "or"))
CENSUS = [
    ("protected_space", 'בנוסף ממ"ק ענק ל2 דירות', "yes"),  # a floor's safe room
    ("protected_space", "מקלט מעולה 100 מ' מהדירה", "unclear"),  # was "yes": 100 m away isn't the building's
    ("broker", "פרטי לא ללא תווך דירה להשכרה", "no_broker"),  # the typo
    ("broker", "מפרטי ללא תווך!", "no_broker"),
    ("broker", "שיקים ותשלום תיווך. הכניסה מיידית", "broker"),
    ("broker", "פאר תיווך נכסים מציגה להשכרה", "broker"),
    ("broker", "[name] | מס' רישיון 318813", "broker"),
    ("broker", "תיווך השכרה, גג/ פנטהאוז, קומה 3, הרצליה", "broker"),
    ("parking", "חנייה משותפת (9 חניות ל-12 דיירים).", "building"),
    ("parking", "חניה משותפת לבנין וניתן למצוא חניה בקלות ברחוב מקביל.", "building"),
    ("parking", "חנייה באיזור גם בכחול לבן וגם באפור בחינם", "street"),
    ("parking", "ברח' חניה, מ-17.00 רק לתושבי הרחוב.", "unclear"),  # not "a space": the street's, maybe
    ("parking", "חניה ללא תשלום", "unclear"),  # free: maybe the street's
    ("room_share", "מתאימה לשני שותפים, או לבני זוג.", "no"),
    ("vaad_bayit", "מחיר כולל ארנונה מיים וועד הוט אינטרנט .", "not_stated"),  # a bare "ועד" may be "and until": left
    ("vaad_bayit", "שכר הדירה כולל ארנונה וועד בניין, והחשבונות נמוכים", "included"),
    ("arnona", "שכר הדירה כולל ארנונה וגז.", "included"),
    ("furniture", "*כיום הבית ריק וללא ריהוט*", ("items", ["says_unfurnished"])),
    ("furniture", "יש את כל הריהוט והציוד", ("items", ["says_furnished"])),
    ("furniture", "5 חד' מרוהטת ושמורה עם חצר קטנה", ("items", ["says_furnished"])),
    ("furniture", "1.5 חדרים בקומה א' מרוהטת : מיטה זוגית ומזרון", ("items", ["bed", "says_furnished"])),
    ("furniture", "מטבח מאובזר.", ("items", ["says_equipped"])),
    ("furniture", "ריהוט חדש מוצרי חשמל חדשים", ("items", ["says_equipped", "says_furnished"])),
    ("furniture", "מקרר מיקרו, מיבש, 2 טלויזיות, שידת מגירות", ("items", ["cabinet", "dryer", "fridge", "microwave", "tv"])),
]
PLAIN = ["יש חניה ומעלית", "2 חניות + מחסן.", "מחסן וחניה.", "ממ\"ד. חנייה רגילה. מעלית .", "&שתי חניות תת קרקעיות טוריות",
         "חניה תת קרקעית רגילה. מיקום מרכזי"]


class TestCensusPhrasings(unittest.TestCase):
    def test_each(self):
        for q, text, want in CENSUS:
            with self.subTest(q=q, text=text):
                got = answer(text).get(q) or {"answer": "not_stated"}
                if isinstance(want, tuple):
                    self.assertEqual((got["answer"], sorted(got.get("items") or [])), want)
                else:
                    self.assertEqual(got["answer"], want, got)

    def test_a_plain_parking_mention_is_the_buildings_or_your_own(self):
        for text in PLAIN:
            got = answer(text)["parking"]
            self.assertEqual((got["answer"], got.get("or")), ("building", ["deeded"]), text)

    def test_the_model_picking_one_option_keeps_the_range(self):
        r = answer("2 חניות + מחסן.")
        got = combine(r, {"parking": {"answer": "deeded", "evidence": "2 חניות"}})["parking"]
        self.assertEqual((got["answer"], got.get("or")), ("building", ["deeded"]))
        got = combine(r, {"parking": {"answer": "street", "evidence": "2 חניות"}})["parking"]
        self.assertEqual(got["answer"], "unclear")  # outside the range: a check

    def test_on_the_card_a_check_for_your_own_never_a_reason_to_hide(self):
        x = _x(inProperty={"includeSecurityRoom": True}, description="דירת 3 חדרים, יש חניה ומעלית")
        l = build_listing(x, OWN)
        self.assertEqual((l.signals["parking_level"].value, l.signals["parking_at_least"].value), (2.0, True))
        s = _score(x, OWN)
        self.assertFalse(s.excluded)
        self.assertTrue(any("say whose" in c for c in s.checks))
        self.assertFalse(_score(x, BUILDING).excluded)
        self.assertFalse(any("say whose" in c for c in _score(x, BUILDING).checks))  # enough for "the building's"


EVAL = ROOT / "tests" / "eval"
B9 = ROOT / "tests" / "fixtures" / "yad2_holdout9_2026-10-29"


def _b9(run):
    from rental_matcher.extraction.evaluate import load
    gold = load(EVAL / "holdout9" / "gold.json")["gold"]
    ans = {k: v for k, v in load(EVAL / "runs" / run).items() if not k.startswith("_")}
    return gold, ans


class TestHeldOutBatch9(unittest.TestCase):
    """147 listings no rule had seen (Netanya, Rehovot, Jerusalem, Beer Sheva; Oct 29), read after
    v1.53 was frozen at e9c9872; two blind labelers (1589/1617 exact). Measured, not fitted: pinned."""

    def test_the_texts_are_the_saved_descriptions_and_furniture_lists(self):
        texts = json.loads((EVAL / "holdout9" / "texts.json").read_text(encoding="utf-8"))
        self.assertEqual(len(texts), 147)
        for f in sorted(B9.glob("*.json")):
            x = json.loads(f.read_text(encoding="utf-8"))
            info = (x.get("furnitureInfo") or "").strip()
            self.assertEqual(texts[x["id"]], x["description"] + (f"\n\nפירוט ריהוט: {info}" if info else ""), x["id"])

    def test_the_frozen_run_is_what_the_frozen_rules_say(self):
        # v1.55: the rules changed after batch 9 was measured (Owner ruling, Oct 30: learn from every misreading),
        # so the frozen run is now the record of what v1.53 said, kept as it was. What the rules say on
        # batch 9 today is in tests/test_v155.py (lessons.json), and batch 9 no longer counts as held out.
        gold, ans = _b9("2026-10-29_rules_v153_frozen_on_holdout9.json")
        texts = json.loads((EVAL / "holdout9" / "texts.json").read_text(encoding="utf-8"))
        self.assertEqual(set(ans), set(texts))
        self.assertEqual(ans["e4ywfxdp"]["furniture"]["items"][-1], "tv")  # the v1.53 misreading, on record
        self.assertNotEqual({k: answer(t) for k, t in texts.items()}, ans)

    def test_the_text_test_rules_by_version(self):
        from rental_matcher.extraction.evaluate import score, settled_coverage, wrongly_hidden
        want = {"2026-10-29_rules_v149_on_holdout9.json": (5, 300, 297),
                "2026-10-29_rules_v151_on_holdout9.json": (4, 316, 312),
                "2026-10-29_rules_v153_frozen_on_holdout9.json": (3, 346, 319)}
        for run, (wrong, right, settled) in want.items():
            gold, ans = _b9(run)
            t = score(gold, ans)["ALL"]
            got, of = settled_coverage(gold, ans)["ALL"]
            self.assertEqual((t.wrong, t.correct_definite, t.definite_gold, got, of), (wrong, right, 403, settled, 372), run)
            self.assertEqual({q: {r: len(v) for r, v in by.items()} for q, by in wrongly_hidden(gold, ans).items()},
                             {"apartment_type": {"is_not unit": 2}}, run)  # the text alone; Yad2's property type settles it

    def test_the_card(self):
        from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
        from rental_matcher.extraction.evaluate import score, settled_coverage, wrongly_hidden
        gold, ans = _b9("2026-10-29_rules_v153_frozen_on_holdout9.json")
        ex = load_extracts(B9)
        tg = {k: v for k, v in gold.items() if k in ex}  # 2 listings with no price aren't shown
        cg, ca, _ = card_score_inputs(ex, tg, {k: combine(ans[k], {}) for k in tg}, PREFS)
        t = score(cg, ca)["ALL"]
        self.assertEqual((len(cg), t.wrong, t.correct_definite, t.definite_gold), (145, 1, 892, 938))  # v1.54: +1 A/C fact from the Tornado box (was 891/937)
        self.assertEqual(settled_coverage(cg, ca)["ALL"], (831, 876))  # v1.54: +1 settled A/C fact from the Tornado box (94.9% either way)
        self.assertEqual(wrongly_hidden(cg, ca), {})
        self.assertEqual([w.split(":")[0] for w in t.wrong_items], ["e4ywfxdp/furniture"])  # "מזנון טלוויזיה" read as a TV


if __name__ == "__main__":
    unittest.main()
