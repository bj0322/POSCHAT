# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""AI 브라우저 에이전트(1.16): 에이전트가 사용자에게 보이는 옆 브라우저(네이티브 웹 뷰)를 직접 조작한다.

동작: snapshot · click · type · select · scroll · wait · extract · screenshot · open · back · forward · refresh
- snapshot은 페이지의 조작할 수 있는 요소를 간단한 목록(e1, e2…)으로 만든다. ID는 그 스냅샷에서만 유효하다:
  주소가 바뀌거나(이동·새로 고침·사용자의 직접 조작) 새 스냅샷을 찍으면 예전 ID는 모두 무효다.
- 동작 전에 요소가 스냅샷 때와 같은지(태그·이름) 다시 확인하고, 다르면 하지 않는다. 동작 뒤에는 주소·제목을 다시 읽어 결과를 확인한다.
- 위험 판단(risk): 읽기·스크롤·기다리기는 바로, 같은 사이트 안 이동은 바로, 처음 가는 사이트·로컬/사설 네트워크는 승인,
  제출·삭제·전송·업로드·구매·계정 변경·로그인·비밀번호·OTP·다운로드·GitHub 병합·리뷰 제출은 언제나 승인(이번 실행 허용 없음).
  이름이 없거나 같은 이름이 여럿인 요소를 누르는 일은 한 번 더 확인한다. 파일 올리기는 하지 않는다(사용자가 직접).
- 웹페이지의 글은 외부 데이터로 감싸 AI에게 준다(connectors.wrap_untrusted). 웹페이지에는 앱 API가 없다(browser.py).
- 비밀번호·OTP 칸에 넣은 값은 기록·화면·AI 관찰에 남기지 않는다(●●●●).
- 제한: 한 번 실행에 브라우저 동작 MAX_ACTIONS번, 전체 MAX_SECONDS초, 같은 동작 3번 반복 금지. 사용자가 멈추면 즉시 멈춘다.
- 이 모듈의 함수는 작업 스레드에서 부른다. backend.read(스크립트)는 UI 스레드를 기다리므로 네이티브 처리기에서 부르지 않는다(B1).
"""
import json
import re
import secrets
import threading
import time
from urllib.parse import urlparse

import browser as browser_mod
import connectors

MAX_ACTIONS = 40
MAX_SECONDS = 600
MAX_ELEMENTS = 150
MAX_TEXT = 6000
WAIT_MAX = 15

# 요소 목록을 만드는 스크립트. 요소에 data-poschat-id="<토큰>-<번호>"를 단다(다음 스냅샷·이동 때 무효).
SNAPSHOT_SCRIPT = r"""
(() => {
  const TOKEN = %(token)s, MAX = %(max)d, MAXTEXT = %(maxtext)d;
  document.querySelectorAll('[data-poschat-id]').forEach((e) => e.removeAttribute('data-poschat-id'));
  const SEL = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], [role=checkbox], [role=radio], ' +
    '[role=tab], [role=menuitem], [role=option], [role=switch], [role=combobox], [role=textbox], [contenteditable=""], [contenteditable=true], [onclick]';
  const vw = window.innerWidth, vh = window.innerHeight;
  const label = (e) => {
    let t = e.getAttribute('aria-label') || '';
    if (!t && e.labels && e.labels.length) t = e.labels[0].innerText;
    if (!t && e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) t = l.innerText; }
    if (!t && e.tagName === 'SELECT') t = e.getAttribute('name') || e.getAttribute('title') || '';
    if (!t && e.tagName !== 'SELECT') t = e.innerText || e.value || e.getAttribute('placeholder') || e.getAttribute('title') || e.getAttribute('alt') || '';
    if (!t) { const img = e.querySelector && e.querySelector('img[alt]'); if (img) t = img.alt; }
    return String(t).replace(/\s+/g, ' ').trim().slice(0, 120);
  };
  const visible = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return null;
    const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) return null;
    return r;
  };
  const out = [];
  let n = 0;
  const all = [...document.querySelectorAll(SEL)];
  const scored = [];
  for (const e of all) {
    const r = visible(e);
    if (!r) continue;
    const inView = r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
    scored.push([inView ? 0 : 1, Math.abs(r.top), e, r, inView]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  for (const [, , e, r, inView] of scored.slice(0, MAX)) {
    n += 1;
    const id = 'e' + n;
    e.setAttribute('data-poschat-id', TOKEN + '-' + id);
    const tag = e.tagName.toLowerCase();
    const type = (e.getAttribute('type') || '').toLowerCase();
    const ac = (e.getAttribute('autocomplete') || '').toLowerCase();
    const nm = (e.getAttribute('name') || e.id || '').toLowerCase();
    const sensitive = type === 'password' || /one-time-code|cc-|current-password|new-password/.test(ac) ||
      /otp|passcode|password|passwd|pin|cvc|cvv|card/.test(nm);
    const form = e.form || (e.closest && e.closest('form'));
    const item = { id, tag, role: e.getAttribute('role') || '', type, text: label(e), name: e.getAttribute('name') || '',
      inView, disabled: !!(e.disabled || e.getAttribute('aria-disabled') === 'true'), sensitive };
    if (tag === 'a') { item.href = e.href; if (e.hasAttribute('download')) item.download = true; if (e.target) item.target = e.target; }
    if (tag === 'input' || tag === 'textarea' || e.isContentEditable) item.editable = !['button','submit','reset','checkbox','radio','file','image'].includes(type);
    if (tag === 'input' && (type === 'checkbox' || type === 'radio')) item.checked = !!e.checked;
    if (item.editable) item.value = sensitive ? (e.value ? '●●●●' : '') : String(e.value || e.innerText || '').slice(0, 80);
    if (tag === 'select') { item.value = e.value; item.options = [...e.options].slice(0, 30).map((o) => o.label || o.text); }
    if (tag === 'button' || (tag === 'input' && ['submit','image'].includes(type))) item.submit = (type || 'submit') === 'submit' && !!form;
    if (form) { item.form_action = form.action || ''; item.form_method = (form.method || 'get').toLowerCase();
      item.form_password = !!form.querySelector('input[type=password]'); }
    if (type === 'file') item.file = true;
    out.push(item);
  }
  const main = document.querySelector('article, main, [role=main]') || document.body;
  return JSON.stringify({ url: location.href, title: document.title || '', token: TOKEN, elements: out, total: all.length,
    scroll: { y: Math.round(scrollY), height: Math.round(document.documentElement.scrollHeight), viewport: vh },
    text: ((main && main.innerText) || '').slice(0, MAXTEXT) });
})()
"""

# 요소 하나에 동작한다. 스냅샷 때의 태그·이름이 그대로인지 먼저 확인한다.
ACTION_SCRIPT = r"""
(() => {
  const TOKEN = %(token)s, ID = %(id)s, OP = %(op)s, ARG = %(arg)s, SIG = %(sig)s;
  const e = document.querySelector('[data-poschat-id="' + TOKEN + '-' + ID + '"]');
  if (!e) return JSON.stringify({ error: 'stale' });
  const label = (x) => {
    let t = x.getAttribute('aria-label') || '';
    if (!t && x.labels && x.labels.length) t = x.labels[0].innerText;
    if (!t && x.id) { const l = document.querySelector('label[for="' + CSS.escape(x.id) + '"]'); if (l) t = l.innerText; }
    if (!t && x.tagName === 'SELECT') t = x.getAttribute('name') || x.getAttribute('title') || '';
    if (!t && x.tagName !== 'SELECT') t = x.innerText || x.value || x.getAttribute('placeholder') || x.getAttribute('title') || x.getAttribute('alt') || '';
    if (!t) { const img = x.querySelector && x.querySelector('img[alt]'); if (img) t = img.alt; }
    return String(t).replace(/\s+/g, ' ').trim().slice(0, 120);
  };
  if (e.tagName.toLowerCase() !== SIG.tag) return JSON.stringify({ error: 'changed' });
  if (SIG.text && label(e) !== SIG.text && !(SIG.editable && OP === 'type')) return JSON.stringify({ error: 'changed' });
  if (e.disabled) return JSON.stringify({ error: 'disabled' });
  e.scrollIntoView({ block: 'center', inline: 'nearest' });
  const fire = (t) => e.dispatchEvent(new Event(t, { bubbles: true }));
  if (OP === 'click') {
    e.focus && e.focus();
    e.click();
  } else if (OP === 'type') {
    e.focus();
    if (e.isContentEditable) { e.textContent = ARG.text; fire('input'); }
    else {
      const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(e, ARG.clear === false ? (e.value + ARG.text) : ARG.text);
      fire('input'); fire('change');
    }
    if (ARG.enter) {
      const opts = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true };
      e.dispatchEvent(new KeyboardEvent('keydown', opts)); e.dispatchEvent(new KeyboardEvent('keypress', opts));
      e.dispatchEvent(new KeyboardEvent('keyup', opts));
      const form = e.form;
      if (form && !ARG._defaultPrevented) { if (form.requestSubmit) form.requestSubmit(); else form.submit(); }
    }
  } else if (OP === 'select') {
    const opts = [...e.options];
    const o = opts.find((x) => x.value === ARG.value) || opts.find((x) => (x.label || x.text).trim() === ARG.value);
    if (!o) return JSON.stringify({ error: 'no_option', options: opts.slice(0, 30).map((x) => x.label || x.text) });
    e.value = o.value; fire('input'); fire('change');
  } else if (OP === 'scroll') {
    // 요소가 보이게 했다
  } else if (OP === 'extract') {
    return JSON.stringify({ ok: true, text: (e.innerText || e.value || '').slice(0, %(maxtext)d), url: location.href, title: document.title });
  } else return JSON.stringify({ error: 'op' });
  return JSON.stringify({ ok: true, url: location.href, title: document.title });
})()
"""

PAGE_SCRIPT = r"""
(() => {
  const OP = %(op)s, ARG = %(arg)s;
  if (OP === 'scroll') {
    const h = window.innerHeight;
    if (ARG.direction === 'top') scrollTo(0, 0);
    else if (ARG.direction === 'bottom') scrollTo(0, document.documentElement.scrollHeight);
    else scrollBy(0, (ARG.direction === 'up' ? -1 : 1) * Math.round(h * 0.8));
  }
  const main = document.querySelector('article, main, [role=main]') || document.body;
  const text = (main && main.innerText) || '';
  return JSON.stringify({ url: location.href, title: document.title, ready: document.readyState,
    found: ARG.text ? text.includes(ARG.text) : null, y: Math.round(scrollY), height: document.documentElement.scrollHeight });
})()
"""

# 위험한 동작을 가리키는 낱말(버튼·링크의 이름, 폼 주소). 맞으면 언제나 승인.
RISKY = re.compile(
    r"(?i)\b(submit|send|delete|remove|destroy|erase|upload|purchase|buy|checkout|pay|payment|order|subscribe|unsubscribe|donate|"
    r"sign\s*in|log\s*in|login|sign\s*up|register|password|passcode|otp|verify|2fa|account|transfer|withdraw|"
    r"merge|squash|rebase and merge|approve|request changes|submit review|close issue|close pull request|publish|post|comment|reply|"
    r"install|download|deploy|release|invite|share)\b"
    r"|(제출|전송|보내기|삭제|지우기|제거|업로드|올리기|구매|결제|주문|구독|해지|후원|로그인|로그아웃|회원\s*가입|비밀번호|인증|계정|"
    r"송금|이체|출금|병합|승인|리뷰\s*제출|게시|등록|댓글|답글|설치|다운로드|배포|초대|공유)")
DOWNLOAD_EXT = re.compile(r"(?i)\.(exe|msi|dmg|pkg|apk|bat|cmd|ps1|sh|jar|zip|7z|rar|tar|gz|iso|deb|rpm|appimage|vbs|scr)(\?|#|$)")
GENERIC = {"", "more", "더보기", "...", "…", "click", "here", "여기", "link", "button", "x", "×", "열기", "open", "menu", "메뉴"}


class AgentBrowserError(Exception):
    pass


def host_of(url):
    try:
        return (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def site_of(host):
    """같은 사이트로 보는 범위: 마지막 두 마디(co.kr 같은 경우 세 마디)."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "ac", "or", "go", "ne", "re", "com", "edu", "gov") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def local_host(host):
    """로컬·사설 네트워크(127.x, localhost, 10.x, 172.16-31.x, 192.168.x, *.local)."""
    import ipaddress

    if host in ("localhost",) or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def classify(action, element=None, page=None, extra=None):
    """동작의 위험도: ('auto'|'ask'|'always', 이유). always는 '이번 실행 동안 허용'이 없는 승인."""
    extra = extra or {}
    if action in ("snapshot", "extract", "scroll", "wait", "screenshot", "back", "forward", "refresh"):
        return "auto", ""
    if action == "upload":
        return "deny", "파일 올리기는 에이전트가 하지 않습니다. 사용자가 직접 하세요."
    el = element or {}
    words = " ".join(str(el.get(k) or "") for k in ("text", "name", "form_action")) + " " + str(extra.get("text") or "")
    if action == "type":
        if el.get("sensitive") or el.get("form_password"):
            return "always", "비밀번호·인증 코드 같은 민감한 칸에 입력"
        if extra.get("enter"):
            return "always", "입력한 뒤 Enter로 폼 제출"
        return "auto", ""
    if action == "select":
        return "auto", ""
    if action == "click":
        if el.get("file"):
            return "deny", "파일 올리기는 에이전트가 하지 않습니다. 사용자가 직접 하세요."
        href = str(el.get("href") or "")
        if el.get("download") or DOWNLOAD_EXT.search(href):
            return "always", "파일 내려받기(내려받은 파일은 실행하지 않습니다)"
        if el.get("submit") or (el.get("form_method") == "post" and el.get("tag") in ("button", "input")):
            return "always", "폼 제출"
        if RISKY.search(words):
            return "always", "제출·삭제·전송·로그인·결제·병합 같은 되돌리기 어려운 동작일 수 있음"
        if href.startswith("javascript:"):
            return "ask", "스크립트 링크"
        if el.get("ambiguous"):
            return "ask", "이름이 없거나 같은 이름의 요소가 여럿이라 무엇을 누르는지 확인이 필요"
        return "auto", ""
    return "ask", ""


class BrowserAgent:
    """에이전트 한 번 실행(Agent.run) 동안의 브라우저 조작 상태."""

    def __init__(self, browser, confirm, on_progress=None, cancelled=lambda: False, paused=None):
        self.browser = browser            # browser.Browser
        self.confirm = confirm            # (kind, title, detail) -> bool
        self.on_progress = on_progress    # (dict) -> None: 화면(브라우저 막대·채팅)에 진행 상황
        self.cancelled = cancelled
        self.paused = paused or threading.Event()   # set이면 다음 동작 전에 기다린다
        self.snapshot = None              # 최근 스냅샷 {"token", "url", "elements": {id: el}}
        self.actions = 0
        self.started = time.monotonic()
        self.recent = []
        self.sites = set()                # 이번 실행에서 승인했거나 시작한 사이트
        self.expect_nav = False
        self.user_moved = False
        start = host_of(browser.state.get("url")) if browser is not None else ""
        if start:
            self.sites.add(site_of(start))

    # browser.navigated에서 부른다(UI 스레드일 수 있다 — 막지 않고 표시만 한다)
    def on_navigated(self, url):
        if self.snapshot and url and url != self.snapshot.get("url"):
            self.snapshot = None
            if not self.expect_nav:
                self.user_moved = True

    def _emit(self, **info):
        if self.on_progress:
            try:
                self.on_progress({"elapsed": round(time.monotonic() - self.started, 1), "count": self.actions,
                                  "limit": MAX_ACTIONS, **info})
            except Exception:
                pass

    def _backend(self):
        b = self.browser
        if b is None or not b.visible or b._backend is None:
            raise AgentBrowserError("브라우저가 열려 있지 않습니다. 사이드바의 브라우저를 먼저 여세요.")
        return b._backend

    def _eval(self, script):
        raw = self._backend().read(script)
        data = raw
        for _ in range(2):  # WebView2·안드로이드는 JSON 문자열을 한 번 더 감싼다
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except ValueError:
                    break
        if not isinstance(data, dict):
            raise AgentBrowserError("웹페이지에서 결과를 받지 못했습니다. 페이지가 다 열린 뒤 다시 시도하세요.")
        return data

    def _guard(self, action, args):
        if self.cancelled():
            raise AgentBrowserError("사용자가 멈췄습니다.")
        while self.paused.is_set():
            self._emit(action=action, status="paused")
            if self.cancelled():
                raise AgentBrowserError("사용자가 멈췄습니다.")
            time.sleep(0.2)
        if self.actions >= MAX_ACTIONS:
            raise AgentBrowserError(f"브라우저 동작 한도({MAX_ACTIONS}번)에 닿았습니다. 지금까지의 결과로 마무리하세요.")
        if time.monotonic() - self.started > MAX_SECONDS:
            raise AgentBrowserError(f"브라우저 작업 시간 한도({MAX_SECONDS // 60}분)를 넘었습니다. 마무리하세요.")
        key = json.dumps([action, args], sort_keys=True, ensure_ascii=False)
        if self.recent[-2:] == [key, key] and action not in ("wait", "scroll", "snapshot"):
            raise AgentBrowserError("같은 동작을 세 번 반복하려고 합니다. 다른 방법을 쓰거나 마무리하세요.")
        self.recent = (self.recent + [key])[-6:]
        self.actions += 1

    def _note(self):
        if self.user_moved:
            self.user_moved = False
            return "\n(사용자가 브라우저에서 직접 페이지를 바꿨습니다. 예전 요소 ID는 무효입니다. browser_snapshot으로 다시 보세요.)"
        return ""

    def _approve(self, level, title, detail):
        if level == "auto":
            return True
        kind = "send" if level == "always" else "browser"
        return self.confirm(kind, title, detail)

    def _check_site(self, url, verb):
        """처음 가는 사이트·로컬/사설 네트워크로의 이동은 승인. 막힌 주소는 열지 않는다."""
        if not browser_mod.allowed(url):
            raise AgentBrowserError("http·https 주소만 열 수 있습니다(file:, javascript:, 앱 내부 주소는 막힘).")
        host = host_of(url)
        site = site_of(host)
        if local_host(host):
            if not self.confirm("browser", f"브라우저: 로컬·사설 네트워크 주소 {verb}",
                                f"{url}\n\n이 PC나 내부망의 서비스(공유기·사내 서버·Jupyter 등)입니다. 에이전트가 접근해도 될 때만 허용하세요."):
                return False
            return True
        if site in self.sites:
            return True
        if self.confirm("browser", f"브라우저: 새 사이트 {verb}", f"{url}\n\n이번 작업에서 처음 가는 사이트({site})입니다. "
                        "웹페이지의 지시로 주소에 정보를 실어 보내는 일을 막기 위해 주소를 확인하세요."):
            self.sites.add(site)
            return True
        return False

    def _wait_loaded(self, seconds=10):
        end = time.monotonic() + seconds
        time.sleep(0.3)
        while time.monotonic() < end and not self.cancelled():
            if not self.browser.state.get("loading"):
                try:
                    if self._eval(PAGE_SCRIPT % {"op": json.dumps("ready"), "arg": "{}"}).get("ready") == "complete":
                        return
                except (AgentBrowserError, browser_mod.BrowserError):
                    pass
            time.sleep(0.25)

    def _after(self, before_url):
        """동작 뒤 다시 확인: 주소·제목, 막힌 주소로 갔으면 되돌린다."""
        self._wait_loaded(8)
        state = self._eval(PAGE_SCRIPT % {"op": json.dumps("state"), "arg": "{}"})
        url = state.get("url") or ""
        moved = url != before_url
        if moved:
            self.snapshot = None
        if url and not browser_mod.allowed(url):
            try:
                self.browser.nav("back")  # 오류 페이지·막힌 주소: 앞 페이지로 돌아간다
                self._wait_loaded(5)
            except browser_mod.BrowserError:
                self.browser.open(browser_mod.HOME_URL)
            self.snapshot = None
            raise AgentBrowserError("허용하지 않는 주소(또는 열 수 없는 페이지)로 이동해 앞 페이지로 돌아왔습니다.")
        if moved and site_of(host_of(url)) not in self.sites and not local_host(host_of(url)):
            note = f"\n다른 사이트로 이동했습니다(리다이렉트 포함): {url}. 이 사이트에서 조작하려면 승인이 필요합니다."
        else:
            note = ""
        return url, state.get("title") or "", moved, note

    # ---- 동작 ----

    def take_snapshot(self):
        self._guard("snapshot", {})
        self.expect_nav = False
        token = "p" + secrets.token_hex(4)
        data = self._eval(SNAPSHOT_SCRIPT % {"token": json.dumps(token), "max": MAX_ELEMENTS, "maxtext": MAX_TEXT})
        if not browser_mod.allowed(data.get("url") or ""):
            raise AgentBrowserError("이 페이지는 읽을 수 없습니다.")
        elements = data.get("elements") or []
        counts = {}
        for el in elements:
            key = (el.get("text") or "").lower()
            counts[key] = counts.get(key, 0) + 1
        for el in elements:
            key = (el.get("text") or "").lower()
            el["ambiguous"] = key in GENERIC or counts.get(key, 0) > 1
        self.snapshot = {"token": token, "url": data.get("url"), "elements": {e["id"]: e for e in elements}}
        self.user_moved = False
        lines = [f"주소: {data.get('url')}", f"제목: {data.get('title')}",
                 f"스크롤: {data['scroll']['y']}/{data['scroll']['height']} (화면 높이 {data['scroll']['viewport']})",
                 f"조작할 수 있는 요소 {len(elements)}개" + (f"(전체 {data.get('total')}개 중 화면 가까운 것)" if data.get("total", 0) > len(elements) else ""),
                 "id | 종류 | 이름 | 정보"]
        for el in elements:
            kind = el["tag"] + (f"[{el['type']}]" if el.get("type") else "") + (f"({el['role']})" if el.get("role") else "")
            info = []
            if el.get("href"):
                info.append("→ " + el["href"][:120])
            if el.get("editable"):
                info.append(f"값='{el.get('value', '')}'")
            if el.get("options"):
                info.append("선택지: " + " / ".join(el["options"][:10]))
            for flag, label in (("disabled", "비활성"), ("sensitive", "민감한 칸"), ("submit", "폼 제출"), ("download", "다운로드"),
                                ("file", "파일 올리기"), ("ambiguous", "이름 모호")):
                if el.get(flag):
                    info.append(label)
            if "checked" in el:
                info.append("체크됨" if el["checked"] else "체크 안 됨")
            if not el.get("inView"):
                info.append("화면 밖")
            lines.append(f"{el['id']} | {kind} | {el.get('text') or '(이름 없음)'} | {', '.join(info)}")
        body = "\n".join(lines) + "\n\n[페이지 글(앞부분)]\n" + (data.get("text") or "")
        self._emit(action="snapshot", status="done", url=data.get("url"), title=data.get("title"),
                   summary=f"요소 {len(elements)}개")
        return connectors.wrap_untrusted(body, f"웹페이지 {data.get('url')}") + \
            "\n(요소 ID는 이 스냅샷에서만 유효합니다. 페이지가 바뀌면 다시 snapshot 하세요.)"

    def _element(self, eid):
        if self.snapshot is None:
            raise AgentBrowserError("유효한 스냅샷이 없습니다(페이지가 바뀌었거나 아직 찍지 않음). 먼저 browser_snapshot 하세요." + self._note())
        el = self.snapshot["elements"].get(str(eid))
        if el is None:
            raise AgentBrowserError(f"스냅샷에 '{eid}' 요소가 없습니다. 요소는 스냅샷 목록의 id(e1, e2…)로 고르세요.")
        return el

    def _act(self, op, el, arg=None):
        sig = {"tag": el["tag"], "text": el.get("text") or "", "editable": bool(el.get("editable"))}
        res = self._eval(ACTION_SCRIPT % {"token": json.dumps(self.snapshot["token"]), "id": json.dumps(el["id"]),
                                          "op": json.dumps(op), "arg": json.dumps(arg or {}, ensure_ascii=False),
                                          "sig": json.dumps(sig, ensure_ascii=False), "maxtext": MAX_TEXT})
        err = res.get("error")
        if err in ("stale", "changed"):
            self.snapshot = None
            raise AgentBrowserError("페이지가 스냅샷 이후 바뀌어 그 요소를 확인할 수 없습니다. browser_snapshot으로 다시 보세요.")
        if err == "disabled":
            raise AgentBrowserError("비활성화된 요소입니다.")
        if err == "no_option":
            raise AgentBrowserError("그 선택지가 없습니다. 선택지: " + " / ".join(res.get("options") or []))
        if err:
            raise AgentBrowserError("동작하지 못했습니다.")
        return res

    def _describe(self, el):
        return f"{el['id']} {el['tag']}{('[' + el['type'] + ']') if el.get('type') else ''} '{el.get('text') or '(이름 없음)'}'"

    def click(self, eid):
        el = self._element(eid)
        self._guard("click", {"id": eid})
        level, why = classify("click", el)
        if level == "deny":
            raise AgentBrowserError(why)
        href = el.get("href") or ""
        if href and browser_mod.allowed(href) and level == "auto" and site_of(host_of(href)) not in self.sites:
            if not self._check_site(href, "이동"):
                return self._denied("click", el)
        elif href and not href.startswith("javascript:") and not browser_mod.allowed(href) and not href.startswith("#"):
            raise AgentBrowserError("http·https가 아닌 링크는 열지 않습니다.")
        detail = f"{self.snapshot['url']}\n누를 요소: {self._describe(el)}" + (f"\n이동할 주소: {href}" if href else "") + \
            (f"\n폼 보낼 곳: {el.get('form_action')}" if el.get("form_action") else "") + (f"\n\n주의: {why}" if why else "")
        if not self._approve(level, "브라우저: 누르기", detail):
            return self._denied("click", el)
        before = self.snapshot["url"]
        self._emit(action="click", status="running", target=el.get("text"))
        self.expect_nav = True
        self._act("click", el)
        url, title, moved, note = self._after(before)
        self.expect_nav = False
        self._emit(action="click", status="done", url=url, title=title, summary=self._describe(el))
        return (f"눌렀습니다: {self._describe(el)}\n지금 주소: {url}\n제목: {title}"
                + ("\n페이지가 바뀌었습니다. 요소를 다시 보려면 browser_snapshot." if moved else "") + note + self._note())

    def type(self, eid, text, enter=False, clear=True):
        el = self._element(eid)
        self._guard("type", {"id": eid, "enter": bool(enter)})
        if not el.get("editable"):
            raise AgentBrowserError("글을 넣을 수 있는 칸이 아닙니다.")
        level, why = classify("type", el, extra={"enter": enter})
        secret = bool(el.get("sensitive") or el.get("form_password"))
        shown = "●●●●" if secret else str(text)[:500]
        detail = f"{self.snapshot['url']}\n칸: {self._describe(el)}\n넣을 값: {shown}" + ("\n입력한 뒤 Enter(폼 제출)" if enter else "") + \
            (f"\n\n주의: {why}" if why else "")
        if not self._approve(level, "브라우저: 입력", detail):
            return self._denied("type", el)
        before = self.snapshot["url"]
        self._emit(action="type", status="running", target=el.get("text"))
        self.expect_nav = bool(enter)
        self._act("type", el, {"text": str(text)[:5000], "enter": bool(enter), "clear": bool(clear)})
        url, title, moved, note = self._after(before)
        self.expect_nav = False
        self._emit(action="type", status="done", url=url, summary=f"{self._describe(el)} ← {shown[:40]}")
        return (f"입력했습니다: {self._describe(el)} ← {shown}" + ("\n(Enter로 제출)" if enter else "")
                + (f"\n지금 주소: {url}" if moved else "") + note + self._note())

    def select(self, eid, value):
        el = self._element(eid)
        self._guard("select", {"id": eid, "value": value})
        if el["tag"] != "select":
            raise AgentBrowserError("선택 목록(select)이 아닙니다.")
        self._emit(action="select", status="running", target=el.get("text"))
        self._act("select", el, {"value": str(value)})
        self._emit(action="select", status="done", summary=f"{self._describe(el)} = {value}")
        return f"골랐습니다: {self._describe(el)} = {value}" + self._note()

    def scroll(self, direction="down", eid=""):
        self._guard("scroll", {"direction": direction, "id": eid})
        if eid:
            el = self._element(eid)
            self._act("scroll", el)
            return f"{self._describe(el)}이(가) 보이게 스크롤했습니다." + self._note()
        if direction not in ("up", "down", "top", "bottom"):
            raise AgentBrowserError("direction은 up·down·top·bottom 중 하나입니다.")
        st = self._eval(PAGE_SCRIPT % {"op": json.dumps("scroll"), "arg": json.dumps({"direction": direction})})
        self._emit(action="scroll", status="done", summary=direction)
        return f"스크롤했습니다({direction}): {st.get('y')}/{st.get('height')}. 새 요소를 보려면 browser_snapshot." + self._note()

    def wait(self, seconds=2, text=""):
        self._guard("wait", {"seconds": seconds, "text": text})
        seconds = max(0.5, min(WAIT_MAX, float(seconds or 2)))
        end = time.monotonic() + seconds
        found = None
        while time.monotonic() < end and not self.cancelled():
            st = self._eval(PAGE_SCRIPT % {"op": json.dumps("state"), "arg": json.dumps({"text": str(text)[:200]})})
            found = st.get("found")
            if text and found:
                break
            if not text and st.get("ready") == "complete" and not self.browser.state.get("loading"):
                break
            time.sleep(0.3)
        self._emit(action="wait", status="done", summary=str(text)[:40] or f"{seconds}초")
        if text:
            return ("페이지에 글이 나타났습니다: " if found else f"{seconds}초 안에 글이 나타나지 않았습니다: ") + str(text)[:200] + self._note()
        return "페이지가 다 열렸습니다." + self._note()

    def extract(self, eid=""):
        self._guard("extract", {"id": eid})
        if eid:
            el = self._element(eid)
            res = self._act("extract", el)
            text, url = res.get("text") or "", res.get("url") or ""
        else:
            page = self.browser.read()
            text, url = browser_mod.page_markdown(page), page["url"]
        self._emit(action="extract", status="done", summary=f"{len(text)}자")
        return connectors.wrap_untrusted(text[:20000], f"웹페이지 {url}") + self._note()

    def screenshot(self):
        self._guard("screenshot", {})
        backend = self._backend()
        fn = getattr(backend, "screenshot", None)
        if fn is None:
            raise AgentBrowserError("이 실행 방식에서는 웹페이지 화면을 캡처할 수 없습니다. browser_snapshot으로 내용을 보세요.")
        png = fn()
        self._emit(action="screenshot", status="done", summary=f"{len(png) // 1024}KB")
        return png

    def open(self, url):
        self._guard("open", {"url": url})
        try:
            target = browser_mod.normalize(url)
        except browser_mod.BrowserError as e:
            raise AgentBrowserError(str(e))
        if not self._check_site(target, "열기"):
            return "사용자가 이 주소를 여는 것을 거부했습니다."
        self.expect_nav = True
        self._emit(action="open", status="running", url=target)
        before = self.browser.state.get("url") or ""
        self.browser.open(target)
        url_now, title, _, note = self._after(before)
        self.expect_nav = False
        self.snapshot = None
        self._emit(action="open", status="done", url=url_now, title=title)
        return f"열었습니다: {url_now}\n제목: {title}{note}\n요소를 보려면 browser_snapshot."

    def nav(self, action):
        self._guard(action, {})
        before = self.browser.state.get("url") or ""
        self.expect_nav = True
        self.browser.nav({"refresh": "reload"}.get(action, action))
        url, title, _, note = self._after(before)
        self.expect_nav = False
        self.snapshot = None
        self._emit(action=action, status="done", url=url, title=title)
        verb = {"back": "뒤로", "forward": "앞으로", "refresh": "새로 고침"}[action]
        return f"{verb} 했습니다: {url}\n제목: {title}{note}"

    def _denied(self, action, el):
        self._emit(action=action, status="denied", summary=self._describe(el))
        return f"사용자가 거부했습니다: {self._describe(el)}. 다시 시도하지 마세요."
