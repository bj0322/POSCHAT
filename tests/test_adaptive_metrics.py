# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive AI 기록·통계(1.17): telemetry 이벤트 6종이 내용 없이 남고, 통계(로컬 비율·승격·지연·성공률·절감 추정)와 주간 예산이 맞는지."""
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import adaptive_engine  # noqa: E402
import telemetry  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from support import isolated_app_dir  # noqa: E402

SECRET = "비밀 프로젝트 파랑새 회의록"


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.iso = isolated_app_dir()
        self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        telemetry.config_getter = lambda: {}
        self.addCleanup(setattr, telemetry, "config_getter", None)
        self.fake = FakeOllama()
        self.addCleanup(self.fake.close)
        self.config = {"adaptive": {"enabled": True, "policy": "economy", "local_retries": 0,
                                    "local": {"endpoint": self.fake.url, "default_model": "qwen2.5:7b"}}}
        self.rt = adaptive_engine.LocalRuntime(lambda: self.config)

    def engine(self):
        return adaptive_engine.AdaptiveEngine(self.config, self.rt, lambda p, m, d, i: "Cloud 답변입니다. 한국어로 씁니다.",
                                              "claude-sonnet-5-5", True)

    def run_mix(self):
        e = self.engine()
        self.fake.replies.append("파랑새 회의에서는 예산을 확정했고 다음 주까지 자료를 준비하기로 했습니다.")
        e.ask(f"{SECRET}을 세 줄로 요약해 줘", task_text=f"{SECRET}을 세 줄로 요약해 줘")            # 로컬, 통과
        self.fake.replies.append("English only answer that should fail the Korean language check for sure.")
        e.ask(f"{SECRET}을 세 줄로 요약해 줘", task_text=f"{SECRET}을 세 줄로 요약해 줘")            # 로컬 → Cloud
        e.ask("두 방법을 비판적으로 비교하고 가설을 검증해 줘", task_text="두 방법을 비판적으로 비교하고 가설을 검증해 줘")  # Cloud
        return e

    def test_events_have_no_content(self):
        self.run_mix()
        raw = telemetry.events_path().read_text(encoding="utf-8")
        self.assertNotIn("파랑새", raw)
        self.assertNotIn("English only", raw)
        types = {json.loads(line)["type"] for line in raw.splitlines()}
        for t in ("routing_decision", "local_inference", "cloud_inference", "quality_check", "escalation"):
            self.assertIn(t, types)
        dec = [json.loads(line) for line in raw.splitlines() if '"routing_decision"' in line]
        for key in ("area", "task", "difficulty", "provider", "model", "policy", "reason", "ms", "est_tokens"):
            self.assertIn(key, dec[0])

    def test_failure_event(self):
        self.config["adaptive"]["policy"] = "local_only"
        self.fake.close()
        self.rt.forget()
        with self.assertRaises(adaptive_engine.AdaptiveError):
            self.engine().ask("요약해 줘", task_text="요약해 줘")
        kinds = [e.get("kind") for e in telemetry.load(1) if e["type"] == "routing_failure"]
        self.assertEqual(kinds, ["local_required_unavailable"])

    def test_summary(self):
        self.run_mix()
        s = adaptive_engine.summary(30)
        self.assertEqual(s["requests"], 3)
        self.assertEqual((s["local"], s["cloud"]), (2, 1))
        self.assertEqual(s["local_ratio"], round(2 / 3, 3))
        self.assertEqual(s["escalations"], 1)
        self.assertEqual(s["escalation_ratio"], 0.5)
        self.assertEqual(s["success_local"]["checked"], 2)
        self.assertEqual(s["success_local"]["ok"], 1)
        self.assertIsNotNone(s["latency_local"]["p95"])
        self.assertIsNotNone(s["latency_cloud"]["avg"])
        # Sonnet 5.5는 크레딧 근거가 있어 '로컬로 처리해 아낀 Cloud 크레딧'을 추정한다(로컬 하드웨어 비용은 넣지 않는다)
        self.assertGreater(s["saved_credits_est"], 0)
        self.assertGreater(s["credits_per_cloud_request"], 0)
        self.assertTrue(any(m["model"] == "local:qwen2.5:7b" for m in s["models"]))

    def test_unknown_cloud_price_is_not_invented(self):
        e = adaptive_engine.AdaptiveEngine(self.config, self.rt, lambda *a: "답", "gpt-5.1-gs-2025-11-13", True)
        self.fake.replies.append("회의에서는 예산을 확정했고 다음 주까지 자료를 준비하기로 했습니다.")
        e.ask("이 글을 요약해 줘", task_text="이 글을 요약해 줘")
        s = adaptive_engine.summary(30)
        self.assertIsNone(s["saved_credits_est"])
        self.assertEqual(s["saved_unknown"], 1)
        self.assertIsNone(s["credits_per_cloud_request"])

    def test_weekly_budget(self):
        for _ in range(3):
            telemetry.record("llm_call", mode="chat_completions", model="claude-sonnet-5-5", ms=10, ok=True,
                             input_tokens=1000, output_tokens=300)
        telemetry.record("llm_call", mode="chat_completions", model="claude-sonnet-5-5", ms=10, ok=False)  # 실패는 세지 않는다
        b = adaptive_engine.budget_state({"adaptive": {"budget": {"weekly_calls": 3}}})
        self.assertEqual(b["calls"], 3)
        self.assertTrue(b["exceeded"])
        b = adaptive_engine.budget_state({"adaptive": {"budget": {"weekly_credits": 1000}}})
        self.assertFalse(b["exceeded"])
        self.assertGreater(b["credits"], 0)
        self.assertFalse(adaptive_engine.budget_state({})["exceeded"])
        old = time.time() - 8 * 86400  # 지난주 기록은 이번 주 예산에 넣지 않는다
        self.assertEqual(adaptive_engine.budget_state({"adaptive": {"budget": {"weekly_calls": 3}}}, now=old + 86400 * 20)["calls"], 0)

    def test_budget_exceeded_keeps_work_local(self):
        for _ in range(2):
            telemetry.record("llm_call", mode="chat_completions", model="gpt-x", ms=10, ok=True)
        self.config["adaptive"]["budget"] = {"weekly_calls": 2}
        calls = []
        e = adaptive_engine.AdaptiveEngine(self.config, self.rt, lambda *a: calls.append(a) or "x", "gpt-x", True)
        self.fake.replies.append("English only answer that should fail the Korean language check for sure.")
        e.ask("이 글을 요약해 줘", task_text="이 글을 요약해 줘")
        self.assertEqual(calls, [])  # 예산을 넘었으면 승격도 하지 않는다
        self.assertEqual(e.summary()["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
