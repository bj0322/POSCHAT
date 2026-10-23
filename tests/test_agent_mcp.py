import tempfile
import unittest

from agent import Agent


class FakeServer:
    def __init__(self, name, tools, builtin=True):
        self.name, self.tools, self.builtin = name, tools, builtin
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return f"{tool} 완료", False


def make_agent(workspace, confirm=lambda *a: True):
    tools = []
    agent = Agent("key", workspace, True, 5, 5, on_status=lambda *a: None,
                  on_tool=lambda summary, detail: tools.append(summary), confirm=confirm, cancelled=lambda: False)
    return agent, tools


class AgentMcpTests(unittest.TestCase):
    def test_write_tool_is_called_after_approval(self):
        # 1.6~1.9.2: 정의되지 않은 read_only 때문에 ai-memory가 아닌 MCP 도구가 모두 NameError로 실패했다
        with tempfile.TemporaryDirectory() as ws:
            asked = []
            agent, tools = make_agent(ws, confirm=lambda kind, title, detail: asked.append(kind) or True)
            server = FakeServer("word", [{"name": "create_document", "inputSchema": {},
                                          "annotations": {"readOnlyHint": False, "openWorldHint": False}}])
            agent.mcp_servers = {"word": server}

            result = agent._execute({"action": "mcp", "tool": "word.create_document", "args": {"path": "a.docx"}})

            self.assertIn("create_document 완료", result)
            self.assertEqual(server.calls, [("create_document", {"path": "a.docx"})])
            self.assertEqual(asked, ["edit"])
            self.assertTrue(agent._did_work)

    def test_read_only_tool_runs_without_approval(self):
        with tempfile.TemporaryDirectory() as ws:
            agent, _ = make_agent(ws, confirm=lambda *a: self.fail("읽기 도구는 묻지 않는다"))
            server = FakeServer("paper", [{"name": "search", "inputSchema": {}, "annotations": {"readOnlyHint": True}}])
            agent.mcp_servers = {"paper": server}

            result = agent._execute({"action": "mcp", "tool": "paper.search", "args": {"query": "x"}})

            self.assertIn("search 완료", result)
            self.assertFalse(agent._did_work)

    def test_denied_tool_is_not_called(self):
        with tempfile.TemporaryDirectory() as ws:
            agent, _ = make_agent(ws, confirm=lambda *a: False)
            server = FakeServer("ext", [{"name": "write", "inputSchema": {}}], builtin=False)
            agent.mcp_servers = {"ext": server}

            result = agent._execute({"action": "mcp", "tool": "ext.write", "args": {}})

            self.assertIn("거부", result)
            self.assertEqual(server.calls, [])


if __name__ == "__main__":
    unittest.main()
