# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""내장 MCP 서버 github: GitHub REST API로 저장소·코드·이슈·PR·커밋·Actions를 다룬다(커넥터 → GitHub).

토큰은 connectors.credential("github")로 읽는다: secret_store의 Personal Access Token(Fine-grained 권장),
없으면 OAuth 디바이스 흐름으로 받은 토큰. 앱 설정 파일에는 토큰이 없다.
쓰기 도구(이슈 만들기·고치기·댓글, PR 리뷰)는 connectors.TOOL_KINDS에서 write·send로 정해 항상 승인을 받는다.

GitHub 공식 MCP 서버(github/github-mcp-server)는 Go 바이너리라 안드로이드에서 띄울 수 없고, 원격 서버는
HTTP 전송이라 이 앱의 stdio 클라이언트로 붙일 수 없다. 데스크톱에 바이너리가 있으면 mcp_client의 추천 서버
github-official(읽기 전용)로 함께 쓸 수 있다.
"""
import base64
import re
import time
from urllib.parse import quote

import connectors
import oauth
import storage
from office_mcp import INT, READ_ONLY, STR, ToolFailure, _schema, http

API = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_CHARS = 20000
WRITES_REMOTE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,100}/[A-Za-z0-9_.\-]{1,100}$")
ERROR_LINE_RE = re.compile(r"(##\[error\]|\berror\b|\bfailed\b|\bfailure\b|traceback|exception|assert|✗|❌|exit code [1-9])",
                           re.IGNORECASE)
TIMESTAMP_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z ")


def _base():
    url = str(connectors.option(storage.load_config(), "github", "api_url", API)).rstrip("/")
    if not url.startswith("https://"):
        raise ToolFailure("GitHub API 주소는 https://로 시작해야 합니다.")
    return url


def _token():
    try:
        return connectors.credential("github")
    except oauth.NeedsAuth as e:
        raise ToolFailure(f"{connectors.NEEDS_AUTH_TAG} GitHub에 연결되어 있지 않습니다({e}). "
                          "연결·도구 → 커넥터 → GitHub에서 토큰을 넣거나 로그인하세요.")
    except oauth.OAuthError as e:
        raise ToolFailure(f"GitHub 토큰을 갱신하지 못했습니다: {e}")


def _repo(repo):
    text = str(repo or "").strip()
    m = re.match(r"^(?:https?://[^/]+/)?([^/\s]+/[^/\s#?]+?)(?:\.git)?(?:[/#?].*)?$", text)
    value = m.group(1) if m else text
    if not REPO_RE.match(value) or any(part in (".", "..") for part in value.split("/")):
        raise ToolFailure(f"저장소는 'owner/name' 형식으로 주세요: {text}")
    return value


def _num(value, name="number"):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ToolFailure(f"{name}는 숫자여야 합니다: {value}")
    if n <= 0:
        raise ToolFailure(f"{name}가 잘못되었습니다: {value}")
    return n


def _limit(value, default=20, hi=100):
    try:
        return max(1, min(hi, int(value or default)))
    except (TypeError, ValueError):
        return default


def _api(method, path, params=None, body=None, accept="application/vnd.github+json", raw=False):
    headers = {"Authorization": f"Bearer {_token()}", "Accept": accept, "X-GitHub-Api-Version": API_VERSION}
    url = path if path.startswith("https://") else _base() + path
    for attempt in range(3):
        r = http(method, url, params=params, json=body, headers=headers, timeout=60)
        retry_after = r.headers.get("Retry-After")
        if method == "GET" and attempt < 2 and (r.status_code in (502, 503, 504) or r.status_code == 429
                                                or (r.status_code == 403 and retry_after)):
            time.sleep(min(10.0, float(retry_after or 2 * (attempt + 1))))
            continue
        break
    if r.status_code in (200, 201):
        return r.text if raw else (r.json() if r.content else {})
    if r.status_code == 204:
        return {}
    try:
        message = r.json().get("message", "")
    except ValueError:
        message = r.text[:300]
    if r.status_code == 401:
        raise ToolFailure(f"{connectors.NEEDS_AUTH_TAG} GitHub 토큰이 올바르지 않거나 만료되었습니다. 새 토큰을 넣거나 다시 로그인하세요.")
    if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
        reset = int(r.headers.get("X-RateLimit-Reset") or 0)
        wait = max(0, reset - int(time.time())) // 60 + 1 if reset else "?"
        raise ToolFailure(f"GitHub API 사용 한도를 다 썼습니다. 약 {wait}분 뒤 다시 시도하세요.")
    if r.status_code == 403:
        raise ToolFailure(f"{connectors.SCOPE_TAG} 토큰에 이 작업 권한이 없습니다. Fine-grained token이라면 저장소 선택과 "
                          f"권한(Contents·Issues·Pull requests·Actions)을 확인하세요. ({message})")
    if r.status_code == 404:
        raise ToolFailure("GitHub에서 찾지 못했습니다. 이름이 맞는지, 비공개 저장소라면 토큰에 그 저장소 권한이 있는지 확인하세요."
                          f" ({message})")
    if r.status_code == 422:
        try:
            errors = "; ".join(str(e.get("message") or e) for e in r.json().get("errors") or [])
        except ValueError:
            errors = ""
        raise ToolFailure(f"GitHub가 요청을 받아들이지 않았습니다: {message} {errors}".strip())
    raise ToolFailure(f"GitHub 요청에 실패했습니다(HTTP {r.status_code}): {message}")


def _clip(text, max_chars, hint="범위를 좁혀 다시 요청하세요."):
    max_chars = max(1000, min(100000, int(max_chars or DEFAULT_CHARS)))
    return text if len(text) <= max_chars else text[:max_chars] + f"\n\n…({max_chars:,}자에서 잘랐습니다. {hint})"


def _day(ts):
    return str(ts or "")[:10]


def _user(obj):
    return (obj or {}).get("login") or "?"


# ---- 저장소 ----

def whoami():
    me = _api("GET", "/user")
    rate = _api("GET", "/rate_limit").get("resources", {}).get("core", {})
    return (f"로그인: {me.get('login')} ({me.get('name') or '이름 없음'})\n"
            f"API 남은 한도: {rate.get('remaining', '?')}/{rate.get('limit', '?')}")


def verify(cid="github", config=None):
    """커넥터 연결 확인(connectors.verify가 부른다)."""
    me = _api("GET", "/user")
    return {"account": me.get("login", ""), "detail": f"{me.get('login')} 계정으로 연결됨"}


def _repo_line(i, r):
    flags = [r.get("visibility") or ("private" if r.get("private") else "public")]
    if r.get("fork"):
        flags.append("fork")
    if r.get("archived"):
        flags.append("archived")
    desc = (r.get("description") or "").strip()
    return (f"{i}. {r['full_name']} ({', '.join(flags)}) ★{r.get('stargazers_count', 0)} · "
            f"{r.get('language') or '-'} · 업데이트 {_day(r.get('pushed_at') or r.get('updated_at'))}"
            + (f"\n   {desc[:200]}" if desc else ""))


def list_repos(query=None, limit=30, affiliation="owner,collaborator,organization_member"):
    limit = _limit(limit, 30)
    repos = _api("GET", "/user/repos", {"sort": "pushed", "per_page": 100 if query else limit,
                                        "affiliation": affiliation})
    if query:
        q = str(query).lower()
        repos = [r for r in repos if q in r["full_name"].lower() or q in (r.get("description") or "").lower()]
    repos = repos[:limit]
    if not repos:
        return "저장소가 없습니다." + (" 검색어를 바꾸거나 search_repos를 쓰세요." if query else "")
    return f"내 저장소 {len(repos)}개 (최근 push 순)\n\n" + "\n".join(_repo_line(i, r) for i, r in enumerate(repos, 1))


def search_repos(query, limit=10):
    data = _api("GET", "/search/repositories", {"q": str(query), "per_page": _limit(limit, 10, 50)})
    items = data.get("items") or []
    if not items:
        return f"'{query}'에 맞는 저장소가 없습니다."
    return (f"저장소 검색 '{query}' (전체 {data.get('total_count', len(items))}개 중 {len(items)}개)\n\n"
            + "\n".join(_repo_line(i, r) for i, r in enumerate(items, 1)))


def get_file(repo, path="", ref=None, max_chars=DEFAULT_CHARS):
    repo = _repo(repo)
    clean = "/".join(quote(part) for part in str(path or "").strip("/").split("/") if part and part not in (".", ".."))
    data = _api("GET", f"/repos/{repo}/contents/{clean}", {"ref": ref} if ref else None)
    if isinstance(data, list):
        lines = [f"{'📁' if e.get('type') == 'dir' else '📄'} {e['path']}" + (f" ({e.get('size', 0):,} bytes)"
                 if e.get("type") == "file" else "") for e in data]
        return f"{repo}/{path or ''} 폴더 ({len(data)}개)\n" + "\n".join(lines)
    if data.get("type") != "file":
        return f"{data.get('path')}는 파일이 아닙니다({data.get('type')})."
    if data.get("encoding") == "base64" and data.get("content"):
        raw = base64.b64decode(data["content"])
    elif data.get("download_url"):
        raw = _api("GET", data["download_url"], raw=True).encode("utf-8")
    else:
        raw = b""
    if b"\x00" in raw[:2048]:
        return f"{data['path']}는 텍스트 파일이 아닙니다({data.get('size', 0):,} bytes)."
    text = raw.decode("utf-8", errors="replace")
    return f"{repo}:{data['path']}" + (f"@{ref}" if ref else "") + f" ({text.count(chr(10)) + 1}줄)\n\n" + _clip(text, max_chars)


def search_code(query, repo=None, limit=10):
    q = str(query or "").strip()
    if not q:
        raise ToolFailure("query가 비어 있습니다.")
    if repo:
        q += f" repo:{_repo(repo)}"
    data = _api("GET", "/search/code", {"q": q, "per_page": _limit(limit, 10, 50)},
                accept="application/vnd.github.text-match+json")
    items = data.get("items") or []
    if not items:
        return f"'{q}'에 맞는 코드가 없습니다."
    lines = [f"코드 검색 '{q}' (전체 {data.get('total_count', len(items))}건 중 {len(items)}건)\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['repository']['full_name']}:{item['path']}")
        for match in (item.get("text_matches") or [])[:2]:
            fragment = " ".join(str(match.get("fragment", "")).split())
            lines.append(f"   … {fragment[:300]}")
    return "\n".join(lines)


# ---- 이슈 ----

def _issue_line(i):
    labels = ", ".join(lb["name"] for lb in i.get("labels") or [] if isinstance(lb, dict))
    kind = "PR" if "pull_request" in i else "이슈"
    return (f"#{i['number']} [{i.get('state')}] {i.get('title')} — {kind}, {_user(i.get('user'))}, "
            f"{_day(i.get('created_at'))}, 댓글 {i.get('comments', 0)}" + (f", 라벨: {labels}" if labels else ""))


def list_issues(repo, state="open", labels=None, limit=20):
    repo = _repo(repo)
    params = {"state": state if state in ("open", "closed", "all") else "open", "per_page": _limit(limit)}
    if labels:
        params["labels"] = labels if isinstance(labels, str) else ",".join(labels)
    items = [i for i in _api("GET", f"/repos/{repo}/issues", params) if "pull_request" not in i]
    if not items:
        return f"{repo}에 {params['state']} 이슈가 없습니다."
    return f"{repo} 이슈 {len(items)}개\n" + "\n".join(_issue_line(i) for i in items)


def get_issue(repo, number, max_chars=DEFAULT_CHARS):
    repo, number = _repo(repo), _num(number)
    issue = _api("GET", f"/repos/{repo}/issues/{number}")
    comments = _api("GET", f"/repos/{repo}/issues/{number}/comments", {"per_page": 50}) if issue.get("comments") else []
    parts = [_issue_line(issue), f"URL: {issue.get('html_url')}", "", issue.get("body") or "(본문 없음)"]
    for c in comments:
        parts += ["", f"--- 댓글: {_user(c.get('user'))}, {_day(c.get('created_at'))} ---", c.get("body") or ""]
    return _clip("\n".join(parts), max_chars)


def create_issue(repo, title, body="", labels=None, assignees=None):
    repo = _repo(repo)
    if not str(title or "").strip():
        raise ToolFailure("title이 비어 있습니다.")
    payload = {"title": str(title), "body": str(body or "")}
    if labels:
        payload["labels"] = [labels] if isinstance(labels, str) else list(labels)
    if assignees:
        payload["assignees"] = [assignees] if isinstance(assignees, str) else list(assignees)
    issue = _api("POST", f"/repos/{repo}/issues", body=payload)
    return f"이슈를 만들었습니다: #{issue['number']} {issue['title']}\n{issue.get('html_url')}"


def update_issue(repo, number, title=None, body=None, state=None, labels=None):
    repo, number = _repo(repo), _num(number)
    payload = {}
    if title is not None:
        payload["title"] = str(title)
    if body is not None:
        payload["body"] = str(body)
    if state is not None:
        if state not in ("open", "closed"):
            raise ToolFailure("state는 open 또는 closed입니다.")
        payload["state"] = state
    if labels is not None:
        payload["labels"] = [labels] if isinstance(labels, str) else list(labels)
    if not payload:
        raise ToolFailure("바꿀 내용(title·body·state·labels)이 없습니다.")
    issue = _api("PATCH", f"/repos/{repo}/issues/{number}", body=payload)
    return f"#{issue['number']}을(를) 고쳤습니다: {', '.join(payload)}\n{issue.get('html_url')}"


def comment_issue(repo, number, body):
    repo, number = _repo(repo), _num(number)
    if not str(body or "").strip():
        raise ToolFailure("body가 비어 있습니다.")
    c = _api("POST", f"/repos/{repo}/issues/{number}/comments", body={"body": str(body)})
    return f"#{number}에 댓글을 남겼습니다.\n{c.get('html_url')}"


# ---- PR ----

def list_pulls(repo, state="open", limit=20):
    repo = _repo(repo)
    state = state if state in ("open", "closed", "all") else "open"
    items = _api("GET", f"/repos/{repo}/pulls", {"state": state, "per_page": _limit(limit), "sort": "updated",
                                                   "direction": "desc"})
    if not items:
        return f"{repo}에 {state} PR이 없습니다."
    lines = [f"{repo} PR {len(items)}개"]
    for p in items:
        lines.append(f"#{p['number']} [{p['state']}{', draft' if p.get('draft') else ''}] {p['title']} — "
                     f"{_user(p.get('user'))}, {p['head']['ref']} → {p['base']['ref']}, 업데이트 {_day(p.get('updated_at'))}")
    return "\n".join(lines)


def get_pull(repo, number, max_chars=DEFAULT_CHARS):
    repo, number = _repo(repo), _num(number)
    p = _api("GET", f"/repos/{repo}/pulls/{number}")
    files = _api("GET", f"/repos/{repo}/pulls/{number}/files", {"per_page": 100})
    reviews = _api("GET", f"/repos/{repo}/pulls/{number}/reviews", {"per_page": 50})
    lines = [f"#{p['number']} {p['title']} [{p['state']}{', merged' if p.get('merged') else ''}"
             f"{', draft' if p.get('draft') else ''}]",
             f"작성: {_user(p.get('user'))} · {p['head']['ref']} → {p['base']['ref']} · 커밋 {p.get('commits')}개 · "
             f"+{p.get('additions')} −{p.get('deletions')} · 파일 {p.get('changed_files')}개",
             f"병합 가능: {p.get('mergeable')} ({p.get('mergeable_state')}) · head {p['head']['sha'][:12]}",
             f"URL: {p.get('html_url')}", "", p.get("body") or "(본문 없음)", "", "변경 파일:"]
    lines += [f"- {f['filename']} ({f['status']}, +{f['additions']} −{f['deletions']})" for f in files]
    if reviews:
        lines += ["", "리뷰:"] + [f"- {_user(r.get('user'))}: {r.get('state')} {(r.get('body') or '')[:200]}"
                                 for r in reviews]
    lines.append("\n전체 diff는 get_pull_diff로 보세요.")
    return _clip("\n".join(lines), max_chars)


def get_pull_diff(repo, number, file=None, max_chars=DEFAULT_CHARS):
    repo, number = _repo(repo), _num(number)
    diff = _api("GET", f"/repos/{repo}/pulls/{number}", accept="application/vnd.github.diff", raw=True)
    if file:
        sections = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
        diff = "".join(s for s in sections if f" b/{file}" in s.split("\n", 1)[0])
        if not diff:
            raise ToolFailure(f"PR #{number}에 '{file}' 파일의 변경이 없습니다.")
    return f"PR #{number} diff ({len(diff):,}자)\n\n" + _clip(diff, max_chars, "file로 파일 하나만 보세요.")


def create_pull_review(repo, number, body="", event="COMMENT", comments=None, commit_id=None):
    repo, number = _repo(repo), _num(number)
    event = str(event or "COMMENT").upper()
    if event not in ("COMMENT", "APPROVE", "REQUEST_CHANGES"):
        raise ToolFailure("event는 COMMENT·APPROVE·REQUEST_CHANGES 중 하나입니다.")
    payload = {"event": event, "body": str(body or "")}
    if commit_id:
        payload["commit_id"] = str(commit_id)
    if comments:
        if not isinstance(comments, list):
            raise ToolFailure("comments는 {path, line, body} 객체 배열이어야 합니다.")
        clean = []
        for c in comments:
            if not isinstance(c, dict) or not c.get("path") or not c.get("body") or not c.get("line"):
                raise ToolFailure("comments의 각 항목에는 path·line·body가 필요합니다.")
            clean.append({"path": str(c["path"]), "line": int(c["line"]), "side": str(c.get("side") or "RIGHT"),
                          "body": str(c["body"])})
        payload["comments"] = clean
    if event != "APPROVE" and not payload["body"] and not payload.get("comments"):
        raise ToolFailure("리뷰 내용(body나 comments)이 비어 있습니다.")
    review = _api("POST", f"/repos/{repo}/pulls/{number}/reviews", body=payload)
    return f"PR #{number}에 리뷰({event})를 제출했습니다.\n{review.get('html_url', '')}"


# ---- 커밋 ----

def list_commits(repo, ref=None, path=None, limit=20):
    repo = _repo(repo)
    params = {"per_page": _limit(limit)}
    if ref:
        params["sha"] = str(ref)
    if path:
        params["path"] = str(path)
    items = _api("GET", f"/repos/{repo}/commits", params)
    if not items:
        return "커밋이 없습니다."
    lines = [f"{repo} 커밋 {len(items)}개" + (f" ({ref})" if ref else "")]
    for c in items:
        msg = (c["commit"]["message"] or "").splitlines()[0][:120]
        author = (c.get("author") or {}).get("login") or c["commit"]["author"].get("name")
        lines.append(f"{c['sha'][:10]} {_day(c['commit']['author'].get('date'))} {author}: {msg}")
    return "\n".join(lines)


def get_commit(repo, sha, max_chars=DEFAULT_CHARS):
    repo = _repo(repo)
    c = _api("GET", f"/repos/{repo}/commits/{quote(str(sha))}")
    lines = [f"커밋 {c['sha']}", f"작성: {c['commit']['author'].get('name')} {_day(c['commit']['author'].get('date'))}",
             "", c["commit"]["message"], "", f"변경: +{c['stats']['additions']} −{c['stats']['deletions']}", ""]
    for f in c.get("files") or []:
        lines.append(f"--- {f['filename']} ({f['status']}, +{f['additions']} −{f['deletions']})")
        if f.get("patch"):
            lines.append(f["patch"])
    return _clip("\n".join(lines), max_chars)


# ---- Actions ----

def list_workflow_runs(repo, branch=None, status=None, limit=10):
    repo = _repo(repo)
    params = {"per_page": _limit(limit, 10, 50)}
    if branch:
        params["branch"] = str(branch)
    if status:
        params["status"] = str(status)
    runs = _api("GET", f"/repos/{repo}/actions/runs", params).get("workflow_runs") or []
    if not runs:
        return "워크플로 실행 기록이 없습니다."
    lines = [f"{repo} Actions 실행 {len(runs)}개"]
    for r in runs:
        lines.append(f"run {r['id']} · {r.get('name')} · {r.get('event')} · {r.get('head_branch')} "
                     f"{(r.get('head_sha') or '')[:8]} · {r.get('status')}/{r.get('conclusion') or '-'} · "
                     f"{_day(r.get('created_at'))}")
    return "\n".join(lines) + "\n\n실패한 실행은 get_workflow_run으로 작업(job)을 보고 get_job_logs로 로그를 보세요."


def get_workflow_run(repo, run_id):
    repo, run_id = _repo(repo), _num(run_id, "run_id")
    run = _api("GET", f"/repos/{repo}/actions/runs/{run_id}")
    jobs = _api("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs", {"per_page": 100}).get("jobs") or []
    lines = [f"run {run_id} · {run.get('name')} · {run.get('status')}/{run.get('conclusion') or '-'} · "
             f"{run.get('head_branch')} {(run.get('head_sha') or '')[:8]}", f"URL: {run.get('html_url')}", "", "작업:"]
    for j in jobs:
        lines.append(f"- job {j['id']} {j.get('name')}: {j.get('status')}/{j.get('conclusion') or '-'}")
        for step in j.get("steps") or []:
            if step.get("conclusion") not in ("success", "skipped", None):
                lines.append(f"    ✗ 단계 {step.get('number')}: {step.get('name')} ({step.get('conclusion')})")
    return "\n".join(lines)


def analyze_log(text, context=3, max_errors=40):
    """Actions 로그에서 실패 원인 후보 줄을 앞뒤 문맥과 함께 뽑는다."""
    lines = [TIMESTAMP_RE.sub("", line) for line in text.splitlines()]
    step, picked, out = "", set(), []
    marks = []
    for i, line in enumerate(lines):
        if line.startswith("##[group]"):
            step = line[len("##[group]"):].strip()
        if ERROR_LINE_RE.search(line) and "::debug::" not in line:
            marks.append((i, step))
    for i, step_name in marks[:max_errors]:
        if i in picked:
            continue
        lo, hi = max(0, i - context), min(len(lines), i + context + 1)
        picked.update(range(lo, hi))
        out.append(f"[{step_name or '단계 알 수 없음'}] 줄 {i + 1}\n" + "\n".join(lines[lo:hi]))
    return out


def get_job_logs(repo, job_id, max_chars=DEFAULT_CHARS, tail=80):
    repo, job_id = _repo(repo), _num(job_id, "job_id")
    text = _api("GET", f"/repos/{repo}/actions/jobs/{job_id}/logs", raw=True)
    errors = analyze_log(text)
    tail_lines = [TIMESTAMP_RE.sub("", line) for line in text.splitlines()[-max(10, min(400, int(tail or 80))):]]
    parts = [f"job {job_id} 로그 ({len(text):,}자)"]
    parts.append("실패 원인 후보:\n\n" + "\n\n".join(errors) if errors else "오류로 보이는 줄을 찾지 못했습니다.")
    parts.append("--- 로그 끝부분 ---\n" + "\n".join(tail_lines))
    return _clip("\n\n".join(parts), max_chars)


REPO_HELP = "repo: 'owner/name' 또는 저장소 URL"

TOOLS = {
    "whoami": (whoami, "연결된 GitHub 계정과 API 남은 한도를 봅니다.", _schema({}, []), READ_ONLY),
    "list_repos": (list_repos, "내 저장소 목록(최근 push 순). query로 이름·설명을 거릅니다.",
                   _schema({"query": STR, "limit": INT}, []), READ_ONLY),
    "search_repos": (search_repos, "GitHub 전체에서 저장소를 찾습니다(GitHub 검색 문법: user:, org:, language: 등).",
                     _schema({"query": STR, "limit": INT}, ["query"]), READ_ONLY),
    "get_file": (get_file, "저장소의 파일 내용이나 폴더 목록을 봅니다. path를 비우면 최상위 폴더. ref는 브랜치·태그·커밋. " + REPO_HELP,
                 _schema({"repo": STR, "path": STR, "ref": STR, "max_chars": INT}, ["repo"]), READ_ONLY),
    "search_code": (search_code, "코드를 검색합니다(GitHub 코드 검색 문법). repo를 주면 그 저장소에서만.",
                    _schema({"query": STR, "repo": STR, "limit": INT}, ["query"]), READ_ONLY),
    "list_issues": (list_issues, "이슈 목록(PR 제외). state: open|closed|all. " + REPO_HELP,
                    _schema({"repo": STR, "state": STR, "labels": STR, "limit": INT}, ["repo"]), READ_ONLY),
    "get_issue": (get_issue, "이슈 본문과 댓글을 봅니다.", _schema({"repo": STR, "number": INT, "max_chars": INT},
                                                                ["repo", "number"]), READ_ONLY),
    "create_issue": (create_issue, "이슈를 만듭니다(사용자 승인 필요). labels·assignees는 문자열 배열.",
                     _schema({"repo": STR, "title": STR, "body": STR, "labels": {"type": "array", "items": STR},
                              "assignees": {"type": "array", "items": STR}}, ["repo", "title"]), WRITES_REMOTE),
    "update_issue": (update_issue, "이슈의 제목·본문·상태(open|closed)·라벨을 바꿉니다(사용자 승인 필요).",
                     _schema({"repo": STR, "number": INT, "title": STR, "body": STR, "state": STR,
                              "labels": {"type": "array", "items": STR}}, ["repo", "number"]), WRITES_REMOTE),
    "comment_issue": (comment_issue, "이슈나 PR에 댓글을 남깁니다(사용자 승인 필요).",
                      _schema({"repo": STR, "number": INT, "body": STR}, ["repo", "number", "body"]), WRITES_REMOTE),
    "list_pulls": (list_pulls, "PR 목록. state: open|closed|all.",
                   _schema({"repo": STR, "state": STR, "limit": INT}, ["repo"]), READ_ONLY),
    "get_pull": (get_pull, "PR의 설명·브랜치·변경 파일 목록·리뷰 상태를 봅니다.",
                 _schema({"repo": STR, "number": INT, "max_chars": INT}, ["repo", "number"]), READ_ONLY),
    "get_pull_diff": (get_pull_diff, "PR의 전체 diff(unified)를 봅니다. file로 파일 하나만 볼 수 있습니다. 리뷰·분석 전에 쓰세요.",
                      _schema({"repo": STR, "number": INT, "file": STR, "max_chars": INT}, ["repo", "number"]), READ_ONLY),
    "create_pull_review": (create_pull_review,
                           "PR에 리뷰를 제출합니다(사용자 승인 필요, 다른 사람에게 보입니다). event: COMMENT|APPROVE|REQUEST_CHANGES. "
                           "comments: [{path, line(새 파일 기준 줄 번호), body}]",
                           _schema({"repo": STR, "number": INT, "body": STR, "event": STR,
                                    "comments": {"type": "array", "items": {"type": "object"}}, "commit_id": STR},
                                   ["repo", "number"]), WRITES_REMOTE),
    "list_commits": (list_commits, "커밋 기록. ref(브랜치·태그·SHA)와 path(그 파일을 바꾼 커밋만)로 거릅니다.",
                     _schema({"repo": STR, "ref": STR, "path": STR, "limit": INT}, ["repo"]), READ_ONLY),
    "get_commit": (get_commit, "커밋 하나의 메시지와 파일별 변경(patch)을 봅니다.",
                   _schema({"repo": STR, "sha": STR, "max_chars": INT}, ["repo", "sha"]), READ_ONLY),
    "list_workflow_runs": (list_workflow_runs, "GitHub Actions 실행 목록. status: completed|in_progress|failure 등.",
                           _schema({"repo": STR, "branch": STR, "status": STR, "limit": INT}, ["repo"]), READ_ONLY),
    "get_workflow_run": (get_workflow_run, "Actions 실행 하나의 작업(job)과 실패한 단계를 봅니다.",
                         _schema({"repo": STR, "run_id": INT}, ["repo", "run_id"]), READ_ONLY),
    "get_job_logs": (get_job_logs, "작업(job) 로그에서 실패 원인 후보 줄(앞뒤 문맥 포함)과 로그 끝부분을 봅니다. "
                                   "워크플로 실패 원인을 분석할 때 쓰세요.",
                     _schema({"repo": STR, "job_id": INT, "max_chars": INT, "tail": INT}, ["repo", "job_id"]), READ_ONLY),
}
