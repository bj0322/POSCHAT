import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import updates


class UpdateTests(unittest.TestCase):
    def manifest(self, version="1.9.0", data=b"test"):
        return {
            "version": version,
            "name": f"POSTECH GenAI Chat {version}",
            "notes": "Release notes",
            "assets": {
                "windows": {
                    "file": "PostechChat-Setup.exe",
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            },
        }

    @patch("updates._latest_manifest")
    def test_check_update_compares_semver_and_requires_platform_asset(self, latest):
        latest.return_value = self.manifest("1.10.0")
        result = updates.check_update("1.9.9", "windows")
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "1.10.0")

        latest.return_value = self.manifest("1.9.9")
        self.assertFalse(updates.check_update("1.10.0", "windows")["available"])

        with self.assertRaisesRegex(updates.UpdateError, "설치 파일"):
            updates.check_update("1.8.0", "macos")

    @patch("updates.requests.get")
    def test_update_check_uses_public_cdn_without_authentication(self, get):
        response = Mock(status_code=200)
        response.json.return_value = self.manifest()
        get.return_value = response

        updates.check_update("1.8.0", "windows")

        self.assertEqual(get.call_args.args[0], updates.MANIFEST_URL)
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])

    @patch("updates.requests.get")
    def test_download_verifies_checksum_and_expected_size(self, get):
        manifest_response = Mock(status_code=200)
        manifest_response.json.return_value = self.manifest()
        asset_response = Mock(status_code=200)
        asset_response.__enter__ = lambda self: self
        asset_response.__exit__ = Mock(return_value=False)
        asset_response.iter_content.return_value = [b"te", b"st"]
        get.side_effect = [manifest_response, asset_response]

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "installer.exe"
            path = updates.download_update("1.8.0", "windows", destination)
            self.assertEqual(path.read_bytes(), b"test")

        self.assertEqual(
            get.call_args_list[1].args[0],
            f"{updates.CDN_BASE_URL}/releases/1.9.0/PostechChat-Setup.exe",
        )

    @patch("updates.requests.get")
    def test_download_rejects_bad_checksum_and_removes_partial_file(self, get):
        manifest_response = Mock(status_code=200)
        manifest = self.manifest()
        manifest["assets"]["windows"]["sha256"] = "0" * 64
        manifest_response.json.return_value = manifest
        asset_response = Mock(status_code=200)
        asset_response.__enter__ = lambda self: self
        asset_response.__exit__ = Mock(return_value=False)
        asset_response.iter_content.return_value = [b"test"]
        get.side_effect = [manifest_response, asset_response]

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "installer.exe"
            with self.assertRaisesRegex(updates.UpdateError, "체크섬"):
                updates.download_update("1.8.0", "windows", destination)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(".exe.part").exists())


if __name__ == "__main__":
    unittest.main()
