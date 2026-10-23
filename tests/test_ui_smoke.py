# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
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
        from support import isolated_app_dir, preserved_hooks

        cls.saved_env = {k: os.environ.get(k) for k in ("APPDATA", "POSTECH_CHAT_SECRETS")}
        cls.hooks = preserved_hooks()
        cls.hooks.__enter__()
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
        cls.server.server_close()
        cls.bridge._mcp.shutdown()
        for k, v in cls.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.isolation.__exit__(None, None, None)
        cls.hooks.__exit__(None, None, None)

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

    def test_research_tab_indexes_the_workspace_and_cites_sources(self):
        from playwright.sync_api import sync_playwright

        ws = os.path.join(os.environ["APPDATA"], "ws")  # make_bridge가 데이터 폴더(임시)로 바꿔 둔 값
        os.makedirs(ws, exist_ok=True)
        with open(os.path.join(ws, "notes.md"), "w", encoding="utf-8") as f:
            f.write("# 실험 기록\n학습률을 0.001로 낮췄더니 손실이 안정되었다.\n")
        self.bridge._config["workspace"] = ws
        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.evaluate("showHub('research')")
                page.wait_for_selector(".hub-panel .feature-toggle")
                page.locator(".hub-panel .feature-toggle input").first.check()
                page.wait_for_selector("text=에이전트 도구 켜기")
                page.click("text=작업 폴더 인덱싱")
                page.wait_for_selector("text=인덱싱 완료", timeout=20000)
                box = page.locator("input[placeholder^='인덱스에서 찾기']")
                box.fill("학습률 손실")
                box.press("Enter")
                page.wait_for_selector(".rag-hit")
                self.assertIn("[1] 원문 · notes.md §실험 기록", page.locator(".rag-hit").first.inner_text())
                self.shot(page, "hub-research")
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_memory_tab_adds_memory_and_turns_on_encrypted_sync(self):
        from playwright.sync_api import sync_playwright

        ws = os.path.join(os.environ["APPDATA"], "proj")
        shared = os.path.join(os.environ["APPDATA"], "cloud")
        os.makedirs(ws, exist_ok=True)
        os.makedirs(shared, exist_ok=True)
        self.bridge._config["workspace"] = ws
        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.evaluate("showHub('memory')")
                page.wait_for_selector(".hub-panel .feature-toggle")
                page.locator(".feature-toggle", has_text="통합 메모리").locator("input").check()
                page.wait_for_selector("text=에이전트 도구 켜기")
                page.fill(".hub-panel textarea", "배포는 금요일에 하지 않기로 함")
                page.locator(".hub-panel select").nth(2).select_option("decision")
                page.click("button:has-text('남기기')")
                page.wait_for_selector(".mem-text:has-text('배포는 금요일')")
                self.assertIn("default/proj", page.locator(".hub-panel").inner_text())
                page.locator(".feature-toggle", has_text="클라우드 동기화").locator("input").check()
                page.wait_for_selector("text=동기화 켜기")
                page.fill("input[placeholder='동기화 폴더 경로']", shared)
                page.fill("input[placeholder^='동기화 암호']", "correct horse battery")
                page.fill("input[placeholder='한 번 더']", "correct horse battery")
                page.click("button:has-text('동기화 켜기')")
                page.wait_for_selector("text=동기화했습니다", timeout=30000)
                self.assertTrue(os.path.exists(os.path.join(shared, "poschat-sync", "meta.json")))
                with open(os.path.join(shared, "poschat-sync", "meta.json"), encoding="utf-8") as f:
                    self.assertNotIn("correct horse", f.read())
                self.shot(page, "hub-memory")
                self.assertEqual(errors, [])
            finally:
                browser.close()
                self.bridge.sync_disconnect()

    def test_automation_tab_registers_an_ssh_host(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.evaluate("showHub('automation')")
                page.wait_for_selector(".hub-panel .feature-toggle")
                page.locator(".feature-toggle", has_text="에이전트 자동화").locator("input").check()
                page.wait_for_selector("text=Python · Jupyter")
                page.locator(".feature-toggle", has_text="Python·Jupyter 실행").locator("input").check()
                page.wait_for_function("() => document.querySelector('.hub-panel').innerText.includes('Python')")
                page.click("summary:has-text('호스트 등록')")
                page.fill("input[placeholder^='별칭']", "gpu1")
                page.fill("input[placeholder^='호스트']", "gpu.example.ac.kr")
                page.fill("input[placeholder='사용자']", "kim")
                page.fill("input[placeholder^='허용 명령']", "nvidia-smi, python train.py")
                page.click("button:has-text('등록')")
                page.wait_for_selector("td.mono:has-text('gpu1')")
                hosts = self.bridge._config["automation"]["ssh"]["hosts"]
                self.assertEqual(hosts["gpu1"]["allowed_commands"], ["nvidia-smi", "python train.py"])
                python = next(c for c in self.bridge.get_connectors()["connectors"] if c["id"] == "python")
                self.assertTrue(python["enabled"])
                self.shot(page, "hub-automation")
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_feedback_shows_up_in_diagnostics(self):
        from playwright.sync_api import sync_playwright

        import storage
        import telemetry

        thread = self.bridge.new_thread()
        thread = storage.load_thread(thread["id"])
        thread["title"] = "평가 테스트"
        thread["messages"] += [storage.make_message("user", "안녕"),
                               storage.make_message("assistant", "안녕하세요! 무엇을 도와드릴까요?", model="claude-sonnet-5-5")]
        storage.save_thread(thread)
        telemetry.record("llm_call", mode="chat_completions", model="claude-sonnet-5-5", ok=True, ms=850,
                         input_tokens=500, output_tokens=150)
        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.evaluate(f"openThread('{thread['id']}')")
                page.wait_for_selector(".msg.assistant .msg-actions button[title='좋은 답변']")
                page.click(".msg.assistant .msg-actions button[title='좋은 답변']")
                page.wait_for_selector(".msg.assistant .msg-actions button.active")
                self.assertEqual(storage.load_thread(thread["id"])["messages"][1]["feedback"], 1)
                page.evaluate("showHub('diagnostics')")
                page.wait_for_selector(".diag-table")
                row = page.locator(".diag-table tr", has_text="claude-sonnet-5-5").first.inner_text()
                self.assertIn("850ms", row)
                self.assertIn("\t28\t", row)  # 크레딧: 24 + 500/250 + 150/75 = 28
                self.shot(page, "hub-diagnostics")
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

    def test_settings_show_the_license_source_and_third_party_licenses(self):
        from playwright.sync_api import sync_playwright
        from version import APP_VERSION

        with sync_playwright() as p:
            for width, height in ((1240, 860), (390, 844)):
                browser, page, errors = self.open(p, width, height)
                try:
                    page.evaluate("showSettings()")
                    block = page.wait_for_selector(".license-block")
                    block.scroll_into_view_if_needed()
                    text = block.inner_text()
                    for want in ("POSCHAT", "Copyright © 2026 Beomjoon Kim", "GNU Affero General Public License v3.0 only"):
                        self.assertIn(want, text)
                    source = page.get_by_text("소스 코드 보기")
                    page.wait_for_function("document.querySelector('.license-block a.btn').href.includes('/tree/')")
                    self.assertTrue(source.get_attribute("href").endswith(f"/tree/v{APP_VERSION}"))
                    self.shot(page, f"license-settings-{width}")
                    page.get_by_text("라이선스 보기").click()
                    page.wait_for_selector(".license-text")
                    self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", page.locator(".license-text").first.inner_text())
                    self.assertIn("AGPL-3.0-only", page.locator(".modal h2").last.inner_text())
                    self.shot(page, f"license-text-{width}")
                    page.locator(".modal-head .icon-btn").last.click()
                    page.get_by_text("제3자 라이선스", exact=True).first.click()
                    page.wait_for_selector("details summary")
                    names = page.locator("details summary").all_inner_texts()
                    self.assertIn("THIRD_PARTY_NOTICES.md", names)
                    self.assertIn("KaTeX-LICENSE.txt", names)
                    overflow = page.evaluate("Math.max(...[...document.querySelectorAll('.modal')].map(m => m.scrollWidth - m.clientWidth))")
                    self.assertLessEqual(overflow, 1)
                    self.shot(page, f"license-third-{width}")
                    self.assertEqual(errors, [])
                finally:
                    browser.close()


if __name__ == "__main__":
    unittest.main()
