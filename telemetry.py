# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""관측(Observability): LLM 호출·MCP 도구 호출·에이전트 실행·답변 평가를 이 기기에 기록하고 모은다.

<데이터 폴더>/telemetry/events.jsonl (90일 보관). 내용(질문·답변·문서·도구 결과)은 남기지 않고 메타데이터만 남긴다.
    llm_call   {mode, model, ms, ok, error, input_tokens, output_tokens, stream, retries}
    tool_call  {server, tool, connector, kind, ok, ms, attempts, approval}   (connectors.on_event)
    agent_run  {mode: chat|agent, model, ms, outcome: done|error|cancelled, steps, tools}
    feedback   {model, rating: 1|-1}
    eval       {model, set, score, passed, ms}

비용은 앱 문서에 근거가 있는 POSTECH GenAI 크레딧만 추정한다(Claude Sonnet 5.5: 입력 약 250토큰·출력 약 75토큰이 1크레딧,
호출마다 기본 약 24크레딧, Opus는 두 배). 근거가 없는 모델은 '추정 불가'다. config["telemetry"]["rates"]로 사용자가 정할 수 있다.

Langfuse 내보내기(선택, 기본 꺼짐): config["telemetry"]["langfuse"] = {"enabled", "host", "include_content"}와
secret_store "langfuse:public_key"·"langfuse:secret_key". /api/public/ingestion으로 메타데이터만 보낸다. include_content를
따로 켜면 질문·답변 앞부분(2000자)을 비밀·이메일을 가린 뒤 함께 보낸다(이 기기의 events.jsonl에는 여전히 남기지 않는다).
"""
import base64
import collections
import datetime as dt
import json
import threading
import time
import uuid

import privacy
import secret_store
import storage

KEEP_DAYS = 90
DOCUMENTED_RATES = {
    # 설정 창·사용법 가이드에 적힌 POSTECH GenAI 크레딧 기준
    "claude-sonnet-5-5": {"base": 24, "input_per_credit": 250, "output_per_credit": 75},
    "claude-opus-5-5": {"base": 48, "input_per_credit": 125, "output_per_credit": 37.5},
}
_lock = threading.Lock()
_queue = collections.deque(maxlen=2000)   # Langfuse로 보낼 이벤트
_export = {"last_error": "", "sent": 0, "last_sent": 0}
enabled = True   # 사용량·진단 기록(기능 플래그 observability)
config_getter = None


def events_path():
    return storage.APP_DIR / "telemetry" / "events.jsonl"


def _config():
    try:
        return config_getter() if config_getter else storage.load_config()
    except Exception:
        return {}


def is_enabled():
    if not enabled:
        return False
    features = _config().get("features") or {}
    return bool(features.get("observability", True))


def record(event_type, **fields):
    if not is_enabled():
        return
    event = {"ts": round(time.time(), 3), "type": event_type, **fields}
    with _lock:
        try:
            path = events_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass
    lf = (_config().get("telemetry") or {}).get("langfuse") or {}
    if lf.get("enabled"):
        _queue.append(event)


def on_llm_call(info, prompt=None, reply=None):
    """api.on_trace가 부른다."""
    fields = {k: info.get(k) for k in ("mode", "model", "ms", "ok", "error", "input_tokens", "output_tokens", "stream",
                                       "retries")}
    record("llm_call", **fields)
    lf = (_config().get("telemetry") or {}).get("langfuse") or {}
    if lf.get("enabled") and lf.get("include_content") and _queue and _queue[-1].get("type") == "llm_call":
        _queue[-1] = dict(_queue[-1], input=privacy.redact_text(str(prompt or "")[:2000], emails=True),
                          output=privacy.redact_text(str(reply or "")[:2000], emails=True))


def on_tool_call(event):
    """connectors.on_event가 부른다."""
    record("tool_call", **{k: v for k, v in event.items() if k != "type"})


def prune(now=None):
    cutoff = (now or time.time()) - KEEP_DAYS * 86400
    with _lock:
        try:
            lines = events_path().read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        kept = [line for line in lines if _ts(line) >= cutoff]
        if len(kept) != len(lines):
            tmp = events_path().with_suffix(".tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            tmp.replace(events_path())


def _ts(line):
    try:
        return float(json.loads(line).get("ts", 0))
    except (ValueError, AttributeError):
        return 0


def load(days=30, now=None):
    cutoff = (now or time.time()) - days * 86400
    try:
        lines = events_path().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("ts", 0) >= cutoff:
            out.append(event)
    return out


# ---- 비용 ----

def credit_estimate(model, input_tokens, output_tokens, calls=1, rates=None):
    """POSTECH 크레딧 추정. 근거가 없는 모델이면 None."""
    rate = (rates or {}).get(model) or DOCUMENTED_RATES.get(model)
    if not rate:
        return None
    return round(calls * rate["base"] + (input_tokens or 0) / rate["input_per_credit"]
                 + (output_tokens or 0) / rate["output_per_credit"], 1)


# ---- 모으기 ----

def _p95(values):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]


def summary(days=30, now=None):
    events = load(days, now)
    rates = (_config().get("telemetry") or {}).get("rates") or {}
    models, tools, agent, feedback, evals = {}, {}, {"chat": [], "agent": []}, {}, {}
    for e in events:
        t = e.get("type")
        if t == "llm_call":
            m = models.setdefault(e.get("model") or "?", {"calls": 0, "errors": 0, "ms": [], "input_tokens": 0,
                                                         "output_tokens": 0, "token_calls": 0, "retries": 0, "error_types": {}})
            m["calls"] += 1
            m["errors"] += not e.get("ok", True)
            m["retries"] += int(e.get("retries") or 0)
            if e.get("ms") is not None:
                m["ms"].append(e["ms"])
            if e.get("input_tokens") or e.get("output_tokens"):
                m["token_calls"] += 1
                m["input_tokens"] += int(e.get("input_tokens") or 0)
                m["output_tokens"] += int(e.get("output_tokens") or 0)
            if e.get("error"):
                m["error_types"][e["error"]] = m["error_types"].get(e["error"], 0) + 1
        elif t == "tool_call":
            key = f"{e.get('server')}.{e.get('tool')}"
            x = tools.setdefault(key, {"calls": 0, "ok": 0, "ms": [], "denied": 0, "retries": 0, "kind": e.get("kind")})
            x["calls"] += 1
            x["ok"] += bool(e.get("ok"))
            x["denied"] += e.get("approval") in ("denied", "blocked")
            x["retries"] += max(0, int(e.get("attempts") or 1) - 1)
            if e.get("ms") is not None:
                x["ms"].append(e["ms"])
        elif t == "agent_run":
            agent.setdefault(e.get("mode") or "chat", []).append(e)
        elif t == "feedback":
            f = feedback.setdefault(e.get("model") or "?", {"up": 0, "down": 0})
            f["up" if e.get("rating", 0) > 0 else "down"] += 1
        elif t == "eval":
            x = evals.setdefault(e.get("model") or "?", {"runs": 0, "score": 0.0, "passed": 0, "cases": 0, "ms": []})
            x["runs"] += 1
            x["score"] += float(e.get("score") or 0)
            x["passed"] += int(e.get("passed") or 0)
            x["cases"] += int(e.get("cases") or 0)
            if e.get("ms") is not None:
                x["ms"].append(e["ms"])
    model_rows = []
    for name, m in sorted(models.items(), key=lambda kv: -kv[1]["calls"]):
        est = credit_estimate(name, m["input_tokens"], m["output_tokens"], m["calls"], rates)
        fb = feedback.get(name, {"up": 0, "down": 0})
        ev = evals.get(name)
        model_rows.append({
            "model": name, "calls": m["calls"], "errors": m["errors"],
            "error_rate": round(m["errors"] / m["calls"], 3) if m["calls"] else 0,
            "avg_ms": round(sum(m["ms"]) / len(m["ms"])) if m["ms"] else None, "p95_ms": _p95(m["ms"]),
            "input_tokens": m["input_tokens"], "output_tokens": m["output_tokens"], "token_calls": m["token_calls"],
            "retries": m["retries"], "credits": est, "error_types": m["error_types"],
            "feedback_up": fb["up"], "feedback_down": fb["down"],
            "eval_score": round(ev["score"] / ev["runs"], 3) if ev and ev["runs"] else None,
        })
    for name in sorted((set(evals) | set(feedback)) - set(models)):  # 평가만 돌렸거나 평가(👍👎)만 있는 모델
        ev = evals.get(name)
        model_rows.append({"model": name, "calls": 0, "errors": 0, "error_rate": 0, "avg_ms": None, "p95_ms": None,
                           "input_tokens": 0, "output_tokens": 0, "token_calls": 0, "retries": 0, "credits": None,
                           "error_types": {}, "feedback_up": feedback.get(name, {}).get("up", 0),
                           "feedback_down": feedback.get(name, {}).get("down", 0),
                           "eval_score": round(ev["score"] / ev["runs"], 3) if ev and ev["runs"] else None})
    tool_rows = [{"tool": k, "kind": v["kind"], "calls": v["calls"], "ok": v["ok"],
                  "success_rate": round(v["ok"] / v["calls"], 3) if v["calls"] else 0, "denied": v["denied"],
                  "retries": v["retries"], "avg_ms": round(sum(v["ms"]) / len(v["ms"])) if v["ms"] else None}
                 for k, v in sorted(tools.items(), key=lambda kv: -kv[1]["calls"])]
    runs = {}
    for mode, items in agent.items():
        if not items:
            continue
        done = sum(1 for r in items if r.get("outcome") == "done")
        runs[mode] = {"runs": len(items), "done": done, "success_rate": round(done / len(items), 3),
                      "errors": sum(1 for r in items if r.get("outcome") == "error"),
                      "avg_steps": round(sum(int(r.get("steps") or 0) for r in items) / len(items), 1),
                      "avg_ms": round(sum(int(r.get("ms") or 0) for r in items) / len(items))}
    credits = [r["credits"] for r in model_rows if r["credits"] is not None]
    return {"days": days, "models": model_rows, "tools": tool_rows, "agent": runs, "events": len(events),
            "credits_total": round(sum(credits), 1) if credits else None,
            "credits_unknown_models": [r["model"] for r in model_rows if r["credits"] is None and r["calls"]],
            "export": dict(_export, pending=len(_queue))}


# ---- Langfuse ----

def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def to_langfuse(event):
    """이벤트 하나 → Langfuse ingestion 배치 항목들."""
    trace_id = uuid.uuid4().hex
    end = event["ts"]
    start = end - (event.get("ms") or 0) / 1000
    meta = {k: v for k, v in event.items() if k not in ("ts", "type", "input", "output")}
    items = [{"id": uuid.uuid4().hex, "timestamp": _iso(end), "type": "trace-create",
              "body": {"id": trace_id, "name": event["type"], "timestamp": _iso(start), "metadata": meta,
                       "tags": ["poschat"]}}]
    if event["type"] == "llm_call":
        body = {"id": uuid.uuid4().hex, "traceId": trace_id, "name": "llm_call", "model": event.get("model"),
                "startTime": _iso(start), "endTime": _iso(end), "metadata": meta,
                "usage": {"input": event.get("input_tokens") or 0, "output": event.get("output_tokens") or 0, "unit": "TOKENS"},
                "level": "DEFAULT" if event.get("ok", True) else "ERROR"}
        if "input" in event:
            body.update(input=event["input"], output=event.get("output"))
        items.append({"id": uuid.uuid4().hex, "timestamp": _iso(end), "type": "generation-create", "body": body})
    elif event["type"] in ("tool_call", "agent_run"):
        items.append({"id": uuid.uuid4().hex, "timestamp": _iso(end), "type": "span-create",
                      "body": {"id": uuid.uuid4().hex, "traceId": trace_id, "name": event["type"], "startTime": _iso(start),
                               "endTime": _iso(end), "metadata": meta,
                               "level": "DEFAULT" if event.get("ok", event.get("outcome") != "error") else "ERROR"}})
    elif event["type"] == "feedback":
        items.append({"id": uuid.uuid4().hex, "timestamp": _iso(end), "type": "score-create",
                      "body": {"id": uuid.uuid4().hex, "traceId": trace_id, "name": "user_feedback",
                               "value": event.get("rating", 0)}})
    return items


def export_pending(http=None, max_batch=100):
    """모아 둔 이벤트를 Langfuse로 보낸다. 보낸 개수. 실패하면 이벤트를 큐에 되돌린다."""
    lf = (_config().get("telemetry") or {}).get("langfuse") or {}
    if not lf.get("enabled") or not _queue:
        return 0
    host = str(lf.get("host") or "").rstrip("/")
    public, secret = secret_store.get("langfuse:public_key"), secret_store.get("langfuse:secret_key")
    if not host.startswith("https://") or not public or not secret:
        _export["last_error"] = "Langfuse 주소(https)와 공개·비밀 키를 넣으세요."
        return 0
    batch_events = [_queue.popleft() for _ in range(min(max_batch, len(_queue)))]
    batch = [item for e in batch_events for item in to_langfuse(e)]
    auth = base64.b64encode(f"{public}:{secret}".encode()).decode("ascii")
    if http is None:
        from office_mcp import http
    try:
        r = http("POST", f"{host}/api/public/ingestion", json={"batch": batch},
                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"}, timeout=20)
        ok = r.status_code in (200, 201, 207)
    except Exception as e:
        ok, r = False, None
        _export["last_error"] = privacy.redact_text(f"{type(e).__name__}: {e}")
    if not ok:
        for e in reversed(batch_events):
            _queue.appendleft(e)
        if r is not None:
            _export["last_error"] = f"HTTP {r.status_code}"
        return 0
    _export.update(last_error="", sent=_export["sent"] + len(batch_events), last_sent=time.time())
    return len(batch_events)
