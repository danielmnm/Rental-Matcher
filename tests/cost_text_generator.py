"""
Generates random listing-note text with a KNOWN correct answer, for
property-testing rental_matcher.costs.

Each generated flag is a sequence of clauses. Every clause carries its own
ground truth (which field it really states an amount for, if any), so a
test can check the parser against what the text actually says rather than
against cases someone happened to think of.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

VAAD_KEYWORDS = ["ועד בית", "ועד הבית", "vaad bayit", "Vaad Bayit"]
ARNONA_KEYWORDS = ["ארנונה", "arnona", "Arnona"]
CURRENCY = ["", "₪", "₪ ", ""]
CURRENCY_AFTER = ["", " ש\"ח", " ₪", " NIS", ""]
# Widened in v1.7 after the seventh review found shapes this generator
# never produced: "/חודש", "ל-2 חודשים", decimal thousands, zero amounts.
MONTHLY = [" לחודש", "/mo", " per month", " monthly", " בחודש", "/חודש", " a month", "/month"]
BIMONTHLY = [" לחודשיים", " דו-חודשי", " bi-monthly", " every two months", " ל-2 חודשים", " per 2 months"]
NOISE = [
    "{n} חדרים", "{n} rooms", "{n} photos", "קומה {n}", "{n} מעליות",
    "Price dropped ₪5,000→₪4,500", "{n}% הנחה", "2025", "{n} דירות בבניין",
    "no parking", "מעלית", "A/C yes", "ממ\"ד", "חניה {n} מטר", "elevator",
]
NEGATED = ["ללא ועד בית", "no vaad bayit", "vaad bayit: none", "ללא ארנונה", "אין ועד בית"]
# Every way the real data (and real listings) separate clauses, including
# the dangerous one: a bare space.
JOINERS = [", ", " — ", " – ", "; ", " - ", " ", " and ", " | "]
# Added in v1.7 from an independent review: things that qualify an amount
# from the far side of a separator, and more ways to join two keywords
# that share one combined amount.
QUALIFIERS = ["per year", "לשנה", "שנתי", "לכל שותף", "per person", "למ\"ר", "200", "כולל ועד", "including arnona"]
COMBINED_JOINERS = [" ו", " + ", " and ", " כולל ", " including ", " plus ", " וגם ", ", "]


def _amount(rng: random.Random, lo: int, hi: int) -> tuple[float, str]:
    value = rng.randint(lo, hi)
    if value >= 1000 and rng.random() < 0.2:
        value_f = value + 0.5
        return value_f, f"{value_f:,.2f}"  # "1,200.50"
    if value >= 1000 and rng.random() < 0.5:
        return float(value), f"{value:,}"
    if rng.random() < 0.15:
        value_f = value + 0.5
        return value_f, f"{value_f}"
    return float(value), str(value)


@dataclass
class GeneratedFlags:
    flags: list[str]
    # Every amount the text truly states for each field. The parser is
    # allowed to return any one of these, or None -- never anything else.
    true_vaad: set[float] = field(default_factory=set)
    true_arnona: set[float] = field(default_factory=set)


def _cost_clause(rng: random.Random, out: GeneratedFlags) -> str:
    kind = rng.choice(["vaad", "arnona", "negated", "negated_combined", "combined", "zero", "qualified", "ambiguous_number"])
    if kind == "qualified":
        # A real amount, but its qualifier sits past a separator: never monthly-as-stated.
        _, text = _amount(rng, 100, 3000)
        return f"{rng.choice(VAAD_KEYWORDS + ARNONA_KEYWORDS)} {text}{rng.choice(['', ' לחודש', '/mo'])}{rng.choice([' - ', ', ', '; '])}{rng.choice(QUALIFIERS)}"
    if kind == "ambiguous_number":
        # "1.200" (period thousands or decimal) and "70+" (at least 70).
        keyword = rng.choice(VAAD_KEYWORDS)
        return rng.choice([f"{keyword} {rng.randint(1, 9)}.{rng.randint(100, 999)}", f"{keyword} {rng.randint(30, 900)}+"])
    if kind == "negated":
        return rng.choice(NEGATED)
    if kind == "negated_combined":
        # "ללא ארנונה וועד בית 400": a negation with only a conjunction after
        # its keyword covers both keywords, so the amount belongs to neither.
        _, text = _amount(rng, 100, 1500)
        first, second = rng.sample([rng.choice(VAAD_KEYWORDS), rng.choice(ARNONA_KEYWORDS)], 2)
        negation = rng.choice(["ללא ", "בלי ", "אין ", "לא כולל ", "without ", "no "])
        conjunction = rng.choice([" ו", " and ", " + ", " וגם ", " & "])
        return f"{negation}{first}{conjunction}{second} {text}{rng.choice(MONTHLY + [''])}"
    if kind == "zero":
        # "none" in numeric form: never a true amount for RecurringCosts.
        keyword = rng.choice(VAAD_KEYWORDS + ARNONA_KEYWORDS)
        return f"{keyword} {rng.choice(['', '₪', '₪ '])}{rng.choice(['0', '0.0', '0.00'])}{rng.choice(MONTHLY + [''])}"
    if kind == "combined":
        value, text = _amount(rng, 200, 1500)
        joiner = rng.choice(COMBINED_JOINERS)
        return f"{rng.choice(ARNONA_KEYWORDS)}{joiner}{rng.choice(VAAD_KEYWORDS)} {text}{rng.choice(MONTHLY)}"

    keywords = VAAD_KEYWORDS if kind == "vaad" else ARNONA_KEYWORDS
    value, text = _amount(rng, 30, 900) if kind == "vaad" else _amount(rng, 200, 2500)
    frequency_kind = rng.choice(["none", "monthly", "bimonthly"])
    frequency = {"none": "", "monthly": rng.choice(MONTHLY), "bimonthly": rng.choice(BIMONTHLY)}[frequency_kind]
    clause = f"{rng.choice(keywords)}{rng.choice([' ', ': ', ' '])}{rng.choice(CURRENCY)}{text}{rng.choice(CURRENCY_AFTER)}{frequency}"

    if kind == "vaad" and frequency_kind != "bimonthly":
        out.true_vaad.add(value)
    if kind == "arnona" and frequency_kind == "monthly":
        out.true_arnona.add(value)
    return clause


def generate(rng: random.Random) -> GeneratedFlags:
    out = GeneratedFlags(flags=[])
    for _ in range(rng.randint(1, 4)):
        clauses = []
        for _ in range(rng.randint(1, 4)):
            if rng.random() < 0.55:
                clauses.append(_cost_clause(rng, out))
            else:
                clauses.append(rng.choice(NOISE).format(n=rng.randint(1, 9)))
        flag = clauses[0]
        for clause in clauses[1:]:
            flag += rng.choice(JOINERS) + clause
        out.flags.append(flag)
    return out
