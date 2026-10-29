# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.12 플러그인(plugins.py): Knowledge Work Plugins 저장소 zip에서 목록을 만들고, 설치한 플러그인의 스킬을 쓴다."""
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import isolated_app_dir  # noqa: E402

import agent  # noqa: E402
import plugins  # noqa: E402

ROOT = "knowledge-work-plugins-main/"


def marketplace_zip(extra=None):
    """실제 저장소와 같은 구조의 작은 zip."""
    files = {
        ".claude-plugin/marketplace.json": json.dumps({"name": "knowledge-work-plugins", "plugins": [
            {"name": "productivity", "displayName": "Productivity", "source": "./productivity",
             "description": "Manage tasks and memory."},
            {"name": "pdf-viewer", "displayName": "PDF Viewer", "source": "./pdf-viewer", "description": "View PDFs."},
            {"name": "brand-voice", "displayName": "Brand Voice", "source": "./partner-built/brand-voice",
             "description": "Keep your brand voice."},
            {"name": "noibu", "displayName": "Noibu", "category": "monitoring", "description": "Ecommerce.",
             "source": {"source": "git-subdir", "url": "https://github.com/Noibu/ai-plugin.git", "path": "src"}},
            {"name": "../evil", "source": "./evil", "description": "bad name"},
        ]}),
        "productivity/.claude-plugin/plugin.json": json.dumps({"name": "productivity", "version": "1.3.1",
                                                                "author": {"name": "Anthropic"}}),
        "productivity/.mcp.json": json.dumps({"mcpServers": {"slack": {"type": "http", "url": "https://mcp.slack.com/mcp"},
                                                             "notion": {"type": "http"}}}),
        "productivity/README.md": "# Productivity\nHelps you.",
        "productivity/LICENSE": "Apache License 2.0",
        "productivity/skills/start/SKILL.md": "---\nname: start\ndescription: >\n  Initialize the productivity\n  system.\n---\n"
                                               "Copy ${CLAUDE_PLUGIN_ROOT}/skills/dashboard.html here.\n",
        "productivity/skills/task-management/SKILL.md": "---\nname: task-management\ndescription: \"Track tasks in TASKS.md\"\n---\nBody\n",
        "productivity/skills/dashboard.html": "<html></html>",
        "pdf-viewer/.claude-plugin/plugin.json": json.dumps({"name": "pdf-viewer", "version": "0.2.0"}),
        "pdf-viewer/commands/annotate.md": "---\ndescription: Annotate a PDF\nargument-hint: \"[path]\"\n---\n# Annotate\n",
        "pdf-viewer/skills/view-pdf/SKILL.md": "---\nname: view-pdf\ndescription: |\n  Line one.\n  Line two.\n---\nView.\n",
        "partner-built/brand-voice/.claude-plugin/plugin.json": json.dumps({"name": "brand-voice"}),
        "partner-built/brand-voice/skills/guidelines/SKILL.md": "---\nname: guidelines\ndescription: Brand rules\n---\nx\n",
    }
    files.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(ROOT + name, text)
    return buf.getvalue()


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.iso = isolated_app_dir()
        self.root = self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)

    def seed(self, data=None):
        plugins._catalog_dir().mkdir(parents=True, exist_ok=True)
        plugins._archive().write_bytes(data or marketplace_zip())
        catalog = plugins.build_catalog()
        plugins._write_json(plugins._catalog_file(), catalog)
        return catalog

    def test_frontmatter_reads_folded_literal_and_quoted_values(self):
        meta, body = plugins.frontmatter("---\nname: a\ndescription: >\n  one\n  two\nhint: \"[x]\"\nlit: |\n  l1\n  l2\n---\nBODY")
        self.assertEqual(meta, {"name": "a", "description": "one two", "hint": "[x]", "lit": "l1\nl2"})
        self.assertEqual(body, "BODY")
        self.assertEqual(plugins.frontmatter("no front")[0], {})

    def test_catalog_lists_in_repo_plugins_and_external_ones_separately(self):
        catalog = self.seed()
        by = {p["name"]: p for p in catalog["plugins"]}
        self.assertNotIn("../evil", by)  # 이상한 이름은 버린다
        prod = by["productivity"]
        self.assertTrue(prod["installable"])
        self.assertEqual(prod["version"], "1.3.1")
        self.assertEqual(prod["author"], "Anthropic")
        self.assertEqual(prod["connectors"], ["notion", "slack"])
        self.assertEqual([s["name"] for s in prod["skills"]], ["start", "task-management"])
        self.assertEqual(prod["skills"][0]["description"], "Initialize the productivity system.")
        self.assertTrue(prod["summary"])  # 한국어 소개
        self.assertEqual(by["pdf-viewer"]["commands"][0], {"name": "annotate", "description": "Annotate a PDF", "argument": "[path]"})
        self.assertTrue(by["brand-voice"]["partner"])
        self.assertFalse(by["noibu"]["installable"])
        self.assertEqual(by["noibu"]["homepage"], "https://github.com/Noibu/ai-plugin")
        # 설치할 수 있는 것과 추천 순서가 먼저
        self.assertEqual([p["name"] for p in catalog["plugins"]][:2], ["productivity", "pdf-viewer"])  # 추천 → 그 밖의 Anthropic
        self.assertEqual(catalog["plugins"][-1]["name"], "noibu")

    def test_install_enable_disable_and_remove_change_the_agent_skills(self):
        self.seed()
        plugins.install("productivity")
        plugins.install("pdf-viewer")
        root = plugins.plugins_dir()
        self.assertTrue((root / "productivity" / "LICENSE").is_file())  # 원본의 라이선스 파일도 함께
        skills = agent.discover_skills("")
        names = sorted(k for k in skills if ":" in k)
        self.assertEqual(names, ["pdf-viewer:annotate", "pdf-viewer:view-pdf", "productivity:start", "productivity:task-management"])
        start = skills["productivity:start"]
        self.assertEqual(start.source, "플러그인 productivity")
        self.assertIn(str(root / "productivity") + "/skills/dashboard.html", start.body)  # ${CLAUDE_PLUGIN_ROOT}
        self.assertEqual(skills["pdf-viewer:view-pdf"].description, "Line one.\nLine two.")
        plugins.set_enabled("pdf-viewer", False)
        self.assertNotIn("pdf-viewer:annotate", agent.discover_skills(""))
        self.assertFalse(plugins.installed()["pdf-viewer"]["enabled"])
        plugins.remove("productivity")
        self.assertFalse((root / "productivity").exists())
        self.assertEqual(list(plugins.installed()), ["pdf-viewer"])

    def test_external_plugins_are_not_installed(self):
        self.seed()
        with self.assertRaisesRegex(plugins.PluginError, "다른 회사 저장소"):
            plugins.install("noibu")
        with self.assertRaises(plugins.PluginError):
            plugins.install("nope")

    def test_paths_outside_the_plugin_folder_are_never_written(self):
        self.seed(marketplace_zip({"productivity/skills/../../../escape.txt": "x",
                                   "productivity/skills/ok/SKILL.md": "---\nname: ok\ndescription: d\n---\n"}))
        plugins.install("productivity")
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertFalse((plugins.plugins_dir() / "escape.txt").exists())
        self.assertTrue((plugins.plugins_dir() / "productivity" / "skills" / "ok" / "SKILL.md").is_file())

    def test_reinstall_replaces_files(self):
        self.seed()
        plugins.install("productivity")
        stale = plugins.plugins_dir() / "productivity" / "skills" / "old" / "SKILL.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("---\nname: old\n---\n")
        plugins.install("productivity")
        self.assertFalse(stale.exists())

    @patch("plugins.requests.get")
    def test_download_builds_the_catalog_and_reports_errors(self, get):
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [marketplace_zip()]
        get.return_value.__enter__.return_value = response
        catalog = plugins.catalog()
        self.assertEqual(get.call_args.args[0], plugins.ARCHIVE_URL)
        self.assertIn("productivity", [p["name"] for p in catalog["plugins"]])
        get.reset_mock()
        plugins.catalog()  # 받아 둔 목록을 쓴다
        get.assert_not_called()
        response.status_code = 403
        with self.assertRaisesRegex(plugins.PluginError, "HTTP 403"):
            plugins.catalog(refresh=True)
        self.assertTrue(plugins._archive().is_file())  # 실패해도 받아 둔 것은 남는다

    def test_bridge_api(self):
        import types
        sys.modules.setdefault("webview", types.ModuleType("webview"))
        import main
        import threading

        self.seed()
        bridge = main.Bridge.__new__(main.Bridge)
        bridge._config, bridge._lock = {}, threading.RLock()
        state = bridge.plugins_state()
        self.assertTrue(state["ok"])
        self.assertNotIn("readme", state["plugins"][0])  # 목록에는 설명서를 싣지 않는다
        res = bridge.plugin_install("productivity")
        self.assertTrue(res["ok"])
        self.assertIn("productivity:start", [s["name"] for s in res["skills"]])
        detail = bridge.plugin_detail("productivity")
        self.assertIn("Helps you", detail["plugin"]["readme"])
        self.assertTrue(detail["installed"]["enabled"])
        self.assertFalse(bridge.plugin_install("noibu")["ok"])
        self.assertTrue(bridge.plugin_set_enabled("productivity", False)["ok"])
        self.assertTrue(bridge.plugin_remove("productivity")["ok"])


if __name__ == "__main__":
    unittest.main()
