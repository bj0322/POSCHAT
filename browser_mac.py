# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""macOS: pywebview 창(NSWindow)의 내용을 NSSplitView로 바꿔 왼쪽에 앱 화면, 오른쪽에 WKWebView를 둔다(browser.py가 쓴다).

격리: 이 WKWebView에는 스크립트 메시지 핸들러(window.webkit.messageHandlers)를 하나도 달지 않는다.
http·https 밖의 주소, 새 창(같은 뷰에서 연다), 다운로드는 내비게이션 대리자에서 막는다.
"""
import threading

import AppKit
import Foundation  # noqa: F401
import WebKit
from objc import super  # noqa: A004
from PyObjCTools import AppHelper

import browser as browser_mod

READ_TIMEOUT = 15


class _Delegate(AppKit.NSObject):
    """WKNavigationDelegate + WKUIDelegate."""

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

    def webView_didFailNavigation_withError_(self, webview, nav, error):
        self.owner.report(webview, loading=False)

    def webView_didFailProvisionalNavigation_withError_(self, webview, nav, error):
        self.owner.report(webview, loading=False)

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
        split.addSubview_(view)
        self.ns_window.setContentView_(split)
        view.setHidden_(True)
        self.split, self.view, self.main_view = split, view, main

    def report(self, webview, loading=None):
        url = webview.URL()
        self.browser.navigated(url=str(url.absoluteString()) if url is not None else "", title=str(webview.title() or ""),
                               loading=loading, can_back=bool(webview.canGoBack()),
                               can_forward=bool(webview.canGoForward()))

    def _layout(self, ratio):
        width = self.split.frame().size.width
        self.split.setPosition_ofDividerAtIndex_(width * (1 - ratio), 0)

    def show(self, ratio):
        def go():
            self.view.setHidden_(False)
            self.split.adjustSubviews()
            self._layout(ratio)
        self._run(go)

    def hide(self):
        def go():
            self.view.setHidden_(True)
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

    def close(self):
        def go():
            if self.split is not None and self.main_view is not None:
                self.ns_window.setContentView_(self.main_view)  # 앱 화면을 원래대로
            if self.view is not None:
                self.view.removeFromSuperview()
        self._run(go)
        self.split = self.view = None
