# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.17 손익분기(adaptive_cost): 단가 비율 r과 손익분기 r*가 실제 기대 비용 비교와 맞는지."""
import unittest

import adaptive_cost as cost
from adaptive_cost import Prices, Profile

FRONTIER = Prices(5.0, 25.0, cache_read=0.5, cache_write=6.25)   # 시험용 단가(실제 모델 가격이 아니다)


def at_ratio(r):
    return FRONTIER.scaled(r)


class BreakevenTests(unittest.TestCase):
    def test_breakeven_is_where_the_costs_meet(self):
        for prof in (Profile(T=300), Profile(T=2000), Profile(T=20000, O=1500, A=800)):
            for cache in (False, True):
                be = cost.breakeven_ratio(FRONTIER, prof, "consult", cache)
                self.assertGreater(be, 0)
                f = cost.frontier_cost(FRONTIER, prof)
                self.assertAlmostEqual(cost.consult_cost(at_ratio(be), FRONTIER, prof, cache), f, delta=f * 1e-3)
                self.assertLess(cost.consult_cost(at_ratio(be * 0.9), FRONTIER, prof, cache), f)
                self.assertGreater(cost.consult_cost(at_ratio(be * 1.1), FRONTIER, prof, cache), f)
            for p_esc in (0.0, 0.2, 0.5):
                be = cost.breakeven_ratio(FRONTIER, prof, "light", p_escalate=p_esc)
                f = cost.frontier_cost(FRONTIER, prof)
                self.assertAlmostEqual(cost.light_cost(at_ratio(be), FRONTIER, prof, p_esc), f, delta=f * 1e-3)

    def test_breakeven_moves_with_the_request_shape(self):
        # 짧은 요청은 프런티어 상담 답(A)이 최종 답(O)만큼 들어 상담이 거의 이득이 없다(r*가 작다).
        # 긴 대화일수록 프런티어가 대화 전체(T)를 읽지 않아 아끼는 몫이 커지지만, 경량 모델이 T를 두 번 읽으므로
        # 캐시가 없으면 r*는 1/2을 넘지 못한다. 캐시를 켜면(두 번째 읽기가 캐시 읽기) r*가 더 올라간다.
        short = cost.breakeven_ratio(FRONTIER, Profile(T=500), "consult")
        long = cost.breakeven_ratio(FRONTIER, Profile(T=30000), "consult")
        cached = cost.breakeven_ratio(FRONTIER, Profile(T=30000), "consult", cache=True)
        self.assertLess(short, 0.15)
        self.assertGreater(long, short)
        self.assertLess(long, 0.5)
        self.assertGreater(cached, long)
        # 승격 확률이 오르면 경량 혼자의 손익분기가 내려가고, 1이면 어떤 단가에서도 이득이 없다
        self.assertGreater(cost.breakeven_ratio(FRONTIER, Profile(T=2000), "light", p_escalate=0.1),
                           cost.breakeven_ratio(FRONTIER, Profile(T=2000), "light", p_escalate=0.4))
        self.assertEqual(cost.breakeven_ratio(FRONTIER, Profile(T=2000), "light", p_escalate=1.0), 0.0)

    def test_decide_picks_the_cheapest_and_agrees_with_the_ratio(self):
        prof = Profile(T=4000)
        cheap = cost.decide(at_ratio(0.05), FRONTIER, prof, p_escalate=0.1)
        self.assertIn(cheap["best"], ("light", "consult"))
        self.assertLess(cheap["ratio"], cheap["breakeven_consult"])
        self.assertGreater(cheap["saving_vs_frontier"]["consult"], 0)
        pricey = cost.decide(at_ratio(0.95), FRONTIER, prof, p_escalate=0.1)
        self.assertEqual(pricey["best"], "frontier")
        self.assertGreater(pricey["ratio"], pricey["breakeven_consult"])
        self.assertLess(pricey["saving_vs_frontier"]["consult"], 0)
        self.assertIsNone(cost.decide(None, FRONTIER, prof))
        # 비율이 다른 단가(입력은 싸고 출력은 비쌈)에서도 판단은 실제 기대 비용으로 낸다
        odd = Prices(0.2, 20.0)
        d = cost.decide(odd, FRONTIER, Profile(T=1000, O=2000))
        self.assertEqual(d["best"], min(d["costs"], key=d["costs"].get))

    def test_per_call_fees_count(self):
        # 호출당 고정 비용(POSTECH 크레딧의 기본 크레딧)이 크면 호출이 셋인 상담이 불리하다
        no_fee = cost.breakeven_ratio(Prices(5, 25), Profile(T=1000), "consult")
        fee = cost.breakeven_ratio(Prices(5, 25, call=0.05), Profile(T=1000), "consult")
        self.assertLess(fee, no_fee)
        self.assertEqual(cost.call_cost(Prices(1, 1, call=2), 0, 0), 2)


class PricesTests(unittest.TestCase):
    def test_from_config_validates(self):
        self.assertIsNone(Prices.from_config({"input": 1}))
        self.assertIsNone(Prices.from_config({"input": 0, "output": 1}))
        self.assertIsNone(Prices.from_config({"input": "x", "output": 1}))
        self.assertIsNone(Prices.from_config("1,2"))
        p = Prices.from_config({"input": "1.5", "output": 7, "cache_read": -1, "cache_write": "", "call": 0.2})
        self.assertEqual((p.input, p.output, p.cache_read, p.cache_write, p.call), (1.5, 7.0, None, None, 0.2))
        # 캐시 단가를 비워 두면 일반 입력 단가로 본다(할인을 가정하지 않는다)
        self.assertEqual(cost.call_cost(p, 0, 0, cache_read=1_000_000), 0.2 + 1.5)

    def test_prices_for_prefers_user_prices_then_credit_rates(self):
        p, src = cost.prices_for("claude-sonnet-5-5")
        self.assertEqual(src, "credits")
        self.assertAlmostEqual(p.input, 1_000_000 / 250)
        self.assertEqual(p.call, 24)
        p, src = cost.prices_for("claude-sonnet-5-5", {"claude-sonnet-5-5": {"input": 3, "output": 15}})
        self.assertEqual((src, p.input), ("prices", 3.0))
        self.assertEqual(cost.prices_for("light-x"), (None, ""))
        self.assertEqual(cost.prices_for(""), (None, ""))

    def test_measured_profile_uses_server_usage(self):
        events = [
            {"type": "cloud_inference", "ok": True, "tier": "light", "purpose": "chat", "output_tokens": 300},
            {"type": "cloud_inference", "ok": True, "tier": "light", "purpose": "chat", "output_tokens": 500},
            {"type": "cloud_inference", "ok": True, "tier": "frontier", "purpose": "consult", "input_tokens": 900, "output_tokens": 200},
            {"type": "cloud_inference", "ok": False, "tier": "frontier", "purpose": "consult", "input_tokens": 99999},
        ]
        prof = cost.measured_profile(events, 1234)
        self.assertEqual((prof.T, prof.O, prof.C, prof.A), (1234, 400, 900, 200))
        self.assertEqual(cost.measured_profile([], 0).O, Profile(T=1).O)


if __name__ == "__main__":
    unittest.main()
