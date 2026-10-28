# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""내장 MCP 서버 gdrive·gdocs·gsheets·gslides·gmail·gcalendar: Google 공식 REST API(커넥터 → Google Workspace).

서비스마다 커넥터가 따로 있고 OAuth 토큰도 따로 받는다(필요한 scope만 요청, 하나를 끊어도 나머지는 그대로).
토큰은 connectors.credential(<커넥터>)로 읽는다(만료 전 자동 갱신). 커넥터 옵션 readonly를 켜면 읽기 scope만
요청하고 쓰기 도구는 거부한다.

Google의 공식 MCP 서버는 이 앱의 stdio 클라이언트로 붙일 수 있는 형태로 제공되지 않아(원격 서버·별도 런타임),
공식 REST API(Drive v3, Docs v1, Sheets v4, Slides v1, Gmail v1, Calendar v3)를 직접 부른다.
Gmail 전송(send_draft)은 받는 사람·제목을 인자로 다시 받아 초안과 맞는지 확인한 뒤에만 보낸다.
그래서 승인 창에 실제 받는 사람과 제목이 보인다.
"""
import base64
import datetime as dt
import email.message
import email.utils
import html
import json
import re
import tempfile
import time
import uuid
from pathlib import Path

import connectors
import oauth
import storage
from office_mcp import BOOL, INT, READ_ONLY, STR, _root, _schema
from net import ToolFailure, http

DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DOCS = "https://docs.googleapis.com/v1/documents"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SLIDES = "https://slides.googleapis.com/v1/presentations"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3"
TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
DEFAULT_CHARS = 15000
MAX_DOWNLOAD = 20 * 1024 * 1024
WRITES_REMOTE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
CHANGES_STATE = storage.APP_DIR / "connectors" / "gdrive_changes.json"
MIME = {
    "doc": "application/vnd.google-apps.document", "sheet": "application/vnd.google-apps.spreadsheet",
    "slide": "application/vnd.google-apps.presentation", "folder": "application/vnd.google-apps.folder",
    "pdf": "application/pdf",
}
EXPORT = {MIME["doc"]: "text/plain", MIME["sheet"]: "text/csv", MIME["slide"]: "text/plain"}
ID_RE = re.compile(r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_\-]{10,})")


# ---- 공통 ----

def _token(cid):
    try:
        return connectors.credential(cid)
    except oauth.NeedsAuth as e:
        name = connectors.CONNECTORS[cid].name
        raise ToolFailure(f"{connectors.NEEDS_AUTH_TAG} {name}에 로그인되어 있지 않습니다({e}). "
                          f"연결·도구 → 커넥터 → {name}에서 로그인하세요.")
    except oauth.OAuthError as e:
        raise ToolFailure(f"Google 토큰을 갱신하지 못했습니다: {e}")


def _writable(cid):
    if connectors.readonly(storage.load_config(), cid):
        raise ToolFailure(f"{connectors.CONNECTORS[cid].name}는 읽기 전용으로 연결되어 있습니다. "
                          "커넥터 옵션에서 읽기 전용을 끄고 다시 로그인하세요.")


def _api(cid, method, url, params=None, body=None, raw=False, data=None, headers=None, stream=False):
    head = {"Authorization": f"Bearer {_token(cid)}", **(headers or {})}
    for attempt in range(3):
        r = http(method, url, params=params, json=body, data=data, headers=head, timeout=60, stream=stream)
        reason = ""
        if r.status_code in (403, 429):
            try:
                errors = r.json().get("error", {}).get("errors") or [{}]
                reason = errors[0].get("reason", "")
            except (ValueError, AttributeError):
                pass
        transient = r.status_code in (429, 500, 502, 503, 504) or reason in ("rateLimitExceeded", "userRateLimitExceeded")
        if transient and attempt < 2 and method in ("GET", "PATCH", "PUT"):
            time.sleep(min(8.0, float(r.headers.get("Retry-After") or 2 * (attempt + 1))))
            continue
        break
    if r.status_code in (200, 201):
        if stream or raw:
            return r
        return r.json() if r.content else {}
    if r.status_code == 204:
        return {}
    try:
        err = r.json().get("error", {})
        message = err.get("message", "") if isinstance(err, dict) else str(err)
        status = err.get("status", "") if isinstance(err, dict) else ""
    except ValueError:
        message, status = r.text[:300], ""
    if r.status_code == 401:
        raise ToolFailure(f"{connectors.NEEDS_AUTH_TAG} Google 인증이 만료되었습니다. 다시 로그인하세요.")
    if r.status_code == 403 and (reason in ("insufficientPermissions", "forbidden") or "scope" in message.lower()
                                 or status == "PERMISSION_DENIED"):
        raise ToolFailure(f"{connectors.SCOPE_TAG} 이 작업에 필요한 권한이 없습니다({message}). "
                          "읽기 전용이 아닌지 확인하고 다시 로그인해 권한을 허용하세요. 다른 사람의 파일이면 공유 권한도 필요합니다.")
    if r.status_code == 403 and "has not been used" in message:
        raise ToolFailure(f"Google Cloud 프로젝트에서 이 API를 사용 설정하지 않았습니다: {message}")
    if r.status_code == 404:
        raise ToolFailure(f"찾지 못했습니다. ID가 맞는지, 이 계정에 접근 권한이 있는지 확인하세요. ({message})")
    raise ToolFailure(f"Google API 요청에 실패했습니다(HTTP {r.status_code}): {message}")


def _id(value, what="ID"):
    text = str(value or "").strip()
    m = ID_RE.search(text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_\-@.]{5,}", text):
        return text
    raise ToolFailure(f"{what}나 Google 주소가 아닙니다: {text}")


def _clip(text, max_chars):
    max_chars = max(1000, min(100000, int(max_chars or DEFAULT_CHARS)))
    return text if len(text) <= max_chars else text[:max_chars] + f"\n\n…({max_chars:,}자에서 잘랐습니다)"


def _limit(value, default=20, hi=100):
    try:
        return max(1, min(hi, int(value or default)))
    except (TypeError, ValueError):
        return default


def _q(text):
    return str(text).replace("\\", "\\\\").replace("'", "\\'")


def _values_arg(values):
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            raise ToolFailure("values는 행 배열(예: [[\"이름\", 1], [\"김\", 2]])이어야 합니다.")
    if not isinstance(values, list) or not all(isinstance(r, list) for r in values):
        raise ToolFailure("values는 행 배열(예: [[\"이름\", 1], [\"김\", 2]])이어야 합니다.")
    return values


def verify(cid, config=None):
    """커넥터 연결 확인: 허용된 scope와(가능하면) 계정 주소."""
    token = _token(cid)
    r = http("GET", TOKENINFO, params={"access_token": token}, timeout=20)
    if r.status_code != 200:
        raise ToolFailure(f"{connectors.NEEDS_AUTH_TAG} Google 토큰을 확인하지 못했습니다(HTTP {r.status_code}).")
    granted = set(str(r.json().get("scope", "")).split())
    wanted = connectors.wanted_scopes(config or storage.load_config(), cid)
    missing = [s for s in wanted if s not in granted]
    if missing:
        raise ToolFailure(f"{connectors.SCOPE_TAG} 허용받지 못한 권한: {', '.join(s.rsplit('/', 1)[-1] for s in missing)}")
    account = ""
    try:
        if cid == "gmail":
            account = _api(cid, "GET", f"{GMAIL}/profile").get("emailAddress", "")
        elif cid == "gdrive":
            account = _api(cid, "GET", f"{DRIVE}/about", {"fields": "user(emailAddress)"})["user"]["emailAddress"]
        elif cid == "gcalendar":
            account = _api(cid, "GET", f"{CALENDAR}/calendars/primary").get("id", "")
    except (ToolFailure, KeyError):
        pass
    return {"account": account, "detail": "권한: " + ", ".join(sorted(s.rsplit("/", 1)[-1] for s in granted))}


# ---- Drive ----

FILE_FIELDS = "id,name,mimeType,modifiedTime,size,webViewLink,parents,owners(displayName)"


def _file_line(i, f):
    kind = {v: k for k, v in MIME.items()}.get(f.get("mimeType"), f.get("mimeType", "").split("/")[-1])
    size = f" {int(f['size']) / 1024:.0f}KB" if f.get("size") else ""
    owner = ", ".join(o.get("displayName", "") for o in f.get("owners") or [])
    return f"{i}. {f.get('name')} [{kind}{size}] 수정 {str(f.get('modifiedTime', ''))[:10]}" + \
        (f" · {owner}" if owner else "") + f"\n   id: {f['id']}"


def drive_search_files(query="", mime_type=None, folder=None, limit=20, raw_query=None):
    terms = ["trashed = false"]
    if raw_query:
        terms.append(f"({raw_query})")
    elif query:
        terms.append(f"(name contains '{_q(query)}' or fullText contains '{_q(query)}')")
    if mime_type:
        terms.append(f"mimeType = '{_q(MIME.get(mime_type, mime_type))}'")
    if folder:
        terms.append(f"'{_q(_id(folder, '폴더 ID'))}' in parents")
    data = _api("gdrive", "GET", f"{DRIVE}/files", {"q": " and ".join(terms), "pageSize": _limit(limit),
                                                    "fields": f"files({FILE_FIELDS})", "orderBy": "modifiedTime desc",
                                                    "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
    files = data.get("files") or []
    if not files:
        return "맞는 파일이 없습니다."
    return f"Drive 파일 {len(files)}개\n\n" + "\n".join(_file_line(i, f) for i, f in enumerate(files, 1))


def drive_get_file(file):
    f = _api("gdrive", "GET", f"{DRIVE}/files/{_id(file, '파일 ID')}", {"fields": FILE_FIELDS + ",description",
                                                                     "supportsAllDrives": "true"})
    return "\n".join(f"{k}: {v}" for k, v in f.items())


def drive_read_file(file, max_chars=DEFAULT_CHARS):
    import documents

    fid = _id(file, "파일 ID")
    meta = _api("gdrive", "GET", f"{DRIVE}/files/{fid}", {"fields": "id,name,mimeType,size", "supportsAllDrives": "true"})
    mime = meta.get("mimeType", "")
    if mime in EXPORT:
        r = _api("gdrive", "GET", f"{DRIVE}/files/{fid}/export", {"mimeType": EXPORT[mime]}, raw=True)
        return f"{meta['name']} ({mime.rsplit('.', 1)[-1]})\n\n" + _clip(r.content.decode("utf-8", errors="replace"), max_chars)
    if mime.startswith("application/vnd.google-apps"):
        raise ToolFailure(f"이 Google 형식({mime})은 글자로 내보낼 수 없습니다.")
    if int(meta.get("size") or 0) > MAX_DOWNLOAD:
        raise ToolFailure("파일이 20MB보다 커서 읽지 않았습니다.")
    r = _api("gdrive", "GET", f"{DRIVE}/files/{fid}", {"alt": "media", "supportsAllDrives": "true"}, raw=True)
    data = r.content
    suffix = Path(meta.get("name", "")).suffix.lower()
    if mime.startswith("text/") or suffix in (".txt", ".md", ".csv", ".json", ".py", ".tex"):
        text = data.decode("utf-8", errors="replace")
    elif suffix in documents.DOCUMENT_EXTS:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / f"file{suffix}"
            p.write_bytes(data)
            try:
                text = documents.extract_text(p)
            except documents.DocumentError as e:
                raise ToolFailure(str(e))
    else:
        raise ToolFailure(f"글자를 뽑을 수 없는 형식입니다({mime}).")
    return f"{meta['name']} ({len(text):,}자)\n\n" + _clip(text, max_chars)


def drive_list_folder(folder="root", limit=50):
    return drive_search_files(folder=folder or "root", limit=limit)


def drive_list_changes(page_token=None, limit=50):
    """변경 사항. page_token이 없으면 지난번에 저장해 둔 기준점부터(처음이면 기준점만 만든다)."""
    state = {}
    try:
        state = json.loads(CHANGES_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        pass
    token = page_token or state.get("page_token")
    if not token:
        token = _api("gdrive", "GET", f"{DRIVE}/changes/startPageToken", {"supportsAllDrives": "true"})["startPageToken"]
        _save_changes_token(token)
        return f"변경 사항 기준점을 만들었습니다(page_token {token}). 다음 호출부터 이후의 변경을 보여 줍니다."
    data = _api("gdrive", "GET", f"{DRIVE}/changes", {"pageToken": token, "pageSize": _limit(limit),
                                                      "fields": f"newStartPageToken,nextPageToken,changes(removed,fileId,time,file({FILE_FIELDS}))",
                                                      "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
    next_token = data.get("nextPageToken") or data.get("newStartPageToken") or token
    _save_changes_token(next_token)
    changes = data.get("changes") or []
    if not changes:
        return "새 변경 사항이 없습니다."
    lines = [f"변경 {len(changes)}건" + (" (더 있음: 다시 호출하세요)" if data.get("nextPageToken") else "")]
    for c in changes:
        f = c.get("file") or {}
        lines.append(f"- {str(c.get('time', ''))[:16]} {'삭제됨' if c.get('removed') else f.get('name', c.get('fileId'))}"
                     f" (id {c.get('fileId')})")
    return "\n".join(lines)


def _save_changes_token(token):
    CHANGES_STATE.parent.mkdir(parents=True, exist_ok=True)
    CHANGES_STATE.write_text(json.dumps({"page_token": token}), encoding="utf-8")


def _multipart(metadata, content, mime):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n").encode("utf-8")
    body += content + f"\r\n--{boundary}--".encode("utf-8")
    return body, {"Content-Type": f"multipart/related; boundary={boundary}"}


def drive_create_folder(name, parent=None):
    _writable("gdrive")
    meta = {"name": str(name), "mimeType": MIME["folder"], **({"parents": [_id(parent, '폴더 ID')]} if parent else {})}
    f = _api("gdrive", "POST", f"{DRIVE}/files", {"fields": FILE_FIELDS, "supportsAllDrives": "true"}, body=meta)
    return f"폴더를 만들었습니다: {f['name']} (id {f['id']})\n{f.get('webViewLink', '')}"


def drive_create_text_file(name, content, parent=None, mime_type="text/plain", convert_to_doc=False):
    _writable("gdrive")
    meta = {"name": str(name), **({"parents": [_id(parent, '폴더 ID')]} if parent else {})}
    if convert_to_doc:
        meta["mimeType"] = MIME["doc"]
    body, headers = _multipart(meta, str(content).encode("utf-8"), mime_type or "text/plain")
    f = _api("gdrive", "POST", UPLOAD, {"uploadType": "multipart", "fields": FILE_FIELDS, "supportsAllDrives": "true"},
             data=body, headers=headers)
    return f"파일을 만들었습니다: {f['name']} (id {f['id']})\n{f.get('webViewLink', '')}"


def drive_upload_file(path, parent=None, name=None, convert=False):
    _writable("gdrive")
    root = _root()
    p = (root / str(path)).resolve()
    if p != root and root not in p.parents:
        raise ToolFailure("작업 폴더 밖의 파일은 올릴 수 없습니다.")
    if not p.is_file():
        raise ToolFailure(f"파일이 없습니다: {path}")
    if p.stat().st_size > MAX_DOWNLOAD:
        raise ToolFailure("20MB보다 큰 파일은 올리지 않습니다.")
    import mimetypes

    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    meta = {"name": str(name or p.name), **({"parents": [_id(parent, '폴더 ID')]} if parent else {})}
    if convert:
        target = {".docx": MIME["doc"], ".doc": MIME["doc"], ".xlsx": MIME["sheet"], ".csv": MIME["sheet"],
                  ".pptx": MIME["slide"]}.get(p.suffix.lower())
        if target:
            meta["mimeType"] = target
    body, headers = _multipart(meta, p.read_bytes(), mime)
    f = _api("gdrive", "POST", UPLOAD, {"uploadType": "multipart", "fields": FILE_FIELDS, "supportsAllDrives": "true"},
             data=body, headers=headers)
    return f"올렸습니다: {f['name']} (id {f['id']})\n{f.get('webViewLink', '')}"


def drive_move_file(file, folder):
    _writable("gdrive")
    fid = _id(file, "파일 ID")
    meta = _api("gdrive", "GET", f"{DRIVE}/files/{fid}", {"fields": "parents,name", "supportsAllDrives": "true"})
    f = _api("gdrive", "PATCH", f"{DRIVE}/files/{fid}", {
        "addParents": _id(folder, "폴더 ID"), "removeParents": ",".join(meta.get("parents") or []),
        "fields": FILE_FIELDS, "supportsAllDrives": "true"}, body={})
    return f"'{f['name']}'을(를) 옮겼습니다. (앱이 만든 파일만 옮길 수 있습니다: drive.file 권한)"


# ---- Docs ----

def _doc_text(doc):
    out = []

    def walk(content):
        for block in content or []:
            if "paragraph" in block:
                para = block["paragraph"]
                text = "".join(e.get("textRun", {}).get("content", "") for e in para.get("elements") or [])
                style = (para.get("paragraphStyle") or {}).get("namedStyleType", "")
                m = re.match(r"HEADING_(\d)", style)
                if m and text.strip():
                    text = "#" * int(m.group(1)) + " " + text
                elif style == "TITLE" and text.strip():
                    text = "# " + text
                if "bullet" in para:
                    text = "- " + text
                out.append(text)
            elif "table" in block:
                for row in block["table"].get("tableRows") or []:
                    cells = []
                    for cell in row.get("tableCells") or []:
                        inner = []
                        for c in cell.get("content") or []:
                            if "paragraph" in c:
                                inner.append("".join(e.get("textRun", {}).get("content", "")
                                                     for e in c["paragraph"].get("elements") or []).strip())
                        cells.append(" ".join(inner))
                    out.append("| " + " | ".join(cells) + " |\n")

    walk((doc.get("body") or {}).get("content"))
    return "".join(out)


def docs_read_document(document, max_chars=DEFAULT_CHARS):
    doc = _api("gdocs", "GET", f"{DOCS}/{_id(document, '문서 ID')}")
    text = _doc_text(doc)
    return f"{doc.get('title')} (id {doc.get('documentId')}, {len(text):,}자)\n\n" + _clip(text, max_chars)


def docs_create_document(title, text=""):
    _writable("gdocs")
    doc = _api("gdocs", "POST", DOCS, body={"title": str(title)})
    if text:
        _api("gdocs", "POST", f"{DOCS}/{doc['documentId']}:batchUpdate",
             body={"requests": [{"insertText": {"location": {"index": 1}, "text": str(text)}}]})
    return f"문서를 만들었습니다: {doc.get('title')} (id {doc['documentId']})\nhttps://docs.google.com/document/d/{doc['documentId']}/edit"


def docs_append_text(document, text):
    _writable("gdocs")
    did = _id(document, "문서 ID")
    doc = _api("gdocs", "GET", f"{DOCS}/{did}")
    end = max(1, int(((doc.get("body") or {}).get("content") or [{}])[-1].get("endIndex", 2)) - 1)
    _api("gdocs", "POST", f"{DOCS}/{did}:batchUpdate",
         body={"requests": [{"insertText": {"location": {"index": end}, "text": "\n" + str(text)}}]})
    return f"'{doc.get('title')}' 끝에 {len(str(text)):,}자를 덧붙였습니다."


def docs_replace_text(document, old, new, match_case=True):
    _writable("gdocs")
    did = _id(document, "문서 ID")
    r = _api("gdocs", "POST", f"{DOCS}/{did}:batchUpdate", body={"requests": [{"replaceAllText": {
        "containsText": {"text": str(old), "matchCase": bool(match_case)}, "replaceText": str(new)}}]})
    count = ((r.get("replies") or [{}])[0].get("replaceAllText") or {}).get("occurrencesChanged", 0)
    return f"{count}곳을 바꿨습니다." if count else "바꿀 글자를 찾지 못했습니다."


# ---- Sheets ----

def sheets_get_info(spreadsheet):
    data = _api("gsheets", "GET", f"{SHEETS}/{_id(spreadsheet, '스프레드시트 ID')}",
                {"fields": "spreadsheetId,properties.title,sheets.properties(title,gridProperties)"})
    lines = [f"{data['properties']['title']} (id {data['spreadsheetId']})"]
    for s in data.get("sheets") or []:
        p = s["properties"]
        grid = p.get("gridProperties") or {}
        lines.append(f"- 시트 '{p['title']}': {grid.get('rowCount', '?')}행 × {grid.get('columnCount', '?')}열")
    return "\n".join(lines)


def sheets_read_values(spreadsheet, range="A1:Z200", max_chars=DEFAULT_CHARS):  # noqa: A002 — API 인자 이름
    sid = _id(spreadsheet, "스프레드시트 ID")
    data = _api("gsheets", "GET", f"{SHEETS}/{sid}/values/{range}", {"valueRenderOption": "FORMATTED_VALUE"})
    rows = data.get("values") or []
    if not rows:
        return f"{data.get('range', range)}: 값이 없습니다."
    text = "\n".join("\t".join(str(c) for c in row) for row in rows)
    return f"{data.get('range')} ({len(rows)}행, 탭으로 구분)\n\n" + _clip(text, max_chars)


def sheets_update_values(spreadsheet, range, values):  # noqa: A002
    _writable("gsheets")
    sid = _id(spreadsheet, "스프레드시트 ID")
    r = _api("gsheets", "PUT", f"{SHEETS}/{sid}/values/{range}", {"valueInputOption": "USER_ENTERED"},
             body={"values": _values_arg(values)})
    return f"{r.get('updatedRange')}에 {r.get('updatedCells', 0)}칸을 썼습니다."


def sheets_append_values(spreadsheet, range, values):  # noqa: A002
    _writable("gsheets")
    sid = _id(spreadsheet, "스프레드시트 ID")
    r = _api("gsheets", "POST", f"{SHEETS}/{sid}/values/{range}:append",
             {"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"}, body={"values": _values_arg(values)})
    return f"{(r.get('updates') or {}).get('updatedRange')}에 {(r.get('updates') or {}).get('updatedRows', 0)}행을 더했습니다."


def sheets_create_spreadsheet(title, sheets=None):
    _writable("gsheets")
    body = {"properties": {"title": str(title)}}
    if sheets:
        names = [sheets] if isinstance(sheets, str) else list(sheets)
        body["sheets"] = [{"properties": {"title": str(n)}} for n in names]
    r = _api("gsheets", "POST", SHEETS, body=body)
    return f"스프레드시트를 만들었습니다: {title} (id {r['spreadsheetId']})\n{r.get('spreadsheetUrl', '')}"


# ---- Slides ----

def _shape_text(element):
    text = []
    for te in ((element.get("shape") or {}).get("text") or {}).get("textElements") or []:
        text.append((te.get("textRun") or {}).get("content", ""))
    return "".join(text).strip()


def slides_read_presentation(presentation, max_chars=DEFAULT_CHARS):
    p = _api("gslides", "GET", f"{SLIDES}/{_id(presentation, '프레젠테이션 ID')}")
    lines = [f"{p.get('title')} (id {p.get('presentationId')}, 슬라이드 {len(p.get('slides') or [])}장)"]
    for i, slide in enumerate(p.get("slides") or [], 1):
        texts = [t for t in (_shape_text(e) for e in slide.get("pageElements") or []) if t]
        notes_page = (slide.get("slideProperties") or {}).get("notesPage") or {}
        notes = [t for t in (_shape_text(e) for e in notes_page.get("pageElements") or []) if t]
        lines.append(f"\n## 슬라이드 {i} (id {slide.get('objectId')})\n" + "\n".join(texts))
        if notes:
            lines.append("[발표자 노트] " + " ".join(notes))
    return _clip("\n".join(lines), max_chars)


def slides_create_presentation(title):
    _writable("gslides")
    p = _api("gslides", "POST", SLIDES, body={"title": str(title)})
    return f"프레젠테이션을 만들었습니다: {title} (id {p['presentationId']})\nhttps://docs.google.com/presentation/d/{p['presentationId']}/edit"


def slides_add_slide(presentation, title="", body="", layout="TITLE_AND_BODY"):
    _writable("gslides")
    pid = _id(presentation, "프레젠테이션 ID")
    slide_id, title_id, body_id = (f"p{uuid.uuid4().hex[:16]}" for _ in range(3))
    layout = layout if layout in ("TITLE_AND_BODY", "TITLE_ONLY", "TITLE", "SECTION_HEADER", "BLANK") else "TITLE_AND_BODY"
    mappings = []
    if layout != "BLANK":
        mappings.append({"layoutPlaceholder": {"type": "CENTERED_TITLE" if layout == "TITLE" else "TITLE"}, "objectId": title_id})
    if layout == "TITLE_AND_BODY":
        mappings.append({"layoutPlaceholder": {"type": "BODY"}, "objectId": body_id})
    requests = [{"createSlide": {"objectId": slide_id, "slideLayoutReference": {"predefinedLayout": layout},
                                 "placeholderIdMappings": mappings}}]
    if title and mappings:
        requests.append({"insertText": {"objectId": title_id, "text": str(title)}})
    if body and layout == "TITLE_AND_BODY":
        text = "\n".join(body) if isinstance(body, list) else str(body)
        requests.append({"insertText": {"objectId": body_id, "text": text}})
    _api("gslides", "POST", f"{SLIDES}/{pid}:batchUpdate", body={"requests": requests})
    return f"슬라이드를 더했습니다(id {slide_id}, {layout})."


def slides_replace_text(presentation, old, new, match_case=True):
    _writable("gslides")
    r = _api("gslides", "POST", f"{SLIDES}/{_id(presentation, '프레젠테이션 ID')}:batchUpdate", body={"requests": [{
        "replaceAllText": {"containsText": {"text": str(old), "matchCase": bool(match_case)}, "replaceText": str(new)}}]})
    count = ((r.get("replies") or [{}])[0].get("replaceAllText") or {}).get("occurrencesChanged", 0)
    return f"{count}곳을 바꿨습니다." if count else "바꿀 글자를 찾지 못했습니다."


# ---- Gmail ----

def _headers(payload):
    return {h["name"].lower(): h["value"] for h in (payload or {}).get("headers") or []}


def _b64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body_text(payload):
    """text/plain을 먼저, 없으면 text/html에서 태그를 뺀 글자."""
    plain, rich = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data))
        elif data and mime == "text/html":
            rich.append(_b64(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    if plain:
        return "\n".join(plain)
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", "\n".join(rich))
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def gmail_search_messages(query="", limit=10):
    data = _api("gmail", "GET", f"{GMAIL}/messages", {"q": str(query or ""), "maxResults": _limit(limit, 10, 50)})
    ids = [m["id"] for m in data.get("messages") or []]
    if not ids:
        return "맞는 메일이 없습니다."
    lines = [f"메일 {len(ids)}개 (검색: {query or '전체'})"]
    for i, mid in enumerate(ids, 1):
        m = _api("gmail", "GET", f"{GMAIL}/messages/{mid}", {"format": "metadata",
                                                             "metadataHeaders": ["From", "To", "Subject", "Date"]})
        h = _headers(m.get("payload"))
        unread = " [안 읽음]" if "UNREAD" in (m.get("labelIds") or []) else ""
        lines.append(f"{i}. {h.get('subject', '(제목 없음)')}{unread}\n   보낸 사람: {h.get('from', '')} · {h.get('date', '')}\n"
                     f"   {(m.get('snippet') or '')[:200]}\n   message_id: {mid}")
    return "\n".join(lines)


def gmail_read_message(message_id, max_chars=DEFAULT_CHARS):
    m = _api("gmail", "GET", f"{GMAIL}/messages/{_id(message_id, '메일 ID')}", {"format": "full"})
    h = _headers(m.get("payload"))
    attachments = []

    def walk(part):
        if part.get("filename"):
            attachments.append(part["filename"])
        for child in part.get("parts") or []:
            walk(child)

    walk(m.get("payload") or {})
    head = [f"제목: {h.get('subject', '')}", f"보낸 사람: {h.get('from', '')}", f"받는 사람: {h.get('to', '')}"]
    if h.get("cc"):
        head.append(f"참조: {h['cc']}")
    head += [f"날짜: {h.get('date', '')}", f"thread_id: {m.get('threadId')}"]
    if attachments:
        head.append("첨부: " + ", ".join(attachments))
    return "\n".join(head) + "\n\n" + _clip(_body_text(m.get("payload")), max_chars)


def gmail_list_drafts(limit=10):
    data = _api("gmail", "GET", f"{GMAIL}/drafts", {"maxResults": _limit(limit, 10, 50)})
    drafts = data.get("drafts") or []
    if not drafts:
        return "초안이 없습니다."
    lines = [f"초안 {len(drafts)}개"]
    for d in drafts:
        full = _api("gmail", "GET", f"{GMAIL}/drafts/{d['id']}", {"format": "metadata"})
        h = _headers((full.get("message") or {}).get("payload"))
        lines.append(f"- draft_id {d['id']}: {h.get('subject', '(제목 없음)')} → {h.get('to', '')}")
    return "\n".join(lines)


def _addresses(value):
    if not value:
        return ""
    items = value if isinstance(value, list) else re.split(r"[,;]", str(value))
    items = [str(a).strip() for a in items if str(a).strip()]
    for a in items:
        if not re.search(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", a):
            raise ToolFailure(f"메일 주소가 아닙니다: {a}")
    return ", ".join(items)


def gmail_create_draft(to, subject, body, cc=None, bcc=None, reply_to_message_id=None):
    _writable("gmail")
    msg = email.message.EmailMessage()
    msg["To"] = _addresses(to)
    if not msg["To"]:
        raise ToolFailure("to(받는 사람)가 비어 있습니다.")
    if cc:
        msg["Cc"] = _addresses(cc)
    if bcc:
        msg["Bcc"] = _addresses(bcc)
    msg["Subject"] = str(subject or "")
    msg.set_content(str(body or ""))
    draft = {"message": {}}
    if reply_to_message_id:
        original = _api("gmail", "GET", f"{GMAIL}/messages/{_id(reply_to_message_id, '메일 ID')}",
                        {"format": "metadata", "metadataHeaders": ["Message-ID", "References", "Subject"]})
        h = _headers(original.get("payload"))
        if h.get("message-id"):
            msg["In-Reply-To"] = h["message-id"]
            msg["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
        draft["message"]["threadId"] = original.get("threadId")
    draft["message"]["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    d = _api("gmail", "POST", f"{GMAIL}/drafts", body=draft)
    return (f"초안을 만들었습니다(draft_id {d['id']}). 받는 사람: {msg['To']} · 제목: {msg['Subject']}\n"
            "보내려면 send_draft에 draft_id와 같은 to·subject를 넘기세요(사용자가 승인해야 보내집니다).")


def gmail_send_draft(draft_id, to, subject):
    _writable("gmail")
    did = _id(draft_id, "초안 ID")
    full = _api("gmail", "GET", f"{GMAIL}/drafts/{did}", {"format": "metadata"})
    h = _headers((full.get("message") or {}).get("payload"))

    def norm(value):
        return sorted(a.lower() for _, a in email.utils.getaddresses([str(value or "")]) if a)

    # 승인 창에 보인 받는 사람·제목이 실제 초안과 같을 때만 보낸다(초안 ID만 바꿔치는 프롬프트 주입 방어)
    if norm(h.get("to")) != norm(_addresses(to)) or (h.get("subject") or "").strip() != str(subject or "").strip():
        raise ToolFailure(f"초안의 받는 사람·제목이 요청과 다릅니다. 초안: {h.get('to')} / {h.get('subject')}. "
                          "gmail.list_drafts로 확인하고 다시 요청하세요.")
    sent = _api("gmail", "POST", f"{GMAIL}/drafts/send", body={"id": did})
    return f"메일을 보냈습니다(message_id {sent.get('id')}): {h.get('subject')} → {h.get('to')}"


# ---- Calendar ----

def _local_tz():
    return dt.datetime.now().astimezone().tzinfo


def _when(value, name):
    """ISO 날짜·시각을 Calendar API의 {date} 또는 {dateTime}으로. 시간대가 없으면 이 기기의 시간대."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d\d-\d\d", text):
        return {"date": text}
    try:
        t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ToolFailure(f"{name}는 ISO 형식(예: 2026-10-23T14:00 또는 2026-10-23)이어야 합니다: {text}")
    if t.tzinfo is None:
        t = t.replace(tzinfo=_local_tz())
    return {"dateTime": t.isoformat()}


def _rfc3339(value, default):
    if not value:
        return default.isoformat()
    w = _when(value, "시각")
    return w.get("dateTime") or dt.datetime.fromisoformat(w["date"]).replace(tzinfo=_local_tz()).isoformat()


def _event_line(e):
    start = e.get("start") or {}
    end = e.get("end") or {}
    when = (start.get("dateTime") or start.get("date") or "")[:16].replace("T", " ")
    until = (end.get("dateTime") or end.get("date") or "")[11:16]
    extra = []
    if e.get("location"):
        extra.append(e["location"])
    if e.get("attendees"):
        extra.append(f"참석자 {len(e['attendees'])}명")
    return f"- {when}{'~' + until if until else ''} {e.get('summary', '(제목 없음)')}" + \
        (f" ({', '.join(extra)})" if extra else "") + f" [event_id {e.get('id')}]"


def calendar_list_calendars():
    data = _api("gcalendar", "GET", f"{CALENDAR}/users/me/calendarList")
    return "캘린더\n" + "\n".join(f"- {c.get('summary')} (id {c['id']}){' [기본]' if c.get('primary') else ''}"
                                for c in data.get("items") or [])


def calendar_list_events(time_min=None, time_max=None, query=None, calendar="primary", limit=50):
    now = dt.datetime.now(_local_tz())
    params = {"timeMin": _rfc3339(time_min, now), "timeMax": _rfc3339(time_max, now + dt.timedelta(days=7)),
              "singleEvents": "true", "orderBy": "startTime", "maxResults": _limit(limit, 50, 250)}
    if query:
        params["q"] = str(query)
    data = _api("gcalendar", "GET", f"{CALENDAR}/calendars/{calendar or 'primary'}/events", params)
    items = data.get("items") or []
    if not items:
        return f"{params['timeMin'][:10]}~{params['timeMax'][:10]}에 일정이 없습니다."
    return f"일정 {len(items)}개 ({params['timeMin'][:10]}~{params['timeMax'][:10]})\n" + "\n".join(_event_line(e) for e in items)


def _busy(start, end, calendars):
    if not start or not end:
        raise ToolFailure("start와 end가 필요합니다.")
    cals = calendars if isinstance(calendars, list) else [calendars or "primary"]
    data = _api("gcalendar", "POST", f"{CALENDAR}/freeBusy", body={
        "timeMin": _rfc3339(start, None), "timeMax": _rfc3339(end, None), "items": [{"id": c} for c in cals]})
    return [(cid, b) for cid, info in (data.get("calendars") or {}).items() for b in info.get("busy") or []]


def _busy_text(busy):
    return "\n".join(f"- {cid}: {b['start'][:16]} ~ {b['end'][:16]}" for cid, b in busy)


def calendar_check_conflicts(start, end, calendars=None):
    busy = _busy(start, end, calendars)
    if not busy:
        return f"{start}~{end}에는 겹치는 일정이 없습니다."
    return "겹치는 일정이 있습니다:\n" + _busy_text(busy)


def calendar_create_event(summary, start, end, description=None, location=None, attendees=None, calendar="primary"):
    _writable("gcalendar")
    event = {"summary": str(summary), "start": _when(start, "start"), "end": _when(end, "end")}
    if description:
        event["description"] = str(description)
    if location:
        event["location"] = str(location)
    if attendees:
        event["attendees"] = [{"email": a.strip()} for a in _addresses(attendees).split(",")]
    busy = _busy(start, end, [calendar or "primary"]) if "dateTime" in event["start"] else []
    # 초대 메일은 보내지 않는다(sendUpdates=none): 남에게 메일이 가는 일은 사용자가 Calendar에서 직접 하게 한다
    e = _api("gcalendar", "POST", f"{CALENDAR}/calendars/{calendar or 'primary'}/events", {"sendUpdates": "none"}, body=event)
    note = f"\n\n주의 — 이 시간에 이미 있던 일정과 겹칩니다:\n{_busy_text(busy)}" if busy else ""
    return f"일정을 만들었습니다: {_event_line(e)}\n{e.get('htmlLink', '')}{note}"


def calendar_update_event(event_id, summary=None, start=None, end=None, description=None, location=None,
                          calendar="primary"):
    _writable("gcalendar")
    patch = {}
    if summary is not None:
        patch["summary"] = str(summary)
    if start:
        patch["start"] = _when(start, "start")
    if end:
        patch["end"] = _when(end, "end")
    if description is not None:
        patch["description"] = str(description)
    if location is not None:
        patch["location"] = str(location)
    if not patch:
        raise ToolFailure("바꿀 내용이 없습니다.")
    e = _api("gcalendar", "PATCH", f"{CALENDAR}/calendars/{calendar or 'primary'}/events/{_id(event_id, '일정 ID')}",
             {"sendUpdates": "none"}, body=patch)
    return f"일정을 바꿨습니다: {_event_line(e)}"


ARR = {"type": "array", "items": STR}
ROWS = {"type": "array", "items": {"type": "array"}}

SERVERS = {
    "gdrive": {
        "search_files": (drive_search_files, "Drive에서 파일을 찾습니다(이름·본문). mime_type: doc|sheet|slide|pdf|folder 또는 MIME. "
                                             "folder로 폴더 안만. raw_query에는 Drive 검색식을 그대로.",
                         _schema({"query": STR, "mime_type": STR, "folder": STR, "limit": INT, "raw_query": STR}, []), READ_ONLY),
        "get_file": (drive_get_file, "파일 정보(이름·형식·수정 시각·링크·상위 폴더)를 봅니다. file: ID 또는 Drive 주소",
                     _schema({"file": STR}, ["file"]), READ_ONLY),
        "read_file": (drive_read_file, "파일 내용을 글자로 읽습니다(Google 문서·시트·프레젠테이션, PDF, Word, PowerPoint, Excel, 한글, 텍스트).",
                      _schema({"file": STR, "max_chars": INT}, ["file"]), READ_ONLY),
        "list_folder": (drive_list_folder, "폴더 안의 파일 목록. folder를 비우면 내 드라이브 최상위.",
                        _schema({"folder": STR, "limit": INT}, []), READ_ONLY),
        "list_changes": (drive_list_changes, "지난번 확인 이후 바뀐 파일. 처음 부르면 기준점만 만듭니다.",
                         _schema({"page_token": STR, "limit": INT}, []), READ_ONLY),
        "create_folder": (drive_create_folder, "폴더를 만듭니다(사용자 승인 필요).",
                          _schema({"name": STR, "parent": STR}, ["name"]), WRITES_REMOTE),
        "create_text_file": (drive_create_text_file, "글자 내용으로 파일을 만듭니다. convert_to_doc이면 Google 문서로(사용자 승인 필요).",
                             _schema({"name": STR, "content": STR, "parent": STR, "mime_type": STR, "convert_to_doc": BOOL},
                                     ["name", "content"]), WRITES_REMOTE),
        "upload_file": (drive_upload_file, "작업 폴더의 파일을 Drive에 올립니다(20MB 이하). convert면 Google 형식으로(사용자 승인 필요).",
                        _schema({"path": STR, "parent": STR, "name": STR, "convert": BOOL}, ["path"]), WRITES_REMOTE),
        "move_file": (drive_move_file, "파일을 다른 폴더로 옮깁니다. 이 앱이 만든 파일만 됩니다(사용자 승인 필요).",
                      _schema({"file": STR, "folder": STR}, ["file", "folder"]), WRITES_REMOTE),
    },
    "gdocs": {
        "read_document": (docs_read_document, "Google 문서 내용을 읽습니다(제목은 #, 표는 |). document: ID 또는 주소",
                          _schema({"document": STR, "max_chars": INT}, ["document"]), READ_ONLY),
        "create_document": (docs_create_document, "새 Google 문서를 만듭니다(사용자 승인 필요).",
                            _schema({"title": STR, "text": STR}, ["title"]), WRITES_REMOTE),
        "append_text": (docs_append_text, "문서 끝에 글을 덧붙입니다(사용자 승인 필요).",
                        _schema({"document": STR, "text": STR}, ["document", "text"]), WRITES_REMOTE),
        "replace_text": (docs_replace_text, "문서에서 old를 모두 new로 바꿉니다(사용자 승인 필요).",
                         _schema({"document": STR, "old": STR, "new": STR, "match_case": BOOL},
                                 ["document", "old", "new"]), WRITES_REMOTE),
    },
    "gsheets": {
        "get_info": (sheets_get_info, "스프레드시트의 제목과 시트 목록·크기를 봅니다.",
                     _schema({"spreadsheet": STR}, ["spreadsheet"]), READ_ONLY),
        "read_values": (sheets_read_values, "범위의 값을 읽습니다. range 예: 'Sheet1!A1:D20'(기본 A1:Z200).",
                        _schema({"spreadsheet": STR, "range": STR, "max_chars": INT}, ["spreadsheet"]), READ_ONLY),
        "update_values": (sheets_update_values, "범위에 값을 씁니다. values는 행 배열, =로 시작하면 수식(사용자 승인 필요).",
                          _schema({"spreadsheet": STR, "range": STR, "values": ROWS}, ["spreadsheet", "range", "values"]),
                          WRITES_REMOTE),
        "append_values": (sheets_append_values, "표 끝에 행을 더합니다(사용자 승인 필요).",
                          _schema({"spreadsheet": STR, "range": STR, "values": ROWS}, ["spreadsheet", "range", "values"]),
                          WRITES_REMOTE),
        "create_spreadsheet": (sheets_create_spreadsheet, "새 스프레드시트를 만듭니다. sheets는 시트 이름 배열(사용자 승인 필요).",
                               _schema({"title": STR, "sheets": ARR}, ["title"]), WRITES_REMOTE),
    },
    "gslides": {
        "read_presentation": (slides_read_presentation, "프레젠테이션의 슬라이드별 글자와 발표자 노트를 읽습니다.",
                              _schema({"presentation": STR, "max_chars": INT}, ["presentation"]), READ_ONLY),
        "create_presentation": (slides_create_presentation, "새 프레젠테이션을 만듭니다(사용자 승인 필요).",
                                _schema({"title": STR}, ["title"]), WRITES_REMOTE),
        "add_slide": (slides_add_slide, "슬라이드를 끝에 더합니다. layout: TITLE_AND_BODY|TITLE|TITLE_ONLY|SECTION_HEADER|BLANK. "
                                        "body는 글 또는 줄 배열(사용자 승인 필요).",
                      _schema({"presentation": STR, "title": STR, "body": STR, "layout": STR}, ["presentation"]), WRITES_REMOTE),
        "replace_text": (slides_replace_text, "모든 슬라이드에서 old를 new로 바꿉니다(사용자 승인 필요).",
                         _schema({"presentation": STR, "old": STR, "new": STR, "match_case": BOOL},
                                 ["presentation", "old", "new"]), WRITES_REMOTE),
    },
    "gmail": {
        "search_messages": (gmail_search_messages, "메일을 찾습니다(Gmail 검색식: from:, subject:, is:unread, newer_than:7d 등). "
                                                   "요약해 달라는 요청이면 찾은 뒤 read_message로 읽으세요.",
                            _schema({"query": STR, "limit": INT}, []), READ_ONLY),
        "read_message": (gmail_read_message, "메일 하나의 머리글·본문·첨부 이름을 읽습니다.",
                         _schema({"message_id": STR, "max_chars": INT}, ["message_id"]), READ_ONLY),
        "list_drafts": (gmail_list_drafts, "초안 목록(받는 사람·제목)을 봅니다.", _schema({"limit": INT}, []), READ_ONLY),
        "create_draft": (gmail_create_draft, "메일 초안을 만듭니다(보내지 않음, 사용자 승인 필요). 답장이면 reply_to_message_id.",
                         _schema({"to": STR, "subject": STR, "body": STR, "cc": STR, "bcc": STR,
                                  "reply_to_message_id": STR}, ["to", "subject", "body"]), WRITES_REMOTE),
        "send_draft": (gmail_send_draft, "초안을 보냅니다. 초안의 to·subject를 그대로 함께 넘겨야 하며, 사용자가 매번 승인해야 보내집니다.",
                       _schema({"draft_id": STR, "to": STR, "subject": STR}, ["draft_id", "to", "subject"]), WRITES_REMOTE),
    },
    "gcalendar": {
        "list_calendars": (calendar_list_calendars, "캘린더 목록.", _schema({}, []), READ_ONLY),
        "list_events": (calendar_list_events, "기간의 일정을 봅니다(기본: 지금부터 7일). 시각은 ISO 형식. 일정 요약에 쓰세요.",
                        _schema({"time_min": STR, "time_max": STR, "query": STR, "calendar": STR, "limit": INT}, []), READ_ONLY),
        "check_conflicts": (calendar_check_conflicts, "그 시간에 겹치는 일정(바쁨)이 있는지 봅니다.",
                            _schema({"start": STR, "end": STR, "calendars": ARR}, ["start", "end"]), READ_ONLY),
        "create_event": (calendar_create_event, "일정을 만듭니다(초대 메일은 보내지 않음, 사용자 승인 필요). start·end: ISO 시각 또는 날짜(종일).",
                         _schema({"summary": STR, "start": STR, "end": STR, "description": STR, "location": STR,
                                  "attendees": ARR, "calendar": STR}, ["summary", "start", "end"]), WRITES_REMOTE),
        "update_event": (calendar_update_event, "일정을 바꿉니다(사용자 승인 필요).",
                         _schema({"event_id": STR, "summary": STR, "start": STR, "end": STR, "description": STR,
                                  "location": STR, "calendar": STR}, ["event_id"]), WRITES_REMOTE),
    },
}
