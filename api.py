"""POSTECH GenAI API 호출.

세 가지 방식을 지원한다.
- chat_completions(기본): POSTECH GenAI의 OpenAI 호환 Chat Completions(`.../agent/openai_compatible/a1/v1`).
  GPT·Claude·Gemini를 모델 ID로 고른다. 인증은 x-api-key 헤더(다른 OpenAI 호환 서버를 위해 Bearer도 함께 보낸다).
- responses: 게이트웨이의 OpenAI Responses API(`.../a<번호>/openai/responses`). 모델을 고를 수 있다.
  주소의 a<번호>는 POSTECH GenAI 콘솔에서 확인해 설정에 넣는다.
- a1: `agent/api/a1/gpt` 단일 호출 API. 모델은 서버가 정한다.

stream을 켜면 받은 글자를 on_delta(지금까지의 전체 텍스트)로 넘긴다. OpenAI 방식은 표준 SSE를,
a1은 문서에 형식이 없어서 SSE·JSON Lines·일반 텍스트를 모두 받아 주고, 실패하면 한 번에 받는 방식으로 다시 요청한다.
응답 헤더의 크레딧 사용량은 on_credit으로 알린다.
"""
import codecs
import json
import re
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit

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
    ("gpt-6.1-sol", "GPT-6.1 Sol"),
    ("gpt-6-astra", "GPT-6 Astra"),
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash"),
]
RESPONSES_MODELS = MODELS[:5]
DEFAULT_MODEL = MODELS[0][0]
MODEL_LABELS = dict(MODELS)
# 1.9 이전 목록의 잘못된 모델 ID. 게이트웨이는 Claude를 점 대신 -로 쓴다(claude-opus-5-5).
MODEL_ALIASES = {"claude-opus-5.5": "claude-opus-5-5", "claude-sonnet-5.5": "claude-sonnet-5-5"}
# 콘솔(에이전트 API)에 안내된 POSTECH GenAI의 OpenAI 호환 주소. 설정에 주소가 없으면 이 주소를 쓴다.
DEFAULT_CHAT_COMPLETIONS_URL = "https://genai.postech.ac.kr/agent/openai_compatible/a1/v1/chat/completions"
DEFAULT_MODE = "chat_completions"  # 1.9부터. a1/gpt는 2026년 10월 현재 서버 오류만 돌려준다
STT_MODEL = "gemini-3.8-flash"  # OpenAI 호환 API에서 음성(input_audio)을 받아 적을 수 있는 모델
REASONING_EFFORT = "low"  # 에이전트는 단계마다 호출하므로 추론 토큰을 아낀다


class ApiError(Exception):
    pass


# 호출이 끝날 때마다 on_usage(mode, model, usage)를 부른다. usage는 서버가 알려 준 토큰 수
# {"input_tokens", "output_tokens"} 또는 None. 앱(main.py)이 storage.record_usage로 설정한다.
on_usage = None


@dataclass
class ApiSettings:
    mode: str = "a1"               # "a1" | "responses" | "chat_completions"(설정의 기본값은 DEFAULT_MODE)
    responses_url: str = ""
    chat_completions_url: str = ""
    model: str = DEFAULT_MODEL
    stream: bool = True

    @classmethod
    def from_config(cls, config):
        mode = config.get("api_mode", DEFAULT_MODE)
        return cls(
            mode=mode if mode in ("a1", "responses", "chat_completions") else DEFAULT_MODE,
            responses_url=endpoint_url(config.get("responses_url"), RESPONSES_PATH),
            chat_completions_url=endpoint_url(config.get("chat_completions_url"), CHAT_COMPLETIONS_PATH)
            or DEFAULT_CHAT_COMPLETIONS_URL,
            model=normalize_model(config.get("model") or DEFAULT_MODEL),
            stream=bool(config.get("stream", True)),
        )


RESPONSES_PATH = "/responses"
CHAT_COMPLETIONS_PATH = "/chat/completions"


def normalize_model(model_id):
    model_id = str(model_id or "")
    return MODEL_ALIASES.get(model_id, model_id)


def _auth_headers(api_key, **extra):
    """OpenAI 호환 API 인증. POSTECH 게이트웨이는 x-api-key를, 다른 OpenAI 호환 서버는 Bearer 토큰을 본다."""
    return {"x-api-key": api_key, "Authorization": f"Bearer {api_key}", **extra}


def endpoint_url(value, path):
    """설정에 넣은 주소를 호출할 주소로 맞춘다.

    OpenAI 호환 도구처럼 기본 주소(`.../v1`, `.../openai`)만 넣어도 path(/responses, /chat/completions)를
    붙여 준다. 끝의 /와 실수로 넣은 /models도 정리한다. `?api-version=...` 같은 쿼리는 경로 뒤에 그대로 둔다.
    """
    url = str(value or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    base = parts.path.rstrip("/")
    if base.endswith("/models"):
        base = base[: -len("/models")]
    if not base.endswith(path):
        base += path
    return urlunsplit(parts._replace(path=base))


def _sibling_url(chat_completions_url, path):
    """Chat Completions 주소와 같은 기본 주소 아래의 다른 API 주소(.../models, .../audio/transcriptions)."""
    url = endpoint_url(chat_completions_url, CHAT_COMPLETIONS_PATH)
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=parts.path[: -len(CHAT_COMPLETIONS_PATH)] + path))


def models_url(chat_completions_url):
    """Chat Completions 주소와 같은 기본 주소의 모델 목록(GET .../models) 주소."""
    return _sibling_url(chat_completions_url, "/models")


def list_models(api_key, chat_completions_url, timeout=20):
    """OpenAI 호환 API가 알려 주는 모델 ID 목록. 서버가 정한 순서를 지킨다."""
    url = models_url(chat_completions_url)
    if not url:
        raise ApiError("Chat Completions 주소를 먼저 입력하세요.")
    try:
        response = _request("GET", url, _auth_headers(api_key, Accept="application/json"), None, timeout, stream=False)
    except ApiError as e:
        if "API 오류 404" in str(e):
            raise ApiError("이 서버는 모델 목록(GET .../models)을 알려 주지 않습니다. 기본 목록을 그대로 쓰세요.") from e
        raise
    try:
        data = response.json()
    except ValueError as e:
        raise ApiError(f"모델 목록 형식 오류: {response.text[:300]}") from e
    items = data.get("data") if isinstance(data, dict) else data
    if isinstance(items, dict):  # 게이트웨이 공통 형식 {"code", "message", "data": {"data": [...]}}
        items = items.get("data")
    if not isinstance(items, list):
        raise ApiError(f"모델 목록 형식 오류: {response.text[:300]}")
    ids = []
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str) and model_id.strip() and model_id.strip() not in ids:
            ids.append(model_id.strip())
    if not ids:
        raise ApiError("서버가 사용할 수 있는 모델을 알려 주지 않았습니다.")
    return ids


def model_label(model_id):
    return MODEL_LABELS.get(model_id, model_id)


def transcribe(api_key, chat_completions_url, wav_b64, language=None, context="", model=STT_MODEL, timeout=120):
    """OpenAI 호환 Chat Completions에 음성(input_audio)을 보내 받아 적게 한다.

    POSTECH 게이트웨이에는 /audio/transcriptions가 없지만 Gemini는 Chat Completions로 음성을 받는다.
    """
    lang = {"ko": "한국어", "en": "영어"}.get(language, "들리는 언어")
    instruction = (f"이 강의 음성을 {lang} 그대로 받아 적으세요. 받아 적은 글만 출력하고, 요약·설명·따옴표를 붙이지 마세요. "
                   "말이 없거나 알아들을 수 없으면 아무것도 출력하지 마세요.")
    if context:
        instruction += f"\n\n참고(앞부분 전사·강의 자료 용어, 받아 적지 말 것):\n{context[-600:]}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "input_audio", "input_audio": {"data": wav_b64, "format": "wav"}},
        ]}],
        "reasoning_effort": "none",
    }
    url = endpoint_url(chat_completions_url, CHAT_COMPLETIONS_PATH) or DEFAULT_CHAT_COMPLETIONS_URL
    response = _post(url, _auth_headers(api_key, **{"Content-Type": "application/json"}), payload, timeout, stream=False)
    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ApiError(f"음성 인식 응답 형식 오류: {response.text[:300]}") from e
    if on_usage:
        try:
            on_usage("stt", model, _usage(data))
        except Exception:
            pass
    return text.strip()


_NUMBERED_RE = re.compile(r"^\s*\[?(\d+)\]?\s*[|:.)\]]\s?(.*)$")


def refine_transcript(api_key, chat_completions_url, wav_b64, drafts, language=None, context="", model=STT_MODEL,
                      timeout=180):
    """로컬 음성 인식 초안 drafts(구간 글 목록)를 음성과 대조해 고친다.

    음성은 drafts의 구간을 차례로 이어 붙인 것이다. 고친 글 목록(drafts와 같은 길이)을 돌려주고,
    모델이 번호를 맞춰 답하지 않으면 번호 없이 이어 쓴 글(str)을 돌려준다.
    """
    lang = {"ko": "한국어", "en": "영어"}.get(language, "들리는 언어")
    lines = "\n".join(f"{i}| {t}" for i, t in enumerate(drafts, 1))
    instruction = (f"이 강의 음성은 아래 {len(drafts)}개 구간을 차례로 이어 붙인 것입니다. 각 줄은 로컬 음성 인식기가 받아 적은 초안이라 "
                   f"틀린 글자가 있을 수 있습니다. 음성을 듣고 구간마다 {lang} 그대로 고쳐 `번호| 고친 글` 형식으로 "
                   f"1번부터 {len(drafts)}번까지 한 줄씩 출력하세요. 맞는 초안은 그대로 두고, 말이 없는 구간은 `번호|`만 쓰세요. "
                   "다른 설명은 쓰지 마세요.")
    if context:
        instruction += f"\n\n참고(강의 자료 용어·앞부분, 받아 적지 말 것):\n{context[-600:]}"
    instruction += f"\n\n[초안]\n{lines}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "input_audio", "input_audio": {"data": wav_b64, "format": "wav"}},
        ]}],
        "reasoning_effort": "none",
    }
    url = endpoint_url(chat_completions_url, CHAT_COMPLETIONS_PATH) or DEFAULT_CHAT_COMPLETIONS_URL
    response = _post(url, _auth_headers(api_key, **{"Content-Type": "application/json"}), payload, timeout, stream=False)
    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ApiError(f"음성 인식 응답 형식 오류: {response.text[:300]}") from e
    if on_usage:
        try:
            on_usage("stt", model, _usage(data))
        except Exception:
            pass
    return parse_numbered(text, len(drafts))


def parse_numbered(text, count):
    """`번호| 글` 줄들을 count개 목록으로. 번호가 다 맞지 않으면 번호를 뗀 글 전체(str)."""
    found, loose = {}, []
    for line in (text or "").strip().splitlines():
        match = _NUMBERED_RE.match(line)
        if match and 1 <= int(match.group(1)) <= count:
            found[int(match.group(1))] = match.group(2).strip()
        elif line.strip():
            loose.append(line.strip())
    if len(found) == count:
        return [found[i] for i in range(1, count + 1)]
    return " ".join([found[i] for i in sorted(found)] + loose).strip()


# ---- 크레딧 ----
# POSTECH 게이트웨이는 모든 응답 헤더에 이번 주기(WEEKLY 등)의 크레딧 사용량과 한도를 담아 준다.
# 크레딧 정보가 담긴 응답을 받을 때마다 on_credit({"usage", "limit", "interval"})을 부른다.
on_credit = None


def _credit(headers):
    def num(name):
        try:
            return float(headers.get(name))
        except (TypeError, ValueError):
            return None
    usage, limit = num("x-role-ratelimit-credit-usage"), num("x-role-ratelimit-credit-limit")
    if usage is None and limit is None:
        return None
    return {"usage": usage, "limit": limit, "interval": (headers.get("x-role-ratelimit-credit-limit-interval") or "").strip()}


def credit(api_key, chat_completions_url=None, timeout=15):
    """크레딧 사용량만 확인한다. GET .../models는 POSTECH에서 404지만 크레딧 헤더가 붙고 크레딧을 쓰지 않는다."""
    url = models_url(chat_completions_url or DEFAULT_CHAT_COMPLETIONS_URL)
    response = _send("GET", url, _auth_headers(api_key, Accept="application/json"), timeout=timeout, stream=False)
    if response.status_code in (401, 403):
        raise ApiError(f"API 키를 확인하세요 (HTTP {response.status_code}).")
    info = _credit(response.headers)
    if info is None:
        raise ApiError("이 서버는 크레딧 정보를 알려 주지 않습니다.")
    return info


def _notify_credit(info):
    if info and on_credit:
        try:
            on_credit(info)
        except Exception:
            pass


def ask(api_key, message, timeout=180, settings=None, on_delta=None, cancelled=None, images=None):
    """모델 답변 전체를 돌려준다. on_delta가 있고 스트리밍이 켜져 있으면 받는 동안 중간 텍스트를 넘긴다.

    images는 [(MIME 형식, base64)]이며 Responses/호환 API에서 보낸다(a1은 글자만 받는다).
    """
    settings = settings or ApiSettings()
    stream = bool(on_delta) and settings.stream
    if settings.mode == "responses":
        text, usage = _ask_responses(api_key, message, timeout, settings, on_delta if stream else None, cancelled,
                                     images)
    elif settings.mode == "chat_completions":
        text, usage = _ask_chat_completions(api_key, message, timeout, settings,
                                            on_delta if stream else None, cancelled, images)
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
            on_usage(settings.mode, settings.model if settings.mode != "a1" else "a1", usage)
        except Exception:
            pass  # 사용량 기록 실패로 답변을 잃지 않는다
    return text


def _ask_chat_completions(api_key, message, timeout, settings, on_delta, cancelled, images=None):
    if not settings.chat_completions_url:
        raise ApiError("OpenAI 호환 API를 쓰려면 설정에서 Chat Completions 주소를 입력하세요.")
    content = message
    if images:
        content = [{"type": "text", "text": message}] + [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
            for mime, data in images
        ]
    payload = {
        "model": settings.model,
        "messages": [{"role": "user", "content": content}],
        "stream": bool(on_delta),
    }
    headers = _auth_headers(api_key, **{"Content-Type": "application/json"})
    response = _post(settings.chat_completions_url, headers, payload, timeout, stream=bool(on_delta))
    if on_delta and not _is_json(response):
        try:
            return _read_stream(response, on_delta, cancelled)
        except _StreamFormatError as e:
            raise ApiError(f"스트리밍 응답을 해석하지 못했습니다: {e}") from e
    try:
        data = response.json()
        choice = data["choices"][0]
        text = choice["message"]["content"]
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not isinstance(text, str):
            raise TypeError("응답 내용이 문자열이 아닙니다.")
        return text, _usage(data)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ApiError(f"응답 형식 오류: {response.text[:300]}") from e


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
            text, usage = data["message"], _usage(data)
        except (ValueError, KeyError, TypeError) as e:
            raise ApiError(f"응답 형식 오류: {response.text[:300]}") from e
    else:
        text, usage = _read_stream(response, on_delta, cancelled)
    _check_a1_error(text)
    return text, usage


# 서버가 답변 대신 보내는 오류 표시. 2026년 10월 기준 a1/gpt는 모든 요청에 이것만 돌려준다(코드 10000).
_A1_ERROR_RE = re.compile(r'^\s*<div\s+cls="error"\s+attr="(\d+)"\s*>\s*</div>\s*$')


def _check_a1_error(text):
    match = _A1_ERROR_RE.match(text or "")
    if match:
        raise ApiError(f"기본(a1/gpt) 서버가 답변 대신 오류 {match.group(1)}을(를) 돌려줬습니다. "
                       "설정 → API 방식에서 'OpenAI 호환 API'를 고르세요(주소는 비워 두면 POSTECH 주소를 씁니다).")


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
    return _request("POST", url, headers, data, timeout, stream)


def _request(method, url, headers, data, timeout, stream, form=None, files=None):
    response = _send(method, url, headers, data, timeout, stream, form, files)
    if response.status_code != 200:
        raise ApiError(f"API 오류 {response.status_code}: {response.text[:300]}")
    return response


def _send(method, url, headers, data=None, timeout=60, stream=False, form=None, files=None):
    """요청을 보내고 응답을 그대로 돌려준다(상태 코드는 보지 않는다). 크레딧 헤더가 있으면 on_credit으로 알린다."""
    host = urlparse(url).hostname
    kwargs = dict(headers=headers, timeout=(15, timeout), stream=stream)
    if data is not None:
        kwargs["json"] = data
    if form is not None:
        kwargs["data"] = form
    if files is not None:
        kwargs["files"] = files
    try:
        if host in _aia_sessions:
            response = _aia_sessions[host].request(method, url, **kwargs)
        else:
            try:
                response = requests.request(method, url, **kwargs)
            except requests.exceptions.SSLError:
                if TRUSTSTORE or host not in AIA_HOSTS:
                    raise
                session = requests.Session()
                session.mount(f"https://{host}", _StrictCAAdapter(_aia_bundle(url, host)))
                response = session.request(method, url, **kwargs)
                _aia_sessions[host] = session
    except requests.RequestException as e:
        raise ApiError(f"네트워크 오류: {e}") from e
    _notify_credit(_credit(response.headers))
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
