"""대화 스레드와 설정을 %APPDATA%\\PostechChat 아래에 JSON으로 저장한다."""
import json
import os
import re
import time
import uuid
from pathlib import Path


def _app_dir():
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "PostechChat"


APP_DIR = _app_dir()
THREADS_DIR = APP_DIR / "threads"
USER_SKILLS_DIR = APP_DIR / "skills"
CONFIG_PATH = APP_DIR / "config.json"
MEMORY_PATH = APP_DIR / "memory.json"
MCP_PATH = APP_DIR / "mcp.json"  # 외부 MCP 서버 설정(Claude Desktop과 같은 형식)

DEFAULT_CONFIG = {
    "api_key": "",
    "workspace": "",
    "agent_mode": True,
    "history_messages": 20,
    "share_threads": True,  # 새 질문과 관련된 다른 대화 내용을 자동으로 참고
}


def ensure_dirs():
    for d in (THREADS_DIR, USER_SKILLS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg):
    _write_json(CONFIG_PATH, cfg)


def make_message(role, content, **extra):
    return {"id": uuid.uuid4().hex, "role": role, "content": content, "ts": time.time(), **extra}


def new_thread():
    now = time.time()
    thread = {"id": uuid.uuid4().hex, "title": "새 대화", "created": now, "updated": now, "messages": []}
    save_thread(thread)
    return thread


def save_thread(thread):
    thread["updated"] = time.time()
    _write_json(THREADS_DIR / f"{thread['id']}.json", thread)


def load_thread(thread_id):
    try:
        return json.loads((THREADS_DIR / f"{thread_id}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def list_threads():
    threads = []
    for p in THREADS_DIR.glob("*.json"):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        threads.append({"id": t["id"], "title": t.get("title", "새 대화"), "updated": t.get("updated", 0)})
    threads.sort(key=lambda t: t["updated"], reverse=True)
    return threads


def delete_thread(thread_id):
    (THREADS_DIR / f"{thread_id}.json").unlink(missing_ok=True)


# ---- 메모리: 모든 대화에 공통으로 들어가는 기억 ----

def load_memory():
    try:
        items = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        return items if isinstance(items, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def add_memory(text):
    text = " ".join(str(text).split())
    if not text:
        return None
    items = load_memory()
    if any(m["text"] == text for m in items):
        return None
    item = {"id": uuid.uuid4().hex, "text": text[:500], "created": time.time()}
    items.append(item)
    _write_json(MEMORY_PATH, items)
    return item


def delete_memory(memory_id):
    _write_json(MEMORY_PATH, [m for m in load_memory() if m["id"] != memory_id])


# ---- 다른 대화 검색 ----

def _bigrams(text):
    """한국어는 조사가 붙어 단어 단위로는 잘 안 맞으므로 글자 2개 단위로 비교한다."""
    grams = set()
    for word in re.findall(r"[0-9a-z가-힣]+", text.lower()):
        grams.update(word[i:i + 2] for i in range(len(word) - 1))
    return grams


def search_threads(query, exclude_id=None, limit=3, min_score=0.35, min_shared=4):
    """다른 대화에서 query와 겹치는 메시지를 찾는다. 대화마다 가장 잘 맞는 메시지 하나씩."""
    q = _bigrams(query)
    if len(q) < 3:
        return []
    best = {}
    for p in THREADS_DIR.glob("*.json"):
        try:
            thread = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if thread.get("id") == exclude_id:
            continue
        for m in thread.get("messages", []):
            if m.get("role") not in ("user", "assistant"):
                continue
            shared = len(q & _bigrams(m["content"][:6000]))
            score = shared / len(q)
            if shared < min_shared or score < min_score:
                continue
            if score > best.get(thread["id"], {}).get("score", 0):
                best[thread["id"]] = {
                    "thread_id": thread["id"], "title": thread.get("title", ""), "role": m["role"],
                    "content": m["content"], "ts": m.get("ts", 0), "score": round(score, 2),
                }
    return sorted(best.values(), key=lambda r: r["score"], reverse=True)[:limit]
