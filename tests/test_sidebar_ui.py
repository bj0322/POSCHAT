# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.16 사이드바 화면 시험: 채팅 목록이 남는 세로 공간을 쓰고 혼자 스크롤하며, 아래 메뉴는 촘촘하지만 그대로 동작한다.

Playwright가 없으면 건너뛴다. POSTECH_UI_SHOTS 폴더가 주어지면 화면 크기별 스크린숏을 남긴다.
"""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
MEASURE = """() => {
  const list = document.querySelector('#thread-list'); const lr = list.getBoundingClientRect();
  const visible = [...list.querySelectorAll('.thread')].filter((t) => { const r = t.getBoundingClientRect();
    return r.top >= lr.top - 1 && r.bottom <= lr.bottom + 1; }).length;
  const bottom = document.querySelector('.sb-bottom').getBoundingClientRect();
  const sb = document.querySelector('#sidebar').getBoundingClientRect();
  return { visible, listH: lr.height, bottomH: bottom.height, bottomInside: bottom.bottom <= sb.bottom + 1,
           scrollable: list.scrollHeight > list.clientHeight };
}"""


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright가 없어 화면 점검을 건너뜁니다")
class SidebarUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import storage
        import ui_harness
        from support import isolated_app_dir, preserved_hooks

        cls.saved_env = {k: os.environ.get(k) for k in ("APPDATA", "POSTECH_CHAT_SECRETS")}
        cls.hooks = preserved_hooks()
        cls.hooks.__enter__()
        cls.isolation = isolated_app_dir()
        data_dir = cls.isolation.__enter__()
        cls.bridge, cls.events = ui_harness.make_bridge(data_dir)
        cls.bridge.save_settings({"api_key": "test-key"})
        for i in range(60):
            t = storage.new_thread()
            t["title"] = f"대화 {i + 1:02d}"
            storage.save_thread(t)
        ws = os.path.join(str(data_dir), "a-very-long-workspace-folder-name-for-ellipsis")
        os.makedirs(ws)
        cls.bridge._config["workspace"] = ws
        cls.ws = ws
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

    def page(self, p, width, height, scale=1):
        browser = p.chromium.launch(**({"executable_path": CHROMIUM} if CHROMIUM else {}))
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(self.init_script)
        page.goto(self.url)
        page.wait_for_selector("#thread-list .thread")
        return browser, page, errors

    def test_thread_list_uses_the_height_and_scrolls_alone(self):
        from playwright.sync_api import sync_playwright

        # 1366×768에서 바꾸기 전에는 채팅 1개만 보였다(아래 메뉴 269px). 지금 기대값은 넉넉히 잡는다.
        expected = {(1920, 1080, 1): 12, (1366, 768, 1): 5, (1280, 720, 1.5): 3, (1100, 600, 1): 2}
        with sync_playwright() as p:
            for (w, hgt, scale), want in expected.items():
                browser, page, errors = self.page(p, w, hgt, scale)
                try:
                    m = page.evaluate(MEASURE)
                    self.assertGreaterEqual(m["visible"], want, f"{w}x{hgt}@{scale}: {m}")
                    self.assertLess(m["bottomH"], 230, m)  # 바꾸기 전 269px
                    self.assertTrue(m["bottomInside"], m)
                    self.assertTrue(m["scrollable"], m)
                    if self.shots:
                        os.makedirs(self.shots, exist_ok=True)
                        page.screenshot(path=os.path.join(self.shots, f"sidebar-{w}x{hgt}@{scale}.png"),
                                        clip={"x": 0, "y": 0, "width": 270, "height": hgt})
                    self.assertEqual(errors, [])
                finally:
                    browser.close()

    def test_scroll_select_rename_and_keyboard_still_work(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.page(p, 1366, 768)
            try:
                bottom_before = page.evaluate("document.querySelector('.sb-bottom').getBoundingClientRect().top")
                page.evaluate("document.querySelector('#thread-list').scrollTop = 600")
                top = page.evaluate("document.querySelector('#thread-list').scrollTop")
                self.assertGreater(top, 0)
                # 목록만 스크롤하고 아래 메뉴는 움직이지 않는다
                self.assertEqual(page.evaluate("document.querySelector('.sb-bottom').getBoundingClientRect().top"), bottom_before)
                # 다시 그려도(대화 열기·목록 갱신) 스크롤 자리를 지킨다
                page.evaluate("renderSidebar()")
                self.assertEqual(page.evaluate("document.querySelector('#thread-list').scrollTop"), top)
                item = page.locator("#thread-list .thread:has-text('대화 30')")
                item.click()
                page.wait_for_function("document.querySelector('#chat-title').textContent.includes('대화 30')")
                page.click("#thread-list .thread.active button[title='이름 변경']")
                page.fill("#thread-list .thread input", "이름 바꾼 대화")
                page.keyboard.press("Enter")
                page.wait_for_selector("#thread-list .thread:has-text('이름 바꾼 대화')")
                # 작업 폴더 경로는 말줄임하고 전체 경로는 툴팁으로
                self.assertEqual(page.get_attribute("#btn-workspace", "title"), self.ws)
                # 키보드: 기능 버튼과 아래 메뉴에 초점을 줄 수 있고 이름이 있다
                for sel, name in (("#btn-research", "연구 라이브러리"), ("#btn-auto", "에이전트 자동화"), ("#btn-lab", "Lab")):
                    self.assertIn(name, page.get_attribute(sel, "aria-label"))
                page.focus("#btn-settings")
                self.assertEqual(page.evaluate("document.activeElement.id"), "btn-settings")
                heights = page.evaluate("[...document.querySelectorAll('.sb-item, .sb-features .new-chat')]"
                                        ".filter(e => e.offsetParent).map(e => e.getBoundingClientRect().height)")
                self.assertGreaterEqual(min(heights), 30)  # 누르기 불편할 만큼 작지 않다
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_phone_drawer(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.page(p, 390, 800)
            try:
                page.click("#btn-expand")
                m = page.evaluate(MEASURE)
                self.assertGreaterEqual(m["visible"], 5, m)
                self.assertTrue(m["bottomInside"], m)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
                page.click("#btn-paper")
                page.wait_for_selector(".paper-sidebar-open", state="visible")
                page.click(".paper-sidebar-open")
                self.assertFalse(page.evaluate("document.querySelector('#app').classList.contains('collapsed')"))
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_opening_views_collapses_sidebar_and_can_reopen_it(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.page(p, 1366, 768)
            try:
                page.route("**/api/browser_show", lambda route: route.fulfill(json={"ok": True}))
                page.route("**/api/browser_hide", lambda route: route.fulfill(json={"ok": True}))
                page.evaluate("BR.available = true; document.querySelector('#btn-browser').hidden = false")
                page.click("#btn-browser")
                page.wait_for_function("document.querySelector('#app').classList.contains('collapsed')")
                self.assertTrue(page.is_visible("#btn-expand"))
                page.click("#btn-expand")
                self.assertFalse(page.evaluate("document.querySelector('#app').classList.contains('collapsed')"))
                page.click("#btn-research")
                self.assertTrue(page.evaluate("document.querySelector('#app').classList.contains('collapsed')"))
                page.click("#btn-expand")
                page.click("#btn-code")
                page.wait_for_selector("#code-sidebar-open", state="visible")
                page.click("#code-sidebar-open")
                self.assertFalse(page.evaluate("document.querySelector('#app').classList.contains('collapsed')"))
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
