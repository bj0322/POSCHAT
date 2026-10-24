# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15): 실행 패널의 명령 실행기(code_runner)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import code_runner  # noqa: E402

PY = f'"{sys.executable}"'


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = self.tmp.name
        self.events = []
        self.log = os.path.join(self.ws, ".log", "runs.jsonl")
        self.mgr = code_runner.RunManager(on_event=self.events.append, log_path=self.log,
                                          secrets=lambda: ["sk-supersecretvalue123"])
        self.addCleanup(self.mgr.shutdown)

    def run_cmd(self, command, timeout=60):
        rec = self.mgr.start(self.ws, command, timeout=timeout)
        self.assertTrue(self.mgr.wait(rec.id, 30), "명령이 끝나지 않았습니다")
        return rec

    def output(self, rec):
        return "".join(e["text"] for e in self.events if e.get("kind") == "run_output" and e["id"] == rec.id)

    def test_normal_run_streams_output_in_the_workspace(self):
        Path(self.ws, "hello.py").write_text("import os, time\nprint('first', flush=True)\ntime.sleep(0.4)\n"
                                             "print('cwd', os.getcwd())\n")
        rec = self.run_cmd(f"{PY} hello.py")
        self.assertEqual((rec.status, rec.code), ("done", 0))
        out = self.output(rec)
        self.assertIn("first", out)
        self.assertIn(os.path.realpath(self.ws), out)
        kinds = [e["kind"] for e in self.events]
        self.assertEqual(kinds[0], "run_start")
        self.assertEqual(kinds[-1], "run_exit")
        self.assertGreaterEqual(kinds.count("run_output"), 2)  # 끝나기 전에도 흘려보낸다
        self.assertEqual(rec.inputs, ["hello.py"])
        self.assertTrue(Path(self.log).is_file())

    def test_failure_exit_code_and_source_locations(self):
        Path(self.ws, "bad.py").write_text("x = 1\nraise ValueError('boom')\n")
        rec = self.run_cmd(f"{PY} bad.py")
        self.assertEqual(rec.status, "failed")
        self.assertEqual(rec.code, 1)
        self.assertIn({"path": "bad.py", "line": 2}, [{k: loc[k] for k in ("path", "line")} for loc in rec.locations])
        self.assertIn("ValueError", rec.output_tail)

    def test_stop_and_timeout_kill_the_process_tree(self):
        script = Path(self.ws, "spawn.py")
        script.write_text("import subprocess, sys, time\n"
                          "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                          "print(child.pid, flush=True)\ntime.sleep(60)\n")
        rec = self.mgr.start(self.ws, f"{PY} spawn.py")
        for _ in range(100):
            if self.output(rec).strip():
                break
            time.sleep(0.05)
        child = int(self.output(rec).split()[0])
        self.mgr.stop(rec.id)
        self.assertTrue(self.mgr.wait(rec.id, 20))
        self.assertEqual(rec.status, "stopped")
        time.sleep(0.5)
        self.assertFalse(_alive(child), "자식 프로세스가 남았습니다")
        rec = self.run_cmd(f"{PY} -c \"import time; time.sleep(30)\"", timeout=1)
        self.assertEqual(rec.status, "timeout")
        self.assertLess(rec.seconds, 10)

    def test_background_child_left_by_the_shell_is_ended(self):
        """셸은 바로 끝나는데 뒤에 띄운 자식이 출력 통로를 쥐고 있어도 실행이 끝나고 자식이 남지 않는다."""
        script = Path(self.ws, "bg.py")
        script.write_text("import subprocess, sys\n"
                          "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                          "print(c.pid, flush=True)\n")  # 자식을 두고 바로 끝난다(자식은 stdout을 물려받음)
        start = time.monotonic()
        rec = self.mgr.start(self.ws, f"{PY} bg.py", timeout=60)
        self.assertTrue(self.mgr.wait(rec.id, 20), "남은 자식 때문에 실행이 끝나지 않았습니다")
        self.assertLess(time.monotonic() - start, 15)
        child = int(self.output(rec).split()[0])
        time.sleep(0.5)
        self.assertFalse(_alive(child), "뒤에 남은 자식 프로세스가 살아 있습니다")
        self.assertIn("남은 하위 프로세스", self.output(rec))
        self.assertEqual(len(self.mgr.running()), 0)

    def test_large_output_is_limited(self):
        with patch.object(code_runner, "MAX_STREAM", 5000), patch.object(code_runner, "MAX_TAIL", 2000):
            rec = self.run_cmd(f"{PY} -c \"print('y' * 200000)\"")
        out = self.output(rec)
        self.assertLess(len(out), 5000 + 300)
        self.assertTrue(rec.truncated)
        self.assertLessEqual(len(rec.output_tail), 2000)
        self.assertEqual(rec.status, "done")

    def test_secrets_are_masked_and_secret_env_is_not_passed(self):
        with patch.dict(os.environ, {"MY_API_TOKEN": "tok-should-not-leak-9876"}):
            rec = self.run_cmd(f"{PY} -c \"import os; print('env', os.environ.get('MY_API_TOKEN')); "
                               f"print('key sk-supersecretvalue123 end'); print('ghp_' + 'a' * 30)\"")
        out = self.output(rec)
        self.assertIn("env None", out)
        self.assertNotIn("sk-supersecretvalue123", out)
        self.assertNotIn("sk-supersecretvalue123", rec.output_tail)
        self.assertNotIn("ghp_aaaa", out)
        self.assertIn("[가림]", out)

    def test_masker_handles_a_secret_split_across_chunks(self):
        m = code_runner.Masker(["SECRET-ABCDEFGH"])
        out = m.feed("hello SECRET-AB") + m.feed("CDEFGH world\n") + m.feed("", final=True)
        self.assertEqual(out, "hello [가림] world\n")
        m = code_runner.Masker(["SECRET-ABCDEFGH"])
        out = m.feed("progress 10%", force=True) + m.feed("... SECRET-ABC", force=True) + m.feed("DEFGH", final=True)
        self.assertNotIn("SECRET-ABCDEFGH", out)

    def test_masker_does_not_cut_a_key_shaped_token_in_half(self):
        m = code_runner.Masker([])
        key = "ghp_" + "A" * 36
        out = m.feed("token " + key[:20], force=True) + m.feed(key[20:] + " done", force=True) + m.feed("", final=True)
        self.assertNotIn(key[20:], out)
        self.assertNotIn(key[:20], out)

    def test_command_analysis_marks_network_and_dangerous_commands(self):
        a = code_runner.analyze("git push --force origin main")
        self.assertTrue(a["network"])
        self.assertTrue(any("이력" in d or "덮어씁니다" in d for d in a["dangers"]))
        self.assertTrue(code_runner.analyze("rm -rf build")["dangers"])
        self.assertTrue(code_runner.analyze("git reset --hard HEAD~1")["dangers"])
        self.assertTrue(code_runner.analyze("git clean -fd")["dangers"])
        quiet = code_runner.analyze("verilator --lint-only -Wall design.sv")
        self.assertEqual((quiet["network"], quiet["dangers"]), (False, []))
        self.assertFalse(code_runner.analyze("make 2>&1")["dangers"])

    def test_bad_requests(self):
        with self.assertRaises(code_runner.RunnerError):
            self.mgr.start(self.ws, "   ")
        with self.assertRaises(code_runner.RunnerError):
            self.mgr.start(self.ws, "x" * (code_runner.MAX_COMMAND + 1))

    def test_rtl_tool_detection_does_not_bundle_tools(self):
        names = {t["name"] for t in code_runner.tools()}
        self.assertTrue({"verilator", "iverilog", "yosys", "git"} <= names)
        loc = code_runner.find_locations(self.ws, "%Error: design.sv:12:5: syntax error")
        self.assertEqual(loc, [])  # 작업 폴더에 없는 파일은 고르지 않는다
        Path(self.ws, "design.sv").write_text("module m;\nendmodule\n")
        loc = code_runner.find_locations(self.ws, "%Error: design.sv:2:5: syntax error\n%Warning-WIDTH: design.sv:1:1: x")
        self.assertEqual([(x["path"], x["line"], x["col"]) for x in loc], [("design.sv", 2, 5), ("design.sv", 1, 1)])


def _alive(pid):
    if os.name == "nt":
        import subprocess
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # 좀비(끝났지만 거두지 않음)는 살아 있지 않은 것으로 본다
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split()[2] != "Z"
    except OSError:
        return True


if __name__ == "__main__":
    unittest.main()
