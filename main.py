"""POSTECH GenAI Chat — pywebview 데스크톱 앱 진입점.

화면은 web/ 아래의 HTML/CSS/JS이고, JS는 window.pywebview.api.<메서드>로 Bridge를 호출한다.
Python → JS 알림은 window.onBackendEvent(event)로 보낸다.
"""
import json
import os
import sys
import threading
import time
import uuid

import webview

import mcp_client
import storage
from agent import INIT_TASK, Agent, discover_skills, load_init, resource_dir
from api import DEFAULT_MODEL, MODELS, ApiError, ApiSettings

APP_TITLE = "POSTECH GenAI Chat"
APP_VERSION = "1.3.0"

SKILL_TEMPLATE = """---
name: {name}
description: 이 스킬을 언제 쓰는지 한 줄로 설명하세요.
---

# {name}

## 절차
1. ...
2. ...

## 출력 형식
- ...
"""


class Bridge:
    """JS에서 호출하는 API. 밑줄로 시작하는 이름은 JS에 노출되지 않는다."""

    def __init__(self):
        storage.ensure_dirs()
        self._config = storage.load_config()
        self._lock = threading.RLock()
        self._window = None
        self._busy = False
        self._run_id = 0
        self._cancel = threading.Event()
        self._pending = {}            # confirm id -> [Event, decision]
        self._session_allow = set()   # "edit" / "run" — 이번 실행 동안 항상 허용
        self._mcp = mcp_client.Manager()

    # ---- 내부 도우미 ----

    def _push(self, event):
        if self._window is None:
            return
        try:
            self._window.evaluate_js(f"window.onBackendEvent({json.dumps(event, ensure_ascii=False)})")
        except Exception:
            pass  # 창이 닫히는 중

    def _workspace(self):
        ws = self._config.get("workspace", "")
        return ws if ws and os.path.isdir(ws) else ""

    def _api_key(self):
        return self._config.get("api_key") or os.environ.get("POSTECH_GENAI_API_KEY", "")

    def _add(self, thread_id, role, content, **extra):
        with self._lock:
            thread = storage.load_thread(thread_id)
            if thread is None:  # 작업 중 삭제됨
                return None
            msg = storage.make_message(role, content, **extra)
            thread["messages"].append(msg)
            storage.save_thread(thread)
        self._push({"type": "message", "thread_id": thread_id, "message": msg})
        return msg

    def _workspace_info(self):
        ws = self._workspace()
        return {
            "path": ws,
            "name": os.path.basename(ws.rstrip("\\/")) if ws else "",
            "has_init": bool(ws) and load_init(ws) is not None,
        }

    def _skills(self):
        return [{"name": s.name, "description": s.description, "source": s.source, "path": str(s.path)}
                for s in discover_skills(self._workspace()).values()]

    # ---- 상태 ----

    def get_state(self):
        key_source = "settings" if self._config.get("api_key") else ("env" if os.environ.get("POSTECH_GENAI_API_KEY") else None)
        return {
            "threads": storage.list_threads(),
            "workspace": self._workspace_info(),
            "skills": self._skills(),
            "busy": self._busy,
            "config": {
                "agent_mode": self._config.get("agent_mode", True),
                "history_messages": self._config.get("history_messages", 20),
                "max_steps": self._config.get("max_steps", 25),
                "permission": self._config.get("permission", "ask"),
                "share_threads": self._config.get("share_threads", True),
                "key_source": key_source,
                "api_mode": self._config.get("api_mode", "a1"),
                "responses_url": self._config.get("responses_url", ""),
                "model": self._config.get("model", DEFAULT_MODEL),
                "stream": self._config.get("stream", True),
            },
            "data_dir": str(storage.APP_DIR),
            "version": APP_VERSION,
            "models": [{"id": m, "label": label} for m, label in MODELS],
            "memory": storage.load_memory(),
        }

    # ---- 스레드 ----

    def list_threads(self):
        return storage.list_threads()

    def load_thread(self, thread_id):
        return storage.load_thread(thread_id)

    def new_thread(self):
        with self._lock:
            return storage.new_thread()

    def rename_thread(self, thread_id, title):
        title = (title or "").strip()
        with self._lock:
            thread = storage.load_thread(thread_id)
            if thread and title:
                thread["title"] = title[:80]
                storage.save_thread(thread)
        return storage.list_threads()

    def delete_thread(self, thread_id):
        with self._lock:
            storage.delete_thread(thread_id)
        return storage.list_threads()

    # ---- 설정 ----

    def save_settings(self, settings):
        url = str(settings.get("responses_url") or "").strip()
        if url and not url.startswith("https://"):
            return {"ok": False, "error": "Responses API 주소는 https://로 시작해야 합니다."}
        with self._lock:
            if settings.get("api_key"):
                self._config["api_key"] = settings["api_key"].strip()
            if settings.get("clear_key"):
                self._config["api_key"] = ""
            for key, lo, hi in (("history_messages", 0, 200), ("max_steps", 1, 100)):
                if key in settings:
                    try:
                        self._config[key] = max(lo, min(hi, int(settings[key])))
                    except (TypeError, ValueError):
                        pass
            if "share_threads" in settings:
                self._config["share_threads"] = bool(settings["share_threads"])
            if settings.get("permission") in ("ask", "auto_edit", "auto_all"):
                self._config["permission"] = settings["permission"]
            if settings.get("api_mode") in ("a1", "responses"):
                self._config["api_mode"] = settings["api_mode"]
            if "responses_url" in settings:
                self._config["responses_url"] = url
            if settings.get("model") in {m for m, _ in MODELS}:
                self._config["model"] = settings["model"]
            if "stream" in settings:
                self._config["stream"] = bool(settings["stream"])
            storage.save_config(self._config)
        return self.get_state()

    def set_agent_mode(self, enabled):
        with self._lock:
            self._config["agent_mode"] = bool(enabled)
            storage.save_config(self._config)

    def choose_workspace(self):
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=self._workspace() or os.path.expanduser("~"))
        if result:
            path = result[0] if isinstance(result, (list, tuple)) else result
            with self._lock:
                self._config["workspace"] = os.path.normpath(path)
                storage.save_config(self._config)
        return {"workspace": self._workspace_info(), "skills": self._skills()}

    def open_folder(self, which):
        targets = {
            "skills": storage.USER_SKILLS_DIR,
            "data": storage.APP_DIR,
            "workspace": self._workspace() or None,
        }
        target = targets.get(which)
        if target and os.path.isdir(target):
            os.startfile(target)

    def create_skill(self, name):
        name = "-".join((name or "").strip().split())
        if not name or any(c in name for c in '\\/:*?"<>|'):
            return {"ok": False, "error": "스킬 이름에 쓸 수 없는 문자가 있습니다."}
        path = storage.USER_SKILLS_DIR / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(SKILL_TEMPLATE.format(name=name), encoding="utf-8")
        os.startfile(path)
        return {"ok": True, "skills": self._skills()}

    # ---- 메모리 ----

    def list_memory(self):
        return storage.load_memory()

    def add_memory(self, text):
        with self._lock:
            item = storage.add_memory(text)
        return {"ok": item is not None, "memory": storage.load_memory()}

    def delete_memory(self, memory_id):
        with self._lock:
            storage.delete_memory(memory_id)
        return storage.load_memory()

    def get_skills(self):
        return self._skills()

    # ---- MCP ----

    def get_mcp(self):
        return self._mcp.status(self._config, self._workspace())

    def connect_mcp(self):
        """켜진 MCP 서버를 지금 연결해 본다(MCP 창의 '연결' 버튼)."""
        self._mcp.ensure(self._config, self._workspace())
        return self.get_mcp()

    def set_mcp_enabled(self, name, enabled):
        with self._lock:
            disabled = set(self._config.get("mcp_disabled", []))
            (disabled.discard if enabled else disabled.add)(str(name))
            self._config["mcp_disabled"] = sorted(disabled)
            storage.save_config(self._config)
        return self.get_mcp()

    def open_mcp_config(self):
        os.startfile(mcp_client.ensure_config_file())

    # ---- 대화 실행 ----

    def send(self, thread_id, text, agent_mode):
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "메시지가 비어 있습니다."}
        if self._busy:
            return {"ok": False, "error": "이전 응답을 기다리는 중입니다."}
        workspace = self._workspace()
        task, forced = text, None

        if text.startswith("/"):
            cmd, _, rest = text[1:].partition(" ")
            cmd, rest = cmd.lower(), rest.strip()
            if cmd == "init":
                if not workspace:
                    return {"ok": False, "error": "/init 을 쓰려면 먼저 작업 폴더를 선택하세요."}
                agent_mode = True
                task = INIT_TASK + (f"\n추가 요청: {rest}" if rest else "")
            else:
                skills = discover_skills(workspace)
                if cmd not in skills:
                    return {"ok": False, "error": f"알 수 없는 명령어 또는 스킬입니다: /{cmd}"}
                forced = skills[cmd]
                task = rest or f"'{forced.name}' 스킬을 실행해 주세요."

        api_key = self._api_key()
        if not api_key:
            return {"ok": False, "need_key": True, "error": "API 키가 없습니다. 설정에서 입력하세요."}

        with self._lock:
            thread = storage.load_thread(thread_id)
            if thread is None:
                return {"ok": False, "error": "대화를 찾을 수 없습니다."}
            history = list(thread["messages"])
            if not history and thread["title"] == "새 대화":
                thread["title"] = text.splitlines()[0][:40]
            msg = storage.make_message("user", text)
            thread["messages"].append(msg)
            storage.save_thread(thread)
            self._busy = True
            self._run_id += 1
            run_id = self._run_id
            self._cancel.clear()

        threading.Thread(target=self._work, daemon=True,
                         args=(run_id, thread_id, history, task, bool(agent_mode), forced, api_key, workspace)).start()
        return {"ok": True, "message": msg, "title": thread["title"]}

    def _work(self, run_id, thread_id, history, task, agent_mode, forced, api_key, workspace):
        def alive():
            return run_id == self._run_id and not self._cancel.is_set()

        def on_status(text):
            if alive():
                self._push({"type": "status", "thread_id": thread_id, "text": text})

        def on_tool(summary, detail):
            if alive():
                self._add(thread_id, "tool", summary, detail=detail)

        last_delta = [0.0]

        def on_delta(text):
            # 화면 갱신이 너무 잦지 않게 0.08초에 한 번만 보낸다. 마지막 답변은 message 이벤트로 따로 온다.
            now = time.monotonic()
            if alive() and now - last_delta[0] >= 0.08:
                last_delta[0] = now
                self._push({"type": "delta", "thread_id": thread_id, "text": text})

        agent = Agent(
            api_key=api_key,
            workspace=workspace,
            agent_mode=agent_mode,
            max_steps=int(self._config.get("max_steps", 25)),
            history_messages=int(self._config.get("history_messages", 20)),
            on_status=on_status,
            on_tool=on_tool,
            confirm=lambda kind, title, detail: self._confirm(thread_id, kind, title, detail, alive),
            cancelled=lambda: not alive(),
            thread_id=thread_id,
            share_threads=bool(self._config.get("share_threads", True)),
            mcp=(lambda: self._mcp.ensure(self._config, workspace, on_status)) if agent_mode and workspace else None,
            api_settings=ApiSettings.from_config(self._config),
            on_delta=on_delta,
        )
        try:
            answer = agent.run(history, task, forced)
            if alive():
                self._add(thread_id, "assistant", answer)
        except ApiError as e:
            if alive():
                self._add(thread_id, "error", str(e))
        except Exception as e:
            if alive():
                self._add(thread_id, "error", f"{type(e).__name__}: {e}")
        finally:
            if run_id == self._run_id:
                self._busy = False
                self._push({"type": "done", "thread_id": thread_id, "workspace": self._workspace_info()})

    def _confirm(self, thread_id, kind, title, detail, alive):
        permission = self._config.get("permission", "ask")
        if permission == "auto_all" or (permission == "auto_edit" and kind == "edit") or kind in self._session_allow:
            return True
        if not alive():
            return False
        cid = uuid.uuid4().hex
        entry = [threading.Event(), "deny"]
        self._pending[cid] = entry
        self._push({"type": "confirm", "id": cid, "thread_id": thread_id, "kind": kind, "title": title, "detail": detail})
        entry[0].wait()
        self._pending.pop(cid, None)
        if entry[1] == "always":
            self._session_allow.add(kind)
            return True
        return entry[1] == "allow" and alive()

    def resolve_confirm(self, cid, decision):
        entry = self._pending.get(cid)
        if entry:
            entry[1] = decision
            entry[0].set()

    def stop(self):
        self._cancel.set()
        for entry in list(self._pending.values()):
            entry[1] = "deny"
            entry[0].set()
        self._busy = False
        return True


def selftest():
    """설치된 exe 진단용: 설정된 키로 API를 한 번 호출하고 결과를 데이터 폴더의 selftest.txt에 쓴다."""
    from api import ask
    storage.ensure_dirs()
    config = storage.load_config()
    key = config.get("api_key") or os.environ.get("POSTECH_GENAI_API_KEY", "")
    lines = [f"web: {(resource_dir() / 'web' / 'index.html').exists()}",
             f"skills: {len(discover_skills(config.get('workspace', '')))}"]
    try:
        import docx, olefile, openpyxl, pptx, pypdf  # noqa: F401,E401  문서 라이브러리가 함께 묶였는지
        lines.append("documents: OK")
    except ImportError as e:
        lines.append(f"documents: FAIL {e}")
    import tempfile
    manager = mcp_client.Manager()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            servers = manager.ensure(config, tmp)
            status = manager.status(config, tmp)["servers"]
            lines.append("mcp: " + ", ".join(
                f"{s['name']} OK({len(s['tools'])})" if s["state"] == "connected" else f"{s['name']} {s['state'].upper()} {s['error']}"
                for s in status if s["enabled"]) + f" [{len(servers)} connected]")
        finally:
            manager.shutdown()  # 서버가 임시 폴더를 쓰고 있으면 지울 수 없으므로 먼저 끈다
    try:
        settings = ApiSettings.from_config(config)
        lines.append(f"api mode: {settings.mode}" + (f" ({settings.model})" if settings.mode == "responses" else ""))
        reply = ask(key, "'정상'이라고 한 단어로만 답하세요.", settings=settings) if key else "(API 키 없음)"
        lines.append(f"api: OK {reply[:80]!r}")
    except ApiError as e:
        lines.append(f"api: FAIL {e}")
    (storage.APP_DIR / "selftest.txt").write_text("\n".join(lines), encoding="utf-8")


def uninstall(quiet=False):
    """설치 프로그램이 등록한 제거 명령(PostechChat.exe --uninstall). 대화 기록·설정은 남긴다."""
    import ctypes
    import subprocess
    import winreg
    from pathlib import Path

    app_dir = Path(sys.executable).resolve().parent
    if not getattr(sys, "frozen", False) or not (app_dir / "_internal").is_dir():
        return  # 소스 실행 중에는 아무것도 지우지 않는다
    MB_YESNO, MB_ICONQUESTION, MB_ICONINFO, IDYES = 0x4, 0x20, 0x40, 6
    message = (f"{APP_TITLE}을(를) 제거할까요?\n\n대화 기록과 설정은 지우지 않고 다음 폴더에 남깁니다.\n{storage.APP_DIR}")
    if not quiet and ctypes.windll.user32.MessageBoxW(None, message, "제거", MB_YESNO | MB_ICONQUESTION) != IDYES:
        return

    def shell_folder(csidl):
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        return Path(buf.value)

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PostechChat"
    shortcuts = [shell_folder(csidl) / f"{APP_TITLE}.lnk" for csidl in (0x02, 0x10)]  # 시작 메뉴, 바탕화면
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            shortcuts += [Path(p) for p in winreg.QueryValueEx(k, "Shortcuts")[0]]  # 설치 때 실제로 만든 바로가기
    except OSError:
        pass
    for lnk in shortcuts:
        try:
            lnk.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except OSError:
        pass
    # 실행 중인 자기 자신은 지울 수 없으므로, 프로세스가 끝난 뒤 cmd가 폴더를 지운다.
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{app_dir}"',
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, cwd=str(app_dir.parent))
    if not quiet:
        ctypes.windll.user32.MessageBoxW(None, f"{APP_TITLE}을(를) 제거했습니다.", "제거", MB_ICONINFO)


def _log_crash():
    """창 모드 exe는 오류가 화면에 안 보이므로 데이터 폴더의 error.log에 남긴다."""
    import traceback
    try:
        storage.APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(storage.APP_DIR / "error.log", "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
    except OSError:
        pass


def main():
    try:
        if "--mcp-server" in sys.argv:
            # 앱 자신을 내장 MCP 서버로 실행한다(mcp_client가 띄운다).
            import office_mcp
            i = sys.argv.index("--mcp-server")
            office_mcp.serve(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        elif "--selftest" in sys.argv:
            selftest()
        elif "--uninstall" in sys.argv:
            uninstall(quiet="--quiet" in sys.argv)
        else:
            run_app()
    except Exception:
        _log_crash()
        raise


def _window_size(width=1240, height=840):
    """작업 표시줄을 뺀 화면 영역(논리 픽셀)의 90%를 넘지 않게 창 크기를 정한다."""
    try:
        import ctypes
        from ctypes import wintypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    try:
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        scale = ctypes.windll.user32.GetDpiForSystem() / 96
        work_w, work_h = (rect.right - rect.left) / scale, (rect.bottom - rect.top) / scale
        return min(width, int(work_w * 0.9)), min(height, int(work_h * 0.9))
    except Exception:
        return width, height


def run_app():
    bridge = Bridge()
    index = resource_dir() / "web" / "index.html"
    width, height = _window_size()
    window = webview.create_window(
        APP_TITLE, url=str(index), js_api=bridge,
        width=width, height=height, min_size=(760, 520), text_select=True,
    )
    bridge._window = window
    try:
        webview.start(debug=os.environ.get("POSTECH_CHAT_DEBUG") == "1")
    finally:
        bridge._mcp.shutdown()


if __name__ == "__main__":
    main()
