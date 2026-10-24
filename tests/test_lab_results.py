# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Lab(1.16): 결과 파일 읽기·지표 뽑기·통계·표본·비교(lab_results)."""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lab_results as lr  # noqa: E402


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        p = os.path.join(self.tmp.name, name)
        Path(p).write_text(text, encoding="utf-8")
        return p

    def test_numbers_are_not_guessed(self):
        self.assertEqual(lr.to_number("1.5"), (1.5, "ok"))
        self.assertEqual(lr.to_number(""), (None, "empty"))
        self.assertEqual(lr.to_number("NaN"), (None, "nan"))
        self.assertEqual(lr.to_number("-inf"), (None, "inf"))
        self.assertEqual(lr.to_number("Infinity"), (None, "inf"))
        self.assertEqual(lr.to_number("12ms"), (None, "text"))  # 단위 붙은 글자를 숫자로 짐작하지 않는다
        self.assertEqual(lr.to_number(True), (None, "text"))
        self.assertEqual(lr.to_number(float("nan")), (None, "nan"))

    def test_units_from_headers(self):
        self.assertEqual(lr.split_unit("latency (ms)"), ("latency", "ms"))
        self.assertEqual(lr.split_unit("power[mW]"), ("power", "mW"))
        self.assertEqual(lr.split_unit("power_mw"), ("power_mw", "mw"))
        self.assertEqual(lr.split_unit("acc"), ("acc", ""))

    def test_csv_stats_use_all_rows_and_report_bad_cells(self):
        rows = ["epoch,loss,acc (%)"] + [f"{i},{1 / (i + 1):.4f},{50 + i * 0.01:.2f}" for i in range(5000)]
        rows[10] = "9,NaN,50.09"
        rows[11] = "10,,50.10"
        rows[12] = "11,inf,50.11"
        rows[13] = "12,oops,50.12"
        p = self.write("log.csv", "\n".join(rows) + "\n")
        table = lr.read_table(p)
        self.assertEqual(table["columns"], ["epoch", "loss", "acc (%)"])
        st = lr.stats(lr.column_values(table, "loss"))
        self.assertEqual((st["count"], st["nan"], st["empty"], st["inf"], st["text"]), (5000, 1, 1, 1, 1))
        self.assertEqual(st["numeric"], 4996)
        self.assertAlmostEqual(st["max"], 1.0)
        s = lr.series(table, "epoch", ["acc (%)"], max_points=500)
        self.assertTrue(s["sampled"])
        self.assertLessEqual(len(s["series"][0]["points"]), 500)
        self.assertEqual(s["series"][0]["stats"]["count"], 5000)  # 통계는 표본이 아니라 전체
        self.assertEqual(s["series"][0]["unit"], "%")
        self.assertAlmostEqual(s["series"][0]["stats"]["max"], 50 + 4999 * 0.01, places=2)

    def test_extract_only_chosen_columns_with_source(self):
        p = self.write("res.csv", "step,loss,val_acc\n1,0.9,0.5\n2,0.5,0.7\n3,0.4,0.65\n")
        ref = lr.file_ref(p, "out/res.csv")
        out = lr.extract(p, [{"column": "val_acc", "how": "max"}, {"column": "loss", "how": "last", "name": "final_loss"},
                             {"column": "missing"}], ref)
        self.assertEqual(set(out["metrics"]), {"val_acc", "final_loss"})  # 고르지 않은 step은 지표가 아니다
        m = out["metrics"]["val_acc"]
        self.assertEqual((m["value"], m["source"]["row"], m["source"]["column"], m["source"]["file"]), (0.7, 2, "val_acc", "out/res.csv"))
        self.assertEqual(m["source"]["sha256"], ref["sha256"])
        self.assertTrue(any("열이 없습니다" in w for w in out["warnings"]))

    def test_extract_skips_non_numeric_and_warns(self):
        p = self.write("r.csv", "a,b\nNaN,x\n,y\n")
        out = lr.extract(p, [{"column": "a"}, {"column": "b", "how": "row:1"}])
        self.assertEqual(out["metrics"], {})
        self.assertTrue(out["warnings"])

    def test_duplicate_headers_are_reported(self):
        p = self.write("d.csv", "x,loss,loss\n1,2,3\n")
        out = lr.extract(p, [{"column": "x"}])
        self.assertTrue(any("겹치는" in w for w in out["warnings"]))

    def test_json_scalars_and_tables(self):
        p = self.write("m.json", json.dumps({"final": {"acc": 0.91, "latency_ms": 12.5, "bad": float("nan")},
                                             "history": [{"epoch": 1, "loss": 0.5}, {"epoch": 2, "loss": 0.3}]}))
        t = lr.read_table(p)
        self.assertEqual(t["table_key"], "history")
        self.assertEqual(t["columns"], ["epoch", "loss"])
        out = lr.extract(p, [{"key": "final.acc"}, {"key": "final.latency_ms"}, {"key": "final.bad"}, {"key": "nope"}])
        self.assertEqual(out["metrics"]["final.acc"]["value"], 0.91)
        self.assertEqual(out["metrics"]["final.latency_ms"]["unit"], "ms")
        self.assertNotIn("final.bad", out["metrics"])
        self.assertEqual(len(out["warnings"]), 2)

    def test_jsonl_tsv_and_log(self):
        p = self.write("h.jsonl", '{"step": 1, "loss": 0.5}\nnot json\n{"step": 2, "loss": 0.25}\n')
        t = lr.read_table(p)
        self.assertEqual((t["columns"], len(t["rows"]), t["bad_lines"]), (["step", "loss"], 2, 1))
        p = self.write("t.tsv", "a\tb (V)\n1\t2\n")
        t = lr.read_table(p)
        self.assertEqual(t["columns"], ["a", "b (V)"])
        p = self.write("run.log", "epoch 1 loss: 0.5\nepoch 2 loss: 0.25 acc=91.5%\nSNR = 60.2 dB\n")
        out = lr.extract(p, [{"key": "loss"}, {"key": "acc"}, {"key": "SNR"}])
        self.assertEqual(out["metrics"]["loss"]["value"], 0.25)
        self.assertEqual(out["metrics"]["acc"]["unit"], "%")
        self.assertEqual(out["metrics"]["SNR"]["unit"], "dB")
        self.assertEqual(out["metrics"]["loss"]["source"]["line"], 2)

    def test_file_ref_detects_change_and_missing(self):
        p = self.write("x.csv", "a\n1\n")
        ref = lr.file_ref(p)
        self.assertEqual(lr.check_ref(ref), "ok")
        Path(p).write_text("a\n2\n3\n")
        self.assertEqual(lr.check_ref(ref), "changed")
        os.remove(p)
        self.assertEqual(lr.check_ref(ref), "missing")

    def test_compare_flags_units_versions_and_missing(self):
        runs = [
            {"id": "run-a", "seq": 1, "params": {"lr": 0.1, "bs": 32}, "metrics": {"lat": {"value": 10, "unit": "ms"},
                                                                                   "acc": {"value": 0.9, "unit": ""}},
             "code": {"commit": "aaa", "dirty": False}, "env": {"python": "3.11", "os": "Linux"}},
            {"id": "run-b", "seq": 2, "params": {"lr": 0.01, "bs": 32}, "metrics": {"lat": {"value": 0.012, "unit": "s"}},
             "code": {"commit": "bbb", "dirty": True}, "env": {"python": "3.12", "os": "Linux"}},
        ]
        c = lr.compare(runs)
        params = {p["name"]: p for p in c["params"]}
        self.assertTrue(params["lr"]["differs"])
        self.assertFalse(params["bs"]["differs"])
        lat = next(m for m in c["metrics"] if m["name"] == "lat")
        self.assertFalse(lat["comparable"])
        self.assertIsNone(lat["max"])
        text = " ".join(c["warnings"])
        for word in ("단위가 다릅니다", "없는 실행: run-b", "커밋", "커밋하지 않은 변경", "환경"):
            self.assertIn(word, text)
        with self.assertRaises(lr.ResultError):
            lr.compare(runs[:1])

    def test_series_without_x_uses_row_numbers(self):
        p = self.write("y.csv", "v\n1\n2\nx\n4\n")
        s = lr.series(lr.read_table(p), "", ["v"])
        self.assertEqual(s["series"][0]["points"], [[1, 1.0], [2, 2.0], [4, 4.0]])
        self.assertEqual(s["series"][0]["skipped"], 1)
        self.assertFalse(s["sampled"])
        self.assertTrue(all(not math.isnan(y) for _, y in s["series"][0]["points"]))


if __name__ == "__main__":
    unittest.main()
