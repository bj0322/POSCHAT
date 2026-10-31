# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Lab(1.16) 화면 시험: 실제 Bridge에 붙은 web/ 화면을 Chromium(Playwright)으로 열어 Lab을 조작한다.

새 실험 → 실행 설정 → 실행 승인 → Run 완료·재현성 기록 → 결과 미리 보기·지표 뽑기 → 두 번째 Run →
비교(다른 조건 강조) → 그래프(SVG, 여러 Run 겹치기) → 결과 가져오기 → AI에게 묻기(채팅 첨부) → 기록 지우기(파일은 남음) → 휴대폰 폭.
Playwright가 없으면 건너뛴다. 스크린숏은 POSTECH_UI_SHOTS 폴더가 주어지면 거기에 남긴다.
"""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
TRAIN = """import argparse, csv, os
p = argparse.ArgumentParser(); p.add_argument('--lr', type=float)
a = p.parse_args()
os.makedirs('out', exist_ok=True)
with open('out/history.csv', 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['epoch', 'loss', 'acc (%)'])
    for e in range(1, 6):
        w.writerow([e, round(1 / (e * a.lr * 10 + 1), 4), round(50 + e * a.lr * 50, 2)])
print('done lr', a.lr)
"""


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright가 없어 화면 점검을 건너뜁니다")
class LabUiTests(unittest.TestCase):
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
        cls.bridge.save_settings({"api_key": "test-key"})
        cls.ws = Path(data_dir) / "lab ws"
        (cls.ws / "results").mkdir(parents=True)
        (cls.ws / "train.py").write_text(TRAIN)
        (cls.ws / "results" / "server.json").write_text(json.dumps({"final": {"acc": 0.93, "latency_ms": 4.2}}))
        cls.bridge._config["workspace"] = str(cls.ws)
        cls.server = ui_harness.serve(cls.bridge, cls.events)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/"
        cls.init_script = ui_harness.INIT_SCRIPT
        cls.shots = os.environ.get("POSTECH_UI_SHOTS")

    @classmethod
    def tearDownClass(cls):
        import lab_store

        cls.server.shutdown()
        cls.server.server_close()
        cls.bridge._code_shutdown()
        cls.bridge._events.stop()
        cls.bridge._mcp.shutdown()
        lab_store.close()
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

    def open(self, p, width=1400, height=900):
        browser = p.chromium.launch(**({"executable_path": CHROMIUM} if CHROMIUM else {}))
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.add_init_script(self.init_script)
        page.goto(self.url)
        page.wait_for_selector("#btn-lab")
        return browser, page, errors

    def run_once(self, page, lr):
        page.click(".lab-head button:has-text('실행')")
        dialog = page.locator(".modal:has(h2:has-text('실행할 설정'))")
        dialog.wait_for()
        dialog.locator("input[aria-label='파라미터 값']").first.fill(str(lr))
        dialog.locator("button:has-text('다음')").click()
        approve = page.locator(".modal:has(h2:has-text('실험 실행 승인'))")
        approve.wait_for()
        self.assertIn(f"--lr {lr}", approve.locator("pre").inner_text())
        self.assertIn("Git 커밋", approve.inner_text())
        approve.locator("input[aria-label='Run 이름']").fill(f"lr {lr}")
        approve.locator(".modal-foot button:has-text('실행')").click()
        page.wait_for_selector(".lab-run .lab-st:has-text('완료')", timeout=30000)

    def test_lab_flow(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.click("#btn-lab")
                page.wait_for_selector(".po-intro:has-text('POSCHAT Lab')")
                self.assertIn("active", page.get_attribute("#btn-lab", "class"))
                self.shot(page, "lab-empty")
                # 새 실험
                page.click(".lab-new")
                page.fill(".modal input[aria-label='실험 이름']", "학습률 비교")
                page.fill(".modal textarea[aria-label='설명']", "lr이 정확도에 주는 영향")
                page.click(".modal-foot button:has-text('만들기')")
                page.wait_for_selector(".lab-title h1:has-text('학습률 비교')")
                # 실행 설정(새 실험은 설정 탭이 열린다)
                page.wait_for_selector(".lab-form")
                page.select_option(".lab-form select[aria-label='실행 방식']", "python")
                page.fill(".lab-form input[aria-label='스크립트·노트북 경로']", "train.py")
                page.click(".lab-form button:has-text('+ 파라미터')")
                page.fill(".lab-form input[aria-label='파라미터 이름']", "lr")
                page.fill(".lab-form input[aria-label='파라미터 값']", "0.1")
                page.fill(".lab-form input[aria-label='결과 파일 패턴']", "out/*.csv")
                page.click("button:has-text('설정 저장')")
                page.wait_for_selector("#toast:has-text('실행 설정을 저장했습니다')")
                # 실행(승인) → 완료
                self.run_once(page, 0.1)
                body = page.inner_text(".lab-run")
                self.assertIn("종료 코드 0", body)
                self.assertIn("Git 기록 없음", body)
                self.assertIn("out/history.csv", body)
                self.assertIn("done lr 0.1", page.inner_text("#lab-log"))
                self.shot(page, "lab-run")
                # 결과 미리 보기 → 지표 뽑기(고른 열만)
                page.click(".lab-outputs button:has-text('미리 보기')")
                modal = page.locator(".modal:has(h3:has-text('지표로 쓸 값 고르기'))")
                modal.wait_for()
                choice = modal.locator(".lab-choice:has-text(\"열 'acc (%)'\")")
                choice.locator("input[type=checkbox]").check()
                choice.locator("select").select_option("max")
                modal.locator("button:has-text('지표 저장')").click()
                page.wait_for_selector(".lab-sec:has(h3:has-text('지표')) td:has-text('acc')")
                metrics = page.inner_text(".lab-sec:has(h3:has-text('지표')) table")
                self.assertIn("%", metrics)
                self.assertIn("history.csv", metrics)
                self.assertNotIn("epoch", metrics)  # 고르지 않은 열은 지표가 아니다
                # 두 번째 Run(같은 규칙으로 지표 자동)
                self.run_once(page, 0.3)
                page.wait_for_selector(".lab-sec:has(h3:has-text('지표')) td:has-text('acc')")
                # 개요 → 두 Run 고르기 → 비교
                page.click("#lab-tab-overview")
                boxes = page.locator(".lab-table input[type=checkbox]")
                self.assertEqual(boxes.count(), 2)
                boxes.nth(0).check()
                page.locator(".lab-table input[type=checkbox]").nth(1).check()
                page.click("button:has-text('고른 Run 비교')")
                page.wait_for_selector(".lab-compare")
                diff = page.inner_text(".lab-compare tr.lab-diff")
                self.assertIn("lr", diff)
                self.assertIn("▲", page.inner_text(".lab-compare"))
                self.shot(page, "lab-compare")
                # 그래프: 두 Run 겹쳐 그리기, 축 단위, 전체 통계
                page.click("#lab-tab-chart")
                page.wait_for_selector(".lab-svg path")
                page.check(".lab-ycols input[value='acc (%)']")
                page.uncheck(".lab-ycols input[value='loss']")
                page.wait_for_function("document.querySelector('.lab-svg') && document.querySelector('.lab-svg').textContent.includes('acc (%)')")
                self.assertEqual(page.locator(".lab-svg path").count(), 2)
                self.assertIn("acc (%)", page.text_content(".lab-svg"))
                self.assertIn("통계(전체 데이터)", page.inner_text(".lab-chart-area"))
                page.select_option("select[aria-label='그래프 종류']", "bar")
                page.wait_for_selector(".lab-svg rect[fill]")
                self.shot(page, "lab-chart")
                # 결과 가져오기(작업 폴더의 파일, 옮기지 않음)
                page.click(".lab-head button:has-text('결과 가져오기')")
                imp = page.locator(".modal:has(h2:has-text('결과 가져오기'))")
                imp.wait_for()
                imp.locator(".lab-pick-row:has-text('results/server.json') input").check()
                imp.locator("input[aria-label='Run 이름']").fill("서버 결과")
                imp.locator(".modal-foot button:has-text('가져오기')").click()
                page.wait_for_selector(".lab-run .lab-st:has-text('가져옴')")
                self.assertTrue((self.ws / "results" / "server.json").exists())
                # AI에게 묻기: 채팅 첨부 + 규칙
                page.click("#lab-tab-compare")
                page.click(".lab-sec button:has-text('결과 요약')")
                page.wait_for_selector("#attach-tray:not([hidden]) > *")
                self.assertFalse(page.is_visible("#tool-view"))
                question = page.input_value("#input")
                self.assertIn("지어내지", question)
                self.assertIn("Run ID", question)
                self.shot(page, "lab-ask")
                # 기록 지우기: 파일은 남는다
                page.evaluate("document.querySelector('#btn-expand').hidden || document.querySelector('#btn-expand').click()")  # 1.19: 도구 화면은 사이드바를 접지 않는다
                page.click("#btn-lab")
                page.wait_for_selector(".lab-head")
                page.click(".lab-head button:has-text('지우기')")
                page.click(".modal-foot button:has-text('기록 지우기')")
                page.wait_for_selector(".po-intro:has-text('POSCHAT Lab')")
                self.assertTrue((self.ws / "out" / "history.csv").exists())
                self.assertTrue((self.ws / "train.py").exists())
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                browser.close()

    def test_phone_width(self):
        import lab_store
        from playwright.sync_api import sync_playwright

        exp = lab_store.create_experiment("휴대폰 실험")
        lab_store.create_run(exp["id"], status="completed", params={"a": 1}, metrics={"m": {"value": 1.5, "unit": "s"}})
        with sync_playwright() as p:
            browser, page, errors = self.open(p, 390, 800)
            try:
                page.click("#btn-expand")
                page.click("#btn-lab")
                page.wait_for_selector(".lab-title h1")
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
                self.shot(page, "lab-phone")
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                browser.close()
                lab_store.delete_experiment(exp["id"])


if __name__ == "__main__":
    unittest.main()
