import requests

try:
    # genai.postech.ac.kr은 중간 인증서를 보내지 않아 certifi로는 검증에 실패한다.
    # OS 인증서 저장소(Windows는 중간 인증서를 자동으로 받아 옴)로 검증하도록 한다.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

URL = "https://genai.postech.ac.kr/agent/api/a1/gpt"


class ApiError(Exception):
    pass


def ask(api_key, message, timeout=180):
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    data = {"message": message, "stream": False}  # 현재는 stream=False만 지원
    try:
        response = requests.post(URL, headers=headers, json=data, timeout=timeout)
    except requests.RequestException as e:
        raise ApiError(f"네트워크 오류: {e}") from e

    if response.status_code != 200:
        raise ApiError(f"API 오류 {response.status_code}: {response.text[:300]}")
    try:
        return response.json()["message"]
    except (ValueError, KeyError) as e:
        raise ApiError(f"응답 형식 오류: {response.text[:300]}") from e
