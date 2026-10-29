# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.18 원격(SSH) 작업 폴더: 원격 도우미(remote_helper)와 경로 나누기(remote_fs). SSH 없이 같은 도우미를 이 컴퓨터의 하위 프로세스로
띄워(remote_client.LocalHelper) 파일·Git·프로젝트 정보·명령·터미널·Code 에이전트가 'ssh://…' 작업 폴더에서 로컬과 같은 규칙으로
도는지 본다. 실제 SSH 연결(인증·호스트 키·점프 호스트)은 test_ssh.py."""
import ast
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import code_git  # noqa: E402
import code_project  # noqa: E402
import code_runner  # noqa: E402
import code_workspace as cw  # noqa: E402
import remote_client  # noqa: E402
import remote_fs  # noqa: E402
import terminal  # noqa: E402

POSIX = os.name != "nt"
HOST = "student@lab.example:2222"


def wait(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


class BundleTests(unittest.TestCase):
    def test_bundle_is_python36_syntax(self):
        """서버의 python3가 3.6이어도 돌게: 도우미 묶음에 새 문법(:=, 위치 전용 인자 등)이 없다."""
        bundled = set(remote_client.BUNDLE)
        for name in remote_client.BUNDLE:
            src = (remote_client.source_dir() / f"{name}.py").read_text(encoding="utf-8")
            tree = ast.parse(src, filename=name, feature_version=(3, 6))
            for node in tree.body:   # 맨 위 import는 표준 라이브러리(3.6에 있는 것)와 묶음 안의 모듈만
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module] if isinstance(node, ast.ImportFrom) else []
                for m in mods:
                    top = m.split(".")[0]
                    self.assertTrue(top in bundled or top in sys.stdlib_module_names, f"{name}: {m}")
                    self.assertNotIn(top, ("dataclasses", "contextvars", "importlib"), f"{name}: 3.7부터 있는 모듈 {m}")
        import remote_helper
        ast.parse(remote_helper.BOOT, feature_version=(3, 6))

    def test_remote_command_finds_python_with_any_login_shell(self):
        cmd = remote_client.remote_command()
        self.assertTrue(cmd.startswith("exec /bin/sh -c '"))
        self.assertNotIn("\n", cmd)          # tcsh도 한 줄로 받는다
        r = subprocess.run(["/bin/sh", "-c", cmd.replace("exec /bin/sh", "/bin/sh", 1)], input=b"", capture_output=True,
                           timeout=30) if POSIX else None
        if r is not None:   # 빈 입력이면 시작 코드가 끝난다(파이썬은 찾았다)
            self.assertNotIn(b"nopython", r.stdout)

    def test_paths(self):
        p = remote_fs.path_of("ssh://" + HOST + "/home/s/proj")
        self.assertEqual((p.host, p.path), (HOST, "/home/s/proj"))
        self.assertEqual(str(p / "src/a.py"), "ssh://" + HOST + "/home/s/proj/src/a.py")
        self.assertIn(p, (p / "src/a.py").parents)
        self.assertEqual((p / "src/a.py").relative_to(p).as_posix(), "src/a.py")
        self.assertEqual((p / "../../etc").path, "/home/etc")
        self.assertEqual(remote_fs.label(p), HOST + ":/home/s/proj")
        with self.assertRaises(TypeError):
            os.fspath(p)                      # 같은 이름의 로컬 파일을 실수로 건드리지 않는다
        with self.assertRaisesRegex(remote_fs.RemoteError, "SSH 연결이 없습니다"):
            cw.list_dir("ssh://nobody@nowhere/x", "")


@unittest.skipUnless(POSIX, "원격 도우미는 Linux·macOS 서버용")
class RemoteHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = dict(os.environ, HOME=str(self.home), MY_API_TOKEN="tok-secret-123", PLAIN_VALUE="보임",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@example.com")
        self.helper = remote_client.LocalHelper(HOST, env=env)
        self.info = self.helper.start()
        remote_fs.register(HOST, self.helper)
        self.addCleanup(remote_fs.unregister, HOST)
        self.addCleanup(self.helper.close)
        self.ws_path = self.tmp / "proj"
        self.ws_path.mkdir()
        (self.ws_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (self.ws_path / "sub").mkdir()
        (self.ws_path / "sub" / "note.md").write_text("한글 메모 TODO\n", encoding="utf-8")
        self.ws = remote_fs.url(HOST, str(self.ws_path))

    def test_files_follow_the_same_rules_on_the_server(self):
        self.assertEqual(self.info["home"], str(self.home))
        self.assertEqual(cw.root_of(self.ws), remote_fs.RPath(HOST, os.path.realpath(self.ws_path)))
        names = [x["name"] for x in cw.list_dir(self.ws, "")["items"]]
        self.assertEqual(names, ["sub", "calc.py"])
        f = cw.read_file(self.ws, "calc.py")
        self.assertIn("return a - b", f["text"])
        saved = cw.write_file(self.ws, "calc.py", f["text"].replace("-", "+"), f["hash"])
        self.assertIn("return a + b", (self.ws_path / "calc.py").read_text())
        with self.assertRaises(cw.ConflictError) as e:
            cw.write_file(self.ws, "calc.py", "x", f["hash"])      # 연 뒤에 바뀜
        self.assertEqual(e.exception.current_hash, saved["hash"])
        with self.assertRaisesRegex(cw.WorkspaceError, "작업 폴더 밖"):
            cw.read_file(self.ws, "../home/x")
        os.symlink("/etc", self.ws_path / "out")
        with self.assertRaisesRegex(cw.WorkspaceError, "밖을 가리키는 링크"):
            cw.read_file(self.ws, "out/hostname")
        self.assertEqual(cw.create(self.ws, "new/x.txt" if False else "x.txt")["path"], "x.txt")
        self.assertEqual(cw.rename(self.ws, "x.txt", "sub/y.txt")["path"], "sub/y.txt")
        d = cw.delete_to_trash(self.ws, "sub/y.txt", None)        # 원격은 서버의 ~/.cache/poschat/trash로
        self.assertTrue(d["trash"].startswith(str(self.home / ".cache" / "poschat" / "trash")))
        self.assertTrue(Path(d["trash"]).is_file())
        hits = cw.search(self.ws, "todo", "text")["results"]
        self.assertEqual([(h["path"], h["line"]) for h in hits], [("sub/note.md", 1)])
        self.assertEqual([r for r, _ in cw.walk_files(self.ws)], ["calc.py", "sub/note.md"])
        self.assertNotEqual(cw.current_hash(self.ws, "calc.py"), cw.ABSENT)
        self.assertEqual(cw.current_hash(self.ws, "nope.py"), cw.ABSENT)

    def test_rpath_reads_and_writes_on_the_server(self):
        root = cw.path_of(self.ws)
        p = root / "sub" / "note.md"
        self.assertTrue(p.exists() and p.is_file() and not p.is_dir())
        self.assertEqual(p.read_text(encoding="utf-8"), "한글 메모 TODO\n")
        self.assertEqual(p.stat().st_size, len("한글 메모 TODO\n".encode()))
        q = root / "deep" / "x.bin"
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(b"\x00\x01")
        self.assertEqual((self.ws_path / "deep" / "x.bin").read_bytes(), b"\x00\x01")
        self.assertEqual(sorted(x.name for x in (root / "deep").iterdir()), ["x.bin"])
        q.unlink()
        q.unlink(missing_ok=True)
        with self.assertRaises(FileNotFoundError):
            q.unlink()
        self.assertEqual(root.resolve(), root)

    def test_git_and_project_info_run_on_the_server(self):
        git(self.ws_path, "init", "-q")
        git(self.ws_path, "add", "-A")
        git(self.ws_path, "commit", "-qm", "init")
        (self.ws_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
        (self.ws_path / "AGENTS.md").write_text("# 지침\n- 테스트는 pytest\n")
        st = code_git.status(self.ws)
        self.assertTrue(st["repo"])
        self.assertEqual({f["path"] for f in st["files"]}, {"calc.py", "AGENTS.md"})
        self.assertIn("+    return a + b", code_git.diff(self.ws, "calc.py")["diff"])
        code_git.stage(self.ws, ["calc.py"])
        self.assertIn("fix", code_git.commit(self.ws, "fix: add", no_verify=True)["commit"])
        self.assertEqual(code_project.git_summary(self.ws)["changed_count"], 1)
        block = code_project.context_block(self.ws)
        self.assertIn("브랜치", block)
        self.assertIn("테스트는 pytest", block)
        text, files = code_project.expand_mentions("@calc.py 봐 줘", self.ws)
        self.assertEqual(files, ["calc.py"])
        self.assertIn("return a + b", text)
        self.assertEqual(code_project.memory_add(self.ws, "원격에서도 메모"), "AGENTS.md")
        self.assertIn("- 원격에서도 메모", (self.ws_path / "AGENTS.md").read_text())

    def test_commands_stream_and_stop_on_the_server(self):
        events = []
        runner = code_runner.RunManager(on_event=events.append)
        self.addCleanup(runner.shutdown)
        rec = runner.start(self.ws, "pwd; echo T=$MY_API_TOKEN P=$PLAIN_VALUE; echo 'calc.py:2: error: nope'; exit 3")
        self.assertTrue(runner.wait(rec.id, 20))
        self.assertEqual((rec.status, rec.code), ("failed", 3))
        out = rec.output_tail
        self.assertIn(os.path.realpath(self.ws_path), out)
        self.assertIn("T= P=보임", out)                      # 서버의 비밀 이름 환경 변수는 넘기지 않는다
        self.assertEqual([(x["path"], x["line"]) for x in rec.locations], [("calc.py", 2)])
        self.assertTrue(any(e.get("kind") == "run_output" for e in events))
        self.assertEqual(rec.inputs, [])
        rec2 = runner.start(self.ws, "cat calc.py > /dev/null; sleep 300 & echo CHILD=$!; wait")
        self.assertEqual(runner.start(self.ws, "true").cwd, str(cw.root_of(self.ws)))
        self.assertTrue(wait(lambda: "CHILD=" in rec2.output_tail))
        child = int(re.search(r"CHILD=(\d+)", rec2.output_tail).group(1))
        runner.stop(rec2.id)
        self.assertTrue(runner.wait(rec2.id, 20))
        self.assertEqual(rec2.status, "stopped")
        self.assertTrue(wait(lambda: not _alive(child)), "서버의 자식 프로세스가 남았습니다")
        self.assertEqual(code_runner.input_files(self.ws, "python calc.py nope.py"), ["calc.py"])

    def test_terminal_opens_in_the_remote_folder(self):
        out = []
        m = terminal.TerminalManager(on_output=lambda sid, t: out.append(t))
        self.addCleanup(m.shutdown)
        s = m.open(self.ws, 90, 20)
        self.assertTrue(s.title.endswith("ssh " + HOST))
        m.write(s.id, "pwd\n")
        self.assertTrue(wait(lambda: os.path.realpath(self.ws_path) in "".join(out)), "".join(out))

    def test_lost_connection_is_a_clear_error(self):
        self.helper.close()
        self.assertTrue(wait(lambda: not self.helper.alive))
        with self.assertRaisesRegex(remote_fs.RemoteError, "SSH 연결이 없습니다"):
            cw.list_dir(self.ws, "")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/status") as f:
            return "\nState:\tZ" not in f.read()
    except OSError:
        return True


@unittest.skipUnless(POSIX, "원격 도우미는 Linux·macOS 서버용")
class RemoteBridgeTests(unittest.TestCase):
    """Bridge(코드 화면 API·Code 에이전트)가 원격 작업 폴더에서 일한다."""

    def setUp(self):
        import main
        from support import isolated_app_dir, preserved_hooks

        self.hooks = preserved_hooks()
        self.hooks.__enter__()
        self.addCleanup(self.hooks.__exit__, None, None, None)
        self.iso = isolated_app_dir()
        self.root = self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        self.home = self.root / "server-home"
        self.home.mkdir()
        self.helper = remote_client.LocalHelper(HOST, env=dict(os.environ, HOME=str(self.home)))
        self.helper.start()
        remote_fs.register(HOST, self.helper)
        self.addCleanup(remote_fs.unregister, HOST)
        self.addCleanup(self.helper.close)
        self.bridge = main.Bridge()
        self.bridge._window = object()
        self.events = []
        self.bridge._push = self.push
        self.addCleanup(self.bridge._code_shutdown)
        self.addCleanup(self.bridge._mcp.shutdown)
        self.addCleanup(self.bridge._events.stop)
        self.local = self.root / "local-ws"
        self.local.mkdir()
        self.remote = self.home / "proj"
        self.remote.mkdir()
        (self.remote / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        (self.remote / "test_calc.py").write_text("from calc import add\nassert add(2, 3) == 5\nprint('ok')\n")
        self.bridge._config["workspace"] = str(self.local)
        self.bridge._config["api_key"] = "test-key"

    def push(self, ev):
        self.events.append(ev)
        if ev.get("type") == "confirm":
            self.bridge.resolve_confirm(ev["id"], "allow")

    def test_open_remote_folder_and_use_the_code_screen(self):
        r = self.bridge.code_ssh_open(HOST, "~/proj")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["workspace"], remote_fs.url(HOST, os.path.realpath(self.remote)))
        st = self.bridge.code_state()
        self.assertTrue(st["workspace"]["remote"])
        self.assertEqual(st["workspace"]["name"], "proj")
        self.assertTrue(st["remote"]["connected"])
        self.assertEqual(st["remote"]["target"], HOST)
        self.assertEqual([x["name"] for x in self.bridge.code_list("")["items"]], ["calc.py", "test_calc.py"])
        f = self.bridge.code_open("calc.py")["file"]
        self.assertTrue(self.bridge.code_save("calc.py", f["text"].replace("-", "+"), f["hash"])["ok"])
        self.assertIn("return a + b", (self.remote / "calc.py").read_text())
        d = self.bridge.code_delete("test_calc.py")
        self.assertTrue(d["ok"], d)
        self.assertTrue(d["deleted"]["trash"].startswith(str(self.home)))     # 서버의 휴지통
        self.assertFalse((self.root / "code-trash").exists())
        self.assertIn("proj", [x["name"] for x in self.bridge.code_ssh_browse(HOST, "")["folder"]["dirs"]])
        # 채팅의 작업 폴더는 그대로 로컬
        self.assertEqual(self.bridge._workspace(), str(self.local))
        # 로컬로 되돌리기
        self.bridge.code_ssh_local()
        st = self.bridge.code_state()
        self.assertIsNone(st["remote"])
        self.assertEqual(st["workspace"]["path"], str(self.local))
        recent = self.bridge.code_ssh_hosts()["recent"]
        self.assertEqual([(x["target"], x["path"]) for x in recent], [(HOST, os.path.realpath(self.remote))])

    def test_disconnected_remote_folder_says_so(self):
        self.bridge.code_ssh_open(HOST, str(self.remote))
        self.helper.close()
        self.assertTrue(wait(lambda: not self.helper.alive))
        st = self.bridge.code_state()
        self.assertFalse(st["remote"]["connected"])
        r = self.bridge.code_list("")
        self.assertFalse(r["ok"])
        self.assertIn("SSH 연결", r["error"])

    def test_code_agent_works_on_the_server(self):
        import agent
        from test_code_agent import FakeModel

        self.bridge.code_ssh_open(HOST, str(self.remote))
        steps = [
            {"action": "list", "path": "."},
            {"action": "glob", "pattern": "**/*.py"},
            {"action": "search", "pattern": "return a"},
            {"action": "read", "path": "calc.py"},
            {"action": "edit", "path": "calc.py", "old": "return a - b", "new": "return a + b", "reason": "덧셈"},
            {"action": "write", "path": "notes/README.md", "content": "원격 메모\n"},
            {"action": "run", "command": "python3 test_calc.py"},
            {"action": "read", "path": "../../etc/hostname"},
            {"action": "done", "answer": "고쳤습니다"},
        ]
        fake = FakeModel(steps)
        with patch.object(agent, "ask", fake):
            r = self.bridge.code_agent_start("add 고치기")
            self.assertTrue(r["ok"], r)
            self.assertTrue(wait(lambda: not self.bridge._ca_running, 60))
        task = self.bridge.code_agent_task(r["task"]["id"])["task"]
        self.assertEqual(task["status"], "done", task["turns"][-1])
        self.assertIn("return a + b", (self.remote / "calc.py").read_text())
        self.assertEqual((self.remote / "notes" / "README.md").read_text(), "원격 메모\n")
        titles = "\n".join(s["title"] + "\n" + s["detail"] for s in task["steps"])
        self.assertIn("calc.py", titles)
        self.assertIn("calc.py:2: ", titles)                     # 서버에서 찾은 search 결과
        self.assertRegex(titles, r"run python3 test_calc.py \(종료 코드 0")
        self.assertIn("작업 폴더 밖", titles)
        self.assertIn(f"원격 SSH 서버 '{HOST}'", fake.prompts[0])   # 에이전트가 서버에서 일한다는 것을 안다
        self.assertEqual(task["workspace"], remote_fs.url(HOST, os.path.realpath(self.remote)))
        # 되돌리기도 서버의 파일에
        rv = self.bridge.code_agent_revert(task["id"])
        self.assertEqual(sorted(rv["reverted"]), ["calc.py", "notes/README.md"])
        self.assertIn("return a - b", (self.remote / "calc.py").read_text())
        self.assertFalse((self.remote / "notes" / "README.md").exists())
        # 격리 작업(git worktree)은 아직 원격에서 쓰지 않는다
        r = self.bridge.code_agent_start("새 작업", "", {"isolate": True})
        self.assertFalse(r["ok"])
        self.assertIn("격리 작업", r["error"])

    def test_terminal_and_shell_command_run_on_the_server(self):
        self.bridge.code_ssh_open(HOST, str(self.remote))
        r = self.bridge.code_term_open(80, 20)
        self.assertTrue(r["ok"], r)
        tid = r["terminal"]["id"]
        self.bridge.code_term_write(tid, "pwd\n")
        out = lambda: "".join(e["data"] for e in self.events if e.get("kind") == "term_output")  # noqa: E731
        self.assertTrue(wait(lambda: os.path.realpath(self.remote) in out()), out())
        chk = self.bridge.code_run_check("ls")
        sh = self.bridge.code_agent_shell("ls", chk["token"])
        self.assertTrue(sh["ok"], sh)
        self.assertTrue(wait(lambda: any(e.get("kind") == "agent_shell_done" for e in self.events)))
        task = self.bridge.code_agent_task(sh["task"]["id"])["task"]
        self.assertIn("calc.py", task["steps"][-1]["detail"])


if __name__ == "__main__":
    unittest.main()
