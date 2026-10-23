# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""내장 MCP 서버 research(논문 라이브러리·연구 문서 검색)와 zotero(Zotero Web API v3). 커넥터 → 연구.

research
- 라이브러리: 더하기(arXiv 번호·DOI면 메타데이터를 찾아 채움)·목록·보기·고치기·지우기·BibTeX·PDF 메타데이터 추출
- 관련 논문 추천(Semantic Scholar Recommendations), 라이브러리 안의 인용 관계와 공통 참고문헌
- RAG: 작업 폴더 문서 인덱싱(rag.py)과 출처가 붙은 검색. 검색 범위는 지금 작업 폴더와 라이브러리 PDF뿐이다.
zotero
- 검색·컬렉션 목록·라이브러리로 가져오기(버전 기반 증분)·Zotero에 항목 추가(Zotero-Write-Token으로 중복 방지)

로컬 라이브러리를 바꾸는 도구는 edit(작업 폴더 수정과 같은 승인), 지우기는 destructive, Zotero에 쓰기는 write다
(connectors.TOOL_KINDS).
"""
import json
import re
import secrets
import time
from pathlib import Path

import connectors
import oauth
import paper_mcp
import rag
import research_library as lib
import storage
import vector_store
from office_mcp import BOOL, INT, READ_ONLY, STR, ToolFailure, _root, _schema, http

S2_RECOMMEND = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper"
ZOTERO = "https://api.zotero.org"
LOCAL_WRITES = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
REMOTE_WRITES = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}
ARR = {"type": "array", "items": STR}


def _lib_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except lib.LibraryError as e:
        raise ToolFailure(str(e))


def _in_workspace(path):
    root = _root()
    p = (root / str(path)).resolve()
    if p != root and root not in p.parents:
        raise ToolFailure("작업 폴더 밖의 파일은 쓸 수 없습니다.")
    return p


# ---- 메타데이터 찾기 ----

def lookup(paper):
    """arXiv 번호·DOI·URL·작업 폴더 PDF로 메타데이터를 찾는다."""
    kind, value = paper_mcp._identify(paper)
    if kind == "file":
        p = _in_workspace(value)
        meta = _lib_call(lib.pdf_metadata, p)
        meta["pdf"] = p.relative_to(_root()).as_posix()
        if meta.get("doi") or meta.get("arxiv"):
            try:
                found = lookup(f"arXiv:{meta['arxiv']}" if meta.get("arxiv") else meta["doi"])
                return {**found, "pdf": meta["pdf"]}
            except ToolFailure:
                pass
        return meta
    if kind == "arxiv":
        entries = paper_mcp._arxiv_entries({"id_list": value, "max_results": 1})
        if entries:
            rec = paper_mcp._from_arxiv(entries[0])
            s2 = paper_mcp._s2("/paper/" + paper_mcp._s2_id(kind, value), {"fields": "citationCount,venue"}, quiet=True)
            if s2:
                rec["citations"] = s2.get("citationCount")
                rec["venue"] = s2.get("venue") or rec["venue"]
            return _from_record(rec, "arXiv")
    if kind == "doi":
        r = http("GET", f"{paper_mcp.CROSSREF_API}/{value}", timeout=30)
        if r.status_code == 200:
            return _from_record(paper_mcp._from_crossref(r.json().get("message") or {}), "Crossref")
    s2 = paper_mcp._s2("/paper/" + paper_mcp._s2_id(kind, value), {"fields": paper_mcp.S2_FIELDS}, quiet=True)
    if s2:
        return _from_record(paper_mcp._from_s2(s2), "Semantic Scholar")
    raise ToolFailure(f"논문 정보를 찾지 못했습니다: {paper}")


def _from_record(rec, source):
    return {k: rec[k] for k in ("title", "authors", "year", "venue", "doi", "arxiv", "url", "abstract", "citations")
            if rec.get(k) not in (None, "", [])} | {"source": source}


# ---- 라이브러리 도구 ----

def library_add(paper=None, title=None, authors=None, year=None, doi=None, arxiv=None, url=None, tags=None,
                collection=None, notes=None, pdf=None):
    meta = lookup(paper) if paper else {}
    manual = {"title": title, "authors": authors, "year": year, "doi": doi, "arxiv": arxiv, "url": url, "notes": notes}
    meta.update({k: v for k, v in manual.items() if v})
    if tags:
        meta["tags"] = tags
    if collection:
        meta["collections"] = [collection] if isinstance(collection, str) else collection
    if pdf:
        meta["pdf"] = _in_workspace(pdf).relative_to(_root()).as_posix()
    if not meta:
        raise ToolFailure("paper(arXiv 번호·DOI·URL·작업 폴더 PDF)나 title을 주세요.")
    record, created = _lib_call(lib.add, meta)
    return ("라이브러리에 더했습니다:\n" if created else "이미 있는 논문이라 빈 정보만 채웠습니다:\n") + lib.format_paper(record)


def library_list(query=None, tag=None, collection=None, limit=30):
    papers = lib.search(query or "", tag, collection, limit)
    if not papers:
        return "라이브러리에 맞는 논문이 없습니다." + ("" if lib.load()["papers"] else " library_add로 더하세요.")
    tags = lib.tags()
    head = f"라이브러리 {len(papers)}편" + (f" (태그: {', '.join(f'{t}({n})' for t, n in tags.items())})" if tags else "")
    return head + "\n\n" + "\n".join(lib.format_paper(p) for p in papers)


def library_get(id):  # noqa: A002 — 도구 인자 이름
    return lib.format_paper(_lib_call(lib.find, id), long=True)


def library_update(id, tags=None, collections=None, notes=None, pdf=None, title=None, year=None, venue=None):  # noqa: A002
    record = _lib_call(lib.find, id)
    fields = {k: v for k, v in {"tags": tags, "collections": collections, "notes": notes, "title": title, "year": year,
                                "venue": venue}.items() if v is not None}
    if pdf is not None:
        fields["pdf"] = _in_workspace(pdf).relative_to(_root()).as_posix() if pdf else ""
    if not fields:
        raise ToolFailure("바꿀 내용이 없습니다.")
    return "고쳤습니다:\n" + lib.format_paper(_lib_call(lib.update, record["id"], **fields), long=True)


def library_remove(id):  # noqa: A002
    record = _lib_call(lib.find, id)
    _lib_call(lib.remove, record["id"])
    return f"라이브러리에서 지웠습니다: {record.get('title')}"


def export_bibtex(ids=None, tag=None, collection=None, path=None):
    if ids:
        papers = [_lib_call(lib.find, i) for i in ([ids] if isinstance(ids, str) else ids)]
    else:
        papers = lib.search("", tag, collection, limit=100000)
    if not papers:
        raise ToolFailure("내보낼 논문이 없습니다.")
    text = lib.to_bibtex(papers)
    if path:
        p = _in_workspace(path)
        if p.suffix.lower() != ".bib":
            raise ToolFailure("BibTeX 파일 이름은 .bib로 끝나야 합니다.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return f"{p.relative_to(_root()).as_posix()}에 {len(papers)}편을 저장했습니다."
    return text


def extract_metadata(path):
    meta = _lib_call(lib.pdf_metadata, _in_workspace(path))
    found = {k: v for k, v in meta.items() if k != "pdf"}
    lines = [f"{path}에서 찾은 정보:"] + [f"- {k}: {v}" for k, v in found.items()]
    if meta.get("doi") or meta.get("arxiv"):
        lines.append("\nlibrary_add에 paper로 이 PDF 경로를 넘기면 DOI·arXiv 번호로 정확한 정보를 찾아 더합니다.")
    return "\n".join(lines)


# ---- 추천·인용 관계 ----

def _s2_ref(p):
    if p.get("arxiv"):
        return f"arXiv:{p['arxiv']}"
    if p.get("doi"):
        return f"DOI:{p['doi']}"
    return ""


def recommend(paper, limit=10):
    try:
        record = lib.find(paper)
        ref = _s2_ref(record)
    except lib.LibraryError:
        kind, value = paper_mcp._identify(paper)
        ref = paper_mcp._s2_id(kind, value) if kind != "file" else ""
    if not ref:
        raise ToolFailure("추천에는 DOI나 arXiv 번호가 있는 논문이 필요합니다.")
    headers = {"x-api-key": paper_mcp._s2_key()} if paper_mcp._s2_key() else {}
    r = http("GET", f"{S2_RECOMMEND}/{ref}", params={"limit": max(1, min(50, int(limit or 10))),
                                                     "fields": "title,authors,year,venue,citationCount,externalIds,url"},
             headers=headers, timeout=30)
    if r.status_code != 200:
        raise ToolFailure(f"Semantic Scholar 추천을 받지 못했습니다(HTTP {r.status_code}).")
    records = paper_mcp.merge_records([paper_mcp._from_s2(p) for p in r.json().get("recommendedPapers") or []])
    if not records:
        return "추천할 논문을 찾지 못했습니다."
    have = {lib.identity(p) for p in lib.load()["papers"].values() if p.get("title")}
    for rec in records:
        try:
            rec["sources"] = rec["sources"] + (["라이브러리에 있음"] if lib.identity(rec) in have else [])
        except lib.LibraryError:
            pass
    return paper_mcp.format_records(records, f"'{ref}'와 관련된 추천 논문(Semantic Scholar) {len(records)}편")


def citation_graph(ids=None, collection=None, max_papers=15):
    papers = [lib.find(i) for i in ids] if ids else lib.search("", None, collection, limit=1000)
    papers = [p for p in papers if _s2_ref(p)][:max(1, min(30, int(max_papers or 15)))]
    if len(papers) < 2:
        raise ToolFailure("인용 관계를 보려면 DOI나 arXiv 번호가 있는 논문이 두 편 이상 필요합니다.")
    by_key = {}
    for p in papers:
        for key in (("doi", p.get("doi")), ("arxiv", p.get("arxiv")), ("title", lib._norm_title(p.get("title")))):
            if key[1]:
                by_key[key] = p
    edges, common, failed = [], {}, []
    for p in papers:
        data = paper_mcp._s2(f"/paper/{_s2_ref(p)}/references", {"limit": 500, "fields": "title,externalIds,year"}, quiet=True)
        if data is None:
            failed.append(p["title"])
            continue
        for row in data.get("data") or []:
            cited = row.get("citedPaper") or {}
            ids_ = cited.get("externalIds") or {}
            keys = [("doi", str(ids_.get("DOI") or "").lower()), ("arxiv", ids_.get("ArXiv") or ""),
                    ("title", lib._norm_title(cited.get("title")))]
            target = next((by_key[k] for k in keys if k[1] and k in by_key), None)
            if target and target["id"] != p["id"]:
                edges.append((p, target))
            elif cited.get("title"):
                entry = common.setdefault(lib._norm_title(cited["title"]), [cited, set()])
                entry[1].add(p["id"])
    lines = [f"라이브러리 {len(papers)}편의 인용 관계"]
    lines += [f"- [{a['id']}] {a['title'][:60]} → 인용 → [{b['id']}] {b['title'][:60]}" for a, b in edges] or ["- 서로 인용한 논문이 없습니다."]
    shared = sorted(((c, s) for c, s in common.values() if len(s) >= 2), key=lambda x: -len(x[1]))[:10]
    if shared:
        lines.append("\n여러 편이 함께 참고한 논문(라이브러리에 없음, 읽어 볼 후보):")
        lines += [f"- {c.get('title')} ({c.get('year') or '?'}) — {len(s)}편이 인용" for c, s in shared]
    if failed:
        lines.append("\n참고문헌을 가져오지 못한 논문: " + "; ".join(failed))
    return "\n".join(lines)


# ---- RAG ----

def _collections(scope):
    ws = rag.workspace_collection(_root())
    return {"workspace": [ws], "library": ["library"]}.get(scope or "all", [ws, "library"])


def _vectors():
    try:
        return vector_store.from_config()
    except Exception:
        return None


def index_documents(paths=None, include_library=True):
    """작업 폴더(또는 그 안의 paths)의 PDF·문서를 인덱싱한다. 라이브러리에 연결한 작업 폴더 PDF도 함께."""
    root = _root()
    vectors = _vectors()
    if isinstance(paths, str):
        paths = [paths]
    try:
        summary = rag.index_folder(root, rag.workspace_collection(root), paths=paths or None, vectors=vectors)
    except rag.RagError as e:
        raise ToolFailure(str(e))
    lib_done = 0
    if include_library:
        for p in lib.load()["papers"].values():
            pdf = p.get("pdf")
            if not pdf:
                continue
            path = (root / pdf).resolve()
            if path.is_file() and (root in path.parents):
                try:
                    rag.index_file(path, "library", title=p.get("title"), library_id=p["id"], vectors=vectors)
                    lib_done += 1
                except (rag.RagError, OSError):
                    pass
    lines = [f"인덱싱: 새로 {summary['indexed']}개, 그대로 {summary['unchanged']}개, 지운 파일 {summary['removed']}개, "
             f"청크 {summary['chunks']}개" + (f", 라이브러리 PDF {lib_done}개" if lib_done else "")]
    lines.append(f"검색 방식: {rag.fts_mode()}" + (" + 벡터" if vectors else ""))
    if summary["failed"]:
        lines.append("실패:\n" + "\n".join(f"- {f}" for f in summary["failed"][:20]))
    return "\n".join(lines)


def search_documents(query, scope="all", limit=8):
    try:
        results = rag.search(query, _collections(scope), limit=max(1, min(20, int(limit or 8))), vectors=_vectors())
    except rag.RagError as e:
        raise ToolFailure(str(e))
    return rag.format_results(results, root=_root())


def index_status():
    st = rag.status(_collections("all"))
    if not st["documents"]:
        return "아직 인덱싱한 문서가 없습니다. index_documents를 부르세요."
    lines = [f"인덱스: 문서 {len(st['documents'])}개, 청크 {st['chunks']}개 (검색 방식 {st['fts']})"]
    root = _root()
    for d in st["documents"][:50]:
        try:
            shown = Path(d["path"]).relative_to(root).as_posix()
        except ValueError:
            shown = Path(d["path"]).name
        lines.append(f"- {shown} ({d['pages'] or '-'}쪽, 청크 {d['chunks']}, {'라이브러리' if d['collection'] == 'library' else '작업 폴더'})")
    return "\n".join(lines)


# ---- Zotero ----

ZOTERO_STATE = "zotero_state.json"


def _zotero_key():
    try:
        return connectors.credential("zotero")
    except oauth.NeedsAuth:
        raise ToolFailure(f"{connectors.NEEDS_AUTH_TAG} Zotero API 키가 없습니다. 연결·도구 → 커넥터 → Zotero에서 넣으세요 "
                          "(zotero.org/settings/keys에서 만듭니다).")


def _zotero(method, path, params=None, body=None, headers=None):
    head = {"Zotero-API-Key": _zotero_key(), "Zotero-API-Version": "3", **(headers or {})}
    for attempt in range(3):
        r = http(method, ZOTERO + path, params=params, json=body, headers=head, timeout=30)
        if r.status_code in (429, 503) and attempt < 2:
            time.sleep(min(10.0, float(r.headers.get("Retry-After") or r.headers.get("Backoff") or 2)))
            continue
        break
    if r.status_code in (200, 201, 204, 304):
        return r
    if r.status_code == 403:
        raise ToolFailure(f"{connectors.SCOPE_TAG} Zotero 키에 이 라이브러리 권한이 없습니다(읽기/쓰기 권한 확인). {r.text[:200]}")
    if r.status_code == 401:
        raise ToolFailure(f"{connectors.NEEDS_AUTH_TAG} Zotero API 키가 올바르지 않습니다.")
    raise ToolFailure(f"Zotero 요청에 실패했습니다(HTTP {r.status_code}): {r.text[:200]}")


def _zotero_library():
    config = storage.load_config()
    kind = connectors.option(config, "zotero", "library_type", "user")
    lid = str(connectors.option(config, "zotero", "library_id", "")).strip()
    if not lid:
        lid = str(_zotero("GET", "/keys/current").json().get("userID", ""))
        kind = "user"
    if not re.fullmatch(r"\d+", lid):
        raise ToolFailure("Zotero 라이브러리 ID(숫자)를 확인하세요.")
    return f"/{'groups' if kind == 'group' else 'users'}/{lid}"


def zotero_verify(cid="zotero", config=None):
    data = _zotero("GET", "/keys/current").json()
    access = data.get("access", {}).get("user", {})
    rights = [k for k in ("library", "write", "notes") if access.get(k)]
    return {"account": data.get("username", str(data.get("userID", ""))),
            "detail": f"사용자 {data.get('userID')} · 권한: {', '.join(rights) or '그룹만'}"}


def _zotero_meta(item, collection_names):
    d = item.get("data") or {}
    authors = []
    for c in d.get("creators") or []:
        name = c.get("name") or " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x)
        if name:
            authors.append(name)
    arxiv = ""
    m = re.search(r"arxiv\.org/abs/([0-9.]+)", d.get("url", "")) or re.search(r"arXiv:\s*([0-9.]+)", d.get("extra", ""))
    if m:
        arxiv = m.group(1)
    return {"title": d.get("title"), "authors": authors, "year": (re.search(r"\d{4}", d.get("date", "")) or [""])[0],
            "venue": d.get("publicationTitle") or d.get("proceedingsTitle") or d.get("repository"),
            "doi": d.get("DOI"), "arxiv": arxiv, "url": d.get("url"), "abstract": d.get("abstractNote"),
            "tags": [t["tag"] for t in d.get("tags") or [] if t.get("tag")],
            "collections": [collection_names[k] for k in d.get("collections") or [] if k in collection_names],
            "zotero_key": item.get("key"), "zotero_version": item.get("version"), "source": "Zotero"}


def _collection_names(base):
    r = _zotero("GET", f"{base}/collections", {"limit": 100})
    return {c["key"]: c["data"]["name"] for c in r.json()}


def zotero_search(query, limit=20):
    base = _zotero_library()
    r = _zotero("GET", f"{base}/items/top", {"q": str(query), "limit": max(1, min(100, int(limit or 20))),
                                              "format": "json", "itemType": "-attachment || note"})
    items = r.json()
    if not items:
        return f"Zotero에서 '{query}'에 맞는 항목이 없습니다."
    names = _collection_names(base)
    lines = [f"Zotero 검색 '{query}' {len(items)}건"]
    for item in items:
        m = _zotero_meta(item, names)
        lines.append(f"- [{m['zotero_key']}] {m['title']} ({m['year'] or '?'}) · {', '.join(m['authors'][:3])}"
                     + (f" · DOI {m['doi']}" if m["doi"] else ""))
    return "\n".join(lines)


def zotero_collections():
    names = _collection_names(_zotero_library())
    return "Zotero 컬렉션\n" + ("\n".join(f"- {n} (key {k})" for k, n in names.items()) or "(없음)")


def _state_path():
    return lib.research_dir() / ZOTERO_STATE


def zotero_import(collection=None, full=False):
    """Zotero 라이브러리를 로컬 라이브러리로 가져온다. 지난번 이후 바뀐 항목만(full이면 전체)."""
    base = _zotero_library()
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        state = {}
    since = 0 if full else int(state.get(base, 0))
    names = _collection_names(base)
    path = f"{base}/collections/{collection}/items/top" if collection else f"{base}/items/top"
    added = updated = 0
    start, version = 0, since
    while True:
        r = _zotero("GET", path, {"since": since, "format": "json", "limit": 100, "start": start,
                                  "itemType": "-attachment || note"})
        items = r.json() if r.status_code == 200 else []
        version = max(version, int(r.headers.get("Last-Modified-Version") or 0))
        for item in items:
            meta = _zotero_meta(item, names)
            if not meta["title"]:
                continue
            try:
                _, created = lib.add(meta)
            except lib.LibraryError:
                continue
            added += created
            updated += not created
        if len(items) < 100:
            break
        start += 100
    state[base] = version
    lib.research_dir().mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state), encoding="utf-8")
    return f"Zotero에서 가져왔습니다: 새로 {added}편, 기존 항목 갱신 {updated}편 (라이브러리 버전 {version})."


def zotero_add(id):  # noqa: A002
    """로컬 라이브러리의 논문을 Zotero에 항목으로 만든다."""
    p = _lib_call(lib.find, id)
    if p.get("zotero_key"):
        return f"이미 Zotero에 있는 항목입니다(key {p['zotero_key']})."
    creators = []
    for name in p.get("authors") or []:
        parts = name.rsplit(" ", 1)
        creators.append({"creatorType": "author", "firstName": parts[0], "lastName": parts[1]} if len(parts) == 2
                        else {"creatorType": "author", "name": name})
    item = {"itemType": "preprint" if p.get("arxiv") and not p.get("doi") else "journalArticle",
            "title": p.get("title", ""), "creators": creators, "date": p.get("year", ""), "url": p.get("url", ""),
            "abstractNote": p.get("abstract", ""), "tags": [{"tag": t} for t in p.get("tags") or []]}
    if item["itemType"] == "journalArticle":
        item.update(DOI=p.get("doi", ""), publicationTitle=p.get("venue", ""))
    else:
        item.update(repository="arXiv", archiveID=f"arXiv:{p['arxiv']}")
    # 같은 요청이 다시 와도(재시도) 항목이 두 번 생기지 않게 쓰기 토큰을 붙인다
    r = _zotero("POST", f"{_zotero_library()}/items", body=[item], headers={"Zotero-Write-Token": secrets.token_hex(16)})
    result = r.json()
    created = (result.get("successful") or {}).get("0") or {}
    if not created:
        raise ToolFailure(f"Zotero가 항목을 만들지 않았습니다: {json.dumps(result.get('failed'), ensure_ascii=False)[:300]}")
    lib.update(p["id"], zotero_key=created.get("key"), zotero_version=created.get("version"))
    return f"Zotero에 만들었습니다(key {created.get('key')}): {p.get('title')}"


PAPER_REF = "id: 라이브러리 id·DOI·arXiv 번호·제목 일부"

TOOLS = {
    "library_add": (library_add, "논문을 라이브러리에 더합니다. paper에 arXiv 번호·DOI·URL·작업 폴더 PDF를 주면 정보를 찾아 채웁니다. "
                                 "tags(배열)·collection·notes·pdf(작업 폴더의 PDF 경로)로 분류합니다.",
                    _schema({"paper": STR, "title": STR, "authors": ARR, "year": STR, "doi": STR, "arxiv": STR,
                             "url": STR, "tags": ARR, "collection": STR, "notes": STR, "pdf": STR}, []), LOCAL_WRITES),
    "library_list": (library_list, "라이브러리 논문 목록. query(제목·저자·초록·메모 검색), tag, collection으로 거릅니다.",
                     _schema({"query": STR, "tag": STR, "collection": STR, "limit": INT}, []), READ_ONLY),
    "library_get": (library_get, "라이브러리 논문 하나의 전체 정보(초록·메모 포함). " + PAPER_REF,
                    _schema({"id": STR}, ["id"]), READ_ONLY),
    "library_update": (library_update, "태그·컬렉션·메모·PDF 연결 등을 바꿉니다(배열은 통째로 바꿈). " + PAPER_REF,
                       _schema({"id": STR, "tags": ARR, "collections": ARR, "notes": STR, "pdf": STR, "title": STR,
                                "year": STR, "venue": STR}, ["id"]), LOCAL_WRITES),
    "library_remove": (library_remove, "라이브러리에서 논문을 지웁니다(사용자 승인 필요). " + PAPER_REF,
                       _schema({"id": STR}, ["id"]), DESTRUCTIVE),
    "export_bibtex": (export_bibtex, "BibTeX으로 내보냅니다. ids(배열)나 tag·collection으로 고르고, 비우면 전체. "
                                     "path(작업 폴더의 .bib)를 주면 파일로 저장합니다.",
                      _schema({"ids": ARR, "tag": STR, "collection": STR, "path": STR}, []), LOCAL_WRITES),
    "extract_metadata": (extract_metadata, "작업 폴더 PDF에서 제목·저자·DOI·arXiv 번호를 뽑습니다.",
                         _schema({"path": STR}, ["path"]), READ_ONLY),
    "recommend": (recommend, "이 논문과 관련된 논문을 추천합니다(Semantic Scholar). paper: 라이브러리 id·DOI·arXiv 번호",
                  _schema({"paper": STR, "limit": INT}, ["paper"]), READ_ONLY),
    "citation_graph": (citation_graph, "라이브러리 논문들 사이의 인용 관계와 여러 편이 함께 참고한 논문을 봅니다. ids나 collection으로 고릅니다.",
                       _schema({"ids": ARR, "collection": STR, "max_papers": INT}, []), READ_ONLY),
    "index_documents": (index_documents, "작업 폴더의 PDF·Word·PowerPoint·한글·텍스트 문서(paths로 일부만)를 검색 인덱스에 넣습니다. "
                                         "바뀐 파일만 다시 나눕니다.",
                        _schema({"paths": ARR, "include_library": BOOL}, []), LOCAL_WRITES),
    "search_documents": (search_documents, "인덱싱한 문서에서 찾고, 파일·쪽·섹션이 붙은 원문 조각을 돌려줍니다. 문서 내용으로 답할 때 쓰세요. "
                                           "scope: all(기본)|workspace|library",
                         _schema({"query": STR, "scope": STR, "limit": INT}, ["query"]), READ_ONLY),
    "index_status": (index_status, "인덱싱한 문서 목록과 검색 방식(trigram·unicode61·벡터)을 봅니다.", _schema({}, []), READ_ONLY),
}

ZOTERO_TOOLS = {
    "search": (zotero_search, "Zotero 라이브러리에서 찾습니다.", _schema({"query": STR, "limit": INT}, ["query"]), READ_ONLY),
    "collections": (zotero_collections, "Zotero 컬렉션 목록.", _schema({}, []), READ_ONLY),
    "import_library": (zotero_import, "Zotero 항목을 로컬 라이브러리로 가져옵니다(지난번 이후 바뀐 것만, full이면 전체). "
                                      "collection(key)으로 한 컬렉션만.",
                       _schema({"collection": STR, "full": BOOL}, []), LOCAL_WRITES),
    "add_item": (zotero_add, "로컬 라이브러리의 논문을 Zotero에 항목으로 만듭니다(사용자 승인 필요). " + PAPER_REF,
                 _schema({"id": STR}, ["id"]), REMOTE_WRITES),
}
