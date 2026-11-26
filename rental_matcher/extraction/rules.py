"""
Phase 2: rule-based answers to the ten questions, from a listing's text.

The free, instant layer under the language model. It answers only the
phrasings it can read with certainty and says `not_stated` for
everything else, so the rule for every pattern below is the same as the
cost parser's: when in doubt, don't answer. A missed fact becomes a check
(or goes to the model); a wrong one corrupts a match.

Three ways a match is refused rather than answered:
- A negation right before the keyword ("ללא מעלית") turns it into a "no";
  a negation a word or two further back ("לא רחוק ממקלט") makes it unsafe,
  so that match is dropped.
- A false friend nearby: preparation or option words ("הכנה למזגן",
  "אפשרות לריהוט"), a public shelter ("מקלט ציבורי"), "ממדים"
  (dimensions) for ממ"ד.
- Two matches that disagree ("ללא מרפסת" ... "מרפסת שמש"): the text
  contradicts itself.

Two kinds of refusal, kept apart because they mean different things:
- `not_stated` (None here): the rules found nothing they can read. The
  text may still say it in words these rules don't know, so a model may
  answer instead.
- `unclear`: the rules DID find the subject, and what they found doesn't
  settle it -- a contradiction, an offer or a plan rather than a fact, a
  shelter down the street, an area where an amount would be. That's the
  text's problem, not the rules', so no reader should answer it: combine()
  turns any model answer there into a check, quoting these words.

Every answer quotes the exact words it rests on (`evidence`), so the same
grounding check that guards the model's answers applies here too.

Standard library only, like the Gemini runner.
"""

from __future__ import annotations

import re
from typing import Any, Iterator, Optional

from ..costs import candidate_spans
from .questions import NOT_STATED, QUESTIONS, UNCLEAR

Answer = dict[str, Any]

# Hebrew has no word spaces inside a word, but one-letter prefixes glue on:
# ו (and), ה (the), ב (in), ל (to), ש (that), מ (from), כ (as).
# v1.51: ו only ever comes first, so "הוספה" (was added) isn't ה+ו+ספה (a sofa; batch 8)
_PRE = r"(?<![א-ת])(?:ו?(?:כש|[שמ][הבל]|[הבלשמכ])?)"
_END = r"(?![א-ת])"
_NEG = r"(?:[וש]?(?:ללא|אין|בלי|לא)|אינה|אינו|אינם|אינן)"  # v1.58: "הדירה אינה מרוהטת" (batch 11)
_NEG_ADJACENT = re.compile(rf"(?<![א-ת]){_NEG}\s*$")
_NEG_NEARBY = re.compile(rf"(?<![א-ת]){_NEG}(?![א-ת])")
_CLAUSE_END = re.compile(r"[.!?;\n,]")


def _w(pattern: str) -> str:
    """A keyword with optional prefixes and a word boundary after it."""
    return rf"{_PRE}(?:{pattern}){_END}"


def _before(text: str, start: int, chars: int = 25) -> str:
    """The text just before a match, cut at the clause start."""
    window = text[max(0, start - chars) : start]
    cut = max((m.end() for m in _CLAUSE_END.finditer(window)), default=0)
    return window[cut:]


def _after(text: str, end: int, chars: int = 30) -> str:
    window = text[end : end + chars]
    m = _CLAUSE_END.search(window)
    return window[: m.start()] if m else window


_CONTRAST = re.compile(r"(?<![א-ת])(?:אבל|אך|אולם|אלא|ואילו)(?![א-ת])")


def _negation(text: str, start: int) -> Optional[str]:
    """'adjacent' (ללא X), 'nearby' (a negation 1-2 words back), or None.
    The keyword's own prefix letters count as part of it, so "ללא ממ"ד" and
    "אין בדירה ממ"ד" are told apart."""
    before = _before(text, start)
    # "אין ממ"ד אבל המקלט תקני": a contrast word ends the negation's reach (batch 5)
    if (but := list(_CONTRAST.finditer(before))):
        before = before[but[-1].end():]
    if _NEG_ADJACENT.search(before):
        return "adjacent"
    words = before.split()
    last = [i for i, w in enumerate(words[-3:]) if _NEG_NEARBY.fullmatch(w)]
    if last and not any(w in ("עם", "יש", "כולל", "כוללת", "וגם", "גם", "ועם", "ויש") for w in words[-3:][last[-1] + 1:]):
        return "nearby"  # v1.49: "ללא מעלית עם חניה": the "עם" starts what there IS
    return None


# v1.49: on the same line only ("פלוס חניה\nללא תיווך" isn't "no parking"), and "ללא תשלום" (free) isn't a denial
# v1.51: not "ו-": "ללא מעלית וללא חניה" denies the next thing too, not the elevator again
_NEG_AFTER = re.compile(r"^[ \t]*[:\-–—=]?[ \t]*(?:ש?(?:אין|לא|ללא|בלי)|אינו|אינה|אינם|אינן|x|X|✗|❌)(?![א-ת])"
                        r"(?![ \t]*(?:תשלום|עלות|הגבלה|הגבלות)(?![א-ת]))"
                        # v1.55: "מרפסת לא סוכה" denies the sukkah, not the balcony (batch 9)
                        r"(?![ \t]*(?:סוכה|גדולה|גדול|ענקית|רחבה|מרווחת|פתוחה|סגורה|שמש)(?![א-ת]))")


# The same denial a few words on, after a qualifier, when a colon or dash sets
# it off: "חניה צמודה: אין", "מקלט בבניין: אין", "מרפסת שמש - אין" (v1.28;
# the qualifier used to be read as the feature). The separator is required,
# so "מרפסת שמש לא גדולה" still has a balcony.
_NEG_AFTER_QUALIFIER = re.compile(
    r"^(?:[ \t]+[^\s:\-–—=,.;!?]+){1,3}(?<!בילט)[ \t]*[:\-–—=][ \t]*(?:[וש]?(?:אין|לא|ללא|בלי)|אינו|אינה|אינם|אינן|x|X|✗|❌)(?![א-ת])"
)  # v1.55 (census): "מדיח כלים ותנור כפול בילט-אין" is built-in, not a denial


def _matches(pattern: str, text: str) -> Iterator[re.Match[str]]:
    """Keyword matches, minus any the words right after deny ("מעלית: אין",
    "מרפסת - לא", "חניה צמודה: אין"): those are dropped, not read as a no."""
    for m in re.finditer(_w(pattern), text):
        rest = text[m.end() :]
        if not _NEG_AFTER.match(rest) and not _NEG_AFTER_QUALIFIER.match(rest):
            yield m


def _ans(answer: str, evidence: str, **extra: Any) -> Answer:
    return {"answer": answer, "evidence": evidence.strip(), **extra}


def _unclear(*evidence: str) -> Answer:
    """The text speaks to the question but doesn't settle it; the quotes
    are joined with "..." (the grounding check reads each piece)."""
    pieces = list(dict.fromkeys(e.strip() for e in evidence if e and e.strip()))
    return _ans(UNCLEAR, " ... ".join(pieces))


def _one(found: list[tuple[str, str]], doubts: Optional[list[str]] = None) -> Optional[Answer]:
    """One answer if all matches agree; unclear if they contradict each
    other, or if there are none but something doubtful was seen (`doubts`:
    an offer, a plan, a shelter down the street); else None."""
    answers = {a for a, _ in found}
    if len(answers) > 1:
        return _unclear(*(e for _, e in found))
    if not answers:
        return _unclear(*doubts) if doubts else None
    answer = answers.pop()
    return _ans(answer, next(e for a, e in found if a == answer))


# --- protected space -------------------------------------------------------

_MAMAD = r"ממ[\"״']?[דק]|מ['\"״]{1,2}מד|מרחב\s+מוגן(?:\s+(?:דירתי|קומתי))?"  # "מ''מד" (v1.55 census)  # v1.53: a floor's safe room (ממ"ק) too (census)
_MIKLAT = r"מי?קלט"  # "מיקלט" too (v1.51)
_SHELTER_QUALIFIER = re.compile(
    r"^\s*(?:ו?(?:ב?בני(?:י)?ן|תקני|מסודר|צמוד|פרטי|בקומ(?:ה|ת)|משותף|בבנין)|של\s+ה?בני(?:י)?ן)(?![א-ת])"
)
_SHELTER_HAS = re.compile(r"(?:^|\s)(?:יש|עם|כולל|ו?גם)\s*$")
# whose shelter: "גן שיש בו מקלט" (a kindergarten's), "מקלט בחצר הגן", "בבניין הצמוד"
_SHELTER_SOMEONE_ELSES = re.compile(r"(?<![א-ת])(?:ש?(?:יש\s+)?(?:בו|בה|בהם)|גן|גינה|פארק)\s*$")
_SHELTER_NOT_HERE = re.compile(r"(?<![א-ת])(?:ב?חצר\s+ה(?:גן|ספר)|ב?(?:גן|פארק|גינה)|ה?סמוך|ה?צמוד(?:ה)?\s+ל(?!דירה)|ה?שכן|ממול|עירוני|ציבורי|שכונתי)(?![א-ת])")
_SHELTER_ELSEWHERE = re.compile(r"(?:ליד|קרוב|רחוק|סמוך|מול|בקרבת|בסמוך|מרחק|דקות?|ציבורי"
                                r"|\d+\s*(?:מ['׳]|מטר(?:ים)?)\s+מ)")  # v1.53: "מקלט מעולה 100 מ' מהדירה" (census)


def protected_space(text: str) -> Optional[Answer]:
    """The question is "a safe room OR a building shelter", so each kind is
    read on its own and either one's yes is a yes: "יש ממ"ד, ללא מקלט" is
    not a contradiction. A contradiction is one kind said both ways."""
    mamad: list[tuple[str, str]] = []
    for m in _matches(_MAMAD, text):
        if re.search(r"(?<![א-ת])(?:קרוב|קרובה|סמוך|בסמוך|צמוד|צמודה|ליד)\s*$", _before(text, m.start(), 15)) and m.group().startswith("ל"):
            continue  # v1.58: "קרובה לממד" (batch 11): near one, not the flat's
        if re.match(r"^\s*(?:נמצא\s+)?(?:כ[-\s]?)?\d+\s*(?:מטר|מ['׳\"״]?)(?:ים)?\s+(?:מ|מן\s+)(?:ה)?(?:דירה|בית|יחידה)(?![א-ת])", text[m.end():]):
            mamad.append(("unclear", m.group() + re.match(r"^\s*\S+(?:\s+\S+){0,3}", text[m.end():]).group()))
            continue  # v1.60: "ממ\"ד 5 מטר מהדירה" (batch 13): one nearby, outside the flat
        neg = _negation(text, m.start())
        if neg == "adjacent":
            mamad.append(("no", _before(text, m.start()).split()[-1] + " " + m.group()))
        elif neg is None:
            mamad.append(("yes", m.group()))
    found: list[tuple[str, str]] = []
    doubts: list[str] = []
    for m in _matches(_MIKLAT, text):
        before, after = _before(text, m.start()), _after(text, m.end())
        if (_SHELTER_ELSEWHERE.search(before) or _SHELTER_ELSEWHERE.search(after) or re.search(r"(?:הסמוך|השכן|ממול)", after)
                or _SHELTER_NOT_HERE.search(after)):  # v1.51: "יש מקלט בחצר הגן" is the kindergarten's
            doubts.append(m.group() + after)  # a public shelter nearby isn't the building's own
            continue
        neg = _negation(text, m.start())
        if neg == "adjacent":
            found.append(("no", before.split()[-1] + " " + m.group()))
        elif neg is None and (_SHELTER_QUALIFIER.match(after) or _SHELTER_HAS.search(before)):
            q = _SHELTER_QUALIFIER.match(after)
            found.append(("yes", m.group() + (after[: q.end()] if q else "")))
        elif (neg is None and not re.search(r"[למכ]$", re.match(r"^(.*?)מי?קלט$", m.group()).group(1))  # not "למקלט" (to one)
              and not _SHELTER_SOMEONE_ELSES.search(before) and not _SHELTER_NOT_HERE.search(after)):
            # v1.51: a shelter listed with the flat's features is the building's ("מעלית ומקלט", "מקלט.",
            # "מקלט שמור בבניין"): 19 of 19 such mentions in the 640 labeled listings were read that way
            found.append(("yes", m.group()))
    kinds = [a for a in (_one(mamad), _one(found, doubts)) if a]
    for wanted in ("yes", UNCLEAR, "no"):
        for a in kinds:
            if a["answer"] == wanted:
                return a
    return None


# --- elevator --------------------------------------------------------------

_PREPARED = re.compile(r"(?:הכנה|הכנות|צורך|אפשרות|תכנון|מתוכננת|בבנייה|עתידית)")

# A floor number this high, with no actual מעלית word anywhere in the text,
# is still real evidence: no building in Israel this tall lacks an elevator
# (the owner's real-world read of "קומה 18" -- see README). The negative
# lookahead skips Yad2's "קומה N ללא" shorthand right after the number,
# which means the opposite (no elevator) even though it never spells out
# the word; that shorthand only shows up on low floors in practice, but the
# guard keeps this safe if that changes.
# (v1.28) The "ללא" check runs after the whole match, not as a lookahead
# inside it: a lookahead let the regex give back "מתוך 8" or a digit until
# the check passed, so "קומה 6 מתוך 8 ללא" and "קומה 10 ללא" read as yes.
_FLOOR = re.compile(r"קומה\s*\.?\s*(?:ה-?)?(\d{1,3})(?!\d)(?:\s*(?:מתוך|/)\s*(\d{1,3})(?!\d))?")
_NO_LIFT_AFTER = re.compile(r"\s*\(?\s*ללא")
ELEVATOR_FLOOR_THRESHOLD = 6


def elevator(text: str) -> Optional[Answer]:
    found: list[tuple[str, str]] = []
    doubts: list[str] = []
    for m in _matches(r"מעלי(?:ת|ות)", text):
        before, after = _before(text, m.start(), 15), _after(text, m.end(), 12)
        if _PREPARED.search(before) or _PREPARED.search(after):
            doubts.append(before + m.group() + after)  # planned, not there
            continue
        if re.search(r"(?:ש|למי\s+ש)(?:צריך|צריכה|צריכים|זקוק|זקוקה|מחפש|מחפשת)\s*$", before):
            doubts.append(before + m.group())  # v1.58: "לא מתאים למי שצריך מעלית" (batch 11): about the tenant
            continue
        neg = _negation(text, m.start())
        if neg is not None and re.match(r"^\s*(?:של\s+)?שבת(?![א-ת])", text[m.end():]):
            doubts.append(before.split()[-1] + " " + m.group() + " שבת")  # v1.56: "אין מעלית שבת" (batch 10): only the Shabbat lift
            continue
        if neg == "adjacent":
            found.append(("no", before.split()[-1] + " " + m.group()))
        elif neg is None:
            found.append(("yes", m.group()))
    if not found and (lm := re.search(r"(?<![א-ת])(?:ללא|בלי)\s+מעלות(?![א-ת])", text)) and re.search(r"מעלית", text):
        found.append(("no", lm.group()))  # v1.58: "16 מדרגות ללא מעלות ... מעלית" (batch 11): the typo, with the word nearby
    answer = _one(found, doubts)
    if answer is not None:
        return answer
    for fm in _FLOOR.finditer(text):
        if _NO_LIFT_AFTER.match(text, fm.end()):
            continue
        if re.match(r"^\s*(?:מטר|מ[\"״']ר|מ['׳]|מר)(?![א-ת])", text[fm.end():]):
            continue  # v1.56: "פנטאוז לבד בקומה 150 מטר" (batch 10): a size, not a floor
        if re.search(r"(?<![א-ת])נוף\s+(?:של\s+|מ)?$", text[max(0, fm.start() - 12):fm.start()]):
            continue  # v1.62: "נמצאת בקומה -1 אך נוף של קומה 6" (Komo batch 1): the view's floor, not the flat's
        if re.match(r"^\s*(?:ה)?גג(?![א-ת])", text[fm.end():]):
            continue  # v1.58: "(בקומה 6 גג הבניין)" (batch 11): the roof's floor, not the flat's
        floors = [int(g) for g in fm.groups() if g and int(g) <= 60]  # v1.59.1 (owner ruling): "קומה 2 מתוך 8": a tall building has a lift, so the building's height counts
        if floors and max(floors) >= ELEVATOR_FLOOR_THRESHOLD:
            return _ans("yes", fm.group(), note=f"floor {max(floors)}: too tall to lack an elevator")
    return None


# --- air conditioning ------------------------------------------------------


# what's being taken out isn't there: "המזגנים שרואים במרפסת זה חלקים ישנים שיפונו" (batch 8)
_REMOVED = re.compile(r"(?<![א-ת])(?:ש|ו)?(?:פונו|יפונו|פורקו|יפורקו|הוסרו|יוסרו|הוצאו|יוצאו|ישנים\s+ש)(?![א-ת])")


def air_conditioning(text: str) -> Optional[Answer]:
    found: list[tuple[str, str]] = []
    doubts: list[str] = []
    for m in _matches(r"מזגנ?ים|מזגן|ממוזג(?:ת|ים|ות)?|מיזוג(?:\s+אוויר|\s+מרכזי)?", text):
        before, after = _before(text, m.start(), 15), _after(text, m.end(), 12)
        if _PREPARED.search(before):
            doubts.append(before + m.group())  # "הכנה למזגן": prepared for one, not one
            continue
        if re.match(r"^\s*(?:חלקי|בחלק)", after):
            continue
        span = next((s for s in _SENTENCE.finditer(text) if s.start() <= m.start() < s.end()), None)
        if span and _REMOVED.search(text[m.end() : span.end()]):
            doubts.append(span.group().strip())  # v1.51: "המזגנים ... חלקים ישנים שיפונו": being taken out (batch 8)
            continue
        neg = _negation(text, m.start())
        if neg == "adjacent":
            found.append(("no", before.split()[-1] + " " + m.group()))
        elif neg is None:
            found.append(("yes", m.group()))
    return _one(found, doubts)


# --- parking -----------------------------------------------------------------

_PARKING = r"חני(?:י)?(?:ה|ות)|חניית(?=\s+נכים)|חניון|חנויות(?=\s+(?:פרטיות|צמודות|בטאבו|רשומות|מקורות|בחניון))"  # v1.56: the typo "2 חנויות פרטיות" (batch 10); "חנויות" alone is shops
# v1.49: the parking phrase book. Parking is said in a small set of ways, so
# each phrasing seen in the 463 labeled listings (typos included: "בטבו") is
# listed under what it settles. Two independent labelers read every one, and
# a phrasing they read two ways is listed as two-way: a definite answer there
# would hide the listing from someone whose must-have the other reading meets
# ("חניה מקורה" may be the apartment's own; "יש חניה" says nothing of whose),
# so it's a check instead. Words that only describe it ("גדולה", "רגילה") are
# read past.
PARKING_PHRASES: dict[str, tuple[str, ...]] = {
    # settled: the labelers read these one way every time
    "deeded": ("פרטית", "פרטיות", "פרטיים", "צמודה", "צמוד", "צמודות", "צמודים", "רשומה", "בטאבו", "בטבו", "משלה", "משלך",  # plurals (v1.51)
               r"לכל\s+דייר"),  # v1.65: "גינה וחנייה לכל דייר" (Komo batch 3)
    "building": (r"ב?בני(?:י)?ן", r"לבני(?:י)?ן", "בבנין", "משותפת", "בתוספת", "בתשלום", "למטה",  # v1.56: "הרבה חניה למטה" (batch 10)
                 r"(?:ע[\"״']?ב|על\s+בסיס)\s*מקום\s+(?:פנוי|חופשי)", r"של\s+(?:ה)?דיירי(?:ם)?", r"לדיירי\s+(?:ה)?בני(?:י)?ן",
                 r"(?:ל|על)[\s\-]*\d+\s+(?:דיירים|דירות)"),  # v1.53: "9 חניות ל-12 דיירים" (census)
    "street": ("בשפע", "ברחוב", "רבות", "ציבורית", "ציבורי", "באזור", "באיזור", "בסביבה", "בשכונה",  # v1.53: "באיזור"
               r"כחול[\s\-]?לבן", "באפור", "אפור", "במפרץ", "לתושבי",
               "בכביש", "עירוני", "עירונית",  # v1.56: "חניה בכביש", "מפרץ חניה עירוני" (batch 10)
               r"(?:ל|ב)צ(?:י)?די\s+(?:ה)?(?:רחוב|כביש)"),  # v1.68: "יש חנייה לצידי הרחוב" (Komo batch 4)
    # two-way: the building's or the apartment's own ...
    "building_or_own": ("מקורה", "מקורות", "מקורים", "נכים", r"תת[\s\-]?קר(?:ק)?עי(?:ת|ות|ים)",  # v1.65: "2 חניות מקורות", "חניית נכים" (Komo batch 3)  # plurals (v1.53); the typo "תת קרעיות" (v1.55, batch 9)
                         "פנימית", "לדיירים", "לדיירי", r"עם\s+שער(?:\s+חשמלי)?",
                        r"עם\s+מחסום", "שמורה", "בחניון", "רובוטית"),  # v1.56: a robotic space may be the flat's own (batch 10)
    # ... or the street's or the building's (free, in a lot)
    "street_or_building": ("חופשית", "חופשי", "חינם", "חינמית", "במגרש", "במתחם", r"ללא\s+תשלום",  # free: maybe the street's (v1.53)
                           r"בסביבת\s+(?:ה)?(?:בית|בניין|בנין)"),  # v1.68: "חנייה גדולה בסביבת הבית" (Komo batch 4): near it, maybe a lot
    "neutral": ("ו?גדולה", "גדול", "רגילה", "אחת", "נוספת", "כפולה", "עוקבת", "עוקבות", "טורית", "טוריות", "קלה", "נוחה", "הבניין", "תשלום",
                "רק", "בלבד",
                # v1.51: "חניה + מחסן בטאבו", "חנייה ומחסן צמודים": what follows the storeroom is said of both
                "זמינה", r"\+", "מחסן", "ומחסן", "בקלות",  # v1.53: "חניה בקלות ברחוב"
                "בכניסה",  # v1.55: "חניה בכניסה לבניין" (batch 9): where it is; what follows says whose
                "נגישה", "מרווחת", "סגור", "סגורה"),  # v1.65: "חניה נגישה", "מתחם חניה סגור לדיירי הקומפלקס" (Komo batch 3)
}
_KIND = {k: re.compile(rf"(?<![א-ת])ו?(?:{'|'.join(v)})(?![א-ת])") for k, v in PARKING_PHRASES.items() if k != "neutral"}
_MOD = r"ו?(?:" + "|".join(p for v in PARKING_PHRASES.values() for p in v) + ")"
_DEEDED, _BUILDING, _STREET = _KIND["deeded"], _KIND["building"], _KIND["street"]
_BUILDING_OR_OWN, _STREET_OR_BUILDING = _KIND["building_or_own"], _KIND["street_or_building"]
# "צמודה לבניין" is where the parking is, not whose: it isn't the apartment's own
_BESIDE = re.compile(r"(?<![א-ת])ו?צמוד(?:ה)?\s+ל(?:ה)?(?:בית|בני(?:י)?ן|בנין|מבנה)(?![א-ת])")  # v1.61: "חניה גדולה וצמודה לבניין" (batch 14)
# what a plain mention ("יש חניה", "כולל חניה", "מעלית וחניה", "2 חניות") is preceded or followed by
_AMENITY = r"(?:מיזוג|מזגן|מזגנים|ממ[\"״']?ד|מעלית|מרפסת|מחסן|מקלט|סורגים|דוד|שמש|נוף)"
_HAS_BEFORE = re.compile(rf"(?:^|\s)(?:יש|ישנה|ישנם|ישנו|כולל|כוללת|הכוללת|וכוללת|עם|פלוס|גם|\+|\||\d+|שתי|שני|שלוש|{_AMENITY}(?:,)?)\s*$")  # v1.65: "מעלית, חניה נגישה" (Komo batch 3)
_HAS_AFTER = re.compile(r"^[ \t]*(?:$|[.,+()\-!:;|]|\n|ו(?=\S)|אחת(?![א-ת])|ל\s*\d|לרכב|במיקום|בקרבת|ומחסן|ומעלית|(?:\d+\s+)?מעליות(?![א-ת]))")  # v1.65: "חנייה + 2 מעליות" (Komo batch 3)
_LEVEL = {"deeded": 3, "building": 2, "street": 1, "none": 0}
# v1.53: a street word in the same sentence as a plain mention may be where it is
_STREET_NEAR = re.compile(r"(?<![א-ת])(?:ב?רח['׳]|ו?ברחוב|ו?לתושבי|ו?באזור|ו?באיזור|ו?בסביבה|ו?בשכונה|בשפע|ציבורי(?:ת)?|כחול[\s\-]?לבן)(?![א-ת])")


# v1.60 (decision 0001): plenty of parking AT the property ("ליד הכניסה", "במקום") may be the building's lot,
# so it's a floor ("street, maybe the building's"), never a reason to hide. Plain "חניה בשפע" stays street,
# as the labelers read it (25 of 25 in the labeled sets); words that place it on the street keep it there.
_AT_PROPERTY = re.compile(r"(?<![א-ת])(?:(?:ליד|סמוך\s+ל|צמוד(?:ה)?\s+ל|מול|מתחת\s+ל)\s*|ב)(?:ה)?(?:כניסה|בניין|בנין|בית|דירה|חצר|מתחם)(?![א-ת])|(?<![א-ת])(?:במקום|למטה)(?![א-ת])")  # v1.62: "המון חניה מתחת לבית" (Komo batch 1)
# words that put parking on the street or in the area
_PLACED = re.compile(r"(?<![א-ת])(?:ב?רח['׳]|ו?ברחוב|ו?בכביש|ו?לתושבי|ו?באזור|ו?באיזור|ו?בסביבה|ו?בשכונה|ציבורי(?:ת)?|עירוני(?:ת)?"
                     r"|כחול[\s\-]?לבן|מפרץ|זכאות|תו)(?![א-ת])")


def _clause_of(text: str, at: int) -> str:
    """v1.60: the comma-to-comma clause around a position ("2 קומות בבניין,חניה בשפע": the building is the
    previous clause's, not where the parking is)."""
    a = max(text.rfind(c, 0, at) for c in ",.!?;\n") + 1
    b = min([i for i in (text.find(c, at) for c in ",.!?;\n") if i >= 0] or [len(text)])
    return text[a:b]


def _sentence(text: str, at: int) -> str:
    """The sentence (or line) around a position."""
    start = max(text.rfind(c, 0, at) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, at) for c in ".!?\n") if i >= 0]
    return text[start : min(ends) if ends else len(text)]


def parking(text: str) -> Optional[Answer]:
    """The best parking the apartment gets. A mention the phrase book reads
    two ways is a `doubt` with the highest level it could mean: when one
    could be better than what was settled, the answer is a check (v1.49)."""
    found: list[tuple[str, str]] = []
    doubts: list[tuple[int, str]] = []
    bare: list[str] = []  # v1.53: "יש חניה", "2 חניות", "חניה + מחסן": there is a space, whose isn't said
    abundant: set[str] = set()  # v1.60: "חניה בשפע" with no word that places it
    unread = 0
    for m in _matches(_PARKING, text):
        rest = _BESIDE.sub(lambda b: " " * len(b.group()), text[m.end() :])  # v1.49: "צמודה לבית" is where, not whose
        mods = re.match(rf"^(?:[ \t]+{_MOD}{_END}){{0,4}}", rest)  # v1.51: on the same line ("חניה תת קרקעית\n\nבבניין", batch 8)
        phrase = m.group() + (mods.group() if mods else "")
        tail = phrase[len(m.group()) :]
        before = _before(text, m.start())
        neg = _negation(text, m.start())
        if re.search(r"(?:אין|ללא|בלי)\s+(?:בעיית|בעיות|בעיה\s+של|בעיות\s+של)\s*$", before):
            doubts.append((2, " ".join(before.split()[-2:]) + " " + m.group()))  # "אין בעיית חנייה": easy -- street or the lot's
            continue
        if (re.search(r"(?:ליד|סמוך\s+ל|בסמוך\s+ל)\s*ה?(?:מבנה|בניין|בנין)\s*$", before)
                and not (_DEEDED.search(tail) or _STREET.search(tail) or _BUILDING.search(tail))):
            doubts.append((2, " ".join(before.split()[-2:]) + " " + m.group()))  # a lot next to the building: whose?
            continue
        if re.search(r"(?<![א-ת])מגרש\s*$", before) and neg is None:
            found.append(("building", "מגרש " + m.group()))  # v1.55 (census): "יש מגרש חניה" (1 of 1 in the 640: the building's)
            continue
        if re.search(r"אפשרויות\s*$", before) and m.group().startswith("ח"):
            found.append(("street", before.split()[-1] + " " + phrase))  # "אפשרויות חניה באזור"
            continue
        if re.search(r"(?<![א-ת])(?:חניות|לחניות)$", m.group()) and re.match(r"^\s+ו?(?:ל)?(?:טיול|מסעד|קניות|בתי\s+קפה|בילוי|מרכז)", text[m.end():]):
            continue  # v1.56: "משמת לחניות ולטיולים" (batch 10): shops misspelled, not parking
        if re.match(r"^\s*(?:ו\S+\s+)?(?:ב)?(?:קירבת|קרבת|סמוך\s+ל|ליד)\s*(?:ה)?(?:בניין|בנין|בית|דירה)(?![א-ת])", text[m.end():]):
            continue  # v1.62: "חניה וחנויות בקירבת הבניין" (Komo batch 1): near the building, not the building's
        if re.search(r"(?<![א-ת])(?:קרוב|קרובה|קרובים|ליד|סמוך|בסמוך|בקירוב|בקרוב)\s*$", before) and m.group().startswith("ל"):  # v1.64: "מחסן גדול בקירוב לחניה" (Komo batch 2)
            continue  # v1.60: "קרוב לחניות ובית כנסת" (batch 13): near it (or near shops, misspelled), not the flat's
        if re.search(r"(?<![א-ת])דרך\s*$", before):
            continue  # v1.56: "שער כניסה נפרד דרך החניה" (batch 10): the way in, not a space
        if re.search(r"(?<![א-ת])(?:מפרץ|זכאות(?:\s+ל)?)\s*$", before) and neg is None:
            found.append(("street", before.split()[-1] + " " + m.group()))  # v1.56: "מפרץ חניה", "זכאות לחניה" (a permit): the street's
            continue
        if re.search(r"(?:^|\s)ו?(?:שפע(?:\s+של)?|הרבה|מלא|המון)(?:\s+מקומות|\s+מקום)?\s*$", before) and neg is None:  # v1.68: "שפע של מקום חניה" (Komo batch 4)  # v1.61: "המון חנייה" (batch 14); v1.64: "ושפע חניה", "שפע של מקומות חניה" (Komo batch 2)
            if _BUILDING.search(tail):
                found.append(("building", " ".join(before.split()[-2:]) + " " + phrase.strip()))  # v1.56: "הרבה חניה למטה"
            else:  # v1.49: "שפע של חנייה"; v1.56: "מלא חניה", quoted with the sentence's "ברחוב" when it has one (the card's text-wins rule reads it)
                near = _STREET_NEAR.search(_sentence(text, m.start()))
                found.append(("street", _sentence(text, m.start()).strip() if near else " ".join(before.split()[-2:]) + " " + m.group()))
                if _AT_PROPERTY.search(_clause_of(text, m.start())) and not _PLACED.search(_clause_of(text, m.start())):  # v1.62: the parking's own clause (Komo batch 1)
                    abundant.add(found[-1][1])  # v1.60 (decision 0001): plenty, but not where: the street's or the lot's
            continue
        if neg is None and re.match(r"^\s+(?:יש\s+)?בשפע(?![א-ת])", text[m.end():]) and (m.group() == "חניון" or re.match(r"^\s+יש\s", text[m.end():])):
            found.append(("street", m.group() + re.match(r"^\s+(?:יש\s+)?בשפע", text[m.end():]).group()))  # v1.64: "חניון בשפע", "חניה יש בשפע" (Komo batch 2)
            if _AT_PROPERTY.search(_clause_of(text, m.start())) and not _PLACED.search(_clause_of(text, m.start())):
                abundant.add(found[-1][1])
            continue
        if re.search(r"(?:ניתן|אפשר|אפשרות|ניתן\s+גם)\s+(?:ל)?(?:שכור|לשכור|קנות|לקנות|רכוש|לרכוש|השכיר|להשכיר)\s*$", before):
            doubts.append((2, " ".join(before.split()[-2:]) + " " + m.group()))  # v1.51: a space you can rent is an offer (batch 8)
            continue
        if re.search(r"(?:^|\s)תו\s*$", before):
            doubts.append((1, "תו " + m.group()))  # v1.49: a permit: street parking, or read two ways -- alone, a check
            continue
        if neg is None and re.match(r"^\s+(?:(?:מקורה|תת[\s\-]?קרקעי(?:ת|ות)?|גדולה|רחבה|ו?מחסן)\s+){0,2}(?:ש)?לדירה(?![א-ת])", text[m.end():]):
            found.append(("deeded", m.group() + re.match(r"^\s+(?:\S+\s+){0,2}?(?:ש)?לדירה", text[m.end():]).group()))
            continue  # v1.55: "חניה מקורה לדירה" (batch 9): the flat's own
        if (neg is None and re.search(r"(?<![א-ת])ו?ל(?:דירה|נכס|יחידה)\s+(?:\d|שתי|שתיים|שלוש)?\s*$", before)
                and not (_STREET.search(tail) or _STREET_OR_BUILDING.search(tail) or _BUILDING.search(tail))):
            said = re.search(r"ו?ל(?:דירה|נכס|יחידה)\s+(?:\d|שתי|שתיים|שלוש)?\s*$", before).group().strip()  # v1.56: "יש לנכס חנייה מקורה"
            found.append(("deeded", said + " " + phrase.strip()))
            continue  # v1.51: "לדירה 2 חניות": the flat's own spaces
        if neg == "adjacent":
            if not tail.strip():
                found.append(("none", before.split()[-1] + " " + m.group()))
            continue  # "ללא חניה צמודה" denies one kind; it says nothing of the rest
        lot = m.group().endswith("חניון")  # "חניון", "לחניון": a parking lot, often down the street
        if lot and neg is None and re.match(r"^\s+ו?(?:ציבורי|עירוני)(?![א-ת])", rest):
            found.append(("street", m.group() + re.match(r"^\s+\S+", rest).group()))  # v1.51: a public lot (batch 8)
            if re.search(r"(?<![א-ת])(?:ב|ו?ב)(?:מתחם|בניין|בנין)\s*$", before):
                abundant.add(found[-1][1])  # v1.65: "במתחם חניון ציבורי" (Komo batch 3): a public lot in the complex: street, maybe the building's
            continue
        if neg == "nearby" or lot and not (_BUILDING.search(tail) or _BUILDING_OR_OWN.search(tail)):
            unread += neg is None
            continue
        if _DEEDED.search(tail):  # v1.51: "חניה בטאבו ברחוב בלפור 139": "ברחוב" there is the address
            if re.search(r"(?<![א-ת])ברחוב\s*$", tail) and re.match(r"^\s+(?!ה?(?:סמוך|ליד|קרוב)(?![א-ת]))[א-ת\"'״]{2,}",
                                                                   text[m.start() + len(phrase):]):
                tail = re.sub(r"(?<![א-ת])ברחוב\s*$", "", tail)
        if _DEEDED.search(tail) and (_STREET.search(tail) or _STREET_OR_BUILDING.search(tail)):
            unread += 1  # "public" and "the apartment's own" at once: let a closer reader decide
        elif _DEEDED.search(tail):
            found.append(("deeded", phrase))
        elif (re.search(r"(?<![א-ת])ו?בשפע(?![א-ת])", tail) and re.search(r"(?<![א-ת])ו?(?:ב|ל)בני(?:י)?ן(?![א-ת])", tail)
              and not _STREET.search(re.sub(r"(?<![א-ת])ו?בשפע(?![א-ת])", "", tail))):
            found.append(("building", phrase))  # v1.65: "יש חניה בשפע בבניין" (Komo batch 3): plenty, in the building
        elif _STREET.search(tail):
            if _BUILDING.search(tail) or _BUILDING_OR_OWN.search(tail) or re.search(r"(?<![א-ת])(?:במגרש|במתחם)(?![א-ת])", tail) or re.match(r"^\s*במקום(?![א-ת])", text[m.start() + len(phrase):]):
                doubts.append((2, phrase))  # "חניה משותפת בשפע", "חינמית ובשפע במגרש": the lot's or the street's; v1.58: "בשפע במקום" (batch 11)
            else:
                found.append(("street", phrase))
                if _AT_PROPERTY.search(_clause_of(text, m.start())) and not _PLACED.search(_clause_of(text, m.start())):  # v1.62: the parking's own clause (Komo batch 1)
                    abundant.add(phrase)  # v1.60: "חניה בשפע ליד הכניסה": plenty, at the property
        elif _BUILDING.search(tail):
            found.append(("building", phrase))
        elif _BUILDING_OR_OWN.search(tail):
            doubts.append((3, phrase))
            bare.append(phrase)  # "חניה תת קרקעית", "חניה מקורה": the building's or the flat's own (v1.53)
        elif _STREET_OR_BUILDING.search(tail):
            doubts.append((2, phrase))
        elif not lot and (_HAS_BEFORE.search(before) or _HAS_AFTER.match(text[m.start() + len(phrase):])):
            # v1.49: "יש חניה", "כולל חניה", "2 חניות": there is parking, but whose isn't said
            # (the labelers read it as the building's or the apartment's own): a check
            doubts.append((3, (before.split()[-1] + " " if _HAS_BEFORE.search(before) else "") + phrase.strip()))
            if not _STREET_NEAR.search(_sentence(text, m.start())):
                bare.append(doubts[-1][1])  # not "ברח' חניה, רק לתושבי הרחוב" (census): that's the street's
        else:
            unread += 1  # a parking mention these rules can't classify
    if not found and bare and len(bare) == len(doubts) and not unread:
        # v1.53: only plain mentions: the building's or the flat's own, the same lower bound as Yad2's
        # ticked box. 21 of 21 such texts in the 640 labeled listings were one of the two (most were
        # read both ways); a user who needs their own space gets a check, one who needs any space doesn't.
        return _ans("building", bare[0], **{"or": ["deeded"]})
    if not found:
        return _unclear(*(e for _, e in doubts)) if doubts else None
    if unread and max(_LEVEL[a] for a, _ in found) < _LEVEL["deeded"]:
        return None  # the unread mention may be the better kind ("חניה לדיירים וחניה בשפע ברחוב")
    kinds = {a for a, _ in found}
    if "none" in kinds and (kinds & {"deeded", "building"} or doubts):
        return _unclear(*(e for _, e in found), *(e for _, e in doubts))  # "no parking" and a space: contradictory
    if "none" in kinds and len(kinds) > 1:
        found = [f for f in found if f[0] != "none"]  # "ללא חניה. חניה בשפע ברחוב": no space, street parking
    best = max(found, key=lambda f: _LEVEL[f[0]])
    if doubts and max(lvl for lvl, _ in doubts) > _LEVEL[best[0]]:
        return _unclear(best[1], *(e for _, e in doubts))  # another mention may be better than the settled one
    if best[0] == "street" and all(e in abundant for k, e in found if k == "street"):
        # v1.60 (decision 0001): "חניה בשפע" says there's room, not whose: at least the street, maybe the building's
        # lot. A floor, like Yad2's box: never a reason to hide a listing from a "building parking" must-have
        return _ans("street", best[1], **{"or": ["building"]})
    return _ans(*best)


# --- room share ----------------------------------------------------------------

_ROOM_SHARE_YES = re.compile(
    r"(?<![א-ת])(?<!כל\s)(?:חדר\s+(?:(?!ו?חצי(?![א-ת])|אחד(?![א-ת])|ו)[א-ת]+\s+)?(?:להשכרה|פנוי|בדירת|בדירה)|להשכרה\s+חדר(?![א-ת])(?!\s+ו?(?:חצי|סלון))"  # v1.59: not "חדר ומחסן בדירה" (rooms and a storeroom), "בכל חדר", "חדר וסלון" (batch 12)  # v1.55: "חדר שקט להשכרה" (batch 9); not "חדר וחצי להשכרה"
    r"|יש\s+(?:\S+\s+)?שות(?:ף|פה|פים|פות)\s+(?:ב)?(?:דירה|בית)(?![א-ת])"  # v1.55: "יש שותף בדירה" (batch 9)
    # v1.55 (census): an ad that opens with the room: "חדר עם חדר אמבטיה פרטי בתוך דירה" (not "חדר וחצי", a 1.5-room flat)
    r"|^\W*(?:להשכרה\s*:?\s*)?חדר\s+(?!ו?חצי|ו?סלון|\d)(?:עם|ב|בתוך|פרטי|גדול|מרווח|מרוהט|להשכרה|שקט|יפה|מואר)(?![א-ת])"
    r"|(?:מחפש|מחפשת|מחפשים|מחפשות|דרוש|דרושה|דרושים)\s+(?:\S+\s+)?שות(?:ף|פ)"
    r"|שות(?:ף|פה|פים|פות|פ/ה|ף/ה)\s+(?:לדירה|לדירת)"
    # v1.39 (the first test search): a room is being vacated, or roommates stay on
    r"|(?:מתפנ|מפנ)(?:ה|ים|ות|ת)?\s+(?:(?:ה|שני|שתי|2)\s+)?חדר(?:ים)?(?![א-ת])(?!\s*(?:\d|ו?חצי))"
    r"|(?:עוד|עם)\s+(?:\S+\s+)?שות(?:ף|פה|פים|פות)(?![א-ת])(?!\s+(?:ל(?:בניין|חצר|גג)))"
    r"|(?:נשאר|נשארת|נשארים|נשארות)\s+(?:\S+\s+)?שות(?:ף|פה|פים|פות)(?![א-ת])"
    r"|שות(?:ף|פה|פים|פות)\s+(?:\S+\s+){0,2}?(?:שנשאר|שנשארת|שנשארים|נשאר|נשארת|נשארים)(?![א-ת])"
    # v1.51: the kitchen or bathroom is shared with others: a room in a home (batch 8)
    r"|(?:ה?מטבח|ה?אמבטיה|ה?מקלחת|ה?שירותים)(?:\s+ו(?:ה)?(?:מטבח|אמבטיה|מקלחת|שירותים))?\s+(?:משותפ(?:ים|ת|ות)?|בשיתוף)(?![א-ת]))"
)
_ROOMMATE_WORD = re.compile(r"(?<![א-ת])ו?(?:ה|ל)?(?:שות(?:ף|פה|פ/ה|ף/ה)(?![א-ת])|דירת\s+שותפים)")  # a singular roommate: unsafe
_NUM = r"(?:\d(?:\.\d)?|אחד|שניים|שניי|שני|שתי|שלושה|שלוש|ארבעה|ארבע|חמישה|חמש)"
_WHOLE_APARTMENT = re.compile(
    rf"(?<![א-ת])(?:ה?דירת\s*\.?\s*{_NUM}\s*(?:חדרים|חד|ח)(?![א-ת])"
    rf"|(?<![\d.]){_NUM}\s*חדרים(?![א-ת])"
    r"|ה?דירת\s+(?:גן|קרקע|גג|סטודיו|פנטהאוז|פנטהאוס|דופלקס|חדר)(?![א-ת])"
    r"|ה?דירת\s*\.?\s*\d(?:\.5)?(?![\d.])(?!\s*(?:קומות|מפלסים|כיווני|דקות|מ[\"״]ר|מטר))"  # "דירת 3.5 שמורה"
    r"|יחידת\s+דיור|ה?דירה\s+להשכרה|להשכרה\s+(?:ה?דירה|ה?דירת)"
    r"|ה?דירה\s+(?:ל|מתאימה\s+ל)(?:יחיד|זוג|משפחה|זוגות)(?![א-ת])"
    rf"|(?:מתאים|מתאימ(?:ה|ים)?|מצוינת|מצויינת|מושלמת|אידיאלית|נהדרת)\s+(?:גם\s+)?ל(?:-?\s*{_NUM}\s+)?שותפים(?![א-ת])"  # a whole apartment roommates could rent ("לשני שותפים", v1.53; "מתאים גם לשותפים", v1.55)
    r"|ה?דירה\s+(?:בשטח\s+של\s+|של\s+)?(?:כ-?\s*)?\d{2,3}\s*(?:מ[\"״]?ר|מטר)"  # the apartment's own size
    r"|להשכרה\s+ב(?:רחוב|שכונת|חולון|תל|בת|רמת|גבעתיים)"
    r"|מחליפ(?:ים|ות|ה|/ה)?\s+לחוזה"  # taking over the lease on the whole flat (batch 6)
    # v1.51 (from the 640 labeled listings): more ways a whole home is offered
    rf"|(?<![\d.]){_NUM}\s*(?:ו\s*חצי\s+)?(?:חדרים|חד['׳]|ח['׳](?=\s))"  # "4 ח' גדולים", "2 וחצי חדרים", "3 חד'"
    rf"|(?<![\d.])\d(?:\.5)?\s*חד(?![א-ת])"  # "3חד", "2.5 חד"
    rf"|(?<![\d.]){_NUM}\s*חדרי\s+שינה(?![א-ת])"  # v1.55 (census): "7 חדרי שינה" (17 of 17 in the 640: a whole home)
    r"|(?:ה)?(?:בית\s+פרטי|בית\s+קרקע|בית\s+(?:[א-ת]+\s+)?צמוד\s+קרקע|וילה|ווילה|קוטג['׳]?|דופלקס|פנטה(?:או|וא)(?:ז|ס)|סטודיו|דירת\s+פרטר)(?![א-ת])"  # v1.57: "בית קרקע", "בית צמוד קרקע"
    r"|יחידה\s+(?:[א-ת]+\s+){0,2}?(?:להשכרה|לבודד|ליחיד|לזוג)(?![א-ת])"  # not "יחידה 12.5 מ\"ר להשכרה" in a dorm (batch 8)
    r"|(?:מתאים|מתאימ(?:ה|ים|ות)|מושלמת|מושלם|אידיאלית|אידיאלי|מיועדת|מיועד)\s+(?:\S+\s+)?(?:ל)(?:זוג|זוגות|משפחה|משפחות|יחיד|בודד|בודדה)(?![א-ת])"
    # v1.56 (batch 10): a home for one person: "מתאים ליחיד" (the masculine was missed), "מיועד לאדם יחיד",
    # "השכרה לבן אדם יחיד בלבד", "לבודד/ת בלבד", "מתאימה לאדם אחד"
    # (not "אידיאלי לאדם יחיד או לזוג": batch 9's labelers read that as not saying)
    r"|(?<![א-ת])(?:מתאים|מתאימה|מיועד|מיועדת|השכרה|להשכרה)\s+ל(?:אדם|בן\s+אדם)\s+(?:אחד|יחיד|בודד)(?![א-ת])"
    r"|(?<![א-ת])ל(?:אדם|בן\s+אדם)\s+(?:אחד|יחיד|בודד)\s+בלבד(?![א-ת])|(?<![א-ת])ל(?:בודד|יחיד)(?:/ת|/ה|ה)?\s+בלבד(?![א-ת])"
    r"|(?<![א-ת])לא\s+לשותפים(?![א-ת])"
    # an ad that opens with "דירה" offers the flat: 137 of 137 labeled listings that do
    # were never a room share (a room's ad opens with "חדר")
    r"|^\W*(?:להשכרה[:\s,\-!]*)?(?:ה)?דירה(?![א-ת])"
    # v1.55 (batch 9): "דירת חמד ...", "להשכרה מפרטי בזבוטינסקי נתניה דירה גדולה", "להשכרה בבלעדיות בית מרווח",
    # "1-room apartment": the ad offers the home itself (a room's ad names the room)
    r"|^\W*(?:להשכרה[:\s,\-!]*)?(?:ה)?דירת\s+(?:חמד|פאר|יוקרה|נופש|בוטיק|חלומות|גג|גן|קרקע)(?![א-ת])"
    r"|^\W*להשכרה\s+(?:\S+\s+){1,4}?(?:ה)?(?:דירה|בית)\s+(?:גדול|גדולה|מרווח|מרווחת|יפה|מקסים|מקסימה|מהמם|מהממת|משופץ|משופצת|חדש|חדשה|פרטי|מואר|מוארת)(?![א-ת])"
    r"|^\W*(?:a\s+)?(?:\d+[\s\-]room|studio|whole)\s+apartment)"
)


# "a shared apartment" (דירת שותפים) is a room in one, unless the text only
# says the flat suits roommates ("מתאימה כדירת שותפים", "גם לדירת שותפים")
_SHARED_FLAT = re.compile(rf"(?<![א-ת])(ו?(?:ב|ל|ה|כ)?)דירת\s+(?:ה)?(?:{_NUM}\s+)?שותפים(?![א-ת])")  # "דירת 3 שותפים" too (v1.39)
_SUITS = re.compile(r"(?<![א-ת])(?:מתאימ|אידיאלי|מושלמ|מצוינ|מצויינ|נהדר|מעולה|גם|או)[א-ת]*\s*(?:\S+\s+)?$")
# the rent is per person: "2,600 ₪ לחדר", "המחיר לשותף", "לכל שותף חוזה בנפרד"
_PER_PERSON = re.compile(
    r"(?:\d[\d,]*\s*(?:₪|ש[\"״]?ח|שקל(?:ים)?)|₪\s*\d[\d,]*|(?<![א-ת])(?:ה?מחיר|שכ[\"״]?ד|ה?שכירות))"  # an amount or the rent, not any number
    r"\s*(?:\S+\s+){0,2}?(?:לחדר|לשותף|לשותפ/ה|לשותף/ה|לאדם|לנפש|לדייר)(?![א-ת])(?!\s+(?:יחיד|אחד|בודד)(?![א-ת]))"  # v1.56: "2500 שח מיועד לאדם יחיד" is one tenant, not per person
    r"|(?<![א-ת])לכל\s+(?:שותף|שותפה|דייר)(?![א-ת])"
)
# a statement that the whole flat is for rent; a room count or a size alone
# isn't one (a room-share post describes the flat it's in)
_WHOLE_STRONG = re.compile(
    r"(?<![א-ת])(?:ה?דירה\s+להשכרה|להשכרה\s+(?:ה?דירה|ה?דירת)|יחידת\s+דיור"
    r"|ה?דירה\s+(?:ל|מתאימה\s+ל)(?:יחיד|זוג|משפחה|זוגות)(?![א-ת])|מחליפ(?:ים|ות|ה|/ה)?\s+לחוזה"
    r"|(?:מתאים|מתאימ(?:ה|ים)?|מצוינת|מצויינת|מושלמת|אידיאלית|נהדרת)\s+(?:גם\s+)?לשותפים(?![א-ת]))"  # the whole flat, for roommates
)


def _shared_flat(text: str) -> Optional[str]:
    for m in _SHARED_FLAT.finditer(text):
        if not m.group(1).endswith("כ") and not _SUITS.search(_before(text, m.start(), 30)):
            return m.group()
    return None


# v1.60 (decision 0001): words that say the flat is shared, not only that a room is offered: roommates, a shared
# kitchen or bathroom, a room being vacated, rent per person, or the room's place in a flat of N rooms
_SHARING_SAID = re.compile(
    r"שות(?:ף|פה|פים|פות|פ/ה|ף/ה)(?![א-ת])|roommate|flatmate"
    r"|(?:מטבח|סלון|שירותים|מקלחת|מקלחות|אמבטיה|חדר\s+רחצה)\s+(?:ו\S+\s+)?(?:ה)?משותפ(?:ים|ת|ות)?(?![א-ת])"
    r"|(?:מתפנ|מפנ)(?:ה|ים|ות|ת)?\s+(?:\S+\s+)?חדר"
    r"|בדירת\s+(?:\d(?:[.,]5)?|שני|שתי|שלוש|ארבע|חמש|שש)\s+(?:חדרים|חד['׳]?)(?![א-ת])"
    r"|(?:דירה|בדירה|הדירה|בית|בבית)\s+(?:ה)?משותפ(?:ת)?(?![א-ת])|בדירה\s+של\s+\d+\s*(?:מ|מטר)"
    r"|(?:דייר|דיירת|דיירים)\s+(?:נוספ|אחר)", re.IGNORECASE)


def room_share(text: str) -> Optional[Answer]:
    yes = _ROOM_SHARE_YES.search(text)
    # v1.49: "תו חניה לכל דייר" (batch 7) is a parking permit per resident, not rent per person
    per = next((m.group() for m in _PER_PERSON.finditer(text) if not re.search(r"(?:חני|חנ(?:י)?ה|תו|ארנונה|ועד)", _before(text, m.start(), 20))), None)
    said = yes.group() if yes else (_shared_flat(text) or per)
    whole = _WHOLE_APARTMENT.search(text)
    if (yes and not whole and re.match(r"^\W*(?:להשכרה\s*:?\s*)?חדר", yes.group()) and not re.search(r"שות(?:ף|פ)", text)
            and (own := re.search(r"כניסה\s+(?:נפרדת|פרטית)|מטבחון", text))):
        return _unclear(said, own.group())  # v1.56: "חדר גדול, דלת כניסה למטבחון ... כניסה נפרדת" (batch 10): a room on its own, or in a flat
    if (yes and not per and not (whole and _WHOLE_STRONG.search(text)) and re.search(r"(?<![א-ת])(?:ה|ל|ב)?חדר(?![א-ת])", yes.group())
            and not _SHARING_SAID.search(text)):
        return _unclear(said)  # v1.60 (decision 0001): "a room" with nothing about sharing is inferred, not said: a check, never a reason to hide
    if said and not whole:
        return _ans("yes", said)
    if whole and not said and not _ROOMMATE_WORD.search(text):
        return _ans("no", whole.group())
    if said and whole:
        strong = _WHOLE_STRONG.search(text)
        if not strong:  # "חדר להשכרה בדירת 4 חדרים": the room count is the flat the room is in (v1.32)
            return _ans("yes", said)
        return _unclear(strong.group(), said)  # the text says both: a check, not silence a model could fill (v1.28)
    return None


# --- balcony ----------------------------------------------------------------------


# v1.49 (batch 7): a balcony the building only plans to add ("צפוי להתחיל בנייה של
# מרפסות"), or one taken into a room ("מרפסת נפתחה להרחבת הסלון"), isn't a balcony
# v1.55: no bare "פרויקט": a new building is a project, and its balconies are real ("בפרויקט ... מרפסת סוכה", batch 9)
_BALCONY_PLANNED = re.compile(r"(?:בנייה|בניית|בניה|צפוי|צפויה|צפויים|יבנו|ייבנו|יתווספו|(?<!ב)תוספת|הוספת|עתידית|עתידיות|"  # "בתוספת מרפסת" is "plus a balcony" (census)
                              r"תכנון|מתוכננ|תמ[\"״]?א|תוכנית)")
# v1.55 (batch 9): "מרפסת לא סוכה" denies the sukkah, not the balcony; "יש גם דירה נוספת עם מרפסת" is another flat's
_BALCONY_QUALIFIER_DENIED = re.compile(r"^\s*(?:לא|ללא|אינה)\s+(?:סוכה|מקורה|שמש|גדולה|ענקית|פתוחה|סגורה|שירות)(?![א-ת])")
_ANOTHER_FLAT = re.compile(r"(?<![א-ת])(?:דירה|יחידה|דירת\s+\S+)\s+(?:נוספת|אחרת|שכנה)\s+(?:עם|כולל|הכוללת|ש(?:יש)?\s*בה)\s*$")
_OTHER_FLATS = re.compile(r"(?<![א-ת])(?:וכן|ועוד|יש\s+גם)\s+(?:מגוון|עוד|מבחר)\s+(?:של\s+)?דירות(?![א-ת])[^.\n]*$")  # v1.58: "וכן מגוון דירות ... עם נוף,מרפסת" (batch 11): other flats
_BALCONY_GONE = re.compile(r"^\s*(?:ש)?(?:נפתחה|נפתחו|נסגרה|נסגרו|הוכנסה|חוברה|צורפה|סופחה|אוחדה)(?![א-ת])")


def balcony(text: str) -> Optional[Answer]:
    real, service, none, doubt = [], [], [], []
    for m in _matches(r"מי?רפס(?:ת|ות)|מרספ(?:ת|ות)", text):  # v1.51: "מירפסות", "מרספות"
        after = _after(text, m.end(), 12)
        if (_BALCONY_PLANNED.search(_before(text, m.start(), 40)) or _BALCONY_GONE.match(text[m.end():])
                or re.search(r"(?<![א-ת])(?:אפשרות|אופציה|ניתן)\s+(?:\S+\s+){0,5}$", _before(text, m.start(), 45))):  # v1.58: "אפשרות לסידור פינת ישיבה או מרפסת" (batch 11)
            b = _before(text, m.start(), 40).split()
            doubt.append((b[-1] + " " if b else "") + m.group())
            continue
        if re.search(r"(?<![א-ת])(?:ריהוט|רהיטי|רהיטים\s+ל|כיסאות|כסאות|שולחן)\s*$", _before(text, m.start(), 12)):
            doubt.append(_before(text, m.start(), 12).split()[-1] + " " + m.group())
            continue  # v1.64: "ריהוט מרפסת" in a furniture list (Komo batch 2): the labelers left the balcony unsaid
        if re.match(r"^\s*(?:ו\S+\s+)?(?:ה)?משותפ(?:ת|ות)(?![א-ת])", text[m.end():]):
            doubt.append(m.group() + _after(text, m.end(), 20).split(",")[0])
            continue  # v1.58: "מרפסת וגינה משותפות" (batch 11): shared, not the flat's own
        if _ANOTHER_FLAT.search(_before(text, m.start(), 40)) or _OTHER_FLATS.search(text[max(0, m.start() - 70) : m.start()]):
            doubt.append(_before(text, m.start(), 40).strip().split("(")[-1].strip() + " " + m.group())
            continue
        neg = None if _BALCONY_QUALIFIER_DENIED.match(text[m.end():]) else _negation(text, m.start())
        is_service = re.match(r"^\s*(?:ה?שירות|ה?שרות|ה?כביסה)(?![א-ת])", after)  # "מרפסת הכביסה" too (batch 5)
        phrase = m.group() + (is_service.group() if is_service else "")
        if neg == "adjacent":
            none.append(_before(text, m.start()).split()[-1] + " " + phrase)
        elif neg == "nearby":
            continue
        elif is_service:
            service.append(phrase)
        else:
            real.append(phrase)
    if not real:
        # v1.51: a roof of the flat's own, with a size or a word for it, is outdoor space too
        # ("+גג פתוח כ 60 מטר", "שטח גג פרטי", "גג עצום של כ-70 מ\"ר"); not "דירת גג" / "דופלקס גג" (the type)
        for m in re.finditer(r"(?<![א-ת])(?:\+|ו|עם\s+)?(?:שטח\s+)?גג\s+(?:פתוח|ענק|עצום|פרטי|גדול|צמוד|מרוצף|של\s+כ|כ[\-\s]?\d|\d)", text):
            if (not re.search(r"(?:דירת|דירות|דופלקס|ב|ל|משותף|גישה\s+ל)\s*$", text[max(0, m.start() - 12) : m.start()])
                    and _negation(text, m.start()) is None and not _BALCONY_PLANNED.search(_before(text, m.start(), 40))):
                real.append(m.group().lstrip("+").strip())
                break
    if real and none:
        return _unclear(real[0], none[0])
    if real:
        return _ans("yes", real[0])
    if service:
        return _ans("service_only", service[0])
    if none:
        return _ans("no", none[0])
    return _unclear(*doubt) if doubt else None


# --- furnished ------------------------------------------------------------------

_OFFER = re.compile(r"(?:אפשרות|אופציה|אופציונלי|אופציונאלי|ניתן|במידת\s+הצורך|לפי\s+בקשה|לבקשת|בתוספת|אם\s+צריך|במידה)")
# An offer with no furniture word the patterns below read: "אופציה לרהט",
# "אפשרות לריהוט", "ניתן לרהט לפי בקשה".
_OFFER_ONLY = re.compile(
    r"(?<![א-ת])(?:אפשרות|אופציה|ניתן)\s+(?:\S+\s+)?(?:ל|ב|ו)?(?:רהט|רהוט|ריהוט|רהיטים|לרהט|לרהוט)(?![א-ת])"
)
_PARTIAL = (r"(?:מרוהטת|מרוהט|מרהטת|מרהטתת|מרוהתת)\s+(?:ב[א-ת]{3,5}\s+)?(?:חלקית|חלקי)|(?:מרוהטת|מרוהט)\s+בחלק(?:ו|ה)(?![א-ת])|ר(?:י)?הוט\s+חלקי"  # v1.51: "מרוהטת באופן חלקי" (batch 8)
            r"|partly\s+furnished|partially\s+furnished|semi[\s\-]furnished"  # v1.55: "מרהטתת חלקית", English (batch 9)
            r"|ר(?:י)?הוט\s+(?:מועט|מינימלי|בסיסי)|(?<![א-ת])מעט\s+ר(?:י)?הוט|(?<![א-ת])חלק\s+מ(?:ה)?ר(?:י)?הוט")  # v1.56: "ריהוט מועט", "חלק מריהוט סלון" (batch 10)
# v1.51: "רהוט" spelled without the yod, "מרוהטות" (flats), "כולל כל הריהוט", "עם רהוט"
_FULL = (r"(?<![א-ת])ר(?:י)?הוט\s+(?:קומפלט|קופלט)(?![א-ת])|(?<![א-ת])כו?ל\s+(?:ה)?ר(?:י)?הוט(?![א-ת])|מרוהטות|מרוהטת|מרוהטים|מרוהט|מרהטת|(?:כולל|עם)\s+ר(?:י)?הוט\s+מלא|ו?ר(?:י)?הוט\s+(?:(?:איכותי|יפה|מעוצב|חדש)\s+)?(?:מלא|חדש)"  # "ריהוט חדש" (v1.53); v1.56: "מרוהטים קומפלט", "ריהוט איכותי מלא" (batch 10)
         r"|(?:כולל|כוללת|הכוללת|וכוללת|עם|יש\s+את)\s+(?:את\s+)?(?:כל\s+)?(?:ה)?ר(?:י)?הוט(?!\s+(?:ל|חלקי|חלקית|ה?מטבח|ה?מרפסת|ה?גינה|גן|חוץ)(?![א-ת]))"
         # v1.55 (batch 9): "כוללת ריהוט (ארונות, ...)", "תכולה מלאה" (not contents insurance), "ריהוט ואבזור מלא", English
         r"|(?<!ביטוח\s)(?:כולל\s+)?תכולה\s+מלאה|ר(?:י)?הוט\s+ו(?:א|אי|י)?בזור\s+מלא|fully\s+furnished|(?<!un)furnished(?!\s+room)")
_STAYS = re.compile(r"(?<![א-ת])(?:נשאר|נשארים|נשארת|יישאר|יישארו|ישאר|ישארו|משאיר|משאירים)\s+(?:בדירה\s+)?(?:ריהוט|רהיטים)(?![א-ת])")
# "מרוהטת" is the apartment's only if the clause is about the apartment (or
# starts with it), and the word right before isn't one room: "סלון מרוהט"
# is part of it, not "furnished".
_APARTMENT_WORD = re.compile(r"(?<![א-ת])[לבו]?(?:ה?דירה|ה?דירת|ה?דירות|יחידת|ה?יחידה|ה?נכס|ה?נכסים|ה?בית)(?![א-ת])"  # v1.56: "בית מרוהט" (batch 10)
                             r"|(?<![\d.])\d(?:\.5)?\s*(?:חד['׳]|חדרים)\s*$"  # "5 חד' מרוהטת" (v1.53, census)
                             r"|פירוט\s+ריהוט\s*:\s*$")  # v1.55: Yad2's own furniture field ("פירוט ריהוט: מרוהטת קומפלט", batch 9)
# v1.55 (batch 9): "מרוהטת קומפלט", "מרוהט לחלוטין", "מרוהט, ומאובזר": said of the whole home, whatever comes before
_WHOLE_HOME_AFTER = re.compile(r"^\s*,?\s*(?:קומפלט|קומפלייט|לגמרי|לחלוטין|במלואה|במלואו|באופן\s+מלא|ו?מאובזר(?:ת)?|ו?ממוזג(?:ת)?)(?![א-ת])")
_ROOM_WORD = re.compile(r"(?:חדר|חדרי|סלון|ה?שינה|ממ[\"״']?ד|ילדים|עבודה|הורים)$")
# "המטבח מרוהט ומאובזר" is the kitchen's equipment, often shared: no claim
# about the apartment's furniture either way (batch 5).
_KITCHEN_WORD = re.compile(r"ה?מטבח(?:ון)?$")


# "מוארת ומרוהטת", "משופצת, מרווחת ומרוהטת": an adjective chain that can
# only describe the apartment (a room is masculine: "סלון מרוהט").
_APARTMENT_ADJECTIVE = re.compile(r"(?:מסודרת|מוארת|משופצת|מרווחת|מאווררת|מטופחת|מעוצבת|שקטה|יפה|חדשה|שמורה|נקייה|מקסימה|ממוזגת|מאובזרת|מושקעת)[\s,]*$")  # v1.56: "מאובזרת, חדשה, ממוזגת ומרוהטת"


def _claims(text: str) -> tuple[list[tuple[int, str, str]], list[str]]:
    """What the text says about furnishing in general: (position, id,
    words) for each claim, and the offers seen (an offer isn't furniture)."""
    found: list[tuple[int, str, str]] = []
    doubts = [m.group() for m in _OFFER_ONLY.finditer(text)]
    for pattern, claim in ((_PARTIAL, "says_partly_furnished"), (_FULL, "says_furnished")):
        for m in _matches(pattern, text):
            if claim == "says_furnished" and re.match(r"^\s*(?:ב[א-ת]{3,5}\s+)?(?:חלקית|חלקי)(?![א-ת])|^\s*בחלק(?:ו|ה)(?![א-ת])", text[m.end() :]):
                continue  # counted as partial above
            if claim == "says_partly_furnished" and re.match(r"^[^\n.,;]{0,20}?(?:למסירה|למכירה|מכירה|לקנות|לקניה|לקנייה)", text[m.end() :]):
                continue  # v1.58: "חלק מהריהוט למסירה" is a sale offer, not the flat's furniture (batch 11)
            clause = _before(text, m.start(), 40) + m.group() + _after(text, m.end(), 40)
            if _OFFER.search(clause):
                doubts.append(m.group())
                continue  # an offer to furnish isn't furniture
            before = _before(text, m.start(), 40)
            words = m.group()
            listing_it = re.match(r"^\s*:", text[m.end() :])  # v1.53: "מרוהטת : מיטה זוגית, ארון ...": what follows is its list
            if claim == "says_furnished" and not listing_it and not m.group().lstrip("ו").startswith(("כולל", "עם", "יש", "ריהוט", "רהוט", "כל ", "כול ")):
                if _KITCHEN_WORD.search(before.rstrip()):
                    continue
                if ((re.search(r"(?<![א-ת])ה?חדר$", before.rstrip()) or re.match(r"^\s*(?:ה)?חדר(?![א-ת])", before))
                        and not _ROOM_WORD.search(before.rstrip().removesuffix("חדר").rstrip() or "x")
                        and (room_share(text) or {}).get("answer") == "yes"):
                    words = before.split()[-1] + " " + m.group()  # v1.51: the room IS what's rented: furnished (batch 8)
                elif _ROOM_WORD.search(before.rstrip()) and m.group().lstrip("ו") in ("מרוהטת", "מרהטת"):
                    words = before.split()[-1] + " " + m.group()  # v1.56: "5חד כולל ממד מרוהטת" (batch 10): the rooms are masculine, the flat isn't
                elif _ROOM_WORD.search(before.rstrip()):
                    claim, words = "says_partly_furnished", before.split()[-1] + " " + m.group()  # "סלון מרוהט": one room
                elif (before.strip() and not _APARTMENT_WORD.search(before) and not _NEG_ADJACENT.search(before)
                      and not _WHOLE_HOME_AFTER.match(text[m.end():])
                      and not ((m.group().startswith("ו") or m.group() in ("מרוהטת", "מרוהטות")) and _APARTMENT_ADJECTIVE.search(before))):
                    continue
            neg = _negation(text, m.start())
            if neg is None and claim == "says_furnished" and (eq := re.match(r"^\s*,?\s*ו(?:מאובזר|מאובזרת)(?![א-ת])", text[m.end():])):
                found.append((m.end(), "says_equipped", eq.group().strip(" ,")))  # v1.55: "מרוהט, ומאובזר" (batch 9)
            if neg == "adjacent" and claim == "says_furnished":
                found.append((m.start(), "says_unfurnished", _before(text, m.start()).split()[-1] + " " + m.group()))
            elif neg is None:
                found.append((m.start(), claim, words))
    for m in re.finditer(r"(?<![א-ת])ו?(?:ללא|בלי|אין)\s+(?:שום\s+)?(?:ריהוט|רהוט|רהיטים)(?![א-ת])|(?<![א-ת])דירה\s+ריקה(?![א-ת])"  # "וללא ריהוט" (v1.53)
                         r"|(?<![א-ת])ריק(?:ה|ים|ות)?\s+מ(?:כל\s+)?(?:ריהוט|רהוט|רהיטים)(?![א-ת])|unfurnished", text):  # v1.55 (batch 9)
        clause = _before(text, m.start(), 60) + m.group()
        if _OFFER.search(clause):
            doubts.append(m.group())  # "ניתן לקבל מרוהטת או ללא ריהוט": the tenant's choice, not a fact
            continue
        found.append((m.start(), "says_unfurnished", m.group()))
    for m in _STAYS.finditer(text):  # some furniture stays: partly furnished
        clause = _before(text, m.start(), 40) + m.group() + _after(text, m.end(), 40)
        if re.match(r"^\s*(?:חדש|איכותי)?\s*[-:–]", text[m.end():]):
            continue  # v1.58: "נשאר ריהוט חדש- תנור, מקרר, ..." heads the list (batch 11)
        if re.match(r"\s*(?:מלא|כולו|הכל)", text[m.end() :]):
            continue
        if _OFFER.search(clause):
            doubts.append(m.group())  # "במידת הצורך נשאר ריהוט": on request, not a fact
        else:
            found.append((m.start(), "says_partly_furnished", m.group()))
    for m in _matches(_EQUIPPED, text):
        clause = _before(text, m.start(), 40) + m.group() + _after(text, m.end(), 30)
        if re.search(r"(?<![א-ת])(?:לא|אינה|אינו|אינם|ללא|בלי)\s+(?:\S+\s+){0,3}$", _clause_before(text, m.start())):
            continue  # v1.58: "לא כולל מוצרי חשמל", "אינה כוללת ריהוט או מוצרי חשמל" (batch 11)
        if (m.group().startswith(("מוצרי", "מכשירי", "מכשרי")) and re.match(r"^\s*[-:–]", text[m.end():])
                and not _clause_before(text, m.start()).replace(_FIELD, "").strip()):
            continue  # v1.58: "מוצרי חשמל - טלויזיה, ..." heads a list; the list says what's there (batch 11)
        if m.group().endswith("מאובזרת") and re.match(r"^\s*ב[א-ת]+(?:\s+ו[א-ת]+)?\s*:", text[m.end():]):
            continue  # v1.61: "מאובזרת בתיחכום ונוחות: ממ\"ד / תריסים חשמליים" (batch 14): features, listed after it
        if m.group() == "מאובזרת" and _BATH_WORD.search(_before(text, m.start(), 15)):
            continue  # v1.60: "אמבטיה מאובזרת" (batch 13): the bathroom's fittings, not appliances
        if _OFFER.search(clause):
            doubts.append(m.group())
        elif _negation(text, m.start()) is None:
            found.append((m.start(), "says_equipped", m.group()))
    return found, doubts


# "מאובזרת" (feminine) agrees with the apartment; "מטבח מאובזר" is the
# kitchen's. Appliances in general words: "עם מוצרי חשמל", "כולל מכשירי חשמל".
_EQUIPPED = (r"מאובזרת|(?:מוצרי|מכשירי|מכשרי|דברי)\s+(?:ה)?חשמל"  # "ריהוט מלא ומוצרי חשמל" (batch 4); any "מוצרי חשמל" (v1.53)
             # v1.53: an equipped kitchen is appliances: 8 of 8 labeled texts that say it, where it isn't an offer
             # v1.55: "מטבח גדול ומאובזר", "מבוזר"; not "המטבח מרוהט ומאובזר" (the kitchen's own fittings, batch 5)
             r"|(?:מטבח|מטבחון)\s+(?:(?!מרוהט|חוץ(?![א-ת]))\S+\s+)?ו?(?:מאובזר|מאובזרים|מבוזר)(?![א-ת])"  # v1.59: not "מטבח חוץ מאובזר" (an outdoor kitchen, batch 12)
             r"|(?:עם|כולל)\s+כל\s+(?:ה)?מכשירים(?![א-ת])|(?:סטודיו|לופט)\s+(?:\S+\s+)?מאובזר(?![א-ת])"
             r"|ר(?:י)?הוט\s+ו(?:א|אי|י)?בזור\s+מלא|fully\s+equipped|(?<![א-ת])ו?ציוד\s+(?:ה)?חשמל(?:י)?|(?<![א-ת])מצו(?:י)?ידת\s+(?:קומפלט|קופלט)(?![א-ת])|(?<![א-ת])ו?(?:א|אי)בזור\s+מלא(?![א-ת])"  # v1.58: "שפע של ארונות ואבזור מלא:" (batch 11)
             r"|(?:(?<=[.:\n])|^)\s*מאובזר(?![א-ת])")  # v1.56: "ריהוט איכותי מלא. מאובזר ומוכן" (batch 10): the flat, unsaid

# The things a listing can say come with it. Each is read only where the
# rules are sure: "פינת אוכל" is as often the dining AREA as a table, and
# "ספרייה" the library down the street, so neither is read here.
_ITEMS: tuple[tuple[str, str], ...] = (
    ("bed", r"מיטה|מיטות|מיטת|מיטה\s+זוגית|ניטה\s+זוגית"),  # v1.58: typo "ניטה זוגית" (batch 11)  # v1.55: "מיטת ספה", "מיטת יחיד" (batch 9)
    ("sofa", r"ספה|ספת|ספות|כורסה|כורסא|כורסאות|כורסות|מערכת\s+ישיבה|שזלונג"),  # v1.56: "ספת סלון", "שזלונג" (batch 10)
    ("table_chairs", r"שולחן|שולחנות|כסאות|כיסאות|כסא|כיסא|שלוחן"),  # v1.55: one chair, "שלוחן" (batch 9)
    ("cabinet", r"מזנון|מזנונים|מיזנון|שידה|שידות|שידת\s+(?:טלוויזיה|טלויזיה|סלון|לילה|איפור|מגירות|מיטה)|קומודה|קומדה|כוננית|כונניות|ארונית(?!ות)"),  # v1.58: "ארונית" is a cabinet; plural "ארוניות" stays closets (batch 9) (batch 11's labelers)  # v1.53: "שידת מגירות"; v1.56: "מיזנון", "שידת מיטה", "כוננית" (batch 10)
    ("fridge", r"מקרר|מקררים"),
    ("washer", r"מכונתכביסה|מכונת\s*,?\s*כביס[הא]|מכונות\s+כביסה|מ[.'׳]\s*כביסה|מכונה(?=\s+ו(?:מ)?י?יבש\s+כביסה)"),  # v1.55 (census): "מ. כביסה"; v1.56: "מכונה ומייבש כביסה" (batch 10)
    ("dryer", r"מי?יבש(?:\s+כביסה)?"),  # "מיבש" too (v1.53)
    ("dishwasher", r"מדיח(?:\s+כלים)?|מדיחים"),
    ("microwave", r"מיקרוגל|מיקרו|מקרוגל"),  # v1.53: "מקרר מיקרו תנור", "מקרוגל"
    ("tv", r"טלוויזיה|טלויזיה|טלוויזיות|טלויזיות|טלביזיה|טלבזיה|טלוזיה|טל[וי]{1,4}זי?(?:ה|ות)|פלזמה"),  # v1.56: "טליוייזיה", "טלוויזה", "פלזמה" (batch 10)
    ("closets", r"ארוניות|ארון|ארונות|ארונות\s+קיר|ארון\s+קיר|אורנות|הרון"),  # v1.56: "הרון" (batch 10)
    # v1.49: no bare "כירה": with a prefix it read "למכירה" (for sale) as a stove (batch 7)
    ("oven_stove", r"תנור|תנורים|כיריים|כריים|כירים|אינדוקציה"),  # v1.58: "כיריים אינדוקציה", a bare "אינדוקציה" (batch 11)
)
# The kitchen's own cabinets aren't closets; "a room suitable for closets"
# isn't closets either.
_KITCHEN_NEAR = re.compile(r"(?:מטבח|המטבח)")
# Nor is a bathroom's: "מקלחת משופצת כולל ארון" (batch 6), "ארון אמבטיה".
# Only within the same clause, so "מקלחת ושירותים, ארונות קיר" still counts.
_BATH_WORD = re.compile(r"(?:מקלחת|מקלחון|אמבטיה|אמבט|חדר\s+רחצה|שירותים)")
_NOT_THERE = re.compile(r"(?:מתאים|מתאימה|הכנה|הכנות|חיבור|חיבורים|מקום|מיקום|נישה|נישת|להעמיד|להציב|לשים|מתחם|עבור)")  # v1.62: "מתחם לחדר ארונות, עבור ארונות שרוכשים השוכרים" (Komo batch 1)
# v1.49: furniture or appliances offered for sale don't come with the apartment.
# "רוב הריהוט ומוצרי החשמל מוצעים למכירה" (batch 7) was read as included.
_FOR_SALE = re.compile(
    r"(?<![א-ת])(?:ו?(?:ה)?מוצע(?:ים|ות|ת)?\s+)?[לב]מכירה(?![א-ת])"
    r"|(?<![א-ת])(?:ניתן|אפשר|אפשרות)\s+(?:ל)?(?:קנות|קנייה|רכוש|רכישה|לקנות|לרכוש|לרכישה)(?![א-ת])"
    r"|(?<![א-ת])(?:ל|ו)?(?:נמכר(?:ים|ת|ות)?|למכור)(?![א-ת])"
    r"|(?<![א-ת])ו?(?:מוכר|מוכרים|מוכרת)\s+את(?![א-ת])"  # "מוכר" alone is also "familiar"
)
# a shared facility's machines aren't the apartment's
_THE_BUILDINGS = re.compile(r"(?<![א-ת])(?:ל|ב)?(?:דיירי|שימוש\s+(?:ה)?דיירים)(?![א-ת])")
# v1.55 (batch 9): a laundry room is the building's only when the sentence says so ("בבניין יש חדר כביסה עם מכונות");
# "חדר כביסה עם מכונת כביסה ומייבש" in a flat's own list is the flat's
_LAUNDRY_ROOM = re.compile(r"חדר\s+כביסה|מכבסה")
_BUILDING_SAID = re.compile(r"(?<![א-ת])(?:ב|ל|ה)?(?:בני(?:י)?ן|ביניין|מגדל|פרויקט|פרוייקט|מתחם)(?![א-ת])|משותפ(?:ים|ת|ות)?(?![א-ת])|דיירים")
# v1.56: a clause that lists what the rent includes ("המחיר כולל ארנונה, מים, אינטרנט וטלוויזיה")
_SERVICES_IN_PRICE = re.compile(r"(?:כולל|כוללת|כוללים|כלול|כלולה|כלולים)(?![א-ת])(?=[^.!?\n]*(?:ארנונה|מים|אינטרנט|חשמל|כבלים|ועד|גז))")


def _clause_before(text: str, at: int) -> str:
    """The words from the start of the sentence (or line) up to a position."""
    start = max(text.rfind(c, 0, at) for c in ".!?\n") + 1
    return text[start:at]


_KITCHEN_IN_CLAUSE = re.compile(r"(?<![א-ת])(?:ה|ו|ב)?מטבח(?:ון)?(?![א-ת])[^,;]*$")  # v1.58: the kitchen is what this clause is about
_FIELD = "פירוט ריהוט:"  # v1.55: Yad2's furniture field, appended to the text by the pipeline
_FURNITURE_WORDS = r"ריהוט|רהיטים|רהיט|(?:מוצרי|מכשירי)\s+(?:ה)?חשמל|" + "|".join(p for _, p in _ITEMS)
_SENTENCE = re.compile(r"[^.!?\n;]+")


def furniture_for_sale(text: str) -> Optional[Answer]:
    """v1.49: a sentence that offers furniture or appliances for sale. Then
    they aren't the apartment's: the card says so, and furniture() leaves
    what that sentence names out of what comes with it."""
    for s in _SENTENCE.finditer(text):
        sentence = s.group()
        if _FOR_SALE.search(sentence) and re.search(rf"{_PRE}(?:{_FURNITURE_WORDS}){_END}", sentence):
            return _ans("yes", sentence.strip())
    return None


def _sale_spans(text: str) -> list[tuple[int, int]]:
    return [(s.start(), s.end()) for s in _SENTENCE.finditer(text)
            if _FOR_SALE.search(s.group()) and re.search(rf"{_PRE}(?:{_FURNITURE_WORDS}){_END}", s.group())]


def _items(text: str) -> tuple[list[tuple[int, str, str]], list[str]]:
    found: list[tuple[int, str, str]] = []
    doubts: list[str] = []
    for item, pattern in _ITEMS:
        for m in _matches(pattern, text):
            before, after = _before(text, m.start(), 30), _after(text, m.end(), 15)
            if item == "tv" and re.search(r"(?:שידת|פינת|מזנון|מזנוני|ארון|מעמד|זרוע|ספת|שולחן|כורסת)\s*(?:ל|ה|ל?ה)?\s*$", before):  # v1.58: "ספת טלוויזיה", "שולחן לטלוויזיה" (batch 11)
                continue  # a TV stand is a cabinet; a TV corner is a space; v1.55: "מזנון טלוויזיה" (batch 9's wrong answer)
            if item == "tv" and re.search(r"(?:(?<![א-ת])ח[.'׳]|(?<![א-ת])חדר)\s*(?:[א-ת]+\s*/\s*)?$", text[max(0, m.start() - 25) : m.start()]):
                continue  # v1.60: "ח. משפחה/ טלויזיה" (batch 13): a TV room, not a set
            if item == "tv" and (re.search(r"(?:כבלים|ערוצי|ערוץ|צפי(?:י)?ה\s+ב(?:ערוצי)?|אינטרנט)\s*ו?ה?\s*$", before)
                                 or _SERVICES_IN_PRICE.search(_clause_before(text, m.start()))):
                continue  # v1.56: "המחיר כולל ארנונה, מים, כבלים טלויזיה" (batch 10's 3 wrong answers): the service, not a set
            if item in ("washer", "dryer") and re.search(r"פינ(?:ת|ה)\s+(?:ה)?(?:כביסה|כבסים)\s*/?\s*ו?$", before):
                continue  # v1.56: "פינת כביסה/מייבש" (batch 10): a corner for it, not it
            if item == "table_chairs" and re.match(r"^\s*ל?(?:ה)?(?:טלוו?יזיה|טלויזיה|טלביזיה|מחשב\s+ו)", after):
                continue  # v1.58: "שולחן לטלוויזיה" (batch 11) is a TV stand
            if item == "closets" and (cb := text[text.rfind("\n", 0, m.start()) + 1 : m.start()]).count("(") > cb.count(")") and _KITCHEN_IN_CLAUSE.search(cb.rsplit("(", 1)[0]):
                continue  # v1.59: "מטבח קבלן עם תוספות (אי ..., וארונות אחסון נוספים)" (batch 12): the kitchen's own
            if item == "closets" and (re.match(r"^\s*(?:ה)?חשמל(?![א-ת])", after) or _KITCHEN_IN_CLAUSE.search(_clause_before(text, m.start()))
                                      and not re.match(r"^\s*(?:ה)?(?:בגדים|קיר|הזזה)(?![א-ת])|^[^,;\n]{0,12}?(?<![א-ת])ב(?:\S+\s+)?(?:ה)?(?:חדר|חדרים|חדרי)(?![א-ת])", _after(text, m.end(), 25))):
                continue  # v1.58: "ארונות חשמל" (electrical), "מטבח גדול עם שפע של ארונות" (the kitchen's) (batch 11)
            if ((re.search(r"(?<![א-ת])(?:מלבד|חוץ\s+מ|פרט\s+ל|למעט)\s*(?:ה)?\s*$", before)
                 or (re.search(r"(?<![א-ת])חוץ\s*$", before) and m.group().startswith("מ")))  # v1.60: "חוץ מטלויזיה" (batch 13)
                    and not re.search(r"(?<![א-ת])(?:לא|ללא|אין|בלי)(?![א-ת])", _clause_before(text, m.start()))):
                continue  # v1.59: "ריהוט מלא מלבד טלוויזיות", "מרוהט מלבד מכונת כביסה" (batch 12): everything except it
            if item != "tv" and re.search(r"(?<![א-ת])(?:אפשרות|אופציה)\s+[^.\n]{0,70}?(?<![א-ת])(?:כגון|כמו|למשל)(?![א-ת])[^.\n]{0,60}$", _clause_before(text, m.start())[-90:]):
                continue  # v1.59: "אפשרות להשארת ריהוט נוסף כגון ... ספה, פינת אוכל" (batch 12): offered, not there
            if item == "closets" and re.match(r"^\s*(?:\S+\s+)?(?:ה)?(?:עליונים|תחתונים|שירות|אחסון|מזווה)(?![א-ת])", after + _after(text, m.end() + len(after), 15)):
                continue  # v1.60: "ארונות עליונים מטבח", "מספר ארונות שירות ומקום אחסון" (batch 13): cupboards, not wardrobes
            if item == "closets" and re.search(r"(?<![א-ת])כיור\s*$", before):
                continue  # v1.59: "אסלה תלויה כיור ארון" (batch 12): a sink cabinet
            if m.group().startswith("ו") and re.search(r"(?<![א-ת])ל(?:מכונ(?:ת|ות)|מדיח|מקרר|מייבש|מיבש)[^,.;:\n]{0,15}$", before):
                continue  # v1.61: "תשתית/מחסן למכונת כביסה ומייבש" (batch 14): the "for" covers the dryer too
            if (gap := re.search(r"(?<![א-ת])(?:חסר(?:ה|ים|ות)?)\s*:?\s+((?:\S+\s+){0,4})$", _clause_before(text, m.start())[-50:])) and not re.search(r"(?<![א-ת])(?:חוץ|מלבד|אבל|אך|יש|רק)(?![א-ת])", gap.group(1)):
                continue  # v1.62: "חסר מקרר תנור גז" (Komo batch 1): missing, not there
            if item == "fridge" and re.match(r"^\s*את(?![א-ת])", after):
                continue  # v1.61: "מזגן ... שמקרר את כל הבית" (batch 14): the verb "cools"
            if re.search(r"(?<![א-ת])(?:לא|אינם|אינו|אינה|אינן)\s+(?:כלול(?:ים|ה|ות)?|נכלל(?:ים|ת|ות)?|כוללת|כולל)\s*:[^.\n]*$", text[: m.start()]):
                continue  # v1.61: "לא כלולים: ריהוט הסלון, ... תנור ומיקרוגל" (batch 14): what isn't there
            if item == "fridge" and re.match(r"^\s*(?:ה)?(?:יין|יינות|משקאות)(?![א-ת])", after):
                continue  # v1.55: a wine fridge isn't the fridge (batch 9)
            if item == "closets" and ((_KITCHEN_NEAR.search(before[-15:]) and not (m.group().startswith("ו") and re.search(r"מטבח(?:ון)?\s*$", before)))  # v1.56: "ארונות מטבח וארון גדול בחדר" (batch 10)
                                      or re.match(r"^\s*ב?(?:ה)?מטבח", after)
                                      or re.search(r"חדר(?:\s+\S+)?\s*/\s*$|(?<!כל\s)חדר\s*$", before) and not (m.group() == "ארונות" and re.search(r"(?<![א-ת])חדר\s*$", before))):  # "לחדר עבודה/ארונות" (batch 8); v1.56: not "בכל חדר ארון"; v1.59: "חדר ארונות" is a walk-in closet (batch 12)
                continue  # kitchen cabinets, or a walk-in "closet room"
            if item == "closets" and not re.match(r"^\s*(?:ה)?בגדים(?![א-ת])", after) and (_BATH_WORD.search(re.split(r"[,.;:\n!]", before)[-1])  # "ארון בגדים" is never the bathroom's (v1.55 census)
                                      or re.match(r"^\s*(?:ה)?(?:אמבטיה|אמבט|מקלחת)", after)):
                continue  # the bathroom's cabinet
            if _NOT_THERE.search(before[-20:]) or re.search(r"(?:מתאים|מתאימה)", before):
                continue  # "הכנה למכונת כביסה", "מתאים לחדר ארונות": a place for it, not it
            if m.group().startswith("ל"):
                continue  # v1.49: "למכונת כביסה" is FOR one; in all 463 labeled listings, never the item itself
            sentence = next((s.group() for s in _SENTENCE.finditer(text) if s.start() <= m.start() < s.end()), "")
            if _THE_BUILDINGS.search(sentence) or (_LAUNDRY_ROOM.search(sentence) and _BUILDING_SAID.search(sentence)):
                doubts.append(sentence.strip())  # v1.51: "בבניין יש חדר כביסה עם מכונות כביסה": the building's (batch 8)
                continue
            clause = _before(text, m.start(), 40) + m.group() + _after(text, m.end(), 40)
            if _OFFER.search(clause):
                doubts.append(m.group())
                continue
            if _negation(text, m.start()) is not None and not re.search(r"(?<![א-ת])(?:מלבד|חוץ\s+מ|פרט\s+ל|למעט)\s*(?:ה)?\s*$", before):
                continue  # "ללא מקרר" says what's missing; this list only names what's there; v1.59: "לא מרוהטת למעט ארון": the exception is there
            found.append((m.start(), item, m.group()))
    field = text.find(_FIELD)
    if field >= 0:  # v1.55: in Yad2's furniture field, "פינת אוכל" is the table (both batch 9 texts that list it there)
        for m in re.finditer(r"(?<![א-ת])ו?פינת\s+(?:ה)?אוכל(?![א-ת])", text[field:]):
            if (re.search(r"(?<![א-ת])(?:בקיר|ליד|מול|מעל|מתחת\s+ל|של|שב)\s*$", _before(text, field + m.start(), 15))
                    or re.search(r"(?<![א-ת])מטבח\s*,?\s*$", _before(text, field + m.start(), 12))
                    or re.match(r"^\s*,?\s*ו?(?:ה)?סלון(?![א-ת])", text[field + m.end():])):  # v1.58: "מטבח פינת אוכל וסלון" lists rooms (batch 11)
                continue  # v1.56: "ארון מזווה מובנה בקיר פינת אוכל" (batch 10's wrong answer): where something is
            if re.search(r"(?<![א-ת])(?:אפשרות|אופציה)\s+[^.\n]{0,70}?(?<![א-ת])(?:כגון|כמו|למשל)(?![א-ת])[^.\n]{0,60}$", text[max(0, field + m.start() - 90) : field + m.start()].split("\n")[-1]):
                continue  # v1.59: "אפשרות להשארת ריהוט נוסף כגון ... פינת אוכל" (batch 12)
            if _negation(text, field + m.start()) is None:
                found.append((field + m.start(), "table_chairs", m.group()))
    return found, doubts


_CONTRARY = ({"says_unfurnished", "says_furnished"}, {"says_unfurnished", "says_partly_furnished"},
             {"says_furnished", "says_partly_furnished"})


# v1.60 (decision 0001): the words that most often name something else (kitchen and storage cupboards, a dining
# AREA, a TV service or stand: most of furniture's 28 wrong answers on batches 10-13). One of them alone, in a text that
# names no other furniture and no furnishing word, isn't a furniture claim (a wardrobe, "ארון קיר/בגדים", still is)
_LOOSE = {"table_chairs", "tv"}  # closets: see _CUPBOARD (a lone "ארונות בחדרים" is right 23 times in the labeled sets)
_FURNISHING = re.compile(r"ר(?:י)?הוט|רהיט|מרוהט|מרהט|מאובזר|(?:מוצרי|מכשירי)\s+(?:ה)?חשמל|(?<![א-ת])(?:כולל|כוללת|נשאר|נשארת|נשארים|ישאר|יישאר|יישארו|תכולה)(?![א-ת])|furnish", re.IGNORECASE)


def _furnishing_said(text: str, item: tuple[int, str, str], found: list[tuple[int, str, str]]) -> bool:
    pos, kind, words = item
    if any(k != kind for _, k, _ in found):
        return True  # the text names other furniture: this word is part of what it lists
    field = text.find(_FIELD)
    if field >= 0 and pos > field and len(text[field + len(_FIELD):].split()) <= 4:
        return True  # Yad2's furniture field holding a short list: "פירוט ריהוט: ארון"
    return bool(_FURNISHING.search(text.replace(_FIELD, "")))


def furniture(text: str) -> Optional[Answer]:
    """The general claims and the named items, as one list. A claim the
    text contradicts ("מרוהטת ... ללא ריהוט") makes it unclear; an offer
    only does when nothing is actually there."""
    claims, doubts = _claims(text)
    items, item_doubts = _items(text)
    sale = _sale_spans(text)
    if sale:  # v1.49: what's offered for sale doesn't come with the apartment
        inside = lambda pos: any(a <= pos < b for a, b in sale)
        claims = [c for c in claims if not inside(c[0])]
        items = [c for c in items if not inside(c[0])]
        doubts = doubts + [text[a:b].strip() for a, b in sale]
    items = [it for it in items if it[1] not in _LOOSE or _furnishing_said(text, it, claims + items)]  # v1.60 (decision 0001)
    ids = {i for _, i, _ in claims}
    if any(pair <= ids for pair in _CONTRARY):
        return _unclear(*(w for _, i, w in sorted(claims) if i in {"says_unfurnished", "says_furnished", "says_partly_furnished"}))
    found = sorted(claims + items)
    if not found:
        return _unclear(*doubts, *item_doubts) if doubts or item_doubts else None
    return _ans("items", " ... ".join(dict.fromkeys(w.strip() for _, _, w in found)),
                items=sorted({i for _, i, _ in found}))


# --- apartment type -------------------------------------------------------------

_TYPES: tuple[tuple[str, str], ...] = (
    ("roof", r"דירת\s+גג|דירות\s+גג|(?:מיני\s*)?פנט[אה]{1,2}(?:או|וא|ו)(?:ז|ס)"  # "פנטהואז" (batch 4), "פנטאהוז" (batch 8), "מיניפנטהאוס" (batch 9)
             r"|דופלקס[\s\-]+גג|דירה\s+על\s+ה?גג"),  # v1.51: "דופלקס גג" is a roof duplex (batch 8)
    ("garden", r"דירת\s+גן|דירות\s+גן"),
    ("unit", r"יחידת\s+ה?דיור|יחידות\s+דיור|יחידת\s+סטודיו|(?<![א-ת])יח[\"״]ד(?![א-ת])"),  # v1.60: "יח\"ד" (batch 13)  # v1.59: "יחידת הדיור", "יחידת סטודיו" (batch 12)
    ("house", r"בית\s+פרטי|קוטג['׳]?|וילה|בית\s+(?:[א-ת]+\s+){0,3}?על\s+(?:ה)?מגרש|בית\s+קרקע"
              r"|בית\s+(?:[א-ת]+\s+)?צמוד\s+קרקע|בית\s+(?:חד|דו)[\s\-]?משפחתי|להשכרה\s+(?:חד|דו)[\s\-]?משפחתי(?![א-ת])"
              r"|(?:^|(?<=[\n\-•]))[ \t\-•]*(?:חד|דו)[\s\-]?משפחתי(?![א-ת])"),  # v1.58: a line that opens "- דו משפחתי 6 חדרים" (batch 11)  # Owner ruling (Nov 2): "בית פרטי/קרקע" are the words for a private home; "בית צמוד קרקע", "בית חד משפחתי"  # v1.55: "בית על מגרש חצי דונם" (batch 9); v1.56: "בית קרקע", "בית מיוחד במינו על מגרש" (batch 10)
    ("duplex", r"דופלקס|דירה\s+(?:ב|על\s+)?(?:שתי|שני|2)\s+(?:קומות|מפלסים)"
               r"|(?<![\d.])(?:2|3|שני|שתי|שלושה|שלוש)\s+מפלסים"  # v1.51: "בית ... 3 מפלסים" (batch 8)
               r"|(?:^|(?<=[\n.]))[ \t]*(?:2|שתי|שני)\s+קומות[ \t]*(?=[.\n]|$)"),  # v1.55: a line that says only "2 קומות." (batch 9)
    ("studio", r"סטודיו(?!\s*=)"),  # v1.64: "סטודיו=(סלון+מטבח) + חדר שינה" names a layout, not the flat's type (Komo batch 2)
)


# v1.51: a ground floor, and on the same line a garden or yard that's the flat's own ("יציאה לחצר
# פרטית", "עם גינה", "מוקפת בגינה פרטית"); not "חלון לגינה" (a view) or "שימוש בחצר" (use of one)
_GROUND_GARDEN = re.compile(
    r"(?<![א-ת])(?:דירת|קומת|בקומת)\s+(?:ה)?קרקע(?![א-ת])[^\n]{0,60}?"
    r"(?:יציאה\s+ל|עם\s+|מוקפת\s+ב|ו)(?P<yard>(?:ה)?(?:חצר|גינה))(?![א-ת])(?!\s+(?:משותפת|של\s+הבניין|ציבורית))")
_OPTION_OF = re.compile(r"(?:אפשרות|אופציה|אופציונלי|ניתן|פוטנציאל|הכנה)\s+(?:\S+\s+)?(?:ו?[לב])?(?:ה)?$")


# v1.56 (batch 10): "בית פרטי ... בנוסף יחידת דיור", "פלוס יחידת דיור", "הבית 6 חד + יחידת דיור",
# "יש יחידת דיור בנוסף": a house that also has a unit, not a unit (4 wrong answers in the text reading)
_EXTRA_BEFORE = re.compile(r"(?:(?<![א-ת])(?:בנוסף|פלוס|ועוד|וגם)|\+)\s*(?:ל)?$")
_HOUSE_SAID = re.compile(r"(?<![א-ת])(?:ה)?(?:בית|וילה|ווילה|קוטג|(?:חד|דו)[\s\-]?משפחתי)(?![א-ת])")


def _extra_unit(text: str, m: re.Match[str]) -> bool:
    """v1.56: a unit the text adds to a house it's renting ("בית ... בנוסף יחידת דיור")."""
    return bool((_EXTRA_BEFORE.search(_before(text, m.start(), 20)) or re.match(r"^\s*(?:\S+\s+){0,2}?בנוסף(?![א-ת])", text[m.end():])
                 or (m.group().startswith("ו") and _HOUSE_SAID.search(text[max(0, text.rfind("\n", 0, m.start()) + 1, m.start() - 80):m.start()]))  # v1.61: "בית גדול ... 5.5 חדרים, ויחידת דיור" (batch 14)
                 or re.match(r"^\s*(?:\S+\s+){0,3}?נפרד(?:ת)?(?![א-ת])", text[m.end():]))  # v1.59: "בית פרטי ... יחידת דיור נפרדת" (batch 12)
                and _HOUSE_SAID.search(text[: m.start()]))


def _option_before(text: str, m: re.Match[str]) -> bool:
    """v1.55: the words before a match (with the match's own prefix letters) offer it as an option."""
    pre = re.match(r"^[ולבהמש]*(?=י)", m.group())
    return bool(_OPTION_OF.search(_before(text, m.start(), 30) + (pre.group() if pre else "")))
_LIKE = re.compile(r"(?<![א-ת])(?:כמו|בסגנון|תחושת|תחושה\s+של|הרגשת|הרגשה\s+של|אווירת|אווירה\s+של)\s*$")
_YARD_UP = re.compile(r"(?<![א-ת])(?:ב)?קומה\s+(?:אחרונה|עליונה)(?![א-ת])(?=[^.\n]{0,80}(?<![א-ת])(?:ל|ב|ו)?(?:ה)?חצר)"
                      r"|(?<![א-ת])(?:ל|ב|ו)?(?:ה)?חצר(?![א-ת])(?=[^.\n]{0,80}(?:ב)?קומה\s+(?:אחרונה|עליונה)(?![א-ת]))")


def apartment_type(text: str) -> Optional[Answer]:
    """In the order above, the first type found wins: a roof apartment on
    two floors is roof, a unit in a private house is unit. A roof apartment
    that is also a garden apartment can't be: unclear."""
    found: dict[str, str] = {}
    in_house = False
    roof_floor = ""
    house_in = ""
    for kind, pattern in _TYPES:
        for m in _matches(pattern, text):
            if kind == "house" and (m.group().startswith("כ") or _LIKE.search(_before(text, m.start()))):
                continue  # v1.51: "דירה שהיא כמו בית פרטי" is a flat (batch 8)
            if kind == "unit" and "יחידות" in m.group():
                continue  # v1.55 (census): "וילה ... + שתי יחידות דיור נפרדות": a house that has units, not a unit
            if kind == "house" and m.group().startswith("ב") and re.search(r"(?<![א-ת])(?:ה)?יחיד(?:ה|ת)(?![א-ת])", text[text.rfind("\n", 0, m.start()) + 1 : m.start()]):
                found.setdefault("unit", m.group())
                in_house = True
                continue  # v1.60: "יחידה יפה ... כניסה נפרדת בבית פרטי" (batch 13): a unit IN a house
            if kind == "house" and re.match(r"^ב(?:בית|וילה|ווילה|קוטג)", m.group()):
                in_house = True
                house_in = house_in or m.group()
                continue  # v1.60: "קומת קרקע ... בבית פרטי", "יח\"ד בוילה" (batch 13): a place IN a house, not the house
            if kind == "house" and re.search(r"(?<![א-ת])(?:מעל|מתחת(?:\s+ל)?|ליד|מול|סמוך\s+ל|בסמוך\s+ל|צמוד\s+ל|שכונת|בשכונת)\s*$", _before(text, m.start(), 20)):
                continue  # v1.55 (census): "דירה ... מעל בית פרטי" is a flat above one
            if kind == "roof" and re.search(r"(?<![א-ת])(?:ב)?קומת\s*(?:ה)?$", _before(text, m.start(), 20)):
                roof_floor = roof_floor or (_before(text, m.start(), 20).split()[-1] + " " + m.group())
                continue  # v1.60: "(קומת פנטהאוז)" (batch 13): a penthouse floor describes the level; the flat may not be one
            if kind == "roof" and re.search(r"(?<![א-ת])(?:לפני|אחרי|מתחת(?:\s+ל)?)\s*$", _before(text, m.start(), 20)):
                continue  # v1.59: "בקומה הכי גבוהה לפני הפנטאהוז" (batch 12): the floor below it
            if kind == "unit" and _option_before(text, m):
                continue  # v1.55: "עם אפשרות ליחידת דיור נפרדת" is an option on a house, not a unit (batch 9's wrong answer)
            if kind == "unit" and _extra_unit(text, m):
                continue  # v1.56: a house plus a unit (batch 10)
            if _negation(text, m.start()) is None:
                found.setdefault(kind, m.group())
    if "roof" in found and "garden" in found:
        return _unclear(found["roof"], found["garden"])
    if "unit" in found and "house" not in found and not in_house and (y := re.search(r"(?<![א-ת])(?:ו|ה)?(?:חצר|גינה)\s+פרטית(?![א-ת])|(?:דירת|קומת|בקומת)\s+(?:ה)?קרקע\s+עם\s+(?:ה)?(?:חצר|גינה)", text)):
        return _unclear(found["unit"], y.group())  # v1.56: a unit with its own yard is a garden flat too (batch 10's labelers read both)
    if not found and (g := _GROUND_GARDEN.search(text)) and _negation(text, g.start("yard")) is None:  # Owner ruling (Nov 2): a room "בקומת קרקע-עם חצר" is a garden flat too
        return _ans("garden", g.group())  # v1.51: a ground-floor flat with its own garden or yard
    if not found and (y := _YARD_UP.search(text)):
        return _unclear(y.group())  # v1.49: a yard on the top floor is a roof terrace, not a garden flat (batch 7)
    for kind, _ in _TYPES:
        if kind in found:
            return _ans(kind, found[kind])
    if roof_floor:
        return _unclear(roof_floor)
    if house_in:
        return _unclear(house_in)  # in a house, but which part of it isn't said
    return None


# --- a unit in someone's home (v1.39) ---------------------------------------------

# A home carved out of someone else's: a housing unit (יחידת דיור), a flat inside a
# private house, a divided apartment (מחולקת / מפוצלת), a compound of small units.
# the first test search showed them as ordinary flats: nothing read them as a kind of
# home to keep out. Negated ("לא מחולקת", "ולא מפוצלת") they say the opposite.
_UNIT = (
    r"יחיד(?:ת|ות)\s+דיור",
    r"(?:\d|שתי|שלוש|ארבע|חמש|שש)\s+יחידות",
    r"בכל\s+יחידה",
    r"יחידה\s+(?:בחצר|צמודה|בבית|עם\s+כניסה\s+נפרדת)",
    r"בבית\s+פרטי|בוילה|בווילה|בקוטג['׳]?",
    r"(?:ה?דירה\s+)?(?:מחולקת|מפוצלת)(?!\s+(?:בצורה|היטב|יפה|נכון|ל))",  # not "מחולקת בצורה מדהימה" (a layout)
    r"חלק\s+מ(?:בית|וילה|ווילה|דירה)",
    r"בעל(?:י|ת)?\s+ה?בית\s+(?:גר|גרה|גרים|מתגורר|מתגוררת|מתגוררים)",
)
_UNIT_RE = "|".join(_UNIT)


def housing_unit(text: str) -> Optional[Answer]:
    """"yes" (a unit in someone's home, with the words), "no" (the text denies it:
    "לא מחולקת"), or None (the text doesn't say)."""
    yes, no = [], []
    for m in _matches(_UNIT_RE, text):
        if _option_before(text, m) or _extra_unit(text, m):
            continue  # v1.55: "עם אפשרות ליחידת דיור נפרדת": an option, not a unit (batch 9); v1.56: a house plus a unit
        (no if _negation(text, m.start()) else yes).append(m.group())
    if yes:
        return _ans("yes", yes[0])
    if no:
        return _ans("no", no[0])
    return None


# --- below ground level, whatever the floor field says (v1.39) -----------------------

# the first test search: "קומת קרקע" in the text with Yad2's floor field at 1, a garden
# apartment at the entrance level, a "basement/parterre" half a floor down, all shown
# despite "not the ground floor". The text and the kind of home say it outright.
_GROUND = re.compile(
    r"(?<![א-ת])(?:ב|ו|ה)?(?:קומת\s+(?:ה)?קרקע|קומה\s+(?:0|אפס|כניסה)|קומת\s+(?:ה)?כניסה|דירת\s+גן)(?![א-ת])"
)
_BELOW = re.compile(
    r"(?<![א-ת])(?:(?:ב|ו|ה)?(?:דירת|יחידת(?:\s+דיור)?|קומת)\s+(?:ה)?מרתף|מרתף\s*/\s*פרטר"
    r"|חצי\s+קומה\s+(?:מתחת|מתחתה|למטה)|(?:שקוע|שקועה)\s+(?:\S+\s+){0,2}?(?:מתחת|באדמה|בקרקע)"
    r"|מתחת\s+ל(?:אדמה|קרקע|מפלס\s+הרחוב))(?![א-ת])"
)


_NOT_THE_FLAT = re.compile(r"(?<![א-ת])(?:מקלט|ממ[\"״]?ד|חני(?:י)?ה|מחסן|לובי|מסחר|חדר\s+אופניים)[א-ת]*(?:\s+\S+)?\s*$")


def ground_level(text: str) -> Optional[Answer]:
    """"below" (a basement, half a floor down), "ground" (the ground or entrance floor, a garden
    apartment), or None. Not when it's what the flat is above ("מעל קומת קרקע", "קומה א' מעל
    קומת עמודים") or negated ("לא קומת קרקע")."""
    for kind, pat in (("below", _BELOW), ("ground", _GROUND)):
        for m in pat.finditer(text):
            before = _before(text, m.start(), 20)
            if re.search(r"(?<![א-ת])(?:מעל|מעלי|ממעל)(?:\s+\S+)?\s*$", before) or _negation(text, m.start()):
                continue
            # where something else is ("מקלט מצויין בקומת קרקע", "ממד קומתי בקומת הקרקע"), or a house's
            # level listed with what's on it ("קומת קרקע- חניה פרטית, סלון")
            if _NOT_THE_FLAT.search(before) or re.match(r"\s*[:\-–]", text[m.end():]):
                continue
            return _ans(kind, m.group())
    return None


# --- a short lease (v1.39) -----------------------------------------------------------

# "מוצעת להשכרה ל4 חודשים בלבד", "לטווח קצר (בעוד שנה מיועדת לתמ"א)", "עד שנה עקב פינוי בינוי":
# not a home to settle into. "לחודש" is per month, not a term; a sublet "לטווח הארוך" isn't short.
_SHORT = re.compile(
    r"(?<![א-ת])(?:ל|ה|ב)?טווח\s+(?:ה)?קצר(?![א-ת])"
    r"|(?<![א-ת])ל(?:תקופה\s+של\s+)?-?\s*(?:[1-8]|חודשיים|שלושה|ארבעה|חמישה|שישה)\s*חודשים(?![א-ת])"
    r"|(?<![א-ת])\d\s*חודשים\s+בלבד"
    r"|(?<![א-ת])(?:מיועד|מיועדת|עומד|עומדת)\s+(?:\S+\s+)?ל(?:תמ\"?א|הריסה|פינוי)"
    r"|(?<![א-ת])עד\s+שנה\s+(?:עקב|בגלל|כי)"
    r"|(?<![א-ת])סאבלט(?![א-ת])"
)
_LONG = re.compile(r"(?<![א-ת])(?:ל|ה)?טווח\s+(?:ה)?ארוך(?![א-ת])")


def short_lease(text: str) -> Optional[Answer]:
    """"yes" with the words when the text offers a short stay; None otherwise. A sublet or a
    term the text also calls long ("סאבלט לטווח הארוך") isn't short."""
    m = _SHORT.search(text)
    if not m:
        return None
    if _LONG.search(text) and "קצר" not in m.group():
        return None
    return _ans("yes", m.group())


# --- fans: a note on air conditioning --------------------------------------------

# "מאוורר" is also an adjective (airy: "חדר מאוורר", "דירה מאווררת"), so a fan
# is read only as a ceiling fan, or listed right next to an air conditioner.
_FAN = re.compile(
    r"(?<![א-ת])[והב]?מאוורר(?:י|ים)?\s+תקרה(?![א-ת])"
    r"|מזג(?:ן|נים)\s*(?:\+|,|&)?\s*ו?מאוורר(?:ים)?(?![א-ת])"
    r"|(?<![א-ת])[ו]?מאוורר(?:ים)?\s*(?:\+|,|&)?\s*ו?מזג(?:ן|נים)(?![א-ת])"
)


def fan(text: str) -> Optional[str]:
    """The words, if the text mentions a fan: an A/C answer then carries a
    "+fan" note, since a fan can stand in for an air conditioner a room
    doesn't have."""
    m = _FAN.search(text)
    return m.group().strip() if m else None


# --- broker ------------------------------------------------------------------------

_NO_BROKER = re.compile(
    r"(?<![א-ת])(?:ו?(?:ללא|בלי|אין)\s*(?:דמי\s*|עמלת\s*|עמלה\s*|עלות\s*|תשלום\s*)?(?:תיווך|תווך|מתווכים|מתווך)"  # v1.53: the typo "ללא תווך" (census)
    r"|(?:מתווכים|מתווך)\s*[\-–—:]?\s*(?:נא\s*)?(?:לא|אל|לא\s+להתקשר)"  # "*מתווכים - נא לא לפנות*" (v1.55 census)
    r"|(?:לא|אינני|איני)\s+(?:מעוניין|מעוניינת|מעוניינים|צריך|צריכה)\s+(?:ב)?(?:שירותי|שרותי)\s+(?:ה)?תיווך"  # v1.55 (batch 9)
    r"|לא\s+(?:דרך\s+)?(?:ל?מתווכים|מתווך|מתווכת|[מל]?תיווך))(?![א-ת])"  # v1.51: "לא למתווכים", "פרטי לא מתווך"; "לא לתיווך" (v1.55 census)
    # v1.55 (census, Oct 30): from the owner: "להשכרה מפרטי", "ישירות מבעלי הדירה" (14 of 14 in the 640 read no broker)
    r"|(?<![א-ת])(?:מפרטי|מהבעלים|ישירות\s+מ(?:ה)?בעלים|(?:ישירות\s+)?מבעלי\s+(?:ה)?(?:דירה|נכס|בית))(?![א-ת])"
    r"|(?i:no\s+(?:brokerage|broker(?:'s)?|agent(?:'s)?)(?:\s+fees?)?|without\s+(?:a\s+)?broker)"  # v1.55: English (batch 9)
)
# v1.51: the ways the 640 labeled listings show a broker (batches 1-8): the fee written out
# ("תיווך: חודש+מעמ"), the office ("משרדנו"), an agency's name at the end ("דובי נכסים"),
# "להשכרה מתיווך", a broker naming themselves ("יועצת ומתווכת נדל"ן", "המתווך שלי")
_BROKER = re.compile(
    r"(?<![א-ת])(?:בבלעדיות|בלעדי\s+ל|(?:ב)?שיווק\s+בלעדי|דמי\s*(?:ה)?תיווך|עמלת\s*תיווך|משרד\s*תיווך"
    r"|(?:רישיון|רשיון)\s*(?:תיווך|מתווך|מס['׳]?|מספר)"
    # v1.53 (census, Oct 29): "מס' רישיון 318813", "ותשלום תיווך", "פאר תיווך נכסים מציגה"
    r"|(?:מס['׳]?|מספר)\s*(?:רישיון|רשיון)(?:\s*תיווך)?\s*:?\s*\d{4,}|ו?תשלום\s+(?:ה|ל)?תיווך|תיווך\s+(?:ו)?נכסים"
    r"|תיווך\s*[:;]?\s*(?:חודש|חצי\s+חודש)|עמלה\s+(?:מופחתת|של\s+חודש|חודש|חצי)"
    r"|[בלמ]?משרדנו|בטיפול\s+משרד|להשכרה\s+מתיווך|בתיווך|^\W*תיווך\s+השכרה"  # Yad2's title for an agency ad (v1.53)
    r"|^\W*נכס\s+מספר\s*:?\s*\d"  # v1.55 (census): an agency's catalogue number opens the ad (8 of 8 in the 640 allow a broker)
    r"|(?:שיווק|ייעוץ|יועצ(?:ת|ים)?|מתווכ(?:ת|ים)?|ו?מתווך)\s+(?:וייעוץ\s+|ו?מתווכת\s+)?נדל[\"״]?ן"
    r"|שיווק\s+(?:\S+\s+){1,3}?נדל[\"״]?ן"  # v1.55 (census): "שיווק [name] נדלן"
    r"|(?:ה)?מתווך\s+שלי|צוות\s+(?:\S+\s+){1,2}?נכסים"
    r"|[^\s.]+[\s\-]נכסים(?=\s*\.?\s*(?:$|\n))"
    # v1.55 (batch 9): the fee as an amount ("תיווך 1000ש\"ח"), and agency chains by name
    r"|(?:עמלת\s+)?תיווך\s*[:\-]?\s*\d[\d,]{2,}\s*(?:ש[\"״]?ח|₪|שקל)"
    r"|רי?מקס|(?i:re/?max)|אנגלו[\s\-]סכסון|סנצ'?ורי\s*21|(?i:century\s*21)|קולדוול|(?i:coldwell))(?![א-ת])"
)


def broker(text: str) -> Optional[Answer]:
    no = list(_NO_BROKER.finditer(text))
    taken = [(m.start(), m.end()) for m in no]
    yes = [m for m in _BROKER.finditer(text) if not any(a <= m.start() < b for a, b in taken)]
    if any(_negation(text, m.start()) for m in yes):
        return None  # "המתווך לא גובה דמי תיווך": a broker, but no fee -- read it yourself
    if no and not yes:
        return _ans("no_broker", no[0].group())
    if yes and not no:
        return _ans("broker", yes[0].group())
    if yes and no:  # "ללא תיווך ... דמי תיווך": said both ways (v1.28: was silence)
        return _unclear(no[0].group(), yes[0].group())
    return None


# --- vaad bayit and arnona ------------------------------------------------------

# "the price includes ..." -- a subject (the price, the rent, or the rent's
# own number) right before כולל, so "לא כולל" and "ועד בית כולל ניקיון"
# (the FEE includes cleaning) never count.
_INCLUDES = re.compile(
    r"(?:(?<![א-ת])ו?(?:המחיר|מחיר|השכירות|שכירות|שכ[\"״]ד|שכר\s+(?:ה)?דירה|התשלום|החיר|החשבון)(?:\s+(?!(?:לא|ללא|אינו|אינה)(?![א-ת]))[א-ת]+)?\s+"  # v1.56: "החשבון כולל ארנונה" (batch 10)
    r"|(?<![\d.,])\d{1,2},?\d{3}\s*(?:₪|ש[\"״']?ח|שקלים|שקל)?\s*"  # a rent-sized number: "4200 כולל ..."; v1.64: "4000 שקלים כולל" (Komo batch 2)
    r"|(?:^|(?<=[\n.!:*,(]))\s*|(?<=\s[\-–—])\s*"  # v1.51: also after a comma or a dash ("4,750 ש\"ח - כולל ארנונה"); v1.56: "(כולל ארנונה" (batch 10)
    r"|(?<![א-ת])(?:להשכרה|לחודש|בחודש)\s+(?=ה?כוללת|ו?כולל))(?:ה|ו)?"  # v1.56: "דירה ... להשכרה הכוללת ארנונה" (batch 10)
    r"(?:כולל|כוללל|כוללת|כוללים|כולל\s+את)[\s\-:,]+((?:[^.\n]|\.(?=[א-ת])){0,80})"  # "כוללים", "כולל-ארנונה" (v1.51); v1.59: "המחיר כולל, כבלים, ארנונה", the typo "כוללל", "כולל מים.ארנונה." (batch 12)
    r"|(?<![א-ת])(?:כלול|כלולים|כלולה)\s+(?:ב)?(?:מחיר|שכירות|שכ[\"״]ד)\s*[:\-]\s*([^.\n]{0,80})"  # v1.59: "כלול במחיר: מים, ארנונה ואינטרנט" (batch 12)
    r"|(?<![א-ת])(?:ה)?(?:הכל|הכול)\s+(?:כלול|כלולים)\s*:?\s*([^.\n]{0,80})"  # "הכל כלול (חשמל, מים וארנונה)"
    r"|(?<![א-ת])ו?(?:המחיר|השכירות|התשלום)\s+כלל\s+([^.\n]{0,80})"  # v1.55: the typo "המחיר כלל ארנונה" (batch 9)
)
# Where a list of what's included stops: a negation or a contrast.
_LIST_STOP = re.compile(r"(?<![א-ת])(?:לא|ללא|אך|אבל|חוץ|מלבד|פרט|למעט|בנוסף|בתוספת)(?![א-ת])|[()\-–—]")
_IN_RENT = re.compile(r"(?:ועד\s*(?:ה)?בית|ארנונה)\s+(?:כלול|כלולה|כלולים)\s+(?:ב)?(?:מחיר|שכירות|שכ[\"״]ד)")


def _included(text: str, keyword: str) -> Optional[str]:
    for m in _INCLUDES.finditer(text):
        listed = next(g for g in m.groups() if g is not None)
        # v1.56 (batch 10): "כולל כל החשבונות / וועד בית, חשמל, מים וארנונה": the list on the next line;
        # "כולל אינטרנט וערוצי טלביזיה..ארנונה מים": an ellipsis goes on with the list
        if re.fullmatch(r"\s*(?:את\s+)?(?:כל\s+)?(?:ה)?(?:חשבונות|הוצאות|מיסים|תשלומים)\s*[:\-]?\s*", listed):
            nxt = re.match(r"[ \t]*\n\s*([^.\n]{0,80})", text[m.end():])
            listed += " " + (nxt.group(1) if nxt else "")
        elif (more := re.match(r"\.{2,}\s*([^.\n]{0,60})", text[m.end():])):
            listed += " " + more.group(1)
        listed = re.sub(r"^\s*(?:את\s+)?(?:ה)?(?:הכל|הכול)\s*[\-–—:]\s*", "", listed)  # v1.56: "השכירות כוללת הכל- ארנונה, מים"
        # v1.51: a list in brackets after "bills" is still the list: "כולל חשבונות (מים, חשמל, ארנונה)"
        listed = re.sub(r"^((?:\S+\s+){0,2}?(?:ה)?(?:חשבונות|הוצאות|מיסים|שירותים|תשלומים)\s*)?\(([^()]*)\)", lambda b: (b.group(1) or "") + " " + b.group(2) + " ", listed)  # "שירותים (...)" (v1.55)
        stop = _LIST_STOP.search(listed)
        end = stop.start() if stop else len(listed)
        k = re.search(rf"(?<![א-ת])(?:ו|ל|ול)?(?:{keyword})", listed[:end])  # v1.64: "כולל תשלום לועד הבית" (Komo batch 2)
        # "כולל ארנונה, ועד בית לא כלול": the item's own negation follows it
        if k and not re.match(r"\s*(?:לא|אינו|אינה|אינם)(?![א-ת])(?!\s+(?:כולל|כוללת|כוללים)(?![א-ת]))", listed[k.end() :]):  # v1.56: not "ארנונה לא כולל חשמל" (a new list)
            return m.group().strip()
    return None


def _amounts(text: str, field: str) -> list[tuple[float, str]]:
    return [(a, text[s:e]) for f, a, s, e in candidate_spans(text, bimonthly_arnona=True) if f == field]


def _cost(text: str, field: str, keyword: str, trap: Optional[re.Pattern[str]] = None) -> Optional[Answer]:
    """An amount, or included in the rent. `trap`: a phrasing that mentions
    the fee without settling it (what's included IN the fee; the area the
    tax is billed on); with no answer otherwise, that's unclear."""
    amounts = _amounts(text, field)
    included = _included(text, keyword)
    for m in _IN_RENT.finditer(text):
        if re.search(keyword, m.group()):
            included = included or m.group()
    if amounts and included:  # "כולל ועד בית ... ועד בית 150": said both ways (v1.28: was silence)
        return _unclear(included, amounts[0][1])
    if included:
        return _ans("included", included)
    if len({a for a, _ in amounts}) == 1:
        value = amounts[0][0]
        return _ans("amount", amounts[0][1], value=int(value) if value == int(value) else value)
    if amounts:  # two different amounts
        return _unclear(*(e for _, e in amounts))
    if trap and not amounts and (t := trap.search(text)):
        return _unclear(t.group())
    return None


# "מים חמים כלולים בדמי ועד הבית": hot water is IN the fee; the fee's own
# amount, and whether the rent covers it, aren't said.
_IN_VAAD = re.compile(r"(?<![א-ת])(?:כלול|כלולה|כלולים|כלולות)\s+(?:ב|גם\s+ב)(?:דמי\s*|מיסי\s*|תשלום\s+)?(?:ה)?ו?ועד(?:\s*(?:ה)?בית)?(?![א-ת])")  # "כלול בתשלום הועד" too (batch 4)
# "בארנונה 117 מטר": the area the tax is billed on, not an amount.
_ARNONA_AREA = re.compile(r"(?<![א-ת])(?:ב|ו)?ארנונה\s*:?\s*(?:של\s+)?\d{2,3}\s*(?:מ[\"״]?ר|מטר|מ['׳]?)(?![א-ת\d])")


# v1.49: "ללא ועד בית", "אין וועד בית": there's no fee, so it's 0 (the labelers' reading, batch 7)
_NO_VAAD = re.compile(r"(?<![א-ת])(?:אין|ללא|בלי)\s+(?:תשלום\s+)?ו?ועד\s*(?:ה)?בית(?![א-ת])")  # "ללא תשלום ועד בית" (v1.53)


# v1.55 (batch 9): a fee with no "בית": "וועד 180 לחודש" (the double vav is the committee), "ועד 60 ש\"ח לחודש"
# (single vav, which is also "and until": only with a currency and "per month")
_VAAD_SHORT = re.compile(r"(?<![א-ת])(?:וועד\s*:?\s*(?P<a>\d{2,4})\s*(?:ש[\"״]?ח|₪|שקל(?:ים)?)?"
                         r"|ועד\s*:?\s*(?P<b>\d{2,4})\s*(?:ש[\"״]?ח|₪|שקל(?:ים)?))\s*(?:ל|כל\s+|ב)?חודש(?![א-ת])")


def vaad_bayit(text: str) -> Optional[Answer]:
    # "ועד" alone also means "and until" (ו+עד); only a listed "ועד" closed by
    # a comma or the end of the list, or "ועד בית", counts.
    got = _cost(text, "vaad", r"ו?ועד\s*(?:ה)?(?:בית|בניין|בנין)|ועד(?=\s*(?:[,.;)]|$))|(?<=ו)ועד(?=\s+ו[א-ת])", _IN_VAAD)  # "ועד בניין" (v1.53); v1.64: "אינטרנט וועד וארנונה" in an included list (Komo batch 2)
    if got is None:
        short = [(int(m.group("a") or m.group("b")), m.group()) for m in _VAAD_SHORT.finditer(text)
                 if 10 <= int(m.group("a") or m.group("b")) <= 2000]
        if len({v for v, _ in short}) == 1:
            got = _ans("amount", short[0][1].strip(), value=short[0][0])
    none = _NO_VAAD.search(text)
    if none and got is None:
        return _ans("amount", none.group(), value=0)
    if none and got["answer"] != "amount" or none and got.get("value") not in (0, None):
        return _unclear(none.group(), got["evidence"])
    return got


# v1.49: an arnona amount with no period ("ארנונה 850", "ארנונה: 800 ש\"ח") may be per
# month or per two months (it's billed bimonthly): the labelers read every one as unclear
_ARNONA_BARE = re.compile(r"(?<![א-ת])(?:ו|ה)?ארנונה\s*[:\-]?\s*(?:כ-?\s*)?\d[\d,]{1,5}(?![\d,])")
_PERIOD = re.compile(r"^\s*(?:ש[\"״]?ח|₪|שקל(?:ים)?)?\s*(?:ל|ב|כל\s+|ה)?(?:חודש|חודשיים|דו[\s\-]?חודשי|לחודש)")
_AREA_AFTER = re.compile(r"^\s*(?:מ[\"״]?ר|מטר|מ['׳])")


def arnona(text: str) -> Optional[Answer]:
    got = _cost(text, "arnona", r"ארנונה|מיסי\s+(?:ה)?עירייה|מיסי\s+עיריה", _ARNONA_AREA)
    if got is None:
        for m in _ARNONA_BARE.finditer(text):
            after = text[m.end() : m.end() + 30]
            if not _PERIOD.match(after) and not _AREA_AFTER.match(after):
                return _unclear(m.group())  # a check, and a model can't fill in the period
    return got


RULES = {
    "protected_space": protected_space,
    "elevator": elevator,
    "parking": parking,
    "air_conditioning": air_conditioning,
    "room_share": room_share,
    "apartment_type": apartment_type,
    "balcony": balcony,
    "furniture": furniture,
    "broker": broker,
    "vaad_bayit": vaad_bayit,
    "arnona": arnona,
}


def answer(text: str) -> dict[str, Answer]:
    """Every question: a rule's answer where it is sure, else not_stated.
    A fan mentioned anywhere adds a "+fan" note to air_conditioning."""
    out: dict[str, Answer] = {}
    for q in QUESTIONS:
        got = RULES[q.id](text)
        out[q.id] = got if got and got["answer"] in q.answers else {"answer": NOT_STATED, "evidence": ""}
    if words := fan(text):
        out["air_conditioning"] = {**out["air_conditioning"], "note": f"+fan: {words}"}
    return out


def combine(rule: dict[str, Answer], model: dict[str, Answer]) -> dict[str, Answer]:
    """Rules and a model, as one reader. Each answer says where it came
    from (`source`), because a model-only answer is trusted less downstream
    (it can't hide a listing on its own; see scoring).

    - Rules unclear: the text itself doesn't settle it, so it stays unclear
      whatever the model says (a model answer there is a guess the rules
      caught a trap for).
    - Both answer and agree: that answer ("both").
    - Both answer and disagree: unclear, both noted -- a human looks.
    - Only one answers: it stands ("rules" or "model"); each has already
      refused what it couldn't read.
    - Two lists (furniture): every id either one read, tagged "model" if
      the model added any; general claims that contradict make it unclear.
    A rules note ("+fan" on air_conditioning) is kept whatever the answer.
    """
    out: dict[str, Answer] = {}
    for q in QUESTIONS:
        r = rule.get(q.id) or {"answer": NOT_STATED}
        m = model.get(q.id) or {"answer": NOT_STATED}
        ra, ma = r["answer"], m["answer"]
        note = {"note": r["note"]} if r.get("note") else {}  # a rules-only note ("+fan") survives either way
        out[q.id] = _combine_one(q, r, m, ra, ma)
        out[q.id].update(note)
    return out


def _combine_one(q: Any, r: Answer, m: Answer, ra: str, ma: str) -> Answer:
    if q.items and ra == ma == "items":
        # Two lists: what either one read, unless their general claims
        # contradict ("unfurnished" against "furnished").
        ri, mi = set(r.get("items") or []), set(m.get("items") or [])
        if any(pair <= ri | mi for pair in _CONTRARY):
            return {"answer": UNCLEAR, "evidence": " ... ".join(e for e in (r.get("evidence"), m.get("evidence")) if e),
                    "source": "both", "problem": f"conflict: rules {sorted(ri)}, model {sorted(mi)}"}
        source = "both" if ri == mi else "rules" if mi <= ri else "model"
        evidence = " ... ".join(dict.fromkeys(e for e in (r.get("evidence"), m.get("evidence")) if e))
        return {"answer": "items", "items": sorted(ri | mi), "evidence": evidence, "source": source}
    return _combine_single(r, m, ra, ma)


def _combine_single(r: Answer, m: Answer, ra: str, ma: str) -> Answer:
    if ra == UNCLEAR:
        veto = {"problem": f"rules found it unclear; model said {ma!r}"} if ma not in (NOT_STATED, UNCLEAR) else {}
        return {**r, "source": "rules", **veto}
    if ra == NOT_STATED:
        return {**m, "source": "model"} if ma != NOT_STATED else dict(m)
    if r.get("or") and ma in (ra, *r["or"]):
        return {**r, "source": "both"}  # v1.53: the model picked one of the rules' options: the rules' range stands
    if ma in (NOT_STATED, UNCLEAR):
        return {**r, "source": "rules"}
    if ra == ma and r.get("value") == m.get("value"):
        return {**r, "source": "both"}
    return {"answer": UNCLEAR, "evidence": " ... ".join(e for e in (r.get("evidence"), m.get("evidence")) if e),
            "source": "both", "problem": f"conflict: rules {ra!r}, model {ma!r}"}
