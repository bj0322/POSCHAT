# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""AGPL-3.0-only 전환: 저장소 점검(tools/license_check.py), 배포본 점검, 설정 화면의 라이선스 정보."""
import io
import os
import sys
import tempfile
import types
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

sys.modules.setdefault("webview", types.ModuleType("webview"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # support.py
sys.path.insert(0, str(HERE.parent / "tools"))

import license_check  # noqa: E402
from support import isolated_app_dir, preserved_hooks  # noqa: E402


def quiet(fn, *args, **kwargs):
    with redirect_stdout(io.StringIO()) as out:
        code = fn(*args, **kwargs)
    return code, out.getvalue()


class RepositoryTests(unittest.TestCase):
    def test_repository_passes_the_license_check(self):
        code, out = quiet(license_check.check_repo)
        self.assertEqual(code, 0, out)

    def test_license_is_the_official_agpl_text(self):
        text = (HERE.parent / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE"))
        self.assertIn("Version 3, 19 November 2007", text)


class PackageTests(unittest.TestCase):
    def test_package_check_finds_license_and_notices_in_zip_or_folder(self):
        license_bytes = (HERE.parent / "LICENSE").read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            good = Path(temp) / "good.apk"
            with zipfile.ZipFile(good, "w") as z:
                z.writestr("assets/LICENSE", license_bytes)
                z.writestr("assets/THIRD_PARTY_NOTICES.md", "notices")
                z.writestr("licenses/python/requests-2/LICENSE", "Apache")
            self.assertEqual(quiet(license_check.check_package, [str(good)], True)[0], 0)

            bad = Path(temp) / "bad.zip"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("LICENSE", "MIT License")  # 다른 라이선스 글
                z.writestr("THIRD_PARTY_NOTICES.md", "notices")
            code, out = quiet(license_check.check_package, [str(bad)])
            self.assertEqual(code, 1)
            self.assertIn("LICENSE", out)

            folder = Path(temp) / "app"
            (folder / "Contents" / "Resources").mkdir(parents=True)
            (folder / "LICENSE.txt").write_bytes(license_bytes)
            (folder / "Contents" / "Resources" / "THIRD_PARTY_NOTICES.md").write_text("n")
            self.assertEqual(quiet(license_check.check_package, [str(folder)])[0], 0)
            self.assertEqual(quiet(license_check.check_package, [str(folder)], True)[0], 1)  # licenses/python 없음

    def test_dependency_list_flags_licenses_that_need_review(self):
        self.assertTrue(license_check.INCOMPATIBLE.search("Proprietary"))
        self.assertTrue(license_check.INCOMPATIBLE.search("CC-BY-NC-4.0"))
        self.assertTrue(license_check.INCOMPATIBLE.search("SSPL-1.0"))
        for ok in ("MIT", "BSD-3-Clause", "Apache-2.0 OR BSD-3-Clause", "MPL-2.0", "PSF-2.0", "MIT-CMU"):
            self.assertIsNone(license_check.INCOMPATIBLE.search(ok), ok)
        with tempfile.TemporaryDirectory() as temp:
            req = Path(temp) / "req.txt"
            req.write_text("requests>=2  # 설명\n")
            rows = license_check.dependency_rows([req])
            names = {r[0].lower() for r in rows}
            self.assertIn("requests", names)
            self.assertIn("urllib3", names)  # 의존성의 의존성까지 따라간다


class AppLicenseInfoTests(unittest.TestCase):
    def test_settings_show_license_source_and_third_party_notices(self):
        import main
        from version import APP_VERSION

        with isolated_app_dir(), preserved_hooks():
            info = main.Bridge().license_info()
        self.assertEqual(info["spdx"], "AGPL-3.0-only")
        self.assertEqual(info["copyright"], "Copyright © 2026 Beomjoon Kim")
        self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", info["license_text"])
        # 저장소 첫 화면이 아니라 이 버전의 태그
        self.assertTrue(info["source_url"].endswith(f"/tree/v{APP_VERSION}"))
        self.assertTrue(info["source_archive"].endswith(f"/archive/refs/tags/v{APP_VERSION}.zip"))
        names = [x["name"] for x in info["third_party"]]
        self.assertEqual(names[0], "THIRD_PARTY_NOTICES.md")
        for vendor in ("marked-LICENSE.md", "DOMPurify-LICENSE.txt", "KaTeX-LICENSE.txt"):
            self.assertIn(vendor, names)


if __name__ == "__main__":
    unittest.main()
