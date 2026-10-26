# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""원격 도우미(remote_helper)와 주고받는 쪽(1.18). SSH 채널(ssh_remote) 위에서 쓰고, 시험에서는 로컬 하위 프로세스(LocalHelper) 위에서 쓴다.

- 시작: 짧은 한 줄 파이썬(ONE_LINER)을 실행하고, 표준 입력으로 도우미 묶음(bundle: 모듈 소스)을 보낸다. 서버에 파일을 남기지 않는다.
  셸 시작 파일이 출력한 글은 건너뛰고 {"poschat": "ready"} 줄부터 읽는다.
- 요청은 {"id", "m", "a", "k"}, 답은 {"id", "r"} 또는 {"id", "e"}(예외 정보 → 같은 종류의 예외로 다시 낸다).
  명령 출력은 이벤트 {"ev": "out"|"eof"|"exit", "p": 번호}로 온다(RemoteProc이 subprocess.Popen처럼 보이게 받는다).
- 연결이 끊기면 기다리던 요청은 RemoteError, 돌던 명령은 끝난 것으로 한다.
"""
import itertools
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import remote_fs
from remote_fs import RemoteError

BUNDLE = ("remote_fs", "code_workspace", "code_git", "code_project", "remote_helper")
ONE_LINER = ('import sys,json;r=sys.stdin.buffer;n=int(r.readline());B=json.loads(r.read(n).decode("utf-8"));'
             'exec(compile(B["boot"],"<poschat-boot>","exec"))')
PYTHONS = ("python3", "python3.13", "python3.12", "python3.11", "python3.10", "python3.9", "python3.8", "python3.7",
           "python3.6")
CALL_TIMEOUT = 300
START_TIMEOUT = 40


def source_dir():
    """도우미 묶음 소스가 있는 곳: 설치본은 _MEIPASS/remote(build_installer가 넣음), 개발 중에는 저장소."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "remote" / "remote_helper.py").is_file():
        return Path(meipass) / "remote"
    return Path(__file__).resolve().parent


def bundle():
    import remote_helper
    modules = [(name, (source_dir() / (name + ".py")).read_text(encoding="utf-8")) for name in BUNDLE]
    data = json.dumps({"boot": remote_helper.BOOT, "modules": modules}).encode("utf-8")
    return str(len(data)).encode("ascii") + b"\n" + data


def remote_command(python=""):
    """서버의 로그인 셸(bash·zsh·tcsh 무엇이든)이 실행할 한 줄: /bin/sh로 python3을 찾아 도우미를 띄운다."""
    choices = [python] if python else list(PYTHONS)
    tries = "; ".join("command -v {0} >/dev/null 2>&1 && exec {0} -c {1}".format(shlex.quote(p), shlex.quote(ONE_LINER))
                      for p in choices)
    script = tries + "; echo '{\"poschat\": \"fatal\", \"error\": \"nopython\"}'"
    return "exec /bin/sh -c " + shlex.quote(script)


class _Stream:
    """RemoteProc.stdout: read1()이 이벤트로 받은 바이트를 하나씩 돌려준다(끝나면 b"")."""

    def __init__(self):
        self.q = queue.Queue()
        self.done = False

    def read1(self, n=65536):
        if self.done:
            return b""
        data = self.q.get()
        if not data:
            self.done = True
        return data

    read = read1

    def close(self):
        pass


class RemoteProc:
    """서버에서 도는 명령. code_runner.RunManager가 subprocess.Popen처럼 쓴다(poll·wait·stdout.read1·kill_tree)."""

    def __init__(self, client, pid):
        self.client = client
        self.pid = pid
        self.returncode = None
        self.stdout = _Stream()
        self._exit = threading.Event()

    def _out(self, data):
        self.stdout.q.put(data)

    def _eof(self):
        self.stdout.q.put(b"")

    def _exited(self, code):
        self.returncode = code
        self._exit.set()

    def poll(self):
        return self.returncode if self._exit.is_set() else None

    def wait(self, timeout=None):
        if not self._exit.wait(timeout):
            raise subprocess.TimeoutExpired("(원격 명령)", timeout)
        return self.returncode

    def kill_tree(self):
        if self._exit.is_set():
            return
        try:
            self.client.call("proc.stop", [self.pid], {}, timeout=20)
        except (RemoteError, OSError):
            pass

    kill = kill_tree
    terminate = kill_tree


class HelperClient:
    """원격 도우미 하나와의 대화. write(bytes)·readline()·close()를 주는 통로 위에서 돈다."""

    def __init__(self, name, write, readline, close=None, on_closed=None):
        self.name = name
        self._write = write
        self._readline = readline
        self._close = close
        self.on_closed = on_closed
        self.alive = False
        self.info = {}
        self.noise = []          # ready 전에 받은 글(셸 시작 파일의 출력·오류 안내)
        self._ids = itertools.count(1)
        self._pending = {}
        self._procs = {}
        self._lock = threading.Lock()
        self._wlock = threading.Lock()

    # ---- 시작·끝 ----

    def start(self, timeout=START_TIMEOUT):
        try:
            self._send_raw(bundle())
        except (OSError, EOFError, ValueError):
            pass   # 서버 쪽이 벌써 끝났다(python3 없음 등): 남긴 글을 아래에서 읽어 이유를 알린다
        result, err = {}, []

        def wait_ready():
            while True:
                line = self._readline()
                if not line:
                    err.append("closed")
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith('{"poschat"'):
                    try:
                        msg = json.loads(text)
                    except ValueError:
                        msg = {}
                    if msg.get("poschat") == "ready":
                        result.update(msg.get("info") or {})
                        return
                    if msg.get("poschat") == "fatal":
                        err.append(msg.get("error") or "fatal")
                        return
                if text and len(self.noise) < 40:
                    self.noise.append(text[:300])

        t = threading.Thread(target=wait_ready, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or err:
            self.close()
            reason = err[0] if err else "timeout"
            if reason in ("nopython", "python"):
                raise RemoteError("원격 컴퓨터에서 Python 3.6 이상(python3 명령)을 찾지 못했습니다. 서버에 python3를 설치하거나 "
                                  "관리자에게 문의하세요.")
            extra = (" 받은 글: " + " / ".join(self.noise[-3:])) if self.noise else ""
            raise RemoteError("원격 도우미를 시작하지 못했습니다({}).{}".format(
                "응답 없음" if reason == "timeout" else "연결이 닫힘", extra)[:600])
        self.info = result
        self.alive = True
        threading.Thread(target=self._reader, daemon=True, name="remote-" + self.name).start()
        return self.info

    def close(self):
        was = self.alive
        self.alive = False
        if self._close:
            try:
                self._close()
            except Exception:
                pass
        if was:
            self._fail_all("SSH 연결을 닫았습니다.")

    def _fail_all(self, message):
        with self._lock:
            pending, self._pending = self._pending, {}
            procs, self._procs = self._procs, {}
        for slot in pending.values():
            slot[1] = {"e": {"cls": "RemoteError", "msg": message}}
            slot[0].set()
        for proc in procs.values():
            proc._out(("\n[" + message + "]\n").encode("utf-8"))
            proc._eof()
            proc._exited(None)

    # ---- 주고받기 ----

    def _send_raw(self, data):
        with self._wlock:
            self._write(data)

    def _send(self, obj):
        data = (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        try:
            self._send_raw(data)
        except (OSError, EOFError, ValueError) as e:
            self.alive = False
            raise RemoteError("SSH 연결이 끊겼습니다: {}".format(e))

    def _reader(self):
        try:
            while True:
                line = self._readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                if "id" in msg:
                    with self._lock:
                        slot = self._pending.pop(msg["id"], None)
                    if slot is not None:
                        slot[1] = msg
                        slot[0].set()
                elif "ev" in msg:
                    self._event(msg)
        except Exception:
            pass
        finally:
            self.alive = False
            self._fail_all("SSH 연결이 끊겼습니다. 코드 화면 위의 'SSH'에서 다시 연결하세요.")
            if self.on_closed:
                try:
                    self.on_closed(self)
                except Exception:
                    pass

    def _event(self, msg):
        with self._lock:
            proc = self._procs.get(msg.get("p"))
        if proc is None:
            return
        kind = msg["ev"]
        if kind == "out":
            proc._out(remote_fs.decode({"__b": msg.get("d") or ""}))
        elif kind == "eof":
            proc._eof()
        elif kind == "exit":
            with self._lock:
                self._procs.pop(proc.pid, None)
            proc._exited(msg.get("c"))

    def call(self, method, args=(), kwargs=None, timeout=CALL_TIMEOUT):
        if not self.alive:
            raise RemoteError("SSH 연결이 끊겼습니다. 코드 화면 위의 'SSH'에서 다시 연결하세요.")
        rid = next(self._ids)
        slot = [threading.Event(), None]
        with self._lock:
            self._pending[rid] = slot
        self._send({"id": rid, "m": method, "a": remote_fs.encode(list(args)), "k": remote_fs.encode(kwargs or {})})
        if not slot[0].wait(timeout):
            with self._lock:
                self._pending.pop(rid, None)
            raise RemoteError("원격 컴퓨터가 {}초 동안 답하지 않았습니다.".format(timeout))
        msg = slot[1]
        if "e" in msg:
            remote_fs.raise_error(msg["e"])
        return remote_fs.decode(msg.get("r"), self.name)

    # ---- 명령·터미널 ----

    def popen(self, cwd, command, extra_env=None, secret_pattern=""):
        """서버에서 명령을 시작한다(작업 폴더 cwd: 서버의 절대 경로)."""
        pid = uuid.uuid4().hex[:12]
        proc = RemoteProc(self, pid)
        with self._lock:
            self._procs[pid] = proc
        try:
            self.call("proc.start", [pid, cwd, command, dict(extra_env or {}), secret_pattern], {}, timeout=60)
        except Exception:
            with self._lock:
                self._procs.pop(pid, None)
            raise
        return proc

    def shell(self, cwd, cols, rows):
        raise RemoteError("이 연결에서는 터미널을 열 수 없습니다.")


class LocalHelper(HelperClient):
    """시험용: 이 컴퓨터에서 도우미를 하위 프로세스로 띄운다(SSH 없이 같은 통로·같은 도우미). 터미널은 로컬 pty."""

    def __init__(self, name, python=None, env=None):
        self.proc = subprocess.Popen([python or sys.executable, "-c", ONE_LINER], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                     cwd=(env or os.environ).get("HOME") or os.path.expanduser("~"))

        def write(data):
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

        def close():
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

        super().__init__(name, write, self.proc.stdout.readline, close)

    def shell(self, cwd, cols, rows):
        import terminal
        exe, args, _ = terminal.default_shell()
        return terminal._PosixPty([exe, *args], cwd, terminal.terminal_env(), cols, rows)

