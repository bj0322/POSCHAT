"""앱과 설치 프로그램을 빌드한다.

    python build_installer.py

필요 패키지: requests, truststore, pywebview, pyinstaller (pip install -r requirements.txt pyinstaller)
결과: release/PostechChat-Setup.exe
빌드 중간 파일은 %TEMP%\\PostechChat-build 에 만든다(클라우드 동기화 폴더에서 빌드하면 느리다).
"""
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


def pyinstaller(*args):
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--workpath", str(WORK / "work"), "--specpath", str(WORK / "spec"), *args,
    ], check=True)


def main():
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
        "--windowed", "--onedir", "--name", "PostechChat", "--icon", str(ICON),
        "--add-data", f"{ROOT / 'web'};web",
        "--add-data", f"{ROOT / 'skills'};skills",
        "--add-data", f"{ROOT / 'LICENSE'};.",
        "--add-data", f"{ROOT / 'THIRD_PARTY_NOTICES.md'};.",
        "--add-data", f"{ROOT / 'licenses'};licenses",
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
