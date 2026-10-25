# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""손익분기 실험 도구(tools/breakeven_experiment.py): 가짜 모델(사용량을 알려 줌)로 실행 → 이어 하기 → 분석까지."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import adaptive_engine  # noqa: E402
import adaptive_router  # noqa: E402
import breakeven_experiment as exp  # noqa: E402
import telemetry  # noqa: E402
from support import isolated_app_dir  # noqa: E402

LIGHT, FRONTIER = "light-m", "frontier-m"


class FakeModels:
    """경량 모델은 어려운 요청(연구 추론)에 상담을 청하고, 프런티어는 정답(reference)을 돌려준다. 사용량은 글자 수로."""

    def __init__(self, cases):
        self.refs = {c["prompt"]: c.get("reference") or "확인했습니다. 한국어로 답합니다." for c in cases}
        self.seen = set()
        self.calls = []

    def answer_for(self, prompt):
        for p, ref in self.refs.items():
            if "[현재 요청]\n" + p in prompt:
                return ref
        return "답입니다."

    def __call__(self, key, prompt, settings=None, timeout=0, usage_out=None, cache_prefix=0):
        self.calls.append((settings.model, cache_prefix))
        if settings.model == LIGHT and adaptive_engine.CONSULT_MARK in prompt and "[상위 모델(프런티어)의 답" not in prompt \
                and ("가설" in prompt or "비판" in prompt or "설계" in prompt):
            text = adaptive_engine.CONSULT_MARK + json.dumps({"question": "핵심 판단을 확인해 주세요"}, ensure_ascii=False)
        elif prompt.startswith(exp.JUDGE_RULE):
            text = '{"score": 4, "why": "작은 빠짐"}'
        elif prompt.startswith("[상담 요청"):
            text = "판단 근거는 이렇습니다."
        else:
            text = self.answer_for(prompt)
        usage = {"input_tokens": len(prompt) // 2, "output_tokens": max(1, len(text) // 2)}
        if cache_prefix:
            head = prompt[:cache_prefix]
            if head in self.seen:
                usage["cache_read_input_tokens"] = cache_prefix // 2
            else:
                usage["cache_creation_input_tokens"] = cache_prefix // 2
                self.seen.add(head)
        usage_out.update(usage)
        return text


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        iso = isolated_app_dir()
        iso.__enter__()
        self.addCleanup(iso.__exit__, None, None, None)
        self.addCleanup(setattr, telemetry, "enabled", telemetry.enabled)
        self.addCleanup(setattr, adaptive_router, "record_outcome", adaptive_router.record_outcome)
        self.tmp = Path(tempfile.mkdtemp())
        self.cases = exp.bench.load()["cases"]
        self.fake = FakeModels(self.cases)

    def run_exp(self, *extra, budget=10000):
        argv = ["run", "--light", LIGHT, "--frontier", FRONTIER, "--split", "all", "--categories", "paper,general",
                "--limit", "12", "--budget-calls", str(budget), "--yes", "--out", str(self.tmp / "e.jsonl"), *extra]
        parsed = self.parse(argv)
        return exp.run(parsed, ask=self.fake, key="k")

    def parse(self, argv):
        with patch.object(exp, "run", lambda a, **k: a), patch.object(exp, "analyze", lambda *a, **k: None):
            return exp.main(argv)

    def rows(self):
        return [json.loads(x) for x in (self.tmp / "e.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_run_records_usage_paths_and_resumes(self):
        self.assertEqual(self.run_exp("--contexts", "0,3000", "--cache", "off,on", "--judge"), 0)
        rows = self.rows()
        paths = {r["path"] for r in rows}
        self.assertEqual(paths, {"frontier", "light", "consult"})
        self.assertTrue(all(t.get("usage") for r in rows for t in r["attempts"]))
        consulted = [r for r in rows if r.get("consulted")]
        self.assertTrue(consulted)                                       # 어려운 요청에서 경량 모델이 상담했다
        self.assertTrue(any(t.get("consult") for r in consulted for t in r["attempts"]))
        cached = [r for r in consulted if r["cache"]]
        self.assertTrue(any((t["usage"] or {}).get("cache_read_input_tokens") for r in cached for t in r["attempts"]))
        self.assertGreater(max(r["T"] for r in rows), 2500)               # 덧붙인 대화로 요청이 길어졌다
        self.assertTrue(all(r["judge"]["score"] for r in rows if r["path"] != "frontier" and r.get("text")))
        n, calls = len(rows), len(self.fake.calls)
        self.run_exp("--contexts", "0,3000", "--cache", "off,on", "--judge")   # 이어 하기: 끝난 칸은 건너뛴다
        self.assertEqual(len(self.rows()), n)
        self.assertEqual(len(self.fake.calls), calls)
        self.assertFalse(telemetry.enabled)                              # 앱의 기록에 섞지 않았다

    def test_budget_stops_and_continues(self):
        self.run_exp(budget=5)
        first = len(self.rows())
        self.assertLessEqual(len(self.fake.calls), 5)
        self.run_exp(budget=10000)
        self.assertGreater(len(self.rows()), first)

    def test_analyze_fits_profile_and_compares_policies(self):
        self.run_exp("--contexts", "0,6000", "--cache", "off,on")
        rep = exp.analyze(self.rows(), exp.parse_price("1,5,0.1,1.25"), exp.parse_price("5,25,0.5,6.25"))
        g = rep["fit"]["*"]
        self.assertGreater(g["O"], 0)
        self.assertGreater(g["consult_rate"], 0)
        self.assertGreater(g["C"], 0)
        for cache in ("cache_off", "cache_on"):
            res = rep["policies"][cache]["by_split"]["all"]
            self.assertEqual(res["frontier"]["cost_vs_frontier"], 1.0)
            self.assertLessEqual(res["oracle"]["cost"], res["frontier"]["cost"] + 1e-12)   # 하한
            self.assertGreaterEqual(res["oracle"]["quality"], res["frontier"]["quality"] - 0.02 - 1e-9)
            for p in exp.POLICIES:
                self.assertEqual(res[p]["units"], res["frontier"]["units"])
        self.assertIn("consult", rep["calibration"])
        exp.print_report(rep)

    def test_cost_counts_cache_separately_and_escalation(self):
        pl, pf = exp.parse_price("1,5,0.1,1.25"), exp.parse_price("5,25")
        t = {"provider": "light", "usage": {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 1_000_000}}
        self.assertAlmostEqual(exp.attempt_cost(t, pl, pf), 0.1)          # 전부 캐시 읽기
        f = {"path": "frontier", "score": 1.0, "attempts": [{"provider": "frontier", "usage": {"input_tokens": 1_000_000}}]}
        bad = {"path": "light", "score": 0.0, "gate_ok": False, "text": "x",
               "attempts": [{"provider": "light", "usage": {"input_tokens": 1_000_000}}]}
        cost, q, ok = exp.outcome({"frontier": f, "light": bad}, "light", pl, pf)
        self.assertAlmostEqual(cost, 1 + 5)                               # 경량 + 승격된 프런티어
        self.assertEqual((q, ok), (1.0, True))
        with self.assertRaises(ValueError):
            exp.parse_price("1")

    def test_no_key_or_consent_refuses(self):
        parsed = self.parse(["run", "--light", LIGHT, "--frontier", FRONTIER, "--out", str(self.tmp / "x.jsonl")])
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}), patch.object(exp, "_config_key", lambda m: ""):
            self.assertEqual(exp.run(parsed), 2)
        self.assertEqual(exp.run(parsed, ask=self.fake, key="k"), 2)     # --yes·상한 없음
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
