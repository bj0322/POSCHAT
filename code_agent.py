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
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import code_runner
import code_workspace as cw
import storage
from agent import ACTION_DOCS, Agent, ToolError, _truncate
from code_workspace import atomic_write

MAX_TASKS = 100
MAX_STEPS_KEPT = 400
MAX_DETAIL = 12000
APPROVALS = ("auto_edit", "ask")
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
                         ("🔍", "search"), ("🧩", "skill"), ("🔎", "recall"), ("🌐", "browser"), ("📋", "plan")):
        if s.startswith(prefix):
            return kind
    return "info"


class CodeAgent(Agent):
    """agent.Agent + plan 단계 + 스트리밍 명령 실행(RunManager). 파일 수정 정책은 review 콜백(CodeAgentApi)이 정한다."""

    step_purpose = "code_agent_step"  # 1.17 라우팅: 코드 수정·명령으로 이어지는 단계(중요·위험)

    def __init__(self, *args, runner=None, on_plan=None, on_run=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.runner = runner      # code_runner.RunManager
        self.on_plan = on_plan    # (steps, done) -> None
        self.on_run = on_run      # (code_run_id) -> None: 지금 도는 명령(멈춤·출력 표시용)
        self.plan = []

    def _static_prompt(self, history, task, forced_skill):
        text = super()._static_prompt(history, task, forced_skill)
        head, sep, tail = text.partition("[규칙]\n")
        text = head.replace(ACTION_DOCS, ACTION_DOCS + "\n" + PLAN_DOC, 1) + sep + tail
        return text.replace("[작업 폴더]\n", CODE_RULES + "\n\n[작업 폴더]\n", 1)

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

    def _tool_run(self, command):
        if self.runner is None:
            return super()._tool_run(command)
        command = str(command).strip()
        if not command:
            raise ToolError("command가 비었습니다.")
        info = code_runner.analyze(command)
        detail = f"{self.workspace}>\n{command}"
        if info.get("dangers"):
            detail += "\n\n위험할 수 있는 동작: " + ", ".join(info["dangers"])
        if info.get("network"):
            detail += "\n이 명령은 인터넷(네트워크)을 쓸 수 있습니다."
        if not self.confirm("run", "명령 실행", detail):
            self.denied.append(f"명령 실행: {command[:200]}")
            self.on_tool(f"⛔ run 거부됨: {command}", "")
            return "사용자가 명령 실행을 거부했습니다."
        if self.cancelled():
            return "(작업을 중지했습니다.)"
        self.on_status(f"명령 실행 중: {command[:60]}")
        self._did_work = True
        self.tools_run.append(f"run: {command[:200]}")
        try:
            rec = self.runner.start(str(self.workspace), command, timeout=600, purpose="Code 에이전트")
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
        self.on_tool(f"▶ run {command} ({label}, {rec.seconds}초)", _truncate(out, 4000))
        return f"{label}\n{_truncate(out, 6000) or '(출력 없음)'}"


class CodeAgentApi:
    """main.Bridge가 상속한다(CodeApi와 함께). 화면은 web/code.js의 '작업' 탭."""

    _ca_store = None
    _ca_running = None   # {"task_id", "cancel": Event, "run_id": code run id or None}

    def _ca(self):
        if self._ca_store is None:
            self._ca_store = TaskStore()
        return self._ca_store

    def _ca_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except (TaskError, cw.WorkspaceError, code_runner.RunnerError) as e:
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

    def code_agent_state(self):
        def go():
            ws = self._workspace()
            running = self._ca_running
            return {"tasks": self._ca().list(ws) if ws else [], "approval": self._ca_approval(),
                    "running": running["task_id"] if running else None, "workspace": ws,
                    "android": self._code_android()}
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
            self._ca().delete(task_id)
            return {"deleted": task_id}
        return self._ca_call(go)

    def code_agent_start(self, text, task_id=""):
        """작업을 맡긴다(task_id가 있으면 그 작업에 이어서 지시). 실제 일은 뒤 스레드에서 한다."""
        def go():
            if self._code_android():
                raise TaskError("안드로이드에서는 Code 에이전트를 쓸 수 없습니다(PC 앱에서 쓰세요).")
            ws = self._code_ws()
            msg = str(text or "").strip()
            if not msg:
                raise TaskError("맡길 작업을 입력하세요.")
            if self._ca_running:
                raise TaskError("다른 작업이 진행 중입니다. 끝나거나 멈춘 뒤 다시 하세요.")
            if getattr(self, "_busy", False):
                raise TaskError("채팅 응답을 기다리는 중입니다. 끝난 뒤 다시 하세요.")
            api_key = self._api_key()
            if not api_key and self._api_needed(self._config, "auto"):  # 1.17: Local Only·로컬 모델이면 키 없이도 된다
                raise TaskError(self._missing_key_error())
            store = self._ca()
            if task_id:
                task = store.load(task_id)
                if os.path.normcase(task["workspace"]) != os.path.normcase(ws):
                    raise TaskError("다른 작업 폴더의 작업입니다. 그 폴더를 고른 뒤 이어서 하세요.")
            else:
                task = store.new(ws, msg.splitlines()[0], self._ca_approval())
            history = [storage.make_message(t["role"], t["text"]) for t in task["turns"]]

            def add_turn(t):
                t["turns"].append({"role": "user", "text": msg[:20000], "at": time.time()})
                t["status"] = "running"
                t["approval"] = self._ca_approval()
            task = store.update(task["id"], add_turn)
            self._ca_running = {"task_id": task["id"], "cancel": threading.Event(), "run_id": None}
            threading.Thread(target=self._ca_work, args=(task["id"], ws, history, msg, api_key), daemon=True,
                             name=f"code-agent-{task['id']}").start()
            self._ca_push("agent_task", task=task)
            return {"task": task}
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

    def _ca_review(self, task_id, approval, alive):
        """에이전트의 write/edit. '수정 자동'이면 원본을 백업하고 바로 적용, '매번 묻기'면 None(승인 창)."""
        store = self._ca()

        def review(rel, old_text, new_text, title, reason, encoding):
            if approval != "auto_edit" or not alive() or AUTO_RUN_FILES.search(str(rel).replace("\\", "/")):
                return None  # 승인 창(confirm "edit")으로 묻는다
            task = store.load(task_id)
            p = cw.resolve(task["workspace"], rel, allow_root=False)
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
            change = task["changes"].get(rel)
            if change is None or change.get("reverted"):
                backup = ""
                if old_text is not None:
                    bdir = store.backup_dir(task_id)
                    backup = f"{len(list(bdir.iterdir())) + 1}.bak"
                    (bdir / backup).write_bytes(p.read_bytes())
                change = {"path": rel, "created": old_text is None, "backup": backup, "before_sha": _sha(old_text),
                          "encoding": encoding, "first_at": time.time()}
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

    def _ca_work(self, task_id, ws, history, msg, api_key):
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

        def confirm(kind, title, detail):
            # 명령(run)과 그 밖의 승인은 채팅 설정의 자동 허용과 관계없이 매번 묻는다. 파일 수정은 review가 정한다.
            if not alive():
                return False
            cid = uuid.uuid4().hex
            entry = [threading.Event(), "deny"]
            self._pending[cid] = entry
            self._push({"type": "confirm", "id": cid, "thread_id": task_id, "kind": kind, "title": title,
                        "detail": detail, "allow_session": False, "source": "code_agent"})
            entry[0].wait()
            self._pending.pop(cid, None)
            return entry[1] in ("allow", "always") and alive()

        approval = self._ca_approval()
        agent = CodeAgent(
            api_key=api_key, workspace=ws, agent_mode=True,
            max_steps=int((self._config.get("code") or {}).get("agent_max_steps") or 40),
            history_messages=20, on_status=on_status,
            on_tool=lambda s, d: self._ca_step(task_id, s, d) if alive() or s.startswith("▶") else None,
            confirm=confirm, cancelled=lambda: not alive(), thread_id=None, share_threads=False,
            mcp=None, api_settings=self._thread_api_settings({}), on_delta=None,
            policy=None, browser=None, paper=None, review=self._ca_review(task_id, approval, alive),
            runner=self._code_runner(), on_plan=on_plan, on_run=on_run,
            # 1.17: 자동 선택을 켰으면 엔진을 거친다. 코드 수정 단계는 '중요·위험'이라 Cloud 먼저, Local Only면 로컬 모델로
            engine=self._make_engine({"model": "auto"}, api_key, lambda: not alive(), area="code_agent"))
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
                                   "steps": agent.steps})
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
                p = cw.resolve(task["workspace"], rel, allow_root=False)
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

    def code_agent_diff(self, task_id, path):
        """작업이 바꾼 파일의 차이(작업 전 → 지금)."""
        def go():
            import difflib

            task = self._ca().load(task_id)
            ch = task["changes"].get(path)
            if not ch:
                raise TaskError("이 작업이 바꾼 파일이 아닙니다.")
            p = cw.resolve(task["workspace"], path, allow_root=False)
            before = ""
            if not ch.get("created") and ch.get("backup"):
                raw = (self._ca().backup_dir(task_id) / ch["backup"]).read_bytes()
                before = raw.decode(ch.get("encoding") or "utf-8", errors="replace")
            now = self._ca_read(p)[0] if p.exists() else ""
            diff = "\n".join(difflib.unified_diff(before.splitlines(), now.splitlines(), f"a/{path}", f"b/{path}", lineterm=""))
            return {"path": path, "diff": diff[:400000], "changed_after": _sha(now if p.exists() else None) != ch.get("after_sha")}
        return self._ca_call(go)

    def _ca_shutdown(self):
        if self._ca_running:
            self.code_agent_stop()
