# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15): 작업 폴더의 Git 상태·차이·스테이지·커밋. 파일 편집 로직(code_workspace)과 나눈다.

안전 규칙
- git은 셸 없이 인자 목록으로 부른다. 경로는 code_workspace.clean_rel로 검사한 뒤 '--' 뒤에 두고,
  --literal-pathspecs로 ':(glob)' 같은 경로 마법도 끈다(경로가 옵션이나 패턴으로 읽히지 않는다).
- 저장소 설정이 프로그램을 실행하는 길(core.fsmonitor, 외부 diff·textconv)은 끈다. 자격 증명을 묻지 않는다(GIT_TERMINAL_PROMPT=0).
- 앱이 부르는 명령은 status·diff·add·restore --staged·commit뿐이다. reset --hard·clean·checkout·push·이력 고치기는 없다.
  커밋은 사용자가 고른(스테이지한) 변경만, 사용자가 확인한 메시지로 한다(-a를 쓰지 않는다). 커밋 훅은 git 그대로 돈다.
- git 출력과 파일 내용은 AI에게 넘길 때 외부 데이터로 감싼다(code_api가 connectors.wrap_untrusted로).
"""
import difflib
import os
import shutil
import subprocess

import code_workspace as cw

TIMEOUT = 30
MAX_DIFF_BYTES = 400_000
MAX_FILES = 2000
SAFE_CONFIG = ["-c", "core.fsmonitor=false", "-c", "core.quotepath=off", "-c", "color.ui=false",
               "-c", "diff.external=", "-c", "core.pager=cat", "--literal-pathspecs", "--no-pager"]


class GitError(Exception):
    pass


def available():
    return shutil.which("git") is not None


def _env():
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_EDITOR="true", GIT_PAGER="cat", LC_ALL="C",
               LANGUAGE="C")
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def _git(root, args, timeout=TIMEOUT, stdin=None, check=True):
    if not available():
        raise GitError("git이 설치되어 있지 않습니다. https://git-scm.com 에서 설치하세요.")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run(["git", *SAFE_CONFIG, *args], cwd=str(root), input=stdin, capture_output=True,
                           timeout=timeout, env=_env(), creationflags=flags,
                           stdin=None if stdin is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise GitError(f"git이 {timeout}초 안에 끝나지 않았습니다.")
    except OSError as e:
        raise GitError(f"git을 실행하지 못했습니다: {e}")
    if check and r.returncode != 0:
        msg = r.stderr.decode("utf-8", errors="replace").strip() or r.stdout.decode("utf-8", errors="replace").strip()
        raise GitError(msg[:800] or f"git 종료 코드 {r.returncode}")
    return r


def _paths(workspace, paths):
    out = []
    for p in paths or []:
        rel = cw.clean_rel(str(p))
        if not rel:
            raise GitError("파일을 고르세요.")
        cw.resolve(workspace, rel, allow_root=False)  # 링크로 작업 폴더 밖을 가리키면 거절
        out.append(rel)
    if not out:
        raise GitError("파일을 고르세요.")
    if len(out) > MAX_FILES:
        raise GitError("한 번에 고를 수 있는 파일이 너무 많습니다.")
    return out


def repo_info(workspace):
    root = cw.root_of(workspace)
    if not available():
        return {"repo": False, "git": False, "reason": "git이 설치되어 있지 않습니다."}
    r = _git(root, ["rev-parse", "--show-toplevel", "--show-prefix"], check=False)
    if r.returncode != 0:
        return {"repo": False, "git": True, "reason": "작업 폴더가 Git 저장소가 아닙니다."}
    lines = r.stdout.decode("utf-8", errors="replace").splitlines()
    return {"repo": True, "git": True, "top": lines[0] if lines else "", "prefix": lines[1] if len(lines) > 1 else ""}


STATE_NAMES = {"M": "수정", "A": "추가", "D": "삭제", "R": "이름 바꿈", "C": "복사", "T": "종류 바뀜", "U": "충돌", "?": "새 파일"}


def _entry(path, x, y, orig=""):
    conflict = x == "U" or y == "U" or (x, y) in (("A", "A"), ("D", "D"))
    return {"path": path, "orig": orig, "x": x, "y": y, "staged": x not in (".", "?", "!") and not conflict,
            "unstaged": y not in (".", "?", "!") and not conflict, "untracked": x == "?", "conflict": conflict,
            "label": "충돌" if conflict else STATE_NAMES.get(y if y != "." else x, "")}


def status(workspace):
    """현재 가지·앞서고 뒤처진 커밋 수·변경 파일. 작업 폴더가 저장소 안의 하위 폴더면 그 안의 파일만."""
    info = repo_info(workspace)
    if not info["repo"]:
        return info
    root = cw.root_of(workspace)
    r = _git(root, ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"])
    fields = r.stdout.decode("utf-8", errors="replace").split("\0")
    prefix = info["prefix"]
    out = {"repo": True, "git": True, "branch": "", "detached": False, "upstream": "", "ahead": 0, "behind": 0,
           "files": [], "outside": 0, "truncated": False}
    i = 0
    while i < len(fields):
        item = fields[i]
        i += 1
        if not item:
            continue
        if item.startswith("# branch.head "):
            head = item[len("# branch.head "):]
            out["detached"] = head == "(detached)"
            out["branch"] = "" if out["detached"] else head
        elif item.startswith("# branch.upstream "):
            out["upstream"] = item[len("# branch.upstream "):]
        elif item.startswith("# branch.ab "):
            parts = item.split()
            out["ahead"], out["behind"] = abs(int(parts[2])), abs(int(parts[3]))
        elif item[0] in "12u?":
            x, y, orig = "?", "?", ""
            if item[0] == "1":
                parts = item.split(" ", 8)
                x, y, raw = parts[1][0], parts[1][1], parts[8]
            elif item[0] == "2":
                parts = item.split(" ", 9)
                x, y, raw = parts[1][0], parts[1][1], parts[9]
                orig = fields[i] if i < len(fields) else ""
                i += 1  # -z: 원래 이름이 다음 칸에 온다
            elif item[0] == "u":
                parts = item.split(" ", 10)
                x, y, raw = parts[1][0], parts[1][1], parts[10]
            else:
                raw = item[2:]
            if prefix and not raw.startswith(prefix):  # 저장소의 다른 폴더(작업 폴더 밖)
                out["outside"] += 1
                continue
            if len(out["files"]) >= MAX_FILES:
                out["truncated"] = True
                continue
            strip = len(prefix)
            out["files"].append(_entry(raw[strip:], x, y, orig[strip:] if orig.startswith(prefix) else orig))
    out["conflicts"] = sum(1 for f in out["files"] if f["conflict"])
    return out


def diff(workspace, rel, staged=False):
    """파일 하나의 차이(unified). 새 파일(추적 안 함)은 빈 파일과의 차이로 만든다."""
    rel = _paths(workspace, [rel])[0]
    root = cw.root_of(workspace)
    args = ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M"] + (["--cached"] if staged else []) + ["--", rel]
    text = _git(root, args).stdout
    if not text.strip() and not staged:
        tracked = _git(root, ["ls-files", "--error-unmatch", "--", rel], check=False).returncode == 0
        path = cw.resolve(workspace, rel, allow_root=False)
        if not tracked and path.is_file():
            raw, _ = cw._read_checked(path, root)
            if cw.looks_binary(raw):
                return {"path": rel, "staged": staged, "diff": f"(바이너리 새 파일: {len(raw):,} bytes)", "truncated": False}
            new = cw.decode(raw[:MAX_DIFF_BYTES])[0].splitlines()
            text = "\n".join(difflib.unified_diff([], new, "/dev/null", f"b/{rel}", lineterm="")).encode("utf-8")
    truncated = len(text) > MAX_DIFF_BYTES
    return {"path": rel, "staged": staged, "diff": text[:MAX_DIFF_BYTES].decode("utf-8", errors="replace"),
            "truncated": truncated}


def diff_all(workspace, staged=False, max_bytes=MAX_DIFF_BYTES):
    """작업 폴더 전체 차이(커밋 메시지·리뷰 요청용)."""
    root = cw.root_of(workspace)
    args = ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M", "--stat", "--patch"] + \
        (["--cached"] if staged else []) + ["--", "."]
    text = _git(root, args).stdout
    return {"diff": text[:max_bytes].decode("utf-8", errors="replace"), "truncated": len(text) > max_bytes}


def stage(workspace, paths):
    rels = _paths(workspace, paths)
    _git(cw.root_of(workspace), ["add", "--", *rels])
    return {"staged": rels}


def unstage(workspace, paths):
    rels = _paths(workspace, paths)
    root = cw.root_of(workspace)
    r = _git(root, ["restore", "--staged", "--", *rels], check=False)
    if r.returncode != 0:  # 첫 커밋 전(HEAD 없음)이거나 오래된 git
        _git(root, ["rm", "--cached", "-q", "--", *rels])
    return {"unstaged": rels}


def commit(workspace, message):
    """스테이지한 변경만 커밋한다(사용자가 메시지를 확인한 뒤 화면에서 부른다)."""
    message = str(message or "").strip()
    if not message:
        raise GitError("커밋 메시지를 입력하세요.")
    if len(message) > 5000:
        raise GitError("커밋 메시지가 너무 깁니다.")
    root = cw.root_of(workspace)
    staged = _git(root, ["diff", "--cached", "--name-only", "-z"]).stdout.split(b"\0")
    if not any(staged):
        raise GitError("스테이지한 변경이 없습니다. 커밋할 파일을 먼저 스테이지하세요.")
    _git(root, ["commit", "-F", "-"], stdin=message.encode("utf-8"), timeout=120)
    head = _git(root, ["log", "-1", "--format=%h %s"]).stdout.decode("utf-8", errors="replace").strip()
    return {"commit": head}
