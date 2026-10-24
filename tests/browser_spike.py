# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.13 브라우저 기술 검증(CI의 Windows·macOS 작업이 실행한다): 실제 pywebview 창에 웹페이지 뷰를 붙인다.

    python tests/browser_spike.py [결과.json]

확인하는 것:
1. 네이티브 방식(Windows WebView2 컨트롤, macOS WKWebView 분할)으로 붙는지(mode == "native")
2. 로컬 페이지를 열고 주소·제목·불러오기 완료 이벤트가 오는지
3. 페이지의 글과 선택한 글, 논문 식별자(meta citation_doi)를 읽는지
4. 격리: 웹페이지 쪽에 window.pywebview가 없고, chrome.webview.hostObjects로 앱 객체에 닿지 못하며, postMessage가 앱에 오지 않는지
5. 뒤로 가기·숨기기·다시 보이기·닫기가 오류 없이 되는지
"""
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Spike Page</title>
<meta name="citation_doi" content="10.1234/poschat.5678"></head>
<body><main><h1>POSCHAT-SPIKE-OK</h1><p id="p">선택할 문장입니다.</p><a id="next" href="/two">다음</a></main>
<script>
const r = document.createRange(); r.selectNodeContents(document.getElementById('p'));
getSelection().removeAllRanges(); getSelection().addRange(r);
window.__isolation = JSON.stringify({pywebview: typeof window.pywebview,
  hostObjects: typeof (window.chrome && window.chrome.webview && window.chrome.webview.hostObjects),
  webkitHandlers: typeof (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.browserDelegate),
  postMessage: typeof (window.chrome && window.chrome.webview && window.chrome.webview.postMessage)});
// WebView2는 chrome.webview.hostObjects 프록시를 늘 넣어 둔다. 실제로 앱 객체에 닿는지 불러 본다.
window.__hostProbe = 'pending';
(async () => {
  const h = window.chrome && window.chrome.webview && window.chrome.webview.hostObjects;
  if (!h) { window.__hostProbe = 'none'; return; }
  for (const name of ['api', 'pywebview', 'bridge', 'external']) {
    try { await h[name]; window.__hostProbe = 'reachable:' + name; return; } catch (e) {}
  }
  window.__hostProbe = 'blocked';
})();
</script></body></html>"""
PAGE_TWO = "<!doctype html><title>Two</title><p>second page</p>"


def message_probe(backend):
    """WebView2: 앱 쪽에 WebMessageReceived를 달아 두고 웹페이지가 postMessage를 보내게 한 뒤, 받은 수를 센다.
    IsWebMessageEnabled=False면 함수는 남아 있어도 메시지가 앱에 오지 않아야 한다. 다른 플랫폼은 None."""
    if getattr(backend, "view", None) is None or not hasattr(backend, "_invoke"):
        return None
    from Microsoft.Web.WebView2.Core import CoreWebView2WebMessageReceivedEventArgs
    from System import EventHandler

    got = []
    on_message = EventHandler[CoreWebView2WebMessageReceivedEventArgs](lambda sender, args: got.append(1))
    backend._invoke(lambda: backend.view.CoreWebView2.add_WebMessageReceived(on_message))
    try:
        backend.read("(function(){try{window.chrome.webview.postMessage('poschat-probe');"
                     "window.chrome.webview.postMessage({probe:1});return 'sent'}catch(e){return 'threw'}})()")
        time.sleep(1.5)
    finally:
        backend._invoke(lambda: backend.view.CoreWebView2.remove_WebMessageReceived(on_message))
    return len(got)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = (PAGE_TWO if self.path.startswith("/two") else PAGE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def js_value(raw):
    """플랫폼마다 다르게 감싼 스크립트 결과(WebView2는 JSON 문자열로 한 번 더 감싼다)를 값으로."""
    for _ in range(2):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                break
    return raw


def wait_for(cond, timeout=30, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔(cp1252)에서 한글 출력이 죽지 않게
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    import webview

    import browser

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "browser-spike.json")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    report = {"platform": sys.platform, "ok": False, "steps": []}
    events = []

    window = webview.create_window("POSCHAT spike", html="<h1>app</h1>", width=1100, height=760)

    def step(name, ok, detail=""):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": str(detail)[:500]})
        print(("PASS " if ok else "FAIL ") + name, detail if not ok else "", flush=True)
        return ok

    shown = threading.Event()
    window.events.loaded += shown.set

    def run():
        try:
            # 앱 화면이 다 열린 뒤에 붙인다(실제 앱에서도 사용자가 브라우저를 여는 것은 화면이 뜬 뒤다)
            step("app window loaded", shown.wait(60), f"native={type(getattr(window, 'native', None)).__name__}")
            b = browser.Browser(browser.desktop_factory(window), on_event=events.append)
            print("... attaching the page view and opening", url, flush=True)
            b.open(url)
            step("backend", b.mode == "native", f"mode={b.mode} note={getattr(b._backend, 'note', '')}")
            loaded = wait_for(lambda: b.state["url"].startswith(url) and not b.state["loading"] and b.state["title"])
            step("navigation events", loaded, json.dumps(b.state))
            print("... reading the page", flush=True)
            page = b.read()
            step("read text", "POSCHAT-SPIKE-OK" in page["text"], page["text"][:200])
            step("read selection", "선택할 문장" in page["selection"], page["selection"])
            step("paper id", page["paper"] == "10.1234/poschat.5678", page["paper"])
            iso = js_value(b._backend.read("window.__isolation || '{}'"))
            iso = iso if isinstance(iso, dict) else {}
            probe = "pending"
            for _ in range(20):
                probe = js_value(b._backend.read("window.__hostProbe || 'none'"))
                if probe != "pending":
                    break
                time.sleep(0.25)
            iso["hostProbe"] = probe
            iso["messagesReceived"] = message_probe(b._backend)
            step("isolation", iso.get("pywebview") == "undefined" and probe in ("none", "blocked")
                 and iso.get("webkitHandlers") in ("undefined", None)
                 and iso["messagesReceived"] in (0, None), iso)
            try:
                browser.normalize("file:///C:/Windows/win.ini")
                step("file url blocked", False, "normalize accepted file:")
            except browser.BrowserError:
                step("file url blocked", True)
            b._backend.read("document.getElementById('next').click(); 'ok'")
            moved = wait_for(lambda: b.state["url"].endswith("/two") and not b.state["loading"])
            step("link navigation", moved, json.dumps(b.state))
            b.nav("back")
            back = wait_for(lambda: not b.state["url"].endswith("/two") and not b.state["loading"])
            step("back", back, json.dumps(b.state))
            b.hide()
            b.show()
            b.set_ratio(0.4)
            step("hide/show/ratio", True)
            b.close()
            step("close", True)
            report["ok"] = all(s["ok"] for s in report["steps"])
        except Exception:
            report["error"] = traceback.format_exc()
            print(report["error"], flush=True)
        finally:
            report["events"] = events[-10:]
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            window.destroy()

    def watchdog():
        time.sleep(150)
        print("TIMEOUT: steps so far", json.dumps(report["steps"], ensure_ascii=False), flush=True)
        report.setdefault("error", "timeout")
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        import os
        os._exit(3)

    threading.Thread(target=watchdog, daemon=True).start()
    print("... starting pywebview", flush=True)
    webview.start(run)
    server.shutdown()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
