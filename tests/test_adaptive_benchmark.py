# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive AI 벤치마크(1.17): 데이터셋 형식·분량·정답의 자기 일관성, 오프라인 라우팅 평가, A~E 실행기(가짜 모델), 예산 중단·동의."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import adaptive_benchmark as bench  # noqa: E402
import adaptive_benchmark_data as data_mod  # noqa: E402
import adaptive_router  # noqa: E402

MINIMUM = {"general": 40, "browser": 30, "paper": 40, "code": 40, "lab": 30, "agent": 20}


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = bench.load()
        cls.cases = cls.data["cases"]

    def test_file_matches_the_generator(self):
        self.assertEqual(self.data, json.loads(json.dumps(data_mod.build(), ensure_ascii=False)),
                         "python tools/adaptive_benchmark_data.py 로 데이터 파일을 다시 만드세요")

    def test_size_and_mix(self):
        self.assertGreaterEqual(len(self.cases), 200)
        counts = {}
        for c in self.cases:
            counts[c["category"]] = counts.get(c["category"], 0) + 1
        for cat, n in MINIMUM.items():
            self.assertGreaterEqual(counts.get(cat, 0), n, cat)
        korean = sum(1 for c in self.cases if adaptive_router.HANGUL.search(c["prompt"]))
        self.assertGreaterEqual(korean / len(self.cases), 0.9)
        self.assertEqual(len({c["id"] for c in self.cases}), len(self.cases))
        splits = [c["split"] for c in self.cases]
        self.assertLessEqual(abs(splits.count("dev") - splits.count("test")), len(MINIMUM))

    def test_every_case_has_answer_check_difficulty_and_route_label(self):
        for c in self.cases:
            for key in ("prompt", "expect", "reference", "verify", "difficulty", "route_label", "task"):
                self.assertTrue(c.get(key) or key == "reference", (c["id"], key))
            self.assertIn(c["difficulty"], adaptive_router.DIFFICULTIES, c["id"])
            self.assertIn(c["route_label"], ("local_ok", "cloud_needed"), c["id"])
            if (c["expect"].get("number")):
                self.assertIsNotNone(c["tolerance"], c["id"])

    def test_references_pass_their_own_checks(self):
        """정답이 적힌 사례는 정답이 자기 채점 규칙을 통과해야 한다(채점 규칙이 틀리면 벤치마크가 무의미하다)."""
        checked = 0
        for c in self.cases:
            ref = c["reference"]
            if ref.startswith("(") or ref == "..." or "..." in ref:
                continue  # 사람이 평가하는 사례·여러 답이 가능한 사례
            score, failed = bench.score(ref, c)
            self.assertEqual(score, 1.0, (c["id"], failed, ref))
            checked += 1
        self.assertGreater(checked, 120)

    def test_reference_code_passes_its_tests(self):
        for c in self.cases:
            if c.get("test") and c["reference"].startswith("```"):
                ok, why = bench.run_test(c["reference"], c["test"])
                self.assertTrue(ok, (c["id"], why))


class OfflineTests(unittest.TestCase):
    def test_offline_report(self):
        report = bench.offline(bench.load(), "balanced")
        for key in ("A", "B", "C", "D", "F", "G"):
            self.assertIn(key, report["configs"])
        self.assertLess(report["configs"]["G"]["frontier_token_share_est"], report["configs"]["F"]["frontier_token_share_est"])
        d = report["configs"]["D"]
        self.assertEqual(set(d["by_split"]), {"dev", "test"})
        # 회귀 막기: 시험용(test, 규칙을 고칠 때 보지 않은 절반)에서 라우팅 정확도와 '잘못 로컬로 보낸' 비율
        self.assertGreaterEqual(d["by_split"]["test"]["routing_accuracy"], 0.85)
        self.assertLessEqual(d["by_split"]["test"]["wrong_local_ratio"], 0.03)
        self.assertEqual(report["configs"]["B"]["local_ratio"], 1.0)

    def test_quality_policy_does_not_go_local_without_measurements(self):
        self.assertEqual(bench.offline(bench.load(), "quality")["configs"]["D"]["local_ratio"], 0.0)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.data = bench.load()
        pick = lambda cat: sorted(c["id"] for c in self.data["cases"] if c["category"] == cat)[:6]  # noqa: E731
        self.ids = set(pick("general") + pick("lab"))
        self.cases = {c["id"]: c for c in self.data["cases"]}

    def fake_local(self, prompt, json_format=False):
        # 일부러 틀린 로컬 답: 한국어 요청에 영어로, 사실도 없음(QualityGate의 언어 검사에 걸려 승격되는지 본다)
        return ("This is an English answer without any of the requested facts, written to fail the language check.", 5)

    def fake_cloud(self, prompt):
        cid = next(i for i in self.ids if self.cases[i]["prompt"] in prompt)
        return (self.cases[cid]["reference"], 7, 30.0)

    def test_all_configs_run_with_fake_models(self):
        runner = bench.Runner(self.fake_local, self.fake_cloud, budget_calls=1000)
        report = runner.run(self.data, ["A", "B", "C", "D", "E"], repeats=2, cases=self.ids)
        a, b, e = report["configs"]["A"], report["configs"]["B"], report["configs"]["E"]
        self.assertEqual(a["status"], "완료")
        self.assertEqual(a["local_ratio"], 0.0)
        self.assertEqual(b["local_ratio"], 1.0)
        self.assertGreater(a["success"], b["success"])          # 틀린 로컬 답은 성공률을 떨어뜨린다
        self.assertGreater(e["success"], report["configs"]["D"]["success"] - 1e-9)  # 검증·승격이 잡아낸다
        self.assertGreater(e["escalation_ratio"], 0)
        self.assertEqual(a["success_std"], 0.0)                  # 같은 답이면 흔들림 없음(반복 2번)
        self.assertIsNotNone(a["credits_est"])
        self.assertIn("lab", a["by_category"])

    def test_tiered_configs_run_the_real_engine(self):
        light_calls = []

        def fake_light(prompt):
            light_calls.append(prompt)
            cid = next(i for i in self.ids if self.cases[i]["prompt"] in prompt)
            return (self.cases[cid]["reference"], 3, None)  # 경량 모델의 크레딧 단가는 근거가 없어 None
        runner = bench.Runner(self.fake_local, self.fake_cloud, budget_calls=1000, light=fake_light, light_model="light")
        report = runner.run(self.data, ["F", "G"], cases=self.ids)
        f, g = report["configs"]["F"], report["configs"]["G"]
        self.assertEqual((f["status"], g["status"]), ("완료", "완료"))
        self.assertTrue(light_calls)  # 로컬이 실패하면 경량 모델로 먼저 간다(앱의 엔진 그대로)
        self.assertGreater(f["frontier_token_saving_est"], 0)
        self.assertGreater(f["success"], 0.5)
        self.assertIn("light_ratio", g)
        none = bench.Runner(self.fake_local, self.fake_cloud, budget_calls=10).run(self.data, ["F"], cases=self.ids)
        self.assertEqual(none["configs"]["F"]["status"], "미실행")

    def test_budget_stops_cloud_spending(self):
        runner = bench.Runner(self.fake_local, self.fake_cloud, budget_calls=3)
        report = runner.run(self.data, ["A", "E"], cases=self.ids)
        self.assertEqual(report["cloud_calls"], 3)
        self.assertEqual(report["configs"]["A"]["status"], "중단")
        self.assertEqual(report["configs"]["E"]["status"], "미실행")
        self.assertIn("상한", report["stopped"])

    def test_cli_refuses_cloud_runs_without_consent(self):
        self.assertEqual(bench.main(["--run", "--configs", "A", "--local-model", "x"]), 2)
        self.assertEqual(bench.main(["--run", "--configs", "A", "--yes", "--local-model", "x"]), 2)  # 상한이 없으면 안 된다


if __name__ == "__main__":
    unittest.main()
