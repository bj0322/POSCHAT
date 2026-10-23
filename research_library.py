"""연구 논문 라이브러리: 논문 메타데이터·분류(태그·컬렉션)·PDF 연결·메모를 이 기기에 보관하고 BibTeX으로 내보낸다.

<데이터 폴더>/research/library.json
    {"version": 1, "papers": {id: 논문}, "deleted": {id: 지운 시각}}
논문: {"id", "title", "authors", "year", "venue", "doi", "arxiv", "url", "abstract", "citations", "tags", "collections",
       "pdf", "notes", "added", "updated", "source", "zotero_key", "zotero_version"}

id는 DOI → arXiv 번호 → 제목으로 만든 짧은 해시라서, 같은 논문을 다시 넣으면 새 항목이 아니라 빈 칸을 채운다.
deleted는 동기화(sync.py)가 다른 기기에서도 지우도록 남기는 표시다.
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata

import storage

FIELDS = ("title", "authors", "year", "venue", "doi", "arxiv", "url", "abstract", "citations", "tags", "collections",
          "pdf", "notes", "source", "zotero_key", "zotero_version")
_lock = threading.RLock()


class LibraryError(Exception):
    pass


def research_dir():
    return storage.APP_DIR / "research"


def _path():
    return research_dir() / "library.json"


def load():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("papers", {})
    data.setdefault("deleted", {})
    return data


def save(data):
    research_dir().mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _path())


def _norm_title(title):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(title or "").lower())


def identity(meta):
    doi = str(meta.get("doi") or "").strip().lower()
    arxiv = re.sub(r"v\d+$", "", str(meta.get("arxiv") or "").strip())
    if doi and not doi.startswith("10.48550/arxiv."):
        return f"doi:{doi}"
    if arxiv:
        return f"arxiv:{arxiv.lower()}"
    if doi:
        return f"arxiv:{doi.split('arxiv.', 1)[1]}"
    title = _norm_title(meta.get("title"))
    if not title:
        raise LibraryError("논문에는 제목이나 DOI·arXiv 번호가 있어야 합니다.")
    return f"title:{title}"


def paper_id(meta):
    return hashlib.sha1(identity(meta).encode("utf-8")).hexdigest()[:12]


def _clean(meta):
    out = {}
    for key in FIELDS:
        if key not in meta or meta[key] in (None, ""):
            continue
        value = meta[key]
        if key in ("authors", "tags", "collections"):
            if isinstance(value, str):
                value = [v.strip() for v in re.split(r"[;,]" if key != "authors" else r";|\band\b", value) if v.strip()]
            value = [str(v).strip() for v in value if str(v).strip()]
            if key != "authors":
                value = sorted(set(value))
        elif key == "year":
            value = str(value)[:4]
        elif key == "citations":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        else:
            value = str(value).strip()
        out[key] = value
    if out.get("doi"):
        out["doi"] = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", out["doi"], flags=re.I).lower()
    if out.get("arxiv"):
        out["arxiv"] = re.sub(r"v\d+$", "", out["arxiv"])
    return out


def add(meta, now=None):
    """논문을 더한다. 이미 있으면 빈 칸만 채우고 태그·컬렉션은 합친다. (논문, 새로 더했는지)"""
    meta = _clean(meta)
    pid = paper_id(meta)
    now = now or time.time()
    with _lock:
        data = load()
        current = data["papers"].get(pid)
        if current is None:
            record = {"id": pid, "tags": [], "collections": [], "added": now, **meta, "updated": now}
            data["papers"][pid] = record
            data["deleted"].pop(pid, None)
            created = True
        else:
            for key, value in meta.items():
                if key in ("tags", "collections"):
                    current[key] = sorted(set(current.get(key) or []) | set(value))
                elif key == "citations":
                    current[key] = max(int(current.get(key) or 0), value)
                elif not current.get(key):
                    current[key] = value
            current["updated"] = now
            record, created = current, False
        save(data)
    return dict(record), created


def get(pid):
    record = load()["papers"].get(str(pid))
    if record is None:
        raise LibraryError(f"라이브러리에 없는 논문입니다: {pid}")
    return dict(record)


def find(ref):
    """id·DOI·arXiv 번호·제목 일부로 찾는다."""
    ref = str(ref or "").strip()
    papers = load()["papers"]
    if ref in papers:
        return dict(papers[ref])
    low = ref.lower().removeprefix("doi:").removeprefix("arxiv:")
    for p in papers.values():
        if low and low in (p.get("doi", ""), p.get("arxiv", "").lower()):
            return dict(p)
    norm = _norm_title(ref)
    hits = [p for p in papers.values() if norm and norm in _norm_title(p.get("title"))]
    if len(hits) == 1:
        return dict(hits[0])
    if hits:
        raise LibraryError("여러 논문이 맞습니다: " + "; ".join(f"{p['id']} {p['title']}" for p in hits[:5]))
    raise LibraryError(f"라이브러리에서 찾지 못했습니다: {ref}")


def update(pid, now=None, **fields):
    allowed = {k: v for k, v in fields.items() if k in FIELDS}
    with _lock:
        data = load()
        record = data["papers"].get(str(pid))
        if record is None:
            raise LibraryError(f"라이브러리에 없는 논문입니다: {pid}")
        for key, value in _clean(allowed).items():
            record[key] = value
        for key in ("tags", "collections", "notes", "pdf"):
            if key in allowed and allowed[key] in ("", [], None):
                record[key] = [] if key in ("tags", "collections") else ""
        record["updated"] = now or time.time()
        save(data)
    return dict(record)


def remove(pid, now=None):
    with _lock:
        data = load()
        record = data["papers"].pop(str(pid), None)
        if record is None:
            raise LibraryError(f"라이브러리에 없는 논문입니다: {pid}")
        data["deleted"][str(pid)] = now or time.time()
        save(data)
    return record


def search(query="", tag=None, collection=None, limit=50):
    papers = list(load()["papers"].values())
    if tag:
        papers = [p for p in papers if tag in (p.get("tags") or [])]
    if collection:
        papers = [p for p in papers if collection in (p.get("collections") or [])]
    if query:
        words = [w.lower() for w in str(query).split()]

        def text(p):
            return " ".join([p.get("title", ""), " ".join(p.get("authors") or []), p.get("venue", ""), p.get("abstract", ""),
                             p.get("notes", ""), " ".join(p.get("tags") or []), p.get("doi", ""), p.get("arxiv", "")]).lower()

        papers = [p for p in papers if all(w in text(p) for w in words)]
    papers.sort(key=lambda p: p.get("updated", 0), reverse=True)
    return [dict(p) for p in papers[:max(1, int(limit or 50))]]


def tags():
    counts = {}
    for p in load()["papers"].values():
        for t in p.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items()))


# ---- BibTeX ----

_BIB_ESCAPE = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}"}


def _bib_value(text):
    return "".join(_BIB_ESCAPE.get(c, c) for c in str(text))


def _ascii(text):
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")


def citation_key(p, taken=None):
    first = (p.get("authors") or ["anon"])[0]
    last = re.sub(r"[^A-Za-z]", "", _ascii(first.split(",")[0] if "," in first else first.split()[-1] if first.split() else first))
    word = next((re.sub(r"[^A-Za-z]", "", _ascii(w)) for w in str(p.get("title", "")).split()
                 if len(re.sub(r"[^A-Za-z]", "", _ascii(w))) > 3), "")
    key = f"{last.lower() or 'anon'}{p.get('year') or ''}{word.lower()}" or p["id"]
    if taken is not None:
        base, n = key, 2
        while key in taken:
            key = f"{base}{chr(ord('a') + n - 2)}"
            n += 1
        taken.add(key)
    return key


def to_bibtex(papers):
    taken, entries = set(), []
    for p in papers:
        kind = "article" if p.get("venue") and p.get("venue") != "arXiv" else "misc"
        fields = [("title", "{" + _bib_value(p.get("title", "")) + "}"),
                  ("author", _bib_value(" and ".join(p.get("authors") or [])))]
        if p.get("year"):
            fields.append(("year", p["year"]))
        if kind == "article":
            fields.append(("journal", _bib_value(p["venue"])))
        if p.get("doi"):
            fields.append(("doi", p["doi"]))
        if p.get("arxiv"):
            fields += [("eprint", p["arxiv"]), ("archivePrefix", "arXiv")]
        if p.get("url"):
            fields.append(("url", p["url"]))
        body = ",\n".join(f"  {k} = {{{v}}}" if not v.startswith("{") else f"  {k} = {{{v[1:-1]}}}" for k, v in fields if v)
        entries.append(f"@{kind}{{{citation_key(p, taken)},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


# ---- PDF에서 메타데이터 ----

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>,;]+[^\s\"<>,;.)\]])", re.I)
ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(v\d+)?", re.I)


def pdf_metadata(path):
    """PDF 정보(제목·저자)와 첫 두 쪽 글자에서 DOI·arXiv 번호·제목 후보를 뽑는다."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        info = reader.metadata or {}
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:2])
    except Exception as e:
        raise LibraryError(f"PDF를 읽지 못했습니다: {type(e).__name__}: {e}")
    meta = {"pdf": str(path), "source": "pdf"}
    title = str(info.get("/Title") or "").strip()
    if title and not re.fullmatch(r"(untitled|microsoft word.*|.*\.(docx?|tex|pdf))", title, re.I):
        meta["title"] = title
    if info.get("/Author"):
        meta["authors"] = [a.strip() for a in re.split(r";|,| and ", str(info["/Author"])) if a.strip()]
    m = DOI_RE.search(text)
    if m:
        meta["doi"] = m.group(1)
    m = ARXIV_RE.search(text)
    if m:
        meta["arxiv"] = m.group(1)
    if "title" not in meta:
        for line in text.splitlines():
            line = line.strip()
            if 15 <= len(line) <= 200 and not DOI_RE.search(line) and not re.search(r"arxiv|preprint|@|http", line, re.I):
                meta["title"] = line
                break
    return meta


def format_paper(p, long=False):
    authors = p.get("authors") or []
    who = ", ".join(authors[:4]) + (f" 외 {len(authors) - 4}명" if len(authors) > 4 else "")
    head = f"[{p['id']}] {p.get('title') or '(제목 없음)'} ({p.get('year') or '연도 미상'})"
    meta = [who, p.get("venue", "")]
    if p.get("citations") is not None:
        meta.append(f"인용 {p['citations']}회")
    lines = [head, "   " + " · ".join(m for m in meta if m)]
    ids = [f"DOI {p['doi']}" if p.get("doi") else "", f"arXiv {p['arxiv']}" if p.get("arxiv") else "",
           f"PDF {p['pdf']}" if p.get("pdf") else ""]
    if any(ids):
        lines.append("   " + " · ".join(i for i in ids if i))
    if p.get("tags") or p.get("collections"):
        lines.append(f"   태그: {', '.join(p.get('tags') or []) or '-'} · 컬렉션: {', '.join(p.get('collections') or []) or '-'}")
    if long:
        if p.get("abstract"):
            lines.append(f"   초록: {p['abstract']}")
        if p.get("notes"):
            lines.append(f"   메모: {p['notes']}")
    return "\n".join(lines)
