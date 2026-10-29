# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""원격(SSH) 작업 폴더의 경로와 호출(1.18). Code 화면이 로컬 폴더 대신 SSH 서버의 폴더에서 일할 수 있게 한다.

- 원격 작업 폴더는 'ssh://<연결 이름>/<절대 경로>' 글(설정·작업 기록에 남기는 꼴)이고, 실행 중에는 RPath(연결 이름 + 경로)다.
- code_workspace·code_git·code_project의 함수에 @remote_ok를 붙이면, 인자에 원격 경로가 있을 때 같은 함수를 원격 도우미
  (remote_helper, 서버에서 도는 작은 파이썬)에서 실행한다. 그래서 작업 폴더 밖 차단·안전한 저장·외부 변경 감지·Git 안전 규칙이
  로컬과 똑같이 서버에서 적용된다.
- 연결(ssh_remote.SshConnection 또는 시험용 remote_client.LocalHelper)은 register()로 이름을 붙여 둔다.

이 파일은 원격 도우미와 함께 서버로 보내져 실행된다(Python 3.6 이상에서 돌아야 한다: 새 문법을 쓰지 않는다).
"""
import base64
import functools
import os
import posixpath
import threading
import types
from pathlib import PurePath, PurePosixPath

SCHEME = "ssh://"
_conns = {}
_lock = threading.Lock()


class RemoteError(OSError):
    """연결이 없거나 끊김, 원격에서 알 수 없는 오류. 사용자에게 그대로 보일 글을 담는다."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.strerror = message

    def __str__(self):
        return self.message


# ---- 연결 목록 ----

def register(name, conn):
    with _lock:
        _conns[name] = conn


def unregister(name, conn=None):
    with _lock:
        if conn is None or _conns.get(name) is conn:
            _conns.pop(name, None)


def connection(name):
    with _lock:
        conn = _conns.get(name)
    if conn is None or not getattr(conn, "alive", False):
        raise RemoteError("SSH 연결이 없습니다({}). 코드 화면 위의 'SSH'에서 다시 연결하세요.".format(name))
    return conn


def connected(name):
    with _lock:
        conn = _conns.get(name)
    return bool(conn is not None and getattr(conn, "alive", False))


# ---- 경로 ----

def is_remote(value):
    return isinstance(value, RPath) or (isinstance(value, str) and value.startswith(SCHEME))


def split(value):
    """원격 경로(글 또는 RPath) → (연결 이름, 절대 경로)."""
    if isinstance(value, RPath):
        return value.host, value.path
    rest = str(value)[len(SCHEME):]
    host, sep, path = rest.partition("/")
    if not host:
        raise RemoteError("원격 경로가 올바르지 않습니다: {}".format(value))
    return host, _norm("/" + path)


def url(host, path):
    return SCHEME + host + _norm(path)


def path_of(value):
    """작업 폴더 글 → RPath(원격) 또는 그대로(로컬)."""
    if isinstance(value, RPath):
        return value
    if isinstance(value, str) and value.startswith(SCHEME):
        host, path = split(value)
        return RPath(host, path)
    return value


def label(value):
    """화면에 보일 'host:/path'."""
    host, path = split(value)
    return "{}:{}".format(host, path)


def _norm(path):
    p = posixpath.normpath(str(path).replace("\\", "/") or "/")
    if p.startswith("//"):
        p = "/" + p.lstrip("/")
    return p if p.startswith("/") else "/" + p


class StatResult:
    """os.stat_result에서 앱이 쓰는 값만."""
    __slots__ = ("st_size", "st_mtime", "st_mode", "st_dev", "st_ino")

    def __init__(self, st_size=0, st_mtime=0.0, st_mode=0, st_dev=0, st_ino=0):
        self.st_size, self.st_mtime, self.st_mode, self.st_dev, self.st_ino = st_size, st_mtime, st_mode, st_dev, st_ino

    @classmethod
    def of(cls, st):
        return cls(st.st_size, st.st_mtime, st.st_mode, st.st_dev, st.st_ino)

    def as_dict(self):
        return {"st_size": self.st_size, "st_mtime": self.st_mtime, "st_mode": self.st_mode, "st_dev": self.st_dev,
                "st_ino": self.st_ino}


class RPath:
    """원격 경로. pathlib.Path에서 앱이 쓰는 것만 흉내 낸다. 파일 작업은 연결을 거쳐 서버에서 한다.
    일부러 os.fspath를 지원하지 않는다(실수로 같은 이름의 로컬 파일을 건드리지 않게)."""
    __slots__ = ("host", "path", "_st")

    def __init__(self, host, path, st=None):
        self.host = host
        self.path = _norm(path)
        self._st = st   # 목록에서 함께 받은 stat(있으면 stat()이 서버에 묻지 않는다)

    # 순수 경로 연산
    def __str__(self):
        return url(self.host, self.path)

    def __repr__(self):
        return "RPath({!r}, {!r})".format(self.host, self.path)

    def __eq__(self, other):
        return isinstance(other, RPath) and other.host == self.host and other.path == self.path

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(("RPath", self.host, self.path))

    def __truediv__(self, other):
        return RPath(self.host, posixpath.join(self.path, str(other).replace("\\", "/")))

    def joinpath(self, *parts):
        p = self
        for part in parts:
            p = p / part
        return p

    @property
    def _pure(self):
        return PurePosixPath(self.path)

    @property
    def name(self):
        return self._pure.name

    @property
    def suffix(self):
        return self._pure.suffix

    @property
    def stem(self):
        return self._pure.stem

    @property
    def parts(self):
        return self._pure.parts

    @property
    def parent(self):
        return RPath(self.host, posixpath.dirname(self.path))

    @property
    def parents(self):
        out, p = [], self
        while p.path != "/":
            p = p.parent
            out.append(p)
        return tuple(out)

    def relative_to(self, other):
        base = other.path if isinstance(other, RPath) else str(other)
        return self._pure.relative_to(base)

    def as_posix(self):
        return self.path

    def is_absolute(self):
        return True

    def with_name(self, name):
        return self.parent / name

    # 서버에 묻는 일
    def _call(self, method, *args):
        return connection(self.host).call(method, [self.path] + list(args), {})

    def resolve(self, strict=False):
        return RPath(self.host, self._call("fs.realpath"))

    def stat(self):
        if self._st is not None:
            return self._st
        return self._call("fs.stat", True)

    def lstat(self):
        return self._call("fs.stat", False)

    def exists(self):
        return bool(self._call("fs.kind", True))

    def is_file(self):
        return self._call("fs.kind", True) == "file"

    def is_dir(self):
        return self._call("fs.kind", True) == "dir"

    def is_symlink(self):
        return self._call("fs.kind", False) == "link"

    def read_bytes(self):
        return self._call("fs.read")

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)

    def write_bytes(self, data):
        self._call("fs.write", bytes(data))
        return len(data)

    def write_text(self, text, encoding="utf-8", errors="strict"):
        return self.write_bytes(str(text).encode(encoding, errors))

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        self._call("fs.mkdir", bool(parents), bool(exist_ok))

    def unlink(self, missing_ok=False):
        self._call("fs.unlink", bool(missing_ok))

    def rmdir(self):
        self._call("fs.rmdir")

    def iterdir(self):
        return [self / name for name in self._call("fs.listdir")]

    def glob(self, pattern):
        return [RPath(self.host, p) for p in self._call("fs.glob", str(pattern))]


# ---- 주고받는 값(JSON) ----

def encode(value):
    """경로·바이트·stat·튜플을 JSON에 담을 꼴로. 원격 경로(RPath)와 서버의 Path는 {"__p": 경로}."""
    if isinstance(value, RPath):
        return {"__p": value.path}
    if isinstance(value, PurePath):
        return {"__p": value.as_posix()}
    if isinstance(value, (bytes, bytearray)):
        return {"__b": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (os.stat_result, StatResult)):
        return {"__st": StatResult.of(value).as_dict()}
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset, types.GeneratorType)):
        return [encode(v) for v in value]
    return value


def decode(value, host=None):
    """encode의 반대. host가 있으면(앱 쪽) 경로를 RPath로, 없으면(서버 쪽) pathlib.Path로."""
    if isinstance(value, dict):
        if len(value) == 1:
            if "__p" in value:
                if host is not None:
                    return RPath(host, value["__p"])
                from pathlib import Path
                return Path(value["__p"])
            if "__b" in value:
                return base64.b64decode(value["__b"])
            if "__st" in value:
                return StatResult(**value["__st"])
        return {k: decode(v, host) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v, host) for v in value]
    return value


def error_dict(e):
    """서버 쪽 예외 → 앱으로 보낼 정보."""
    d = {"cls": type(e).__name__, "mod": type(e).__module__, "msg": str(e), "args": [str(a) for a in e.args][:4]}
    if isinstance(e, OSError):
        d.update(errno=e.errno, strerror=e.strerror, filename=str(e.filename) if e.filename is not None else None)
    if hasattr(e, "current_hash"):
        d["hash"] = e.current_hash
    return d


def raise_error(err):
    """error_dict → 앱 쪽에서 같은 종류의 예외로."""
    cls, msg = err.get("cls") or "", err.get("msg") or ""
    if cls in ("WorkspaceError", "ConflictError"):
        import code_workspace as cw
        if cls == "ConflictError":
            raise cw.ConflictError(msg, err.get("hash"))
        raise cw.WorkspaceError(msg)
    if cls == "GitError":
        import code_git
        raise code_git.GitError(msg)
    if cls == "ProjectError":
        import code_project
        raise code_project.ProjectError(msg)
    if cls == "RemoteError":
        raise RemoteError(msg)
    import builtins
    kind = getattr(builtins, cls, None)
    if isinstance(kind, type) and issubclass(kind, OSError):
        if err.get("errno") is not None:
            raise kind(err["errno"], err.get("strerror") or msg, *([err["filename"]] if err.get("filename") else []))
        raise kind(msg)
    if cls in ("ValueError", "TypeError", "KeyError", "LookupError", "UnicodeError", "UnicodeDecodeError", "error"):
        raise ValueError(msg)   # error: 정규식(re.error)
    raise RemoteError("원격 컴퓨터에서 오류가 났습니다: {}: {}".format(cls, msg)[:1000])


# ---- 원격에서 실행하기 ----

def _host_of(value):
    if isinstance(value, RPath):
        return value.host
    if isinstance(value, str) and value.startswith(SCHEME):
        return split(value)[0]
    return None


def _to_remote_arg(value):
    if isinstance(value, str) and value.startswith(SCHEME):
        return split(value)[1]
    return value


def remote_ok(fn):
    """인자에 원격 경로(ssh://… 글 또는 RPath)가 있으면 같은 함수를 원격 도우미에서 실행한다."""
    name = fn.__module__ + "." + fn.__name__

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        host = None
        for v in args:
            host = _host_of(v)
            if host:
                break
        if host is None:
            for v in kwargs.values():
                host = _host_of(v)
                if host:
                    break
        if host is None:
            return fn(*args, **kwargs)
        return connection(host).call(name, [_to_remote_arg(v) for v in args],
                                     {k: _to_remote_arg(v) for k, v in kwargs.items()})
    wrapper.remote_name = name
    return wrapper


def call(value, method, *args, **kwargs):
    """원격 경로가 속한 연결에서 도우미 함수를 부른다(value는 경로가 아니라 연결을 고르는 데만 쓴다)."""
    host = _host_of(value)
    return connection(host).call(method, list(args), kwargs)

