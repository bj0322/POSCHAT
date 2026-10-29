# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""대화 검색 색인(thread_index)과 구조 점검: storage.search_threads 결과, 색인 갱신, Bridge 이름 충돌, net 공용 도우미."""
import collections
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import net  # noqa: E402
import office_mcp  # noqa: E402
import storage  # noqa: E402
from support import isolated_app_dir  # noqa: E402


def reference_search(query, exclude_id=None, limit=3, min_score=0.35, min_shared=4):
    """색인을 쓰기 전의 구현(모든 대화 파일을 읽어 점수를 매긴다). 결과가 같은지 비교하는 기준."""
    q = storage._bigrams(query)
    if len(q) < 3:
        return []
    best = {}
    for p in storage.THREADS_DIR.glob("*.json"):
        thread = json.loads(p.read_text(encoding="utf-8"))
        if thread.get("id") == exclude_id:
            continue
        for m in thread.get("messages", []):
            if m.get("role") not in ("user", "assistant"):
                continue
            shared = storage.shared_bigrams(q, m["content"][:6000])
            score = shared / len(q)
            if shared < min_shared or score < min_score:
                continue
            if score > best.get(thread["id"], {}).get("score", 0):
                best[thread["id"]] = {"thread_id": thread["id"], "title": thread.get("title", ""), "role": m["role"],
                                      "content": m["content"], "ts": m.get("ts", 0), "score": round(score, 2)}
    return sorted(best.values(), key=lambda r: r["score"], reverse=True)[:limit]


def make_thread(tid, *texts, title="제목"):
    return {"id": tid, "title": title, "updated": 1,
            "messages": [{"role": ("user", "assistant")[i % 2], "content": t, "ts": i} for i, t in enumerate(texts)]}


class ThreadSearchTests(unittest.TestCase):
    def setUp(self):
        self.ctx = isolated_app_dir()
        self.root = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def save(self, thread):
        storage.save_thread(thread, update_timestamp=False)

    def same_as_reference(self, query, **kw):
        got, want = storage.search_threads(query, **kw), reference_search(query, **kw)
        self.assertEqual(got, want)
        return got

    def test_matches_reference(self):
        self.save(make_thread("a", "양자역학 시험 범위가 어디까지인가요", "시험 범위는 1장부터 5장까지입니다", title="양자"))
        self.save(make_thread("b", "알고리즘 과제에서 최적화 방법을 설명해 주세요", "동적 계획법을 쓰면 됩니다"))
        self.save(make_thread("c", "오늘 점심 메뉴 추천", "김치찌개가 좋겠습니다"))
        for query in ("양자역학 시험 범위", "알고리즘 최적화 과제", "점심 메뉴", "전혀 무관한 내용입니다 abc"):
            for kw in ({}, {"min_score": 0.2, "min_shared": 3}, {"limit": 1}, {"exclude_id": "a"}):
                self.same_as_reference(query, **kw)
        hits = self.same_as_reference("양자역학 시험 범위", min_score=0.2, min_shared=3)
        self.assertEqual(hits[0]["thread_id"], "a")
        self.assertEqual(hits[0]["title"], "양자")

    def test_short_query_returns_nothing(self):
        self.save(make_thread("a", "안녕하세요"))
        self.assertEqual(storage.search_threads("안"), [])

    def test_index_follows_changes(self):
        self.save(make_thread("a", "열역학 제2법칙 엔트로피 증가"))
        self.assertEqual(self.same_as_reference("열역학 엔트로피 법칙", min_score=0.2, min_shared=3)[0]["thread_id"], "a")
        # 대화를 고치면 다시 읽는다
        self.save(make_thread("a", "미적분 적분 공식 정리표 부분적분"))
        self.assertEqual(storage.search_threads("열역학 엔트로피 법칙", min_score=0.2, min_shared=3), [])
        self.assertEqual(self.same_as_reference("미적분 적분 공식 정리표", min_score=0.2, min_shared=3)[0]["thread_id"], "a")
        # 새 대화를 더하고, 지운다
        self.save(make_thread("b", "열역학 엔트로피 법칙 질문"))
        self.assertEqual(self.same_as_reference("열역학 엔트로피 법칙", min_score=0.2, min_shared=3)[0]["thread_id"], "b")
        storage.delete_thread("b")
        self.assertEqual(storage.search_threads("열역학 엔트로피 법칙", min_score=0.2, min_shared=3), [])

    def test_broken_file_is_skipped_and_index_can_be_deleted(self):
        self.save(make_thread("a", "회로 이론 키르히호프 법칙 전압 전류"))
        (storage.THREADS_DIR / "broken.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(storage.search_threads("키르히호프 법칙 전압", min_score=0.2, min_shared=3)[0]["thread_id"], "a")
        (self.root / "thread_index.db").unlink()  # 색인은 지워도 다시 만들어진다
        self.assertEqual(storage.search_threads("키르히호프 법칙 전압", min_score=0.2, min_shared=3)[0]["thread_id"], "a")

    def test_long_message_only_front_is_searched(self):
        self.save(make_thread("a", "가" * 6000 + " 양자역학 시험 범위"))
        self.assertEqual(self.same_as_reference("양자역학 시험 범위", min_score=0.2, min_shared=3), [])


class StructureTests(unittest.TestCase):
    def test_bridge_public_names_are_unique(self):
        """Bridge와 믹스인이 같은 공개 메서드 이름을 정의하면 뒤엣것이 앞엣것을 가린다(화면 API는 모두 한 이름 공간)."""
        import main

        owners = collections.defaultdict(list)
        for cls in main.Bridge.__mro__:
            if cls is object:
                continue
            for name, value in vars(cls).items():
                if not name.startswith("_") and callable(value):
                    owners[name].append(cls.__name__)
        clashes = {n: o for n, o in owners.items() if len(o) > 1}
        self.assertEqual(clashes, {})

    def test_net_helpers_are_shared_with_office_mcp(self):
        self.assertIs(office_mcp.ToolFailure, net.ToolFailure)
        self.assertIs(office_mcp.http, net.http)

    def test_non_mcp_modules_do_not_import_office_mcp(self):
        """sync·rag·telemetry·vector_store·paper·agent는 공용 도우미를 net에서 가져온다(MCP 서버 모듈에 기대지 않는다)."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        for name in ("sync", "rag", "telemetry", "vector_store", "paper", "agent", "web_research", "workspace_api"):
            text = (root / f"{name}.py").read_text(encoding="utf-8")
            self.assertNotIn("from office_mcp import", text, name)


if __name__ == "__main__":
    unittest.main()
