# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""손익분기 실험(1.17 뒤): 같은 요청을 '프런티어 직접 · 경량 혼자 · 경량 + 상담'으로 실제 모델에 보내 서버가 알려 준 토큰과 품질을 재고,
그 기록으로 adaptive_cost의 토큰 분포·승격 확률을 맞추고 어떤 결정 함수(정책)가 가장 싼지(품질 조건 안에서) 찾는다.

    run      실제 모델을 부른다(Cloud 비용). 결과는 JSONL에 한 줄씩 덧붙이고, 다시 돌리면 끝난 칸은 건너뛴다(이어 하기).
    analyze  JSONL과 단가로 분석한다(모델을 부르지 않는다): 실측 프로필, 비용 모델의 예측 오차, 정책별 비용·성공률(dev/test).

키: 개인 Claude API는 ANTHROPIC_API_KEY, POSTECH GenAI는 POSTECH_GENAI_API_KEY(없으면 앱 설정 config.json의 키).

    python tools/breakeven_experiment.py run --mode anthropic --light claude-haiku-5-5 --frontier claude-opus-5-5 \\
        --split dev --contexts 0,4000,16000 --cache off,on --budget-calls 600 --yes --out exp.jsonl
    python tools/breakeven_experiment.py analyze --in exp.jsonl --light-price 1,5,0.1,1.25 --frontier-price 5,25,0.5,6.25

실험 칸 하나 = (사례, 덧붙인 대화 길이, 경로, 캐시, 반복). 경로:
    frontier  프런티어가 바로 답한다(기준).
    light     경량 모델 혼자(상담 안내 없음). 앱에서는 검증에 실패하면 프런티어로 승격되므로, 분석은 그때 같은 칸의 frontier 비용·품질을 더한다.
    consult   경량 모델 + 상담 안내(앱의 AdaptiveEngine을 그대로 돌린다). 경량 모델이 상담할지 스스로 정한다(상담 비율도 잰다).
덧붙인 대화(--contexts): 벤치마크 요청은 짧아서(T 작음) 긴 대화의 손익분기를 볼 수 없다. 그래서 다른 사례로 만든 지난 대화를 앞에 붙여
요청 길이 T를 바꾼다(관련 없는 대화라 실제 대화보다 쉬울 수 있다 — 한계).
품질: 벤치마크 채점(규칙·수치·선택: 코드 시험). --judge를 켜면 프런티어가 경량 답을 프런티어 답·정답과 비교해 1~5점을 매긴다
(같은 계열 모델이 채점하는 편향이 있다 — 참고 값).
"""
import argparse
import json
import os
import statistics
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import adaptive_benchmark as bench  # noqa: E402
import adaptive_cost  # noqa: E402
import adaptive_engine  # noqa: E402
import adaptive_router  # noqa: E402
import telemetry  # noqa: E402

PATHS = ("frontier", "light", "consult")
CONSULT_CATEGORIES_SKIP = ("agent",)   # 에이전트 단계(JSON)는 앱이 상담을 쓰지 않는다
JUDGE_RULE = (
    "[채점 — 당신은 채점자입니다]\n아래 [평가할 답]이 사용자 요청을 얼마나 잘 해결했는지 [참고 답]과 [기준 정답](있으면)에 비추어 1~5점으로 매기세요.\n"
    "5: 참고 답만큼 정확하고 충분함, 4: 작은 빠짐, 3: 쓸 만하나 중요한 빠짐·부정확, 2: 대부분 틀림, 1: 답이 아님.\n"
    '설명 없이 JSON 한 줄만: {"score": 1~5, "why": "한 문장"}')


class BudgetExceeded(BaseException):
    """Cloud 호출 상한. 엔진이 모델 오류로 삼키지 않게 BaseException."""


# ---- 실행 ----

def history_pad(cases, tokens, seed_id):
    """요청 앞에 붙일 지난 대화(다른 사례의 요청·자료로 만든다). 같은 입력이면 같은 글."""
    if tokens <= 0:
        return ""
    others = [c for c in cases if c["id"] != seed_id]
    start = sum(map(ord, seed_id)) % len(others)
    lines, i = ["[이전 대화]"], 0
    while adaptive_router.estimate_tokens("\n".join(lines)) < tokens:
        c = others[(start + i) % len(others)]
        lines.append("사용자: " + c["prompt"] + ("\n" + c["context"]["text"] if c.get("context") else ""))
        lines.append("어시스턴트: " + (c.get("reference") or "확인했습니다. 이어서 도와드릴게요.")[:1200])
        i += 1
    return "\n".join(lines) + "\n\n"


class Caller:
    """api.ask를 부르고(사용량 포함) 호출 수를 센다. ask를 바꿔 끼우면 시험에서 가짜 모델을 쓸 수 있다."""

    def __init__(self, mode, key, budget_calls, ask=None):
        import api

        self.api = api
        self.mode, self.key, self.budget, self.calls = mode, key, budget_calls, 0
        self.ask = ask or api.ask

    def __call__(self, prompt, model, on_delta=None, images=None, cache_prefix=0):
        if self.calls >= self.budget:
            raise BudgetExceeded()
        self.calls += 1
        settings = self.api.ApiSettings.from_config({"api_mode": self.mode})
        settings.model, settings.stream = model, False
        usage = {}
        text = self.ask(self.key, prompt, settings=settings, timeout=300, usage_out=usage,
                        **({"cache_prefix": cache_prefix} if cache_prefix else {}))
        return text, usage


def run_cell(caller, c, prompt, path, cache, light, frontier):
    """칸 하나를 앱의 엔진으로 돌린다. 경로는 라우터 대신 고정하고, 승격은 끈다(승격 비용은 분석이 frontier 칸으로 더한다)."""
    config = {"adaptive": {"enabled": True, "policy": "balanced", "tiered": True, "escalation": False, "consult": True,
                           "consult_max": 1, "local_retries": 0, "prompt_cache": cache}}
    rt = types.SimpleNamespace(candidate=lambda m: (None, "실험"), provider=lambda: None)
    engine = adaptive_engine.AdaptiveEngine(config, rt, caller, frontier, True, light_model=light)
    a_task = adaptive_router.analyze(prompt, c["prompt"], "agent_step" if c["category"] == "agent" else "chat",
                                     attachments=bool(c.get("context")))
    if path == "frontier":
        route = adaptive_router.Route(provider="cloud", model=frontier, tier="frontier", reason_code="experiment")
    else:
        route = adaptive_router.Route(provider="light", model=light, tier="light", consult=path == "consult",
                                      reason_code="light_consult" if path == "consult" else "light")
    engine._route = lambda a, purpose="chat": route
    purpose = "agent_step" if c["category"] == "agent" else "chat"
    start = time.monotonic()
    error = ""
    try:
        text = engine.ask(prompt, purpose=purpose, task_text=c["prompt"], attachments=bool(c.get("context")))
    except adaptive_engine.AdaptiveError as e:
        text, error = "", str(e)[:200]
    s = engine.summary() or {}
    sc, failed = bench.score(text, c)
    gate = s.get("gate") or {}
    return {"text": text, "score": sc, "failed": failed[:5], "error": error, "ms": int((time.monotonic() - start) * 1000),
            "attempts": [{k: t.get(k) for k in ("provider", "model", "ok", "ms", "usage", "consult", "after_consult")}
                         for t in s.get("attempts") or []],
            "consulted": bool(s.get("consulted")), "status": s.get("status"),
            "gate_ok": gate.get("ok") if gate else None, "gate_verifiable": gate.get("verifiable") if gate else None,
            "task": a_task.task, "difficulty": a_task.difficulty, "rule_tier": rule_choice(a_task)}


def rule_choice(a, policy="balanced"):
    """앱의 규칙(tier)이 이 요청에 고를 경로(경량 모델이 있을 때, 로컬 없이)."""
    route = adaptive_router.Route(provider="cloud", model="F", policy=policy, tier="frontier")
    light = adaptive_router.Candidate(provider="cloud", model="L")
    out = adaptive_router.tier(route, a, light, {"consult": True, "consult_max": 1})
    return "frontier" if out.provider == "cloud" else ("consult" if out.reason_code == "light_consult" else "light")


def judge(caller, frontier, c, prompt, answer, reference_answer):
    body = (JUDGE_RULE + "\n\n[사용자 요청]\n" + prompt[-6000:] + "\n\n[참고 답]\n" + reference_answer[:4000]
            + ("\n\n[기준 정답]\n" + c["reference"][:2000] if c.get("reference") else "") + "\n\n[평가할 답]\n" + answer[:4000])
    text, usage = caller(body, frontier)
    try:
        start = text.index("{")
        score = int(json.loads(text[start:text.index("}", start) + 1]).get("score"))
        return {"score": max(1, min(5, score)), "usage": usage}
    except (ValueError, TypeError):
        return {"score": None, "usage": usage, "raw": text[:200]}


def cell_key(r):
    return (r["case"], r["context"], r["path"], r["cache"], r["rep"])


def run(args, ask=None, key=None):
    data = bench.load()
    cases = [c for c in data["cases"] if args.split == "all" or c["split"] == args.split]
    if args.categories:
        cases = [c for c in cases if c["category"] in args.categories.split(",")]
    if args.limit:
        cases = cases[:args.limit]
    contexts = [int(x) for x in str(args.contexts).split(",") if x.strip()]
    caches = [x.strip() == "on" for x in str(args.cache).split(",") if x.strip()]
    paths = [p for p in args.paths.split(",") if p in PATHS]
    key = key if key is not None else (os.environ.get("ANTHROPIC_API_KEY") if args.mode == "anthropic"
                                       else os.environ.get("POSTECH_GENAI_API_KEY")) or _config_key(args.mode)
    if not key and ask is None:
        print("API 키가 없습니다. ANTHROPIC_API_KEY 또는 POSTECH_GENAI_API_KEY 환경 변수를 넣으세요.", file=sys.stderr)
        return 2
    cells = len(cases) * len(contexts) * args.repeats * sum(len(caches) if p != "frontier" else 1 for p in paths)
    print(f"칸 {cells}개(사례 {len(cases)} × 대화 길이 {contexts} × 반복 {args.repeats}), 칸마다 Cloud 호출 1~3번"
          + (" + 채점 1번" if args.judge else "") + f", 상한 {args.budget_calls}번")
    if not args.yes or args.budget_calls <= 0:
        print("Cloud 비용이 듭니다. --budget-calls N과 --yes를 주세요.", file=sys.stderr)
        return 2
    out = Path(args.out)
    done = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                done[cell_key(r)] = r
            except ValueError:
                pass
    telemetry.enabled = False                                  # 앱의 사용량·진단 기록에 섞지 않는다
    adaptive_router.record_outcome = lambda *a, **k: None      # 앱의 측정 기록(stats.json)도 건드리지 않는다
    caller = Caller(args.mode, key, args.budget_calls, ask)
    n = 0
    try:
        with out.open("a", encoding="utf-8") as f:
            for rep in range(args.repeats):
                for ctx in contexts:
                    for c in cases:
                        prompt = history_pad(data["cases"], ctx, c["id"]) + bench.build_prompt(c)
                        t_est = adaptive_router.estimate_tokens(prompt)
                        for path in paths:
                            if path == "consult" and c["category"] in CONSULT_CATEGORIES_SKIP:
                                continue
                            for cache in (caches if path != "frontier" else [caches[0]]):
                                k = (c["id"], ctx, path, cache, rep)
                                if k in done:
                                    continue
                                cell = run_cell(caller, c, prompt, path, cache, args.light, args.frontier)
                                ref = done.get((c["id"], ctx, "frontier", caches[0], rep))
                                if args.judge and path != "frontier" and ref and cell["text"]:
                                    cell["judge"] = judge(caller, args.frontier, c, prompt, cell["text"], ref.get("text") or "")
                                if args.judge and path == "frontier":
                                    cell["judge"] = {"score": 5}
                                row = {"case": c["id"], "category": c["category"], "split": c["split"], "context": ctx,
                                       "path": path, "cache": cache, "rep": rep, "T": t_est, "light": args.light,
                                       "frontier": args.frontier, "mode": args.mode, **cell}
                                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                                f.flush()
                                done[k] = row
                                n += 1
                                if sys.stdout.isatty():
                                    print(f"\r{n}칸 · Cloud 호출 {caller.calls}", end="", flush=True)
    except BudgetExceeded:
        print(f"\nCloud 호출 상한({args.budget_calls})에 닿아 멈췄습니다. 같은 --out으로 다시 돌리면 이어서 합니다.")
    print(f"\n끝: 새 칸 {n}개, Cloud 호출 {caller.calls}번 → {out}")
    return 0


def _config_key(mode):
    try:
        import storage

        cfg = storage.load_config()
        return cfg.get("anthropic_api_key" if mode == "anthropic" else "api_key") or ""
    except Exception:
        return ""


# ---- 분석 ----

def parse_price(text):
    v = [float(x) for x in str(text).split(",") if x.strip() != ""]
    if len(v) < 2:
        raise ValueError("단가는 입력,출력[,캐시 읽기,캐시 쓰기[,호출당]] (100만 토큰당)")
    return adaptive_cost.Prices(v[0], v[1], v[2] if len(v) > 2 else None, v[3] if len(v) > 3 else None, v[4] if len(v) > 4 else 0.0)


def attempt_cost(t, pl, pf):
    u = t.get("usage") or {}
    p = pl if t.get("provider") == "light" else pf
    cr, cw = int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0)
    regular = max(0, int(u.get("input_tokens") or 0) - cr - cw)   # 서버의 input_tokens는 캐시 몫을 포함한다(api.py)
    return adaptive_cost.call_cost(p, regular, int(u.get("output_tokens") or 0), cr, cw)


def quality(r, use_judge=False):
    if use_judge and (r.get("judge") or {}).get("score") is not None:
        return r["judge"]["score"] / 5
    return float(r.get("score") or 0)


def units(rows, cache):
    """(사례, 대화 길이, 반복)마다 세 경로를 모은다. 앱처럼 경량 답이 검증에 실패하면 프런티어로 승격된 것으로 친다."""
    by = {}
    for r in rows:
        if r["path"] != "frontier" and r["cache"] != cache:
            continue
        by.setdefault((r["case"], r["context"], r["rep"]), {})[r["path"]] = r
    return [u for u in by.values() if "frontier" in u and "light" in u]


def outcome(u, path, pl, pf, use_judge=False):
    """(비용, 품질, 성공) — 승격 포함. consult가 없는 칸(에이전트)은 light로."""
    f = u["frontier"]
    f_cost = sum(attempt_cost(t, pl, pf) for t in f["attempts"])
    if path == "frontier":
        return f_cost, quality(f, use_judge), f["score"] == 1.0
    r = u.get(path) or u["light"]
    cost = sum(attempt_cost(t, pl, pf) for t in r["attempts"])
    if r.get("gate_ok") is False or not r.get("text"):     # 앱은 여기서 프런티어로 다시 답한다
        return cost + f_cost, quality(f, use_judge), f["score"] == 1.0
    return cost, quality(r, use_judge), r["score"] == 1.0


def fit_profile(rows):
    """실측 토큰 분포(작업별·전체)와 승격 확률·상담 비율."""
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.mean(xs)) if xs else None

    groups = {}
    for r in rows:
        groups.setdefault(r.get("task") or "?", []).append(r)
    groups["*"] = rows
    out = {}
    for g, rs in groups.items():
        fr = [r for r in rs if r["path"] == "frontier"]
        lr = [r for r in rs if r["path"] == "light"]
        cr = [r for r in rs if r["path"] == "consult"]
        consulted = [r for r in cr if r.get("consulted")]
        cons_att = [t for r in consulted for t in r["attempts"] if t.get("consult")]
        first = [r["attempts"][0] for r in consulted if r["attempts"]]
        final = [r["attempts"][-1] for r in consulted if r["attempts"] and r["attempts"][-1].get("after_consult")]
        out[g] = {
            "n": len(rs),
            "O": mean([(t.get("usage") or {}).get("output_tokens") for r in fr for t in r["attempts"][:1]]),
            "O_light": mean([(t.get("usage") or {}).get("output_tokens") for r in lr for t in r["attempts"][:1]]),
            "Q": mean([(t.get("usage") or {}).get("output_tokens") for t in first]),
            "C": mean([(t.get("usage") or {}).get("input_tokens") for t in cons_att]),
            "A": mean([(t.get("usage") or {}).get("output_tokens") for t in cons_att]),
            "O_after_consult": mean([(t.get("usage") or {}).get("output_tokens") for t in final]),
            "p_escalate_light": round(sum(1 for r in lr if r.get("gate_ok") is False or not r.get("text")) / len(lr), 3) if lr else None,
            "p_escalate_consult": round(sum(1 for r in cr if r.get("gate_ok") is False or not r.get("text")) / len(cr), 3) if cr else None,
            "consult_rate": round(len(consulted) / len(cr), 3) if cr else None,
            "cache_hit": round(sum(int((t.get("usage") or {}).get("cache_read_input_tokens") or 0) for r in rs for t in r["attempts"])
                               / max(1, sum(int((t.get("usage") or {}).get("input_tokens") or 0) for r in rs for t in r["attempts"])), 3),
        }
    return out


def profile_for(fit, task, T):
    g = fit.get(task) if (fit.get(task) or {}).get("n", 0) >= 10 else fit.get("*")
    d = adaptive_cost.Profile(T=T)
    if not g:
        return d, 0.15, 1.0
    for k in ("O", "Q", "C", "A"):
        if g.get(k):
            setattr(d, k, g[k])
    d.R = adaptive_router.estimate_tokens(adaptive_engine.CONSULT_RULE)
    return d, (g.get("p_escalate_light") if g.get("p_escalate_light") is not None else 0.15), \
        (g.get("consult_rate") if g.get("consult_rate") is not None else 1.0)


def predicted(path, prof, pl, pf, p_esc, cache, consult_rate=1.0):
    """비용 모델의 예측. consult_rate<1이면 '상담을 안 하고 혼자 답한 경우'를 섞는다(1.17 함수는 언제나 상담한다고 본다)."""
    if path == "frontier":
        return adaptive_cost.frontier_cost(pf, prof)
    if path == "light":
        return adaptive_cost.light_cost(pl, pf, prof, p_esc)
    alone = adaptive_cost.call_cost(pl, prof.T + prof.R, prof.O) + p_esc * adaptive_cost.frontier_cost(pf, prof)
    return consult_rate * adaptive_cost.consult_cost(pl, pf, prof, cache) + (1 - consult_rate) * alone


POLICIES = {
    "frontier": "언제나 프런티어",
    "rules": "1.17 규칙(tier)",
    "breakeven_default": "규칙 + 1.17 손익분기(기본 프로필, 상담은 언제나 한다고 봄)",
    "breakeven_fitted": "규칙 + 손익분기(실측 프로필·승격 확률·상담 비율)",
    "table": "작업×길이 표: dev에서 품질 조건을 지키는 가장 싼 경로",
    "oracle": "칸마다 가장 싼 경로(품질 유지, 사후 — 하한)",
}


def choose(policy, u, fit, pl, pf, cache, table=None):
    r = u["light"]
    rule = r.get("rule_tier") or "frontier"
    has_consult = "consult" in u
    if rule == "consult" and not has_consult:
        rule = "light"
    if policy == "frontier":
        return "frontier"
    if policy == "rules":
        return rule
    if policy in ("breakeven_default", "breakeven_fitted"):
        if rule == "frontier":
            return "frontier"
        if policy == "breakeven_default":
            prof, p_esc, q = adaptive_cost.Profile(T=r["T"]), adaptive_engine.DEFAULT_P_ESCALATE, 1.0
            prof.R = adaptive_router.estimate_tokens(adaptive_engine.CONSULT_RULE)
        else:
            prof, p_esc, q = profile_for(fit, r.get("task"), r["T"])
        cost_rule = predicted(rule, prof, pl, pf, p_esc, cache, q)
        return rule if cost_rule < adaptive_cost.frontier_cost(pf, prof) else "frontier"
    if policy == "table":
        return (table or {}).get(table_key(r), rule)
    raise ValueError(policy)


def table_key(r):
    band = "short" if r["T"] < 2000 else "mid" if r["T"] < 10000 else "long"
    return f"{r.get('task')}|{band}"


def learn_table(us, pl, pf, max_drop, use_judge):
    """dev 칸으로 (작업, 길이대)마다 품질 하락이 max_drop 이내인 경로 중 가장 싼 것을 고른다."""
    groups = {}
    for u in us:
        groups.setdefault(table_key(u["light"]), []).append(u)
    table = {}
    for k, g in groups.items():
        base = [outcome(u, "frontier", pl, pf, use_judge) for u in g]
        base_q = statistics.mean(q for _, q, _ in base)
        best, best_cost = "frontier", sum(c for c, _, _ in base)
        for path in ("light", "consult"):
            res = [outcome(u, path, pl, pf, use_judge) for u in g]
            if statistics.mean(q for _, q, _ in res) >= base_q - max_drop and sum(c for c, _, _ in res) < best_cost:
                best, best_cost = path, sum(c for c, _, _ in res)
        table[k] = best
    return table


def evaluate(us, policy, fit, pl, pf, cache, use_judge, table=None, max_drop=0.02):
    cost = q = ok = 0.0
    picks = {"frontier": 0, "light": 0, "consult": 0}
    for u in us:
        if policy == "oracle":
            base = outcome(u, "frontier", pl, pf, use_judge)
            cands = [(outcome(u, p, pl, pf, use_judge), p) for p in ("frontier", "light", "consult") if p == "frontier" or p in u]
            fine = [x for x in cands if x[0][1] >= base[1] - max_drop]
            (c, qq, s), path = min(fine, key=lambda x: x[0][0])
        else:
            path = choose(policy, u, fit, pl, pf, cache, table)
            c, qq, s = outcome(u, path, pl, pf, use_judge)
        picks[path] = picks.get(path, 0) + 1
        cost += c
        q += qq
        ok += s
    n = max(1, len(us))
    return {"units": len(us), "cost": round(cost, 6), "quality": round(q / n, 4), "success": round(ok / n, 4), "picks": picks}


def calibration(rows, fit, pl, pf):
    """비용 모델의 예측과 실측 비용의 차이(경로별 평균 절대 오차 %). 기본 프로필과 실측 프로필을 비교한다."""
    out = {}
    for path in PATHS:
        errs = {"default": [], "fitted": []}
        for r in rows:
            if r["path"] != path or not r["attempts"]:
                continue
            actual = sum(attempt_cost(t, pl, pf) for t in r["attempts"])
            if path == "light" and (r.get("gate_ok") is False):
                continue   # 승격 비용은 칸 밖(분석이 더한다): 경량 호출 비용만 비교
            if actual <= 0:
                continue
            d = adaptive_cost.Profile(T=r["T"])
            d.R = adaptive_router.estimate_tokens(adaptive_engine.CONSULT_RULE)
            fp, _, q = profile_for(fit, r.get("task"), r["T"])
            pd = predicted(path, d, pl, pf, 0.0, r["cache"], 1.0)
            pfit = predicted(path, fp, pl, pf, 0.0, r["cache"], q if path == "consult" else 1.0)
            errs["default"].append(abs(pd - actual) / actual)
            errs["fitted"].append(abs(pfit - actual) / actual)
        out[path] = {k: round(statistics.mean(v), 3) if v else None for k, v in errs.items()} | {"n": len(errs["default"])}
    return out


def analyze(rows, pl, pf, max_drop=0.02, use_judge=False):
    rows = [r for r in rows if r.get("attempts") is not None]
    dev = [r for r in rows if r["split"] == "dev"]
    fit = fit_profile(dev or rows)
    report = {"rows": len(rows), "prices": {"light": pl.to_dict(), "frontier": pf.to_dict()}, "max_drop": max_drop,
              "judge": use_judge, "fit": fit, "calibration": calibration(rows, fit, pl, pf), "policies": {}}
    for cache in sorted({r["cache"] for r in rows if r["path"] != "frontier"}):
        dev_u = units(dev, cache)
        table = learn_table(dev_u, pl, pf, max_drop, use_judge) if dev_u else {}
        res = {}
        for split in ("dev", "test", "all"):
            us = units([r for r in rows if split == "all" or r["split"] == split], cache)
            if not us:
                continue
            res[split] = {p: evaluate(us, p, fit, pl, pf, cache, use_judge, table, max_drop) for p in POLICIES}
            base = res[split]["frontier"]
            for p, v in res[split].items():
                v["cost_vs_frontier"] = round(v["cost"] / base["cost"], 4) if base["cost"] else None
                v["quality_drop"] = round(base["quality"] - v["quality"], 4)
        report["policies"]["cache_on" if cache else "cache_off"] = {"by_split": res, "table": table}
    return report


def print_report(rep):
    print(f"칸 {rep['rows']}개 · 품질 하락 허용 {rep['max_drop']:.0%}" + (" · 채점자 점수 사용" if rep["judge"] else ""))
    g = rep["fit"].get("*") or {}
    print(f"실측(전체): 최종 답 O={g.get('O')} 경량 답={g.get('O_light')} 상담 요청 Q={g.get('Q')} 상담 입력 C={g.get('C')} "
          f"상담 답 A={g.get('A')} · 승격 확률 경량={g.get('p_escalate_light')} 상담={g.get('p_escalate_consult')} · "
          f"상담 비율={g.get('consult_rate')} · 캐시 적중={g.get('cache_hit')}")
    print("비용 모델 오차(평균 |예측-실측|/실측): " + ", ".join(
        f"{p} 기본 {v['default']} → 실측 {v['fitted']} (n={v['n']})" for p, v in rep["calibration"].items()))
    for cache, block in rep["policies"].items():
        for split, res in block["by_split"].items():
            print(f"\n[{cache} · {split}] {'정책':<20} {'비용/프런티어':>12} {'품질 하락':>9} {'성공률':>7}  선택(F/L/C)")
            for p, v in res.items():
                pk = v["picks"]
                print(f"  {p:<26} {v['cost_vs_frontier']!s:>10} {v['quality_drop']:>9} {v['success']:>7}  "
                      f"{pk.get('frontier', 0)}/{pk.get('light', 0)}/{pk.get('consult', 0)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", default="anthropic", choices=("anthropic", "chat_completions", "responses"))
    r.add_argument("--light", required=True)
    r.add_argument("--frontier", required=True)
    r.add_argument("--paths", default="frontier,light,consult")
    r.add_argument("--split", default="dev", choices=("dev", "test", "all"))
    r.add_argument("--categories", default="")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--contexts", default="0", help="앞에 붙일 지난 대화 길이(토큰), 쉼표로 여러 개")
    r.add_argument("--cache", default="off", help="off,on 중 쉼표로")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--judge", action="store_true")
    r.add_argument("--budget-calls", type=int, default=0)
    r.add_argument("--yes", action="store_true")
    r.add_argument("--out", default="breakeven-experiment.jsonl")
    a = sub.add_parser("analyze")
    a.add_argument("--in", dest="inp", required=True)
    a.add_argument("--light-price", required=True, help="입력,출력[,캐시 읽기,캐시 쓰기[,호출당]] 100만 토큰당")
    a.add_argument("--frontier-price", required=True)
    a.add_argument("--max-drop", type=float, default=0.02)
    a.add_argument("--judge", action="store_true", help="품질에 채점자 점수를 쓴다(있는 칸만)")
    a.add_argument("--out", default="")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return run(args)
    rows = [json.loads(line) for line in Path(args.inp).read_text(encoding="utf-8").splitlines() if line.strip()]
    rep = analyze(rows, parse_price(args.light_price), parse_price(args.frontier_price), args.max_drop, args.judge)
    print_report(rep)
    out = Path(args.out or Path(args.inp).with_suffix(".report.json"))
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n보고서: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
