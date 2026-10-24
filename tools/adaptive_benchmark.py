# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive AI 벤치마크 실행기(1.17). 데이터: tools/data/adaptive_benchmark.json (tools/adaptive_benchmark_data.py로 만든다)

구성
    A cloud_only   모든 요청을 Cloud 모델로
    B local_only   모든 요청을 로컬 모델로
    C rule         규칙 라우터만(의미 분류 없음: 규칙에 안 걸리면 '분포 밖'으로 보고 Cloud), 검증·승격 없음
    D adaptive     규칙 + 의미 분류 라우터, 검증·승격 없음
    E cascade      D + QualityGate + Cloud 승격(경량 모델 없이 쓸 때 앱의 동작)
    F tiered       로컬 → 경량 Cloud(Haiku 등) → 프런티어, 검증·승격(앱의 AdaptiveEngine을 그대로 돌린다, 상담 끔)
    G consult      F + 상담: 경량 모델이 이끌고 필요한 부분만 프런티어에 짧게 묻는다(앱의 AdaptiveEngine, 상담 켬)

두 가지 방식
    --offline      모델을 부르지 않는다. 라우터 결정만 보고 라우팅 정확도(데이터의 route_label과 비교)와 로컬 처리 비율,
                   Cloud 크레딧 추정(근거 있는 모델만)을 낸다. 품질은 재지 않는다(측정값처럼 보이지 않게 '추정'으로 적는다).
    --run          실제로 모델을 부른다. 로컬은 Ollama(--endpoint, --local-model), Cloud는 앱 설정(config.json)의 키·방식과 --cloud-model.
                   Cloud 비용이 드므로 --budget-calls(Cloud 호출 상한)와 --yes가 있어야 한다. --repeats로 같은 요청을 여러 번 돌려
                   흔들림(성공률의 표준편차)을 잰다. F·G는 --light-model(같은 API 방식의 경량 모델)이 있어야 돈다. --run-code를 켜면 코드 문제의 시험(assert)을 임시 폴더의 별도 Python으로 10초 안에 돌린다.

    python tools/adaptive_benchmark.py --offline --policy balanced
    python tools/adaptive_benchmark.py --run --configs B,E --local-model qwen2.5:7b --cloud-model claude-sonnet-5-5 --budget-calls 300 --yes

결과는 --out(기본 adaptive-benchmark-<시각>.json)에 남기고 표를 출력한다. 실행하지 않은 구성은 '미실행'으로 남긴다.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import adaptive_engine  # noqa: E402
import adaptive_router  # noqa: E402
import connectors  # noqa: E402
import evals  # noqa: E402
import quality_gate  # noqa: E402
import telemetry  # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "adaptive_benchmark.json"
CONFIGS = {"A": "cloud_only", "B": "local_only", "C": "rule", "D": "adaptive", "E": "cascade", "F": "tiered", "G": "consult"}


class BudgetExceeded(BaseException):
    """Cloud 호출 상한. 엔진이 모델 오류(Exception)로 삼켜 다른 모델로 넘기지 않게 BaseException으로 둔다."""


def load(path=DATA):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_prompt(c):
    """앱이 실제로 보내는 꼴과 같게: 요청 + 기능이 감싼 외부 데이터."""
    parts = ["[현재 요청]\n" + c["prompt"]]
    ctx = c.get("context")
    if ctx:
        parts.append(connectors.wrap_untrusted(ctx["text"], ctx["source"]))
    return "\n\n".join(parts)


def score(answer, c, run_code=False):
    """(점수 0~1, 실패 목록). evals 규칙 + 숫자 허용 오차 + (선택) 코드 시험."""
    expect = dict(c["expect"])
    number = expect.pop("number", None)
    s, failed = evals.score(answer, expect) if expect else (1.0, [])
    checks = max(1, len([k for k in expect if expect[k]]))
    total_ok = s * checks
    if number is not None:
        checks += 1
        values = [float(x.replace(",", "")) for x in re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", answer or "")]
        if any(abs(v - number["value"]) <= number["tol"] or abs(v / 100 - number["value"]) <= number["tol"] for v in values):
            total_ok += 1
        else:
            failed.append(f"수치 {number['value']}±{number['tol']} 없음")
    if run_code and c.get("test"):
        checks += 1
        ok, why = run_test(answer, c["test"])
        total_ok += 1 if ok else 0
        if not ok:
            failed.append(f"시험 실패: {why}")
    return round(total_ok / checks, 3), failed


def run_test(answer, test, timeout=10):
    """답의 첫 Python 코드 블록 + 시험(assert)을 임시 폴더에서 별도 Python(-I)으로 돌린다. 네트워크·파일 쓰기를 막지는 않으므로
    믿을 수 없는 모델 출력을 돌릴 때는 --run-code를 켜지 마세요(기본 꺼짐)."""
    m = re.search(r"```(?:python|py)?\n(.*?)```", answer or "", re.S)
    if not m:
        return False, "코드 블록 없음"
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.py"
        path.write_text(m.group(1) + "\n" + test + "\n", encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, "-I", str(path)], cwd=d, capture_output=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, "시간 초과"
    return r.returncode == 0, (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:120]


def analyze(c, use_semantic=True):
    """앱과 같은 꼴로 분석한다. 에이전트 사례는 앱이 '다음 단계' 목적(agent_step)으로 부른다."""
    prompt = build_prompt(c)
    purpose = "agent_step" if c["category"] == "agent" else "chat"
    if use_semantic:
        return adaptive_router.analyze(prompt, c["prompt"], purpose=purpose, attachments=bool(c.get("context")))
    original = adaptive_router.semantic
    adaptive_router.semantic = lambda text: ("other", 0.0, 0.0)  # 규칙만: 규칙에 안 걸리면 분포 밖
    try:
        return adaptive_router.analyze(prompt, c["prompt"], purpose=purpose, attachments=bool(c.get("context")))
    finally:
        adaptive_router.semantic = original


def offline(data, policy="balanced", cloud_model="claude-sonnet-5-5", local_ctx=32768):
    """모델을 부르지 않는 라우팅 평가. 로컬 후보는 '있다'고 가정한다(문맥 길이 local_ctx, 이미지 없음)."""
    local = adaptive_router.Candidate("local", "local-model", context_length=local_ctx)
    report = {"mode": "offline", "policy": policy, "cloud_model": cloud_model, "cases": len(data["cases"]), "configs": {}}
    for key, name in (("C", "rule"), ("D", "adaptive")):
        rows = []
        for c in data["cases"]:
            a = analyze(c, use_semantic=(name != "rule"))
            cost = telemetry.credit_estimate(cloud_model, a.est_tokens, adaptive_engine.EST_OUTPUT_TOKENS)
            cloud = adaptive_router.Candidate("cloud", cloud_model, cost=cost)
            r = adaptive_router.route(a, policy, local, cloud, {}, {}, None)
            rows.append({"id": c["id"], "category": c["category"], "split": c.get("split", ""), "label": c["route_label"], "provider": r.provider,
                         "task": a.task, "difficulty": a.difficulty, "method": a.method, "cost": cost})
        report["configs"][key] = summarize_routing(rows)
    for key, consult in (("F", False), ("G", True)):
        rows = []
        for c in data["cases"]:
            a = analyze(c)
            cloud = adaptive_router.Candidate("cloud", cloud_model)
            r = adaptive_router.route(a, policy, local, cloud, {}, {}, None)
            r = adaptive_router.tier(r, a, adaptive_router.Candidate("cloud", "light-model"), {"consult": consult},
                                     allow_consult=c["category"] != "agent")
            rows.append({"tier": r.tier, "consult": r.consult and r.reason_code == "light_consult", "tokens": a.est_tokens,
                         "category": c["category"]})
        total = sum(r["tokens"] for r in rows) or 1
        frontier = sum(r["tokens"] for r in rows if r["tier"] == "frontier")
        report["configs"][key] = {
            "local_ratio": round(sum(r["tier"] == "local" for r in rows) / len(rows), 3),
            "light_ratio": round(sum(r["tier"] == "light" for r in rows) / len(rows), 3),
            "frontier_ratio": round(sum(r["tier"] == "frontier" for r in rows) / len(rows), 3),
            "consult_candidates": sum(r["consult"] for r in rows),
            # 처음 라우팅만 본 값: 검증 실패로 인한 승격·상담 질문의 토큰은 실제 실행(--run)에서만 알 수 있다
            "frontier_token_share_est": round(frontier / total, 3),
        }
    report["configs"]["A"] = {"local_ratio": 0.0, "note": "모든 요청을 Cloud로(기준)"}
    report["configs"]["B"] = {"local_ratio": 1.0, "note": "모든 요청을 로컬로"}
    return report


def summarize_routing(rows):
    def pick(rs):
        n = len(rs)
        local = [r for r in rs if r["provider"] == "local"]
        correct = sum(1 for r in rs if (r["provider"] == "local") == (r["label"] == "local_ok"))
        wrong_local = sum(1 for r in local if r["label"] == "cloud_needed")
        missed_local = sum(1 for r in rs if r["provider"] != "local" and r["label"] == "local_ok")
        known = [r["cost"] for r in rs if r["cost"] is not None]
        base = sum(known)
        spent = sum(r["cost"] for r in rs if r["cost"] is not None and r["provider"] != "local")
        return {"n": n, "local_ratio": round(len(local) / n, 3) if n else None,
                "routing_accuracy": round(correct / n, 3) if n else None,
                "wrong_local": wrong_local, "wrong_local_ratio": round(wrong_local / n, 3) if n else None,
                "missed_local": missed_local,
                "credit_saving_est": round(1 - spent / base, 3) if base else None}
    out = pick(rows)
    out["by_category"] = {cat: pick([r for r in rows if r["category"] == cat]) for cat in sorted({r["category"] for r in rows})}
    # 라우터 규칙은 dev의 틀린 사례만 보고 고쳤다: test가 덜 낙관적인 값이다
    out["by_split"] = {sp: pick([r for r in rows if r.get("split") == sp]) for sp in sorted({r.get("split") for r in rows} - {"", None})}
    out["wrong_local_ids"] = [r["id"] for r in rows if r["provider"] == "local" and r["label"] == "cloud_needed"][:40]
    return out


class Runner:
    """실제 실행. local(prompt, json) -> (글, ms), cloud(prompt) -> (글, ms, credits_or_None)."""

    def __init__(self, local, cloud, budget_calls, run_code=False, local_model="local", cloud_model="cloud", light=None,
                 light_model=""):
        self.local, self.cloud, self.light = local, cloud, light
        self.light_model = light_model or ("light" if light else "")
        self.budget_calls = budget_calls
        self.cloud_calls = 0
        self.run_code = run_code
        self.local_model, self.cloud_model = local_model, cloud_model

    def _cloud(self, prompt):
        if self.cloud_calls >= self.budget_calls:
            raise BudgetExceeded(f"Cloud 호출 상한({self.budget_calls})에 닿아 멈췄습니다.")
        self.cloud_calls += 1
        return self.cloud(prompt)

    def _engine_one(self, c, consult):
        """앱의 AdaptiveEngine(3단계·상담)을 그대로 돌린다. 로컬·경량·프런티어 호출을 가짜 없이 이 실행기의 함수로 잇는다."""
        import adaptive_engine
        import local_ai

        prompt = build_prompt(c)
        tokens = {"frontier": 0, "light": 0}
        credits = []
        config = {"adaptive": {"enabled": True, "policy": "balanced", "consult": consult, "consult_max": 1, "local_retries": 0,
                               "local": {"default_model": self.local_model}}}

        class Shim:
            def stream(shim, req, on_delta, cancelled):
                text, ms = self.local(req.prompt, req.json_format)
                return local_ai.LocalResult(text=text, model=req.model, ms=ms)

        rt = types.SimpleNamespace(provider=lambda: Shim(),
                                   candidate=lambda m: (adaptive_router.Candidate("local", m, context_length=32768), ""))

        def cloud_ask(p, model, on_delta, images):
            tier = "light" if model == self.light_model else "frontier"
            tokens[tier] += adaptive_router.estimate_tokens(p)
            if tier == "light":
                text, _, cr = self.light(p)
            else:
                text, _, cr = self._cloud(p)
            if cr is not None:
                credits.append(cr)
            return text

        engine = adaptive_engine.AdaptiveEngine(config, rt, cloud_ask, self.cloud_model, True, light_model=self.light_model)
        purpose = "agent_step" if c["category"] == "agent" else "chat"
        start = time.monotonic()
        text = engine.ask(prompt, purpose=purpose, task_text=c["prompt"], attachments=bool(c.get("context")))
        s = engine.summary() or {}
        sc, failed = score(text, c, self.run_code)
        provider = {"local": "local", "light": "light"}.get(s.get("provider"), "cloud")
        return {"id": c["id"], "category": c["category"], "label": c["route_label"], "provider": provider,
                "escalated": bool(s.get("escalated")), "consulted": bool(s.get("consulted")), "score": sc, "ok": sc == 1.0,
                "failed": failed[:5], "ms": int((time.monotonic() - start) * 1000), "credits": sum(credits) if credits else None,
                "frontier_tokens": tokens["frontier"], "light_tokens": tokens["light"],
                "baseline_tokens": adaptive_router.estimate_tokens(prompt)}

    def one(self, c, config):
        if config in ("tiered", "consult"):
            return self._engine_one(c, consult=config == "consult")
        prompt = build_prompt(c)
        a = analyze(c, use_semantic=config != "rule")
        start = time.monotonic()
        provider, escalated, credits = "cloud", False, None
        if config == "cloud_only":
            text, _, credits = self._cloud(prompt)
        elif config == "local_only":
            text, _ = self.local(prompt, c["category"] == "agent")
            provider = "local"
        else:
            local_c = adaptive_router.Candidate("local", self.local_model, context_length=32768)
            cloud_c = adaptive_router.Candidate("cloud", self.cloud_model)
            r = adaptive_router.route(a, "balanced", local_c, cloud_c, {}, {}, None)
            if r.provider == "local":
                provider = "local"
                text, _ = self.local(prompt, c["category"] == "agent")
                if config == "cascade":
                    area = quality_gate.area_for(a.task, "agent_step" if c["category"] == "agent" else "chat")
                    gate = quality_gate.check(area, text, {"prompt": prompt, "korean": a.korean,
                                                           "pages": (c.get("context") or {}).get("pages", 0)})
                    if not gate.ok:
                        text, _, credits = self._cloud(prompt)
                        provider, escalated = "cloud", True
            else:
                text, _, credits = self._cloud(prompt)
        s, failed = score(text, c, self.run_code)
        base = adaptive_router.estimate_tokens(prompt)
        return {"id": c["id"], "category": c["category"], "label": c["route_label"], "provider": provider, "escalated": escalated,
                "score": s, "ok": s == 1.0, "failed": failed[:5], "ms": int((time.monotonic() - start) * 1000), "credits": credits,
                "frontier_tokens": base if provider == "cloud" else 0, "light_tokens": 0, "baseline_tokens": base}

    def run(self, data, configs, repeats=1, cases=None, on_progress=None):
        report = {"mode": "run", "configs": {}, "repeats": repeats, "cloud_calls": 0, "stopped": ""}
        items = [c for c in data["cases"] if not cases or c["id"] in cases]
        for key in configs:
            name = CONFIGS[key]
            runs = []
            if name in ("tiered", "consult") and not self.light:
                report["configs"][key] = {"status": "미실행", "why": "경량 모델(--light-model)을 주지 않음"}
                continue
            try:
                for rep in range(repeats):
                    rows = []
                    for c in items:
                        rows.append(self.one(c, name))
                        if on_progress:
                            on_progress(key, rep, len(rows), len(items))
                    runs.append(rows)
            except BudgetExceeded as e:
                report["stopped"] = str(e)
                report["configs"][key] = {"status": "중단", "partial": summarize_run(runs + ([rows] if rows else []))}
                break
            report["configs"][key] = {"status": "완료", **summarize_run(runs)}
        report["cloud_calls"] = self.cloud_calls
        for key in CONFIGS:
            report["configs"].setdefault(key, {"status": "미실행"})
        return report


def summarize_run(runs):
    if not runs or not runs[0]:
        return {}
    rates = [sum(r["ok"] for r in rows) / len(rows) for rows in runs if rows]
    rows = [r for rs in runs for r in rs]
    ms = sorted(r["ms"] for r in rows)
    credits = [r["credits"] for r in rows if r["credits"] is not None]
    cloud = [r for r in rows if r["provider"] == "cloud"]
    by_cat = {}
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        by_cat[cat] = {"n": len(rs), "success": round(sum(r["ok"] for r in rs) / len(rs), 3),
                       "score": round(sum(r["score"] for r in rs) / len(rs), 3)}
    mean = sum(rates) / len(rates)
    base = sum(r.get("baseline_tokens") or 0 for r in rows)
    frontier = sum(r.get("frontier_tokens") or 0 for r in rows)
    return {"n": len(rows), "success": round(mean, 3),
            "light_ratio": round(sum(r["provider"] == "light" for r in rows) / len(rows), 3),
            "consults": sum(1 for r in rows if r.get("consulted")),
            "frontier_tokens_est": frontier, "light_tokens_est": sum(r.get("light_tokens") or 0 for r in rows),
            "frontier_token_saving_est": round(1 - frontier / base, 3) if base else None,
            "success_std": round(math.sqrt(sum((x - mean) ** 2 for x in rates) / len(rates)), 4) if len(rates) > 1 else None,
            "score": round(sum(r["score"] for r in rows) / len(rows), 3),
            "local_ratio": round(sum(r["provider"] == "local" for r in rows) / len(rows), 3),
            "escalation_ratio": round(sum(r["escalated"] for r in rows) / max(1, sum(r["provider"] == "local" or r["escalated"] for r in rows)), 3),
            "cloud_calls": len(cloud), "credits_est": round(sum(credits), 1) if credits else None,
            "wrong_local": sum(1 for r in rows if r["provider"] == "local" and not r["ok"] and r["label"] == "cloud_needed"),
            "p50_ms": ms[len(ms) // 2], "p95_ms": ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))],
            "by_category": by_cat}


def print_table(report):
    print(f"\n== {report['mode']} ==")
    for key, r in report["configs"].items():
        if not isinstance(r, dict) or r.get("status") == "미실행":
            print(f"{key} {CONFIGS[key]:<11} 미실행")
            continue
        fields = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("by_category", "wrong_local_ids", "partial"))
        print(f"{key} {CONFIGS[key]:<11} {fields}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--policy", default="balanced", choices=adaptive_router.POLICIES)
    ap.add_argument("--configs", default="A,B,C,D,E")
    ap.add_argument("--endpoint", default="http://127.0.0.1:11434")
    ap.add_argument("--local-model", default="")
    ap.add_argument("--cloud-model", default="claude-sonnet-5-5")
    ap.add_argument("--light-model", default="", help="3단계(F·G)의 경량 Cloud 모델, 예: claude-haiku-5-5")
    ap.add_argument("--budget-calls", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--run-code", action="store_true")
    ap.add_argument("--yes", action="store_true", help="Cloud 비용이 드는 실행에 동의")
    ap.add_argument("--cases", default="", help="쉼표로 고른 id만")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    data = load()
    if args.offline or not args.run:
        report = offline(data, args.policy, args.cloud_model)
    else:
        configs = [c.strip().upper() for c in args.configs.split(",") if c.strip().upper() in CONFIGS]
        needs_cloud = any(c in ("A", "C", "D", "E", "F", "G") for c in configs)
        if needs_cloud and (not args.yes or args.budget_calls <= 0):
            print("Cloud 비용이 드는 구성입니다. --budget-calls N(Cloud 호출 상한)과 --yes를 함께 주세요.", file=sys.stderr)
            return 2
        import local_ai

        provider = local_ai.OllamaProvider(args.endpoint)

        def local(prompt, json_format=False):
            res = provider.stream(local_ai.LocalRequest(model=args.local_model, prompt=prompt, timeout=300, json_format=json_format), None, None)
            return res.text, res.ms

        def cloud(prompt, model=None):
            import api
            import storage

            usage = {}
            api.on_usage = lambda mode, model, u: usage.update(u or {})
            settings = api.ApiSettings.from_config(storage.load_config())
            settings.model, settings.stream = model or args.cloud_model, False
            key = storage.load_config().get("api_key") or os.environ.get("POSTECH_GENAI_API_KEY", "")
            start = time.monotonic()
            text = api.ask(key, prompt, settings=settings, timeout=180)
            return text, int((time.monotonic() - start) * 1000), telemetry.credit_estimate(
                model or args.cloud_model, usage.get("input_tokens"), usage.get("output_tokens")) if usage else None

        telemetry.enabled = False  # 벤치마크 호출은 앱의 사용량·진단 기록에 섞지 않는다
        light = (lambda p: cloud(p, args.light_model)) if args.light_model else None
        runner = Runner(local, cloud, args.budget_calls, args.run_code, args.local_model, args.cloud_model, light, args.light_model)
        report = runner.run(data, configs, args.repeats, set(filter(None, args.cases.split(","))),
                            on_progress=lambda k, rep, i, n: print(f"\r{k} {rep + 1}회째 {i}/{n}", end="", flush=True))
    out = Path(args.out or f"adaptive-benchmark-{time.strftime('%Y%m%d-%H%M%S')}.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print_table(report)
    print(f"\n결과: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
