"""
Deterministic extraction of recurring monthly costs (vaad bayit, arnona)
from free-text listing notes.

Design rule: when in doubt, don't extract. A missed amount stays in
`notes` as readable text; a wrong amount silently corrupts the scoring
engine's cost math. So every rule below exists to REJECT a candidate,
never to rescue one. Anything this can't parse confidently is Phase 2's
job (the LLM extraction pipeline, which has an evaluation set).

How a candidate amount is found, per flag string (never across flags):

1. Split the flag into clauses on separators that can't be part of a
   number: ';', '|', a spaced hyphen (' - '), an em/en dash not between
   digits, a comma not acting as a thousands separator ("1,200"), and a
   period not acting as a decimal point ("70.5").
2. Within a clause, each cost keyword owns the text from the end of the
   keyword up to the start of the NEXT cost keyword (or the clause end).
   Two keywords with no number between them share one amount, so
   neither gets it -- checked across the whole flag, commas included.
   That's what stops "ועד בית 70 לחודש וארנונה 800 לחודשיים" from lending
   vaad bayit's "לחודש" to arnona.
3. The amount must follow its keyword with nothing but whitespace or
   ':', '=', '~', '₪' in between. No letters: "vaad bayit: none 6
   photos" never reaches the 6.
4. After the amount, only a currency, a frequency word, and a trailing
   conjunction may follow (a whitelist -- see _TAIL). If the amount ends
   its clause, the NEXT clause mustn't start by qualifying it ("- per
   year", ", לכל שותף", "- 200"). Also
   reject if the keyword is negated ("ללא ועד בית 4 דירות"), if two
   keywords share one amount ("ארנונה וועד בית 400" is a combined total),
   or if a bi-monthly marker appears in the keyword's span.
5. Arnona additionally needs an explicit monthly marker in its own span,
   because it's conventionally billed bi-monthly in Israel and a bare
   figure is ambiguous by a factor of two. Vaad bayit has no such
   convention and is accepted without one.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # imported lazily below, so the rule-based extractor runs without pydantic
    from .schema import RecurringCosts

_KEYWORD_RE = re.compile(
    r"(?P<vaad>vaad\s*(?:ha)?\s*bayit|ועד\s*(?:ה)?בית)|(?P<arnona>arnona|ארנונה)",
    re.IGNORECASE,
)

_CLAUSE_SPLIT_RE = re.compile(
    r";|\|"
    r"|\s-\s"
    r"|(?<!\d)[–—]|[–—](?!\d)"
    r"|(?<!\d),|,(?!\d{3}(?!\d))"
    r"|(?<!\d)\.|\.(?!\d)"
    r"|\n"
)

_AMOUNT = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
# Anchored at the start of a keyword's span: only non-letter filler allowed.
# v1.51: "כ" / "כ-" (about) before the number: "ארנונה כ 600 ש\"ח לחודש" (the labeled listings)
_ABOUT = r"(?:כ[\-־]?\s*)?"
_AMOUNT_AFTER_KEYWORD_RE = re.compile(rf"^[\s:=~₪]*{_ABOUT}(?P<amount>{_AMOUNT})")
# v1.64: "ועד בית - 150 ש\"ח בחודש" (Komo batch 2): a dash between a fee's name and its amount isn't a new clause.
# Blanked to spaces of the same length, so every offset (the evidence) stays the text's own.
_DASH_AFTER_KEYWORD_RE = re.compile(r"((?<![א-ת])ו?(?:ועד\s*(?:ה)?בית|ארנונה))(\s+[\-–]\s+)(?=(?:כ[\-־]?\s*)?\d)")

# "לא" / "לא כולל" ("not" / "not including") are common negations the
# earlier version missed, so "לא כולל ועד בית 100" wrongly extracted 100.
# Adding to a negation only ever REMOVES an extraction (never creates a
# wrong one), so it can't break soundness; it costs a little recall where a
# word happens to end in "לא".
_NEGATION_BEFORE_RE = re.compile(r"(?:ללא|בלי|אין|לא(?:\s+כולל)?|\bno|\bnot|\bwithout)\s*$", re.IGNORECASE)
# A zero amount is never extracted (see _candidates), so "0" doesn't need
# to be listed here -- listing it was how "₪0" slipped past this check.
_NEGATION_AFTER_RE = re.compile(r"^[\s:=~₪]*(?:none|n/a|אין|ללא)", re.IGNORECASE)

# Frequency phrases, each defined ONCE. Every regex below is built from
# these two lists, so the "is it monthly?" check and the "what may follow
# an amount?" whitelist can't disagree (they did: "450/חודש" passed one
# and failed the other). Python's \b treats Hebrew letters as word
# characters, so "לחודש\b" does not match inside "לחודשיים".
_MONTHLY_PHRASES = [
    r"/\s*mo(?:nth)?\b", r"/\s*חודש\b", r"per\s*month\b", r"\ba\s*month\b",
    r"\bmonthly\b", r"לחודש\b", r"בחודש\b", r"חודשי\b",
]
_BIMONTHLY_PHRASES = [
    r"לחודשיים", r"דו[\s\-־]?חודשי", r"\bbi[\s\-]?monthly\b",
    r"every\s*(?:two|2)\s*months\b", r"per\s*2\s*months\b", r"ל[\s\-]?2\s*חודשים",
]
_MONTHLY = "|".join(_MONTHLY_PHRASES)
_BIMONTHLY = "|".join(_BIMONTHLY_PHRASES)
# Bi-monthly is checked before monthly wherever both apply: "דו-חודשי"
# contains "חודשי".
_BIMONTHLY_RE = re.compile(_BIMONTHLY, re.IGNORECASE)
_MONTHLY_RE = re.compile(_MONTHLY, re.IGNORECASE)

# WHITELIST of what may follow an amount, up to the end of its keyword's
# span: an optional currency, an optional frequency, an optional trailing
# conjunction that belongs to the next keyword. Anything else -- "4
# חדרים", "2 מעליות", "10%", "50 למ\"ר", "150-200", "2025: 450", "1 200",
# "70 (paid by landlord)" -- means the number may not be the amount, so
# nothing is extracted. A blacklist of bad units was tried first and
# failed on the first adversarial pass; there is no complete list of
# things a number in a listing can count.
_CURRENCY = r"₪|ש[\"״']?ח|nis\b|ils\b|shekels?\b|שקלים|שקל"
_TAIL = rf"\s*(?:{_CURRENCY})?\s*(?:{_BIMONTHLY}|{_MONTHLY})?\s*"
# A trailing conjunction is allowed only when another cost keyword follows
# in the same clause (it belongs to that keyword); at the end of a clause,
# "70+" means "at least 70", not 70.
# The conjunction must be set off by whitespace: "70 + ארנונה" joins two
# items, but "70+" glued to the digits means "at least 70".
_ALLOWED_TAIL_BEFORE_KEYWORD_RE = re.compile(rf"{_TAIL}(?:(?<=\s)(?:ו|and\b|&|\+))?\s*", re.IGNORECASE)
_ALLOWED_TAIL_AT_END_RE = re.compile(_TAIL, re.IGNORECASE)

# "1.200" is a thousands figure written with a period (common in Europe),
# or a decimal; either reading is possible, so neither is guessed.
_AMBIGUOUS_PERIOD_THOUSANDS_RE = re.compile(r"\d{1,3}\.\d{3}")

# The start of the NEXT clause, when it qualifies the amount just before
# the separator: "1200 - per year", "400 לחודש, לכל שותף", "150 - 200",
# "450, כולל ועד". A separator mustn't hide that from the tail whitelist.
# Periods other than a month. Used both after a separator (", לחודשיים",
# "- quarterly") and before the keyword ("Annual: vaad bayit 1200").
_OTHER_PERIOD = (
    r"yearly\b|annual|per\s+year|a\s+year|quarterly|per\s+quarter|once\s+a\s+year"
    r"|לשנה|בשנה|שנתי|לרבעון|רבעוני|פעם\s+ב(?:שנה|רבעון|חודשיים)"
)
_OTHER_PERIOD_RE = re.compile(rf"{_OTHER_PERIOD}|{_BIMONTHLY}", re.IGNORECASE)
_QUALIFIER_START_RE = re.compile(
    r"\s*(?:/|per\b|each\b|every\b|for\s+(?:each|every)\b|a\s+(?:year|month)\b"
    r"|incl|including\b|plus\b"
    r"|לכל|לאדם|לשותף|לחדר|לדייר|לראש|לנפש|לשוכר|למ[\"״]ר|למטר|כל\s|ל-?\d|כולל|לא\s+כולל|וגם|פלוס"
    rf"|{_OTHER_PERIOD}|{_BIMONTHLY})",
    re.IGNORECASE,
)
# If the amount ends its clause and the next clause starts with a number,
# the amount isn't taken: that number may be the other end of a range
# ("150 - 200") or qualify the amount. Two attempts to allow "safe" cases
# (a bare-number test, then a list of units like "– 2 דירות") each failed
# on the next generator run ("…, 200 no parking", "…, 200 קומה 2"), so this
# is deliberately blunt and costs some recall.
_STARTS_WITH_NUMBER_RE = re.compile(r"\s*\d")


def _clause_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for sep in _CLAUSE_SPLIT_RE.finditer(text):
        spans.append((pos, sep.start()))
        pos = sep.end()
    spans.append((pos, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def split_clauses(text: str) -> list[str]:
    return [text[a:b] for a, b in _clause_spans(text)]


def _parse_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def _joined_keyword_starts(flag: str) -> set[int]:
    """Positions of cost keywords that share one amount with a neighbour:
    two keywords with no number between them ("ארנונה וועד בית 400", "vaad
    bayit including arnona 600", "ארנונה, ועד בית 600") state a combined
    total, unless the first is negated and a separator ends that negation
    ("ללא ועד בית, ארנונה 450 לחודש"). A negation followed by only a
    conjunction covers both keywords, so both are refused. Checked across
    the whole flag, so a comma between them doesn't hide it.
    """
    keywords = list(_KEYWORD_RE.finditer(flag))
    joined: set[int] = set()
    for first, second in zip(keywords, keywords[1:]):
        between = flag[first.end() : second.start()]
        if re.search(r"\d", between):
            continue
        if bool(first.group("vaad")) == bool(second.group("vaad")):
            continue  # the same fee named twice ("כולל ועד בית. ועד בית 150") isn't a combined total (v1.28)
        if _NEGATION_BEFORE_RE.search(flag[: first.start()]):
            # "ללא ועד בית, ארנונה 450": a separator ends the negation's scope,
            # so the second keyword stands alone. "ללא ארנונה וועד בית 400":
            # with only a conjunction between them the negation covers BOTH
            # ("without arnona and vaad bayit"), so neither may take the 400.
            if _CLAUSE_SPLIT_RE.search(between):
                continue
        elif _NEGATION_AFTER_RE.match(between):
            continue
        joined.update({first.start(), second.start()})
    return joined


def _candidates(flag: str) -> list[tuple[str, float]]:
    """(field, amount) pairs this flag supports, in order of appearance."""
    return [(field, amount) for field, amount, _, _ in candidate_spans(flag)]


# "ארנונה דו חודשית: 450" -- the bi-monthly marker between keyword and amount.
_BIMONTHLY_THEN_AMOUNT_RE = re.compile(rf"^[\s:=~₪]*(?:{_BIMONTHLY})(?:ת)?[\s:=~₪]*{_ABOUT}(?P<amount>{_AMOUNT})", re.IGNORECASE)


def candidate_spans(flag: str, bimonthly_arnona: bool = False) -> list[tuple[str, float, int, int]]:
    """(field, monthly amount, start, end) for each confident amount; start
    and end bound the keyword-to-amount text in `flag` (the evidence).

    bimonthly_arnona=False (what parse_recurring_costs uses) refuses any
    amount with a bi-monthly marker, as it always has. True accepts ARNONA
    whose own span says it's per two months -- "ארנונה 700 לחודשיים",
    "ארנונה דו חודשית: 450" -- and returns HALF, the monthly amount. Every
    other rejection rule still applies unchanged."""
    flag = _DASH_AFTER_KEYWORD_RE.sub(lambda m: m.group(1) + " " * len(m.group(2)), flag)
    spans = _clause_spans(flag)
    joined = _joined_keyword_starts(flag)
    first_kw = _KEYWORD_RE.search(flag)
    # The heading before the first cost keyword ("Annual: vaad bayit 1200"):
    # its own clause, plus a one-word clause right before it ("שנתי - ועד בית
    # 1200"). Not the whole text before it (v1.28): a full description's
    # "להשכרה לשנה. ועד בית 150" isn't a yearly fee.
    header = ""
    if first_kw:
        at = next((i for i, (a, b) in enumerate(spans) if a <= first_kw.start() < b), None)
        if at is not None:
            header = flag[spans[at][0] : first_kw.start()]
            if at > 0 and len(flag[spans[at - 1][0] : spans[at - 1][1]].split()) == 1:
                header = flag[spans[at - 1][0] : spans[at - 1][1]] + " " + header
    found: list[tuple[str, float, int, int]] = []
    for ci, (start, end) in enumerate(spans):
        clause = flag[start:end]
        next_clause = flag[spans[ci + 1][0] : spans[ci + 1][1]] if ci + 1 < len(spans) else ""
        keywords = list(_KEYWORD_RE.finditer(clause))
        previous_amount_end = 0  # clause offset where the previous keyword's own amount ended
        for i, kw in enumerate(keywords):
            field = "vaad" if kw.group("vaad") else "arnona"
            has_next = i + 1 < len(keywords)
            span = clause[kw.end() : keywords[i + 1].start() if has_next else len(clause)]
            own_amount = _AMOUNT_AFTER_KEYWORD_RE.match(span)
            marker_first = False
            if own_amount is None and bimonthly_arnona and field == "arnona":
                own_amount = _BIMONTHLY_THEN_AMOUNT_RE.match(span)
                marker_first = own_amount is not None
            # Text before this keyword that isn't the previous keyword's own
            # amount. A number there means amounts may be written BEFORE
            # their keywords ("70 ש״ח ועד בית 400 ש״ח ארנונה"), so the number
            # after this keyword may belong to the next one; a non-monthly
            # period there ("Annual: vaad bayit 1200") qualifies the amount.
            before = clause[previous_amount_end : kw.start()]
            previous_amount_end = kw.end() + own_amount.end() if own_amount else kw.end()
            if re.search(r"\d", before):
                continue
            if start + kw.start() in joined:
                continue

            if _NEGATION_BEFORE_RE.search(clause[: kw.start()]) or _NEGATION_AFTER_RE.match(span):
                continue
            m = own_amount
            if m is None or _AMBIGUOUS_PERIOD_THOUSANDS_RE.fullmatch(m.group("amount")):
                continue
            after = span[m.end() :]
            tail = _ALLOWED_TAIL_BEFORE_KEYWORD_RE if has_next else _ALLOWED_TAIL_AT_END_RE
            if not tail.fullmatch(after):
                continue
            if not has_next and (
                _QUALIFIER_START_RE.match(next_clause) or _STARTS_WITH_NUMBER_RE.match(next_clause)
            ):
                continue
            if _BIMONTHLY_RE.search(span):
                # Only the opt-in path, only arnona, and only when the marker is
                # this amount's own: right after it (in the whitelisted tail,
                # with no monthly word too) or right before it.
                if not (bimonthly_arnona and field == "arnona"):
                    continue
                if marker_first:
                    if _BIMONTHLY_RE.search(after) or _MONTHLY_RE.search(after):
                        continue
                elif not _BIMONTHLY_RE.search(after) or _BIMONTHLY_RE.search(span[: m.start("amount")]):
                    continue
                if _MONTHLY_RE.search(_BIMONTHLY_RE.sub("", after)):
                    continue
                amount = _parse_amount(m.group("amount"))
                if amount > 0:
                    found.append((field, amount / 2, start + kw.start(), start + kw.end() + len(span.rstrip())))
                continue
            explicit_monthly = bool(_MONTHLY_RE.search(after))
            if field == "arnona" and not explicit_monthly:
                continue
            # A non-monthly period can qualify this amount from two places:
            # a heading before the flag's first keyword ("Annual: vaad bayit
            # 1200"), or text inside this clause before the keyword but after
            # the previous keyword's own amount (`before`). A period word
            # that belongs to an EARLIER keyword's own clause ("ארנונה 800
            # לחודשיים, ועד בית 150") must NOT reach across to this one -- that
            # was order-dependent. Checking only the heading and `before`
            # keeps the heading rule and drops the cross-clause leak.
            if not explicit_monthly and (_OTHER_PERIOD_RE.search(header) or _OTHER_PERIOD_RE.search(before)):
                continue
            amount = _parse_amount(m.group("amount"))
            if amount <= 0:
                # "vaad bayit 0" / "₪0" means "none", which RecurringCosts
                # can't distinguish from "not stated" -- not extracted.
                continue
            found.append((field, amount, start + kw.start(), start + kw.end() + len(span.rstrip())))
    return found


def parse_recurring_costs(flags: list[str]) -> RecurringCosts | None:
    """Return the first confident vaad bayit / arnona monthly amounts found
    across `flags`, each flag parsed on its own. Returns None (not an
    empty RecurringCosts) when nothing confident is found, so an absent
    value never masquerades as a checked-and-zero one."""
    vaad: float | None = None
    arnona: float | None = None
    for flag in flags:
        for field, amount in _candidates(flag):
            if field == "vaad" and vaad is None:
                vaad = amount
            elif field == "arnona" and arnona is None:
                arnona = amount
    if vaad is None and arnona is None:
        return None
    from .schema import RecurringCosts

    return RecurringCosts(vaad_bayit_monthly=vaad, arnona_monthly=arnona)
