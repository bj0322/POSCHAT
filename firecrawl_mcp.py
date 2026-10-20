"""내장 MCP 서버 firecrawl: 웹페이지를 마크다운으로 읽고, 웹을 검색하고, 사이트를 훑는다(Firecrawl API v2).

설정 창에 넣은 Firecrawl API 키(config.json의 firecrawl_key) 또는 FIRECRAWL_API_KEY 환경 변수를 쓴다.
키는 https://www.firecrawl.dev 에서 무료로 가입하면 받는다(무료 크레딧 제공). 직접 띄운 Firecrawl 서버를
쓰려면 FIRECRAWL_API_URL에 주소를 넣는다(이때는 키가 없어도 된다). 작업 폴더에는 쓰지 않는다.
"""
import os
import time

from office_mcp import BOOL, INT, READ_ONLY, STR, ToolFailure, _schema, http

API = "https://api.firecrawl.dev/v2"
DEFAULT_CHARS = 12000
CRAWL_WAIT = 100  # crawl이 끝나기를 기다리는 시간(초). MCP 호출 제한(180초)보다 짧아야 한다
SETUP_HINT = ("설정 → Firecrawl API 키에 키(fc-...)를 넣으세요. https://www.firecrawl.dev 에서 무료로 가입하면 "
              "키와 무료 크레딧을 받을 수 있습니다.")


def _base():
    return (os.environ.get("FIRECRAWL_API_URL") or API).rstrip("/")


def _key():
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        import storage

        key = storage.load_config().get("firecrawl_key", "")
    key = (key or "").strip()
    if not key and not os.environ.get("FIRECRAWL_API_URL"):
        raise ToolFailure("Firecrawl API 키가 없습니다. " + SETUP_HINT)
    return key


def _api(method, path, body=None, timeout=90):
    key = _key()
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
    for attempt in range(2):
        r = http(method, _base() + path, json=body, headers=headers, timeout=timeout)
        if r.status_code == 429 and attempt == 0:
            time.sleep(min(10.0, float(r.headers.get("Retry-After") or 5)))  # 무료 요금제는 분당 요청 수가 적다
            continue
        break
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code == 200 and data.get("success", True):
        return data
    message = data.get("error") or data.get("message") or r.text[:300]
    if r.status_code == 401:
        raise ToolFailure("Firecrawl API 키가 올바르지 않습니다. " + SETUP_HINT)
    if r.status_code == 402:
        raise ToolFailure("Firecrawl 크레딧이 모자랍니다. firecrawl.dev 대시보드에서 남은 크레딧을 확인하세요.")
    if r.status_code == 429:
        raise ToolFailure("Firecrawl 요청 한도를 넘었습니다(무료 요금제는 분당 약 10회). 잠시 뒤 다시 시도하세요.")
    if r.status_code == 408:
        raise ToolFailure(f"페이지를 가져오는 데 시간이 너무 걸렸습니다. ({message})")
    raise ToolFailure(f"Firecrawl 요청에 실패했습니다(HTTP {r.status_code}): {message}")


def _url(url):
    url = str(url or "").strip()
    if not url:
        raise ToolFailure("url을 주세요.")
    return url if url.startswith(("http://", "https://")) else "https://" + url


def _limit(value, default, hi):
    try:
        return max(1, min(hi, int(value or default)))
    except (TypeError, ValueError):
        return default


def _clip(text, max_chars):
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n…(분량이 많아 {max_chars:,}자에서 잘랐습니다. 필요하면 max_chars를 늘리세요.)"


def _page_text(page, max_chars):
    meta = page.get("metadata") or {}
    title = meta.get("title") or page.get("title") or ""
    url = meta.get("sourceURL") or meta.get("url") or page.get("url") or ""
    head = f"# {title}\n{url}" if title else url
    return head + "\n\n" + _clip(page.get("markdown") or "(본문 없음)", max_chars)


# ---- 도구 ----

def scrape(url, only_main_content=True, max_chars=DEFAULT_CHARS):
    max_chars = _limit(max_chars, DEFAULT_CHARS, 60000)
    data = _api("POST", "/scrape", {"url": _url(url), "formats": ["markdown"],
                                   "onlyMainContent": bool(only_main_content) if only_main_content is not None else True})
    page = data.get("data") or {}
    status = (page.get("metadata") or {}).get("statusCode")
    note = f"\n\n(페이지 응답 코드 {status})" if status and status >= 400 else ""
    return _page_text(page, max_chars) + note


def search(query, limit=5, scrape=False, max_chars=4000):
    query = str(query or "").strip()
    if not query:
        raise ToolFailure("query가 비어 있습니다.")
    body = {"query": query, "limit": _limit(limit, 5, 20)}
    if scrape:
        body["scrapeOptions"] = {"formats": ["markdown"], "onlyMainContent": True}
    data = _api("POST", "/search", body)
    results = (data.get("data") or {}).get("web") or []
    if not results:
        return f"'{query}' 검색 결과가 없습니다."
    max_chars = _limit(max_chars, 4000, 20000)
    lines = [f"웹 검색 '{query}' ({len(results)}건)"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n{i}. {r.get('title') or '(제목 없음)'}\n   {r.get('url', '')}\n   {r.get('description') or ''}".rstrip())
        if scrape and r.get("markdown"):
            lines.append(_clip(r["markdown"], max_chars))
    if not scrape:
        lines.append("\n본문이 필요하면 scrape에 url을 넘기거나 search를 scrape=true로 부르세요.")
    return "\n".join(lines)


def map_site(url, search=None, limit=100):
    body = {"url": _url(url), "limit": _limit(limit, 100, 1000)}
    if search:
        body["search"] = str(search)
    links = _api("POST", "/map", body).get("links") or []
    if not links:
        return "찾은 주소가 없습니다."
    lines = [f"{_url(url)}에서 찾은 주소 {len(links)}개" + (f" ('{search}' 관련 순)" if search else "")]
    for item in links:
        if isinstance(item, dict):
            lines.append(f"- {item.get('url', '')}" + (f"  — {item['title']}" if item.get("title") else ""))
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _crawl_text(job, data, max_chars):
    pages = data.get("data") or []
    status = data.get("status")
    head = (f"크롤링 {('완료' if status == 'completed' else '실패' if status == 'failed' else '진행 중')}: "
            f"{data.get('completed', len(pages))}/{data.get('total', '?')}쪽 (job: {job})")
    if status not in ("completed", "failed"):
        head += "\ncrawl_status로 다시 확인하세요."
    if not pages:
        return head
    per = max(1500, max_chars // max(1, len(pages)))
    body = "\n\n---\n\n".join(_page_text(p, per) for p in pages)
    return head + "\n\n" + _clip(body, max_chars)


def crawl(url, limit=10, max_depth=None, max_chars=20000):
    body = {"url": _url(url), "limit": _limit(limit, 10, 100),
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}}
    if max_depth:
        body["maxDiscoveryDepth"] = _limit(max_depth, 2, 10)
    job = _api("POST", "/crawl", body).get("id")
    if not job:
        raise ToolFailure("Firecrawl이 크롤링 작업 번호를 돌려주지 않았습니다.")
    deadline = time.time() + CRAWL_WAIT
    data = {}
    while time.time() < deadline:
        time.sleep(3)
        data = _api("GET", f"/crawl/{job}")
        if data.get("status") in ("completed", "failed"):
            break
    return _crawl_text(job, data, _limit(max_chars, 20000, 60000))


def crawl_status(job, max_chars=20000):
    job = str(job or "").strip()
    if not job:
        raise ToolFailure("job(crawl이 돌려준 작업 번호)을 주세요.")
    return _crawl_text(job, _api("GET", f"/crawl/{job}"), _limit(max_chars, 20000, 60000))


TOOLS = {
    "scrape": (scrape, "웹페이지 하나를 깔끔한 마크다운으로 읽습니다(자바스크립트로 그리는 페이지 포함). "
                       "only_main_content(기본 true)는 메뉴·광고를 뺍니다. max_chars 기본 12000.",
               _schema({"url": STR, "only_main_content": BOOL, "max_chars": INT}, ["url"]), READ_ONLY),
    "search": (search, "웹을 검색해 제목·주소·요약을 봅니다. scrape=true면 각 결과의 본문도 가져옵니다(크레딧을 더 씁니다).",
               _schema({"query": STR, "limit": INT, "scrape": BOOL, "max_chars": INT}, ["query"]), READ_ONLY),
    "map": (map_site, "사이트의 페이지 주소 목록을 빠르게 찾습니다. search를 주면 관련 있는 주소부터.",
            _schema({"url": STR, "search": STR, "limit": INT}, ["url"]), READ_ONLY),
    "crawl": (crawl, "사이트의 여러 페이지를 따라가며 읽습니다(limit 기본 10쪽, 최대 100쪽, 쪽마다 크레딧 사용). "
                     "오래 걸리면 진행 중으로 돌아오니 crawl_status로 확인하세요.",
              _schema({"url": STR, "limit": INT, "max_depth": INT, "max_chars": INT}, ["url"]), READ_ONLY),
    "crawl_status": (crawl_status, "crawl 작업의 진행 상황과 결과를 봅니다.",
                     _schema({"job": STR, "max_chars": INT}, ["job"]), READ_ONLY),
}
