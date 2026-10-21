"""Check and download public updates from the configured CDN."""
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

CDN_BASE_URL = "https://pub-a728df363f0f4ef5a6ee3fae8245231f.r2.dev"
MANIFEST_URL = f"{CDN_BASE_URL}/latest.json"
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
        raise UpdateError(f"업데이트 버전 형식이 올바르지 않습니다: {value}")
    return tuple(map(int, match.groups()))


def _latest_manifest():
    try:
        response = requests.get(
            MANIFEST_URL,
            headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "POSTECH-GenAI-Chat"},
            params={"_": time.time_ns()},
            timeout=(10, 20),
        )
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 서버에 연결하지 못했습니다: {e}") from e
    if response.status_code == 404:
        raise UpdateError("CDN에 업데이트 정보가 아직 게시되지 않았습니다.")
    if response.status_code != 200:
        raise UpdateError(f"CDN 업데이트 확인 실패 (HTTP {response.status_code}).")
    try:
        manifest = response.json()
    except ValueError as e:
        raise UpdateError("CDN에서 올바르지 않은 업데이트 정보를 받지 못했습니다.") from e
    if not isinstance(manifest, dict):
        raise UpdateError("CDN 업데이트 정보의 형식이 올바르지 않습니다.")
    _version(manifest.get("version"))
    if not isinstance(manifest.get("assets"), dict):
        raise UpdateError("CDN 업데이트 정보에 설치 파일 목록이 없습니다.")
    return manifest


def _asset(manifest, platform):
    asset_name = ASSETS.get(platform)
    asset = manifest["assets"].get(platform)
    if not asset_name or not isinstance(asset, dict) or asset.get("file") != asset_name:
        raise UpdateError(
            f"{manifest['version']} 업데이트에 이 기기용 설치 파일({asset_name or platform})이 없습니다."
        )
    size = asset.get("size")
    digest = asset.get("sha256")
    if type(size) is not int or size <= 0 or size > MAX_DOWNLOAD_BYTES:
        raise UpdateError("업데이트 파일 크기 정보가 올바르지 않습니다.")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise UpdateError("업데이트 파일 체크섬 정보가 올바르지 않습니다.")
    return asset_name, asset


def check_update(installed_version, platform=None):
    manifest = _latest_manifest()
    version = str(manifest["version"]).removeprefix("v")
    if _version(version) <= _version(installed_version):
        return {"available": False, "version": version}
    _asset(manifest, platform or current_platform())
    return {
        "available": True,
        "version": version,
        "name": str(manifest.get("name") or f"POSTECH GenAI Chat {version}"),
        "notes": str(manifest.get("notes") or "").strip(),
    }


def download_update(installed_version, platform=None, destination=None):
    manifest = _latest_manifest()
    version = str(manifest["version"]).removeprefix("v")
    if _version(version) <= _version(installed_version):
        raise UpdateError("이미 최신 버전입니다.")
    platform = platform or current_platform()
    asset_name, asset = _asset(manifest, platform)
    path = Path(destination or Path.home() / "PostechChat-update" / asset_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{CDN_BASE_URL}/releases/{quote(version, safe='.')}/{quote(asset_name)}"
    temp_path = path.with_suffix(path.suffix + ".part")
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with requests.get(url, headers={"User-Agent": "POSTECH-GenAI-Chat"},
                          timeout=(15, 180), stream=True) as response:
            if response.status_code != 200:
                raise UpdateError(f"업데이트 파일 다운로드 실패 (HTTP {response.status_code}).")
            with temp_path.open("wb") as out:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES or downloaded > asset["size"]:
                        raise UpdateError("업데이트 파일 크기가 예상 범위를 초과했습니다.")
                    digest.update(chunk)
                    out.write(chunk)
        if downloaded != asset["size"]:
            raise UpdateError("업데이트 파일이 비어 있거나 다운로드가 완전하지 않습니다.")
        if digest.hexdigest().lower() != asset["sha256"].lower():
            raise UpdateError("업데이트 파일 체크섬이 일치하지 않습니다.")
        os.replace(temp_path, path)
    except requests.RequestException as e:
        raise UpdateError(f"업데이트 파일을 다운로드하지 못했습니다: {e}") from e
    finally:
        temp_path.unlink(missing_ok=True)
    return path
