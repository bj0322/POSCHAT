# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""업데이트 서버에서 새 버전을 확인하고 이 기기용 설치 파일을 내려받는다.

저장소가 비공개라서 GitHub 대신 자체 업데이트 서버(UPDATE_BASE_URL)를 쓴다. 서버는 GitHub의 releases/latest와 같은 모양의 JSON
(`/api/releases/latest`)과 파일(`/releases/download/<태그>/<이름>`)을 준다.
서버 주소가 http여도 변조되지 않도록, 설치 파일은 릴리스를 만든 CI의 Ed25519 서명(`<이름>.sig`)을 앱에 넣은 공개키로
확인한 뒤에만 쓴다. 서명이 없거나 맞지 않으면 설치하지 않는다(건너뛰는 설정은 없다). 크기와 SHA-256(digest)도 함께 확인한다.
"""
import base64
import hashlib
import os
import re
import sys
from pathlib import Path

import requests

REPOSITORY = "bj0322/POSCHAT"  # 소스 코드 주소(설정의 라이선스 정보)에만 쓴다. 업데이트는 아래 서버에서 받는다.
# 업데이트 서버. 도메인과 HTTPS가 생기면 이 값만 바꾼다(설치 파일은 서명으로 확인하므로 http여도 변조되지 않는다).
UPDATE_BASE_URL = "http://3.38.118.65"
# 서명 공개키(Ed25519 raw 32바이트의 base64). 여러 개를 두면 하나라도 맞을 때 받아들인다(키 교체: docs/security.md).
UPDATE_PUBLIC_KEYS = ("Et1RfxsTZ4VAy/odq+idHpUVPwcvfoHkkp8fPwY4g/A=",)
# Microsoft Store 제품 ID(파트너 센터의 'Store ID', 9N…로 시작). 비어 있으면 Store의 '다운로드 및 업데이트' 화면을 연다.
STORE_PRODUCT_ID = ""
RELEASE_URL = f"{UPDATE_BASE_URL}/api/releases/latest"
RELEASES_PAGE = f"{UPDATE_BASE_URL}/"
DOWNLOAD_PREFIX = f"{UPDATE_BASE_URL}/releases/download/"
ASSETS = {
    "windows": "POSCHAT-Setup.exe",
    "macos": "POSCHAT-mac.dmg",
    "android": "POSCHAT.apk",
}
USER_AGENT = "POSCHAT"
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
MAX_SIGNATURE_BYTES = 1024
SIGNATURE_CONTEXT = b"POSCHAT-update-v1"


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


def signed_message(tag, name, size, sha256):
    """서명하는 내용: 태그·파일 이름·크기·SHA-256. 다른 버전이나 다른 파일의 서명을 바꿔치기할 수 없다."""
    return b"\n".join([SIGNATURE_CONTEXT, tag.encode(), name.encode(), str(size).encode(), sha256.encode()])


def verify_signature(message, signature, keys=None):
    """signature(base64 문자열)가 공개키 중 하나로 message에 맞는지 확인한다. 아니면 UpdateError."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:
        raise UpdateError("서명을 확인할 수 없어 업데이트를 설치하지 않습니다.") from e
    try:
        raw = base64.b64decode(str(signature).strip(), validate=True)
    except ValueError as e:
        raise UpdateError("업데이트 서명 형식이 올바르지 않습니다.") from e
    for key in UPDATE_PUBLIC_KEYS if keys is None else keys:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(raw, message)
            return
        except (InvalidSignature, ValueError):
            continue
    raise UpdateError("업데이트 서명이 맞지 않습니다. 설치하지 않습니다.")


def latest_release(timeout=15):
    """최신 정식 릴리스 {"version", "name", "notes", "url", "assets": {이름: asset}}."""
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    try:
        response = requests.get(RELEASE_URL, headers=headers, timeout=(10, timeout), allow_redirects=False)
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 서버에 연결하지 못했습니다: {e}") from e
    if response.status_code == 404:
        raise UpdateError("업데이트 서버에 올라온 릴리스가 아직 없습니다.")
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
        "url": RELEASES_PAGE,
        "assets": {a.get("name"): a for a in release.get("assets") or [] if isinstance(a, dict)},
    }


def asset_name(release, platform=None):
    """릴리스에 있는 이 기기용 설치 파일 이름(서명 파일이 함께 있을 때만) 또는 None."""
    name = ASSETS.get(platform or current_platform())
    if name and name in release["assets"] and name + ".sig" in release["assets"]:
        return name
    return None


def check(installed_version, platform=None):
    """{"available", "version", "name", "notes", "url", "asset"(이 기기용 파일 이름 또는 None)}."""
    release = latest_release()
    newer = version_tuple(release["version"]) > version_tuple(installed_version)
    return {"available": newer, "version": release["version"], "name": release["name"],
            "notes": release["notes"][:4000], "url": release["url"], "asset": asset_name(release, platform)}


def _asset_url(release, asset, name):
    """서버가 알려 준 파일 주소. 이 서버의 이 버전 폴더 안 이름이 같은 파일만 받아들인다."""
    url = str(asset.get("browser_download_url") or "")
    if url != f"{DOWNLOAD_PREFIX}v{release['version']}/{name}":
        raise UpdateError("업데이트 파일 주소가 이 업데이트 서버의 릴리스가 아닙니다.")
    return url


def _fetch_signature(url):
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(15, 30), allow_redirects=False)
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 서명을 내려받지 못했습니다: {e}") from e
    if r.status_code != 200:
        raise UpdateError(f"업데이트 서명을 내려받지 못했습니다 (HTTP {r.status_code}).")
    text = r.text
    if not text.strip() or len(text) > MAX_SIGNATURE_BYTES:
        raise UpdateError("업데이트 서명 형식이 올바르지 않습니다.")
    return text


def download(installed_version, directory, platform=None, on_progress=None, cancelled=None):
    """새 버전의 이 기기용 설치 파일을 받아 서명·크기·SHA-256을 확인한 뒤 directory에 두고 경로를 돌려준다."""
    release = latest_release()
    if version_tuple(release["version"]) <= version_tuple(installed_version):
        raise UpdateError("이미 최신 버전입니다.")
    name = asset_name(release, platform)
    asset = release["assets"].get(name) if name else None
    if not asset:
        raise UpdateError(f"{release['version']} 릴리스에 이 기기용 설치 파일이나 서명이 없습니다. 업데이트 서버 페이지에서 받으세요.")
    url, size = _asset_url(release, asset, name), asset.get("size")
    if not isinstance(size, int) or not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise UpdateError("업데이트 파일 크기 정보가 올바르지 않습니다.")
    digest = str(asset.get("digest") or "").lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise UpdateError("업데이트 파일의 SHA-256 정보가 없습니다. 설치하지 않습니다.")
    expected = digest[len("sha256:"):]
    signature = _fetch_signature(_asset_url(release, release["assets"][name + ".sig"], name + ".sig"))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path, part = directory / name, directory / (name + ".part")
    sha, done = hashlib.sha256(), 0
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(15, 120), stream=True,
                          allow_redirects=False) as r:
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
        if sha.hexdigest() != expected:
            raise UpdateError("내려받은 업데이트 파일이 손상되었습니다(SHA-256 불일치). 다시 시도하세요.")
        verify_signature(signed_message(f"v{release['version']}", name, size, expected), signature)
        os.replace(part, path)  # 서명까지 맞은 파일만 최종 이름이 된다
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
