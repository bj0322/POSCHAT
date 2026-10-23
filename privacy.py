# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""로그·관측 데이터에 비밀이나 개인 정보가 남지 않게 지우는 도우미. 커넥터 감사 로그와 telemetry가 쓴다."""
import json
import re

# 흔한 키·토큰 형식. 로그에 남기기 전에 [가림]으로 바꾼다.
SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"),          # OpenAI 형식·Langfuse 키
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                 # GitHub 토큰
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),               # GitHub fine-grained PAT
    re.compile(r"\bya29\.[A-Za-z0-9_\-.]{20,}"),                 # Google access token
    re.compile(r"\b1//[A-Za-z0-9_\-]{20,}"),                     # Google refresh token
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),                    # Google API 키
    re.compile(r"\b(?:ntn|secret)_[A-Za-z0-9]{20,}"),            # Notion
    re.compile(r"\bfc-[A-Za-z0-9]{16,}"),                        # Firecrawl
    re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9_\-.=:+/]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b(\s*[:=]\s*)(\"?)[^\s\"',]{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
SECRET_ARG_NAMES = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|cookie|credential)")
MASK = "[가림]"


def redact_text(text, emails=False):
    text = str(text)
    for rx in SECRET_PATTERNS:
        if rx.groups >= 3:
            text = rx.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{MASK}", text)
        elif rx.groups == 1:
            text = rx.sub(lambda m: f"{m.group(1)} {MASK}", text)
        else:
            text = rx.sub(MASK, text)
    if emails:
        text = EMAIL_RE.sub("[이메일]", text)
    return text


def redact_args(arguments, max_value=120):
    """도구 인자의 요약: 이름이 비밀처럼 보이는 값은 가리고, 긴 값(문서 본문·메일 내용)은 길이만 남긴다."""
    def walk(value, key=""):
        if key and SECRET_ARG_NAMES.search(key):
            return MASK
        if isinstance(value, dict):
            return {str(k): walk(v, str(k)) for k, v in list(value.items())[:30]}
        if isinstance(value, list):
            return [walk(v, key) for v in value[:10]] + ([f"…({len(value)}개)"] if len(value) > 10 else [])
        if isinstance(value, str):
            value = redact_text(value, emails=True)
            return value if len(value) <= max_value else f"{value[:max_value]}…({len(value):,}자)"
        return value

    return walk(arguments if isinstance(arguments, dict) else {})


def compact_json(value, limit=1000):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
