"""
Phase 2 extractor: Google's Gemini API, free tier.

The project's constraint is no money spent. The Gemini API has a free tier;
a key made in a Google Cloud project WITHOUT billing can only ever use it,
so it can't be charged. (A Gemini app subscription doesn't cover API use:
Google bills the API separately.) Free-tier content may be used to
improve Google's products, so only public listing text is sent -- the
fixtures already have phone numbers blanked, and nothing personal is in
the prompt.

The key is read from the GEMINI_API_KEY environment variable or a
`.gemini_key` file next to the repo, on the machine that runs this. It is
never printed, logged or written into any output.

Standard library only (urllib), so it runs anywhere Python does.

    python -m rental_matcher.extraction.gemini tests/eval/yad2_texts.json \\
        tests/eval/runs/<date>_gemini_<model>.json [--model NAME]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from .prompt import batch_schema, build_batch_prompt, build_prompt, ground, prompt_id, response_schema
from .questions import BY_ID, NOT_STATED, QUESTIONS

API = "https://generativelanguage.googleapis.com/v1beta"
KEY_FILE = Path(__file__).resolve().parents[2] / ".gemini_key"
TIMEOUT = 300  # seconds per request. v1.48: back to 300 -- v1.44 cut it to 120, and
# from then on every one of the owner's runs ended in read timeouts, while 300 had
# carried 7 batches through. A Gemini 3 Flash model thinks before answering,
# and 8 listings with a strict JSON schema can take minutes, more so under load.
# The wait is no longer silent (the request and every retry are printed).

Post = Callable[[str, dict[str, Any], str], dict[str, Any]]


class GeminiError(RuntimeError):
    pass


def api_key() -> str:
    """From GEMINI_API_KEY, or a `.gemini_key` file next to the repo or in
    the current folder. Never printed."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    for path in (KEY_FILE, Path.cwd() / ".gemini_key", KEY_FILE.parent.parent / ".gemini_key"):
        if not key and path.is_file():
            key = path.read_text(encoding="utf-8-sig").strip()  # -sig: Notepad may add a BOM
    if not key:
        raise GeminiError("no key: set GEMINI_API_KEY or create .gemini_key next to the repo")
    return key


def _http_get(url: str, key: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise GeminiError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def candidate_models(listing: dict[str, Any]) -> list[str]:
    """Flash-class models this key can call for generateContent, best
    first: stable before preview/experimental, Flash before Flash-Lite,
    newer before older. Free-tier quotas differ by model, so the runner
    tries them in this order."""
    names = []
    for m in listing.get("models", []):
        name = str(m.get("name", "")).removeprefix("models/")
        if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in name \
                and not any(x in name for x in ("image", "tts", "audio", "live", "thinking", "embedding")):
            names.append(name)

    def rank(name: str) -> tuple:
        unstable = any(x in name for x in ("preview", "exp"))
        lite = "lite" in name
        version = [int(n) for n in re.findall(r"(\d+)", name.split("flash")[0])] or [0]
        return (unstable, lite, [-v for v in version], name)

    return sorted(set(names), key=rank)


def _quota_details(body: str) -> str:
    """The parts of a 429 that say WHICH limit was hit and when to retry:
    Google's error details carry a quotaId ("...PerDay..." or
    "...PerMinute...") and a retryDelay ("37s")."""
    try:
        details = json.loads(body).get("error", {}).get("details", [])
    except (ValueError, AttributeError):
        return ""
    found = []
    for d in details if isinstance(details, list) else []:
        if not isinstance(d, dict):
            continue
        for v in d.get("violations", []) or []:
            if isinstance(v, dict) and v.get("quotaId"):
                found.append(f"[quota: {v['quotaId']}]")
        if d.get("retryDelay"):
            found.append(f"[retry: {d['retryDelay']}]")
    return " ".join(dict.fromkeys(found))


def _http_post(url: str, body: dict[str, Any], key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},  # header, so the key isn't in a URL
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")[:8000]
        raise GeminiError(f"HTTP {e.code}: {_quota_details(raw)} {raw[:300]}".replace("  ", " ")) from None
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
        # A slow or dropped connection (it happened on listing 8 of the owner's
        # first run): retried like a rate limit, never a crash.
        raise GeminiError(f"network: {type(e).__name__}: {e}"[:300]) from None


def gemini_schema(schema: Any) -> Any:
    """Gemini's `responseSchema` is an OpenAPI subset: no
    `additionalProperties`, and `nullable` instead of a ["x", "null"] type."""
    if isinstance(schema, dict):
        out = {k: gemini_schema(v) for k, v in schema.items() if k != "additionalProperties"}
        if isinstance(out.get("type"), list):
            types = [t for t in out["type"] if t != "null"]
            out["type"] = types[0]
            if len(types) < len(schema["type"]):
                out["nullable"] = True
        return out
    if isinstance(schema, list):
        return [gemini_schema(v) for v in schema]
    return schema


def _text(response: dict[str, Any]) -> str:
    try:
        return "".join(p.get("text", "") for p in response["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise GeminiError(f"no text in response: {json.dumps(response)[:300]}") from None


def clean(reply: Any) -> dict[str, dict[str, Any]]:
    """Keep only well-formed answers; anything else becomes not_stated
    with the problem noted, so a malformed reply can't sneak a value in."""
    out: dict[str, dict[str, Any]] = {}
    for q in QUESTIONS:
        entry = reply.get(q.id) if isinstance(reply, dict) else None
        if not isinstance(entry, dict) or entry.get("answer") not in BY_ID[q.id].answers:
            out[q.id] = {"answer": NOT_STATED, "evidence": "", "problem": f"malformed: {entry!r}"[:200]}
            continue
        kept = {"answer": entry["answer"], "evidence": str(entry.get("evidence") or "")}
        v = entry.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0:
            kept["value"] = v
        if entry["answer"] == "amount" and "value" not in kept:  # "an amount" with no number says nothing (v1.28)
            out[q.id] = {"answer": NOT_STATED, "evidence": "", "problem": f"malformed amount: {entry!r}"[:200]}
            continue
        if q.items and entry["answer"] == "items":
            raw = entry.get("items") if isinstance(entry.get("items"), list) else []
            ids = sorted({i for i in raw if isinstance(i, str) and i in q.items})
            if not ids:  # a list answer that names nothing usable says nothing
                out[q.id] = {"answer": NOT_STATED, "evidence": "", "problem": f"malformed: {entry!r}"[:200]}
                continue
            kept["items"] = ids
            if len(ids) != len(raw):
                kept["problem"] = f"dropped ids outside the list: {[i for i in raw if i not in ids]!r}"[:200]
        out[q.id] = kept
    return out


def _daily_quota(error: GeminiError) -> bool:
    return "HTTP 429" in str(error) and "PerDay" in str(error)


def _retry_after(error: GeminiError) -> Optional[float]:
    m = re.search(r"\[retry: (\d+(?:\.\d+)?)s\]", str(error))
    return min(float(m.group(1)) + 1, 120.0) if m else None


def _ask(prompt: str, schema: Any, model: str, key: str, post: Optional[Post], retries: int) -> Any:
    """One generateContent call, retried on transient errors; returns the
    parsed JSON reply. A used-up DAILY quota is never retried: waiting
    seconds won't bring it back."""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "responseSchema": gemini_schema(schema)},
    }
    post = post or _http_post  # looked up at call time, so tests can replace it
    delay = 5.0
    for attempt in range(retries + 1):
        try:
            return json.loads(_text(post(f"{API}/models/{model}:generateContent", body, key)))
        except GeminiError as e:
            if _daily_quota(e):
                raise DailyQuotaError(
                    f"{model}: today's free-tier quota is used up ({e}). It resets at midnight "
                    "Pacific time (about 10:00 in Israel). Run again after that: it resumes."
                ) from None
            transient = any(x in str(e) for x in ("HTTP 429", "HTTP 500", "HTTP 503", "network:"))
            if attempt < retries and transient and not _no_free_quota(e):
                wait = _retry_after(e) or delay  # the server's own retry hint, when it gives one
                # v1.44: say so -- a request can legitimately sit silent for minutes (TIMEOUT)
                # before this fires, and the owner read that silence as "stuck".
                print(f"  {model}: busy right now ({e}); waiting {wait:.0f}s and trying again "
                      f"(attempt {attempt + 1} of {retries})...", file=sys.stderr)
                time.sleep(wait)
                delay *= 2
                continue
            raise
        except json.JSONDecodeError as e:
            raise GeminiError(f"reply wasn't JSON: {e}") from None
    raise GeminiError("unreachable")


def extract(description: str, model: str, key: str, post: Optional[Post] = None, retries: int = 4) -> dict[str, dict[str, Any]]:
    """One listing, one request."""
    return ground(clean(_ask(build_prompt(description), response_schema(), model, key, post, retries)), description)


def extract_batch(items: dict[str, str], model: str, key: str, post: Optional[Post] = None,
                  retries: int = 4) -> dict[str, dict[str, dict[str, Any]]]:
    """Several listings, one request: the free tier's daily limit counts
    requests, not listings. Each listing's answers are cleaned and checked
    against ITS text. A listing missing from the reply, or answered twice,
    is left out, so a resumed run asks for it again."""
    if len(items) == 1:
        (lid, text), = items.items()
        return {lid: extract(text, model, key, post, retries)}
    reply = _ask(build_batch_prompt(items), batch_schema(list(items)), model, key, post, retries)
    rows = [r for r in reply if isinstance(r, dict)] if isinstance(reply, list) else []
    ids = [r.get("id") for r in rows]
    return {r["id"]: ground(clean(r), items[r["id"]]) for r in rows
            if r.get("id") in items and ids.count(r["id"]) == 1}


def run(texts: dict[str, str], model: "str | list[str]", key: str, post: Optional[Post] = None, pause: float = 4.5,
        done: Optional[dict[str, Any]] = None, save: Optional[Callable[[str, dict[str, Any]], None]] = None,
        batch: int = 1, first: Optional[dict[str, Any]] = None) -> tuple[str, dict[str, Any]]:
    """Answers for every listing, `batch` listings per request. `done` holds
    answers from an earlier, interrupted run (skipped here); `save` is called
    with the model name and the answers so far after each request, so a
    crash loses at most the request in flight.

    `model` is one name, or several to fall back through in order: once the
    one in use hits ITS free-tier daily quota (or has none at all on this
    key), later requests move to the next -- mid-run, not only at the start
    -- without losing anything already answered. Returns the model that
    ended up answering the last request, and every answer so far."""
    models = [model] if isinstance(model, str) else list(model)
    current = models[0]
    answers: dict[str, Any] = {**(done or {}), **(first or {})}
    if first and save:
        save(current, answers)
    todo = [k for k in texts if k not in answers]
    requests = 0
    exhausted: set[str] = set()
    while todo:
        chunk = todo[:batch]
        if requests or first:
            time.sleep(pause)  # stay well under free-tier requests-per-minute
        # v1.44: printed BEFORE the request, since a single call can sit silent
        # for a while (TIMEOUT) if the free tier is under high demand -- without
        # this line that wait looks identical to a hang.
        print(f"  asking {current} for {len(chunk)} listing(s) (a reply can take a few minutes)...", file=sys.stderr)
        started = time.monotonic()
        try:
            got = extract_batch({k: texts[k] for k in chunk}, current, key, post)
        except GeminiError as e:
            left = [m for m in models if m not in exhausted and m != current]
            out_of_quota = isinstance(e, DailyQuotaError) or _no_free_quota(e)
            # v1.47: the owner's actual case -- a model that just answers "HTTP
            # 503: ... currently experiencing high demand" (or times out)
            # again and again isn't out of QUOTA, but it's just as stuck, and
            # by the time this is caught here, its own retries (in _ask) are
            # already exhausted. Worth abandoning for another candidate too.
            overloaded = any(x in str(e) for x in ("HTTP 429", "HTTP 500", "HTTP 503", "network:"))
            if (out_of_quota or overloaded) and left:
                exhausted.add(current)
                current = left[0]
                print(f"  {current}: switching models ({e})", file=sys.stderr)
                continue  # retry this same chunk, now on the next model
            if (out_of_quota or overloaded) and len(models) > 1:  # every candidate's out, and there WERE others to try
                raise GeminiError(f"none of these models answered on this key right now: "
                                  f"{models} (last: {e})") from None
            raise  # one model only, or a non-transient error: its own message stands
        requests += 1
        answers.update(got)
        if save:
            save(current, answers)
        print(f"  {len(got)} of {len(chunk)} answered in {time.monotonic() - started:.0f}s "
              f"({len(answers)}/{len(texts)})", file=sys.stderr)
        if not got:
            raise GeminiError(f"{current} answered none of {chunk}; stopping rather than looping")
        todo = [k for k in texts if k not in answers]
    return current, answers


def _no_free_quota(error: GeminiError) -> bool:
    text = str(error)
    return "HTTP 404" in text or "HTTP 403" in text or ("HTTP 429" in text and "limit: 0" in text)


class DailyQuotaError(GeminiError):
    pass


def run_with_fallback(texts: dict[str, str], key: str, models: list[str], post: Optional[Post] = None,
                      done: Optional[dict[str, Any]] = None,
                      save: Optional[Callable[[str, dict[str, Any]], None]] = None,
                      batch: int = 1) -> tuple[str, dict[str, Any]]:
    """Try the candidate models in order; move to the next whenever one has
    no free quota left on this key -- right at the start, or mid-run once
    its daily limit is used up -- keeping every answer already saved."""
    if not [k for k in texts if k not in (done or {})]:  # nothing left: no request (v1.28: it sent an empty one)
        return models[0], dict(done or {})
    return run(texts, models, key, post, done=done, save=save, batch=batch)


def resumable(previous: dict[str, Any], model: str) -> bool:
    """Can a saved run be resumed? Only one made by the same model (or any,
    with "auto") with this very prompt (v1.28): answers to an older wording
    must not be mixed into a run of a newer one."""
    return bool(previous.get("_model")) and model in ("auto", previous["_model"]) and previous.get("_prompt") == prompt_id()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("texts")
    parser.add_argument("out")
    parser.add_argument("--model", default="auto",
                        help="a model name to pin (never swapped out), or 'auto' to pick a free one "
                             "and move to the next free one if its daily quota runs out")
    parser.add_argument("--batch", type=int, default=1, help="listings per request")
    args = parser.parse_args(argv)
    texts = json.loads(Path(args.texts).read_text(encoding="utf-8"))
    out = Path(args.out)
    key = api_key()

    def save(model: str, answers: dict[str, Any]) -> None:
        body = {"_model": model, "_prompt": prompt_id(), "_batch": args.batch, "_complete": all(k in answers for k in texts), **answers}
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(out)  # never a half-written file

    # Resume an interrupted run of the same model, if there is one.
    previous = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    done = {k: v for k, v in previous.items() if not k.startswith("_") and k in texts}
    if done and resumable(previous, args.model):
        if args.model == "auto":
            # v1.45: a resumed "auto" run can still move off the model it
            # started with, if THAT model's daily quota runs out partway
            # through today's continuation -- not just on a fresh run's first request.
            others = [m for m in candidate_models(_http_get(f"{API}/models?pageSize=200", key))
                     if m != previous["_model"]]
            models = [previous["_model"], *others]
        else:
            models = [previous["_model"]]  # a pinned model is never swapped out from under you
        print(f"  resuming: {len(done)} of {len(texts)} already done with {models[0]}", file=sys.stderr)
    else:
        done = {}
        models = candidate_models(_http_get(f"{API}/models?pageSize=200", key)) if args.model == "auto" else [args.model]
    # v1.47: say up front whether there's anything to fall back to, so a stop
    # later (every candidate quota'd out, or every one overloaded) is read as
    # what it is -- not "it didn't even try" -- when there's genuinely only one.
    print(f"  {len(models)} candidate model(s) on this key: {models}" if len(models) > 1
          else f"  only one candidate model on this key: {models[0]} (nothing to fall back to)", file=sys.stderr)
    model, answers = run_with_fallback(texts, key, models, done=done, save=save, batch=max(1, args.batch))
    save(model, answers)
    print(f"wrote {len(answers)} listings to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
