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


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright 없음")
class PlmsUiTests(unittest.TestCase):
    setUpClass = classmethod(smoke.UiSmokeTests.setUpClass.__func__)
    tearDownClass = classmethod(smoke.UiSmokeTests.tearDownClass.__func__)
    open = smoke.UiSmokeTests.open

    def test_login_courses_notice_agent_and_disconnect(self):
        from playwright.sync_api import sync_playwright

        backends = []
        def factory(b):
            backend = FakeBackend(b)
            backend.plms_cookies = lambda origin, clear=False: []
            backends.append(backend)
            return backend
        self.bridge._browser_obj = browser.Browser(factory)
        course = {"id": "7", "title": "물리학", "url": plms.ORIGIN + "/course/view.php?id=7"}
        forum = {"title": "공지사항", "url": plms.ORIGIN + "/mod/forum/view.php?id=9"}
        post = {"title": "중간고사", "url": plms.ORIGIN + "/mod/forum/discuss.php?d=11"}
        def read(action, **kwargs):
            if action == "courses":
                return [course]
            if action == "course":
                return {**course, "text": "이번 주 수업", "items": [forum]}
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
                page.get_by_role("button", name="물리학", exact=True).click()
                page.get_by_role("button", name="공지사항", exact=True).click()
                page.get_by_role("button", name="중간고사", exact=True).click()
                page.wait_for_selector(".plms-text:has-text('금요일 시험')")
                self.assertEqual(page.locator("#plms-content script").count(), 0)
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
