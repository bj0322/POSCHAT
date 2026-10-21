import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import updates


class UpdateTests(unittest.TestCase):
    def release(self, tag="v1.9.0"):
        return {
            "tag_name": tag,
            "name": "POSTECH GenAI Chat",
            "body": "Release notes",
            "html_url": "https://github.com/bj0322/POSCHAT/releases/tag/v1.9.0",
            "assets": [{"id": 42, "name": "PostechChat-Setup.exe", "size": 4}],
        }

    @patch("updates._latest_release")
    def test_check_update_selects_platform_asset_and_compares_semver(self, latest):
        latest.return_value = self.release("v1.10.0")
        result = updates.check_update("1.9.9", "token", "windows")
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "1.10.0")

        latest.return_value = self.release("v1.9.9")
        self.assertFalse(updates.check_update("1.10.0", "token", "windows")["available"])

    @patch("updates.requests.get")
    def test_download_uses_release_asset_api_and_writes_expected_bytes(self, get):
        release_response = Mock(status_code=200)
        release_response.json.return_value = self.release()
        asset_response = Mock(status_code=200)
        asset_response.__enter__ = lambda self: self
        asset_response.__exit__ = Mock(return_value=False)
        asset_response.iter_content.return_value = [b"test"]
        get.side_effect = [release_response, asset_response]

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "installer.exe"
            path = updates.download_update("1.8.0", "secret-token", "windows", destination)
            self.assertEqual(path.read_bytes(), b"test")

        self.assertEqual(get.call_args_list[1].args[0],
                         "https://api.github.com/repos/bj0322/POSCHAT/releases/assets/42")
        self.assertEqual(get.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer secret-token")

    @patch("updates.requests.get")
    def test_private_repository_requires_authentication(self, get):
        response = Mock(status_code=404)
        get.return_value = response
        with self.assertRaisesRegex(updates.UpdateError, "토큰이 필요합니다"):
            updates.check_update("1.8.0", "", "windows")


if __name__ == "__main__":
    unittest.main()
