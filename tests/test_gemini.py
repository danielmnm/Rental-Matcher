"""Tests for the Gemini extractor, against a fake API (no network, no key)."""

import json
import unittest
from pathlib import Path
from unittest import mock

from rental_matcher.extraction import gemini
from rental_matcher.extraction.questions import QUESTIONS


def _reply(answers: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(answers, ensure_ascii=False)}]}}]}


ALL_NOT_STATED = {q.id: {"answer": "not_stated", "evidence": ""} for q in QUESTIONS}


class TestGemini(unittest.TestCase):
    def test_a_good_reply_is_kept(self):
        calls = []

        def post(url, body, key):
            calls.append((url, body, key))
            return _reply({**ALL_NOT_STATED, "elevator": {"answer": "no", "evidence": "ללא מעלית"},
                           "vaad_bayit": {"answer": "amount", "evidence": "ועד בית 35", "value": 35}})

        out = gemini.extract("קומה 2 ללא מעלית, ועד בית 35", "m", "SECRET", post)
        self.assertEqual(out["elevator"], {"answer": "no", "evidence": "ללא מעלית"})
        self.assertEqual(out["vaad_bayit"]["value"], 35)
        url, body, key = calls[0]
        self.assertNotIn("SECRET", url)  # the key travels in a header, never the URL
        self.assertEqual(body["generationConfig"]["temperature"], 0)
        self.assertIn("ללא מעלית", body["contents"][0]["parts"][0]["text"])

    def test_malformed_answers_become_not_stated(self):
        bad = {**ALL_NOT_STATED, "elevator": {"answer": "probably"}, "parking": "street",
               "vaad_bayit": {"answer": "amount", "value": True, "evidence": "x"},
               "furniture": {"answer": "items", "items": ["sofa", "air_conditioner"]},
               "apartment_type": {"answer": "items", "items": ["roof"]}}
        del bad["balcony"]
        out = gemini.extract("x", "m", "k", lambda *a: _reply(bad))
        self.assertEqual(out["elevator"]["answer"], "not_stated")
        self.assertEqual(out["parking"]["answer"], "not_stated")
        self.assertEqual(out["balcony"]["answer"], "not_stated")
        self.assertIn("problem", out["elevator"])
        cleaned = gemini.clean(bad)
        # a bool isn't an amount, and an amount with no number says nothing (v1.28: was kept as "amount")
        self.assertEqual(cleaned["vaad_bayit"]["answer"], "not_stated")
        self.assertEqual(cleaned["furniture"]["items"], ["sofa"])  # an id outside the list is dropped, and noted
        self.assertIn("air_conditioner", cleaned["furniture"]["problem"])
        self.assertIn("ungrounded", out["furniture"]["problem"])  # ...and a list with no quote is a guess
        self.assertEqual(cleaned["apartment_type"]["answer"], "not_stated")  # "items" isn't an answer there
        empty = gemini.clean({**ALL_NOT_STATED, "furniture": {"answer": "items", "items": ["air_conditioner"], "evidence": "מזגן"}})
        self.assertEqual(empty["furniture"]["answer"], "not_stated")  # a list naming nothing usable says nothing

    def test_an_answer_whose_quote_isnt_in_the_text_is_demoted(self):
        reply = {**ALL_NOT_STATED,
                 "elevator": {"answer": "yes", "evidence": "בניין עם מעלית"},  # invented: the text says no such thing
                 "parking": {"answer": "deeded", "evidence": "חניה  בטאבו"},  # real, with different spacing
                 "balcony": {"answer": "service_only", "evidence": "מרפסת שירות ... מקלט"},  # two real pieces
                 "protected_space": {"answer": "yes", "evidence": "מקלט מסודר מאוד"}}  # close, but not the text
        out = gemini.extract("דירה יפה. חניה בטאבו. מרפסת שירות. מקלט מסודר מאד.", "m", "k", lambda *a: _reply(reply))
        self.assertEqual(out["elevator"]["answer"], "not_stated")
        self.assertIn("ungrounded", out["elevator"]["problem"])
        self.assertEqual(out["parking"]["answer"], "deeded")
        self.assertEqual(out["balcony"]["answer"], "service_only")
        self.assertEqual(out["protected_space"]["answer"], "not_stated")

    def test_rate_limits_back_off_then_succeed_and_other_errors_raise(self):
        replies = [gemini.GeminiError("HTTP 429: slow down"), _reply(ALL_NOT_STATED)]

        def post(*a):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("time.sleep") as sleep:
            gemini.extract("x", "m", "k", post)
            sleep.assert_called_once()
        with self.assertRaises(gemini.GeminiError):
            gemini.extract("x", "m", "k", lambda *a: (_ for _ in ()).throw(gemini.GeminiError("HTTP 400: bad")))
        with self.assertRaises(gemini.GeminiError):
            gemini.extract("x", "m", "k", lambda *a: {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})

    def test_a_network_timeout_is_retried_not_a_crash(self):
        replies = [gemini.GeminiError("network: TimeoutError: The read operation timed out"), _reply(ALL_NOT_STATED)]

        def post(*a):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("time.sleep"):
            self.assertEqual(gemini.extract("x", "m", "k", post)["elevator"]["answer"], "not_stated")

    def test_http_post_turns_a_socket_timeout_into_a_gemini_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("The read operation timed out")):
            with self.assertRaisesRegex(gemini.GeminiError, "network: TimeoutError"):
                gemini._http_post("https://example.invalid", {}, "k")

    def test_an_interrupted_run_resumes_and_saves_after_each_listing(self):
        import tempfile
        from pathlib import Path
        texts = {"a": "x", "b": "y", "c": "z"}
        asked, down = [], [True]

        def post(url, body, key):
            listing = next(k for k, v in texts.items() if f"<<<\n{v}\n>>>" in body["contents"][0]["parts"][0]["text"])
            asked.append(listing)
            if listing == "b" and down[0]:  # "b" keeps timing out: retries run out, the run stops
                raise gemini.GeminiError("network: TimeoutError")
            return _reply(ALL_NOT_STATED)

        models = {"models": [{"name": "models/m-flash", "supportedGenerationMethods": ["generateContent"]}]}
        with tempfile.TemporaryDirectory() as d, mock.patch("time.sleep"), \
                mock.patch.object(gemini, "api_key", return_value="k"), \
                mock.patch.object(gemini, "_http_get", return_value=models), \
                mock.patch.object(gemini, "_http_post", side_effect=post):
            tf, out = Path(d) / "t.json", Path(d) / "out.json"
            tf.write_text(json.dumps(texts), encoding="utf-8")
            with self.assertRaises(gemini.GeminiError):
                gemini.main([str(tf), str(out)])
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual((saved["_model"], saved["_complete"]), ("m-flash", False))
            self.assertEqual([k for k in saved if not k.startswith("_")], ["a"])  # kept, despite the crash
            asked.clear()
            down[0] = False
            gemini.main([str(tf), str(out)])
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(saved["_complete"])
            self.assertEqual(sorted(k for k in saved if not k.startswith("_")), ["a", "b", "c"])
            self.assertEqual(asked, ["b", "c"])  # resumed: "a" isn't asked again

    def test_a_429_says_which_quota_and_a_daily_one_is_not_retried(self):
        import io
        import urllib.error
        body = json.dumps({"error": {"code": 429, "message": "You exceeded your current quota", "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}).encode()
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(body))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(gemini.GeminiError) as ctx:
                gemini._http_post("https://example.invalid", {}, "k")
        self.assertIn("PerDay", str(ctx.exception))
        self.assertIn("[retry: 37s]", str(ctx.exception))
        with mock.patch("time.sleep") as sleep:
            with self.assertRaisesRegex(gemini.DailyQuotaError, "resets at midnight Pacific"):
                gemini.extract("x", "m", "k", lambda *a: (_ for _ in ()).throw(ctx.exception))
            sleep.assert_not_called()

    def test_a_per_minute_429_waits_as_long_as_the_server_asks(self):
        replies = [gemini.GeminiError("HTTP 429: [quota: GenerateRequestsPerMinutePerProjectPerModel-FreeTier] [retry: 21s]"),
                   _reply(ALL_NOT_STATED)]

        def post(*a):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("time.sleep") as sleep:
            gemini.extract("x", "m", "k", post)
        sleep.assert_called_once_with(22.0)

    def test_a_batch_is_one_request_and_each_listing_is_checked_against_its_own_text(self):
        texts = {"a": "קומה 2 ללא מעלית", "b": "חניה בטאבו", "c": "דירה יפה"}
        calls = []

        def post(url, body, key):
            calls.append(body)
            return {"candidates": [{"content": {"parts": [{"text": json.dumps([
                {"id": "a", **ALL_NOT_STATED, "elevator": {"answer": "no", "evidence": "ללא מעלית"}},
                {"id": "b", **ALL_NOT_STATED, "elevator": {"answer": "no", "evidence": "ללא מעלית"},  # a's words, not b's
                 "parking": {"answer": "deeded", "evidence": "חניה בטאבו"}},
                {"id": "zz", **ALL_NOT_STATED},  # not asked for
            ], ensure_ascii=False)}]}}]}

        out = gemini.extract_batch(texts, "m", "k", post)
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["a"]["elevator"]["answer"], "no")
        self.assertEqual(out["b"]["parking"]["answer"], "deeded")
        self.assertEqual(out["b"]["elevator"]["answer"], "not_stated")  # borrowed quote: demoted
        self.assertNotIn("c", out)  # missing from the reply: asked again on resume
        self.assertNotIn("zz", out)
        prompt = calls[0]["contents"][0]["parts"][0]["text"]
        self.assertIn("Listing c:", prompt)
        self.assertEqual(calls[0]["generationConfig"]["responseSchema"]["type"], "array")

    def test_a_listing_answered_twice_in_a_batch_is_dropped(self):
        rows = [{"id": "a", **ALL_NOT_STATED}, {"id": "a", **ALL_NOT_STATED}, {"id": "b", **ALL_NOT_STATED}]
        post = lambda *a: {"candidates": [{"content": {"parts": [{"text": json.dumps(rows)}]}}]}
        self.assertEqual(sorted(gemini.extract_batch({"a": "x", "b": "y"}, "m", "k", post)), ["b"])

    def test_a_batched_run_keeps_the_probe_and_saves_after_each_request(self):
        texts = {k: k for k in "abcde"}
        saves, calls = [], []

        def post(url, body, key):
            prompt = body["contents"][0]["parts"][0]["text"]
            asked = [k for k in texts if f"Listing {k}:" in prompt]
            calls.append(asked)
            return {"candidates": [{"content": {"parts": [{"text": json.dumps([{"id": k, **ALL_NOT_STATED} for k in asked])}]}}]}

        with mock.patch("time.sleep"):
            model, answers = gemini.run_with_fallback(texts, "k", ["m"], post, save=lambda m, a: saves.append(len(a)), batch=2)
        # the probe's two answers are kept, not asked again; a lone last listing uses the one-listing prompt
        self.assertEqual(calls, [["a", "b"], ["c", "d"], []])
        self.assertEqual(sorted(answers), list("abcde"))
        self.assertEqual(saves, [2, 4, 5])

    def test_a_model_that_answers_none_of_a_batch_stops_the_run_instead_of_looping(self):
        calls = []

        def post(*a):
            calls.append(1)
            if len(calls) > 5:
                raise RuntimeError("looped")
            return {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}

        with mock.patch("time.sleep"), self.assertRaisesRegex(gemini.GeminiError, "answered none"):
            gemini.run({"a": "x", "b": "y"}, "m", "k", post, batch=2)

    def test_schema_is_converted_to_geminis_subset(self):
        s = gemini.gemini_schema({"type": "object", "additionalProperties": False,
                                  "properties": {"v": {"type": ["number", "null"]}}})
        self.assertEqual(s, {"type": "object", "properties": {"v": {"type": "number", "nullable": True}}})
        self.assertNotIn("additionalProperties", json.dumps(gemini.gemini_schema(gemini.response_schema())))

    def test_no_key_is_a_clear_error(self):
        # api_key() also checks the current folder (so it works when the repo
        # itself is the cwd) and the repo's own parent -- a real .gemini_key
        # sitting in either must not leak into this "no key" case, so an empty
        # tempdir stands in for the cwd and KEY_FILE's own parent is patched too.
        import tempfile
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(gemini, "KEY_FILE", Path(d) / "nope" / ".gemini_key"), \
                mock.patch("pathlib.Path.cwd", return_value=Path(d)):
            with self.assertRaises(gemini.GeminiError):
                gemini.api_key()


if __name__ == "__main__":
    unittest.main()


class TestModelChoice(unittest.TestCase):
    def test_candidates_best_first_and_only_text_flash(self):
        listing = {"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in
                              ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3-flash-preview", "gemini-2.5-flash-image",
                               "gemini-3.6-flash", "gemini-3.1-pro"]]}
        self.assertEqual(gemini.candidate_models(listing),
                         ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"])

    def test_falls_back_past_a_model_with_no_free_quota(self):
        def post(url, body, key):
            if "first" in url:
                raise gemini.GeminiError("HTTP 429: quota exceeded, limit: 0")
            return _reply(ALL_NOT_STATED)

        with mock.patch("time.sleep"):
            model, answers = gemini.run_with_fallback({"a": "x", "b": "y"}, "k", ["first", "second"], post)
        self.assertEqual((model, sorted(answers)), ("second", ["a", "b"]))
        with self.assertRaises(gemini.GeminiError), mock.patch("time.sleep") as sleep:
            gemini.run_with_fallback({"a": "x"}, "k", ["first"], post)
        sleep.assert_not_called()  # a zero quota isn't waited on (it used to cost 75 s of backoff per model)

    def test_a_daily_quota_used_up_mid_run_moves_to_the_next_model(self):
        # v1.45: it used to only try the next model on the very first request
        # of a run; a model whose quota ran out partway through (common on a
        # resumed run) just stopped the whole thing instead of moving on.
        calls = []

        def post(url, body, key):
            model = url.split("/models/")[1].split(":")[0]
            calls.append(model)
            if model == "first" and calls.count("first") > 1:  # answers one, then today's quota is gone
                raise gemini.GeminiError("HTTP 429: [quota: GenerateRequestsPerDayPerProjectPerModel-FreeTier]")
            return _reply(ALL_NOT_STATED)

        with mock.patch("time.sleep"):
            model, answers = gemini.run({"a": "x", "b": "y", "c": "z"}, ["first", "second"], "k", post, batch=1)
        self.assertEqual(model, "second")
        self.assertEqual(sorted(answers), ["a", "b", "c"])  # "a" (answered before the quota hit) wasn't lost
        self.assertEqual(calls, ["first", "first", "second", "second"])  # "first" retried once, then dropped

    def test_a_persistently_overloaded_model_moves_to_the_next_one(self):
        # v1.47: the owner's real case -- not a quota error at all, just
        # "HTTP 503: ... currently experiencing high demand" (or a network
        # timeout) every single time, even after _ask's own retries ran out.
        # That's just as worth abandoning for another candidate as a quota.
        calls = []

        def post(url, body, key):
            model = url.split("/models/")[1].split(":")[0]
            calls.append(model)
            if model == "first":
                raise gemini.GeminiError('HTTP 503: {"error": {"status": "UNAVAILABLE"}}')
            return _reply(ALL_NOT_STATED)

        with mock.patch("time.sleep"):
            model, answers = gemini.run({"a": "x"}, ["first", "second"], "k", post, batch=1)
        self.assertEqual(model, "second")
        self.assertEqual(list(answers), ["a"])
        self.assertEqual(calls.count("first"), 5)  # all of _ask's own retries (default retries=4), then abandoned
        self.assertEqual(calls.count("second"), 1)

    def test_every_candidate_overloaded_raises_one_clear_error(self):
        with mock.patch("time.sleep"), self.assertRaisesRegex(gemini.GeminiError, "none of these models answered"):
            gemini.run({"a": "x"}, ["first", "second"], "k",
                      lambda *a: (_ for _ in ()).throw(gemini.GeminiError("network: ConnectionError")))

    def test_a_non_transient_error_is_never_a_reason_to_switch_models(self):
        # a malformed request (our own bug, not the model's availability)
        # would just as deterministically fail on every candidate, so it
        # isn't treated as a reason to burn through the whole list.
        calls = []

        def post(url, body, key):
            calls.append(url)
            raise gemini.GeminiError("HTTP 400: bad request")

        with self.assertRaisesRegex(gemini.GeminiError, "HTTP 400"):
            gemini.run({"a": "x"}, ["first", "second"], "k", post, batch=1)
        self.assertEqual(len(calls), 1)  # never even tried "second"

    def test_a_bom_from_notepad_is_stripped(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, mock.patch.dict("os.environ", {}, clear=True):
            key_file = Path(d) / ".gemini_key"
            key_file.write_text("﻿abc123\n", encoding="utf-8")
            with mock.patch.object(gemini, "KEY_FILE", key_file):
                self.assertEqual(gemini.api_key(), "abc123")


class TestRunFile(unittest.TestCase):
    def test_a_run_belongs_to_one_prompt(self):
        import json
        import tempfile
        import run_gemini_test as r
        from rental_matcher.extraction.prompt import prompt_id
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d)
            first = r.run_file(runs)
            self.assertIn(f"_p{prompt_id()}", first.name)
            first.write_text(json.dumps({"_complete": False}), encoding="utf-8")
            self.assertEqual(r.run_file(runs), first)  # unfinished: resume it
            first.write_text(json.dumps({"_complete": True}), encoding="utf-8")
            self.assertNotEqual(r.run_file(runs), first)  # finished: never overwritten
            old = runs / "2026-10-01_gemini_b8.json"  # an older prompt's unfinished run
            old.write_text(json.dumps({"_complete": False}), encoding="utf-8")
            self.assertNotEqual(r.run_file(runs), old)


class TestRescore(unittest.TestCase):
    def test_latest_run_is_the_newest_complete_one(self):
        import json, os, tempfile, time
        sys_path = Path(__file__).resolve().parents[1]
        import sys
        sys.path.insert(0, str(sys_path))
        import run_gemini_test
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d)
            (runs / "2026-10-19_gemini_b8.json").write_text(json.dumps({"_complete": True}))
            time.sleep(0.01)
            (runs / "2026-10-20_gemini_b8_pabc.json").write_text(json.dumps({"_complete": False}))
            self.assertEqual(run_gemini_test.latest_run(runs).name, "2026-10-19_gemini_b8.json")
            os.utime(runs / "2026-10-19_gemini_b8.json", (1, 1))
            (runs / "2026-10-21_gemini_b8_pdef.json").write_text(json.dumps({"_complete": True}))
            self.assertEqual(run_gemini_test.latest_run(runs).name, "2026-10-21_gemini_b8_pdef.json")
