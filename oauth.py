# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""OAuth 2.0: 설치형 앱 루프백 흐름(PKCE), 토큰 교환·갱신·폐기, GitHub 디바이스 흐름.

- 루프백 흐름(RFC 8252): 127.0.0.1의 임의 포트에 한 번만 받는 HTTP 서버를 띄우고 브라우저로 동의 화면을 연다.
  state(32바이트 난수)가 맞는 /callback 요청만 받는다(CSRF). PKCE는 S256이다. 5분 안에 끝나지 않으면 취소한다.
- 토큰은 secret_store에 "oauth:<커넥터>" 이름의 JSON으로 저장한다.
  {"access_token", "refresh_token", "expires_at", "scope": [..], "token_type"}
- access_token()은 만료 60초 전이면 갱신한다. 갱신이 invalid_grant로 거절되면 토큰을 지우고 NeedsAuth를 낸다.
- 디바이스 흐름(RFC 8628, GitHub): 브라우저 리디렉트가 없어 안드로이드에서도 쓸 수 있다.

클라이언트 ID·비밀은 사용자가 만든 것을 쓴다(Google Cloud Console의 '데스크톱 앱' OAuth 클라이언트,
GitHub OAuth App). 앱에 넣어 배포하지 않는다.
"""
import base64
import hashlib
import hmac
import http.server
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

import secret_store

LOGIN_TIMEOUT = 300
REFRESH_MARGIN = 60
DONE_PAGE = ("<!doctype html><meta charset='utf-8'><title>POSTECH GenAI Chat</title>"
             "<body style='font-family:sans-serif;padding:40px'><h2>{title}</h2><p>{text}</p></body>")


class OAuthError(Exception):
    pass


class NeedsAuth(OAuthError):
    """토큰이 없거나 갱신이 거절됨: 사용자가 다시 로그인해야 한다."""


@dataclass(frozen=True)
class Provider:
    name: str
    auth_url: str = ""
    token_url: str = ""
    revoke_url: str = ""
    device_url: str = ""
    # 동의 화면에 붙이는 추가 인자(Google: refresh_token을 받으려면 access_type=offline)
    auth_params: tuple = ()


GOOGLE = Provider(
    "google",
    auth_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    revoke_url="https://oauth2.googleapis.com/revoke",
    auth_params=(("access_type", "offline"), ("prompt", "consent")),
)
GITHUB = Provider(
    "github",
    auth_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",
    device_url="https://github.com/login/device/code",
)
PROVIDERS = {p.name: p for p in (GOOGLE, GITHUB)}

_session = None


def _http():
    global _session
    if _session is None:
        import requests

        try:
            import truststore  # 학교·회사 프록시 인증서(안드로이드에는 없다)

            truststore.inject_into_ssl()
        except ImportError:
            pass
        _session = requests.Session()
        _session.headers["Accept"] = "application/json"
    return _session


def _post(url, data, timeout=30):
    import requests

    try:
        r = _http().post(url, data=data, timeout=timeout)
    except requests.RequestException as e:
        raise OAuthError(f"인증 서버에 연결하지 못했습니다: {type(e).__name__}") from None
    try:
        body = r.json()
    except ValueError:
        body = {k: v[0] for k, v in parse_qs(r.text).items()}  # GitHub의 예전 형식
    if not isinstance(body, dict):
        body = {}
    return r.status_code, body


# ---- PKCE · state ----

def pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def new_state():
    return secrets.token_urlsafe(32)


def _normalize(body, previous=None):
    """토큰 응답을 저장 형식으로. 갱신 응답에 refresh_token이 없으면 이전 것을 유지한다."""
    if body.get("error") or not body.get("access_token"):
        raise OAuthError(_error_text(body))
    previous = previous or {}
    scope = body.get("scope", previous.get("scope", []))
    if isinstance(scope, str):
        scope = [s for s in scope.replace(",", " ").split() if s]
    token = {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token") or previous.get("refresh_token", ""),
        "token_type": body.get("token_type", "Bearer"),
        "scope": list(scope),
        "expires_at": time.time() + float(body["expires_in"]) if body.get("expires_in") else 0,
        "obtained_at": time.time(),
    }
    return token


def _error_text(body):
    code = body.get("error") or "unknown_error"
    desc = body.get("error_description") or ""
    return f"인증에 실패했습니다({code}){': ' + desc if desc else ''}"


# ---- 루프백 흐름 ----

class LoopbackFlow:
    """start()로 동의 화면 주소를 얻고(브라우저를 연다), wait()로 토큰을 받는다."""

    def __init__(self, provider, client_id, scopes, client_secret="", opener=webbrowser.open, timeout=LOGIN_TIMEOUT):
        if not client_id:
            raise OAuthError("OAuth 클라이언트 ID가 없습니다. 설정에서 먼저 입력하세요.")
        self.provider, self.client_id, self.client_secret = provider, client_id, client_secret
        self.scopes = list(scopes)
        self.opener, self.timeout = opener, timeout
        self.state = new_state()
        self.verifier, self.challenge = pkce_pair()
        self._done = threading.Event()
        self._result = None   # ("code", 코드) | ("error", 문구)
        self._server = None
        self.redirect_uri = ""

    def start(self):
        flow = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                if url.path != "/callback":
                    self.send_error(404)
                    return
                params = {k: v[0] for k, v in parse_qs(url.query).items()}
                if not hmac.compare_digest(str(params.get("state", "")), flow.state):
                    # 다른 사이트가 보낸 요청(CSRF)이거나 오래된 탭: 무시하고 진짜 콜백을 계속 기다린다
                    self._page(400, "요청을 확인할 수 없습니다", "앱에서 로그인을 다시 시작하세요.")
                    return
                if flow._done.is_set():
                    self._page(400, "이미 처리했습니다", "앱으로 돌아가세요.")
                    return
                if params.get("error"):
                    flow._result = ("error", _error_text(params))
                elif params.get("code"):
                    flow._result = ("code", params["code"])
                else:
                    flow._result = ("error", "인증 코드가 없습니다.")
                ok = flow._result[0] == "code"
                self._page(200 if ok else 400, "인증을 마쳤습니다" if ok else "인증하지 못했습니다",
                           "이 창을 닫고 POSTECH GenAI Chat으로 돌아가세요." if ok else flow._result[1])
                flow._done.set()

            def _page(self, status, title, text):
                body = DONE_PAGE.format(title=title, text=text).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass  # 표준 오류에 요청 줄(코드 포함)을 남기지 않는다

        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 1
        port = self._server.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{port}/callback"
        threading.Thread(target=self._serve, daemon=True, name="oauth-loopback").start()
        params = {"client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code",
                  "scope": " ".join(self.scopes), "state": self.state,
                  "code_challenge": self.challenge, "code_challenge_method": "S256", **dict(self.provider.auth_params)}
        url = f"{self.provider.auth_url}?{urlencode(params)}"
        if self.opener:
            self.opener(url)
        return url

    def _serve(self):
        deadline = time.monotonic() + self.timeout
        while not self._done.is_set() and time.monotonic() < deadline:
            self._server.handle_request()
        if not self._done.is_set():
            self._result = ("error", "로그인 시간이 지났습니다(5분). 다시 시도하세요.")
            self._done.set()
        self._server.server_close()

    def cancel(self):
        if not self._done.is_set():
            self._result = ("error", "로그인을 취소했습니다.")
            self._done.set()

    def wait(self):
        self._done.wait(self.timeout + 5)
        kind, value = self._result or ("error", "로그인 시간이 지났습니다.")
        if kind != "code":
            raise OAuthError(value)
        status, body = _post(self.provider.token_url, {
            "grant_type": "authorization_code", "code": value, "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "code_verifier": self.verifier,
            **({"client_secret": self.client_secret} if self.client_secret else {}),
        })
        if status != 200:
            raise OAuthError(_error_text(body))
        return _normalize(body)


# ---- 디바이스 흐름 (GitHub) ----

def device_start(provider, client_id, scopes):
    """{"device_code", "user_code", "verification_uri", "interval", "expires_in"}"""
    if not client_id:
        raise OAuthError("OAuth App의 Client ID가 없습니다.")
    status, body = _post(provider.device_url, {"client_id": client_id, "scope": " ".join(scopes)})
    if status != 200 or not body.get("device_code"):
        raise OAuthError(_error_text(body))
    return body


def device_poll(provider, client_id, device, cancelled=lambda: False, sleep=time.sleep):
    interval = int(device.get("interval") or 5)
    deadline = time.monotonic() + int(device.get("expires_in") or 900)
    while time.monotonic() < deadline:
        if cancelled():
            raise OAuthError("로그인을 취소했습니다.")
        sleep(interval)
        status, body = _post(provider.token_url, {
            "client_id": client_id, "device_code": device["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error or status != 200:
            raise OAuthError(_error_text(body))
        return _normalize(body)
    raise OAuthError("코드 입력 시간이 지났습니다. 다시 시도하세요.")


# ---- 저장·갱신·폐기 ----

_refresh_locks = {}
_locks_guard = threading.Lock()


def _key(name):
    return f"oauth:{name}"


def load(name):
    return secret_store.get_json(_key(name))


def save(name, token):
    secret_store.set_json(_key(name), token)


def forget(name):
    secret_store.delete(_key(name))


def refresh(provider, client_id, token, client_secret=""):
    if not token.get("refresh_token"):
        raise NeedsAuth("갱신 토큰이 없습니다. 다시 로그인하세요.")
    status, body = _post(provider.token_url, {
        "grant_type": "refresh_token", "refresh_token": token["refresh_token"], "client_id": client_id,
        **({"client_secret": client_secret} if client_secret else {}),
    })
    if body.get("error") in ("invalid_grant", "unauthorized_client", "invalid_client"):
        raise NeedsAuth(_error_text(body))
    if status != 200:
        raise OAuthError(_error_text(body))
    return _normalize(body, previous=token)


def access_token(name, provider, client_id, client_secret=""):
    """유효한 access token. 곧 만료되면 갱신해 저장한다. 없거나 갱신이 거절되면 NeedsAuth."""
    with _locks_guard:
        lock = _refresh_locks.setdefault(name, threading.Lock())
    with lock:
        token = load(name)
        if not token or not token.get("access_token"):
            raise NeedsAuth("로그인이 필요합니다.")
        expires = float(token.get("expires_at") or 0)
        if expires and expires - REFRESH_MARGIN < time.time():
            try:
                token = refresh(provider, client_id, token, client_secret)
            except NeedsAuth:
                forget(name)
                raise
            save(name, token)
        return token["access_token"]


def revoke(provider, token):
    """서버에서 토큰을 폐기한다. 실패해도 로컬 삭제는 호출한 쪽이 한다. 폐기했으면 True."""
    if not provider.revoke_url or not token:
        return False
    value = token.get("refresh_token") or token.get("access_token")
    if not value:
        return False
    try:
        status, _ = _post(provider.revoke_url, {"token": value}, timeout=15)
    except OAuthError:
        return False
    return status == 200


def missing_scopes(token, wanted):
    """요청한 scope 중 허용받지 못한 것. 응답에 scope가 없으면(GitHub PAT 등) 판단하지 않는다."""
    granted = set((token or {}).get("scope") or [])
    if not granted:
        return []
    return [s for s in wanted if s not in granted]
