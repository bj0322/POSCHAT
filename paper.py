# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.14 논문 읽기(POSCHAT Paper): 앱 안에서 PDF를 열고, 쪽 번호가 붙은 글자를 뽑아 채팅·에이전트에 넘긴다.

화면(web/paper.js)은 PDF.js로 PDF를 그린다. PDF 바이트는 이 모듈이 조각(base64)으로 넘긴다(read_chunk).
글자는 pypdf로 쪽마다 뽑아 캐시해 두고(page_texts), 질문·요약·비교에 쓴다. PDF의 글은 외부 데이터라서
채팅·에이전트에 넘길 때는 connectors.wrap_untrusted로 감싼다(논문 안의 지시를 따르지 않게).

연 문서는 <데이터 폴더>/research/pdfs에 둔다:
- 라이브러리 논문의 PDF(경로가 있으면 그대로, arXiv 번호만 있으면 받아서 저장)
- 주소로 받은 PDF, 화면에서 고른 파일(첨부 파일로 올린 뒤 복사)
"""
import base64
import hashlib
import re
import shutil
import threading
import time
from pathlib import Path

MAX_PDF_BYTES = 60 * 1024 * 1024
CHUNK_BYTES = 768 * 1024
MAX_PAGES_PER_READ = 12
MAX_READ_CHARS = 30000
MAX_COMPARE = 6
RECENT_MAX = 12
ARXIV_PDF = "https://arxiv.org/pdf/{}"
_ARXIV_ID = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")
# 실험 조건·결과를 담은 쪽을 고를 때 쓰는 낱말(영어·한국어)
RESULT_WORDS = re.compile(
    r"experiment|evaluation|result|setup|dataset|benchmark|baseline|accuracy|table|ablation|implementation|"
    r"실험|결과|평가|데이터|성능|비교|조건", re.I)

_lock = threading.RLock()
_docs = {}          # doc_id -> {"path", "title", "pid", ...}
_text_cache = {}    # (path, mtime, size) -> [쪽 글자]


class PaperError(Exception):
    pass


def pdf_dir():
    import research_library

    return research_library.research_dir() / "pdfs"


def _safe_stem(text):
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(text or "")).strip(" ._")
    return text[:80] or "paper"


def _check_pdf(path):
    path = Path(path)
    if not path.is_file():
        raise PaperError(f"PDF 파일을 찾지 못했습니다: {path}")
    size = path.stat().st_size
    if size > MAX_PDF_BYTES:
        raise PaperError(f"PDF가 너무 큽니다({MAX_PDF_BYTES // 1024 // 1024}MB 초과).")
    with open(path, "rb") as f:
        if b"%PDF" not in f.read(1024):
            raise PaperError("PDF 파일이 아닙니다.")
    return path


def doc_id_for(path):
    return hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:16]


# ---- 열기 ----

def download(url, dest, http=None):
    """http(s) 주소의 PDF를 dest에 받는다(크기 제한·PDF 확인). http는 시험에서 바꿔 끼운다."""
    if not re.match(r"^https?://", str(url or ""), re.I):
        raise PaperError("http·https 주소의 PDF만 받을 수 있습니다.")
    if http is None:
        from office_mcp import http  # 인증서 저장소·User-Agent를 맞춘 공용 요청
    try:
        r = http("GET", url, timeout=60, stream=True)
    except Exception as e:  # office_mcp.ToolFailure(연결 실패)
        raise PaperError(str(e))
    if getattr(r, "status_code", 200) != 200:
        raise PaperError(f"PDF를 받지 못했습니다(HTTP {r.status_code}).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    total = 0
    try:
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise PaperError(f"PDF가 너무 큽니다({MAX_PDF_BYTES // 1024 // 1024}MB 초과).")
                f.write(chunk)
        _check_pdf(tmp)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def library_pdf(paper, workspace="", http=None):
    """라이브러리 논문의 PDF 경로. 없고 arXiv 번호가 있으면 받아 두고 라이브러리에 경로를 적는다.
    작업 폴더 PDF는 라이브러리에 작업 폴더 기준 상대 경로로 적혀 있다(research.library_add)."""
    import research_library

    pdf = str(paper.get("pdf") or "")
    if pdf:
        path = Path(pdf)
        if not path.is_absolute() and workspace:
            path = Path(workspace) / pdf
        if path.is_file():
            return _check_pdf(path)
    arxiv = str(paper.get("arxiv") or "").strip()
    if arxiv:
        dest = pdf_dir() / f"arXiv-{_safe_stem(arxiv)}.pdf"
        if not dest.is_file():
            download(ARXIV_PDF.format(arxiv), dest, http=http)
        research_library.update(paper["id"], pdf=str(dest))
        return dest
    if pdf:
        raise PaperError(f"라이브러리에 적힌 PDF를 찾지 못했습니다: {pdf}")
    raise PaperError("이 논문에는 PDF가 없습니다. arXiv 논문이거나 PDF 파일을 연결한 논문만 열 수 있습니다.")


def register(path, title="", pid=None, source=""):
    """PDF를 열린 문서로 등록하고 정보를 돌려준다."""
    path = _check_pdf(path)
    did = doc_id_for(path)
    texts = page_texts(path)
    if not title:
        try:
            import research_library

            title = research_library.pdf_metadata(path).get("title") or ""
        except Exception:
            title = ""
    doc = {"id": did, "path": str(path), "title": (title or path.stem)[:200], "pid": pid, "pages": len(texts),
           "size": path.stat().st_size, "source": source, "name": path.name}
    with _lock:
        _docs[did] = doc
    return dict(doc)


def get(doc_id):
    with _lock:
        doc = _docs.get(str(doc_id or ""))
    if doc is None:
        raise PaperError("열린 논문을 찾지 못했습니다. 논문을 다시 여세요.")
    return doc


def opened():
    with _lock:
        return [dict(d) for d in _docs.values()]


def upload_chunk(upload_id, offset, data_b64, last):
    """화면에서 고른 PDF를 조각으로 받는다(research/pdfs/.incoming). 마지막 조각이면 받은 파일 경로."""
    if not re.fullmatch(r"[0-9a-f]{16,40}", str(upload_id or "")):
        raise PaperError("잘못된 업로드 번호입니다.")
    part = pdf_dir() / ".incoming" / f"{upload_id}.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    offset = int(offset or 0)
    size = part.stat().st_size if part.exists() else 0
    if offset == 0 and size:
        part.unlink()
        size = 0
    if size != offset:
        part.unlink(missing_ok=True)
        raise PaperError("파일을 받는 중 순서가 어긋났습니다. 다시 여세요.")
    chunk = base64.b64decode(data_b64 or "")
    if size + len(chunk) > MAX_PDF_BYTES:
        part.unlink(missing_ok=True)
        raise PaperError(f"PDF가 너무 큽니다({MAX_PDF_BYTES // 1024 // 1024}MB 초과).")
    with open(part, "ab") as f:
        f.write(chunk)
    return part if last else None


def import_file(src, name=""):
    """화면에서 고른 PDF(첨부로 올린 파일)를 research/pdfs로 복사한다. 같은 내용이면 같은 파일을 쓴다."""
    src = _check_pdf(src)
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
    dest = pdf_dir() / f"{_safe_stem(Path(name or src.name).stem)}-{digest}.pdf"
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    return dest


def read_chunk(doc_id, offset):
    """PDF.js에 넘길 바이트 조각. {"data": base64, "offset", "size", "done"}"""
    doc = get(doc_id)
    offset = max(0, int(offset or 0))
    with open(doc["path"], "rb") as f:
        f.seek(offset)
        data = f.read(CHUNK_BYTES)
    size = doc["size"]
    return {"data": base64.b64encode(data).decode("ascii"), "offset": offset, "size": size,
            "done": offset + len(data) >= size}


# ---- 글자 ----

def page_texts(path):
    """쪽마다의 글자 목록(1쪽이 [0]). 파일이 바뀌지 않았으면 캐시를 쓴다."""
    from pypdf import PdfReader

    path = Path(path)
    st = path.stat()
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    with _lock:
        if key in _text_cache:
            return _text_cache[key]
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        texts = [re.sub(r"[ \t]{2,}", " ", page.extract_text() or "").strip() for page in reader.pages]
    except Exception as e:
        raise PaperError(f"PDF 글자를 읽지 못했습니다: {type(e).__name__}: {e}")
    with _lock:
        if len(_text_cache) > 16:
            _text_cache.clear()
        _text_cache[key] = texts
    return texts


def parse_pages(spec, total):
    """"3", "2-5", "1,4,7-8" → [쪽 번호]. 빈 값이면 앞쪽부터. 범위를 벗어나면 PaperError."""
    spec = str(spec or "").replace(" ", "")
    if not spec:
        return list(range(1, min(total, MAX_PAGES_PER_READ) + 1))
    pages = []
    for part in spec.split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise PaperError(f"쪽 번호를 이해하지 못했습니다: {part} (예: 3, 2-5, 1,4)")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a > b:
            a, b = b, a
        pages.extend(range(a, b + 1))
    pages = sorted(set(p for p in pages if 1 <= p <= total))
    if not pages:
        raise PaperError(f"이 논문은 {total}쪽입니다.")
    return pages[:MAX_PAGES_PER_READ]


def pages_markdown(texts, pages, budget=MAX_READ_CHARS):
    """쪽 표시([p. N])를 붙인 글자. 한도를 넘으면 뒤를 줄인다."""
    out, used = [], 0
    for p in pages:
        body = texts[p - 1] or "(이 쪽에서 글자를 찾지 못했습니다. 그림이나 스캔한 쪽일 수 있습니다)"
        block = f"[p. {p}]\n{body}"
        if used + len(block) > budget:
            room = budget - used
            if room > 200:
                out.append(block[:room] + "\n... (글자 수 한도로 생략)")
            else:
                out.append(f"[p. {p}] ... (글자 수 한도로 생략)")
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


def digest(texts, budget):
    """비교용 요약 발췌: 첫 쪽(제목·초록)과 실험·결과 낱말이 많은 쪽을 쪽 순서대로, 한도 안에서."""
    if not texts:
        return ""
    scores = sorted(((len(RESULT_WORDS.findall(t)), i) for i, t in enumerate(texts) if i > 0), reverse=True)
    chosen, used = [0], len(texts[0])
    for score, i in scores:
        if score == 0 or used >= budget:
            break
        chosen.append(i)
        used += len(texts[i])
    return pages_markdown(texts, sorted(p + 1 for p in chosen), budget)


def find_pages(texts, query, limit=5):
    """낱말이 많이 나오는 쪽 번호(에이전트가 어디를 읽을지 고를 때)."""
    words = [w for w in re.split(r"\s+", str(query or "").lower()) if len(w) >= 2]
    if not words:
        return []
    scored = []
    for i, t in enumerate(texts):
        low = t.lower()
        s = sum(low.count(w) for w in words)
        if s:
            scored.append((s, i + 1))
    return [p for _, p in sorted(scored, reverse=True)[:limit]]


def cite(doc, page=None):
    title = doc.get("title") or doc.get("name") or "논문"
    return f"{title}, p. {page}" if page else title


def source_label(doc, pages=None):
    where = ""
    if pages:
        where = f" p. {pages[0]}" if len(pages) == 1 else f" pp. {pages[0]}-{pages[-1]}"
    return f"논문 PDF '{doc.get('title') or doc.get('name')}'{where}"


# ---- 최근 문서 ----

def remember(config, doc):
    """최근에 연 논문(설정 paper_recent). 경로·제목·라이브러리 id만 적는다."""
    recent = [r for r in (config.get("paper_recent") or []) if isinstance(r, dict) and r.get("path") != doc["path"]]
    recent.insert(0, {"path": doc["path"], "title": doc["title"], "pid": doc.get("pid"), "pages": doc["pages"],
                      "at": int(time.time())})
    config["paper_recent"] = recent[:RECENT_MAX]
    return config["paper_recent"]


def recent(config):
    out = []
    for r in config.get("paper_recent") or []:
        if isinstance(r, dict) and r.get("path") and Path(r["path"]).is_file():
            out.append(r)
    return out


def arxiv_id(text):
    m = _ARXIV_ID.match(str(text or "").strip())
    return m.group(1) if m else ""

