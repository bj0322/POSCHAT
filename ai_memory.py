"""ai-memory(https://github.com/akitaonrails/ai-memory) 연동: 다른 코딩 에이전트와 기억을 이어 쓴다.

mcp.json에 ai-memory를 표준 입출력 브리지로 등록하면(command "ai-memory", args ["mcp-bridge", "--no-session-id"])
에이전트 모드에서 다음을 자동으로 한다. Claude Code 같은 에이전트는 수명 주기 훅으로 하는 일이다.

- 대화의 첫 에이전트 실행: 작업 폴더에 남은 인계(handoff)를 받고 최근 기억 페이지를 불러와 프롬프트에 넣는다.
- 파일 수정·명령 실행 같은 작업을 한 실행이 끝나면: 다음 에이전트가 이어받을 인계를 남긴다.
  같은 대화에서 다시 남길 때는 앞의 인계를 취소해서 대화마다 인계가 하나만 열려 있게 한다.
- 모델이 부르는 ai-memory 도구에는 workspace·project를 앱이 채운다.

브리지는 세션 id를 넘기지 않는 정적 MCP 클라이언트이므로 ai-memory 규칙대로 작업 폴더에서 이름을 정한다:
가장 가까운 .ai-memory.toml의 workspace·project → git 원격(upstream, 없으면 origin)의 호스트를 뺀 경로
→ 원격이 없으면 저장소(또는 폴더) 이름. workspace의 기본값은 "default"다.
"""
import json
import re
import tomllib
from pathlib import Path

from mcp_client import MCPError

REQUIRED_TOOLS = {"memory_handoff_accept", "memory_handoff_begin", "memory_recent"}
RECENT_LIMIT = 5
MAX_NOTE_CHARS = 4000
MAX_SUMMARY_CHARS = 1200
MAX_FILES = 50
_SCOPE_RE = re.compile(r'^\s*\[\s*remote\s+"([^"]+)"\s*\]')
_URL_RE = re.compile(r"^\s*url\s*=\s*(.+?)\s*$", re.IGNORECASE)


def find_server(servers):
    """연결된 서버 중 ai-memory(필요한 도구를 모두 가진 서버). 없으면 None."""
    for server in servers:
        if REQUIRED_TOOLS <= {t["name"] for t in server.tools}:
            return server
    return None


# ---- 작업 폴더 → (workspace, project) ----

def _git_dir(start):
    """(저장소 최상위 폴더, git 공통 폴더). git 저장소가 아니면 (None, None)."""
    for d in (start, *start.parents):
        dot = d / ".git"
        if dot.is_dir():
            return d, dot
        if dot.is_file():  # 워크트리·서브모듈: "gitdir: 경로"
            try:
                text = dot.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return d, None
            if not text.startswith("gitdir:"):
                return d, None
            gitdir = (d / text[len("gitdir:"):].strip()).resolve()
            common = gitdir
            try:
                common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
            except OSError:
                pass
            return d, common
    return None, None


def _remote_urls(git_dir):
    try:
        text = (git_dir / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    urls, current = {}, None
    for line in text.splitlines():
        m = _SCOPE_RE.match(line)
        if m:
            current = m[1]
            continue
        if line.lstrip().startswith("["):
            current = None
            continue
        m = _URL_RE.match(line)
        if current and m and current not in urls:
            urls[current] = m[1].strip('"')
    return urls


def normalize_remote_url(raw):
    """git 원격 주소를 'host/경로'로. 파일 경로 같은 원격은 None. ai-memory의 normalize_remote_url과 같은 규칙."""
    raw = raw.strip()
    if not raw:
        return None
    scheme, rest = None, raw
    if "://" in raw:
        idx = raw.find("://")
        scheme, rest = raw[:idx].lower(), raw[idx + 3:]
    if scheme == "file":
        return None
    path_start = rest.find("/") if "/" in rest else len(rest)
    at = rest.rfind("@", 0, path_start)
    host_and_path = rest[at + 1:] if at != -1 else rest
    if scheme is not None:
        host, _, path = host_and_path.partition("/")
        if ":" in host and host.rsplit(":", 1)[1].isdigit():
            host = host.rsplit(":", 1)[0]
        if not host or not path:
            return None
    else:
        colon = host_and_path.find(":")
        if colon == -1:
            return None
        slash = host_and_path.find("/")
        if slash != -1 and slash < colon:
            return None
        host, path = host_and_path[:colon], host_and_path[colon + 1:]
        if len(host) <= 1 or not path or "\\" in path:
            return None
    out = f"{host}/{path}".lower().rstrip("/")
    if out.endswith(".git"):
        out = out[:-4].rstrip("/")
    while "//" in out:
        out = out.replace("//", "/")
    return out if "/" in out else None


def project_name_from(raw):
    """프로젝트 이름에 못 쓰는 글자는 '-'로, 연속된 '-'는 하나로, 양 끝 '-'는 지운다."""
    out = re.sub(r"[^\w.-]", "-", raw)
    out = re.sub(r"-{2,}", "-", out).strip("-")
    return out or "repository"


def _marker(cwd, repo_root):
    """가장 가까운 .ai-memory.toml의 최상위 workspace·project. 홈 밖이면 저장소 최상위까지만 올라간다."""
    home = Path.home()
    if cwd == home or home in cwd.parents:
        stop = home
    else:
        stop = repo_root or cwd
    for d in (cwd, *cwd.parents):
        path = d / ".ai-memory.toml"
        if path.is_file():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
            found = {k: data[k].strip() for k in ("workspace", "project")
                     if isinstance(data.get(k), str) and data[k].strip()}
            if found:  # [capture]만 있는 파일은 건너뛴다
                return found
        if d == stop:
            break
    return {}


def resolve_scope(workspace):
    """작업 폴더가 속한 ai-memory의 (workspace, project)."""
    cwd = Path(workspace).resolve()
    repo_root, git_dir = _git_dir(cwd)
    marker = _marker(cwd, repo_root)
    ws = marker.get("workspace", "default")
    if marker.get("project"):
        return ws, marker["project"]
    if git_dir:
        urls = _remote_urls(git_dir)
        for name in ("upstream", "origin"):
            identity = normalize_remote_url(urls.get(name, ""))
            if identity:
                return ws, project_name_from("-".join(identity.split("/")[1:]))
    if repo_root and git_dir and git_dir.name == ".git":
        return ws, git_dir.parent.name  # 워크트리도 원래 저장소 이름을 쓴다
    return ws, (repo_root or cwd).name


# ---- 서버 호출 ----

def _call_json(server, tool, args):
    text, is_error = server.call(tool, args)
    if is_error:
        raise MCPError(text)
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit] + "..."


def _bullets(title, items):
    items = [str(i) for i in items or [] if str(i).strip()]
    return [f"{title}:"] + [f"  - {i}" for i in items] if items else []


class AiMemory:
    def __init__(self, server, workspace):
        self.server = server
        self.cwd = str(Path(workspace).resolve())
        self.workspace, self.project = resolve_scope(workspace)

    @property
    def scope(self):
        return {"workspace": self.workspace, "project": self.project}

    def fill_args(self, tool_spec, arguments):
        """모델이 부른 ai-memory 도구 인자에 빠진 workspace·project(와 인계의 cwd)를 채운 사본."""
        props = (tool_spec.get("inputSchema") or {}).get("properties") or {}
        args = dict(arguments)
        explicit = any(k in args for k in ("workspace", "project", "scopes")) or args.get("global") \
            or args.get("scope") == "global"
        if "workspace" in props and "project" in props and not explicit:
            args.update(self.scope)
        if "from_workspace" in props and "from_project" in props and \
                not any(k in args for k in ("from_workspace", "from_project")):
            args.update(from_workspace=self.workspace, from_project=self.project)
        if tool_spec["name"] in ("memory_handoff_begin", "memory_handoff_accept") and "cwd" in props \
                and "cwd" not in args and not explicit:
            args["cwd"] = self.cwd
        return args

    def start(self):
        """열린 인계를 받고 최근 기억을 불러 프롬프트에 넣을 글로 만든다. (글, 화면에 보일 요약)"""
        parts, shown = [], []
        try:
            data = _call_json(self.server, "memory_handoff_accept", {**self.scope, "cwd": self.cwd})
        except MCPError as e:
            data = {}
            shown.append(f"인계 확인 실패: {e}")
        handoff = data.get("handoff") if isinstance(data, dict) else None
        if isinstance(handoff, dict):
            agent = handoff.get("from_agent") or "다른 에이전트"
            lines = [f"[이어받은 인계 — {agent}, {handoff.get('created_at', '')}]",
                     str(handoff.get("summary") or "").strip()]
            lines += _bullets("남은 질문", handoff.get("open_questions"))
            lines += _bullets("다음 할 일", handoff.get("next_steps"))
            lines += _bullets("수정한 파일", (handoff.get("files_touched") or [])[:20])
            parts.append("\n".join(line for line in lines if line))
            shown.append(f"📥 {agent}의 인계를 받았습니다: {_truncate(str(handoff.get('summary') or ''), 60)}")
        try:
            recent = _call_json(self.server, "memory_recent", {**self.scope, "limit": RECENT_LIMIT})
        except MCPError:
            recent = {}  # 아직 기억이 없는 새 프로젝트
        hits = recent.get("hits") if isinstance(recent, dict) else None
        if hits:
            lines = ["[최근 기억 페이지 — 자세한 내용은 memory_read_page·memory_query로 보세요]"]
            for h in hits:
                if isinstance(h, dict):
                    snippet = " ".join(str(h.get("snippet") or "").split())
                    lines.append(f"- {h.get('title') or h.get('path')} ({h.get('path', '')}): {_truncate(snippet, 300)}")
            parts.append("\n".join(lines))
            shown.append(f"최근 기억 페이지 {len(hits)}개")
        return _truncate("\n\n".join(parts), MAX_NOTE_CHARS), shown

    def handoff(self, summary, files_touched, previous_id=None):
        """새 인계를 남기고 id를 돌려준다. previous_id(같은 대화의 앞선 인계)는 취소한다."""
        if previous_id:
            try:
                self.server.call("memory_handoff_cancel", {**self.scope, "handoff_id": previous_id})
            except MCPError:
                pass  # 이미 다른 에이전트가 받아 갔다
        data = _call_json(self.server, "memory_handoff_begin", {
            **self.scope,
            "cwd": self.cwd,
            "summary": _truncate(summary, MAX_SUMMARY_CHARS),
            "open_questions": [],
            "next_steps": [],
            "files_touched": list(files_touched)[:MAX_FILES],
        })
        return data.get("handoff_id") if isinstance(data, dict) else None
