# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.11.1 설치 프로그램의 앱 파일 바꾸기(installer/appfiles.py): 중간에 실패해도 앱이 열리지 않는 상태로 남지 않는다."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "installer"))
import appfiles  # noqa: E402

EXE = "PostechChat.exe"


def payload(version):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(EXE, f"exe {version}")
        zf.writestr("_internal/python312.dll", f"python {version}")
        zf.writestr("_internal/VCRUNTIME140.dll", f"vcrt {version}")
        zf.writestr("_internal/web/index.html", f"web {version}")
    buf.seek(0)
    return zipfile.ZipFile(buf)


def read(path):
    return Path(path).read_text(encoding="utf-8")


class AppFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "PostechChat"
        appfiles.replace(self.dest, appfiles.extract(payload("1.10"), self.dest))
        self.assertEqual(read(self.dest / "_internal" / "python312.dll"), "python 1.10")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self):
        return sorted(p.name for p in self.dest.iterdir())

    def test_update_replaces_files_and_leaves_no_work_folders(self):
        (self.dest / "uninstall.ps1").write_text("old")
        progress = []
        stage = appfiles.extract(payload("1.11"), self.dest, lambda v, t: progress.append(v), share=88)
        appfiles.verify(stage, EXE)
        appfiles.replace(self.dest, stage)
        self.assertEqual(read(self.dest / EXE), "exe 1.11")
        self.assertEqual(read(self.dest / "_internal" / "VCRUNTIME140.dll"), "vcrt 1.11")
        self.assertEqual(self.names(), [EXE, "_internal"])
        self.assertAlmostEqual(progress[-1], 88)

    def test_a_dll_in_use_is_moved_aside_one_file_at_a_time(self):
        # Windows: 불러 둔 DLL이 있는 폴더는 통째로 옮기지 못하지만 그 파일 자체는 옮길 수 있다
        real_rename = os.rename
        locked_dir = str(self.dest / "_internal")

        def rename(src, dst):
            if str(src) == locked_dir:
                raise PermissionError(13, "Access is denied", str(src))
            return real_rename(src, dst)

        stage = appfiles.extract(payload("1.11"), self.dest)
        with patch.object(appfiles.os, "rename", side_effect=rename):
            appfiles.replace(self.dest, stage, attempts=2, delay=0)
        self.assertEqual(read(self.dest / "_internal" / "python312.dll"), "python 1.11")
        self.assertEqual(read(self.dest / "_internal" / "web" / "index.html"), "web 1.11")

    def test_failure_puts_the_previous_version_back(self):
        real_rename = os.rename
        locked = str(self.dest / "_internal" / "VCRUNTIME140.dll")

        def rename(src, dst):
            if str(src) in (locked, str(self.dest / "_internal")):
                raise PermissionError(13, "Access is denied", str(src))
            return real_rename(src, dst)

        stage = appfiles.extract(payload("1.11"), self.dest)
        with patch.object(appfiles.os, "rename", side_effect=rename):
            with self.assertRaisesRegex(appfiles.InstallError, "이전 버전은 그대로"):
                appfiles.replace(self.dest, stage, attempts=2, delay=0)
        # 이전 버전 파일이 모두 제자리에 있다(반쯤 지워진 _internal이 남지 않는다)
        self.assertEqual(read(self.dest / EXE), "exe 1.10")
        for name, text in (("python312.dll", "python 1.10"), ("VCRUNTIME140.dll", "vcrt 1.10")):
            self.assertEqual(read(self.dest / "_internal" / name), text)
        self.assertEqual(read(self.dest / "_internal" / "web" / "index.html"), "web 1.10")
        # 남은 작업 폴더는 다음 설치가 정리하고 그대로 설치된다
        appfiles.cleanup(self.dest)
        appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest))
        self.assertEqual(read(self.dest / "_internal" / "VCRUNTIME140.dll"), "vcrt 1.11")
        self.assertEqual(self.names(), [EXE, "_internal"])

    def test_a_half_deleted_install_from_1_11_0_is_repaired(self):
        (self.dest / "_internal" / "python312.dll").unlink()  # 1.11.0 설치 프로그램이 지우다 멈춘 상태
        appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest))
        self.assertEqual(read(self.dest / "_internal" / "python312.dll"), "python 1.11")

    def test_leftover_work_folder_that_cannot_be_removed_gets_another_name(self):
        (self.dest / "_old").mkdir()
        real_remove = appfiles.remove

        def remove(path, attempts=1, delay=0.5):
            return False if Path(path).name == "_old" else real_remove(path, attempts, delay)

        with patch.object(appfiles, "remove", side_effect=remove):
            appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest))
        self.assertEqual(read(self.dest / EXE), "exe 1.11")
        self.assertTrue((self.dest / "_old").exists())  # 지우지 못한 것은 그대로 두고 _old-1을 썼다

    def test_verify_refuses_a_payload_without_python(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(EXE, "exe")
            zf.writestr("_internal/base_library.zip", "x")
        stage = appfiles.extract(zipfile.ZipFile(io.BytesIO(buf.getvalue())), self.dest)
        with self.assertRaises(appfiles.InstallError):
            appfiles.verify(stage, EXE)
        self.assertEqual(read(self.dest / EXE), "exe 1.10")


if __name__ == "__main__":
    unittest.main()
