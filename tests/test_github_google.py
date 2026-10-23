import base64
import email
import email.policy
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # support.py

import connectors
import github_mcp
import google_mcp
import office_mcp
import oauth
import secret_store
import storage
from office_mcp import ToolFailure
from support import FakeHttp, FakeResponse, isolated_app_dir


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self._dir.__enter__()
        secret_store.set(connectors.secret_name("github", "token"), "github_pat_test")

    def tearDown(self):
        self._dir.__exit__(None, None, None)

    def run_with(self, routes, fn, *args, **kwargs):
        fake = FakeHttp(routes)
        with patch.object(github_mcp, "http", fake), patch.object(github_mcp.time, "sleep"):
            return fn(*args, **kwargs), fake

    def test_repo_argument_accepts_urls_and_rejects_paths(self):
        self.assertEqual(github_mcp._repo("https://github.com/bj0322/POSCHAT/pull/3"), "bj0322/POSCHAT")
        self.assertEqual(github_mcp._repo("bj0322/POSCHAT.git"), "bj0322/POSCHAT")
        with self.assertRaises(ToolFailure):
            github_mcp._repo("../../etc/passwd")

    def test_get_file_decodes_base64_and_sends_the_token(self):
        content = base64.b64encode("print('안녕')\n".encode()).decode()
        text, fake = self.run_with([("GET", "/repos/a/b/contents/src/app.py",
                                     FakeResponse(data={"type": "file", "path": "src/app.py", "encoding": "base64",
                                                        "content": content}))],
                                   github_mcp.get_file, "a/b", "src/app.py", ref="main")
        self.assertIn("print('안녕')", text)
        self.assertEqual(fake.calls[0]["headers"]["Authorization"], "Bearer github_pat_test")
        self.assertEqual(fake.calls[0]["params"], {"ref": "main"})

    def test_errors_carry_auth_and_scope_tags(self):
        with self.assertRaisesRegex(ToolFailure, r"\[인증 필요\]"):
            self.run_with([("GET", "/user", FakeResponse(401, {"message": "Bad credentials"}))], github_mcp.whoami)
        with self.assertRaisesRegex(ToolFailure, r"\[권한 부족\]"):
            self.run_with([("POST", "/issues", FakeResponse(403, {"message": "Resource not accessible"}))],
                          github_mcp.create_issue, "a/b", "제목")
        with self.assertRaisesRegex(ToolFailure, "한도"):
            self.run_with([("GET", "/user", FakeResponse(403, {"message": "rate"}, headers={"X-RateLimit-Remaining": "0"}))],
                          github_mcp.whoami)

    def test_missing_token_is_needs_auth(self):
        secret_store.delete(connectors.secret_name("github", "token"))
        with self.assertRaisesRegex(ToolFailure, r"\[인증 필요\]"):
            github_mcp._token()

    def test_server_errors_are_retried_for_reads(self):
        responses = iter([FakeResponse(502), FakeResponse(data={"login": "kim", "name": "Kim"}),
                          FakeResponse(data={"resources": {"core": {"remaining": 10, "limit": 5000}}})])
        text, fake = self.run_with([("GET", "api.github.com", lambda call: next(responses))], github_mcp.whoami)
        self.assertIn("kim", text)
        self.assertEqual(len(fake.calls), 3)

    def test_pull_diff_can_show_one_file(self):
        diff = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
                "diff --git a/y.py b/y.py\n--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-c\n+d\n")
        text, fake = self.run_with([("GET", "/pulls/7", FakeResponse(text=diff))],
                                   github_mcp.get_pull_diff, "a/b", 7, file="y.py")
        self.assertIn("+d", text)
        self.assertNotIn("+b", text)
        self.assertEqual(fake.calls[0]["headers"]["Accept"], "application/vnd.github.diff")

    def test_review_validation_and_payload(self):
        with self.assertRaises(ToolFailure):
            github_mcp.create_pull_review("a/b", 1, event="MERGE")
        with self.assertRaises(ToolFailure):
            github_mcp.create_pull_review("a/b", 1, comments=[{"path": "x.py"}])
        text, fake = self.run_with([("POST", "/pulls/1/reviews", FakeResponse(200, {"html_url": "u"}))],
                                   github_mcp.create_pull_review, "a/b", 1, body="좋아요",
                                   comments=[{"path": "x.py", "line": 3, "body": "여기"}])
        self.assertEqual(fake.calls[0]["json"]["comments"][0], {"path": "x.py", "line": 3, "side": "RIGHT", "body": "여기"})
        self.assertEqual(fake.calls[0]["json"]["event"], "COMMENT")

    def test_job_log_analysis_finds_the_failure_with_context(self):
        log = "\n".join([
            "2026-10-23T01:00:00.0000000Z ##[group]Run python -m unittest",
            "2026-10-23T01:00:01.0000000Z test_a ... ok",
            "2026-10-23T01:00:02.0000000Z Traceback (most recent call last):",
            "2026-10-23T01:00:02.1000000Z   File \"x.py\", line 3",
            "2026-10-23T01:00:02.2000000Z AssertionError: 1 != 2",
            "2026-10-23T01:00:03.0000000Z ##[error]Process completed with exit code 1.",
        ])
        found = github_mcp.analyze_log(log)
        self.assertTrue(found)
        self.assertIn("Run python -m unittest", found[0])
        self.assertIn("AssertionError: 1 != 2", "\n".join(found))
        self.assertNotIn("2026-10-23T", "\n".join(found))

    def test_issue_list_skips_pull_requests(self):
        items = [{"number": 1, "title": "버그", "state": "open", "user": {"login": "a"}, "labels": [], "comments": 0,
                  "created_at": "2026-10-01"},
                 {"number": 2, "title": "PR", "state": "open", "pull_request": {}, "user": {"login": "b"}}]
        text, _ = self.run_with([("GET", "/repos/a/b/issues", FakeResponse(data=items))], github_mcp.list_issues, "a/b")
        self.assertIn("#1", text)
        self.assertNotIn("#2", text)

    def test_enterprise_url_must_be_https(self):
        storage.save_config({"connectors": {"github": {"options": {"api_url": "http://ghe.local"}}}})
        with self.assertRaises(ToolFailure):
            github_mcp._base()


class GoogleTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()
        self.changes = patch.object(google_mcp, "CHANGES_STATE", self.root / "connectors" / "gdrive_changes.json")
        self.changes.start()
        for cid in ("gdrive", "gdocs", "gsheets", "gmail", "gcalendar", "gslides"):
            oauth.save(cid, {"access_token": f"ya29.{cid}", "expires_at": 0, "scope": []})

    def tearDown(self):
        self.changes.stop()
        self._dir.__exit__(None, None, None)

    def run_with(self, routes, fn, *args, **kwargs):
        fake = FakeHttp(routes)
        with patch.object(google_mcp, "http", fake), patch.object(google_mcp.time, "sleep"):
            return fn(*args, **kwargs), fake

    def test_ids_from_urls(self):
        self.assertEqual(google_mcp._id("https://docs.google.com/document/d/1AbCdEfGhIjKlMn/edit"), "1AbCdEfGhIjKlMn")
        self.assertEqual(google_mcp._id("https://drive.google.com/drive/folders/0BxYz123456789"), "0BxYz123456789")
        with self.assertRaises(ToolFailure):
            google_mcp._id("a b")

    def test_drive_reads_google_docs_by_exporting_text(self):
        text, fake = self.run_with([
            ("GET", "/files/doc123456789/export", FakeResponse(content="회의록 본문".encode())),
            ("GET", "/files/doc123456789", FakeResponse(data={"id": "doc123456789", "name": "회의록",
                                                              "mimeType": google_mcp.MIME["doc"]})),
        ], google_mcp.drive_read_file, "doc123456789")
        self.assertIn("회의록 본문", text)
        self.assertEqual(fake.calls[1]["params"], {"mimeType": "text/plain"})
        self.assertEqual(fake.calls[0]["headers"]["Authorization"], "Bearer ya29.gdrive")

    def test_drive_search_escapes_quotes(self):
        _, fake = self.run_with([("GET", "/drive/v3/files", FakeResponse(data={"files": []}))],
                                google_mcp.drive_search_files, "O'Reilly", mime_type="pdf")
        q = fake.calls[0]["params"]["q"]
        self.assertIn("name contains 'O\\'Reilly'", q)
        self.assertIn("mimeType = 'application/pdf'", q)

    def test_drive_changes_keep_a_page_token(self):
        text, _ = self.run_with([("GET", "/changes/startPageToken", FakeResponse(data={"startPageToken": "10"}))],
                                google_mcp.drive_list_changes)
        self.assertIn("기준점", text)
        text, fake = self.run_with([("GET", "/drive/v3/changes", FakeResponse(data={
            "newStartPageToken": "12", "changes": [{"fileId": "f1", "time": "2026-10-23T01:00", "file": {"name": "보고서"}}]}))],
            google_mcp.drive_list_changes)
        self.assertIn("보고서", text)
        self.assertEqual(fake.calls[0]["params"]["pageToken"], "10")
        self.assertEqual(json.loads((self.root / "connectors" / "gdrive_changes.json").read_text())["page_token"], "12")

    def test_upload_stays_inside_the_workspace(self):
        ws = self.root / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("hi")
        with patch.object(office_mcp, "ROOT", ws):
            with self.assertRaises(ToolFailure):
                google_mcp.drive_upload_file("../config.json")
            text, fake = self.run_with([("POST", "upload/drive", FakeResponse(data={"id": "f", "name": "a.txt"}))],
                                       google_mcp.drive_upload_file, "a.txt")
        self.assertIn("올렸습니다", text)
        self.assertIn(b"hi", fake.calls[0]["data"])

    def test_readonly_option_blocks_writes(self):
        storage.save_config({"connectors": {"gdocs": {"options": {"readonly": "true"}}}})
        with self.assertRaisesRegex(ToolFailure, "읽기 전용"):
            google_mcp.docs_create_document("제목")

    def test_docs_text_keeps_headings_lists_and_tables(self):
        doc = {"body": {"content": [
            {"paragraph": {"paragraphStyle": {"namedStyleType": "HEADING_1"}, "elements": [{"textRun": {"content": "개요\n"}}]}},
            {"paragraph": {"bullet": {}, "elements": [{"textRun": {"content": "항목\n"}}]}},
            {"table": {"tableRows": [{"tableCells": [
                {"content": [{"paragraph": {"elements": [{"textRun": {"content": "A\n"}}]}}]},
                {"content": [{"paragraph": {"elements": [{"textRun": {"content": "B\n"}}]}}]}]}]}},
        ]}}
        self.assertEqual(google_mcp._doc_text(doc), "# 개요\n- 항목\n| A | B |\n")

    def test_sheets_values_must_be_rows(self):
        with self.assertRaises(ToolFailure):
            google_mcp._values_arg({"a": 1})
        self.assertEqual(google_mcp._values_arg('[["a", 1]]'), [["a", 1]])

    def test_gmail_draft_is_rfc822_and_send_checks_recipients(self):
        _, fake = self.run_with([("POST", "/drafts", FakeResponse(data={"id": "r-51234567"}))],
                                google_mcp.gmail_create_draft, "kim@example.com", "회의", "내일 10시")
        raw = fake.calls[0]["json"]["message"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=email.policy.default)
        self.assertEqual(msg["To"], "kim@example.com")
        self.assertEqual(msg["Subject"], "회의")

        draft = FakeResponse(data={"message": {"payload": {"headers": [
            {"name": "To", "value": "Kim <kim@example.com>"}, {"name": "Subject", "value": "회의"}]}}})
        with self.assertRaisesRegex(ToolFailure, "다릅니다"):
            self.run_with([("GET", "/drafts/r-51234567", draft)], google_mcp.gmail_send_draft, "r-51234567", "attacker@evil.com", "회의")
        text, fake = self.run_with([("GET", "/drafts/r-51234567", draft), ("POST", "/drafts/send", FakeResponse(data={"id": "m1"}))],
                                   google_mcp.gmail_send_draft, "r-51234567", "kim@example.com", "회의")
        self.assertIn("보냈습니다", text)
        self.assertEqual(fake.calls[-1]["json"], {"id": "r-51234567"})

    def test_gmail_html_body_is_turned_into_text(self):
        html = base64.urlsafe_b64encode("<p>안녕&amp;하세요</p><script>x()</script>".encode()).decode()
        self.assertEqual(google_mcp._body_text({"mimeType": "text/html", "body": {"data": html}}), "안녕&하세요")

    def test_calendar_adds_local_timezone_and_does_not_send_invites(self):
        self.assertIn("date", google_mcp._when("2026-10-23", "start"))
        self.assertRegex(google_mcp._when("2026-10-23T14:00", "start")["dateTime"], r"[+-]\d\d:\d\d$")
        text, fake = self.run_with([
            ("POST", "/freeBusy", FakeResponse(data={"calendars": {"primary": {"busy": [
                {"start": "2026-10-23T14:30:00+09:00", "end": "2026-10-23T15:00:00+09:00"}]}}})),
            ("POST", "/events", FakeResponse(data={"id": "e1", "summary": "세미나", "start": {"dateTime": "2026-10-23T14:00"}})),
        ], google_mcp.calendar_create_event, "세미나", "2026-10-23T14:00", "2026-10-23T15:00")
        self.assertIn("겹칩니다", text)
        self.assertEqual(fake.calls[-1]["params"], {"sendUpdates": "none"})

    def test_verify_reports_missing_scopes(self):
        storage.save_config({})
        with self.assertRaisesRegex(ToolFailure, r"\[권한 부족\]"):
            self.run_with([("GET", "tokeninfo", FakeResponse(data={
                "scope": "https://www.googleapis.com/auth/gmail.readonly"}))], google_mcp.verify, "gmail")


if __name__ == "__main__":
    unittest.main()
