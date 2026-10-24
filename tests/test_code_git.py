# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15): Git 상태·차이·스테이지·커밋(code_git). git이 없으면 건너뛴다."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import code_git  # noqa: E402


@unittest.skipUnless(shutil.which("git"), "git이 없습니다")
class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "내 저장소 one")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "tester")
        self.write("src/한글 파일.py", "x = 1\n")
        self.write("README.md", "# r\n")
        self.git("add", ".")
        self.git("commit", "-qm", "init")

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True, check=check)

    def write(self, rel, text):
        p = Path(self.repo, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_not_a_repository(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        st = code_git.status(plain)
        self.assertFalse(st["repo"])
        self.assertIn("Git 저장소가 아닙니다", st["reason"])

    def test_status_staged_unstaged_untracked_and_deleted(self):
        self.write("src/한글 파일.py", "x = 2\n")
        self.write("new file.txt", "n\n")
        os.remove(Path(self.repo, "README.md"))
        self.write("staged.txt", "s\n")
        self.git("add", "staged.txt")
        st = code_git.status(self.repo)
        self.assertEqual(st["branch"], "main")
        files = {f["path"]: f for f in st["files"]}
        self.assertTrue(files["src/한글 파일.py"]["unstaged"])
        self.assertFalse(files["src/한글 파일.py"]["staged"])
        self.assertTrue(files["new file.txt"]["untracked"])
        self.assertEqual(files["README.md"]["y"], "D")
        self.assertTrue(files["staged.txt"]["staged"])
        self.assertEqual(files["staged.txt"]["x"], "A")

    def test_diff_staged_and_unstaged_and_untracked(self):
        self.write("src/한글 파일.py", "x = 2\n")
        d = code_git.diff(self.repo, "src/한글 파일.py")
        self.assertIn("-x = 1", d["diff"])
        self.assertIn("+x = 2", d["diff"])
        self.assertEqual(code_git.diff(self.repo, "src/한글 파일.py", staged=True)["diff"], "")
        code_git.stage(self.repo, ["src/한글 파일.py"])
        self.assertIn("+x = 2", code_git.diff(self.repo, "src/한글 파일.py", staged=True)["diff"])
        self.assertEqual(code_git.diff(self.repo, "src/한글 파일.py")["diff"], "")
        code_git.unstage(self.repo, ["src/한글 파일.py"])
        st = {f["path"]: f for f in code_git.status(self.repo)["files"]}
        self.assertFalse(st["src/한글 파일.py"]["staged"])
        self.write("brand new.v", "module m; endmodule\n")
        self.assertIn("+module m; endmodule", code_git.diff(self.repo, "brand new.v")["diff"])

    def test_commit_only_what_was_staged(self):
        self.write("src/한글 파일.py", "x = 3\n")
        self.write("README.md", "# changed\n")
        with self.assertRaises(code_git.GitError):
            code_git.commit(self.repo, "nothing staged")
        code_git.stage(self.repo, ["README.md"])
        res = code_git.commit(self.repo, "docs: update readme")
        self.assertIn("docs: update readme", res["commit"])
        st = {f["path"]: f for f in code_git.status(self.repo)["files"]}
        self.assertTrue(st["src/한글 파일.py"]["unstaged"])  # 스테이지하지 않은 파일은 커밋되지 않았다
        self.assertNotIn("README.md", st)
        with self.assertRaises(code_git.GitError):
            code_git.commit(self.repo, "   ")

    def test_conflicts_are_detected(self):
        self.git("checkout", "-q", "-b", "other")
        self.write("README.md", "# other\n")
        self.git("commit", "-qam", "other")
        self.git("checkout", "-q", "main")
        self.write("README.md", "# main\n")
        self.git("commit", "-qam", "main")
        self.git("merge", "other", check=False)
        st = code_git.status(self.repo)
        self.assertEqual(st["conflicts"], 1)
        self.assertTrue([f for f in st["files"] if f["path"] == "README.md"][0]["conflict"])

    def test_workspace_in_a_subfolder_sees_only_its_files(self):
        self.write("src/한글 파일.py", "x = 9\n")
        self.write("README.md", "# outside\n")
        st = code_git.status(os.path.join(self.repo, "src"))
        self.assertEqual([f["path"] for f in st["files"]], ["한글 파일.py"])
        self.assertEqual(st["outside"], 1)
        self.assertIn("+x = 9", code_git.diff(os.path.join(self.repo, "src"), "한글 파일.py")["diff"])

    def test_no_dangerous_commands_are_exposed(self):
        names = [n for n in dir(code_git) if not n.startswith("_")]
        for bad in ("reset", "clean", "checkout", "push", "rebase", "force"):
            self.assertFalse([n for n in names if bad in n.lower()], bad)


if __name__ == "__main__":
    unittest.main()
