# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Code 에이전트 1.17.1(Claude Code·Codex처럼): 권한 모드, '다시 묻지 않기' 규칙, 줄 번호 read·glob·multi_edit·백그라운드 명령·note,
AGENTS.md·프로젝트 정보, 슬래시 명령, 작업 중 지시, 마지막 지시 되돌리기, 대화 줄이기, 격리 작업 공간(git worktree)."""
import json
import os
import shutil
import subprocess
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
import code_project  # noqa: E402
import main  # noqa: E402
from support import isolated_app_dir, preserved_hooks  # noqa: E402
from test_code_agent import FakeModel  # noqa: E402

PY = f'"{sys.executable}"'
HAVE_GIT = shutil.which("git") is not None
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}


class Base(unittest.TestCase):
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
        (self.ws / "calc.py").write_text("def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n")
        (self.ws / "test_calc.py").write_text("from calc import add\nassert add(2, 3) == 5, 'add 틀림'\nprint('ok')\n")
        self.bridge._config["workspace"] = str(self.ws)
        self.bridge._config["api_key"] = "test-key"

    def push(self, ev):
        self.events.append(ev)
        if ev.get("type") == "confirm":
            self.bridge.resolve_confirm(ev["id"], self.answer)

    def confirms(self):
        return [e for e in self.events if e.get("type") == "confirm"]

    def run_task(self, steps, text="일하기", task_id="", options=None, timeout=60):
        fake = FakeModel(steps)
        with patch.object(agent, "ask", fake):
            r = self.bridge.code_agent_start(text, task_id, options)
            self.assertTrue(r["ok"], r)
            end = time.time() + timeout
            while self.bridge._ca_running and time.time() < end:
                time.sleep(0.05)
        self.assertIsNone(self.bridge._ca_running, "작업이 끝나지 않았습니다")
        return self.bridge.code_agent_task(r["task"]["id"])["task"], fake

    def steps_of(self, task, kind):
        return [s for s in task["steps"] if s["kind"] == kind]


class ModeTests(Base):
    def test_plan_mode_reads_but_never_edits_or_runs(self):
        task, fake = self.run_task([
            {"action": "read", "path": "calc.py"},
            {"action": "edit", "path": "calc.py", "old": "return a - b", "new": "return a + b"},
            {"action": "run", "command": f"{PY} test_calc.py"},
            {"action": "done", "answer": "계획: calc.py의 add를 a + b로 고치고 test_calc.py로 확인"},
        ], options={"mode": "plan"})
        self.assertIn("return a - b", (self.ws / "calc.py").read_text())
        self.assertEqual(self.confirms(), [])
        self.assertIn("[권한: 계획 모드]", fake.prompts[0])
        self.assertIn("계획 모드라", fake.prompts[2])           # 막혔다는 관찰이 모델에 간다
        last = task["turns"][-1]
        self.assertTrue(last["plan_proposal"])
        self.assertEqual(task["turns"][0]["mode"], "plan")
        # '이 계획으로 진행': 같은 작업에 수정 자동으로 이어서
        task, _ = self.run_task([
            {"action": "edit", "path": "calc.py", "old": "return a - b\n\n\ndef sub", "new": "return a + b\n\n\ndef sub"},
            {"action": "done", "answer": "고쳤습니다"},
        ], text="위 계획대로 진행하세요.", task_id=task["id"], options={"mode": "auto_edit"})
        self.assertIn("return a + b", (self.ws / "calc.py").read_text())

    def test_full_auto_runs_commands_but_asks_for_dangerous_ones(self):
        self.answer = "deny"
        task, _ = self.run_task([
            {"action": "run", "command": f"{PY} test_calc.py"},
            {"action": "run", "command": "git push origin main"},
            {"action": "done", "answer": "끝"},
        ], options={"mode": "full_auto"})
        runs = self.steps_of(task, "run")
        self.assertTrue(runs and "자동 허용" in runs[0]["title"])
        self.assertEqual(len(self.confirms()), 1)                 # 네트워크(git push)만 물었다
        self.assertIn("git push", self.confirms()[0]["detail"])
        self.assertTrue(self.steps_of(task, "denied"))

    def test_remember_rule_skips_the_next_confirm_but_not_chained_commands(self):
        self.answer = "remember"
        cmd = f"{PY} test_calc.py"
        task, _ = self.run_task([{"action": "run", "command": cmd}, {"action": "done", "answer": "끝"}])
        prefix = self.confirms()[0]["remember"]
        self.assertTrue(prefix)
        self.assertIn(prefix, self.bridge.code_agent_rules()["rules"])
        self.assertTrue(self.steps_of(task, "rule"))
        self.events.clear()
        self.answer = "deny"
        task, _ = self.run_task([
            {"action": "run", "command": cmd},                           # 규칙으로 묻지 않음
            {"action": "run", "command": cmd + " && echo hi"},           # 연결된 명령은 묻는다
            {"action": "done", "answer": "끝"}])
        self.assertEqual(len(self.confirms()), 1)
        self.assertIn("&& echo hi", self.confirms()[0]["detail"])
        self.assertNotIn("remember", self.confirms()[0])                 # 연결된 명령은 규칙으로 남길 수 없다
        self.bridge.code_agent_rule_delete(prefix)
        self.assertEqual(self.bridge.code_agent_rules()["rules"], [])


class ToolTests(Base):
    def test_read_numbers_lines_and_pages(self):
        (self.ws / "big.py").write_text("".join(f"line{i}\n" for i in range(1, 51)))
        task, fake = self.run_task([
            {"action": "read", "path": "big.py", "offset": 10, "limit": 3},
            {"action": "glob", "pattern": "**/*.py"},
            {"action": "done", "answer": "끝"}])
        obs = fake.prompts[1]
        self.assertIn("    10\tline10", obs)
        self.assertIn("    12\tline12", obs)
        self.assertNotIn("line13\n", obs.split("big.py")[-1].split("glob")[0])
        self.assertIn("offset=13", obs)
        self.assertIn("test_calc.py", fake.prompts[2].split("[진행 기록]")[-1])

    def test_multi_edit_is_all_or_nothing_and_replace_all(self):
        task, fake = self.run_task([
            {"action": "multi_edit", "path": "calc.py", "edits": [{"old": "def add", "new": "def plus"}, {"old": "없는 글", "new": "x"}]},
            {"action": "multi_edit", "path": "calc.py", "edits": [{"old": "return a - b", "new": "return a + b"}]},
            {"action": "edit", "path": "calc.py", "old": "a - b", "new": "b - a", "replace_all": True},
            {"action": "multi_edit", "path": "calc.py", "edits": [
                {"old": "def add(a, b):\n    return b - a", "new": "def add(a, b):\n    return a + b"},
                {"old": "def sub", "new": "def minus"}], "reason": "이름", "note": "덧셈을 고치고 이름을 바꿉니다"},
            {"action": "done", "answer": "끝"}])
        text = (self.ws / "calc.py").read_text()
        self.assertIn("def add(a, b):\n    return a + b", text)
        self.assertIn("def minus(a, b):\n    return b - a", text)
        self.assertNotIn("plus", text)                                  # 첫 multi_edit는 하나가 안 맞아 아무것도 안 바꿈
        self.assertIn("아무것도 바꾸지 않았습니다", fake.prompts[1])
        self.assertIn("2번 나옵니다", fake.prompts[2])                     # 같은 글이 두 곳이면 replace_all 없이 거부
        self.assertTrue(any("덧셈을 고치고" in s["title"] for s in self.steps_of(task, "note")))

    def test_background_job_output_and_stop(self):
        (self.ws / "serve.py").write_text("import time\nprint('ready', flush=True)\nwhile True:\n    time.sleep(0.1)\n")
        self.answer = "allow"
        task, fake = self.run_task([
            {"action": "run", "command": f"{PY} serve.py", "background": True},
            {"action": "job_output", "job": 1, "wait": 2},
            {"action": "job_stop", "job": 1},
            {"action": "done", "answer": "끝"}])
        self.assertIn("백그라운드로 시작했습니다: 작업 1번", fake.prompts[1])
        self.assertIn("ready", fake.prompts[2])
        self.assertIn("멈췄습니다", fake.prompts[3])
        self.assertTrue(self.steps_of(task, "job"))

    def test_background_jobs_stop_when_the_task_ends(self):
        (self.ws / "serve.py").write_text("import time\nwhile True:\n    time.sleep(0.1)\n")
        self.run_task([{"action": "run", "command": f"{PY} serve.py", "background": True}, {"action": "done", "answer": "끝"}])
        end = time.time() + 10
        runner = self.bridge._code_runner()
        while runner.running() and time.time() < end:
            time.sleep(0.1)
        self.assertFalse(runner.running())

    def test_project_instructions_and_detected_commands_reach_the_prompt(self):
        (self.ws / "AGENTS.md").write_text("# 지침\n테스트는 python test_calc.py로 돌린다. 들여쓰기는 4칸.\n")
        (self.ws / "package.json").write_text(json.dumps({"scripts": {"test": "jest", "build": "tsc"}}))
        _, fake = self.run_task([{"action": "done", "answer": "끝"}])
        p = fake.prompts[0]
        self.assertIn("[프로젝트 지침 (AGENTS.md)", p)
        self.assertIn("들여쓰기는 4칸", p)
        self.assertIn("test `npm test`", p)
        self.assertIn("build `npm run build`", p)
        st = self.bridge.code_agent_state()
        self.assertEqual(st["project"]["instructions"], ["AGENTS.md"])
        self.assertIn("/review", [x[0] for x in st["slash"]])


class TurnTests(Base):
    def test_steer_while_running_reaches_the_next_step(self):
        def steer():
            r = self.bridge.code_agent_steer("sub 함수는 건드리지 마세요")
            self.assertTrue(r["ok"], r)
            return {"action": "read", "path": "calc.py"}
        task, fake = self.run_task([steer, {"action": "done", "answer": "끝"}])
        self.assertIn("sub 함수는 건드리지 마세요", fake.prompts[1].split("[진행 기록]")[-1])
        self.assertTrue(self.steps_of(task, "steer"))
        self.assertTrue(any(t.get("steer") for t in task["turns"]))
        self.assertFalse(self.bridge.code_agent_steer("또")["ok"])         # 끝난 뒤에는 보낼 곳이 없다

    def test_undo_reverts_only_the_last_instruction(self):
        original = (self.ws / "calc.py").read_text()
        task, _ = self.run_task([
            {"action": "edit", "path": "calc.py", "old": "return a - b\n\n\ndef sub", "new": "return a + b\n\n\ndef sub"},
            {"action": "done", "answer": "1"}])
        after_first = (self.ws / "calc.py").read_text()
        task, _ = self.run_task([
            {"action": "edit", "path": "calc.py", "old": "def sub", "new": "def minus"},
            {"action": "write", "path": "notes.txt", "content": "메모"},
            {"action": "done", "answer": "2"}], text="더", task_id=task["id"])
        self.assertTrue((self.ws / "notes.txt").exists())
        r = self.bridge.code_agent_undo(task["id"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["turn"], 2)
        self.assertEqual((self.ws / "calc.py").read_text(), after_first)
        self.assertFalse((self.ws / "notes.txt").exists())
        r = self.bridge.code_agent_undo(task["id"])
        self.assertEqual((self.ws / "calc.py").read_text(), original)
        self.assertFalse(self.bridge.code_agent_undo(task["id"])["ok"])  # 더 되돌릴 것이 없다
        # 사용자가 그 뒤 고친 파일은 덮어쓰지 않는다
        task, _ = self.run_task([{"action": "edit", "path": "calc.py", "old": "def sub", "new": "def minus"},
                                 {"action": "done", "answer": "3"}], text="또", task_id=task["id"])
        (self.ws / "calc.py").write_text("사용자가 고침\n")
        r = self.bridge.code_agent_undo(task["id"])
        self.assertEqual(r["skipped"][0]["path"], "calc.py")
        self.assertEqual((self.ws / "calc.py").read_text(), "사용자가 고침\n")

    def test_compact_summarizes_past_turns(self):
        task, _ = self.run_task([{"action": "done", "answer": "첫 답"}])
        task, _ = self.run_task([{"action": "done", "answer": "둘째 답"}], text="이어서", task_id=task["id"])
        with patch.object(agent, "ask", lambda key, prompt, **kw: "- 목표: 덧셈 고치기\n- 남은 일: 없음"):
            r = self.bridge.code_agent_compact(task["id"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["summarized"], 4)
        self.assertEqual(len(r["task"]["turns"]), 2)
        self.assertIn("덧셈 고치기", r["task"]["turns"][1]["text"])
        _, fake = self.run_task([{"action": "done", "answer": "셋째"}], text="계속", task_id=task["id"])
        self.assertIn("[지난 작업 요약]", fake.prompts[0])
        self.assertNotIn("첫 답", fake.prompts[0])

    def test_slash_commands(self):
        _, fake = self.run_task([{"action": "done", "answer": "끝"}], text="/init")
        self.assertIn("AGENTS.md를 만들어", fake.prompts[0])
        task, fake = self.run_task([{"action": "done", "answer": "계획"}], text="/plan 로그 추가")
        self.assertEqual(task["turns"][0]["mode"], "plan")
        self.assertIn("[목표]\n로그 추가", fake.prompts[0])
        _, fake = self.run_task([{"action": "done", "answer": "끝"}], text="/test calc")
        self.assertIn("테스트를 찾아 실행", fake.prompts[0])
        for bad in ("/nope", "/undo", "/plan"):
            self.assertFalse(self.bridge.code_agent_start(bad)["ok"], bad)
        r = self.bridge.code_agent_start("/review")                     # Git 저장소가 아니면 리뷰할 변경이 없다
        self.assertFalse(r["ok"])
        self.assertIn("Git 변경", r["error"])


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=dict(os.environ, **GIT_ENV))


@unittest.skipUnless(HAVE_GIT, "git이 없어 건너뜁니다")
class GitTests(Base):
    def setUp(self):
        super().setUp()
        git(self.ws, "init", "-q")
        (self.ws / ".gitignore").write_text("__pycache__/\n")
        git(self.ws, "add", "-A")
        git(self.ws, "commit", "-q", "-m", "처음")
        env = patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)

    def test_review_sends_the_diff_in_plan_mode(self):
        (self.ws / "calc.py").write_text("def add(a, b):\n    return a * b\n")
        task, fake = self.run_task([{"action": "done", "answer": "calc.py:2 — 곱셈은 버그"}], text="/review 보안 위주")
        self.assertEqual(task["turns"][0]["mode"], "plan")
        self.assertIn("+    return a * b", fake.prompts[0])
        self.assertIn("보안 위주", fake.prompts[0])
        self.assertIn("Git: 브랜치", fake.prompts[0])

    def test_isolated_worktree_apply(self):
        task, fake = self.run_task([
            {"action": "edit", "path": "calc.py", "old": "return a - b\n\n\ndef sub", "new": "return a + b\n\n\ndef sub"},
            {"action": "write", "path": "new_mod.py", "content": "X = 1\n"},
            {"action": "run", "command": f"{PY} test_calc.py"},
            {"action": "done", "answer": "끝"}], options={"isolate": True, "mode": "full_auto"})
        wt = Path(task["worktree"])
        self.assertTrue(task["isolated"])
        self.assertIn("return a + b", (wt / "calc.py").read_text())
        self.assertIn("return a - b", (self.ws / "calc.py").read_text())    # 원래 폴더는 그대로
        self.assertFalse((self.ws / "new_mod.py").exists())
        self.assertIn("격리 작업 공간", fake.prompts[0])
        run = self.steps_of(task, "run")[0]
        self.assertIn("종료 코드 0", run["title"])                            # 명령은 worktree에서 돌았다
        d = self.bridge.code_agent_worktree_diff(task["id"])
        self.assertEqual(d["files"], 2)
        r = self.bridge.code_agent_apply(task["id"])
        self.assertTrue(r["ok"], r)
        self.assertIn("return a + b", (self.ws / "calc.py").read_text())
        self.assertEqual((self.ws / "new_mod.py").read_text(), "X = 1\n")
        self.assertFalse(wt.exists())
        self.assertTrue(r["task"]["worktree_removed"])
        self.assertFalse(self.bridge.code_agent_start("더", task["id"])["ok"])  # 정리한 격리 작업은 이어 갈 수 없다

    def test_isolated_worktree_discard_and_conflict(self):
        task, _ = self.run_task([
            {"action": "edit", "path": "calc.py", "old": "return a - b\n\n\ndef sub", "new": "return a + b\n\n\ndef sub"},
            {"action": "done", "answer": "끝"}], options={"isolate": True})
        (self.ws / "calc.py").write_text("def add(a, b):\n    return 0\n")  # 그 사이 원래 폴더의 같은 곳이 바뀜
        r = self.bridge.code_agent_apply(task["id"])
        self.assertFalse(r["ok"])
        self.assertIn("적용하지 않았습니다", r["error"])
        self.assertEqual((self.ws / "calc.py").read_text(), "def add(a, b):\n    return 0\n")
        self.assertIn("브랜치로 남기기", r["error"])
        # 원래 브랜치에 겹치는 커밋이 생긴 경우: 3-way 충돌이 나도 충돌 표시를 남기지 않고 그대로 둔다
        git(self.ws, "commit", "-qam", "사용자 커밋")
        r = self.bridge.code_agent_apply(task["id"])
        self.assertFalse(r["ok"])
        self.assertEqual((self.ws / "calc.py").read_text(), "def add(a, b):\n    return 0\n")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertEqual(status.strip(), "")
        r = self.bridge.code_agent_discard(task["id"])
        self.assertTrue(r["ok"], r)
        self.assertFalse(Path(task["worktree"]).exists())
        branches = subprocess.run(["git", "branch", "--list", "poschat/*"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertEqual(branches.strip(), "")

    def test_keep_branch_commits_the_worktree(self):
        task, _ = self.run_task([
            {"action": "write", "path": "feature.py", "content": "def f():\n    return 1\n"},
            {"action": "done", "answer": "끝"}], options={"isolate": True})
        r = self.bridge.code_agent_keep_branch(task["id"])
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["committed"])
        self.assertFalse(Path(task["worktree"]).exists())
        self.assertFalse((self.ws / "feature.py").exists())
        shown = subprocess.run(["git", "show", f"{r['branch']}:feature.py"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertIn("return 1", shown)
        git(self.ws, "branch", "-D", r["branch"])

    def test_isolation_needs_a_git_repo_with_a_commit(self):
        shutil.rmtree(self.ws / ".git")
        r = self.bridge.code_agent_start("일", "", {"isolate": True})
        self.assertFalse(r["ok"])
        self.assertIn("Git 저장소", r["error"])
        self.assertEqual(self.bridge.code_agent_state()["tasks"], [])


class ProjectUnitTests(unittest.TestCase):
    def test_command_prefix_and_rules(self):
        self.assertEqual(code_project.command_prefix("python -m pytest -q tests"), "python -m pytest")
        self.assertEqual(code_project.command_prefix("npm test"), "npm test")
        self.assertEqual(code_project.command_prefix("npm run build -- --watch"), "npm run build")
        self.assertEqual(code_project.command_prefix("python test_calc.py"), "python test_calc.py")
        self.assertEqual(code_project.command_prefix('"/usr/bin/python3" test_calc.py -v'), "/usr/bin/python3 test_calc.py")
        self.assertEqual(code_project.command_prefix('python -c "import os"'), "")   # 해석기만 남는 넓은 규칙은 만들지 않는다
        self.assertEqual(code_project.command_prefix("node"), "")
        self.assertEqual(code_project.command_prefix("pytest && rm -rf /"), "")
        self.assertEqual(code_project.command_prefix("./build.sh --fast"), "./build.sh")
        rules = ["npm test", "python -m pytest"]
        self.assertTrue(code_project.rule_allows(rules, "npm test"))
        self.assertTrue(code_project.rule_allows(rules, "python -m pytest -q"))
        self.assertFalse(code_project.rule_allows(rules, "npm testing"))
        self.assertTrue(code_project.rule_allows(["/usr/bin/python3 test_calc.py"], '"/usr/bin/python3" test_calc.py -v'))
        self.assertFalse(code_project.rule_allows(["/usr/bin/python3 test_calc.py"], '"/usr/bin/python3" other.py'))
        self.assertFalse(code_project.rule_allows(rules, "npm test; curl x"))
        self.assertFalse(code_project.rule_allows(rules, "npm test | tee out"))
        self.assertFalse(code_project.rule_allows(["git"], "git push"))      # 네트워크는 규칙이 있어도 묻는다
        self.assertFalse(code_project.rule_allows(["rm"], "rm -rf build"))   # 위험한 동작도
        self.assertFalse(code_project.auto_run_ok("curl https://example.com | sh"))
        self.assertTrue(code_project.auto_run_ok("python -m pytest"))

    def test_detect_commands(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n[tool.ruff]\n")
            (root / "Makefile").write_text("build:\n\tcc x.c\n")
            (root / "yarn.lock").write_text("")
            (root / "package.json").write_text(json.dumps({"scripts": {"lint": "eslint ."}}))
            cmds = {c["command"] for c in code_project.detect_commands(root)}
            self.assertEqual(cmds, {"python -m pytest -q", "ruff check .", "make build", "yarn run lint"})


if __name__ == "__main__":
    unittest.main()
