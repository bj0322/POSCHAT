# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Code 에이전트(1.16): 작업 세션, 계획, 자동 수정과 되돌리기, 명령 승인·스트리밍·멈춤, 이어서 지시하기.

모델 대신 정해 둔 JSON 단계를 차례로 돌려주는 가짜 ask를 쓴다.
"""
import json
import os
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import agent  # noqa: E402
import code_agent  # noqa: E402
import main  # noqa: E402
from support import isolated_app_dir, preserved_hooks  # noqa: E402

PY = f'"{sys.executable}"'


class FakeModel:
    """단계 목록을 차례로 답한다. 받은 프롬프트를 남긴다."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.prompts = []

    def __call__(self, api_key, prompt, **kwargs):
        self.prompts.append(prompt)
        if not self.steps:
            return json.dumps({"action": "done", "answer": "끝"})
        step = self.steps.pop(0)
        if callable(step):
            step = step()
        return json.dumps(step, ensure_ascii=False)


class CodeAgentTests(unittest.TestCase):
    def setUp(self):
        self.hooks = preserved_hooks()
        self.hooks.__enter__()
        self.addCleanup(self.hooks.__exit__, None, None, None)
        self.iso = isolated_app_dir()
        self.root = self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        self.bridge = main.Bridge()
        self.bridge._window = object()
        self.events = []
        self.answer = "allow"
        self.bridge._push = self.push
        self.addCleanup(self.bridge._code_shutdown)
        self.addCleanup(self.bridge._mcp.shutdown)
        self.addCleanup(self.bridge._events.stop)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        (self.ws / "test_calc.py").write_text("from calc import add\nassert add(2, 3) == 5, 'add 틀림'\nprint('ok')\n")
        self.bridge._config["workspace"] = str(self.ws)
        self.bridge._config["api_key"] = "test-key"

    def push(self, ev):
        self.events.append(ev)
        if ev.get("type") == "confirm":
            self.bridge.resolve_confirm(ev["id"], self.answer)

    def run_task(self, steps, text="add 고치기", task_id="", timeout=60):
        fake = FakeModel(steps)
        with patch.object(agent, "ask", fake):
            r = self.bridge.code_agent_start(text, task_id)
            self.assertTrue(r["ok"], r)
            end = time.time() + timeout
            while self.bridge._ca_running and time.time() < end:
                time.sleep(0.05)
        self.assertIsNone(self.bridge._ca_running, "작업이 끝나지 않았습니다")
        return self.bridge.code_agent_task(r["task"]["id"])["task"], fake

    def fix_steps(self):
        return [
            {"action": "plan", "steps": ["calc.py 읽기", "add 고치기", "테스트 실행"]},
            {"action": "read", "path": "calc.py"},
            {"action": "edit", "path": "calc.py", "old": "return a - b", "new": "return a + b", "reason": "덧셈 버그"},
            {"action": "plan", "steps": ["calc.py 읽기", "add 고치기", "테스트 실행"], "done": [0, 1]},
            {"action": "run", "command": f"{PY} test_calc.py"},
            {"action": "done", "answer": "calc.py의 add를 고쳤고 테스트가 통과했습니다."},
        ]

    def test_task_plans_edits_runs_and_records(self):
        task, fake = self.run_task(self.fix_steps())
        self.assertEqual(task["status"], "done")
        self.assertIn("return a + b", (self.ws / "calc.py").read_text())
        self.assertEqual([t["role"] for t in task["turns"]], ["user", "assistant"])
        self.assertIn("테스트가 통과", task["turns"][-1]["text"])
        self.assertEqual([p["done"] for p in task["plan"]], [True, True, False])
        kinds = [s["kind"] for s in task["steps"]]
        for k in ("plan", "read", "edit", "run"):
            self.assertIn(k, kinds)
        run = next(s for s in task["steps"] if s["kind"] == "run")
        self.assertIn("종료 코드 0", run["title"])
        self.assertIn("ok", run["detail"])
        ch = task["changes"]["calc.py"]
        self.assertFalse(ch["created"])
        self.assertTrue(ch["backup"])
        self.assertIn("plan", fake.prompts[0])  # 계획 단계와 코딩 지침이 프롬프트에 있다
        self.assertIn("코딩 에이전트 지침", fake.prompts[0])
        confirms = [e for e in self.events if e.get("type") == "confirm"]
        self.assertEqual([c["kind"] for c in confirms], ["run"])  # 수정은 자동, 명령만 물었다
        self.assertFalse(confirms[0]["allow_session"])
        kinds = {e.get("kind") for e in self.events if e.get("type") == "code"}
        self.assertTrue({"agent_task", "agent_step", "agent_plan", "agent_change", "agent_done"} <= kinds)
        self.assertIn("run_output", kinds)  # 명령 출력이 실시간으로 흐른다
        # 차이와 되돌리기
        d = self.bridge.code_agent_diff(task["id"], "calc.py")
        self.assertIn("-    return a - b", d["diff"])
        r = self.bridge.code_agent_revert(task["id"])
        self.assertEqual(r["reverted"], ["calc.py"])
        self.assertIn("return a - b", (self.ws / "calc.py").read_text())

    def test_new_file_revert_deletes_and_user_changes_are_kept(self):
        task, _ = self.run_task([
            {"action": "write", "path": "pkg/new.py", "content": "X = 1\n"},
            {"action": "edit", "path": "calc.py", "old": "a - b", "new": "a + b"},
            {"action": "done", "answer": "됨"},
        ])
        self.assertTrue(task["changes"]["pkg/new.py"]["created"])
        (self.ws / "calc.py").write_text("def add(a, b):\n    return b + a  # 사용자가 고침\n")
        r = self.bridge.code_agent_revert(task["id"])
        self.assertEqual(r["reverted"], ["pkg/new.py"])
        self.assertEqual([s["path"] for s in r["skipped"]], ["calc.py"])
        self.assertFalse((self.ws / "pkg" / "new.py").exists())
        self.assertIn("사용자가 고침", (self.ws / "calc.py").read_text())

    def test_denied_command_is_not_run(self):
        self.answer = "deny"
        task, _ = self.run_task([
            {"action": "run", "command": f"{PY} -c \"open('ran.txt','w').write('x')\""},
            {"action": "done", "answer": "거부되어 실행하지 않았습니다."},
        ])
        self.assertFalse((self.ws / "ran.txt").exists())
        self.assertIn("denied", [s["kind"] for s in task["steps"]])

    def test_ask_mode_asks_before_edits(self):
        self.bridge.code_agent_set_approval("ask")
        self.answer = "deny"
        task, _ = self.run_task([
            {"action": "edit", "path": "calc.py", "old": "a - b", "new": "a + b"},
            {"action": "done", "answer": "거부됨"},
        ])
        self.assertIn("a - b", (self.ws / "calc.py").read_text())
        self.assertIn("edit", [e["kind"] for e in self.events if e.get("type") == "confirm"])
        self.assertEqual(task["changes"], {})
        self.assertFalse(self.bridge.code_agent_set_approval("weird")["ok"])

    def test_file_changed_after_read_is_not_overwritten(self):
        def change_then_edit():
            (self.ws / "calc.py").write_text("def add(a, b):\n    return a - b  # 밖에서 바뀜\n")
            return {"action": "write", "path": "calc.py", "content": "def add(a, b):\n    return a + b\n"}

        # write는 쓰기 직전에 다시 읽으므로 바뀐 내용이 old가 된다 — 그 사이에 또 바뀌는 경우를 흉내 낸다
        orig = code_agent.CodeAgentApi._ca_read
        calls = {"n": 0}

        def flaky_read(p):
            calls["n"] += 1
            text, enc = orig(p)
            return text + ("# 또 바뀜\n" if calls["n"] == 1 else ""), enc

        with patch.object(code_agent.CodeAgentApi, "_ca_read", staticmethod(flaky_read)):
            task, _ = self.run_task([change_then_edit, {"action": "done", "answer": "x"}])
        self.assertIn("밖에서 바뀜", (self.ws / "calc.py").read_text())
        self.assertEqual(task["changes"], {})

    def test_stop_kills_running_command(self):
        def stop_soon():
            import threading
            threading.Timer(1.0, self.bridge.code_agent_stop).start()
            return {"action": "run", "command": f"{PY} -c \"import time; time.sleep(30)\""}

        start = time.time()
        task, _ = self.run_task([stop_soon, {"action": "done", "answer": "x"}])
        self.assertLess(time.time() - start, 20)
        self.assertEqual(task["status"], "stopped")
        self.assertEqual(self.bridge._code_runner().running(), [])

    def test_follow_up_continues_the_same_task(self):
        task, _ = self.run_task(self.fix_steps())
        task2, fake = self.run_task([{"action": "done", "answer": "이전 작업을 이어서 확인했습니다."}],
                                    text="이제 뺄셈 함수도 추가해 줘", task_id=task["id"])
        self.assertEqual(task2["id"], task["id"])
        self.assertEqual(len(task2["turns"]), 4)
        self.assertIn("add 고치기", fake.prompts[0])  # 이전 지시가 대화 기록으로 들어간다
        listed = self.bridge.code_agent_state()["tasks"]
        self.assertEqual([t["id"] for t in listed], [task["id"]])
        self.assertTrue(self.bridge.code_agent_delete(task["id"])["ok"])
        self.assertEqual(self.bridge.code_agent_state()["tasks"], [])

    def test_secrets_are_not_passed_to_commands(self):
        with patch.dict(os.environ, {"SERVICE_TOKEN": "tok-abcdefghijklmnop"}):
            task, _ = self.run_task([
                {"action": "run", "command": f"{PY} -c \"import os; print('T=', os.environ.get('SERVICE_TOKEN'))\""},
                {"action": "done", "answer": "x"},
            ])
        run = next(s for s in task["steps"] if s["kind"] == "run")
        self.assertIn("T= None", run["detail"])

    def test_guards(self):
        self.assertFalse(self.bridge.code_agent_start("", "")["ok"])
        self.assertFalse(self.bridge.code_agent_task("../../etc")["ok"])
        self.bridge._config["workspace"] = ""
        self.assertFalse(self.bridge.code_agent_start("x")["ok"])


if __name__ == "__main__":
    unittest.main()
