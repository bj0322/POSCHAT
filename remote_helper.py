# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT 원격 도우미(1.18): SSH 서버에서 도는 작은 파이썬 프로그램. 앱이 SSH로 실행하고, 표준 입출력으로 JSON 한 줄씩 주고받는다.

- 서버에 아무것도 설치하지 않는다. 앱이 이 파일과 remote_fs·code_workspace·code_git·code_project의 소스를 보내 메모리에서 실행한다
  (remote_client.bundle). 연결이 끊기면(표준 입력이 닫히면) 띄운 명령을 모두 끝내고 스스로 끝난다.
- 하는 일: 위 모듈의 함수 호출(작업 폴더 규칙은 그 모듈이 지킨다), 파일 기본 작업(fs.*), 에이전트 찾기(agent.*),
  명령 실행과 출력 흘려보내기(proc.*). 서버의 사용자 권한으로 돈다(앱이 SSH로 할 수 있는 것보다 더 하지 않는다).
- Python 3.6 이상(CentOS 7·Ubuntu 18.04의 python3)에서 돌아야 한다. 새 문법을 쓰지 않는다.
"""
import base64
import codecs
import fnmatch
import getpass
import json
import os
import posixpath
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import remote_fs

PROTO = 1
MODULES = ("code_workspace", "code_git", "code_project")
MAX_READ = 64 * 1024 * 1024
MAX_WALK = 50000
TEXT_SNIFF = 2048


def info():
    return {"proto": PROTO, "python": "{}.{}.{}".format(*sys.version_info[:3]), "platform": sys.platform,
            "home": os.path.expanduser("~"), "user": _user(), "host": socket.gethostname(),
            "shell": os.environ.get("SHELL") or "/bin/sh", "git": shutil.which("git") is not None, "pid": os.getpid()}


def _user():
    try:
        return getpass.getuser()
    except Exception:
        return ""


# ---- 파일 기본 작업(RPath가 부른다) ----

def fs_realpath(path):
    return os.path.realpath(path)


def fs_stat(path, follow=True):
    st = os.stat(path) if follow else os.lstat(path)
    return remote_fs.StatResult.of(st)


def fs_kind(path, follow=True):
    try:
        st = os.stat(path) if follow else os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode):
        return "link"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def fs_read(path):
    size = os.path.getsize(path)
    if size > MAX_READ:
        raise OSError(27, "파일이 너무 큽니다({:.0f}MB)".format(size / 1048576), path)
    with open(path, "rb") as f:
        return f.read()


def fs_write(path, data):
    import code_workspace
    code_workspace.atomic_write(Path(path), data)


def fs_mkdir(path, parents=False, exist_ok=False):
    Path(path).mkdir(parents=parents, exist_ok=exist_ok)


def fs_unlink(path, missing_ok=False):
    try:
        os.unlink(path)
    except FileNotFoundError:
        if not missing_ok:
            raise


def fs_rmdir(path):
    os.rmdir(path)


def fs_listdir(path):
    return sorted(os.listdir(path))


def fs_glob(path, pattern):
    return [p.as_posix() for p in sorted(Path(path).glob(pattern))[:5000]]


def fs_walk(root, skip_dirs=(), skip_hidden=True, limit=MAX_WALK):
    """파일만 [(경로, stat)] — 에이전트의 _iter_files와 같은 순서·같은 거르기."""
    skip = set(skip_dirs or ())
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not (skip_hidden and d.startswith(".")))
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            try:
                st = os.stat(p)
            except OSError:
                st = None
            out.append([p, remote_fs.StatResult.of(st) if st is not None else None])
            if len(out) >= limit:
                return out
    return out


def fs_tree(root, skip_dirs=(), limit=500, base=None):
    """에이전트 list 단계: ['상대/폴더/', '상대/파일 (크기 bytes)'] — agent.Agent._tool_list와 같은 꼴(base 기준 상대 경로)."""
    skip = set(skip_dirs or ())
    base = base or root
    lines = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.startswith("."))
        for d in dirnames:
            lines.append(_rel(os.path.join(dirpath, d), base) + "/")
        for f in sorted(filenames):
            try:
                size = os.stat(os.path.join(dirpath, f)).st_size
            except OSError:
                continue
            lines.append("{} ({:,} bytes)".format(_rel(os.path.join(dirpath, f), base), size))
        if len(lines) >= limit:
            return lines[:limit], True
    return lines, False


def _rel(path, root):
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    return "." if rel == "." else rel


def fs_dirs(path=""):
    """폴더 고르기 창: path(비면 홈)의 하위 폴더."""
    target = os.path.realpath(os.path.expanduser(path or "~"))
    if not os.path.isdir(target):
        raise FileNotFoundError(2, "폴더가 없습니다", path)
    dirs = []
    try:
        names = sorted(os.listdir(target), key=lambda n: (n.startswith("."), n.lower()))
    except OSError as e:
        raise PermissionError(e.errno or 13, "폴더를 읽지 못했습니다: {}".format(e.strerror or e), target)
    for name in names[:3000]:
        p = os.path.join(target, name)
        try:
            if os.path.isdir(p):
                dirs.append({"name": name, "hidden": name.startswith("."), "link": os.path.islink(p)})
        except OSError:
            continue
    git = os.path.isdir(os.path.join(target, ".git"))
    return {"path": target, "parent": posixpath.dirname(target) if target != "/" else "", "dirs": dirs, "git": git,
            "home": os.path.expanduser("~")}


# ---- 에이전트 찾기(서버에서 한 번에) ----

def agent_search(root, pattern, glob="**/*", skip_dirs=(), max_bytes=2 * 1024 * 1024, documents=()):
    """agent.Agent._tool_search와 같은 결과를 서버에서. 문서 파일(PDF 등)은 건너뛰고 그 수를 돌려준다."""
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    docs = set(documents or ())
    matches, skipped_docs = [], 0
    for path, _st in fs_walk(root, skip_dirs):
        rel = _rel(path, root)
        name = os.path.basename(path)
        if glob not in ("**/*", "*") and not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(name, glob):
            continue
        if os.path.splitext(name)[1].lower() in docs:
            skipped_docs += 1
            continue
        try:
            if os.path.getsize(path) > max_bytes:
                continue
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        if b"\x00" in raw[:TEXT_SNIFF]:
            continue
        text = _decode(raw)
        for no, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                matches.append("{}:{}: {}".format(rel, no, line.strip()[:200]))
                if len(matches) >= 100:
                    break
        if len(matches) >= 100:
            matches.append("... (100개에서 중단)")
            break
    return {"matches": matches, "skipped_documents": skipped_docs}


def _decode(raw):
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---- 명령 실행 도우미(code_runner가 쓰는 확인) ----

def runner_input_files(root, words, limit=20):
    import code_workspace as cw
    out = []
    for w in words:
        if len(out) >= limit:
            break
        try:
            p = cw.resolve(root, w, allow_root=False)
        except cw.WorkspaceError:
            continue
        if p.is_file():
            out.append(cw.clean_rel(w))
    return out


def runner_locations(root, raws):
    """출력에 나온 경로들 → {경로: 작업 폴더 기준 상대 경로 또는 None}."""
    out = {}
    for raw in list(raws)[:500]:
        try:
            p = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(root, raw))
            rel = os.path.relpath(p, root).replace(os.sep, "/")
        except ValueError:
            out[raw] = None
            continue
        out[raw] = rel if not rel.startswith("..") and os.path.isfile(p) else None
    return out


# ---- 도우미 본체 ----

class Helper:
    def __init__(self, rfile, wfile):
        self.rfile = rfile
        self.wfile = wfile
        self.wlock = threading.Lock()
        self.procs = {}
        self.plock = threading.Lock()

    def send(self, obj):
        data = (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        with self.wlock:
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except (OSError, ValueError):
                pass

    def lookup(self, method):
        group, _, name = str(method).partition(".")
        if not name or name.startswith("__"):
            raise ValueError("알 수 없는 요청: {}".format(method))
        if group in MODULES:
            fn = getattr(sys.modules[group], name, None)
        elif group in ("fs", "agent", "runner"):
            fn = globals().get("{}_{}".format(group, name))
        elif group == "proc":
            fn = getattr(self, "proc_" + name, None)
        elif method == "sys.info":
            fn = info
        else:
            fn = None
        if not callable(fn):
            raise ValueError("알 수 없는 요청: {}".format(method))
        return fn

    def handle(self, req):
        rid = req.get("id")
        try:
            fn = self.lookup(req.get("m"))
            args = remote_fs.decode(req.get("a") or [])
            kwargs = remote_fs.decode(req.get("k") or {})
            result = fn(*args, **kwargs)
            self.send({"id": rid, "r": remote_fs.encode(result)})
        except Exception as e:
            self.send({"id": rid, "e": remote_fs.error_dict(e)})

    def serve(self):
        self.send({"poschat": "ready", "info": info()})
        try:
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                threading.Thread(target=self.handle, args=(req,), daemon=True).start()
        finally:
            self.proc_stop_all()

    # ---- 명령 ----

    def proc_start(self, pid, cwd, command, extra_env=None, secret_pattern=""):
        """명령을 셸로 실행하고 출력(표준 출력+오류)을 이벤트로 흘려보낸다. 비밀 이름의 환경 변수는 넘기지 않는다."""
        rx = re.compile(secret_pattern, re.I) if secret_pattern else None
        env = {k: v for k, v in os.environ.items() if not (rx and rx.search(k))}
        for k, v in (extra_env or {}).items():
            if not (rx and rx.search(str(k))):
                env[str(k)] = str(v)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        shell = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
        proc = subprocess.Popen(command, shell=True, executable=shell, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        with self.plock:
            self.procs[pid] = proc

        def reader():
            stream = proc.stdout
            while True:
                try:
                    data = stream.read1(65536) if hasattr(stream, "read1") else stream.read(4096)
                except (OSError, ValueError):
                    break
                if not data:
                    break
                self.send({"ev": "out", "p": pid, "d": base64.b64encode(data).decode("ascii")})
            self.send({"ev": "eof", "p": pid})

        def waiter():
            code = proc.wait()
            with self.plock:
                self.procs.pop(pid, None)
            self.send({"ev": "exit", "p": pid, "c": code})

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=waiter, daemon=True).start()
        return {"pid": proc.pid}

    def proc_stop(self, pid):
        with self.plock:
            proc = self.procs.get(pid)
        if proc is not None:
            _kill_group(proc)
        return True

    def proc_stop_all(self):
        with self.plock:
            procs = list(self.procs.values())
        for proc in procs:
            _kill_group(proc, wait=0.5)


def _kill_group(proc, wait=2.0):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
        if sig == signal.SIGTERM:
            end = time.time() + wait
            while proc.poll() is None and time.time() < end:
                time.sleep(0.05)
            time.sleep(0.1)


def main():
    rfile = sys.stdin.buffer
    wfile = sys.stdout.buffer
    # 셸 시작 파일이 무엇을 출력해도 앱과의 통로를 더럽히지 않게: 이후의 print는 표준 오류로
    sys.stdout = codecs.getwriter("utf-8")(sys.stderr.buffer)
    Helper(rfile, wfile).serve()


# 앱이 보내는 시작 코드(remote_client.bundle). 위의 모듈을 메모리에 올리고 main()을 부른다.
BOOT = r'''
import sys, types
if sys.version_info < (3, 6):
    sys.stdout.write('{"poschat": "fatal", "error": "python"}\n')
    sys.stdout.flush()
    sys.exit(3)
import subprocess
if sys.version_info < (3, 7):
    _run = subprocess.run

    def _run37(*a, **k):
        if k.pop("capture_output", False):
            k["stdout"] = subprocess.PIPE
            k["stderr"] = subprocess.PIPE
        if "text" in k:
            k["universal_newlines"] = k.pop("text")
        return _run(*a, **k)
    subprocess.run = _run37
for _name, _src in B["modules"]:
    _m = types.ModuleType(_name)
    _m.__file__ = "<poschat " + _name + ">"
    sys.modules[_name] = _m
    exec(compile(_src, _m.__file__, "exec"), _m.__dict__)
sys.modules["remote_helper"].main()
'''
