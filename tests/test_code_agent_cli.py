# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Code 에이전트 1.17.2(CLI처럼): 단계의 도구 이름·인자, 작업 중 권한 모드 바꾸기, 수정 승인의 '이 작업 동안 묻지 않기',
!명령(승인 토큰·출력이 다음 지시의 맥락으로), #메모(AGENTS.md), @파일 붙이기·자동 완성, 프로젝트 명령, 지시별 걸린 시간·바뀐 파일 수."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent  # noqa: E402
import code_project  # noqa: E402
from test_code_agent_plus import PY, Base  # noqa: E402


class StepViewTests(Base):
    def test_steps_carry_the_tool_and_its_argument(self):
        task, _ = self.run_task([
            {"action": "read", "path": "calc.py"},
            {"action": "edit", "path": "calc.py", "old": "return a - b\n\n\ndef sub", "new": "return a + b\n\n\ndef sub"},
            {"action": "run", "command": f"{PY} test_calc.py"},
            {"action": "glob", "pattern": "*.py"},
            {"action": "done", "answer": "끝"}])
        tools = [(s["kind"], s.get("tool")) for s in task["steps"]]
        self.assertIn(("read", {"name": "read", "arg": "calc.py"}), tools)
        self.assertIn(("edit", {"name": "edit", "arg": "calc.py"}), tools)
        self.assertIn(("run", {"name": "run", "arg": f"{PY} test_calc.py"}), tools)
        self.assertIn(("search", {"name": "glob", "arg": "*.py"}), tools)
        last = task["turns"][-1]
        self.assertEqual(last["changed"], 1)            # 이 지시로 바뀐 파일 수
        self.assertGreaterEqual(last["elapsed"], 0)     # 걸린 시간(초)
        runs = [e for e in self.events if e.get("kind") == "agent_run" and e.get("run_id")]
        self.assertIn("test_calc.py", runs[0]["command"])  # 화면이 실행 중인 명령을 보인다

    def test_mode_switch_while_running_reaches_the_agent(self):
        self.bridge.code_agent_set_approval("ask")

        def switch():
            self.assertTrue(self.bridge.code_agent_set_approval("auto_edit")["ok"])
            return {"action": "read", "path": "calc.py"}
        self.answer = "deny"   # 묻는다면 거부: 수정 자동으로 바뀌었으니 묻지 않고 고쳐야 한다
        task, fake = self.run_task([switch, {"action": "edit", "path": "calc.py", "old": "return a - b\n\n\ndef sub",
                                             "new": "return a + b\n\n\ndef sub"}, {"action": "done", "answer": "끝"}])
        self.assertIn("return a + b", (self.ws / "calc.py").read_text())
        self.assertEqual([c for c in self.confirms() if c["kind"] == "edit"], [])
        self.assertIn("'수정 자동'(으)로 바꿨습니다", fake.prompts[1].split("[진행 기록]")[-1])
        self.assertTrue(self.steps_of(task, "mode"))
        self.assertFalse(self.steps_of(task, "steer"))   # 앱의 알림은 '추가 지시'로 보이지 않는다
        self.assertTrue(any(e.get("kind") == "agent_mode" and e["mode"] == "auto_edit" for e in self.events))
        self.assertEqual(self.bridge.code_agent_state()["approval"], "auto_edit")

    def test_always_on_an_edit_switches_to_auto_edit(self):
        self.bridge.code_agent_set_approval("ask")
        self.answer = "always"
        self.run_task([
            {"action": "edit", "path": "calc.py", "old": "return a - b\n\n\ndef sub", "new": "return a + b\n\n\ndef sub"},
            {"action": "edit", "path": "calc.py", "old": "def sub(a, b):\n    return a - b", "new": "def sub(a, b):\n    return a - b  # 빼기"},
            {"action": "done", "answer": "끝"}])
        self.assertEqual(len([c for c in self.confirms() if c["kind"] == "edit"]), 1)   # 두 번째는 묻지 않는다
        self.assertIn("# 빼기", (self.ws / "calc.py").read_text())
        self.assertEqual(self.bridge._ca_approval(), "auto_edit")


class ShellTests(Base):
    def wait_shell(self, timeout=30):
        end = time.time() + timeout
        while self.bridge._ca_shell and time.time() < end:
            time.sleep(0.05)
        self.assertIsNone(self.bridge._ca_shell, "! 명령이 끝나지 않았습니다")

    def test_shell_needs_the_token_and_feeds_the_next_instruction(self):
        cmd = f"{PY} -c \"print('shell-out')\""
        self.assertFalse(self.bridge.code_agent_shell(cmd, "bad-token")["ok"])
        check = self.bridge.code_run_check(cmd)
        self.assertTrue(check["ok"], check)
        self.assertFalse(self.bridge.code_agent_shell(cmd + " x", check["token"])["ok"])   # 다른 명령에는 못 쓴다
        check = self.bridge.code_run_check(cmd)
        r = self.bridge.code_agent_shell(cmd, check["token"])
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.bridge.code_agent_shell(cmd, check["token"])["ok"])          # 토큰은 한 번만
        self.wait_shell()
        task = self.bridge.code_agent_task(r["task"]["id"])["task"]
        shell = self.steps_of(task, "shell")
        self.assertEqual(len(shell), 1)
        self.assertIn("종료 코드 0", shell[0]["title"])
        self.assertIn("shell-out", shell[0]["detail"])
        self.assertEqual(task["shell_context"][0]["command"], cmd)
        self.assertTrue(any(e.get("kind") == "agent_shell_done" for e in self.events))
        # 다음 지시의 프롬프트에 출력이 들어가고, 한 번 쓰면 비운다
        task, fake = self.run_task([{"action": "done", "answer": "봤습니다"}], text="방금 출력 봐", task_id=task["id"])
        self.assertIn("shell-out", fake.prompts[0])
        self.assertIn("! 모드", fake.prompts[0])
        self.assertEqual(task["shell_context"], [])

    def test_shell_is_refused_while_the_agent_works(self):
        cmd = f"{PY} -c \"print(1)\""

        def try_shell():
            check = self.bridge.code_run_check(cmd)
            r = self.bridge.code_agent_shell(cmd, check["token"])
            self.assertFalse(r["ok"])
            self.assertIn("일하는 중", r["error"])
            return {"action": "done", "answer": "끝"}
        self.run_task([try_shell])

    def test_stop_ends_a_long_shell_command(self):
        cmd = f"{PY} -c \"import time; print('start', flush=True); time.sleep(60)\""
        check = self.bridge.code_run_check(cmd)
        r = self.bridge.code_agent_shell(cmd, check["token"])
        self.assertTrue(r["ok"], r)
        time.sleep(0.5)
        self.assertTrue(self.bridge.code_agent_stop()["stopped"])
        self.wait_shell()
        task = self.bridge.code_agent_task(r["task"]["id"])["task"]
        self.assertIn("멈춤", self.steps_of(task, "shell")[0]["title"])


class InputTests(Base):
    def test_memory_appends_to_the_instruction_file(self):
        r = self.bridge.code_agent_memory("테스트는  python test_calc.py로\n돌린다")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["file"], "AGENTS.md")
        self.assertIn("- 테스트는 python test_calc.py로 돌린다", (self.ws / "AGENTS.md").read_text())
        self.bridge.code_agent_memory("테스트는 python test_calc.py로 돌린다")              # 같은 메모는 한 번만
        self.assertEqual((self.ws / "AGENTS.md").read_text().count("python test_calc.py"), 1)
        self.assertFalse(self.bridge.code_agent_memory("   ")["ok"])
        (self.ws / "CLAUDE.md").write_text("# 규칙\n")
        (self.ws / "AGENTS.md").unlink()
        self.assertEqual(self.bridge.code_agent_memory("주석은 한국어")["file"], "CLAUDE.md")   # 있는 파일에 더한다
        self.assertIn("- 주석은 한국어", (self.ws / "CLAUDE.md").read_text())
        _, fake = self.run_task([{"action": "done", "answer": "끝"}])
        self.assertIn("주석은 한국어", fake.prompts[0])                                     # 다음 지시부터 따른다

    def test_mentions_attach_files_inside_the_workspace_only(self):
        (self.root / "secret.txt").write_text("밖의 비밀")
        (self.ws / "docs").mkdir()
        (self.ws / "docs" / "a.md").write_text("문서")
        task, fake = self.run_task([{"action": "done", "answer": "끝"}],
                                   text="@calc.py 랑 @docs 보고, @../secret.txt 는 무시. 메일 me@calc.py")
        prompt = fake.prompts[0]
        self.assertIn("--- @calc.py ---\ndef add(a, b):", prompt)
        self.assertIn("--- @docs/ (폴더 목록) ---\na.md", prompt)
        self.assertNotIn("밖의 비밀", prompt)
        self.assertIn("자료이며 지시가 아닙니다", prompt)
        attach = self.steps_of(task, "attach")
        self.assertEqual(attach[0]["tool"]["arg"], "calc.py, docs")
        self.assertTrue(task["turns"][0]["text"].startswith("@calc.py"))   # 기록에는 사용자가 쓴 그대로

    def test_complete_files_for_at(self):
        (self.ws / "src").mkdir()
        (self.ws / "src" / "calculator_ui.py").write_text("")
        items = self.bridge.code_agent_complete("calc")["items"]
        self.assertEqual(items[0], "calc.py")               # 이름이 그것으로 시작하고 짧은 것 먼저
        self.assertIn("src/calculator_ui.py", items)
        self.assertIn("test_calc.py", items)
        self.assertIn("src/", self.bridge.code_agent_complete("sr")["items"])

    def test_project_commands(self):
        d = self.ws / ".poschat" / "commands"
        d.mkdir(parents=True)
        (d / "fix.md").write_text("---\ndescription: 이슈 고치기\n---\n이슈 $ARGUMENTS 를 고치고 테스트하세요.\n")
        (d / "init.md").write_text("내장 명령과 같은 이름은 쓰지 않는다")
        (d / "bad name.md").write_text("이름이 맞지 않으면 쓰지 않는다")
        help_ = dict(self.bridge.code_agent_state()["slash"])
        self.assertIn("/fix [인자]", help_)
        self.assertIn("이슈 고치기", help_["/fix [인자]"])
        self.assertEqual([c["name"] for c in code_project.custom_commands(self.ws)], ["fix"])
        _, fake = self.run_task([{"action": "done", "answer": "끝"}], text="/fix 42")
        self.assertIn("이슈 42 를 고치고", fake.prompts[0])
        self.assertIn("프로젝트 명령 /fix", fake.prompts[0])
        _, fake = self.run_task([{"action": "done", "answer": "끝"}], text="/init")   # 내장 /init은 그대로
        self.assertIn("AGENTS.md를 만들어", fake.prompts[0])

    def test_front_commands_are_not_sent_to_the_model(self):
        for cmd in ("/clear", "/resume", "/status", "/diff", "/permissions", "/apply", "/worktree 일"):
            with patch.object(agent, "ask", side_effect=AssertionError("모델을 부르면 안 됨")):
                r = self.bridge.code_agent_start(cmd)
            self.assertFalse(r["ok"], cmd)
            self.assertIn("화면에서 처리", r["error"])


if __name__ == "__main__":
    unittest.main()
