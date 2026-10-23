# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
import json
import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("webview", types.ModuleType("webview"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # support.py

import api
import evals
import secret_store
import storage
import telemetry
from support import FakeHttp, FakeResponse, isolated_app_dir


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()
        self.config = {}
        self.getter = patch.object(telemetry, "config_getter", lambda: self.config)
        self.getter.start()
        telemetry._queue.clear()

    def tearDown(self):
        self.getter.stop()
        telemetry._queue.clear()
        self._dir.__exit__(None, None, None)

    def test_api_calls_are_traced_without_content(self):
        traces = []
        settings = api.ApiSettings(mode="chat_completions", chat_completions_url="https://x/v1/chat/completions",
                                   model="claude-sonnet-5-5")
        with patch.object(api, "on_trace", lambda info, prompt, reply: traces.append((info, prompt, reply))), \
                patch.object(api, "_ask_chat_completions", return_value=("답", {"input_tokens": 1000, "output_tokens": 150})):
            self.assertEqual(api.ask("k", "질문", settings=settings), "답")
        info, prompt, reply = traces[0]
        self.assertEqual((info["ok"], info["model"], info["input_tokens"], prompt, reply), (True, "claude-sonnet-5-5", 1000, "질문", "답"))
        with patch.object(api, "on_trace", lambda info, prompt, reply: traces.append((info, prompt, reply))), \
                patch.object(api, "_ask_chat_completions", side_effect=api.ApiError("서버 오류(HTTP 429)")):
            with self.assertRaises(api.ApiError):
                api.ask("k", "질문", settings=settings)
        self.assertEqual((traces[1][0]["ok"], traces[1][0]["error"]), (False, "http_429"))
        # telemetry는 내용을 남기지 않는다
        telemetry.on_llm_call(traces[0][0], "비밀 질문", "비밀 답")
        text = telemetry.events_path().read_text(encoding="utf-8")
        self.assertNotIn("비밀", text)
        self.assertIn('"model": "claude-sonnet-5-5"', text)

    def test_feature_off_records_nothing(self):
        self.config["features"] = {"observability": False}
        telemetry.record("llm_call", model="m", ok=True)
        self.assertFalse(telemetry.events_path().exists())

    def test_summary_rates_latency_credits_tools_agent_and_feedback(self):
        now = time.time()
        for i, (ok, ms_) in enumerate([(True, 100), (True, 300), (False, 900), (True, 200)]):
            telemetry.record("llm_call", model="claude-sonnet-5-5", ok=ok, ms=ms_, input_tokens=250, output_tokens=75,
                             error="" if ok else "http_500")
        telemetry.record("llm_call", model="gpt-6-astra", ok=True, ms=50)
        telemetry.record("tool_call", server="github", tool="get_file", ok=True, ms=40, attempts=2, approval="auto", kind="read")
        telemetry.record("tool_call", server="github", tool="create_issue", ok=False, ms=0, approval="denied", kind="write")
        telemetry.record("agent_run", mode="agent", outcome="done", steps=4, ms=1000)
        telemetry.record("agent_run", mode="agent", outcome="error", steps=2, ms=500)
        telemetry.record("feedback", model="claude-sonnet-5-5", rating=1)
        telemetry.record("feedback", model="claude-sonnet-5-5", rating=-1)
        s = telemetry.summary(30, now=now + 1)
        sonnet = next(m for m in s["models"] if m["model"] == "claude-sonnet-5-5")
        self.assertEqual((sonnet["calls"], sonnet["errors"], sonnet["error_rate"]), (4, 1, 0.25))
        self.assertEqual(sonnet["p95_ms"], 900)
        self.assertEqual(sonnet["credits"], 4 * 24 + 4 * 1 + 4 * 1)  # 호출마다 24 + 입력 250토큰·출력 75토큰 = 각 1크레딧
        self.assertEqual((sonnet["feedback_up"], sonnet["feedback_down"]), (1, 1))
        gpt = next(m for m in s["models"] if m["model"] == "gpt-6-astra")
        self.assertIsNone(gpt["credits"])  # 근거가 없는 모델은 추정하지 않는다
        self.assertEqual(s["credits_unknown_models"], ["gpt-6-astra"])
        tools = {t["tool"]: t for t in s["tools"]}
        self.assertEqual(tools["github.get_file"]["retries"], 1)
        self.assertEqual(tools["github.create_issue"]["denied"], 1)
        self.assertEqual(s["agent"]["agent"]["success_rate"], 0.5)

    def test_prune_drops_old_events(self):
        telemetry.record("llm_call", model="m")
        path = telemetry.events_path()
        old = json.dumps({"ts": time.time() - 100 * 86400, "type": "llm_call"})
        path.write_text(old + "\n" + path.read_text(), encoding="utf-8")
        telemetry.prune()
        self.assertEqual(len(path.read_text().splitlines()), 1)

    def test_langfuse_export_sends_metadata_and_redacts_optional_content(self):
        self.config["telemetry"] = {"langfuse": {"enabled": True, "host": "https://lf.example", "include_content": False}}
        secret_store.set("langfuse:public_key", "pk-lf-1")
        secret_store.set("langfuse:secret_key", "sk-lf-2")
        telemetry.on_llm_call({"mode": "chat_completions", "model": "m", "ms": 10, "ok": True, "input_tokens": 3,
                               "output_tokens": 4}, "질문 내용", "답 내용")
        fake = FakeHttp([("POST", "/api/public/ingestion", FakeResponse(207, {"successes": []}))])
        self.assertEqual(telemetry.export_pending(http=fake), 1)
        batch = fake.calls[0]["json"]["batch"]
        self.assertEqual([b["type"] for b in batch], ["trace-create", "generation-create"])
        self.assertEqual(batch[1]["body"]["usage"]["input"], 3)
        self.assertNotIn("input", batch[1]["body"])
        self.assertTrue(fake.calls[0]["headers"]["Authorization"].startswith("Basic "))
        self.config["telemetry"]["langfuse"]["include_content"] = True
        telemetry.on_llm_call({"mode": "x", "model": "m", "ms": 1, "ok": True},
                              "내 키는 sk-abcdefghijklmnopqrstuv 이고 메일은 kim@example.com", "답")
        fake = FakeHttp([("POST", "/api/public/ingestion", FakeResponse(500, {}))])
        self.assertEqual(telemetry.export_pending(http=fake), 0)
        self.assertEqual(len(telemetry._queue), 1)  # 실패하면 다시 보낼 수 있게 남긴다
        body = telemetry.to_langfuse(telemetry._queue[0])[1]["body"]
        self.assertNotIn("sk-abcdefghijklmnopqrstuv", body["input"])
        self.assertNotIn("kim@example.com", body["input"])

    def test_export_needs_https_and_keys(self):
        self.config["telemetry"] = {"langfuse": {"enabled": True, "host": "http://lf.example"}}
        telemetry.record("llm_call", model="m")
        self.assertEqual(telemetry.export_pending(http=FakeHttp([])), 0)
        self.assertIn("https", telemetry._export["last_error"])


class EvalTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()
        self.getter = patch.object(telemetry, "config_getter", lambda: {})
        self.getter.start()

    def tearDown(self):
        self.getter.stop()
        self._dir.__exit__(None, None, None)

    def test_rule_based_scoring(self):
        self.assertEqual(evals.score("391", {"regex": r"^\D*391\D*$", "max_chars": 20}), (1.0, []))
        s, failed = evals.score('결과: {"label": "부정"}', {"json_keys": ["label", "reason"], "contains": ["긍정"]})
        self.assertEqual(s, 0.0)
        self.assertEqual(len(failed), 2)
        self.assertEqual(evals.score("\\(2x\\)", {"any": ["2x"], "regex": r"\\\(", "not_contains": ["```"]})[0], 1.0)

    def test_run_compares_models_and_records_results(self):
        answers = {"good": {"arith": "391", "json": '{"label": "긍정", "reason": "기분이 좋다"}', "korean": "Artificial Intelligence",
                            "list": "포항공과대학교", "latex": "\\(2x\\)", "refuse-secret": "회의는 3시에 시작한다."},
                   "bad": {}}

        def ask(model, prompt):
            if model == "broken":
                raise api.ApiError("HTTP 500")
            case = next(c for c in evals.BUILTIN["cases"] if c["prompt"] == prompt)
            return answers[model].get(case["id"], "모르겠습니다")

        report = evals.run(evals.BUILTIN, ["good", "bad", "broken"], ask)
        self.assertEqual(report["models"]["good"]["score"], 1.0)
        self.assertLess(report["models"]["bad"]["score"], 0.5)
        self.assertEqual(report["models"]["broken"]["score"], 0.0)
        self.assertEqual(evals.recent(1)[0]["models"]["good"]["passed"], len(evals.BUILTIN["cases"]))
        s = telemetry.summary(1)
        self.assertEqual(next(m for m in s["models"] if m["model"] == "good")["eval_score"], 1.0)

    def test_user_sets_are_validated(self):
        d = self.root / "evals"
        d.mkdir()
        (d / "mine.json").write_text(json.dumps({"name": "mine", "cases": [{"id": "a", "prompt": "p", "expect": {"contains": ["x"]}}]}))
        (d / "broken.json").write_text(json.dumps({"name": "broken", "cases": [{"id": "a"}]}))
        names = set(evals.sets())
        self.assertIn("mine", names)
        self.assertNotIn("broken", names)


class FeedbackTests(unittest.TestCase):
    def test_feedback_is_saved_on_the_message_and_counted_per_model(self):
        import main

        with isolated_app_dir():
            bridge = main.Bridge.__new__(main.Bridge)
            bridge._config = {}
            bridge._lock = threading.RLock()
            thread = storage.new_thread()
            msg = storage.make_message("assistant", "답", model="gemini-3.8-flash")
            thread["messages"].append(msg)
            storage.save_thread(thread)
            with patch.object(telemetry, "config_getter", lambda: {}):
                self.assertTrue(bridge.feedback(thread["id"], msg["id"], 1)["ok"])
                self.assertEqual(storage.load_thread(thread["id"])["messages"][0]["feedback"], 1)
                bridge.feedback(thread["id"], msg["id"], 1)  # 같은 평가를 다시 눌러도 한 번만 센다
                s = telemetry.summary(1)
            gem = next(m for m in s["models"] if m["model"] == "gemini-3.8-flash")
            self.assertEqual(gem["feedback_up"], 1)
            self.assertFalse(bridge.feedback(thread["id"], "nope", 1)["ok"])


if __name__ == "__main__":
    unittest.main()
