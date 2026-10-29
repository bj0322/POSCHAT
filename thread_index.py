# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""대화 검색용 색인(storage.search_threads가 쓴다).

예전에는 질문 하나마다 threads/*.json을 전부 다시 읽어 JSON을 해석했다(대화가 쌓일수록 느려진다).
여기서는 메시지 본문(앞 6000자, 소문자)을 SQLite 파일(thread_index.db)에 두고, 바뀐 대화 파일만 다시 읽는다.
점수 계산은 예전과 같다(질문의 글자쌍 중 본문에 있는 것의 비율). 색인은 언제든 지워도 다시 만들어진다.
"""
import json
import sqlite3
import threading

import storage

VERSION = 1  # 색인에 넣는 내용이 바뀌면 올린다(옛 색인은 지우고 다시 만든다)
TEXT_CHARS = 6000

_lock = threading.Lock()


def _connect():
    con = sqlite3.connect(str(storage.APP_DIR / "thread_index.db"), timeout=10)
    if con.execute("PRAGMA user_version").fetchone()[0] != VERSION:
        con.executescript("DROP TABLE IF EXISTS msgs; DROP TABLE IF EXISTS threads;")
        con.execute(f"PRAGMA user_version = {VERSION}")
    con.executescript(
        "CREATE TABLE IF NOT EXISTS threads (name TEXT PRIMARY KEY, tid TEXT, mtime INTEGER, size INTEGER);"
        "CREATE TABLE IF NOT EXISTS msgs (name TEXT, idx INTEGER, role TEXT, text TEXT);"
        "CREATE INDEX IF NOT EXISTS msgs_name ON msgs (name);")
    return con


def _sync(con):
    """대화 파일과 색인을 맞춘다: 새로 생기거나 바뀐 파일은 다시 읽고, 사라진 파일은 뺀다."""
    files = {}
    for p in storage.THREADS_DIR.glob("*.json"):
        try:
            st = p.stat()
        except OSError:
            continue
        files[p.name] = (p, st.st_mtime_ns, st.st_size)
    known = {name: (mtime, size) for name, mtime, size in con.execute("SELECT name, mtime, size FROM threads")}
    for name in set(known) - set(files):
        con.execute("DELETE FROM msgs WHERE name = ?", (name,))
        con.execute("DELETE FROM threads WHERE name = ?", (name,))
    for name, (p, mtime, size) in files.items():
        if known.get(name) == (mtime, size):
            continue
        try:
            thread = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # 깨졌거나 쓰는 중이다. 다음 검색 때 다시 본다
        con.execute("DELETE FROM msgs WHERE name = ?", (name,))
        con.execute("INSERT OR REPLACE INTO threads VALUES (?, ?, ?, ?)", (name, str(thread.get("id")), mtime, size))
        con.executemany(
            "INSERT INTO msgs VALUES (?, ?, ?, ?)",
            [(name, i, m["role"], str(m.get("content", ""))[:TEXT_CHARS].lower())
             for i, m in enumerate(thread.get("messages", [])) if m.get("role") in ("user", "assistant")])
    con.commit()


def _shared(grams, text, need):
    """text에 들어 있는 글자쌍 수. need개에 못 미칠 것이 확실해지면 일찍 0을 돌려준다."""
    hits, left = 0, len(grams)
    for g in grams:
        left -= 1
        if g in text:
            hits += 1
        elif hits + left < need:
            return 0
    return hits


def candidates(grams, exclude_id, min_score, min_shared):
    """[(thread_id, 파일 이름, 메시지 순번, 역할, 점수)] 대화마다 가장 점수가 높은 메시지 하나씩, 점수 높은 순."""
    grams = sorted(grams)
    need = max(min_shared, int(min_score * len(grams)))  # 이보다 적게 겹치면 어차피 탈락(소수 오차로 느슨한 쪽)
    best = {}
    with _lock:
        con = _connect()
        try:
            _sync(con)
            rows = con.execute(
                "SELECT t.tid, m.name, m.idx, m.role, m.text FROM msgs m JOIN threads t ON t.name = m.name ORDER BY m.rowid")
            for tid, name, idx, role, text in rows:
                if tid == exclude_id:
                    continue
                shared = _shared(grams, text, need)
                score = shared / len(grams)
                if shared < min_shared or score < min_score:
                    continue
                if score > best.get(tid, (0,))[-1]:
                    best[tid] = (tid, name, idx, role, score)
        finally:
            con.close()
    return sorted(best.values(), key=lambda c: round(c[4], 2), reverse=True)
