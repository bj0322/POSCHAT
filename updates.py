"""Check and download signed-in users' private GitHub Releases."""
import os
import re
import sys
from pathlib import Path

import requests

REPOSITORY = "bj0322/POSCHAT"
RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSETS = {
    "windows": "PostechChat-Setup.exe",
    "macos": "PostechChat-mac.dmg",
    "android": "PostechChat.apk",
}
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024


class UpdateError(Exception):
    pass


def current_platform():
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "android" or (sys.platform.startswith("linux") and os.environ.get("APPDATA")):
        return "android"
    return "unsupported"


def _version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    if not match:
        raise UpdateError(f"릴리스 버전 형식이 올바르지 않습니다: {value}")
    return tuple(map(int, match.groups()))


def _headers(token, accept="application/vnd.github+json"):
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "POSTECH-GenAI-Chat",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _latest_release(token):
    try:
        response = requests.get(RELEASE_URL, headers=_headers(token), timeout=(10, 20))
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 서버에 연결하지 못했습니다: {e}") from e
    if response.status_code == 404 and not token:
        raise UpdateError("저장소가 비공개이므로 업데이트 확인용 GitHub 읽기 토큰이 필요합니다.")
    if response.status_code in (401, 403, 404):
        raise UpdateError("GitHub 토큰이 유효하지 않거나 비공개 저장소의 릴리스 읽기 권한이 없습니다.")
    if response.status_code != 200:
        raise UpdateError(f"GitHub 업데이트 확인 실패 (HTTP {response.status_code}).")
    try:
        release = response.json()
    except ValueError as e:
        raise UpdateError("GitHub에서 올바르지 않은 업데이트 정보를 받았습니다.") from e
    if not isinstance(release, dict) or release.get("draft"):
        raise UpdateError("GitHub에서 유효한 정식 릴리스를 찾지 못했습니다.")
    return release


def check_update(installed_version, token="", platform=None):
    release = _latest_release(token)
    version = str(release.get("tag_name", "")).removeprefix("v")
    if _version(version) <= _version(installed_version):
        return {"available": False, "version": version}
    platform = platform or current_platform()
    asset_name = ASSETS.get(platform)
    asset = next((a for a in release.get("assets", []) if a.get("name") == asset_name), None)
    if asset is None:
        raise UpdateError(f"{version} 릴리스에 이 기기용 설치 파일({asset_name or platform})이 없습니다.")
    return {
        "available": True,
        "version": version,
        "name": str(release.get("name") or f"POSTECH GenAI Chat {version}"),
        "notes": str(release.get("body") or "").strip(),
        "release_url": str(release.get("html_url") or ""),
    }


def download_update(installed_version, token="", platform=None, destination=None):
    release = _latest_release(token)
    version = str(release.get("tag_name", "")).removeprefix("v")
    if _version(version) <= _version(installed_version):
        raise UpdateError("이미 최신 버전입니다.")
    platform = platform or current_platform()
    asset_name = ASSETS.get(platform)
    asset = next((a for a in release.get("assets", []) if a.get("name") == asset_name), None)
    if asset is None or not isinstance(asset.get("id"), int):
        raise UpdateError(f"{version} 릴리스에 이 기기용 설치 파일({asset_name or platform})이 없습니다.")
    size = asset.get("size")
    if isinstance(size, int) and (size <= 0 or size > MAX_DOWNLOAD_BYTES):
        raise UpdateError("업데이트 파일 크기가 허용 범위를 벗어났습니다.")
    path = Path(destination or Path.home() / "PostechChat-update" / asset_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/{REPOSITORY}/releases/assets/{asset['id']}"
    try:
        with requests.get(url, headers=_headers(token, "application/octet-stream"),
                          timeout=(15, 180), stream=True) as response:
            if response.status_code != 200:
                raise UpdateError(f"업데이트 파일 다운로드 실패 (HTTP {response.status_code}).")
            temp_path = path.with_suffix(path.suffix + ".part")
            downloaded = 0
            try:
                with temp_path.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > MAX_DOWNLOAD_BYTES or (isinstance(size, int) and downloaded > size):
                            raise UpdateError("업데이트 파일 크기가 예상 범위를 초과했습니다.")
                        out.write(chunk)
                if downloaded == 0 or (isinstance(size, int) and downloaded != size):
                    raise UpdateError("업데이트 파일이 비어 있거나 다운로드가 완전하지 않습니다.")
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 파일을 다운로드하지 못했습니다: {e}") from e
    return path
