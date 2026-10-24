# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import updates

DATA = b"new installer bytes"


def release(version="1.11.0", digest=None, size=None, url=None, names=("POSCHAT-Setup.exe",)):
    assets = [{
        "name": name,
        "size": len(DATA) if size is None else size,
        "browser_download_url": url or f"{updates.DOWNLOAD_PREFIX}v{version}/{name}",
        "digest": digest if digest is not None else "sha256:" + hashlib.sha256(DATA).hexdigest(),
    } for name in names]
    return {"tag_name": f"v{version}", "name": f"POSCHAT v{version}", "body": "notes",
            "html_url": "https://github.com/bj0322/POSCHAT/releases/tag/v" + version, "assets": assets}


def response(status=200, json_data=None, chunks=None):
    r = Mock(status_code=status)
    r.json.return_value = json_data
    r.iter_content.return_value = chunks or [DATA[:5], DATA[5:]]
    r.__enter__ = lambda self: self
    r.__exit__ = Mock(return_value=False)
    return r


class UpdateTests(unittest.TestCase):
    @patch("updates.requests.get")
    def test_check_compares_versions_numerically(self, get):
        get.return_value = response(json_data=release("1.11.0"))
        result = updates.check("1.10.0", "windows")
        self.assertTrue(result["available"])
        self.assertEqual((result["version"], result["asset"]), ("1.11.0", "POSCHAT-Setup.exe"))
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])  # 공개 저장소: 토큰 없이 확인
        self.assertFalse(updates.check("1.11.0", "windows")["available"])
        self.assertIsNone(updates.check("1.9.1", "macos")["asset"])  # 이 릴리스에 맥 파일이 없다

    @patch("updates.requests.get")
    def test_new_file_names_first_and_old_names_for_older_releases(self, get):
        # 1.11 릴리스는 새 이름과 예전 이름(1.9.1~1.10.0 앱의 자동 업데이트용)을 함께 올린다
        get.return_value = response(json_data=release("1.11.0", names=("PostechChat-Setup.exe", "POSCHAT-Setup.exe")))
        self.assertEqual(updates.check("1.10.0", "windows")["asset"], "POSCHAT-Setup.exe")
        # 새 이름이 없는 릴리스는 예전 이름으로 받는다
        get.return_value = response(json_data=release("1.11.0", names=("PostechChat.apk",)))
        self.assertEqual(updates.check("1.10.0", "android")["asset"], "PostechChat.apk")

    @patch("updates.requests.get")
    def test_private_repository_is_reported_without_crashing(self, get):
        get.return_value = response(status=404)
        with self.assertRaisesRegex(updates.UpdateError, "공개"):
            updates.check("1.9.1", "windows")

    @patch("updates.requests.get")
    def test_download_checks_size_and_sha256(self, get):
        with tempfile.TemporaryDirectory() as temp:
            get.side_effect = [response(json_data=release()), response()]
            path, version = updates.download("1.9.1", temp, "windows")
            self.assertEqual((path.read_bytes(), version), (DATA, "1.11.0"))
            self.assertEqual(path.name, "POSCHAT-Setup.exe")

            get.side_effect = [response(json_data=release(digest="sha256:" + "0" * 64)), response()]
            with self.assertRaisesRegex(updates.UpdateError, "SHA-256"):
                updates.download("1.9.1", Path(temp) / "bad", "windows")
            self.assertFalse((Path(temp) / "bad" / "POSCHAT-Setup.exe").exists())
            self.assertFalse((Path(temp) / "bad" / "POSCHAT-Setup.exe.part").exists())

            get.side_effect = [response(json_data=release(size=len(DATA) + 10)), response()]
            with self.assertRaisesRegex(updates.UpdateError, "끝까지"):
                updates.download("1.9.1", Path(temp) / "short", "windows")

    @patch("updates.requests.get")
    def test_download_refuses_files_outside_this_repository(self, get):
        get.return_value = response(json_data=release(url="https://example.com/POSCHAT-Setup.exe"))
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(updates.UpdateError, "Releases"):
            updates.download("1.9.1", temp, "windows")

    @patch("updates.requests.get")
    def test_no_download_when_already_latest(self, get):
        get.return_value = response(json_data=release("1.9.1"))
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(updates.UpdateError, "최신"):
            updates.download("1.9.1", temp, "windows")


if __name__ == "__main__":
    unittest.main()
