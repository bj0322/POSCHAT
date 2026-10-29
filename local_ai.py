# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""로컬 AI(1.17): 이 PC에서 도는 모델 실행기(Ollama)에 연결한다. 앱은 실행기나 모델을 함께 설치하지 않는다.

- LocalModelProvider: 로컬 실행기의 공통 꼴(is_available·list_models·capabilities·generate·stream·health_check).
  지금은 OllamaProvider 하나다. 나중에 llama.cpp 서버(OpenAI 호환 /v1/chat/completions)를 같은 꼴로 더할 수 있다.
- 주소는 기본 http://127.0.0.1:11434(이 PC)만. 다른 PC의 Ollama는 사용자가 설정에서 '원격 허용'을 켰을 때만 쓰고,
  링크 로컬(169.254.x 클라우드 메타데이터 등)·0.0.0.0·멀티캐스트는 언제나 막는다. 모든 요청은 리다이렉트를 따라가지 않고
  프록시·.netrc를 쓰지 않는다(trust_env=False). 로컬 요청에는 POSTECH·Claude API 키를 넣지 않는다.
- 모델 기능(글·이미지·도구 호출·구조화 출력·추론)과 문맥 길이는 /api/show가 알려 준 대로만 쓴다(모델 이름으로 짐작하지 않는다).
- 모델 받기(/api/pull)는 사용자가 누를 때만. 받기 전에 Ollama 공개 저장소의 목록(manifest)으로 크기와 라이선스를 보여 준다.
- 로컬 서버의 응답도 믿지 않는다: 크기를 제한하고, 형식이 틀리면 오류로 다룬다. 모델이 쓴 글은 그냥 글이다(권한 없음).
- 안드로이드에서는 쓸 수 없다(SUPPORTED=False). 화면은 '쓸 수 없음'으로 보인다.
"""
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
REGISTRY = "https://registry.ollama.ai"
LIBRARY_URL = "https://ollama.com/library"
CONNECT_TIMEOUT = 3
MAX_REPLY_CHARS = 400_000          # 한 답변의 상한(로컬 서버가 끝없이 보내도 앱이 멈추지 않게)
MAX_LINE_BYTES = 1_000_000         # 스트림 한 줄의 상한
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*(/[A-Za-z0-9][A-Za-z0-9._\-]*)?(:[A-Za-z0-9][A-Za-z0-9._\-]*)?$")
METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data", "metadata.azure.com"}
ANDROID = sys.platform == "android" or hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ
SUPPORTED = not ANDROID


class LocalAIError(Exception):
    """로컬 AI 오류. kind: unavailable(실행기 없음·꺼짐) | model(모델 없음·기능 없음) | timeout | context | resource |
    blocked(주소 정책) | format(응답 형식) | cancelled | error"""

    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind


@dataclass
class LocalRequest:
    model: str
    prompt: str
    images: list = field(default_factory=list)   # [(MIME, base64)]
    timeout: float = 300.0                      # 전체 시간 제한(초)
    num_ctx: int = 0                            # 0이면 실행기 기본값
    max_tokens: int = 0                         # 0이면 제한 없음(num_predict)
    json_format: bool = False                   # 구조화 출력(지원하는 모델만)


@dataclass
class LocalResult:
    text: str
    model: str
    done_reason: str = ""          # stop | length | cancelled
    input_tokens: int = 0
    output_tokens: int = 0
    ms: int = 0
    load_ms: int = 0
    tokens_per_s: float = 0.0


class LocalModelProvider:
    """로컬 모델 실행기의 공통 꼴. 메서드는 작업 스레드에서 부른다(네트워크를 기다린다)."""

    name = "local"

    def is_available(self):
        raise NotImplementedError

    def health_check(self):
        raise NotImplementedError

    def list_models(self):
        raise NotImplementedError

    def capabilities(self, model_id):
        raise NotImplementedError

    def generate(self, request):
        return self.stream(request, None, None)

    def stream(self, request, on_delta, cancelled):
        raise NotImplementedError


# ---- 주소 정책 ----

def _bad_ip(ip):
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved or str(ip) in ("100.100.100.200",)


def check_endpoint(url, allow_remote=False, resolve=True):
    """(정리한 주소, 루프백 여부). 쓸 수 없으면 LocalAIError(kind=blocked).

    - 이 PC(127.0.0.1·::1·localhost)는 언제나 된다. localhost는 DNS를 거치지 않게 127.0.0.1로 바꾼다.
    - 다른 호스트는 allow_remote일 때만. 공개 인터넷 주소는 https만, 사설망(192.168.x 등)은 http도 된다.
    - 링크 로컬(169.254.x)·0.0.0.0·멀티캐스트·클라우드 메타데이터 이름은 언제나 막는다. 이름은 풀어서 나온 주소도 같은 규칙으로 본다.
    """
    text = str(url or "").strip() or DEFAULT_ENDPOINT
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise LocalAIError("로컬 AI 주소 형식이 올바르지 않습니다.", "blocked")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LocalAIError("로컬 AI 주소는 http:// 또는 https://로 시작해야 합니다(예: http://127.0.0.1:11434).", "blocked")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path.strip("/"):
        raise LocalAIError("로컬 AI 주소에는 호스트와 포트만 넣으세요(경로·계정·쿼리 없이).", "blocked")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost":
        host = "127.0.0.1"
    netloc = (f"[{host}]" if ":" in host else host) + (f":{port}" if port else "")
    clean = f"{parts.scheme}://{netloc}"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and ip.is_loopback:
        return clean, True
    if host in METADATA_HOSTS or host.endswith(".internal") and host.startswith("metadata"):
        raise LocalAIError("클라우드 메타데이터 주소에는 연결하지 않습니다.", "blocked")
    if ip is not None and _bad_ip(ip):
        raise LocalAIError("이 주소(링크 로컬·0.0.0.0·멀티캐스트)에는 연결하지 않습니다.", "blocked")
    if not allow_remote:
        raise LocalAIError("이 PC가 아닌 주소입니다. 다른 PC의 Ollama를 쓰려면 'AI 실행 정책 → 원격 Ollama 허용'을 켜세요.", "blocked")
    addrs = [ip] if ip is not None else []
    if ip is None and resolve:
        try:
            infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
            addrs = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
        except (OSError, ValueError):
            raise LocalAIError(f"로컬 AI 주소의 이름({host})을 찾지 못했습니다.", "unavailable")
    if any(_bad_ip(a) for a in addrs):
        raise LocalAIError("이 이름은 링크 로컬·메타데이터 주소로 풀립니다. 연결하지 않습니다.", "blocked")
    public = any(not (a.is_private or a.is_loopback) for a in addrs) or (ip is None and not addrs)
    if public and parts.scheme != "https":
        raise LocalAIError("인터넷의 원격 Ollama는 https 주소만 씁니다(주고받는 글이 보이지 않게).", "blocked")
    return clean, False


def valid_model_name(name):
    name = str(name or "").strip()
    return bool(name) and len(name) <= 200 and bool(MODEL_RE.match(name))


# ---- 이 PC의 자원 ----

def _run(cmd, timeout=3):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else ""


def _memory():
    """(전체 RAM, 쓸 수 있는 RAM) 바이트. 모르면 (None, None)."""
    try:
        if sys.platform.startswith("linux"):
            info = {}
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    key, _, value = line.partition(":")
                    info[key] = int(value.split()[0]) * 1024
            return info.get("MemTotal"), info.get("MemAvailable", info.get("MemFree"))
        if os.name == "nt":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MemStatus()
            st.dwLength = ctypes.sizeof(MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullTotalPhys), int(st.ullAvailPhys)
        if sys.platform == "darwin":
            total = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0) or None
            vm = _run(["vm_stat"])
            page = re.search(r"page size of (\d+)", vm)
            free = sum(int(m) for m in re.findall(r"Pages (?:free|inactive|speculative):\s+(\d+)", vm))
            return total, (free * int(page.group(1)) if page and free else None)
    except (OSError, ValueError, AttributeError):
        pass
    return None, None


def _gpus():
    out = []
    if shutil.which("nvidia-smi"):
        for line in _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"]).splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3:
                try:
                    out.append({"name": parts[0], "vram_total": int(float(parts[1])) * 2**20,
                                "vram_free": int(float(parts[2])) * 2**20})
                except ValueError:
                    continue
    return out


def system_resources():
    """이 PC의 자원. 알아내지 못한 값은 None이고 reliable=False면 보수적으로 쓴다(자동 추천을 줄인다)."""
    total, available = _memory()
    apple = sys.platform == "darwin" and platform.machine() == "arm64"
    gpus = [] if apple else _gpus()
    return {"ram_total": total, "ram_available": available, "cpu_count": os.cpu_count(), "gpus": gpus,
            "apple_silicon": apple, "platform": sys.platform, "reliable": total is not None and available is not None}


CONSERVATIVE_BUDGET = 4 * 2**30   # 자원을 모를 때 쓸 수 있다고 보는 메모리(4GB)


def memory_budget(res):
    """모델에 쓸 수 있다고 보는 메모리(바이트, 추정). GPU가 있으면 남은 VRAM, 없으면 쓸 수 있는 RAM의 70%."""
    if not res or not res.get("reliable"):
        return CONSERVATIVE_BUDGET
    vram = max((g.get("vram_free") or 0 for g in res.get("gpus") or []), default=0)
    ram = int((res.get("ram_available") or 0) * 0.7)
    return max(vram, ram) if vram else ram


def estimate_memory(size_bytes, num_ctx=8192):
    """모델 파일 크기와 문맥 길이로 실행에 드는 메모리를 어림한다(추정치: 파일의 1.15배 + 문맥 1천 토큰당 약 64MB)."""
    if not size_bytes:
        return None
    return int(size_bytes * 1.15 + (num_ctx / 1000) * 64 * 2**20)


# ---- Ollama ----

def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _context_length(model_info):
    for key, value in (model_info or {}).items():
        if key.endswith(".context_length") and _num(value):
            return _num(value)
    return 0


def _size_label(n):
    if not n:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return str(n)


class OllamaProvider(LocalModelProvider):
    """Ollama 기본 API(/api/*). OpenAI 호환 API(/v1)도 있지만 기능 정보(/api/show)와 받기(/api/pull)가 기본 API에만 있어 이쪽을 쓴다."""

    name = "ollama"

    def __init__(self, endpoint=DEFAULT_ENDPOINT, allow_remote=False, http=None):
        self.endpoint, self.loopback = check_endpoint(endpoint, allow_remote)
        self.allow_remote = allow_remote
        self._http = http
        self._caps = {}            # 모델 -> (가져온 시각, 기능 dict)
        self._lock = threading.Lock()

    # 요청 하나를 보낸다. 리다이렉트를 따라가지 않고 프록시·.netrc를 쓰지 않는다.
    def _request(self, method, path, body=None, timeout=10, stream=False):
        if not self.loopback:
            check_endpoint(self.endpoint, self.allow_remote)  # DNS가 바뀌었을 수 있다(리바인딩): 보낼 때마다 다시 본다
        url = self.endpoint + path
        if self._http is not None:
            return self._http(method, url, body, timeout, stream)
        session = requests.Session()
        session.trust_env = False
        try:
            r = session.request(method, url, json=body, timeout=(CONNECT_TIMEOUT, timeout), stream=stream,
                                allow_redirects=False, headers={"Accept": "application/json"})
        except requests.exceptions.ConnectTimeout:
            raise LocalAIError("로컬 AI(Ollama)에 연결하지 못했습니다(시간 초과). Ollama가 켜져 있는지 확인하세요.", "unavailable")
        except requests.exceptions.ConnectionError:
            raise LocalAIError("로컬 AI(Ollama)가 실행 중이 아닙니다. Ollama를 설치·실행한 뒤 다시 시도하세요.", "unavailable")
        except requests.exceptions.Timeout:
            raise LocalAIError("로컬 AI 응답 시간이 초과되었습니다.", "timeout")
        except requests.RequestException as e:
            raise LocalAIError(f"로컬 AI 요청 실패: {type(e).__name__}", "error")
        if 300 <= r.status_code < 400:
            r.close()
            raise LocalAIError("로컬 AI 서버가 다른 주소로 보내려 했습니다(리다이렉트). 따라가지 않습니다.", "blocked")
        return r

    def _json(self, method, path, body=None, timeout=10):
        r = self._request(method, path, body, timeout)
        try:
            if r.status_code == 404:
                raise LocalAIError(self._error_text(r) or "모델을 찾지 못했습니다.", "model")
            if r.status_code != 200:
                raise LocalAIError(f"로컬 AI 오류(HTTP {r.status_code}): {self._error_text(r)}"[:300], "error")
            if len(r.content) > 50 * 2**20:
                raise LocalAIError("로컬 AI 응답이 너무 큽니다.", "format")
            try:
                return r.json()
            except ValueError:
                raise LocalAIError("로컬 AI 응답 형식이 올바르지 않습니다.", "format")
        finally:
            r.close()

    @staticmethod
    def _error_text(r):
        try:
            data = r.json()
            return str(data.get("error") or "")[:300] if isinstance(data, dict) else ""
        except (ValueError, AttributeError):
            return (getattr(r, "text", "") or "")[:200]

    def health_check(self):
        """{"ok", "version", "endpoint", "loopback", "error", "ms"} — 실패해도 예외를 내지 않는다."""
        start = time.monotonic()
        try:
            data = self._json("GET", "/api/version", timeout=5)
            return {"ok": True, "version": str(data.get("version") or ""), "endpoint": self.endpoint,
                    "loopback": self.loopback, "error": "", "ms": int((time.monotonic() - start) * 1000)}
        except LocalAIError as e:
            return {"ok": False, "version": "", "endpoint": self.endpoint, "loopback": self.loopback, "error": str(e),
                    "kind": e.kind, "ms": int((time.monotonic() - start) * 1000)}

    def is_available(self):
        return self.health_check()["ok"]

    def list_models(self):
        """설치된 모델 [{"id", "size", "size_label", "family", "parameter_size", "quantization", "format", "modified"}]."""
        data = self._json("GET", "/api/tags", timeout=10)
        out = []
        for m in data.get("models") or []:
            if not isinstance(m, dict):
                continue
            name = str(m.get("model") or m.get("name") or "")
            if not valid_model_name(name):
                continue
            d = m.get("details") if isinstance(m.get("details"), dict) else {}
            out.append({"id": name, "size": _num(m.get("size")), "size_label": _size_label(_num(m.get("size"))),
                        "family": str(d.get("family") or "")[:40], "parameter_size": str(d.get("parameter_size") or "")[:20],
                        "quantization": str(d.get("quantization_level") or "")[:20], "format": str(d.get("format") or "")[:20],
                        "modified": str(m.get("modified_at") or "")[:40]})
        return out

    def capabilities(self, model_id, refresh=False):
        """{"completion", "vision", "tools", "json", "thinking", "embedding", "context_length", "license", "known"}.
        known=False면 실행기가 기능 목록을 주지 않았다(오래된 Ollama): 글만 된다고 보고 나머지는 없다고 본다."""
        if not valid_model_name(model_id):
            raise LocalAIError("모델 이름이 올바르지 않습니다.", "model")
        with self._lock:
            hit = self._caps.get(model_id)
        if hit and not refresh and time.time() - hit[0] < 600:
            return dict(hit[1])
        data = self._json("POST", "/api/show", {"model": model_id}, timeout=15)
        caps = data.get("capabilities")
        known = isinstance(caps, list)
        caps = {str(c) for c in caps} if known else {"completion"}
        info = {"completion": "completion" in caps, "vision": "vision" in caps, "tools": "tools" in caps,
                # Ollama의 format(JSON·스키마)은 글을 만드는 모델이면 실행기가 문법으로 강제한다
                "json": "completion" in caps, "thinking": "thinking" in caps, "embedding": "embedding" in caps,
                "context_length": _context_length(data.get("model_info")),
                "license": str(data.get("license") or "")[:4000], "known": known,
                "family": str((data.get("details") or {}).get("family") or "")[:40]}
        with self._lock:
            self._caps[model_id] = (time.time(), info)
        return dict(info)

    def running(self):
        """메모리에 올라 있는 모델 [{"id", "size", "size_vram"}]."""
        try:
            data = self._json("GET", "/api/ps", timeout=5)
        except LocalAIError:
            return []
        return [{"id": str(m.get("model") or m.get("name") or ""), "size": _num(m.get("size")), "size_vram": _num(m.get("size_vram"))}
                for m in data.get("models") or [] if isinstance(m, dict)]

    def stream(self, request, on_delta, cancelled):
        """글을 만든다. on_delta(지금까지의 전체 글)가 있으면 받는 대로 넘긴다. cancelled()가 참이 되면 멈춘다."""
        if not valid_model_name(request.model):
            raise LocalAIError("로컬 모델을 고르세요(AI 실행 정책 → 기본 로컬 모델).", "model")
        message = {"role": "user", "content": request.prompt}
        if request.images:
            message["images"] = [b64 for _, b64 in request.images]
        options = {}
        if request.num_ctx:
            options["num_ctx"] = int(request.num_ctx)
        if request.max_tokens:
            options["num_predict"] = int(request.max_tokens)
        body = {"model": request.model, "messages": [message], "stream": True}
        if options:
            body["options"] = options
        if request.json_format:
            body["format"] = "json"
        started = time.monotonic()
        r = self._request("POST", "/api/chat", body, timeout=max(10.0, float(request.timeout)), stream=True)
        text, final = "", {}
        try:
            if r.status_code == 404:
                raise LocalAIError(self._error_text(r) or f"로컬 모델 '{request.model}'이(가) 설치되어 있지 않습니다.", "model")
            if r.status_code != 200:
                err = self._error_text(r)
                kind = "context" if "context" in err.lower() else "resource" if "memory" in err.lower() else "error"
                raise LocalAIError(f"로컬 AI 오류(HTTP {r.status_code}): {err}"[:300], kind)
            for raw in r.iter_lines(chunk_size=8192):
                if cancelled and cancelled():
                    final = {"done_reason": "cancelled"}
                    break
                if time.monotonic() - started > request.timeout:
                    raise LocalAIError(f"로컬 AI가 {int(request.timeout)}초 안에 답을 끝내지 못했습니다.", "timeout")
                if not raw:
                    continue
                if len(raw) > MAX_LINE_BYTES:
                    raise LocalAIError("로컬 AI 응답 형식이 올바르지 않습니다(줄이 너무 깁니다).", "format")
                try:
                    obj = json.loads(raw)
                except ValueError:
                    raise LocalAIError("로컬 AI 응답 형식이 올바르지 않습니다.", "format")
                if not isinstance(obj, dict):
                    continue
                if obj.get("error"):
                    err = str(obj["error"])[:300]
                    kind = "context" if "context" in err.lower() else "resource" if "memory" in err.lower() else "error"
                    raise LocalAIError(f"로컬 AI 오류: {err}", kind)
                piece = (obj.get("message") or {}).get("content") if isinstance(obj.get("message"), dict) else None
                if isinstance(piece, str) and piece:
                    text += piece
                    if len(text) > MAX_REPLY_CHARS:
                        final = {"done_reason": "length"}
                        break
                    if on_delta:
                        on_delta(text)
                if obj.get("done"):
                    final = obj
                    break
            else:
                if not final:
                    raise LocalAIError("로컬 AI 연결이 답변 도중 끊겼습니다.", "unavailable")
        except requests.RequestException:
            raise LocalAIError("로컬 AI 연결이 답변 도중 끊겼습니다.", "unavailable")
        finally:
            r.close()
        eval_ns, out = _num(final.get("eval_duration")), _num(final.get("eval_count"))
        return LocalResult(text=text, model=request.model, done_reason=str(final.get("done_reason") or "stop"),
                           input_tokens=_num(final.get("prompt_eval_count")), output_tokens=out,
                           ms=int((time.monotonic() - started) * 1000), load_ms=_num(final.get("load_duration")) // 1_000_000,
                           tokens_per_s=round(out / (eval_ns / 1e9), 1) if eval_ns and out else 0.0)

    def measure(self, model_id, cancelled=None):
        """짧은 질문 하나로 속도를 잰다: {"tokens_per_s", "first_ms", "ms", "load_ms"}."""
        first = [None]
        start = time.monotonic()

        def on_delta(_text):
            if first[0] is None:
                first[0] = int((time.monotonic() - start) * 1000)

        res = self.stream(LocalRequest(model=model_id, prompt="한 문장으로 자기소개를 하세요.", timeout=120, max_tokens=64),
                          on_delta, cancelled)
        return {"tokens_per_s": res.tokens_per_s, "first_ms": first[0], "ms": res.ms, "load_ms": res.load_ms,
                "output_tokens": res.output_tokens}

    def pull(self, model_id, on_progress=None, cancelled=None):
        """모델을 받는다(사용자가 누를 때만 부른다). on_progress(완료 바이트, 전체 바이트, 상태)."""
        if not valid_model_name(model_id):
            raise LocalAIError("모델 이름이 올바르지 않습니다(예: qwen2.5:7b).", "model")
        r = self._request("POST", "/api/pull", {"model": model_id, "stream": True}, timeout=3600, stream=True)
        try:
            if r.status_code != 200:
                raise LocalAIError(f"모델을 받지 못했습니다: {self._error_text(r)}"[:300], "error")
            for raw in r.iter_lines(chunk_size=8192):
                if cancelled and cancelled():
                    raise LocalAIError("모델 받기를 멈췄습니다(받은 조각은 Ollama가 다음에 이어 받습니다).", "cancelled")
                if not raw or len(raw) > MAX_LINE_BYTES:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if obj.get("error"):
                    err = str(obj["error"])[:300]
                    kind = "resource" if "space" in err.lower() or "disk" in err.lower() else "error"
                    raise LocalAIError(f"모델을 받지 못했습니다: {err}", kind)
                if on_progress:
                    on_progress(_num(obj.get("completed")), _num(obj.get("total")), str(obj.get("status") or "")[:80])
                if obj.get("status") == "success":
                    with self._lock:
                        self._caps.pop(model_id, None)
                    return True
        except requests.RequestException:
            raise LocalAIError("모델을 받는 도중 연결이 끊겼습니다.", "unavailable")
        finally:
            r.close()
        raise LocalAIError("모델 받기가 끝나지 않았습니다.", "error")

    def delete(self, model_id):
        if not valid_model_name(model_id):
            raise LocalAIError("모델 이름이 올바르지 않습니다.", "model")
        r = self._request("DELETE", "/api/delete", {"model": model_id}, timeout=30)
        try:
            if r.status_code != 200:
                raise LocalAIError(f"모델을 지우지 못했습니다: {self._error_text(r)}"[:300], "error")
        finally:
            r.close()
        with self._lock:
            self._caps.pop(model_id, None)
        return True


# ---- 받기 전 확인(공개 저장소) ----

def pull_preview(model_id, http=None, timeout=15):
    """Ollama 공개 저장소(registry.ollama.ai)의 목록으로 받을 크기와 라이선스를 미리 본다(사용자가 '확인'을 눌렀을 때만).

    {"id", "source", "size", "size_label", "license", "license_name", "page"}. 저장소에 없으면 LocalAIError(model)."""
    if not valid_model_name(model_id):
        raise LocalAIError("모델 이름이 올바르지 않습니다(예: qwen2.5:7b).", "model")
    name, _, tag = model_id.partition(":")
    repo = name if "/" in name else f"library/{name}"
    get = http or (lambda url, headers: requests.get(url, headers=headers, timeout=timeout))
    accept = "application/vnd.docker.distribution.manifest.v2+json"
    try:
        r = get(f"{REGISTRY}/v2/{repo}/manifests/{tag or 'latest'}", {"Accept": accept})
    except requests.RequestException as e:
        raise LocalAIError(f"모델 정보를 받지 못했습니다(네트워크): {type(e).__name__}", "unavailable")
    if r.status_code == 404:
        raise LocalAIError(f"Ollama 공개 저장소에 '{model_id}'이(가) 없습니다.", "model")
    if r.status_code != 200:
        raise LocalAIError(f"모델 정보를 받지 못했습니다(HTTP {r.status_code}).", "error")
    try:
        layers = r.json().get("layers") or []
    except (ValueError, AttributeError):
        raise LocalAIError("모델 정보 형식이 올바르지 않습니다.", "format")
    size = sum(_num(layer.get("size")) for layer in layers if isinstance(layer, dict))
    license_text = ""
    lic = next((layer for layer in layers if isinstance(layer, dict)
                and layer.get("mediaType") == "application/vnd.ollama.image.license"), None)
    if lic and re.fullmatch(r"sha256:[0-9a-f]{64}", str(lic.get("digest") or "")):
        try:
            lr = get(f"{REGISTRY}/v2/{repo}/blobs/{lic['digest']}", {})
            if lr.status_code == 200:
                license_text = (lr.text or "")[:6000]
        except requests.RequestException:
            pass
    first = license_text.strip().splitlines()[0][:120] if license_text.strip() else ""
    return {"id": model_id, "source": f"{REGISTRY}/v2/{repo}", "size": size, "size_label": _size_label(size),
            "license": license_text, "license_name": first or "(저장소에 라이선스 파일이 없습니다 — 모델 페이지에서 확인하세요)",
            "page": f"{LIBRARY_URL}/{name}" if "/" not in name else f"https://ollama.com/{name}"}


def disk_free(path=None):
    """Ollama 모델 폴더(OLLAMA_MODELS 또는 ~/.ollama)가 있는 디스크의 남은 공간(바이트). 모르면 None."""
    target = path or os.environ.get("OLLAMA_MODELS") or os.path.join(os.path.expanduser("~"), ".ollama")
    probe = target
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe or os.path.expanduser("~")).free
    except OSError:
        return None


def make_provider(config):
    """설정(config["adaptive"]["local"])으로 실행기를 만든다. 쓸 수 없는 곳(안드로이드)이나 주소 정책 위반이면 LocalAIError."""
    if not SUPPORTED:
        raise LocalAIError("이 기기(안드로이드)에서는 로컬 AI를 쓸 수 없습니다.", "unavailable")
    local = ((config or {}).get("adaptive") or {}).get("local") or {}
    return OllamaProvider(local.get("endpoint") or DEFAULT_ENDPOINT, bool(local.get("allow_remote")))
