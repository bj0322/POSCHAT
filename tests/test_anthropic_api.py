# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.11 개인 Claude API(Anthropic Messages API). 로컬 가짜 서버로 SDK 경로(데스크톱)와 HTTP 경로(안드로이드)를 모두 확인한다."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import api

GOOD_KEY = "sk-ant-test-key"


class FakeAnthropic(BaseHTTPRequestHandler):
    requests = []
    refuse = False

    def log_message(self, *args):
        pass

    def _json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        # SDK(2.x)는 Authorization: Bearer로, HTTP 경로는 x-api-key로 보낸다. 둘 다 받는다.
        if GOOD_KEY not in (self.headers.get("x-api-key"), (self.headers.get("Authorization") or "")[7:]):
            self._json(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        if self.path.startswith("/v1/models"):
            self._json(200, {"data": [{"type": "model", "id": "claude-opus-5-5", "display_name": "Claude Opus 5.5"},
                                      {"type": "model", "id": "claude-haiku-5-5", "display_name": "Claude Haiku 5.5"}],
                             "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-haiku-5-5"})
        else:
            self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "nope"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeAnthropic.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if not self._authorized():
            return
        stop = "refusal" if FakeAnthropic.refuse else "end_turn"
        message = {"id": "msg_1", "type": "message", "role": "assistant", "model": body.get("model"),
                   "content": [] if FakeAnthropic.refuse else [{"type": "text", "text": "안녕하세요"}],
                   "stop_reason": stop, "stop_sequence": None,
                   "usage": {"input_tokens": 11, "output_tokens": 4}}
        if FakeAnthropic.refuse:
            message["stop_details"] = {"type": "refusal", "category": "cyber", "explanation": None}
        if not body.get("stream"):
            return self._json(200, message)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        start = dict(message, content=[], stop_reason=None, usage={"input_tokens": 11, "output_tokens": 0})
        start.pop("stop_details", None)
        events = [("message_start", {"type": "message_start", "message": start})]
        if not FakeAnthropic.refuse:
            events += [
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                ("ping", {"type": "ping"}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "안녕"}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "하세요"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ]
        delta = {"stop_reason": stop, "stop_sequence": None}
        if FakeAnthropic.refuse:
            delta["stop_details"] = message["stop_details"]
        events += [("message_delta", {"type": "message_delta", "delta": delta, "usage": {"output_tokens": 4}}),
                   ("message_stop", {"type": "message_stop"})]
        for name, data in events:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()


class AnthropicApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnthropic)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.env = patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeAnthropic.requests.clear()
        FakeAnthropic.refuse = False
        patcher = patch.object(api, "ANTHROPIC_BASE_URL", self.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def paths(self):
        """(이름, SDK를 쓸지). SDK가 설치되지 않은 환경에서는 HTTP 경로만 확인한다."""
        out = [("http", api._SDK_MISSING)]
        if api._anthropic_sdk() is not None:
            out.insert(0, ("sdk", api._anthropic_sdk()))
        return out

    def settings(self, model="claude-opus-5-5", stream=True):
        return api.ApiSettings(mode=api.ANTHROPIC_MODE, model=model, stream=stream)

    def test_settings_keep_a_separate_claude_model(self):
        settings = api.ApiSettings.from_config({"api_mode": "anthropic", "model": "gpt-5.1-gs-2025-11-13",
                                                "anthropic_model": "claude-sonnet-5-5"})
        self.assertEqual((settings.mode, settings.model), ("anthropic", "claude-sonnet-5-5"))
        self.assertEqual(api.ApiSettings.from_config({"api_mode": "anthropic"}).model, api.DEFAULT_ANTHROPIC_MODEL)
        self.assertEqual(api.model_config_key("anthropic"), "anthropic_model")
        self.assertEqual(api.model_config_key("chat_completions"), "model")

    def test_streams_and_returns_the_answer(self):
        for name, sdk in self.paths():
            with self.subTest(path=name), patch.object(api, "_sdk_module", sdk):
                FakeAnthropic.requests.clear()
                deltas, usage = [], []
                with patch.object(api, "on_usage", lambda mode, model, u: usage.append((mode, model, u))):
                    text = api.ask(GOOD_KEY, "안녕?", settings=self.settings(), on_delta=deltas.append)
                self.assertEqual(text, "안녕하세요")
                self.assertEqual(deltas[-1], "안녕하세요")
                self.assertEqual(usage, [("anthropic", "claude-opus-5-5", {"input_tokens": 11, "output_tokens": 4})])
                sent = FakeAnthropic.requests[-1]
                self.assertEqual(sent["path"], "/v1/messages")
                self.assertEqual(sent["headers"].get("anthropic-version"), api.ANTHROPIC_VERSION)  # SDK 기본값과 같다
                self.assertIn(api.ANTHROPIC_FALLBACK_BETA, sent["headers"].get("anthropic-beta", ""))
                body = sent["body"]
                self.assertTrue(body["stream"])
                self.assertEqual(body["fallbacks"], "default")
                self.assertEqual(body["output_config"], {"effort": api.ANTHROPIC_EFFORT})
                self.assertEqual(body["max_tokens"], api.ANTHROPIC_MAX_TOKENS)
                self.assertNotIn("temperature", body)
                self.assertNotIn("thinking", body)

    def test_non_streaming_request_with_images(self):
        for name, sdk in self.paths():
            with self.subTest(path=name), patch.object(api, "_sdk_module", sdk):
                text = api.ask(GOOD_KEY, "이 그림은?", settings=self.settings("claude-haiku-5-5", stream=False),
                               images=[("image/png", "aGVsbG8=")])
                self.assertEqual(text, "안녕하세요")
                body = FakeAnthropic.requests[-1]["body"]
                self.assertFalse(body.get("stream", False))
                self.assertEqual(body["max_tokens"], api.ANTHROPIC_MAX_TOKENS_ONCE)
                content = body["messages"][0]["content"]
                self.assertEqual(content[0], {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                                          "data": "aGVsbG8="}})
                self.assertEqual(content[-1], {"type": "text", "text": "이 그림은?"})
                # Haiku에는 서버 대체 모델(fallbacks)이 없다
                self.assertNotIn("fallbacks", body)
                self.assertNotIn("anthropic-beta", {k.lower() for k in FakeAnthropic.requests[-1]["headers"]})

    def test_prompt_cache_prefix_and_usage(self):
        # 1.17: 앞부분을 cache_control 블록으로 나누고, 서버가 알려 준 캐시 토큰을 따로 돌려준다
        params, _ = api._anthropic_params(self.settings(), "앞부분뒷부분", None, True, cache_prefix=3)
        self.assertEqual(params["messages"][0]["content"], [
            {"type": "text", "text": "앞부분", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "뒷부분"}])
        params, _ = api._anthropic_params(self.settings(), "전부", [("image/png", "aGk=")], True, cache_prefix=99)
        self.assertEqual(params["messages"][0]["content"][-1], {"type": "text", "text": "전부", "cache_control": {"type": "ephemeral"}})
        params, _ = api._anthropic_params(self.settings(), "그대로", None, True)
        self.assertEqual(params["messages"][0]["content"], "그대로")
        self.assertEqual(api._anthropic_usage({"input_tokens": 10, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0,
                                               "output_tokens": 5}),
                         {"input_tokens": 910, "output_tokens": 5, "cache_read_input_tokens": 900})
        self.assertEqual(api._usage({"usage": {"prompt_tokens": 2000, "completion_tokens": 10,
                                               "prompt_tokens_details": {"cached_tokens": 1024}}}),
                         {"input_tokens": 2000, "output_tokens": 10, "cache_read_input_tokens": 1024})
        for name, sdk in self.paths():
            with self.subTest(path=name), patch.object(api, "_sdk_module", sdk):
                out = {}
                api.ask(GOOD_KEY, "안녕", settings=self.settings(stream=False), usage_out=out, cache_prefix=1)
                self.assertEqual(out, {"input_tokens": 11, "output_tokens": 4})
                body = FakeAnthropic.requests[-1]["body"]
                self.assertEqual(body["messages"][0]["content"][0]["cache_control"], {"type": "ephemeral"})

    def test_older_models_get_no_effort(self):
        params, betas = api._anthropic_params(self.settings("claude-opus-4-8"), "hi", None, True)
        self.assertNotIn("output_config", params)
        self.assertEqual(betas, [])

    def test_refusal_is_an_error(self):
        FakeAnthropic.refuse = True
        for name, sdk in self.paths():
            for stream in (True, False):
                with self.subTest(path=name, stream=stream), patch.object(api, "_sdk_module", sdk):
                    with self.assertRaisesRegex(api.ApiError, "안전 정책.*cyber"):
                        api.ask(GOOD_KEY, "x", settings=self.settings(stream=stream),
                                on_delta=(lambda t: None) if stream else None)

    def test_bad_key_says_so(self):
        for name, sdk in self.paths():
            with self.subTest(path=name), patch.object(api, "_sdk_module", sdk):
                with self.assertRaisesRegex(api.ApiError, "Anthropic API 키를 확인하세요 \\(HTTP 401\\)"):
                    api.ask("wrong", "x", settings=self.settings(stream=False))

    def test_lists_models(self):
        for name, sdk in self.paths():
            with self.subTest(path=name), patch.object(api, "_sdk_module", sdk):
                self.assertEqual(api.list_anthropic_models(GOOD_KEY), ["claude-opus-5-5", "claude-haiku-5-5"])
        self.assertEqual(api.model_label("claude-haiku-5-5"), "Claude Haiku 5.5 — 가장 빠르고 저렴")


if __name__ == "__main__":
    unittest.main()
