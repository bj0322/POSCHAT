# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""macOS: pywebview 창(NSWindow)의 내용을 NSSplitView로 바꿔 왼쪽에 앱 화면, 오른쪽에 WKWebView를 둔다(browser.py가 쓴다).

격리: 이 WKWebView에는 스크립트 메시지 핸들러(window.webkit.messageHandlers)를 하나도 달지 않는다.
http·https 밖의 주소, 새 창(같은 뷰에서 연다), 다운로드는 내비게이션 대리자에서 막는다.
"""
import threading

import AppKit
import Foundation
import WebKit
from objc import super  # noqa: A004
from PyObjCTools import AppHelper

import browser as browser_mod

READ_TIMEOUT = 15


class _Delegate(AppKit.NSObject):
    """WKNavigationDelegate + WKUIDelegate. 메인(UI) 스레드에서 불린다: 여기서 UI 스레드를 기다리는 호출을 하면 안 된다
    (browser.navigated() → Bridge._push()는 큐에 넣고 바로 돌아온다, ui_events·B1)."""

    def initWithOwner_(self, owner):
        self = super(_Delegate, self).init()
        if self is not None:
            self.owner = owner
        return self

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, handler):
        url = str(action.request().URL().absoluteString() or "")
        if browser_mod.allowed(url) or url == "about:blank":
            handler(getattr(WebKit, "WKNavigationActionPolicyAllow", 1))
        else:
            handler(getattr(WebKit, "WKNavigationActionPolicyCancel", 0))
            self.owner.browser.blocked(url, "http·https 주소만 열 수 있습니다.")

    def webView_decidePolicyForNavigationResponse_decisionHandler_(self, webview, response, handler):
        if response.canShowMIMEType():
            handler(WebKit.WKNavigationResponsePolicyAllow)
        else:  # 화면에 보일 수 없는 파일 = 다운로드
            handler(WebKit.WKNavigationResponsePolicyCancel)
            self.owner.browser.blocked(str(response.response().URL().absoluteString() or ""),
                                       "다운로드는 기본 브라우저에서 하세요(외부 브라우저로 열기).")

    def webView_didStartProvisionalNavigation_(self, webview, nav):
        self.owner.browser.navigated(loading=True)

    def webView_didFinishNavigation_(self, webview, nav):
        self.owner.report(webview, loading=False)
        # didFinish 시점에 webview.title()이 아직 비어 있을 때가 있어 문서 제목을 한 번 더 읽는다
        webview.evaluateJavaScript_completionHandler_("document.title", self.owner.title_handler(webview))

    def webView_didFailNavigation_withError_(self, webview, nav, error):
        self.owner.report(webview, loading=False)

    def webView_didFailProvisionalNavigation_withError_(self, webview, nav, error):
        self.owner.report(webview, loading=False)

    # 1.19 웹페이지 위 막대의 버튼(메인 스레드). hide는 메인 스레드를 기다리므로 작업 스레드로 넘긴다(B1)
    def closeBrowser_(self, sender):
        threading.Thread(target=self.owner.browser.hide, daemon=True).start()

    def openExternal_(self, sender):
        threading.Thread(target=self.owner.browser.open_external, daemon=True).start()

    def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, webview, config, action,
                                                                                  features):
        url = str(action.request().URL().absoluteString() or "")
        if browser_mod.allowed(url):
            webview.loadRequest_(action.request())  # 새 창 대신 같은 뷰에서 연다
        return None


class WKWebViewBackend:
    mode = "native"

    def __init__(self, window, browser):
        self.ns_window = getattr(window, "native", None)
        if self.ns_window is None:
            raise browser_mod.BrowserError("앱 창을 찾지 못했습니다.")
        self.browser = browser
        self.split = None
        self.view = None
        self.pane = None  # 1.19: 웹페이지 위 막대 + 웹페이지
        self.title_label = None
        self.toolbar = False
        self.main_view = None
        self.delegate = None
        self._run(self._create)

    def _run(self, fn, wait=True):
        """메인(UI) 스레드에서 fn을 실행한다. wait면 끝날 때까지 기다리고 결과를 돌려준다."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        box, done = {}, threading.Event()

        def go():
            try:
                box["value"] = fn()
            except Exception as e:
                box["error"] = e
            finally:
                done.set()

        AppHelper.callAfter(go)
        if not wait:
            return None
        if not done.wait(20):
            raise browser_mod.BrowserError("앱 화면이 응답하지 않습니다.")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _create(self):
        main = self.ns_window.contentView()
        frame = main.frame()
        config = WebKit.WKWebViewConfiguration.alloc().init()  # 메시지 핸들러 없음
        view = WebKit.WKWebView.alloc().initWithFrame_configuration_(frame, config)
        self.delegate = _Delegate.alloc().initWithOwner_(self)
        view.setNavigationDelegate_(self.delegate)
        view.setUIDelegate_(self.delegate)
        view.setAllowsBackForwardNavigationGestures_(True)
        split = AppKit.NSSplitView.alloc().initWithFrame_(frame)
        split.setVertical_(True)  # 왼쪽·오른쪽
        split.setDividerStyle_(AppKit.NSSplitViewDividerStyleThin)
        split.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        split.addSubview_(main)  # 앱 화면(pywebview WKWebView)을 왼쪽으로 옮긴다
        pane = view
        try:
            pane = self._make_pane(frame, view)
            self.toolbar = True
        except Exception:
            self.toolbar = False  # 막대를 못 만들면 앱 화면의 주소 표시줄에 버튼을 그대로 둔다
        split.addSubview_(pane)
        self.ns_window.setContentView_(split)
        pane.setHidden_(True)
        self.split, self.view, self.pane, self.main_view = split, view, pane, main

    def _make_pane(self, frame, view):
        """웹페이지와 그 위 막대(제목·기본 브라우저로 열기·닫기)를 담은 보기. 좌표는 왼쪽 아래가 원점이다."""
        bar_h = 34
        w, h = frame.size.width, frame.size.height
        pane = AppKit.NSView.alloc().initWithFrame_(frame)
        pane.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        view.setFrame_(Foundation.NSMakeRect(0, 0, w, h - bar_h))
        view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        pane.addSubview_(view)
        bar = AppKit.NSView.alloc().initWithFrame_(Foundation.NSMakeRect(0, h - bar_h, w, bar_h))
        bar.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
        close = AppKit.NSButton.buttonWithTitle_target_action_("닫기", self.delegate, "closeBrowser:")
        close.setToolTip_("브라우저 닫기")
        external = AppKit.NSButton.buttonWithTitle_target_action_("기본 브라우저로 열기", self.delegate, "openExternal:")
        external.setToolTip_("지금 페이지를 기본 브라우저로 엽니다")
        x = w - 8
        for b in (close, external):
            b.sizeToFit()
            bw, bh = b.frame().size.width, b.frame().size.height
            x -= bw
            b.setFrame_(Foundation.NSMakeRect(x, (bar_h - bh) / 2, bw, bh))
            b.setAutoresizingMask_(AppKit.NSViewMinXMargin)
            bar.addSubview_(b)
            x -= 4
        label = AppKit.NSTextField.labelWithString_("브라우저")
        label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        label.sizeToFit()
        lh = label.frame().size.height
        label.setFrame_(Foundation.NSMakeRect(10, (bar_h - lh) / 2, max(40, x - 14), lh))
        label.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        bar.addSubview_(label)
        line = AppKit.NSBox.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, w, 1))
        line.setBoxType_(AppKit.NSBoxSeparator)
        line.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        bar.addSubview_(line)
        pane.addSubview_(bar)
        self.title_label = label
        return pane

    def report(self, webview, loading=None):
        url = webview.URL()
        self._set_title(str(webview.title() or "") or (str(url.absoluteString()) if url is not None else ""))
        self.browser.navigated(url=str(url.absoluteString()) if url is not None else "", title=str(webview.title() or ""),
                               loading=loading, can_back=bool(webview.canGoBack()),
                               can_forward=bool(webview.canGoForward()))

    def title_handler(self, webview):
        def done(result, error):
            if error is None and result:
                self._set_title(str(result))
                self.browser.navigated(title=str(result))
        return done

    def _set_title(self, text):
        if self.title_label is not None and text:
            try:
                self.title_label.setStringValue_(text)
            except Exception:
                pass

    def _layout(self, ratio):
        width = self.split.frame().size.width
        self.split.setPosition_ofDividerAtIndex_(width * (1 - ratio), 0)

    def show(self, ratio):
        def go():
            self.pane.setHidden_(False)
            self.split.adjustSubviews()
            self._layout(ratio)
        self._run(go)

    def hide(self):
        def go():
            self.pane.setHidden_(True)
            self.split.adjustSubviews()
        self._run(go)

    def set_ratio(self, ratio):
        self._run(lambda: self._layout(ratio))

    def open(self, url):
        def go():
            request = Foundation.NSURLRequest.requestWithURL_(Foundation.NSURL.URLWithString_(url))
            self.view.loadRequest_(request)
        self._run(go)

    def back(self):
        self._run(lambda: self.view.goBack())

    def forward(self):
        self._run(lambda: self.view.goForward())

    def reload(self):
        self._run(lambda: self.view.reload())

    def stop(self):
        self._run(lambda: self.view.stopLoading())

    def read(self, script):
        box, done = {}, threading.Event()

        def handler(result, error):
            box["result"], box["error"] = result, error
            done.set()

        self._run(lambda: self.view.evaluateJavaScript_completionHandler_(script, handler), wait=False)
        if not done.wait(READ_TIMEOUT):
            raise browser_mod.BrowserError("웹페이지가 응답하지 않습니다.")
        if box.get("error") is not None:
            raise browser_mod.BrowserError(f"웹페이지를 읽지 못했습니다: {box['error']}")
        return str(box.get("result") or "")

    def plms_cookies(self, origin, clear=False):
        box, done = {}, threading.Event()

        def receive(cookies):
            matching = [c for c in cookies if "plms.postech.ac.kr" == str(c.domain()).lstrip(".")
                        or "plms.postech.ac.kr".endswith("." + str(c.domain()).lstrip("."))]
            if clear:
                store = self.view.configuration().websiteDataStore().httpCookieStore()
                pending = [c for c in matching if str(c.domain()).lstrip(".") == "plms.postech.ac.kr"]
                remaining = [len(pending)]
                def deleted():
                    remaining[0] -= 1
                    if remaining[0] == 0:
                        done.set()
                for cookie in pending:
                    store.deleteCookie_completionHandler_(cookie, deleted)
                if not pending:
                    done.set()
            else:
                box["cookies"] = [{"name": str(c.name()), "value": str(c.value()), "path": str(c.path())} for c in matching]
                done.set()

        self._run(lambda: self.view.configuration().websiteDataStore().httpCookieStore().getAllCookies_(receive), wait=False)
        if not done.wait(READ_TIMEOUT):
            raise browser_mod.BrowserError("PLMS 세션을 읽지 못했습니다.")
        return box.get("cookies", [])

    def screenshot(self):
        """보이는 웹페이지를 PNG로(1.16 브라우저 에이전트). 작업 스레드에서 부른다."""
        box, done = {}, threading.Event()

        def handler(image, error):
            try:
                if image is not None:
                    rep = AppKit.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
                    box["png"] = bytes(rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {}))
                box["error"] = error
            finally:
                done.set()

        self._run(lambda: self.view.takeSnapshotWithConfiguration_completionHandler_(None, handler), wait=False)
        if not done.wait(READ_TIMEOUT) or not box.get("png"):
            raise browser_mod.BrowserError("화면을 캡처하지 못했습니다.")
        return box["png"]

    def close(self):
        def go():
            if self.split is not None and self.main_view is not None:
                self.ns_window.setContentView_(self.main_view)  # 앱 화면을 원래대로
            if self.pane is not None:
                self.pane.removeFromSuperview()
        self._run(go)
        self.split = self.view = self.pane = None
