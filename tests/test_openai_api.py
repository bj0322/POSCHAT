# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.18 개인 GPT API(OpenAI Responses API). 로컬 가짜 서버로 요청 형식(Bearer만, 추론 설정, 이미지)·스트리밍·오류·모델 목록과
설정 저장·키 고르기를 확인한다."""
import json
import os
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import api  # noqa: E402

GOOD_KEY = "sk-openai-test-key"


class FakeOpenAI(BaseHTTPRequestHandler):
    requests = []
    no_reasoning = False   # 추론 설정을 받지 않는 모델 흉내
    status = 200

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
        if self.headers.get("Authorization") != f"Bearer {GOOD_KEY}":
            self._json(401, {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        if self.path == "/v1/models":
            self._json(200, {"object": "list", "data": [
                {"id": "gpt-4.1-mini", "created": 100}, {"id": "gpt-5.1", "created": 300},
                {"id": "text-embedding-3-small", "created": 400}, {"id": "gpt-4o-audio-preview", "created": 500},
                {"id": "o4-mini", "created": 200}, {"id": "dall-e-3", "created": 50}, {"id": "gpt-5.1", "created": 300}]})
        else:
            self._json(404, {"error": {"message": "nope"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeOpenAI.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if not self._authorized():
            return
        if FakeOpenAI.status != 200:
            return self._json(FakeOpenAI.status, {"error": {"message": "You exceeded your current quota"}})
        if FakeOpenAI.no_reasoning and "reasoning" in body:
            return self._json(400, {"error": {"message": "Unsupported parameter: 'reasoning.effort' is not supported with this model."}})
        usage = {"input_tokens": 12, "output_tokens": 3, "input_tokens_details": {"cached_tokens": 0}}
        response = {"id": "resp_1", "object": "response", "status": "completed", "model": body.get("model"),
                    "output": [{"type": "message", "role": "assistant",
                                "content": [{"type": "output_text", "text": "안녕하세요"}]}], "usage": usage}
        if not body.get("stream"):
            return self._json(200, response)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        events = [("response.created", {"type": "response.created", "response": dict(response, output=[], status="in_progress")}),
                  ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "안녕"}),
                  ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "하세요"}),
                  ("response.completed", {"type": "response.completed", "response": response})]
        for name, data in events:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()


class OpenAiApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"
        cls.env = patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeOpenAI.requests.clear()
        FakeOpenAI.no_reasoning = False
        FakeOpenAI.status = 200
        patcher = patch.object(api, "OPENAI_BASE_URL", self.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def settings(self, model="gpt-5.1", stream=True):
        return api.ApiSettings(mode=api.OPENAI_MODE, model=model, stream=stream)

    def test_settings_keep_a_separate_gpt_model(self):
        s = api.ApiSettings.from_config({"api_mode": "openai", "model": "gpt-5.1-gs-2025-11-13", "openai_model": "gpt-5-mini"})
        self.assertEqual((s.mode, s.model), ("openai", "gpt-5-mini"))
        self.assertEqual(api.ApiSettings.from_config({"api_mode": "openai"}).model, api.DEFAULT_OPENAI_MODEL)
        self.assertEqual(api.model_config_key("openai"), "openai_model")
        self.assertEqual(api.default_model("openai"), "gpt-5.1")

    def test_streams_with_bearer_only_and_reasoning(self):
        got = []
        usage = {}
        text = api.ask(GOOD_KEY, "안녕", settings=self.settings(), on_delta=got.append, usage_out=usage)
        self.assertEqual(text, "안녕하세요")
        self.assertEqual(got[-1], "안녕하세요")
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (12, 3))
        req = FakeOpenAI.requests[-1]
        self.assertEqual(req["path"], "/v1/responses")
        self.assertNotIn("x-api-key", {k.lower() for k in req["headers"]})   # POSTECH용 헤더로 키를 흘리지 않는다
        self.assertEqual(req["body"]["reasoning"], {"effort": api.REASONING_EFFORT})
        self.assertTrue(req["body"]["stream"])
        self.assertFalse(req["body"]["store"])

    def test_once_with_images_and_no_reasoning_for_gpt4(self):
        text = api.ask(GOOD_KEY, "그림 설명", settings=self.settings("gpt-4.1-mini", stream=False), images=[("image/png", "AAAA")])
        self.assertEqual(text, "안녕하세요")
        body = FakeOpenAI.requests[-1]["body"]
        self.assertNotIn("reasoning", body)
        parts = body["input"][0]["content"]
        self.assertEqual(parts[0], {"type": "input_text", "text": "그림 설명"})
        self.assertEqual(parts[1]["image_url"], "data:image/png;base64,AAAA")

    def test_model_without_reasoning_is_retried_once_without_it(self):
        FakeOpenAI.no_reasoning = True
        text = api.ask(GOOD_KEY, "안녕", settings=self.settings("gpt-5.1", stream=False))
        self.assertEqual(text, "안녕하세요")
        self.assertEqual(["reasoning" in r["body"] for r in FakeOpenAI.requests], [True, False])

    def test_errors_say_what_to_do(self):
        with self.assertRaisesRegex(api.ApiError, "OpenAI API 키가 올바르지 않습니다"):
            api.ask("sk-wrong", "안녕", settings=self.settings(stream=False))
        FakeOpenAI.status = 429
        with self.assertRaisesRegex(api.ApiError, "잔액이 부족"):
            api.ask(GOOD_KEY, "안녕", settings=self.settings(stream=False))
        with self.assertRaisesRegex(api.ApiError, "키가 없습니다"):
            api.ask("", "안녕", settings=self.settings(stream=False))

    def test_lists_chat_models_newest_first(self):
        self.assertEqual(api.list_openai_models(GOOD_KEY), ["gpt-5.1", "o4-mini", "gpt-4.1-mini"])
        with self.assertRaises(api.ApiError):
            api.list_openai_models("sk-wrong")


class BridgeTests(unittest.TestCase):
    def setUp(self):
        import main
        from support import isolated_app_dir, preserved_hooks

        self.hooks = preserved_hooks()
        self.hooks.__enter__()
        self.addCleanup(self.hooks.__exit__, None, None, None)
        self.iso = isolated_app_dir()
        self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("OPENAI_API_KEY", None)
        self.bridge = main.Bridge()
        self.addCleanup(self.bridge._mcp.shutdown)
        self.addCleanup(self.bridge._events.stop)

    def test_saving_the_gpt_mode_and_key(self):
        self.bridge.save_settings({"api_key": "postech-key"})
        state = self.bridge.save_settings({"api_mode": "openai", "openai_api_key": " sk-mine ", "model": "gpt-5-mini"})
        c = state["config"]
        self.assertEqual((c["api_mode"], c["openai_model"], c["openai_key_source"]), ("openai", "gpt-5-mini", "settings"))
        self.assertTrue(c["has_key"])
        self.assertEqual(self.bridge._api_key(), "sk-mine")        # 모델 호출은 OpenAI 키로
        self.assertEqual(self.bridge._postech_key(), "postech-key")  # POSTECH 키는 그대로(크레딧·음성)
        self.assertNotEqual(self.bridge._config.get("model"), "gpt-5-mini")   # POSTECH 방식의 모델은 건드리지 않는다
        self.assertIn("gpt-5.1", [m["id"] for m in state["openai_models"]])
        self.assertNotIn("sk-mine", json.dumps(state))               # 키는 화면으로 돌아가지 않는다
        self.assertEqual(self.bridge.new_thread()["model"], "gpt-5-mini")
        # 받아 온 모델 목록은 저장할 때 반영
        state = self.bridge.save_settings({"openai_server_models": ["gpt-5.2", "o4-mini"], "model": "o4-mini"})
        self.assertEqual([m["id"] for m in state["openai_models"]], ["gpt-5.2", "o4-mini"])
        self.assertEqual(state["openai_models_source"], "server")
        self.assertEqual(state["config"]["openai_model"], "o4-mini")
        # 키 지우기
        state = self.bridge.save_settings({"clear_openai_key": True})
        self.assertFalse(state["config"]["has_key"])
        self.assertIn("OpenAI API 키가 없습니다", self.bridge._missing_key_error())

    def test_refresh_models_uses_the_openai_key(self):
        with patch.object(api, "list_openai_models", return_value=["gpt-5.1"]) as lm:
            r = self.bridge.refresh_models({"api_mode": "openai", "openai_api_key": "sk-typed"})
        lm.assert_called_once_with("sk-typed")
        self.assertEqual(r["models"], [{"id": "gpt-5.1", "label": api.model_label("gpt-5.1")}])
        self.assertFalse(self.bridge.refresh_models({"api_mode": "openai"})["ok"])   # 키가 없으면


if __name__ == "__main__":
    unittest.main()
