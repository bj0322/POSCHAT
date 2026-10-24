# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""3단계 라우팅(1.17): 사용자 → 경량 Cloud 모델(Haiku 등) → 프런티어. 경량 모델이 혼자 답하거나, 필요한 부분만 프런티어에 짧게
상담(<<CONSULT>>)하고, 검증에 실패하면 프런티어로 올린다. 프런티어 상담 기록은 대화별 세션으로 이어진다."""
import json
import os
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import adaptive_engine  # noqa: E402
import adaptive_router as r  # noqa: E402
import telemetry  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from support import isolated_app_dir  # noqa: E402

LIGHT, FRONTIER = "claude-haiku-5-5", "claude-opus-5-5"
LONG_HISTORY = "[이전 대화]\n" + "\n".join(f"사용자: 실험 {i}번의 조건과 결과를 길게 설명한 기록입니다. 비밀 코드명 파랑새." for i in range(60))
KO = "회의에서는 예산을 확정했고, 다음 주까지 발표 자료를 준비하기로 했습니다. 담당자는 김 연구원입니다."


class TierRuleTests(unittest.TestCase):
    def route(self, text, policy="balanced", light=True, settings=None, purpose="chat"):
        a = r.analyze(text, text, purpose=purpose)
        base = r.route(a, policy, None, r.Candidate("cloud", FRONTIER), {}, {}, None)
        return r.tier(base, a, r.Candidate("cloud", LIGHT) if light else None, settings or {}, allow_consult=purpose == "chat")

    def test_light_answers_moderate_work_and_consults_on_hard_work(self):
        out = self.route("이 회의록을 세 줄로 요약해 줘")
        self.assertEqual((out.provider, out.model, out.tier), ("light", LIGHT, "light"))
        hard = self.route("두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘")
        self.assertEqual((hard.provider, hard.consult, hard.reason_code), ("light", True, "light_consult"))
        self.assertIn("프런티어에 상담", hard.reason)

    def test_frontier_keeps_critical_steps_and_quality_hard_work(self):
        self.assertEqual(self.route("x", purpose="agent_step").tier, "frontier")
        self.assertEqual(self.route("두 방법을 비판적으로 비교하고 가설을 검증해 줘", policy="quality").tier, "frontier")
        self.assertEqual(self.route("이 회의록을 세 줄로 요약해 줘", policy="quality").tier, "light")  # 쉬운 일은 Quality도 경량
        self.assertEqual(self.route("두 방법을 비판적으로 비교하고 가설을 검증해 줘", settings={"consult": False}).tier, "frontier")
        self.assertEqual(self.route("두 방법을 비판적으로 비교하고 가설을 검증해 줘", settings={"consult_max": 0}).tier, "frontier")

    def test_without_a_light_model_nothing_changes(self):
        out = self.route("이 회의록을 세 줄로 요약해 줘", light=False)
        self.assertEqual((out.provider, out.model, out.tier), ("cloud", FRONTIER, "frontier"))

    def test_economy_lets_light_answer_hard_work_alone(self):
        out = self.route("두 방법을 비판적으로 비교하고 가설을 검증해 줘", policy="economy")
        self.assertEqual((out.provider, out.reason_code), ("light", "light"))
        self.assertTrue(out.consult)  # 혼자 답하되 필요하면 상담할 수 있다


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.iso = isolated_app_dir()
        self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        telemetry.config_getter = lambda: {}
        self.addCleanup(setattr, telemetry, "config_getter", None)
        self.calls = []        # (model, prompt)
        self.replies = {LIGHT: [], FRONTIER: []}
        self.events = []
        self.config = {"adaptive": {"enabled": True, "policy": "balanced", "local_retries": 0}}
        self.rt = types.SimpleNamespace(candidate=lambda m: (None, "기본 로컬 모델을 고르지 않음"), provider=lambda: None)

    def cloud(self, prompt, model, on_delta, images):
        self.calls.append((model, prompt))
        queue = self.replies[model]
        text = queue.pop(0) if queue else ("프런티어 답입니다. 한국어로 정확히 답합니다." if model == FRONTIER else KO)
        if isinstance(text, Exception):
            raise text
        if on_delta:  # 받는 대로 조금씩
            for i in range(5, len(text) + 5, 5):
                on_delta(text[:i])
        return text

    def engine(self, session=None, **over):
        self.config["adaptive"].update(over)
        return adaptive_engine.AdaptiveEngine(self.config, self.rt, self.cloud, FRONTIER, True, on_event=self.events.append,
                                              light_model=LIGHT, frontier_session=session)

    def test_light_answers_alone(self):
        e = self.engine()
        out = e.ask("[현재 요청]\n이 회의록을 세 줄로 요약해 줘", task_text="이 회의록을 세 줄로 요약해 줘")
        self.assertEqual(out, KO)
        self.assertEqual([m for m, _ in self.calls], [LIGHT])
        s = e.summary()
        self.assertEqual((s["provider"], s["label"], s["status"]), ("light", "Light · 요약", "verified"))
        self.assertIn(adaptive_engine.CONSULT_MARK, self.calls[0][1])  # 상담 안내가 붙어 있다(쓸지는 경량 모델이 정한다)

    def test_consult_sends_only_the_question_to_the_frontier(self):
        task = "두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘"
        prompt = LONG_HISTORY + "\n\n[현재 요청]\n" + task
        req = {"question": "ADC 6비트와 8비트의 정확도 차이(0.023)가 노이즈 0.01에서 유의한가?", "context": "run2 0.884, run3 0.902"}
        self.replies[LIGHT] = [adaptive_engine.CONSULT_MARK + json.dumps(req, ensure_ascii=False),
                               "프런티어 상담 결과를 반영한 최종 답: 표본이 적어 유의성을 단정할 수 없습니다."]
        self.replies[FRONTIER] = ["표본 1개씩이라 유의성 검정이 불가능합니다. 반복 실험이 필요합니다."]
        deltas = []
        e = self.engine()
        out = e.ask(prompt, task_text=task, on_delta=deltas.append)
        self.assertIn("최종 답", out)
        self.assertEqual([m for m, _ in self.calls], [LIGHT, FRONTIER, LIGHT])
        frontier_prompt = self.calls[1][1]
        self.assertIn(req["question"], frontier_prompt)
        self.assertNotIn("파랑새", frontier_prompt)            # 대화 전체(기록)는 프런티어로 가지 않는다
        self.assertLess(len(frontier_prompt), len(prompt) / 3)
        self.assertIn("[외부 데이터: 상담에 붙인 발췌", frontier_prompt)  # 경량 모델이 고른 발췌도 외부 데이터로 감싼다
        self.assertIn("표본 1개씩이라", self.calls[2][1])      # 프런티어 답이 경량 모델의 맥락으로 돌아간다
        self.assertFalse(any(adaptive_engine.CONSULT_MARK in d or d.lstrip().startswith("<<") for d in deltas))  # 상담 줄은 화면에 안 보인다
        s = e.summary()
        self.assertTrue(s["consulted"])
        self.assertEqual(s["label"], "Light ⇄ Frontier · 연구 추론")
        self.assertLess(s["consult"]["frontier_tokens_est"], s["consult"]["full_tokens_est"])
        self.assertIn("consulted", [ev["kind"] for ev in self.events])
        self.assertEqual(len(e.frontier_session), 1)
        # 다음 요청: 지난 상담 기록이 프런티어 질문에 이어 붙는다(세션)
        self.calls.clear()
        self.replies[LIGHT] = [adaptive_engine.CONSULT_MARK + json.dumps({"question": "그럼 몇 번 반복해야 하나?"}, ensure_ascii=False), "세 번 이상 반복하세요."]
        e2 = self.engine(session=e.frontier_session)
        e2.ask("[현재 요청]\n" + task, task_text=task)
        self.assertIn("[이전 상담 기록(이 대화)]", self.calls[1][1])
        self.assertIn("ADC 6비트와 8비트", self.calls[1][1])

    def test_bad_consult_request_goes_to_the_frontier(self):
        task = "두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘"
        self.replies[LIGHT] = [adaptive_engine.CONSULT_MARK + "{not json"]
        e = self.engine()
        out = e.ask("[현재 요청]\n" + task, task_text=task)
        self.assertEqual(out, "프런티어 답입니다. 한국어로 정확히 답합니다.")
        self.assertEqual([m for m, _ in self.calls], [LIGHT, FRONTIER])
        self.assertEqual(e.summary()["label"], "Light → Frontier · 연구 추론")

    def test_light_answer_that_fails_the_gate_goes_to_the_frontier(self):
        self.replies[LIGHT] = ["This English answer fails the Korean language check because it is long enough to be checked."]
        e = self.engine()
        out = e.ask("[현재 요청]\n이 회의록을 세 줄로 요약해 줘", task_text="이 회의록을 세 줄로 요약해 줘")
        self.assertTrue(out.startswith("프런티어"))
        s = e.summary()
        self.assertEqual(s["chain"], ["light", "frontier"])
        self.assertTrue(s["provisional"].startswith("This English"))

    def test_no_escalation_keeps_the_light_answer_marked(self):
        self.replies[LIGHT] = ["This English answer fails the Korean language check because it is long enough to be checked."]
        e = self.engine(escalation=False)
        e.ask("[현재 요청]\n이 회의록을 세 줄로 요약해 줘", task_text="이 회의록을 세 줄로 요약해 줘")
        self.assertEqual([m for m, _ in self.calls], [LIGHT])
        self.assertEqual(e.summary()["status"], "unverified")

    def test_agent_steps_and_json_calls_do_not_consult(self):
        e = self.engine()
        e.ask("다음 단계 JSON", purpose="agent_step")
        self.assertEqual([m for m, _ in self.calls], [FRONTIER])  # 부작용으로 이어지는 단계는 프런티어
        self.calls.clear()
        self.replies[LIGHT] = ['{"memory": "답 끝에 — 끝"}']
        e.ask("[사용자 메시지] 기억해 줘", purpose="memory_extract")
        self.assertEqual([m for m, _ in self.calls], [LIGHT])
        self.assertNotIn(adaptive_engine.CONSULT_MARK, self.calls[0][1])  # JSON 호출에는 상담 안내를 붙이지 않는다

    def test_consult_cap(self):
        task = "두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘"
        e = self.engine()
        for _ in range(adaptive_engine.RUN_CONSULT_CAP + 2):
            self.replies[LIGHT] += [adaptive_engine.CONSULT_MARK + '{"question": "q"}', "최종 답입니다."]
            e.ask("[현재 요청]\n" + task, task_text=task)
        self.assertEqual(e.consults, adaptive_engine.RUN_CONSULT_CAP)

    def test_stats_show_light_share_consults_and_frontier_tokens(self):
        e = self.engine()
        e.ask("[현재 요청]\n이 회의록을 세 줄로 요약해 줘", task_text="이 회의록을 세 줄로 요약해 줘")
        task = "두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘"
        self.replies[LIGHT] = [adaptive_engine.CONSULT_MARK + '{"question": "짧은 질문"}', "최종 답입니다."]
        e.ask(LONG_HISTORY + "\n[현재 요청]\n" + task, task_text=task)
        e.ask("다음 단계 JSON", purpose="agent_step")
        s = adaptive_engine.summary(30)
        self.assertEqual(s["light"], 2)
        self.assertEqual(s["consults"], 1)
        self.assertGreater(s["frontier_token_saving_est"], 0.5)
        self.assertGreater(s["light_tokens_est"], 0)
        raw = telemetry.events_path().read_text(encoding="utf-8")
        self.assertNotIn("파랑새", raw)
        self.assertNotIn("짧은 질문", raw)  # 상담 질문 내용도 기록에 남기지 않는다


class LocalToLightTests(unittest.TestCase):
    def test_local_failure_goes_to_light_then_frontier(self):
        with isolated_app_dir():
            fake = FakeOllama()
            self.addCleanup(fake.close)
            config = {"adaptive": {"enabled": True, "policy": "economy", "local_retries": 0,
                                   "local": {"endpoint": fake.url, "default_model": "qwen2.5:7b"}}}
            rt = adaptive_engine.LocalRuntime(lambda: config)
            calls = []
            english = "This English answer fails the Korean language check because it is long enough to be checked."

            def cloud(prompt, model, on_delta, images):
                calls.append(model)
                return english if model == LIGHT else "프런티어가 한국어로 다시 쓴 답입니다."
            fake.replies.append(english)
            e = adaptive_engine.AdaptiveEngine(config, rt, cloud, FRONTIER, True, light_model=LIGHT)
            out = e.ask("[현재 요청]\n이 회의록을 세 줄로 요약해 줘", task_text="이 회의록을 세 줄로 요약해 줘")
            self.assertEqual(out, "프런티어가 한국어로 다시 쓴 답입니다.")
            self.assertEqual(calls, [LIGHT, FRONTIER])
            s = e.summary()
            self.assertEqual(s["chain"], ["local", "light", "frontier"])
            self.assertEqual(s["label"], "Local → Light → Frontier · 요약")


class BridgeTests(unittest.TestCase):
    def test_bridge_saves_the_frontier_session_and_validates_the_light_model(self):
        import agent
        import main
        import storage

        env = patch.dict(os.environ, {"POSTECH_GENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        with isolated_app_dir():
            b = main.Bridge()
            self.addCleanup(b._events.stop)
            self.addCleanup(b._mcp.shutdown)
            done = threading.Event()
            b._push = lambda ev: ev.get("type") == "done" and done.set()
            b._config.update(anthropic_api_key="k", api_mode="anthropic")
            st = b.adaptive_save({"enabled": True, "policy": "balanced", "light_model": "no-such-model"})
            self.assertEqual(st["settings"]["light_model"], "")
            st = b.adaptive_save({"light_model": LIGHT, "cloud_model": FRONTIER})
            self.assertEqual(st["light_model"], LIGHT)
            self.assertIn(LIGHT, st["light_suggestions"])
            replies = {LIGHT: [adaptive_engine.CONSULT_MARK + '{"question": "핵심 질문"}', "상담을 반영한 최종 답입니다."],
                       FRONTIER: ["프런티어의 짧은 답"]}

            def fake_ask(key, prompt, settings=None, **kw):
                return replies[settings.model].pop(0)
            with patch.object(agent, "ask", side_effect=fake_ask):
                thread = b.new_thread()
                b.send(thread["id"], "두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘", False)
                self.assertTrue(done.wait(20))
            t = storage.load_thread(thread["id"])
            msg = t["messages"][-1]
            self.assertEqual(msg["content"], "상담을 반영한 최종 답입니다.")
            self.assertTrue(msg["routing"]["consulted"])
            self.assertEqual(msg["routing"]["frontier_model"], FRONTIER)
            self.assertEqual(t["frontier_session"][0]["q"], "핵심 질문")
            self.assertEqual(t["frontier_session"][0]["a"], "프런티어의 짧은 답")


if __name__ == "__main__":
    unittest.main()
