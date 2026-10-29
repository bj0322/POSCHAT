# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""내장 MCP 서버 notion: Notion 페이지·데이터베이스를 찾고, 읽고, 쓴다(Notion 공식 API, 무료).

설정 창에 넣은 Notion 통합 토큰(config.json의 notion_token) 또는 NOTION_TOKEN 환경 변수를 쓴다.
토큰은 https://www.notion.so/profile/integrations 에서 '내부 통합'을 만들면 받고, 통합이 다룰
페이지마다 오른쪽 위 ··· → 연결(Connections)에서 그 통합을 추가해야 한다. 페이지 내용은 마크다운으로
주고받는다.
"""
import json
import os
import re
import time

from office_mcp import INT, READ_ONLY, STR, _schema
from net import ToolFailure, http

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_CHARS = 12000
MAX_DEPTH = 3          # 읽을 때 들어가는 하위 블록 깊이
MAX_BLOCKS = 1500      # 한 번에 읽는 블록 수 상한
TEXT_LIMIT = 2000      # Notion rich_text 한 조각의 글자 수 상한
CHILDREN_LIMIT = 100   # 한 요청에 넣을 수 있는 블록 수
WRITES_REMOTE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
SETUP_HINT = ("설정 → Notion 통합 토큰에 토큰을 넣으세요. 토큰은 https://www.notion.so/profile/integrations 에서 "
              "'새 통합'(내부)을 만들면 받을 수 있고, 다룰 페이지의 오른쪽 위 ··· → 연결에서 그 통합을 추가해야 합니다.")


def _token():
    token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY")
    if not token:
        import storage

        token = storage.load_config().get("notion_token", "")
    if not token:
        raise ToolFailure("Notion 토큰이 없습니다. " + SETUP_HINT)
    return token.strip()


def _api(method, path, body=None, params=None):
    headers = {"Authorization": f"Bearer {_token()}", "Notion-Version": NOTION_VERSION,
               "Content-Type": "application/json"}
    for attempt in range(3):
        r = http(method, API + path, headers=headers, params=params,
                 data=json.dumps(body).encode("utf-8") if body is not None else None, timeout=30)
        if r.status_code == 429 and attempt < 2:
            time.sleep(min(10.0, float(r.headers.get("Retry-After") or 1)))
            continue
        break
    if r.status_code == 200:
        return r.json()
    try:
        message = r.json().get("message", "")
    except ValueError:
        message = r.text[:300]
    if r.status_code == 401:
        raise ToolFailure("Notion 토큰이 올바르지 않습니다. " + SETUP_HINT)
    if r.status_code == 404:
        raise ToolFailure("Notion에서 찾지 못했습니다. 주소가 맞는지, 그리고 그 페이지(또는 상위 페이지)의 ··· → 연결에서 "
                          f"통합을 추가했는지 확인하세요. ({message})")
    if r.status_code == 403:
        raise ToolFailure(f"Notion 통합에 이 작업 권한이 없습니다(통합 설정의 기능 항목을 확인하세요). ({message})")
    raise ToolFailure(f"Notion 요청에 실패했습니다(HTTP {r.status_code}): {message}")


def _id(value):
    """페이지·데이터베이스 ID나 Notion URL에서 ID를 꺼낸다."""
    text = str(value or "").strip()
    path = re.split(r"[?#]", text)[0]
    found = re.findall(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}", path)
    if not found:
        raise ToolFailure(f"Notion 페이지 ID나 URL이 아닙니다: {text}. search로 먼저 찾으세요.")
    h = found[-1].replace("-", "").lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _paginate(method, path, body=None, limit=None):
    results, cursor = [], None
    while True:
        if method == "GET":
            params = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
            data = _api("GET", path, params=params)
        else:
            page_size = min(100, limit - len(results)) if limit else 100
            data = _api("POST", path, {**(body or {}), "page_size": page_size, **({"start_cursor": cursor} if cursor else {})})
        results += data.get("results", [])
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor or (limit and len(results) >= limit):
            return results[:limit] if limit else results


# ---- Notion → 마크다운 ----

def _plain(rich):
    return "".join(t.get("plain_text", "") for t in rich or [])


def _md_text(rich):
    out = []
    for t in rich or []:
        text = t.get("plain_text", "")
        if not text:
            continue
        a = t.get("annotations") or {}
        if t.get("type") == "equation":
            text = f"${text}$"
        elif a.get("code"):
            text = f"`{text}`"
        else:
            core = text.strip()
            if core:
                lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
                if a.get("bold"):
                    core = f"**{core}**"
                if a.get("italic"):
                    core = f"*{core}*"
                if a.get("strikethrough"):
                    core = f"~~{core}~~"
                text = lead + core + trail
        href = t.get("href")
        if href and t.get("type") != "mention":
            text = f"[{text}]({href})"
        out.append(text)
    return "".join(out)


def _title_of(obj):
    if obj.get("object") == "database":
        return _plain(obj.get("title")) or "(제목 없음)"
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title")) or "(제목 없음)"
    return "(제목 없음)"


def _prop_text(prop):
    kind = prop.get("type")
    v = prop.get(kind)
    if v is None:
        return ""
    if kind in ("title", "rich_text"):
        return _plain(v)
    if kind in ("select", "status"):
        return v.get("name", "")
    if kind == "multi_select":
        return ", ".join(o.get("name", "") for o in v)
    if kind == "date":
        return v.get("start", "") + (f" → {v['end']}" if v.get("end") else "")
    if kind == "checkbox":
        return "✔" if v else "✘"
    if kind in ("people",):
        return ", ".join(p.get("name") or p.get("id", "")[:8] for p in v)
    if kind in ("created_by", "last_edited_by"):
        return v.get("name") or v.get("id", "")[:8]
    if kind == "relation":
        return f"연결 {len(v)}개" if v else ""
    if kind == "files":
        return ", ".join(f.get("name", "") for f in v)
    if kind == "formula":
        return str(v.get(v.get("type")) if not isinstance(v.get(v.get("type")), dict) else _prop_text(v))
    if kind == "rollup":
        sub = v.get("type")
        if sub == "array":
            return ", ".join(_prop_text(x) for x in v.get("array") or [])
        return str(v.get(sub) or "")
    if kind == "unique_id":
        return f"{v.get('prefix') + '-' if v.get('prefix') else ''}{v.get('number')}"
    return str(v)


def _block_md(block, depth, state):
    """블록 하나를 마크다운 줄 목록으로. 하위 블록은 들여 써서 붙인다."""
    kind = block.get("type")
    data = block.get(kind) or {}
    rich = _md_text(data.get("rich_text"))
    indent = "  " * depth
    lines = []
    if kind == "paragraph":
        lines.append(rich)
    elif kind in ("heading_1", "heading_2", "heading_3"):
        lines.append("#" * int(kind[-1]) + " " + rich)
    elif kind == "bulleted_list_item":
        lines.append("- " + rich)
    elif kind == "numbered_list_item":
        lines.append("1. " + rich)
    elif kind == "to_do":
        lines.append(f"- [{'x' if data.get('checked') else ' '}] " + rich)
    elif kind == "toggle":
        lines.append("▸ " + rich)
    elif kind == "quote":
        lines.append("> " + rich)
    elif kind == "callout":
        icon = (data.get("icon") or {}).get("emoji", "💡")
        lines.append(f"> {icon} " + rich)
    elif kind == "code":
        lines += [f"```{data.get('language', '')}", _plain(data.get("rich_text")), "```"]
    elif kind == "equation":
        lines.append(f"$$ {data.get('expression', '')} $$")
    elif kind == "divider":
        lines.append("---")
    elif kind == "child_page":
        lines.append(f"📄 하위 페이지: {data.get('title', '')} (id: {block['id']})")
    elif kind == "child_database":
        lines.append(f"🗃 데이터베이스: {data.get('title', '')} (id: {block['id']})")
    elif kind in ("image", "video", "file", "pdf", "audio"):
        url = (data.get("file") or data.get("external") or {}).get("url", "")
        caption = _plain(data.get("caption"))
        lines.append(f"[{kind}: {caption or data.get('name', '')}] {url}".strip())
    elif kind in ("bookmark", "embed", "link_preview"):
        lines.append(f"🔗 {data.get('url', '')}")
    elif kind == "link_to_page":
        lines.append(f"↪ 페이지 링크: {data.get(data.get('type'), '')}")
    elif kind == "table":
        rows = _children(block["id"], state)
        for i, row in enumerate(rows):
            cells = [_md_text(c).replace("|", "\\|") for c in (row.get("table_row") or {}).get("cells", [])]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("|" + "---|" * len(cells))
        return [indent + x for x in lines]
    elif kind in ("column_list", "column", "synced_block", "template"):
        pass  # 내용은 하위 블록에 있다
    elif kind == "unsupported":
        lines.append("(Notion API가 지원하지 않는 블록)")
    else:
        lines.append(rich or f"({kind})")
    out = [indent + x for x in lines]
    if block.get("has_children") and kind not in ("child_page", "child_database", "table") and depth < MAX_DEPTH:
        child_depth = depth if kind in ("column_list", "column", "synced_block", "template") else depth + 1
        for child in _children(block["id"], state):
            out += _block_md(child, child_depth, state)
    return out


def _children(block_id, state):
    if state["count"] >= MAX_BLOCKS or state["chars"] >= state["max_chars"]:
        state["truncated"] = True
        return []
    blocks = _paginate("GET", f"/blocks/{block_id}/children")
    state["count"] += len(blocks)
    return blocks


def _page_markdown(page_id, max_chars):
    state = {"count": 0, "chars": 0, "max_chars": max_chars, "truncated": False}
    lines = []
    for block in _children(page_id, state):
        part = _block_md(block, 0, state)
        lines += part
        state["chars"] += sum(len(x) + 1 for x in part)
    return "\n".join(lines), state["truncated"]


# ---- 마크다운 → Notion ----

INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|~~[^~]+~~|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\$[^$\s][^$]*\$)")
CODE_LANGS = {
    "py": "python", "python": "python", "js": "javascript", "javascript": "javascript", "ts": "typescript",
    "typescript": "typescript", "java": "java", "c": "c", "cpp": "c++", "c++": "c++", "cs": "c#", "c#": "c#",
    "go": "go", "rust": "rust", "rs": "rust", "sh": "shell", "bash": "bash", "shell": "shell", "zsh": "shell",
    "ps1": "powershell", "powershell": "powershell", "json": "json", "html": "html", "css": "css", "sql": "sql",
    "md": "markdown", "markdown": "markdown", "yaml": "yaml", "yml": "yaml", "kotlin": "kotlin", "kt": "kotlin",
    "swift": "swift", "r": "r", "matlab": "matlab", "latex": "latex", "tex": "latex", "xml": "xml",
    "ruby": "ruby", "php": "php", "scala": "scala", "dart": "dart", "mermaid": "mermaid",
}


def _text(content, **annotations):
    """긴 글자를 2000자 조각으로 나눈 rich_text 목록."""
    out = []
    for i in range(0, max(1, len(content)), TEXT_LIMIT):
        piece = {"type": "text", "text": {"content": content[i:i + TEXT_LIMIT]}}
        if annotations.get("link"):
            piece["text"]["link"] = {"url": annotations.pop("link")}
        if annotations:
            piece["annotations"] = annotations
        out.append(piece)
    return out


def _rich(text):
    out = []
    for part in INLINE_RE.split(str(text)):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out += _text(part[2:-2], bold=True)
        elif part.startswith("~~") and part.endswith("~~") and len(part) > 4:
            out += _text(part[2:-2], strikethrough=True)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out += _text(part[1:-1], code=True)
        elif part.startswith("[") and part.endswith(")") and "](" in part:
            label, url = part[1:-1].split("](", 1)
            out += _text(label, link=url) if url.startswith(("http://", "https://")) else _text(part)
        elif part.startswith("$") and part.endswith("$") and len(part) > 2:
            out.append({"type": "equation", "equation": {"expression": part[1:-1]}})
        elif len(part) > 2 and part[0] == part[-1] and part[0] in "*_":
            out += _text(part[1:-1], italic=True)
        else:
            out += _text(part)
    return out


def _block(kind, text="", **extra):
    return {"object": "block", "type": kind, kind: {"rich_text": _rich(text) if text != "" else [], **extra}}


def _markdown_blocks(markdown):
    """마크다운을 Notion 블록 목록으로. 들여 쓴 목록(공백 2칸)은 하위 블록으로, 한 단계까지(더 깊으면 같은 단계로)."""
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    blocks, stack, para = [], [], []  # stack: [(들여쓰기, 목록 블록)]

    def flush():
        if para:
            blocks.append(_block("paragraph", "\n".join(para)))
            para.clear()

    def add(block, indent=0):
        flush()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:  # 한 요청에 넣을 수 있는 중첩 깊이에 제한이 있어 맨 위 목록 항목 아래로만 넣는다
            parent = stack[0][1]
            parent[parent["type"]].setdefault("children", []).append(block)
        else:
            blocks.append(block)
        if block["type"] in ("bulleted_list_item", "numbered_list_item", "to_do"):
            stack.append((indent, block))

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        indent = (len(raw) - len(raw.lstrip(" "))) // 2
        if not line:
            flush()
            stack.clear()
            i += 1
            continue
        if line.startswith("```"):
            lang = CODE_LANGS.get(line[3:].strip().lower(), "plain text")
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            add({"object": "block", "type": "code",
                 "code": {"rich_text": _text("\n".join(code)), "language": lang}})
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                add({"object": "block", "type": "table", "table": {
                    "table_width": width, "has_column_header": True, "has_row_header": False,
                    "children": [{"object": "block", "type": "table_row",
                                  "table_row": {"cells": [_rich(r[c]) if c < len(r) else [] for c in range(width)]}}
                                 for r in rows]}})
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            add(_block(f"heading_{min(3, len(m.group(1)))}", m.group(2)))
        elif re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", line):
            add({"object": "block", "type": "divider", "divider": {}})
        elif re.match(r"^[-*+]\s+\[( |x|X)\]\s+", line):
            checked = line[3].lower() == "x"
            add(_block("to_do", re.sub(r"^[-*+]\s+\[.\]\s+", "", line), checked=checked), indent)
        elif re.match(r"^[-*+]\s+", line):
            add(_block("bulleted_list_item", re.sub(r"^[-*+]\s+", "", line)), indent)
        elif re.match(r"^\d+[.)]\s+", line):
            add(_block("numbered_list_item", re.sub(r"^\d+[.)]\s+", "", line)), indent)
        elif line.startswith(">"):
            add(_block("quote", line.lstrip(">").strip()))
        elif line.startswith("$$") and line.endswith("$$") and len(line) > 4:
            add({"object": "block", "type": "equation", "equation": {"expression": line[2:-2].strip()}})
        else:
            stack.clear()
            para.append(line)
        i += 1
    flush()
    return blocks


def _append(block_id, blocks):
    for i in range(0, len(blocks), CHILDREN_LIMIT):
        _api("PATCH", f"/blocks/{block_id}/children", {"children": blocks[i:i + CHILDREN_LIMIT]})


# ---- 속성 값 ----

def _prop_value(kind, value, name):
    """간단한 값(문자열·숫자·목록)을 Notion 속성 형식으로. dict는 API 형식으로 보고 그대로 쓴다."""
    if isinstance(value, dict):
        return value
    if kind in ("title", "rich_text"):
        return {kind: _rich(str(value))}
    if kind == "number":
        try:
            return {"number": None if value in (None, "") else float(value) if "." in str(value) else int(value)}
        except ValueError:
            raise ToolFailure(f"'{name}'은(는) 숫자 속성입니다: {value}")
    if kind in ("select", "status"):
        return {kind: {"name": str(value)} if value not in (None, "") else None}
    if kind == "multi_select":
        items = value if isinstance(value, list) else [x.strip() for x in str(value).split(",") if x.strip()]
        return {"multi_select": [{"name": str(x)} for x in items]}
    if kind == "date":
        if value in (None, ""):
            return {"date": None}
        start, _, end = str(value).partition("/")
        return {"date": {"start": start.strip(), **({"end": end.strip()} if end.strip() else {})}}
    if kind == "checkbox":
        return {"checkbox": value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1", "yes", "y", "예", "o", "✔")}
    if kind in ("url", "email", "phone_number"):
        return {kind: str(value) if value not in (None, "") else None}
    if kind == "relation":
        items = value if isinstance(value, list) else [value]
        return {"relation": [{"id": _id(x)} for x in items]}
    if kind == "people":
        items = value if isinstance(value, list) else [value]
        return {"people": [{"id": str(x)} for x in items]}
    raise ToolFailure(f"'{name}'({kind}) 속성은 간단한 값으로 쓸 수 없습니다. Notion API 형식의 객체로 주세요.")


def _properties(schema, values):
    """schema: 속성 이름 -> 속성(type 포함). values: 이름 -> 간단한 값."""
    if values is None:
        return {}
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            raise ToolFailure("properties는 {\"속성 이름\": 값} 객체여야 합니다.")
    if not isinstance(values, dict):
        raise ToolFailure("properties는 {\"속성 이름\": 값} 객체여야 합니다.")
    lower = {k.lower(): k for k in schema}
    out = {}
    for name, value in values.items():
        key = name if name in schema else lower.get(str(name).lower())
        if key is None:
            raise ToolFailure(f"'{name}' 속성이 없습니다. 있는 속성: {', '.join(schema) or '없음'}")
        out[key] = _prop_value(schema[key].get("type"), value, key)
    return out


def _title_prop(schema):
    return next((k for k, v in schema.items() if v.get("type") == "title"), "title")


def _schema_text(schema):
    parts = []
    for name, prop in schema.items():
        kind = prop.get("type")
        options = (prop.get(kind) or {}).get("options") if kind in ("select", "multi_select", "status") else None
        parts.append(f"{name}({kind}" + (": " + "/".join(o.get("name", "") for o in options[:15]) if options else "") + ")")
    return ", ".join(parts)


# ---- 도구 ----

def search(query="", type=None, limit=10):
    limit = max(1, min(50, int(limit or 10)))
    body = {"query": str(query or "")}
    if type in ("page", "database"):
        body["filter"] = {"property": "object", "value": type}
    body["sort"] = {"direction": "descending", "timestamp": "last_edited_time"}
    results = _paginate("POST", "/search", body, limit)
    if not results:
        return ("결과가 없습니다. 찾는 페이지가 있다면 그 페이지의 ··· → 연결에서 통합을 추가했는지 확인하세요"
                "(통합은 연결된 페이지와 그 하위 페이지만 볼 수 있습니다).")
    lines = [f"Notion 검색 '{query}' ({len(results)}건)"]
    for i, obj in enumerate(results, 1):
        kind = "🗃 데이터베이스" if obj.get("object") == "database" else "📄 페이지"
        lines.append(f"{i}. {kind} {_title_of(obj)}  (id: {obj['id']}, 수정 {obj.get('last_edited_time', '')[:10]})\n   {obj.get('url', '')}")
    return "\n".join(lines)


def read_page(page, max_chars=DEFAULT_CHARS):
    page_id = _id(page)
    max_chars = max(2000, min(40000, int(max_chars or DEFAULT_CHARS)))
    try:
        obj = _api("GET", f"/pages/{page_id}")
    except ToolFailure as e:
        try:
            _api("GET", f"/databases/{page_id}")
        except ToolFailure:
            raise e
        raise ToolFailure("페이지가 아니라 데이터베이스입니다. query_database로 읽으세요.")
    lines = [f"# {_title_of(obj)}", obj.get("url", "")]
    props = [(k, _prop_text(v)) for k, v in (obj.get("properties") or {}).items() if v.get("type") != "title"]
    props = [f"- {k}: {v}" for k, v in props if v]
    if props:
        lines += ["", "속성:"] + props
    body, truncated = _page_markdown(page_id, max_chars)
    text = "\n".join(lines) + "\n\n" + (body or "(본문 없음)")
    if len(text) > max_chars or truncated:
        text = text[:max_chars] + "\n\n…(분량이 많아 일부만 읽었습니다. max_chars를 늘리거나 하위 페이지를 따로 읽으세요.)"
    return text


def query_database(database, filter=None, sorts=None, limit=20):
    db_id = _id(database)
    db = _api("GET", f"/databases/{db_id}")
    schema = db.get("properties") or {}
    body = {}
    for key, value in (("filter", filter), ("sorts", sorts)):
        if value:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    raise ToolFailure(f"{key}는 Notion API 형식의 JSON이어야 합니다.")
            body[key] = value
    limit = max(1, min(100, int(limit or 20)))
    rows = _paginate("POST", f"/databases/{db_id}/query", body, limit)
    title = _title_prop(schema)
    names = [title] + [k for k in schema if k != title]
    lines = [f"🗃 {_title_of(db)} (id: {db_id})", f"속성: {_schema_text(schema)}", f"행 {len(rows)}개" + (" (limit까지)" if len(rows) >= limit else ""), ""]
    for i, row in enumerate(rows, 1):
        props = row.get("properties") or {}
        cells = [f"{k}={_prop_text(props[k])}" for k in names if k in props and _prop_text(props[k])]
        lines.append(f"{i}. " + " · ".join(cells) + f"  (id: {row['id']})")
    return "\n".join(lines)


def create_page(parent, title, markdown="", properties=None):
    parent_id = _id(parent)
    try:
        db = _api("GET", f"/databases/{parent_id}")
    except ToolFailure:
        db = None
    blocks = _markdown_blocks(markdown)
    if db:
        schema = db.get("properties") or {}
        props = _properties(schema, properties)
        props[_title_prop(schema)] = {"title": _rich(str(title))}
        body = {"parent": {"database_id": parent_id}, "properties": props}
    else:
        if properties:
            raise ToolFailure("일반 페이지 아래에 만드는 페이지에는 제목 외의 속성을 줄 수 없습니다(데이터베이스에만 있습니다).")
        body = {"parent": {"page_id": parent_id}, "properties": {"title": {"title": _rich(str(title))}}}
    body["children"] = blocks[:CHILDREN_LIMIT]
    page = _api("POST", "/pages", body)
    _append(page["id"], blocks[CHILDREN_LIMIT:])
    where = f"데이터베이스 '{_title_of(db)}'" if db else "페이지"
    return f"{where} 아래에 '{title}' 페이지를 만들었습니다(블록 {len(blocks)}개).\nid: {page['id']}\n{page.get('url', '')}"


def append_content(page, markdown):
    page_id = _id(page)
    blocks = _markdown_blocks(markdown)
    if not blocks:
        raise ToolFailure("markdown이 비어 있습니다.")
    _append(page_id, blocks)
    return f"페이지 끝에 블록 {len(blocks)}개를 덧붙였습니다(id: {page_id})."


def update_page(page, title=None, properties=None):
    page_id = _id(page)
    obj = _api("GET", f"/pages/{page_id}")
    schema = obj.get("properties") or {}
    props = _properties(schema, properties)
    if title:
        props[_title_prop(schema)] = {"title": _rich(str(title))}
    if not props:
        raise ToolFailure("바꿀 title이나 properties를 주세요.")
    _api("PATCH", f"/pages/{page_id}", {"properties": props})
    return f"'{_title_of(obj)}' 페이지의 {', '.join(props)}을(를) 바꿨습니다."


PAGE_HELP = "page: 페이지 ID 또는 Notion URL"
MD_HELP = ("markdown: # 제목, - 목록(공백 2칸 들여쓰기), 1. 번호, - [ ] 할 일, > 인용, ``` 코드 ```, | 표 |, ---, "
           "**굵게**, *기울임*, `코드`, [글](URL), $수식$")
PROPS_HELP = ("properties: {\"속성 이름\": 값} — select·status는 이름, multi_select는 목록, date는 \"2026-10-20\"(기간은 "
              "\"시작/끝\"), checkbox는 true/false, number는 숫자. query_database 결과의 속성 목록을 참고하세요.")

TOOLS = {
    "search": (search, "Notion에서 페이지·데이터베이스를 제목으로 찾습니다(최근 수정 순). query를 비우면 통합이 볼 수 있는 "
                       "전체 목록. type: page|database",
               _schema({"query": STR, "type": STR, "limit": INT}, []), READ_ONLY),
    "read_page": (read_page, "Notion 페이지의 속성과 본문을 마크다운으로 읽습니다. " + PAGE_HELP,
                  _schema({"page": STR, "max_chars": INT}, ["page"]), READ_ONLY),
    "query_database": (query_database, "Notion 데이터베이스의 속성 구성과 행을 봅니다. filter·sorts는 Notion API 형식"
                                       "(예: {\"property\": \"상태\", \"status\": {\"equals\": \"진행 중\"}}).",
                       _schema({"database": STR, "filter": {"type": "object"}, "sorts": {"type": "array"}, "limit": INT},
                               ["database"]), READ_ONLY),
    "create_page": (create_page, "parent(페이지나 데이터베이스의 ID·URL) 아래에 새 페이지를 만듭니다. " + MD_HELP + ". "
                                 "데이터베이스에 만들 때만 " + PROPS_HELP,
                    _schema({"parent": STR, "title": STR, "markdown": STR, "properties": {"type": "object"}},
                            ["parent", "title"]), WRITES_REMOTE),
    "append_content": (append_content, "Notion 페이지 끝에 마크다운 내용을 덧붙입니다. " + MD_HELP,
                       _schema({"page": STR, "markdown": STR}, ["page", "markdown"]), WRITES_REMOTE),
    "update_page": (update_page, "Notion 페이지의 제목이나 데이터베이스 속성 값을 바꿉니다. " + PROPS_HELP,
                    _schema({"page": STR, "title": STR, "properties": {"type": "object"}}, ["page"]), WRITES_REMOTE),
}
