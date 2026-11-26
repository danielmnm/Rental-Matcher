"""
Phase 2: score an extractor's answers against the labeled test set.

The gold set is two independent labelers' answers merged (`build_gold`):
for each listing x question, the ACCEPTABLE answers are everything either
labeler said or marked as also defensible. The two agreed exactly on
192 of 200 items, and every remaining one was compatible, so nothing
needed overruling.

Three outcomes per item, and the metric that matters most is the first:
- WRONG: a definite answer outside the acceptable set ("yes, there's a
  shelter" when the text says nothing). This is what corrupts a match;
  the scoring engine trusts a confirmed signal.
- MISSED: "not_stated" where the text does settle it. Costs coverage,
  never correctness: the listing gets a "check" instead.
"unclear" is graded exactly like not_stated -- an abstention, never wrong,
never coverage -- because what it does downstream is the same (a check),
just with the words to look at. It's counted on its own (FLAGGED) so a
reader that flags everything can't hide: its coverage would collapse.
- CORRECT: inside the acceptable set (for an amount, the number matches).

A list question (furniture) is graded on its ids: the gold REQUIRES the
ids both labelers named and ALLOWS any id either one named or marked
defensible. Naming an id nobody allowed is WRONG (the one that matters:
an AC counted as furniture); leaving out a required one is MISSED.

Reported per question and overall: wrong rate (wrong / definite answers
given), coverage (correct definite answers / items whose gold has one).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from .questions import BY_ID, NOT_STATED, QUESTIONS, UNCLEAR

Answers = dict[str, dict[str, dict[str, Any]]]  # listing id -> question id -> {"answer", "value"?, "evidence"?}


def _abstentions(answers: set[str]) -> set[str]:
    """not_stated and unclear are the same for grading: if a label allows
    one, it allows the other."""
    return answers | {NOT_STATED, UNCLEAR} if answers & {NOT_STATED, UNCLEAR} else answers


def _entry(labels: Answers, listing: str, question: str) -> dict[str, Any]:
    return labels.get(listing, {}).get(question) or {"answer": NOT_STATED}


def build_gold(a: Answers, b: Answers, adjudications: Optional[list[dict[str, Any]]] = None) -> dict[str, dict[str, dict[str, Any]]]:
    """Merge two labelers. Raises ValueError on a real conflict (neither's
    answer acceptable to the other): that needs a human, not a rule.
    `adjudications` (tests/eval/yad2_adjudications.json) are changes made
    after a model's answers were seen: each only widens `acceptable`, and
    carries its note into the gold so the change is visible where it's used."""
    gold: dict[str, dict[str, dict[str, Any]]] = {}
    for listing in sorted(set(a) | set(b)):
        gold[listing] = {}
        for q in QUESTIONS:
            ea, eb = _entry(a, listing, q.id), _entry(b, listing, q.id)
            sa = {ea["answer"], *ea.get("also_ok", [])}
            sb = {eb["answer"], *eb.get("also_ok", [])}
            if ea["answer"] not in _abstentions(sb) and eb["answer"] not in _abstentions(sa):
                raise ValueError(f"{listing}/{q.id}: labelers conflict ({ea['answer']!r} vs {eb['answer']!r})")
            # The number comes with an amount answer, or with "amount" marked also_ok.
            values = {e["value"] for e in (ea, eb) if "value" in e and (e["answer"] == "amount" or "amount" in e.get("also_ok", []))}
            if len(values) > 1:
                raise ValueError(f"{listing}/{q.id}: labelers disagree on the amount {sorted(map(str, values))}")
            acceptable = sorted(sa | sb)
            for answer in acceptable:
                if answer not in q.answers:
                    raise ValueError(f"{listing}/{q.id}: {answer!r} is not an answer to this question")
            gold[listing][q.id] = {
                "answer": ea["answer"],
                "acceptable": acceptable,
                **({"value": values.pop()} if values else {}),
                **(_gold_items(listing, q, ea, eb) if q.items else {}),
                "evidence": ea.get("evidence") or eb.get("evidence") or "",
            }
    for adj in adjudications or []:
        entry = gold[adj["listing"]][adj["question"]]
        for answer in adj["also_ok"]:
            if answer not in BY_ID[adj["question"]].answers:
                raise ValueError(f"{adj['listing']}/{adj['question']}: {answer!r} is not an answer to this question")
        entry["acceptable"] = sorted(set(entry["acceptable"]) | set(adj["also_ok"]))
        if "value" in adj:
            if "value" in entry and entry["value"] != adj["value"]:
                raise ValueError(f"{adj['listing']}/{adj['question']}: an adjudication can't change a labeled amount")
            entry["value"] = adj["value"]
        entry["adjudicated"] = adj["note"]
    for listing, by_q in gold.items():
        for qid, entry in by_q.items():
            # An acceptable amount with no number to check would mark every
            # amount wrong, the right one included.
            if "amount" in entry["acceptable"] and "value" not in entry:
                raise ValueError(f"{listing}/{qid}: 'amount' is acceptable but no labeler gave the number")
    return gold


def _gold_items(listing: str, q: Any, ea: dict[str, Any], eb: dict[str, Any]) -> dict[str, list[str]]:
    """A list question's ids: required = named by every labeler who
    answered with a list; allowed = named or marked defensible by either."""
    named = [set(e.get("items") or []) for e in (ea, eb) if e["answer"] == "items"]
    allowed = set().union(*named, *(set(e.get("also_ok_items") or []) for e in (ea, eb)))
    for item in allowed:
        if item not in q.items:
            raise ValueError(f"{listing}/{q.id}: {item!r} is not an item of this question")
    listed = any("items" in e.get("also_ok", []) for e in (ea, eb))
    if listed and not allowed:
        raise ValueError(f"{listing}/{q.id}: a list is acceptable but no labeler said which ids")
    if not named and not listed:
        return {}
    return {"items": sorted(set.intersection(*named)) if named else [], "allowed_items": sorted(allowed)}


@dataclass
class Tally:
    correct: int = 0
    wrong: int = 0
    missed: int = 0
    flagged: int = 0  # "unclear" answers: a check with the words to look at
    definite_given: int = 0  # answers other than not_stated
    definite_gold: int = 0  # items whose gold has a definite answer
    wrong_items: list[str] = field(default_factory=list)

    @property
    def wrong_rate(self) -> float:
        return self.wrong / self.definite_given if self.definite_given else 0.0

    correct_definite: int = 0  # correct, definite answers on items whose gold is definite

    @property
    def coverage(self) -> float:
        """Of the items the text settles, the share answered correctly.
        Ambiguous items (gold accepts not_stated too) don't count either
        way: a definite answer there is fine but not "coverage"."""
        return (self.correct_definite / self.definite_gold) if self.definite_gold else 1.0


def _acceptable(gold_entry: dict[str, Any]) -> set[str]:
    return _abstentions(set(gold_entry["acceptable"]))


def _definite(gold_entry: dict[str, Any]) -> bool:
    return NOT_STATED not in _acceptable(gold_entry)


def score(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers) -> dict[str, Tally]:
    """Per question id, plus "ALL"."""
    tallies = {q.id: Tally() for q in QUESTIONS}
    tallies["ALL"] = Tally()
    for listing, by_q in gold.items():
        for qid, g in by_q.items():
            got = _entry(answers, listing, qid)
            answer = got.get("answer", NOT_STATED)
            if answer not in BY_ID[qid].answers:
                answer = "__invalid__"  # an answer outside the closed set is wrong
            flagged = answer == UNCLEAR
            if flagged:
                answer = NOT_STATED  # an abstention that points at the words
            problem = ""
            partial = False
            if answer == "items":
                named = set(got.get("items") or [])
                extra = sorted(named - set(g.get("allowed_items", [])))
                if not named:
                    answer = NOT_STATED  # an empty list says nothing
                    ok = answer in _acceptable(g)
                elif "items" not in _acceptable(g) or extra:
                    ok, problem = False, f" ({', '.join(extra) or 'no list'} not acceptable)"
                elif set(g["items"]) - named:
                    # partly right: costs coverage, not correctness -- but it was a
                    # definite answer, so it counts as given (v1.28: it wasn't, which
                    # shrank wrong_rate's denominator)
                    ok, answer, partial = False, NOT_STATED, True
                else:
                    ok = True
            elif got.get("or"):
                # v1.53: "one of these" (a ticked parking box: the building's or the flat's own): right if the
                # truth is among them; it tells the user the fact only if it's exactly as precise as the truth
                options = {answer, *got["or"]}
                ok = bool(options & _acceptable(g))
                partial = ok and not options <= _acceptable(g)
                if partial:
                    answer = NOT_STATED  # right, but it doesn't settle which: no coverage, no error
            else:
                ok = answer in _acceptable(g) and (answer != "amount" or got.get("value") == g.get("value"))
            for t in (tallies[qid], tallies["ALL"]):
                t.flagged += flagged
                t.definite_gold += _definite(g)
                if answer != NOT_STATED or partial:
                    t.definite_given += 1
                if ok:
                    t.correct += 1
                    t.correct_definite += answer != NOT_STATED and _definite(g)
                elif answer == NOT_STATED:
                    t.missed += 1
                else:
                    t.wrong += 1
                    shown = f"{answer!r} {sorted(got.get('items') or [])}" if answer == "items" else repr(answer)
                    if answer == "amount":
                        shown += f" {got.get('value')!r}"
                    t.wrong_items.append(f"{listing}/{qid}: said {shown}{problem}, acceptable {g['acceptable']}"
                                         + (f" with items {g.get('allowed_items')}" if g.get("allowed_items") else "")
                                         + (f" (value {g['value']!r})" if "value" in g else ""))
    return tallies


def report(name: str, tallies: dict[str, Tally]) -> str:
    lines = [f"{name}", f"  {'question':16} {'wrong':>6} {'wrong%':>7} {'missed':>7} {'coverage':>9} {'unclear':>8}"]
    for qid, t in tallies.items():
        lines.append(f"  {qid:16} {t.wrong:>6} {t.wrong_rate:>7.0%} {t.missed:>7} {t.coverage:>9.0%} {t.flagged:>8}")
    return "\n".join(lines)


def same_questions(gold: dict[str, dict[str, dict[str, Any]]], run: Answers) -> dict[str, dict[str, dict[str, Any]]]:
    """The gold cut to the listings and questions a saved run was asked. A
    run from before a question existed isn't "missing" its answers, and a
    retired question ("furnished", replaced by "furniture" on 2026-10-20)
    can't be graded any more."""
    asked = {q for k, v in run.items() if not k.startswith("_") and isinstance(v, dict) for q in v if q in BY_ID}  # v1.28: retired ids too
    return {k: {q: e for q, e in v.items() if q in asked} for k, v in gold.items() if k in run}


def widen(gold: dict[str, dict[str, dict[str, Any]]], review: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """v1.56: the owner's review of a held-out batch (holdout10/adjudications.json), on top of the blind gold,
    which is never edited. Each entry widens what's right: `add_acceptable` (another answer the listing supports)
    or `add_allowed_items` (an item it's not wrong to name); or, v1.59, `set_acceptable`: the owner's ruling that
    the labelers were too loose and only these answers are right."""
    import copy
    out = copy.deepcopy(gold)
    for r in review:
        g = out[r["id"]][r["question"]]
        for a in r.get("add_acceptable", []):
            if a not in BY_ID[r["question"]].answers:
                raise ValueError(f"{r['id']}/{r['question']}: {a!r} is not an answer to this question")
        if r.get("set_acceptable"):  # v1.59: the owner's ruling that only these are right (a label he overrules, not a widening)
            for a in r["set_acceptable"]:
                if a not in BY_ID[r["question"]].answers:
                    raise ValueError(f"{r['id']}/{r['question']}: {a!r} is not an answer to this question")
            g["acceptable"] = sorted(set(r["set_acceptable"]))
            g["answer"] = r["set_acceptable"][0] if g.get("answer") not in r["set_acceptable"] else g["answer"]
        g["acceptable"] = sorted(set(g.get("acceptable", [])) | set(r.get("add_acceptable", [])))
        if r.get("add_allowed_items"):
            g["allowed_items"] = sorted(set(g.get("allowed_items", [])) | set(r["add_allowed_items"]))
        g["adjudicated"] = r["reason"]
    return out


def load(path: Union[str, Path]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def gold_set(eval_dir: Optional[Path] = None) -> dict[str, dict[str, dict[str, Any]]]:
    eval_dir = eval_dir or Path(__file__).resolve().parents[2] / "tests" / "eval"
    return load(eval_dir / "yad2_gold.json")["gold"]


# Phase 2's definition of done, in code so the runner and the README can't drift.
TARGET_COVERAGE = 0.95
# The first test user's must-haves when the bar was first set (Oct 18). Kept for the record:
# since v1.49 the bar covers EVERY question, since any of them can be someone's must-have.
DEALBREAKERS = ("protected_space", "room_share", "parking", "air_conditioning", "elevator")
MIN_LISTINGS = 50


def _passes(q: Any, answer: str, items: set[str], value: Any, req: tuple) -> bool:
    kind, x = req
    if kind == "is":
        return answer == x
    if kind == "is_not":
        return answer != x
    if kind == "value":  # the signal's value is what the must-have wants
        return q.values.get(answer) == x
    if kind == "at_least":
        v = q.values.get(answer) if q.values else None
        return v is not None and v >= x
    raise ValueError(kind)


# Signals a question feeds besides its own: an apartment the text calls a unit
# is a unit in someone's home, so "Not a unit in someone's home" hides it.
_FEEDS = {("apartment_type", "housing_unit"): [("is_not", "unit")]}


def requirements(q: Any, catalog: Optional[list[dict[str, Any]]] = None) -> list[tuple]:
    """v1.49: every must-have the settings can express on what this question
    feeds, at any limit a user could pick: taken from the settings catalog
    itself (setup.CATALOG), so a criterion added there is tested here. A yes/no
    criterion wants one value; a ladder (parking) can be set to any rung.
    Questions no criterion reads (the broker, the fees) can't hide a listing,
    and a furniture item can't be a must-have (scoring.py refuses one)."""
    if catalog is None:
        from ..setup import CATALOG as catalog
    reqs: list[tuple] = []
    for c in catalog:
        field = str(c.get("field", ""))
        if not field.startswith("signal:") or c.get("kind") == "has_items":
            continue
        signal = field.removeprefix("signal:")
        if signal == q.signal:
            if c.get("kind") == "yes_no":
                reqs.append(("value", c.get("wants")))
            elif q.values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in q.values.values()):
                reqs += [("at_least", v) for v in sorted(set(q.values.values()))[1:]]
        reqs += _FEEDS.get((q.id, signal), [])
    return list(dict.fromkeys(reqs))


def wrongly_hidden(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers,
                   model_can_hide: bool = False) -> dict[str, dict[str, list[str]]]:
    """v1.49: for every question and every must-have a user could set on it,
    the listings a reader's answer would hide although the text, as the
    labelers read it, doesn't rule them out. A listing hidden by a misreading
    is the error a user never sees, so the bar is that this is empty, for any
    user's settings, not just the owner's. An abstention never hides (the listing
    is shown with a check), and neither does an answer only the AI gave
    (scoring.py's rule), unless `model_can_hide` asks what it would do if it could."""
    out: dict[str, dict[str, list[str]]] = {}
    reqs = {q.id: requirements(q) for q in QUESTIONS}
    for listing, by_q in gold.items():
        for qid, g in by_q.items():
            q = BY_ID.get(qid)
            if q is None:
                continue
            got = _entry(answers, listing, qid)
            answer = got.get("answer", NOT_STATED)
            items = set(got.get("items") or [])
            if answer in (NOT_STATED, UNCLEAR) or (answer == "items" and not items) or answer not in q.answers:
                continue  # an abstention is shown with a check, never hidden
            if got.get("source") == "model" and not model_can_hide:
                continue  # only the AI read it: scoring.py never lets that hide a listing on its own
            acceptable = _acceptable(g)
            definite = acceptable - {NOT_STATED, UNCLEAR}
            reader_ok = (answer in acceptable and (answer != "amount" or got.get("value") == g.get("value"))
                         and (answer != "items" or items <= set(g.get("allowed_items") or [])))
            for req in reqs.get(qid, []):
                if any(_passes(q, a, items, got.get("value"), req) for a in (answer, *(got.get("or") or []))):
                    continue  # v1.53: "one of these" is never a reason to hide: the best of them may hold
                # wrongly hidden: another reading the labelers accepted would keep it, or the
                # reader said something they didn't accept where the text may not say at all
                gold_allows = any(_passes(q, a, set(g.get("allowed_items") or []), g.get("value"), req) for a in definite) \
                    or (not reader_ok and bool(acceptable & {NOT_STATED, UNCLEAR}))
                if gold_allows:
                    out.setdefault(qid, {}).setdefault(f"{req[0]} {req[1]}", []).append(listing)
    return out


def definition_of_done(tallies: dict[str, Tally], listings: int) -> list[tuple[str, bool]]:
    """Each check of the bar, and whether this run meets it."""
    checks = [
        (f"0 wrong answers (got {tallies['ALL'].wrong})", tallies["ALL"].wrong == 0),
        (f"coverage >= {TARGET_COVERAGE:.0%} overall (got {tallies['ALL'].coverage:.0%})", tallies["ALL"].coverage >= TARGET_COVERAGE),
    ]
    for q in (q.id for q in QUESTIONS):  # v1.49: every question, not only one user's must-haves
        t = tallies.get(q)
        if t is None or not t.definite_gold:
            continue
        checks.append((f"coverage >= {TARGET_COVERAGE:.0%} on {q} (got {t.correct_definite}/{t.definite_gold})", t.coverage >= TARGET_COVERAGE))
    checks.append((f"at least {MIN_LISTINGS} listings (got {listings})", listings >= MIN_LISTINGS))
    return checks


def settled(g: dict[str, Any]) -> bool:
    """v1.49: the labelers settled this fact: exactly one definite answer is
    acceptable (one amount, one list), and "the text doesn't say" isn't."""
    acceptable = _acceptable(g)
    return not (acceptable & {NOT_STATED, UNCLEAR}) and len(acceptable) == 1


def settled_coverage(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers) -> dict[str, tuple[int, int]]:
    """Per question and "ALL": (answered right, settled facts). A fact the
    labelers read two ways is left out: there the right answer is a check
    (a definite one would hide the listing from someone the other reading
    suits), so it can't count against coverage either way."""
    out: dict[str, list[int]] = {}
    for listing, by_q in gold.items():
        for qid, g in by_q.items():
            if qid not in BY_ID or not settled(g):
                continue
            t = score({listing: {qid: g}}, {listing: {qid: _entry(answers, listing, qid)}})[qid]
            for key in (qid, "ALL"):
                c = out.setdefault(key, [0, 0])
                c[0] += t.correct_definite
                c[1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def settled_credit(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers) -> dict[str, tuple[float, int]]:
    """v1.55 (owner ruling, Oct 30): "a furniture list should be considered partial" when an item is missing.
    Like `settled_coverage`, but a list answer that names only some of the listed items earns the share
    it named (5 of 6 items: 5/6 of a fact) instead of nothing. A list that names something the listing
    doesn't have is still wrong and earns nothing. Everything else counts as in settled_coverage."""
    out: dict[str, list[float]] = {}
    for listing, by_q in gold.items():
        for qid, g in by_q.items():
            if qid not in BY_ID or not settled(g):
                continue
            got = _entry(answers, listing, qid)
            t = score({listing: {qid: g}}, {listing: {qid: got}})[qid]
            credit = float(t.correct_definite)
            if not credit and not t.wrong and got.get("answer") == "items" and g.get("items"):
                need = set(g["items"])
                credit = len(need & set(got.get("items") or [])) / len(need)
            for key in (qid, "ALL"):
                c = out.setdefault(key, [0.0, 0])
                c[0] += credit
                c[1] += 1
    return {k: (v[0], int(v[1])) for k, v in out.items()}


def partial_lists(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers) -> list[str]:
    """v1.55: settled lists the reader named only part of: "listing/question: missing a, b"."""
    out = []
    for listing, by_q in gold.items():
        for qid, g in by_q.items():
            if qid not in BY_ID or not settled(g) or not g.get("items"):
                continue
            got = _entry(answers, listing, qid)
            if got.get("answer") != "items":
                continue
            named, need = set(got.get("items") or []), set(g["items"])
            if named and named <= set(g.get("allowed_items") or []) and need - named:
                out.append(f"{listing}/{qid}: missing {', '.join(sorted(need - named))}")
    return out


def universal_bar(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers,
                  partial: bool = False) -> list[tuple[str, bool]]:
    """v1.49: Phase 2's bar for every user, whatever their settings:
    - 0 wrong answers, on every question;
    - no listing hidden by a misreading, for any must-have the settings can
      express (`wrongly_hidden`);
    - at least 95% of the settled facts answered, overall and per question;
    - at least 50 listings.
    v1.55 `partial`: a list missing some items earns the share it named (`settled_credit`), the owner's
    reading of the bar from Oct 30 on. Without it, the bar as it was measured before."""
    tallies = score(gold, answers)
    hidden = wrongly_hidden(gold, answers)
    pairs = {(listing, q) for q, by in hidden.items() for ls in by.values() for listing in ls}
    cov = settled_credit(gold, answers) if partial else settled_coverage(gold, answers)
    checks = [(f"0 wrong answers (got {tallies['ALL'].wrong})", tallies["ALL"].wrong == 0),
              (f"no listing hidden by a misreading, for any must-have (got {len(pairs)})", not pairs)]
    for q in ["ALL"] + [q.id for q in QUESTIONS]:
        if q in cov:
            right, n = cov[q]
            shown = f"{right:g}" if isinstance(right, int) or float(right).is_integer() else f"{right:.1f}"
            checks.append((f"settled facts answered >= {TARGET_COVERAGE:.0%} {'overall' if q == 'ALL' else 'on ' + q} "
                           f"(got {shown}/{n}, {right / n:.0%})", right / n >= TARGET_COVERAGE))
    checks.append((f"at least {MIN_LISTINGS} listings (got {len(gold)})", len(gold) >= MIN_LISTINGS))
    return checks


# Decision 0001 (Nov 6): Phase 2's bar as error budgets by consequence. See docs/decisions/0001-phase-2-exit-bar.md.
BAR_V2_MIN_LISTINGS = 250
BAR_V2_WRONG_OVERALL = 0.005   # facts that can hide or rank a listing (every question but furniture)
BAR_V2_WRONG_PER_QUESTION = 0.02
BAR_V2_WRONG_FURNITURE = 0.03  # furniture never hides a listing
BAR_V2_COVERAGE_OVERALL = 0.90
BAR_V2_COVERAGE_PER_QUESTION = 0.85
INFORMATIONAL = {"furniture"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The 95% Wilson interval for k of n (a rate measured on a sample)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    return (max(0.0, (c - r) / d), min(1.0, (c + r) / d))


def answer_counts(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers) -> dict[str, tuple[int, int]]:
    """Per question and overall: (definite answers the reader gave, of them wrong). A definite answer is one
    that tells the user something (not "not stated", not a check, not an empty list); "wrong" is outside what
    the labelers accept. The denominators of decision 0001's error budgets."""
    tallies = score(gold, answers)
    out: dict[str, list[int]] = {}
    for listing, by_q in gold.items():
        for q in by_q:
            got = _entry(answers, listing, q)
            definite = got.get("answer") not in (None, NOT_STATED, UNCLEAR) and not (got.get("answer") == "items" and not got.get("items"))
            out.setdefault(q, [0, 0])[0] += definite
    for q, t in tallies.items():
        if q != "ALL" and q in out:
            out[q][1] = t.wrong
    return {q: (d, w) for q, (d, w) in out.items()}


def bar_v2(gold: dict[str, dict[str, dict[str, Any]]], answers: Answers) -> list[tuple[str, bool]]:
    """Decision 0001's Card test v2: each check and whether this run meets it."""
    counts = answer_counts(gold, answers)
    hidden = wrongly_hidden(gold, answers)
    listings_hidden = {x for by in hidden.values() for ls in by.values() for x in ls}
    cov = settled_credit(gold, answers)
    pct = lambda x: f"{100 * x:.1f}%"
    checks = [(f"no listing hidden by a misreading, for any must-have (got {len(listings_hidden)})", not listings_hidden)]
    d = sum(c[0] for q, c in counts.items() if q not in INFORMATIONAL)
    w = sum(c[1] for q, c in counts.items() if q not in INFORMATIONAL)
    lo, hi = wilson(w, d)
    checks.append((f"facts that can hide or rank: wrong <= {pct(BAR_V2_WRONG_OVERALL)} (got {w}/{d}, {pct(w / max(d, 1))}, "
                   f"95% CI {pct(lo)}-{pct(hi)})", w <= BAR_V2_WRONG_OVERALL * d))
    for q in (q.id for q in QUESTIONS):
        if q not in counts or counts[q][0] == 0:
            continue
        dq, wq = counts[q]
        limit = BAR_V2_WRONG_FURNITURE if q in INFORMATIONAL else BAR_V2_WRONG_PER_QUESTION
        checks.append((f"wrong <= {pct(limit)} on {q} (got {wq}/{dq}, {pct(wq / dq)})", wq <= limit * dq))
    for q in ["ALL"] + [q.id for q in QUESTIONS]:
        if q in cov and cov[q][1]:
            right, n = cov[q]
            floor = BAR_V2_COVERAGE_OVERALL if q == "ALL" else BAR_V2_COVERAGE_PER_QUESTION
            checks.append((f"settled facts read >= {pct(floor)} {'overall' if q == 'ALL' else 'on ' + q} (got {right:.1f}/{n}, {pct(right / n)})",
                           right / n >= floor))
    checks.append((f"at least {BAR_V2_MIN_LISTINGS} listings (got {len(gold)})", len(gold) >= BAR_V2_MIN_LISTINGS))
    return checks


def pooled_budgets(cards: list[tuple[dict[str, dict[str, dict[str, Any]]], Answers]]) -> list[tuple[str, str]]:
    """Decision 0002: accuracy judged on held-out batches pooled together, each measured once with frozen rules.
    For each budget of decision 0001, the pooled wrong rate with its 95% interval, and a verdict:
    "met" (the interval's upper bound is within the budget), "over" (the point estimate is past it), or
    "not shown yet" (within on the point estimate, but the interval still reaches past it: more data needed)."""
    totals: dict[str, list[int]] = {}
    for gold, answers in cards:
        for q, (d, w) in answer_counts(gold, answers).items():
            t = totals.setdefault(q, [0, 0])
            t[0] += d
            t[1] += w
    def verdict(w: int, d: int, budget: float) -> str:
        lo, hi = wilson(w, d)
        return "met" if hi <= budget else "over" if w > budget * d else "not shown yet"
    out = []
    d = sum(t[0] for q, t in totals.items() if q not in INFORMATIONAL)
    w = sum(t[1] for q, t in totals.items() if q not in INFORMATIONAL)
    lo, hi = wilson(w, d)
    out.append((f"facts that can hide or rank: {w}/{d} wrong ({100 * w / max(d, 1):.2f}%, 95% CI {100 * lo:.2f}-{100 * hi:.2f}%), budget {100 * BAR_V2_WRONG_OVERALL:.1f}%",
                verdict(w, d, BAR_V2_WRONG_OVERALL)))
    for q in (q.id for q in QUESTIONS):
        if q not in totals or not totals[q][0]:
            continue
        dq, wq = totals[q]
        budget = BAR_V2_WRONG_FURNITURE if q in INFORMATIONAL else BAR_V2_WRONG_PER_QUESTION
        lo, hi = wilson(wq, dq)
        out.append((f"{q}: {wq}/{dq} wrong ({100 * wq / dq:.1f}%, 95% CI {100 * lo:.1f}-{100 * hi:.1f}%), budget {100 * budget:.0f}%", verdict(wq, dq, budget)))
    return out
