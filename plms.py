# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""로그인된 내장 브라우저의 PLMS 세션으로 수업·공지·자료를 읽는다. 인증 정보는 저장하지 않는다."""
import json
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit, unquote

import requests

import documents
from web_research import html_to_text

ORIGIN = "https://plms.postech.ac.kr"
LOGIN = ORIGIN + "/login/index.php"
MAX_BYTES = 20 * 1024 * 1024
PAGE_CHARS = 18000
READ_PATHS = {"/my/", "/", "/course/view.php", "/mod/forum/index.php", "/mod/forum/view.php",
              "/mod/forum/discuss.php", "/mod/ubboard/view.php", "/mod/ubboard/article.php",
              "/mod/resource/view.php", "/mod/folder/view.php", "/mod/page/view.php",
              "/mod/book/view.php", "/mod/book/tool/print/index.php", "/mod/assign/view.php",
              "/mod/url/view.php", "/mod/ubfile/view.php", "/local/ubion/user/index.php",
              "/local/ubion/course/syllabusV.php"}
FILE_PATHS = ("/pluginfile.php/", "/webservice/pluginfile.php/")


class PlmsError(Exception):
    pass


def safe_url(url):
    """학교 PLMS의 조회 경로만 허용한다. 인증·제출·완료 처리와 외부 리다이렉트를 막는다."""
    if len(str(url)) > 2000:
        raise PlmsError("PLMS 주소가 너무 깁니다.")
    p = urlsplit(urljoin(ORIGIN + "/", str(url)))
    if p.scheme != "https" or p.netloc != "plms.postech.ac.kr" or p.username or p.password:
        raise PlmsError("PLMS 안의 자료 주소만 읽을 수 있습니다.")
    path = p.path
    decoded = unquote(path)
    if ".." in decoded.split("/") or "\\" in decoded or any(ord(c) < 32 for c in decoded) or not (path in READ_PATHS or path.startswith(FILE_PATHS)):
        raise PlmsError("지원하지 않는 PLMS 조회 경로입니다.")
    args = parse_qs(p.query, keep_blank_values=True)
    allowed = {"id", "d", "f", "b", "a", "n", "chapterid", "section", "page", "perpage", "lang", "forceview",
               "forcedownload", "group", "search", "sort", "mode", "artid", "boardid", "bwid", "pid"}
    if set(args) - allowed or any(len(v) != 1 for v in args.values()):
        raise PlmsError("조회 외의 동작이 포함된 PLMS 주소는 읽을 수 없습니다.")
    if args.get("mode", [""])[0] not in ("", "view", "flatoldest", "flatnewest", "threaded", "nested"):
        raise PlmsError("조회 외의 게시판 동작은 허용하지 않습니다.")
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


class _Links(HTMLParser):
    """내 수업의 탐색 메뉴도 읽는다(일반 웹 본문 추출기는 nav를 제외한다)."""
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.links, self.href, self.label = base, [], None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.href = urljoin(self.base, attrs.get("href", ""))
            self.label = [attrs.get("title", "")]
        if tag == "img" and self.href:
            self.label.append(attrs.get("alt", ""))

    def handle_data(self, data):
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            title = " ".join(" ".join(self.label).split())[:200]
            if title:
                self.links.append((title, self.href))
            self.href = None


def links(raw, base):
    parser = _Links(base)
    parser.feed(raw)
    found = {}
    for title, url in parser.links:
        try:
            url = safe_url(url)
        except PlmsError:
            continue
        found.setdefault(url, {"title": title, "url": url})
    return list(found.values())


class Client:
    def __init__(self, browser, cancelled=lambda: False):
        if browser is None:
            raise PlmsError("사이드바의 PLMS에서 로그인하고 브라우저를 열어 둔 뒤 다시 요청하세요.")
        self.cancelled = cancelled
        self.session = requests.Session()
        self.session.trust_env = False  # 환경 프록시·netrc에 학교 인증 정보를 넘기지 않는다
        self.session.headers["User-Agent"] = "POSCHAT/PLMS read-only"
        try:
            cookies = browser.plms_cookies()
            for c in cookies:
                self.session.cookies.set(c["name"], c["value"], domain="plms.postech.ac.kr", path=c.get("path") or "/", secure=True)
        except Exception:
            self.session.close()
            raise PlmsError("PLMS 세션을 읽지 못했습니다. 내장 브라우저에서 로그인한 뒤 다시 시도하세요.") from None
        self._dashboard = None
        self._courses = None

    def close(self):
        self.session.cookies.clear()
        self.session.close()

    def _request(self, url, *, ajax=None):
        url = safe_url(url) if ajax is None else ORIGIN + "/lib/ajax/service.php"
        for _ in range(6):
            if self.cancelled():
                raise PlmsError("PLMS 읽기를 멈췄습니다.")
            try:
                kwargs = {"timeout": (10, 25), "allow_redirects": False, "stream": True}
                if ajax is None:
                    r = self.session.get(url, **kwargs)
                else:
                    r = self.session.post(url, params={"sesskey": ajax[0]}, json=ajax[1], **kwargs)
                with r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        if ajax is not None:
                            raise PlmsError("PLMS 로그인이 만료되었습니다. 다시 로그인하세요.")
                        dest = urljoin(url, r.headers.get("Location", ""))
                        try:
                            url = safe_url(dest)
                        except PlmsError:
                            raise PlmsError("로그인이 필요하거나 외부 자료로 연결됩니다. PLMS 브라우저에서 확인하세요.") from None
                        continue
                    if r.status_code in (401, 403):
                        raise PlmsError("PLMS 로그인 또는 수업 접근 권한을 확인하세요.")
                    if r.status_code != 200:
                        raise PlmsError(f"PLMS 응답 오류({r.status_code}). 잠시 뒤 다시 시도하세요.")
                    body = bytearray()
                    for chunk in r.iter_content(65536):
                        if self.cancelled():
                            raise PlmsError("PLMS 읽기를 멈췄습니다.")
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise PlmsError("20MB를 넘는 자료는 읽을 수 없습니다.")
                    return url, r.headers, bytes(body)
            except requests.RequestException:
                raise PlmsError("PLMS에 연결하지 못했습니다. 네트워크와 로그인 상태를 확인하세요.") from None
        raise PlmsError("PLMS 리다이렉트가 너무 많습니다.")

    def _html(self, url):
        final, headers, body = self._request(url)
        raw = body.decode("utf-8", errors="replace")
        if re.search(r'type\s*=\s*["\']password|<body[^>]*\b(?:notloggedin|guestuser)\b', raw, re.I):
            raise PlmsError("PLMS 로그인이 만료되었습니다. PLMS에서 SSO 로그인 후 다시 시도하세요.")
        if "html" not in headers.get("Content-Type", "").lower():
            raise PlmsError("웹페이지 대신 파일이 반환되었습니다. 자료 읽기를 사용하세요.")
        return final, raw

    def courses(self):
        if self._courses is not None:
            return self._courses
        final, raw = self._html(ORIGIN + "/my/")
        # 로그인 뒤 Moodle 페이지의 사용자 ID가 있어야 공개 강좌 목록을 수강 목록으로 오인하지 않는다.
        uid = re.search(r'["\']userid["\']\s*:\s*["\']?(\d+)', raw)
        logged = (uid and int(uid[1]) > 1) or bool(re.search(r'/user/profile\.php\?id=\d+|/login/logout\.php\?', raw))
        if not logged:
            raise PlmsError("로그인된 내 수업 화면을 확인하지 못했습니다. PLMS에서 로그인 상태를 확인하세요.")
        self._dashboard = raw
        courses = {}
        for item in links(raw, final):
            p = urlsplit(item["url"])
            cid = parse_qs(p.query).get("id", [""])[0]
            if p.path == "/course/view.php" and cid.isdigit() and int(cid) > 1:
                courses[cid] = {"id": cid, **item}
        # 새 Moodle 대시보드는 수강 목록을 AJAX로 늦게 불러온다. 허용된 조회 함수 하나만 사용한다.
        key = re.search(r'["\']sesskey["\']\s*:\s*["\']([a-zA-Z0-9]+)', raw)
        listed = False
        if key:
            try:
                _, _, body = self._request("", ajax=(key[1], [{"index": 0,
                    "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                    "args": {"classification": "all", "limit": 0, "offset": 0, "sort": "fullname"}}]))
                data = json.loads(body)
                result = data[0]
                if not result.get("error"):
                    listed = True
                    for c in result.get("data", {}).get("courses", []):
                        cid = str(int(c["id"]))
                        if int(cid) > 1:
                            courses[cid] = {"id": cid, "title": str(c.get("fullname") or c.get("shortname") or cid),
                                            "url": ORIGIN + "/course/view.php?id=" + cid}
            except (PlmsError, ValueError, KeyError, TypeError, IndexError):
                if self.cancelled():
                    raise PlmsError("PLMS 읽기를 멈췄습니다.") from None
        if not courses:
            # POSTECH Coursemos의 '정규 강좌 → 나의 강좌'는 기본 Moodle 대시보드와 경로가 다르다.
            try:
                final, raw = self._html(ORIGIN + "/local/ubion/user/index.php")
                for item in links(raw, final):
                    p = urlsplit(item["url"])
                    cid = parse_qs(p.query).get("id", [""])[0]
                    if p.path == "/course/view.php" and cid.isdigit() and int(cid) > 1:
                        courses[cid] = {"id": cid, **item}
            except PlmsError:
                if not listed:
                    raise PlmsError("내 수업 목록을 불러오지 못했습니다. PLMS의 내 강좌 화면을 확인하세요.") from None
        self._courses = list(courses.values())
        return self._courses

    def course(self, course_id):
        cid = str(course_id)
        course = next((c for c in self.courses() if c["id"] == cid), None)
        if not course:
            raise PlmsError("현재 로그인 계정의 수강 목록에 없는 수업입니다.")
        final, raw = self._html(course["url"])
        title, text, _ = html_to_text(raw, final)
        items = [x for x in links(raw, final) if urlsplit(x["url"]).path != "/course/view.php"
                 and urlsplit(x["url"]).path not in ("/", "/my/")]
        return {"id": cid, "title": course["title"], "url": final, "text": text[:PAGE_CHARS], "items": items[:400]}

    def read(self, course_id, url, query="", offset=0, parent=""):
        """수강 중인 수업에서 찾은 링크만 읽는다. 게시판·폴더는 상위 링크를 지정해 한 단계 더 탐색한다."""
        target = safe_url(url)
        course = self.course(course_id)
        candidates = {x["url"] for x in course["items"]}
        trail = parent if isinstance(parent, list) else ([parent] if parent else [])
        if len(trail) > 4:
            raise PlmsError("게시판·폴더는 네 단계까지 탐색할 수 있습니다.")
        for ancestor in trail:
            ancestor = safe_url(ancestor)
            if ancestor not in candidates:
                raise PlmsError("수업에서 찾은 게시판·폴더 주소가 아닙니다.")
            purl, praw = self._html(ancestor)
            candidates.update(x["url"] for x in links(praw, purl))
        if target not in candidates and target != course["url"]:
            raise PlmsError("수업에서 찾은 자료 주소만 읽을 수 있습니다. 수업 목록의 링크와 parent를 확인하세요.")
        final, headers, body = self._request(target)
        ctype = headers.get("Content-Type", "").lower()
        title = next((x["title"] for x in course["items"] if x["url"] == target), "PLMS 자료")
        items = []
        if "html" in ctype:
            raw = body.decode("utf-8", errors="replace")
            if re.search(r'type\s*=\s*["\']password', raw, re.I):
                raise PlmsError("PLMS 로그인이 만료되었습니다. 다시 로그인하세요.")
            title, text, _ = html_to_text(raw, final)
            items = links(raw, final)[:400]
        else:
            # 서버 파일명을 경로로 쓰지 않고 확장자만 취한다. 임시 파일은 읽은 즉시 지운다.
            disposition = headers.get("Content-Disposition", "")
            suffix = Path(urlsplit(final).path).suffix.lower()
            if suffix not in documents.DOCUMENT_EXTS | {".txt", ".md", ".csv"}:
                m = re.search(r'\.(pdf|docx|pptx|xlsx|xlsm|hwp|hwpx|txt|md|csv)\b', disposition, re.I)
                suffix = "." + m[1].lower() if m else (".pdf" if "application/pdf" in ctype else "")
            if suffix in {".txt", ".md", ".csv"}:
                text = body.decode("utf-8-sig", errors="replace")
            elif suffix in documents.DOCUMENT_EXTS:
                try:
                    with tempfile.TemporaryDirectory(prefix="poschat-plms-") as folder:
                        path = Path(folder) / ("material" + suffix)
                        path.write_bytes(body)
                        text = documents.extract_text(path)
                except documents.DocumentError as e:
                    raise PlmsError(str(e)) from None
            else:
                raise PlmsError("읽을 수 없는 자료 형식입니다. PDF·Office·한글·텍스트 자료를 선택하세요.")
        start = max(0, int(offset))
        if query:
            index = text.casefold().find(str(query).casefold())
            if index >= 0:
                start = max(0, index - 1000)
        return {"title": title, "url": final, "text": text[start:start + PAGE_CHARS], "offset": start,
                "total_chars": len(text), "next_offset": start + PAGE_CHARS if start + PAGE_CHARS < len(text) else None,
                "items": items}
