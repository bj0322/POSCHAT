import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # support.py

import connectors
import office_mcp
import runner_mcp
import storage
from agent import Agent
from office_mcp import ToolFailure
from support import isolated_app_dir


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()
        self.ws = self.root / "ws"
        self.ws.mkdir()
        self.rootp = patch.object(office_mcp, "ROOT", self.ws)
        self.rootp.start()

    def tearDown(self):
        self.rootp.stop()
        self._dir.__exit__(None, None, None)

    def configure(self, **automation):
        storage.save_config({"automation": automation})

    def test_python_runs_in_the_workspace_without_secret_env_and_is_logged(self):
        with patch.dict(os.environ, {"MY_API_KEY": "sk-shouldnotleak1234567890", "HARMLESS": "ok"}):
            out = runner_mcp.python_run("import os, pathlib\n"
                                        "pathlib.Path('result.txt').write_text('42')\n"
                                        "print(os.environ.get('MY_API_KEY'), os.environ.get('HARMLESS'))")
        self.assertIn("종료 코드 0", out)
        self.assertIn("None ok", out)
        self.assertEqual((self.ws / "result.txt").read_text(), "42")
        log = [json.loads(line) for line in (self.root / "logs" / "exec.jsonl").read_text().splitlines()]
        self.assertEqual(log[-1]["kind"], "python")
        self.assertIn("result.txt", log[-1]["input"])

    def test_timeout_kills_the_process(self):
        self.configure(python={"timeout": 2})
        out = runner_mcp.python_run("import time\nprint('start', flush=True)\ntime.sleep(30)")
        self.assertIn("시간 초과", out)
        self.assertIn("start", out)

    def test_errors_show_the_traceback(self):
        out = runner_mcp.python_run("raise ValueError('잘못된 값')")
        self.assertIn("종료 코드 1", out)
        self.assertIn("ValueError: 잘못된 값", out)

    def test_docker_isolation_builds_a_locked_down_command(self):
        self.configure(python={"isolation": "docker", "docker_image": "python:3.12-slim", "memory_mb": 512})
        seen = {}

        def fake_run(cmd, timeout, cwd, stdin_text=None, limits=None):
            seen.update(cmd=cmd, stdin=stdin_text)
            return {"code": 0, "stdout": "ok", "stderr": "", "timed_out": False, "seconds": 0.1}

        with patch.object(runner_mcp.shutil, "which", return_value="/usr/bin/docker"), patch.object(runner_mcp, "_run", fake_run):
            runner_mcp.python_run("print(1)")
        cmd = seen["cmd"]
        self.assertEqual(cmd[:3], ["/usr/bin/docker", "run", "--rm"])
        self.assertIn("--network", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        self.assertIn(f"{self.ws}:/work", cmd)
        self.assertEqual(cmd[cmd.index("--memory") + 1], "512m")
        self.assertEqual(seen["stdin"], "print(1)")
        self.assertIn("Docker python:3.12-slim", runner_mcp.preview("python", "python_run", {}, self.ws))

    def test_ssh_allowlist_meta_characters_and_command_line(self):
        self.configure(ssh={"timeout": 30, "hosts": {"gpu1": {"host": "gpu.example.ac.kr", "user": "kim", "port": 2222,
                                                               "cwd": "/home/kim/exp", "allowed_commands": ["nvidia-smi", "python train.py"]}}})
        with self.assertRaisesRegex(ToolFailure, "셸 연결"):
            runner_mcp.ssh_run("gpu1", "nvidia-smi; rm -rf ~")
        with self.assertRaisesRegex(ToolFailure, "허용 목록"):
            runner_mcp.ssh_run("gpu1", "rm -rf ~")
        with self.assertRaisesRegex(ToolFailure, "설정에 없는"):
            runner_mcp.ssh_run("unknown", "ls")
        seen = {}

        def fake_run(cmd, timeout, cwd, stdin_text=None, limits=None):
            seen.update(cmd=cmd, timeout=timeout)
            return {"code": 0, "stdout": "GPU 0: A100", "stderr": "", "timed_out": False, "seconds": 1.0}

        with patch.object(runner_mcp.shutil, "which", return_value="/usr/bin/ssh"), patch.object(runner_mcp, "_run", fake_run):
            out = runner_mcp.ssh_run("gpu1", "python train.py --epochs 1")
        self.assertIn("A100", out)
        cmd = seen["cmd"]
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("StrictHostKeyChecking=yes", cmd)
        self.assertEqual(cmd[cmd.index("-p") + 1], "2222")
        self.assertEqual(cmd[-3:], ["kim@gpu.example.ac.kr", "--", "cd /home/kim/exp && python train.py --epochs 1"])
        self.assertEqual(seen["timeout"], 30)
        preview = runner_mcp.preview("ssh", "run", {"host": "gpu1", "command": "rm -rf /"}, self.ws)
        self.assertIn("kim@gpu.example.ac.kr:2222", preview)
        self.assertIn("막힘", preview)

    def test_notebook_must_stay_in_the_workspace(self):
        with self.assertRaises(ToolFailure):
            runner_mcp.run_notebook("../x.ipynb")
        with self.assertRaises(ToolFailure):
            runner_mcp.run_notebook("missing.ipynb")

    def test_exec_tools_show_the_target_and_always_ask(self):
        class Server:
            name, builtin = "python", True
            tools = [{"name": "python_run", "inputSchema": {}}]

            def call(self, tool, args, timeout=None):
                return "ok", False

        details = []
        agent = Agent("k", str(self.ws), True, 5, 5, on_status=lambda *a: None, on_tool=lambda *a: None,
                      confirm=lambda kind, title, detail: details.append((kind, detail)) or True,
                      cancelled=lambda: False, policy=connectors.Policy({"connectors": {"python": {"policy": {"python_run": "allow"}}}}))
        agent.mcp_servers = {"python": Server()}
        agent._execute({"action": "mcp", "tool": "python.python_run", "args": {"code": "print(1)"}})
        kind, detail = details[0]
        self.assertEqual(kind, "exec")  # 사용자가 allow로 바꿔도 실행은 묻는다
        self.assertIn("실행 대상:", detail)
        self.assertIn("print(1)", detail)


if __name__ == "__main__":
    unittest.main()
