# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import updates

DATA = b"new installer bytes"
KEY = Ed25519PrivateKey.generate()
PUBLIC = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
OTHER_KEY = Ed25519PrivateKey.generate()


def sign(tag="v1.11.0", name="POSCHAT-Setup.exe", data=DATA, key=KEY):
    message = updates.signed_message(tag, name, len(data), hashlib.sha256(data).hexdigest())
    return base64.b64encode(key.sign(message)).decode() + "\n"


def release(version="1.11.0", digest=None, size=None, url=None, names=("POSCHAT-Setup.exe",), signatures=True):
    def asset(name, size, digest=None):
        return {"name": name, "size": size, "browser_download_url": f"{updates.DOWNLOAD_PREFIX}v{version}/{name}",
                **({"digest": digest} if digest else {})}

    assets = []
    for name in names:
        item = asset(name, len(DATA) if size is None else size,
                     digest if digest is not None else "sha256:" + hashlib.sha256(DATA).hexdigest())
        if url:
            item["browser_download_url"] = url
        if digest == "":
            item.pop("digest", None)
        assets.append(item)
        if signatures:
            assets.append(asset(name + ".sig", 90))
    return {"tag_name": f"v{version}", "name": f"POSCHAT v{version}", "body": "notes",
            "html_url": updates.RELEASES_PAGE, "draft": False, "prerelease": False, "assets": assets}


def response(status=200, json_data=None, chunks=None, text=""):
    r = Mock(status_code=status, text=text)
    r.json.return_value = json_data
    r.iter_content.return_value = chunks or [DATA[:5], DATA[5:]]
    r.__enter__ = lambda self: self
    r.__exit__ = Mock(return_value=False)
    return r


def serve(feed, signature=None, body=None):
    """latest_release → 서명 → 파일 순서로 받는 요청에 답한다."""
    return [response(json_data=feed), response(text=sign() if signature is None else signature),
            body or response()]


@patch.object(updates, "UPDATE_PUBLIC_KEYS", (PUBLIC,))
class UpdateTests(unittest.TestCase):
    @patch("updates.requests.get")
    def test_check_reports_newer_release_and_this_platforms_asset(self, get):
        get.return_value = response(json_data=release())
        result = updates.check("1.10.0", "windows")
        self.assertEqual((result["available"], result["version"], result["asset"]), (True, "1.11.0", "POSCHAT-Setup.exe"))
        self.assertEqual(result["url"], updates.RELEASES_PAGE)
        self.assertFalse(updates.check("1.11.0", "windows")["available"])
        self.assertIsNone(updates.check("1.9.1", "macos")["asset"])  # 이 릴리스에 맥 파일이 없다

    @patch("updates.requests.get")
    def test_asset_without_signature_file_is_not_offered(self, get):
        get.return_value = response(json_data=release(signatures=False))
        self.assertIsNone(updates.check("1.10.0", "windows")["asset"])

    @patch("updates.requests.get")
    def test_server_requests_do_not_follow_redirects(self, get):
        get.return_value = response(status=302)
        with self.assertRaisesRegex(updates.UpdateError, "HTTP 302"):
            updates.check("1.9.1", "windows")
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)

    @patch("updates.requests.get")
    def test_missing_release_is_reported_without_crashing(self, get):
        get.return_value = response(status=404)
        with self.assertRaisesRegex(updates.UpdateError, "아직 없습니다"):
            updates.check("1.9.1", "windows")

    @patch("updates.requests.get")
    def test_unreachable_server_is_reported(self, get):
        get.side_effect = requests.ConnectionError("down")
        with self.assertRaisesRegex(updates.UpdateError, "연결하지 못했습니다"):
            updates.check("1.9.1", "windows")

    @patch("updates.requests.get")
    def test_download_checks_size_sha256_and_signature(self, get):
        with tempfile.TemporaryDirectory() as temp:
            get.side_effect = serve(release())
            path, version = updates.download("1.9.1", temp, "windows")
            self.assertEqual((path.read_bytes(), version), (DATA, "1.11.0"))
            self.assertEqual(path.name, "POSCHAT-Setup.exe")
            self.assertFalse((path.parent / "POSCHAT-Setup.exe.part").exists())

    def assert_refused(self, get, pattern, directory="x"):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / directory
            with self.assertRaisesRegex(updates.UpdateError, pattern):
                updates.download("1.9.1", target, "windows")
            self.assertFalse((target / "POSCHAT-Setup.exe").exists())
            self.assertFalse((target / "POSCHAT-Setup.exe.part").exists())

    @patch("updates.requests.get")
    def test_download_refuses_hash_mismatch(self, get):
        get.side_effect = serve(release(digest="sha256:" + "0" * 64))
        self.assert_refused(get, "SHA-256")

    @patch("updates.requests.get")
    def test_download_refuses_short_file(self, get):
        get.side_effect = serve(release(size=len(DATA) + 10))
        self.assert_refused(get, "끝까지")

    @patch("updates.requests.get")
    def test_download_refuses_missing_digest(self, get):
        get.side_effect = serve(release(digest=""))
        self.assert_refused(get, "SHA-256 정보가 없습니다")

    @patch("updates.requests.get")
    def test_download_refuses_signature_from_another_key(self, get):
        get.side_effect = serve(release(), signature=sign(key=OTHER_KEY))
        self.assert_refused(get, "서명이 맞지 않습니다")

    @patch("updates.requests.get")
    def test_download_refuses_signature_of_another_version_or_file(self, get):
        get.side_effect = serve(release(), signature=sign(tag="v1.10.9"))
        self.assert_refused(get, "서명이 맞지 않습니다")
        get.side_effect = serve(release(), signature=sign(name="POSCHAT.apk"))
        self.assert_refused(get, "서명이 맞지 않습니다", "y")

    @patch("updates.requests.get")
    def test_download_refuses_tampered_file_even_if_feed_digest_was_changed_too(self, get):
        tampered = b"evil installer bytes"
        get.side_effect = serve(release(digest="sha256:" + hashlib.sha256(tampered).hexdigest(), size=len(tampered)),
                                body=response(chunks=[tampered]))
        self.assert_refused(get, "서명이 맞지 않습니다")

    @patch("updates.requests.get")
    def test_download_refuses_garbage_or_missing_signature(self, get):
        get.side_effect = serve(release(), signature="not base64!!")
        self.assert_refused(get, "형식")
        get.side_effect = [response(json_data=release()), response(status=404)]
        self.assert_refused(get, "서명을 내려받지 못했습니다", "y")
        get.side_effect = serve(release(signatures=False))
        self.assert_refused(get, "서명이 없습니다", "z")

    @patch("updates.requests.get")
    def test_download_refuses_without_any_public_key(self, get):
        get.side_effect = serve(release())
        with patch.object(updates, "UPDATE_PUBLIC_KEYS", ("",)):
            self.assert_refused(get, "서명이 맞지 않습니다")

    @patch("updates.requests.get")
    def test_second_public_key_allows_key_rotation(self, get):
        get.side_effect = serve(release(), signature=sign(key=OTHER_KEY))
        other = base64.b64encode(OTHER_KEY.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        with tempfile.TemporaryDirectory() as temp, patch.object(updates, "UPDATE_PUBLIC_KEYS", (PUBLIC, other)):
            self.assertEqual(updates.download("1.9.1", temp, "windows")[0].read_bytes(), DATA)

    @patch("updates.requests.get")
    def test_download_refuses_files_outside_this_server(self, get):
        get.return_value = response(json_data=release(url="https://example.com/POSCHAT-Setup.exe"))
        self.assert_refused(get, "업데이트 서버의 릴리스가 아닙니다")

    @patch("updates.requests.get")
    def test_download_refuses_another_versions_folder(self, get):
        get.return_value = response(json_data=release(url=f"{updates.DOWNLOAD_PREFIX}v9.9.9/POSCHAT-Setup.exe"))
        self.assert_refused(get, "업데이트 서버의 릴리스가 아닙니다")

    @patch("updates.requests.get")
    def test_no_download_when_already_latest(self, get):
        get.return_value = response(json_data=release("1.9.1"))
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(updates.UpdateError, "최신"):
            updates.download("1.9.1", temp, "windows")


class ShippedKeyTests(unittest.TestCase):
    def test_app_ships_a_valid_public_key(self):
        self.assertTrue(updates.UPDATE_PUBLIC_KEYS)
        for key in updates.UPDATE_PUBLIC_KEYS:
            self.assertEqual(len(base64.b64decode(key, validate=True)), 32)

    def test_update_server_address_is_consistent(self):
        self.assertTrue(updates.DOWNLOAD_PREFIX.startswith(updates.UPDATE_BASE_URL))
        self.assertTrue(updates.RELEASE_URL.startswith(updates.UPDATE_BASE_URL))


if __name__ == "__main__":
    unittest.main()
