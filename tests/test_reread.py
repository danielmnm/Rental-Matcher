"""
Oct 21, 2026: every listing saved Oct 18-20 (282) re-read with the browser
module (browser/yad2_pull.js) at its defaults. Two questions:

1. Does the browser extractor read a page the way the saved extracts did?
   The 60 from Oct 20's live pull have the same shape, so field by field.
2. How often does a listing change in 1-3 days, and how much of that would
   a cache miss? A change in price, floor, rooms, size or property type
   shows on the search row (the cache's fingerprint sees it); a change in
   the text alone doesn't, which is what the cache's one-day limit is for.

Every difference between a saved extract and its re-read is accounted for
below, as a real change or as a known artifact of how the old fixtures
were saved, so a new difference fails the test until it's explained.
"""

import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
FIELDS = ["adType", "price", "floor", "rooms", "sqm", "property", "inProperty", "desc"]

# real changes since the listing was saved
PRICE_CHANGED = {"bxhf5ute", "hxi6yv52", "59ejqd9p", "vpzd6fhh", "jqiup473", "smthpu2j", "ammvhkw4", "scfin790"}
TEXT_ONLY_EDITS = {"kepp0jzj", "lb9t8oqe"}  # a sentence added; a full rewrite. Nothing on the search row changed.
TEXT_AND_PRICE = {"scfin790"}  # a headline added, and ₪5,700 -> ₪5,400
# artifacts of the old saves, not changes
HAND_BLANKED_NAMES = {"5jadp0mm", "p44lnhi3", "vpfyna4w", "yyarmwwi"}  # agency/agent names blanked by hand then; the
#   automatic scrub only blanks the poster's own (2+ word) name, so these read in full now
OVER_BLANKED = {"z5x3xizp"}  # bus line numbers ("60 160 15 54 62") were blanked as a phone number then
CONTROL_CHAR = {"vpzd6fhh"}  # a U+0096 in the live text the old save didn't keep
NAME_AS_WORD = {"ze6q5qb8"}  # the bug this re-read found: poster "אור" blanked "שפע אור טבעי"; fixed (2+ word names only)
OLD_SHAPE_NO_PROPERTY = {"yad2_holdout2_2026-10-19", "yad2_holdout3_2026-10-19"}  # those saves kept no property type


def _norm(s):
    s = re.sub(r"\[(phone|name)\]", "", s or "")
    return re.sub(r"[\s‎‏﻿]+", " ", s).strip()


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _canon(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def saved():
    """The newest saved copy of each listing, projected like the re-read."""
    best = {}
    for f in sorted(FIX.glob("yad2*/*.json")):
        if f.parent.name in ("yad2_search_batyam_2026-10-20", "yad2_reread_2026-10-21") or f.name.startswith("routes"):
            continue
        if (re.search(r"2026-\d\d-\d\d", f.parent.name) or [""])[0] > "2026-10-21":  # v1.57: November too (batch 11)
            continue  # v1.42: saved after the Oct 21 re-read (held-out batch 7), so not in it
        data = json.loads(f.read_text(encoding="utf-8"))
        m = re.search(r"2026-10-\d\d", f.parent.name)
        for x in data if isinstance(data, list) else [data]:
            if "error" in x:
                continue
            when = (x.get("fetched_at") or (m.group(0) if m else "2026-10-18"))[:10]
            if x["id"] in best and best[x["id"]]["when"] >= when:
                continue
            ad = x.get("additionalDetails") or {}
            prop = ad["property"].get("text") if isinstance(ad.get("property"), dict) else x.get("property")
            best[x["id"]] = {"when": when, "dir": f.parent.name, "adType": x.get("adType"), "price": x.get("price"),
                             "floor": x.get("floor", "?"), "rooms": ad.get("roomsCount", x.get("rooms", "?")),
                             "sqm": ad.get("squareMeter", "?"), "property": prop,
                             "inProperty": _h(_canon(x["inProperty"])) if "inProperty" in x else "?",
                             "desc": _h(_norm(x.get("description")))}
    return best


class TestReread(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = json.loads((FIX / "yad2_reread_2026-10-21" / "reread.json").read_text(encoding="utf-8"))
        cls.new = {r[0]: r for r in d["rows"]}
        cls.old = saved()

    def fresh(self, i):
        r = self.new[i]
        return dict(zip(FIELDS, r[2:10])) if r[1] == "ok" else None

    def diffs(self, i):
        o, n = self.old[i], self.fresh(i)
        out = [f for f in FIELDS if o[f] != "?" and o[f] != n[f]]
        if "property" in out and o["property"] is None and o["dir"] in OLD_SHAPE_NO_PROPERTY:
            out.remove("property")
        return out

    def test_the_pull(self):
        self.assertEqual(set(self.new), set(self.old))
        status = [r[1] for r in self.new.values()]
        self.assertEqual((len(status), status.count("ok"), status.count("removed")), (282, 264, 18))  # 6% gone in 1-3 days

    def test_the_browser_extractor_reads_like_the_saved_extracts(self):
        live = json.loads((FIX / "yad2_live_2026-10-20" / "extracts.json").read_text(encoding="utf-8"))
        same, changed = 0, []
        for x in live:
            ad = x["additionalDetails"]
            o = {"adType": x["adType"], "price": x["price"], "floor": x["floor"], "rooms": ad.get("roomsCount", "?"),
                 "sqm": ad.get("squareMeter", "?"), "property": (ad.get("property") or {}).get("text"),
                 "inProperty": _h(_canon(x["inProperty"])), "desc": _h(_norm(x["description"]))}
            n = self.fresh(x["id"])
            d = [f for f in o if o[f] != n[f]]
            if d:
                changed.append((x["id"], d))
            else:
                same += 1
        self.assertEqual(same, 59)  # every field the same
        self.assertEqual(changed, [("scfin790", ["price", "desc"])])  # and the one that differs really changed

    def test_every_difference_is_accounted_for(self):
        live = [i for i in self.old if self.fresh(i)]
        price = {i for i in live if "price" in self.diffs(i)}
        text = {i for i in live if "desc" in self.diffs(i)}
        other = {f for i in live for f in self.diffs(i) if f not in ("price", "desc")}
        self.assertEqual(price, PRICE_CHANGED)
        self.assertEqual(other, {"inProperty"})
        self.assertEqual({i for i in live if "inProperty" in self.diffs(i)}, {"ammvhkw4"})  # with its price
        self.assertEqual(text, TEXT_ONLY_EDITS | TEXT_AND_PRICE | HAND_BLANKED_NAMES | OVER_BLANKED | CONTROL_CHAR | NAME_AS_WORD)

    def test_what_the_cache_could_miss(self):
        live = [i for i in self.old if self.fresh(i)]
        real = PRICE_CHANGED | TEXT_ONLY_EDITS
        unchanged = [i for i in live if i not in real]
        self.assertEqual((len(live), len(unchanged)), (264, 254))  # 96% the same after 1-3 days
        # a price change is on the search row, so the fingerprint sees it; text alone isn't
        self.assertEqual(len(PRICE_CHANGED), 8)
        self.assertEqual(len(TEXT_ONLY_EDITS), 2)  # 2 of 264 (0.8%) over 1-3 days
        when = {i: self.old[i]["when"] for i in TEXT_ONLY_EDITS}
        self.assertEqual(when, {"kepp0jzj": "2026-10-20", "lb9t8oqe": "2026-10-19"})
        read_a_day_ago = [i for i in live if self.old[i]["when"] == "2026-10-20"]
        self.assertEqual(len(read_a_day_ago), 152)  # 1 text-only edit among them: ~0.7% a day, so the cache keeps a day


class TestCacheLive(unittest.TestCase):
    """The cache on real pages (Oct 21): what the record says, held to its claims."""

    def test_a_second_pull_opens_nothing_and_an_edit_reopens_one(self):
        c = json.loads((FIX / "yad2_reread_2026-10-21" / "cache_check.json").read_text(encoding="utf-8"))
        self.assertEqual(c["search"]["seen"], c["search"]["total"])  # one read of the pages saw every listing Yad2 counts
        self.assertEqual((c["first"]["requests"], c["second"]["requests"], c["third_one_fingerprint_changed"]["requests"]), (10, 0, 1))
        self.assertTrue(c["second"]["extracts_identical"])
        self.assertEqual(c["third_one_fingerprint_changed"]["reopened"], [c["third_one_fingerprint_changed"]["changed"]])
        self.assertEqual(c["ze6q5qb8_after_fix"], {"status": "ok", "keeps_the_word": True, "has_name_tag": False})
        # the pace held: 17 search pages in 20 s, 10 listings in 11.5 s
        self.assertLess(c["search"]["ms"] / c["search"]["pages"], 1250)
        self.assertLess(c["first"]["ms"] / c["first"]["requests"], 1250)


if __name__ == "__main__":
    unittest.main()
