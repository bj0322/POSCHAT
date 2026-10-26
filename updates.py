# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""GitHub Releases에서 새 버전을 확인하고 이 기기용 설치 파일을 내려받는다.

공개 저장소의 Releases API(토큰 없음)를 쓴다. 저장소가 비공개인 동안은 404가 오므로 확인하지 못했다고만 알린다.
내려받은 파일은 Releases가 알려 준 크기와 SHA-256(digest)으로 확인한다.
"""
import hashlib
import os
import re
import sys
from pathlib import Path

import requests

REPOSITORY = "bj0322/POSCHAT"
# Microsoft Store 제품 ID(파트너 센터의 'Store ID', 9N…로 시작). 비어 있으면 Store의 '다운로드 및 업데이트' 화면을 연다.
STORE_PRODUCT_ID = ""
RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPOSITORY}/releases/download/"
ASSETS = {
    "windows": "POSCHAT-Setup.exe",
    "macos": "POSCHAT-mac.dmg",
    "android": "POSCHAT.apk",
}
# 1.10 이전 이름. 1.9.1~1.10.0 앱이 자동 업데이트할 수 있도록 릴리스에 같은 파일을 이 이름으로도 올린다.
# 이 앱은 새 이름을 먼저 찾고, 새 이름이 없는 릴리스(1.10.0 이전)에서는 예전 이름을 쓴다.
LEGACY_ASSETS = {
    "windows": "PostechChat-Setup.exe",
    "macos": "PostechChat-mac.dmg",
    "android": "PostechChat.apk",
}
USER_AGENT = "POSCHAT"
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024


class UpdateError(Exception):
    pass


def current_platform():
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "android" or hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ:
        return "android"
    return "unsupported"


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    if not match:
        raise UpdateError(f"릴리스 버전 형식이 올바르지 않습니다: {value}")
    return tuple(map(int, match.groups()))


def latest_release(timeout=15):
    """최신 정식 릴리스 {"version", "name", "notes", "url", "assets": {이름: asset}}."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": USER_AGENT}
    try:
        response = requests.get(RELEASE_URL, headers=headers, timeout=(10, timeout))
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 서버에 연결하지 못했습니다: {e}") from e
    if response.status_code == 404:
        raise UpdateError("업데이트 정보를 찾지 못했습니다(저장소가 공개되면 확인할 수 있습니다).")
    if response.status_code == 403:
        raise UpdateError("GitHub 요청이 잠시 제한되었습니다. 나중에 다시 확인하세요.")
    if response.status_code != 200:
        raise UpdateError(f"업데이트 확인 실패 (HTTP {response.status_code}).")
    try:
        release = response.json()
    except ValueError as e:
        raise UpdateError("업데이트 정보 형식이 올바르지 않습니다.") from e
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        raise UpdateError("정식 릴리스를 찾지 못했습니다.")
    version = str(release.get("tag_name", "")).removeprefix("v")
    version_tuple(version)
    return {
        "version": version,
        "name": str(release.get("name") or f"POSCHAT {version}"),
        "notes": str(release.get("body") or "").strip(),
        "url": str(release.get("html_url") or RELEASES_PAGE),
        "assets": {a.get("name"): a for a in release.get("assets") or [] if isinstance(a, dict)},
    }


def asset_name(release, platform=None):
    """릴리스에 있는 이 기기용 설치 파일 이름(새 이름 우선) 또는 None."""
    platform = platform or current_platform()
    for name in (ASSETS.get(platform), LEGACY_ASSETS.get(platform)):
        if name and name in release["assets"]:
            return name
    return None


def check(installed_version, platform=None):
    """{"available", "version", "name", "notes", "url", "asset"(이 기기용 파일 이름 또는 None)}."""
    release = latest_release()
    newer = version_tuple(release["version"]) > version_tuple(installed_version)
    return {"available": newer, "version": release["version"], "name": release["name"],
            "notes": release["notes"][:4000], "url": release["url"], "asset": asset_name(release, platform)}


def download(installed_version, directory, platform=None, on_progress=None, cancelled=None):
    """새 버전의 이 기기용 설치 파일을 directory에 내려받아 경로를 돌려준다."""
    release = latest_release()
    if version_tuple(release["version"]) <= version_tuple(installed_version):
        raise UpdateError("이미 최신 버전입니다.")
    name = asset_name(release, platform)
    asset = release["assets"].get(name) if name else None
    if not asset:
        raise UpdateError(f"{release['version']} 릴리스에 이 기기용 설치 파일이 없습니다. Releases 페이지에서 받으세요.")
    url, size = str(asset.get("browser_download_url") or ""), asset.get("size")
    if not url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError("업데이트 파일 주소가 이 저장소의 Releases가 아닙니다.")
    if not isinstance(size, int) or not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise UpdateError("업데이트 파일 크기 정보가 올바르지 않습니다.")
    digest = str(asset.get("digest") or "")
    expected = digest[len("sha256:"):].lower() if digest.startswith("sha256:") else None
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path, part = directory / name, directory / (name + ".part")
    sha, done = hashlib.sha256(), 0
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(15, 120), stream=True) as r:
            if r.status_code != 200:
                raise UpdateError(f"업데이트 파일을 내려받지 못했습니다 (HTTP {r.status_code}).")
            with open(part, "wb") as out:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if cancelled and cancelled():
                        raise UpdateError("내려받기를 취소했습니다.")
                    done += len(chunk)
                    if done > size:
                        raise UpdateError("업데이트 파일이 예상보다 큽니다.")
                    sha.update(chunk)
                    out.write(chunk)
                    if on_progress:
                        on_progress(done, size)
        if done != size:
            raise UpdateError("업데이트 파일을 끝까지 받지 못했습니다. 다시 시도하세요.")
        if expected and sha.hexdigest() != expected:
            raise UpdateError("내려받은 업데이트 파일이 손상되었습니다(SHA-256 불일치). 다시 시도하세요.")
        os.replace(part, path)
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 파일을 내려받지 못했습니다: {e}") from e
    finally:
        part.unlink(missing_ok=True)
    return path, release["version"]


def store_url():
    """Store판의 업데이트 안내에서 여는 주소: 제품 페이지(ID가 있으면) 또는 Store의 다운로드 및 업데이트."""
    if STORE_PRODUCT_ID:
        return f"ms-windows-store://pdp/?productid={STORE_PRODUCT_ID}"
    return "ms-windows-store://downloadsandupdates"
