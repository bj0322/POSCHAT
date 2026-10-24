# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive 정책(1.17): Economy·Balanced·Quality·Local Only의 선택, 예산·요청당 비용 한도, 개인정보 설정, 설정 기본값."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import adaptive_engine  # noqa: E402
import adaptive_router as r  # noqa: E402

LOCAL = r.Candidate("local", "qwen2.5:7b", context_length=8192)
CLOUD = r.Candidate("cloud", "claude-sonnet-5-5", cost=30.0)
REQUESTS = {
    "summary": "이 회의록을 세 줄로 요약해 줘",
    "chat": "주말에 포항에서 가볼 만한 곳 추천해 줘",
    "classify": "이 리뷰가 긍정인지 부정인지 분류해 줘",
    "translate": "다음 문장을 영어로 번역해 줘: 오늘 회의는 3시입니다",
    "code": "파이썬 함수에서 KeyError가 나는 버그 고쳐 줘",
    "research": "두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘",
}


def pick(policy, key, settings=None, local=LOCAL, cloud=CLOUD, budget=None, **kw):
    a = r.analyze(REQUESTS[key], REQUESTS[key], **kw)
    return r.route(a, policy, local, cloud, settings or {}, {}, budget)


class PolicyTests(unittest.TestCase):
    def test_economy_prefers_local_for_light_work(self):
        for key in ("summary", "chat", "classify", "translate"):
            self.assertEqual(pick("economy", key).provider, "local", key)
        for key in ("code", "research"):
            self.assertEqual(pick("economy", key).provider, "cloud", key)

    def test_balanced_is_conservative_on_research_and_code(self):
        self.assertEqual(pick("balanced", "summary").provider, "local")
        self.assertEqual(pick("balanced", "classify").provider, "local")
        for key in ("code", "research"):
            out = pick("balanced", key)
            self.assertEqual(out.provider, "cloud", key)
            self.assertIn("Balanced", out.reason)

    def test_quality_uses_local_only_when_measured(self):
        for key in REQUESTS:
            self.assertEqual(pick("quality", key).provider, "cloud", key)

    def test_local_only_never_routes_to_cloud(self):
        for key in REQUESTS:
            out = pick("local_only", key)
            self.assertEqual(out.provider, "local", key)
            self.assertFalse(out.escalation)
            self.assertEqual(out.fallback_model, "")
        out = pick("local_only", "summary", local=None)
        self.assertEqual(out.provider, "none")
        self.assertIn("로컬", out.reason)

    def test_escalation_flag_follows_settings(self):
        self.assertTrue(pick("economy", "summary").escalation)
        self.assertFalse(pick("economy", "summary", settings={"escalation": False}).escalation)
        self.assertFalse(pick("economy", "summary", cloud=None).escalation)

    def test_budget_and_cost_limit(self):
        out = pick("balanced", "code", budget={"exceeded": True})
        self.assertEqual(out.provider, "local")
        self.assertIn("budget", out.constraints)
        self.assertIn("예산", out.reason)
        out = pick("balanced", "code", settings={"max_cost_per_request": 10})
        self.assertEqual(out.provider, "local")
        self.assertIn("cost_limit", out.constraints)
        out = pick("balanced", "code", budget={"exceeded": True}, local=None)
        self.assertEqual(out.provider, "none")
        unknown = r.Candidate("cloud", "gpt-x", cost=None)  # 비용 근거가 없는 모델은 한도로 막지 않는다
        self.assertEqual(pick("balanced", "code", settings={"max_cost_per_request": 10}, cloud=unknown).provider, "cloud")

    def test_latency_priority(self):
        fast = r.Candidate("local", "qwen2.5:7b", context_length=8192, tokens_per_s=40)
        a = r.analyze("오늘 기분 어때", "오늘 기분 어때")
        self.assertEqual(r.route(a, "quality", fast, CLOUD, {"latency": "fast"}, {}, None).provider, "local")
        self.assertEqual(r.route(a, "quality", LOCAL, CLOUD, {"latency": "fast"}, {}, None).provider, "cloud")  # 속도를 재지 않았다

    def test_no_cloud_key(self):
        self.assertEqual(pick("balanced", "code", cloud=None).provider, "local")
        self.assertEqual(pick("balanced", "code", cloud=None, local=None).provider, "none")


class SettingsTests(unittest.TestCase):
    def test_defaults_keep_the_old_behavior(self):
        s = adaptive_engine.settings({})
        self.assertFalse(s["enabled"])
        self.assertFalse(adaptive_engine.active({}))
        self.assertEqual(s["policy"], "balanced")
        self.assertEqual(s["local"]["endpoint"], "http://127.0.0.1:11434")
        self.assertFalse(s["local"]["allow_remote"])
        self.assertEqual(s["local"]["default_model"], "")

    def test_bad_values_are_clamped(self):
        s = adaptive_engine.settings({"adaptive": {"policy": "free-for-all", "max_escalations": 99, "local_retries": 9,
                                                   "local": {"num_ctx": 4096}}})
        self.assertEqual(s["policy"], "balanced")
        self.assertEqual(s["max_escalations"], adaptive_engine.MAX_ESCALATIONS)
        self.assertEqual(s["local_retries"], 1)
        self.assertEqual(s["local"]["endpoint"], "http://127.0.0.1:11434")  # 일부만 저장돼 있어도 기본값을 채운다

    def test_model_ids(self):
        self.assertTrue(adaptive_engine.is_auto("auto"))
        self.assertEqual(adaptive_engine.local_model_of("local:qwen2.5:7b"), "qwen2.5:7b")
        self.assertEqual(adaptive_engine.local_model_of("gpt-5"), "")
        self.assertTrue(adaptive_engine.local_only({"adaptive": {"enabled": True, "policy": "local_only"}}))
        self.assertFalse(adaptive_engine.local_only({"adaptive": {"enabled": False, "policy": "local_only"}}))


if __name__ == "__main__":
    unittest.main()
