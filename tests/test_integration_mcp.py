# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""통합 테스트: 커넥터의 내장 서버를 실제로 띄워(데스크톱: 하위 프로세스, 안드로이드: 스레드) MCP로 주고받는다.

네트워크는 쓰지 않는다. 도구 목록, 인자 검사 오류, 인증 정보 없음 오류가 MCP 경로를 그대로 지나는지 본다.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # support.py

import connectors
import mcp_client
from agent import Agent
from support import isolated_app_dir

CONFIG = {"connectors": {"github": {"enabled": True}, "gmail": {"enabled": True}}}


class ConnectorServerIntegrationTests(unittest.TestCase):
    def check_manager(self, manager, ws):
        servers = {s.name: s for s in manager.ensure(CONFIG, ws)}
        status = {s["name"]: s for s in manager.status(CONFIG, ws)["servers"]}
        self.assertIn("github", servers, status.get("github"))
        self.assertIn("gmail", servers, status.get("gmail"))
        github = servers["github"]
        self.assertEqual(github.connector, "github")
        self.assertEqual({t["name"] for t in github.tools}, set(connectors.TOOL_KINDS["github"]))
        # 인자 검사는 네트워크 전에 실패한다
        text, is_error = github.call("get_file", {"repo": "../.."})
        self.assertTrue(is_error)
        self.assertIn("owner/name", text)
        # 토큰이 없으면 [인증 필요]
        text, is_error = github.call("whoami", {})
        self.assertTrue(is_error)
        self.assertIn(connectors.NEEDS_AUTH_TAG, text)
        text, is_error = servers["gmail"].call("search_messages", {"query": "x"})
        self.assertIn(connectors.NEEDS_AUTH_TAG, text)
        return servers

    def test_subprocess_servers(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as ws, \
                patch.dict(os.environ, {"APPDATA": data, "POSTECH_CHAT_SECRETS": "file"}):
            manager = mcp_client.Manager()
            try:
                self.check_manager(manager, ws)
            finally:
                manager.shutdown()

    def test_inprocess_servers_like_android(self):
        with isolated_app_dir(), tempfile.TemporaryDirectory() as ws, patch.object(mcp_client, "INPROCESS_BUILTIN", True):
            manager = mcp_client.Manager()
            try:
                servers = self.check_manager(manager, ws)
                self.assertEqual(servers["github"].command, mcp_client.INPROCESS)
            finally:
                manager.shutdown()

    def test_agent_reports_needs_auth_through_the_gateway(self):
        with isolated_app_dir(), tempfile.TemporaryDirectory() as ws, patch.object(mcp_client, "INPROCESS_BUILTIN", True):
            manager = mcp_client.Manager()
            try:
                agent = Agent("key", ws, True, 5, 5, on_status=lambda *a: None, on_tool=lambda *a: None,
                              confirm=lambda *a: True, cancelled=lambda: False, policy=connectors.Policy(CONFIG))
                agent.mcp_servers = {s.name: s for s in manager.ensure(CONFIG, ws)}
                result = agent._execute({"action": "mcp", "tool": "github.whoami", "args": {}})
                self.assertIn(connectors.NEEDS_AUTH_TAG, result)
                self.assertTrue(result.startswith("[외부 데이터: github.whoami"))
                self.assertEqual(connectors._health["github"]["state"], "needs_auth")
                self.assertEqual(connectors.status(CONFIG, "github")["state"], "needs_auth")
            finally:
                manager.shutdown()


if __name__ == "__main__":
    unittest.main()
