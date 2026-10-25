# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""SSH 연결(1.18): paramiko로 서버에 붙어 원격 도우미(remote_helper)와 터미널 채널을 연다. 데스크톱 전용(안드로이드에는 paramiko가 없다).

- 대상: ~/.ssh/config의 Host 이름, 또는 user@host[:port]. config의 HostName·User·Port·IdentityFile·IdentitiesOnly·ProxyJump·
  ProxyCommand를 따른다(Include는 읽지 않는다).
- 호스트 키: ~/.ssh/known_hosts와 앱의 known_hosts(데이터 폴더/ssh/known_hosts)로 확인한다. 처음 보는 서버는 지문을 보이고 사용자가
  받아들일 때만 앱의 파일에 남긴다(사용자의 known_hosts는 고치지 않는다). 키가 바뀐 서버에는 연결하지 않는다.
- 인증 순서: SSH 에이전트의 키 → IdentityFile(없으면 id_ed25519·id_ecdsa·id_rsa, 암호문은 물어본다) → keyboard-interactive
  (OTP·암호 질문을 그대로 보인다) → 암호. 2단계 인증(키 + OTP)도 된다. 암호·OTP는 저장하지 않는다(키 암호문은 앱을 끌 때까지 기억).
- 서버에는 아무것도 설치하지 않는다. 연결이 끊기면 서버의 도우미와 명령이 함께 끝난다.
"""
import base64
import codecs
import hashlib
import os
import re
import shlex
import socket
import threading

import paramiko

import remote_client
import storage
from remote_fs import RemoteError

CONNECT_TIMEOUT = 15
KEEPALIVE_SECONDS = 30
DEFAULT_KEYS = ("id_ed25519", "id_ecdsa", "id_rsa")
NAME_RE = re.compile(r"^[\w.@:%\[\]-]{1,200}$")
_key_cache = {}   # 키 파일 경로 → 불러온 키(암호문을 다시 묻지 않게, 앱을 끌 때까지)
_key_lock = threading.Lock()


class SshError(RemoteError):
    pass


class Cancelled(SshError):
    def __init__(self):
        super().__init__("연결을 취소했습니다.")


def ssh_dir():
    return os.path.join(os.path.expanduser("~"), ".ssh")


def app_known_hosts():
    return str(storage.APP_DIR / "ssh" / "known_hosts")


def load_config():
    path = os.path.join(ssh_dir(), "config")
    if os.path.isfile(path):
        try:
            return paramiko.SSHConfig.from_path(path)
        except Exception:
            pass
    return paramiko.SSHConfig()


def config_hosts():
    """~/.ssh/config의 Host 이름들(와일드카드 제외) [{name, hostname, user, port}]."""
    cfg = load_config()
    out = []
    try:
        names = sorted(cfg.get_hostnames())
    except Exception:
        names = []
    for name in names:
        if not name or any(c in name for c in "*?!") or not NAME_RE.match(name):
            continue
        h = cfg.lookup(name)
        out.append({"name": name, "hostname": h.get("hostname", name), "user": h.get("user", ""),
                    "port": int(h.get("port") or 22)})
    return out[:200]


def parse_target(text):
    """'user@host:port' · 'host' · 'ssh -p 2222 user@host' → (연결 이름, user, host, port 또는 None)."""
    s = " ".join(str(text or "").split())
    port = None
    if s.startswith("ssh "):
        words = s.split()[1:]
        rest = []
        i = 0
        while i < len(words):
            if words[i] == "-p" and i + 1 < len(words):
                port = words[i + 1]
                i += 2
                continue
            if words[i].startswith("-"):
                raise SshError("ssh 명령의 옵션은 -p만 알아듣습니다. 나머지는 ~/.ssh/config에 적으세요.")
            rest.append(words[i])
            i += 1
        if len(rest) != 1:
            raise SshError("연결할 서버를 하나만 쓰세요. 예: user@server.postech.ac.kr")
        s = rest[0]
    if not s:
        raise SshError("연결할 서버를 쓰세요. 예: user@server.postech.ac.kr 또는 ~/.ssh/config의 Host 이름")
    user, _, host = s.rpartition("@")
    m = re.match(r"^\[(.+)\](?::(\d+))?$", host) or re.match(r"^([^:]+)(?::(\d+))?$", host)
    if not m:
        raise SshError("서버 주소가 올바르지 않습니다: " + s)
    host, p = m.group(1), m.group(2)
    port = p or port
    if port is not None:
        try:
            port = int(port)
        except ValueError:
            raise SshError("포트가 숫자가 아닙니다.")
        if not 0 < port < 65536:
            raise SshError("포트가 올바르지 않습니다.")
    name = (user + "@" if user else "") + host + (":" + str(port) if port and port != 22 else "")
    if not NAME_RE.match(name) or "/" in name:
        raise SshError("서버 이름에 쓸 수 없는 글자가 있습니다: " + s)
    return name, user, host, port


class Hop:
    """접속 한 단계(점프 호스트 또는 목적지)."""

    def __init__(self, alias, user, port, cfg):
        h = cfg.lookup(alias)
        self.alias = alias
        self.hostname = h.get("hostname", alias)
        self.user = user or h.get("user") or _local_user()
        self.port = int(port or h.get("port") or 22)
        self.identity_files = [os.path.expanduser(p) for p in (h.get("identityfile") or [])]
        self.identities_only = str(h.get("identitiesonly", "no")).lower() == "yes"
        self.proxyjump = h.get("proxyjump", "")
        self.proxycommand = h.get("proxycommand", "")
        self.label = "{}@{}".format(self.user, self.hostname) + (":{}".format(self.port) if self.port != 22 else "")


def _local_user():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return ""


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")


class SshConnection:
    """서버 하나와의 연결. remote_fs.register(name, 이것)으로 등록해 두면 ssh://name/… 경로가 이 연결을 쓴다."""

    def __init__(self, target, prompt, on_closed=None, on_status=None, python=""):
        self.name, self.user, self.host, self.port = parse_target(target)
        self.prompt = prompt              # (kind, data) -> dict 또는 None(취소). 앱 화면에 묻는다
        self.on_closed = on_closed
        self.on_status = on_status or (lambda text: None)
        self.python = python
        self.transports = []
        self.client = None
        self.info = {}
        self._stderr = []
        self._closed = False

    @property
    def alive(self):
        return bool(self.client is not None and self.client.alive and self.transports and self.transports[-1].is_active())

    # ---- 연결 ----

    def connect(self):
        cfg = load_config()
        final = Hop(self.host, self.user, self.port, cfg)
        hops = []
        if final.proxyjump and final.proxyjump.lower() != "none":
            for j in final.proxyjump.split(","):
                _, ju, jh, jp = parse_target(j.strip())
                hops.append(Hop(jh, ju, jp, cfg))
        hops.append(final)
        try:
            sock = None
            for i, hop in enumerate(hops):
                self.on_status("{} 연결 중…".format(hop.label))
                if sock is None:
                    if hop.proxycommand and i == 0:
                        sock = paramiko.ProxyCommand(hop.proxycommand)
                    else:
                        sock = socket.create_connection((hop.hostname, hop.port), CONNECT_TIMEOUT)
                t = paramiko.Transport(sock)
                t.banner_timeout = 30
                t.auth_timeout = 60
                self.transports.append(t)
                try:
                    t.start_client(timeout=CONNECT_TIMEOUT)
                except paramiko.SSHException as e:
                    raise SshError("SSH 서버와 연결을 맺지 못했습니다({}): {}".format(hop.label, e))
                self._check_host_key(t, hop)
                self._auth(t, hop)
                t.set_keepalive(KEEPALIVE_SECONDS)
                if i + 1 < len(hops):
                    nxt = hops[i + 1]
                    try:
                        sock = t.open_channel("direct-tcpip", (nxt.hostname, nxt.port), ("127.0.0.1", 0),
                                              timeout=CONNECT_TIMEOUT)
                    except paramiko.SSHException as e:
                        raise SshError("점프 호스트 {}에서 {}로 가지 못했습니다: {}".format(hop.label, nxt.label, e))
            self.on_status("원격 도우미 시작 중…")
            self._start_helper()
        except Cancelled:
            self.close()
            raise
        except (OSError, paramiko.SSHException, EOFError) as e:
            self.close()
            if isinstance(e, SshError):
                raise
            if isinstance(e, socket.timeout):
                raise SshError("서버가 {}초 안에 답하지 않았습니다. 주소·포트·VPN을 확인하세요.".format(CONNECT_TIMEOUT))
            if isinstance(e, socket.gaierror):
                raise SshError("서버 이름을 찾지 못했습니다: {}".format(hops[0].hostname))
            raise SshError("연결하지 못했습니다: {}".format(getattr(e, "strerror", None) or e))
        return self.info

    def _start_helper(self):
        t = self.transports[-1]
        chan = t.open_session(timeout=CONNECT_TIMEOUT)
        chan.exec_command(remote_client.remote_command(self.python))
        rfile = chan.makefile("rb")
        errfile = chan.makefile_stderr("rb")

        def drain():
            try:
                for line in iter(errfile.readline, b""):
                    self._stderr = (self._stderr + [line.decode("utf-8", errors="replace").rstrip()])[-20:]
            except Exception:
                pass
        threading.Thread(target=drain, daemon=True).start()
        self.client = remote_client.HelperClient(self.name, chan.sendall, rfile.readline, close=chan.close,
                                                 on_closed=lambda c: self._lost())
        try:
            self.info = self.client.start()
        except RemoteError as e:
            tail = " / ".join(x for x in self._stderr[-3:] if x)
            raise SshError(str(e) + (" (서버: {})".format(tail[:300]) if tail else ""))

    def _lost(self):
        if not self._closed and self.on_closed:
            try:
                self.on_closed(self)
            except Exception:
                pass

    def close(self):
        self._closed = True
        if self.client is not None:
            self.client.close()
        for t in reversed(self.transports):
            try:
                t.close()
            except Exception:
                pass

    # ---- 호스트 키 ----

    def _check_host_key(self, t, hop):
        key = t.get_remote_server_key()
        name = hop.hostname if hop.port == 22 else "[{}]:{}".format(hop.hostname, hop.port)
        known = paramiko.HostKeys()
        for path in (os.path.join(ssh_dir(), "known_hosts"), app_known_hosts()):
            if os.path.isfile(path):
                try:
                    known.load(path)
                except Exception:
                    continue
        entry = known.lookup(name)
        if entry:
            have = entry.get(key.get_name())
            if have is not None and have.asbytes() == key.asbytes():
                return
            raise SshError(
                "{}의 호스트 키가 알고 있던 것과 다릅니다. 누군가 연결을 가로채고 있을 수 있어 연결하지 않았습니다. 서버 키가 정말 바뀐 것이라면 "
                "관리자에게 확인한 뒤 ~/.ssh/known_hosts(또는 POSCHAT 데이터 폴더의 ssh/known_hosts)에서 이 서버 줄을 지우세요. "
                "받은 키: {} {}".format(hop.label, key.get_name(), fingerprint(key)))
        answer = self.prompt("hostkey", {"host": hop.label, "keytype": key.get_name(), "fingerprint": fingerprint(key)})
        if not answer or not answer.get("accept"):
            raise Cancelled()
        path = app_known_hosts()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mine = paramiko.HostKeys()
        if os.path.isfile(path):
            try:
                mine.load(path)
            except Exception:
                pass
        mine.add(name, key.get_name(), key)
        mine.save(path)

    # ---- 인증 ----

    def _auth(self, t, hop):
        try:
            t.auth_none(hop.user)
            if t.is_authenticated():
                return
            allowed = ["publickey", "keyboard-interactive", "password"]
        except paramiko.BadAuthenticationType as e:
            allowed = list(e.allowed_types or [])
        except paramiko.AuthenticationException:
            allowed = ["publickey", "keyboard-interactive", "password"]
        tried_keys = False
        for _ in range(4):   # 부분 성공(키 다음 OTP 같은 2단계)을 따라간다
            if t.is_authenticated():
                return
            if "publickey" in allowed and not tried_keys:
                tried_keys = True
                rest = self._auth_keys(t, hop)
                if rest is not None:
                    allowed = rest
                    continue
            if "keyboard-interactive" in allowed:
                rest = self._auth_interactive(t, hop)
                if rest is not None:
                    allowed = rest
                    continue
            if "password" in allowed:
                rest = self._auth_password(t, hop)
                if rest is not None:
                    allowed = rest
                    continue
            break
        if not t.is_authenticated():
            raise SshError("{}에 로그인하지 못했습니다(인증 실패). 사용자 이름·키·암호를 확인하세요. 서버가 허용하는 방식: {}".format(
                hop.label, ", ".join(allowed) or "알 수 없음"))

    def _keys(self, hop):
        keys = []
        if not hop.identities_only:
            try:
                keys += [("SSH 에이전트", k) for k in paramiko.Agent().get_keys()]
            except Exception:
                pass
        files = hop.identity_files or [os.path.join(ssh_dir(), n) for n in DEFAULT_KEYS]
        for path in files:
            if os.path.isfile(path):
                keys.append((path, None))
        return keys

    def _load_key(self, path, hop):
        with _key_lock:
            if path in _key_cache:
                return _key_cache[path]
        passphrase = None
        for attempt in range(3):
            try:
                key = paramiko.PKey.from_path(path, passphrase.encode("utf-8") if passphrase is not None else None)
                # 위치 인자로: 이름이 3.x는 passphrase, 4.x부터 password. 바이트는 둘 다 받는다
                with _key_lock:
                    _key_cache[path] = key
                return key
            except paramiko.PasswordRequiredException:
                pass   # 암호문이 걸린 키
            except TypeError:
                if passphrase is not None:
                    return None
                # paramiko 4 이상은 암호문 없는 시도를 TypeError로 알린다
            except (paramiko.SSHException, ValueError) as e:
                if passphrase is None and not re.search(r"password|passphrase|encrypt", str(e), re.I):
                    return None   # 읽을 수 없는 형식(지원하지 않는 키 등)
                # 암호문이 틀렸다: 다시 묻는다
            except OSError:
                return None
            answer = self.prompt("secret", {"host": hop.label, "title": "키 암호문",
                                            "message": "{} 키의 암호문을 입력하세요{}".format(
                                                os.path.basename(path), " (다시)" if attempt else ""),
                                            "fields": [{"label": "암호문", "secret": True}]})
            if answer is None:
                raise Cancelled()
            passphrase = (answer.get("values") or [""])[0]
        return None

    def _auth_keys(self, t, hop):
        for source, key in self._keys(hop):
            if key is None:
                key = self._load_key(source, hop)
                if key is None:
                    continue
            try:
                rest = t.auth_publickey(hop.user, key)
            except paramiko.AuthenticationException:
                continue
            except paramiko.SSHException:
                continue
            return list(rest or [])
        return None

    def _auth_interactive(self, t, hop):
        cancelled = []

        def handler(title, instructions, prompts):
            # paramiko의 통신 스레드에서 불린다: 예외를 던지면 연결이 깨지므로 취소는 표시만 하고 빈 답을 보낸다
            if not prompts or cancelled:
                return [""] * len(prompts)
            answer = self.prompt("secret", {
                "host": hop.label, "title": title or "로그인", "message": instructions or "서버가 묻는 것에 답하세요.",
                "fields": [{"label": str(p).strip() or "입력", "secret": not echo} for p, echo in prompts]})
            if answer is None:
                cancelled.append(True)
                return [""] * len(prompts)
            values = list(answer.get("values") or [])
            return (values + [""] * len(prompts))[:len(prompts)]
        for _ in range(3):
            try:
                rest = list(t.auth_interactive(hop.user, handler) or [])
                if cancelled:
                    raise Cancelled()
                return rest
            except paramiko.BadAuthenticationType:
                return None
            except (paramiko.AuthenticationException, paramiko.SSHException):
                if cancelled:
                    raise Cancelled()
                if not t.is_active():
                    raise SshError("서버가 연결을 끊었습니다(로그인 실패가 많음).")
                continue
        return None

    def _auth_password(self, t, hop):
        for attempt in range(3):
            answer = self.prompt("secret", {"host": hop.label, "title": "암호",
                                            "message": "{}의 암호{}".format(hop.label, "가 틀렸습니다. 다시 입력하세요" if attempt else "를 입력하세요"),
                                            "fields": [{"label": "암호", "secret": True}]})
            if answer is None:
                raise Cancelled()
            try:
                return list(t.auth_password(hop.user, (answer.get("values") or [""])[0]) or [])
            except paramiko.BadAuthenticationType:
                return None
            except paramiko.AuthenticationException:
                if not t.is_active():
                    raise SshError("서버가 연결을 끊었습니다(로그인 실패가 많음).")
                continue
        return None

    # ---- 도우미·터미널 ----

    def call(self, method, args=(), kwargs=None, timeout=remote_client.CALL_TIMEOUT):
        if self.client is None:
            raise RemoteError("SSH 연결이 없습니다.")
        return self.client.call(method, args, kwargs, timeout)

    def popen(self, cwd, command, extra_env=None, secret_pattern=""):
        return self.client.popen(cwd, command, extra_env, secret_pattern)

    def shell(self, cwd, cols, rows):
        if not self.alive:
            raise RemoteError("SSH 연결이 끊겼습니다.")
        return SshShell(self.transports[-1], cwd, cols, rows)


class SshShell:
    """터미널(terminal.TerminalManager) 한 개: 서버의 pty 채널에서 로그인 셸을 작업 폴더에서 연다."""

    def __init__(self, transport, cwd, cols, rows):
        import terminal

        self.chan = transport.open_session(timeout=CONNECT_TIMEOUT)
        self.chan.get_pty(term="xterm-256color", width=cols, height=rows)
        for k, v in (("COLORTERM", "truecolor"), ("TERM_PROGRAM", "POSCHAT")):
            try:
                self.chan.set_environment_variable(k, v)   # 서버가 받지 않으면(AcceptEnv) 조용히 버린다
            except Exception:
                pass
        script = 'cd "$1" 2>/dev/null || echo "작업 폴더로 가지 못했습니다: $1"; exec "${SHELL:-/bin/sh}" -l'
        self.chan.exec_command("exec /bin/sh -c " + shlex.quote(script) + " poschat " + shlex.quote(cwd))
        self.chan.settimeout(terminal.FLUSH_SECONDS)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pid = None

    def read(self):
        try:
            data = self.chan.recv(65536)
        except socket.timeout:
            return ""
        except Exception:
            return None
        if not data:
            return None
        return self._decoder.decode(data)

    def write(self, text):
        self.chan.sendall(text.encode("utf-8"))

    def resize(self, cols, rows):
        self.chan.resize_pty(width=cols, height=rows)

    def exit_code(self):
        return self.chan.recv_exit_status() if self.chan.exit_status_ready() else None

    def close(self):
        try:
            self.chan.close()
        except Exception:
            pass


def selfcheck():
    """설치본 진단: paramiko와 그 암호 라이브러리(cryptography·bcrypt·pynacl)가 묶였는지 키를 만들고 서명해 본다."""
    try:
        key = paramiko.Ed25519Key.from_private_key(_ed25519_sample())
        sig = key.sign_ssh_data(b"poschat")
        sig.rewind()
        public = paramiko.Ed25519Key(data=key.asbytes())
        if not public.verify_ssh_sig(b"poschat", sig):
            return "FAIL 서명 확인"
        paramiko.RSAKey.generate(1024)
        return "OK"
    except Exception as e:
        return "FAIL {}: {}".format(type(e).__name__, e)


def _ed25519_sample():
    """암호문 없는 시험용 OpenSSH Ed25519 키(selfcheck 전용, 아무 데도 쓰지 않는다)를 그때그때 만든다."""
    import io

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
    return io.StringIO(pem.decode("ascii"))
