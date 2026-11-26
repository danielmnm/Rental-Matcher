"""
Phase 2: the questions an extractor answers about a listing's TEXT.

One spec serves three jobs, so they can't drift apart: it is the labeling
guide for the test set, the prompt an extractor is given, and the map from
an answer to a Signal the scoring engine reads.

Each question is narrow, with a closed set of answers, and two of them are
always there: "not_stated" (the text doesn't mention it) and "unclear" (it
mentions it but doesn't settle it: a typo, a contradiction, an offer or a
plan rather than a fact). The extractor's job is to report what the text
says, never to guess what's likely. "unclear" is how a reader says "I see
something here, a human should look", and it carries the words that need
the look. Every answer except not_stated must come with the words it rests
on (evidence), quoted from the text.

Answers come from the description only. Structured fields (Yad2's
checkboxes) are read separately by the adapter; a merge step combines
the two (see merge.py).
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Optional

NOT_STATED = "not_stated"
UNCLEAR = "unclear"
_UNCLEAR_MEANING = ("it mentions this but doesn't settle it: a typo, a contradiction, an offer or a plan "
                    "rather than a fact, or something nearby rather than the apartment's own -- quote those words")


def _answers(**meanings: str) -> dict[str, str]:
    """A question's answers, with "unclear" and "not_stated" always last."""
    not_stated = meanings.pop(NOT_STATED, "it doesn't say")
    return {**meanings, UNCLEAR: _UNCLEAR_MEANING, NOT_STATED: not_stated}


@dataclass(frozen=True)
class Question:
    id: str
    ask: str  # the question, in plain English
    answers: dict[str, str]  # answer -> what it means
    guidance: tuple[str, ...] = ()  # how to decide the hard cases
    signal: Optional[str] = None  # the Signal this feeds
    values: dict[str, object] = field(default_factory=dict)  # answer -> the signal's value; missing = no signal
    # A list question: its "items" answer carries the ids it names in `items`
    # (id -> what it means). Empty for an ordinary one-answer question.
    items: dict[str, str] = field(default_factory=dict)
    # Words the evidence must contain for an answer (or a list id) to stand:
    # a quote of "קומת קרקע" (ground floor) can't carry "garden", a quote of
    # "שידת טלוויזיה" (a TV stand) can't carry "tv". Checked by prompt.ground
    # on every reader's answers. Missing = no extra check.
    requires: dict[str, str] = field(default_factory=dict)


# a floor number of 6 or more, leading zeros allowed ("06"), never "02"
_BIG = r"0*(?:[6-9]|[1-9]\d{1,2})(?!\d)"

QUESTIONS: tuple[Question, ...] = (
    Question(
        id="protected_space",
        ask="Does the text say the apartment has a safe room (mamad, ממ\"ד) or the building has a shelter (מקלט, miklat)?",
        answers=_answers(**{"yes": "it says there is one", "no": "it says there is none", NOT_STATED: "it doesn't say"}),
        guidance=(
            "A public shelter down the street (מקלט ציבורי) is not the building's own: answer unclear (quote it) unless it says the building has one.",
            "'מקלט תקני', 'מקלט מסודר בבניין', 'מקלט צמוד לבניין' all mean yes.",
        ),
        requires={a: r"ממ[\"״']?[דק]|ממד|מרחב\s+מוגן|מי?קלט|מוגן" for a in ("yes", "no")},  # "מיקלט" too (v1.49)
        signal="protected_space",
        values={"yes": True, "no": False},
    ),
    Question(
        id="elevator",
        ask="Does the text say whether the building has an elevator (מעלית)?",
        answers=_answers(**{"yes": "it has one", "no": "it says there is none (e.g. 'ללא מעלית')", NOT_STATED: "it doesn't say"}),
        guidance=(
            "'ללא' / 'בלי' (without) denies only the word right after it: 'ללא X' says nothing about an elevator unless X is מעלית.",
            "A floor of 6 or higher is 'yes' even with no מעלית word: no building that tall lacks an elevator (e.g. 'קומה 18').",
        ),
        # "ללא עמודים" (no pillars) is a real quote, but there's no elevator in it.
        # "yes" also accepts a floor number of 6+ on its own ([6-9] or 2-3 digits
        # both mean >= 6); the trailing (?!...ללא) skips Yad2's "קומה N ללא"
        # shorthand for no elevator, which never spells out the word either.
        # v1.28: the same reading as rules.elevator: "קומה 2 מתוך 8" (an 8-floor
        # building) is a yes; "קומה 02" isn't 6+; a "ללא" after the whole floor
        # phrase ("קומה 6 מתוך 8 ללא") is Yad2's no.
        requires={"yes": "מעלי|קומה\\s*\\.?\\s*(?:ה-?)?(?:" + _BIG + "(?!\\s*(?:מתוך|/))|\\d{1,3}\\s*(?:מתוך|/)\\s*" + _BIG
                  + "|" + _BIG + "\\s*(?:מתוך|/)\\s*\\d{1,3}(?!\\d))(?!\\s*\\(?\\s*ללא)",
                  "no": r"מעלי|קומה\s*\d+\s*\(?\s*ללא"},  # "קומה 4 ללא": Yad2 shorthand for no elevator
        signal="elevator",
        values={"yes": True, "no": False},
    ),
    Question(
        id="parking",
        ask="What parking does the text describe?",
        answers=_answers(**{
            "deeded": "a parking space that belongs to the apartment (חניה צמודה, חניה בטאבו, private/assigned)",
            "building": "parking in the building or its lot, not stated as the apartment's own (חניה בבניין)",
            "street": "only street or public parking nearby (חניה בשפע, חניה ציבורית, אפשרויות חניה באזור)",
            "none": "it says there is no parking",
            NOT_STATED: "it doesn't mention parking",
        }),
        guidance=(
            "'Parking available for an extra fee' (בתוספת תשלום) is building parking unless it says it's on the street.",
            "If two kinds are mentioned, answer the best one the apartment actually gets.",
        ),
        requires={a: r"חני|חנ(?:י)?ה|חניון|רכב" for a in ("deeded", "building", "street", "none")},
        signal="parking_level",
        values={"deeded": 3.0, "building": 2.0, "street": 1.0, "none": 0.0},
    ),
    Question(
        id="air_conditioning",
        ask="Does the text say the apartment has air conditioning (מזגן, מיזוג)?",
        answers=_answers(**{"yes": "it says so", "no": "it says there is none", NOT_STATED: "it doesn't say"}),
        requires={a: r"מזג|מיזוג|ממוזג" for a in ("yes", "no")},
        signal="air_conditioning",
        values={"yes": True, "no": False},
    ),
    Question(
        id="room_share",
        ask="Is this a room in a shared apartment (you'd live with other tenants), rather than a whole apartment?",
        answers=_answers(**{
            "yes": "a room for rent, or the poster is looking for a roommate to join",
            "no": "a whole apartment for rent",
            NOT_STATED: "the text doesn't make it clear",
        }),
        guidance=(
            "'Suitable for roommates' (מתאימה לשותפים) describes a WHOLE apartment that roommates could rent together: answer no.",
            "A text that describes the whole apartment for rent ('דירת 3 חדרים להשכרה') is no.",
        ),
        # "yes" needs a room, a single roommate or a shared flat in its quote: the
        # plural "מתאימה לשותפים" (suits roommates) describes a whole apartment.
        # v1.18.7: "seeking" / "replacing" alone name no room: "מחפשת
        # מחליף/ה!" was a whole-apartment lease handover (batch 6), and
        # "מחפש" is in 21 whole-apartment listings ("למי שמחפש...").
        # Seeking + a roommate word ("מחפשת שותפה", "מחפשים שותפים") does name it.
        requires={"yes": r"(?<![א-ת])[הל]?חדר(?![א-ת])|שות(?:ף|פה|פ/ה|ף/ה)(?![א-ת])|דירת\s+שותפים|לכל\s+שותף"
                         r"|(?:מחפש|דרוש)\S*\s+(?:\S+\s+)?שות(?:ף|פ)"
                         r"|משותפ(?:ים|ת|ות)?|בשיתוף"},  # v1.51: a shared kitchen or bathroom
        signal="roommate_listing",
        values={"yes": True, "no": False},
    ),
    Question(
        id="apartment_type",
        ask="Does the text say the home is a special type rather than an ordinary apartment in a building?",
        answers=_answers(**{
            "roof": "a roof apartment or penthouse (דירת גג, פנטהאוז, מיני פנטהאוז)",
            "garden": "a garden apartment (דירת גן): ground floor with its own yard",
            "duplex": "on two floors (דופלקס, דירה בשתי קומות / מפלסים), and not a roof apartment",
            "studio": "a studio (סטודיו)",
            "unit": "a housing unit (יחידת דיור), often part of a private house",
            "house": "a whole private house or cottage (בית פרטי, קוטג')",
            NOT_STATED: "it doesn't say it's any of these (most listings)",
        }),
        guidance=(
            "A roof apartment on two floors is roof.",
            "A housing unit in a private house ('יחידת דיור בבית פרטי') is unit, not house.",
            "The building's shared roof (גג משותף, גישה לגג) doesn't make it a roof apartment.",
            "Two different types that can't both be true (a garden apartment and a penthouse): unclear.",
            "A ground-floor apartment (קומת קרקע, דירת קרקע) is NOT a garden apartment unless the text gives it its own garden or yard.",
        ),
        requires={"roof": r"גג|פנט[הא]", "garden": r"גן|גינ|חצר", "duplex": r"דופלקס|קומות|מפלס",
                  "studio": r"סטודיו", "unit": r"יחיד", "house": r"בית|קוטג|וילה"},
        signal="apartment_type",
        values={"roof": "roof", "garden": "garden", "duplex": "duplex", "studio": "studio", "unit": "unit", "house": "house"},
    ),
    Question(
        id="balcony",
        ask="Does the text say the apartment has a balcony (מרפסת)?",
        answers=_answers(**{
            "yes": "a real balcony, open or enclosed (מרפסת, מרפסת שמש, מרפסת סגורה)",
            "service_only": "only a service balcony (מרפסת שירות, for laundry)",
            "no": "it says there is none",
            NOT_STATED: "it doesn't say",
        }),
        guidance=(
            "A roof apartment (דירת גג, פנטהאוז) is a type of home (see apartment_type), not a balcony: on its own it says nothing about one.",
            "A roof terrace or a roof that is the apartment's own (מרפסת גג, גג צמוד, גג פרטי) is yes; a shared roof (גג משותף) isn't the apartment's own: unclear.",
        ),
        requires={"yes": r"מי?רפס|מרספ|גג|טרס", "service_only": r"מי?רפס|מרספ", "no": r"מי?רפס|מרספ"},  # "מירפסת" (v1.49); "חדר שירות" isn't a balcony
        signal="balcony",
        values={"yes": True, "service_only": False, "no": False},
    ),
    Question(
        id="furniture",
        ask="What furniture and appliances does the text say come with the apartment?",
        answers=_answers(**{
            "items": "it names what comes with the apartment, or says in general that it's furnished or unfurnished: put the ids in `items`",
            NOT_STATED: "it says nothing about furniture or appliances",
        }),
        items={
            "says_furnished": "it says the apartment is furnished, in general words (מרוהטת, ריהוט מלא, מרוהטת קומפלט)",
            "says_partly_furnished": "it says partly furnished, or that some furniture stays, without naming it (מרוהטת חלקית, ריהוט חלקי, נשאר ריהוט, סלון מרוהט)",
            "says_unfurnished": "it says the apartment is unfurnished (לא מרוהטת, ללא ריהוט)",
            "says_equipped": "it says it comes with appliances, without naming them (מאובזרת, מוצרי חשמל, מכשירי חשמל)",
            "bed": "a bed (מיטה)",
            "sofa": "a sofa or armchair (ספה, כורסה)",
            "table_chairs": "a table or chairs (שולחן, כסאות, פינת אוכל)",
            "cabinet": "free-standing storage furniture (מזנון, שידה, ספרייה, קומודה, ויטרינה)",
            "fridge": "a refrigerator (מקרר)",
            "washer": "a washing machine (מכונת כביסה)",
            "dryer": "a dryer (מייבש)",
            "dishwasher": "a dishwasher (מדיח)",
            "microwave": "a microwave (מיקרוגל)",
            "tv": "a television (טלוויזיה)",
            "closets": "closets or wardrobes (ארונות, ארונות קיר, ארון בגדים): usually built in, so listed but not counted as furniture",
            "oven_stove": "an oven or stove (תנור, כיריים): part of the kitchen, listed but not counted as furniture",
        },
        guidance=(
            "List every id the text gives words for; a general claim and named items go together ('מרוהטת: ספה ומיטה' -> says_furnished, sofa, bed).",
            "Air conditioning (מזגן) and fans (מאוורר) are NOT furniture or appliances: never list them here (they belong to air_conditioning). Nor lighting, boilers, kitchen cabinets, window bars or flooring.",
            "An offer or option ('אפשרות לריהוט', 'ניתן להשאיר את המקרר', 'במידת הצורך') is unclear: an offer isn't furniture. So is the tenant's choice ('מרוהטת או ללא ריהוט').",
            "What IS there still counts next to an offer of more: 'מרוהטת חלקית, אפשרות לריהוט מלא' -> says_partly_furnished; 'ספה ומיטה, אפשרות להשאיר מקרר' -> sofa, bed (not fridge).",
            "Unfurnished with a few things staying ('ללא ריהוט אך נשאר תנור') -> says_unfurnished, oven_stove.",
            "Only the apartment's own: things in the building or a shared space don't count.",
            "A TV stand (שידת טלוויזיה) is a cabinet, not a tv.",
        ),
        requires={
            "says_furnished": r"רהוט|ריהוט|רהיט|מרוהט", "says_partly_furnished": r"רהוט|ריהוט|רהיט|מרוהט",
            "says_unfurnished": r"רהוט|ריהוט|רהיט|מרוהט", "says_equipped": r"אובזר|אבזור|חשמל",
            "bed": r"מיט|חדר\s+שינה\s+קומפלט", "sofa": r"ספה|ספות|כורס|ישיבה", "table_chairs": r"שולחן|שולחנות|כיסא|כסא|כסאות|כיסאות|פינת\s+אוכל",
            "cabinet": r"מזנון|שיד|ספרי|קומוד|ויטרינ", "fridge": r"מקרר", "washer": r"כביסה|מכונה", "dryer": r"מי?יבש",
            "dishwasher": r"מדיח", "microwave": r"מיקרו",
            # v1.49: kitchen cabinets aren't closets; "למכירה" (for sale) isn't a stove
            "closets": r"ארון(?!ות)(?!\s*(?:ה)?מטבח)|ארונות(?!\s*(?:ה)?מטבח)",
            "oven_stove": r"תנור|כיריים|(?<!מ)כירה|גז",
            # a TV, not a TV stand or a TV corner
            "tv": r"(?<!שידת )(?<!פינת )(?<!שידת)(?<!פינת)טלו?ויזי",
        },
        signal="furniture",
    ),
    Question(
        id="broker",
        ask="What does the text say about a broker (תיווך)?",
        answers=_answers(**{
            "no_broker": "it says there's no broker (ללא תיווך)",
            "broker": "it shows the poster is a broker or agency (an agency name, a license, 'בבלעדיות', 'דמי תיווך')",
            NOT_STATED: "it doesn't say",
        }),
        guidance=("'Brokers please don't call' (מתווכים נא לא לפנות) is no_broker.",
                  "Asking recruiters or other companies not to call (חברות כ\"א לא להתקשר) says nothing about a broker."),
        requires={"no_broker": r"תיווך|תווך|מתווכ|ישיר|מהבעלים|בעל(?:ת)?\s+ה?(?:דירה|נכס)|פרטי"},
    ),
    Question(
        id="vaad_bayit",
        ask="What does the text say about the monthly building fee (ועד בית)?",
        answers=_answers(**{
            "amount": "it gives a monthly amount: put the number in `value`",
            "included": "it says the fee is included in the rent",
            NOT_STATED: "it doesn't say",
        }),
        guidance=(
            "An amount that isn't clearly monthly is unclear.",
            "Something included IN the fee ('X כלול בדמי ועד הבית') is about what the fee covers, not about the fee being in the rent: unclear unless it also gives the amount or says the fee is in the rent.",
        ),
    ),
    Question(
        id="arnona",
        ask="What does the text say about the municipal tax (ארנונה)?",
        answers=_answers(**{
            "amount": "it gives an amount and its period: put the MONTHLY amount in `value`",
            "included": "it says arnona is included in the rent",
            NOT_STATED: "it doesn't say",
        }),
        guidance=(
            "Arnona is often billed every two months: 'לחודשיים' or 'דו חודשי' means per two months, so `value` is HALF the stated number ('ארנונה 600 לחודשיים' -> 300).",
            "'מיסי עירייה' (municipal taxes) means arnona: 'המחיר כולל מיסי עירייה' is included.",
            "An amount with no period stated: answer amount with the number as given only if the text says it's monthly (לחודש); otherwise unclear.",
            "A size in meters next to ארנונה is the area the tax is billed on, not an amount: unclear.",
        ),
    ),
)

BY_ID = {q.id: q for q in QUESTIONS}


def guide() -> str:
    """The questions as one plain-text guide: what a labeler reads, and
    what an extractor is prompted with."""
    lines = []
    for q in QUESTIONS:
        lines.append(f"[{q.id}] {q.ask}")
        lines.extend(f"  - {a}: {meaning}" for a, meaning in q.answers.items())
        lines.extend(f"    item {i}: {meaning}" for i, meaning in q.items.items())
        lines.extend(f"  note: {g}" for g in q.guidance)
    return "\n".join(lines)


# v1.56 (owner ruling, Oct 30): words that place the parking on the street. With one of them the text
# overrules Yad2's ticked parking box ("חניה בכביש"); "חניה בשפע" alone may be the lot's.
PLACES_PARKING = re.compile(r"ברחוב|בכביש|עירוני|כחול[\s\-]?לבן|ציבורי|מפרץ|זכאות|לתושבי|(?<![א-ת])תו(?![א-ת])")
