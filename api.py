"""POSTECH GenAI API 호출.

두 가지 방식을 지원한다.
- a1: `agent/api/a1/gpt` 단일 호출 API. 모델은 서버가 정한다. 키만 있으면 바로 쓸 수 있는 기본값.
- responses: 게이트웨이의 OpenAI Responses API(`.../a<번호>/openai/responses`). 모델을 고를 수 있다.
  주소의 a<번호>는 POSTECH GenAI 콘솔에서 확인해 설정에 넣는다.

stream을 켜면 받은 글자를 on_delta(지금까지의 전체 텍스트)로 넘긴다. Responses는 OpenAI 표준 SSE를,
a1은 문서에 형식이 없어서 SSE·JSON Lines·일반 텍스트를 모두 받아 주고, 실패하면 한 번에 받는 방식으로 다시 요청한다.
"""
import codecs
import json
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

import certs

try:
    # genai.postech.ac.kr은 중간 인증서를 보내지 않아 certifi로는 검증에 실패한다.
    # OS 인증서 저장소(Windows는 중간 인증서를 자동으로 받아 옴)로 검증하도록 한다.
    import truststore
    truststore.inject_into_ssl()
    TRUSTSTORE = True
except ImportError:
    TRUSTSTORE = False  # 안드로이드 등: 검증 실패 때 중간 인증서를 직접 받아 온다(certs.py)

# 중간 인증서를 보내지 않는 것을 확인한 서버. 이 서버에만 AIA로 중간 인증서를 받아 온다.
AIA_HOSTS = {"genai.postech.ac.kr"}
_aia_sessions = {}  # 호스트 -> 중간 인증서를 더한 CA 묶음으로 검증하는 세션


class _StrictCAAdapter(requests.adapters.HTTPAdapter):
    """받아 온 중간 인증서를 신뢰 기준점으로 삼지 않도록 VERIFY_X509_PARTIAL_CHAIN을 끈 연결.

    Python 3.13+와 urllib3는 이 옵션을 켜므로, 그대로 두면 CA 묶음에 넣은 중간 인증서만으로 검증이
    끝나 버린다. 끄면 중간 인증서는 체인을 잇는 데만 쓰이고 certifi의 루트까지 서명이 이어져야 통과한다.
    """

    def __init__(self, ca_file):
        self._ca_file = ca_file
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        from urllib3.util.ssl_ import create_urllib3_context

        ctx = create_urllib3_context(verify_flags=0)
        ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
        ctx.load_verify_locations(self._ca_file)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

URL = "https://genai.postech.ac.kr/agent/api/a1/gpt"

# 게이트웨이 Responses API에서 쓸 수 있는 GPT 모델(posicube-services/llm-agent-api README 기준)
MODELS = [
    ("gpt-5.1-gs-2025-11-13", "GPT-5.1 — 권장: 성능과 비용의 균형"),
    ("gpt-5.2-gs-2025-12-11", "GPT-5.2 — 가장 좋은 성능, 비용 높음"),
    ("gpt-5-gs-2025-08-07", "GPT-5"),
    ("gpt-5-mini-gs-2025-08-07", "GPT-5 mini — 빠르고 저렴"),
    ("gpt-4.1-mini-gs-2025-04-14", "GPT-4.1 mini — 추론 없음, 저렴"),
]
DEFAULT_MODEL = MODELS[0][0]
REASONING_EFFORT = "low"  # 에이전트는 단계마다 호출하므로 추론 토큰을 아낀다


class ApiError(Exception):
    pass


# 호출이 끝날 때마다 on_usage(mode, model, usage)를 부른다. usage는 서버가 알려 준 토큰 수
# {"input_tokens", "output_tokens"} 또는 None. 앱(main.py)이 storage.record_usage로 설정한다.
on_usage = None


@dataclass
class ApiSettings:
    mode: str = "a1"               # "a1" | "responses"
    responses_url: str = ""
    model: str = DEFAULT_MODEL
    stream: bool = True

    @classmethod
    def from_config(cls, config):
        mode = config.get("api_mode", "a1")
        return cls(
            mode=mode if mode in ("a1", "responses") else "a1",
            responses_url=str(config.get("responses_url", "") or "").strip(),
            model=str(config.get("model") or DEFAULT_MODEL),
            stream=bool(config.get("stream", True)),
        )


def ask(api_key, message, timeout=180, settings=None, on_delta=None, cancelled=None, images=None):
    """모델 답변 전체를 돌려준다. on_delta가 있고 스트리밍이 켜져 있으면 받는 동안 중간 텍스트를 넘긴다.

    images는 [(MIME 형식, base64)]이며 Responses API에서만 보낸다(a1은 글자만 받는다).
    """
    settings = settings or ApiSettings()
    stream = bool(on_delta) and settings.stream
    if settings.mode == "responses":
        text, usage = _ask_responses(api_key, message, timeout, settings, on_delta if stream else None, cancelled,
                                     images)
    else:
        text, usage = None, None
        if stream:
            try:
                text, usage = _ask_a1(api_key, message, timeout, on_delta, cancelled)
            except _StreamFormatError:
                pass  # 서버가 알 수 없는 형식으로 보냈다: 한 번에 받는 방식으로 다시 요청한다
        if text is None:
            text, usage = _ask_a1(api_key, message, timeout, None, cancelled)
    if on_usage:
        try:
            on_usage(settings.mode, settings.model if settings.mode == "responses" else "a1", usage)
        except Exception:
            pass  # 사용량 기록 실패로 답변을 잃지 않는다
    return text


def _usage(data):
    """응답(또는 게이트웨이가 감싼 응답)의 토큰 사용량. 없으면 None."""
    if not isinstance(data, dict):
        return None
    for obj in (data.get("usage"), (data.get("response") or {}).get("usage") if isinstance(data.get("response"), dict) else None,
                (data.get("data") or {}).get("usage") if isinstance(data.get("data"), dict) else None):
        if isinstance(obj, dict):
            inp = obj.get("input_tokens", obj.get("prompt_tokens"))
            out = obj.get("output_tokens", obj.get("completion_tokens"))
            if isinstance(inp, int) or isinstance(out, int):
                return {"input_tokens": int(inp or 0), "output_tokens": int(out or 0)}
    return None


# ---- a1 단일 호출 ----

def _ask_a1(api_key, message, timeout, on_delta, cancelled):
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    data = {"message": message, "stream": bool(on_delta)}
    response = _post(URL, headers, data, timeout, stream=bool(on_delta))
    if not on_delta or _is_json(response):
        try:
            data = response.json()
            return data["message"], _usage(data)
        except (ValueError, KeyError, TypeError) as e:
            raise ApiError(f"응답 형식 오류: {response.text[:300]}") from e
    return _read_stream(response, on_delta, cancelled)


# ---- OpenAI Responses ----

def _ask_responses(api_key, message, timeout, settings, on_delta, cancelled, images=None):
    if not settings.responses_url:
        raise ApiError("모델 선택(Responses API)을 쓰려면 설정에서 Responses API 주소를 입력하세요.")
    content = message
    if images:
        content = [{"role": "user", "content": [{"type": "input_text", "text": message}] + [
            {"type": "input_image", "image_url": f"data:{mime};base64,{data}"} for mime, data in images]}]
    payload = {"model": settings.model, "input": content, "stream": bool(on_delta), "store": False}
    if not settings.model.startswith("gpt-4"):
        payload["reasoning"] = {"effort": REASONING_EFFORT}
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    response = _post(settings.responses_url, headers, payload, timeout, stream=bool(on_delta))
    if on_delta and not _is_json(response):
        try:
            return _read_stream(response, on_delta, cancelled)
        except _StreamFormatError as e:
            raise ApiError(f"스트리밍 응답을 해석하지 못했습니다: {e}") from e
    try:
        data = response.json()
    except ValueError as e:
        raise ApiError(f"응답 형식 오류: {response.text[:300]}") from e
    text = _response_text(data)
    if text is None:
        raise ApiError(f"응답 형식 오류: {response.text[:300]}")
    return text, _usage(data)


def _response_text(data):
    """Responses API 응답(또는 게이트웨이가 감싼 응답)에서 답변 텍스트를 꺼낸다."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("data"), dict):  # 게이트웨이 공통 형식 {"code", "message", "data"}
        inner = _response_text(data["data"])
        if inner is not None:
            return inner
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    if isinstance(data.get("output"), list):
        parts = [c.get("text", "") for item in data["output"] if isinstance(item, dict) and item.get("type") == "message"
                 for c in item.get("content") or [] if isinstance(c, dict) and c.get("type") == "output_text"]
        return "".join(parts)
    if isinstance(data.get("message"), str):
        return data["message"]
    return None


# ---- 공통 ----

class _StreamFormatError(Exception):
    pass


RAW = object()  # _events가 SSE도 JSON도 아닌 텍스트 조각에 붙이는 표시


def _post(url, headers, data, timeout, stream):
    host = urlparse(url).hostname
    kwargs = dict(headers=headers, json=data, timeout=(15, timeout), stream=stream)
    try:
        if host in _aia_sessions:
            response = _aia_sessions[host].post(url, **kwargs)
        else:
            try:
                response = requests.post(url, **kwargs)
            except requests.exceptions.SSLError:
                if TRUSTSTORE or host not in AIA_HOSTS:
                    raise
                session = requests.Session()
                session.mount(f"https://{host}", _StrictCAAdapter(_aia_bundle(url, host)))
                response = session.post(url, **kwargs)
                _aia_sessions[host] = session
    except requests.RequestException as e:
        raise ApiError(f"네트워크 오류: {e}") from e
    if response.status_code != 200:
        raise ApiError(f"API 오류 {response.status_code}: {response.text[:300]}")
    return response


def _aia_bundle(url, host):
    import certifi

    out = Path(tempfile.gettempdir()) / f"postech-chat-ca-{host}.pem"
    try:
        return certs.build_bundle(url, certifi.where(), out, lambda u: requests.get(u, timeout=15).content)
    except (certs.CertError, OSError, requests.RequestException) as e:
        raise ApiError(f"서버 인증서를 검증하지 못했습니다(중간 인증서 받기 실패): {e}") from e


def _is_json(response):
    return "application/json" in response.headers.get("Content-Type", "").lower()


def _events(response):
    """SSE면 (event, data)를, JSON Lines면 (None, 줄)을, 그 밖의 텍스트면 (RAW, 받은 글자)를 차례로 내놓는다."""
    ctype = response.headers.get("Content-Type", "").lower()
    if "text/event-stream" not in ctype and "json" not in ctype:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")  # 조각 경계에서 한글이 잘려도 이어 붙인다
        for raw in response.iter_content(chunk_size=None):
            text = decoder.decode(raw)
            if text:
                yield RAW, text
        return
    sse = "text/event-stream" in ctype
    event, data = None, []
    for raw in response.iter_lines():
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if not sse:
            if line.strip():
                yield None, line
            continue
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = None, []
        elif line.startswith(":"):
            continue  # 주석(연결 유지용)
        else:
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
    if data:
        yield event, "\n".join(data)


def _read_stream(response, on_delta, cancelled):
    """(답변 텍스트, 토큰 사용량 또는 None)."""
    text, final, usage = "", None, None
    try:
        for event, data in _events(response):
            if cancelled and cancelled():
                break
            kind, value = _chunk(event, data)
            if kind == "done":
                break
            if kind == "delta":
                text += value
            elif kind == "chunk":
                # 형식이 문서에 없는 a1 스트림: 지금까지의 전체 텍스트를 다시 보내는 방식이면 바꾸고, 조각이면 잇는다.
                text = value if text and value.startswith(text) else text + value
            elif kind == "final":
                final, usage = value
                break
            else:
                continue
            on_delta(text)
    except requests.RequestException as e:
        raise ApiError(f"네트워크 오류(스트리밍 중): {e}") from e
    finally:
        response.close()
    result = final if final else text
    if result.lstrip().startswith("{"):
        # 형식 표시 없이 JSON 응답 하나를 통째로 보낸 경우({"message": ...})
        try:
            result = _response_text(json.loads(result)) or result
        except ValueError:
            pass
    if not result and not (cancelled and cancelled()):
        raise _StreamFormatError("받은 내용이 없습니다")
    return result, usage


def _chunk(event, data):
    """스트림 조각 하나를 (종류, 값)으로 바꾼다. 종류: delta, chunk, final, done, None(무시)."""
    if event is RAW:
        return "delta", data
    if data.strip() == "[DONE]":
        return "done", None
    try:
        obj = json.loads(data)
    except ValueError:
        return "chunk", data  # JSON이 아닌 일반 텍스트 조각
    if isinstance(obj, str):
        return "chunk", obj
    if not isinstance(obj, dict):
        return None, None
    kind = obj.get("type") or event or ""
    if kind == "response.output_text.delta":
        return "delta", str(obj.get("delta", ""))
    if kind == "response.completed":
        return "final", (_response_text(obj.get("response") or {}) or None, _usage(obj))
    if kind in ("response.failed", "response.incomplete", "error"):
        err = (obj.get("response") or {}).get("error") or obj.get("error") or obj
        raise ApiError(f"모델 오류: {json.dumps(err, ensure_ascii=False)[:300]}")
    if kind.startswith("response."):
        return None, None  # 생성 시작·추론 요약 같은 진행 이벤트
    choices = obj.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        content = (choices[0].get("delta") or {}).get("content")
        return ("delta", content) if isinstance(content, str) else (None, None)
    for key in ("delta", "text", "content", "message", "answer"):
        if isinstance(obj.get(key), str):
            return "chunk", obj[key]
    return None, None
