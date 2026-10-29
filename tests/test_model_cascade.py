# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Quality-aware cascade(1.17): 로컬 답 검증 → 같은 모델로 다시 → Cloud 승격, 상한, 실패 처리, 임시 답 표시, 부작용 한 번만.
가짜 Ollama(tests/fake_ollama.py)와 실제 LocalRuntime·AdaptiveEngine을 쓴다. Cloud는 가짜 함수."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import adaptive_engine  # noqa: E402
import agent  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from support import isolated_app_dir  # noqa: E402

GOOD_KO = "회의에서는 예산을 확정했고, 다음 주까지 발표 자료를 준비하기로 했습니다. 담당자는 김 연구원입니다."


class CascadeTests(unittest.TestCase):
    def setUp(self):
        self.iso = isolated_app_dir()
        self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        self.fake = FakeOllama()
        self.addCleanup(self.fake.close)
        self.config = {"adaptive": {"enabled": True, "policy": "economy", "local": {"endpoint": self.fake.url,
                                                                                  "default_model": "qwen2.5:7b"}}}
        self.rt = adaptive_engine.LocalRuntime(lambda: self.config)
        self.cloud_calls = []
        self.cloud_reply = "Cloud가 다시 쓴 정확한 답변입니다. 한국어로 요약합니다."
        self.events = []

    def cloud(self, prompt, model, on_delta, images):
        self.cloud_calls.append((model, prompt))
        if isinstance(self.cloud_reply, Exception):
            raise self.cloud_reply
        if on_delta:
            on_delta(self.cloud_reply)
        return self.cloud_reply

    def engine(self, mode="auto", cloud=True, **over):
        self.config["adaptive"].update(over)
        return adaptive_engine.AdaptiveEngine(self.config, self.rt, self.cloud, "claude-sonnet-5-5", cloud, mode=mode,
                                              on_event=self.events.append)

    def ask(self, engine, text="이 회의록을 세 줄로 요약해 줘", **kw):
        return engine.ask("[현재 요청]\n" + text, task_text=text, **kw)

    def kinds(self):
        return [e["kind"] for e in self.events]

    def test_verified_local_answer(self):
        self.fake.replies.append(GOOD_KO)
        e = self.engine()
        deltas = []
        self.assertEqual(self.ask(e, on_delta=deltas.append), GOOD_KO)
        self.assertEqual(self.cloud_calls, [])
        s = e.summary()
        self.assertEqual((s["provider"], s["status"], s["api_call"]), ("local", "verified", False))
        self.assertEqual(s["label"], "Local · 요약")
        self.assertIn("provisional", self.kinds())  # 받는 동안은 '검증 전'으로 보인다
        self.assertIn("verified", self.kinds())
        self.assertTrue(deltas)

    def test_retry_same_local_model_for_format_problems(self):
        self.fake.replies.extend(["기억할 것은 없습니다", '{"memory": "답 끝에 — 끝"}'])
        e = self.engine()
        self.assertEqual(json.loads(e.ask("[사용자 메시지] 기억해 줘", purpose="memory_extract"))["memory"], "답 끝에 — 끝")
        self.assertEqual(self.cloud_calls, [])
        self.assertIn("retry", self.kinds())
        self.assertIn("[형식 안내]", self.fake.requests[-1]["body"]["messages"][0]["content"])
        self.assertTrue(self.fake.requests[-1]["body"]["format"] == "json")

    def test_escalates_when_verification_fails(self):
        self.fake.replies.append("This is an English answer even though the request was Korean, so it fails the check.")
        e = self.engine(local_retries=0)
        streamed = []
        answer = self.ask(e, on_delta=streamed.append)
        self.assertEqual(answer, self.cloud_reply)
        self.assertEqual(len(self.cloud_calls), 1)
        s = e.summary()
        self.assertTrue(s["escalated"])
        self.assertEqual(s["status"], "escalated")
        self.assertEqual(s["label"], "Local → Cloud · 요약")
        self.assertEqual(s["escalation_reason"], "요청한 언어가 아님")
        self.assertTrue(s["provisional"].startswith("This is an English"))  # 임시 답은 버리지 않고 남긴다(조용히 덮지 않음)
        self.assertEqual([a["provider"] for a in s["attempts"]], ["local", "cloud"])
        k = self.kinds()
        self.assertLess(k.index("provisional"), k.index("escalating"))
        self.assertEqual(streamed[-1], self.cloud_reply)

    def test_no_escalation_when_disabled_or_local_only(self):
        for over in ({"escalation": False}, {"policy": "local_only"}):
            self.events.clear()
            self.fake.replies.append("This is an English answer even though the request was Korean, so it fails.")
            e = self.engine(local_retries=0, **over)
            answer = self.ask(e)
            self.assertTrue(answer.startswith("This is an English"))
            self.assertEqual(self.cloud_calls, [], over)
            self.assertEqual(e.summary()["status"], "unverified")
            self.assertIn("검증 실패", e.summary()["label"])
            self.config["adaptive"].update(escalation=True, policy="economy")

    def test_cloud_failure_during_escalation_keeps_the_local_answer_visible(self):
        self.fake.replies.append("This is an English answer even though the request was Korean, so it fails.")
        self.cloud_reply = RuntimeError("HTTP 429")
        e = self.engine(local_retries=0)
        answer = self.ask(e)
        self.assertTrue(answer.startswith("This is an English"))
        s = e.summary()
        self.assertEqual(s["status"], "unverified")
        self.assertIn("429", s["escalation_error"])

    def test_local_runtime_failure_escalates_or_errors(self):
        self.fake.httpd.models.pop("qwen2.5:7b")  # 모델이 지워졌다(라우팅 뒤): 캐시된 후보로 갔다가 실행에서 실패
        self.rt.forget()
        e = self.engine()
        self.assertEqual(self.ask(e), self.cloud_reply)  # 후보가 없으니 처음부터 Cloud
        self.assertEqual(e.summary()["provider"], "cloud")
        self.fake.close()  # Ollama가 꺼졌다
        self.rt.forget()
        e = self.engine(policy="local_only")
        with self.assertRaises(adaptive_engine.AdaptiveError):
            self.ask(e)

    def test_mid_stream_drop_escalates(self):
        self.fake.replies.append({"text": GOOD_KO * 3, "drop": True})
        e = self.engine()
        self.assertEqual(self.ask(e), self.cloud_reply)
        s = e.summary()
        self.assertEqual(s["attempts"][0]["error"], "unavailable")
        self.assertTrue(s["escalated"])

    def test_escalation_cap_per_run(self):
        e = self.engine(local_retries=0)
        for _ in range(adaptive_engine.RUN_ESCALATION_CAP + 2):
            self.fake.replies.append("Only English here, long enough to be checked for language mismatch rules.")
            self.ask(e)
        self.assertEqual(len(self.cloud_calls), adaptive_engine.RUN_ESCALATION_CAP)
        self.assertEqual(e.routes[-1]["status"], "unverified")

    def test_manual_local_model_never_falls_back(self):
        self.fake.replies.append("Only English here, long enough to be checked for language mismatch rules.")
        e = self.engine(mode="local:qwen2.5:7b")
        self.assertTrue(self.ask(e, text="양자 컴퓨터의 미래를 비판적으로 분석해 줘").startswith("Only English"))
        self.assertEqual(self.cloud_calls, [])  # 어려운 작업이어도 직접 고른 로컬 모델을 바꾸지 않는다
        self.fake.close()
        e = self.engine(mode="local:qwen2.5:7b")
        with self.assertRaises(adaptive_engine.AdaptiveError):
            self.ask(e)
        self.assertEqual(self.cloud_calls, [])

    def test_cancel_during_local_stream(self):
        self.fake.replies.append({"text": GOOD_KO * 10, "delay": 0.02})
        stop = threading.Event()
        e = adaptive_engine.AdaptiveEngine(self.config, self.rt, self.cloud, "claude-sonnet-5-5", True, cancelled=stop.is_set)
        threading.Timer(0.1, stop.set).start()
        text = self.ask(e, on_delta=lambda t: None)
        self.assertLess(len(text), len(GOOD_KO * 10))
        self.assertEqual(self.cloud_calls, [])
        self.assertEqual(e.summary()["status"], "cancelled")

    def test_hard_tasks_go_to_cloud_first(self):
        e = self.engine(policy="balanced")
        self.ask(e, text="두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘")
        self.assertEqual(len(self.cloud_calls), 1)
        self.assertFalse(any(r["path"] == "/api/chat" for r in self.fake.requests))


class SideEffectTests(unittest.TestCase):
    def test_retries_and_escalation_never_repeat_a_file_write(self):
        """승격·다시 하기는 모델 호출 안에서 끝나므로 에이전트의 write 단계는 한 번만 실행된다."""
        with isolated_app_dir():
            fake = FakeOllama()
            self.addCleanup(fake.close)
            config = {"adaptive": {"enabled": True, "policy": "local_only", "local": {"endpoint": fake.url, "default_model": "qwen2.5:7b"}}}
            rt = adaptive_engine.LocalRuntime(lambda: config)
            fake.replies.extend([
                "파일을 쓰겠습니다",  # 형식 실패 → 같은 모델로 다시
                json.dumps({"action": "write", "path": "log.txt", "content": "한 줄\n"}),
                json.dumps({"action": "done", "answer": "썼습니다"}),
            ])
            engine = adaptive_engine.AdaptiveEngine(config, rt, lambda *a: "", "", False)
            confirms = []
            with tempfile.TemporaryDirectory() as ws:
                a = agent.Agent(api_key="", workspace=ws, agent_mode=True, max_steps=4, history_messages=0,
                                on_status=lambda t: None, on_tool=lambda s, d: None,
                                confirm=lambda kind, title, detail: confirms.append(kind) or True,
                                cancelled=lambda: False, engine=engine)
                answer = a._agent_loop([], "log.txt에 한 줄 써 줘", None)
                self.assertEqual(answer, "썼습니다")
                self.assertEqual((Path(ws) / "log.txt").read_text(), "한 줄\n")
                self.assertEqual(confirms, ["edit"])  # 승인도 한 번
            steps = [r for r in engine.routes if r["purpose"] == "agent_step"]
            self.assertEqual(len(steps), 2)
            self.assertEqual(len(steps[0]["attempts"]), 2)  # 첫 단계는 다시 해서 성공


if __name__ == "__main__":
    unittest.main()
