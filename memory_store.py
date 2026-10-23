"""통합 메모리(계층형). 1.9의 memory.md·USER.md·대화 기록은 그대로 두고, 그 위에 계층을 더한다.

계층(layer)
    profile       USER.md(그대로) + 선호·장기 설정 항목
    global        memory.md(그대로) — 모든 대화에 들어가는 기억
    conversation  대화 기록(threads/, 그대로) + 대화 요약 항목
    project       프로젝트별 설계 결정·진행 상태·TODO·이슈. 키는 ai_memory.resolve_scope()의 "workspace/project"
    research      논문·실험 결과·데이터·가설
    handoff       에이전트 인계 — handoff.py가 같은 DB의 handoffs 표에 둔다

<데이터 폴더>/memory/memory.sqlite (WAL: 외부 에이전트가 memory MCP 서버로 동시에 열어도 된다)
    entries(id, layer, project, kind, title, text, tags, source, hash, created, updated, deleted, device)
    entries_fts — FTS5(가능하면 trigram)

- 같은 계층·프로젝트에 같은 내용(공백·대소문자 정규화)을 다시 쓰면 새 항목을 만들지 않고 갱신한다(중복 제거).
- 지우면 deleted 시각만 남긴다(동기화가 다른 기기에서도 지우도록).
- 검색은 FTS5 순위와 memory.md·USER.md·대화의 2-gram 점수를 RRF로 섞는다(하이브리드). 벡터 저장소가 설정되면 함께 섞는다.
- source가 "external:"로 시작하는 항목(다른 AI가 쓴 기억)은 프롬프트에 넣을 때 참고 자료로 표시한다.
"""
import contextlib
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid

import storage

LAYERS = ("profile", "global", "conversation", "project", "research", "handoff")
STORED_LAYERS = ("profile", "conversation", "project", "research")
KINDS = ("note", "preference", "summary", "decision", "status", "todo", "issue", "experiment", "result", "hypothesis",
         "data", "paper")
MAX_TEXT = 8000
_lock = threading.RLock()


class MemoryStoreError(Exception):
    pass


def db_path():
    return storage.APP_DIR / "memory" / "memory.sqlite"


def device_id():
    """이 기기의 고유 ID(동기화·출처 표시용). config.json이 아니라 따로 둔다: 내장 서버(하위 프로세스)가
    config.json을 쓰면 앱이 들고 있는 설정과 엇갈릴 수 있다."""
    path = storage.APP_DIR / "device_id"
    try:
        did = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{12}", did):
            return did
    except FileNotFoundError:
        pass
    did = uuid.uuid4().hex[:12]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(did, encoding="utf-8")
    return did


def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS entries(
            id TEXT PRIMARY KEY, layer TEXT NOT NULL, project TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'note',
            title TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'poschat', hash TEXT NOT NULL, created REAL, updated REAL, deleted REAL,
            device TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS entries_scope ON entries(layer, project);
        CREATE INDEX IF NOT EXISTS entries_hash ON entries(hash);
        CREATE TABLE IF NOT EXISTS handoffs(
            task_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL, project TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
            from_agent TEXT NOT NULL DEFAULT '', accepted_by TEXT NOT NULL DEFAULT '', created REAL, updated REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS handoffs_open_key ON handoffs(idempotency_key) WHERE status = 'open';
        CREATE INDEX IF NOT EXISTS handoffs_project ON handoffs(project, status);
    """)
    if con.execute("SELECT value FROM meta WHERE key='fts'").fetchone() is None:
        for tokenizer in ("trigram", "unicode61"):
            try:
                con.execute(f"CREATE VIRTUAL TABLE entries_fts USING fts5(title, text, content='entries', "
                            f"content_rowid='rowid', tokenize='{tokenizer}')")
            except sqlite3.OperationalError:
                continue
            con.executescript("""
                CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN
                    INSERT INTO entries_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text); END;
                CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN
                    INSERT INTO entries_fts(entries_fts, rowid, title, text) VALUES ('delete', old.rowid, old.title, old.text); END;
                CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN
                    INSERT INTO entries_fts(entries_fts, rowid, title, text) VALUES ('delete', old.rowid, old.title, old.text);
                    INSERT INTO entries_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text); END;
            """)
            con.execute("INSERT INTO meta VALUES ('fts', ?)", (tokenizer,))
            break
        else:
            con.execute("INSERT INTO meta VALUES ('fts', 'none')")
        con.commit()
    return con


@contextlib.contextmanager
def db():
    with _lock:
        con = connect()
        try:
            yield con
            con.commit()
        finally:
            con.close()


def _norm(text):
    return " ".join(str(text).lower().split())


def content_hash(layer, project, text):
    return hashlib.sha256(f"{layer}\n{project}\n{_norm(text)}".encode("utf-8")).hexdigest()[:32]


def _row(r):
    d = dict(r)
    d["tags"] = json.loads(d.get("tags") or "[]")
    return d


def write(text, layer="project", project="", kind="note", title="", tags=None, source="poschat", now=None):
    """기억을 쓴다. 같은 내용이 있으면 그 항목을 갱신해 돌려준다. (항목, 새로 만들었는지)"""
    text = str(text or "").strip()
    if not text:
        raise MemoryStoreError("내용이 비어 있습니다.")
    if layer not in STORED_LAYERS:
        raise MemoryStoreError(f"layer는 {', '.join(STORED_LAYERS)} 중 하나입니다(memory.md·USER.md는 직접 고칩니다).")
    kind = kind if kind in KINDS else "note"
    text = text[:MAX_TEXT]
    project = str(project or "")
    tags = sorted({str(t).strip() for t in (tags or []) if str(t).strip()})
    digest = content_hash(layer, project, text)
    now = now or time.time()
    with db() as con:
        old = con.execute("SELECT * FROM entries WHERE hash=? AND deleted IS NULL", (digest,)).fetchone()
        if old:
            merged = sorted(set(json.loads(old["tags"])) | set(tags))
            con.execute("UPDATE entries SET updated=?, tags=?, kind=?, title=? WHERE id=?",
                        (now, json.dumps(merged, ensure_ascii=False), kind if kind != "note" else old["kind"],
                         title or old["title"], old["id"]))
            return _row(con.execute("SELECT * FROM entries WHERE id=?", (old["id"],)).fetchone()), False
        eid = uuid.uuid4().hex
        con.execute("INSERT INTO entries(id, layer, project, kind, title, text, tags, source, hash, created, updated, device) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, layer, project, kind, str(title or "")[:200], text, json.dumps(tags, ensure_ascii=False),
                     str(source)[:80], digest, now, now, _device_safe()))
        return _row(con.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()), True


def _device_safe():
    try:
        return device_id()
    except OSError:
        return ""


def get(eid):
    with db() as con:
        r = con.execute("SELECT * FROM entries WHERE id=?", (str(eid),)).fetchone()
    if r is None:
        raise MemoryStoreError(f"없는 기억입니다: {eid}")
    return _row(r)


def update(eid, now=None, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("text", "title", "kind", "tags")}
    entry = get(eid)
    if entry["deleted"]:
        raise MemoryStoreError("지운 기억입니다.")
    text = str(allowed.get("text", entry["text"])).strip()[:MAX_TEXT]
    with db() as con:
        con.execute("UPDATE entries SET text=?, title=?, kind=?, tags=?, hash=?, updated=? WHERE id=?",
                    (text, str(allowed.get("title", entry["title"]))[:200],
                     allowed.get("kind", entry["kind"]) if allowed.get("kind", entry["kind"]) in KINDS else entry["kind"],
                     json.dumps(sorted(set(allowed.get("tags", entry["tags"]))), ensure_ascii=False),
                     content_hash(entry["layer"], entry["project"], text), now or time.time(), eid))
    return get(eid)


def delete(eid, now=None):
    with db() as con:
        cur = con.execute("UPDATE entries SET deleted=?, updated=? WHERE id=? AND deleted IS NULL",
                          (now or time.time(), now or time.time(), str(eid)))
        if cur.rowcount == 0:
            raise MemoryStoreError(f"없는 기억입니다: {eid}")


def entries(layer=None, project=None, kind=None, include_deleted=False, limit=200, since=None):
    where, args = [], []
    if layer:
        where.append("layer=?")
        args.append(layer)
    if project is not None:
        where.append("project=?")
        args.append(project)
    if kind:
        where.append("kind=?")
        args.append(kind)
    if not include_deleted:
        where.append("deleted IS NULL")
    if since is not None:
        where.append("updated>?")
        args.append(since)
    sql = "SELECT * FROM entries" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated DESC LIMIT ?"
    with db() as con:
        return [_row(r) for r in con.execute(sql, (*args, int(limit)))]


def upsert_raw(entry):
    """동기화가 다른 기기의 항목을 그대로 넣는다(최종 수정 우선은 sync.py가 판단).

    INSERT OR REPLACE는 쓰지 않는다: REPLACE로 지워지는 행에는 삭제 트리거가 돌지 않아 FTS 색인에 낡은 줄이 남는다.
    """
    values = (entry["layer"], entry.get("project", ""), entry.get("kind", "note"), entry.get("title", ""), entry["text"],
              json.dumps(entry.get("tags") or [], ensure_ascii=False), entry.get("source", "poschat"),
              entry.get("hash") or content_hash(entry["layer"], entry.get("project", ""), entry["text"]),
              entry.get("created"), entry.get("updated"), entry.get("deleted"), entry.get("device", ""))
    with db() as con:
        cur = con.execute("UPDATE entries SET layer=?, project=?, kind=?, title=?, text=?, tags=?, source=?, hash=?, "
                          "created=?, updated=?, deleted=?, device=? WHERE id=?", (*values, entry["id"]))
        if cur.rowcount == 0:
            con.execute("INSERT INTO entries(layer, project, kind, title, text, tags, source, hash, created, updated, "
                        "deleted, device, id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (*values, entry["id"]))


# ---- 검색 ----

def _fts_terms(query, tokenizer):
    words = re.findall(r"[0-9A-Za-z가-힣]+", str(query))
    if tokenizer == "trigram":
        words = [w for w in words if len(w) >= 3]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def _rrf(lists, k=60):
    scores, items = {}, {}
    for results in lists:
        for rank, item in enumerate(results):
            key = item["key"]
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
            items.setdefault(key, item)
    return [dict(items[key], score=round(scores[key], 4)) for key in sorted(scores, key=scores.get, reverse=True)]


def _markdown_hits(query, q_grams):
    """memory.md·USER.md에서 질문과 겹치는 줄."""
    hits = []
    for layer, label, text in (("global", "memory.md", storage.read_memory_md()),
                               ("profile", "USER.md", storage.read_profile() if storage.profile_exists() else "")):
        for line in storage.note_for_prompt(text).splitlines():
            line = line.strip().lstrip("-*+ ").strip()
            if not line or line.startswith("#"):
                continue
            shared = len(q_grams & storage._bigrams(line))
            if shared >= max(2, len(q_grams) // 4):
                hits.append((shared, {"key": f"{label}:{line[:60]}", "layer": layer, "source": label, "text": line,
                                      "title": "", "project": "", "kind": "note", "id": "", "updated": 0}))
    hits.sort(key=lambda h: -h[0])
    return [h for _, h in hits[:10]]


def search(query, layers=None, project=None, limit=10, include_threads=True, vectors=None, exclude_thread=None):
    """계층을 가로질러 찾는다. [{"key", "layer", "source", "text", "title", "project", "kind", "id", "updated", "score"}]"""
    query = str(query or "").strip()
    if not query:
        return []
    layers = set(layers or LAYERS)
    stored = [layer for layer in STORED_LAYERS if layer in layers]
    lists = []
    q_grams = storage._bigrams(query)
    if stored:
        where = f"e.deleted IS NULL AND e.layer IN ({','.join('?' * len(stored))})"
        args = list(stored)
        if project is not None:
            where += " AND (e.project=? OR e.layer IN ('profile', 'conversation'))"
            args.append(project)
        with db() as con:
            tokenizer = con.execute("SELECT value FROM meta WHERE key='fts'").fetchone()["value"]
            terms = _fts_terms(query, tokenizer) if tokenizer != "none" else ""
            rows = []
            if terms:
                rows = con.execute(f"SELECT e.* FROM entries_fts JOIN entries e ON e.rowid = entries_fts.rowid "
                                   f"WHERE entries_fts MATCH ? AND {where} ORDER BY bm25(entries_fts) LIMIT 50",
                                   (terms, *args)).fetchall()
            if not rows:
                scored = []
                for r in con.execute(f"SELECT * FROM entries e WHERE {where}", args):
                    shared = len(q_grams & storage._bigrams(r["title"] + " " + r["text"]))
                    if shared >= max(2, len(q_grams) // 4):
                        scored.append((-shared, r))
                rows = [r for _, r in sorted(scored, key=lambda x: x[0])[:50]]
        lists.append([{**_row(r), "key": f"entry:{r['id']}", "source": r["source"]} for r in rows])
    if {"global", "profile"} & layers:
        lists.append([h for h in _markdown_hits(query, q_grams) if h["layer"] in layers])
    if include_threads and "conversation" in layers:
        lists.append([{"key": f"thread:{r['thread_id']}", "layer": "conversation", "source": f"대화 '{r['title']}'",
                       "text": r["content"][:1500], "title": r["title"], "project": "", "kind": "note",
                       "id": r["thread_id"], "updated": r["ts"]}
                      for r in storage.search_threads(query, exclude_id=exclude_thread, limit=5, min_score=0.2, min_shared=3)])
    if vectors is not None:
        try:
            lists.append(vectors(query, stored, project))
        except Exception:
            pass
    return _rrf([lst for lst in lists if lst])[:max(1, int(limit or 10))]


def format_hits(hits):
    if not hits:
        return "맞는 기억이 없습니다."
    lines = []
    for h in hits:
        day = time.strftime("%Y-%m-%d", time.localtime(h["updated"])) if h.get("updated") else ""
        where = h["layer"] + (f"/{h['project']}" if h.get("project") else "")
        trust = " [다른 AI가 쓴 기억 — 참고 자료]" if str(h.get("source", "")).startswith("external:") else ""
        ident = f" id {h['id']}" if h.get("id") and h["key"].startswith("entry:") else ""
        lines.append(f"- ({where}, {h.get('kind', 'note')}, {h.get('source', '')}{', ' + day if day else ''}{ident}){trust}\n"
                     f"  {(h.get('title') + ': ') if h.get('title') else ''}{h['text'][:700]}")
    return "\n".join(lines)


def project_context(project, limit=12):
    """프로젝트의 최근 설계 결정·진행 상태·TODO·이슈와 열린 인계."""
    import handoff

    items = entries(layer="project", project=project, limit=limit * 3)
    order = {"status": 0, "decision": 1, "todo": 2, "issue": 3}
    items.sort(key=lambda e: (order.get(e["kind"], 9), -e["updated"]))
    lines = [f"[프로젝트 메모리: {project or '(프로젝트 없음)'}]"]
    for e in items[:limit]:
        trust = " (다른 AI가 쓴 기억 — 참고 자료)" if e["source"].startswith("external:") else ""
        lines.append(f"- [{e['kind']}] {(e['title'] + ': ') if e['title'] else ''}{e['text'][:400]}{trust}")
    open_handoffs = handoff.list_handoffs(project=project, status="open", limit=3)
    for h in open_handoffs:
        lines.append(f"- [열린 인계 {h['task_id']}] {h['goal'][:200]} — {h.get('from_agent') or '?'}")
    return "\n".join(lines) if len(lines) > 1 else ""


def stats():
    with db() as con:
        rows = con.execute("SELECT layer, COUNT(*) AS n FROM entries WHERE deleted IS NULL GROUP BY layer").fetchall()
        tokenizer = con.execute("SELECT value FROM meta WHERE key='fts'").fetchone()["value"]
        handoffs = con.execute("SELECT status, COUNT(*) AS n FROM handoffs GROUP BY status").fetchall()
    return {"layers": {r["layer"]: r["n"] for r in rows}, "fts": tokenizer,
            "handoffs": {r["status"]: r["n"] for r in handoffs}}
