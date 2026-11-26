"""
Run the Phase 2 test set through Gemini's free tier and print the score.

    python run_gemini_test.py

Needs: Python 3.9+, nothing else installed, and your key in a file named
`.gemini_key` in this folder (or the GEMINI_API_KEY environment variable).
The key is never printed or written anywhere. It sends 8 listings per
request (the free tier's daily limit counts requests, not listings) and
pauses between requests. If it stops (a timeout, the day's quota), just
run it again, even the next day: it saves after every request and picks
up where it left off.
`--rescore` scores the newest saved Gemini run again under today's
checks (grounding, rules, gold) without asking Gemini anything: no quota.
By default it lets the free tier pick a model ("auto") and, if that
model's own daily quota runs out partway through (even on a later,
resumed run), moves on to the next free one on this key by itself --
nothing already answered is lost. Pass `--model gemini-3.5-flash-lite`
(or any other model name) to pin one and skip that switching, e.g. to
compare models, or when "auto" keeps landing on one with a low daily
quota for this key.
Writes Gemini's answers to tests/eval/runs/ and prints three scores:
the rule-based answerer alone, Gemini alone, and the two combined
(where they disagree, the answer becomes a check), then the Phase 2
definition of done for the combined reader.
"""

import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from rental_matcher.extraction import gemini  # noqa: E402
from rental_matcher.extraction.evaluate import (definition_of_done, load, report, same_questions, score,  # noqa: E402
                                                 universal_bar, wrongly_hidden)
from rental_matcher.extraction.prompt import ground, prompt_id  # noqa: E402
from rental_matcher.extraction.rules import answer as rule_answer, combine  # noqa: E402


BATCH = 8  # listings per request: the free tier's daily limit counts requests

# The honest number: listings fetched only after the reader was frozen.
# Scored with the rules output saved AT that freeze (not today's rules), so
# a later rules fix can't flatter it. (frozen commit, fixtures, frozen rules run)
HELD_OUT = ("a6c3fdb", "yad2_holdout8_2026-10-28", "2026-10-28_rules_v149_frozen_on_holdout8.json")  # v1.50: batch 8 (batch 7: v1.43)


def _runs_of(runs: Path, tag: str) -> list[Path]:
    """This prompt's run files, newest first: "<date><tag>.json" and a later one the same
    day, "<date><tag>_2.json". v1.50: the "_2" ones used to be missed, so a finished
    second run of the day was never the one continued (a renamed, set-aside file still isn't)."""
    pat = re.compile(rf"^(\d{{4}}-\d\d-\d\d){re.escape(tag)}(?:_(\d+))?\.json$")
    found = [(m[1], int(m[2] or 1), f) for f in runs.glob("*.json") if (m := pat.match(f.name))]
    return [f for *_, f in sorted(found, reverse=True)]


def run_file(runs: Path = ROOT / "tests" / "eval" / "runs") -> Path:
    """An unfinished run of THIS prompt from an earlier day is continued
    (the daily quota resets overnight); otherwise a new file for today.
    The prompt's fingerprint is in the name, so changing the prompt starts
    a new run instead of reusing answers to the old one."""
    tag = f"_gemini_b{BATCH}_p{prompt_id()}"
    for f in _runs_of(runs, tag):
        if not load(f).get("_complete"):
            return f
    today = runs / f"{date.today().isoformat()}{tag}.json"
    n = 2
    while today.exists():  # a finished run of the same prompt today: keep it, start another
        today = runs / f"{date.today().isoformat()}{tag}_{n}.json"
        n += 1
    # v1.43: a finished run of this very prompt that's missing listings added since (held-out batch 7):
    # today's run starts from its answers and asks Gemini only for the new ones (24 requests, not 58)
    texts = load(ROOT / "tests" / "eval" / "yad2_texts.json")
    finished = _runs_of(runs, tag)
    if finished:
        last = load(finished[0])
        if last.get("_complete") and not all(k in last for k in texts):
            # (a run from before v1.28 names its prompt only in its file name, which is this prompt's)
            today.write_text(json.dumps({**last, "_prompt": prompt_id(), "_complete": False}, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return today


def latest_run(runs: Path = ROOT / "tests" / "eval" / "runs") -> Path:
    """The newest complete Gemini run of any prompt."""
    done = [f for f in runs.glob("*_gemini_b*.json") if load(f).get("_complete")]
    if not done:
        raise SystemExit("no complete Gemini run saved yet: run without --rescore first")
    return max(done, key=lambda f: f.stat().st_mtime)


def held_out_ids(fixtures: str = "") -> set[str]:
    return {f.stem for f in (ROOT / "tests" / "fixtures" / (fixtures or HELD_OUT[1])).glob("*.json")}


def held_out_first(texts: dict[str, str]) -> dict[str, str]:
    """v1.48: the same listings, the held-out batch first. Its score is the
    number Phase 2 needs, and on the free tier's daily quota the whole set
    can take days, so it's asked for before the in-sample listings."""
    ids = held_out_ids()
    return {**{k: v for k, v in texts.items() if k in ids}, **{k: v for k, v in texts.items() if k not in ids}}


def held_out_report(answers: dict, gold: dict) -> bool:
    """Print the held-out score once Gemini has answered every held-out
    listing; otherwise say how far it got. True if it printed the score."""
    commit, _, rules_run = HELD_OUT
    ids = held_out_ids()
    frozen = load(ROOT / "tests" / "eval" / "runs" / rules_run)
    held_gold = {k: v for k, v in same_questions(gold, frozen).items() if k in ids}  # the questions the frozen rules had
    done = sum(k in answers for k in held_gold)
    if not held_gold or done < len(held_gold):
        print(f"\nHeld out: Gemini has answered {done} of {len(held_gold)} so far; the score comes when all are in.")
        return False
    print(f"\nHeld out (listings fetched after {commit} was frozen; {len(held_gold)} listings):")
    held_together = {k: combine(frozen[k], answers[k]) for k in held_gold}
    for name, these in (("Rules alone (frozen)", frozen), ("Gemini alone", answers), ("Rules + Gemini", held_together)):
        t = score(held_gold, these)["ALL"]
        print(f"  {name}: {t.wrong} wrong, coverage {t.coverage:.0%} ({t.correct_definite}/{t.definite_gold}), "
              f"{t.flagged} flagged unclear")
        for item in t.wrong_items if name != "Rules alone (frozen)" else ():
            print("    WRONG:", item)
    print("  The bar, for every user's settings (Rules + Gemini, held out, the text alone):")
    for check, ok in universal_bar(held_gold, held_together):
        print(f"    [{'PASS' if ok else 'FAIL'}] {check}")
    # v1.52: what the card shows -- Yad2's own form first, then the text (extraction/card_eval)
    from rental_matcher.extraction.card_eval import card_score_inputs, load_extracts
    from rental_matcher.scoring import PreferenceSet
    prefs = PreferenceSet.load(ROOT / "tests" / "fixtures" / "prefs_frozen.json")
    extracts = load_extracts(ROOT / "tests" / "fixtures" / HELD_OUT[1])
    print(f"\n  What the card shows (Yad2's form + the text; {len(extracts)} listings the product reads):")
    card_gold = card_together = None
    for name, these in (("Rules alone (frozen)", frozen), ("Rules + Gemini", held_together)):
        cg, ca, _ = card_score_inputs(extracts, held_gold, {k: combine(these[k], {}) if name.startswith("Rules alone") else these[k]
                                                            for k in held_gold}, prefs)
        t = score(cg, ca)["ALL"]
        print(f"    {name}: {t.wrong} wrong, coverage {t.coverage:.0%} ({t.correct_definite}/{t.definite_gold})")
        card_gold, card_together = cg, ca
    print("  The bar, for every user's settings (Rules + Gemini, what the card shows):")
    for check, ok in universal_bar(card_gold, card_together):
        print(f"    [{'PASS' if ok else 'FAIL'}] {check}")
    return True


def main() -> None:
    texts = ROOT / "tests" / "eval" / "yad2_texts.json"
    args = [a for a in sys.argv[1:] if a != "--rescore"]
    stopped = None
    if "--rescore" in sys.argv[1:]:
        out = latest_run()
        print(f"  rescoring {out.name} (no Gemini calls)")
    else:
        out = run_file()
        # held-out listings first (v1.48), from a copy outside the repo
        with tempfile.TemporaryDirectory() as d:
            ordered = Path(d) / "texts_held_out_first.json"
            ordered.write_text(json.dumps(held_out_first(load(texts)), ensure_ascii=False), encoding="utf-8")
            try:
                # Extra args (e.g. --model gemini-3.5-flash-lite) pass straight through to
                # gemini.main(), so a model picked by "auto" can be overridden for a test
                # run without changing what production picks.
                gemini.main([str(ordered), str(out), "--batch", str(BATCH), *args])
            except gemini.GeminiError as e:
                stopped = e
    listing_texts = load(texts)
    # Grounded again under today's checks (idempotent): a newer check applies
    # to an older run too.
    answers = {k: (ground(v, listing_texts[k]) if not k.startswith("_") and k in listing_texts else v)
               for k, v in load(out).items()} if out.is_file() else {}
    gold = load(ROOT / "tests" / "eval" / "yad2_gold.json")["gold"]
    if stopped:
        # v1.48: a stop (the day's quota, an overloaded model) still shows the
        # held-out score if those listings are all answered -- it's the one that matters.
        held_out_report(answers, gold)
        raise stopped
    rules = {k: rule_answer(v) for k, v in listing_texts.items()}
    together = {k: combine(rules[k], answers.get(k, {})) for k in listing_texts}
    print()
    for name, these in (("Rules alone (free, instant)", rules),
                        (f"Gemini alone ({answers.get('_model')}), free tier", answers),
                        ("Rules + Gemini (a disagreement becomes a check)", together)):
        t = score(gold, these)["ALL"]
        print(f"  {name}: {t.wrong} wrong, coverage {t.coverage:.0%} ({t.correct_definite}/{t.definite_gold}), "
              f"{t.flagged} flagged unclear")
    tallies = score(gold, together)
    print()
    print(report("Rules + Gemini, per question", tallies))
    for item in tallies["ALL"].wrong_items:
        print("  WRONG:", item)
    conflicts = sum("conflict" in e.get("problem", "") for v in together.values() for e in v.values())
    print(f"\n  disagreements between rules and Gemini (turned into checks): {conflicts}")
    vetoed = sum("rules found it unclear" in e.get("problem", "") for v in together.values() for e in v.values())
    print(f"  Gemini answers over a trap the rules recognized (kept as checks): {vetoed}")
    ai_only = sum(e.get("source") == "model" and e.get("answer") not in ("not_stated", "unclear")
                  for v in together.values() for e in v.values())
    print(f"  answers only Gemini gave (they score, but can't hide a listing alone): {ai_only}")
    fans = sum(bool(v.get("air_conditioning", {}).get("note")) for v in together.values())
    print(f"  air conditioning answers carrying a '+fan' note: {fans}")
    dropped = sum(("ungrounded" in e.get("problem", "") or "unsupported" in e.get("problem", "")) for k, v in answers.items() if not k.startswith("_") and isinstance(v, dict) for e in v.values())
    print(f"\n  answers dropped because their quote wasn't in the text or didn't say it: {dropped}")
    held_out_report(answers, gold)
    print("\nPhase 2's bar, for every user's settings (v1.49; all listings, in-sample):")
    for check, ok in universal_bar(gold, together):
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    for q, by in wrongly_hidden(gold, together).items():
        for req, ids in by.items():
            print(f"  HIDDEN by a misreading: {q} must-have '{req}': {', '.join(ids)}")
    print("\nCoverage the old way (every fact with a definite reading, two-way ones included), for comparison:")
    for check, ok in definition_of_done(tallies, len(gold)):
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    print(f"\nRun file: {out}")


if __name__ == "__main__":
    try:
        main()
    except gemini.GeminiError as e:
        print(f"\nStopped: {e}", file=sys.stderr)
        print("Progress is saved. Run it again to continue from here.", file=sys.stderr)
        sys.exit(1)
