"""화면 통합 점검: 실제 Bridge에 붙은 web/ 화면을 Chromium(Playwright)으로 열어 '연결·도구' 창을 조작한다.

Playwright가 없으면(기본 CI) 건너뛴다. 스크린숏은 POSTECH_UI_SHOTS 폴더가 주어지면 거기에 남긴다.
"""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CARD_HAS = "([name, text]) => [...document.querySelectorAll('.conn-card')].some((c) => c.innerText.includes(name) && c.innerText.includes(text))"
HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright가 없어 화면 점검을 건너뜁니다")
class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ui_harness
        from support import isolated_app_dir

        cls.saved_env = {k: os.environ.get(k) for k in ("APPDATA", "POSTECH_CHAT_SECRETS")}
        cls.isolation = isolated_app_dir()
        data_dir = cls.isolation.__enter__()  # 다른 테스트가 storage를 먼저 불러왔어도 임시 폴더를 쓴다
        cls.bridge, cls.events = ui_harness.make_bridge(data_dir)
        cls.bridge.save_settings({"api_key": "test-key"})  # 첫 실행 설정 창이 뜨지 않게
        cls.server = ui_harness.serve(cls.bridge, cls.events)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/"
        cls.init_script = ui_harness.INIT_SCRIPT
        cls.shots = os.environ.get("POSTECH_UI_SHOTS")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.bridge._mcp.shutdown()
        for k, v in cls.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.isolation.__exit__(None, None, None)

    def shot(self, page, name):
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
            page.screenshot(path=os.path.join(self.shots, f"{name}.png"), full_page=False)

    def open(self, p, width=1240, height=860):
        browser = p.chromium.launch(**({"executable_path": CHROMIUM} if CHROMIUM else {}))
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.add_init_script(self.init_script)
        page.goto(self.url)
        page.wait_for_selector("#btn-mcp")
        return browser, page, errors

    def test_hub_connectors_and_mcp_tabs(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.click("#btn-mcp")
                page.wait_for_selector(".hub-tab.active")
                page.wait_for_selector(".conn-card")
                cards = page.locator(".conn-card")
                self.assertGreaterEqual(cards.count(), 7)
                github = cards.filter(has_text="GitHub").first
                self.assertIn("비활성화", github.inner_text())
                self.shot(page, "hub-connectors")
                # GitHub 켜기 → 인증 필요
                github.locator("input[type=checkbox]").first.check()
                page.wait_for_function(CARD_HAS, arg=["GitHub", "인증 필요"])
                # 토큰 저장 → 연결됨(확인 전)
                github.locator("summary").first.click()
                github = page.locator(".conn-card").filter(has_text="GitHub").first
                github.locator("input[type=password]").first.fill("github_pat_uitest1234567890")
                github.locator("button", has_text="저장").first.click()
                page.wait_for_function(CARD_HAS, arg=["GitHub", "연결됨"])
                self.assertTrue(self.bridge.get_connectors()["connectors"][0]["secrets"][0]["has"])
                self.assertNotIn("github_pat_uitest", page.content())  # 저장한 토큰은 화면으로 돌아오지 않는다
                # 도구 정책: 전송 도구는 '묻지 않고 허용'을 고를 수 없다
                review = page.locator(".policy-table tr", has_text="create_pull_review").first
                self.assertTrue(review.locator("option[value=allow]").is_disabled())
                review.locator("select").select_option("deny")
                page.wait_for_timeout(300)
                policy = self.bridge._config["connectors"]["github"]["policy"]
                self.assertEqual(policy["create_pull_review"], "deny")
                self.shot(page, "hub-github-open")
                # MCP 탭: 기존 내장 서버와 켠 커넥터 서버가 보인다
                page.click(".hub-tab:has-text('MCP 서버')")
                page.wait_for_selector(".hub-panel .skill-item")
                text = page.locator(".hub-panel").inner_text()
                for name in ("word", "paper", "notion", "github"):
                    self.assertIn(name, text)
                self.shot(page, "hub-mcp")
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_hub_fits_a_phone_screen(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.open(p, 390, 844)
            try:
                page.evaluate("showHub('connectors')")
                page.wait_for_selector(".conn-card")
                overflow = page.evaluate("document.querySelector('.modal').scrollWidth - document.querySelector('.modal').clientWidth")
                self.assertLessEqual(overflow, 1)
                self.shot(page, "hub-phone")
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
