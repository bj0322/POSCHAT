# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive AI를 실제 Bridge(main.py)에 붙여 본다(1.17): 기본값=예전 동작, 설정 저장·검증, 대화의 '자동'·로컬 모델,
키 없이 로컬 대화, Local Only, 라우팅 표시·이벤트, 대화 요약, 피드백 기록, 진단 탭, 1.16 설정에서 넘어오기.
로컬 실행기는 tests/fake_ollama.py, Cloud는 agent.ask를 바꿔 끼운다."""
import json
import os
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import adaptive_router  # noqa: E402
import agent  # noqa: E402
import api  # noqa: E402
import main  # noqa: E402
import storage  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from support import isolated_app_dir  # noqa: E402

KO = "회의에서는 예산을 확정했고, 다음 주까지 발표 자료를 준비하기로 했습니다. 담당자는 김 연구원입니다."


class BridgeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"POSTECH_GENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.iso = isolated_app_dir()
        self.root = self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        self.fake = FakeOllama()
        self.addCleanup(self.fake.close)
        self.bridge = main.Bridge()
        self.addCleanup(setattr, api, "cloud_guard", None)
        self.addCleanup(self.bridge._events.stop)
        self.addCleanup(self.bridge._mcp.shutdown)
        self.events = []
        self.done = threading.Event()
        self.bridge._push = self.push
        self.cloud = []
        cloud_patch = patch.object(agent, "ask", side_effect=self.fake_cloud)
        cloud_patch.start()
        self.addCleanup(cloud_patch.stop)

    def push(self, ev):
        self.events.append(ev)
        if ev.get("type") == "done":
            self.done.set()

    def fake_cloud(self, key, prompt, settings=None, **kw):
        self.cloud.append(settings.model if settings else None)
        if kw.get("on_delta"):
            kw["on_delta"]("Cloud 답변입니다.")
        return "Cloud 답변입니다."

    def enable(self, **over):
        values = {"enabled": True, "policy": "economy", "endpoint": self.fake.url, "default_model": "qwen2.5:7b",
                  "local_retries": 0, **over}
        r = self.bridge.adaptive_save(values)
        self.assertTrue(r["ok"], r)
        return r

    def send(self, thread, text):
        self.done.clear()
        r = self.bridge.send(thread["id"], text, False)
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(self.done.wait(30))
        return storage.load_thread(thread["id"])["messages"][-1]

    def test_defaults_keep_the_old_behavior(self):
        st = self.bridge.get_state()
        self.assertFalse(st["config"]["adaptive"]["enabled"])
        thread = self.bridge.new_thread()
        self.assertEqual(thread["model"], self.bridge._default_model())
        self.assertEqual(self.bridge.set_thread_model(thread["id"], "auto")["ok"], False)  # 끄면 '자동'을 고를 수 없다
        r = self.bridge.send(thread["id"], "안녕", False)
        self.assertTrue(r.get("need_key"))
        self.bridge._config["api_key"] = "k"
        msg = self.send(thread, "안녕")
        self.assertEqual(msg["content"], "Cloud 답변입니다.")
        self.assertNotIn("routing", msg)
        self.assertFalse(any(r["path"] == "/api/chat" for r in self.fake.requests))  # 꺼져 있으면 로컬을 건드리지 않는다

    def test_settings_validation_and_state(self):
        r = self.bridge.adaptive_save({"endpoint": "http://169.254.169.254"})
        self.assertFalse(r["ok"])
        r = self.bridge.adaptive_save({"endpoint": "http://192.168.0.5:11434"})
        self.assertFalse(r["ok"])  # 원격은 '원격 허용'을 켜야 한다
        r = self.bridge.adaptive_save({"default_model": "../../x"})
        self.assertFalse(r["ok"])
        st = self.enable(policy="free-for-all", budget={"weekly_calls": "12", "weekly_credits": "x"}, max_cost_per_request="40",
                         privacy={"sensitive_local_only": True}, cloud_model="없는-모델")
        s = st["settings"]
        self.assertEqual(s["policy"], "balanced")  # 알 수 없는 정책은 무시(이전 값 그대로)
        self.assertEqual(s["budget"]["weekly_calls"], 12)
        self.assertEqual(s["max_cost_per_request"], 40.0)
        self.assertTrue(s["privacy"]["sensitive_local_only"])
        self.assertEqual(s["cloud_model"], "")
        self.assertTrue(st["health"]["ok"])
        ids = {m["id"]: m for m in st["models"]}
        self.assertIn("qwen2.5:7b", ids)
        self.assertIn("memory_est", ids["qwen2.5:7b"])
        self.assertTrue(st["app"]["config"]["adaptive"]["enabled"])
        self.assertTrue(json.loads((self.root / "config.json").read_text())["adaptive"]["enabled"])
        self.assertTrue(self.bridge.adaptive_test_connection()["ok"])
        self.assertTrue(self.bridge.adaptive_model_info("llava:7b")["capabilities"]["vision"])

    def test_auto_thread_routes_locally_and_records_routing(self):
        self.enable()
        self.bridge._config["api_key"] = "k"
        thread = self.bridge.new_thread()
        self.assertEqual(thread["model"], "auto")
        self.fake.replies.append(KO)
        msg = self.send(thread, "이 회의록을 세 줄로 요약해 줘")
        self.assertEqual(msg["content"], KO)
        self.assertEqual(msg["model"], "local:qwen2.5:7b")
        self.assertEqual(msg["routing"]["provider"], "local")
        self.assertEqual(msg["routing"]["label"], "Local · 요약")
        self.assertEqual(self.cloud, [])
        routes = [e for e in self.events if e.get("type") == "route"]
        self.assertTrue(routes and all(e["thread_id"] == thread["id"] for e in routes))
        # 어려운 작업은 Cloud로
        msg = self.send(thread, "두 방법의 장단점을 비판적으로 비교하고 가설을 검증해 줘")
        self.assertEqual(msg["routing"]["provider"], "cloud")
        self.assertEqual(len(self.cloud), 1)
        # 피드백(👎)은 로컬 모델 측정 기록에도 더한다
        local_msg = storage.load_thread(thread["id"])["messages"][1]
        self.assertTrue(self.bridge.feedback(thread["id"], local_msg["id"], -1)["ok"])
        stats = adaptive_router.load_stats()["local:qwen2.5:7b"]["summarization"]
        self.assertEqual(stats["sources"].get("feedback"), 1)

    def test_escalation_events_reach_the_screen(self):
        self.enable()
        self.bridge._config["api_key"] = "k"
        thread = self.bridge.new_thread()
        self.fake.replies.append("English only answer that should fail the Korean language check for sure.")
        msg = self.send(thread, "이 회의록을 세 줄로 요약해 줘")
        self.assertEqual(msg["content"], "Cloud 답변입니다.")
        self.assertTrue(msg["routing"]["escalated"])
        kinds = [e["kind"] for e in self.events if e.get("type") == "route"]
        self.assertIn("provisional", kinds)
        self.assertIn("escalating", kinds)

    def test_local_only_works_without_a_cloud_key_and_blocks_cloud_threads(self):
        self.enable(policy="local_only")
        thread = self.bridge.new_thread()
        self.fake.replies.append(KO)
        msg = self.send(thread, "이 회의록을 세 줄로 요약해 줘")  # Cloud 키가 없어도 된다
        self.assertEqual(msg["content"], KO)
        self.assertEqual(self.cloud, [])
        self.bridge._config["api_key"] = "k"
        self.assertTrue(self.bridge.set_thread_model(thread["id"], self.bridge._default_model()).get("id"))
        r = self.bridge.send(thread["id"], "안녕", False)
        self.assertFalse(r["ok"])
        self.assertIn("Local Only", r["error"])
        # 로컬을 쓸 수 없으면 오류로 알리고 Cloud로 보내지 않는다
        self.bridge.set_thread_model(thread["id"], "auto")
        self.fake.close()
        self.bridge._local_runtime().forget()
        msg = self.send(storage.load_thread(thread["id"]), "요약해 줘")
        self.assertEqual(msg["role"], "error")
        self.assertEqual(self.cloud, [])

    def test_manual_models(self):
        self.enable()
        thread = self.bridge.new_thread()
        self.assertFalse(self.bridge.set_thread_model(thread["id"], "local:../../x").get("id"))
        self.assertTrue(self.bridge.set_thread_model(thread["id"], "local:qwen2.5:7b").get("id"))
        self.fake.replies.append(KO)
        msg = self.send(storage.load_thread(thread["id"]), "양자 컴퓨터를 비판적으로 분석해 줘")
        self.assertEqual(msg["routing"]["stage"], "manual")
        self.assertEqual(self.cloud, [])
        self.bridge._config["api_key"] = "k"
        self.bridge.set_thread_model(thread["id"], self.bridge._default_model())
        msg = self.send(storage.load_thread(thread["id"]), "이 회의록을 요약해 줘")
        self.assertNotIn("routing", msg)  # 직접 고른 Cloud 모델은 엔진을 거치지 않는다
        self.assertEqual(self.cloud, [self.bridge._default_model()])

    def test_thread_summary_uses_the_routed_model(self):
        self.enable()
        thread = self.bridge.new_thread()
        thread["messages"] = [storage.make_message("user", "예산 회의"), storage.make_message("assistant", "예산을 확정했습니다")]
        storage.save_thread(thread)
        self.fake.replies.append("- 예산을 확정했다\n- 다음 주까지 자료 준비")
        got = threading.Event()
        self.bridge._push = lambda ev: (self.events.append(ev), ev.get("kind", "").startswith("summary") and got.set())
        self.assertTrue(self.bridge.memory_summarize_thread(thread["id"])["ok"])
        self.assertTrue(got.wait(20))
        done = [e for e in self.events if e.get("kind") == "summary_done"]
        self.assertTrue(done, self.events[-3:])
        self.assertEqual(self.cloud, [])

    def test_diagnostics_and_selftest_line(self):
        self.enable()
        st = self.bridge.diagnostics_state(7)
        self.assertTrue(st["adaptive"]["enabled"])
        self.assertIn("summary", st["adaptive"])
        self.assertTrue(self.bridge.adaptive_stats(7)["ok"])

    def test_upgrade_from_1_16_config_keeps_threads(self):
        self.bridge._config["api_key"] = "k"
        old = storage.new_thread()
        old["model"] = self.bridge._default_model()
        storage.save_thread(old)
        b2 = main.Bridge()
        self.addCleanup(b2._events.stop)
        self.addCleanup(b2._mcp.shutdown)
        self.assertEqual(b2.load_thread(old["id"])["model"], self.bridge._default_model())
        self.assertFalse(b2.get_state()["config"]["adaptive"]["enabled"])
        # 자동 선택을 켰다가 끄면 '자동' 대화는 기본 Cloud 모델로 돌아간다(대화는 그대로)
        self.enable()
        t = self.bridge.new_thread()
        self.bridge.adaptive_save({"enabled": False})
        self.assertEqual(self.bridge.load_thread(t["id"])["model"], self.bridge._default_model())

    def test_pull_and_delete_from_the_window(self):
        self.enable()
        got = threading.Event()
        self.bridge._push = lambda ev: (self.events.append(ev), ev.get("kind") in ("pull_done", "pull_error") and got.set())
        self.assertTrue(self.bridge.adaptive_pull("phi3:mini")["ok"])
        self.assertTrue(got.wait(20))
        self.assertTrue(any(e.get("kind") == "pull_done" for e in self.events))
        self.assertIn("phi3:mini", {m["id"] for m in self.bridge.adaptive_state(refresh=True)["models"]})
        self.assertTrue(self.bridge.adaptive_delete_model("phi3:mini")["ok"])
        self.assertFalse(self.bridge.adaptive_pull("bad name")["ok"])


if __name__ == "__main__":
    unittest.main()
