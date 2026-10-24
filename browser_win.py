# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Windows: pywebview 창(WinForms Form)에 WebView2 컨트롤을 하나 더 붙여 웹페이지를 띄운다(browser.py가 쓴다).

pywebview(edgechromium)가 이미 불러 둔 WebView2 .NET 어셈블리를 그대로 쓴다. 폼의 오른쪽에 웹페이지 뷰를,
그 왼쪽에 크기 조절 막대(Splitter)를 붙이고, 앱 화면(pywebview의 WebView2)은 남은 자리를 채운다.

격리: 이 뷰에는 host object·WebMessage를 쓰지 않고(설정에서 끈다) 개발자 도구도 끈다. 프로필 폴더를 따로 둔다.
"""
import threading

import browser as browser_mod
from webview.platforms import edgechromium  # noqa: F401  WebView2 어셈블리 참조(clr.AddReference)를 불러 둔다

import System.Windows.Forms as WinForms  # noqa: E402
from System import Func, Type  # noqa: E402
from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState  # noqa: E402
from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2  # noqa: E402

READ_TIMEOUT_MS = 15000


class WebView2Backend:
    mode = "native"

    def __init__(self, window, browser):
        self.form = getattr(window, "native", None)
        if self.form is None or not hasattr(self.form, "Controls"):
            raise browser_mod.BrowserError("앱 창을 찾지 못했습니다.")
        self.browser = browser
        self.view = None
        self.splitter = None
        self.ready = threading.Event()
        self.error = None
        self.pending = None
        self.ratio = browser.ratio
        self._invoke(self._create)

    def _invoke(self, fn):
        """폼의 UI 스레드에서 fn을 실행하고 결과를 돌려준다(예외는 그대로 다시 낸다)."""
        box = {}

        def run():
            try:
                box["value"] = fn()
            except Exception as e:  # .NET 예외도 여기로 온다
                box["error"] = e

        if self.form.InvokeRequired:
            self.form.Invoke(Func[Type](run))
        else:
            run()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    # ---- 만들기 ----

    def _create(self):
        view = WebView2()
        props = CoreWebView2CreationProperties()
        props.UserDataFolder = str(browser_mod.profile_dir())
        view.CreationProperties = props
        view.Dock = WinForms.DockStyle.Right
        view.Visible = False
        splitter = WinForms.Splitter()
        splitter.Dock = WinForms.DockStyle.Right
        splitter.Width = 6
        splitter.MinSize = 320
        splitter.MinExtra = 360
        splitter.Visible = False
        splitter.SplitterMoved += self._on_split
        # 도킹은 컨트롤 순서의 뒤쪽부터: 웹페이지(맨 바깥) → 막대 → 앱 화면(Fill, 맨 앞)
        self.form.Controls.Add(splitter)
        self.form.Controls.Add(view)
        main = getattr(getattr(self.form, "browser", None), "webview", None)
        if main is not None:
            main.BringToFront()
        view.CoreWebView2InitializationCompleted += self._on_ready
        view.EnsureCoreWebView2Async(None)
        self.view, self.splitter = view, splitter

    def _on_ready(self, sender, args):
        if not args.IsSuccess:
            self.error = str(args.InitializationException)
            self.ready.set()
            return
        core = self.view.CoreWebView2
        settings = core.Settings
        settings.AreHostObjectsAllowed = False  # 웹페이지가 앱 객체를 부를 길을 막는다
        settings.IsWebMessageEnabled = False
        settings.AreDevToolsEnabled = False
        settings.IsStatusBarEnabled = True
        core.NavigationStarting += self._on_starting
        core.NavigationCompleted += self._on_completed
        core.SourceChanged += lambda s, e: self._report()
        core.DocumentTitleChanged += lambda s, e: self._report()
        core.HistoryChanged += lambda s, e: self._report()
        core.NewWindowRequested += self._on_new_window
        core.PermissionRequested += self._on_permission
        try:
            core.DownloadStarting += self._on_download
        except Exception:
            pass  # 오래된 WebView2 런타임
        self.ready.set()
        if self.pending:
            url, self.pending = self.pending, None
            core.Navigate(url)

    # ---- 이벤트 ----

    def _report(self, loading=None):
        core = self.view.CoreWebView2 if self.view is not None else None
        if core is None:
            return
        self.browser.navigated(url=str(core.Source or ""), title=str(core.DocumentTitle or ""), loading=loading,
                               can_back=bool(core.CanGoBack), can_forward=bool(core.CanGoForward))

    def _on_starting(self, sender, e):
        url = str(e.Uri or "")
        if not browser_mod.allowed(url) and url != "about:blank":
            e.Cancel = True
            self.browser.blocked(url, "http·https 주소만 열 수 있습니다.")
            return
        self.browser.navigated(loading=True)

    def _on_completed(self, sender, e):
        self._report(loading=False)

    def _on_new_window(self, sender, e):
        e.Handled = True  # 새 창 대신 같은 뷰에서 연다
        url = str(e.Uri or "")
        if browser_mod.allowed(url):
            self.view.CoreWebView2.Navigate(url)

    def _on_permission(self, sender, e):
        e.State = CoreWebView2PermissionState.Deny  # 카메라·마이크·위치·알림 등

    def _on_download(self, sender, e):
        e.Cancel = True
        self.browser.blocked(str(e.DownloadOperation.Uri or ""), "다운로드는 기본 브라우저에서 하세요(외부 브라우저로 열기).")

    def _on_split(self, sender, e):
        width = self.form.ClientSize.Width
        if width > 0 and self.view is not None:
            self.ratio = self.view.Width / width
            self.browser.ratio = round(self.ratio, 3)

    # ---- browser.Browser가 부른다 ----

    def _layout(self, ratio):
        self.view.Width = max(320, int(self.form.ClientSize.Width * ratio))

    def show(self, ratio):
        def go():
            self._layout(ratio)
            self.splitter.Visible = True
            self.view.Visible = True
        self._invoke(go)

    def hide(self):
        def go():
            self.view.Visible = False
            self.splitter.Visible = False
        self._invoke(go)

    def set_ratio(self, ratio):
        self._invoke(lambda: self._layout(ratio))

    def open(self, url):
        def go():
            if self.view.CoreWebView2 is None:
                self.pending = url
            else:
                self.view.CoreWebView2.Navigate(url)
        self._invoke(go)

    def _core_call(self, name):
        def go():
            core = self.view.CoreWebView2
            if core is not None:
                getattr(core, name)()
        self._invoke(go)

    def back(self):
        self._core_call("GoBack")

    def forward(self):
        self._core_call("GoForward")

    def reload(self):
        self._core_call("Reload")

    def stop(self):
        self._core_call("Stop")

    def read(self, script):
        if not self.ready.wait(20):
            raise browser_mod.BrowserError("웹페이지 뷰를 준비하지 못했습니다.")
        if self.error:
            raise browser_mod.BrowserError(f"WebView2를 시작하지 못했습니다: {self.error}")
        task = self._invoke(lambda: self.view.CoreWebView2.ExecuteScriptAsync(script))
        # UI 스레드 밖(이 함수를 부른 작업 스레드)에서 기다린다. UI 스레드가 비어 있어야 결과가 온다.
        if not task.Wait(READ_TIMEOUT_MS):
            raise browser_mod.BrowserError("웹페이지가 응답하지 않습니다.")
        return str(task.Result)

    def close(self):
        def go():
            for control in (self.view, self.splitter):
                if control is not None:
                    self.form.Controls.Remove(control)
                    control.Dispose()
        self._invoke(go)
        self.view = self.splitter = None
