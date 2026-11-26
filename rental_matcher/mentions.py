"""
Flags for things a listing's free text MENTIONS, carrying the words as
evidence, without deciding what they mean (v1.12).

Why not decide: the deterministic parsers in costs.py and listed_by.py
tried to read meaning from free text ("is this a broker?", "is 200 the
monthly vaad bayit?"), and every review round found a phrasing that gave a
wrong answer -- "לא מתווכחים" ("no haggling") read as a broker word, "paid
annually" read as monthly, "per roommate" read as the whole flat. Word
lists can't cover a language. A flag only claims "these words appear
here", which is checkable and can't be wrong in that way; the person
reading the listing, or the Phase 2 extractor, decides what they mean.

Brokers: since March 9, 2025, the Real Estate Brokers Regulations (Ethics
and Professional Duties) 2024 require a broker to display their details,
including their license number, on every advertisement. So a lawful
broker listing carries an indicator, and this flag is built to catch one.
Its absence suggests a private listing but does not confirm it (not
every advertiser complies), which is why `listed_by` stays unset.

Each flag is a Signal with status UNCONFIRMED ("a hint, not enough to
commit to a value") and the matched text as `evidence`.
"""

from __future__ import annotations

import re
from typing import Optional

from .costs import _KEYWORD_RE as _COST_KEYWORD_RE
from .schema import ExtractedBy, Signal, SignalStatus

_HE = "א-ת"
# Hebrew attaches prepositions and articles to the front of a word (ה, ו,
# ב, ל, מ, ש, כ: "והמתווך", "ללא תיווך" has "תיווך" as its own word). The
# word itself must end at a non-letter, so "מתווכחים" ("arguing") is not
# "מתווכים" ("brokers").
_HE_BROKER = rf"(?<![{_HE}])[והבלמשכ]{{0,3}}(?:תיווך|מתווך|מתווכ(?:ים|ת|ות))(?![{_HE}])"
_NO = r"(?:מס(?:פר)?['׳.]?|No\.?|number|#)"
_LICENSE_WORD = r"(?:רישיון|רשיון)(?:\s+תיווך)?"
# A license number: "רישיון תיווך מס' 31245", "רשיון מס. 31245". The law
# requires one on every broker ad. "מספר רישיון: 31245" and "מס' רישיון 31245"
# match too, from the license word on (the number word before it isn't
# needed, so it isn't spelled out).
_HE_LICENSE = rf"(?<![{_HE}])[והבלמשכ]{{0,2}}{_LICENSE_WORD}\s*(?:{_NO}\s*)?[:#]?\s*\d{{3,}}"
# Real-estate agents and offices: סוכן / סוכנת / סוכנות / משרד / יועץ נדל"ן
# (סוכן ends in a final nun, so it is spelled out, not stem + suffix).
_HE_AGENT = rf"(?<![{_HE}])[והבלמשכ]{{0,2}}(?:סוכן|סוכנ(?:ת|ות|ים)|משרד(?:י)?|יועץ|יועצ(?:ת|ים))\s+(?:ה)?נדל[\"״'׳]?ן"
_EN_BROKER = (
    r"\b(?:brokers?|brokerage|realtors?|real[\s-]estate\s+(?:agents?|agency|office|broker)"
    r"|(?:agency|agent'?s?|broker'?s?|finder'?s?)\s+fees?"
    r"|lic(?:en[cs]e)?\.?\s*(?:no\.?|number|#)?\s*[:#]?\s*\d{3,})\b"
)
_BROKER_RE = re.compile(rf"{_HE_BROKER}|{_HE_LICENSE}|{_HE_AGENT}|{_EN_BROKER}", re.IGNORECASE)

# A text this short is kept whole: cutting it at a comma would drop the
# qualifier ("ועד בית 200, אחת לחודשיים") that decides what the amount means.
_WHOLE_TEXT_MAX = 160
# Longer texts: from the start of the match's sentence (at most _BEFORE
# back -- "בעל הבית משלם: ועד בית 150" needs the words before it) to
# _AFTER past it (qualifiers usually follow the amount). Windows that
# overlap are merged, so no text appears twice.
_BEFORE, _AFTER = 120, 90
_SENTENCE_END = re.compile(r"[.!?;|\n]\s")
_EVIDENCE_MAX = 400


def _windows(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in pattern.finditer(text):
        floor = max(0, m.start() - _BEFORE)
        ends = [e.end() for e in _SENTENCE_END.finditer(text, floor, m.start())]
        a, b = (ends[-1] if ends else floor), min(len(text), m.end() + _AFTER)
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], b))
        else:
            spans.append((a, b))
    return spans


def _pieces(texts: list[str], pattern: re.Pattern[str]) -> list[str]:
    pieces = []
    for text in texts:
        if not isinstance(text, str) or not pattern.search(text):
            continue
        if len(text) <= _WHOLE_TEXT_MAX:
            pieces.append(text.strip())
            continue
        for a, b in _windows(text, pattern):
            pieces.append(("…" if a > 0 else "") + text[a:b].strip() + ("…" if b < len(text) else ""))
    return pieces


def _flag(pieces: list[str]) -> Optional[Signal]:
    if not pieces:
        return None
    evidence = " | ".join(dict.fromkeys(pieces))  # de-duplicated, in order
    if len(evidence) > _EVIDENCE_MAX:
        evidence = evidence[: _EVIDENCE_MAX - 1] + "…"
    return Signal(status=SignalStatus.UNCONFIRMED, evidence=evidence, extracted_by=ExtractedBy.RULE)


def brokerage_mention(texts: list[str]) -> Optional[Signal]:
    """A flag if any text mentions brokerage or a broker's license, with
    every match as evidence ("ללא תיווך" is evidence too: the reader sees it
    says no broker). None when nothing matches."""
    return _flag(_pieces(texts, _BROKER_RE))


def recurring_costs_mention(texts: list[str]) -> Optional[Signal]:
    """A flag if any text mentions vaad bayit or arnona, with the text
    around each mention as evidence -- amount, period and qualifiers
    included, since those are exactly what a word list can't be trusted to
    read."""
    return _flag(_pieces(texts, _COST_KEYWORD_RE))
