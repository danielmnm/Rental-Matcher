"""v1.39: what the first test search let through. Room shares in new words, units in someone's
home, the ground floor under a wrong floor field, and short stays.

The phrases are from that search's exported listings: in-sample from here on, not a held-out
measurement."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rental_matcher.extraction.rules import ground_level, housing_unit, room_share, short_lease
from rental_matcher.pipeline import build_listing
from rental_matcher.scoring import Preference, PreferenceSet, score_listing
from rental_matcher.setup import CATALOG

ROOT = Path(__file__).resolve().parents[1]
WHEN = datetime(2026, 10, 26, tzinfo=timezone.utc)


def _x(**over):
    base = {"id": "t1", "adType": "private", "price": 4800, "floor": 2, "city": "תל אביב יפו", "neighborhood": "יד אליהו",
            "street": "דרך ההגנה", "additionalDetails": {"roomsCount": 2, "squareMeterBuild": 50, "property": {"text": "דירה"}},
            "inProperty": {"includeAirconditioner": True}, "description": "דירת 2 חדרים, קומה 2, מרפסת"}
    base.update(over)
    return base


def _ans(a):
    return a and a["answer"]


class TestRoomShare(unittest.TestCase):
    def test_new_words_for_a_room(self):
        for text in ("מתפנים שני חדרים בדירת 3 שותפים בלב העיר!!",
                     "סאבלט לטווח הארוך ! / בדירה יש עוד שותף בן 24",
                     "נשארים שותף ושותפה מקסימים",
                     "יש שותפה מקסימה שנשארת"):
            self.assertEqual(_ans(room_share(text)), "yes", text)

    def test_whole_flats_stay_whole(self):
        for text in ("מתפנה דירת 2 חדרים", "דירה 3 חדרים מתאימה לשותפים", "דירת 3 חדרים מתפנה ב1.1"):
            self.assertEqual(_ans(room_share(text)), "no", text)
        self.assertIsNone(room_share("חניה בחניון משותף לבניין"))


class TestHousingUnit(unittest.TestCase):
    def test_units_and_flats_in_a_house(self):
        for text in ("יחידת דיור, אם חצר משותפת.", "קומה 1 מתוך 1 בבית פרטי בשכונת כפיר",
                     "קומפלקס דו קומתי ייחודי, עם 5 יחידות בגדלים שונים", "דירת 2 חדרים מחולקת. שופצה לאחרונה",
                     "בעלי הבית גרים בקומה למעלה"):
            self.assertEqual(_ans(housing_unit(text)), "yes", text)

    def test_denied_or_a_layout(self):
        self.assertEqual(_ans(housing_unit("39מ\"ר. (לא מחולקת). קומת קרקע")), "no")
        self.assertEqual(_ans(housing_unit("שקטה ולא מפוצלת ברח' תקוע")), "no")
        self.assertIsNone(housing_unit("הדירה משופצת ומחולקת בצורה מדהימה"))  # its rooms are laid out well
        self.assertIsNone(housing_unit("בית פרטי להשכרה 5 חדרים"))  # the whole house

    def test_the_signal(self):
        sig = lambda **o: build_listing(_x(**o), PREFS, pulled_at=WHEN).signals.get("housing_unit")
        self.assertIs(sig(additionalDetails={"roomsCount": 2, "property": {"text": "יחידת דיור"}}).value, True)
        self.assertIs(sig(description="דירת 2 חדרים בבית פרטי").value, True)  # the text beats Yad2's default "דירה"
        plain = sig()
        self.assertIs(plain.value, False)
        self.assertIn("listed as דירה", plain.evidence)
        self.assertIsNone(sig(additionalDetails={"roomsCount": 2}))  # no kind given, nothing said: unknown


class TestGroundLevel(unittest.TestCase):
    def test_said_outright(self):
        self.assertEqual(_ans(ground_level("39מ\"ר. קומת קרקע מסורגת. 1 חדרים")), "ground")
        self.assertEqual(_ans(ground_level("השכרה, דירת גן, קומה כניסה")), "ground")
        self.assertEqual(_ans(ground_level("הדיקה חצי קומה מתחת לאדמה יש חלונות גדולים")), "below")

    def test_not_the_flat(self):
        for text in ("מקלט מצויין בקומת קרקע", "ממד קומתי בקומת הקרקע", "קומת קרקע- חניה פרטית, סלון", "קומה א מעל קומת עמודים",
                     "קומה ראשונה מעל קומת קרקע"):
            self.assertIsNone(ground_level(text), text)

    def test_the_floor_follows(self):
        floor = lambda **o: build_listing(_x(**o), PREFS, pulled_at=WHEN).floor
        self.assertEqual(floor(floor=1, description="דירה מתוקה, קומת קרקע מסורגת"), 0)
        self.assertEqual(floor(floor=1, additionalDetails={"roomsCount": 2, "property": {"text": "מרתף/ פרטר"}}), -1)
        self.assertEqual(floor(floor=1, additionalDetails={"roomsCount": 2, "property": {"text": "דירת גן"}}), 0)
        self.assertEqual(floor(floor=3), 3)
        house = {"roomsCount": 5, "property": {"text": "בית פרטי/ קוטג'"}}
        self.assertEqual(floor(floor=1, additionalDetails=house, description="קוטג', קומת קרקע הכל במפלס אחד"), 1)


class TestShortLease(unittest.TestCase):
    def test_short(self):
        for text in ("מוצעת להשכרה ל4 חודשים בלבד.", "דירה נעימה להשכרה לטווח קצר (בעוד שנה מיועדת לתמ\"א)",
                     "הדירה להשכרה לטווח קצר עד שנה עקב פינוי בינוי", "סאבלט עד סוף ינואר"):
            self.assertEqual(_ans(short_lease(text)), "yes", text)

    def test_not_short(self):
        for text in ("5000 ש\"ח לחודש", "סאבלט לטווח הארוך !", "פיקדון של 3 חודשים", "חוזה לשנה עם אופציה", "לטווח ארוך"):
            self.assertIsNone(short_lease(text), text)

    def test_the_signal_says_what_the_text_says(self):
        s = build_listing(_x(description="להשכרה ל4 חודשים בלבד"), PREFS, pulled_at=WHEN).signals["short_lease"]
        self.assertEqual((s.value, s.evidence), (True, "ל4 חודשים"))
        self.assertIs(build_listing(_x(), PREFS, pulled_at=WHEN).signals["short_lease"].value, False)


class TestCriteria(unittest.TestCase):
    def test_in_the_catalog(self):
        by = {c["name"]: c for c in CATALOG}
        for name, field in (("no_housing_unit", "signal:housing_unit"), ("no_short_lease", "signal:short_lease")):
            entry = {k: v for k, v in by[name].items() if k != "group"}
            p = Preference.model_validate(entry)
            self.assertEqual((p.field, p.kind, p.wants), (field, "yes_no", False))

    def test_must_haves_hide_them(self):
        must = [{"name": "no_housing_unit", "label": "Not a unit", "field": "signal:housing_unit", "kind": "yes_no",
                 "relevance": 10, "wants": False},
                {"name": "no_short_lease", "label": "Not short", "field": "signal:short_lease", "kind": "yes_no",
                 "relevance": 10, "wants": False}]
        raw = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
        raw["preferences"] += must
        prefs = PreferenceSet.model_validate(raw)
        score = lambda **o: score_listing(build_listing(_x(**o), prefs, pulled_at=WHEN), prefs)
        self.assertTrue(score(description="יחידת דיור נעימה, 2 חדרים").excluded)
        self.assertTrue(score(description="דירת 2 חדרים להשכרה ל4 חודשים בלבד").excluded)
        ok = score()
        self.assertFalse(any(r.startswith(("Not a unit", "Not short")) for r in ok.exclusion_reasons))


PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")

if __name__ == "__main__":
    unittest.main()
