"""MCP(Model Context Protocol) 클라이언트: 표준 입출력 MCP 서버를 띄우고 도구를 부른다.

내장 서버(word·powerpoint·excel·paper·notion·firecrawl)는 앱 exe 자신을
`--mcp-server <이름>`으로, 소스 실행 때는 office_mcp.py를 실행한다. 추천 서버(playwright)는 앱이
실행 방법을 아는 외부 서버로, 기본은 꺼져 있고 MCP 창에서 켠다. 그 밖의 외부 서버는
%APPDATA%\\PostechChat\\mcp.json에 Claude Desktop과 같은 형식으로 적는다.

    {"mcpServers": {"이름": {"command": "npx", "args": ["-y", "패키지"], "env": {"KEY": "값"}}}}

서버는 처음 필요할 때(에이전트 실행이나 MCP 창의 '연결') 작업 폴더를 현재 폴더로 해서 띄우고,
작업 폴더나 설정이 바뀌면 다시 띄운다.
"""
import collections
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import connectors
import secret_store
import storage
from version import APP_VERSION

PROTOCOL_VERSION = "2025-06-18"
START_TIMEOUT = 30
CALL_TIMEOUT = 180
# 하위 프로세스를 띄울 수 없는 환경(안드로이드)에서는 내장 서버를 앱 프로세스 안의 스레드로 돌린다.
INPROCESS_BUILTIN = False
INPROCESS = "(앱 내장)"

BUILTIN_SERVERS = {
    "word": "Word 문서(.docx) 만들기·내용 추가·글자 바꾸기",
    "powerpoint": "PowerPoint(.pptx) 만들기·슬라이드 추가·글자 바꾸기",
    "excel": "Excel(.xlsx) 만들기·셀 쓰기",
    "paper": "논문 찾기(arXiv·Semantic Scholar)·정보·한 줄 요약·섹션별로 읽기·참고/인용 논문",
    "notion": "Notion 페이지·데이터베이스 찾기·읽기·만들기·덧붙이기(설정에 Notion 통합 토큰 필요)",
    "firecrawl": "웹페이지를 마크다운으로 읽기·웹 검색·사이트 지도·여러 쪽 크롤링(설정에 Firecrawl API 키 필요)",
}
PLAYWRIGHT_VERSION = "0.0.83"  # 같은 동작이 유지되도록 버전을 고정한다


def preset_servers():
    """추천 외부 서버: 이름 -> mcp.json 형식 설정. mcp.json에 같은 이름이 있으면 그쪽을 쓴다."""
    if INPROCESS_BUILTIN:
        return {}  # 안드로이드: 하위 프로세스(npx)를 띄울 수 없다
    args = ["-y", f"@playwright/mcp@{PLAYWRIGHT_VERSION}", "--output-dir", ".playwright-mcp"]
    if os.name == "nt":
        args += ["--browser", "msedge"]  # Windows에 늘 있는 Edge를 써서 브라우저를 따로 받지 않는다
    presets = {"playwright": {
        "command": "npx", "args": args,
        "description": "브라우저 자동화(Microsoft Playwright): 페이지 열기·클릭·입력·스크린샷. PC에 Node.js 필요",
    }}
    if shutil.which("github-mcp-server"):
        # GitHub 공식 MCP 서버(Go 바이너리)가 설치돼 있을 때만. 기본은 읽기 전용이고 토큰은 GitHub 커넥터의 것을 쓴다.
        presets["github-official"] = {
            "command": "github-mcp-server", "args": ["stdio", "--read-only"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": secret_store.get(connectors.secret_name("github", "token"))},
            "description": "GitHub 공식 MCP 서버(읽기 전용). 토큰은 커넥터 → GitHub의 토큰을 씁니다",
        }
    return presets

CONFIG_TEMPLATE = {
    "mcpServers": {},
    "_설명": "외부 MCP 서버를 mcpServers 아래에 적으세요. 예: "
             "\"filesystem\": {\"command\": \"npx\", \"args\": [\"-y\", \"@modelcontextprotocol/server-filesystem\", \".\"]}. "
             "npx·uvx 같은 실행 도구는 이 PC에 따로 설치되어 있어야 합니다.",
}


class MCPError(Exception):
    pass


def builtin_command(name):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--mcp-server", name]
    return [sys.executable, str(Path(__file__).resolve().parent / "office_mcp.py"), name]


def load_external():
    """mcp.json의 외부 서버 설정. 파일이 없거나 잘못되면 (빈 dict, 오류 문구)."""
    path = storage.MCP_PATH
    if not path.exists():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
        if not isinstance(servers, dict):
            raise ValueError("mcpServers는 객체여야 합니다")
    except (OSError, ValueError) as e:
        return {}, f"mcp.json을 읽지 못했습니다: {e}"
    out = {}
    for name, spec in servers.items():
        if isinstance(spec, dict) and spec.get("command") and name not in BUILTIN_SERVERS:
            out[str(name)] = spec
    return out, ""


def ensure_config_file():
    path = storage.MCP_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(CONFIG_TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class _InProcessServer:
    """subprocess.Popen 대신 쓰는 객체: 내장 서버를 같은 프로세스의 스레드에서 돌리고 os.pipe로 MCP를 주고받는다."""

    def __init__(self, name, cwd):
        import office_mcp

        client_read, server_write = os.pipe()
        server_read, client_write = os.pipe()
        self.stdin = os.fdopen(client_write, "wb")
        self.stdout = os.fdopen(client_read, "rb")
        self.stderr = io.BytesIO()
        server_in, server_out = os.fdopen(server_read, "rb"), os.fdopen(server_write, "wb")
        office_mcp.ROOT = cwd  # 내장 서버는 모두 같은 작업 폴더를 쓴다

        def run():
            try:
                office_mcp.serve(name, server_in, server_out)
            finally:
                server_in.close()
                server_out.close()  # 클라이언트 쪽 stdout이 끝나 읽기 스레드가 멈춘다

        self._thread = threading.Thread(target=run, daemon=True, name=f"mcp-{name}")
        self._thread.start()

    def poll(self):
        return None if self._thread.is_alive() else 0

    def wait(self, timeout=None):
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise subprocess.TimeoutExpired(INPROCESS, timeout)
        return 0

    def kill(self):
        pass  # stdin을 닫으면 서버 루프가 끝난다


class Server:
    """표준 입출력으로 연결된 MCP 서버 하나."""

    def __init__(self, name, command, args=(), env=None, cwd=None, builtin=False, connector=""):
        self.name, self.builtin, self.connector = name, builtin, connector
        self.command, self.args, self.env, self.cwd = command, list(args), dict(env or {}), cwd
        self.proc = None
        self.tools = []
        self.error = ""
        self._next_id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.stderr_tail = collections.deque(maxlen=40)
        self.spec_key = None  # Manager가 설정이 바뀌었는지 비교하는 값

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.command == INPROCESS:
            self.proc = _InProcessServer(self.args[0], self.cwd)
            self._initialize()
            return
        exe = shutil.which(self.command) or self.command
        env = dict(os.environ, **{k: str(v) for k, v in self.env.items()})
        env.setdefault("PYTHONIOENCODING", "utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cmd = [exe, *self.args]
        if os.name == "nt" and Path(exe).suffix.lower() in (".cmd", ".bat"):
            cmd = ["cmd", "/c", exe, *self.args]  # npx.cmd 같은 배치 파일은 cmd로 실행해야 한다
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         cwd=self.cwd or None, env=env, creationflags=flags)
        except OSError as e:
            raise MCPError(f"서버를 실행하지 못했습니다({self.command}): {e}")
        self._initialize()

    def _initialize(self):
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "postech-genai-chat", "version": APP_VERSION},
        }, timeout=START_TIMEOUT)
        self.notify("notifications/initialized")
        tools, cursor = [], None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=START_TIMEOUT)
            tools += [t for t in result.get("tools", []) if isinstance(t, dict) and t.get("name")]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        self.tools, self.error = tools, ""

    def _read_stdout(self):
        stream = self.proc.stdout  # close()가 self.proc을 비워도 끝까지 읽고 닫는다
        for line in stream:
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # 서버가 표준 출력에 섞어 쓴 로그
            if isinstance(msg, dict) and "id" in msg and ("result" in msg or "error" in msg):
                with self._lock:
                    box = self._pending.pop(msg["id"], None)
                if box:
                    box.put(msg)
        stream.close()
        with self._lock:  # 서버가 끝났다: 기다리는 요청을 모두 깨운다
            for box in self._pending.values():
                box.put(None)
            self._pending.clear()

    def _read_stderr(self):
        stream = self.proc.stderr
        for line in stream:
            self.stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())
        stream.close()

    def _send(self, msg):
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
        except (OSError, ValueError):
            raise MCPError(f"'{self.name}' 서버와 연결이 끊겼습니다.{self._stderr_hint()}")

    def _stderr_hint(self):
        tail = [line for line in self.stderr_tail if line.strip()][-3:]
        return ("\n" + "\n".join(tail)) if tail else ""

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def request(self, method, params=None, timeout=CALL_TIMEOUT):
        if not self.alive():
            raise MCPError(f"'{self.name}' 서버가 실행 중이 아닙니다.{self._stderr_hint()}")
        box = queue.Queue(maxsize=1)
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            self._pending[rid] = box
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        try:
            msg = box.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(rid, None)
            raise MCPError(f"'{self.name}' 서버가 {timeout}초 안에 응답하지 않았습니다({method}).")
        if msg is None:
            raise MCPError(f"'{self.name}' 서버가 종료되었습니다.{self._stderr_hint()}")
        if "error" in msg:
            err = msg["error"] or {}
            raise MCPError(f"{err.get('message', '알 수 없는 오류')} (코드 {err.get('code')})")
        return msg.get("result") or {}

    def call(self, tool, arguments, timeout=CALL_TIMEOUT):
        result = self.request("tools/call", {"name": tool, "arguments": arguments or {}}, timeout=timeout)
        parts = []
        for item in result.get("content") or []:
            kind = item.get("type")
            if kind == "text":
                parts.append(item.get("text", ""))
            elif kind == "resource":
                res = item.get("resource") or {}
                parts.append(res.get("text") or f"[리소스 {res.get('uri', '')}]")
            elif kind == "resource_link":
                parts.append(f"[링크 {item.get('name', '')} {item.get('uri', '')}]")
            else:
                parts.append(f"[{kind} {item.get('mimeType', '')}]")
        if not parts and result.get("structuredContent") is not None:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        return "\n".join(parts).strip() or "(결과 없음)", bool(result.get("isError"))

    def close(self):
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()  # 표준 입력이 닫히면 서버는 스스로 끝난다
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None


class Manager:
    """설정에 맞게 서버들을 띄우고 유지한다. 브리지와 에이전트 스레드에서 함께 쓴다."""

    def __init__(self):
        self._servers = {}
        self._errors = {}   # 이름 -> 마지막 연결 오류
        self._lock = threading.RLock()
        self._ensure_lock = threading.Lock()

    def specs(self, config, workspace):
        disabled = set(config.get("mcp_disabled", []))
        specs = {}
        for name in BUILTIN_SERVERS:
            cmd = [INPROCESS, name] if INPROCESS_BUILTIN else builtin_command(name)
            specs[name] = {"command": cmd[0], "args": cmd[1:], "env": {}, "builtin": True,
                           "enabled": name not in disabled, "description": BUILTIN_SERVERS[name]}
        enabled = set(config.get("mcp_enabled", []))
        external, _ = load_external()
        for cid, connector in connectors.CONNECTORS.items():
            # 커넥터의 내장 서버는 켠 커넥터만. mcp.json에 같은 이름의 서버가 있으면 그쪽을 쓴다(status가 알린다).
            if connector.server in external or connector.server in specs:
                continue
            if not connectors.is_enabled(config, cid, inprocess=INPROCESS_BUILTIN):
                continue
            cmd = [INPROCESS, connector.server] if INPROCESS_BUILTIN else builtin_command(connector.server)
            specs[connector.server] = {
                "command": cmd[0], "args": cmd[1:], "builtin": True, "enabled": True, "connector": cid,
                "env": {"POSCHAT_CONNECTOR_REV": connectors.options_rev(config, cid)}, "description": connector.description}
        for name, spec in preset_servers().items():
            if name not in external:
                specs[name] = {"command": spec["command"], "args": spec["args"], "env": dict(spec.get("env") or {}),
                               "builtin": False,
                               "preset": True, "enabled": name in enabled and name not in disabled,
                               "description": spec["description"]}
        for name, spec in external.items():
            args = spec.get("args") or []
            specs[name] = {"command": str(spec["command"]), "args": [str(a) for a in args] if isinstance(args, list) else [],
                           "env": spec.get("env") if isinstance(spec.get("env"), dict) else {}, "builtin": False,
                           "enabled": name not in disabled and not spec.get("disabled"),
                           "description": str(spec.get("description", ""))}
        for spec in specs.values():
            spec["cwd"] = workspace or None
        return specs

    def ensure(self, config, workspace, on_status=None):
        """켜진 서버를 모두 연결된 상태로 만든다. 연결된 서버 목록을 돌려준다."""
        specs = self.specs(config, workspace)
        with self._ensure_lock:  # 동시에 불려도 같은 서버를 두 번 띄우지 않는다
            stale = []
            with self._lock:
                for name in list(self._servers):
                    spec, server = specs.get(name), self._servers[name]
                    if not spec or not spec["enabled"] or not server.alive() or server.spec_key != self._key(spec):
                        stale.append(self._servers.pop(name))
                todo = [(n, s) for n, s in specs.items() if s["enabled"] and n not in self._servers]
            for server in stale:
                server.close()
            if todo and on_status:
                on_status("MCP 서버 연결 중... (" + ", ".join(n for n, _ in todo) + ")")
            threads = [threading.Thread(target=self._start, args=(n, s), daemon=True) for n, s in todo]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        with self._lock:
            return [self._servers[n] for n in specs if n in self._servers]

    @staticmethod
    def _key(spec):
        return (spec["command"], tuple(spec["args"]), tuple(sorted((k, str(v)) for k, v in spec["env"].items())), spec["cwd"])

    def _start(self, name, spec):
        server = Server(name, spec["command"], spec["args"], spec["env"], spec["cwd"], spec["builtin"],
                        spec.get("connector", ""))
        server.spec_key = self._key(spec)
        try:
            server.start()
        except MCPError as e:
            server.close()
            with self._lock:
                self._errors[name] = str(e)
            return
        with self._lock:
            self._servers[name] = server
            self._errors.pop(name, None)

    def status(self, config, workspace):
        specs = self.specs(config, workspace)
        _, file_error = load_external()
        out = []
        with self._lock:
            for name, spec in specs.items():
                server = self._servers.get(name)
                connected = server is not None and server.alive()
                out.append({
                    "name": name, "builtin": spec["builtin"], "preset": spec.get("preset", False), "enabled": spec["enabled"],
                    "connector": spec.get("connector", ""),
                    "description": spec["description"],
                    "command": " ".join([spec["command"], *spec["args"]]) if not spec["builtin"] else "",
                    "state": "connected" if connected else ("error" if name in self._errors and spec["enabled"] else "idle"),
                    "error": self._errors.get(name, "") if spec["enabled"] else "",
                    "tools": [t["name"] for t in server.tools] if connected else [],
                })
        return {"servers": out, "config_error": file_error, "config_path": str(storage.MCP_PATH)}

    def get(self, name):
        with self._lock:
            server = self._servers.get(name)
        if server is None or not server.alive():
            raise MCPError(f"MCP 서버 '{name}'가 연결되어 있지 않습니다.")
        return server

    def shutdown(self):
        with self._lock:
            servers, self._servers = list(self._servers.values()), {}
        for server in servers:
            server.close()
