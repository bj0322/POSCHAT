import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # support.py

import connectors
import handoff
import memory_mcp
import memory_store
import office_mcp
import po_note
import research_library as lib
import storage
import sync
from agent import Agent
from support import isolated_app_dir


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()

    def tearDown(self):
        self._dir.__exit__(None, None, None)

    def test_write_dedupes_and_merges_tags(self):
        a, created = memory_store.write("API 응답은  JSON으로 통일한다", project="ws/app", kind="decision", tags=["api"])
        self.assertTrue(created)
        b, created = memory_store.write("api 응답은 json으로 통일한다", project="ws/app", tags=["style"])
        self.assertFalse(created)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(b["tags"], ["api", "style"])
        self.assertEqual(b["kind"], "decision")
        # 다른 프로젝트에서는 다른 기억
        _, created = memory_store.write("API 응답은 JSON으로 통일한다", project="ws/other")
        self.assertTrue(created)
        with self.assertRaises(memory_store.MemoryStoreError):
            memory_store.write("x", layer="global")  # memory.md는 직접 고친다

    def test_search_mixes_layers_and_respects_projects(self):
        memory_store.write("결제 모듈은 재시도 3회 후 실패 처리", project="ws/shop", kind="decision")
        memory_store.write("결제 모듈 리팩터링 TODO", project="ws/blog", kind="todo")
        memory_store.write("학습률 0.001에서 손실 수렴", layer="research", project="ws/shop", kind="result")
        storage.add_memory("결제 관련 답변은 표로 정리")
        hits = memory_store.search("결제 모듈 재시도", project="ws/shop")
        texts = [h["text"] for h in hits]
        self.assertIn("결제 모듈은 재시도 3회 후 실패 처리", texts)
        self.assertNotIn("결제 모듈 리팩터링 TODO", texts)
        self.assertIn("결제 관련 답변은 표로 정리", [h["text"] for h in memory_store.search("결제 관련 답변", project="ws/shop")])  # memory.md도
        self.assertEqual(memory_store.search("손실 수렴", layers=["research"], project="ws/shop")[0]["layer"], "research")

    def test_delete_leaves_a_tombstone_and_external_entries_are_marked(self):
        e, _ = memory_store.write("남이 쓴 기억", project="p", source="external:claude-code")
        self.assertIn("다른 AI가 쓴 기억", memory_store.format_hits(memory_store.search("남이 쓴 기억", project="p")))
        self.assertIn("다른 AI", memory_store.project_context("p"))
        memory_store.delete(e["id"])
        self.assertFalse(memory_store.search("남이 쓴 기억", project="p"))
        self.assertTrue(memory_store.entries(include_deleted=True)[0]["deleted"])

    def test_upsert_raw_keeps_the_fts_index_consistent(self):
        e, _ = memory_store.write("원래 문장 alpha", project="p")
        memory_store.upsert_raw(dict(e, text="바뀐 문장 omega", updated=e["updated"] + 1))
        self.assertFalse([h for h in memory_store.search("원래 문장 alpha", project="p", include_threads=False)
                          if h["key"].startswith("entry:")])
        self.assertTrue(memory_store.search("바뀐 문장 omega", project="p"))


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self._dir.__enter__()

    def tearDown(self):
        self._dir.__exit__(None, None, None)

    def test_same_key_updates_the_open_handoff(self):
        a, created = handoff.create("로그인 버그 고치기", project="p", idempotency_key="k1", files_changed=["a.py"],
                                    tests=[{"command": "pytest", "passed": False}])
        self.assertTrue(created)
        b, created = handoff.create("로그인 버그 고치기", project="p", idempotency_key="k1", files_changed=["b.py", "a.py"],
                                    next_steps=["회귀 테스트"])
        self.assertFalse(created)
        self.assertEqual(a["task_id"], b["task_id"])
        self.assertEqual(b["files_changed"], ["a.py", "b.py"])
        self.assertEqual(b["next_steps"], ["회귀 테스트"])
        handoff.accept("codex", task_id=a["task_id"])
        c, created = handoff.create("로그인 버그 고치기", project="p", idempotency_key="k1")
        self.assertTrue(created)  # 받아 간 인계는 닫혔으니 새 인계
        self.assertNotEqual(c["task_id"], a["task_id"])

    def test_only_one_agent_can_accept(self):
        rec, _ = handoff.create("작업", project="p")
        results, barrier = [], threading.Barrier(8)

        def take(i):
            barrier.wait()
            results.append(handoff.accept(f"agent{i}", project="p"))

        threads = [threading.Thread(target=take, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners = [r for r in results if r]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["task_id"], rec["task_id"])
        done = handoff.complete(rec["task_id"], "끝")
        self.assertEqual(handoff.complete(rec["task_id"], "다시")["result"], "끝")  # 다시 불러도 같다
        self.assertEqual(done["status"], "completed")

    def test_sync_never_moves_a_handoff_back(self):
        rec, _ = handoff.create("작업", project="p")
        handoff.complete(rec["task_id"])
        self.assertFalse(handoff.upsert_raw(dict(rec, status="open", updated=rec["updated"] + 100)))
        self.assertEqual(handoff.get(rec["task_id"])["status"], "completed")

    def test_ai_memory_mapping(self):
        rec, _ = handoff.create("작업", summary="요약", files_changed=["x.py"], todo=["문서"], next_steps=["배포"],
                                tests=[{"command": "pytest", "passed": True}])
        mapped = handoff.to_ai_memory(rec)
        self.assertIn("pytest: 통과", mapped["summary"])
        self.assertEqual(mapped["next_steps"], ["배포", "문서"])
        self.assertEqual(mapped["files_touched"], ["x.py"])


class MemoryServerTests(unittest.TestCase):
    def test_external_clients_are_tagged_and_project_comes_from_the_folder(self):
        with isolated_app_dir() as root:
            ws = root / "myrepo"
            ws.mkdir()
            with patch.object(office_mcp, "ROOT", ws), patch.object(office_mcp, "CLIENT_INFO", {"name": "claude-code"}):
                memory_mcp.memory_write("배포는 금요일에 하지 않는다", kind="decision")
                out = memory_mcp.project_context()
                memory_mcp.handoff_create("API 문서 정리", files_changed=["docs/api.md"])
                taken = memory_mcp.handoff_accept()
            self.assertIn("default/myrepo", out)
            entry = memory_store.entries(layer="project")[0]
            self.assertEqual((entry["project"], entry["source"]), ("default/myrepo", "external:claude-code"))
            self.assertIn("API 문서 정리", taken)
            self.assertEqual(handoff.list_handoffs(status="accepted")[0]["accepted_by"], "claude-code")


class AgentMemoryHubTests(unittest.TestCase):
    def test_project_memory_goes_into_the_prompt_and_runs_leave_a_handoff(self):
        with isolated_app_dir() as root:
            ws = root / "proj"
            ws.mkdir()
            memory_store.write("DB는 PostgreSQL로 결정", project="default/proj", kind="decision")
            tools = []
            agent = Agent("k", str(ws), True, 5, 5, on_status=lambda *a: None,
                          on_tool=lambda summary, detail: tools.append(summary), confirm=lambda *a: True,
                          cancelled=lambda: False, thread_id="t" * 32,
                          policy=connectors.Policy({"features": {"memory_hub": True}}))
            agent._prepare_context("DB 마이그레이션 계획")
            self.assertTrue(any("PostgreSQL" in b for b in agent.context_blocks))
            agent._touched.add("db.sql")
            agent.tools_run.append("run: pytest -q")
            agent.commands.append({"command": "python -m pytest -q", "code": 1})
            agent.denied.append("명령 실행: rm -rf build")
            agent._record_handoff("DB 마이그레이션", "마이그레이션 스크립트를 만들었습니다.", "")
            rec = handoff.list_handoffs(project="default/proj")[0]
            self.assertEqual(rec["files_changed"], ["db.sql"])
            self.assertEqual(rec["tests"][0]["passed"], False)
            self.assertEqual(rec["approvals_needed"], ["명령 실행: rm -rf build"])
            # 같은 대화에서 다시 실행하면 같은 인계를 갱신한다
            agent._touched.add("db2.sql")
            agent._record_handoff("DB 마이그레이션", "더 고쳤습니다.", "")
            self.assertEqual(len(handoff.list_handoffs(project="default/proj")), 1)

    def test_without_the_feature_nothing_changes(self):
        with isolated_app_dir() as root:
            memory_store.write("숨은 기억", project="default/x")
            (root / "x").mkdir()
            agent = Agent("k", str(root / "x"), True, 5, 5, on_status=lambda *a: None, on_tool=lambda *a: None,
                          confirm=lambda *a: True, cancelled=lambda: False)
            agent._prepare_context("숨은 기억")
            self.assertFalse(any("숨은 기억" in b for b in agent.context_blocks))


class Device:
    """한 기기: 자기 데이터 폴더와 설정. 같은 공유 폴더로 동기화한다."""

    def __init__(self, shared, name):
        self.shared, self.name = shared, name
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {"sync": {"enabled": True, "backend": "folder", "folder": str(shared)}}
        self.root = Path(self.tmp.name)

    def __enter__(self):
        self.ctx = isolated_app_dir(self.root)
        self.ctx.__enter__()
        storage.THREADS_DIR.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc):
        self.ctx.__exit__(*exc)

    def setup(self, passphrase="correct horse battery"):
        key = sync.setup(sync.FolderBackend(str(self.shared)), passphrase)
        sync.save_key(key)

    def sync(self):
        def on_settings(values, stamp):
            self.config.update(values)
            self.config["settings_updated"] = stamp

        return sync.sync_once(self.config, device=self.name, device_name=self.name, on_settings=on_settings)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shared = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # 두 기기를 오가며 테스트하므로 동기화 상태(sync_state.json)도 기기별 폴더에 둔다(isolated_app_dir)

    def run_on(self, device, fn):
        with device:
            return fn(device)

    def test_crypto_and_names_hide_contents(self):
        with self.assertRaises(sync.SyncError):
            sync.derive_key("short", b"0" * 16)
        key = sync.derive_key("long enough pass", b"s" * 16)
        c = sync.Cipher(key)
        blob = c.encrypt({"secret": "비밀 메시지"})
        self.assertEqual(c.decrypt(blob), {"secret": "비밀 메시지"})
        with self.assertRaises(sync.SyncError):
            c.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]))
        with self.assertRaises(sync.SyncError):
            sync.Cipher(sync.derive_key("another pass!!", b"s" * 16)).decrypt(blob)
        self.assertRegex(c.name("thread:abc"), r"^[0-9a-f]{40}$")

    def test_two_devices_share_data_merge_edits_and_propagate_deletes(self):
        a, b = Device(self.shared, "pc"), Device(self.shared, "phone")
        thread_id = {}

        def a_first(d):
            d.setup()
            t = storage.new_thread()
            t["title"] = "여행 계획"
            t["messages"].append(storage.make_message("user", "안녕 A"))
            storage.save_thread(t)
            thread_id["id"] = t["id"]
            storage.save_memory_md(storage.MEMORY_TEMPLATE + "- 공통 기억\n")
            storage.save_profile("# 사용자 정보\n- 포스텍 학생\n")
            memory_store.write("API는 REST로", project="default/app", kind="decision")
            lib.add({"title": "Attention Is All You Need", "arxiv": "1706.03762"})
            d.config.update(history_messages=33, settings_updated=1000.0, api_key="must-not-sync")
            report = d.sync()
            self.assertEqual(report["errors"], [])
            self.assertGreaterEqual(report["uploaded"], 6)

        self.run_on(a, a_first)
        # 원격에는 평문이 없다
        blobs = b"".join(p.read_bytes() for p in (self.shared / "poschat-sync" / "objects").iterdir())
        for plain in ("안녕 A".encode(), b"REST", b"Attention", b"must-not-sync", "포스텍".encode()):
            self.assertNotIn(plain, blobs)
        self.assertNotIn("api_key", json.dumps(json.loads((self.shared / "poschat-sync" / "meta.json").read_text())))

        def b_first(d):
            with self.assertRaises(sync.SyncError):
                sync.setup(sync.FolderBackend(str(self.shared)), "wrong passphrase")
            d.setup()
            report = d.sync()
            self.assertEqual(report["errors"], [])
            t = storage.load_thread(thread_id["id"])
            self.assertEqual(t["messages"][0]["content"], "안녕 A")
            self.assertIn("- 공통 기억", storage.read_memory_md())
            self.assertIn("포스텍 학생", storage.read_profile())
            self.assertEqual(memory_store.entries(layer="project")[0]["text"], "API는 REST로")
            self.assertEqual(lib.find("1706.03762")["title"], "Attention Is All You Need")
            self.assertEqual(d.config["history_messages"], 33)
            self.assertNotIn("api_key", d.config)
            self.assertEqual({x["id"] for x in report["devices"]}, {"pc", "phone"})
            # B에서 동시에 고친다: 메시지·기억 추가, 공통 기억 지우기
            t["messages"].append(storage.make_message("assistant", "B의 답"))
            storage.save_thread(t)
            storage.save_memory_md(storage.read_memory_md().replace("- 공통 기억\n", "") + "- B 기억\n")

        self.run_on(b, b_first)

        def a_second(d):
            # B는 고친 뒤 아직 동기화하지 않았다(오프라인). A도 따로 고치고 먼저 동기화한다.
            t = storage.load_thread(thread_id["id"])
            t["messages"].append(storage.make_message("user", "A의 질문"))
            storage.save_thread(t)
            storage.save_memory_md(storage.read_memory_md() + "- A 기억\n")
            report = d.sync()
            self.assertEqual((report["merged"], report["errors"]), (0, []))

        self.run_on(a, a_second)

        def b_second(d):
            report = d.sync()  # 양쪽이 모두 바뀐 대화와 memory.md를 합친다
            self.assertEqual(report["merged"], 2, report)
            merged = storage.load_thread(thread_id["id"])
            self.assertEqual([m["content"] for m in merged["messages"]], ["안녕 A", "B의 답", "A의 질문"])
            memory = storage.read_memory_md()
            self.assertIn("- A 기억", memory)
            self.assertIn("- B 기억", memory)
            self.assertNotIn("- 공통 기억", memory)  # B가 지운 줄은 지워진 채로

        self.run_on(b, b_second)

        def a_third(d):
            d.sync()
            self.assertEqual(len(storage.load_thread(thread_id["id"])["messages"]), 3)
            self.assertIn("- B 기억", storage.read_memory_md())
            self.assertNotIn("- 공통 기억", storage.read_memory_md())

        self.run_on(a, a_third)

        def b_third(d):
            storage.delete_thread(thread_id["id"])  # B에서 대화와 기억을 지운다
            memory_store.delete(memory_store.entries(layer="project")[0]["id"])
            report = d.sync()
            self.assertEqual(report["errors"], [])

        self.run_on(b, b_third)

        def a_fourth(d):
            report = d.sync()
            self.assertIsNone(storage.load_thread(thread_id["id"]))
            self.assertEqual(memory_store.entries(layer="project"), [])
            self.assertGreaterEqual(report["deleted"], 1)

        self.run_on(a, a_fourth)

    def test_profile_conflicts_keep_both_versions(self):
        a, b = Device(self.shared, "pc"), Device(self.shared, "phone")
        self.run_on(a, lambda d: (d.setup(), storage.save_profile("# 나\n- 처음\n"), d.sync()))
        self.run_on(b, lambda d: (d.setup(), d.sync(), storage.save_profile("# 나\n- 휴대폰에서 고침\n")))

        def a_edit(d):
            storage.save_profile("# 나\n- PC에서 고침\n")
            os.utime(storage.PROFILE_PATH, (1, 1))  # PC 쪽을 더 오래전에 고친 것으로
            d.sync()

        self.run_on(a, a_edit)

        def b_merge(d):
            report = d.sync()
            self.assertEqual(len(report["conflicts"]), 1)
            self.assertIn("휴대폰에서 고침", storage.read_profile())  # 더 늦게 고친 쪽(휴대폰)이 남는다
            self.assertIn("PC에서 고침", Path(report["conflicts"][0]).read_text(encoding="utf-8"))

        self.run_on(b, b_merge)

    def test_conflict_copies_made_by_sync_clients_are_merged(self):
        a, b = Device(self.shared, "pc"), Device(self.shared, "phone")
        thread_id = {}

        def a_first(d):
            d.setup()
            t = storage.new_thread()
            t["messages"].append(storage.make_message("user", "원본"))
            storage.save_thread(t)
            thread_id["id"] = t["id"]
            d.sync()

        self.run_on(a, a_first)
        objects = self.shared / "poschat-sync" / "objects"

        def b_copy(d):
            # 다른 기기가 오프라인일 때 쓴 내용을 Dropbox가 "이름 (1).bin"으로 남긴 상황을 만든다
            d.setup()
            d.sync()
            key = sync.load_key()
            cipher = sync.Cipher(key)
            name = cipher.name(f"thread:{thread_id['id']}")
            t = storage.load_thread(thread_id["id"])
            t["messages"].append(storage.make_message("assistant", "충돌 사본의 답"))
            t["updated"] += 50
            env = {"key": f"thread:{thread_id['id']}", "kind": "thread", "id": t["id"], "updated": t["updated"],
                   "deleted": None, "data": t, "device": "phone"}
            (objects / f"{name} (1).bin").write_bytes(cipher.encrypt(env))

        self.run_on(b, b_copy)

        def a_merge(d):
            report = d.sync()
            self.assertEqual(report["errors"], [])
            contents = [m["content"] for m in storage.load_thread(thread_id["id"])["messages"]]
            self.assertEqual(contents, ["원본", "충돌 사본의 답"])
            self.assertFalse(list(objects.glob("* (1).bin")))

        self.run_on(a, a_merge)

    def test_excluded_kinds_stay_local_and_wipe_removes_everything_remote(self):
        a = Device(self.shared, "pc")

        def run(d):
            d.setup()
            d.config["sync"]["include"] = {"threads": False}
            t = storage.new_thread()
            t["messages"].append(storage.make_message("user", "로컬에만"))
            storage.save_thread(t)
            d.sync()
            cipher = sync.Cipher(sync.load_key())
            self.assertFalse((self.shared / "poschat-sync" / "objects" / (cipher.name(f"thread:{t['id']}") + ".bin")).exists())
            sync.wipe(sync.FolderBackend(str(self.shared)))
            self.assertFalse((self.shared / "poschat-sync").exists())
            self.assertIsNone(sync.load_key())
            self.assertIsNotNone(storage.load_thread(t["id"]))  # 로컬 데이터는 남는다

        self.run_on(a, run)

    def test_po_notes_sync_text_but_not_material_files(self):
        a, b = Device(self.shared, "pc"), Device(self.shared, "phone")
        note_id = {}

        def a_first(d):
            d.setup()
            note = po_note.create("선형대수 3주차")
            note_id["id"] = note["id"]
            po_note.save_note(note["id"], "# 고유값\n- 정의")
            po_note.upload_material(note["id"], "a" * 32, "slides.md", 0, base64.b64encode(b"# slides").decode(), True)
            d.sync()

        self.run_on(a, a_first)

        def b_check(d):
            d.setup()
            d.sync()
            loaded = po_note.load(note_id["id"])
            self.assertEqual(loaded["title"], "선형대수 3주차")
            self.assertIn("고유값", loaded["note"])
            self.assertEqual(loaded.get("materials", []), [])

        self.run_on(b, b_check)


if __name__ == "__main__":
    unittest.main()
