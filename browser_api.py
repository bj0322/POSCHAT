# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""브라우저(1.13) 화면 API: main.Bridge가 상속한다. 웹페이지 뷰 자체는 browser.py가 다룬다.

화면(web/browser.js) → browser_*(...) 호출, 브라우저 → 화면은 {"type": "browser"} 이벤트.
"""
import base64
import sys
import uuid

import attachments
import browser
import connectors

# 안드로이드는 android_main이 이 값을 정한다(Kotlin WebView를 다루는 백엔드 만들기).
android_factory = None


class BrowserApi:
    _browser_obj = None

    def _browser(self, create=True):
        if self._browser_obj is None and create:
            factory = android_factory
            if factory is None:
                window = getattr(self, "_window", None)
                if window is None or not hasattr(window, "events"):
                    raise browser.BrowserError("이 실행 방식에서는 브라우저를 쓸 수 없습니다.")
                factory = browser.desktop_factory(window)
            ratio = float(self._config.get("browser_ratio") or browser.DEFAULT_RATIO)
            self._browser_obj = browser.Browser(factory, on_event=self._browser_event, ratio=ratio)
        return self._browser_obj

    def _browser_event(self, event):
        self._push({"type": "browser", **event})

    def _browser_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except browser.BrowserError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # 네이티브 뷰 오류(.NET·Objective-C)도 화면에 알린다
            return {"ok": False, "error": f"브라우저 오류: {type(e).__name__}: {e}"}

    def browser_state(self):
        b = self._browser(create=False)
        available = android_factory is not None or sys.platform in ("win32", "darwin") or b is not None
        state = dict(b.state, visible=b.visible, mode=b.mode) if b else {"visible": False, "url": "", "title": ""}
        return {"ok": True, "available": available, "ratio": b.ratio if b else
                float(self._config.get("browser_ratio") or browser.DEFAULT_RATIO), **state}

    def browser_open(self, text):
        return self._browser_call(lambda: {"url": self._browser().open(text)})

    def browser_show(self):
        return self._browser_call(lambda: self._browser().show())

    def browser_hide(self):
        b = self._browser(create=False)
        return self._browser_call(lambda: b.hide() if b else None)

    def browser_nav(self, action):
        return self._browser_call(lambda: self._browser().nav(str(action)))

    def browser_ratio(self, ratio):
        def go():
            value = self._browser().set_ratio(ratio)
            with self._lock:
                self._config["browser_ratio"] = value
                import storage
                storage.save_config(self._config)
            return {"ratio": value}
        return self._browser_call(go)

    def browser_external(self):
        """지금 페이지를 기본 브라우저로 연다(다운로드·로그인이 필요한 사이트)."""
        def go():
            b = self._browser(create=False)
            url = b.state.get("url") if b else ""
            if not url or not browser.allowed(url):
                raise browser.BrowserError("열린 웹페이지가 없습니다.")
            self._open_url(url)
        return self._browser_call(go)

    def browser_attach(self, kind="page"):
        """지금 페이지(또는 선택한 부분)를 채팅 첨부 파일로 만든다. 내용은 '외부 데이터'로 감싼다."""
        def go():
            page = self._browser().read()
            selection = kind == "selection"
            if selection and not page["selection"].strip():
                raise browser.BrowserError("웹페이지에서 선택한 글이 없습니다. 묻고 싶은 부분을 먼저 드래그하세요.")
            if not selection and not page["text"].strip():
                raise browser.BrowserError("이 페이지에서 읽을 글을 찾지 못했습니다.")
            text = connectors.wrap_untrusted(browser.page_markdown(page, selection_only=selection), f"웹페이지 {page['url']}")
            title = (page["title"] or "웹페이지").strip()[:60]
            name = f"{'선택' if selection else '웹페이지'} - {title}.md"
            attach_id = uuid.uuid4().hex
            item = attachments.upload_chunk(attach_id, name, 0, base64.b64encode(text.encode("utf-8")).decode("ascii"), True)
            return {"attachment": item, "url": page["url"], "paper": page["paper"]}
        return self._browser_call(go)

    def browser_save_paper(self):
        """지금 페이지의 논문(arXiv·DOI)을 연구 라이브러리에 더한다."""
        try:
            page = self._browser().read()
        except browser.BrowserError as e:
            return {"ok": False, "error": str(e)}
        if not page["paper"]:
            return {"ok": False, "error": "이 페이지에서 arXiv 번호나 DOI를 찾지 못했습니다. 논문 페이지에서 다시 시도하세요."}
        if not self._config.get("features", {}).get("research"):
            return {"ok": False, "need_feature": "research",
                    "error": "연구 라이브러리가 꺼져 있습니다. 사이드바의 연구 라이브러리에서 켠 뒤 다시 시도하세요."}
        res = self.research_add(page["paper"], ["웹에서"])
        if res.get("ok"):
            res["paper"] = page["paper"]
        return res

    def _browser_pause_event(self):
        if getattr(self, "_browser_paused", None) is None:
            import threading

            self._browser_paused = threading.Event()
        return self._browser_paused

    def browser_agent_pause(self, paused):
        """브라우저 에이전트 일시정지·계속(1.16). 멈추기는 채팅의 중지(stop)를 쓴다."""
        ev = self._browser_pause_event()
        ev.set() if paused else ev.clear()
        self._push({"type": "browser", "kind": "agent", "status": "paused" if paused else "resumed"})
        return {"ok": True, "paused": bool(paused)}

    # 에이전트가 쓴다(main.Bridge._work가 Agent에 넘긴다)
    def _browser_for_agent(self):
        b = self._browser(create=False)
        return b if b is not None and b.visible else None

    def plms_login(self):
        """저장된 계정이 있으면 로그인 창의 칸을 채워 준다. 없거나 2단계(StonePASS) 인증은 사용자가 직접 한다."""
        import plms
        def go():
            with self._lock:
                if self._browser_owner is not None:
                    raise plms.PlmsError("브라우저를 쓰는 에이전트를 멈춘 뒤 로그인하세요.")
            b = self._browser()
            b.open(plms.LOGIN)
            with self._lock:
                self._config["plms_enabled"] = True
                import storage
                storage.save_config(self._config)
            auto = plms.credentials() is not None
            if auto:
                self._plms_autologin(b)
            return {"url": plms.LOGIN, "auto": auto}
        return self._plms_call(go)

    def _plms_autologin(self, b):
        """로그인 창이 뜰 때까지 기다리는 스레드. 새 로그인·연결 해제·창 닫기 때 이전 것은 멈춘다."""
        import threading
        import plms
        with self._lock:
            self._plms_login_gen = getattr(self, "_plms_login_gen", 0) + 1
            gen = self._plms_login_gen
        def cancelled():
            return gen != getattr(self, "_plms_login_gen", 0) or not b.visible or not self._config.get("plms_enabled")
        def work():
            result = plms.autologin(b, cancelled,
                                    on_status=lambda text: self._push({"type": "plms", "kind": "autologin", "message": text}))
            if result == "timeout" and not cancelled():
                self._push({"type": "plms", "kind": "autologin", "message": "자동 입력을 하지 못했습니다. 로그인 창에서 직접 입력하세요."})
        threading.Thread(target=work, name="plms-autologin", daemon=True).start()

    def plms_account(self):
        """저장된 계정 정보(아이디만). 비밀번호는 돌려주지 않는다."""
        import plms
        return {"ok": True, "username": plms.saved_username()}

    def _plms_call(self, fn):
        import plms
        try:
            return {"ok": True, **fn()}
        except (plms.PlmsError, browser.BrowserError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            return {"ok": False, "error": "PLMS 자료를 읽지 못했습니다. 로그인 상태를 확인하고 다시 시도하세요."}

    def _plms_read(self, action, cancelled=lambda: False, **kwargs):
        import plms
        if not self._config.get("plms_enabled"):
            raise plms.PlmsError("PLMS 로그인·연결을 먼저 켜세요.")
        client = plms.Client(self._browser(create=False),
                             cancelled=lambda: cancelled() or not self._config.get("plms_enabled"))
        try:
            return getattr(client, action)(**kwargs)
        finally:
            client.close()

    def plms_courses(self):
        return self._plms_call(lambda: {"courses": self._plms_read("courses")})

    def plms_course(self, course_id):
        return self._plms_call(lambda: {"course": self._plms_read("course", course_id=course_id)})

    def plms_read(self, course_id, url, query="", offset=0, parent=""):
        return self._plms_call(lambda: {"document": self._plms_read("read", course_id=course_id, url=url,
                                                                  query=query, offset=offset, parent=parent)})

    def plms_disconnect(self):
        def go():
            with self._lock:
                if self._browser_owner is not None:
                    raise browser.BrowserError("브라우저를 쓰는 에이전트를 멈춘 뒤 연결을 해제하세요.")
                self._config["plms_enabled"] = False
                self._plms_login_gen = getattr(self, "_plms_login_gen", 0) + 1
                import storage
                storage.save_config(self._config)
            b = self._browser(create=False)
            if b is not None:
                b.plms_cookies(clear=True)
                b.open("https://plms.postech.ac.kr/login/index.php")
            return {}
        return self._plms_call(go)
