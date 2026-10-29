# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.18 Code 화면의 터미널(terminal.py, code_api.code_term_*): 진짜 셸(pty)·입력·출력·크기·끝남·닫기·비밀 환경 변수·
개수 제한·안드로이드 막기·AI에게 묻기(제어 글자 빼기·비밀 가리기). Windows(ConPTY)는 CI의 설치본 selftest가 확인한다."""
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

import terminal  # noqa: E402

POSIX = os.name != "nt"
SH = ("/bin/sh", [], "sh")


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@unittest.skipUnless(POSIX and terminal.SUPPORTED, "macOS·Linux pty 시험")
class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.out, self.exits = [], []
        self.m = terminal.TerminalManager(on_output=lambda sid, t: self.out.append((sid, t)),
                                          on_exit=lambda sid, code: self.exits.append((sid, code)))
        self.addCleanup(self.m.shutdown)

    def text(self, sid):
        return "".join(t for i, t in self.out if i == sid)

    def test_shell_runs_in_the_folder_with_size_and_without_secrets(self):
        d = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        with patch.dict(os.environ, {"MY_API_KEY": "sk-secret-123456", "SSH_AUTH_SOCK": "/tmp/agent.sock", "PLAIN_VALUE": "보임"}):
            s = self.m.open(str(d), 100, 30, shell=SH)
        self.m.write(s.id, "pwd; stty size; echo K=$MY_API_KEY S=$SSH_AUTH_SOCK P=$PLAIN_VALUE T=$TERM\n")
        self.assertTrue(wait(lambda: "T=xterm-256color" in self.text(s.id)), self.text(s.id))
        out = self.text(s.id)
        self.assertIn(os.path.realpath(d), out.replace(str(d), os.path.realpath(d)))
        self.assertIn("30 100", out)
        self.assertIn("K= ", out)                         # 비밀 이름 환경 변수는 넘기지 않는다
        self.assertIn("S=/tmp/agent.sock", out)           # SSH 에이전트는 넘긴다
        self.assertIn("P=보임", out)                      # 한글(UTF-8)
        self.m.resize(s.id, 120, 40)
        self.m.write(s.id, "stty size\n")
        self.assertTrue(wait(lambda: "40 120" in self.text(s.id)))
        self.assertIn("40 120", self.m.get(s.id)["scrollback"])   # 다시 그릴 때 쓰는 끝부분

    def test_exit_is_reported_and_writes_after_are_refused(self):
        s = self.m.open(os.getcwd(), shell=SH)
        self.m.write(s.id, "exit 7\n")
        self.assertTrue(wait(lambda: self.exits))
        self.assertEqual(self.exits, [(s.id, 7)])
        self.assertFalse(self.m.get(s.id)["alive"])
        with self.assertRaises(terminal.TerminalError):
            self.m.write(s.id, "echo\n")

    def test_close_kills_the_shell_and_its_children(self):
        s = self.m.open(os.getcwd(), shell=SH)
        self.m.write(s.id, "sleep 300 & echo CHILD=$!\n")
        import re

        found = lambda: re.search(r"CHILD=(\d+)", self.text(s.id))  # noqa: E731  (입력 줄의 'CHILD=$!' 메아리는 건너뛴다)
        self.assertTrue(wait(found), self.text(s.id))
        child = int(found().group(1))
        self.m.close(s.id)
        self.assertTrue(wait(lambda: not _alive(child)), "자식 프로세스가 남았습니다")
        self.assertEqual(self.m.list(), [])
        with self.assertRaises(terminal.TerminalError):
            self.m.get(s.id)

    def test_limit_and_android(self):
        for _ in range(terminal.MAX_TERMINALS):
            self.m.open(os.getcwd(), shell=SH)
        with self.assertRaisesRegex(terminal.TerminalError, "까지"):
            self.m.open(os.getcwd(), shell=SH)
        self.m.shutdown()
        with patch.object(terminal, "SUPPORTED", False):
            with self.assertRaisesRegex(terminal.TerminalError, "PC 앱"):
                self.m.open(os.getcwd(), shell=SH)
            self.assertTrue(terminal.selfcheck().startswith("SKIP"))

    def test_selfcheck(self):
        self.assertEqual(terminal.selfcheck(), "OK")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:   # 좀비(끝났지만 거두지 않음)는 끝난 것으로 본다
        with open(f"/proc/{pid}/status") as f:
            return "\nState:\tZ" not in f.read()
    except OSError:
        return True


class BridgeTests(unittest.TestCase):
    def setUp(self):
        import main
        from support import isolated_app_dir, preserved_hooks

        self.hooks = preserved_hooks()
        self.hooks.__enter__()
        self.addCleanup(self.hooks.__exit__, None, None, None)
        self.iso = isolated_app_dir()
        self.root = self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        self.bridge = main.Bridge()
        self.events = []
        self.bridge._push = self.events.append
        self.addCleanup(self.bridge._code_shutdown)
        self.addCleanup(self.bridge._mcp.shutdown)
        self.addCleanup(self.bridge._events.stop)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        self.bridge._config["workspace"] = str(self.ws)

    @unittest.skipUnless(POSIX and terminal.SUPPORTED, "macOS·Linux pty 시험")
    def test_open_write_events_and_shutdown(self):
        with patch.object(terminal, "default_shell", return_value=SH):
            r = self.bridge.code_term_open(90, 20)
        self.assertTrue(r["ok"], r)
        tid = r["terminal"]["id"]
        self.assertTrue(self.bridge.code_state()["features"]["terminal"])
        self.assertTrue(self.bridge.code_term_write(tid, "echo 터미널-$((2+3))\n")["ok"])
        out = lambda: "".join(e["data"] for e in self.events if e.get("kind") == "term_output" and e["id"] == tid)  # noqa: E731
        self.assertTrue(wait(lambda: "터미널-5" in out()), out())
        self.assertTrue(self.bridge.code_term_resize(tid, 100, 30)["ok"])
        listed = self.bridge.code_terms()["terminals"]
        self.assertEqual([t["id"] for t in listed], [tid])
        self.assertIn("터미널-5", listed[0]["scrollback"])
        self.assertFalse(self.bridge.code_term_write("term-nope", "x")["ok"])
        self.bridge._code_shutdown()
        self.assertEqual(self.bridge.code_terms()["terminals"], [])

    def test_android_has_no_terminal(self):
        with patch.object(type(self.bridge), "_code_android", staticmethod(lambda: True)):
            r = self.bridge.code_term_open()
            self.assertFalse(r["ok"])
            self.assertIn("안드로이드", r["error"])
            self.assertFalse(self.bridge.code_state()["features"]["terminal"])

    def test_ask_strips_control_codes_and_masks_secrets(self):
        self.bridge._config["api_key"] = "postech-secret-key-0123456789"
        r = self.bridge.code_term_ask("\x1b[32m$ make\x1b[0m\r\nerror: key postech-secret-key-0123456789 rejected\r\n\x1b]0;title\x07done",
                                      "1: bash")
        self.assertTrue(r["ok"], r)
        att = r["attachments"][0]
        self.assertIn("터미널 출력", att["name"])
        import storage

        body = storage.attachment_file(att["id"]).read_text(encoding="utf-8")
        self.assertNotIn("\x1b", body)                                  # 색·제목 같은 제어 글자는 뺀다
        self.assertNotIn("postech-secret-key-0123456789", body)          # 앱이 아는 비밀은 가린다
        self.assertIn("$ make", body)
        self.assertIn("터미널 출력", r["question"])
        self.assertFalse(self.bridge.code_term_ask("   \x1b[0m  ")["ok"])


if __name__ == "__main__":
    unittest.main()
