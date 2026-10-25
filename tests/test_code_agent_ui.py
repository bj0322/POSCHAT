# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Code 에이전트 화면 시험: Code 화면의 '작업' 탭(1.17.2부터 Claude Code 같은 터미널)에서 작업을 맡기고(가짜 모델),
기록 안의 선택지로 명령을 승인하고, 계획·단계·diff·되돌리기·이어서 지시하기·슬래시 명령·! 명령·# 메모·@ 파일·단축키를 확인한다.
위쪽 안내 글이 아래 패널을 덮지 않는지도 본다(1.15 화면 겹침 회귀).
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
        if callable(step):
            step = step()
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

    def send(self, page, text):
        page.fill("#ca-input", text)
        page.dispatch_event("#ca-input", "input")
        page.wait_for_timeout(60)
        page.press("#ca-input", "Enter")

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
                # 작업 탭이 맨 앞에 있고, 열린 파일이 없으면 작업 탭(터미널)이 보이고 입력 칸에 초점이 있다
                page.wait_for_selector(".code-tab.agent.active")
                page.wait_for_selector(".ca-term .ca-banner .ca-tips")
                self.assertEqual(page.locator(".code-tab.agent .code-tab-close").count(), 0)
                page.wait_for_function("document.activeElement && document.activeElement.id === 'ca-input'")
                self.assertIn("수정 자동", page.inner_text("#ca-mode"))
                self.send(page, "test_calc.py가 통과하도록 calc.py를 고쳐 줘")
                # 명령 실행은 기록 안의 선택지로 묻는다(대화 상자 없음, '이번 실행 동안 허용' 없음)
                confirm = page.locator("#ca-select:has-text('Bash 명령')")
                confirm.wait_for(timeout=20000)
                self.assertIn("test_calc.py", confirm.inner_text())
                self.assertEqual(page.locator(".modal").count(), 0)
                self.assertNotIn("이번 실행 동안", confirm.inner_text())
                self.shot(page, "code-agent-confirm")
                page.press("#ca-input", "1")                       # 1. 예
                page.wait_for_selector(".ca-a:has-text('통과했습니다')", timeout=30000)
                self.assertIn("return a + b", (self.ws / "calc.py").read_text())
                log = page.inner_text("#ca-log")
                self.assertIn("Read(calc.py)", log)
                self.assertIn("Update(calc.py)", log)
                self.assertIn("1줄 더함, 1줄 지움", log)
                self.assertIn("Bash(", log)
                self.assertIn("종료 코드 0", log)
                self.assertIn("Update Todos", log)
                self.assertGreaterEqual(page.locator(".ca-tool.edit .ca-diff .add").count(), 1)
                self.assertEqual(page.locator(".ca-todos").last.locator("li.done").count(), 3)
                self.assertIn("동안 일했습니다", log)
                self.shot(page, "code-agent-done")
                # 출력 펼치기(ctrl+o) → 접힌 read 내용이 보인다
                self.assertNotIn("return a + b", page.inner_text(".ca-tool.read"))
                page.press("#ca-input", "Control+o")
                self.assertIn("return a", page.inner_text(".ca-tool.read"))
                page.press("#ca-input", "Control+o")
                # /diff는 기록에 줄 번호가 붙은 diff를 보인다
                self.send(page, "/diff")
                page.wait_for_selector(".ca-sys .ca-diff .del")
                # /revert → 선택지 → Enter(1. 예)
                self.send(page, "/revert")
                page.wait_for_selector("#ca-select:has-text('되돌릴까요')")
                page.press("#ca-input", "Enter")
                page.wait_for_selector(".ca-sys:has-text('되돌림 1개')")
                self.assertIn("return a - b", (self.ws / "calc.py").read_text())
                # 이어서 지시하기(같은 작업)
                self.script.queue[:] = [{"action": "done", "answer": "되돌린 상태를 확인했습니다."}]
                self.send(page, "지금 상태를 확인해 줘")
                page.wait_for_selector(".ca-a:has-text('되돌린 상태')", timeout=20000)
                self.assertEqual(page.locator(".ca-u").count(), 2)
                # ↑로 지난 입력을 다시 부른다
                page.press("#ca-input", "ArrowUp")
                self.assertEqual(page.input_value("#ca-input"), "지금 상태를 확인해 줘")
                page.press("#ca-input", "ArrowDown")
                self.assertEqual(page.input_value("#ca-input"), "")
                # /clear → 새 작업, /resume으로 다시 고른다
                self.send(page, "/clear")
                page.wait_for_selector(".ca-banner .ca-tips")
                self.assertEqual(page.locator(".ca-u").count(), 0)
                self.send(page, "/resume")
                page.wait_for_selector("#ca-select:has-text('이어서 할 작업')")
                page.press("#ca-input", "1")
                page.wait_for_selector(".ca-a:has-text('되돌린 상태')")
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                browser.close()

    def test_plan_mode_approve_remember_steer_and_undo(self):
        """계획 모드(Shift+Tab) → '이 계획으로 진행' → 명령 '다시 묻지 않기' → 작업 중 추가 지시 → /undo."""
        import time

        from playwright.sync_api import sync_playwright

        self.script.queue[:] = [{"action": "read", "path": "calc.py", "note": "add 함수를 먼저 봅니다"},
                                {"action": "done", "answer": "계획: 1) calc.py의 add를 a + b로 2) test_calc.py로 확인"}]
        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.wait_for_selector(".code-tab.agent.active")
                page.wait_for_selector(".ca-banner")
                page.press("#ca-input", "Shift+Tab")             # 수정 자동 → 계획 모드
                page.wait_for_selector("#ca-mode:has-text('계획 모드')")
                self.assertEqual(self.bridge._ca_approval(), "plan")
                page.press("#ca-input", "Shift+Tab")             # → 전체 자동
                page.wait_for_selector("#ca-mode:has-text('전체 자동')")
                page.fill("#ca-input", "/mode plan")
                page.press("#ca-input", "Enter")
                page.wait_for_selector("#ca-mode:has-text('계획 모드')")
                # / 를 치면 명령 목록이 뜬다
                page.fill("#ca-input", "/")
                page.dispatch_event("#ca-input", "input")
                page.wait_for_selector("#ca-menu:not([hidden]) .ca-mi:has-text('/review')")
                page.fill("#ca-input", "/re")
                page.dispatch_event("#ca-input", "input")
                page.wait_for_selector("#ca-menu .ca-mi.cur:has-text('/review')")
                page.press("#ca-input", "Escape")
                page.wait_for_selector("#ca-menu", state="hidden")
                self.send(page, "/plan calc 고치기")
                page.wait_for_selector(".ca-a.proposal:has-text('계획: 1)')", timeout=20000)
                self.assertIn("add 함수를 먼저 봅니다", page.inner_text("#ca-log"))
                self.assertIn("return a - b", (self.ws / "calc.py").read_text())  # 계획 모드는 고치지 않는다
                page.wait_for_selector("#ca-select.plan:has-text('진행할까요')")
                self.shot(page, "code-agent-plan")
                # 이 계획으로 진행(1. 수정 자동) → 명령은 2. 다시 묻지 않기
                self.script.queue[:] = [
                    {"action": "edit", "path": "calc.py", "old": "return a - b", "new": "return a + b"},
                    {"action": "run", "command": f"{PY} test_calc.py"},
                    {"action": "done", "answer": "고치고 확인했습니다."}]
                page.click("#ca-approve")
                page.wait_for_selector("#ca-select:has-text('Bash 명령') #ca-remember", timeout=20000)
                page.press("#ca-input", "2")
                page.wait_for_selector(".ca-a:has-text('고치고 확인했습니다')", timeout=30000)
                self.assertIn("수정 자동", page.inner_text("#ca-mode"))   # 계획을 승인하면 계획 모드를 벗어난다
                self.assertIn("calc 고치기", page.inner_text("#ca-line"))
                self.assertIn("return a + b", (self.ws / "calc.py").read_text())
                self.assertTrue(self.bridge.code_agent_rules()["rules"])
                self.assertIn("다시 묻지 않습니다", page.inner_text("#ca-log"))
                # 작업 중 추가 지시(Enter): 모델이 다음 단계를 고르기 전에 지시가 들어온다
                waited = {}

                def wait_for_steer():
                    end = time.time() + 15
                    while time.time() < end and not (self.bridge._ca_running or {}).get("steer"):
                        time.sleep(0.05)
                    waited["ok"] = bool((self.bridge._ca_running or {}).get("steer"))
                    return {"action": "read", "path": "calc.py"}
                self.script.queue[:] = [wait_for_steer, {"action": "done", "answer": "추가 지시도 반영했습니다."}]
                self.send(page, "테스트 파일도 한 번 읽어 줘")
                page.wait_for_selector("#ca-spin:has-text('esc로 멈춤')", timeout=10000)
                self.send(page, "주석은 한국어로")
                page.wait_for_selector(".ca-a:has-text('추가 지시도 반영')", timeout=30000)
                self.assertTrue(waited.get("ok"))
                page.wait_for_selector(".ca-u.steer:has-text('주석은 한국어로')")
                self.assertEqual(page.inner_text("#ca-spin"), "")
                # Esc 두 번 → 마지막 수정 지시 되돌리기
                page.press("#ca-input", "Escape")
                page.press("#ca-input", "Escape")
                page.wait_for_selector("#ca-select:has-text('되돌릴까요')")
                page.press("#ca-input", "1")
                page.wait_for_selector(".ca-sys:has-text('지시를 되돌렸습니다')")
                self.assertIn("return a - b", (self.ws / "calc.py").read_text())
                self.shot(page, "code-agent-steer-undo")
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                for r in self.bridge.code_agent_rules().get("rules", []):
                    self.bridge.code_agent_rule_delete(r)
                self.bridge.code_agent_set_approval("auto_edit")
                browser.close()

    def test_cli_input_bash_memory_mentions_and_feedback(self):
        """1.17.2: !명령(바로 실행) · #메모(AGENTS.md) · @파일 자동 완성 · ? 단축키 · /help · /status ·
        매번 묻기의 수정 승인('이 작업 동안 묻지 않기' → 수정 자동) · 거부하고 다르게 하라고 알려 주기."""
        import time

        from playwright.sync_api import sync_playwright

        agents = self.ws / "AGENTS.md"
        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.wait_for_selector(".ca-banner")
                self.send(page, "/clear")
                # ? → 단축키, Esc로 닫기
                page.press("#ca-input", "?")
                page.wait_for_selector("#ca-keys:has-text('Shift+Tab')")
                page.press("#ca-input", "Escape")
                page.wait_for_selector("#ca-keys", state="detached")
                # ! 명령: 입력 상자가 바뀌고, 실행 출력이 기록에 남는다
                page.fill("#ca-input", f"!{PY} -c \"print('hello-shell')\"")
                page.dispatch_event("#ca-input", "input")
                self.assertIn("bash", page.get_attribute("#ca-box", "class"))
                page.press("#ca-input", "Enter")
                page.wait_for_selector(".ca-tool.shell:not(.live):has-text('hello-shell')", timeout=20000)
                page.wait_for_selector(".ca-tool.shell.live", state="detached")
                self.assertIn("종료 코드 0", page.inner_text(".ca-tool.shell"))
                task_id = self.bridge.code_agent_state()["tasks"][0]["id"]
                self.assertTrue(self.bridge.code_agent_task(task_id)["task"]["shell_context"])
                # # 메모: AGENTS.md에 한 줄
                self.send(page, "# 테스트는 test_calc.py로 확인한다")
                page.wait_for_selector(".ca-tool.memory:has-text('AGENTS.md')")
                self.assertIn("- 테스트는 test_calc.py로 확인한다", agents.read_text())
                # @ 파일 자동 완성(Tab)
                page.fill("#ca-input", "이 파일 봐 @cal")
                page.dispatch_event("#ca-input", "input")
                page.wait_for_selector("#ca-menu .ca-mi:has-text('calc.py')")
                page.press("#ca-input", "Tab")
                self.assertEqual(page.input_value("#ca-input"), "이 파일 봐 @calc.py ")
                page.fill("#ca-input", "")
                page.dispatch_event("#ca-input", "input")
                # /help · /status
                self.send(page, "/help")
                page.wait_for_selector(".ca-help:has-text('/resume')")
                self.assertIn("#메모", page.inner_text(".ca-help"))
                self.send(page, "/status")
                page.wait_for_selector(".ca-sys:has-text('POSCHAT Code 상태')")
                self.assertIn("AGENTS.md", page.inner_text(".ca-sys:has-text('POSCHAT Code 상태')"))
                # 매번 묻기: 수정도 기록 안에서 묻는다 → 2. 이 작업 동안 수정은 묻지 않기 → 수정 자동
                self.send(page, "/mode ask")
                page.wait_for_selector("#ca-mode:has-text('매번 묻기')")
                waited = {}

                def wait_for_steer():
                    end = time.time() + 15
                    while time.time() < end and not any(isinstance(x, str) for x in (self.bridge._ca_running or {}).get("steer", [])):
                        time.sleep(0.05)
                    waited["ok"] = True
                    return {"action": "done", "answer": "알려 준 대로 하겠습니다."}
                self.script.queue[:] = [
                    {"action": "edit", "path": "calc.py", "old": "return a - b", "new": "return a + b"},
                    {"action": "run", "command": f"{PY} test_calc.py"},
                    wait_for_steer]
                self.send(page, "@calc.py 고쳐 줘")
                page.wait_for_selector("#ca-select:has-text('이렇게 고칠까요') #ca-always", timeout=20000)
                self.assertGreaterEqual(page.locator("#ca-select .ca-diff .add").count(), 1)
                page.press("#ca-input", "2")
                page.wait_for_selector("#ca-mode:has-text('수정 자동')")
                self.assertEqual(self.bridge._ca_approval(), "auto_edit")
                # 명령은 Esc(= 아니요, 다르게 하라고 알려 주기) → 다르게 할 일을 쓰고 Enter
                page.wait_for_selector("#ca-select:has-text('Bash 명령')", timeout=20000)
                page.press("#ca-input", "Escape")
                page.wait_for_selector("#ca-select:has-text('무엇을 다르게 할지')")
                self.send(page, "명령은 돌리지 말고 끝내 줘")
                page.wait_for_selector(".ca-a:has-text('알려 준 대로')", timeout=30000)
                self.assertTrue(waited.get("ok"))
                log = page.inner_text("#ca-log")
                self.assertIn("사용자가 거부했습니다", log)
                self.assertIn("Attach(calc.py)", log)
                page.wait_for_selector(".ca-u.steer:has-text('명령은 돌리지 말고')")
                self.shot(page, "code-agent-cli")
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                agents.unlink(missing_ok=True)
                self.bridge.code_agent_set_approval("auto_edit")
                (self.ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")
                browser.close()

    def test_worktree_hint(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page, errors = self.open(p)
            try:
                page.wait_for_selector(".code-tab.agent.active")
                text = page.evaluate("""() => {
                  const live = caWorktreeHint({ id: 't', worktree: '/x', branch: 'poschat/task-1', plan: [], changes: {}, turns: [] });
                  const done = caWorktreeHint({ id: 't', worktree: '/x', worktree_removed: true, plan: [], changes: {}, turns: [] });
                  return live.innerText + ' --- ' + String(done); }""")
                self.assertIn("poschat/task-1", text)
                self.assertIn("/apply", text)
                self.assertIn("/discard", text)
                self.assertIn("null", text.split("---")[1])
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
                for sel in (".ca-banner", ".ca-log"):
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
