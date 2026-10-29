# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.18 SSH 연결(ssh_remote, ssh_api): 시험용 SSH 서버(fake_ssh, paramiko 서버 모드)로 호스트 키 확인·기억·바뀐 키 거절,
암호·키(암호문)·keyboard-interactive(OTP)·2단계 인증, ProxyJump, 취소, 원격 도우미·터미널, 화면 API 흐름(묻기 이벤트)을 본다."""
import os
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

try:
    import paramiko
    HAVE = os.name != "nt"
except ImportError:
    HAVE = False

if HAVE:
    import fake_ssh
    import ssh_remote

import remote_fs  # noqa: E402
import storage  # noqa: E402


def wait(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Answers:
    """prompt 콜백: 호스트 키는 받아들이고, 칸 이름에 맞는 값을 준다. 받은 질문을 남긴다."""

    def __init__(self, values=None, accept=True):
        self.values = values or {}
        self.accept = accept
        self.asked = []

    def __call__(self, kind, data):
        self.asked.append((kind, data))
        if kind == "hostkey":
            return {"accept": True} if self.accept else None
        out = []
        for f in data["fields"]:
            v = self.values.get(f["label"])
            if v is None:
                return None
            out.append(v.pop(0) if isinstance(v, list) else v)
        return {"values": out}


@unittest.skipUnless(HAVE, "paramiko가 없거나 Windows")
class SshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        (self.home / ".ssh").mkdir(parents=True)
        self.app = self.tmp / "app"
        self.app.mkdir()
        for p in (patch.dict(os.environ, {"HOME": str(self.home)}), patch.object(storage, "APP_DIR", self.app),
                  patch.dict(os.environ, {"SSH_AUTH_SOCK": ""})):
            p.start()
            self.addCleanup(p.stop)
        ssh_remote._key_cache.clear()
        self.ws = self.tmp / "proj"
        self.ws.mkdir()
        (self.ws / "hello.txt").write_text("안녕\n", encoding="utf-8")

    def server(self, **kw):
        srv = fake_ssh.FakeSSH(home=str(self.home), **kw).__enter__()
        self.addCleanup(srv.stop)
        return srv

    def connect(self, target, answers, **kw):
        c = ssh_remote.SshConnection(target, answers, **kw)
        self.addCleanup(c.close)
        c.connect()
        return c

    def test_password_login_remembers_the_host_key_and_refuses_a_changed_one(self):
        srv = self.server(allowed=("password",))
        a = Answers({"암호": "pw-1234"})
        c = self.connect(f"student@127.0.0.1:{srv.port}", a)
        self.assertTrue(c.alive)
        self.assertEqual([k for k, _ in a.asked], ["hostkey", "secret"])
        fp = a.asked[0][1]["fingerprint"]
        self.assertTrue(fp.startswith("SHA256:"))
        self.assertEqual(fp, ssh_remote.fingerprint(srv.host_key))
        known = (self.app / "ssh" / "known_hosts").read_text()
        self.assertIn(f"[127.0.0.1]:{srv.port}", known)
        self.assertFalse((self.home / ".ssh" / "known_hosts").exists())   # 사용자의 known_hosts는 고치지 않는다
        # 원격 도우미가 돈다
        self.assertEqual(c.info["home"], str(self.home))
        self.assertEqual(c.call("fs.kind", [str(self.ws / "hello.txt")]), "file")
        c.close()
        # 두 번째: 호스트 키는 묻지 않는다
        a2 = Answers({"암호": "pw-1234"})
        self.connect(f"student@127.0.0.1:{srv.port}", a2)
        self.assertEqual([k for k, _ in a2.asked], ["secret"])
        # 알던 주소에 다른 키의 서버(키가 바뀜): 연결하지 않는다
        srv2 = self.server(allowed=("password",))
        known_path = self.app / "ssh" / "known_hosts"
        known_path.write_text(known_path.read_text().replace(f"[127.0.0.1]:{srv.port}", f"[127.0.0.1]:{srv2.port}"))
        with self.assertRaisesRegex(ssh_remote.SshError, "호스트 키가 알고 있던 것과 다릅니다"):
            self.connect(f"student@127.0.0.1:{srv2.port}", Answers({"암호": "pw-1234"}))

    def test_wrong_password_is_asked_again_and_cancel_stops(self):
        srv = self.server(allowed=("password",))
        a = Answers({"암호": ["nope", "pw-1234"]})
        self.connect(f"student@127.0.0.1:{srv.port}", a)
        msgs = [d["message"] for k, d in a.asked if k == "secret"]
        self.assertEqual(len(msgs), 2)
        self.assertIn("틀렸습니다", msgs[1])
        with self.assertRaises(ssh_remote.Cancelled):
            self.connect(f"student@127.0.0.1:{srv.port}", Answers({}))      # 암호 창에서 취소
        with self.assertRaises(ssh_remote.Cancelled):
            srv3 = self.server(allowed=("password",))
            self.connect(f"student@127.0.0.1:{srv3.port}", Answers({"암호": "pw-1234"}, accept=False))   # 호스트 키 거절

    def test_key_with_passphrase_then_otp_two_factor(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        private = ed25519.Ed25519PrivateKey.generate()
        path = self.home / ".ssh" / "id_ed25519"
        path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                               serialization.BestAvailableEncryption("열쇠-암호".encode())))
        key = paramiko.Ed25519Key.from_path(str(path), "열쇠-암호".encode())
        srv = self.server(key=key, allowed=("publickey", "keyboard-interactive"),
                          require_all=("publickey", "keyboard-interactive"))
        (self.home / ".ssh" / "config").write_text(
            f"Host lab\n  HostName 127.0.0.1\n  Port {srv.port}\n  User student\n  IdentityFile ~/.ssh/id_ed25519\n")
        a = Answers({"암호문": "열쇠-암호", "Password:": "pw-1234", "OTP:": "246810"})
        c = self.connect("lab", a)
        self.assertTrue(c.alive)
        kinds = [(k, d.get("title")) for k, d in a.asked]
        self.assertEqual(kinds, [("hostkey", None), ("secret", "키 암호문"), ("secret", "POSTECH 로그인")])
        otp = a.asked[2][1]["fields"]
        self.assertEqual([(f["label"], f["secret"]) for f in otp], [("Password:", True), ("OTP:", False)])
        self.assertEqual([x["name"] for x in ssh_remote.config_hosts()], ["lab"])
        c.close()
        # 키 암호문은 앱을 끌 때까지 기억한다(다시 묻지 않음). OTP는 다시 묻는다
        a2 = Answers({"Password:": "pw-1234", "OTP:": "246810"})
        self.connect("lab", a2)
        self.assertEqual([d.get("title") for k, d in a2.asked], ["POSTECH 로그인"])

    def test_proxy_jump(self):
        jump = self.server(allowed=("password",))
        target = self.server(allowed=("password",))
        (self.home / ".ssh" / "config").write_text(
            f"Host gate\n  HostName 127.0.0.1\n  Port {jump.port}\n  User student\n"
            f"Host inner\n  HostName 127.0.0.1\n  Port {target.port}\n  User student\n  ProxyJump gate\n")
        a = Answers({"암호": "pw-1234"})
        c = self.connect("inner", a)
        self.assertTrue(c.alive)
        self.assertEqual(jump.forwards, [("127.0.0.1", target.port)])   # 점프 호스트를 거쳐 들어갔다
        self.assertEqual([d["host"] for k, d in a.asked if k == "hostkey"],
                         [f"student@127.0.0.1:{jump.port}", f"student@127.0.0.1:{target.port}"])

    def test_missing_python_is_explained(self):
        srv = self.server(allowed=("password",))
        with self.assertRaisesRegex(ssh_remote.SshError, "Python 3.6 이상"):
            self.connect(f"student@127.0.0.1:{srv.port}", Answers({"암호": "pw-1234"}), python="python-없음")

    def test_remote_terminal_in_the_folder(self):
        srv = self.server(allowed=("password",))
        c = self.connect(f"student@127.0.0.1:{srv.port}", Answers({"암호": "pw-1234"}))
        sh = c.shell(str(self.ws), 100, 30)
        self.addCleanup(sh.close)
        sh.write("pwd; stty size; echo T=$TERM\n")
        out = []
        self.assertTrue(wait(lambda: out.append(sh.read() or "") or "T=xterm-256color" in "".join(out)), "".join(out))
        text = "".join(out)
        self.assertIn(os.path.realpath(self.ws), text)
        self.assertIn("30 100", text)
        sh.resize(120, 40)
        sh.write("stty size\n")
        self.assertTrue(wait(lambda: out.append(sh.read() or "") or "40 120" in "".join(out)))
        sh.write("exit 4\n")
        self.assertTrue(wait(lambda: sh.read() is None or sh.exit_code() is not None))
        self.assertTrue(wait(lambda: sh.exit_code() == 4))

    def test_parse_target(self):
        self.assertEqual(ssh_remote.parse_target("me@a.b")[0], "me@a.b")
        self.assertEqual(ssh_remote.parse_target("ssh -p 2222 me@a.b")[:4], ("me@a.b:2222", "me", "a.b", 2222))
        self.assertEqual(ssh_remote.parse_target("me@a.b:22")[0], "me@a.b")
        for bad in ("", "a b c", "me@a.b:99999", "ssh -i key me@a", "x/y"):
            with self.assertRaises(ssh_remote.SshError, msg=bad):
                ssh_remote.parse_target(bad)


@unittest.skipUnless(HAVE, "paramiko가 없거나 Windows")
class SshBridgeTests(unittest.TestCase):
    """화면 API: 연결 → 묻기 이벤트 → 답 → 폴더 고르기·열기 → 끊김."""

    def setUp(self):
        import main
        from support import isolated_app_dir, preserved_hooks

        self.hooks = preserved_hooks()
        self.hooks.__enter__()
        self.addCleanup(self.hooks.__exit__, None, None, None)
        self.iso = isolated_app_dir()
        self.root = self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        self.home = self.root / "home"
        (self.home / "proj").mkdir(parents=True)
        (self.home / "proj" / "a.py").write_text("print(1)\n")
        p = patch.dict(os.environ, {"HOME": str(self.home), "SSH_AUTH_SOCK": ""})
        p.start()
        self.addCleanup(p.stop)
        ssh_remote._key_cache.clear()
        self.srv = fake_ssh.FakeSSH(home=str(self.home), allowed=("keyboard-interactive",)).__enter__()
        self.addCleanup(self.srv.stop)
        self.bridge = main.Bridge()
        self.bridge._window = object()
        self.events = []
        self.answers = {"hostkey": {"accept": True}, "secret": {"values": ["pw-1234", "246810"]}}
        self.bridge._push = self.push
        self.addCleanup(self.bridge._ssh_shutdown)
        self.addCleanup(self.bridge._code_shutdown)
        self.addCleanup(self.bridge._mcp.shutdown)
        self.addCleanup(self.bridge._events.stop)
        self.target = f"student@127.0.0.1:{self.srv.port}"

    def push(self, ev):
        self.events.append(ev)
        if ev.get("kind") == "ssh_prompt":
            ans = self.answers.get(ev["prompt"])
            import threading
            threading.Thread(target=self.bridge.code_ssh_answer, args=(ev["id"], ans), daemon=True).start()

    def states(self):
        return [e["state"] for e in self.events if e.get("kind") == "ssh_state"]

    def test_connect_open_use_and_disconnect(self):
        r = self.bridge.code_ssh_connect(self.target)
        self.assertEqual(r["state"], "connecting")
        self.assertTrue(wait(lambda: "connected" in self.states()), self.events[-3:])
        prompts = [e for e in self.events if e.get("kind") == "ssh_prompt"]
        self.assertEqual([p["prompt"] for p in prompts], ["hostkey", "secret"])
        self.assertNotIn("pw-1234", repr(self.bridge._config))           # 암호·OTP는 저장하지 않는다
        folder = self.bridge.code_ssh_browse(self.target, "")["folder"]
        self.assertEqual(folder["path"], os.path.realpath(self.home))
        self.assertIn("proj", [d["name"] for d in folder["dirs"]])
        opened = self.bridge.code_ssh_open(self.target, folder["path"] + "/proj")
        self.assertTrue(opened["ok"], opened)
        st = self.bridge.code_state()
        self.assertTrue(st["remote"]["connected"])
        self.assertEqual(st["remote"]["server"]["user"], os.environ.get("USER") or st["remote"]["server"]["user"])
        self.assertEqual([x["name"] for x in self.bridge.code_list("")["items"]], ["a.py"])
        hosts = self.bridge.code_ssh_hosts()
        self.assertEqual(hosts["recent"][0]["target"], self.target)
        self.assertEqual(hosts["states"][self.target], "connected")
        # 끊기: 코드 화면은 원격 폴더를 기억하고 '연결 안 됨'으로 보인다
        self.bridge.code_ssh_disconnect()
        st = self.bridge.code_state()
        self.assertFalse(st["remote"]["connected"])
        self.assertFalse(self.bridge.code_list("")["ok"])
        # 다시 연결하면 그대로 쓴다
        self.events.clear()
        self.bridge.code_ssh_connect(self.target)
        self.assertTrue(wait(lambda: "connected" in self.states()))
        self.assertEqual([e["prompt"] for e in self.events if e.get("kind") == "ssh_prompt"], ["secret"])   # 호스트 키는 기억함
        self.assertTrue(self.bridge.code_list("")["ok"])

    def test_failed_login_and_cancel(self):
        self.answers["secret"] = {"values": ["wrong", "000000"]}
        self.bridge.code_ssh_connect(self.target)
        self.assertTrue(wait(lambda: "failed" in self.states(), 30), self.events[-3:])
        failed = [e for e in self.events if e.get("kind") == "ssh_state" and e["state"] == "failed"][0]
        self.assertIn("로그인하지 못했습니다", failed["message"])
        self.answers["secret"] = None   # 창에서 취소
        self.events.clear()
        self.bridge.code_ssh_connect(self.target)
        self.assertTrue(wait(lambda: "cancelled" in self.states()), self.events[-3:])
        self.assertFalse(self.bridge.code_ssh_open(self.target, "/")["ok"])

    def test_android_has_no_ssh(self):
        with patch.object(type(self.bridge), "_code_android", staticmethod(lambda: True)):
            self.assertFalse(self.bridge.code_ssh_connect(self.target)["ok"])
            self.assertFalse(self.bridge.code_ssh_hosts()["supported"])
            self.assertFalse(self.bridge.code_state()["features"]["ssh"])


if __name__ == "__main__":
    unittest.main()
