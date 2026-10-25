# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code 에이전트(1.16): Codex·Claude Code처럼 작업을 맡기면 에이전트가 작업 폴더에서 스스로 읽고·고치고·실행해 확인한다.

- 작업(task)은 이어서 지시할 수 있는 세션이다. 데이터 폴더의 code/tasks/<id>.json에 대화·단계·계획·바뀐 파일을 남긴다.
- 에이전트 루프는 agent.Agent를 그대로 쓴다(같은 도구·같은 외부 데이터 감싸기). CodeAgent는 다음만 바꾼다.
  - plan 단계: 할 일 목록을 화면에 체크리스트로 보인다.
  - 파일 수정: 승인 방식이 '수정 자동'(기본)이면 바로 적용하되, 처음 고치기 전에 원본을 백업해 작업 단위·파일 단위로 되돌릴 수 있다.
    '매번 묻기'면 예전처럼 승인 창으로 묻는다. 어느 쪽이든 읽은 뒤 파일이 바뀌었으면 덮어쓰지 않는다.
  - 명령 실행: 매번 승인(Bridge의 승인 창, '이번 실행 동안 허용' 없음). code_runner.RunManager로 실행해 출력이 실시간으로 흐르고,
    비밀 환경 변수를 넘기지 않고, 출력의 비밀을 가리고, 멈추면 프로세스 트리를 끝낸다.
- 되돌리기는 에이전트가 쓴 내용 그대로일 때만 한다(그 뒤 사용자가 고쳤으면 건너뛰고 알린다).
"""
import fnmatch
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import adaptive_engine
import code_project
import code_runner
import code_workspace as cw
import documents
import storage
from agent import ACTION_DOCS, MAX_READ_CHARS, Agent, ToolError, _truncate
from code_workspace import atomic_write

MAX_TASKS = 100
MAX_STEPS_KEPT = 400
MAX_DETAIL = 12000
# 권한 모드(1.17.1, Claude Code의 권한 모드·Codex의 승인 방식): 계획(읽기만) · 매번 묻기 · 수정 자동(기본) · 전체 자동
APPROVALS = ("plan", "ask", "auto_edit", "full_auto")
# '수정 자동'이어도 승인 창으로 묻는 파일: 다음 git commit·편집기 열기·셸 진입 때 저절로 프로그램을 실행하게 하는 설정.
# (.git 안은 에이전트가 아예 고치지 않는다 — agent._in_git_dir)
AUTO_RUN_FILES = re.compile(
    r"(?i)(^|/)(\.husky/|\.githooks/|\.pre-commit-config\.ya?ml$|\.pre-commit-hooks\.ya?ml$|lefthook(-local)?\.ya?ml$|"
    r"\.lefthook(-local)?\.ya?ml$|\.envrc$|\.vscode/(tasks|settings|launch)\.json$|\.idea/|\.devcontainer/|"
    r"\.gitattributes$|\.gitmodules$)")
PLAN_DOC = '{"action": "plan", "steps": ["할 일 1", "할 일 2"], "done": [0]}  할 일 목록 쓰기·갱신(done: 끝낸 항목 번호, 0부터)'
CODE_RULES = """[코딩 에이전트 지침 — Codex·Claude Code처럼 일하세요]
- 여러 단계가 필요한 작업이면 먼저 plan으로 할 일 목록(3~7개)을 쓰고, 하나씩 끝낼 때마다 plan의 done을 갱신하세요.
- 고치기 전에 list·search·read로 관련 코드를 찾아 읽으세요. 추측으로 고치지 마세요.
- 필요한 곳만 작게 고치세요(edit 우선). 요청과 관계없는 파일·서식은 건드리지 마세요.
- 고친 뒤에는 테스트·빌드·실행(run)으로 확인하고, 실패하면 원인을 찾아 다시 고치세요. 테스트가 없으면 가능한 가장 작은 확인을 하세요.
- 명령은 사용자가 매번 승인합니다. 거부되면 같은 명령을 다시 시도하지 말고 다른 확인 방법을 쓰거나 done으로 알리세요.
- git commit·push·reset·clean, 패키지 설치, 작업 폴더 밖 파일 수정은 사용자가 요청한 경우에만 하세요.
- done의 answer에는 무엇을 왜 바꿨는지(파일별), 확인한 결과(명령과 통과·실패), 남은 일을 짧게 쓰세요."""
CODE_TOOLS_DOC = """{"action": "read", "path": "파일", "offset": 1, "limit": 200}  줄 번호를 붙여 보기(offset·limit은 선택, 긴 파일은 나눠 읽기)
{"action": "glob", "pattern": "**/*.py"}  이름 꼴로 파일 찾기(최근에 고친 순)
{"action": "edit", "path": "파일", "old": "...", "new": "...", "replace_all": true}  같은 문자열을 모두 바꾸기(replace_all은 선택)
{"action": "multi_edit", "path": "파일", "edits": [{"old": "...", "new": "..."}], "reason": "이유"}  한 파일 여러 곳을 한 번에(하나라도 안 맞으면 아무것도 안 바꿈)
{"action": "run", "command": "명령", "background": true}  서버·감시처럼 끝나지 않는 명령을 백그라운드로(기다리지 않음)
{"action": "job_output", "job": 1, "wait": 5}  백그라운드 명령의 상태·최근 출력(wait초까지 기다림)
{"action": "job_stop", "job": 1}  백그라운드 명령 멈춤
어느 단계에나 "note": "사용자에게 보일 한 줄 설명"을 붙일 수 있습니다(무엇을 왜 하는지)."""
MODE_RULES = {
    "plan": "[권한: 계획 모드] 파일을 고치거나 명령을 실행하지 마세요(막혀 있습니다). list·read·search·glob으로 조사한 뒤 done의 answer에 "
            "실행 계획을 쓰세요: 바꿀 파일과 방법, 순서, 확인할 명령, 위험과 질문. 사용자가 승인하면 그 계획대로 진행합니다.",
    "ask": "[권한: 매번 묻기] 파일 수정과 명령 실행을 사용자가 하나씩 승인합니다.",
    "auto_edit": "[권한: 수정 자동] 파일 수정은 바로 적용됩니다(되돌리기 가능). 명령 실행은 사용자가 승인합니다.",
    "full_auto": "[권한: 전체 자동] 파일 수정과 명령 실행이 바로 됩니다. 단, 위험한 동작·네트워크를 쓰는 명령은 사용자가 승인합니다. "
                 "그래도 요청과 관계없는 명령·설치·삭제는 하지 마세요.",
}
CODE_RULES += """
- read 결과 앞의 줄 번호와 탭은 파일 내용이 아닙니다. edit의 old에는 넣지 마세요.
- 파일을 찾을 때는 glob(이름)·search(내용)를 쓰고, 긴 파일은 offset·limit으로 필요한 부분만 읽으세요.
- [프로젝트 지침]이 있으면 따르고, 테스트·빌드는 [프로젝트 정보]의 명령을 먼저 확인하세요.
- 끝나지 않는 명령(개발 서버·watch)은 background로 실행하고 job_output으로 확인하세요. 일반 명령은 background를 쓰지 마세요."""


class TaskError(Exception):
    pass


def tasks_dir():
    d = storage.APP_DIR / "code" / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _task_path(task_id):
    if not re.fullmatch(r"task-[0-9a-f]{10}", str(task_id or "")):
        raise TaskError("작업을 찾지 못했습니다.")
    return tasks_dir() / f"{task_id}.json"


def _sha(text):
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest() if text is not None else ""


class TaskStore:
    """작업 기록(JSON 파일). 한 프로세스 안에서 잠금으로 보호한다."""

    def __init__(self):
        self.lock = threading.RLock()

    def new(self, workspace, title, approval):
        tid = "task-" + uuid.uuid4().hex[:10]
        now = time.time()
        task = {"id": tid, "title": title[:80] or "새 작업", "workspace": str(workspace), "created": now, "updated": now,
                "status": "idle", "approval": approval, "turns": [], "steps": [], "plan": [], "changes": {}}
        self.save(task)
        self._prune()
        return task

    def load(self, task_id):
        p = _task_path(task_id)
        with self.lock:
            if not p.is_file():
                raise TaskError("작업을 찾지 못했습니다.")
            return json.loads(p.read_text(encoding="utf-8"))

    def save(self, task):
        task["updated"] = time.time()
        task["steps"] = task["steps"][-MAX_STEPS_KEPT:]
        with self.lock:
            atomic_write(_task_path(task["id"]), json.dumps(task, ensure_ascii=False).encode("utf-8"))

    def update(self, task_id, fn):
        with self.lock:
            task = self.load(task_id)
            fn(task)
            self.save(task)
            return task

    def list(self, workspace=None):
        out = []
        for p in sorted(tasks_dir().glob("task-*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if workspace and os.path.normcase(t.get("workspace", "")) != os.path.normcase(str(workspace)):
                continue
            out.append({k: t.get(k) for k in ("id", "title", "workspace", "created", "updated", "status")}
                       | {"changed": len(t.get("changes") or {}), "turns": len(t.get("turns") or [])})
        return out

    def delete(self, task_id):
        p = _task_path(task_id)
        with self.lock:
            import shutil

            shutil.rmtree(tasks_dir() / task_id, ignore_errors=True)
            p.unlink(missing_ok=True)

    def backup_dir(self, task_id):
        d = tasks_dir() / task_id / "backup"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _prune(self):
        files = sorted(tasks_dir().glob("task-*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        for p in files[MAX_TASKS:]:
            self.delete(p.stem)


def step_kind(summary):
    s = summary.lstrip()
    for prefix, kind in (("✏️", "edit"), ("▶", "run"), ("⛔", "denied"), ("⚠", "error"), ("📄", "read"), ("📂", "list"),
                         ("🔍", "search"), ("🧩", "skill"), ("🔎", "recall"), ("🌐", "browser"), ("📋", "plan"),
                         ("💬", "note"), ("🗣", "steer"), ("📟", "job"), ("⏹", "job"), ("✅", "rule"), ("📥", "apply"),
                         ("🗑", "revert")):
        if s.startswith(prefix):
            return kind
    return "info"


class CodeAgent(Agent):
    """agent.Agent + plan 단계 + 스트리밍 명령 실행(RunManager) + 1.17.1 도구(줄 번호 read, glob, multi_edit, 백그라운드 명령,
    note)·권한 모드·작업 중 지시. 파일 수정 정책은 review 콜백(CodeAgentApi)이 정한다."""

    step_purpose = "code_agent_step"  # 1.17 라우팅: 코드 수정·명령으로 이어지는 단계(중요·위험)

    def __init__(self, *args, runner=None, on_plan=None, on_run=None, mode="auto_edit", allowed=None, steer=None,
                 project_note="", **kwargs):
        super().__init__(*args, **kwargs)
        self.runner = runner      # code_runner.RunManager
        self.on_plan = on_plan    # (steps, done) -> None
        self.on_run = on_run      # (code_run_id) -> None: 지금 도는 명령(멈춤·출력 표시용)
        self.plan = []
        self.mode = mode if mode in APPROVALS else "auto_edit"
        self.allowed = allowed or (lambda command: False)   # '다시 묻지 않기' 규칙
        self.steer = steer or (lambda: [])                  # 작업 중 지시를 꺼낸다
        self.project_note = project_note
        self.jobs = []            # 백그라운드 명령(RunRecord)

    def _static_prompt(self, history, task, forced_skill):
        text = super()._static_prompt(history, task, forced_skill)
        head, sep, tail = text.partition("[규칙]\n")
        text = head.replace(ACTION_DOCS, ACTION_DOCS + "\n" + PLAN_DOC + "\n" + CODE_TOOLS_DOC, 1) + sep + tail
        rules = CODE_RULES + "\n" + MODE_RULES[self.mode]
        try:
            project = code_project.context_block(self.workspace, self.project_note)
        except Exception as e:  # 프로젝트 정보가 없어도 작업은 한다
            project = f"[프로젝트 정보]\n(읽지 못함: {type(e).__name__})"
        return text.replace("[작업 폴더]\n", rules + "\n\n" + project + "\n\n[작업 폴더]\n", 1)

    def run(self, history, task, forced_skill=None, attached=()):
        try:
            return super().run(history, task, forced_skill, attached)
        finally:
            for rec in self.jobs:   # 끝나면 백그라운드 명령도 멈춘다(남겨 두지 않는다)
                if not rec.ended and self.runner is not None:
                    try:
                        self.runner.stop(rec.id)
                    except code_runner.RunnerError:
                        pass

    def _steer_messages(self):
        out = []
        for msg in self.steer() or []:
            msg = str(msg).strip()[:20000]
            if msg:
                self.on_tool("🗣 추가 지시를 반영합니다", msg)
                out.append(msg)
        return out

    def _execute(self, action):
        note = str(action.get("note") or "").strip()
        if note:
            self.on_tool("💬 " + note[:600], "")
        return super()._execute({k: v for k, v in action.items() if k != "note"})

    # ---- 계획 모드: 읽기만 ----

    def _read_only(self, what):
        if self.mode == "plan":
            raise ToolError(f"계획 모드라 {what}하지 않습니다. 읽기·검색으로 조사한 뒤 done의 answer에 계획(바꿀 파일·방법·확인 방법)을 쓰세요.")

    def _check_text_target(self, p):
        self._read_only("파일을 고치")
        super()._check_text_target(p)

    def _tool_plan(self, steps=None, done=None, **_):
        items = [str(s).strip()[:200] for s in (steps or self.plan or []) if str(s).strip()][:12]
        if not items:
            raise ToolError("steps에 할 일을 하나 이상 쓰세요.")
        finished = set()
        for i in done or []:
            try:
                finished.add(int(i))
            except (TypeError, ValueError):
                continue
        self.plan = items
        if self.on_plan:
            self.on_plan(items, sorted(i for i in finished if 0 <= i < len(items)))
        lines = "\n".join(f"{'[x]' if i in finished else '[ ]'} {s}" for i, s in enumerate(items))
        self.on_tool(f"📋 계획 ({len(finished)}/{len(items)})", lines)
        return "계획을 기록했습니다:\n" + lines

    # ---- 읽기·찾기 ----

    def _tool_read(self, path, offset=0, limit=0):
        """텍스트 파일은 줄 번호를 붙여 보인다(Claude Code처럼). offset(1부터)·limit(줄 수)로 일부만 읽는다."""
        p = self._resolve(path)
        if documents.is_document(p):
            return super()._tool_read(path)
        text, _ = self._read_file(p)
        lines = text.splitlines()
        try:
            start = max(1, int(offset or 1))
            count = max(0, int(limit or 0))
        except (TypeError, ValueError):
            raise ToolError("offset·limit은 숫자로 쓰세요.")
        end = min(len(lines), start - 1 + count) if count else len(lines)
        out, used = [], 0
        for no in range(start, end + 1):
            row = f"{no:>6}\t{lines[no - 1]}"
            if used + len(row) > MAX_READ_CHARS and out:
                end = no - 1
                break
            out.append(row)
            used += len(row) + 1
        more = f"\n... ({end}/{len(lines)}줄까지 보임. 이어 읽기: offset={end + 1})" if end < len(lines) else ""
        rel = self._rel(p)
        span = f"{start}~{end}줄" if (start > 1 or end < len(lines)) else f"{len(lines)}줄"
        self.on_tool(f"📄 read {rel} ({span})", _truncate("\n".join(out), 3000))
        return ("\n".join(out) or "(빈 파일)") + more

    def _tool_glob(self, pattern, path="."):
        """이름 꼴로 파일 찾기(최근에 고친 순). 예: **/*.py, src/**/test_*.ts"""
        root = self._resolve(path)
        pat = str(pattern or "").strip().replace("\\", "/")
        if not pat:
            raise ToolError("pattern을 쓰세요. 예: **/*.py")
        alts = {pat, pat[3:] if pat.startswith("**/") else pat}
        found = []
        for f in self._iter_files(root):
            rel = self._rel(f)
            sub = f.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(sub, a) or fnmatch.fnmatch(rel, a) for a in alts) or ("/" not in pat and fnmatch.fnmatch(f.name, pat)):
                try:
                    found.append((f.stat().st_mtime, rel))
                except OSError:
                    continue
            if len(found) >= 2000:
                break
        found.sort(reverse=True)
        lines = [rel for _, rel in found[:200]]
        result = "\n".join(lines) + (f"\n... ({len(found)}개 중 200개)" if len(found) > 200 else "") if lines else "(일치하는 파일 없음)"
        self.on_tool(f"🔍 glob {pat} ({len(found)}개)", result)
        return result

    # ---- 고치기 ----

    def _tool_edit(self, path, old, new, reason="", replace_all=False):
        if not replace_all:
            return super()._tool_edit(path, old, new, reason)
        p = self._resolve(path)
        self._check_text_target(p)
        text, enc = self._read_file(p)
        old, new = str(old), str(new)
        if not old:
            raise ToolError("old가 비었습니다.")
        if old not in text and "\r\n" in text:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        n = text.count(old)
        if n == 0:
            raise ToolError("old 문자열을 파일에서 찾지 못했습니다. read로 정확한 내용을 다시 확인하세요.")
        return self._save(p, text, text.replace(old, new), enc, f"파일 수정({n}곳)", reason)

    def _tool_multi_edit(self, path, edits, reason=""):
        """한 파일의 여러 곳을 차례로 고친다. 하나라도 맞지 않으면 아무것도 바꾸지 않는다."""
        p = self._resolve(path)
        self._check_text_target(p)
        if not isinstance(edits, list) or not edits:
            raise ToolError("edits에 [{\"old\": ..., \"new\": ...}] 목록을 쓰세요.")
        text, enc = self._read_file(p)
        crlf = "\r\n" in text
        new_text = text
        for i, e in enumerate(edits[:50], 1):
            if not isinstance(e, dict):
                raise ToolError(f"{i}번째 항목이 객체가 아닙니다.")
            old, new = str(e.get("old") or ""), str(e.get("new") if e.get("new") is not None else "")
            if not old:
                raise ToolError(f"{i}번째 old가 비었습니다.")
            if old not in new_text and crlf:
                old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
            n = new_text.count(old)
            if n == 0:
                raise ToolError(f"{i}번째 old를 찾지 못했습니다(앞의 수정이 반영된 내용 기준). 아무것도 바꾸지 않았습니다.")
            if n > 1 and not e.get("replace_all"):
                raise ToolError(f"{i}번째 old가 {n}번 나옵니다. 더 길게 쓰거나 replace_all을 쓰세요. 아무것도 바꾸지 않았습니다.")
            new_text = new_text.replace(old, new) if e.get("replace_all") else new_text.replace(old, new, 1)
        return self._save(p, text, new_text, enc, f"파일 수정({len(edits)}곳)", reason)

    # ---- 명령 ----

    def _tool_run(self, command, background=False, timeout=600):
        self._read_only("명령을 실행")
        if self.runner is None:
            return super()._tool_run(command)
        command = str(command).strip()
        if not command:
            raise ToolError("command가 비었습니다.")
        info = code_runner.analyze(command)
        auto = (self.mode == "full_auto" and code_project.auto_run_ok(command)) or self.allowed(command)
        if not auto:
            detail = f"{self.workspace}>\n{command}"
            if info.get("dangers"):
                detail += "\n\n위험할 수 있는 동작: " + ", ".join(info["dangers"])
            if info.get("network"):
                detail += "\n이 명령은 인터넷(네트워크)을 쓸 수 있습니다."
            if background:
                detail += "\n(백그라운드로 실행하고 에이전트는 기다리지 않습니다. 작업이 끝나면 멈춥니다.)"
            prefix = code_project.command_prefix(command) if not info.get("dangers") and not info.get("network") else ""
            ok = self.confirm("run", "명령 실행", detail, remember=prefix) if prefix else self.confirm("run", "명령 실행", detail)
            if not ok:
                self.denied.append(f"명령 실행: {command[:200]}")
                self.on_tool(f"⛔ run 거부됨: {command}", "")
                return "사용자가 명령 실행을 거부했습니다."
        if self.cancelled():
            return "(작업을 중지했습니다.)"
        self._did_work = True
        self.tools_run.append(f"run: {command[:200]}")
        try:
            t = max(5, min(code_runner.MAX_TIMEOUT, int(timeout or 600)))
        except (TypeError, ValueError):
            t = 600
        if background:
            try:
                rec = self.runner.start(str(self.workspace), command, timeout=code_runner.MAX_TIMEOUT, purpose="Code 에이전트(백그라운드)")
            except code_runner.RunnerError as e:
                raise ToolError(str(e))
            self.jobs.append(rec)
            n = len(self.jobs)
            self.on_tool(f"▶ run {command} (백그라운드 {n}번" + (", 자동 허용" if auto else "") + ")", "")
            time.sleep(1.0)  # 바로 실패하는 명령(오타 등)을 잡는다
            return (f"백그라운드로 시작했습니다: 작업 {n}번. 출력은 job_output(job={n}), 멈추려면 job_stop(job={n}).\n"
                    + self._job_text(rec))
        self.on_status(f"명령 실행 중: {command[:60]}")
        try:
            rec = self.runner.start(str(self.workspace), command, timeout=t, purpose="Code 에이전트")
        except code_runner.RunnerError as e:
            raise ToolError(str(e))
        if self.on_run:
            self.on_run(rec.id)
        while not rec.ended:
            if self.cancelled():
                self.runner.stop(rec.id)
                self.runner.wait(rec.id, 15)
                break
            time.sleep(0.1)
        if self.on_run:
            self.on_run(None)
        self.commands.append({"command": command, "code": rec.code})
        out = rec.output_tail.strip()
        label = {"timeout": "시간 초과", "stopped": "멈춤"}.get(rec.status, f"종료 코드 {rec.code}")
        self.on_tool(f"▶ run {command} ({label}, {rec.seconds}초" + (", 자동 허용" if auto else "") + ")", _truncate(out, 4000))
        return f"{label}\n{_truncate(out, 6000) or '(출력 없음)'}"

    def _job(self, job):
        try:
            return self.jobs[int(job) - 1]
        except (TypeError, ValueError, IndexError):
            raise ToolError(f"백그라운드 작업 {job}번이 없습니다(1~{len(self.jobs)}).")

    @staticmethod
    def _job_text(rec):
        state = "실행 중" if not rec.ended else {"timeout": "시간 초과", "stopped": "멈춤"}.get(rec.status, f"끝남(종료 코드 {rec.code})")
        return f"상태: {state}\n최근 출력:\n{_truncate(rec.output_tail.strip()[-6000:], 6000) or '(아직 출력 없음)'}"

    def _tool_job_output(self, job, wait=0):
        rec = self._job(job)
        try:
            until = time.monotonic() + max(0, min(60, float(wait or 0)))
        except (TypeError, ValueError):
            until = time.monotonic()
        while not rec.ended and time.monotonic() < until and not self.cancelled():
            time.sleep(0.2)
        text = self._job_text(rec)
        self.on_tool(f"📟 job_output {job}번", _truncate(text, 3000))
        return text

    def _tool_job_stop(self, job):
        rec = self._job(job)
        if not rec.ended:
            self.runner.stop(rec.id)
            self.runner.wait(rec.id, 15)
        self.on_tool(f"⏹ job_stop {job}번", "")
        return "멈췄습니다.\n" + self._job_text(rec)


class CodeAgentApi:
    """main.Bridge가 상속한다(CodeApi와 함께). 화면은 web/code-agent.js의 '작업' 탭."""

    _ca_store = None
    _ca_running = None   # {"task_id", "cancel": Event, "run_id": code run id or None, "steer": [지시]}

    def _ca(self):
        if self._ca_store is None:
            self._ca_store = TaskStore()
        return self._ca_store

    def _ca_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except (TaskError, cw.WorkspaceError, code_runner.RunnerError, code_project.ProjectError) as e:
            return {"ok": False, "error": str(e)}
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": f"잘못된 요청입니다: {e}"}
        except OSError as e:
            return {"ok": False, "error": f"파일을 다루지 못했습니다: {e.strerror or e}"}

    def _ca_approval(self):
        mode = (self._config.get("code") or {}).get("agent_approval")
        return mode if mode in APPROVALS else "auto_edit"

    def _ca_push(self, kind, **data):
        self._push({"type": "code", "kind": kind, **data})

    @staticmethod
    def _ca_root(task):
        """에이전트가 일하는 폴더: 격리 작업이면 worktree, 아니면 작업 폴더."""
        return task.get("worktree") or task["workspace"]

    # ---- '다시 묻지 않기' 명령 규칙(작업 폴더별) ----

    def _ca_rules(self, ws):
        rules = ((self._config.get("code") or {}).get("allow_commands") or {}).get(os.path.normcase(str(ws))) or []
        return [r for r in rules if isinstance(r, str)][:code_project.MAX_RULES]

    def _ca_add_rule(self, ws, prefix):
        conf = self._code_conf()
        table = conf.setdefault("allow_commands", {})
        key = os.path.normcase(str(ws))
        rules = [r for r in table.get(key) or [] if r != prefix]
        table[key] = ([prefix] + rules)[:code_project.MAX_RULES]
        self._code_save_conf()

    def code_agent_rules(self):
        return self._ca_call(lambda: {"rules": self._ca_rules(self._code_ws())})

    def code_agent_rule_delete(self, prefix):
        def go():
            ws = self._code_ws()
            conf = self._code_conf()
            key = os.path.normcase(str(ws))
            conf.setdefault("allow_commands", {})[key] = [r for r in self._ca_rules(ws) if r != prefix]
            self._code_save_conf()
            return {"rules": self._ca_rules(ws)}
        return self._ca_call(go)

    # ---- 상태 ----

    def code_agent_state(self):
        def go():
            ws = self._workspace()
            running = self._ca_running
            info = {}
            if ws and not self._code_android():
                info = {"instructions": [n for n, _ in code_project.instructions(ws)],
                        "commands": code_project.detect_commands(ws), "git": code_project.git_summary(ws) is not None,
                        "rules": self._ca_rules(ws)}
            return {"tasks": self._ca().list(ws) if ws else [], "approval": self._ca_approval(),
                    "running": running["task_id"] if running else None, "workspace": ws,
                    "android": self._code_android(), "project": info, "slash": code_project.SLASH_HELP,
                    "modes": list(APPROVALS)}
        return self._ca_call(go)

    def code_agent_set_approval(self, mode):
        def go():
            if mode not in APPROVALS:
                raise TaskError("알 수 없는 승인 방식입니다.")
            self._code_conf()["agent_approval"] = mode
            self._code_save_conf()
            return {"approval": mode}
        return self._ca_call(go)

    def code_agent_task(self, task_id):
        return self._ca_call(lambda: {"task": self._ca().load(task_id)})

    def code_agent_delete(self, task_id):
        def go():
            if self._ca_running and self._ca_running["task_id"] == task_id:
                raise TaskError("실행 중인 작업은 지울 수 없습니다. 먼저 멈추세요.")
            task = self._ca().load(task_id)
            if task.get("worktree") and not task.get("worktree_removed"):
                code_project.worktree_remove(task["workspace"], task["worktree"], task.get("branch"))
            self._ca().delete(task_id)
            return {"deleted": task_id}
        return self._ca_call(go)

    # ---- 맡기기·이어서·작업 중 지시 ----

    def code_agent_start(self, text, task_id="", options=None):
        """작업을 맡긴다(task_id가 있으면 그 작업에 이어서 지시). 실제 일은 뒤 스레드에서 한다.
        options: {"mode": 이번 지시의 권한 모드, "isolate": 새 작업을 격리 작업 공간(git worktree)에서}. 글이 /로 시작하면 슬래시 명령."""
        options = options if isinstance(options, dict) else {}

        def go():
            if self._code_android():
                raise TaskError("안드로이드에서는 Code 에이전트를 쓸 수 없습니다(PC 앱에서 쓰세요).")
            ws = self._code_ws()
            msg = str(text or "").strip()
            if not msg:
                raise TaskError("맡길 작업을 입력하세요.")
            if self._ca_running:
                raise TaskError("다른 작업이 진행 중입니다. 끝나거나 멈춘 뒤 다시 하세요(진행 중인 작업에는 '추가 지시'를 보낼 수 있습니다).")
            if getattr(self, "_busy", False):
                raise TaskError("채팅 응답을 기다리는 중입니다. 끝난 뒤 다시 하세요.")
            api_key = self._api_key()
            if not api_key and self._api_needed(self._config, "auto"):  # 1.17: Local Only·로컬 모델이면 키 없이도 된다
                raise TaskError(self._missing_key_error())
            store = self._ca()
            task = None
            if task_id:
                task = store.load(task_id)
                if os.path.normcase(task["workspace"]) != os.path.normcase(ws):
                    raise TaskError("다른 작업 폴더의 작업입니다. 그 폴더를 고른 뒤 이어서 하세요.")
                if task.get("worktree_removed"):
                    raise TaskError("격리 작업 공간을 이미 적용·정리한 작업입니다. 새 작업을 시작하세요.")
            prompt, slash_mode = code_project.expand_slash(msg, self._ca_root(task) if task else ws)
            mode = slash_mode or (options.get("mode") if options.get("mode") in APPROVALS else self._ca_approval())
            if task is None:
                first = msg.splitlines()[0]
                if first.startswith("/"):  # 제목: '/plan 할 일' → '할 일', '/review' → '코드 리뷰'
                    cmd, _, rest = first.partition(" ")
                    label = {"/init": "AGENTS.md 만들기", "/review": "코드 리뷰", "/test": "테스트 실행·고치기"}.get(cmd.lower(), "")
                    first = (rest.strip() if cmd.lower() == "/plan" else (label + (f": {rest.strip()}" if rest.strip() else ""))) or first
                task = store.new(ws, first, mode)
                if options.get("isolate"):
                    path = tasks_dir().parent / "worktrees" / task["id"]
                    branch = f"poschat/{task['id']}"
                    try:
                        base = code_project.worktree_create(ws, path, branch)
                    except code_project.ProjectError:
                        store.delete(task["id"])
                        raise

                    def iso(t):
                        t.update(isolated=True, worktree=str(path), branch=branch, base=base)
                    task = store.update(task["id"], iso)
            history = [storage.make_message(t["role"], t["text"]) for t in task["turns"]]

            def add_turn(t):
                t["turn_no"] = int(t.get("turn_no") or 0) + 1
                t["turns"].append({"role": "user", "text": msg[:20000], "at": time.time(), "mode": mode, "turn": t["turn_no"]})
                t["status"] = "running"
                t["approval"] = mode
            task = store.update(task["id"], add_turn)
            self._ca_running = {"task_id": task["id"], "cancel": threading.Event(), "run_id": None, "steer": []}
            threading.Thread(target=self._ca_work, args=(task["id"], self._ca_root(task), history, prompt, api_key, mode),
                             daemon=True, name=f"code-agent-{task['id']}").start()
            self._ca_push("agent_task", task=task)
            return {"task": task}
        return self._ca_call(go)

    def code_agent_steer(self, text):
        """진행 중인 작업에 추가 지시(Claude Code처럼 일하는 중에 끼어들기). 다음 단계부터 반영한다."""
        def go():
            running = self._ca_running
            msg = str(text or "").strip()
            if not running:
                raise TaskError("진행 중인 작업이 없습니다.")
            if not msg:
                raise TaskError("보낼 지시를 쓰세요.")
            if msg.startswith("/"):
                raise TaskError("작업 중에는 슬래시 명령을 쓸 수 없습니다. 끝나거나 멈춘 뒤 쓰세요.")
            running["steer"].append(msg[:20000])

            def put(t):
                t["turns"].append({"role": "user", "text": msg[:20000], "at": time.time(), "steer": True})
            task = self._ca().update(running["task_id"], put)
            self._ca_push("agent_task", task=task)
            return {"queued": True}
        return self._ca_call(go)

    def code_agent_stop(self):
        running = self._ca_running
        if not running:
            return {"ok": True, "stopped": False}
        running["cancel"].set()
        if running.get("run_id"):
            try:
                self._code_runner().stop(running["run_id"])
            except code_runner.RunnerError:
                pass
        for entry in list(getattr(self, "_pending", {}).values()):  # 기다리는 승인은 거부로
            entry[1] = "deny"
            entry[0].set()
        return {"ok": True, "stopped": True}

    def _ca_step(self, task_id, summary, detail):
        step = {"at": time.time(), "kind": step_kind(summary), "title": str(summary)[:500],
                "detail": str(detail or "")[:MAX_DETAIL]}

        def add(t):
            step["n"] = len(t["steps"]) + 1
            t["steps"].append(step)
        self._ca().update(task_id, add)
        self._ca_push("agent_step", task_id=task_id, step=step)

    def _ca_review(self, task_id, mode, alive):
        """에이전트의 write/edit. '수정 자동'·'전체 자동'이면 원본을 백업하고 바로 적용, '매번 묻기'면 None(승인 창).
        지시(turn)마다 처음 고치기 전 상태도 남겨 '마지막 지시 되돌리기'(/undo)를 할 수 있게 한다."""
        store = self._ca()

        def review(rel, old_text, new_text, title, reason, encoding):
            if mode not in ("auto_edit", "full_auto") or not alive() or AUTO_RUN_FILES.search(str(rel).replace("\\", "/")):
                return None  # 승인 창(confirm "edit")으로 묻는다
            task = store.load(task_id)
            p = cw.resolve(self._ca_root(task), rel, allow_root=False)
            current = None
            if p.exists():
                current, _ = self._ca_read(p)
            if (old_text is None and p.exists()) or (old_text is not None and current != old_text):
                return {"status": "conflict", "message": "읽은 뒤 파일이 바뀌어 저장하지 않았습니다"}
            if current == new_text:
                return {"status": "unchanged"}
            import difflib

            diff = "\n".join(difflib.unified_diff((old_text or "").splitlines(), new_text.splitlines(), f"a/{rel}", f"b/{rel}",
                                                  lineterm=""))
            bdir = store.backup_dir(task_id)

            def keep_backup():
                name = f"{len(list(bdir.iterdir())) + 1}.bak"
                (bdir / name).write_bytes(p.read_bytes())
                return name
            change = task["changes"].get(rel)
            if change is None or change.get("reverted"):
                change = {"path": rel, "created": old_text is None, "backup": keep_backup() if old_text is not None else "",
                          "before_sha": _sha(old_text), "encoding": encoding, "first_at": time.time(), "turns": {}}
            turn = str(task.get("turn_no") or 0)
            turns = change.setdefault("turns", {})
            if turn not in turns:   # 이 지시에서 처음 고침: 지시 전 상태를 남긴다
                first = change.get("backup") if not turns else ""
                turns[turn] = {"created": old_text is None, "before_sha": _sha(old_text),
                               "backup": "" if old_text is None else (first or keep_backup())}
            p.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(p, new_text.encode(encoding or "utf-8"))
            change.update(after_sha=_sha(new_text), reverted=False, edits=change.get("edits", 0) + 1, last_at=time.time(),
                          reason=str(reason or "")[:300])

            def put(t):
                t["changes"][rel] = change
            store.update(task_id, put)
            self._ca_push("agent_change", task_id=task_id, path=rel, change=change)
            return {"status": "applied", "diff": diff}
        return review

    @staticmethod
    def _ca_read(p):
        raw = Path(p).read_bytes()
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                return raw.decode(enc), enc
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace"), "utf-8"

    def _ca_work(self, task_id, root, history, msg, api_key, mode):
        running = self._ca_running
        cancel = running["cancel"]
        store = self._ca()

        def alive():
            return not cancel.is_set()

        def on_status(text):
            self._ca_push("agent_status", task_id=task_id, text=text)

        def on_plan(steps, done):
            def put(t):
                t["plan"] = [{"text": s, "done": i in done} for i, s in enumerate(steps)]
            task = store.update(task_id, put)
            self._ca_push("agent_plan", task_id=task_id, plan=task["plan"])

        def on_run(rid):
            running["run_id"] = rid
            self._ca_push("agent_run", task_id=task_id, run_id=rid)

        ws = store.load(task_id)["workspace"]

        def confirm(kind, title, detail, remember=""):
            # 명령(run)과 그 밖의 승인은 채팅 설정의 자동 허용과 관계없이 묻는다. 파일 수정은 review가 정한다.
            # remember: '다시 묻지 않기'로 남길 명령 접두어(있을 때만 그 단추를 보인다)
            if not alive():
                return False
            cid = uuid.uuid4().hex
            entry = [threading.Event(), "deny"]
            self._pending[cid] = entry
            self._push({"type": "confirm", "id": cid, "thread_id": task_id, "kind": kind, "title": title,
                        "detail": detail, "allow_session": False, "source": "code_agent",
                        **({"remember": remember} if remember else {})})
            entry[0].wait()
            self._pending.pop(cid, None)
            if entry[1] == "remember" and remember and alive():
                self._ca_add_rule(ws, remember)
                self._ca_step(task_id, f"✅ 이 작업 폴더에서 '{remember}' 명령은 다시 묻지 않습니다", "")
                return True
            return entry[1] in ("allow", "always") and alive()

        def steer():
            out, running["steer"] = running["steer"], []
            return out

        agent = CodeAgent(
            api_key=api_key, workspace=root, agent_mode=True,
            max_steps=int((self._config.get("code") or {}).get("agent_max_steps") or 40),
            history_messages=20, on_status=on_status,
            on_tool=lambda s, d: self._ca_step(task_id, s, d) if alive() or s.startswith("▶") else None,
            confirm=confirm, cancelled=lambda: not alive(), thread_id=None, share_threads=False,
            mcp=None, api_settings=self._thread_api_settings({}), on_delta=None,
            policy=None, browser=None, paper=None, review=self._ca_review(task_id, mode, alive),
            runner=self._code_runner(), on_plan=on_plan, on_run=on_run,
            # 1.17: 자동 선택을 켰으면 엔진을 거친다. 코드 수정 단계는 '중요·위험'이라 Cloud 먼저, Local Only면 로컬 모델로
            engine=self._make_engine({"model": "auto"}, api_key, lambda: not alive(), area="code_agent"),
            prompt_cache=adaptive_engine.settings(self._config)["prompt_cache"],
            mode=mode, allowed=lambda command: code_project.rule_allows(self._ca_rules(ws), command), steer=steer,
            project_note=("격리 작업 공간(git worktree)에서 일합니다. 원래 작업 폴더는 사용자가 '적용'할 때 바뀝니다. "
                          "설치하지 않은 의존성(node_modules·가상환경)은 없을 수 있습니다." if os.path.normcase(str(root)) != os.path.normcase(str(ws)) else ""))
        status, answer = "done", ""
        try:
            answer = agent.run(history, msg)
            if not alive():
                status, answer = "stopped", answer or "(작업을 멈췄습니다.)"
        except Exception as e:  # API 오류 등
            status, answer = "error", f"오류: {type(e).__name__}: {e}"
        finally:
            def finish(t):
                t["status"] = status
                t["turns"].append({"role": "assistant", "text": str(answer)[:40000], "at": time.time(), "status": status,
                                   "steps": agent.steps, "mode": mode, "plan_proposal": mode == "plan" and status == "done"})
            try:
                task = store.update(task_id, finish)
            except Exception:
                task = None
            self._ca_running = None
            self._ca_push("agent_done", task_id=task_id, task=task, status=status)

    # ---- 되돌리기 ----

    def code_agent_revert(self, task_id, path=""):
        """작업이 바꾼 파일을 처음 상태로. 에이전트가 쓴 뒤 다른 변경이 있으면 건너뛴다(덮어쓰지 않는다)."""
        def go():
            if self._ca_running and self._ca_running["task_id"] == task_id:
                raise TaskError("진행 중인 작업은 되돌릴 수 없습니다. 먼저 멈추세요.")
            store = self._ca()
            task = store.load(task_id)
            targets = [path] if path else list(task["changes"])
            done, skipped = [], []
            for rel in targets:
                ch = task["changes"].get(rel)
                if not ch or ch.get("reverted"):
                    continue
                p = cw.resolve(self._ca_root(task), rel, allow_root=False)
                current = self._ca_read(p)[0] if p.exists() else None
                if _sha(current) != ch.get("after_sha"):
                    skipped.append({"path": rel, "reason": "에이전트가 쓴 뒤 파일이 바뀌었습니다"})
                    continue
                if ch.get("created"):
                    p.unlink()
                else:
                    data = (store.backup_dir(task_id) / ch["backup"]).read_bytes()
                    atomic_write(p, data)
                ch["reverted"] = True
                ch["reverted_at"] = time.time()
                ch["turns"] = {}
                done.append(rel)

            def put(t):
                for rel in done:
                    t["changes"][rel] = task["changes"][rel]
                t["steps"].append({"n": len(t["steps"]) + 1, "at": time.time(), "kind": "revert",
                                   "title": f"↩ 되돌림 {len(done)}개" + (f", 건너뜀 {len(skipped)}개" if skipped else ""),
                                   "detail": "\n".join(done + [f"{s['path']}: {s['reason']}" for s in skipped])})
            task = store.update(task_id, put)
            return {"task": task, "reverted": done, "skipped": skipped}
        return self._ca_call(go)

    def code_agent_undo(self, task_id):
        """마지막 지시(turn)로 바뀐 파일만 그 지시 전으로(Claude Code의 되감기처럼). 그 뒤 바뀐 파일은 건너뛴다."""
        def go():
            if self._ca_running and self._ca_running["task_id"] == task_id:
                raise TaskError("진행 중인 작업은 되돌릴 수 없습니다. 먼저 멈추세요.")
            store = self._ca()
            task = store.load(task_id)
            turns = sorted({int(k) for ch in task["changes"].values() if not ch.get("reverted") for k in (ch.get("turns") or {})})
            if not turns:
                raise TaskError("되돌릴 지시가 없습니다(이 작업이 바꾼 파일이 없음).")
            last = str(turns[-1])
            done, skipped = [], []
            for rel, ch in task["changes"].items():
                entry = (ch.get("turns") or {}).get(last)
                if ch.get("reverted") or not entry:
                    continue
                p = cw.resolve(self._ca_root(task), rel, allow_root=False)
                current = self._ca_read(p)[0] if p.exists() else None
                if _sha(current) != ch.get("after_sha"):
                    skipped.append({"path": rel, "reason": "에이전트가 쓴 뒤 파일이 바뀌었습니다"})
                    continue
                if entry.get("created"):
                    p.unlink(missing_ok=True)
                else:
                    atomic_write(p, (store.backup_dir(task_id) / entry["backup"]).read_bytes())
                del ch["turns"][last]
                ch["after_sha"] = entry.get("before_sha", "")
                if not ch["turns"]:
                    ch["reverted"], ch["reverted_at"] = True, time.time()
                done.append(rel)

            def put(t):
                for rel in done:
                    t["changes"][rel] = task["changes"][rel]
                t["steps"].append({"n": len(t["steps"]) + 1, "at": time.time(), "kind": "revert",
                                   "title": f"↩ {last}번째 지시를 되돌림: {len(done)}개" + (f", 건너뜀 {len(skipped)}개" if skipped else ""),
                                   "detail": "\n".join(done + [f"{s['path']}: {s['reason']}" for s in skipped])})
            task = store.update(task_id, put)
            return {"task": task, "reverted": done, "skipped": skipped, "turn": int(last)}
        return self._ca_call(go)

    def code_agent_diff(self, task_id, path):
        """작업이 바꾼 파일의 차이(작업 전 → 지금)."""
        def go():
            import difflib

            task = self._ca().load(task_id)
            ch = task["changes"].get(path)
            if not ch:
                raise TaskError("이 작업이 바꾼 파일이 아닙니다.")
            p = cw.resolve(self._ca_root(task), path, allow_root=False)
            before = ""
            if not ch.get("created") and ch.get("backup"):
                raw = (self._ca().backup_dir(task_id) / ch["backup"]).read_bytes()
                before = raw.decode(ch.get("encoding") or "utf-8", errors="replace")
            now = self._ca_read(p)[0] if p.exists() else ""
            diff = "\n".join(difflib.unified_diff(before.splitlines(), now.splitlines(), f"a/{path}", f"b/{path}", lineterm=""))
            return {"path": path, "diff": diff[:400000], "changed_after": _sha(now if p.exists() else None) != ch.get("after_sha")}
        return self._ca_call(go)

    # ---- 대화 줄이기(/compact) ----

    def code_agent_compact(self, task_id):
        """지난 지시·답을 요약 하나로 줄인다(긴 작업에서 다음 지시의 맥락을 가볍게). 바뀐 파일·되돌리기 기록은 그대로."""
        def go():
            if self._ca_running:
                raise TaskError("작업이 진행 중입니다. 끝난 뒤 하세요.")
            store = self._ca()
            task = store.load(task_id)
            turns = [t for t in task["turns"] if not t.get("compacted")]
            if len(turns) < 2:
                raise TaskError("줄일 대화가 없습니다.")
            api_key = self._api_key()
            convo = "\n\n".join(f"{'사용자' if t['role'] == 'user' else '에이전트'}: {t['text'][:6000]}" for t in turns)
            files = ", ".join(sorted(k for k, v in task["changes"].items() if not v.get("reverted"))) or "(없음)"
            prompt = ("다음은 코딩 에이전트 작업의 지난 대화입니다. 다음 지시를 이어 갈 수 있게 요약하세요: 사용자의 목표와 요구, "
                      "한 일과 결정, 바꾼 파일, 확인한 결과(테스트), 남은 일·열린 질문. 한국어, 글머리표, 1,500자 안.\n\n"
                      f"[바뀐 파일]\n{files}\n\n[대화]\n{convo[-60000:]}")
            ask, _ = self._routed_ask("auto", api_key, "thread_summary", area="code_agent")
            if ask is None:
                import agent as agent_module

                if not api_key:
                    raise TaskError(self._missing_key_error())
                summary = agent_module.ask(api_key, prompt, settings=self._thread_api_settings({}))
            else:
                summary = ask(prompt)

            def put(t):
                kept = [x for x in t["turns"] if x.get("compacted")]
                t["turns"] = kept + [
                    {"role": "user", "text": "(이전 지시들 — /compact로 요약함)", "at": time.time(), "compacted": True},
                    {"role": "assistant", "text": "[지난 작업 요약]\n" + str(summary)[:8000], "at": time.time(), "compacted": True,
                     "status": "done"}]
                t["compacted_turns"] = int(t.get("compacted_turns") or 0) + len(turns)
            task = store.update(task_id, put)
            return {"task": task, "summarized": len(turns)}
        return self._ca_call(go)

    # ---- 격리 작업 공간(git worktree) ----

    def code_agent_apply(self, task_id, discard_after=True):
        """격리 작업의 변경을 원래 작업 폴더에 적용한다(먼저 검사, 겹치면 3-way). 적용 뒤 격리 공간을 정리한다."""
        def go():
            if self._ca_running and self._ca_running["task_id"] == task_id:
                raise TaskError("진행 중인 작업입니다. 끝난 뒤 적용하세요.")
            store = self._ca()
            task = store.load(task_id)
            if not task.get("worktree") or task.get("worktree_removed"):
                raise TaskError("격리 작업 공간이 없는 작업입니다.")
            patch = code_project.worktree_patch(task["worktree"], task["base"])
            result = code_project.worktree_apply(task["workspace"], patch)
            if discard_after and result.get("applied"):
                code_project.worktree_remove(task["workspace"], task["worktree"], task.get("branch"))

            def put(t):
                t["applied_at"] = time.time() if result.get("applied") else t.get("applied_at")
                if discard_after and result.get("applied"):
                    t["worktree_removed"] = True
                t["steps"].append({"n": len(t["steps"]) + 1, "at": time.time(), "kind": "info",
                                   "title": (f"📥 원래 작업 폴더에 적용: 파일 {len(result.get('files') or [])}개"
                                             + (" (3-way)" if result.get("three_way") else "")) if result.get("applied")
                                   else "📥 적용할 변경이 없습니다", "detail": "\n".join(result.get("files") or [])})
            task = store.update(task_id, put)
            return {"task": task, **result}
        return self._ca_call(go)

    def code_agent_keep_branch(self, task_id):
        """격리 작업의 변경을 그 브랜치(poschat/<작업>)에 커밋해 남기고 worktree만 정리한다(Codex처럼). 원래 폴더는 그대로이고,
        사용자가 Git으로 합친다(git merge poschat/<작업>). 커밋 훅은 돌리지 않는다(--no-verify: 승인 없이 명령이 돌지 않게)."""
        def go():
            if self._ca_running and self._ca_running["task_id"] == task_id:
                raise TaskError("진행 중인 작업입니다. 끝난 뒤 하세요.")
            store = self._ca()
            task = store.load(task_id)
            if not task.get("worktree") or task.get("worktree_removed"):
                raise TaskError("격리 작업 공간이 없는 작업입니다.")
            committed = code_project.worktree_commit(task["worktree"], f"POSCHAT Code 에이전트: {task['title']}"[:200])
            code_project.worktree_remove(task["workspace"], task["worktree"], "")   # 브랜치는 남긴다

            def put(t):
                t["worktree_removed"] = True
                t["kept_branch"] = t.get("branch")
                t["steps"].append({"n": len(t["steps"]) + 1, "at": time.time(), "kind": "apply",
                                   "title": f"📥 브랜치 {t.get('branch')}에 " + ("커밋해 남겼습니다" if committed else "남겼습니다(바뀐 것 없음)"),
                                   "detail": f"합치기: git merge {t.get('branch')}"})
            return {"task": store.update(task_id, put), "branch": task.get("branch"), "committed": committed}
        return self._ca_call(go)

    def code_agent_discard(self, task_id):
        """격리 작업 공간과 브랜치를 버린다(원래 작업 폴더는 그대로)."""
        def go():
            if self._ca_running and self._ca_running["task_id"] == task_id:
                raise TaskError("진행 중인 작업입니다. 먼저 멈추세요.")
            store = self._ca()
            task = store.load(task_id)
            if not task.get("worktree") or task.get("worktree_removed"):
                raise TaskError("격리 작업 공간이 없는 작업입니다.")
            code_project.worktree_remove(task["workspace"], task["worktree"], task.get("branch"))

            def put(t):
                t["worktree_removed"] = True
                t["steps"].append({"n": len(t["steps"]) + 1, "at": time.time(), "kind": "revert",
                                   "title": "🗑 격리 작업 공간을 버렸습니다(원래 작업 폴더는 그대로)", "detail": ""})
            return {"task": store.update(task_id, put)}
        return self._ca_call(go)

    def code_agent_worktree_diff(self, task_id):
        """격리 작업의 전체 차이(기준 커밋 → 지금, 새 파일 포함)."""
        def go():
            task = self._ca().load(task_id)
            if not task.get("worktree") or task.get("worktree_removed"):
                raise TaskError("격리 작업 공간이 없는 작업입니다.")
            patch = code_project.worktree_patch(task["worktree"], task["base"])
            return {"diff": patch[:400000], "files": len(re.findall(r"(?m)^diff --git ", patch))}
        return self._ca_call(go)

    def _ca_shutdown(self):
        if self._ca_running:
            self.code_agent_stop()
