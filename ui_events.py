# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Python → 화면 이벤트를 막지 않고 보내는 큐(1.15, 브라우저 멈춤 버그 B1 수정).

왜 필요한가: pywebview의 window.evaluate_js()는 스크립트를 UI 스레드에 맡기고 결과가 올 때까지 기다린다
(Windows edgechromium: Invoke + Semaphore, macOS cocoa: AppHelper.callAfter + Semaphore). 그런데 웹페이지 뷰의
네이티브 이벤트 처리기(WebView2 NavigationCompleted·SourceChanged, WKWebView 대리자)는 UI 스레드에서 돈다.
처리기 → Browser.navigated() → Bridge._push() → evaluate_js()가 UI 스레드에서 불리면, 결과를 넘겨줄 UI 스레드가
바로 자기 자신이라 영원히 기다리고 앱 창이 "응답 없음"이 된다.

그래서 _push는 이벤트를 큐에 넣고 바로 돌아오고, 전용 백그라운드 스레드 하나가 순서대로 evaluate_js를 부른다.
- 순서를 지킨다(스레드 하나, 먼저 넣은 것부터).
- 연달아 들어온 같은 종류의 '상태' 이벤트(브라우저 주소·제목, 스트리밍 중간 답변, 녹음 소리 크기)는 마지막 것만 보낸다.
  상태 전체를 담은 이벤트라 마지막 것만 보내도 잃는 정보가 없다. 다른 이벤트를 사이에 두고는 합치지 않는다.
- 큐가 MAX_PENDING을 넘으면 합칠 수 있는(상태) 이벤트부터 오래된 것을 버린다. 화면이 아예 멈춰 HARD_LIMIT을
  넘으면 가장 오래된 이벤트를 버리고 센다(메모리가 끝없이 늘지 않게).
- 보내다가 난 예외는 그 이벤트만 실패로 세고 다음 이벤트로 넘어간다.
- 창이 닫히면 stop()으로 끝낸다. 보내는 중인 evaluate_js가 돌아오지 않아도 오래 기다리지 않는다(데몬 스레드).
"""
import collections
import threading

MAX_PENDING = 1000
HARD_LIMIT = 5000


def coalesce_key(event):
    """연달아 오면 마지막 것만 보내도 되는 이벤트의 키. 나머지는 None(하나도 버리지 않는다)."""
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    if kind == "browser" and not event.get("kind"):
        return ("browser",)  # 주소·제목·불러오는 중 — 매번 전체 상태를 담는다
    if kind == "delta":
        return ("delta", event.get("thread_id"))  # 지금까지의 답변 전체
    if kind == "po" and event.get("kind") in ("level", "download"):
        return ("po", event.get("kind"), event.get("note_id"))
    if kind == "update" and event.get("kind") == "progress":
        return ("update", "progress")
    return None


class EventPump:
    """send(event)를 전용 스레드에서 순서대로 부른다. push()는 절대 막지 않는다."""

    def __init__(self, send, name="poschat-events", max_pending=MAX_PENDING, hard_limit=HARD_LIMIT):
        self._send = send
        self._name = name
        self._max = max_pending
        self._hard = hard_limit
        self._queue = collections.deque()  # (key, event)
        self._cond = threading.Condition()
        self._thread = None
        self._stopped = False
        self._busy = False
        self.stats = {"sent": 0, "coalesced": 0, "dropped": 0, "errors": 0}

    # ---- 넣기 ----

    def push(self, event):
        """이벤트를 큐에 넣고 바로 돌아온다(UI 스레드에서 불러도 된다)."""
        key = coalesce_key(event)
        with self._cond:
            if self._stopped:
                return False
            if key is not None and self._queue and self._queue[-1][0] == key:
                self._queue[-1] = (key, event)  # 바로 앞의 같은 상태 이벤트를 새것으로
                self.stats["coalesced"] += 1
            else:
                self._queue.append((key, event))
                if len(self._queue) > self._max:
                    self._trim()
            self._ensure_thread()
            self._cond.notify()
        return True

    def _trim(self):
        """큐가 너무 길다(화면이 이벤트를 못 받고 있다): 상태 이벤트부터 버린다."""
        over = len(self._queue) - self._max
        if over > 0:
            kept = collections.deque()
            for item in self._queue:
                if over > 0 and item[0] is not None:
                    over -= 1
                    self.stats["dropped"] += 1
                    continue
                kept.append(item)
            self._queue = kept
        while len(self._queue) > self._hard:
            self._queue.popleft()
            self.stats["dropped"] += 1

    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
            self._thread.start()

    # ---- 보내기(전용 스레드) ----

    def _loop(self):
        while True:
            with self._cond:
                while not self._queue and not self._stopped:
                    self._busy = False
                    self._cond.notify_all()
                    self._cond.wait()
                if self._stopped:
                    self._busy = False
                    self._cond.notify_all()
                    return
                _, event = self._queue.popleft()
                self._busy = True
            try:
                self._send(event)
                self.stats["sent"] += 1
            except Exception:
                self.stats["errors"] += 1  # 창이 닫히는 중 등: 다음 이벤트로 넘어간다

    # ---- 끝내기·시험 ----

    def flush(self, timeout=5.0):
        """큐가 빌 때까지 기다린다(시험·종료 전 정리용). 다 보냈으면 True."""
        with self._cond:
            return self._cond.wait_for(lambda: self._stopped or (not self._queue and not self._busy), timeout)

    def pending(self):
        with self._cond:
            return len(self._queue)

    def stop(self, timeout=1.0):
        """더 받지 않고 남은 이벤트를 버린 뒤 스레드를 끝낸다. 보내는 중인 evaluate_js는 timeout까지만 기다린다."""
        with self._cond:
            self._stopped = True
            self._queue.clear()
            self._cond.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()
