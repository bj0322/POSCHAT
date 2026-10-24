# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15): 변경 제안(ChangeProposal)·덩어리 적용(code_diff)과 에이전트 write/edit의 Code 화면 검토."""
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import code_diff  # noqa: E402
import code_workspace as cw  # noqa: E402
import main  # noqa: E402
from agent import Agent  # noqa: E402
from support import isolated_app_dir, preserved_hooks  # noqa: E402

BASE = "".join(f"line {i}\n" for i in range(1, 41))


def changed(text, **repl):
    lines = text.splitlines(keepends=True)
    for k, v in repl.items():
        lines[int(k[1:]) - 1] = v
    return "".join(lines)


class HunkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = self.tmp.name
        Path(self.ws, "f.py").write_text(BASE)
        self.new = changed(BASE, l3="LINE three\n", l20="LINE twenty\n", l38="LINE 38\n")

    def proposal(self, new=None, rel="f.py"):
        original = Path(self.ws, rel).read_text() if Path(self.ws, rel).exists() else ""
        return code_diff.new_proposal(self.ws, rel, original, new if new is not None else self.new)

    def test_far_apart_changes_are_separate_hunks(self):
        p = self.proposal()
        self.assertEqual(len(p.hunks), 3)
        d = p.to_dict()
        self.assertEqual((d["added"], d["removed"]), (3, 3))
        self.assertEqual(d["hunks"][0]["header"], "@@ -1,6 +1,6 @@")
        kinds = [x["t"] for x in d["hunks"][1]["lines"]]
        self.assertEqual(kinds.count("-"), 1)
        self.assertEqual(kinds.count("+"), 1)

    def test_nearby_changes_are_one_hunk(self):
        p = self.proposal(changed(BASE, l10="A\n", l13="B\n"))
        self.assertEqual(len(p.hunks), 1)

    def test_accept_some_hunks(self):
        p = self.proposal()
        res = code_diff.apply(self.ws, p, [0, 2])
        self.assertEqual(res["status"], "partial")
        text = Path(self.ws, "f.py").read_text()
        self.assertIn("LINE three", text)
        self.assertNotIn("LINE twenty", text)
        self.assertIn("line 20\n", text)
        self.assertIn("LINE 38", text)
        self.assertEqual(p.status, "partial")
        self.assertEqual(p.accepted, [0, 2])

    def test_accept_all_and_reject_all(self):
        p = self.proposal()
        self.assertEqual(code_diff.apply(self.ws, p, [0, 1, 2])["status"], "applied")
        self.assertEqual(Path(self.ws, "f.py").read_text(), self.new)
        Path(self.ws, "f.py").write_text(BASE)
        p = self.proposal()
        self.assertEqual(code_diff.reject(p)["status"], "rejected")
        self.assertEqual(Path(self.ws, "f.py").read_text(), BASE)
        p = self.proposal()
        self.assertEqual(code_diff.apply(self.ws, p, [])["status"], "rejected")  # 아무것도 고르지 않음 = 거부

    def test_no_double_apply(self):
        p = self.proposal()
        code_diff.apply(self.ws, p, [0])
        with self.assertRaises(code_diff.ProposalError):
            code_diff.apply(self.ws, p, [0, 1, 2])
        with self.assertRaises(code_diff.ProposalError):
            code_diff.reject(p)
        self.assertEqual(Path(self.ws, "f.py").read_text().count("LINE three"), 1)

    def test_store_reuses_an_identical_pending_proposal(self):
        store = code_diff.ProposalStore()
        a, created_a = store.add(self.proposal())
        b, created_b = store.add(self.proposal())  # 에이전트가 같은 변경을 다시 시도
        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertIs(a, b)
        self.assertEqual(len(store.pending()), 1)

    def test_file_changed_during_review_is_a_conflict(self):
        p = self.proposal()
        Path(self.ws, "f.py").write_text(changed(BASE, l30="edited elsewhere\n"))
        with self.assertRaises(cw.ConflictError):
            code_diff.apply(self.ws, p, [0, 1, 2])
        self.assertEqual(p.status, "pending")
        self.assertIn("edited elsewhere", Path(self.ws, "f.py").read_text())
        self.assertTrue(code_diff.preview(self.ws, p, [0])["conflict"])
        # 문맥이 그대로인 덩어리는 현재 파일에 맞춰 적용할 수 있다
        res = code_diff.apply(self.ws, p, [0, 1, 2], rebase=True)
        text = Path(self.ws, "f.py").read_text()
        self.assertEqual(res["status"], "applied")
        self.assertIn("edited elsewhere", text)
        self.assertIn("LINE three", text)
        self.assertIn("LINE 38", text)

    def test_rebase_refuses_when_the_hunk_context_changed(self):
        p = self.proposal()
        current = changed(BASE, l21="someone changed the context\n")
        Path(self.ws, "f.py").write_text(current)
        with self.assertRaises(cw.ConflictError) as ctx:
            code_diff.apply(self.ws, p, [0, 1, 2], rebase=True)
        self.assertIn("2번", str(ctx.exception))
        self.assertEqual(Path(self.ws, "f.py").read_text(), current)  # 하나라도 안 맞으면 아무것도 쓰지 않는다

    def test_failed_write_keeps_the_original(self):
        p = self.proposal()
        with patch.object(cw.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                code_diff.apply(self.ws, p, [0, 1, 2])
        self.assertEqual(Path(self.ws, "f.py").read_text(), BASE)
        self.assertEqual(p.status, "pending")  # 다시 시도할 수 있다
        self.assertEqual(sorted(os.listdir(self.ws)), ["f.py"])

    def test_crlf_lines_are_kept_in_partial_apply(self):
        raw = b"a\r\nb\r\nc\r\n" + b"x\r\n" * 10 + b"y\r\nz\r\n"
        Path(self.ws, "w.c").write_bytes(raw)
        original = raw.decode()
        new = original.replace("b\r\n", "B\r\n").replace("z\r\n", "Z\r\n")
        p = code_diff.new_proposal(self.ws, "w.c", original, new)
        self.assertEqual(len(p.hunks), 2)
        code_diff.apply(self.ws, p, [1])
        self.assertEqual(Path(self.ws, "w.c").read_bytes(), raw.replace(b"z\r\n", b"Z\r\n"))

    def test_new_file_and_edited_content(self):
        p = code_diff.new_proposal(self.ws, "pkg/new.py", "", "x = 1\n")
        self.assertTrue(p.is_new_file)
        code_diff.apply(self.ws, p, [0])
        self.assertEqual(Path(self.ws, "pkg/new.py").read_text(), "x = 1\n")
        p = self.proposal()
        res = code_diff.apply(self.ws, p, [], edited=BASE.replace("line 5\n", "my own fix\n"))
        self.assertEqual(res["status"], "edited")
        self.assertIn("my own fix", Path(self.ws, "f.py").read_text())

    def test_preview_warns_about_broken_python(self):
        Path(self.ws, "g.py").write_text("def f():\n    return 1\n")
        p = code_diff.new_proposal(self.ws, "g.py", "def f():\n    return 1\n", "def f(:\n    return 1\n")
        self.assertIn("문법 오류", code_diff.preview(self.ws, p, [0])["warning"])
        self.assertEqual(code_diff.preview(self.ws, p, [])["warning"], "")

    def test_proposal_requires_the_current_content(self):
        with self.assertRaises(code_diff.ProposalError):
            code_diff.new_proposal(self.ws, "f.py", "stale content\n", "x\n")


class AgentReviewTests(unittest.TestCase):
    """에이전트 edit → Code 화면 제안 → 사용자가 덩어리를 골라 적용 → 에이전트가 결과를 본다."""

    def setUp(self):
        self.hooks = preserved_hooks()
        self.hooks.__enter__()
        self.addCleanup(self.hooks.__exit__, None, None, None)
        self.iso = isolated_app_dir()
        root = self.iso.__enter__()
        self.addCleanup(self.iso.__exit__, None, None, None)
        self.ws = root / "ws"
        self.ws.mkdir()
        (self.ws / "f.py").write_text(BASE)
        self.bridge = main.Bridge()
        self.addCleanup(self.bridge._mcp.shutdown)
        self.addCleanup(self.bridge._events.stop)
        self.bridge._config["workspace"] = str(self.ws)
        self.events = []
        self.bridge._push = self.events.append
        self.confirms = []
        self.tools = []
        self.stop = threading.Event()

    def agent(self):
        alive = lambda: not self.stop.is_set()  # noqa: E731
        return Agent(api_key="k", workspace=str(self.ws), agent_mode=True, max_steps=1, history_messages=1,
                     on_status=lambda t: None, on_tool=lambda s, d: self.tools.append(s),
                     confirm=lambda kind, title, detail: self.confirms.append(kind) or True,
                     cancelled=lambda: not alive(),
                     review=lambda *a: self.bridge._code_review_edit("t1", alive, *a))

    def run_edit(self, agent, new_text):
        box = {}
        t = threading.Thread(target=lambda: box.setdefault("obs", agent._tool_write("f.py", new_text, "테스트")))
        t.start()
        return t, box

    def wait_proposal(self):
        for _ in range(100):
            pending = self.bridge._code_store().pending()
            if pending:
                return pending[0]
            time.sleep(0.02)
        self.fail("제안이 오지 않았습니다")

    def test_closed_code_pane_uses_the_old_confirm(self):
        obs = self.agent()._tool_write("f.py", changed(BASE, l3="X\n"))
        self.assertEqual(self.confirms, ["edit"])
        self.assertIn("저장 완료", obs)
        self.assertIn("X\n", (self.ws / "f.py").read_text())

    def test_partial_approval_in_the_code_pane(self):
        self.bridge.code_set_active(True)
        t, box = self.run_edit(self.agent(), changed(BASE, l3="LINE three\n", l30="LINE thirty\n"))
        p = self.wait_proposal()
        self.assertEqual((self.ws / "f.py").read_text(), BASE)  # 승인 전에는 파일을 건드리지 않는다
        self.assertEqual(p.reason, "테스트")
        res = self.bridge.code_review_apply(p.proposal_id, [1])
        self.assertTrue(res["ok"], res)
        t.join(5)
        self.assertIn("일부만 적용", box["obs"])
        self.assertIn("1/2", box["obs"])
        text = (self.ws / "f.py").read_text()
        self.assertIn("LINE thirty", text)
        self.assertNotIn("LINE three", text)
        self.assertEqual(self.confirms, [])  # 승인 창은 뜨지 않았다
        self.assertTrue(any(e.get("kind") == "proposal" for e in self.events))

    def test_reject_in_the_code_pane(self):
        self.bridge.code_set_active(True)
        t, box = self.run_edit(self.agent(), changed(BASE, l3="nope\n"))
        p = self.wait_proposal()
        self.assertTrue(self.bridge.code_review_reject(p.proposal_id)["ok"])
        t.join(5)
        self.assertIn("거부", box["obs"])
        self.assertEqual((self.ws / "f.py").read_text(), BASE)

    def test_closing_the_pane_moves_the_request_to_the_confirm_window(self):
        self.bridge.code_set_active(True)
        t, box = self.run_edit(self.agent(), changed(BASE, l3="via modal\n"))
        self.wait_proposal()
        self.assertEqual(self.bridge.code_set_active(False)["moved"], 1)
        t.join(5)
        self.assertEqual(self.confirms, ["edit"])
        self.assertIn("via modal", (self.ws / "f.py").read_text())

    def test_stopping_the_agent_cancels_the_proposal(self):
        self.bridge.code_set_active(True)
        t, box = self.run_edit(self.agent(), changed(BASE, l3="never\n"))
        p = self.wait_proposal()
        self.stop.set()
        t.join(5)
        self.assertEqual(p.status, "cancelled")
        self.assertIn("적용하지 않았습니다", box["obs"])
        self.assertFalse(self.bridge.code_review_apply(p.proposal_id, [0])["ok"])  # 끝난 제안은 적용할 수 없다
        self.assertEqual((self.ws / "f.py").read_text(), BASE)

    def test_auto_edit_permission_applies_and_records(self):
        self.bridge.code_set_active(True)
        self.bridge._config["permission"] = "auto_edit"
        obs = self.agent()._tool_write("f.py", changed(BASE, l3="auto\n"))
        self.assertIn("저장 완료", obs)
        self.assertIn("auto\n", (self.ws / "f.py").read_text())
        self.assertEqual(self.bridge._code_store().all()[0].status, "auto")

    def test_file_changed_while_waiting_for_the_old_confirm_is_not_overwritten(self):
        agent = self.agent()

        def confirm(kind, title, detail):
            (self.ws / "f.py").write_text("someone else saved\n")
            return True
        agent.confirm = confirm
        obs = agent._tool_write("f.py", changed(BASE, l3="late\n"))
        self.assertIn("바뀌어 저장하지 않았습니다", obs)
        self.assertEqual((self.ws / "f.py").read_text(), "someone else saved\n")


if __name__ == "__main__":
    unittest.main()
