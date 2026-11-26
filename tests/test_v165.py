"""v1.65 (Nov 11): Komo batch 3's parking phrasings, and the owner's ruling on "דירה ..." (a whole flat), each with the look-alikes
it must not catch. No right answer lost on the 640, batches 9 to 14 or Komo batches 1 to 3."""
import unittest

from rental_matcher.extraction.rules import answer


def _p(text):
    return answer(text).get("parking", {})


class TestParkingPhrasings(unittest.TestCase):
    def test_plain_mentions_are_a_floor(self):
        for t in ("מעלית, חניה נגישה\nמקלט", "לכניסה מיידית . חנייה + 2 מעליות .", "מתחם חניה סגור לדיירי הקומפלקס",
                  "מעלית\nחניית נכים מרווחת עם כניסה נפרדת לבניין"):
            got = _p(t)
            self.assertEqual((got["answer"], got.get("or")), ("building", ["deeded"]), t)  # there's parking; whose isn't said
        self.assertEqual(_p("חניית אופניים בבניין").get("answer", "not_stated"), "not_stated")  # a bicycle rack isn't parking

    def test_the_flats_own(self):
        self.assertEqual(_p("2 חניות מקורות וצמודות - נגמרו החיפושים")["answer"], "deeded")
        self.assertEqual(_p("גינה וחנייה לכל דייר")["answer"], "deeded")

    def test_plenty_in_the_building(self):
        self.assertEqual(_p("יש חניה בשפע בבניין")["answer"], "building")
        self.assertEqual(_p("חניה בשפע ברחוב")["answer"], "street")
        self.assertNotEqual(_p("מעלית, חניה בשפע על בסיס מקום פנוי, מזגן")["answer"], "building")  # batch 9: the labelers said street

    def test_a_public_lot_in_the_complex_is_a_floor(self):
        """The one listing Komo batch 3 hid: "במתחם חניון ציבורי" (street, or the building's)."""
        got = _p("במתחם חניון ציבורי וחדר כושר (בתשלום)")
        self.assertEqual((got["answer"], got.get("or")), ("street", ["building"]))
        self.assertEqual(_p("חניון ציבורי קרוב")["answer"], "street")
        self.assertIsNone(_p("חניון ציבורי קרוב").get("or"))


class TestWholeFlatRuling(unittest.TestCase):
    """the owner (Nov 11), after reviewing the 65 Komo batch 3 listings: "דירה ..." with nothing about a room is a whole flat."""

    def test_the_rule_stands(self):
        for t in ("דירה משופצת", "דירה נחמדה ליחיד או לזוג", "דירה בבינין 4 דיירים"):
            self.assertEqual(answer(t)["room_share"]["answer"], "no", t)
        self.assertEqual(answer("חדר להשכרה בדירת 3 חדרים")["room_share"]["answer"], "yes")


if __name__ == "__main__":
    unittest.main()
