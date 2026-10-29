# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""코드 화면의 원격(SSH) 작업 폴더 API(1.18): main.Bridge가 상속한다. 화면은 web/code-ssh.js.

- 연결은 사용자가 고른 서버에만, 뒤 스레드에서 한다. 호스트 키 확인·암호·OTP·키 암호문은 {"type": "code", "kind": "ssh_prompt"}
  이벤트로 화면에 묻고 code_ssh_answer로 답을 받는다(5분 안에 답이 없으면 취소). 암호·OTP는 저장하지 않는다.
- 원격 작업 폴더를 열면 설정의 code.remote에 {target, path}를 남기고, 코드 화면(파일·Git·터미널·Code 에이전트)은 작업 폴더로
  'ssh://target/path'를 쓴다(remote_fs). 채팅·Lab의 작업 폴더는 그대로 로컬이다.
- 안드로이드에는 paramiko가 없어 쓰지 않는다.
"""
import threading
import time
import uuid

import remote_fs

MAX_RECENT = 10
PROMPT_SECONDS = 300


class SshApi:
    _ssh_conns = None      # 연결 이름 → SshConnection
    _ssh_states = None     # 연결 이름 → {"state", "message"}
    _ssh_prompts = None    # 묻는 id → [Event, 답, 연결 이름]
    _ssh_lock = None

    def _ssh_init(self):
        if self._ssh_conns is None:
            self._ssh_conns, self._ssh_states, self._ssh_prompts = {}, {}, {}
            self._ssh_lock = threading.Lock()

    def _ssh_supported(self):
        if self._code_android():
            return False
        try:
            import paramiko  # noqa: F401
        except Exception:
            return False
        return True

    def _ssh_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except OSError as e:   # RemoteError·SshError 포함
            return {"ok": False, "error": str(e.strerror if getattr(e, "strerror", None) else e)}
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": f"잘못된 요청입니다: {e}"}

    # ---- 코드 화면의 작업 폴더 ----

    def _code_remote(self):
        r = (self._config.get("code") or {}).get("remote")
        if isinstance(r, dict) and isinstance(r.get("target"), str) and isinstance(r.get("path"), str) and r["path"].startswith("/"):
            return r
        return None

    def _code_ws_opt(self):
        """코드 화면의 작업 폴더: 원격을 열었으면 'ssh://target/path', 아니면 로컬 작업 폴더(없으면 None)."""
        r = self._code_remote()
        if r:
            return remote_fs.url(r["target"], r["path"])
        return self._workspace()

    def _ssh_state(self, name):
        self._ssh_init()
        st = dict(self._ssh_states.get(name) or {"state": "closed", "message": ""})
        if remote_fs.connected(name):
            st["state"] = "connected"
        elif st["state"] == "connected":
            st = {"state": "lost", "message": "연결이 끊겼습니다."}
        return st

    def _ssh_info(self):
        """code_state에 넣을 원격 정보(원격 작업 폴더가 아니면 None)."""
        r = self._code_remote()
        if not r:
            return None
        st = self._ssh_state(r["target"])
        conn = (self._ssh_conns or {}).get(r["target"])
        info = getattr(conn, "info", None) or {}
        return {"target": r["target"], "path": r["path"], "label": f"{r['target']}:{r['path']}", "state": st["state"],
                "message": st.get("message", ""), "connected": st["state"] == "connected",
                "server": {k: info.get(k) for k in ("host", "user", "python", "platform", "git")} if info else {}}

    # ---- 화면 API ----

    def code_ssh_hosts(self):
        """연결 창: ~/.ssh/config의 Host들과 최근에 연 원격 폴더."""
        def go():
            hosts = []
            if self._ssh_supported():
                import ssh_remote
                hosts = ssh_remote.config_hosts()
            recent = [r for r in (self._config.get("code") or {}).get("remotes") or [] if isinstance(r, dict)]
            self._ssh_init()
            states = {n: self._ssh_state(n)["state"] for n in list(self._ssh_states)}
            return {"supported": self._ssh_supported(), "hosts": hosts, "recent": recent[:MAX_RECENT], "states": states,
                    "current": self._ssh_info()}
        return self._ssh_call(go)

    def code_ssh_connect(self, target):
        """연결을 시작한다(바로 돌아온다). 진행·결과는 ssh_state 이벤트로, 묻는 것은 ssh_prompt 이벤트로 온다."""
        def go():
            if not self._ssh_supported():
                raise remote_fs.RemoteError("이 기기에서는 SSH 원격 작업 폴더를 쓸 수 없습니다(PC 앱에서 쓰세요).")
            import ssh_remote
            name = ssh_remote.parse_target(target)[0]
            self._ssh_init()
            with self._ssh_lock:
                st = self._ssh_state(name)["state"]
                if st in ("connecting", "connected"):
                    return {"target": name, "state": st}
                self._ssh_states[name] = {"state": "connecting", "message": "연결 중…"}
            threading.Thread(target=self._ssh_work, args=(str(target), name), daemon=True, name=f"ssh-{name}").start()
            return {"target": name, "state": "connecting"}
        return self._ssh_call(go)

    def _ssh_push(self, name, state, message=""):
        self._ssh_states[name] = {"state": state, "message": message}
        self._push({"type": "code", "kind": "ssh_state", "target": name, "state": state, "message": message})

    def _ssh_work(self, target, name):
        import ssh_remote

        def prompt(kind, data):
            return self._ssh_ask(name, kind, data)

        def lost(conn):
            remote_fs.unregister(name, conn)
            with self._ssh_lock:
                if self._ssh_conns.get(name) is conn:
                    self._ssh_conns.pop(name, None)
                    self._ssh_push(name, "lost", "SSH 연결이 끊겼습니다. 다시 연결하세요.")

        self._ssh_push(name, "connecting", "연결 중…")
        conn = ssh_remote.SshConnection(target, prompt, on_closed=lost,
                                        on_status=lambda text: self._ssh_push(name, "connecting", text))
        try:
            conn.connect()
        except OSError as e:
            self._ssh_push(name, "cancelled" if isinstance(e, ssh_remote.Cancelled) else "failed", str(e))
            return
        with self._ssh_lock:
            old = self._ssh_conns.get(name)
            self._ssh_conns[name] = conn
        if old is not None and old is not conn:
            old.close()
        remote_fs.register(name, conn)
        self._ssh_push(name, "connected", f"{conn.info.get('user', '')}@{conn.info.get('host', '')} · Python {conn.info.get('python', '')}")

    def _ssh_ask(self, name, kind, data):
        self._ssh_init()
        pid = uuid.uuid4().hex
        entry = [threading.Event(), None, name]
        self._ssh_prompts[pid] = entry
        self._push({**data, "type": "code", "kind": "ssh_prompt", "id": pid, "target": name, "prompt": kind})
        entry[0].wait(PROMPT_SECONDS)
        self._ssh_prompts.pop(pid, None)
        if not entry[0].is_set():
            self._push({"type": "code", "kind": "ssh_prompt_done", "id": pid})
        return entry[1]

    def code_ssh_answer(self, prompt_id, answer=None):
        """묻는 창의 답. answer: {"accept": true} 또는 {"values": [...]}. None이면 취소."""
        self._ssh_init()
        entry = self._ssh_prompts.get(str(prompt_id or ""))
        if entry is None:
            return {"ok": False, "error": "이미 끝난 질문입니다."}
        if isinstance(answer, dict):
            values = answer.get("values")
            entry[1] = {"accept": bool(answer.get("accept")),
                        "values": [str(v)[:4096] for v in values][:10] if isinstance(values, list) else []}
        entry[0].set()
        return {"ok": True}

    def code_ssh_cancel(self, target=""):
        """연결 중인 것을 취소한다(기다리는 질문에 '취소'로 답한다)."""
        self._ssh_init()
        for entry in list(self._ssh_prompts.values()):
            if not target or entry[2] == target:
                entry[1] = None
                entry[0].set()
        return {"ok": True}

    def code_ssh_browse(self, target, path=""):
        """연결한 서버의 폴더 목록(폴더 고르기 창). path가 비면 홈."""
        return self._ssh_call(lambda: {"folder": remote_fs.connection(str(target)).call("fs.dirs", [str(path or "")], {})})

    def code_ssh_open(self, target, path):
        """서버의 폴더를 코드 화면의 작업 폴더로 연다."""
        def go():
            name = str(target)
            conn = remote_fs.connection(name)
            real = conn.call("fs.dirs", [str(path or "")], {})["path"]   # ~·상대 경로(홈 기준)를 서버에서 실제 경로로
            conf = self._code_conf()
            conf["remote"] = {"target": name, "path": real}
            recent = [r for r in conf.get("remotes") or [] if isinstance(r, dict) and (r.get("target"), r.get("path")) != (name, real)]
            conf["remotes"] = ([{"target": name, "path": real, "at": time.time()}] + recent)[:MAX_RECENT]
            self._code_save_conf()
            return {"workspace": remote_fs.url(name, real), "current": self._ssh_info()}
        return self._ssh_call(go)

    def code_ssh_local(self):
        """코드 화면을 로컬 작업 폴더로 되돌린다(연결은 끊지 않는다 — 다시 원격으로 갈 때 바로 쓴다)."""
        conf = self._code_conf()
        conf.pop("remote", None)
        self._code_save_conf()
        return {"ok": True}

    def code_ssh_disconnect(self, target=""):
        self._ssh_init()
        r = self._code_remote()
        name = str(target or (r or {}).get("target") or "")
        with self._ssh_lock:
            conn = self._ssh_conns.pop(name, None)
        if conn is not None:
            remote_fs.unregister(name, conn)
            conn.close()
        self._ssh_push(name, "closed", "연결을 끊었습니다.")
        return {"ok": True}

    def code_ssh_forget(self, target, path):
        conf = self._code_conf()
        conf["remotes"] = [r for r in conf.get("remotes") or [] if isinstance(r, dict) and (r.get("target"), r.get("path")) != (target, path)]
        self._code_save_conf()
        return {"ok": True, "recent": conf["remotes"]}

    def _ssh_shutdown(self):
        if self._ssh_conns is None:
            return
        self.code_ssh_cancel()
        for name, conn in list(self._ssh_conns.items()):
            remote_fs.unregister(name, conn)
            try:
                conn.close()
            except Exception:
                pass
        self._ssh_conns.clear()
