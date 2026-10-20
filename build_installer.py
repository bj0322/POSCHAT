"""앱과 설치 프로그램을 빌드한다.

    python build_installer.py

필요 패키지: requirements.txt와 pyinstaller (pip install -r requirements.txt pyinstaller)
결과: Windows는 release/PostechChat-Setup.exe, macOS는 release/PostechChat-mac.dmg(앱 아이콘을 위해 pillow도 필요)
빌드 중간 파일은 %TEMP%\\PostechChat-build 에 만든다(클라우드 동기화 폴더에서 빌드하면 느리다).
"""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = Path(tempfile.gettempdir()) / "PostechChat-build"
ICON = ROOT / "assets" / "icon.ico"
ICON_PNG = ROOT / "assets" / "icon.png"
BUNDLE_ID = "io.github.bj0322.poschat"
APP_DATA = [
    "--add-data", f"{ROOT / 'web'}{os.pathsep}web",
    "--add-data", f"{ROOT / 'skills'}{os.pathsep}skills",
    "--add-data", f"{ROOT / 'LICENSE'}{os.pathsep}.",
    "--add-data", f"{ROOT / 'THIRD_PARTY_NOTICES.md'}{os.pathsep}.",
    "--add-data", f"{ROOT / 'licenses'}{os.pathsep}licenses",
    # python-docx·python-pptx는 새 문서를 만들 때 패키지 안의 기본 서식 파일을 쓴다.
    "--collect-data", "docx", "--collect-data", "pptx",
]


def pyinstaller(*args):
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--workpath", str(WORK / "work"), "--specpath", str(WORK / "spec"), *args,
    ], check=True)


def build_mac():
    """PostechChat.app을 만들고 '응용 프로그램'으로 끌어다 놓는 디스크 이미지(.dmg)로 묶는다."""
    from version import APP_VERSION

    print("[1/2] 앱 빌드")
    pyinstaller(
        "--windowed", "--onedir", "--name", "PostechChat", "--icon", str(ICON_PNG),
        "--osx-bundle-identifier", BUNDLE_ID, *APP_DATA,
        "--distpath", str(WORK / "app"),
        str(ROOT / "main.py"),
    )
    app = WORK / "app" / "PostechChat.app"
    plist_path = app / "Contents" / "Info.plist"
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)
    plist.update(CFBundleDisplayName="POSTECH GenAI Chat", CFBundleShortVersionString=APP_VERSION,
                 CFBundleVersion=APP_VERSION, NSHighResolutionCapable=True)
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)
    # Info.plist를 바꾸면 서명이 깨지므로 다시 임시(ad-hoc) 서명한다. Apple Silicon은 서명 없는 앱을 실행하지 않는다.
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)

    print("[2/2] 디스크 이미지 만들기")
    stage = WORK / "dmg"
    stage.mkdir()
    shutil.copytree(app, stage / app.name, symlinks=True)
    (stage / "Applications").symlink_to("/Applications")
    out = ROOT / "release"
    out.mkdir(exist_ok=True)
    target = out / "PostechChat-mac.dmg"
    target.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", "POSTECH GenAI Chat", "-srcfolder", str(stage),
                    "-ov", "-format", "UDZO", str(target)], check=True)
    print(f"완료: {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")


def main():
    if sys.platform == "darwin":
        if WORK.exists():
            shutil.rmtree(WORK)
        return build_mac()
    if (Path(sys.base_prefix) / "conda-meta").is_dir():
        # conda의 OpenSSL은 실행 파일에 OPENSSL_Applink가 있어야 해서, PyInstaller exe에서는
        # HTTPS 요청 때 "OPENSSL_Uplink: no OPENSSL_Applink"로 프로세스가 꺼진다.
        sys.exit("Anaconda/conda Python으로는 빌드할 수 없습니다. python.org 공식 Python 3.10 이상으로 실행하세요.\n"
                 "  예) py -3.12 -m venv .buildenv && .buildenv\\Scripts\\python -m pip install -r requirements.txt pyinstaller\n"
                 "      .buildenv\\Scripts\\python build_installer.py")
    try:
        import tkinter  # noqa: F401  설치 프로그램 화면에 필요
    except ImportError:
        sys.exit("이 Python에는 tkinter가 없습니다. python.org 설치 프로그램으로 설치한 Python(tcl/tk 포함)을 쓰세요.")
    if WORK.exists():
        shutil.rmtree(WORK)

    print("[1/3] 앱 빌드")
    pyinstaller(
        "--windowed", "--onedir", "--name", "PostechChat", "--icon", str(ICON), *APP_DATA,
        "--distpath", str(WORK / "app"),
        str(ROOT / "main.py"),
    )
    app_dir = WORK / "app" / "PostechChat"

    print("[2/3] 앱 압축")
    payload = WORK / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(app_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(app_dir).as_posix())

    print("[3/3] 설치 프로그램 빌드")
    pyinstaller(
        "--windowed", "--onefile", "--name", "PostechChat-Setup", "--icon", str(ICON),
        "--add-data", f"{payload};.",
        "--add-data", f"{ICON};.",
        "--add-data", f"{ICON_PNG};.",
        "--paths", str(ROOT),  # installer.py가 저장소 최상위의 version.py를 가져온다
        "--distpath", str(WORK / "setup"),
        str(ROOT / "installer" / "installer.py"),
    )
    out = ROOT / "release"
    out.mkdir(exist_ok=True)
    target = out / "PostechChat-Setup.exe"
    shutil.copy2(WORK / "setup" / "PostechChat-Setup.exe", target)
    print(f"완료: {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
