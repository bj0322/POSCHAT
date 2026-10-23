# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""내장 MCP 서버 memory: 통합 메모리(memory_store)와 에이전트 인계(handoff)를 POSCHAT 에이전트에 MCP 도구로 연다
(커넥터 → 통합 메모리).

- 프로젝트는 작업 폴더에서 ai-memory와 같은 규칙(ai_memory.resolve_scope)으로 정한다. project 인자로 바꿀 수 있다.
- 다른 AI 클라이언트와 기억을 나누는 기능(Universal AI Memory Hub)은 1.10에서 넣지 않았다. 앱 실행 파일은 내장 서버를
  `--mcp-server <이름>`으로 띄우므로, POSCHAT이 아닌 클라이언트(initialize의 clientInfo.name)가 이 서버를 띄우면
  도구를 거부한다. 다른 코딩 에이전트와의 인계는 기존 ai-memory 연동을 쓴다.
"""
import ai_memory
import handoff
import memory_store
import office_mcp
from office_mcp import INT, READ_ONLY, STR, ToolFailure, _root, _schema

POSCHAT_CLIENT = "postech-genai-chat"
LOCAL_WRITES = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}
ARR = {"type": "array", "items": STR}
TESTS = {"type": "array", "items": {"type": "object"}}


def _only_poschat():
    name = str((office_mcp.CLIENT_INFO or {}).get("name") or "")
    if name and name != POSCHAT_CLIENT:
        raise ToolFailure("이 메모리 서버는 POSTECH GenAI Chat 안에서만 씁니다(다른 AI 클라이언트 연결은 지원하지 않음).")


def _project(project=None):
    if project:
        return str(project)
    try:
        workspace, name = ai_memory.resolve_scope(_root())
    except OSError:
        return ""
    return f"{workspace}/{name}"


def _call(fn, *args, **kwargs):
    _only_poschat()
    try:
        return fn(*args, **kwargs)
    except (memory_store.MemoryStoreError, handoff.HandoffError) as e:
        raise ToolFailure(str(e))


def memory_search(query, layers=None, project=None, limit=10):
    _only_poschat()
    layers = [layers] if isinstance(layers, str) else layers
    hits = memory_store.search(query, layers=layers, project=_project(project), limit=max(1, min(30, int(limit or 10))))
    return f"기억 검색 '{query}' (프로젝트 {_project(project) or '-'})\n" + memory_store.format_hits(hits)


def memory_write(text, layer="project", kind="note", project=None, title="", tags=None):
    entry, created = _call(memory_store.write, text, layer=layer, project=_project(project) if layer in ("project", "research") else "",
                           kind=kind, title=title, tags=tags, source="poschat")
    return (f"기억을 {'남겼습니다' if created else '갱신했습니다(같은 내용이 이미 있음)'}: id {entry['id']} "
            f"({entry['layer']}/{entry['project'] or '-'}, {entry['kind']})")


def memory_delete(id):  # noqa: A002 — 도구 인자 이름
    _call(memory_store.delete, id)
    return f"기억을 지웠습니다: {id}"


def project_context(project=None):
    _only_poschat()
    text = memory_store.project_context(_project(project))
    return text or f"프로젝트 '{_project(project)}'에 남은 기억이 없습니다. memory_write(layer='project')로 남기세요."


def handoff_create(goal, summary="", files_changed=None, commits=None, tools_run=None, tests=None, todo=None,
                   next_steps=None, approvals_needed=None, open_questions=None, idempotency_key=None, project=None,
                   from_agent=None):
    agent = from_agent or "poschat"
    rec, created = _call(handoff.create, goal, project=_project(project), idempotency_key=idempotency_key,
                         from_agent=agent, summary=summary, files_changed=files_changed, commits=commits,
                         tools_run=tools_run, tests=tests, todo=todo, next_steps=next_steps,
                         approvals_needed=approvals_needed, open_questions=open_questions)
    return ("인계를 남겼습니다" if created else "같은 키의 열린 인계를 갱신했습니다") + f":\n{handoff.format_handoff(rec)}"


def handoff_list(project=None, status="open", limit=10):
    _only_poschat()
    items = handoff.list_handoffs(project=_project(project), status=status or None, limit=max(1, min(50, int(limit or 10))))
    if not items:
        return f"{status or ''} 인계가 없습니다."
    return "\n\n".join(handoff.format_handoff(r) for r in items)


def handoff_accept(task_id=None, project=None, agent=None):
    who = agent or "poschat"
    rec = _call(handoff.accept, who, task_id=task_id, project=_project(project))
    if rec is None:
        return "받을 열린 인계가 없습니다(이미 다른 에이전트가 받았을 수 있습니다)."
    return "인계를 받았습니다. 아래 내용을 이어서 작업하세요. 끝나면 handoff_complete를 부르세요.\n" + handoff.format_handoff(rec, long=True)


def handoff_complete(task_id, result=""):
    return "인계를 마쳤습니다:\n" + handoff.format_handoff(_call(handoff.complete, task_id, result))


TOOLS = {
    "memory_search": (memory_search, "통합 메모리에서 찾습니다: 프로젝트 결정·진행 상태·TODO, 연구 기록, 대화 요약, memory.md, USER.md, 예전 대화. "
                                     "layers: profile|global|conversation|project|research 배열(비우면 전체)",
                      _schema({"query": STR, "layers": ARR, "project": STR, "limit": INT}, ["query"]), READ_ONLY),
    "memory_write": (memory_write, "기억을 남깁니다. layer: project(기본)|research|conversation|profile. "
                                   "kind: decision|status|todo|issue|experiment|result|hypothesis|data|preference|summary|note. "
                                   "같은 내용은 하나로 합칩니다.",
                     _schema({"text": STR, "layer": STR, "kind": STR, "project": STR, "title": STR, "tags": ARR}, ["text"]),
                     LOCAL_WRITES),
    "memory_delete": (memory_delete, "기억을 지웁니다(사용자 승인 필요).", _schema({"id": STR}, ["id"]), DESTRUCTIVE),
    "project_context": (project_context, "이 프로젝트의 최근 결정·진행 상태·TODO·이슈와 열린 인계를 한 번에 봅니다. 작업을 시작할 때 쓰세요.",
                        _schema({"project": STR}, []), READ_ONLY),
    "handoff_create": (handoff_create, "다른 에이전트가 이어받을 인계를 남깁니다: goal, summary, files_changed, commits, tools_run, "
                                       "tests([{command, result, passed}]), todo, next_steps, approvals_needed, open_questions. "
                                       "같은 idempotency_key의 열린 인계가 있으면 갱신합니다.",
                       _schema({"goal": STR, "summary": STR, "files_changed": ARR, "commits": ARR, "tools_run": ARR,
                                "tests": TESTS, "todo": ARR, "next_steps": ARR, "approvals_needed": ARR,
                                "open_questions": ARR, "idempotency_key": STR, "project": STR, "from_agent": STR},
                               ["goal"]), LOCAL_WRITES),
    "handoff_list": (handoff_list, "인계 목록. status: open(기본)|accepted|completed|cancelled",
                     _schema({"project": STR, "status": STR, "limit": INT}, []), READ_ONLY),
    "handoff_accept": (handoff_accept, "열린 인계를 받습니다(task_id가 없으면 이 프로젝트의 최근 것). 한 인계는 한 에이전트만 받을 수 있습니다.",
                       _schema({"task_id": STR, "project": STR, "agent": STR}, []), LOCAL_WRITES),
    "handoff_complete": (handoff_complete, "받은 인계를 끝냈다고 기록합니다.",
                         _schema({"task_id": STR, "result": STR}, ["task_id"]), LOCAL_WRITES),
}
