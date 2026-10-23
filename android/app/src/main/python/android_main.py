# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""안드로이드 앱(Chaquopy)에서 데스크톱 앱의 Python 코드(main.Bridge, agent, MCP 등)를 그대로 쓰기 위한 연결.

pywebview가 하던 일을 Kotlin(MainActivity)이 대신한다.
- JS → Python: 화면의 window.pywebview.api.<메서드>(...) 호출을 Kotlin이 call(메서드, 인자 JSON)로 넘긴다.
- Python → JS: Bridge가 창의 evaluate_js를 부르면 host.evalJs로 WebView에 실행한다.
- 폴더 고르기·파일 열기(os.startfile)는 host.pickFolder / host.openPath로 안드로이드 화면을 띄운다.

host는 Kotlin 객체이며 evalJs(str), pickFolder() -> str | None, openPath(str) 메서드가 있다.
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

_bridge = None
_host = None


class _Window:
    """pywebview 창 대신 Bridge가 쓰는 객체."""

    def evaluate_js(self, script):
        _host.evalJs(script)

    def create_file_dialog(self, dialog_type, directory=None):
        path = _host.pickFolder()
        return [str(path)] if path else None


def _setup(files_dir, res_dir):
    """데스크톱 코드를 import하기 전에 안드로이드 환경에 맞춘다."""
    os.environ["APPDATA"] = str(files_dir)  # storage.APP_DIR = <files>/PostechChat
    sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))
    import agent
    import mcp_client

    agent.SHELL = "/system/bin/sh"
    agent.ACTION_DOCS = agent.ACTION_DOCS.replace(f"({agent.SHELL_NAME},", "(Android sh,")
    agent.resource_dir = lambda: Path(res_dir)  # 내장 스킬(<res>/skills)
    mcp_client.INPROCESS_BUILTIN = True  # 하위 프로세스 대신 앱 안의 스레드로 내장 MCP 서버를 돌린다


def start(host, files_dir, res_dir):
    global _bridge, _host
    _host = host
    if _bridge is not None:
        return  # 프로세스가 살아 있는 채로 화면만 다시 열렸다: 대화·MCP 상태를 그대로 쓰고 host만 바꾼다
    _setup(files_dir, res_dir)
    import main

    os.startfile = lambda path: _host.openPath(str(path))  # 스킬·데이터 폴더·mcp.json 열기
    _bridge = main.Bridge()
    _bridge._window = _Window()


def call(method, args_json):
    """JS의 api.<method>(...args)를 실행하고 결과를 JSON 문자열로 돌려준다."""
    if not method or method.startswith("_") or not callable(getattr(_bridge, method, None)):
        raise AttributeError(f"알 수 없는 API: {method}")
    result = getattr(_bridge, method)(*json.loads(args_json or "[]"))
    return json.dumps(result, ensure_ascii=False)


def shutdown():
    if _bridge is not None:
        _bridge._mcp.shutdown()


def selftest(files_dir, res_dir):
    """설치된 앱이 제대로 묶였는지 확인한다(계측 테스트에서 부른다). 결과는 JSON 문자열."""
    _setup(files_dir, res_dir)
    import agent
    import attachments
    import documents
    import mcp_client
    from version import APP_VERSION

    report = {"version": APP_VERSION, "skills": sorted(agent.discover_skills("").keys()),
              "attachments": attachments.selfcheck()}
    try:
        import docx, olefile, openpyxl, pptx, pypdf  # noqa: F401,E401
        report["documents"] = "OK"
    except ImportError as e:
        report["documents"] = f"FAIL {e}"
    manager = mcp_client.Manager()
    with tempfile.TemporaryDirectory() as ws:
        try:
            servers = manager.ensure({}, ws)
            report["mcp"] = {s.name: len(s.tools) for s in servers}
            if "word" in report["mcp"]:
                text, is_error = manager.get("word").call("create_document", {"path": "t.docx", "markdown": "# 제목\n- 항목"})
                report["word_create"] = "FAIL " + text if is_error else "OK"
                report["word_read"] = documents.extract_text(Path(ws) / "t.docx")
        finally:
            manager.shutdown()
    report["po_note"] = _po_note_check()
    report.update(_v110_check())
    return json.dumps(report, ensure_ascii=False)


def _v110_check():
    """1.10: 커넥터 서버(스레드)·연구 인덱스(trigram)·동기화 암호화가 안드로이드 묶음에서 되는지."""
    import connectors
    import mcp_client
    import rag
    import sync

    out = {"crypto": sync.selfcheck()}
    check = {"features": {k: True for k in connectors.FEATURES},
             "connectors": {c: {"enabled": True} for c in ("github", "research", "memory", "python", "ssh")}}
    manager = mcp_client.Manager()
    with tempfile.TemporaryDirectory() as ws:
        out["rag"] = rag.selfcheck(ws).split(" ")[0]
        out["rag_mode"] = rag.fts_mode()
        try:
            out["connectors"] = {s.name: len(s.tools) for s in manager.ensure(check, ws)
                                 if s.name in ("github", "research", "memory", "python", "ssh")}
        finally:
            manager.shutdown()
    return out


def _po_note_check():
    """PO노트: 노트를 만들고 강의 자료를 올려 노트 프롬프트까지 만들 수 있는지. 녹음은 휴대폰에서 꺼져 있어야 한다."""
    import base64
    import uuid
    import po_note
    import stt
    try:
        note = po_note.create("selftest")
        po_note.upload_material(note["id"], uuid.uuid4().hex, "slides.md", 0,
                                base64.b64encode("# 베이즈 정리".encode()).decode(), True)
        po_note.append_segment(note["id"], {"start": 0, "end": 1, "text": "오늘은 베이즈 정리"})
        ok = "베이즈 정리" in po_note.build_prompts(note["id"])[0][0][1]
        po_note.delete(note["id"])
        return "OK" if ok and not stt.available()[0] else "FAIL"
    except Exception as e:
        return f"FAIL {type(e).__name__}: {e}"
