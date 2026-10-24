# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Code 에이전트(1.16) 화면 시험: Code 화면의 '작업' 탭에서 작업을 맡기고(가짜 모델), 명령을 승인하고,
계획·단계·바뀐 파일·되돌리기·이어서 지시하기를 확인한다. 위쪽 안내 글이 아래 패널을 덮지 않는지도 본다(1.15 화면 겹침 회귀).
Playwright가 없으면 건너뛴다. 스크린숏은 POSTECH_UI_SHOTS 폴더가 주어지면 거기에 남긴다.
"""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
PY = f'"{sys.executable}"'


class Script:
    def __init__(self):
        self.queue = []

    def __call__(self, api_key, prompt, **kwargs):
        step = self.queue.pop(0) if self.queue else {"action": "done", "answer": "끝"}
        return json.dumps(step, ensure_ascii=False)


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright가 없어 화면 점검을 건너뜁니다")
class CodeAgentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import agent
        import ui_harness
        from support import isolated_app_dir, preserved_hooks

        cls.saved_env = {k: os.environ.get(k) for k in ("APPDATA", "POSTECH_CHAT_SECRETS")}
        cls.hooks = preserved_hooks()
        cls.hooks.__enter__()
        cls.isolation = isolated_app_dir()
        data_dir = cls.isolation.__enter__()
        cls.bridge, cls.events = ui_harness.make_bridge(data_dir)
        cls.bridge.save_settings({"api_key": "test-key"})
        cls.ws = Path(data_dir) / "agent ws"
        cls.ws.mkdir()
        (cls.ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        (cls.ws / "test_calc.py").write_text("from calc import add\nassert add(2, 3) == 5\nprint('통과')\n")
        cls.bridge._config["workspace"] = str(cls.ws)
        cls.script = Script()
        cls.patch = patch.object(agent, "ask", cls.script)
        cls.patch.start()
        cls.server = ui_harness.serve(cls.bridge, cls.events)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/"
        cls.init_script = ui_harness.INIT_SCRIPT
        cls.shots = os.environ.get("POSTECH_UI_SHOTS")

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.bridge._ca_shutdown()
        cls.bridge._code_shutdown()
        cls.bridge._events.stop()
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

    def open(self, p, width=1400, height=900):
        browser = p.chromium.launch(**({"executable_path": CHROMIUM} if CHROMIUM else {}))
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.add_init_script(self.init_script)
        page.goto(self.url)
        page.wait_for_selector("#btn-code")
        page.click("#btn-code")
        page.wait_for_selector("#code-pane:not([hidden])")
        return browser, page, errors

    def test_agent_task_flow(self):
        from playwright.sync_api import sync_playwright

        self.script.queue[:] = [
            {"action": "plan", "steps": ["calc.py 읽기", "add 고치기", "테스트로 확인"]},
            {"action": "read", "path": "calc.py"},
            {"action": "edit", "path": "calc.py", "old": "return a - b", "new": "return a + b", "reason": "덧셈 버그"},
            {"action": "plan", "steps": ["calc.py 읽기", "add 고치기", "테스트로 확인"], "done": [0, 1]},
            {"action": "run", "command": f"{PY} test_calc.py"},
            {"action": "plan", "steps": ["calc.py 읽기", "add 고치기", "테스트로 확인"], "done": [0, 1, 2]},
            {"action": "done", "answer": "**calc.py**의 `add`를 고쳤고 `test_calc.py`가 통과했습니다."},
        ]
        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                # 작업 탭이 맨 앞에 있고, 열린 파일이 없으면 작업 탭이 보인다
                page.wait_for_selector(".code-tab.agent.active")
                page.wait_for_selector(".ca-intro")
                self.assertEqual(page.locator(".code-tab.agent .code-tab-close").count(), 0)
                page.fill("#ca-input", "test_calc.py가 통과하도록 calc.py를 고쳐 줘")
                page.keyboard.press("Control+Enter")
                # 명령 실행은 묻는다('이번 실행 동안 허용' 없음)
                confirm = page.locator(".modal:has-text('명령 실행')")
                confirm.wait_for(timeout=20000)
                self.assertIn("test_calc.py", confirm.inner_text())
                self.assertEqual(confirm.locator("button:has-text('이번 실행 동안')").count(), 0)
                confirm.locator("button:has-text('허용')").click()
                page.wait_for_selector(".ca-answer:has-text('통과했습니다')", timeout=30000)
                self.assertIn("return a + b", (self.ws / "calc.py").read_text())
                log = page.inner_text("#ca-log")
                self.assertIn("calc.py", log)
                self.assertIn("종료 코드 0", log)
                self.assertEqual(page.locator(".ca-step.edit .diff .add").count() >= 1, True)
                self.assertEqual(page.locator(".ca-plan li.done").count(), 3)
                self.assertIn("calc.py", page.inner_text(".ca-changes"))
                self.shot(page, "code-agent-done")
                # 차이 보기 → 편집기에서 열기
                page.click(".ca-changes button:has-text('차이')")
                page.wait_for_selector(".modal .diff .del")
                page.click(".modal-foot button:has-text('편집기에서 열기')")
                page.wait_for_selector(".code-tab.active:has-text('calc.py')")
                page.click("#code-tab-agent")
                # 모두 되돌리기
                page.click(".ca-side button:has-text('모두 되돌리기')")
                page.click(".modal-foot button:has-text('되돌리기')")
                page.wait_for_selector("#toast:has-text('되돌림 1개')")
                self.assertIn("return a - b", (self.ws / "calc.py").read_text())
                # 이어서 지시하기(같은 작업)
                self.script.queue[:] = [{"action": "done", "answer": "되돌린 상태를 확인했습니다."}]
                page.fill("#ca-input", "지금 상태를 확인해 줘")
                page.click("#ca-send")
                page.wait_for_selector(".ca-answer:has-text('되돌린 상태')", timeout=20000)
                self.assertEqual(page.locator(".ca-user").count(), 2)
                self.assertEqual(page.locator(".ca-pick option").count(), 2)  # 새 작업 + 이 작업
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                browser.close()

    def test_welcome_text_never_covers_the_bottom_panel(self):
        """1.15에서 좁은 창이면 편집기 자리의 안내 글이 아래 '실행' 패널 위로 넘쳐 겹쳐 보였다."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.open(p, 1000, 560)
            try:
                page.wait_for_selector(".code-tab.agent")
                for sel in (".ca-intro", ".ca-log"):
                    page.wait_for_selector(sel)
                page.click("#code-btab-run")
                # 1.15 화면처럼 안내 글(code-welcome)을 편집기 자리에 띄운다
                page.evaluate("""() => { document.querySelectorAll('.code-tabpane').forEach((t) => { t.hidden = true; });
                  document.querySelector('#code-stack').append(codeWelcome()); }""")
                over = page.evaluate("""() => {
                  const stack = document.querySelector('#code-stack').getBoundingClientRect();
                  const bottom = document.querySelector('#code-bottom').getBoundingClientRect();
                  const hits = [];
                  for (let x = bottom.left + 10; x < bottom.right - 10; x += 40)
                    for (let y = bottom.top + 5; y < bottom.bottom - 5; y += 20) {
                      const el = document.elementFromPoint(x, y);
                      if (el && !el.closest('#code-bottom')) hits.push(el.className || el.tagName);
                    }
                  return { hits: hits.slice(0, 5), stackBottom: stack.bottom, bottomTop: bottom.top };
                }""")
                self.assertEqual(over["hits"], [], over)
                self.assertLessEqual(over["stackBottom"], over["bottomTop"] + 1)
                # 작업 탭 안에서 기록이 넘치면 그 안에서 스크롤한다
                clipped = page.evaluate("""() => { const s = document.querySelector('#code-stack');
                  return getComputedStyle(s).overflow; }""")
                self.assertEqual(clipped, "hidden")
                self.shot(page, "code-agent-small-window")
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
