# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""브라우저 에이전트(1.16) 화면 시험: 브라우저 막대의 진행 표시(동작·상태·횟수·시간), 일시정지·계속, 멈춤, 끝나면 사라짐."""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright가 없어 화면 점검을 건너뜁니다")
class BrowserAgentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ui_harness
        from support import isolated_app_dir, preserved_hooks

        cls.saved_env = {k: os.environ.get(k) for k in ("APPDATA", "POSTECH_CHAT_SECRETS")}
        cls.hooks = preserved_hooks()
        cls.hooks.__enter__()
        cls.isolation = isolated_app_dir()
        data_dir = cls.isolation.__enter__()
        cls.bridge, cls.events = ui_harness.make_bridge(data_dir)
        cls.bridge.save_settings({"api_key": "test-key"})  # 첫 실행 설정 창이 뜨지 않게
        cls.server = ui_harness.serve(cls.bridge, cls.events)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/"
        cls.init_script = ui_harness.INIT_SCRIPT
        cls.shots = os.environ.get("POSTECH_UI_SHOTS")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.bridge._events.stop()
        cls.bridge._mcp.shutdown()
        for k, v in cls.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.isolation.__exit__(None, None, None)
        cls.hooks.__exit__(None, None, None)

    def test_progress_strip(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(**({"executable_path": CHROMIUM} if CHROMIUM else {}))
            page = browser.new_page(viewport={"width": 1300, "height": 800})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(self.init_script)
            page.goto(self.url)
            page.wait_for_selector("#btn-browser", state="attached")  # 이 시험 환경(리눅스)에는 브라우저가 없어 숨겨진다
            page.wait_for_function("typeof renderBrowserBar === 'function'")
            try:
                # 브라우저 막대를 연 상태(네이티브 뷰는 이 시험에 없다)
                page.evaluate("BR.open = true; BR.url = 'https://example.com/'; renderBrowserBar()")
                self.assertTrue(page.is_hidden("#browser-agent"))
                page.evaluate("""onBackendEvent({type: 'browser', kind: 'agent', action: 'click', status: 'running',
                                 target: '검색', count: 3, limit: 40, elapsed: 12.4})""")
                text = page.inner_text("#browser-agent-text")
                for part in ("누르기", "검색", "하는 중", "3/40번", "12초"):
                    self.assertIn(part, text)
                # 일시정지 → 백엔드 이벤트로 '계속' 버튼이 된다
                page.click("#browser-agent-pause")
                page.wait_for_selector("#browser-agent.paused")
                self.assertEqual(page.inner_text("#browser-agent-pause"), "계속")
                self.assertTrue(self.bridge._browser_pause_event().is_set())
                page.click("#browser-agent-pause")
                page.wait_for_selector("#browser-agent:not(.paused)")
                self.assertFalse(self.bridge._browser_pause_event().is_set())
                page.evaluate("""onBackendEvent({type: 'browser', kind: 'agent', action: 'click', status: 'denied',
                                 summary: 'e4 button 저장소 삭제', count: 4, limit: 40, elapsed: 20})""")
                self.assertIn("거부됨", page.inner_text("#browser-agent-text"))
                self.assertIn("error", page.get_attribute("#browser-agent", "class"))
                if self.shots:
                    os.makedirs(self.shots, exist_ok=True)
                    page.screenshot(path=os.path.join(self.shots, "browser-agent-strip.png"), clip={"x": 260, "y": 0, "width": 1040, "height": 160})
                page.click("#browser-agent-stop")
                page.wait_for_selector("#toast:has-text('멈췄습니다')")
                page.evaluate("onBackendEvent({type: 'browser', kind: 'agent', status: 'finished', count: 4})")
                self.assertTrue(page.is_hidden("#browser-agent"))
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
