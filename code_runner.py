# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15): 실행 패널의 명령 실행기. 사용자가 승인한 명령 하나를 작업 폴더에서 돌리고 출력을 흘려보낸다.

- 셸: Windows는 cmd(에이전트 run과 같다), macOS·Linux는 /bin/sh. 대화형 터미널(PTY·ConPTY)은 아니다(입력 없음).
- 제한: 실행 시간(기본 10분), 화면에 보낼 출력(MAX_STREAM), 기억하는 출력 끝부분(MAX_TAIL). 넘으면 끊거나 줄인다.
- 중지·시간 초과·앱 종료: 프로세스 그룹(POSIX) 또는 프로세스 트리(Windows taskkill /T)를 끝낸다.
- 비밀: API 키·토큰 같은 이름의 환경 변수는 넘기지 않고(runner_mcp와 같다), 출력에 앱이 아는 비밀 값이나 흔한 키 모양이
  보이면 [가림]으로 바꾼 뒤 화면·기록에 남긴다.
- 기록(RunRecord): 명령·작업 폴더·입력 파일·종료 코드·실행 시간·출력 끝부분·출력에서 찾은 소스 위치(파일:줄).
  v1.16 Lab이 실험 실행 기록으로 다시 쓸 수 있게 JSON 한 줄씩 남긴다.

작업 폴더는 명령이 시작하는 위치일 뿐 보안 격리(샌드박스)가 아니다. 명령은 사용자 권한으로 PC 전체에 닿을 수 있다.
"""
import codecs
import json
import locale
import os
import re
import shlex
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

import code_workspace as cw
import privacy

DEFAULT_TIMEOUT = 600
MAX_TIMEOUT = 3600
MAX_STREAM = 2 * 1024 * 1024     # 화면에 흘려보낼 출력(글자 수)
MAX_TAIL = 64 * 1024             # 기록에 남길 끝부분
FLUSH_SECONDS = 0.1
MAX_COMMAND = 4000
MAX_RECORDS = 200
SECRET_ENV = re.compile(r"(?i)(key|token|secret|password|passwd|credential|auth|cookie|session)")
NETWORK_RE = re.compile(r"(?i)\b(curl|wget|ssh|scp|sftp|rsync|ftp|telnet|nc|ncat|ping|git\s+(push|pull|fetch|clone|remote|submodule)|"
                        r"pip3?\s+(install|download)|python3?\s+-m\s+pip\s+install|npm\s+(i|install|ci|publish|update)|yarn(\s+(add|install))?|"
                        r"pnpm\s+(add|install|i)|conda\s+(install|create|update)|apt(-get)?\s+install|brew\s+install|"
                        r"Invoke-WebRequest|iwr|winget|choco|docker\s+(pull|push|run))\b")
DANGER_PATTERNS = [
    (re.compile(r"(?i)\brm\s+(-\w*[rf]\w*\s+)+"), "파일·폴더를 지웁니다(rm -r/-f)"),
    (re.compile(r"(?i)\b(rmdir|rd)\s+/s\b|\bdel\s+(/\w\s+)*/[sq]\b"), "파일·폴더를 지웁니다(del /s, rmdir /s)"),
    (re.compile(r"(?i)\bgit\s+reset\s+--hard\b"), "Git 변경을 되돌릴 수 없게 버립니다(git reset --hard)"),
    (re.compile(r"(?i)\bgit\s+clean\b"), "추적하지 않는 파일을 지웁니다(git clean)"),
    (re.compile(r"(?i)\bgit\s+push\b.*(--force|-f\b)"), "원격 저장소 이력을 덮어씁니다(git push --force)"),
    (re.compile(r"(?i)\bgit\s+(checkout|switch)\b.*(\s-f\b|--force|--discard-changes)"), "변경을 버리고 가지를 바꿉니다"),
    (re.compile(r"(?i)\bgit\s+(rebase|filter-branch|filter-repo)\b|\bgit\s+commit\b.*--amend"), "Git 이력을 고칩니다"),
    (re.compile(r"(?i)\b(mkfs|format|diskpart|dd\s+if=)"), "디스크를 지우거나 덮어쓸 수 있습니다"),
    (re.compile(r"(?i)\b(shutdown|reboot|halt|poweroff)\b"), "컴퓨터를 끄거나 다시 시작합니다"),
    (re.compile(r"(?i)\b(sudo|su\s|runas)\b"), "관리자 권한으로 실행합니다"),
    (re.compile(r"(?i)\bchmod\s+(-R|--recursive)|\bchown\s+(-R|--recursive)"), "여러 파일의 권한을 한꺼번에 바꿉니다"),
    (re.compile(r"(?i)(curl|wget|iwr|Invoke-WebRequest)[^|]*\|\s*(ba|z|)sh\b|\|\s*iex\b"), "내려받은 스크립트를 바로 실행합니다"),
    (re.compile(r"(^|[^>2&])>\s*[^\s&|>]"), "출력으로 파일을 덮어씁니다(>)"),
    (re.compile(r"(?i)\b(reg\s+(add|delete)|setx)\b"), "Windows 설정(레지스트리·환경 변수)을 바꿉니다"),
]
# 출력에서 소스 위치 찾기: gcc/clang·verilator·iverilog·Python traceback·일반 file:line
LOCATION_PATTERNS = [
    re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+)'),
    re.compile(r"%(?:Error|Warning)[^:]*: (?P<path>[^\s:]+):(?P<line>\d+):(?:(?P<col>\d+):)?"),
    re.compile(r"(?P<path>[\w./\\-]+\.[A-Za-z0-9]{1,6}):(?P<line>\d+)(?::(?P<col>\d+))?"),
]
EDA_TOOLS = [
    ("verilator", "verilator --lint-only -Wall design.sv"),
    ("iverilog", "iverilog -g2012 -o sim.out tb.sv design.sv"),
    ("vvp", "vvp sim.out"),
    ("yosys", "yosys -p \"read_verilog -sv design.sv; synth\""),
    ("gtkwave", "gtkwave wave.vcd"),
    ("ngspice", "ngspice -b circuit.sp"),
    ("python", "python script.py"),
    ("python3", "python3 -m pytest"),
    ("gcc", "gcc -Wall -o main main.c"),
    ("g++", "g++ -Wall -std=c++17 -o main main.cpp"),
    ("clang", "clang -Wall -o main main.c"),
    ("make", "make"),
    ("cmake", "cmake -S . -B build"),
    ("node", "node script.js"),
    ("tclsh", "tclsh script.tcl"),
    ("git", "git status"),
]


class RunnerError(Exception):
    pass


def shell_name():
    return "Windows cmd" if os.name == "nt" else "/bin/sh"


def tools():
    """설치된 개발 도구(번들하지 않는다: PATH에서 찾는다)."""
    import shutil

    return [{"name": name, "path": shutil.which(name) or "", "example": example} for name, example in EDA_TOOLS]


def analyze(command):
    """승인 창에 보일 정보: 네트워크를 쓸 수 있는지, 위험할 수 있는 동작."""
    command = str(command or "")
    dangers = [label for rx, label in DANGER_PATTERNS if rx.search(command)]
    return {"network": bool(NETWORK_RE.search(command)), "dangers": dangers, "shell": shell_name()}


def clean_env(extra_secret_names=()):
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k) and k not in extra_secret_names}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    return env


class Masker:
    """출력에서 비밀을 가린다. 조각 경계에 걸친 비밀도 가리도록 끝부분 몇 글자는 다음 조각과 이어서 본다."""

    def __init__(self, secrets=()):
        self.secrets = sorted({s for s in secrets if isinstance(s, str) and len(s) >= 6}, key=len, reverse=True)
        self.keep = max((len(s) for s in self.secrets), default=1) - 1
        self.carry = ""

    def _mask(self, text):
        for s in self.secrets:
            text = text.replace(s, privacy.MASK)
        return privacy.redact_text(text)

    def feed(self, text, final=False, force=False):
        """force: 줄이 끝나지 않았어도(진행률 표시·입력 안내) 비밀 경계만 지켜 내보낸다."""
        text = self.carry + text
        if final or not text:
            self.carry = ""
            return self._mask(text)
        nl = max(text.rfind("\n"), text.rfind("\r"))
        if nl >= 0:
            cut = nl + 1  # 줄 단위로 내보낸다(비밀·키 모양은 줄을 넘지 않는다)
        elif len(text) < 8192 and not force:
            self.carry = text  # 줄이 끝나기를 조금 기다린다
            return ""
        else:
            cut = len(text) - self.keep  # 줄이 끝나지 않은 긴 출력: 끝부분은 다음 조각과 이어서 본다
        for s in self.secrets:  # cut이 비밀 한가운데면 비밀 앞에서 자른다
            start = text.find(s)
            while start != -1:
                if start < cut < start + len(s):
                    cut = start
                start = text.find(s, start + 1)
        cut = max(0, cut)
        self.carry = text[cut:]
        return self._mask(text[:cut])


def find_locations(workspace, text, limit=50):
    """출력의 '파일:줄'을 작업 폴더 안 파일만 골라 [{path, line, col, text}]로."""
    out, seen = [], set()
    try:
        root = cw.root_of(workspace)
    except cw.WorkspaceError:
        return out
    for line in text.splitlines():
        for rx in LOCATION_PATTERNS:
            for m in rx.finditer(line):
                raw = m.group("path")
                try:
                    p = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(root, raw))
                    rel = os.path.relpath(p, root).replace("\\", "/")
                except ValueError:
                    continue
                if rel.startswith("..") or not os.path.isfile(p):
                    continue
                key = (rel, int(m.group("line")))
                if key in seen:
                    continue
                seen.add(key)
                col = m.groupdict().get("col")
                out.append({"path": rel, "line": key[1], "col": int(col) if col else 1, "text": line.strip()[:200]})
                if len(out) >= limit:
                    return out
            if out and out[-1]["text"] == line.strip()[:200]:
                break  # 한 줄에서 앞 규칙이 찾았으면 다음 규칙은 보지 않는다
    return out


def input_files(workspace, command, limit=20):
    """명령에 나온 작업 폴더 안 파일(입력 파일 후보)."""
    try:
        words = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        words = command.split()
    out = []
    for w in words[1:]:
        w = w.strip("\"'")
        if not w or w.startswith("-") or len(out) >= limit:
            continue
        try:
            p = cw.resolve(workspace, w, allow_root=False)
        except cw.WorkspaceError:
            continue
        if p.is_file():
            out.append(cw.clean_rel(w))
    return out


@dataclass
class RunRecord:
    id: str
    command: str
    cwd: str                 # 작업 폴더(절대 경로)
    started: float
    status: str = "running"  # running · done · failed · stopped · timeout · error
    code: object = None
    seconds: float = 0.0
    inputs: list = field(default_factory=list)
    output_tail: str = ""
    output_chars: int = 0
    truncated: bool = False
    locations: list = field(default_factory=list)
    purpose: str = ""
    error: str = ""
    ended: float = 0.0       # 기록까지 다 남긴 시각(0이면 아직)

    def to_dict(self, tail=True):
        d = asdict(self)
        if not tail:
            d.pop("output_tail")
        return d


class RunManager:
    """명령 실행을 맡는다. on_event(dict)로 출력·종료를 알린다(Bridge._push → 큐, 막지 않는다)."""

    def __init__(self, on_event=None, log_path=None, secrets=lambda: ()):
        self.on_event = on_event
        self.log_path = log_path
        self.secrets = secrets
        self._runs = {}
        self._procs = {}
        self._lock = threading.Lock()

    def _emit(self, **event):
        if self.on_event:
            try:
                self.on_event({"type": "code", **event})
            except Exception:
                pass

    def records(self):
        with self._lock:
            return sorted(self._runs.values(), key=lambda r: r.started, reverse=True)

    def get(self, run_id):
        with self._lock:
            r = self._runs.get(str(run_id or ""))
        if r is None:
            raise RunnerError("실행 기록을 찾지 못했습니다.")
        return r

    def running(self):
        with self._lock:
            return [r for r in self._runs.values() if r.status == "running"]

    def start(self, workspace, command, timeout=DEFAULT_TIMEOUT, purpose=""):
        command = str(command or "").strip()
        if not command:
            raise RunnerError("실행할 명령을 입력하세요.")
        if len(command) > MAX_COMMAND or "\x00" in command:
            raise RunnerError("명령이 너무 길거나 쓸 수 없는 글자가 있습니다.")
        root = cw.root_of(workspace)
        if len(self.running()) >= 4:
            raise RunnerError("동시에 4개까지 실행할 수 있습니다. 끝나거나 멈춘 뒤 다시 실행하세요.")
        timeout = max(1, min(MAX_TIMEOUT, int(timeout or DEFAULT_TIMEOUT)))
        masker = Masker(self.secrets())
        rec = RunRecord(id=uuid.uuid4().hex[:12], command=masker._mask(command), cwd=str(root), started=time.time(),
                        inputs=input_files(workspace, command), purpose=str(purpose or "")[:300])
        popen = dict(cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     env=clean_env(), shell=True)
        if os.name == "nt":
            popen["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen["start_new_session"] = True  # 중지할 때 자식까지 한꺼번에
            popen["executable"] = "/bin/sh"
        try:
            proc = subprocess.Popen(command, **popen)
        except OSError as e:
            raise RunnerError(f"명령을 시작하지 못했습니다: {e}")
        with self._lock:
            self._runs[rec.id] = rec
            self._procs[rec.id] = proc
            for old in sorted(self._runs.values(), key=lambda r: r.started)[:max(0, len(self._runs) - MAX_RECORDS)]:
                if old.status != "running":
                    self._runs.pop(old.id, None)
        self._emit(kind="run_start", run=rec.to_dict(tail=False))
        threading.Thread(target=self._pump, args=(rec, proc, masker, timeout, workspace), daemon=True,
                         name=f"code-run-{rec.id}").start()
        return rec

    def _pump(self, rec, proc, masker, timeout, workspace):
        start = time.monotonic()
        deadline = start + timeout
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        fallback = locale.getpreferredencoding(False) or "utf-8"
        pending, tail, sent = [], [], 0
        last_flush = time.monotonic()
        lock = threading.Lock()
        done = threading.Event()

        def flush(final=False, force=False):
            nonlocal pending, sent, last_flush
            with lock:
                text = masker.feed("".join(pending), final=final, force=force)
                pending = []
                last_flush = time.monotonic()
            if not text:
                return
            tail.append(text)
            joined = "".join(tail)
            if len(joined) > MAX_TAIL * 2:
                tail[:] = [joined[-MAX_TAIL:]]
            rec.output_chars += len(text)
            if sent < MAX_STREAM:
                chunk = text[:MAX_STREAM - sent]
                sent += len(chunk)
                self._emit(kind="run_output", id=rec.id, text=chunk)
                if sent >= MAX_STREAM:
                    rec.truncated = True
                    self._emit(kind="run_output", id=rec.id,
                               text=f"\n[출력이 {MAX_STREAM // 1048576}MB를 넘어 화면에 더 보이지 않습니다. 명령은 계속 실행됩니다.]\n")

        def reader():
            nonlocal decoder
            stream = proc.stdout
            while True:
                try:
                    data = stream.read1(65536) if hasattr(stream, "read1") else stream.read(4096)
                except (OSError, ValueError):
                    break
                if not data:
                    break
                try:
                    text = decoder.decode(data)
                except UnicodeDecodeError:
                    # UTF-8이 아닌 출력(Windows cmd의 CP949 등): 이후는 시스템 인코딩으로
                    decoder = codecs.getincrementaldecoder(fallback)("replace")
                    text = decoder.decode(data)
                with lock:
                    pending.append(text)
            done.set()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        status = None
        while not done.wait(FLUSH_SECONDS):
            if pending:
                flush()
            elif masker.carry and time.monotonic() - last_flush > 0.5:
                flush(force=True)  # 줄 바꿈 없이 멈춘 출력도 보이게
            if time.monotonic() > deadline and status is None:
                status = "timeout"
                self._kill(proc)
            if rec.status == "stopping" and status is None:
                status = "stopped"
                self._kill(proc)
        if status is None and rec.status == "stopping":
            status = "stopped"
        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._kill(proc)
            code = proc.wait()
        t.join(2)
        try:
            proc.stdout.close()
        except OSError:
            pass
        try:
            tail_bytes = decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            tail_bytes = ""
        with lock:
            pending.append(tail_bytes)
        flush(final=True)
        rec.code = code
        rec.seconds = round(time.monotonic() - start, 2)
        rec.status = status or ("done" if code == 0 else "failed")
        rec.output_tail = "".join(tail)[-MAX_TAIL:]
        rec.locations = find_locations(workspace, rec.output_tail)
        with self._lock:
            self._procs.pop(rec.id, None)
        self._log(rec)
        rec.ended = time.time()
        self._emit(kind="run_exit", run=rec.to_dict(tail=False))

    def wait(self, run_id, timeout=None):
        """끝날(기록까지 남길) 때까지 기다린다. 끝났으면 True."""
        rec = self.get(run_id)
        end = time.monotonic() + (timeout if timeout is not None else MAX_TIMEOUT + 60)
        while not rec.ended and time.monotonic() < end:
            time.sleep(0.02)
        return bool(rec.ended)

    @staticmethod
    def _kill(proc):
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass

    def stop(self, run_id):
        rec = self.get(run_id)
        if rec.status != "running":
            return rec
        rec.status = "stopping"
        with self._lock:
            proc = self._procs.get(rec.id)
        if proc is not None:
            self._kill(proc)
        return rec

    def shutdown(self):
        """앱 종료: 돌고 있는 명령을 모두 끝낸다(프로세스가 남지 않게)."""
        with self._lock:
            procs = list(self._procs.values())
            for r in self._runs.values():
                if r.status == "running":
                    r.status = "stopping"
        for proc in procs:
            self._kill(proc)

    def _log(self, rec):
        if not self.log_path:
            return
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            data = rec.to_dict(tail=False)
            data["output_tail"] = rec.output_tail[-4000:]
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except OSError:
            pass
