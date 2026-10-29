# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""3단계 비용 계산과 손익분기(1.17): 경량 모델·상담·프런티어 중 무엇이 싼지를 단가 비율로 정한다.

단가(Prices)는 사용자가 'AI 실행 정책 → 단가'에 넣은 값만 쓴다(앱은 모델 가격을 지어내지 않는다). 단위는 무엇이든 같기만 하면 된다
(예: 100만 토큰당 USD, 또는 POSTECH 크레딧). 캐시 읽기·쓰기 단가를 비워 두면 일반 입력 단가로 본다(할인을 가정하지 않는다).

토큰 분포(Profile): 한 요청의 입력·출력 토큰. 실제로 잰 평균(telemetry의 서버 사용량)이 있으면 그것을, 없으면 요청 길이로 어림한다.
    T  요청 입력(대화·첨부 포함)        R  상담 안내(CONSULT_RULE) 토큰
    Q  경량 모델의 상담 요청 줄 출력     C  프런티어가 받는 상담 프롬프트
    A  프런티어의 상담 답               I  최종 답을 쓰라는 안내
    O  최종 답

비용(모두 선형):
    프런티어 직접      F  = f(T, O)
    경량 단독          L  = l(T+R, O) + p_esc × F                  (p_esc: 그 작업에서 경량 답이 검증에 실패해 승격될 확률)
    상담               K  = l(T+R, Q) + f(C, A) + l(T+A+I, O)       캐시를 켜면 두 번째 l의 T 몫은 캐시 읽기, 첫 번째의 T 몫은 캐시 쓰기

경량 단가 = r × 프런티어 단가(입력·출력·캐시 단가가 모두 같은 비율이라고 볼 때)라 두면 L, K는 r에 대해 직선이므로
손익분기 비율 r* = (F에서 프런티어 몫을 뺀 값) / (경량 몫을 프런티어 단가로 잰 값). 실제 비율 r < r*이면 그 방식이 싸다.
"""
from dataclasses import asdict, dataclass

PER = 1_000_000  # 단가는 100만 토큰당


@dataclass
class Prices:
    input: float
    output: float
    cache_read: float = None    # 비우면 input과 같다고 본다
    cache_write: float = None   # 비우면 input과 같다고 본다
    call: float = 0.0           # 호출 한 번의 고정 비용(POSTECH 크레딧의 기본 크레딧처럼)

    @classmethod
    def from_config(cls, raw):
        """config["adaptive"]["prices"][모델] → Prices 또는 None(입력·출력 단가가 둘 다 있어야 한다)."""
        if not isinstance(raw, dict):
            return None
        try:
            inp, out = float(raw.get("input")), float(raw.get("output"))
        except (TypeError, ValueError):
            return None
        if inp <= 0 or out <= 0:
            return None

        def opt(key):
            try:
                v = float(raw.get(key))
                return v if v >= 0 else None
            except (TypeError, ValueError):
                return None
        return cls(inp, out, opt("cache_read"), opt("cache_write"), opt("call") or 0.0)

    @classmethod
    def from_credit_rate(cls, rate):
        """telemetry의 크레딧 기준 {base, input_per_credit, output_per_credit} → 100만 토큰당 크레딧 단가."""
        try:
            return cls(PER / float(rate["input_per_credit"]), PER / float(rate["output_per_credit"]), call=float(rate.get("base") or 0))
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            return None

    def to_dict(self):
        return asdict(self)

    def scaled(self, r):
        """이 단가에 r을 곱한 단가(손익분기 계산에서 '경량 = r × 프런티어'로 둘 때)."""
        return Prices(self.input * r, self.output * r,
                      None if self.cache_read is None else self.cache_read * r,
                      None if self.cache_write is None else self.cache_write * r, self.call * r)


def call_cost(p, input_tokens, output_tokens, cache_read=0, cache_write=0):
    """호출 하나의 비용. input_tokens는 캐시 몫을 뺀 일반 입력이다."""
    cr = p.input if p.cache_read is None else p.cache_read
    cw = p.input if p.cache_write is None else p.cache_write
    return p.call + (p.input * max(0, input_tokens) + p.output * max(0, output_tokens) + cr * max(0, cache_read)
            + cw * max(0, cache_write)) / PER


@dataclass
class Profile:
    T: int          # 요청 입력
    O: int = 600    # 최종 답
    R: int = 220    # 상담 안내
    Q: int = 120    # 상담 요청 줄
    C: int = 500    # 프런티어 상담 프롬프트
    A: int = 500    # 프런티어 상담 답
    I: int = 80     # 최종 답 안내

    def to_dict(self):
        return asdict(self)


def frontier_cost(pf, prof):
    return call_cost(pf, prof.T, prof.O)


def light_cost(pl, pf, prof, p_escalate=0.0):
    """경량 단독의 기대 비용(검증 실패로 승격되면 프런티어 비용이 더해진다)."""
    return call_cost(pl, prof.T + prof.R, prof.O) + max(0.0, min(1.0, p_escalate)) * frontier_cost(pf, prof)


def consult_cost(pl, pf, prof, cache=False):
    if cache:
        first = call_cost(pl, prof.R, prof.Q, cache_write=prof.T)
        second = call_cost(pl, prof.A + prof.I, prof.O, cache_read=prof.T)
    else:
        first = call_cost(pl, prof.T + prof.R, prof.Q)
        second = call_cost(pl, prof.T + prof.A + prof.I, prof.O)
    return first + call_cost(pf, prof.C, prof.A) + second


def breakeven_ratio(pf, prof, mode="consult", cache=False, p_escalate=0.0):
    """경량 단가 / 프런티어 단가의 손익분기 비율 r*. 실제 비율이 r*보다 작으면 mode(consult|light)가 프런티어 직접보다 싸다.
    r*가 0 이하면 어떤 비율에서도 싸지 않다(예: 승격 확률이 1)."""
    F = frontier_cost(pf, prof)
    if mode == "light":
        light_part = call_cost(pf, prof.T + prof.R, prof.O)        # 경량 몫을 프런티어 단가로 잰 값(r=1)
        fixed = max(0.0, min(1.0, p_escalate)) * F                  # 경량 단가와 관계없는 몫
    else:
        fixed = call_cost(pf, prof.C, prof.A)                       # 프런티어 상담 몫
        light_part = consult_cost(pf, pf, prof, cache) - fixed      # 경량 두 번을 프런티어 단가로 잰 값
    if light_part <= 0:
        return None
    return round((F - fixed) / light_part, 4)


def ratio(pl, pf, prof=None):
    """실제 단가 비율 r. 프로필이 있으면 그 요청 꼴(T 입력, O 출력)의 호출 비용 비율, 없으면 입력·출력 단가 비율의 평균."""
    if prof is not None:
        f = call_cost(pf, prof.T, prof.O)
        return round(call_cost(pl, prof.T, prof.O) / f, 4) if f > 0 else None
    return round(((pl.input / pf.input) + (pl.output / pf.output)) / 2, 4)


def prices_for(model, prices=None, credit_rates=None):
    """모델의 단가: 사용자가 넣은 단가(config["adaptive"]["prices"]) → 크레딧 기준(사용자 값·앱 안내 값) 순서. 없으면 None.
    두 모델의 단가는 같은 단위여야 하므로 decide()는 둘 다 같은 출처일 때만 비교한다(source로 알려 준다)."""
    import telemetry
    user = Prices.from_config((prices or {}).get(model)) if model else None
    if user:
        return user, "prices"
    rate = (credit_rates or {}).get(model) or telemetry.DOCUMENTED_RATES.get(model)
    p = Prices.from_credit_rate(rate) if rate else None
    return (p, "credits") if p else (None, "")


def decide(pl, pf, prof, p_escalate=0.0, cache=False):
    """{'frontier', 'light', 'consult'} 각각의 기대 비용과 손익분기, 가장 싼 방식. 단가가 없으면 None.
    판단은 실제 단가로 낸 기대 비용을 비교한다(입력·출력·고정 비용의 비율이 달라도 맞다). ratio와 breakeven은 그 판단을
    '단가 비율 r < 손익분기 r*'로 읽을 수 있게 보여 주는 값이다(모든 단가가 같은 비율일 때 두 판단은 같다)."""
    if pl is None or pf is None:
        return None
    p_escalate = max(0.0, min(1.0, float(p_escalate or 0)))
    costs = {"frontier": frontier_cost(pf, prof), "light": light_cost(pl, pf, prof, p_escalate),
             "consult": consult_cost(pl, pf, prof, cache)}
    best = min(costs, key=costs.get)
    return {"costs": {k: round(v, 6) for k, v in costs.items()}, "best": best, "ratio": ratio(pl, pf, prof),
            "breakeven_consult": breakeven_ratio(pf, prof, "consult", cache),
            "breakeven_light": breakeven_ratio(pf, prof, "light", cache, p_escalate),
            "saving_vs_frontier": {k: round(1 - v / costs["frontier"], 4) if costs["frontier"] else None for k, v in costs.items()},
            "profile": prof.to_dict(), "cache": bool(cache), "p_escalate": round(p_escalate, 3)}


def measured_profile(events, est_tokens):
    """telemetry 이벤트(서버가 알려 준 실제 사용량)로 프로필의 평균을 채운다. 없는 값은 기본값, T는 이번 요청 어림."""
    prof = Profile(T=max(1, int(est_tokens or 1)))

    def avg(rows, key):
        vals = [int(r.get(key) or 0) for r in rows if r.get(key)]
        return int(sum(vals) / len(vals)) if vals else None

    light = [e for e in events if e.get("type") == "cloud_inference" and e.get("tier") == "light" and e.get("ok")]
    consult = [e for e in events if e.get("type") == "cloud_inference" and e.get("purpose") == "consult" and e.get("ok")]
    final = [e for e in light if e.get("purpose") in ("chat", "po_note", "thread_summary")]
    prof.O = avg(final, "output_tokens") or prof.O
    prof.C = avg(consult, "input_tokens") or prof.C
    prof.A = avg(consult, "output_tokens") or prof.A
    return prof
