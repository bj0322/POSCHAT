# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.9.2 데이터 폴더에서 1.10을 처음 실행할 때: 기존 파일은 그대로, 백업은 한 번, 새 기능은 모두 꺼진 채로."""
import json
import os
import sys
import types
import unittest

sys.modules.setdefault("webview", types.ModuleType("webview"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # support.py

import connectors
import mcp_client
import storage
from support import isolated_app_dir, preserved_hooks

OLD_CONFIG = {"api_key": "posech-key", "workspace": "", "agent_mode": True, "history_messages": 20, "share_threads": True,
              "api_mode": "chat_completions", "migrated_1_9": True, "model": "gpt-5.1-gs-2025-11-13",
              "notion_token": "ntn_old", "mcp_disabled": ["excel"]}


class MigrationTests(unittest.TestCase):
    def test_first_1_10_start_backs_up_once_and_changes_nothing(self):
        import main

        with isolated_app_dir() as root, preserved_hooks():
            (root / "config.json").write_text(json.dumps(OLD_CONFIG), encoding="utf-8")
            (root / "memory.md").write_text(storage.MEMORY_TEMPLATE + "- 답변은 표로\n", encoding="utf-8")
            (root / "USER.md").write_text("# 사용자 정보\n- 대학원생\n", encoding="utf-8")
            (root / "mcp.json").write_text(json.dumps({"mcpServers": {"fs": {"command": "npx"}}}), encoding="utf-8")
            thread = {"id": "a" * 32, "title": "예전 대화", "created": 1, "updated": 2, "model": "gpt-5.1-gs-2025-11-13",
                      "messages": [{"id": "m1", "role": "user", "content": "안녕", "ts": 1},
                                   {"id": "m2", "role": "assistant", "content": "안녕하세요", "ts": 2}]}
            (root / "threads" / f"{thread['id']}.json").write_text(json.dumps(thread), encoding="utf-8")
            before = {name: (root / name).read_bytes() for name in ("memory.md", "USER.md", "mcp.json")}
            thread_before = (root / "threads" / f"{thread['id']}.json").read_bytes()

            bridge = main.Bridge()
            try:
                backups = list((root / "backups").iterdir())
                self.assertEqual(len(backups), 1)
                backup = backups[0]
                for name in ("config.json", "memory.md", "USER.md", "mcp.json", "README.txt"):
                    self.assertTrue((backup / name).is_file(), name)
                self.assertEqual(json.loads((backup / "config.json").read_text())["notion_token"], "ntn_old")
                self.assertTrue((backup / "threads" / f"{thread['id']}.json").is_file())
                # 기존 파일·설정은 그대로
                for name, data in before.items():
                    self.assertEqual((root / name).read_bytes(), data, name)
                self.assertEqual((root / "threads" / f"{thread['id']}.json").read_bytes(), thread_before)
                config = json.loads((root / "config.json").read_text())
                for key, value in OLD_CONFIG.items():
                    self.assertEqual(config[key], value, key)
                self.assertTrue(config["migrated_1_10"])
                # 새 기능은 모두 꺼져 있고, 기존 MCP 서버 구성은 같다
                state = bridge.get_connectors()
                self.assertFalse(any(c["enabled"] for c in state["connectors"]))
                specs = bridge._mcp.specs(bridge._config, None)
                self.assertEqual({n for n, s in specs.items() if s["enabled"]},
                                 {"word", "powerpoint", "paper", "notion", "firecrawl", "fs"})
                self.assertFalse(connectors.feature_enabled(bridge._config, "sync"))
                self.assertEqual(bridge.load_thread(thread["id"])["messages"][1]["content"], "안녕하세요")
                # 1.9 답변(모델 기록 없음)에도 평가를 남길 수 있다
                self.assertTrue(bridge.feedback(thread["id"], "m2", 1)["ok"])
            finally:
                bridge._mcp.shutdown()
            bridge2 = main.Bridge()  # 두 번째 실행: 다시 백업하지 않는다
            bridge2._mcp.shutdown()
            self.assertEqual(len(list((root / "backups").iterdir())), 1)

    def test_fresh_install_makes_no_backup(self):
        import main

        with isolated_app_dir() as root, preserved_hooks():
            bridge = main.Bridge()
            bridge._mcp.shutdown()
            self.assertFalse((root / "backups").exists())
            self.assertTrue(bridge._config["migrated_1_10"])
            self.assertEqual(mcp_client.Manager().specs(bridge._config, None)["word"]["enabled"], True)


if __name__ == "__main__":
    unittest.main()
