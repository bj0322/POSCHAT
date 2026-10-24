# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Lab(1.16): 실험(Experiment)과 실행 기록(Run)의 저장소. 데이터 폴더의 lab/lab.db(SQLite).

- 실험과 실행은 나눠 둔다. 실험 하나에 Run이 여러 개 있다(Run 번호는 실험 안에서 1, 2, 3…).
- 한 번에 하나의 트랜잭션으로 쓰므로 쓰다가 앱이 꺼져도 반쯤 쓴 기록이 남지 않는다(WAL).
- 형식 버전은 PRAGMA user_version으로 관리한다(SCHEMA_VERSION). 새 버전은 여기서 옮긴다.
- 실행 중(running·queued)으로 남은 Run은 다음에 앱을 켤 때 '중단됨(interrupted)'으로 표시한다(recover).
- 기록을 지워도 사용자의 원본 결과 파일은 지우지 않는다. 화면에서 올린 결과 파일 사본(lab/files/<run>)만 함께 지운다.
- 비밀(키·토큰·비밀번호)은 저장하지 않는다: 환경 변수는 비밀 이름을 빼고, 명령·로그는 code_runner가 가린 것을 쓴다.
"""
import json
import shutil
import sqlite3
import threading
import time
import uuid

import storage

SCHEMA_VERSION = 1
STATUSES = ("queued", "running", "completed", "failed", "cancelled", "interrupted", "imported")
STATUS_LABEL = {"queued": "대기", "running": "실행 중", "completed": "완료", "failed": "실패", "cancelled": "취소됨",
                "interrupted": "중단됨(앱 종료)", "imported": "가져옴"}
MAX_TEXT = 200_000
_lock = threading.RLock()
_conn = None
_conn_path = None


class LabError(Exception):
    pass


def lab_dir():
    path = storage.APP_DIR / "lab"
    path.mkdir(parents=True, exist_ok=True)
    return path


def files_dir(run_id):
    path = lab_dir() / "files" / str(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db():
    """연결 하나를 잠금과 함께 쓴다(데이터 폴더가 바뀌면 다시 연다 — 시험의 격리 폴더)."""
    global _conn, _conn_path
    path = lab_dir() / "lab.db"
    if _conn is None or _conn_path != path:
        if _conn is not None:
            try:
                _conn.close()
            except sqlite3.Error:
                pass
        con = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        _migrate(con)
        _conn, _conn_path = con, path
    return _conn


def _migrate(con):
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise LabError(f"더 새 버전의 POSCHAT이 만든 Lab 기록입니다(형식 {version}). 앱을 업데이트하세요.")
    if version < 1:
        with con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS experiments(
              id TEXT PRIMARY KEY, name TEXT NOT NULL, project TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
              workspace TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]', settings TEXT NOT NULL DEFAULT '{}',
              created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
              seq INTEGER NOT NULL, name TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'poschat',
              started REAL, ended REAL, seconds REAL, command TEXT NOT NULL DEFAULT '', command_template TEXT NOT NULL DEFAULT '',
              cwd TEXT NOT NULL DEFAULT '', params TEXT NOT NULL DEFAULT '{}', code TEXT NOT NULL DEFAULT '{}',
              env TEXT NOT NULL DEFAULT '{}', inputs TEXT NOT NULL DEFAULT '[]', outputs TEXT NOT NULL DEFAULT '[]',
              exit_code INTEGER, metrics TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '', log_tail TEXT NOT NULL DEFAULT '',
              locations TEXT NOT NULL DEFAULT '[]', code_run_id TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
              UNIQUE(experiment_id, seq));
            CREATE INDEX IF NOT EXISTS runs_exp ON runs(experiment_id, seq);
            """)
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


JSON_FIELDS = ("params", "code", "env", "inputs", "outputs", "metrics", "locations", "tags", "settings")


def _row(r):
    d = dict(r)
    for k in JSON_FIELDS:
        if k in d:
            try:
                d[k] = json.loads(d[k] or ("[]" if k in ("inputs", "outputs", "locations", "tags") else "{}"))
            except ValueError:
                d[k] = [] if k in ("inputs", "outputs", "locations", "tags") else {}
    if "status" in d:
        d["status_label"] = STATUS_LABEL.get(d["status"], d["status"])
    return d


def _clean_text(value, limit=2000):
    return str(value or "").strip()[:limit]


# ---- 실험 ----

def create_experiment(name, project="", description="", workspace="", tags=None, settings=None):
    name = _clean_text(name, 200)
    if not name:
        raise LabError("실험 이름을 입력하세요.")
    now = time.time()
    eid = "exp-" + uuid.uuid4().hex[:8]
    with _lock:
        con = _db()
        with con:
            con.execute("INSERT INTO experiments(id, name, project, description, workspace, tags, settings, created, updated) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (eid, name, _clean_text(project, 200), _clean_text(description, 5000),
                                                       str(workspace or ""), json.dumps(list(tags or [])[:30], ensure_ascii=False),
                                                       json.dumps(settings or {}, ensure_ascii=False), now, now))
    return get_experiment(eid)


def update_experiment(eid, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("name", "project", "description", "tags", "settings")}
    exp = get_experiment(eid, runs=False)
    if "name" in allowed and not _clean_text(allowed["name"]):
        raise LabError("실험 이름을 입력하세요.")
    values = {
        "name": _clean_text(allowed.get("name", exp["name"]), 200),
        "project": _clean_text(allowed.get("project", exp["project"]), 200),
        "description": _clean_text(allowed.get("description", exp["description"]), 5000),
        "tags": json.dumps(list(allowed.get("tags", exp["tags"]))[:30], ensure_ascii=False),
        "settings": json.dumps(allowed.get("settings", exp.get("settings") or {}), ensure_ascii=False),
    }
    with _lock:
        con = _db()
        with con:
            con.execute("UPDATE experiments SET name=?, project=?, description=?, tags=?, settings=?, updated=? WHERE id=?",
                        (values["name"], values["project"], values["description"], values["tags"], values["settings"],
                         time.time(), eid))
    return get_experiment(eid)


def get_experiment(eid, runs=True):
    with _lock:
        r = _db().execute("SELECT * FROM experiments WHERE id=?", (str(eid),)).fetchone()
        if r is None:
            raise LabError("실험을 찾지 못했습니다.")
        exp = _row(r)
        if runs:
            exp["runs"] = [_row(x) for x in _db().execute(
                "SELECT * FROM runs WHERE experiment_id=? ORDER BY seq", (exp["id"],)).fetchall()]
    return exp


def list_experiments():
    with _lock:
        rows = _db().execute(
            "SELECT e.*, (SELECT COUNT(*) FROM runs r WHERE r.experiment_id=e.id) AS run_count, "
            "(SELECT MAX(COALESCE(r.updated, 0)) FROM runs r WHERE r.experiment_id=e.id) AS last_run "
            "FROM experiments e ORDER BY MAX(e.updated, COALESCE(last_run, 0)) DESC").fetchall()
        return [_row(r) for r in rows]


def delete_experiment(eid):
    """실험과 그 Run 기록을 지운다. 사용자 원본 파일은 그대로, Lab에 올린 사본만 지운다."""
    exp = get_experiment(eid)
    with _lock:
        con = _db()
        with con:
            con.execute("DELETE FROM experiments WHERE id=?", (exp["id"],))
    for run in exp["runs"]:
        shutil.rmtree(lab_dir() / "files" / run["id"], ignore_errors=True)
    return {"deleted": exp["id"], "runs": len(exp["runs"])}


# ---- 실행 기록 ----

def create_run(experiment_id, status="queued", source="poschat", **fields):
    if status not in STATUSES:
        raise LabError("알 수 없는 상태입니다.")
    get_experiment(experiment_id, runs=False)
    now = time.time()
    rid = "run-" + uuid.uuid4().hex[:10]
    with _lock:
        con = _db()
        with con:
            seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM runs WHERE experiment_id=?",
                              (experiment_id,)).fetchone()[0]
            con.execute("INSERT INTO runs(id, experiment_id, seq, status, source, created, updated) VALUES(?,?,?,?,?,?,?)",
                        (rid, experiment_id, seq, status, source, now, now))
            con.execute("UPDATE experiments SET updated=? WHERE id=?", (now, experiment_id))
    if fields:
        return update_run(rid, **fields)
    return get_run(rid)


RUN_FIELDS = ("name", "status", "started", "ended", "seconds", "command", "command_template", "cwd", "params", "code",
              "env", "inputs", "outputs", "exit_code", "metrics", "notes", "log_tail", "locations", "code_run_id")


def update_run(rid, **fields):
    sets, args = [], []
    for k, v in fields.items():
        if k not in RUN_FIELDS:
            continue
        if k == "status" and v not in STATUSES:
            raise LabError("알 수 없는 상태입니다.")
        if k in JSON_FIELDS:
            v = json.dumps(v if v is not None else {}, ensure_ascii=False, allow_nan=False, default=str)
        elif k in ("notes", "log_tail", "command", "command_template", "name", "cwd"):
            v = str(v or "")[:MAX_TEXT]
        sets.append(f"{k}=?")
        args.append(v)
    if not sets:
        return get_run(rid)
    now = time.time()
    with _lock:
        con = _db()
        with con:
            cur = con.execute(f"UPDATE runs SET {', '.join(sets)}, updated=? WHERE id=?", (*args, now, str(rid)))
            if cur.rowcount == 0:
                raise LabError("실행 기록을 찾지 못했습니다.")
            con.execute("UPDATE experiments SET updated=? WHERE id=(SELECT experiment_id FROM runs WHERE id=?)",
                        (now, str(rid)))
    return get_run(rid)


def get_run(rid):
    with _lock:
        r = _db().execute("SELECT * FROM runs WHERE id=?", (str(rid),)).fetchone()
    if r is None:
        raise LabError("실행 기록을 찾지 못했습니다.")
    return _row(r)


def get_runs(run_ids):
    out = []
    for rid in run_ids:
        out.append(get_run(rid))
    return out


def find_run_by_code_run(code_run_id):
    with _lock:
        r = _db().execute("SELECT * FROM runs WHERE code_run_id=?", (str(code_run_id),)).fetchone()
    return _row(r) if r else None


def delete_run(rid):
    run = get_run(rid)
    with _lock:
        con = _db()
        with con:
            con.execute("DELETE FROM runs WHERE id=?", (run["id"],))
    shutil.rmtree(lab_dir() / "files" / run["id"], ignore_errors=True)
    return {"deleted": run["id"]}


def recover(now=None):
    """앱을 켤 때: 실행 중·대기로 남은 Run을 '중단됨'으로 바꾼다(지우지 않는다). 바꾼 수를 돌려준다."""
    now = now or time.time()
    with _lock:
        con = _db()
        with con:
            cur = con.execute("UPDATE runs SET status='interrupted', ended=COALESCE(ended, ?), updated=?, "
                              "notes=CASE WHEN notes='' THEN ? ELSE notes || char(10) || ? END "
                              "WHERE status IN ('running', 'queued')",
                              (now, now, "앱이 실행 중에 종료되어 결과가 완전하지 않을 수 있습니다.",
                               "앱이 실행 중에 종료되어 결과가 완전하지 않을 수 있습니다."))
    return cur.rowcount


_recovered = set()


def recover_once():
    """이 프로세스에서 데이터 폴더마다 한 번만 recover(앱을 켠 뒤 처음 Lab을 열 때)."""
    with _lock:
        key = str(lab_dir())
        if key in _recovered:
            return 0
        _recovered.add(key)
        return recover()


def close():
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except sqlite3.Error:
                pass
        _conn = _conn_path = None
