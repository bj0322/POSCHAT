"""테스트 도우미: 데이터 폴더를 임시 폴더로 바꾸고, 내장 서버의 HTTP 호출을 가짜 응답으로 바꾼다."""
import contextlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import connectors
import po_note
import secret_store
import storage


@contextlib.contextmanager
def isolated_app_dir(root=None):
    """storage·secret_store·connectors가 쓰는 경로를 모두 임시 폴더로. keyring 대신 파일 저장소를 쓴다.
    root를 주면 그 폴더를 쓰고 지우지 않는다(여러 번 들어갔다 나오는 '기기' 흉내)."""
    with (contextlib.nullcontext(str(root)) if root else tempfile.TemporaryDirectory()) as tmp:
        root = Path(tmp)
        patches = [
            patch.object(storage, "APP_DIR", root),
            patch.object(storage, "CONFIG_PATH", root / "config.json"),
            patch.object(storage, "THREADS_DIR", root / "threads"),
            patch.object(storage, "MEMORY_PATH", root / "memory.md"),
            patch.object(storage, "PROFILE_PATH", root / "USER.md"),
            patch.object(storage, "MCP_PATH", root / "mcp.json"),
            patch.object(storage, "USER_SKILLS_DIR", root / "skills"),
            patch.object(storage, "ATTACH_DIR", root / "attachments"),
            patch.object(storage, "USAGE_PATH", root / "usage.json"),
            patch.object(storage, "OLD_MEMORY_PATH", root / "memory.json"),
            patch.object(secret_store, "SECRETS_PATH", root / "secrets.json"),
            patch.object(secret_store, "_keyring", False),
            patch.object(po_note, "NOTES_DIR", root / "po_notes"),
            patch.object(connectors, "LOG_DIR", root / "logs"),
            patch.object(connectors, "AUDIT_PATH", root / "logs" / "tool_calls.jsonl"),
        ]
        for p in patches:
            p.start()
        connectors._health.clear()
        (root / "threads").mkdir(exist_ok=True)
        try:
            yield root
        finally:
            for p in reversed(patches):
                p.stop()
            connectors._health.clear()


class FakeResponse:
    def __init__(self, status=200, data=None, text=None, headers=None, content=None):
        self.status_code = status
        self.headers = headers or {}
        if content is not None:
            self.content = content
            self.text = content.decode("utf-8", errors="replace")
        elif text is not None:
            self.text, self.content = text, text.encode("utf-8")
        else:
            self.text = json.dumps(data if data is not None else {})
            self.content = self.text.encode("utf-8") if data is not None else b""
        self._data = data

    def json(self):
        if self._data is None:
            return json.loads(self.text)
        return self._data


class FakeHttp:
    """routes: [(메서드, URL 일부, 응답 또는 (요청) -> 응답)]. 맞는 첫 경로를 쓴다. 받은 요청은 calls에 남긴다."""

    def __init__(self, routes):
        self.routes = list(routes)
        self.calls = []

    def __call__(self, method, url, timeout=30, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        for m, part, response in self.routes:
            if m == method and part in url:
                return response(self.calls[-1]) if callable(response) else response
        raise AssertionError(f"예상하지 못한 요청: {method} {url}")


@contextlib.contextmanager
def preserved_hooks():
    """Bridge()가 바꾸는 모듈 전역 훅(api.on_usage 등)을 테스트가 끝나면 되돌린다."""
    import api
    import telemetry

    saved = (api.on_usage, api.on_credit, api.on_trace, connectors.on_event, telemetry.config_getter)
    try:
        yield
    finally:
        api.on_usage, api.on_credit, api.on_trace, connectors.on_event, telemetry.config_getter = saved
