# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""에이전트 작업 인계(Agent Handoff): 표준 형식과 상태 기계. JSON Schema는 docs/api/handoff.schema.json.

인계 하나
    task_id, idempotency_key, project, goal, status(open|accepted|completed|cancelled), from_agent, accepted_by,
    created, updated, 그리고 data: summary, files_changed, commits, tools_run, tests[{command, result, passed}],
    todo, next_steps, approvals_needed, open_questions, result

- 같은 idempotency_key의 열린(open) 인계가 있으면 새로 만들지 않고 그 인계를 갱신한다(목록은 합친다).
  SQLite 부분 고유 색인(status='open'일 때만 고유)이 이를 보장한다.
- 받기(accept)는 BEGIN IMMEDIATE + 조건부 UPDATE(WHERE status='open')라서 두 에이전트가 같은 인계를 함께 받을 수 없다.
- ai-memory가 연결돼 있으면 agent.py가 to_ai_memory()로 바꿔 ai-memory에도 남긴다.
"""
import json
import re
import sqlite3
import time
import uuid

import memory_store

STATUSES = ("open", "accepted", "completed", "cancelled")
LIST_FIELDS = ("files_changed", "commits", "tools_run", "todo", "next_steps", "approvals_needed", "open_questions")
MAX_ITEMS = 100


class HandoffError(Exception):
    pass


def _clean_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [v.strip() for v in re.split(r"\n|;", value) if v.strip()]
    return [str(v)[:500] for v in value if str(v).strip()][:MAX_ITEMS]


def _clean_tests(value):
    out = []
    for t in value or []:
        if isinstance(t, str):
            t = {"command": t}
        if isinstance(t, dict) and (t.get("command") or t.get("name")):
            out.append({"command": str(t.get("command") or t.get("name"))[:300],
                        "result": str(t.get("result") or "")[:500],
                        "passed": t.get("passed") if isinstance(t.get("passed"), bool) else None})
    return out[:50]


def _record(row):
    if row is None:
        return None
    rec = dict(row)
    rec.update(json.loads(rec.pop("data") or "{}"))
    return rec


def _merge_unique(old, new):
    return list(dict.fromkeys(list(old or []) + list(new or [])))[:MAX_ITEMS]


def create(goal, project="", idempotency_key=None, from_agent="poschat", summary="", files_changed=None, commits=None,
           tools_run=None, tests=None, todo=None, next_steps=None, approvals_needed=None, open_questions=None, now=None):
    """인계를 남긴다. 같은 키의 열린 인계가 있으면 갱신. (인계, 새로 만들었는지)"""
    goal = str(goal or "").strip()
    if not goal:
        raise HandoffError("goal(작업 목표)이 비어 있습니다.")
    now = now or time.time()
    key = str(idempotency_key or f"{from_agent}:{project}:{goal}")[:300]
    data = {"summary": str(summary or "")[:4000], "tests": _clean_tests(tests),
            **{f: _clean_list(v) for f, v in (("files_changed", files_changed), ("commits", commits),
                                              ("tools_run", tools_run), ("todo", todo), ("next_steps", next_steps),
                                              ("approvals_needed", approvals_needed),
                                              ("open_questions", open_questions))}}
    with memory_store.db() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM handoffs WHERE idempotency_key=? AND status='open'", (key,)).fetchone()
        if row:
            old = json.loads(row["data"] or "{}")
            merged = {**old, "summary": data["summary"] or old.get("summary", ""),
                      "tests": data["tests"] or old.get("tests", [])}
            for f in LIST_FIELDS:
                merged[f] = _merge_unique(old.get(f), data[f]) if f in ("files_changed", "commits", "tools_run") else (
                    data[f] or old.get(f, []))
            con.execute("UPDATE handoffs SET goal=?, data=?, updated=? WHERE task_id=?",
                        (goal[:1000], json.dumps(merged, ensure_ascii=False), now, row["task_id"]))
            return _record(con.execute("SELECT * FROM handoffs WHERE task_id=?", (row["task_id"],)).fetchone()), False
        task_id = "h-" + uuid.uuid4().hex[:12]
        con.execute("INSERT INTO handoffs(task_id, idempotency_key, project, goal, status, data, from_agent, created, updated) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (task_id, key, str(project or ""), goal[:1000], "open",
                                                   json.dumps(data, ensure_ascii=False), str(from_agent)[:80], now, now))
        return _record(con.execute("SELECT * FROM handoffs WHERE task_id=?", (task_id,)).fetchone()), True


def get(task_id):
    with memory_store.db() as con:
        rec = _record(con.execute("SELECT * FROM handoffs WHERE task_id=?", (str(task_id),)).fetchone())
    if rec is None:
        raise HandoffError(f"없는 인계입니다: {task_id}")
    return rec


def accept(agent, task_id=None, project=None, now=None):
    """열린 인계 하나를 받는다(task_id가 없으면 그 프로젝트의 가장 최근 것). 이미 다른 에이전트가 받았으면 None."""
    now = now or time.time()
    with memory_store.db() as con:
        con.execute("BEGIN IMMEDIATE")
        if task_id:
            target = str(task_id)
        else:
            row = con.execute("SELECT task_id FROM handoffs WHERE status='open' AND project=? ORDER BY updated DESC LIMIT 1",
                              (str(project or ""),)).fetchone()
            if row is None:
                return None
            target = row["task_id"]
        cur = con.execute("UPDATE handoffs SET status='accepted', accepted_by=?, updated=? WHERE task_id=? AND status='open'",
                          (str(agent)[:80], now, target))
        if cur.rowcount == 0:
            return None
        return _record(con.execute("SELECT * FROM handoffs WHERE task_id=?", (target,)).fetchone())


def _finish(task_id, status, result="", now=None):
    with memory_store.db() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM handoffs WHERE task_id=?", (str(task_id),)).fetchone()
        if row is None:
            raise HandoffError(f"없는 인계입니다: {task_id}")
        if row["status"] in ("completed", "cancelled"):
            return _record(row)  # 같은 요청을 다시 받아도 결과는 같다
        data = json.loads(row["data"] or "{}")
        if result:
            data["result"] = str(result)[:4000]
        con.execute("UPDATE handoffs SET status=?, data=?, updated=? WHERE task_id=?",
                    (status, json.dumps(data, ensure_ascii=False), now or time.time(), str(task_id)))
        return _record(con.execute("SELECT * FROM handoffs WHERE task_id=?", (str(task_id),)).fetchone())


def complete(task_id, result="", now=None):
    return _finish(task_id, "completed", result, now)


def cancel(task_id, now=None):
    return _finish(task_id, "cancelled", "", now)


def list_handoffs(project=None, status=None, limit=20):
    where, args = [], []
    if project is not None:
        where.append("project=?")
        args.append(str(project))
    if status:
        where.append("status=?")
        args.append(status)
    sql = "SELECT * FROM handoffs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated DESC LIMIT ?"
    with memory_store.db() as con:
        return [_record(r) for r in con.execute(sql, (*args, int(limit)))]


def upsert_raw(rec):
    """동기화: 다른 기기의 인계를 넣는다. 받기·끝내기가 앞선 상태로 돌아가지 않게 상태 순서를 지킨다."""
    order = {s: i for i, s in enumerate(STATUSES)}
    data = {k: rec.get(k) for k in ("summary", "tests", "result", *LIST_FIELDS) if k in rec}
    with memory_store.db() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT status, updated FROM handoffs WHERE task_id=?", (rec["task_id"],)).fetchone()
        if row and (order.get(row["status"], 0) > order.get(rec["status"], 0) or
                    (row["status"] == rec["status"] and (row["updated"] or 0) >= (rec.get("updated") or 0))):
            return False
        values = (rec.get("idempotency_key") or rec["task_id"], rec.get("project", ""), rec.get("goal", ""), rec["status"],
                  json.dumps(data, ensure_ascii=False), rec.get("from_agent", ""), rec.get("accepted_by", ""),
                  rec.get("created"), rec.get("updated"))
        try:
            if row:
                con.execute("UPDATE handoffs SET idempotency_key=?, project=?, goal=?, status=?, data=?, from_agent=?, "
                            "accepted_by=?, created=?, updated=? WHERE task_id=?", (*values, rec["task_id"]))
            else:
                con.execute("INSERT INTO handoffs(idempotency_key, project, goal, status, data, from_agent, accepted_by, "
                            "created, updated, task_id) VALUES (?,?,?,?,?,?,?,?,?,?)", (*values, rec["task_id"]))
        except sqlite3.IntegrityError:
            return False  # 이 기기에도 같은 키의 열린 인계가 있다: 이 기기의 것을 유지한다
        return True


def to_ai_memory(rec):
    """ai-memory memory_handoff_begin 인자로."""
    summary = rec.get("summary") or rec["goal"]
    tests = [f"{t['command']}: {'통과' if t.get('passed') else '실패' if t.get('passed') is False else t.get('result', '')}"
             for t in rec.get("tests") or []]
    if tests:
        summary += "\n테스트: " + "; ".join(tests)
    return {"summary": summary[:1200], "open_questions": rec.get("open_questions") or [],
            "next_steps": (rec.get("next_steps") or []) + (rec.get("todo") or []),
            "files_touched": rec.get("files_changed") or []}


def format_handoff(rec, long=False):
    lines = [f"[{rec['task_id']}] {rec['status']} · {rec.get('project') or '-'} · {rec.get('from_agent') or '?'}"
             + (f" → {rec['accepted_by']}" if rec.get("accepted_by") else "")
             + f" · {time.strftime('%Y-%m-%d %H:%M', time.localtime(rec.get('updated') or 0))}",
             f"목표: {rec['goal']}"]
    if rec.get("summary"):
        lines.append(f"요약: {rec['summary'] if long else rec['summary'][:300]}")
    labels = {"files_changed": "변경 파일", "commits": "커밋", "tools_run": "실행한 도구", "todo": "미완료 작업",
              "next_steps": "다음 단계", "approvals_needed": "필요한 승인", "open_questions": "남은 질문"}
    for field, label in labels.items():
        items = rec.get(field) or []
        if items:
            shown = items if long else items[:8]
            lines.append(f"{label}: " + "; ".join(shown) + (f" 외 {len(items) - len(shown)}개" if len(items) > len(shown) else ""))
    for t in rec.get("tests") or []:
        mark = "통과" if t.get("passed") else "실패" if t.get("passed") is False else "결과"
        lines.append(f"테스트 {mark}: {t['command']}" + (f" — {t['result'][:200]}" if t.get("result") else ""))
    if rec.get("result"):
        lines.append(f"결과: {rec['result']}")
    return "\n".join(lines)
