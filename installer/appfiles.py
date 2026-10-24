# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""설치 폴더의 앱 파일을 망가뜨리지 않고 바꾼다(installer.py가 쓴다. Windows 전용 모듈을 쓰지 않아 어디서나 시험할 수 있다).

1.11.0까지는 이전 버전의 _internal을 먼저 지우고 새 파일을 풀었다. 앱을 막 끈 직후에는 Windows·백신이 일부 파일을
잠시 붙잡고 있어 지우다 멈추면, 반쯤 지워진 _internal(python312.dll 없음)이 남아 앱이 열리지 않았다.

이제는 새 파일을 설치 폴더 안의 임시 폴더에 모두 푼 뒤, 이전 파일을 이름만 바꿔 비켜 두고(같은 디스크라 즉시 끝난다)
새 파일을 제자리로 옮긴다. Windows는 어떤 프로세스가 불러 둔 DLL(예: VCRUNTIME140.dll)을 지우지는 못하게 하지만
같은 디스크 안에서 옮기는 것은 허락하므로, 폴더째 옮기지 못하면 파일을 하나씩 옮긴다.
옮기기가 끝내 안 되면 이전 파일을 되돌려 놓으므로 이전 버전은 그대로 실행된다.
비켜 둔 이전 파일은 지울 수 있을 때 지우고, 못 지우면 다음 설치 때 지운다.

1.11.2 보강:
- 설치 전: zip 손상(CRC)과 필수 파일(실행 파일·파이썬 DLL·표준 라이브러리·VC 런타임)을 확인한다.
- 설치 후: 새 앱을 실제로 한 번 실행해 보는 확인(check)이 실패하면 이전 버전으로 되돌린다.
- 되돌리기 자체가 실패하면 백업 폴더에 복구 표시(POSCHAT-RESTORE.txt)를 남기고 지우지 않는다.
  복구 표시가 있거나 지금 설치된 앱이 온전하지 않으면 다음 설치도 백업을 먼저 지우지 않고, 새 설치가 확인된 뒤에만 지운다.
"""
import os
import shutil
import time
from pathlib import Path

STAGE = "_update"   # 새 파일을 먼저 푸는 곳
OLD = "_old"        # 이전 파일을 비켜 두는 곳
CORE = "_internal"  # PyInstaller onedir의 실행 파일 옆 폴더(파이썬 DLL·라이브러리)
STALE = ("uninstall.ps1",)  # 예전 버전이 남긴 파일
MARKER = "POSCHAT-RESTORE.txt"  # 되돌리기에 실패한 백업: 이 폴더에만 온전한 이전 버전이 있다
# 이 앱 실행에 꼭 필요한 _internal 안의 파일(Windows 빌드). 하나라도 없으면 "Failed to load Python DLL" 같은 오류가 난다.
REQUIRED_PATTERNS = (("python3*.dll", "libpython3*", "Python"), ("base_library.zip",), ("VCRUNTIME140.dll", "*.dylib", "*.so*"))


class InstallError(Exception):
    def __init__(self, message, backup=None):
        super().__init__(message)
        self.backup = backup  # 되돌리기에 실패했을 때 온전한 이전 버전이 있는 폴더


def _retry(action, attempts, delay):
    for i in range(attempts):
        try:
            return action()
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def remove(path, attempts=1, delay=0.5):
    """path를 지운다. 끝내 지우지 못하면 False(남겨 둔다)."""
    path = Path(path)

    def go():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()

    try:
        _retry(go, attempts, delay)
        return True
    except OSError:
        return False


def _free_dir(dest, name, wipe):
    """dest 안에 비어 있는 작업 폴더 이름을 마련한다.

    wipe: 같은 이름의 지난 폴더를 지우고 그 이름을 쓴다(임시 폴더). False면 있는 폴더는 건드리지 않고 다른 이름을 쓴다(백업).
    """
    path = dest / name
    if (wipe and remove(path, attempts=3)) or not path.exists():
        return path
    for i in range(1, 100):
        alt = dest / f"{name}-{i}"
        if (wipe and remove(alt)) or not alt.exists():
            return alt
    raise InstallError(f"작업 폴더를 만들 수 없습니다: {path}")


def _is_work(p, base):
    return p.name == base or p.name.startswith(base + "-")


def backups(dest):
    """지난 설치가 남긴 백업 폴더들."""
    dest = Path(dest)
    return sorted(p for p in dest.iterdir() if p.is_dir() and _is_work(p, OLD)) if dest.is_dir() else []


def cleanup(dest, exe):
    """지난 설치가 남긴 임시 폴더를 지운다. 백업은 지금 앱이 온전하고 복구 표시가 없을 때만 지운다(못 지우면 그대로 둔다)."""
    dest = Path(dest)
    if not dest.is_dir():
        return
    healthy = complete(dest, exe)
    for p in dest.iterdir():
        if _is_work(p, STAGE):
            remove(p, attempts=2)
        elif _is_work(p, OLD) and healthy and not (p / MARKER).exists():
            remove(p, attempts=2)


def extract(zf, dest, progress=None, share=90):
    """zip을 dest 안의 임시 폴더에 풀고 그 폴더를 돌려준다. 진행은 progress(0~share, 글)로 알린다."""
    bad = zf.testzip()  # 받은 설치 파일이 깨졌으면 아무것도 바꾸기 전에 멈춘다
    if bad:
        raise InstallError(f"설치 파일이 손상되었습니다({bad}). 설치 파일을 다시 받으세요.")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stage = _free_dir(dest, STAGE, wipe=True)
    stage.mkdir()
    members = zf.infolist()
    total = sum(m.file_size for m in members) or 1
    done = 0
    for m in members:
        zf.extract(m, stage)
        done += m.file_size
        if progress:
            progress(done / total * share, "파일 복사 중...")
    return stage


def missing(root, exe):
    """root(설치 폴더 또는 임시 폴더)에 없는 필수 파일 이름들. 비어 있으면 실행에 필요한 파일을 갖췄다."""
    root = Path(root)
    out = [] if (root / exe).is_file() and (root / exe).stat().st_size > 0 else [exe]
    core = root / CORE
    if not core.is_dir():
        return out + [CORE]
    for patterns in REQUIRED_PATTERNS:
        if not any(f.is_file() and f.stat().st_size > 0 for pat in patterns for f in core.glob(pat)):
            out.append(f"{CORE}/{patterns[0]}")
    return out


def complete(root, exe):
    return not missing(root, exe)


def verify(stage, exe):
    """풀어 놓은 앱이 실행에 필요한 파일을 갖췄는지. 없으면 아무것도 바꾸지 않고 멈춘다."""
    lack = missing(stage, exe)
    if lack:
        raise InstallError("설치 파일에 실행에 필요한 파일이 없습니다: " + ", ".join(lack) + ". 설치 파일을 다시 받으세요.")


def move(src, dst, attempts=1, delay=0.5):
    """src를 dst로 옮긴다(같은 디스크). 폴더를 통째로 옮기지 못하면(안의 파일을 누가 쓰는 중) 파일을 하나씩 옮긴다.

    dst가 이미 있는 폴더면 그 안으로 합친다. 끝내 옮기지 못한 파일이 있으면 OSError를 낸다.
    """
    src, dst = Path(src), Path(dst)
    is_dir = src.is_dir() and not src.is_symlink()
    try:
        # 폴더째 옮기기는 안의 파일 하나만 쓰는 중이어도 계속 실패하므로 몇 번만 해 보고 파일 단위로 넘어간다
        _retry(lambda: os.rename(src, dst), min(attempts, 4) if is_dir else attempts, delay)
        return
    except OSError:
        if not is_dir:
            raise
    dst.mkdir(exist_ok=True)
    for child in sorted(src.iterdir()):
        move(child, dst / child.name, attempts, delay)
    _retry(lambda: os.rmdir(src), attempts, delay)


def replace(dest, stage, exe, check=None, attempts=60, delay=0.5):
    """stage의 파일로 dest의 앱 파일을 바꾼다.

    check(dest)가 있으면 바꾼 뒤 새 앱을 확인하고, False를 돌려주거나 예외를 내면 실패로 본다.
    실패하면 이전 파일을 되돌리고 InstallError를 낸다. 되돌리기도 실패하면 백업 폴더에 복구 표시를 남기고
    지우지 않으며, 그 폴더를 InstallError.backup으로 알린다. 성공하면 임시 폴더와 지난 백업을 모두 지운다.
    이름 바꾸기는 파일이 잠깐 잠겨 있으면 attempts × delay초 동안 다시 해 본다.
    """
    dest, stage = Path(dest), Path(stage)
    verify(stage, exe)
    names = sorted(p.name for p in stage.iterdir())
    had_app = complete(dest, exe)
    old = None
    moved_old, moved_new = [], []
    try:
        existing = [n for n in names if (dest / n).exists()]
        if existing:
            old = _free_dir(dest, OLD, wipe=False)  # 지난 백업은 건드리지 않는다
            old.mkdir()
        for n in existing:
            moved_old.append(n)  # 일부만 옮겨졌어도 되돌릴 수 있게 먼저 적는다
            move(dest / n, old / n, attempts, delay)
        for n in names:
            moved_new.append(n)
            move(stage / n, dest / n, attempts, delay)
        lack = missing(dest, exe)
        if lack:
            raise InstallError("바꾼 뒤 필수 파일이 보이지 않습니다: " + ", ".join(lack))
        if check is not None:
            try:
                ok = check(dest)
            except Exception as e:  # 확인 도구 자체의 오류도 설치 실패로 본다
                raise InstallError(f"새 버전이 실행되지 않습니다: {e}") from e
            if ok is False:
                raise InstallError("새 버전이 실행되지 않습니다.")
    except (OSError, InstallError) as e:
        _rollback(dest, stage, old, moved_old, moved_new, had_app, exe, attempts, delay, e)
    for n in STALE:
        remove(dest / n)
    remove(stage, attempts=2)
    for b in backups(dest):  # 이번 백업과, 새 설치가 확인되었으니 지난 복구 표시 백업까지
        remove(b, attempts=4)  # 아직 잠긴 파일이 있으면 다음 설치 때 지운다


def _rollback(dest, stage, old, moved_old, moved_new, had_app, exe, attempts, delay, error):
    """새 파일을 빼고 이전 파일을 제자리로 되돌린다. 되돌렸는지 확인하고, 실패하면 백업을 지키고 알린다."""
    # 새 파일 옮기기는 이전 파일을 모두 비킨 뒤에 하므로 dest의 그 이름에는 새 파일만 있다
    for n in moved_new:
        remove(dest / n, attempts=3)
    for n in moved_old:  # 일부만 옮겨진 폴더는 남은 쪽으로 합친다
        if (old / n).exists():
            try:
                move(old / n, dest / n, attempts, delay)
            except OSError:
                pass
    remove(stage, attempts=2)  # 남은 새 파일(다음 설치 때 다시 푼다)
    restored = all((dest / n).exists() and not (old / n).exists() for n in moved_old) and \
        (not had_app or complete(dest, exe))
    reason = str(error)
    if restored:
        if old is not None:
            remove(old, attempts=2)
        if isinstance(error, InstallError):
            raise InstallError(f"{reason} 이전 버전은 그대로 남아 있습니다. 설치 파일을 다시 받아 설치해 보세요.") from error
        raise InstallError("앱 파일이 아직 사용 중이라 바꾸지 못했습니다. 이전 버전은 그대로 남아 있습니다. "
                           f"잠시 뒤(안 되면 PC를 다시 시작한 뒤) 다시 설치하세요. ({reason})") from error
    backup = old if old is not None and old.exists() else None
    if backup is not None:
        try:
            (backup / MARKER).write_text(
                "POSCHAT 설치가 실패했고 이전 버전을 제자리로 되돌리지 못했습니다.\n"
                f"이 폴더에 이전 버전의 앱 파일이 있습니다. 설치 프로그램을 다시 실행하면 새 버전을 설치하고,\n"
                f"설치가 확인된 뒤에 이 폴더를 지웁니다. 직접 되돌리려면 이 폴더의 파일을 {dest}로 옮기세요.\n"
                f"원인: {reason}\n", encoding="utf-8")
        except OSError:
            pass
    raise InstallError("설치에 실패했고 이전 버전도 제자리로 되돌리지 못했습니다. "
                       + (f"이전 버전은 {backup}에 그대로 보관했습니다. " if backup else "")
                       + "PC를 다시 시작한 뒤 설치 프로그램을 다시 실행하세요. 대화·설정은 안전합니다. "
                       f"({reason})", backup=backup) from error
