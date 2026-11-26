"""
Classify a listing as PRIVATE or AGENCY from its free-text notes.

Same rule as costs.py: when in doubt, return None (unknown). A wrong
AGENCY hides a private listing from a renter who filters agencies out;
a wrong PRIVATE hides a broker fee. Unknown costs nothing but a manual
check.

Per clause (split with costs.split_clauses, so "Agency listing — no fee
mentioned" is two clauses, not one negated agency mention):

1. A fee-waiver phrase ("ללא עמלת תיווך", "ללא דמי תיווך", "0% עמלה",
   "no broker fee") -> AGENCY. A broker is involved; the tenant just
   isn't charged.
2. A recognized "no brokers" phrase -> PRIVATE. Patterns, not a list of
   exact wordings: a negation directly before a broker word ("ללא תיווך",
   "שלא דרך מתווך", "no broker") unless the broker word is followed by a
   fee ("no broker's fee" is about a fee); "from the owner" ("מבעלים");
   or a broker word next to "don't call / contact" in either order
   ("מתווכים נא לא לפנות", "נא לא לפנות מתווכים") -- across a separator
   only when each side is nothing else ("מתווכים - נא לא לפנות").
3. A broker word with ANY negation anywhere else in the clause ->
   unknown. "Agency listing not furnished" and "broker fee not stated"
   both have a negation that isn't about whether there's a broker; this
   doesn't try to guess which.
4. A broker word with no negation in the clause -> AGENCY.

Clauses that disagree with each other also give unknown.
"""

from __future__ import annotations

import re

from .costs import split_clauses
from .schema import ListedBy

# Hebrew words take one-letter prefixes (ל, ו, ה, מ, ש, ב): "למתווכים",
# "ומתווך", "מהתיווך". Matched as substrings of a word for that reason.
_HE_BROKER = r"[לוהמשב]{0,2}(?:תיווך|מתווכ\w*|מתווך)"
_EN_BROKER = r"(?:agency|agencies|agents?|brokers?|brokerage|realtors?)"
_BROKER_RE = re.compile(rf"{_HE_BROKER}|\b{_EN_BROKER}\b", re.IGNORECASE)

# Negation words, with the one-letter prefixes Hebrew attaches to them
# ("וללא", "ולא", "שלא", "ובלי"). "אל" is deliberately NOT here: as a
# standalone word it's usually the preposition "to" ("פנו אל המתווך" =
# "contact the broker"); it only negates as "don't" before an imperative,
# which _HE_DONT_CONTACT covers.
_HE_NEG = r"[וש]?(?:ללא|בלי|אין|לא)"
_EN_NEG = r"(?:no|not|without|non|don'?t|do\s+not|never)"
# A negation that is the VALUE of a "label:" pair ("smoking: no", "pets:
# לא") answers that label, so it never starts a "no brokers" phrase --
# without this, "smoking: no Agency listing" read as "no agency".
_NOT_A_LABEL_VALUE = r"(?<!:)(?<!:\s)"
_ANY_NEGATION_RE = re.compile(rf"(?<!\w){_HE_NEG}(?!\w)|\b{_EN_NEG}\b", re.IGNORECASE)

_HE_DONT_CONTACT = (
    r"(?:נא\s+|בבקשה\s+)?(?:[וש]?לא\s+(?:לפנות|להתקשר|יתקשרו|יפנו|לשלוח|לכתוב)"
    r"|אל\s+(?:תפנו|תתקשרו|יפנו|יתקשרו))"
)
_EN_DONT_CONTACT = r"(?:please\s+)?(?:do\s+not|don'?t|no)\s+(?:call|calls|contact|message|messages|apply)"
# Plural / collective broker words: "brokers, don't call" is addressed TO
# brokers. A singular one ("Agent please don't call before 9") is usually
# the broker talking about themself, so it doesn't make the listing private.
_HE_BROKERS = r"[לוהמשב]{0,2}(?:מתווכים|תיווך)"
_EN_BROKERS = r"(?:brokers|agents|agencies|realtors)"
# "don't contact" must END the clause: "no calls after 22:00" and "נא לא
# להתקשר בשבת" restrict WHEN to call, they don't refuse brokers.
_CLAUSE_END = r"\s*(?:please|בבקשה|תודה|thanks?|!|\.)*\s*$"

# A broker word followed by a fee or "for the tenant" is about a FEE, not
# about whether a broker exists: "no broker's fee", "בלי תיווך לשוכר".
_NOT_ABOUT_A_FEE = r"(?!'?s?\s+(?:fee|fees|commission)\b|\s+[למ]?ה?שוכר)"

_FEE_WAIVER_RE = re.compile(
    rf"(?<!\w){_HE_NEG}\s+(?:עמלת|דמי)\s+[לה]?תיווך"
    rf"|(?<!\w){_HE_NEG}\s+[לה]?תיווך\s+[למ]?ה?שוכר"
    r"|0\s*%\s*עמלה|ללא\s+עמלה"
    rf"|\b(?:no|without)\s+(?:an?\s+)?{_EN_BROKER}(?:'s|s'|s)?\s+(?:fee|fees|commission)\b"
    r"|\bno\s+fee\s+to\s+(?:the\s+)?tenant\b|\bfee\s+waived\b",
    re.IGNORECASE,
)

_PRIVATE_RES = [
    # negation directly before a broker word ("ללא תיווך", "שלא דרך מתווך")
    re.compile(
        rf"{_NOT_A_LABEL_VALUE}(?<!\w){_HE_NEG}\s+(?:דרך\s+|באמצעות\s+)?{_HE_BROKER}{_NOT_ABOUT_A_FEE}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_NOT_A_LABEL_VALUE}\b(?:(?:no|without(?:\s+an?)?|not\s+(?:an?|through\s+an?))\s+|non[-\s]?)"
        rf"{_EN_BROKER}\b{_NOT_ABOUT_A_FEE}",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:broker|agent|agency)[-\s]free\b", re.IGNORECASE),
    # a features-list answer in one clause: "Broker: no", "תיווך: אין"
    re.compile(rf"^\s*(?:{_HE_BROKER}|{_EN_BROKER})\s*:\s*(?:לא|אין|ללא|no|none)\s*[!.]*\s*$", re.IGNORECASE),
    # brokers and "don't contact", either order, at most one word between
    # (a colon after the broker word too, v1.28: "מתווכים: נא לא לפנות"; ":" doesn't split a clause)
    re.compile(rf"{_HE_BROKERS}(?:\s*:\s*|\s+)(?:\S+\s+)?{_HE_DONT_CONTACT}{_CLAUSE_END}", re.IGNORECASE),
    re.compile(rf"{_NOT_A_LABEL_VALUE}{_HE_DONT_CONTACT}\s+(?:\S+\s+)?{_HE_BROKERS}", re.IGNORECASE),
    re.compile(rf"\b{_EN_BROKERS}(?:\s*:\s*|\s+)(?:\S+\s+)?{_EN_DONT_CONTACT}{_CLAUSE_END}", re.IGNORECASE),
    re.compile(rf"{_NOT_A_LABEL_VALUE}\b{_EN_DONT_CONTACT}\s+(?:\S+\s+)?(?:from\s+)?{_EN_BROKERS}\b", re.IGNORECASE),
]
# "From the owner" is the standard private phrase in Hebrew listings, but
# agencies use it too ("תיווך בלעדי מהבעלים" = an exclusive listing from
# the owner, via the agency). So it only counts when no broker word
# appears in the clause other than inside a "no broker" phrase.
_FROM_OWNER_RE = re.compile(
    r"(?<!\w)ו?(?:מבעלים|מהבעלים|מבעל\s+הבית|ישירות\s+מה?בעל)"
    r"|\bdirect(?:ly)?\s+from\s+(?:the\s+)?owner\b",
    re.IGNORECASE,
)

# Across a separator, only the tightest form counts: a clause that is
# NOTHING but a broker word, next to a clause that is nothing but "don't
# contact" or a bare "no" -- "מתווכים - נא לא לפנות", "Brokers, please
# don't call", "מתווכים — לא". "Agency listing - no calls after 22:00" is
# not swept in, because "Agency listing" is more than a bare broker word.
_BARE_BROKER_RE = re.compile(rf"\s*(?:{_HE_BROKER}|{_EN_BROKER})\s*[:!.]*\s*", re.IGNORECASE)
_BARE_BROKERS_RE = re.compile(rf"\s*(?:{_HE_BROKERS}|{_EN_BROKERS})\s*[:!.]*\s*", re.IGNORECASE)
_BARE_DONT_CONTACT_RE = re.compile(
    rf"\s*(?:{_HE_DONT_CONTACT}|{_EN_DONT_CONTACT}|לא|no|nope)(?:\s+(?:תודה|thanks?|thank\s+you))?\s*[!.]*\s*",
    re.IGNORECASE,
)


_BARE_NO_RE = re.compile(r"\s*(?:לא|אין|ללא|no|none|nope)\s*[!.]*\s*", re.IGNORECASE)


def _classify_clause(clause: str) -> ListedBy | None:
    waiver = bool(_FEE_WAIVER_RE.search(clause))
    no_broker = any(r.search(clause) for r in _PRIVATE_RES)
    from_owner = bool(_FROM_OWNER_RE.search(clause))
    if waiver and (no_broker or from_owner):
        return None  # "ללא עמלה ישירות מהבעלים": both readings present
    if waiver:
        return ListedBy.AGENCY
    if no_broker:
        return ListedBy.PRIVATE
    has_broker = bool(_BROKER_RE.search(clause))
    if from_owner:
        return None if has_broker else ListedBy.PRIVATE
    if not has_broker or _ANY_NEGATION_RE.search(clause):
        return None
    if _BARE_BROKER_RE.fullmatch(clause):
        # A lone "Brokers" / "תיווך" says nothing about THIS listing; it's
        # usually half of "Brokers - no thanks". AGENCY needs a phrase
        # describing the listing ("Agency listing", "משרד תיווך X").
        return None
    return ListedBy.AGENCY


_FEE_WORD_RE = re.compile(r"\bfees?\b|\bcommission\b|עמלה|עמלת|דמי\s+תיווך", re.IGNORECASE)


def _classify_flag(flag: str) -> list[ListedBy | None]:
    clauses = split_clauses(flag)
    # "Agent - no, fee 1 month": a fee mentioned anywhere in the flag means
    # the singular features-list "no" may not be about the listing.
    mentions_fee = bool(_FEE_WORD_RE.search(flag))
    verdicts = [_classify_clause(c) for c in clauses]
    for i in range(len(clauses) - 1):
        a, b = clauses[i], clauses[i + 1]
        if (
            (_BARE_BROKERS_RE.fullmatch(a) and _BARE_DONT_CONTACT_RE.fullmatch(b))
            or (_BARE_DONT_CONTACT_RE.fullmatch(a) and _BARE_BROKERS_RE.fullmatch(b))
            # A features-list answer -- "מתווך - לא", "Broker: no", "תיווך - אין"
            # -- is a "no" even with a singular broker word. Only a bare "no"
            # counts here; a singular word next to "don't call" may be the
            # broker talking about themself.
            or (not mentions_fee and _BARE_BROKER_RE.fullmatch(a) and _BARE_NO_RE.fullmatch(b))
        ):
            verdicts[i] = verdicts[i + 1] = ListedBy.PRIVATE
    return verdicts


def detect_listed_by(flags: list[str]) -> ListedBy | None:
    verdicts = {v for flag in flags for v in _classify_flag(flag) if v is not None}
    return verdicts.pop() if len(verdicts) == 1 else None
