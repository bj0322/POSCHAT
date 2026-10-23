"""POSTECH GenAI Chat — pywebview 데스크톱 앱 진입점.

화면은 web/ 아래의 HTML/CSS/JS이고, JS는 window.pywebview.api.<메서드>로 Bridge를 호출한다.
Python → JS 알림은 window.onBackendEvent(event)로 보낸다.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlparse

import webview

import api
import attachments
import connectors
import mcp_client
import po_note
import storage
import stt
import updates
from workspace_api import WorkspaceApi
from agent import INIT_TASK, Agent, discover_skills, load_init, resource_dir
from api import DEFAULT_MODEL, MODELS, RESPONSES_MODELS, ApiError, ApiSettings
from version import APP_VERSION

APP_TITLE = "POSTECH GenAI Chat"
UPDATE_INTERVAL = 6 * 3600  # 시작할 때 새 버전을 확인하는 최소 간격(초)
PO_RESERVES = (0, 10, 20, 30, 50)  # PO노트 크레딧 예산 보호: 이번 주 한도의 몇 %를 남겨 둘지(0은 끄기)

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


def open_path(path):
    """파일이나 폴더를 운영체제의 기본 앱으로 연다(안드로이드는 android_main이 os.startfile을 바꿔 끼운다)."""
    if hasattr(os, "startfile"):
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def _extend_mac_path():
    """Finder에서 연 맥 앱은 PATH가 /usr/bin:/bin 정도뿐이라 npx·ai-memory 같은 외부 MCP 실행 도구를 못 찾는다."""
    if sys.platform != "darwin":
        return
    home = os.path.expanduser("~")
    extra = ["/opt/homebrew/bin", "/usr/local/bin", f"{home}/.local/bin", f"{home}/.cargo/bin"]
    current = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(current + [d for d in extra if d not in current])


class Bridge(WorkspaceApi):
    """JS에서 호출하는 API. 밑줄로 시작하는 이름은 JS에 노출되지 않는다. '연결·도구' 창의 API는 WorkspaceApi에 있다."""

    def __init__(self):
        storage.ensure_dirs()
        self._config = storage.load_config()
        if "github_update_token" in self._config:  # 1.8.0의 업데이트 확인용 GitHub 토큰은 더 쓰지 않는다
            self._config.pop("github_update_token", None)
            storage.save_config(self._config)
        self._lock = threading.RLock()
        self._window = None
        self._busy = False
        self._run_id = 0
        self._cancel = threading.Event()
        self._pending = {}            # confirm id -> [Event, decision]
        self._session_allow = set()   # "edit" / "run" / "write" — 이번 실행(메시지 하나) 동안 항상 허용
        self._mcp = mcp_client.Manager()
        self._credit = None           # 응답 헤더로 받은 최근 크레딧 {"usage", "limit", "interval"}
        self._po_session = None       # 녹음 중인 stt.LiveSession
        self._po_note = None          # 녹음 중인 노트 ID
        self._po_stopping = False
        self._po_download = None      # 내려받는 중인 모델 {"key", "done", "total"}
        self._po_cancel_download = threading.Event()
        self._po_generating = None    # 노트를 만드는 중인 노트 ID
        self._po_label = ""           # 녹음 중인 인식 방식 이름
        self._updating = False        # 업데이트 파일을 내려받는 중
        api.on_usage = storage.record_usage
        api.on_credit = self._on_credit
        storage.cleanup_staged()
        connectors.prune_audit()
        self._migrate_config()
        self._sync_schedule(10)  # 동기화를 켰으면 시작하고 조금 뒤 한 번

    def _migrate_config(self):
        """1.9: a1/gpt가 서버 오류만 돌려주므로 OpenAI 호환 API(POSTECH 주소 내장)로 한 번 옮긴다. 잘못된 Claude 모델 ID도 고친다."""
        changed = False
        if not self._config.get("migrated_1_9"):
            if self._config.get("api_mode", "a1") == "a1":
                self._config["api_mode"] = api.DEFAULT_MODE
            self._config["migrated_1_9"] = True
            changed = True
        model = api.normalize_model(self._config.get("model"))
        if self._config.get("model") and model != self._config["model"]:
            self._config["model"] = model
            changed = True
        if changed:
            storage.save_config(self._config)

    def _mode(self):
        mode = self._config.get("api_mode", api.DEFAULT_MODE)
        return mode if mode in ("a1", "responses", "chat_completions") else api.DEFAULT_MODE

    def _on_credit(self, info):
        self._credit = info
        self._push({"type": "credit", "credit": info})

    # ---- 내부 도우미 ----

    def _push(self, event):
        if getattr(self, "_window", None) is None:
            return
        try:
            self._window.evaluate_js(f"window.onBackendEvent({json.dumps(event, ensure_ascii=False)})")
        except Exception:
            pass  # 창이 닫히는 중

    def _open_url(self, url):
        open_path(url)  # Windows os.startfile·macOS open·안드로이드 host.openPath 모두 https 주소를 브라우저로 연다

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
                "api_mode": self._mode(),
                "responses_url": self._config.get("responses_url", ""),
                "chat_completions_url": self._config.get("chat_completions_url", ""),
                "model": self._config.get("model", DEFAULT_MODEL),
                "stream": self._config.get("stream", True),
                "update_check": self._config.get("update_check", True),
                "notion_source": "settings" if self._config.get("notion_token") else (
                    "env" if os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY") else None),
                "firecrawl_source": "settings" if self._config.get("firecrawl_key") else (
                    "env" if os.environ.get("FIRECRAWL_API_KEY") else None),
            },
            "data_dir": str(storage.APP_DIR),
            "version": APP_VERSION,
            "models": [{"id": m, "label": label} for m, label in self._models("chat_completions")],
            "responses_models": [{"id": m, "label": label} for m, label in RESPONSES_MODELS],
            "models_source": "server" if self._config.get("server_models") else "builtin",
            "memory": storage.load_memory(),
            "attach_limits": {"max_bytes": attachments.MAX_BYTES, "max_files": attachments.MAX_FILES},
            "default_chat_completions_url": api.DEFAULT_CHAT_COMPLETIONS_URL,
            "credit": self._credit,
            "po_available": stt.available()[0],
        }

    # ---- 스레드 ----

    def list_threads(self):
        return storage.list_threads()

    def load_thread(self, thread_id):
        with self._lock:
            thread = storage.load_thread(thread_id)
            if thread is not None and api.normalize_model(thread.get("model")) != thread.get("model"):
                thread["model"] = api.normalize_model(thread.get("model"))
                storage.save_thread(thread, update_timestamp=False)
            if thread is not None and thread.get("model") not in self._model_ids(self._mode()):
                thread["model"] = self._default_model()
                storage.save_thread(thread, update_timestamp=False)
            return thread

    def new_thread(self):
        with self._lock:
            thread = storage.new_thread()
            thread["model"] = self._default_model()
            storage.save_thread(thread)
            return thread

    def _models(self, mode):
        """mode에서 고를 수 있는 (모델 ID, 이름). OpenAI 호환 API는 서버에서 받아 둔 목록을 먼저 쓴다."""
        if mode == "responses":
            return RESPONSES_MODELS
        server = [m for m in self._config.get("server_models") or [] if isinstance(m, str) and m]
        return [(m, api.model_label(m)) for m in server] if server else MODELS

    def _model_ids(self, mode):
        return {model_id for model_id, _ in self._models(mode)}

    def _default_model(self):
        mode = self._mode()
        allowed = self._models(mode)
        configured = self._config.get("model", DEFAULT_MODEL)
        return configured if configured in {model_id for model_id, _ in allowed} else allowed[0][0]

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

    def set_thread_model(self, thread_id, model):
        if model not in self._model_ids(self._mode()):
            return {"ok": False, "error": "지원하지 않는 모델입니다."}
        with self._lock:
            thread = storage.load_thread(thread_id)
            if thread is None:
                return {"ok": False, "error": "대화를 찾을 수 없습니다."}
            thread["model"] = model
            storage.save_thread(thread)
        return thread

    # ---- 설정 ----

    def save_settings(self, settings):
        mode = settings.get("api_mode", self._mode())
        url = api.endpoint_url(settings.get("responses_url", self._config.get("responses_url", "")),
                               api.RESPONSES_PATH)
        compatible_url = api.endpoint_url(settings.get("chat_completions_url",
                                                       self._config.get("chat_completions_url", "")),
                                          api.CHAT_COMPLETIONS_PATH)
        if mode == "responses" and not self._valid_https_url(url):
            return {"ok": False, "error": "Responses API를 선택했다면 올바른 HTTPS 주소를 입력해야 합니다."}
        if mode == "chat_completions" and compatible_url and not self._valid_https_url(compatible_url):
            return {"ok": False, "error": "OpenAI 호환 API를 선택했다면 올바른 HTTPS Chat Completions 주소를 입력해야 합니다."}
        with self._lock:
            before = self._sync_settings()
            if settings.get("api_key"):
                self._config["api_key"] = settings["api_key"].strip()
            if settings.get("clear_key"):
                self._config["api_key"] = ""
            if settings.get("notion_token"):
                self._config["notion_token"] = settings["notion_token"].strip()
            if settings.get("clear_notion"):
                self._config["notion_token"] = ""
            if settings.get("firecrawl_key"):
                self._config["firecrawl_key"] = settings["firecrawl_key"].strip()
            if settings.get("clear_firecrawl"):
                self._config["firecrawl_key"] = ""
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
            if settings.get("api_mode") in ("a1", "responses", "chat_completions"):
                self._config["api_mode"] = settings["api_mode"]
            if "responses_url" in settings:
                self._config["responses_url"] = url
            if "chat_completions_url" in settings:
                if compatible_url != self._config.get("chat_completions_url", ""):
                    self._config.pop("server_models", None)  # 다른 서버의 목록은 버린다
                self._config["chat_completions_url"] = compatible_url
            # 설정 창에서 '모델 목록 불러오기'로 받은 목록은 저장을 눌러야 반영한다(취소하면 버린다).
            server_models = self._clean_models(settings.get("server_models"))
            if server_models:
                self._config["server_models"] = server_models
            if settings.get("model") in self._model_ids(self._mode()):
                self._config["model"] = settings["model"]
            if "stream" in settings:
                self._config["stream"] = bool(settings["stream"])
            if "update_check" in settings:
                self._config["update_check"] = bool(settings["update_check"])
            self._stamp_settings(before)
            storage.save_config(self._config)
        return self.get_state()

    def get_usage(self):
        return storage.usage_summary()

    @staticmethod
    def _clean_models(models):
        if not isinstance(models, list):
            return []
        out = []
        for m in models:
            m = m.strip() if isinstance(m, str) else ""
            if m and m not in out:
                out.append(m)
        return out[:500]

    def refresh_models(self, settings=None):
        """OpenAI 호환 API의 모델 목록을 서버에서 받아 돌려준다. 설정 창의 '모델 목록 불러오기'.

        여기서는 저장하지 않는다. 설정 창이 저장할 때 server_models로 함께 보낸다.
        """
        settings = settings or {}
        key = str(settings.get("api_key") or "").strip() or self._api_key()
        if not key:
            return {"ok": False, "error": "API 키를 먼저 입력하세요."}
        url = api.endpoint_url(settings.get("chat_completions_url", self._config.get("chat_completions_url", "")),
                               api.CHAT_COMPLETIONS_PATH) or api.DEFAULT_CHAT_COMPLETIONS_URL
        if not self._valid_https_url(url):
            return {"ok": False, "error": "올바른 HTTPS Chat Completions 주소를 입력하세요."}
        try:
            ids = api.list_models(key, url)
        except ApiError as e:
            return {"ok": False, "error": f"모델 목록을 불러오지 못했습니다: {e}"}
        return {"ok": True, "chat_completions_url": url,
                "models": [{"id": m, "label": api.model_label(m)} for m in ids]}

    @staticmethod
    def _valid_https_url(value):
        try:
            parsed = urlparse(value)
            return (parsed.scheme == "https" and bool(parsed.hostname) and bool(parsed.path.strip("/"))
                    and not parsed.username and not parsed.password and parsed.port != 0)
        except ValueError:
            return False

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
            open_path(target)

    def create_skill(self, name):
        name = "-".join((name or "").strip().split())
        if not name or any(c in name for c in '\\/:*?"<>|'):
            return {"ok": False, "error": "스킬 이름에 쓸 수 없는 문자가 있습니다."}
        path = storage.USER_SKILLS_DIR / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(SKILL_TEMPLATE.format(name=name), encoding="utf-8")
        open_path(path)
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

    # ---- Markdown 노트: memory.md(메모리), USER.md(사용자 정보) ----

    def _note(self, kind):
        if kind == "memory":
            return storage.MEMORY_PATH, storage.read_memory_md, storage.save_memory_md
        if kind == "profile":
            return storage.PROFILE_PATH, storage.read_profile, storage.save_profile
        raise ValueError(f"알 수 없는 노트: {kind}")

    def read_note(self, kind):
        path, read, _ = self._note(kind)
        return {"path": str(path), "text": read(), "exists": path.exists()}

    def save_note(self, kind, text):
        _, _, save = self._note(kind)
        with self._lock:
            save(text)
        return {"ok": True, "memory": storage.load_memory()}

    def open_note(self, kind):
        path, read, save = self._note(kind)
        with self._lock:
            if not path.exists():
                save(read())
        open_path(path)

    # ---- 첨부 파일 ----

    def upload_attachment(self, attach_id, name, offset, data_b64, last):
        """화면이 파일을 조각으로 나눠 보낸다. 마지막 조각이면 첨부 정보를 돌려준다."""
        try:
            item = attachments.upload_chunk(attach_id, name, int(offset), data_b64, bool(last))
        except (attachments.AttachmentError, ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "attachment": item}

    def discard_attachment(self, attach_id):
        """보내기 전에 뺀 첨부 파일을 지운다(이미 메시지에 붙은 파일은 지우지 않는다)."""
        try:
            if (storage.attachment_dir(attach_id) / storage.STAGED_MARK).exists():
                storage.delete_attachment(attach_id)
        except ValueError:
            pass

    def attachment_preview(self, attach_id):
        try:
            return attachments.preview(attach_id)
        except (ValueError, OSError):
            return None

    def open_attachment(self, attach_id):
        path = storage.attachment_file(attach_id)
        if path:
            open_path(path)

    # ---- MCP ----

    def get_mcp(self):
        status = self._mcp.status(self._config, self._workspace())
        policies = self._config.get("mcp_policy") or {}
        for server in status["servers"]:
            server["policy"] = (policies.get(server["name"]) or {}).get("mode", "")
        return status

    def connect_mcp(self):
        """켜진 MCP 서버를 지금 연결해 본다(MCP 창의 '연결' 버튼)."""
        self._mcp.ensure(self._config, self._workspace())
        return self.get_mcp()

    def set_mcp_enabled(self, name, enabled):
        name = str(name)
        with self._lock:
            # 추천 서버는 기본이 꺼짐이라 켠 것을, 나머지는 기본이 켜짐이라 끈 것을 기록한다
            key, on = ("mcp_enabled", enabled) if name in mcp_client.preset_servers() else ("mcp_disabled", not enabled)
            names = set(self._config.get(key, []))
            (names.add if on else names.discard)(name)
            self._config[key] = sorted(names)
            storage.save_config(self._config)
        return self.get_mcp()

    def open_mcp_config(self):
        open_path(mcp_client.ensure_config_file())

    # ---- 업데이트 ----

    def check_for_updates(self, manual=False):
        """GitHub Releases의 최신 버전. 시작할 때(manual=False)는 설정을 따르고 6시간에 한 번만, 건너뛴 버전은 알리지 않는다."""
        if not manual and (not self._config.get("update_check", True)
                           or time.time() - self._config.get("update_checked_at", 0) < UPDATE_INTERVAL):
            return {"available": False, "skipped": True}
        try:
            result = updates.check(APP_VERSION)
        except updates.UpdateError as e:
            return {"available": False, "error": str(e)}
        with self._lock:
            self._config["update_checked_at"] = time.time()
            storage.save_config(self._config)
        if not manual and result["version"] == self._config.get("update_skip"):
            result["available"] = False
        result["can_install"] = bool(result["asset"]) and self._can_self_update()
        result["current"] = APP_VERSION
        return result

    @staticmethod
    def _can_self_update():
        platform = updates.current_platform()
        if platform == "windows":
            return bool(getattr(sys, "frozen", False))  # 소스로 실행 중이면 설치 프로그램으로 바꿀 것이 없다
        return platform in ("macos", "android")

    def skip_update(self, version):
        with self._lock:
            self._config["update_skip"] = str(version)
            storage.save_config(self._config)

    def open_release_page(self):
        import webbrowser
        webbrowser.open(updates.RELEASES_PAGE)

    def download_update(self):
        """새 버전을 내려받아 설치를 시작한다. 진행은 {"type": "update"} 이벤트로 알린다."""
        if self._updating:
            return {"ok": False, "error": "이미 업데이트를 내려받고 있습니다."}
        if not self._can_self_update():
            return {"ok": False, "error": "이 실행 방식에서는 자동으로 설치할 수 없습니다. Releases 페이지에서 받으세요."}
        self._updating = True
        threading.Thread(target=self._update_work, daemon=True).start()
        return {"ok": True}

    def _update_work(self):
        last = [0.0]

        def progress(done, total):
            if time.monotonic() - last[0] >= 0.25 or done == total:
                last[0] = time.monotonic()
                self._push({"type": "update", "kind": "progress", "done": done, "total": total})

        try:
            path, version = updates.download(APP_VERSION, storage.APP_DIR / "updates", on_progress=progress)
            platform = updates.current_platform()
            if platform == "windows":
                # 설치 프로그램은 앱이 실행 중이면 설치하지 않는다. 같은 폴더에 설치하도록 열고 앱을 닫는다.
                install_dir = Path(sys.executable).resolve().parent
                subprocess.Popen([str(path), f"--dir={install_dir}"], cwd=str(path.parent))
                self._push({"type": "update", "kind": "installing", "version": version,
                            "message": "설치 프로그램을 열었습니다. 앱을 닫으니 설치 프로그램에서 '설치'를 누르세요."})
                threading.Timer(2.0, self._close_for_update).start()
            else:
                open_path(path)
                message = ("Android 설치 화면에서 업데이트를 승인하세요." if platform == "android" else
                           "디스크 이미지를 열었습니다. 앱을 끝낸 뒤 POSTECH GenAI Chat을 응용 프로그램 폴더로 끌어다 놓아 바꾸세요.")
                self._push({"type": "update", "kind": "opened", "version": version, "message": message})
        except (updates.UpdateError, OSError) as e:
            self._push({"type": "update", "kind": "error", "error": str(e)})
        finally:
            self._updating = False

    def _close_for_update(self):
        try:
            self._window.destroy()
        except Exception:
            os._exit(0)

    # ---- 크레딧 ----

    def get_credit(self):
        """POSTECH GenAI의 이번 주기 크레딧 사용량. 크레딧을 쓰지 않는 요청으로 확인한다."""
        key = self._api_key()
        if not key:
            return {"ok": False, "error": "API 키를 먼저 입력하세요."}
        url = self._config.get("chat_completions_url") or api.DEFAULT_CHAT_COMPLETIONS_URL
        if urlparse(url).hostname != urlparse(api.DEFAULT_CHAT_COMPLETIONS_URL).hostname:
            url = api.DEFAULT_CHAT_COMPLETIONS_URL  # 다른 OpenAI 호환 서버를 쓰더라도 크레딧은 POSTECH에 묻는다
        try:
            return {"ok": True, **api.credit(key, url)}
        except ApiError as e:
            return {"ok": False, "error": str(e)}

    # ---- PO노트 ----

    def _po_push(self, kind, **data):
        self._push({"type": "po", "kind": kind, **data})

    def po_state(self):
        ok, reason = stt.available()
        session = self._po_session
        return {
            "available": ok, "reason": reason,
            "engine": self._config.get("po_engine", "auto"),
            "model": self._config.get("po_model", stt.DEFAULT_MODEL),
            "language": self._config.get("po_language", "ko"),
            "device": self._config.get("po_device", ""),
            "reserve": self._po_reserve(),
            "models": stt.models_status() if ok else [],
            "languages": stt.LANGUAGES,
            "has_key": bool(self._api_key()),
            "recording": {"note_id": self._po_note, "elapsed": session.elapsed if session else 0,
                          "engine": self._po_label if session else "", "stopping": self._po_stopping}
            if self._po_note else None,
            "download": self._po_download,
            "generating": self._po_generating,
            "credit": self._credit,
        }

    def po_devices(self):
        if not stt.available()[0]:
            return []
        try:
            return stt.input_devices()
        except Exception:
            return []

    def po_save_settings(self, settings):
        with self._lock:
            before = self._sync_settings()
            if settings.get("engine") in ("auto", "local", "server"):
                self._config["po_engine"] = settings["engine"]
            if settings.get("model") in stt.LOCAL_MODELS:
                self._config["po_model"] = settings["model"]
            if settings.get("language") in stt.LANGUAGES:
                self._config["po_language"] = settings["language"]
            if "device" in settings:
                self._config["po_device"] = settings["device"] if isinstance(settings["device"], int) else ""
            if settings.get("reserve") in PO_RESERVES:
                self._config["po_reserve"] = settings["reserve"]
            self._stamp_settings(before)
            storage.save_config(self._config)
        return self.po_state()

    def po_download_model(self, key):
        if key not in stt.LOCAL_MODELS:
            return {"ok": False, "error": "알 수 없는 모델입니다."}
        if self._po_download:
            return {"ok": False, "error": "이미 모델을 내려받고 있습니다."}
        self._po_download = {"key": key, "done": 0, "total": 0}
        self._po_cancel_download.clear()
        threading.Thread(target=self._po_download_work, args=(key,), daemon=True).start()
        return {"ok": True}

    def _po_download_work(self, key):
        last = [0.0]

        def progress(done, total):
            self._po_download = {"key": key, "done": done, "total": total}
            if time.monotonic() - last[0] >= 0.25:
                last[0] = time.monotonic()
                self._po_push("download", **self._po_download)

        try:
            stt.download(key, progress, self._po_cancel_download.is_set)
            self._po_download = None
            self._po_push("download_done", key=key, state=self.po_state())
        except stt.SttError as e:
            self._po_download = None
            self._po_push("download_error", key=key, error=str(e))

    def po_cancel_download(self):
        self._po_cancel_download.set()

    def po_delete_model(self, key):
        if self._po_session and getattr(self._po_session.engine, "key", None) == key:
            return {"ok": False, "error": "녹음에 쓰고 있는 모델은 지울 수 없습니다."}
        stt.delete_model(key)
        return {"ok": True, "state": self.po_state()}

    def _po_call(self, fn, *args):
        try:
            return {"ok": True, "result": fn(*args)}
        except (po_note.NoteError, OSError, ValueError) as e:
            return {"ok": False, "error": str(e)}

    def po_list(self):
        return po_note.list_notes()

    def po_create(self, title=None):
        return self._po_call(po_note.create, title)

    def po_load(self, note_id):
        return self._po_call(po_note.load, note_id)

    def po_rename(self, note_id, title):
        return self._po_call(po_note.rename, note_id, title)

    def po_delete(self, note_id):
        if note_id in (self._po_note, self._po_generating):
            return {"ok": False, "error": "녹음하거나 노트를 만드는 중인 강의는 지울 수 없습니다."}
        return self._po_call(po_note.delete, note_id)

    def po_save_note(self, note_id, text):
        return self._po_call(po_note.save_note, note_id, text)

    def po_save_memo(self, note_id, text):
        return self._po_call(po_note.save_memo, note_id, text)

    def po_upload_material(self, note_id, upload_id, name, offset, data_b64, last):
        return self._po_call(po_note.upload_material, note_id, upload_id, name, int(offset), data_b64, bool(last))

    def po_remove_material(self, note_id, material_id):
        return self._po_call(po_note.remove_material, note_id, material_id)

    def po_material_text(self, note_id, material_id):
        return self._po_call(po_note.material_text, note_id, material_id)

    def po_open_material(self, note_id, material_id):
        result = self._po_call(po_note.material_path, note_id, material_id)
        if result["ok"]:
            open_path(result["result"])
        return result

    def po_open_folder(self, note_id):
        result = self._po_call(po_note.export_files, note_id)
        if result["ok"]:
            open_path(result["result"])
        return result

    def _po_reserve(self):
        reserve = self._config.get("po_reserve", 30)
        return reserve if reserve in PO_RESERVES else 30

    def _po_budget_ok(self):
        """크레딧 예산 보호: 이번 주 남은 크레딧이 한도의 po_reserve% 아래면 서버를 쓰지 않는다."""
        reserve, c = self._po_reserve(), self._credit
        if not reserve or not c or not c.get("limit") or c.get("usage") is None:
            return True
        return c["limit"] - c["usage"] >= c["limit"] * reserve / 100

    def _po_engines(self, note_id):
        """{"engine", "fallback", "refiner", "label", "notice"}.

        auto: 로컬 모델이 있고 API 키가 있으면 하이브리드(로컬로 바로 받아 적고 불확실한 구간만 서버가 보정),
              모델이 없으면 이번에는 서버로 받아 적으면서 모델을 내려받기 시작한다. 키가 없으면 로컬만.
        server: 서버로 모두 받아 적고, 실패하거나 예산 아래면 로컬(있으면)로. local: 로컬만.
        """
        choice = self._config.get("po_engine", "auto")
        language = self._config.get("po_language", "ko")
        model = self._config.get("po_model", stt.DEFAULT_MODEL)
        key = self._api_key()
        local = stt.LocalEngine(model, language) if stt.model_installed(model) else None
        server = None
        if key and choice != "local":
            url = self._config.get("chat_completions_url") or api.DEFAULT_CHAT_COMPLETIONS_URL
            server = stt.ServerEngine(key, url, language, hint=po_note.vocabulary(note_id))
        if choice == "local" or (choice == "auto" and server is None):
            if local is None:
                raise stt.SttError("로컬 음성 인식 모델을 먼저 내려받으세요(PO노트 → 음성 인식 설정)."
                                   + ("" if key else " API 키가 있으면 POSTECH 서버로도 받아 적을 수 있습니다."))
            return {"engine": local, "fallback": None, "refiner": None, "label": local.label, "notice": ""}
        if server is None:
            raise stt.SttError("POSTECH 서버 음성 인식에는 API 키가 필요합니다. 설정에서 키를 입력하세요.")
        if choice == "auto" and local is not None:
            return {"engine": local, "fallback": None, "refiner": server,
                    "label": f"{local.label} + POSTECH 보정", "notice": ""}
        notice = ""
        if choice == "auto" and not self._po_download:
            self.po_download_model(model)  # 다음 녹음부터 하이브리드로 크레딧을 아낀다
            notice = "로컬 AI 모델을 내려받는 동안 이번 녹음은 POSTECH 서버로 받아 적습니다."
        return {"engine": server, "fallback": local, "refiner": None, "label": server.label, "notice": notice}

    def po_start(self, note_id):
        ok, reason = stt.available()
        if not ok:
            return {"ok": False, "error": reason}
        if self._po_note:
            return {"ok": False, "error": "이미 녹음하고 있습니다."}
        try:
            meta = po_note.touch(note_id)
            if not stt.vad_installed():
                self._po_push("status", note_id=note_id, text="음성 구간 검출 모델(약 2MB)을 내려받는 중…")
                stt.download(None)
            engines = self._po_engines(note_id)
            if engines["refiner"] or isinstance(engines["engine"], stt.ServerEngine):
                try:
                    api.credit(self._api_key(), self._config.get("chat_completions_url") or None)  # 예산 판단용(무료)
                except ApiError:
                    pass
        except (po_note.NoteError, stt.SttError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # 모델 파일이 깨졌거나 라이브러리를 불러오지 못했다
            return {"ok": False, "error": f"음성 인식을 시작하지 못했습니다: {type(e).__name__}: {e}"}
        last_error = [0.0]

        def on_segment(segment):
            try:
                po_note.append_segment(note_id, segment)
            except (po_note.NoteError, OSError):
                return
            self._po_push("segment", note_id=note_id, segment=segment)

        def on_refine(ids, fixed):
            try:
                items = po_note.apply_refinement(note_id, ids, fixed)
            except (po_note.NoteError, OSError):
                return
            self._po_push("transcript", note_id=note_id, transcript=items)

        def on_level(level, speaking):
            session = self._po_session
            self._po_push("level", note_id=note_id, level=round(level, 3), speaking=bool(speaking),
                          elapsed=round(meta.get("duration", 0) + (session.elapsed if session else 0), 1))

        def on_error(message):
            if time.monotonic() - last_error[0] >= 10:  # 같은 오류로 화면을 덮지 않는다
                last_error[0] = time.monotonic()
                self._po_push("error", note_id=note_id, error=message)

        device = self._config.get("po_device", "")
        session = stt.LiveSession(engines["engine"], on_segment, on_level, on_error,
                                  device=device if device != "" else None, offset=meta.get("duration", 0),
                                  fallback=engines["fallback"], refiner=engines["refiner"], on_refine=on_refine,
                                  budget_ok=self._po_budget_ok, id_base=po_note.next_segment_id(note_id))
        try:
            session.start()
        except stt.SttError as e:
            return {"ok": False, "error": str(e)}
        self._po_session, self._po_note, self._po_stopping = session, note_id, False
        self._po_label = engines["label"]
        po_note.touch(note_id, engine=engines["label"])
        return {"ok": True, "engine": engines["label"], "notice": engines["notice"], "state": self.po_state()}

    def po_stop(self):
        """녹음을 멈춘다. 남은 말 구간을 인식하는 동안 기다리지 않도록 백그라운드에서 마무리한다."""
        session, note_id = self._po_session, self._po_note
        if session is None or self._po_stopping:
            return {"ok": True}
        self._po_stopping = True
        self._po_push("stopping", note_id=note_id)

        def finish():
            elapsed = session.elapsed
            session.stop()
            try:
                meta = po_note._meta(note_id)
                po_note.touch(note_id, duration=round(meta.get("duration", 0) + elapsed, 1))
            except po_note.NoteError:
                pass
            self._po_session, self._po_note, self._po_stopping = None, None, False
            self._po_push("stopped", note_id=note_id)

        threading.Thread(target=finish, daemon=True).start()
        return {"ok": True}

    def _po_shutdown(self):
        """창을 닫을 때: 녹음을 멈추고 녹음 길이를 저장한다."""
        session, note_id = self._po_session, self._po_note
        if session is not None:
            elapsed = session.elapsed
            session.stop(timeout=20)
            try:
                po_note.touch(note_id, duration=round(po_note._meta(note_id).get("duration", 0) + elapsed, 1))
            except po_note.NoteError:
                pass
        self._po_cancel_download.set()

    def po_generate(self, note_id, model=None):
        """강의 자료·전사·메모로 필기 노트(note.md)를 만든다. 진행은 po 이벤트로 알린다."""
        key = self._api_key()
        if not key:
            return {"ok": False, "error": "API 키를 먼저 입력하세요."}
        if self._po_generating:
            return {"ok": False, "error": "다른 노트를 만들고 있습니다. 끝난 뒤 다시 시도하세요."}
        try:
            po_note.build_prompts(note_id)
        except po_note.NoteError as e:
            return {"ok": False, "error": str(e)}
        settings = ApiSettings.from_config(self._config)
        allowed = self._model_ids(settings.mode)
        if model in allowed:
            settings.model = model
        elif settings.model not in allowed:
            settings.model = self._default_model()
        self._po_generating = note_id
        threading.Thread(target=self._po_generate_work, args=(note_id, key, settings), daemon=True).start()
        return {"ok": True, "model": settings.model}

    def _po_generate_work(self, note_id, key, settings):
        last = [0.0]

        def on_delta(text):
            if time.monotonic() - last[0] >= 0.1:
                last[0] = time.monotonic()
                self._po_push("note_delta", note_id=note_id, text=text)

        def ask(prompt, delta):
            return api.ask(key, prompt, timeout=600, settings=settings, on_delta=delta)

        try:
            text = po_note.generate(note_id, ask,
                                    on_status=lambda label: self._po_push("note_status", note_id=note_id, text=label),
                                    on_delta=on_delta)
            self._po_push("note_done", note_id=note_id, note=text)
        except (ApiError, po_note.NoteError, OSError) as e:
            self._po_push("note_error", note_id=note_id, error=str(e))
        finally:
            self._po_generating = None

    # ---- 대화 실행 ----

    def send(self, thread_id, text, agent_mode, attachment_ids=None):
        text = (text or "").strip()
        attachment_ids = [str(a) for a in attachment_ids or []]
        if not text and not attachment_ids:
            return {"ok": False, "error": "메시지가 비어 있습니다."}
        if self._busy:
            return {"ok": False, "error": "이전 응답을 기다리는 중입니다."}
        workspace = self._workspace()
        task, forced, command = text or "첨부한 파일을 살펴보고 내용을 알려 주세요.", None, None

        if text.startswith("/"):
            cmd, _, rest = text[1:].partition(" ")
            cmd, rest = cmd.lower(), rest.strip()
            if cmd == "user":
                command, task = "profile", rest
            elif cmd == "init":
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
            try:
                attached = attachments.commit(attachment_ids)
            except (attachments.AttachmentError, ValueError) as e:
                return {"ok": False, "error": str(e)}
            history = list(thread["messages"])
            if not history and thread["title"] == "새 대화":
                thread["title"] = (text.splitlines()[0] if text else attached[0]["name"])[:40]
            msg = storage.make_message("user", text, **({"attachments": attached} if attached else {}))
            thread["messages"].append(msg)
            storage.save_thread(thread)
            self._busy = True
            self._run_id += 1
            run_id = self._run_id
            self._cancel.clear()
            self._session_allow.clear()  # 1.10: "이번 실행 동안 모두 허용"은 실행이 끝나면 사라진다

        threading.Thread(target=self._work, daemon=True,
                         args=(run_id, thread_id, history, task, bool(agent_mode), forced, api_key, workspace,
                               attached, command)).start()
        return {"ok": True, "message": msg, "title": thread["title"]}

    def _work(self, run_id, thread_id, history, task, agent_mode, forced, api_key, workspace, attached=(), command=None):
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

        def save_ai_memory_state(state):
            with self._lock:
                thread = storage.load_thread(thread_id)
                if thread is not None:
                    thread["ai_memory"] = state
                    storage.save_thread(thread)

        thread = storage.load_thread(thread_id) or {}
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
            api_settings=self._thread_api_settings(thread),
            on_delta=on_delta,
            ai_memory_state=thread.get("ai_memory"),
            on_ai_memory_state=save_ai_memory_state,
            policy=connectors.Policy(dict(self._config)),
        )
        try:
            if command == "profile":
                answer = agent.update_profile(task, attached)
            else:
                answer = agent.run(history, task, forced, attached)
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
            self._sync_schedule(20)  # 대화가 끝나면 잠시 뒤 동기화(켰을 때만)

    def _thread_api_settings(self, thread):
        settings = ApiSettings.from_config(self._config)
        model = thread.get("model")
        allowed = self._models(settings.mode)
        if model in {model_id for model_id, _ in allowed}:
            settings.model = model
        elif settings.model not in {model_id for model_id, _ in allowed}:
            settings.model = allowed[0][0]
        return settings

    def _confirm(self, thread_id, kind, title, detail, alive):
        """kind: edit(파일 수정)·run(명령·외부 도구)·write(커넥터 쓰기)는 설정으로 자동 허용할 수 있고,
        send(전송)·destructive(삭제)·exec(코드 실행)는 설정과 관계없이 매번 묻는다."""
        permission = self._config.get("permission", "ask")
        always_ask = kind in connectors.ALWAYS_ASK
        if not always_ask and (permission == "auto_all" or (permission == "auto_edit" and kind == "edit")
                               or kind in self._session_allow):
            return True
        if not alive():
            return False
        cid = uuid.uuid4().hex
        entry = [threading.Event(), "deny"]
        self._pending[cid] = entry
        self._push({"type": "confirm", "id": cid, "thread_id": thread_id, "kind": kind, "title": title, "detail": detail,
                    "allow_session": not always_ask})
        entry[0].wait()
        self._pending.pop(cid, None)
        if entry[1] == "always":
            if not always_ask:
                self._session_allow.add(kind)
            return alive()
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
    lines = [f"version: {APP_VERSION}",
             f"web: {(resource_dir() / 'web' / 'index.html').exists()}",
             f"skills: {len(discover_skills(config.get('workspace', '')))}"]
    try:
        import docx, olefile, openpyxl, pptx, pypdf  # noqa: F401,E401  문서 라이브러리가 함께 묶였는지
        lines.append("documents: OK")
    except ImportError as e:
        lines.append(f"documents: FAIL {e}")
    lines.append(f"attachments: {attachments.selfcheck()}")
    import secret_store
    lines.append(f"secrets: {secret_store.backend_name()}")
    lines.append(f"stt: {stt.selfcheck()}")
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
    _extend_mac_path()
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
        bridge._po_shutdown()
        bridge._mcp.shutdown()


if __name__ == "__main__":
    main()
