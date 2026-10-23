# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""라이선스 자동 점검(CI의 license 작업과 tests/test_license.py가 부른다).

    python tools/license_check.py repo                      # LICENSE 원문·SPDX 머리말·필수 문서·배포 설정
    python tools/license_check.py deps [--out 파일.md]       # 설치된 의존성의 라이선스 목록(requirements 기준)
    python tools/license_check.py package <폴더|zip|apk>...  # 배포 결과물에 라이선스 전문·제3자 고지가 들었는지

도구가 찾은 결과는 사람이 검토할 재료일 뿐, 법적 호환성을 확정하지 않는다(docs/license-audit.md).
"""
import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# https://www.gnu.org/licenses/agpl-3.0.txt (GNU AGPL v3 공식 영문 원문)의 SHA-256
AGPL_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"
SPDX_LINE = "SPDX-License-Identifier: AGPL-3.0-only"
COPYRIGHT_LINE = "SPDX-FileCopyrightText: 2026 Beomjoon Kim"
SOURCE_SUFFIXES = {".py", ".js", ".css", ".html", ".kt", ".kts", ".bat", ".yml", ".yaml", ".sh"}
# 제3자 파일·생성 파일: 프로젝트의 AGPL 머리말을 붙이지 않는다
THIRD_PARTY = ("web/vendor/", "licenses/", "android/gradle/", "android/gradlew")
REQUIRED_DOCS = ["LICENSE", "LICENSE_HISTORY.md", "THIRD_PARTY_NOTICES.md", "docs/license-audit.md"]
# 라이선스 이름에 이런 말이 있으면 AGPL-3.0-only 배포와 함께 쓸 수 없을 가능성이 높아 사람이 꼭 본다
INCOMPATIBLE = re.compile(r"proprietary|commercial|non-?commercial|\bNC\b|SSPL|Commons Clause|BUSL|Elastic|"
                          r"GPL-2\.0-only|GPLv2 only|\bCDDL|\bEPL-1|JSON License|Original BSD|BSD-4", re.I)


def fail(errors):
    for e in errors:
        print(f"FAIL {e}")
    return 1 if errors else 0


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):  # git이 없는 소스 아카이브
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def check_repo():
    errors = []
    license_file = ROOT / "LICENSE"
    if not license_file.is_file():
        errors.append("루트 LICENSE가 없습니다.")
    elif hashlib.sha256(license_file.read_bytes()).hexdigest() != AGPL_SHA256:
        errors.append("LICENSE가 GNU AGPL v3 공식 원문(https://www.gnu.org/licenses/agpl-3.0.txt)과 다릅니다.")
    for doc in REQUIRED_DOCS:
        if not (ROOT / doc).is_file():
            errors.append(f"필수 라이선스 문서가 없습니다: {doc}")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8") if (ROOT / "THIRD_PARTY_NOTICES.md").is_file() else ""
    for link in re.findall(r"\((licenses/[^)]+)\)", notices):
        if not (ROOT / link).is_file():
            errors.append(f"THIRD_PARTY_NOTICES.md가 가리키는 라이선스 원문이 없습니다: {link}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "## 라이선스" not in readme or "AGPL-3.0-only" not in readme:
        errors.append("README에 AGPL-3.0-only 라이선스 절이 없습니다.")
    # 배포 결과물에 라이선스가 들어가도록 한 빌드 설정
    build = (ROOT / "build_installer.py").read_text(encoding="utf-8")
    gradle = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        if f"ROOT / '{name}'" not in build:
            errors.append(f"build_installer.py가 앱에 {name}을 넣지 않습니다.")
        if f'"{name}"' not in gradle:
            errors.append(f"android/app/build.gradle.kts가 APK에 {name}을 넣지 않습니다.")
    checked = 0
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix not in SOURCE_SUFFIXES or rel.startswith(THIRD_PARTY) or not path.is_file():
            continue
        head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:6])
        checked += 1
        if SPDX_LINE not in head or COPYRIGHT_LINE not in head:
            errors.append(f"SPDX 저작권·라이선스 머리말이 없습니다: {rel}")
        if re.search(r"SPDX-License-Identifier:\s*(?!AGPL-3\.0-only\b)\S+", head):
            errors.append(f"다른 SPDX 라이선스가 적혀 있습니다(AGPL-3.0-only만 씁니다): {rel}")
    print(f"repo: 소스 {checked}개 머리말 확인, LICENSE 원문·문서·빌드 설정 확인")
    return fail(errors)


def _requirement_names(files):
    names = []
    for f in files:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                names.append(re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0])
    return names


def _license_of(dist):
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr.strip()
    text = (meta.get("License") or "").strip()
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if text and len(text) <= 80 and "\n" not in text:
        return text
    return " / ".join(classifiers) or (text.splitlines()[0][:80] if text else "")


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_rows(requirement_files):
    seen, rows = set(), []
    queue = _requirement_names(requirement_files)
    while queue:
        name = _norm(queue.pop(0))
        if name in seen:
            continue
        seen.add(name)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # 이 플랫폼에서 설치되지 않는 의존성(예: Windows 전용)
        lic = _license_of(dist)
        status = "확인 필요(라이선스 정보 없음)" if not lic else ("검토 필요" if INCOMPATIBLE.search(lic) else "특이 사항 없음")
        rows.append((dist.metadata["Name"], dist.version, lic or "?", status))
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            queue.append(re.split(r"[<>=!~;\[ (]", req, maxsplit=1)[0])
    return sorted(rows, key=lambda r: r[0].lower())


LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS|COPYRIGHT)", re.I)


def license_files(dist):
    """패키지가 함께 싣는 라이선스·고지 파일들(dist-info/licenses/ 포함)."""
    found = []
    for f in dist.files or []:
        if LICENSE_FILE.match(f.name) or "licenses" in f.parts[:-1]:
            path = Path(f.locate())
            if path.is_file():
                found.append(path)
    return found


def collect(dest, requirement_files=None):
    """배포본에 넣을 의존성 라이선스 원문을 dest/<패키지>-<버전>/에 모은다(build_installer.py가 부른다)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    rows = dependency_rows(requirement_files or [ROOT / "requirements.txt"])
    index = ["# Python 패키지 라이선스", "", "| Package | Version | License |", "|---|---|---|"]
    for name, version, lic, _ in rows:
        folder = dest / f"{name}-{version}"
        folder.mkdir(exist_ok=True)
        files = license_files(metadata.distribution(name))
        for f in files:
            (folder / f.name).write_bytes(f.read_bytes())
        if not files:  # 원문 파일을 싣지 않은 패키지: 메타데이터의 라이선스 글을 남긴다
            text = metadata.distribution(name).metadata.get("License") or lic
            (folder / "LICENSE-metadata.txt").write_text(text, encoding="utf-8")
        index.append(f"| {name} | {version} | {lic} |")
    # PyInstaller가 함께 묶는 Python 인터프리터 자체(PSF-2.0)
    for cand in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
                 Path(sys.base_prefix) / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "LICENSE.txt"):
        if cand.is_file():
            py = dest / f"CPython-{sys.version.split()[0]}"
            py.mkdir(exist_ok=True)
            (py / "LICENSE.txt").write_bytes(cand.read_bytes())
            index.append(f"| CPython | {sys.version.split()[0]} | PSF-2.0 |")
            break
    (dest / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return rows


def check_deps(out=None, requirement_files=None):
    files = requirement_files or [ROOT / "requirements.txt"]
    rows = dependency_rows(files)
    lines = ["| Package | Version | License (메타데이터) | 자동 점검 |", "|---|---|---|---|"]
    lines += [f"| {n} | {v} | {lic} | {s} |" for n, v, lic, s in rows]
    text = "\n".join(lines) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
    print(text)
    flagged = [f"{n} {v}: {lic}" for n, v, lic, s in rows if s == "검토 필요"]
    unknown = [n for n, v, lic, s in rows if s.startswith("확인 필요")]
    if unknown:
        print("WARN 라이선스 정보가 없는 패키지(사람이 확인): " + ", ".join(unknown))
    return fail([f"AGPL과 함께 쓸 수 없을 수 있는 라이선스(사람이 검토): {x}" for x in flagged])


def check_package(paths, python_licenses=False):
    errors = []
    want = hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest()
    for raw in paths:
        path = Path(raw)
        found_license = found_notices = found_python = False
        if path.is_dir():
            for f in path.rglob("*"):
                if f.is_file() and f.name in ("LICENSE", "LICENSE.txt") and hashlib.sha256(f.read_bytes()).hexdigest() == want:
                    found_license = True
                found_notices |= f.name == "THIRD_PARTY_NOTICES.md"
                found_python |= "licenses/python/" in f.as_posix()
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    base = info.filename.rsplit("/", 1)[-1]
                    if base in ("LICENSE", "LICENSE.txt") and hashlib.sha256(z.read(info)).hexdigest() == want:
                        found_license = True
                    found_notices |= base == "THIRD_PARTY_NOTICES.md"
                    found_python |= "licenses/python/" in info.filename
        else:
            errors.append(f"{path}: 폴더나 zip(apk)이 아닙니다.")
            continue
        if not found_license:
            errors.append(f"{path}: AGPL 라이선스 전문(LICENSE)이 없습니다.")
        if not found_notices:
            errors.append(f"{path}: THIRD_PARTY_NOTICES.md가 없습니다.")
        if python_licenses and not found_python:
            errors.append(f"{path}: Python 패키지 라이선스 원문(licenses/python/)이 없습니다.")
        if found_license and found_notices and (found_python or not python_licenses):
            print(f"package OK: {path}")
    return fail(errors)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("repo")
    deps = sub.add_parser("deps")
    deps.add_argument("--out")
    deps.add_argument("--requirements", nargs="*")
    pkg = sub.add_parser("package")
    pkg.add_argument("paths", nargs="+")
    pkg.add_argument("--python-licenses", action="store_true", help="데스크톱 앱: licenses/python/도 있어야 한다")
    args = parser.parse_args(argv)
    if args.cmd == "repo":
        return check_repo()
    if args.cmd == "deps":
        return check_deps(args.out, args.requirements)
    return check_package(args.paths, args.python_licenses)


if __name__ == "__main__":
    sys.exit(main())
