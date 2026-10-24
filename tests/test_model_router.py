# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive 라우터(1.17): 요청 분석(작업 유형·난이도·의미 분류·분포 밖), 제약(이미지·문맥·메모리), 측정 기록."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import adaptive_router as r  # noqa: E402
import connectors  # noqa: E402
from support import isolated_app_dir  # noqa: E402

LOCAL = r.Candidate("local", "qwen2.5:7b", context_length=8192, vision=False)
CLOUD = r.Candidate("cloud", "gpt-5.1-gs-2025-11-13")


class AnalyzerTests(unittest.TestCase):
    def check(self, text, task, difficulty=None, prompt=None, **kw):
        a = r.analyze(prompt or text, text, **kw)
        self.assertEqual(a.task, task, f"{text}: {a}")
        if difficulty:
            self.assertEqual(a.difficulty, difficulty, f"{text}: {a}")
        return a

    def test_task_types(self):
        self.check("이 글을 세 줄로 요약해 줘", "summarization", "easy")
        self.check("다음 문장을 영어로 번역해 줘: 오늘 회의는 3시입니다", "translation", "easy")
        self.check("이 리뷰가 긍정인지 부정인지 분류해 줘", "classification", "easy")
        self.check("이 공지에서 날짜와 장소만 뽑아 줘", "extraction", "easy")
        self.check("파이썬 함수에서 KeyError가 나는 버그 고쳐 줘", "coding", "hard")
        self.check("리스트와 튜플의 차이를 코드로 설명해 줘", "coding", "moderate")
        self.check("이 실험 결과로 가설을 검증할 수 있는지 통계적으로 따져 줘", "research", "hard")
        self.check("고마워 오늘도 수고했어", "general_chat", "easy")

    def test_feature_markers_from_attachments(self):
        page = connectors.wrap_untrusted("본문", "웹페이지 https://x.org")
        self.check("이 페이지 요약해 줘", "browser", "easy", prompt="[현재 요청]\n이 페이지 요약해 줘\n" + page)
        pdf = connectors.wrap_untrusted("본문", "논문 PDF 'Attention' p. 3")
        self.check("3쪽 실험 설정을 설명해 줘", "paper", "hard", prompt="x\n" + pdf)
        self.check("이 논문 요약해 줘", "paper", "moderate", prompt="x\n" + pdf)
        lab = connectors.wrap_untrusted("acc,0.9", "Lab 실험 기록 AIMC")
        self.check("두 Run의 정확도 차이를 정리해 줘", "data_lab", prompt="x\n" + lab)
        code = connectors.wrap_untrusted("def f(): pass", "작업 폴더 파일 a.py")
        self.check("이 코드 설명해 줘", "coding", prompt="x\n" + code)

    def test_purposes_for_internal_calls(self):
        self.check("기억해 줘", "extraction", "easy", purpose="memory_extract")
        a = self.check("파일 정리해 줘", "agent_planning", "critical", purpose="agent_step")
        self.assertTrue(a.needs_tools and a.side_effects)
        self.check("x", "coding", "critical", purpose="code_agent_step")

    def test_out_of_distribution_is_conservative(self):
        a = r.analyze("zxqv plmok wert", "zxqv plmok wert")
        self.assertEqual((a.task, a.method), ("other", "ood"))
        self.assertEqual(r.route(a, "balanced", LOCAL, CLOUD, {}, {}, None).provider, "cloud")

    def test_semantic_stage_reports_confidence(self):
        task, top, margin = r.semantic("주말에 포항에서 가볼 만한 곳 추천해 줘")
        self.assertEqual(task, "general_chat")
        self.assertGreater(top, r.SEMANTIC_MIN)
        self.assertGreaterEqual(margin, 0)

    def test_adjustments(self):
        long = "가" * 13000
        self.assertEqual(r.analyze(long + " 요약해 줘", "요약해 줘").difficulty, "hard")
        self.assertTrue(r.analyze("최신 뉴스 알려 줘", "최신 뉴스 알려 줘").needs_fresh)
        self.assertFalse(r.analyze("오늘 점심 뭐 먹지", "오늘 점심 뭐 먹지").needs_fresh)
        a = r.analyze("논문 요약해 줘, 몇 쪽인지 근거도", "논문 요약해 줘, 몇 쪽인지 근거도",
                      )
        self.assertEqual(a.grounding, "high")
        self.assertTrue(r.analyze("x", "x", images=True).images)

    def test_tokens_and_sensitivity(self):
        self.assertGreater(r.estimate_tokens("가나다라"), r.estimate_tokens("abcd"))
        self.assertTrue(r.sensitive("주민번호 900101-1234567"))
        self.assertTrue(r.sensitive("token: ghp_abcdefghijklmnopqrstuvwxyz123456"))
        self.assertTrue(r.sensitive("메일 kim@postech.ac.kr로"))
        self.assertFalse(r.sensitive("오늘 회의는 3시"))


class ConstraintTests(unittest.TestCase):
    def test_images_need_a_vision_model(self):
        a = r.analyze("이 사진 설명해 줘", "이 사진 설명해 줘", images=True)
        out = r.route(a, "economy", LOCAL, CLOUD, {}, {}, None)
        self.assertEqual((out.provider, out.reason_code), ("cloud", "no_vision"))
        vision = r.Candidate("local", "llava:7b", context_length=4096, vision=True)
        self.assertEqual(r.route(a, "economy", vision, CLOUD, {}, {}, None).provider, "local")

    def test_context_window(self):
        a = r.analyze("가" * 9000 + " 요약해 줘", "요약해 줘")
        out = r.route(a, "economy", LOCAL, CLOUD, {}, {}, None)
        self.assertEqual((out.provider, out.reason_code), ("cloud", "context"))
        out = r.route(a, "local_only", LOCAL, CLOUD, {}, {}, None)
        self.assertEqual(out.provider, "none")
        self.assertIn("문맥", out.reason)

    def test_memory(self):
        a = r.analyze("요약해 줘", "요약해 줘")
        heavy = r.Candidate("local", "big:70b", context_length=8192, memory_ok=False)
        out = r.route(a, "economy", heavy, CLOUD, {}, {}, None)
        self.assertEqual((out.provider, out.reason_code), ("cloud", "memory"))

    def test_side_effects_go_to_cloud(self):
        a = r.analyze("x", "x", purpose="agent_step")
        self.assertEqual(r.route(a, "economy", LOCAL, CLOUD, {}, {}, None).reason_code, "critical")

    def test_measured_success_rate(self):
        a = r.analyze("이 글을 요약해 줘", "이 글을 요약해 줘")
        low = {"qwen2.5:7b": {"summarization": {"n": 40, "ok": 20}}}
        out = r.route(a, "balanced", LOCAL, CLOUD, {}, low, None)
        self.assertEqual((out.provider, out.stage), ("cloud", "measured"))
        high = {"qwen2.5:7b": {"summarization": {"n": 40, "ok": 39}}}
        out = r.route(a, "quality", LOCAL, CLOUD, {}, high, None)
        self.assertEqual(out.provider, "cloud")  # Quality 정책은 이 작업(요약)을 로컬 대상으로 두지 않는다
        out = r.route(r.analyze("긍정인지 부정인지 분류해 줘", "긍정인지 부정인지 분류해 줘"), "quality", LOCAL, CLOUD, {},
                      {"qwen2.5:7b": {"classification": {"n": 40, "ok": 39}}}, None)
        self.assertEqual((out.provider, out.stage), ("local", "measured"))
        few = {"qwen2.5:7b": {"summarization": {"n": 3, "ok": 0}}}  # 표본이 적으면 믿지 않는다
        self.assertEqual(r.route(a, "balanced", LOCAL, CLOUD, {}, few, None).stage, "default")

    def test_stats_are_recorded_without_content(self):
        with isolated_app_dir():
            r.record_outcome("local:qwen2.5:7b", "summarization", True)
            r.record_outcome("local:qwen2.5:7b", "summarization", False, source="feedback")
            rate, n = r.success_rate(r.load_stats(), "local:qwen2.5:7b", "summarization")
            self.assertEqual((rate, n), (0.5, 2))
            self.assertEqual(r.load_stats()["local:qwen2.5:7b"]["summarization"]["sources"], {"gate": 1, "feedback": 1})

    def test_reason_has_no_prompt_text(self):
        secret = "내 비밀 프로젝트 코드네임 파랑새"
        a = r.analyze(secret + " 요약해 줘", secret + " 요약해 줘")
        out = r.route(a, "balanced", LOCAL, CLOUD, {}, {}, None)
        self.assertNotIn("파랑새", out.reason)


if __name__ == "__main__":
    unittest.main()
