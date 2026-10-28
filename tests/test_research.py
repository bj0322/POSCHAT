# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # support.py

import net
import office_mcp
import paper_mcp
import rag
import research_library as lib
import research_mcp
import secret_store
import storage
import vector_store
from office_mcp import ToolFailure
from support import FakeHttp, FakeResponse, isolated_app_dir


def make_pdf(path, pages, title=None):
    """글자가 든 아주 작은 PDF(Helvetica, 한 줄씩)를 만든다. pypdf가 글자를 뽑을 수 있다."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        ops = ["BT /F1 11 Tf 14 TL 72 760 Td"]
        for line in lines:
            ops.append("(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        content_no = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_no} 0 R "
                       f"/Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(len(objects))
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    if title:
        objects.append(f"<< /Title ({title}) >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        body = obj if isinstance(obj, bytes) else obj.encode("latin-1")
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R" + (f" /Info {len(objects)} 0 R" if title else "") + " >>"
    out += f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).write_bytes(bytes(out))


ATTENTION_PDF = [
    ["Attention Is All You Need", "Ashish Vaswani, Noam Shazeer", "arXiv:1706.03762v5", "Abstract",
     "The dominant sequence transduction models are based on recurrent networks."],
    ["1 Introduction", "Recurrent neural networks have been firmly established.", "2 Background",
     "Self-attention relates different positions of a single sequence."],
    ["3 Model Architecture", "The Transformer uses stacked self-attention and point-wise layers.",
     "3.1 Scaled Dot-Product Attention", "We compute the dot products of the query with all keys and apply softmax."],
]


class MergeTests(unittest.TestCase):
    def test_records_merge_by_doi_arxiv_and_title(self):
        a = paper_mcp._record(title="Attention Is All You Need", arxiv="1706.03762v5", year="2017", sources=["arXiv"])
        b = paper_mcp._record(title="Attention is all you need", doi="10.48550/arXiv.1706.03762", citations=100,
                              sources=["Semantic Scholar"])
        c = paper_mcp._record(title="Attention Is All You Need.", venue="NeurIPS", citations=150, sources=["OpenAlex"])
        d = paper_mcp._record(title="BERT", doi="https://doi.org/10.18653/V1/N19-1423", sources=["Crossref"])
        e = paper_mcp._record(title="BERT: Pre-training", doi="10.18653/v1/n19-1423", citations=9, sources=["OpenAlex"])
        merged = paper_mcp.merge_records([a, b, c, d, e])
        self.assertEqual(len(merged), 2)
        first = merged[0]
        self.assertEqual(first["arxiv"], "1706.03762")
        self.assertEqual(first["venue"], "NeurIPS")
        self.assertEqual(first["citations"], 150)
        self.assertEqual(first["sources"], ["arXiv", "Semantic Scholar", "OpenAlex"])
        self.assertEqual(merged[1]["doi"], "10.18653/v1/n19-1423")
        self.assertEqual(merged[1]["citations"], 9)

    def test_openalex_abstract_is_rebuilt(self):
        self.assertEqual(paper_mcp._openalex_abstract({"world": [1], "hello": [0], "again": [2]}), "hello world again")

    def test_search_all_combines_sources_and_reports_failures(self):
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>'
                '<id>http://arxiv.org/abs/1706.03762v5</id><title>Attention Is All You Need</title>'
                '<author><name>Ashish Vaswani</name></author><published>2017-06-12</published>'
                '<updated>2017-12-06</updated><summary>Transformer.</summary>'
                '<arxiv:primary_category term="cs.CL"/></entry></feed>')
        fake = FakeHttp([
            ("GET", "export.arxiv.org", FakeResponse(text=atom)),
            ("GET", "semanticscholar.org/graph/v1/paper/search", FakeResponse(429, {})),
            ("GET", "api.crossref.org", FakeResponse(data={"message": {"items": [{
                "DOI": "10.5555/3295222.3295349", "title": ["Attention is all you need"],
                "author": [{"given": "Ashish", "family": "Vaswani"}], "issued": {"date-parts": [[2017]]},
                "container-title": ["NeurIPS"], "is-referenced-by-count": 1000}]}})),
            ("GET", "api.openalex.org", FakeResponse(data={"results": [{
                "title": "Attention Is All You Need", "publication_year": 2017, "cited_by_count": 120000,
                "doi": "https://doi.org/10.5555/3295222.3295349", "authorships": [],
                "locations": [{"landing_page_url": "https://arxiv.org/abs/1706.03762"}]}]})),
        ])
        with patch.object(paper_mcp, "http", fake), patch.object(paper_mcp.time, "sleep"):
            text = paper_mcp.search("attention is all you need", limit=3, source="all")
        self.assertIn("1편", text)
        self.assertIn("DOI: 10.5555/3295222.3295349", text)
        self.assertIn("arXiv: 1706.03762", text)
        self.assertIn("인용 120000회", text)
        self.assertIn("출처: arXiv, Crossref, OpenAlex", text)
        self.assertIn("Semantic Scholar", text.split("일부 출처는 실패했습니다")[1])


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()

    def tearDown(self):
        self._dir.__exit__(None, None, None)

    def test_add_merges_the_same_paper_and_remove_leaves_a_tombstone(self):
        p, created = lib.add({"title": "Attention Is All You Need", "arxiv": "1706.03762v5", "tags": "nlp, transformer"})
        self.assertTrue(created)
        self.assertEqual(p["tags"], ["nlp", "transformer"])
        again, created = lib.add({"title": "attention is all you need", "arxiv": "1706.03762", "venue": "NeurIPS",
                                  "tags": ["classic"]})
        self.assertFalse(created)
        self.assertEqual(again["id"], p["id"])
        self.assertEqual(again["venue"], "NeurIPS")
        self.assertEqual(again["tags"], ["classic", "nlp", "transformer"])
        self.assertEqual(lib.find("1706.03762")["id"], p["id"])
        self.assertEqual(lib.find("attention is all")["id"], p["id"])
        lib.update(p["id"], notes="읽음", tags=[])
        self.assertEqual(lib.get(p["id"])["tags"], [])
        lib.remove(p["id"])
        self.assertIn(p["id"], lib.load()["deleted"])
        with self.assertRaises(lib.LibraryError):
            lib.get(p["id"])

    def test_bibtex_escapes_and_keeps_keys_unique(self):
        papers = [lib.add({"title": "Deep Learning & Friends_2", "authors": ["Yann LeCun", "Yoshua Bengio"], "year": 2015,
                           "venue": "Nature", "doi": "10.1038/nature14539"})[0],
                  lib.add({"title": "Deep Learning again", "authors": ["Yann LeCun"], "year": 2015, "arxiv": "1501.00001"})[0]]
        text = lib.to_bibtex(papers)
        self.assertIn("@article{lecun2015deep,", text)
        self.assertIn("@misc{lecun2015deepa,", text)  # 같은 키가 있으면 a, b, …를 붙인다
        self.assertIn(r"Deep Learning \& Friends\_2", text)
        self.assertIn("author = {Yann LeCun and Yoshua Bengio}", text)
        self.assertIn("eprint = {1501.00001}", text)

    def test_pdf_metadata(self):
        path = self.root / "paper.pdf"
        make_pdf(path, ATTENTION_PDF, title="Attention Is All You Need")
        meta = lib.pdf_metadata(path)
        self.assertEqual(meta["title"], "Attention Is All You Need")
        self.assertEqual(meta["arxiv"], "1706.03762")


class RagTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()
        self.ws = self.root / "ws"
        self.ws.mkdir()
        make_pdf(self.ws / "attention.pdf", ATTENTION_PDF)
        (self.ws / "notes.md").write_text("# 실험 기록\n어텐션은 쿼리와 키의 내적으로 가중치를 구한다.\n\n# 다음 할 일\n학습률 조정\n",
                                          encoding="utf-8")
        self.coll = rag.workspace_collection(self.ws)

    def tearDown(self):
        self._dir.__exit__(None, None, None)

    def test_index_search_cite_and_update(self):
        summary = rag.index_folder(self.ws, self.coll)
        self.assertEqual((summary["indexed"], summary["failed"]), (2, []))
        self.assertEqual(rag.index_folder(self.ws, self.coll)["unchanged"], 2)
        results = rag.search("dot products query keys softmax", [self.coll])
        self.assertTrue(results)
        top = results[0]
        self.assertIn("dot products", top["text"])
        self.assertEqual(top["page_start"], 3)
        self.assertEqual(top["section"], "3.1 Scaled Dot-Product Attention")
        self.assertIn("[1] 원문 · attention.pdf p.3 §3.1 Scaled Dot-Product Attention", rag.format_results(results, self.ws))
        self.assertIn("해설", rag.format_results(results, self.ws))
        # 한국어: 조사가 붙은 낱말도 찾는다(trigram 또는 2-gram)
        ko = rag.search("어텐션 내적", [self.coll])
        self.assertTrue(ko and ko[0]["section"] == "실험 기록", ko)
        # 바뀐 파일만 다시, 사라진 파일은 지운다
        (self.ws / "notes.md").write_text("# 실험 기록\n배치 크기 64로 바꿈\n", encoding="utf-8")
        (self.ws / "attention.pdf").unlink()
        summary = rag.index_folder(self.ws, self.coll)
        self.assertEqual((summary["indexed"], summary["removed"]), (1, 1))
        self.assertFalse(rag.search("softmax", [self.coll]))
        self.assertTrue(rag.search("배치 크기", [self.coll]))

    def test_other_workspaces_are_not_searched(self):
        rag.index_folder(self.ws, self.coll)
        other = self.root / "other"
        other.mkdir()
        (other / "secret.md").write_text("# 비밀 프로젝트\nsoftmax temperature secret plan\n", encoding="utf-8")
        rag.index_folder(other, rag.workspace_collection(other))
        hits = rag.search("secret plan softmax", [self.coll, "library"])
        self.assertTrue(all("secret.md" not in h["path"] for h in hits))
        with self.assertRaises(rag.RagError):
            rag.index_folder(self.ws, self.coll, paths=["../other/secret.md"])

    def test_without_fts5_the_bigram_fallback_works(self):
        def no_fts(con):
            con.execute("INSERT INTO meta VALUES ('fts', 'none')")
            con.commit()

        with patch.object(rag, "_create_fts", no_fts):
            rag.index_folder(self.ws, self.coll)
            self.assertEqual(rag.fts_mode(), "none")
            hits = rag.search("Scaled Dot-Product Attention softmax", [self.coll])
        self.assertTrue(hits)
        self.assertEqual(hits[0]["page_start"], 3)

    def test_vector_hits_are_fused(self):
        rag.index_folder(self.ws, self.coll)
        with rag._db() as con:
            target = con.execute("SELECT id FROM chunks WHERE text LIKE '%학습률%'").fetchone()["id"]

        class FakeVectors:
            def search(self, query, collections, limit):
                return [{"chunk_id": target, "score": 0.9}]

        hits = rag.search("learning rate schedule", [self.coll], vectors=FakeVectors())
        self.assertIn(target, [h["chunk_id"] for h in hits])


class VectorStoreTests(unittest.TestCase):
    def test_qdrant_points_and_filters(self):
        fake = FakeHttp([
            ("POST", "/embeddings", lambda call: FakeResponse(data={"data": [
                {"index": i, "embedding": [float(i), 1.0]} for i in range(len(call["json"]["input"]))]})),
            ("GET", "/collections/poschat", FakeResponse(404, {})),
            ("PUT", "/collections/poschat/index", FakeResponse(data={})),
            ("PUT", "/collections/poschat/points", FakeResponse(data={})),
            ("PUT", "/collections/poschat", FakeResponse(data={})),
            ("POST", "/points/delete", FakeResponse(data={})),
            ("POST", "/points/search", FakeResponse(data={"result": [{"payload": {"chunk_id": 7}, "score": 0.5}]})),
        ])
        index = vector_store.VectorIndex(vector_store.Embedder("https://emb.example/v1/embeddings", "m", "k"),
                                         vector_store.Qdrant("http://127.0.0.1:6333", "poschat"))
        with patch.object(net, "http", fake):
            index.replace_document("doc1", [(7, "doc1", "ws:x", "가"), (8, "doc1", "ws:x", "나")])
            hits = index.search("질문", ["ws:x", "library"], 5)
        self.assertEqual(hits, [{"chunk_id": 7, "score": 0.5}])
        upsert = next(c for c in fake.calls if c["method"] == "PUT" and "/points" in c["url"])
        points = upsert["json"]["points"]
        self.assertEqual([p["payload"]["chunk_id"] for p in points], [7, 8])
        self.assertEqual(len(points[0]["id"]), 36)  # UUID
        search = fake.calls[-1]["json"]
        self.assertEqual(search["filter"]["must"][0], {"key": "collection", "match": {"any": ["ws:x", "library"]}})
        embed = next(c for c in fake.calls if c["url"].endswith("/embeddings"))
        self.assertEqual(embed["headers"]["Authorization"], "Bearer k")

    def test_from_config_needs_every_setting(self):
        self.assertIsNone(vector_store.from_config({"vector": {"enabled": True, "qdrant_url": "http://127.0.0.1:6333"}}))
        self.assertIsNone(vector_store.from_config({}))


class ResearchServerTests(unittest.TestCase):
    def setUp(self):
        self._dir = isolated_app_dir()
        self.root = self._dir.__enter__()
        self.ws = self.root / "ws"
        self.ws.mkdir()
        self.rootp = patch.object(office_mcp, "ROOT", self.ws)
        self.rootp.start()

    def tearDown(self):
        self.rootp.stop()
        self._dir.__exit__(None, None, None)

    def with_http(self, routes):
        fake = FakeHttp(routes)
        stack = [patch.object(paper_mcp, "http", fake), patch.object(research_mcp, "http", fake),
                 patch.object(research_mcp.time, "sleep"), patch.object(paper_mcp.time, "sleep")]
        for p in stack:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(stack)])
        return fake

    def test_library_add_by_arxiv_id_and_export(self):
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>'
                '<id>http://arxiv.org/abs/1706.03762v5</id><title>Attention Is All You Need</title>'
                '<author><name>Ashish Vaswani</name></author><published>2017-06-12</published>'
                '<updated>2017-12-06</updated><summary>Transformer.</summary></entry></feed>')
        self.with_http([("GET", "export.arxiv.org", FakeResponse(text=atom)),
                        ("GET", "semanticscholar.org", FakeResponse(data={"citationCount": 5, "venue": "NeurIPS"}))])
        text = research_mcp.library_add(paper="1706.03762", tags=["nlp"])
        self.assertIn("더했습니다", text)
        record = lib.find("1706.03762")
        self.assertEqual((record["venue"], record["citations"], record["tags"]), ("NeurIPS", 5, ["nlp"]))
        self.assertIn("refs.bib", research_mcp.export_bibtex(path="refs.bib"))
        self.assertIn("Vaswani", (self.ws / "refs.bib").read_text())
        with self.assertRaises(ToolFailure):
            research_mcp.export_bibtex(path="../outside.bib")

    def test_index_and_search_documents_tools(self):
        make_pdf(self.ws / "attention.pdf", ATTENTION_PDF)
        self.assertIn("새로 1개", research_mcp.index_documents())
        out = research_mcp.search_documents("softmax keys")
        self.assertIn("attention.pdf p.3", out)
        self.assertIn("attention.pdf", research_mcp.index_status())

    def test_zotero_import_is_incremental_and_add_uses_a_write_token(self):
        secret_store.set("connector:zotero:api_key", "zkey")
        item = {"key": "ABCD1234", "version": 12, "data": {
            "title": "Attention Is All You Need", "creators": [{"firstName": "Ashish", "lastName": "Vaswani"}],
            "date": "2017-06-12", "DOI": "10.5555/3295222.3295349", "tags": [{"tag": "nlp"}], "collections": ["C1"],
            "url": ""}}
        fake = self.with_http([
            ("GET", "/keys/current", FakeResponse(data={"userID": 42, "username": "kim"})),
            ("GET", "/users/42/collections", FakeResponse(data=[{"key": "C1", "data": {"name": "읽을 논문"}}])),
            ("GET", "/users/42/items/top", FakeResponse(data=[item], headers={"Last-Modified-Version": "12"})),
            ("POST", "/users/42/items", FakeResponse(data={"successful": {"0": {"key": "NEW1", "version": 13}}})),
        ])
        self.assertIn("새로 1편", research_mcp.zotero_import())
        record = lib.find("10.5555/3295222.3295349")
        self.assertEqual((record["zotero_key"], record["collections"], record["tags"]), ("ABCD1234", ["읽을 논문"], ["nlp"]))
        research_mcp.zotero_import()
        items_calls = [c for c in fake.calls if "/items/top" in c["url"]]
        self.assertEqual(items_calls[0]["params"]["since"], 0)
        self.assertEqual(items_calls[1]["params"]["since"], 12)
        self.assertEqual(items_calls[0]["headers"]["Zotero-API-Key"], "zkey")
        mine, _ = lib.add({"title": "My Preprint", "arxiv": "2401.00001", "authors": ["Kim Bum"]})
        self.assertIn("NEW1", research_mcp.zotero_add(mine["id"]))
        post = [c for c in fake.calls if c["method"] == "POST"][-1]
        self.assertEqual(len(post["headers"]["Zotero-Write-Token"]), 32)
        self.assertEqual(post["json"][0]["itemType"], "preprint")
        self.assertEqual(lib.get(mine["id"])["zotero_key"], "NEW1")

    def test_citation_graph_links_library_papers(self):
        a, _ = lib.add({"title": "Paper A", "doi": "10.1/a"})
        b, _ = lib.add({"title": "Paper B", "doi": "10.1/b"})
        c, _ = lib.add({"title": "Paper C", "arxiv": "2001.00001"})
        refs = {"DOI:10.1/a": [{"citedPaper": {"title": "Paper B", "externalIds": {"DOI": "10.1/B"}}},
                               {"citedPaper": {"title": "Shared Classic", "externalIds": {}}}],
                "DOI:10.1/b": [{"citedPaper": {"title": "Shared Classic", "externalIds": {}}}],
                "arXiv:2001.00001": [{"citedPaper": {"title": "Paper A", "externalIds": {}}}]}

        def route(call):
            key = call["url"].split("/paper/")[1].rsplit("/references", 1)[0]
            return FakeResponse(data={"data": refs[key]})

        self.with_http([("GET", "/references", route)])
        out = research_mcp.citation_graph()
        self.assertIn(f"[{a['id']}] Paper A → 인용 → [{b['id']}] Paper B", out)
        self.assertIn(f"[{c['id']}] Paper C → 인용 → [{a['id']}] Paper A", out)
        self.assertIn("Shared Classic", out)


if __name__ == "__main__":
    unittest.main()
