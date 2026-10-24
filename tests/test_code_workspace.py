# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15): 파일 열기·저장·목록·찾기(code_workspace)."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import code_workspace as cw  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "작업 폴더")
        os.makedirs(self.ws)

    def put(self, rel, data):
        p = Path(self.ws, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p


class OpenSaveTests(Base):
    def test_open_and_save_a_normal_file(self):
        self.put("src/main.py", "print('hi')\n")
        info = cw.read_file(self.ws, "src/main.py")
        self.assertEqual(info["text"], "print('hi')\n")
        self.assertEqual(info["language"], "python")
        self.assertFalse(info["readonly"])
        saved = cw.write_file(self.ws, "src/main.py", "print('bye')\n", info["hash"])
        self.assertEqual(Path(self.ws, "src/main.py").read_text(), "print('bye')\n")
        self.assertEqual(saved["hash"], cw.current_hash(self.ws, "src/main.py"))
        self.assertFalse(list(Path(self.ws, "src").glob("*.poschat-tmp")))  # 임시 파일이 남지 않는다

    def test_crlf_and_final_newline_are_kept(self):
        self.put("a.c", b"int a;\r\nint b;\r\n")
        info = cw.read_file(self.ws, "a.c")
        self.assertEqual(info["newline"], "\r\n")
        self.assertEqual(info["text"], "int a;\nint b;\n")  # 편집기는 \n
        cw.write_file(self.ws, "a.c", info["text"] + "int c;\n", info["hash"], info["encoding"], info["newline"])
        self.assertEqual(Path(self.ws, "a.c").read_bytes(), b"int a;\r\nint b;\r\nint c;\r\n")
        self.put("b.txt", b"no newline at end")
        info = cw.read_file(self.ws, "b.txt")
        self.assertFalse(info["final_newline"])
        cw.write_file(self.ws, "b.txt", info["text"] + "!", info["hash"])
        self.assertEqual(Path(self.ws, "b.txt").read_bytes(), b"no newline at end!")

    def test_mixed_newlines_are_reported(self):
        self.put("m.txt", b"a\r\nb\r\nc\n")
        info = cw.read_file(self.ws, "m.txt")
        self.assertTrue(info["mixed_newlines"])
        self.assertEqual(info["newline"], "\r\n")

    def test_unicode_bom_and_cp949_encodings_are_kept(self):
        self.put("한글.md", "# 반도체 설계 노트\n")
        info = cw.read_file(self.ws, "한글.md")
        self.assertEqual(info["encoding"], "utf-8")
        self.assertIn("반도체", info["text"])
        self.put("bom.txt", b"\xef\xbb\xbfhello\n")
        info = cw.read_file(self.ws, "bom.txt")
        self.assertEqual(info["encoding"], "utf-8-sig")
        cw.write_file(self.ws, "bom.txt", "hello2\n", info["hash"], info["encoding"])
        self.assertEqual(Path(self.ws, "bom.txt").read_bytes(), b"\xef\xbb\xbfhello2\n")
        self.put("old.txt", "옛 한글 파일\n".encode("cp949"))
        info = cw.read_file(self.ws, "old.txt")
        self.assertEqual(info["encoding"], "cp949")
        cw.write_file(self.ws, "old.txt", "옛 한글 파일 고침\n", info["hash"], info["encoding"])
        self.assertEqual(Path(self.ws, "old.txt").read_bytes(), "옛 한글 파일 고침\n".encode("cp949"))
        with self.assertRaises(cw.WorkspaceError):  # CP949에 없는 글자
            cw.write_file(self.ws, "old.txt", "emoji 😀\n", cw.current_hash(self.ws, "old.txt"), "cp949")
        self.put("u16.txt", b"\xff\xfe" + "wide\n".encode("utf-16-le"))
        info = cw.read_file(self.ws, "u16.txt")
        self.assertEqual((info["encoding"], info["text"], info["binary"]), ("utf-16", "wide\n", False))

    def test_unknown_encoding_opens_read_only(self):
        self.put("bad.txt", b"ok \x81\xff\xfe\x80 broken")  # UTF-8도 CP949도 아니다
        info = cw.read_file(self.ws, "bad.txt")
        self.assertTrue(info["readonly"])
        self.assertIn("인코딩", info["reason"])

    def test_large_and_binary_files(self):
        self.put("big.v", "// x\n" * (cw.MAX_EDIT_BYTES // 5 + 10))
        info = cw.read_file(self.ws, "big.v")
        self.assertTrue(info["readonly"])
        self.assertIn("1MB", info["reason"])
        with patch.object(cw, "MAX_OPEN_BYTES", 1000):
            with self.assertRaises(cw.WorkspaceError):
                cw.read_file(self.ws, "big.v")
        self.put("img.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(100))
        info = cw.read_file(self.ws, "img.png")
        self.assertTrue(info["binary"])
        self.assertEqual(info["text"], "")

    def test_external_change_is_a_conflict_and_force_overwrites(self):
        self.put("x.py", "a = 1\n")
        info = cw.read_file(self.ws, "x.py")
        self.put("x.py", "a = 2  # 다른 프로그램\n")
        with self.assertRaises(cw.ConflictError) as ctx:
            cw.write_file(self.ws, "x.py", "a = 3\n", info["hash"])
        self.assertEqual(Path(self.ws, "x.py").read_text(encoding="utf-8"), "a = 2  # 다른 프로그램\n")
        self.assertEqual(ctx.exception.current_hash, cw.current_hash(self.ws, "x.py"))
        cw.write_file(self.ws, "x.py", "a = 3\n", info["hash"], force=True)
        self.assertEqual(Path(self.ws, "x.py").read_text(), "a = 3\n")
        os.remove(Path(self.ws, "x.py"))
        with self.assertRaises(cw.ConflictError):  # 지워진 파일
            cw.write_file(self.ws, "x.py", "a = 4\n", cw.sha256(b"a = 3\n"))

    def test_failed_save_keeps_the_original(self):
        self.put("keep.py", "original\n")
        info = cw.read_file(self.ws, "keep.py")
        with patch.object(cw.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                cw.write_file(self.ws, "keep.py", "new\n", info["hash"])
        self.assertEqual(Path(self.ws, "keep.py").read_text(), "original\n")
        self.assertEqual([p.name for p in Path(self.ws).iterdir()], ["keep.py"])  # 임시 파일 정리

    @unittest.skipIf(os.name == "nt", "POSIX 권한 비트")
    def test_permission_bits_are_kept(self):
        p = self.put("run.sh", "#!/bin/sh\necho hi\n")
        os.chmod(p, 0o755)
        info = cw.read_file(self.ws, "run.sh")
        cw.write_file(self.ws, "run.sh", "#!/bin/sh\necho bye\n", info["hash"])
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o755)

    @unittest.skipIf(os.name == "nt", "POSIX 권한 비트")
    def test_new_files_get_normal_permissions_and_read_only_files_are_kept(self):
        cw.write_file(self.ws, "fresh.py", "x = 1\n", cw.ABSENT)
        self.assertEqual(stat.S_IMODE(os.stat(Path(self.ws, "fresh.py")).st_mode), cw.DEFAULT_MODE)
        p = self.put("locked.txt", "keep\n")
        os.chmod(p, 0o444)
        self.addCleanup(os.chmod, p, 0o644)
        info = cw.read_file(self.ws, "locked.txt")
        if os.access(p, os.W_OK):
            self.skipTest("관리자 권한으로 실행 중(읽기 전용 파일도 쓸 수 있음)")
        self.assertTrue(info["readonly"])
        with self.assertRaises(PermissionError):
            cw.write_file(self.ws, "locked.txt", "changed\n", info["hash"], force=True)
        self.assertEqual(p.read_text(), "keep\n")

    def test_empty_base_hash_means_the_file_must_be_new(self):
        self.put("exists.txt", "a\n")
        with self.assertRaises(cw.ConflictError):
            cw.write_file(self.ws, "exists.txt", "b\n", "")
        self.assertEqual(Path(self.ws, "exists.txt").read_text(), "a\n")

    def test_create_rename_delete(self):
        Path(self.ws, "rtl").mkdir()
        cw.create(self.ws, "rtl/top.sv")
        self.assertTrue(Path(self.ws, "rtl/top.sv").is_file())
        with self.assertRaises(cw.WorkspaceError):
            cw.create(self.ws, "rtl/top.sv")  # 이미 있음
        cw.create(self.ws, "rtl/sim", "dir")
        self.assertTrue(Path(self.ws, "rtl/sim").is_dir())
        self.put("rtl/tb.sv", "module tb; endmodule\n")
        with self.assertRaises(cw.WorkspaceError):
            cw.rename(self.ws, "rtl/tb.sv", "rtl/top.sv")  # 덮어쓰지 않는다
        cw.rename(self.ws, "rtl/tb.sv", "rtl/sim/tb.sv")
        self.assertTrue(Path(self.ws, "rtl/sim/tb.sv").is_file())
        trash = Path(self.tmp.name, "trash")
        res = cw.delete_to_trash(self.ws, "rtl/sim/tb.sv", trash)
        self.assertFalse(Path(self.ws, "rtl/sim/tb.sv").exists())
        self.assertEqual(Path(res["trash"]).read_text(), "module tb; endmodule\n")  # 되살릴 수 있다
        with self.assertRaises(cw.WorkspaceError):
            cw.delete_to_trash(self.ws, "rtl", trash)  # 비어 있지 않은 폴더


class ListSearchTests(Base):
    def test_list_one_level_with_default_excludes_and_hidden(self):
        for rel in ("src/a.py", "node_modules/x/index.js", ".venv/lib/x.py", "__pycache__/a.pyc", ".env", "README.md",
                    ".git/objects/ab/cdef"):
            self.put(rel, "x")
        res = cw.list_dir(self.ws, "")
        names = [i["name"] for i in res["items"]]
        self.assertEqual(names, ["src", "README.md"])  # 폴더 먼저, 제외·숨김 빠짐
        self.assertTrue(res["items"][0]["dir"])
        self.assertGreaterEqual(res["excluded"], 2)
        hidden = cw.list_dir(self.ws, "", show_hidden=True)
        self.assertIn(".env", [i["name"] for i in hidden["items"]])
        self.assertNotIn(".git", [i["name"] for i in hidden["items"]])  # .git은 기본 제외
        custom = cw.list_dir(self.ws, "", show_hidden=True, excludes=[])
        self.assertIn("node_modules", [i["name"] for i in custom["items"]])
        self.assertEqual([i["path"] for i in cw.list_dir(self.ws, "src")["items"]], ["src/a.py"])

    def test_search_names_and_text(self):
        self.put("rtl/adc.sv", "module adc(input clk);\n  // quantize here\nendmodule\n")
        self.put("sim/aimc.py", "def quantize(x):\n    return round(x)\n")
        self.put("node_modules/q.js", "quantize")
        self.put("bin.dat", b"\x00quantize")
        self.assertEqual([r["path"] for r in cw.search(self.ws, "adc", "name")["results"]], ["rtl/adc.sv"])
        hits = cw.search(self.ws, "QUANTIZE", "text")["results"]
        self.assertEqual(sorted((h["path"], h["line"]) for h in hits), [("rtl/adc.sv", 2), ("sim/aimc.py", 1)])
        self.assertEqual(len(cw.search(self.ws, "QUANTIZE", "text", case=True)["results"]), 0)
        self.assertEqual(cw.search(self.ws, r"def \w+\(", "text", regex=True)["results"][0]["path"], "sim/aimc.py")
        with self.assertRaises(cw.WorkspaceError):
            cw.search(self.ws, "(", "text", regex=True)

    def test_language_detection(self):
        for name, lang in (("a.py", "python"), ("b.cpp", "cpp"), ("c.h", "c"), ("d.ts", "typescript"),
                           ("e.sv", "systemverilog"), ("f.v", "verilog"), ("g.tcl", "tcl"), ("h.sh", "shell"),
                           ("i.sp", "spice"), ("j.json", "json"), ("k.md", "markdown"), ("Makefile", "text"),
                           ("l.unknown", "text")):
            self.assertEqual(cw.language_of(name), lang, name)


if __name__ == "__main__":
    unittest.main()
