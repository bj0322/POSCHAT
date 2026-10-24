# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""작업별 답변 검증(1.17 QualityGate): 일반·JSON·에이전트 단계·브라우저·논문·코드·Lab."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import connectors  # noqa: E402
import quality_gate as g  # noqa: E402


class GeneralTests(unittest.TestCase):
    def test_empty_truncated_repetition(self):
        self.assertEqual(g.check("general", "  ").failures, ["empty"])
        r = g.check("general", "답의 앞부분", {"done_reason": "length"})
        self.assertIn("truncated", r.failures)
        self.assertTrue(r.retryable)
        r = g.check("general", "\n".join(["같은 문장을 계속 되풀이합니다."] * 10))
        self.assertIn("repetition", r.failures)
        self.assertTrue(g.check("general", "정상적인 한국어 답변입니다. 요청한 내용을 설명합니다.").ok)

    def test_language(self):
        english = "This answer is written entirely in English although the user asked in Korean, which is a mismatch here."
        self.assertIn("language", g.check("general", english, {"korean": True}).failures)
        self.assertTrue(g.check("general", english, {"korean": False}).ok)
        mixed = "다음 코드를 보세요.\n```python\nprint('hello world, this is a long english line of code here')\n```\n설명은 위와 같습니다."
        self.assertTrue(g.check("general", mixed, {"korean": True}).ok)  # 코드 블록은 언어 판단에서 뺀다

    def test_json_and_agent_step(self):
        self.assertTrue(g.check("json", '{"memory": "답 끝에 — 끝을 붙인다"}').ok)
        self.assertEqual(g.check("json", "기억할 내용은 없습니다").failures, ["json"])
        self.assertTrue(g.check("agent_step", '{"action": "read", "path": "a.py"}').ok)
        self.assertEqual(g.check("agent_step", '{"action": "format_disk"}').failures, ["action"])
        self.assertTrue(g.check("agent_step", '{"action": "read"}', {"allowed_actions": {"read"}}).ok)
        self.assertTrue(g.check("json", "").retryable)

    def test_model_confidence_is_not_trusted(self):
        r = g.check("paper", "저는 99% 확신합니다. 결과는 정확도 97.3%입니다.",
                    {"prompt": connectors.wrap_untrusted("정확도는 91.2%였다.", "논문 PDF 'x'")})
        self.assertFalse(r.ok)  # '확신한다'는 말로 통과하지 않는다: 원문에 없는 수치


class GroundingTests(unittest.TestCase):
    def page(self, text, url="https://x.org/a"):
        return "[현재 요청]\n요약\n" + connectors.wrap_untrusted(f"주소: {url}\n{text}", f"웹페이지 {url}")

    def test_browser_urls_and_quotes(self):
        prompt = self.page("POSTECH은 1986년에 세워진 연구 중심 대학이다. 자세히는 https://postech.ac.kr/about 참고.")
        ok = g.check("browser", '페이지에 따르면 "POSTECH은 1986년에 세워진 연구 중심 대학이다". https://postech.ac.kr/about', {"prompt": prompt})
        self.assertTrue(ok.ok, ok)
        self.assertIn("quote", ok.checks)
        bad = g.check("browser", "자세한 내용은 https://evil.example/phish 에 있습니다.", {"prompt": prompt})
        self.assertIn("url", bad.failures)
        bad = g.check("browser", '페이지는 "POSTECH은 2001년에 서울에 세워졌다고 말한다"고 적었다.', {"prompt": prompt})
        self.assertIn("quote", bad.failures)

    def test_paper_pages_and_numbers(self):
        prompt = "x\n" + connectors.wrap_untrusted("Table 2: BLEU 28.4 on WMT14 En-De, training cost 3.3 days.", "논문 PDF 'Attention' pp. 1-15")
        ok = g.check("paper", "p. 8의 표 2에서 BLEU 28.4를 보고했고 학습에 3.3일이 걸렸습니다.", {"prompt": prompt, "pages": 15})
        self.assertTrue(ok.ok, ok)
        bad = g.check("paper", "p. 22에 따르면 BLEU 41.8입니다.", {"prompt": prompt, "pages": 15})
        self.assertIn("page", bad.failures)
        self.assertIn("number", bad.failures)
        self.assertFalse(bad.retryable)

    def test_lab_numbers_need_a_source_or_a_disclosure(self):
        prompt = "x\n" + connectors.wrap_untrusted("run7 accuracy 0.884 latency 15.2ms\nrun12 accuracy 0.861 latency 12.9ms",
                                                   "Lab 실험 기록 AIMC")
        self.assertTrue(g.check("lab", "Run 7은 정확도 0.884, Run 12는 0.861입니다.", {"prompt": prompt}).ok)
        bad = g.check("lab", "Run 7의 정확도는 0.932, 지연은 9.7ms입니다.", {"prompt": prompt})
        self.assertIn("unsupported_number", bad.failures)
        told = g.check("lab", "정확도 차이는 약 0.023(계산한 추정치)이고 지연은 2.3ms 줄었습니다(추정).", {"prompt": prompt})
        self.assertTrue(told.ok, told)
        self.assertIn("unsupported_number_disclosed", told.checks)


class CodeTests(unittest.TestCase):
    def test_python_and_json_blocks(self):
        self.assertTrue(g.check("code", "```python\ndef f(x):\n    return x + 1\n```").ok)
        self.assertIn("syntax", g.check("code", "```python\ndef f(x)\n    return x +\n```").failures)
        self.assertIn("syntax", g.check("code", '```json\n{"a": 1,}\n```').failures)
        r = g.check("code", "코드 없이 설명만 합니다.")
        self.assertTrue(r.ok)
        self.assertNotIn("syntax", r.checks)  # 확인할 것이 없으면 확인했다고 하지 않는다

    def test_area_mapping(self):
        self.assertEqual(g.area_for("summarization", "agent_step"), "agent_step")
        self.assertEqual(g.area_for("extraction", "memory_extract"), "json")
        self.assertEqual(g.area_for("paper", "chat"), "paper")
        self.assertEqual(g.area_for("data_lab", "chat"), "lab")
        self.assertEqual(g.area_for("general_chat", "chat"), "general")


if __name__ == "__main__":
    unittest.main()
