# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Code 화면 아래 패널의 터미널(1.18): 진짜 대화형 셸. Windows는 ConPTY(pywinpty), macOS·Linux는 pty.

- 사용자가 코드 화면의 터미널을 열 때만 셸을 시작한다(에이전트는 쓰지 않는다). 작업 폴더에서 시작한다.
- 이름에 key·token·secret 같은 말이 든 환경 변수(code_runner.SECRET_ENV)는 넘기지 않는다. 다만 셸이 제대로 돌게
  SSH 에이전트(SSH_AUTH_SOCK)·로그인 세션 정보 몇 가지는 넘긴다.
- 읽는 스레드가 출력을 조금씩(약 30ms) 모아 on_output(id, 글)로 보낸다. 다시 그릴 때를 위해 끝부분(200KB)을 남긴다.
- 앱이 닫히면 모든 셸과 그 자식 프로세스를 끝낸다. 안드로이드에서는 쓰지 않는다(SUPPORTED).
- 원격(SSH) 작업 폴더면 서버의 셸(SSH pty 채널, ssh_remote)을 같은 방식(read·write·resize·exit_code·close)으로 쓴다.
"""
import codecs
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

import code_runner
import remote_fs

MAX_TERMINALS = 6
SCROLLBACK = 200_000
FLUSH_SECONDS = 0.03
KEEP_ENV = re.compile(r"^(SSH_AUTH_SOCK|SESSIONNAME|DBUS_SESSION_BUS_ADDRESS|XDG_SESSION_\w+)$", re.I)
SUPPORTED = not hasattr(sys, "getandroidapilevel") and "ANDROID_ARGUMENT" not in os.environ \
    and "ANDROID_DATA" not in os.environ


class TerminalError(Exception):
    pass


def default_shell():
    """(실행 파일, 인자, 이름). Windows는 PowerShell(없으면 cmd), macOS·Linux는 로그인 셸($SHELL)."""
    if os.name == "nt":
        for name in ("powershell.exe", "pwsh.exe"):
            path = shutil.which(name)
            if path:
                return path, ["-NoLogo"], "PowerShell"
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return comspec, [], "cmd"
    shell = os.environ.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/bash")
    if not os.path.exists(shell):
        shell = "/bin/sh"
    return shell, ["-l"], os.path.basename(shell)


def terminal_env():
    env = {k: v for k, v in os.environ.items() if not code_runner.SECRET_ENV.search(k) or KEEP_ENV.match(k)}
    env.update(TERM="xterm-256color", COLORTERM="truecolor", TERM_PROGRAM="POSCHAT")
    if os.name != "nt" and not (env.get("LANG") or env.get("LC_ALL")):
        env["LANG"] = "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"   # 한글이 깨지지 않게
    return env


class _PosixPty:
    def __init__(self, argv, cwd, env, cols, rows):
        import pty

        self.master, slave = pty.openpty()
        self._size(slave, cols, rows)
        try:
            self.proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                                         start_new_session=True, close_fds=True)
        except OSError:
            os.close(self.master)
            raise
        finally:
            os.close(slave)
        self.pid = self.proc.pid
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    @staticmethod
    def _size(fd, cols, rows):
        import fcntl
        import struct
        import termios

        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def read(self):
        """받은 글(잠깐 기다려도 없으면 ""), 끝나면 None."""
        import select

        try:
            ready, _, _ = select.select([self.master], [], [], FLUSH_SECONDS)
            if not ready:
                return ""
            data = os.read(self.master, 65536)
        except OSError:   # 자식이 닫히면 EIO
            return None
        if not data:
            return None
        return self._decoder.decode(data)

    def write(self, text):
        data = text.encode("utf-8")
        while data:
            n = os.write(self.master, data)
            data = data[n:]

    def resize(self, cols, rows):
        self._size(self.master, cols, rows)

    def exit_code(self):
        return self.proc.poll()

    def close(self):
        import signal

        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.killpg(self.proc.pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                break
            try:
                self.proc.wait(1.0)
                break
            except subprocess.TimeoutExpired:
                continue
        try:
            os.close(self.master)
        except OSError:
            pass


class _WinPty:
    """pywinpty의 낮은 수준 PTY(ConPTY). 읽기는 막지 않는 방식으로 조금씩 본다."""

    def __init__(self, argv, cwd, env, cols, rows):
        try:
            import winpty
        except ImportError as e:
            raise TerminalError("터미널 구성 요소(pywinpty)가 없습니다. 앱을 다시 설치하세요.") from e
        self.pty = winpty.PTY(cols, rows)
        env_text = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        cmdline = " " + subprocess.list2cmdline(argv[1:]) if len(argv) > 1 else None
        if not self.pty.spawn(argv[0], cmdline=cmdline, cwd=cwd, env=env_text):
            raise TerminalError("셸을 시작하지 못했습니다.")
        self.pid = self.pty.pid

    def read(self):
        try:
            data = self.pty.read(blocking=False)
        except Exception:
            return None
        if data:
            return data
        if self.pty.iseof() or not self.pty.isalive():
            return None
        time.sleep(0.01)
        return ""

    def write(self, text):
        self.pty.write(text)

    def resize(self, cols, rows):
        self.pty.set_size(cols, rows)

    def exit_code(self):
        return None if self.pty.isalive() else self.pty.get_exitstatus()

    def close(self):
        if self.pid:  # 셸이 띄운 프로그램까지 함께 끝낸다
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.pid)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.pty.cancel_io()
        except Exception:
            pass
        self.pty = None


class Session:
    def __init__(self, sid, title, cwd, backend):
        self.id = sid
        self.title = title
        self.cwd = cwd
        self.backend = backend
        self.started = time.time()
        self.alive = True
        self.code = None
        self.scrollback = ""
        self.lock = threading.Lock()

    def to_dict(self, scrollback=False):
        d = {"id": self.id, "title": self.title, "cwd": self.cwd, "alive": self.alive, "code": self.code, "started": self.started}
        if scrollback:
            d["scrollback"] = self.scrollback
        return d


class TerminalManager:
    def __init__(self, on_output=None, on_exit=None):
        self.on_output = on_output or (lambda sid, text: None)
        self.on_exit = on_exit or (lambda sid, code: None)
        self.sessions = {}
        self.lock = threading.Lock()
        self.count = 0

    def open(self, cwd, cols=80, rows=24, shell=None):
        if not SUPPORTED:
            raise TerminalError("이 기기에서는 터미널을 쓸 수 없습니다(PC 앱에서 쓰세요).")
        with self.lock:
            if sum(1 for s in self.sessions.values() if s.alive) >= MAX_TERMINALS:
                raise TerminalError(f"터미널은 {MAX_TERMINALS}개까지 열 수 있습니다. 쓰지 않는 터미널을 닫으세요.")
            self.count += 1
            n = self.count
        cols, rows = _clamp(cols, 2, 500, 80), _clamp(rows, 2, 300, 24)
        if remote_fs.is_remote(cwd):   # 원격(SSH) 작업 폴더: 서버의 로그인 셸을 그 폴더에서 연다
            host, path = remote_fs.split(cwd)
            name = "ssh " + host
            try:
                backend = remote_fs.connection(host).shell(path, cols, rows)
            except OSError as e:
                raise TerminalError(f"원격 터미널을 열지 못했습니다: {e}") from e
            cwd = str(cwd)
        else:
            exe, args, name = shell or default_shell()
            cwd = cwd if cwd and os.path.isdir(cwd) else os.path.expanduser("~")
            try:
                backend = (_WinPty if os.name == "nt" else _PosixPty)([exe, *args], cwd, terminal_env(), cols, rows)
            except OSError as e:
                raise TerminalError(f"셸을 시작하지 못했습니다: {e.strerror or e}") from e
        s = Session("term-" + uuid.uuid4().hex[:8], f"{n}: {name}", cwd, backend)
        with self.lock:
            self.sessions[s.id] = s
        threading.Thread(target=self._pump, args=(s,), daemon=True, name=f"terminal-{s.id}").start()
        return s

    def _get(self, sid):
        s = self.sessions.get(str(sid or ""))
        if s is None:
            raise TerminalError("터미널을 찾지 못했습니다.")
        return s

    def write(self, sid, data):
        s = self._get(sid)
        if not s.alive:
            raise TerminalError("끝난 터미널입니다. 새 터미널을 여세요.")
        text = str(data or "")[:65536]
        try:
            s.backend.write(text)
        except (OSError, EOFError, Exception) as e:   # 셸이 막 끝난 경우
            raise TerminalError(f"터미널에 보내지 못했습니다: {e}") from e

    def resize(self, sid, cols, rows):
        s = self._get(sid)
        if s.alive:
            try:
                s.backend.resize(_clamp(cols, 2, 500, 80), _clamp(rows, 2, 300, 24))
            except Exception:
                pass

    def close(self, sid):
        s = self._get(sid)
        with self.lock:
            self.sessions.pop(s.id, None)
        if s.alive:
            s.alive = False
            try:
                s.backend.close()
            except Exception:
                pass
        return s

    def list(self):
        return [s.to_dict() for s in sorted(self.sessions.values(), key=lambda x: x.started)]

    def get(self, sid, scrollback=True):
        return self._get(sid).to_dict(scrollback)

    def shutdown(self):
        for sid in list(self.sessions):
            try:
                self.close(sid)
            except TerminalError:
                pass

    def _pump(self, s):
        buf, last = [], time.monotonic()

        def flush():
            nonlocal buf, last
            last = time.monotonic()
            if not buf:
                return
            text = "".join(buf)
            buf = []
            with s.lock:
                s.scrollback = (s.scrollback + text)[-SCROLLBACK:]
            try:
                self.on_output(s.id, text)
            except Exception:
                pass

        while s.alive:
            data = s.backend.read()
            if data is None:
                break
            if data:
                buf.append(data)
            # 잠깐 조용해지거나(프롬프트를 기다림) 시간이 지나거나 많이 모이면 보낸다
            if buf and (not data or time.monotonic() - last >= FLUSH_SECONDS or sum(map(len, buf)) > 32768):
                flush()
        flush()
        if s.alive:   # 셸이 스스로 끝났다(exit)
            s.alive = False
            deadline = time.monotonic() + 2
            while s.code is None and time.monotonic() < deadline:
                s.code = s.backend.exit_code()
                if s.code is None:
                    time.sleep(0.05)
            try:
                s.backend.close()
            except Exception:
                pass
        try:
            self.on_exit(s.id, s.code)
        except Exception:
            pass


def selfcheck(timeout=10):
    """설치본 진단: 진짜 셸을 열어 한 줄을 받아 본다(Windows는 ConPTY가 묶였는지까지)."""
    if not SUPPORTED:
        return "SKIP(안드로이드)"
    out, done = [], threading.Event()
    m = TerminalManager(on_output=lambda sid, text: out.append(text), on_exit=lambda sid, code: done.set())
    shell = ((os.environ.get("COMSPEC") or "cmd.exe"), ["/c", "echo poschat-term-ok"], "cmd") if os.name == "nt" \
        else ("/bin/sh", ["-c", "echo poschat-term-ok; sleep 1"], "sh")   # 바로 끝나면 macOS pty가 남은 출력을 버릴 수 있다
    try:
        m.open(os.path.expanduser("~"), 80, 24, shell=shell)
    except TerminalError as e:
        return f"FAIL {e}"
    done.wait(timeout)
    m.shutdown()
    return "OK" if "poschat-term-ok" in "".join(out) else "FAIL 출력 없음"


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default
