# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""도구·네트워크 공용 도우미: ToolFailure와 공용 HTTP 요청.

내장 MCP 서버(office_mcp·paper_mcp 등)뿐 아니라 sync·rag·telemetry·vector_store·web_research·paper도 쓴다.
MCP 서버 모듈이 아닌 곳에서 office_mcp를 가져오지 않도록 여기에 둔다. office_mcp는 같은 이름을 다시 내보낸다.
"""


class ToolFailure(Exception):
    pass


_SESSION = None


def http(method, url, timeout=30, **kwargs):
    """requests 호출. 연결 실패는 ToolFailure로 바꾼다. 응답 상태는 호출한 쪽이 본다."""
    global _SESSION
    import requests

    if _SESSION is None:
        try:
            import truststore  # Windows 인증서 저장소를 쓴다(학교·회사 프록시 인증서). 안드로이드에는 없다

            truststore.inject_into_ssl()
        except ImportError:
            pass
        from version import APP_VERSION

        _SESSION = requests.Session()
        _SESSION.headers["User-Agent"] = f"POSCHAT/{APP_VERSION} (+https://github.com/bj0322/POSCHAT)"
    try:
        return _SESSION.request(method, url, timeout=timeout, **kwargs)
    except requests.RequestException as e:
        raise ToolFailure(f"인터넷 요청에 실패했습니다({url.split('?')[0]}): {type(e).__name__}: {e}")
