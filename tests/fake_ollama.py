# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""시험용 가짜 Ollama 서버. Ollama 기본 API(docs.ollama.com/api)의 응답 꼴을 흉내 낸다.

    /api/version · /api/tags · /api/show · /api/chat(NDJSON 스트림) · /api/pull · /api/delete · /api/ps
server.replies에 답을 차례로 넣는다(문자열, 또는 {"text", "done_reason", "error", "drop", "delay", "status", "huge"}).
server.requests에 받은 요청(경로·헤더·본문)이 남는다.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {
    "qwen2.5:7b": {"size": 4_700_000_000, "family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M",
                   "capabilities": ["completion", "tools"], "context_length": 32768, "license": "Apache License 2.0"},
    "llava:7b": {"size": 4_700_000_000, "family": "llama", "parameter_size": "7B", "quantization_level": "Q4_0",
                 "capabilities": ["completion", "vision"], "context_length": 4096, "license": "LLAMA 2 COMMUNITY LICENSE"},
    "nomic-embed-text:latest": {"size": 270_000_000, "family": "nomic-bert", "parameter_size": "137M", "quantization_level": "F16",
                                "capabilities": ["embedding"], "context_length": 2048, "license": "Apache License 2.0"},
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def _send(self, status, obj, ctype="application/json"):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _lines(self, rows, delay=0.0, drop_after=None):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i, row in enumerate(rows):
            if drop_after is not None and i >= drop_after:
                self.close_connection = True
                return  # 끝 표시 없이 끊는다
            data = (json.dumps(row) + "\n").encode()
            try:
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            if delay:
                time.sleep(delay)
        try:
            self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):  # noqa: N802
        srv = self.server
        srv.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers), "body": None})
        if self.path == "/api/version":
            return self._send(200, {"version": "0.9.6"})
        if self.path == "/api/tags":
            return self._send(200, {"models": [
                {"name": k, "model": k, "modified_at": "2026-10-01T00:00:00Z", "size": v["size"], "digest": "x" * 12,
                 "details": {"format": "gguf", "family": v["family"], "parameter_size": v["parameter_size"],
                             "quantization_level": v["quantization_level"]}} for k, v in srv.models.items()]})
        if self.path == "/api/ps":
            return self._send(200, {"models": [{"name": k, "model": k, "size": v["size"], "size_vram": 0} for k, v in list(srv.models.items())[:1]]})
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        body = self._body()
        self.server.requests.append({"method": "DELETE", "path": self.path, "headers": dict(self.headers), "body": body})
        if body.get("model") in self.server.models:
            self.server.models.pop(body["model"])
            return self._send(200, {})
        self._send(404, {"error": f"model '{body.get('model')}' not found"})

    def do_POST(self):  # noqa: N802
        srv = self.server
        body = self._body()
        srv.requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
        if srv.redirect_all:
            self.send_response(307)
            self.send_header("Location", "http://169.254.169.254/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/api/show":
            m = srv.models.get(body.get("model"))
            if m is None:
                return self._send(404, {"error": f"model '{body.get('model')}' not found"})
            out = {"license": m["license"], "details": {"family": m["family"]},
                   "model_info": {"general.architecture": m["family"], f"{m['family']}.context_length": m["context_length"]}}
            if not srv.old_version:
                out["capabilities"] = m["capabilities"]
            return self._send(200, out)
        if self.path == "/api/chat":
            if body.get("model") not in srv.models:
                return self._send(404, {"error": f"model \"{body.get('model')}\" not found, try pulling it first"})
            reply = srv.replies.pop(0) if srv.replies else "기본 답변입니다."
            reply = {"text": reply} if isinstance(reply, str) else dict(reply)
            if reply.get("status"):
                return self._send(reply["status"], {"error": reply.get("error", "error")})
            text = reply.get("text", "")
            if reply.get("huge"):
                text = "가" * reply["huge"]
            pieces = [text[i:i + 7] for i in range(0, len(text), 7)] or [""]
            rows = [{"model": body["model"], "message": {"role": "assistant", "content": p}, "done": False} for p in pieces]
            if reply.get("error"):
                rows.append({"error": reply["error"]})
            rows.append({"model": body["model"], "message": {"role": "assistant", "content": ""}, "done": True,
                         "done_reason": reply.get("done_reason", "stop"), "prompt_eval_count": 42, "eval_count": len(pieces),
                         "eval_duration": 500_000_000, "load_duration": 20_000_000})
            return self._lines(rows, reply.get("delay", 0.0), len(pieces) // 2 if reply.get("drop") else None)
        if self.path == "/api/pull":
            name = body.get("model")
            if srv.pull_error:
                return self._lines([{"status": "pulling manifest"}, {"error": srv.pull_error}])
            rows = [{"status": "pulling manifest"}] + [
                {"status": "pulling abc", "digest": "sha256:abc", "total": 1000, "completed": c} for c in range(0, 1001, 100)
            ] + [{"status": "verifying sha256 digest"}, {"status": "success"}]

            def finish():
                srv.models[name] = dict(MODELS["qwen2.5:7b"])
            self._lines(rows, srv.pull_delay)
            finish()
            return
        self._send(404, {"error": "not found"})


class FakeOllama:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.handle_error = lambda request, client_address: None  # 시험이 일부러 연결을 끊는다(취소·시간 초과)
        self.httpd.models = {k: dict(v) for k, v in MODELS.items()}
        self.httpd.replies = []
        self.httpd.requests = []
        self.httpd.old_version = False
        self.httpd.redirect_all = False
        self.httpd.pull_error = ""
        self.httpd.pull_delay = 0.0
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __getattr__(self, name):
        return getattr(self.httpd, name)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
