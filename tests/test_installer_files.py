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
        zf.writestr("_internal/base_library.zip", f"stdlib {version}")
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
        appfiles.replace(self.dest, appfiles.extract(payload("1.10"), self.dest), EXE)
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
        appfiles.replace(self.dest, stage, EXE)
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
            appfiles.replace(self.dest, stage, EXE, attempts=2, delay=0)
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
                appfiles.replace(self.dest, stage, EXE, attempts=2, delay=0)
        # 이전 버전 파일이 모두 제자리에 있다(반쯤 지워진 _internal이 남지 않는다)
        self.assertEqual(read(self.dest / EXE), "exe 1.10")
        for name, text in (("python312.dll", "python 1.10"), ("VCRUNTIME140.dll", "vcrt 1.10")):
            self.assertEqual(read(self.dest / "_internal" / name), text)
        self.assertEqual(read(self.dest / "_internal" / "web" / "index.html"), "web 1.10")
        # 남은 작업 폴더는 다음 설치가 정리하고 그대로 설치된다
        appfiles.cleanup(self.dest, EXE)
        appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest), EXE)
        self.assertEqual(read(self.dest / "_internal" / "VCRUNTIME140.dll"), "vcrt 1.11")
        self.assertEqual(self.names(), [EXE, "_internal"])

    def test_a_half_deleted_install_from_1_11_0_is_repaired(self):
        (self.dest / "_internal" / "python312.dll").unlink()  # 1.11.0 설치 프로그램이 지우다 멈춘 상태
        appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest), EXE)
        self.assertEqual(read(self.dest / "_internal" / "python312.dll"), "python 1.11")

    def test_leftover_work_folder_that_cannot_be_removed_gets_another_name(self):
        (self.dest / "_old").mkdir()
        real_remove = appfiles.remove

        def remove(path, attempts=1, delay=0.5):
            return False if Path(path).name == "_old" else real_remove(path, attempts, delay)

        with patch.object(appfiles, "remove", side_effect=remove):
            appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest), EXE)
        self.assertEqual(read(self.dest / EXE), "exe 1.11")
        self.assertEqual(read(self.dest / "_internal" / "python312.dll"), "python 1.11")

    def test_verify_refuses_a_payload_without_python(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(EXE, "exe")
            zf.writestr("_internal/base_library.zip", "x")
            zf.writestr("_internal/VCRUNTIME140.dll", "x")
        stage = appfiles.extract(zipfile.ZipFile(io.BytesIO(buf.getvalue())), self.dest)
        with self.assertRaises(appfiles.InstallError):
            appfiles.verify(stage, EXE)
        self.assertEqual(read(self.dest / EXE), "exe 1.10")

    def test_failed_launch_check_puts_the_previous_version_back(self):
        stage = appfiles.extract(payload("1.11"), self.dest)
        seen = []

        def check(root):
            seen.append(read(Path(root) / EXE))
            return False

        with self.assertRaisesRegex(appfiles.InstallError, "실행되지 않습니다.*이전 버전은 그대로"):
            appfiles.replace(self.dest, stage, EXE, check=check, attempts=2, delay=0)
        self.assertEqual(seen, ["exe 1.11"])  # 바꾼 뒤의 새 버전을 확인했다
        self.assertEqual(read(self.dest / EXE), "exe 1.10")
        self.assertEqual(read(self.dest / "_internal" / "python312.dll"), "python 1.10")
        self.assertEqual(self.names(), [EXE, "_internal"])

    def test_launch_check_errors_count_as_failure(self):
        def check(root):
            raise RuntimeError("timeout")

        with self.assertRaisesRegex(appfiles.InstallError, "timeout"):
            appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest), EXE, check=check, attempts=2, delay=0)
        self.assertEqual(read(self.dest / EXE), "exe 1.10")

    def test_failed_rollback_keeps_the_backup_with_a_restore_note(self):
        real_rename = os.rename
        state = {"phase": "install"}

        def rename(src, dst):
            # 새 파일을 다 옮긴 뒤 확인이 실패하고, 되돌리는 중에는 _internal을 제자리로 옮기지 못한다
            if state["phase"] == "rollback" and Path(src).name in ("_internal", "python312.dll") and "_old" in str(src):
                raise PermissionError(13, "Access is denied", str(src))
            return real_rename(src, dst)

        def check(root):
            state["phase"] = "rollback"
            return False

        stage = appfiles.extract(payload("1.11"), self.dest)
        with patch.object(appfiles.os, "rename", side_effect=rename):
            with self.assertRaises(appfiles.InstallError) as caught:
                appfiles.replace(self.dest, stage, EXE, check=check, attempts=2, delay=0)
        backup = caught.exception.backup
        self.assertIsNotNone(backup)
        self.assertIn("되돌리지 못했습니다", str(caught.exception))
        self.assertTrue((backup / appfiles.MARKER).is_file())
        self.assertEqual(read(backup / "_internal" / "python312.dll"), "python 1.10")  # 이전 버전이 백업에 남아 있다
        # 다음 설치는 지금 앱이 온전하지 않으므로 백업을 먼저 지우지 않는다
        appfiles.cleanup(self.dest, EXE)
        self.assertTrue((backup / "_internal" / "python312.dll").exists())
        # 새 설치가 확인되면 그때 백업을 지운다
        appfiles.replace(self.dest, appfiles.extract(payload("1.11"), self.dest), EXE, check=lambda root: True)
        self.assertEqual(read(self.dest / "_internal" / "python312.dll"), "python 1.11")
        self.assertFalse(backup.exists())
        self.assertEqual(self.names(), [EXE, "_internal"])

    def test_backup_with_restore_note_survives_cleanup_even_when_app_is_healthy(self):
        backup = self.dest / "_old"
        (backup / "_internal").mkdir(parents=True)
        (backup / appfiles.MARKER).write_text("restore", encoding="utf-8")
        appfiles.cleanup(self.dest, EXE)
        self.assertTrue(backup.exists())
        # 새 백업은 그 폴더를 건드리지 않고 다른 이름을 쓴다
        self.assertEqual(appfiles._free_dir(self.dest, appfiles.OLD, wipe=False).name, "_old-1")

    def test_corrupted_payload_is_refused_before_touching_anything(self):
        data = bytearray(payload("1.11").fp.getvalue())
        i = data.find(b"python 1.11")
        data[i:i + 6] = b"PYTHON"  # 내용은 바뀌고 CRC는 그대로
        with self.assertRaisesRegex(appfiles.InstallError, "손상"):
            appfiles.extract(zipfile.ZipFile(io.BytesIO(bytes(data))), self.dest)
        self.assertEqual(self.names(), [EXE, "_internal"])
        self.assertEqual(read(self.dest / EXE), "exe 1.10")

    def test_missing_vc_runtime_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(EXE, "exe")
            zf.writestr("_internal/python312.dll", "py")
            zf.writestr("_internal/base_library.zip", "x")
        stage = appfiles.extract(zipfile.ZipFile(io.BytesIO(buf.getvalue())), self.dest)
        with self.assertRaisesRegex(appfiles.InstallError, "VCRUNTIME140"):
            appfiles.replace(self.dest, stage, EXE)
        self.assertEqual(read(self.dest / EXE), "exe 1.10")


if __name__ == "__main__":
    unittest.main()
