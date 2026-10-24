# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""로컬 AI(1.17): Ollama 연결·모델 목록·기능·스트리밍·취소·오류·받기·지우기·자원 추정. 실제 Ollama 대신 tests/fake_ollama.py."""
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_ai  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama()
        self.addCleanup(self.fake.close)
        self.p = local_ai.OllamaProvider(self.fake.url)

    def test_health_and_models(self):
        h = self.p.health_check()
        self.assertTrue(h["ok"])
        self.assertEqual(h["version"], "0.9.6")
        self.assertTrue(h["loopback"])
        models = {m["id"]: m for m in self.p.list_models()}
        self.assertEqual(set(models), {"qwen2.5:7b", "llava:7b", "nomic-embed-text:latest"})
        self.assertEqual(models["qwen2.5:7b"]["quantization"], "Q4_K_M")
        self.assertEqual(models["qwen2.5:7b"]["parameter_size"], "7.6B")
        self.assertTrue(models["qwen2.5:7b"]["size_label"].endswith("GB"))
        self.assertTrue(self.p.running())

    def test_capabilities_come_from_the_runtime_not_the_name(self):
        q = self.p.capabilities("qwen2.5:7b")
        self.assertTrue(q["completion"] and q["tools"] and q["known"])
        self.assertFalse(q["vision"])
        self.assertEqual(q["context_length"], 32768)
        self.assertIn("Apache", q["license"])
        self.assertTrue(self.p.capabilities("llava:7b")["vision"])
        self.assertFalse(self.p.capabilities("nomic-embed-text:latest")["completion"])
        # 기능 목록을 주지 않는 오래된 Ollama: 글만 된다고 본다(이미지·도구는 없다고 본다)
        self.fake.httpd.old_version = True
        old = self.p.capabilities("llava:7b", refresh=True)
        self.assertFalse(old["known"])
        self.assertTrue(old["completion"])
        self.assertFalse(old["vision"])
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.capabilities("없는:모델")
        self.assertEqual(cm.exception.kind, "model")

    def test_stream_deltas_tokens_and_options(self):
        self.fake.replies.append("안녕하세요. 로컬 모델의 답변입니다. 스트리밍으로 옵니다.")
        seen = []
        res = self.p.stream(local_ai.LocalRequest(model="qwen2.5:7b", prompt="안녕", num_ctx=4096, max_tokens=100,
                                                  json_format=True, images=[("image/png", "QUJD")]), seen.append, None)
        self.assertEqual(res.text, "안녕하세요. 로컬 모델의 답변입니다. 스트리밍으로 옵니다.")
        self.assertGreater(len(seen), 2)
        self.assertEqual(seen[-1], res.text)
        self.assertEqual(res.done_reason, "stop")
        self.assertEqual(res.input_tokens, 42)
        self.assertGreater(res.tokens_per_s, 0)
        body = self.fake.requests[-1]["body"]
        self.assertEqual(body["options"], {"num_ctx": 4096, "num_predict": 100})
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["messages"][0]["images"], ["QUJD"])
        self.assertTrue(body["stream"])

    def test_generate_without_deltas(self):
        self.fake.replies.append("한 번에 받기")
        self.assertEqual(self.p.generate(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x")).text, "한 번에 받기")

    def test_length_stop_is_reported(self):
        self.fake.replies.append({"text": "끊긴 답", "done_reason": "length"})
        self.assertEqual(self.p.generate(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x")).done_reason, "length")

    def test_cancel_stops_streaming(self):
        self.fake.replies.append({"text": "가나다라마바사아자차카타파하" * 20, "delay": 0.02})
        stop = threading.Event()
        seen = []

        def on_delta(t):
            seen.append(t)
            if len(seen) == 3:
                stop.set()
        res = self.p.stream(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x"), on_delta, stop.is_set)
        self.assertEqual(res.done_reason, "cancelled")
        self.assertLess(len(res.text), 280)

    def test_timeout(self):
        self.fake.replies.append({"text": "느린 답변" * 30, "delay": 0.05})
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.stream(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x", timeout=0.2), None, None)
        self.assertEqual(cm.exception.kind, "timeout")

    def test_connection_dropped_mid_stream(self):
        self.fake.replies.append({"text": "중간에 끊기는 답변입니다 " * 5, "drop": True})
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.stream(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x"), None, None)
        self.assertEqual(cm.exception.kind, "unavailable")

    def test_errors_from_the_runtime(self):
        self.fake.replies.append({"text": "앞", "error": "model requires more system memory (12 GiB) than is available"})
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.generate(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x"))
        self.assertEqual(cm.exception.kind, "resource")
        self.fake.replies.append({"status": 500, "error": "input exceeds the context length"})
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.generate(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x"))
        self.assertEqual(cm.exception.kind, "context")
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.generate(local_ai.LocalRequest(model="phi3:mini", prompt="x"))
        self.assertEqual(cm.exception.kind, "model")
        with self.assertRaises(local_ai.LocalAIError):
            self.p.generate(local_ai.LocalRequest(model="", prompt="x"))

    def test_huge_reply_is_capped(self):
        self.fake.replies.append({"huge": local_ai.MAX_REPLY_CHARS + 5000})
        res = self.p.generate(local_ai.LocalRequest(model="qwen2.5:7b", prompt="x"))
        self.assertEqual(res.done_reason, "length")
        self.assertLessEqual(len(res.text), local_ai.MAX_REPLY_CHARS + 7)

    def test_not_running(self):
        p = local_ai.OllamaProvider(f"http://127.0.0.1:{free_port()}")
        h = p.health_check()
        self.assertFalse(h["ok"])
        self.assertEqual(h["kind"], "unavailable")
        self.assertIn("실행 중이 아닙니다", h["error"])
        self.assertFalse(p.is_available())
        with self.assertRaises(local_ai.LocalAIError) as cm:
            p.list_models()
        self.assertEqual(cm.exception.kind, "unavailable")

    def test_runtime_stops_while_running(self):
        self.assertTrue(self.p.is_available())
        self.fake.close()
        self.assertFalse(self.p.health_check()["ok"])

    def test_pull_progress_cancel_and_errors(self):
        progress = []
        self.assertTrue(self.p.pull("phi3:mini", lambda d, t, s: progress.append((d, t, s))))
        self.assertIn("phi3:mini", {m["id"] for m in self.p.list_models()})
        self.assertTrue(any(t == 1000 and d == 1000 for d, t, _ in progress))
        self.fake.httpd.pull_delay = 0.05
        stop = threading.Event()
        threading.Timer(0.15, stop.set).start()
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.pull("gemma3:4b", None, stop.is_set)
        self.assertEqual(cm.exception.kind, "cancelled")
        self.fake.httpd.pull_delay = 0
        self.fake.httpd.pull_error = "write /root/.ollama/models/blobs/x: no space left on device"
        with self.assertRaises(local_ai.LocalAIError) as cm:
            self.p.pull("gemma3:4b")
        self.assertEqual(cm.exception.kind, "resource")
        with self.assertRaises(local_ai.LocalAIError):
            self.p.pull("../../etc")

    def test_delete(self):
        self.assertTrue(self.p.delete("llava:7b"))
        self.assertNotIn("llava:7b", {m["id"] for m in self.p.list_models()})
        with self.assertRaises(local_ai.LocalAIError):
            self.p.delete("llava:7b")

    def test_measure(self):
        self.fake.replies.append("저는 로컬 모델입니다.")
        m = self.p.measure("qwen2.5:7b")
        self.assertGreater(m["tokens_per_s"], 0)
        self.assertIsNotNone(m["first_ms"])


class CheckScriptTests(unittest.TestCase):
    def test_local_check_script_runs_every_local_step(self):
        """tools/local_ai_check.py(사용자 PC용 실제 점검)가 끝까지 돌고, Cloud 단계는 통과로 적지 않고 '건너뜀'으로 남기는지."""
        import contextlib
        import io

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import local_ai_check

        fake = FakeOllama()
        self.addCleanup(fake.close)
        fake.replies.extend(["속도 측정용 답입니다.", "391", "포항은 바다 도시입니다. 포스텍이 있습니다. 해맞이가 유명합니다.",
                             {"text": "1\n2\n3\n" * 300, "delay": 0.02}, "약 6000자입니다.",
                             "회의에서 예산 300만 원을 확정했고 금요일까지 자료를 만들기로 했습니다."])
        local_ai_check.RESULTS.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            code = local_ai_check.main(["--endpoint", fake.url, "--model", "qwen2.5:7b"])
        status = {step.split()[0]: st for step, st, _ in local_ai_check.RESULTS}
        self.assertEqual(code, 0, local_ai_check.RESULTS)
        self.assertEqual([status[str(i)] for i in range(1, 9)], ["PASS"] * 8)
        self.assertEqual((status["9"], status["10"]), ("SKIP", "SKIP"))


class PreviewAndResourceTests(unittest.TestCase):
    def test_pull_preview_reads_size_and_license_from_the_registry(self):
        calls = []

        class R:
            def __init__(self, status, data=None, text=""):
                self.status_code, self._data, self.text = status, data, text

            def json(self):
                return self._data

        def http(url, headers):
            calls.append(url)
            if "/manifests/" in url:
                return R(200, {"layers": [
                    {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:" + "a" * 64, "size": 4_000_000_000},
                    {"mediaType": "application/vnd.ollama.image.license", "digest": "sha256:" + "b" * 64, "size": 11000},
                    {"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:" + "c" * 64, "size": 1000}]})
            return R(200, text="Apache License\nVersion 2.0, January 2004\n...")
        info = local_ai.pull_preview("qwen2.5:7b", http=http)
        self.assertEqual(info["size"], 4_000_012_000)
        self.assertEqual(info["license_name"], "Apache License")
        self.assertIn("registry.ollama.ai/v2/library/qwen2.5", info["source"])
        self.assertEqual(info["page"], "https://ollama.com/library/qwen2.5")
        self.assertTrue(calls[0].endswith("/v2/library/qwen2.5/manifests/7b"))
        self.assertIn("/blobs/sha256:" + "b" * 64, calls[1])
        with self.assertRaises(local_ai.LocalAIError) as cm:
            local_ai.pull_preview("nothing:here", http=lambda url, h: R(404))
        self.assertEqual(cm.exception.kind, "model")
        with self.assertRaises(local_ai.LocalAIError):
            local_ai.pull_preview("bad name; rm -rf", http=http)

    def test_resources_and_memory_estimate(self):
        res = local_ai.system_resources()
        for key in ("ram_total", "ram_available", "cpu_count", "gpus", "apple_silicon", "reliable"):
            self.assertIn(key, res)
        self.assertGreater(local_ai.memory_budget(res), 0)
        self.assertEqual(local_ai.memory_budget({"reliable": False}), local_ai.CONSERVATIVE_BUDGET)  # 모르면 보수적으로
        self.assertEqual(local_ai.memory_budget({"reliable": True, "ram_available": 10 * 2**30, "gpus": [{"vram_free": 20 * 2**30}]}),
                         20 * 2**30)
        self.assertGreater(local_ai.estimate_memory(4 * 2**30, 32768), local_ai.estimate_memory(4 * 2**30, 2048))
        self.assertIsNone(local_ai.estimate_memory(0))
        self.assertIsNotNone(local_ai.disk_free())

    def test_android_is_not_supported(self):
        with patch.object(local_ai, "SUPPORTED", False):
            with self.assertRaises(local_ai.LocalAIError) as cm:
                local_ai.make_provider({})
            self.assertIn("안드로이드", str(cm.exception))

    def test_model_names(self):
        for ok in ("qwen2.5:7b", "llama3.2", "hf.co/user/model:Q4_K_M".replace("hf.co/", ""), "user/model:tag", "nomic-embed-text:latest"):
            self.assertTrue(local_ai.valid_model_name(ok), ok)
        for bad in ("", "../x", "a b", "x;rm", "a:b:c", "-x", "a" * 201):
            self.assertFalse(local_ai.valid_model_name(bad), bad)


if __name__ == "__main__":
    unittest.main()
