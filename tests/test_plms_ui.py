# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""PLMS 화면: 로그인 진입·수업·공지 탐색·에이전트 질문·연결 해제. 학교 계정은 사용하지 않는다."""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ui_smoke as smoke
from test_browser import FakeBackend
import browser
import plms
import storage


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright 없음")
class PlmsUiTests(unittest.TestCase):
    setUpClass = classmethod(smoke.UiSmokeTests.setUpClass.__func__)
    tearDownClass = classmethod(smoke.UiSmokeTests.tearDownClass.__func__)
    open = smoke.UiSmokeTests.open
    shot = smoke.UiSmokeTests.shot

    def test_duplicate_courses_and_pdf_viewer(self):
        import base64
        import io
        from pypdf import PdfWriter
        from playwright.sync_api import sync_playwright

        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        stream = io.BytesIO()
        writer.write(stream)
        course = {"id": "7", "title": "물리학", "status": "current", "term": ""}
        item = {"title": "강의 PDF", "url": plms.ORIGIN + "/mod/resource/view.php?id=10", "kind": "file", "section": ""}
        def read(action, **kwargs):
            if action == "courses":
                return [course, {**course, "id": "007"}]
            if action == "course":
                return {**course, "items": [item], "text": ""}
            if action == "preview":
                return {"kind": "pdf", "data": base64.b64encode(stream.getvalue()).decode("ascii")}
            return {"title": "강의 PDF", "text": "추출한 글", "file_type": "pdf", "items": [], "next_offset": None}
        with patch.object(self.bridge, "_plms_read", side_effect=read), sync_playwright() as p:
            bw, page, errors = self.open(p)
            try:
                page.evaluate("plmsPanel()")
                page.get_by_role("button", name="내 수업 불러오기", exact=True).click()
                page.wait_for_selector("#plms-content h3:has-text('이번 학기 수업 1개')")
                page.get_by_role("button", name="물리학", exact=True).click()
                page.get_by_role("button", name="강의 PDF", exact=False).click()
                page.wait_for_selector(".plms-preview canvas")
                page.wait_for_selector(".plms-preview:has-text('1 / 2쪽')")
                page.get_by_role("button", name="다음 쪽", exact=True).click()
                page.wait_for_selector(".plms-preview:has-text('2 / 2쪽')")
                self.assertEqual(errors, [])
            finally:
                bw.close()

    def test_login_courses_notice_agent_and_disconnect(self):
        from playwright.sync_api import sync_playwright

        backends = []
        def factory(b):
            backend = FakeBackend(b)
            backend.plms_cookies = lambda origin, clear=False: []
            backends.append(backend)
            return backend
        self.bridge._browser_obj = browser.Browser(factory)
        course = {"id": "7", "title": "물리학", "url": plms.ORIGIN + "/course/view.php?id=7", "status": "current", "term": "2026년 2학기"}
        old = {"id": "5", "title": "지난 학기 화학", "url": plms.ORIGIN + "/course/view.php?id=5", "status": "past", "term": "2025년 2학기"}
        forum = {"title": "공지사항", "url": plms.ORIGIN + "/mod/forum/view.php?id=9", "kind": "notice", "section": ""}
        lecture = {"title": "강의 PDF", "url": plms.ORIGIN + "/mod/resource/view.php?id=10", "kind": "file", "section": "1주차 · 개요"}
        post = {"title": "중간고사", "url": plms.ORIGIN + "/mod/forum/discuss.php?d=11", "kind": "other", "section": ""}
        def read(action, **kwargs):
            if action == "courses":
                return [course, old]
            if action == "course":
                return {**course, "text": "이번 주 수업", "items": [forum, lecture]}
            if kwargs["url"] == forum["url"]:
                return {**forum, "text": "공지 목록", "items": [post], "next_offset": None}
            self.assertEqual(kwargs["parent"], [forum["url"]])
            return {**post, "text": "금요일 시험 <script>alert('bad')</script>", "items": [], "next_offset": None}
        with patch.object(self.bridge, "_plms_read", side_effect=read), sync_playwright() as p:
            bw, page, errors = self.open(p)
            try:
                page.click("#btn-plms")
                page.get_by_role("button", name="SSO 로그인", exact=True).click()
                page.wait_for_function("document.querySelector('#browser-address').value.includes('plms.postech.ac.kr')")
                self.assertTrue(self.bridge._config["plms_enabled"])
                page.click("#btn-plms")
                page.get_by_role("button", name="내 수업 불러오기", exact=True).click()
                # 이번 학기 수업이 앞에, 지난 학기 수업은 접힌 묶음에
                page.wait_for_selector("#plms-content h3:has-text('이번 학기 수업 1개')")
                self.assertNotIn("null", page.inner_text("#plms-content"))
                self.shot(page, "plms-courses")
                self.assertFalse(page.locator("#plms-content details:has-text('지난 학기 수업') ").first.evaluate("e => e.open"))
                self.assertEqual(page.locator("#plms-content > .plms-cards .plms-card").count(), 1)
                page.get_by_role("button", name="물리학", exact=True).click()
                # 수업 화면: 종류 칩·주차별 묶음. 칩으로 거르면 해당 종류만 보인다
                page.wait_for_selector(".plms-group summary:has-text('1주차 · 개요')")
                self.assertNotIn("null", page.inner_text("#plms-content"))
                self.shot(page, "plms-course")
                page.get_by_role("button", name="자료 1", exact=True).click()
                self.assertEqual(page.locator(".plms-row").count(), 1)
                page.get_by_role("button", name="전체 2", exact=True).click()
                page.get_by_role("button", name="공지사항", exact=True).click()
                page.get_by_role("button", name="중간고사", exact=True).click()
                page.wait_for_selector(".plms-text:has-text('금요일 시험')")
                self.assertEqual(page.locator("#plms-content script").count(), 0)
                # 돌아가기: 게시글 → 공지 목록 → 수업 화면
                page.get_by_role("button", name="← 돌아가기", exact=True).click()
                page.wait_for_selector(".plms-text:has-text('공지 목록')")
                page.get_by_role("button", name="중간고사", exact=True).click()
                page.wait_for_selector(".plms-text:has-text('금요일 시험')")
                page.get_by_role("button", name="에이전트에게 이 자료 묻기", exact=True).click()
                self.assertEqual(page.locator("#plms-content").count(), 0)
                self.assertIn("course_id=7", page.input_value("#input"))
                self.assertIn(forum["url"], page.input_value("#input"))
                self.assertTrue(page.is_checked("#agent-toggle"))
                page.click("#btn-plms")
                page.get_by_role("button", name="연결 해제", exact=True).click()
                page.wait_for_selector("#plms-content:has-text('쿠키를 지웠습니다')")
                self.assertFalse(self.bridge._config["plms_enabled"])
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                bw.close()
                self.bridge._browser_obj = None

    def test_settings_saves_plms_account_without_exposing_password(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            bw, page, errors = self.open(p)
            try:
                page.click("#btn-settings")
                page.wait_for_selector("input[placeholder='POSTECH 아이디 (선택)']")
                page.fill("input[placeholder='POSTECH 아이디 (선택)']", "student1")
                page.fill("input[placeholder='비밀번호 (선택)']", "s3cret-pw")
                page.get_by_role("button", name="저장", exact=True).click()
                page.wait_for_selector("#toast:has-text('설정을 저장했습니다')")
                self.assertEqual(plms.credentials(), ("student1", "s3cret-pw"))
                state = json.dumps(self.bridge.get_state(), ensure_ascii=False)
                self.assertIn("student1", state)
                self.assertNotIn("s3cret-pw", state)
                self.assertNotIn("s3cret-pw", (storage.CONFIG_PATH.read_text(encoding="utf-8") if storage.CONFIG_PATH.exists() else ""))
                # 아이디만 그대로 두고 저장하면 비밀번호는 유지된다. 지우기 체크 시 삭제
                self.assertEqual(self.bridge.save_settings({"plms_username": "student1"}).get("ok", True), True)
                self.assertEqual(plms.credentials(), ("student1", "s3cret-pw"))
                self.assertEqual(self.bridge.save_settings({"clear_plms": True}).get("ok", True), True)
                self.assertIsNone(plms.credentials())
                self.assertEqual([e for e in errors if "favicon" not in e], [])
            finally:
                bw.close()

    def test_saved_account_logs_in_without_opening_the_browser(self):
        from playwright.sync_api import sync_playwright

        def factory(b):
            backend = FakeBackend(b)
            backend.plms_cookies = lambda origin, clear=False: []
            return backend
        self.bridge._browser_obj = browser.Browser(factory)
        plms.save_credentials("student1", "pw-for-test")
        course = {"id": "7", "title": "물리학", "url": plms.ORIGIN + "/course/view.php?id=7", "status": "current", "term": "2026년 2학기"}
        logins = []
        def background(browser_obj, cancelled, **kwargs):
            logins.append(1)
            return "ok", "PLMS에 로그인했습니다."
        try:
            with patch.object(plms, "background_login", side_effect=background), \
                    patch.object(plms, "session_alive", return_value=False), \
                    patch.object(self.bridge, "_plms_read", return_value=[course]), sync_playwright() as p:
                bw, page, errors = self.open(p)
                try:
                    page.evaluate("S.config.plms_username = 'student1'")
                    page.click("#btn-plms")
                    page.get_by_role("button", name="로그인", exact=True).click()
                    page.wait_for_selector("#plms-content h3:has-text('이번 학기 수업 1개')")
                    self.assertEqual(logins, [1])
                    self.assertFalse(page.evaluate("BR.open"))  # 브라우저를 열지 않았다
                    self.assertEqual([e for e in errors if "favicon" not in e], [])
                finally:
                    bw.close()
        finally:
            plms.clear_credentials()
            self.bridge._browser_obj = None
