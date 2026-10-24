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
"""
import os
import shutil
import time
from pathlib import Path

STAGE = "_update"   # 새 파일을 먼저 푸는 곳
OLD = "_old"        # 이전 파일을 비켜 두는 곳
CORE = "_internal"  # PyInstaller onedir의 실행 파일 옆 폴더(파이썬 DLL·라이브러리)
STALE = ("uninstall.ps1",)  # 예전 버전이 남긴 파일


class InstallError(Exception):
    pass


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


def _free_dir(dest, name):
    """dest 안에 비어 있는 작업 폴더 이름을 마련한다. 지난번 것이 지워지지 않으면 다른 이름을 쓴다."""
    path = dest / name
    if remove(path, attempts=3):
        return path
    for i in range(1, 100):
        alt = dest / f"{name}-{i}"
        if remove(alt, attempts=1):
            return alt
    raise InstallError(f"작업 폴더를 만들 수 없습니다: {path}")


def cleanup(dest):
    """지난 설치가 남긴 작업 폴더를 지운다(못 지우면 그대로 둔다)."""
    dest = Path(dest)
    if not dest.is_dir():
        return
    for p in dest.iterdir():
        if p.name in (STAGE, OLD) or p.name.startswith((STAGE + "-", OLD + "-")):
            remove(p, attempts=2)


def extract(zf, dest, progress=None, share=90):
    """zip을 dest 안의 임시 폴더에 풀고 그 폴더를 돌려준다. 진행은 progress(0~share, 글)로 알린다."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stage = _free_dir(dest, STAGE)
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


def verify(stage, exe):
    """풀어 놓은 앱이 실행에 필요한 파일을 갖췄는지(실행 파일과 파이썬 DLL)."""
    stage = Path(stage)
    if not (stage / exe).is_file():
        raise InstallError(f"설치 파일에 {exe}가 없습니다.")
    core = stage / CORE
    if core.is_dir() and not any(core.glob("python3*.dll")) and not any(core.glob("libpython3*")) \
            and not any(core.glob("Python*")):
        raise InstallError("설치 파일에 파이썬 라이브러리가 없습니다.")


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


def replace(dest, stage, attempts=60, delay=0.5):
    """stage의 파일로 dest의 앱 파일을 바꾼다. 실패하면 이전 파일을 되돌리고 InstallError를 낸다.

    이름 바꾸기는 파일이 잠깐 잠겨 있으면 attempts × delay초 동안 다시 해 본다.
    """
    dest, stage = Path(dest), Path(stage)
    names = sorted(p.name for p in stage.iterdir())
    old = None
    moved_old, moved_new = [], []
    try:
        existing = [n for n in names if (dest / n).exists()]
        if existing:
            old = _free_dir(dest, OLD)
            old.mkdir()
        for n in existing:
            moved_old.append(n)  # 일부만 옮겨졌어도 되돌릴 수 있게 먼저 적는다
            move(dest / n, old / n, attempts, delay)
        for n in names:
            moved_new.append(n)
            move(stage / n, dest / n, attempts, delay)
    except OSError as e:
        # 되돌린다: 새 파일 옮기기는 이전 파일을 모두 비킨 뒤에 하므로 dest의 그 이름에는 새 파일만 있다
        for n in moved_new:
            remove(dest / n, attempts=3)
        for n in moved_old:  # 일부만 옮겨진 폴더는 남은 쪽으로 합친다
            if (old / n).exists():
                try:
                    move(old / n, dest / n, attempts, delay)
                except OSError:
                    pass
        raise InstallError("앱 파일이 아직 사용 중이라 바꾸지 못했습니다. 이전 버전은 그대로 남아 있습니다. "
                           f"잠시 뒤(안 되면 PC를 다시 시작한 뒤) 다시 설치하세요. ({e})") from e
    for n in STALE:
        remove(dest / n)
    remove(stage, attempts=2)
    if old is not None:
        remove(old, attempts=4)  # 아직 잠긴 파일이 있으면 다음 설치 때 지운다
