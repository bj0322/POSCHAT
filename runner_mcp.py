"""내장 MCP 서버 python·ssh: 코드·원격 명령 실행(커넥터 → 에이전트 자동화). 기본 비활성, 데스크톱 전용.

임의 코드 실행은 위험하므로
- 커넥터를 켜야만 도구가 보이고, 도구 종류가 exec라서 '모두 자동 허용' 설정이어도 매번 승인을 받는다.
- 승인 창에 실행 대상(인터프리터·격리 방식·원격 호스트·사용자·작업 폴더)을 앱이 만든 글로 보인다(preview).
- 시간 제한, POSIX에서는 리소스 제한(CPU 시간·메모리·파일 크기), 작업 폴더를 현재 폴더로, 비밀처럼 보이는 환경 변수는 지운다.
- 격리: 설정에서 Docker를 고르면 `docker run --rm --network none`(작업 폴더만 /work로 연결)으로 실행한다.
  고르지 않으면 이 PC의 사용자 권한으로 실행된다(샌드박스가 아니다). 이 사실을 승인 창에 함께 적는다.
- SSH는 설정한 호스트 별칭만, BatchMode·StrictHostKeyChecking=yes(처음 보는 호스트 키를 자동으로 믿지 않음)로 실행하고,
  허용 명령 접두어 목록이 있으면 그 명령만, 셸 연결 문자(; && | ` $( > < 줄바꿈)는 막는다.
- 실행한 코드·명령과 결과 앞부분을 logs/exec.jsonl에 남긴다(비밀 패턴은 가림).

설정(config.json, 비밀 없음)
    "automation": {"python": {"interpreter": "", "isolation": "none|docker", "docker_image": "python:3.12-slim",
                              "timeout": 120, "memory_mb": 2048},
                   "ssh": {"timeout": 120, "hosts": {"gpu1": {"host": "...", "user": "...", "port": 22,
                           "identity_file": "", "cwd": "", "allowed_commands": ["nvidia-smi", "python "]}}}}
"""
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import privacy
import storage
from office_mcp import INT, STR, ToolFailure, _root, _schema

MAX_OUTPUT = 20000
EXEC = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}
READ = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
SECRET_ENV = re.compile(r"(?i)(key|token|secret|password|passwd|credential|auth)")
SHELL_META = re.compile(r"[;&|`<>\n\r]|\$\(")
HOST_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


def _settings(section):
    return ((storage.load_config().get("automation") or {}).get(section) or {})


def _limit(value, default, hi):
    try:
        return max(1, min(hi, int(value or default)))
    except (TypeError, ValueError):
        return default


def _clean_env():
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def _limits(cpu_seconds, memory_mb):
    """POSIX 하위 프로세스에 CPU 시간·주소 공간·파일 크기 제한을 건다(Windows는 시간 제한만)."""
    if os.name != "posix":
        return None

    def apply():
        import resource

        wanted = [(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5)),
                  (resource.RLIMIT_FSIZE, (512 * 1024 * 1024, 512 * 1024 * 1024))]
        if memory_mb:
            wanted.append((resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024)))
        for kind, value in wanted:
            try:
                resource.setrlimit(kind, value)
            except (ValueError, OSError):
                pass  # macOS는 RLIMIT_AS를 받지 않는다: 시간 제한은 그대로 걸린다
    return apply


def _run(cmd, timeout, cwd, stdin_text=None, limits=None):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    start = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_clean_env(), creationflags=flags,
                            start_new_session=os.name == "posix", preexec_fn=limits)
    try:
        out, err = proc.communicate(stdin_text.encode("utf-8") if stdin_text is not None else None, timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)  # 자식 프로세스까지
            else:
                proc.kill()
        except OSError:
            pass
        out, err = proc.communicate()
    return {"code": None if timed_out else proc.returncode, "stdout": out.decode("utf-8", errors="replace"),
            "stderr": err.decode("utf-8", errors="replace"), "timed_out": timed_out,
            "seconds": round(time.monotonic() - start, 2)}


def _format(result, label):
    text = result["stdout"]
    if result["stderr"].strip():
        text += ("\n" if text else "") + "[stderr]\n" + result["stderr"]
    text = text.strip() or "(출력 없음)"
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT // 2] + f"\n…({len(text):,}자 중 가운데를 생략)…\n" + text[-MAX_OUTPUT // 2:]
    status = f"시간 초과로 중단({result['seconds']}초)" if result["timed_out"] else f"종료 코드 {result['code']} ({result['seconds']}초)"
    return f"{label}: {status}\n{text}"


def _log(kind, target, payload, result):
    record = {"ts": round(time.time(), 3), "kind": kind, "target": target,
              "input": privacy.redact_text(payload)[:20000], "code": result.get("code"),
              "timed_out": result.get("timed_out"), "seconds": result.get("seconds"),
              "output": privacy.redact_text((result.get("stdout", "") + result.get("stderr", ""))[:4000])}
    path = storage.APP_DIR / "logs" / "exec.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ---- Python ----

def interpreter():
    """쓸 Python 실행 파일. 설정 → PATH의 python3·python·py 순. 앱 실행 파일(PyInstaller)은 쓰지 않는다."""
    configured = str(_settings("python").get("interpreter") or "").strip()
    if configured:
        if not os.path.isfile(configured):
            raise ToolFailure(f"설정한 Python을 찾지 못했습니다: {configured}")
        return configured
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("python3", "python", "py"):
        found = shutil.which(name)
        if found and "WindowsApps" not in found:  # Microsoft Store 안내용 가짜 python.exe
            return found
    raise ToolFailure("이 PC에서 Python을 찾지 못했습니다. python.org에서 설치하거나 연결·도구 → 에이전트 자동화에서 경로를 넣으세요.")


def _python_plan():
    s = _settings("python")
    isolation = "docker" if s.get("isolation") == "docker" else "none"
    return {"isolation": isolation, "timeout": _limit(s.get("timeout"), 120, 3600), "memory_mb": _limit(s.get("memory_mb"), 2048, 65536),
            "image": str(s.get("docker_image") or "python:3.12-slim")}


def preview_python(arguments, root=None):
    plan = _python_plan()
    try:
        target = ("Docker " + plan["image"] + " (네트워크 없음, 작업 폴더만 /work로 연결)") if plan["isolation"] == "docker" \
            else interpreter() + " (이 PC의 사용자 권한으로 실행 — 샌드박스 아님)"
    except ToolFailure as e:
        target = str(e)
    timeout = _limit(arguments.get("timeout"), plan["timeout"], plan["timeout"])
    return (f"실행 대상: {target}\n작업 폴더: {root or _root()}\n시간 제한: {timeout}초"
            + (f" · 메모리 {plan['memory_mb']}MB" if os.name == "posix" or plan["isolation"] == "docker" else ""))


def python_info():
    plan = _python_plan()
    exe = interpreter()
    r = _run([exe, "-I", "-c", "import sys, platform; print(sys.version); print(platform.platform())"], 20, str(_root()))
    lines = [f"Python: {exe}", r["stdout"].strip(), f"격리: {plan['isolation']} · 시간 제한 {plan['timeout']}초"]
    nb = _run([exe, "-I", "-c", "import nbconvert, nbformat, ipykernel"], 20, str(_root()))
    lines.append("Jupyter 노트북 실행: " + ("가능" if nb["code"] == 0 else "불가(nbconvert·ipykernel 설치 필요)"))
    if plan["isolation"] == "docker":
        lines.append("Docker: " + ("있음" if shutil.which("docker") else "없음 — 설정에서 격리를 끄거나 Docker를 설치하세요"))
    return "\n".join(lines)


def python_run(code, timeout=None):
    code = str(code or "")
    if not code.strip():
        raise ToolFailure("code가 비어 있습니다.")
    plan = _python_plan()
    timeout = _limit(timeout, plan["timeout"], plan["timeout"])
    root = str(_root())
    if plan["isolation"] == "docker":
        docker = shutil.which("docker")
        if not docker:
            raise ToolFailure("Docker를 찾지 못했습니다. 설정에서 격리를 끄거나 Docker를 설치하세요.")
        cmd = [docker, "run", "--rm", "-i", "--network", "none", "--memory", f"{plan['memory_mb']}m", "--cpus", "1",
               "--pids-limit", "256", "-v", f"{root}:/work", "-w", "/work", plan["image"], "python", "-I", "-"]
        result = _run(cmd, timeout + 30, root, stdin_text=code)
        target = f"docker:{plan['image']}"
    else:
        exe = interpreter()
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            script = f.name
        try:
            result = _run([exe, "-I", script], timeout, root, limits=_limits(timeout, plan["memory_mb"]))
        finally:
            os.unlink(script)
        target = exe
    _log("python", target, code, result)
    return _format(result, "Python")


def run_notebook(path, timeout=None):
    """작업 폴더의 .ipynb를 실행해 <이름>.executed.ipynb로 저장하고 오류·마지막 출력을 요약한다."""
    root = _root()
    p = (root / str(path)).resolve()
    if p != root and root not in p.parents:
        raise ToolFailure("작업 폴더 밖의 노트북은 실행하지 않습니다.")
    if p.suffix != ".ipynb" or not p.is_file():
        raise ToolFailure(f"노트북(.ipynb)이 없습니다: {path}")
    plan = _python_plan()
    timeout = _limit(timeout, plan["timeout"], plan["timeout"])
    out = p.with_name(p.stem + ".executed.ipynb")
    cmd = [interpreter(), "-I", "-m", "nbconvert", "--to", "notebook", "--execute", f"--ExecutePreprocessor.timeout={timeout}",
           "--output", out.name, str(p)]
    result = _run(cmd, timeout + 60, str(p.parent), limits=_limits(timeout + 60, plan["memory_mb"]))
    _log("notebook", str(p), " ".join(cmd), result)
    if result["code"] != 0 or not out.is_file():
        return _format(result, "노트북 실행 실패(nbconvert·ipykernel이 설치돼 있는지 확인)")
    nb = json.loads(out.read_text(encoding="utf-8"))
    errors, last = [], ""
    for i, cell in enumerate(nb.get("cells") or [], 1):
        for o in cell.get("outputs") or []:
            if o.get("output_type") == "error":
                errors.append(f"셀 {i}: {o.get('ename')}: {o.get('evalue')}")
            elif o.get("output_type") == "stream":
                last = "".join(o.get("text") or "")
            elif o.get("output_type") in ("execute_result", "display_data"):
                last = "".join((o.get("data") or {}).get("text/plain") or "")
    return (f"노트북을 실행했습니다: {out.relative_to(root).as_posix()} ({result['seconds']}초)\n"
            + ("오류:\n" + "\n".join(errors) if errors else "오류 없음") + (f"\n마지막 출력:\n{last[-3000:]}" if last else ""))


# ---- SSH ----

def _hosts():
    hosts = _settings("ssh").get("hosts") or {}
    return {k: v for k, v in hosts.items() if ALIAS_RE.match(str(k)) and isinstance(v, dict)}


def _host(alias):
    h = _hosts().get(str(alias))
    if not h:
        raise ToolFailure(f"설정에 없는 호스트입니다: {alias}. 연결·도구 → 에이전트 자동화에서 별칭을 먼저 등록하세요.")
    if not HOST_RE.match(str(h.get("host", ""))) or (h.get("user") and not HOST_RE.match(str(h["user"]))):
        raise ToolFailure(f"호스트 설정이 잘못되었습니다: {alias}")
    return h


def check_command(h, command):
    command = str(command or "").strip()
    if not command:
        raise ToolFailure("command가 비어 있습니다.")
    if not h.get("allow_shell") and SHELL_META.search(command):
        raise ToolFailure("명령에 셸 연결 문자(; && | ` $( > < 줄바꿈)를 쓸 수 없습니다. 이 호스트 설정에서 allow_shell을 켜야 합니다.")
    allowed = [str(a) for a in h.get("allowed_commands") or [] if str(a).strip()]
    if allowed and not any(command == a.strip() or command.startswith(a) for a in allowed):
        raise ToolFailure(f"허용 목록에 없는 명령입니다. 허용: {', '.join(allowed)}")
    return command


def _ssh_cmd(h, command):
    ssh = shutil.which("ssh")
    if not ssh:
        raise ToolFailure("ssh 명령을 찾지 못했습니다(Windows는 'OpenSSH 클라이언트' 선택 기능을 설치하세요).")
    cmd = [ssh, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10"]
    if h.get("port"):
        cmd += ["-p", str(int(h["port"]))]
    if h.get("identity_file"):
        cmd += ["-i", os.path.expanduser(str(h["identity_file"]))]
    target = f"{h['user']}@{h['host']}" if h.get("user") else h["host"]
    remote = f"cd {shlex.quote(str(h['cwd']))} && {command}" if h.get("cwd") else command
    return cmd + [target, "--", remote], target


def preview_ssh(arguments, root=None):
    try:
        h = _host(arguments.get("host"))
        check = "통과"
        try:
            check_command(h, arguments.get("command"))
        except ToolFailure as e:
            check = f"막힘 — {e}"
        target = (f"{h.get('user') + '@' if h.get('user') else ''}{h['host']}:{h.get('port') or 22}")
        return (f"원격 호스트: {target} (별칭 {arguments.get('host')})\n원격 작업 폴더: {h.get('cwd') or '(로그인 폴더)'}\n"
                f"허용 목록 검사: {check}\n시간 제한: {_limit(_settings('ssh').get('timeout'), 120, 3600)}초")
    except ToolFailure as e:
        return f"실행 대상을 확인하지 못했습니다: {e}"


def ssh_hosts():
    hosts = _hosts()
    if not hosts:
        return "등록한 SSH 호스트가 없습니다. 연결·도구 → 에이전트 자동화에서 등록하세요."
    lines = ["SSH 호스트(별칭)"]
    for alias, h in hosts.items():
        allowed = ", ".join(h.get("allowed_commands") or []) or "제한 없음"
        lines.append(f"- {alias}: {h.get('user') + '@' if h.get('user') else ''}{h.get('host')}:{h.get('port') or 22} "
                     f"· 작업 폴더 {h.get('cwd') or '-'} · 허용 명령: {allowed}")
    return "\n".join(lines)


def ssh_run(host, command, timeout=None):
    h = _host(host)
    command = check_command(h, command)
    limit = _limit(_settings("ssh").get("timeout"), 120, 3600)
    timeout = _limit(timeout, limit, limit)
    cmd, target = _ssh_cmd(h, command)
    result = _run(cmd, timeout, str(_root()))
    _log("ssh", target, command, result)
    text = _format(result, f"SSH {target}")
    if result["code"] == 255 and "Host key verification failed" in result["stderr"]:
        text += "\n\n처음 연결하는 호스트입니다. 터미널에서 직접 한 번 ssh로 접속해 호스트 키를 확인·저장한 뒤 다시 시도하세요."
    return text


PREVIEWS = {("python", "python_run"): preview_python, ("python", "run_notebook"): preview_python,
            ("ssh", "run"): preview_ssh}


def preview(server, tool, arguments, root=None):
    """승인 창에 보일 실행 대상(앱이 설정에서 만든 글). 앱 프로세스에서 부르므로 작업 폴더를 받는다."""
    fn = PREVIEWS.get((server, tool))
    return fn(arguments or {}, root) if fn else ""


PYTHON_TOOLS = {
    "python_info": (python_info, "쓸 Python 버전·격리 방식·Jupyter 가능 여부를 봅니다.", _schema({}, []), READ),
    "python_run": (python_run, "Python 코드를 작업 폴더에서 실행합니다(사용자 승인 필요, 시간 제한). 결과 파일은 작업 폴더에 쓰세요. "
                               "데이터 분석·계산·그래프 저장에 쓰세요.",
                   _schema({"code": STR, "timeout": INT}, ["code"]), EXEC),
    "run_notebook": (run_notebook, "작업 폴더의 Jupyter 노트북(.ipynb)을 실행해 <이름>.executed.ipynb로 저장하고 오류와 마지막 출력을 "
                                   "요약합니다(사용자 승인 필요, nbconvert 필요).",
                     _schema({"path": STR, "timeout": INT}, ["path"]), EXEC),
}
SSH_TOOLS = {
    "hosts": (ssh_hosts, "등록한 SSH 호스트 별칭과 허용 명령을 봅니다.", _schema({}, []), READ),
    "run": (ssh_run, "등록한 원격 호스트에서 명령을 실행합니다(사용자 승인 필요). host는 별칭. 허용 목록의 명령만 됩니다.",
            _schema({"host": STR, "command": STR, "timeout": INT}, ["host", "command"]), EXEC),
}
