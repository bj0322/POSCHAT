# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""첨부 열기: 이미지·문서만 운영체제 앱으로 열고, 텍스트로 받은 파일(.bat·.js 등)은 실행되지 않게 내용만 돌려준다."""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import storage  # noqa: E402


class OpenAttachmentTests(unittest.TestCase):
    def setUp(self):
        import main
        from support import isolated_app_dir

        self.main = main
        self.iso = isolated_app_dir()
        self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)

    def _put(self, name, data):
        attach_id = "a" * 32 if name.endswith(".bat") else "b" * 32
        d = storage.attachment_dir(attach_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(data)
        return attach_id

    def test_script_is_shown_not_executed(self):
        attach_id = self._put("setup.bat", b"@echo off\r\ndel /q C:\\x\r\n")
        with patch.object(self.main, "open_path") as opened:
            r = self.main.Bridge.open_attachment(None, attach_id)
        opened.assert_not_called()
        self.assertEqual(r["name"], "setup.bat")
        self.assertIn("del /q", r["text"])
        self.assertFalse(r["truncated"])

    def test_documents_and_images_open_in_their_app(self):
        attach_id = self._put("paper.pdf", b"%PDF-1.4\n")
        with patch.object(self.main, "open_path") as opened:
            r = self.main.Bridge.open_attachment(None, attach_id)
        opened.assert_called_once()
        self.assertIsNone(r)

    def test_macro_workbook_is_not_opened(self):
        attach_id = self._put("book.xlsm", b"not really a workbook")
        with patch.object(self.main, "open_path") as opened:
            r = self.main.Bridge.open_attachment(None, attach_id)
        opened.assert_not_called()
        self.assertIn("매크로", r["text"])

    def test_missing_attachment(self):
        with patch.object(self.main, "open_path") as opened:
            self.assertIsNone(self.main.Bridge.open_attachment(None, "c" * 32))
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
