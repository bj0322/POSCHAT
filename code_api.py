# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15) 화면 API: main.Bridge가 상속한다. 화면은 web/code.js.

나눈 일
- 파일 찾기·읽기·저장: code_workspace (작업 폴더 밖 차단, 안전한 저장, 외부 변경 감지)
- AI 변경 제안·덩어리 검토·적용: code_diff (에이전트 edit/write → 제안 → 사용자가 고른 것만 적용)
- Git: code_git (상태·차이·스테이지·커밋, 푸시 없음)
- 명령 실행: code_runner (사용자 승인 뒤 실행, 출력 스트리밍) — 1.18부터 코드 화면에는 쓰지 않고 Lab·에이전트가 쓴다
- 터미널(1.18): terminal (아래 패널의 대화형 셸, Windows ConPTY·macOS/Linux pty). 사용자가 직접 치는 터미널이라 승인 창이 없다
- 원격(SSH) 작업 폴더(1.18): ssh_api가 연결을 맡고, 작업 폴더가 'ssh://…'이면 위 모듈들이 서버의 원격 도우미에서 같은 일을 한다(remote_fs)

모든 API는 앱 화면(js_api)에서만 부를 수 있다. 웹페이지 뷰·PDF 화면에는 js_api가 없다(browser.py·paper.js).
입력은 여기서 모두 검사한다(경로는 code_workspace.clean_rel, 길이·형식).

에이전트 수정 승인 정책(설정 → 권한과 Code의 '변경 검토'):
- 승인이 필요한지는 지금처럼 권한 설정이 정한다(묻기 · 파일 수정 자동 허용 · 모두 자동 허용 · 이번 실행 동안 허용).
- 어디서 승인하는지는 Code 설정이 정한다. 'Code 화면에서 검토'(기본)이고 Code 화면이 열려 있으면 승인 창 대신
  Code 화면에 변경 제안이 뜨고 덩어리마다 받아들이거나 거부한다. 자동 허용이면 바로 적용하고 '자동 적용' 기록만 남긴다.
- Code 화면이 닫혀 있거나(닫는 순간 대기 중인 제안 포함) 안드로이드면 예전 승인 창(전체 받아들이기·거부)을 쓴다.
- 명령 실행 승인(에이전트 run, 실행 패널)은 파일 수정 승인과 따로다.
"""
import base64
import hashlib
import os
import re
import secrets
import sys
import threading
import time
import uuid

import attachments
import code_diff
import code_git
import code_runner
import code_workspace as cw
import connectors
import remote_fs
import storage
import terminal

MAX_RECENT = 15
MAX_HISTORY = 30
TOKEN_SECONDS = 300
ASK_PRESETS = {
    "explain": "선택한 코드가 무엇을 하는지 쉽게 설명해 줘. 입력·출력과 핵심 흐름을 짚어 줘.",
    "bug": "이 코드에서 오류가 날 수 있는 곳을 찾아 줘. 원인과 고치는 방법을 줄 번호와 함께 알려 줘.",
    "perf": "이 코드의 성능을 개선할 방법을 알려 줘. 병목과 바꾼 코드, 예상 효과를 함께 써 줘.",
    "refactor": "이 코드를 읽기 쉽고 유지보수하기 좋게 리팩터링하는 방법을 제안해 줘. 동작은 바꾸지 마.",
    "comment": "이 코드에 알맞은 주석과 문서 문자열(docstring)을 달아 줘. 고친 코드 전체를 보여 줘.",
    "test": "이 코드를 검증할 테스트 코드를 제안해 줘. 경계값과 실패 경우도 넣어 줘.",
    "rtl": ("이 RTL(Verilog/SystemVerilog) 로직을 검토해 줘. 래치 추론, 블로킹/논블로킹 할당, 리셋, 클록 도메인, "
            "비트 폭 불일치, 합성 가능성, 조합 루프를 줄 번호와 함께 짚어 줘."),
}
GIT_ASKS = {
    "explain": "첨부한 변경(git diff)이 무엇을 바꾸는지 파일별로 쉽게 설명해 줘.",
    "review": ("첨부한 변경(git diff)을 코드 리뷰해 줘. 버그 가능성, 빠진 테스트, 보안 문제, 읽기 어려운 곳을 "
               "파일:줄과 함께 중요한 것부터 알려 줘."),
    "commit": ("첨부한 스테이지 변경(git diff --cached)에 맞는 커밋 메시지를 Conventional Commits 형식으로 제안해 줘. "
               "첫 줄은 72자 이내 영어(예: fix: correct ADC quantization handling), 빈 줄 뒤 본문에 무엇을 왜 바꿨는지 짧게."),
}


class CodeApi:
    _code_store_obj = None
    _code_runner_obj = None
    _code_active = False
    _code_waiters = None
    _code_tokens = None
    _code_terms_obj = None

    # ---- 도우미 ----

    def _code_store(self):
        if self._code_store_obj is None:
            self._code_store_obj = code_diff.ProposalStore()
            self._code_waiters = {}
        return self._code_store_obj

    def _code_runner(self):
        if self._code_runner_obj is None:
            self._code_runner_obj = code_runner.RunManager(
                on_event=self._push, log_path=str(storage.APP_DIR / "code" / "runs.jsonl"), secrets=self._code_secrets)
        return self._code_runner_obj

    def _code_secrets(self):
        """출력에서 가릴 비밀 값: 설정에 저장한 키·토큰과 비밀 이름의 환경 변수 값."""
        values = []
        for key, value in (self._config or {}).items():
            if isinstance(value, str) and code_runner.SECRET_ENV.search(key):
                values.append(value)
        for key, value in os.environ.items():
            if code_runner.SECRET_ENV.search(key):
                values.append(value)
        for cid, c in connectors.CONNECTORS.items():  # 커넥터 토큰(OS 보안 저장소)
            for field in getattr(c, "secrets", None) or []:
                try:
                    v = connectors.secret(cid, field.name)
                except Exception:
                    v = None
                if v:
                    values.append(v)
        return [v for v in values if isinstance(v, str) and len(v) >= 8]

    @staticmethod
    def _code_android():
        import browser_api

        return browser_api.android_factory is not None

    def _code_settings(self):
        cfg = self._config.get("code") or {}
        excludes = cfg.get("exclude")
        return {
            "show_hidden": bool(cfg.get("show_hidden", False)),
            "exclude": [str(x) for x in excludes][:100] if isinstance(excludes, list) else list(cw.DEFAULT_EXCLUDES),
            "review": cfg.get("review") if cfg.get("review") in ("auto", "off") else "auto",
            "wrap": bool(cfg.get("wrap", False)),
            "timeout": int(cfg.get("timeout") or code_runner.DEFAULT_TIMEOUT),
        }

    def _code_ws(self):
        ws = self._code_ws_opt()   # 1.18: 원격(SSH) 작업 폴더면 'ssh://…'(ssh_api)
        if not ws:
            raise cw.WorkspaceError("작업 폴더가 지정되지 않았습니다. 사이드바 아래의 '작업 폴더'에서 폴더를 고르세요.")
        return ws

    def _code_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except cw.ConflictError as e:
            return {"ok": False, "conflict": True, "current_hash": e.current_hash, "error": str(e)}
        except (cw.WorkspaceError, code_diff.ProposalError, code_git.GitError, code_runner.RunnerError,
                attachments.AttachmentError) as e:
            return {"ok": False, "error": str(e)}
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": f"잘못된 요청입니다: {e}"}
        except OSError as e:
            return {"ok": False, "error": f"파일을 다루지 못했습니다: {e.strerror or e}"}

    def _code_conf(self):
        with self._lock:
            return self._config.setdefault("code", {})

    def _code_save_conf(self):
        with self._lock:
            storage.save_config(self._config)

    def _code_attach(self, name, text):
        attach_id = uuid.uuid4().hex
        return attachments.upload_chunk(attach_id, name, 0, base64.b64encode(text.encode("utf-8")).decode("ascii"), True)

    # ---- 화면 상태·설정 ----

    def code_state(self):
        ws = self._code_ws_opt()
        android = self._code_android()
        conf = self._config.get("code") or {}
        store = self._code_store()
        remote = self._ssh_info()
        git = (remote.get("server") or {}).get("git", True) if remote else code_git.available()
        return {
            "ok": True,
            "workspace": {"path": ws, "name": os.path.basename(ws.rstrip("\\/")) if ws else "", "remote": bool(remote)},
            "remote": remote,
            "platform": "android" if android else {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux"),
            "features": {"run": not android, "git": not android and git, "review": not android,
                         "edit": True, "search": True, "ask": True, "terminal": not android and terminal.SUPPORTED,
                         "ssh": self._ssh_supported()},
            "settings": self._code_settings(),
            "recent": (conf.get("recent") or {}).get(ws, []) if ws else [],
            "history": conf.get("history") or [],
            "proposals": [p.to_dict(full=False) for p in store.all()],
            "runs": [r.to_dict(tail=False) for r in self._code_runner().records()] if not android else [],
            "shell": code_runner.shell_name(),
            "permission": self._config.get("permission", "ask"),
            "limits": {"edit_bytes": cw.MAX_EDIT_BYTES, "open_bytes": cw.MAX_OPEN_BYTES},
        }

    def code_save_settings(self, settings):
        def go():
            s = settings if isinstance(settings, dict) else {}
            conf = self._code_conf()
            if "show_hidden" in s:
                conf["show_hidden"] = bool(s["show_hidden"])
            if "wrap" in s:
                conf["wrap"] = bool(s["wrap"])
            if s.get("review") in ("auto", "off"):
                conf["review"] = s["review"]
            if "exclude" in s:
                items = s["exclude"] if isinstance(s["exclude"], list) else str(s["exclude"]).split(",")
                conf["exclude"] = [x.strip() for x in items if isinstance(x, str) and x.strip() and "/" not in x][:100]
            if "timeout" in s:
                conf["timeout"] = max(10, min(code_runner.MAX_TIMEOUT, int(s["timeout"])))
            self._code_save_conf()
            return {"settings": self._code_settings()}
        return self._code_call(go)

    def code_set_active(self, active):
        """화면이 Code 창을 열고 닫을 때 알린다. 닫으면 대기 중인 에이전트 제안은 예전 승인 창으로 넘긴다."""
        self._code_active = bool(active)
        moved = 0
        if not self._code_active:
            for p in self._code_store().pending():
                if self._code_waiters.get(p.proposal_id) and \
                        self._code_finish(p, "cancelled", "Code 화면을 닫아 승인 창으로 넘김"):
                    self._code_resolve(p.proposal_id, "fallback")
                    moved += 1
        return {"ok": True, "active": self._code_active, "moved": moved}

    # ---- 파일 ----

    def code_list(self, path="", show_hidden=None):
        def go():
            s = self._code_settings()
            hidden = s["show_hidden"] if show_hidden is None else bool(show_hidden)
            return cw.list_dir(self._code_ws(), str(path or ""), hidden, s["exclude"])
        return self._code_call(go)

    def code_open(self, path):
        def go():
            ws = self._code_ws()
            info = cw.read_file(ws, str(path))
            conf = self._code_conf()
            recent = conf.setdefault("recent", {})
            items = [p for p in recent.get(ws, []) if p != info["path"]]
            recent[ws] = [info["path"]] + items[:MAX_RECENT - 1]
            for key in list(recent)[:-20]:  # 작업 폴더 20개까지만 기억
                recent.pop(key, None)
            self._code_save_conf()
            return {"file": info}
        return self._code_call(go)

    def code_save(self, path, text, base_hash, encoding="utf-8", newline="\n", force=False):
        def go():
            if not isinstance(text, str):
                raise TypeError("내용이 글이 아닙니다.")
            if len(text) > cw.MAX_OPEN_BYTES:
                raise cw.WorkspaceError("내용이 너무 큽니다.")
            if newline not in ("\n", "\r\n", "\r"):
                raise ValueError("줄 끝 형식")
            enc = str(encoding or "utf-8")
            if enc not in ("utf-8", "utf-8-sig", "utf-16", "cp949"):
                raise ValueError("인코딩")
            saved = cw.write_file(self._code_ws(), str(path), text, str(base_hash or ""), enc, newline, bool(force))
            self._push({"type": "code", "kind": "file_changed", "path": saved["path"], "hash": saved["hash"], "by": "editor"})
            return {"file": saved}
        return self._code_call(go)

    def code_create(self, path, kind="file"):
        return self._code_call(lambda: {"created": cw.create(self._code_ws(), str(path), "dir" if kind == "dir" else "file")})

    def code_rename(self, src, dst):
        return self._code_call(lambda: {"renamed": cw.rename(self._code_ws(), str(src), str(dst))})

    def code_delete(self, path):
        """화면에서 사용자가 확인한 뒤 부른다. 파일은 데이터 폴더의 code-trash로 옮긴다(되살릴 수 있다)."""
        def go():
            ws = self._code_ws()
            trash = None if remote_fs.is_remote(ws) else storage.APP_DIR / "code-trash"   # 원격은 서버의 ~/.cache/poschat/trash
            return {"deleted": cw.delete_to_trash(ws, str(path), trash)}
        return self._code_call(go)

    def code_search(self, query, mode="name", regex=False, case=False):
        def go():
            s = self._code_settings()
            return cw.search(self._code_ws(), str(query or ""), "text" if mode == "text" else "name", bool(regex),
                             bool(case), s["show_hidden"], s["exclude"])
        return self._code_call(go)

    def code_hash(self, path):
        """열린 파일이 디스크에서 바뀌었는지 확인할 때(창으로 돌아올 때 등)."""
        return self._code_call(lambda: {"hash": cw.current_hash(self._code_ws(), str(path))})

    # ---- AI에게 묻기 ----

    def code_ask(self, request):
        """선택한 코드·블록·파일(여러 개)을 채팅 첨부로 만든다. 파일 내용은 외부 데이터로 감싼다(그 안의 지시를 따르지 않게).
        request: {"path", "kind": selection|block|file|files, "text", "from_line", "to_line", "context",
                  "context_from", "preset", "paths": [...]}"""
        def go():
            req = request if isinstance(request, dict) else {}
            kind = req.get("kind", "selection")
            preset = ASK_PRESETS.get(req.get("preset") or "explain", ASK_PRESETS["explain"])
            ws = self._code_ws()
            limit = attachments.MAX_TEXT_CHARS - 1200
            items = []
            if kind == "files":
                paths = [str(p) for p in (req.get("paths") or [])][:6]
                if not paths:
                    raise cw.WorkspaceError("첨부할 파일을 고르세요.")
                for p in paths:
                    info = cw.read_file(ws, p)
                    if info["binary"]:
                        continue
                    items.append(self._code_ask_item(info["path"], info["language"], info["text"], 1, None,
                                                     limit // max(1, min(len(paths), 2)), "파일"))
                question = "첨부한 파일들을 함께 보고 " + preset
            else:
                rel = cw.clean_rel(str(req.get("path") or ""))
                if not rel:
                    raise cw.WorkspaceError("파일을 먼저 여세요.")
                cw.resolve(ws, rel, allow_root=False)
                lang = cw.language_of(rel)
                text = req.get("text")
                if not isinstance(text, str):
                    text = cw.read_file(ws, rel)["text"]
                if kind in ("selection", "block") and not text.strip():
                    raise cw.WorkspaceError("코드를 먼저 선택하세요.")
                start = int(req.get("from_line") or 1)
                end = int(req.get("to_line") or (start + text.count("\n")))
                label = {"selection": "선택한 코드", "block": "현재 함수·블록", "file": "파일 전체"}.get(kind, "코드")
                items.append(self._code_ask_item(rel, lang, text, start, end, limit, label,
                                                 context=req.get("context"), context_from=req.get("context_from")))
                question = preset if kind != "file" else preset.replace("선택한 코드", "이 파일")
            return {"attachments": items, "question": question}
        return self._code_call(go)

    def _code_ask_item(self, rel, lang, text, start, end, limit, label, context=None, context_from=None):
        label_lang = cw.LANG_LABEL.get(lang, lang)
        truncated = len(text) > limit
        body = text[:limit]
        lines = f"{start}-{end}" if end else f"{start}-{start + body.count(chr(10))}"
        head = [f"파일: {rel}", f"언어: {label_lang}", f"줄: {lines}", f"범위: {label}"]
        if truncated:
            head.append(f"(내용이 길어 앞부분 {limit:,}자만 넣었습니다. 필요한 부분을 선택해 다시 물어보세요.)")
        fence = "````" if "```" in body else "```"
        parts = ["\n".join(head), "", f"{label}:", f"{fence}{lang if lang != 'text' else ''}", body.rstrip("\n"), fence]
        if isinstance(context, str) and context.strip() and len(body) < limit - 500:
            ctx = context[:max(0, limit - len(body) - 400)]
            parts += ["", f"주변 코드({context_from or '?'}번째 줄부터, 참고용):", fence + (lang if lang != "text" else ""),
                      ctx.rstrip("\n"), fence]
        wrapped = connectors.wrap_untrusted("\n".join(parts) + "\n", f"작업 폴더 파일 {rel}")
        name = f"코드 - {os.path.basename(rel)} {lines}.md"
        return self._code_attach(re.sub(r"[\\/:*?\"<>|]", "_", name)[:120], wrapped)

    # ---- 변경 제안 검토 ----

    def code_proposals(self):
        return {"ok": True, "proposals": [p.to_dict(full=False) for p in self._code_store().all()]}

    def _code_proposal_ws(self, p):
        """제안이 만들어진 작업 폴더(사용자가 그 사이 작업 폴더를 바꿔도 다른 폴더의 같은 이름 파일에 쓰지 않는다)."""
        return p.workspace or self._code_ws()

    def code_proposal(self, proposal_id):
        def go():
            p = self._code_store().get(proposal_id)
            data = p.to_dict(full=True)
            if p.status == "pending":
                now = cw.current_hash(self._code_proposal_ws(p), p.file_path)
                data["conflict"] = now != p.base_hash
            return {"proposal": data}
        return self._code_call(go)

    def code_review_preview(self, proposal_id, accepted, edited=None):
        def go():
            p = self._code_store().get(proposal_id)
            res = code_diff.preview(self._code_proposal_ws(p), p, accepted or [],
                                    edited if isinstance(edited, str) else None)
            res.pop("text", None)
            return res
        return self._code_call(go)

    def code_review_apply(self, proposal_id, accepted, edited=None, rebase=False):
        def go():
            p = self._code_store().get(proposal_id)
            with self._lock:  # 에이전트 중지(finish)와 겹치지 않게
                result = code_diff.apply(self._code_proposal_ws(p), p, [int(i) for i in (accepted or [])],
                                         edited if isinstance(edited, str) else None, bool(rebase))
            self._code_resolve(p.proposal_id, result)
            self._push({"type": "code", "kind": "proposal", "proposal": p.to_dict(full=False)})
            if result["status"] != "rejected":
                self._push({"type": "code", "kind": "file_changed", "path": p.file_path, "hash": p.result_hash,
                            "by": "review"})
            return {"result": {k: v for k, v in result.items() if k != "content"}, "proposal": p.to_dict(full=False)}
        return self._code_call(go)

    def code_review_reject(self, proposal_id):
        def go():
            p = self._code_store().get(proposal_id)
            with self._lock:
                result = code_diff.reject(p)
            self._code_resolve(p.proposal_id, result)
            self._push({"type": "code", "kind": "proposal", "proposal": p.to_dict(full=False)})
            return {"proposal": p.to_dict(full=False)}
        return self._code_call(go)

    def _code_resolve(self, proposal_id, result):
        """그 제안을 기다리는 에이전트 모두에게 결과를 알린다(같은 제안을 둘이 기다릴 수 있다)."""
        for entry in list((self._code_waiters or {}).get(proposal_id, [])):
            entry[1] = result
            entry[0].set()

    def _code_finish(self, p, status, message):
        """적용 없이 끝낸다. 이미 적용·거부됐으면(사용자가 먼저 눌렀다) 그대로 두고 False."""
        with self._lock:
            if p.status != "pending":
                return False
            code_diff.finish(p, status, message)
        self._push({"type": "code", "kind": "proposal", "proposal": p.to_dict(full=False)})
        return True

    def _code_review_edit(self, thread_id, alive, workspace, rel, old_text, new_text, title, reason, encoding):
        """에이전트의 write/edit(agent.Agent.review). workspace는 그 에이전트의 작업 폴더.
        None을 돌려주면 예전 승인 창을 쓴다."""
        if not self._code_active or self._code_android() or self._code_settings()["review"] != "auto":
            return None
        ws = workspace or self._workspace()
        if not ws:
            return None
        try:
            p = code_diff.new_proposal(ws, rel, old_text or "", new_text, encoding, reason, title, "agent", thread_id)
        except (code_diff.ProposalError, cw.WorkspaceError) as e:
            return {"status": "conflict", "message": str(e)}
        if not p.hunks:
            return {"status": "unchanged", "message": "변경 없음"}
        store = self._code_store()
        p, created = store.add(p)
        permission = self._config.get("permission", "ask")
        if permission in ("auto_edit", "auto_all") or "edit" in getattr(self, "_session_allow", set()):
            try:
                with self._lock:
                    result = code_diff.apply(self._code_proposal_ws(p), p, [h.id for h in p.hunks])
                    p.status, p.message = "auto", "설정에 따라 자동 적용"
            except (cw.ConflictError, code_diff.ProposalError) as e:
                return {"status": "conflict", "message": str(e)}
            result = dict(result, status="applied")
            self._code_resolve(p.proposal_id, result)  # 같은 제안을 기다리던 다른 에이전트에게도
            self._push({"type": "code", "kind": "proposal", "proposal": p.to_dict(full=False)})
            self._push({"type": "code", "kind": "file_changed", "path": p.file_path, "hash": p.result_hash, "by": "agent"})
            return result
        if not alive():
            if created:
                self._code_finish(p, "cancelled", "에이전트 실행을 멈춤")
            return {"status": "cancelled", "message": "중지됨"}
        entry = [threading.Event(), None]
        self._code_waiters.setdefault(p.proposal_id, []).append(entry)
        if p.status != "pending":  # 등록하는 사이에 끝났다
            entry[1] = {"status": p.status if p.status != "auto" else "applied", "message": p.message}
            entry[0].set()
        self._push({"type": "code", "kind": "proposal", "proposal": p.to_dict(full=False), "new": created})
        self._push({"type": "status", "thread_id": thread_id, "text": f"Code 화면에서 변경을 검토해 주세요: {p.file_path}"})
        try:
            while not entry[0].wait(0.5):
                if not alive():
                    if self._code_finish(p, "cancelled", "에이전트 실행을 멈춤"):
                        self._code_resolve(p.proposal_id, {"status": "cancelled", "message": "중지됨"})
                        return {"status": "cancelled", "message": "중지됨"}
                    entry[0].wait(5)  # 사용자가 막 적용·거부했다: 그 결과를 받는다
                    break
        finally:
            waiters = self._code_waiters.get(p.proposal_id, [])
            if entry in waiters:
                waiters.remove(entry)
            if not waiters:
                self._code_waiters.pop(p.proposal_id, None)
        result = entry[1]
        if result is None:
            return {"status": "cancelled", "message": "중지됨"}
        if result == "fallback":
            return None
        return result

    # ---- Git ----

    def _code_git_ready(self):
        if self._code_android():
            raise code_git.GitError("안드로이드에서는 Git 기능을 쓸 수 없습니다(PC 앱에서 쓰세요).")
        return self._code_ws()

    def code_git_status(self):
        return self._code_call(lambda: {"git": code_git.status(self._code_git_ready())})

    def code_git_diff(self, path, staged=False):
        return self._code_call(lambda: {"diff": code_git.diff(self._code_git_ready(), str(path), bool(staged))})

    def code_git_stage(self, paths):
        return self._code_call(lambda: code_git.stage(self._code_git_ready(), list(paths or [])))

    def code_git_unstage(self, paths):
        return self._code_call(lambda: code_git.unstage(self._code_git_ready(), list(paths or [])))

    def code_git_commit(self, message, no_verify=False):
        return self._code_call(lambda: code_git.commit(self._code_git_ready(), str(message or ""), bool(no_verify)))

    def code_git_ask(self, kind="explain", path="", staged=False):
        """변경 설명·코드 리뷰·커밋 메시지 제안: 차이를 외부 데이터로 감싼 첨부와 질문."""
        def go():
            ws = self._code_git_ready()
            if kind not in GIT_ASKS:
                raise ValueError("요청 종류")
            use_staged = True if kind == "commit" else bool(staged)
            if path:
                d = code_git.diff(ws, str(path), use_staged)
                text, truncated, what = d["diff"], d["truncated"], d["path"]
            else:
                d = code_git.diff_all(ws, use_staged, attachments.MAX_TEXT_CHARS * 2)
                text, truncated, what = d["diff"], d["truncated"], "작업 폴더 전체"
            if not text.strip():
                raise code_git.GitError("스테이지한 변경이 없습니다. 파일을 먼저 스테이지하세요." if use_staged
                                        else "보낼 변경이 없습니다.")
            limit = attachments.MAX_TEXT_CHARS - 600
            body = text[:limit]
            note = "\n(차이가 길어 앞부분만 넣었습니다.)" if truncated or len(text) > limit else ""
            head = f"# git diff{' --cached' if use_staged else ''} — {what}\n"
            wrapped = connectors.wrap_untrusted(head + "```diff\n" + body.rstrip("\n") + "\n```" + note + "\n",
                                                f"Git 변경 {what}")
            name = f"git diff - {os.path.basename(str(path)) if path else '전체'}{' (staged)' if use_staged else ''}.md"
            return {"attachments": [self._code_attach(name, wrapped)], "question": GIT_ASKS[kind]}
        return self._code_call(go)

    # ---- 명령 실행 ----

    def _code_run_ready(self):
        if self._code_android():
            raise code_runner.RunnerError("안드로이드에서는 명령을 실행할 수 없습니다(PC 앱에서 쓰세요).")
        return self._code_ws()

    def code_tools(self):
        return self._code_call(lambda: {"tools": code_runner.tools() if not self._code_android() else []})

    def code_run_check(self, command):
        """승인 창에 보일 정보와 한 번 쓰는 승인 토큰(5분). 화면은 사용자가 '실행'을 누르면 토큰과 함께 code_run_start를 부른다."""
        def go():
            ws = self._code_run_ready()
            cmd = str(command or "").strip()
            if not cmd:
                raise code_runner.RunnerError("실행할 명령을 입력하세요.")
            if len(cmd) > code_runner.MAX_COMMAND:
                raise code_runner.RunnerError("명령이 너무 깁니다.")
            info = code_runner.analyze(cmd)
            token = secrets.token_hex(16)
            if self._code_tokens is None:
                self._code_tokens = {}
            now = time.time()
            for t, (_, at) in list(self._code_tokens.items()):
                if now - at > TOKEN_SECONDS:
                    self._code_tokens.pop(t, None)
            self._code_tokens[token] = (hashlib.sha256(cmd.encode("utf-8")).hexdigest(), now)
            return {"token": token, "command": cmd, "cwd": ws, "inputs": code_runner.input_files(ws, cmd),
                    "timeout": self._code_settings()["timeout"], **info}
        return self._code_call(go)

    def code_run_start(self, command, token, purpose=""):
        def go():
            ws = self._code_run_ready()
            cmd = str(command or "").strip()
            self._code_take_token(cmd, token)
            rec = self._code_runner().start(ws, cmd, self._code_settings()["timeout"], purpose)
            conf = self._code_conf()
            history = [c for c in conf.get("history") or [] if c != rec.command]
            conf["history"] = [rec.command] + history[:MAX_HISTORY - 1]
            self._code_save_conf()
            return {"run": rec.to_dict(tail=False)}
        return self._code_call(go)

    def _code_take_token(self, cmd, token):
        """code_run_check가 준 한 번 쓰는 승인 토큰을 확인하고 없앤다(명령이 같고 5분 안일 때만)."""
        entry = (self._code_tokens or {}).pop(str(token or ""), None)
        if not entry or entry[0] != hashlib.sha256(str(cmd).encode("utf-8")).hexdigest() or \
                time.time() - entry[1] > TOKEN_SECONDS:
            raise code_runner.RunnerError("승인한 명령과 다르거나 승인이 만료되었습니다. 다시 실행을 누르세요.")

    def code_run_stop(self, run_id):
        return self._code_call(lambda: {"run": self._code_runner().stop(str(run_id)).to_dict(tail=False)})

    def code_runs(self):
        return self._code_call(lambda: {"runs": [r.to_dict(tail=False) for r in self._code_runner().records()]})

    def code_run_get(self, run_id):
        return self._code_call(lambda: {"run": self._code_runner().get(str(run_id)).to_dict(tail=True)})

    def code_run_ask(self, run_id):
        """실행 결과(명령·종료 코드·출력 끝부분·소스 위치)를 채팅 첨부로. 출력은 외부 데이터로 감싼다."""
        def go():
            rec = self._code_runner().get(str(run_id))
            tail = rec.output_tail[-(attachments.MAX_TEXT_CHARS - 1500):]
            locs = "\n".join(f"- {x['path']}:{x['line']}" for x in rec.locations[:20])
            body = (f"명령: {rec.command}\n작업 폴더: {rec.cwd}\n결과: {rec.status} (종료 코드 {rec.code}, {rec.seconds}초)\n"
                    + (f"입력 파일: {', '.join(rec.inputs)}\n" if rec.inputs else "")
                    + (f"출력에 나온 소스 위치:\n{locs}\n" if locs else "")
                    + f"\n출력(끝부분):\n```\n{tail}\n```\n")
            wrapped = connectors.wrap_untrusted(body, f"명령 출력 {rec.command[:60]}")
            name = re.sub(r"[\\/:*?\"<>|]", "_", f"실행 출력 - {rec.command[:30]}.md")
            return {"attachments": [self._code_attach(name, wrapped)],
                    "question": "이 명령의 출력에서 오류 원인을 찾고 고치는 방법을 알려 줘. 관련 파일:줄을 짚어 줘."}
        return self._code_call(go)

    # ---- 터미널(1.18) ----

    def _code_terms(self):
        if self._code_terms_obj is None:
            self._code_terms_obj = terminal.TerminalManager(
                on_output=lambda sid, text: self._push({"type": "code", "kind": "term_output", "id": sid, "data": text}),
                on_exit=lambda sid, code: self._push({"type": "code", "kind": "term_exit", "id": sid, "code": code}))
        return self._code_terms_obj

    def _code_term_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except (terminal.TerminalError, cw.WorkspaceError, remote_fs.RemoteError) as e:
            return {"ok": False, "error": str(e)}

    def code_term_open(self, cols=80, rows=24):
        """새 터미널(작업 폴더에서 시작하는 셸). 출력은 {"type": "code", "kind": "term_output"} 이벤트로 온다."""
        def go():
            if self._code_android():
                raise terminal.TerminalError("안드로이드에서는 터미널을 쓸 수 없습니다(PC 앱에서 쓰세요).")
            return {"terminal": self._code_terms().open(self._code_ws_opt(), cols, rows).to_dict()}
        return self._code_term_call(go)

    def code_term_write(self, term_id, data):
        return self._code_term_call(lambda: self._code_terms().write(term_id, data))

    def code_term_resize(self, term_id, cols, rows):
        return self._code_term_call(lambda: self._code_terms().resize(term_id, cols, rows))

    def code_term_close(self, term_id):
        return self._code_term_call(lambda: {"terminal": self._code_terms().close(term_id).to_dict()})

    def code_terms(self):
        """열린 터미널과 끝부분 출력(화면을 다시 그릴 때)."""
        if self._code_terms_obj is None:
            return {"ok": True, "terminals": []}
        m = self._code_terms_obj
        return {"ok": True, "terminals": [m.get(t["id"]) for t in m.list()]}

    def code_term_ask(self, text, title="터미널"):
        """터미널에서 고른 글(또는 끝부분)을 채팅 첨부로. 비밀은 가리고, 외부 데이터로 감싼다."""
        def go():
            body = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07", "", str(text or ""))   # 색·커서 같은 제어 글자 빼기
            body = body.replace("\r\n", "\n").replace("\r", "\n").strip()[-(attachments.MAX_TEXT_CHARS - 1500):]
            if not body:
                raise terminal.TerminalError("물어볼 터미널 출력이 없습니다.")
            body = code_runner.Masker(self._code_secrets()).feed(body, final=True)
            ws = self._code_ws_opt()
            where = remote_fs.label(ws) + " (SSH 원격)" if ws and remote_fs.is_remote(ws) else ws
            wrapped = connectors.wrap_untrusted(f"작업 폴더: {where}\n\n```\n{body}\n```\n", f"{title} 출력")
            name = re.sub(r"[\\/:*?\"<>|]", "_", f"터미널 출력 - {str(title)[:30]}.md")
            return {"attachments": [self._code_attach(name, wrapped)],
                    "question": "이 터미널 출력에서 무슨 일이 일어났는지 설명하고, 오류가 있으면 원인과 고치는 방법을 알려 줘."}
        return self._code_term_call(go)

    def _code_shutdown(self):
        if self._code_terms_obj is not None:
            self._code_terms_obj.shutdown()
        if self._code_runner_obj is not None:
            self._code_runner_obj.shutdown()
