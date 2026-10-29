# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""에이전트의 인터넷 도구(1.18.1): 웹 검색, 웹페이지·PDF 읽기, 저자별 논문 목록.

에이전트가 "인터넷에 접속할 수 없다"고 답하지 않고 스스로 찾아 읽게 한다(사용자 요청: 논문 전수조사).
- 웹 검색: 키 없이 DuckDuckGo(HTML 판). Firecrawl 키가 있으면 그쪽을 먼저 쓴다.
- 읽기: http·https만. 로컬·사설 네트워크 주소(공유기·내부 서버·이 PC의 서비스)는 열지 않는다(리디렉션도 매번 확인).
  HTML은 글과 링크만, PDF는 글자를 뽑는다. 결과는 에이전트가 '외부 데이터'로 감싼다(agent.py).
- 저자별 논문: OpenAlex(키 없음)에서 저자를 찾아 그 저자의 논문을 최신순으로 모두(최대 200편) 가져온다.
"""
import html
import re
import socket
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from net import ToolFailure, http

DDG_HTML = "https://html.duckduckgo.com/html/"
OPENALEX = "https://api.openalex.org"
MAX_BYTES = 15 * 1024 * 1024
DEFAULT_CHARS = 12000
MAX_LINKS = 40
WIKI_LANGS = ("ko", "en")


class WebError(Exception):
    pass


def _fail(e):
    return WebError(str(e))


# ---- 주소 확인 ----

def normalize_url(url):
    """비교용 주소: 앞뒤 공백·#조각을 떼고, 스킴·호스트는 소문자로."""
    url = str(url or "").strip()
    try:
        p = urlparse(url)
    except ValueError:
        return url
    if not p.scheme:
        return url
    return p._replace(scheme=p.scheme.lower(), netloc=p.netloc.lower(), fragment="").geturl()


def check_url(url):
    """http·https 공개 주소면 정리한 주소를, 아니면 WebError."""
    from browser_agent import local_host

    url = str(url or "").strip()
    if not re.match(r"(?i)^https?://", url):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
            url = "https://" + url
        else:
            raise WebError("http·https 주소만 읽을 수 있습니다.")
    try:
        p = urlparse(url)
    except ValueError:
        raise WebError("주소 꼴이 잘못되었습니다.")
    host = (p.hostname or "").lower()
    if not host or p.username or p.password:
        raise WebError("주소 꼴이 잘못되었습니다(사용자 이름·비밀번호를 넣은 주소는 읽지 않습니다).")
    if local_host(host) or _resolves_local(host):
        raise WebError("로컬·사설 네트워크 주소(이 PC나 내부망의 서비스)는 에이전트가 읽지 않습니다.")
    return url


def _resolves_local(host):
    """이름이 사설·로컬 IP로 풀리면 True(DNS로 내부 서비스를 가리키는 주소 막기). 풀리지 않으면(프록시 환경 등) False."""
    from browser_agent import local_host

    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    return any(local_host(info[4][0]) for info in infos)


# ---- HTML → 글 ----

class _TextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head", "nav", "footer", "form", "button", "select"}
    BLOCK = {"p", "div", "section", "article", "main", "header", "li", "ul", "ol", "table", "tr", "br", "hr", "pre",
             "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "figcaption", "aside"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts = []
        self.links = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._href = None
        self._anchor = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
            return
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.parts.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.parts.append("- ")
        if tag in ("td", "th"):
            self.parts.append(" | ")
        if tag == "a" and not self._skip:
            href = dict(attrs).get("href") or ""
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self._href = urljoin(self.base, href)
                self._anchor = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "a" and self._href:
            text = " ".join("".join(self._anchor).split())
            if text and len(self.links) < 400:
                self.links.append((text[:120], self._href))
            self._href = None
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data)


def html_to_text(raw, base=""):
    """(제목, 글, 링크 [(글, 주소)])."""
    parser = _TextParser(base)
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # 깨진 HTML도 읽은 데까지는 쓴다
        pass
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out, blank = [], False
    for line in lines:
        if not line or line in ("-", "|"):
            if not blank and out:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    seen, links = set(), []
    for text_, href in parser.links:
        if href in seen or not href.startswith(("http://", "https://")):
            continue
        seen.add(href)
        links.append((text_, href))
    return " ".join(parser.title.split()), "\n".join(out).strip(), links


# ---- 가져오기 ----

def _get(url, timeout=30):
    """리디렉션을 하나씩 따라가며(매번 주소 확인) 받는다. (마지막 주소, 응답, 본문 bytes)."""
    url = check_url(url)
    for _ in range(6):
        try:
            r = http("GET", url, timeout=timeout, allow_redirects=False, stream=True, headers={"Accept-Language": "ko,en;q=0.8"})
        except ToolFailure as e:
            raise _fail(e)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = check_url(urljoin(url, r.headers["Location"]))
            r.close()
            continue
        body = bytearray()
        try:
            for chunk in r.iter_content(65536):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise WebError(f"파일이 너무 큽니다({MAX_BYTES // (1024 * 1024)}MB 넘음).")
        except WebError:
            raise
        except Exception as e:
            raise WebError(f"받는 중 끊겼습니다: {type(e).__name__}")
        finally:
            r.close()
        return url, r, bytes(body)
    raise WebError("리디렉션이 너무 많습니다.")


def _pdf_text(data):
    import documents

    with tempfile.TemporaryDirectory(prefix="poschat-web-") as d:
        p = Path(d) / "page.pdf"
        p.write_bytes(data)
        try:
            return documents.extract_text(p)
        except Exception as e:
            raise WebError(f"PDF 글자를 읽지 못했습니다: {e}")


def _find(text, query, max_chars):
    """query 낱말이 많이 나오는 곳 둘레를 앞에서부터 모은다(긴 문서에서 필요한 부분만)."""
    words = [w.lower() for w in re.findall(r"\w{2,}", query or "")]
    if not words:
        return None
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    scored = [(sum(p.lower().count(w) for w in words), i) for i, p in enumerate(paras)]
    picked = sorted(i for s, i in sorted(scored, reverse=True)[:40] if s > 0)
    if not picked:
        return None
    out, size = [], 0
    for i in picked:
        part = paras[i].strip()
        if size + len(part) > max_chars:
            break
        out.append(part)
        size += len(part) + 2
    return "\n\n".join(out)


def fetch(url, query="", offset=0, max_chars=DEFAULT_CHARS):
    """주소의 글. (마지막 주소, 보여 줄 글, 글 속 링크 주소 목록)."""
    max_chars = max(1000, min(40000, int(max_chars or DEFAULT_CHARS)))
    offset = max(0, int(offset or 0))
    final, r, data = _get(url)
    if r.status_code >= 400:
        raise WebError(f"HTTP {r.status_code} — 페이지를 열 수 없습니다({final}).")
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    title, links = "", []
    if ctype == "application/pdf" or data[:5] == b"%PDF-":
        text = _pdf_text(data)
        kind = "PDF"
    elif ctype in ("text/html", "application/xhtml+xml") or (not ctype and b"<html" in data[:2000].lower()):
        enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
        m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', data[:4000], re.I)
        raw = data.decode(enc or (m.group(1).decode("ascii") if m else "utf-8"), errors="replace")
        title, text, links = html_to_text(raw, final)
        kind = "웹페이지"
    elif ctype.startswith("text/") or ctype in ("application/json", "application/xml", "application/x-bibtex"):
        text = data.decode(r.encoding or "utf-8", errors="replace")
        kind = ctype
    else:
        raise WebError(f"글로 읽을 수 없는 파일입니다({ctype or '형식 모름'}, {len(data):,}바이트). 필요하면 web_download로 받으세요.")
    total = len(text)
    found = _find(text, query, max_chars) if query and not offset else None
    if found:
        body = found + f"\n\n(전체 {total:,}자 중 '{query}' 둘레만 보였습니다. 처음부터 읽으려면 query 없이, 이어서는 offset을 쓰세요.)"
    else:
        body = text[offset:offset + max_chars]
        if offset + max_chars < total:
            body += f"\n\n(전체 {total:,}자 중 {offset:,}~{offset + len(body):,}자. 이어서 읽으려면 offset: {offset + max_chars})"
    head = f"{kind}: {title + ' — ' if title else ''}{final}"
    link_lines = [f"- {t} — {u}" for t, u in links[:MAX_LINKS]]
    if link_lines and not offset:
        body += "\n\n[페이지의 링크 일부]\n" + "\n".join(link_lines)
    return final, head + "\n\n" + body, [u for _, u in links]


def download(url):
    """(마지막 주소, Content-Type, 본문 bytes)."""
    final, r, data = _get(url, timeout=60)
    if r.status_code >= 400:
        raise WebError(f"HTTP {r.status_code} — 받을 수 없습니다({final}).")
    return final, (r.headers.get("Content-Type") or "").split(";")[0].strip().lower(), data


# ---- 웹 검색 ----

def _ddg_url(href):
    """DuckDuckGo 결과 링크(//duckduckgo.com/l/?uddg=…)에서 실제 주소를 꺼낸다."""
    href = html.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    p = urlparse(href)
    if p.netloc.endswith("duckduckgo.com") and p.path.startswith("/l/"):
        target = parse_qs(p.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


def parse_ddg(raw):
    """DuckDuckGo HTML 결과 → [{"title", "url", "snippet"}]."""
    results = []
    starts = [(m.start(), m.group(1).split()) for m in re.finditer(r'<div[^>]+class="([^"]*)"', raw)]
    starts = [(i, cls) for i, cls in starts if "result" in cls]
    for n, (i, cls) in enumerate(starts):
        if "result--ad" in cls:
            continue
        b = raw[i:starts[n + 1][0] if n + 1 < len(starts) else len(raw)]
        a = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.S) or \
            re.search(r'<a[^>]+href="([^"]+)"[^>]+class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', b, re.S)
        if not a:
            continue
        url = _ddg_url(a.group(1))
        if not url.startswith(("http://", "https://")) or "duckduckgo.com/y.js" in url:
            continue
        s = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div|td)>', b, re.S)
        clean = lambda x: " ".join(html.unescape(re.sub(r"<[^>]+>", "", x or "")).split())  # noqa: E731
        results.append({"title": clean(a.group(2)), "url": url, "snippet": clean(s.group(1) if s else "")})
    return results


def _ddg(query, limit):
    try:
        r = http("POST", DDG_HTML, data={"q": query}, timeout=25, headers={"Accept-Language": "ko,en;q=0.8"})
    except ToolFailure as e:
        raise _fail(e)
    if r.status_code != 200:
        raise WebError(f"DuckDuckGo가 검색을 받지 않았습니다(HTTP {r.status_code}).")
    return parse_ddg(r.text)[:limit]


def _wikipedia(query, limit):
    """위키백과 검색 API(키 없음): 인물·회사·개념의 기본 정보. 일반 웹 검색이 막혔을 때 마지막으로 쓴다."""
    out = []
    for lang in WIKI_LANGS:
        try:
            r = http("GET", f"https://{lang}.wikipedia.org/w/api.php", timeout=20,
                     params={"action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json"})
        except ToolFailure:
            continue
        if r.status_code != 200:
            continue
        for item in ((r.json().get("query") or {}).get("search") or []):
            title = item.get("title") or ""
            out.append({"title": f"{title} — 위키백과({lang})",
                        "url": f"https://{lang}.wikipedia.org/wiki/" + title.replace(" ", "_"),
                        "snippet": " ".join(html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet") or "")).split())})
    return out[:limit]


def _has_firecrawl():
    import os

    try:
        import storage

        return bool(os.environ.get("FIRECRAWL_API_KEY") or (storage.load_config().get("firecrawl_key") or "").strip())
    except Exception:
        return False


def _firecrawl(query, limit):
    import firecrawl_mcp

    try:
        data = firecrawl_mcp._api("POST", "/search", {"query": query, "limit": max(1, min(20, limit))})
    except ToolFailure as e:
        raise _fail(e)
    return [{"title": r.get("title") or "", "url": r.get("url") or "", "snippet": r.get("description") or ""}
            for r in (data.get("data") or {}).get("web") or [] if r.get("url")]


def search(query, limit=8):
    """[{"title", "url", "snippet"}]. Firecrawl 키가 있으면 Firecrawl, 없거나 실패하면 DuckDuckGo, 그것도 안 되면 위키백과."""
    query = " ".join(str(query or "").split())[:400]
    if not query:
        raise WebError("query가 비어 있습니다.")
    limit = max(1, min(20, int(limit or 8)))
    errors = []
    if _has_firecrawl():
        try:
            found = _firecrawl(query, limit)
            if found:
                return found
        except WebError as e:
            errors.append(f"Firecrawl: {e}")
    try:
        found = _ddg(query, limit)
        if found:
            return found
    except WebError as e:
        errors.append(str(e))
    found = _wikipedia(query, limit)
    if found:
        return found
    raise WebError("웹 검색에 실패했습니다: " + ("; ".join(errors) or "결과 없음") + ". 논문은 paper_search, 아는 사이트는 web_fetch로 "
                   "직접 읽으세요(설정의 Firecrawl API 키를 넣으면 웹 검색이 더 안정적입니다).")


def format_results(query, results):
    if not results:
        return f"'{query}' 검색 결과가 없습니다. 다른 낱말(영어 이름·정식 명칭 등)로 다시 찾아보세요."
    lines = [f"웹 검색 '{query}' ({len(results)}건)"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title'] or '(제목 없음)'}\n   {r['url']}" + (f"\n   {r['snippet']}" if r["snippet"] else ""))
    lines.append("본문은 web_fetch에 url을 넘겨 읽으세요.")
    return "\n".join(lines)


# ---- 저자별 논문(OpenAlex) ----

def _oa(path, params):
    import os

    key = os.environ.get("OPENALEX_API_KEY")
    try:
        r = http("GET", OPENALEX + path, params={**params, **({"api_key": key} if key else {})}, timeout=30)
    except ToolFailure as e:
        raise _fail(e)
    if r.status_code != 200:
        raise WebError(f"OpenAlex 요청에 실패했습니다(HTTP {r.status_code}).")
    return r.json()


def _inst(a):
    names = [i.get("display_name") for i in (a.get("last_known_institutions") or []) if i.get("display_name")]
    return ", ".join(names[:2])


def author_works(name, affiliation="", limit=100, author_id=""):
    """저자의 논문 목록(최신순). 이름이 같은 저자가 여럿이면 소속(affiliation)·논문 수로 고르고 다른 후보도 알린다.
    OpenAlex가 안 되면(요청 한도 등) Semantic Scholar로 찾는다."""
    limit = max(1, min(200, int(limit or 100)))
    try:
        return _openalex_works(name, affiliation, limit, author_id)
    except WebError as e:
        if author_id and not str(author_id).isdigit():
            raise
        try:
            return _s2_works(name, limit, author_id) + f"\n\n(OpenAlex 대신 Semantic Scholar 결과입니다: {e})"
        except (WebError, ToolFailure) as e2:
            raise WebError(f"{e} / Semantic Scholar: {e2}")


def _s2_works(name, limit, author_id=""):
    import paper_mcp

    if author_id:
        a = paper_mcp._s2(f"/author/{author_id}", {"fields": "name,affiliations,paperCount,citationCount"})
        cands = [a]
    else:
        name = " ".join(str(name or "").split())
        if not name:
            raise WebError("저자 이름(author)이 비어 있습니다.")
        cands = (paper_mcp._s2("/author/search", {"query": name, "fields": "name,affiliations,paperCount,citationCount",
                                                  "limit": 10}) or {}).get("data") or []
        if not cands:
            return f"Semantic Scholar에서 저자 '{name}'을(를) 찾지 못했습니다."
        cands.sort(key=lambda c: -(c.get("paperCount") or 0))
        a = cands[0]
    papers = (paper_mcp._s2(f"/author/{a['authorId']}/papers",
                            {"fields": "title,year,venue,externalIds,url,authors,openAccessPdf", "limit": 1000}) or {}).get("data") or []
    papers.sort(key=lambda p: -(p.get("year") or 0))
    lines = [f"저자: {a.get('name')} (Semantic Scholar {a['authorId']}) · 소속: {', '.join(a.get('affiliations') or []) or '알 수 없음'} · "
             f"논문 {a.get('paperCount', '?')}편 · 피인용 {a.get('citationCount', '?')}",
             f"논문 {len(papers[:limit])}편 (최신순)"]
    for i, p in enumerate(papers[:limit], 1):
        ids = p.get("externalIds") or {}
        link = f"https://doi.org/{ids['DOI']}" if ids.get("DOI") else (f"https://arxiv.org/abs/{ids['ArXiv']}" if ids.get("ArXiv") else p.get("url"))
        authors = [x.get("name") for x in p.get("authors") or []]
        who = ", ".join(n for n in authors[:5] if n) + (" 외" if len(authors) > 5 else "")
        pdf = (p.get("openAccessPdf") or {}).get("url")
        lines.append(f"{i}. {p.get('title')} ({p.get('year') or '?'}{', ' + p['venue'] if p.get('venue') else ''}) — {who}\n   {link}"
                     + (f"\n   PDF: {pdf}" if pdf else ""))
    others = cands[1:6]
    if others:
        lines.append("\n같은 이름의 다른 저자 후보(맞지 않으면 author_id로 다시 부르세요):")
        lines += [f"- {c.get('name')} ({c['authorId']}) · {', '.join(c.get('affiliations') or []) or '소속 모름'} · 논문 {c.get('paperCount')}편"
                  for c in others]
    return "\n".join(lines)


def _openalex_works(name, affiliation, limit, author_id):
    if author_id:
        aid = str(author_id).rsplit("/", 1)[-1]
        if not re.fullmatch(r"A\d+", aid):
            raise WebError("author_id는 OpenAlex 저자 번호(A로 시작)입니다.")
        a = _oa(f"/authors/{aid}", {})
        cands = [a]
    else:
        name = " ".join(str(name or "").split())
        if not name:
            raise WebError("저자 이름(author)이 비어 있습니다.")
        cands = _oa("/authors", {"search": name, "per-page": 10}).get("results") or []
        if not cands:
            return f"OpenAlex에서 저자 '{name}'을(를) 찾지 못했습니다. 영어 이름 철자(예: 성·이름 순서)를 바꿔 보세요."
        aff = str(affiliation or "").lower()
        if aff:
            match = [c for c in cands if aff in _inst(c).lower() or
                     any(aff in str(x.get("institution", {}).get("display_name", "")).lower() for x in c.get("affiliations") or [])]
            if match:
                cands = match + [c for c in cands if c not in match]
        a = cands[0]
    aid = a["id"].rsplit("/", 1)[-1]
    works, cursor = [], "*"
    while cursor and len(works) < limit:
        data = _oa("/works", {"filter": f"author.id:{aid}", "sort": "publication_date:desc",
                              "per-page": min(200, limit), "cursor": cursor})
        works += data.get("results") or []
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not data.get("results"):
            break
    lines = [f"저자: {a.get('display_name')} (OpenAlex {aid}) · 소속: {_inst(a) or '알 수 없음'} · "
             f"논문 {a.get('works_count', '?')}편 · 피인용 {a.get('cited_by_count', '?')}",
             f"논문 {len(works[:limit])}편 (최신순{', 일부만' if (a.get('works_count') or 0) > limit else ''})"]
    for i, w in enumerate(works[:limit], 1):
        venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        authors = [(x.get("author") or {}).get("display_name") for x in w.get("authorships") or []]
        who = ", ".join(n for n in authors[:5] if n) + (" 외" if len(authors) > 5 else "")
        link = w.get("doi") or ((w.get("primary_location") or {}).get("landing_page_url")) or w.get("id")
        oa = (w.get("open_access") or {}).get("oa_url")
        lines.append(f"{i}. {w.get('title') or w.get('display_name')} ({w.get('publication_year') or '?'}"
                     f"{', ' + venue if venue else ''}) — {who}\n   {link}" + (f"\n   PDF: {oa}" if oa and oa != link else ""))
    others = [c for c in cands[1:6] if c is not a]
    if others:
        lines.append("\n같은 이름의 다른 저자 후보(맞지 않으면 author_id로 다시 부르세요):")
        lines += [f"- {c.get('display_name')} ({c['id'].rsplit('/', 1)[-1]}) · {_inst(c) or '소속 모름'} · 논문 {c.get('works_count')}편"
                  for c in others]
    return "\n".join(lines)
