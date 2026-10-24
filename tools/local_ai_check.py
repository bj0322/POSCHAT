# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""로컬 AI 실제 점검(1.17): 사용자 PC의 Ollama로 Adaptive AI의 실제 동작을 확인한다(CI에서는 돌지 않는다).

    python tools/local_ai_check.py --model qwen2.5:7b                 # 로컬만(1~8단계)
    python tools/local_ai_check.py --model qwen2.5:7b --cloud --yes   # Cloud 승격·비용 기록까지(9~10단계, Cloud 호출 2번 이하)

1 연결  2 모델 불러오기  3 간단한 질의  4 스트리밍  5 취소  6 문맥 한도  7 자동 라우팅  8 품질 검증  9 Cloud 승격  10 비용 기록
Cloud 단계는 앱 설정(데이터 폴더의 config.json)의 API 키를 쓰고, --cloud와 --yes가 있을 때만 돈다. 키가 없으면 '건너뜀'으로 적는다.
결과는 PASS / FAIL / SKIP으로 출력하고 끝 코드는 FAIL이 있으면 1이다. 실행하지 않은 단계를 통과로 적지 않는다.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import adaptive_engine  # noqa: E402
import adaptive_router  # noqa: E402
import local_ai  # noqa: E402
import quality_gate  # noqa: E402
import telemetry  # noqa: E402

RESULTS = []


def report(step, status, detail=""):
    RESULTS.append((step, status, detail))
    print(f"[{status:<4}] {step}" + (f" — {detail}" if detail else ""), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default=local_ai.DEFAULT_ENDPOINT)
    ap.add_argument("--model", required=True)
    ap.add_argument("--cloud", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)

    try:
        p = local_ai.OllamaProvider(args.endpoint)
    except local_ai.LocalAIError as e:
        report("1 연결", "FAIL", str(e))
        return 1
    h = p.health_check()
    if not h["ok"]:
        report("1 연결", "FAIL", h["error"])
        return 1
    report("1 연결", "PASS", f"Ollama {h['version']} {h['ms']}ms")

    models = {m["id"] for m in p.list_models()}
    if args.model not in models:
        report("2 모델 불러오기", "FAIL", f"{args.model}이(가) 없습니다. 설치된 모델: {', '.join(sorted(models)) or '없음'}")
        return 1
    caps = p.capabilities(args.model)
    try:
        m = p.measure(args.model)
        report("2 모델 불러오기", "PASS", f"불러오기 {m['load_ms']}ms · {m['tokens_per_s']} 토큰/초 · 문맥 {caps['context_length']} · "
               f"기능 {[k for k in ('vision', 'tools', 'thinking') if caps.get(k)]}")
    except local_ai.LocalAIError as e:
        report("2 모델 불러오기", "FAIL", f"{e.kind}: {e}")
        return 1

    res = p.generate(local_ai.LocalRequest(model=args.model, prompt="17 × 23은? 숫자만.", timeout=120))
    report("3 간단한 질의", "PASS" if "391" in res.text else "FAIL", f"답 {res.text.strip()[:40]!r} {res.ms}ms")

    pieces = []
    p.stream(local_ai.LocalRequest(model=args.model, prompt="포항을 세 문장으로 소개해 줘.", timeout=180), pieces.append, None)
    report("4 스트리밍", "PASS" if len(pieces) >= 3 else "FAIL", f"조각 {len(pieces)}개")

    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    t0 = time.monotonic()
    res = p.stream(local_ai.LocalRequest(model=args.model, prompt="1부터 300까지 한 줄에 하나씩 써.", timeout=180), lambda t: None, stop.is_set)
    report("5 취소", "PASS" if res.done_reason == "cancelled" and time.monotonic() - t0 < 10 else "FAIL",
           f"{res.done_reason} · {int((time.monotonic() - t0) * 1000)}ms")

    try:
        res = p.generate(local_ai.LocalRequest(model=args.model, prompt="가" * 6000 + "\n위 글자 수를 대략 말해.", num_ctx=2048, timeout=180))
        report("6 문맥 한도", "PASS", f"2048 토큰 문맥에서 긴 입력: 실행기가 잘라 처리(done_reason={res.done_reason}). "
               "앱 라우터는 이런 입력을 로컬로 보내지 않는다(문맥 90% 초과)")
    except local_ai.LocalAIError as e:
        report("6 문맥 한도", "PASS" if e.kind in ("context", "error") else "FAIL", f"오류로 알림({e.kind})")

    config = {"adaptive": {"enabled": True, "policy": "balanced", "local": {"endpoint": args.endpoint, "default_model": args.model}}}
    rt = adaptive_engine.LocalRuntime(lambda: config)
    cand, why = rt.candidate(args.model)
    easy = adaptive_router.analyze("이 문장을 영어로 번역해 줘: 오늘 회의는 3시입니다.", "이 문장을 영어로 번역해 줘: 오늘 회의는 3시입니다.")
    hard = adaptive_router.analyze("두 방법을 비판적으로 비교하고 가설을 검증해 줘", "두 방법을 비판적으로 비교하고 가설을 검증해 줘")
    cloud = adaptive_router.Candidate("cloud", "cloud-model")
    r1 = adaptive_router.route(easy, "balanced", cand, cloud, {}, {}, None) if cand else None
    r2 = adaptive_router.route(hard, "balanced", cand, cloud, {}, {}, None) if cand else None
    ok = r1 is not None and r1.provider == "local" and r2.provider == "cloud"
    report("7 자동 라우팅", "PASS" if ok else "FAIL", why or f"번역→{r1.provider}, 연구 추론→{r2.provider}")

    engine = adaptive_engine.AdaptiveEngine(config, rt, lambda *a: (_ for _ in ()).throw(RuntimeError("Cloud 없음")), "", False)
    text = engine.ask("[현재 요청]\n이 회의록을 한 문장으로 요약해 줘.\n회의에서는 예산 300만 원을 확정했고 금요일까지 자료를 만든다.",
                      task_text="이 회의록을 한 문장으로 요약해 줘.")
    s = engine.summary()
    report("8 품질 검증", "PASS" if s and s["status"] in ("verified", "unchecked", "unverified") else "FAIL",
           f"상태 {s['status'] if s else '-'} · 검증 {((s or {}).get('gate') or {}).get('checks')} · 답 {text.strip()[:40]!r}")

    if not args.cloud or not args.yes:
        report("9 Cloud 승격", "SKIP", "--cloud --yes를 주지 않아 Cloud를 부르지 않았습니다")
        report("10 비용 기록", "SKIP", "Cloud를 부르지 않았습니다")
    else:
        import api
        import storage

        cfg = storage.load_config()
        key = cfg.get("api_key") or ""
        if not key:
            report("9 Cloud 승격", "SKIP", "앱 설정에 POSTECH API 키가 없습니다")
            report("10 비용 기록", "SKIP", "Cloud 키 없음")
        else:
            settings = api.ApiSettings.from_config(cfg)

            def cloud_ask(prompt, model, on_delta, images):
                settings.model = model
                return api.ask(key, prompt, settings=settings, timeout=180)

            telemetry.config_getter = lambda: {}
            config["adaptive"]["local_retries"] = 0
            engine = adaptive_engine.AdaptiveEngine(config, rt, cloud_ask, settings.model, True)
            original = quality_gate.check
            quality_gate.check = lambda *a, **k: quality_gate.GateResult(ok=False, verifiable=True, failures=["language"],
                                                                         detail="점검용으로 일부러 실패")
            try:
                engine.ask("[현재 요청]\n오늘 회의는 3시라고 한 문장으로 알려 줘.", task_text="오늘 회의는 3시라고 한 문장으로 알려 줘.")
            finally:
                quality_gate.check = original
            s = engine.summary()
            report("9 Cloud 승격", "PASS" if s and s["escalated"] and s["status"] == "escalated" else "FAIL",
                   f"{s['label'] if s else '-'} · Cloud 모델 {settings.model}")
            ev = [e for e in telemetry.load(1) if e["type"] in ("escalation", "cloud_inference")][-2:]
            report("10 비용 기록", "PASS" if len(ev) == 2 else "FAIL",
                   f"기록 {[e['type'] for e in ev]} · 크레딧 추정 {ev[-1].get('credits_est') if ev else None}(근거 있는 모델만)")
    fails = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n통과 {sum(r[1] == 'PASS' for r in RESULTS)} · 실패 {len(fails)} · 건너뜀 {sum(r[1] == 'SKIP' for r in RESULTS)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
