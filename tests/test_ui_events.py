# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""1.15 B1: 화면 이벤트 큐(ui_events.EventPump)와 Bridge._push.

pywebview의 evaluate_js처럼 'UI 스레드에 스크립트를 맡기고 결과를 기다리는' 가짜 창을 만들어,
UI 스레드에서 이벤트를 보내도 멈추지 않는지(그리고 예전 방식은 멈추는지) 확인한다.
"""
import json
import os
import queue
import sys
import threading
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("webview", types.SimpleNamespace(FOLDER_DIALOG=20))

import browser  # noqa: E402
import main  # noqa: E402
import ui_events  # noqa: E402
from support import isolated_app_dir, preserved_hooks  # noqa: E402


class FakeUiWindow:
    """UI 스레드 하나와 pywebview식 evaluate_js(UI 스레드에 맡기고 세마포어로 기다림)."""

    def __init__(self, delay=0.0, wait_timeout=None):
        self.tasks = queue.Queue()
        self.scripts = []
        self.delay = delay
        self.wait_timeout = wait_timeout  # None이면 pywebview처럼 끝없이 기다린다
        self.ui = threading.Thread(target=self._loop, daemon=True)
        self.ui.start()

    def _loop(self):
        while True:
            fn = self.tasks.get()
            if fn is None:
                return
            fn()

    def on_ui(self, fn):
        """fn을 UI 스레드에서 실행한다(네이티브 이벤트 처리기 흉내)."""
        done = threading.Event()

        def run():
            try:
                fn()
            finally:
                done.set()
        self.tasks.put(run)
        return done

    def evaluate_js(self, script):
        sem = threading.Semaphore(0)

        def run():
            if self.delay:
                time.sleep(self.delay)
            self.scripts.append(script)
            sem.release()
        self.tasks.put(run)  # 결과는 UI 스레드가 넘겨준다
        if not sem.acquire(timeout=self.wait_timeout) if self.wait_timeout else not sem.acquire():
            raise TimeoutError("UI 스레드가 응답하지 않습니다")

    def events(self):
        prefix = "window.onBackendEvent("
        return [json.loads(s[len(prefix):-1]) for s in self.scripts if s.startswith(prefix)]

    def close(self):
        self.tasks.put(None)


class EventPumpTests(unittest.TestCase):
    def test_push_returns_at_once_even_if_sending_is_slow(self):
        sent = []
        pump = ui_events.EventPump(lambda e: (time.sleep(0.3), sent.append(e)))
        start = time.monotonic()
        for i in range(5):
            pump.push({"type": "status", "text": str(i)})
        self.assertLess(time.monotonic() - start, 0.1)
        self.assertTrue(pump.flush(5))
        self.assertEqual([e["text"] for e in sent], ["0", "1", "2", "3", "4"])
        pump.stop()

    def test_order_is_kept(self):
        sent = []
        pump = ui_events.EventPump(sent.append)
        for i in range(300):
            pump.push({"type": "message", "n": i})
        self.assertTrue(pump.flush(5))
        self.assertEqual([e["n"] for e in sent], list(range(300)))
        pump.stop()

    def test_only_consecutive_state_events_are_merged(self):
        gate, sent = threading.Event(), []
        pump = ui_events.EventPump(lambda e: (gate.wait(5), sent.append(e)))
        pump.push({"type": "status", "text": "first"})  # 스레드가 이것을 잡고 gate에서 기다린다
        time.sleep(0.1)
        for i in range(50):
            pump.push({"type": "browser", "url": f"https://a/{i}", "loading": True})
        pump.push({"type": "browser", "kind": "blocked", "url": "file:///x", "reason": "r"})
        pump.push({"type": "browser", "kind": "blocked", "url": "file:///y", "reason": "r"})
        pump.push({"type": "browser", "url": "https://a/last", "loading": False})
        pump.push({"type": "delta", "thread_id": "t", "text": "a"})
        pump.push({"type": "delta", "thread_id": "t", "text": "ab"})
        pump.push({"type": "message", "thread_id": "t", "message": {"role": "assistant"}})
        gate.set()
        self.assertTrue(pump.flush(5))
        summary = [(e["type"], e.get("kind") or e.get("url") or e.get("text") or "") for e in sent]
        self.assertEqual(summary, [
            ("status", "first"),
            ("browser", "https://a/49"),          # 연달아 온 상태 50개 → 마지막 하나
            ("browser", "blocked"), ("browser", "blocked"),  # 차단 알림은 합치지 않는다
            ("browser", "https://a/last"),
            ("delta", "ab"),
            ("message", ""),
        ])
        self.assertEqual(pump.stats["coalesced"], 50)
        pump.stop()

    def test_a_failing_event_does_not_stop_the_rest(self):
        sent = []

        def send(e):
            if e.get("bad"):
                raise RuntimeError("창이 닫히는 중")
            sent.append(e)
        pump = ui_events.EventPump(send)
        pump.push({"type": "a"})
        pump.push({"type": "b", "bad": True})
        pump.push({"type": "c"})
        self.assertTrue(pump.flush(5))
        self.assertEqual([e["type"] for e in sent], ["a", "c"])
        self.assertEqual(pump.stats["errors"], 1)
        pump.stop()

    def test_queue_does_not_grow_without_bound(self):
        gate = threading.Event()
        pump = ui_events.EventPump(lambda e: gate.wait(5), max_pending=20, hard_limit=40)
        pump.push({"type": "hold"})
        time.sleep(0.1)
        for i in range(30):  # 서로 다른 상태 이벤트(합칠 수 없게 사이사이 다른 이벤트)
            pump.push({"type": "browser", "url": str(i)})
            pump.push({"type": "message", "n": i})
        self.assertLessEqual(pump.pending(), 40)
        kept = [item[1] for item in pump._queue]
        self.assertEqual(sum(1 for e in kept if e["type"] == "message"), 30)  # 상태 이벤트부터 버린다
        self.assertGreater(pump.stats["dropped"], 0)
        gate.set()
        pump.stop()

    def test_stop_does_not_wait_for_a_hung_send(self):
        hung = threading.Event()
        pump = ui_events.EventPump(lambda e: hung.wait(30))
        pump.push({"type": "x"})
        time.sleep(0.05)
        start = time.monotonic()
        pump.stop(timeout=0.3)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertFalse(pump.push({"type": "after"}))  # 끝낸 뒤에는 받지 않는다
        hung.set()


class UiThreadDeadlockTests(unittest.TestCase):
    """B1 재현: 네이티브 처리기(UI 스레드) → _push → evaluate_js."""

    def setUp(self):
        self.window = FakeUiWindow()
        self.addCleanup(self.window.close)

    def test_old_synchronous_push_deadlocks_on_the_ui_thread(self):
        window = FakeUiWindow(wait_timeout=1.0)  # 시험이 끝나도록 1초만 기다린다
        self.addCleanup(window.close)
        failed = []

        def handler():
            try:
                window.evaluate_js("window.onBackendEvent({})")  # 1.13~1.14의 _push
            except TimeoutError:
                failed.append(True)
        window.on_ui(handler).wait(5)
        self.assertEqual(failed, [True], "UI 스레드에서 동기 evaluate_js는 결과를 받지 못한다(교착)")

    def test_bridge_push_from_the_ui_thread_does_not_block(self):
        with preserved_hooks(), isolated_app_dir():
            bridge = main.Bridge()
            bridge._window = self.window
            b = browser.Browser(lambda br: types.SimpleNamespace(mode="native"), on_event=bridge._browser_event)
            done = self.window.on_ui(lambda: [b.navigated(url=f"https://e.com/{i}", title="t", loading=i < 99)
                                              for i in range(100)])
            self.assertTrue(done.wait(2), "UI 스레드가 이벤트 처리기에서 멈췄다")
            # UI 스레드가 계속 돌므로 evaluate_js도 끝난다
            self.assertTrue(bridge._events.flush(5))
            evs = [e for e in self.window.events() if e["type"] == "browser"]
            self.assertTrue(evs)
            self.assertEqual(evs[-1]["url"], "https://e.com/99")
            self.assertFalse(evs[-1]["loading"])
            self.assertLess(len(evs), 100)  # 연달은 상태 이벤트는 합쳐진다
            bridge._events.stop()
            bridge._mcp.shutdown()

    def test_other_features_still_receive_every_event_in_order(self):
        with preserved_hooks(), isolated_app_dir():
            bridge = main.Bridge()
            bridge._window = self.window
            for i in range(20):
                bridge._po_push("segment", note_id="n", segment={"i": i})
                bridge._push({"type": "status", "thread_id": "t", "text": str(i)})
            bridge._push({"type": "confirm", "id": "c1", "kind": "edit", "title": "x", "detail": ""})
            self.assertTrue(bridge._events.flush(5))
            evs = self.window.events()
            self.assertEqual(len(evs), 41)
            self.assertEqual([e["segment"]["i"] for e in evs if e["type"] == "po"], list(range(20)))
            self.assertEqual(evs[-1]["type"], "confirm")
            bridge._events.stop()
            bridge._mcp.shutdown()

    def test_push_without_a_window_is_ignored(self):
        with preserved_hooks(), isolated_app_dir():
            bridge = main.Bridge()
            bridge._push({"type": "status"})
            self.assertEqual(bridge._events.pending(), 0)
            bridge._events.stop()
            bridge._mcp.shutdown()


if __name__ == "__main__":
    unittest.main()
