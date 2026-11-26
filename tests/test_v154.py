"""
v1.54: every box ticked on Yad2's form shows on the card (Owner ruling, Oct 29: "a renter will not tell
all directly but will tick those boxes and you will have visual confirmation").

An audit of 729 saved listings found ticked boxes going missing four ways:
- the furniture box ("ריהוט") showed nothing on 157 of 283 listings when the text listed no items;
- four boxes no code read: דוד שמש (515), מזגן טורנדו (228), מחסן (95), מטבח כשר (90);
- ממ"ק (13) was read with no bubble for it;
- the simple card showed only what matched the settings, at most 4.

The furniture box stays weaker than the text (owner ruling: posters tick it for one chair): with no items
in the text it shows as "might be furnished", for information, and never counts for a furniture
must-have. The display check below holds the card to every box on every saved listing, so a box
can't drop out of sight again without a test failing.
"""

import glob
import json
import re
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rental_matcher.adapters import komo, yad2
from rental_matcher.extraction.card_eval import normalized
from rental_matcher.pipeline import build_listing
from rental_matcher.scoring import PreferenceSet, rank, score_listing
from rental_matcher.server import FEATURE_KEYS, _view

ROOT = Path(__file__).resolve().parents[1]
PREFS = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")  # wants a sofa
NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)

# Yad2's box -> the bubble(s) that show it. None: not a feature of the flat (Yad2's ad settings).
SHOWN_AS = {
    "includeAirconditioner": ("ac",), "includeBalcony": ("balcony",), "includeElevator": ("elevator",),
    "isRenovated": ("renovated",), "isPetsAllowed": ("pets",), "includeSecurityRoom": ("mamad",),
    "includeBuildingShelter": ("building_shelter",), "includeFloorShelter": ("floor_shelter",),
    "includeBars": ("bars",), "isHandicapped": ("accessible",), "isForPartners": ("suits_roommates",),
    "includeParking": ("parking_",), "isImmediateEntrance": ("available",),
    "includeFurniture": ("item_", "maybe_furnished"), "includeBoiler": ("solar_heater",),
    "includeTornado": ("tornado_ac",), "includeWarehouse": ("storage",), "isKitchenKosher": ("kosher_kitchen",),
    "includePandorDoors": ("pandor_doors",),  # v1.55: first seen on batch 10
    "isEarlyAccess": None, "isAssetExclusive": None,
}
# the signal each box sets: when the text contradicts it, the card shows a check instead of a bubble
SIGNAL = {"includeAirconditioner": "air_conditioning", "includeBalcony": "balcony", "includeElevator": "elevator",
          "isRenovated": "renovated", "includeParking": "parking_level", "includeFurniture": "furniture",
          "isImmediateEntrance": "days_until_available", "includeSecurityRoom": "mamad"}


def _x(**over):
    base = {"id": "t1", "adType": "private", "price": 4300, "floor": 2, "city": "בת ים",
            "additionalDetails": {"roomsCount": 3, "squareMeterBuild": 70, "property": {"text": "דירה"}},
            "inProperty": {"includeAirconditioner": True}, "description": "דירת 3 חדרים, מעלית"}
    return {**base, **over}


def _card(x, prefs=PREFS):
    listing = build_listing(normalized(x), prefs, pulled_at=NOW)
    s = rank([listing], prefs)[0]
    return listing, s, _view(s, listing, prefs)


def _keys(view):
    return {f["key"]: f["tone"] for f in view["feature_keys"]}


def saved_extracts():
    out = []
    for f in sorted(glob.glob(str(ROOT / "tests" / "fixtures" / "yad2*" / "**" / "*.json"), recursive=True)):
        try:
            e = json.loads(Path(f).read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(e, dict) and isinstance(e.get("inProperty"), dict) and e.get("price"):
            out.append(e)
    return out


class TestEveryBoxIsRead(unittest.TestCase):
    def test_the_four_boxes_no_code_read(self):
        x = _x(inProperty={"includeBoiler": True, "includeTornado": True, "includeWarehouse": True, "isKitchenKosher": True})
        sig = yad2.structured_signals(normalized(x), NOW.date())
        for name in ("solar_heater", "tornado_ac", "storage", "kosher_kitchen"):
            self.assertEqual(sig[name].value, True, name)
        # a Tornado A/C is an air conditioner (12 saved listings tick it without the A/C box)
        self.assertEqual(sig["air_conditioning"].value, True)

    def test_komo_sends_two_of_them_too(self):
        self.assertEqual(komo._TICKED["solar_heater"], "solar_heater")
        self.assertEqual(komo._TICKED["kosher_kitchen"], "kosher_kitchen")

    def test_every_bubble_has_words_in_both_languages_and_an_icon(self):
        i18n = (ROOT / "browser" / "i18n.js").read_text(encoding="utf-8")
        cards = (ROOT / "browser" / "cards.js").read_text(encoding="utf-8")
        icons = re.search(r"const ICONS = \{(.*?)\n  \};", cards, re.S).group(1)
        for words in FEATURE_KEYS.values():
            for key in words.values():
                if key == "no_photos":
                    continue  # said by the photo badge, not a bubble
                self.assertEqual(len(re.findall(rf"\bf_{key}:", i18n)), 2, f"f_{key} in English and Hebrew")
                self.assertRegex(icons, rf"\b{key}:", f"an icon for {key}")
        for key in ("maybe_furnished", "parking_any", "public_shelter"):
            self.assertEqual(len(re.findall(rf"\bf_{key}:", i18n)), 2, key)


class TestFurnitureBox(unittest.TestCase):
    """the owner: posters tick "ריהוט" even for one chair, so the text is stronger than the box."""

    def test_the_box_alone_is_a_maybe_and_never_a_match(self):
        listing, s, v = _card(_x(inProperty={"includeFurniture": True}, description="דירת 3 חדרים"))
        self.assertEqual(_keys(v).get("maybe_furnished"), "info")
        self.assertFalse(any(k.startswith("item_") for k in _keys(v)))
        furniture = next(r for r in s.results if r.name == "furniture")
        self.assertNotEqual(furniture.status, "met")  # a sofa must-have isn't met by the box

    def test_the_text_wins_when_it_lists_items(self):
        _, s, v = _card(_x(inProperty={"includeFurniture": True}, description="דירת 3 חדרים, יש ספה ומקרר"))
        keys = _keys(v)
        self.assertIn("item_sofa", keys)
        self.assertNotIn("maybe_furnished", keys)

    def test_the_text_wins_when_it_says_unfurnished(self):
        _, _, v = _card(_x(inProperty={"includeFurniture": True}, description="דירת 3 חדרים, ללא ריהוט"))
        keys = _keys(v)
        self.assertNotIn("maybe_furnished", keys)
        self.assertIn("item_says_unfurnished", keys)


class TestDisplayCheck(unittest.TestCase):
    """What the test missed until v1.54: it scored the card's data, not what the card shows."""

    @classmethod
    def setUpClass(cls):
        cls.listings = saved_extracts()

    def test_every_ticked_box_on_every_saved_listing_is_on_the_card(self):
        self.assertGreaterEqual(len(self.listings), 700)
        missing, ticked, checks = [], 0, 0
        for e in self.listings:
            listing, _, v = _card(e)
            keys = _keys(v)
            for box, on in e["inProperty"].items():
                if on is not True:
                    continue
                self.assertIn(box, SHOWN_AS, f"a Yad2 box nobody has looked at: {box} ({e['id']})")
                shown = SHOWN_AS[box]
                if shown is None:
                    continue
                ticked += 1
                if any(k.startswith(p) for p in shown for k in keys):
                    continue
                sig = listing.signals.get(SIGNAL.get(box, ""))
                if sig is not None and sig.status.value == "conflicting":
                    checks += 1  # the text says otherwise: a check, not a bubble
                    continue
                missing.append(f"{e['id']}: {box}")
        self.assertEqual(missing, [], f"{len(missing)} ticked boxes not on the card")
        self.assertGreater(ticked, 4900)  # 4969 on Oct 29
        self.assertLess(checks / ticked, 0.005)  # a rate, not a count, so new batches don't trip it: 21 of ~5,900 (0.36%) with batch 13, 25 with batch 14

    def test_a_contradicted_box_becomes_a_check(self):
        listing, s, v = _card(_x(inProperty={"includeBalcony": True}, description="דירת 3 חדרים, אין מרפסת"))
        self.assertEqual(listing.signals["balcony"].status.value, "conflicting")
        self.assertNotIn("balcony", _keys(v))
        self.assertNotIn("no_balcony", _keys(v))


try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipUnless(sync_playwright is not None, "Playwright isn't installed")
class TestSimpleCardDrawsEverything(unittest.TestCase):
    """The simple card (the default) draws every fact: the matches, then the rest in a quieter row."""

    def test_the_simple_card(self):
        i18n = (ROOT / "browser" / "i18n.js").read_text(encoding="utf-8")
        cards = (ROOT / "browser" / "cards.js").read_text(encoding="utf-8")
        x = {"id": "abc", "url": "https://www.yad2.co.il/realestate/item/abc", "price": 4300, "fit": "good",
             "city": "בת ים", "street": "סוקולוב", "feature_keys": [
                 {"key": "ac", "tone": "good"}, {"key": "balcony", "tone": "good"}, {"key": "elevator", "tone": "good"},
                 {"key": "renovated", "tone": "good"}, {"key": "item_sofa", "tone": "good"},
                 {"key": "solar_heater", "tone": "info"}, {"key": "storage", "tone": "info"},
                 {"key": "kosher_kitchen", "tone": "info"}, {"key": "maybe_furnished", "tone": "info"},
                 {"key": "pets", "tone": "info"}, {"key": "floor_shelter", "tone": "info"}],
             "notes": [], "asks": [], "trips": []}
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page()
            page.set_content("<html><body><div id=r></div></body></html>")
            page.add_script_tag(content=i18n)
            page.add_script_tag(content=cards)
            out = page.evaluate("""(x) => {
                const I = window.RentalI18n; I.setLang("en");
                const c = window.RentalCards.render(document, x, { I });
                document.getElementById("r").append(c);
                const rows = [...c.querySelectorAll(".rm-sicons")].map((r) => ({ cls: r.className, text: r.innerText }));
                return rows;
            }""", x)
            b.close()
        self.assertEqual(len(out), 2, out)
        good, other = out
        for word in ("Air conditioning", "Balcony", "Elevator", "Renovated", "Sofa"):
            self.assertIn(word, good["text"])  # five matches, none cut to "+1"
        self.assertIn("other", other["cls"])
        for word in ("Solar water heater", "Storage room", "Kosher kitchen", "Might be furnished", "Pets allowed", "Floor safe room"):
            self.assertIn(word, other["text"])


if __name__ == "__main__":
    unittest.main()
