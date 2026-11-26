"""
Phase 2: the prompt and the response schema every candidate extractor
gets, so each one is measured on exactly the same task.

"unclear" counts as an answer here: it needs evidence like any other, so
a model can't flag a listing for a check without pointing at the words.

The schema closes every answer to its allowed set, so a model that
supports constrained output (Chrome's built-in Prompt API takes it as
`responseConstraint`; Gemini as `responseSchema`) physically can't
return an answer outside it. Evidence is required for every definite
answer: an answer the text doesn't contain words for is a guess.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .questions import BY_ID, NOT_STATED, QUESTIONS, guide

INSTRUCTIONS = """You read one Hebrew rental listing's description and answer fixed questions about it.

Rules:
- Answer ONLY from the description text. Never guess what is likely.
- If the text doesn't mention a question's subject, answer "not_stated".
- If it mentions it but doesn't settle it (a typo, a contradiction, an offer or a plan rather than a fact, something nearby rather than the apartment's own), answer "unclear": a human will check.
- For every answer other than "not_stated", copy into "evidence" the exact words from the text that it rests on.
- For an amount, put the number in "value". For a list (furniture), put every id the text gives words for in "items".
- Reply with JSON only, matching the schema.

Questions:
"""


def response_schema() -> dict[str, Any]:
    """JSON Schema for one listing's answers: every question required,
    each answer closed to its allowed set."""
    props: dict[str, Any] = {}
    for q in QUESTIONS:
        entry: dict[str, Any] = {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "enum": list(q.answers)},
                "evidence": {"type": "string"},
            },
            "required": ["answer", "evidence"],
            "additionalProperties": False,
        }
        if "amount" in q.answers:
            entry["properties"]["value"] = {"type": ["number", "null"]}
        if q.items:
            entry["properties"]["items"] = {"type": "array", "items": {"type": "string", "enum": list(q.items)}}
        props[q.id] = entry
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


BATCH_INSTRUCTIONS = """You read several Hebrew rental listings' descriptions and answer the same fixed questions about EACH one.

Rules:
- Treat every listing on its own: answer only from THAT listing's description, never from another's.
- Never guess what is likely. If a listing's text doesn't mention a question's subject, answer "not_stated".
- If it mentions it but doesn't settle it (a typo, a contradiction, an offer or a plan rather than a fact, something nearby rather than the apartment's own), answer "unclear": a human will check.
- For every answer other than "not_stated", copy into "evidence" the exact words from that listing's text that it rests on.
- For an amount, put the number in "value". For a list (furniture), put every id the text gives words for in "items".
- Reply with JSON only: an array with one object per listing, each with the listing's "id" and its answers, matching the schema.

Questions:
"""


def batch_schema(ids: list[str]) -> dict[str, Any]:
    """An array of per-listing answers, each tagged with its listing id. One
    item schema however many listings there are, so the schema stays small."""
    item = response_schema()
    item = {**item, "properties": {"id": {"type": "string", "enum": list(ids)}, **item["properties"]},
            "required": ["id", *item["required"]]}
    return {"type": "array", "items": item}


def prompt_id() -> str:
    """A short fingerprint of the prompt (instructions + question guide).
    A saved run belongs to one prompt: answers from an older wording must
    not be resumed into a run of a newer one."""
    import hashlib
    return hashlib.sha1((INSTRUCTIONS + BATCH_INSTRUCTIONS + guide()).encode("utf-8")).hexdigest()[:6]


def build_batch_prompt(items: dict[str, str]) -> str:
    listings = "\n\n".join(f"Listing {lid}:\n<<<\n{text}\n>>>" for lid, text in items.items())
    return f"{BATCH_INSTRUCTIONS}{guide()}\n\nListings:\n\n{listings}\n\nJSON schema of the reply:\n{json.dumps(batch_schema(list(items)), ensure_ascii=False)}"


def build_prompt(description: str) -> str:
    return f"{INSTRUCTIONS}{guide()}\n\nDescription:\n<<<\n{description}\n>>>\n\nJSON schema of the reply:\n{json.dumps(response_schema(), ensure_ascii=False)}"


def _norm(s: str) -> str:
    s = s.replace("״", '"').replace("׳", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def ground(answers: dict[str, dict[str, Any]], description: str) -> dict[str, dict[str, Any]]:
    """The check that makes "evidence" mean something, in two steps:
    1. A definite answer whose quoted evidence isn't actually in the text
       is demoted to not_stated (with the problem noted). A model that
       invents a quote is guessing, and a guess must cost coverage, never
       correctness. Quotes may be joined with "..." for words that aren't
       adjacent.
    2. The quote must also contain the words the answer means
       (`Question.requires`): "קומת קרקע" (ground floor) is a real quote,
       but it can't carry "garden apartment"; "שידת טלוויזיה" (a TV stand)
       can't carry "tv". A list keeps only the ids its quote supports.
    Idempotent, so a saved run can be grounded again under newer checks."""
    text = _norm(description)
    out: dict[str, dict[str, Any]] = {}
    for qid, entry in answers.items():
        if entry.get("answer") == NOT_STATED:
            out[qid] = entry
            continue
        pieces = [_norm(p) for p in re.split(r"\.\.\.|…", str(entry.get("evidence") or ""))]
        pieces = [p for p in pieces if p]
        if not pieces or any(p not in text for p in pieces):
            out[qid] = {"answer": NOT_STATED, "evidence": "",
                        "problem": f"ungrounded {entry.get('answer')!r}: evidence {entry.get('evidence')!r} isn't in the text"[:200]}
            continue
        out[qid] = _supported(BY_ID.get(qid), entry, " ... ".join(pieces))
    return out


def _supported(q: Any, entry: dict[str, Any], quote: str) -> dict[str, Any]:
    if q is None or not q.requires:
        return entry
    answer = entry.get("answer")
    if answer == "items" and q.items:
        items = list(entry.get("items") or [])
        kept = [i for i in items if i not in q.requires or re.search(q.requires[i], quote)]
        if kept == items:
            return entry
        dropped = f"unsupported {sorted(set(items) - set(kept))}: the quote doesn't say them"
        if not kept:
            return {"answer": NOT_STATED, "evidence": "", "problem": dropped[:200]}
        return {**entry, "items": kept, "problem": dropped[:200]}
    pattern = q.requires.get(answer)
    if pattern is None or re.search(pattern, quote):
        return entry
    return {"answer": NOT_STATED, "evidence": "",
            "problem": f"unsupported {answer!r}: {entry.get('evidence')!r} doesn't say it"[:200]}
