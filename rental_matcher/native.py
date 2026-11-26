"""
The helper as a Chrome native messaging host (v1.24): Chrome starts it
when the extension needs it and stops it when the extension lets go, so
there's no window to keep open and no port listening on the machine.

Chrome talks to it over stdin/stdout, each message a 4-byte length (native
byte order) and UTF-8 JSON. A request is {"id", "path", "body"}, the same
paths as the HTTP helper (/config, /plan, /score, /drives), plus the setup
page's (/prefs, /saveprefs, /places: rental_matcher/setup.py); the answer is
{"id", "ok", "status", "body"}. Chrome refuses a message from a host over
1 MB, so a bigger answer goes in pieces: {"id", "part", "of", "data"},
`data` slices of the JSON text, which the extension joins.

Registered once by `python -m rental_matcher.install`; Chrome only lets
the Rental Matcher extension (its id is in the registration) start it.
Nothing goes to stdout but messages; problems go to stderr, which Chrome
keeps out of the conversation.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, BinaryIO, Optional

from . import setup, traffic
from .scoring import PreferenceSet
from .server import BadRequest, config, do_calibrate, do_drives, do_plan, do_score, do_suggest

PIECE = 450_000  # bytes of the answer's JSON per piece; escaping may add some, see send()
HANDLERS = {"/plan": do_plan, "/score": do_score, "/drives": do_drives, "/suggest": do_suggest, "/calibrate": do_calibrate}
SETUP = {
    "/prefs": lambda path, body, get: setup.read(path),
    "/saveprefs": lambda path, body, get: setup.save(path, (body or {}).get("prefs") if isinstance(body, dict) else None),
    "/places": lambda path, body, get: setup.places((body or {}).get("q") if isinstance(body, dict) else None, get=get),
    "/relax": lambda path, body, get: setup.relax(path, body),
    "/reweigh": lambda path, body, get: setup.reweigh(path, body),
}


def read_message(stream: BinaryIO) -> Optional[Any]:
    head = stream.read(4)
    if len(head) < 4:
        return None  # Chrome closed the pipe: the extension is done
    (n,) = struct.unpack("=I", head)
    data = stream.read(n)
    if len(data) < n:
        return None
    return json.loads(data.decode("utf-8"))


def write_message(stream: BinaryIO, message: Any) -> None:
    data = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("=I", len(data)) + data)
    stream.flush()


def answer(request: Any, prefs_path: Path, get: Optional[traffic.Get] = None) -> dict[str, Any]:
    """One request -> {ok, status, body}, like the HTTP helper's answers."""
    if not isinstance(request, dict) or not isinstance(request.get("path"), str):
        return {"ok": False, "status": 400, "body": {"error": "a request is {id, path, body}"}}
    path, body = request["path"], request.get("body")
    if path in SETUP:  # the setup page: works even when the file is broken, so it can be fixed
        try:
            return {"ok": True, "status": 200, "body": SETUP[path](prefs_path, body, get)}
        except setup.SetupError as e:
            return {"ok": False, "status": 400, "body": {"error": str(e)}}
        except traffic.TrafficError as e:
            return {"ok": False, "status": 502, "body": {"error": str(e)}}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "status": 500, "body": {"error": f"{type(e).__name__}: {e}"}}
    try:
        prefs = PreferenceSet.load(prefs_path)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": 500, "body": {"error": f"the preferences file can't be read: {e}"}}
    try:
        if path == "/health":
            return {"ok": True, "status": 200, "body": {"ok": True}}
        if path == "/config":
            return {"ok": True, "status": 200, "body": config(prefs)}
        h = HANDLERS.get(path)
        if h is None:
            return {"ok": False, "status": 404, "body": {"error": "not found"}}
        if not isinstance(body, dict):
            raise BadRequest("a JSON object, please")
        if path == "/drives":
            out = do_drives(body, prefs, get)
        elif path == "/suggest":
            out = do_suggest(body, prefs, raw=json.loads(prefs_path.read_text(encoding="utf-8")))
        else:
            out = h(body, prefs)
        return {"ok": True, "status": 200, "body": out}
    except BadRequest as e:
        return {"ok": False, "status": 400, "body": {"error": str(e)}}
    except traffic.TrafficError as e:  # built without the URL: no key in it
        return {"ok": False, "status": 502, "body": {"error": str(e)}}
    except Exception as e:  # noqa: BLE001 -- answer, don't die mid-pull
        return {"ok": False, "status": 500, "body": {"error": f"{type(e).__name__}: {e}"}}


LIMIT = 1_000_000  # bytes a host's message may be (Chrome's limit is 1 MB), with a little room


def _slices(data: bytes, size: int) -> list[str]:
    """UTF-8 bytes cut into pieces of at most `size` bytes, never inside a character."""
    out, i = [], 0
    while i < len(data):
        j = min(i + size, len(data))
        while j < len(data) and (data[j] & 0xC0) == 0x80:  # a continuation byte: back up to the character's start
            j -= 1
        out.append(data[i:j].decode("utf-8"))
        i = j
    return out


def send(stream: BinaryIO, rid: Any, reply: dict[str, Any]) -> None:
    data = json.dumps({"id": rid, **reply}, ensure_ascii=False).encode("utf-8")
    if len(data) < LIMIT:
        stream.write(struct.pack("=I", len(data)) + data)
        stream.flush()
        return
    size = PIECE
    while True:  # escaping inside a piece can grow it: smaller pieces until every one fits
        parts = _slices(data, size)
        framed = [json.dumps({"id": rid, "part": k, "of": len(parts), "data": p}, ensure_ascii=False).encode("utf-8")
                  for k, p in enumerate(parts)]
        if all(len(f) < LIMIT for f in framed):
            break
        size //= 2
    for f in framed:
        stream.write(struct.pack("=I", len(f)) + f)
    stream.flush()


def serve(prefs_path: Path, stdin: BinaryIO, stdout: BinaryIO, get: Optional[traffic.Get] = None) -> None:
    while True:
        try:
            request = read_message(stdin)
        except (ValueError, UnicodeDecodeError):
            write_message(stdout, {"id": None, "ok": False, "status": 400, "body": {"error": "not JSON"}})
            continue
        if request is None:
            return
        rid = request.get("id") if isinstance(request, dict) else None
        send(stdout, rid, answer(request, prefs_path, get))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Rental Matcher's helper, as Chrome starts it")
    ap.add_argument("--prefs", required=True)
    a, _ = ap.parse_known_args(argv)  # Chrome adds the caller's origin (and a window handle on Windows)
    serve(Path(a.prefs).resolve(), sys.stdin.buffer, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
