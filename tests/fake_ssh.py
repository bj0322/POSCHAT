# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""시험용 SSH 서버(paramiko 서버 모드). 이 컴퓨터를 '원격 서버'로 흉내 낸다: exec(파이프 또는 pty)를 로컬 /bin/sh로 실행하고,
암호·키·keyboard-interactive(OTP 2단계 포함) 인증과 direct-tcpip(점프 호스트)를 지원한다."""
import os
import select
import socket
import subprocess
import threading

import paramiko


class _Server(paramiko.ServerInterface):
    def __init__(self, fake):
        self.fake = fake
        self.pty = None
        self.exec_event = threading.Event()
        self.command = None
        self.partial = set()

    # 인증
    def get_allowed_auths(self, username):
        return ",".join(self.fake.allowed)

    def _ok(self, method):
        self.partial.add(method)
        need = self.fake.require_all
        if need and not set(need) <= self.partial:
            return paramiko.AUTH_PARTIALLY_SUCCESSFUL
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_password(self, username, password):
        self.fake.log.append(("password", username))
        if username == self.fake.user and password == self.fake.password:
            return self._ok("password")
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        self.fake.log.append(("publickey", username))
        if username == self.fake.user and self.fake.key is not None and key.asbytes() == self.fake.key.asbytes():
            return self._ok("publickey")
        return paramiko.AUTH_FAILED

    def check_auth_interactive(self, username, submethods):
        self.fake.log.append(("interactive", username))
        if username != self.fake.user:
            return paramiko.AUTH_FAILED
        return paramiko.InteractiveQuery("POSTECH 로그인", "OTP 앱의 숫자를 넣으세요", ("Password: ", False), ("OTP: ", True))

    def check_auth_interactive_response(self, responses):
        if list(responses) == [self.fake.password, self.fake.otp]:
            return self._ok("keyboard-interactive")
        return paramiko.AUTH_FAILED

    # 채널
    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        self.fake.direct[chanid] = destination
        self.fake.forwards.append(destination)
        return paramiko.OPEN_SUCCEEDED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        self.pty = (term, width, height)
        return True

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        resize = getattr(channel, "_fake_resize", None)
        if resize:
            resize(width, height)
        return True

    def check_channel_env_request(self, channel, name, value):
        return False

    def check_channel_exec_request(self, channel, command):
        self.fake.commands.append(command.decode("utf-8", errors="replace"))
        threading.Thread(target=_run, args=(self.fake, channel, command.decode("utf-8"), self.pty), daemon=True).start()
        return True

    def check_channel_shell_request(self, channel):
        threading.Thread(target=_run, args=(self.fake, channel, os.environ.get("SHELL", "/bin/sh") + " -l", self.pty),
                         daemon=True).start()
        return True


def _run(fake, chan, command, pty_info):
    env = dict(os.environ, **fake.env)
    if pty_info:
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()

        def resize(w, h):
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", h, w, 0, 0))
        resize(pty_info[1], pty_info[2])
        chan._fake_resize = resize
        env["TERM"] = pty_info[0]
        proc = subprocess.Popen(["/bin/sh", "-c", command], stdin=slave, stdout=slave, stderr=slave, env=env,
                                start_new_session=True, close_fds=True)
        os.close(slave)
        fake.procs.append(proc)
        try:
            while True:
                r, _, _ = select.select([master, chan], [], [], 0.05)
                if master in r:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    chan.sendall(data)
                if chan in r:
                    data = chan.recv(65536)
                    if not data:
                        break
                    os.write(master, data)
                if proc.poll() is not None and not select.select([master], [], [], 0)[0]:
                    break
        finally:
            if chan.closed:
                try:
                    os.killpg(proc.pid, 1)
                except OSError:
                    pass
            code = proc.wait()
            os.close(master)
            _finish(chan, code)
        return
    proc = subprocess.Popen(["/bin/sh", "-c", command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=fake.home, start_new_session=True)
    fake.procs.append(proc)

    def pump_in():
        try:
            while True:
                data = chan.recv(65536)
                if not data:
                    break
                proc.stdin.write(data)
                proc.stdin.flush()
        except (OSError, EOFError, socket.error):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    def pump_err():
        for data in iter(lambda: proc.stderr.read1(65536), b""):
            try:
                chan.sendall_stderr(data)
            except (OSError, EOFError):
                break
    threading.Thread(target=pump_in, daemon=True).start()
    threading.Thread(target=pump_err, daemon=True).start()
    try:
        for data in iter(lambda: proc.stdout.read1(65536), b""):
            chan.sendall(data)
    except (OSError, EOFError):
        pass
    _finish(chan, proc.wait())


def _finish(chan, code):
    try:
        chan.send_exit_status(code if code >= 0 else 255)
        chan.close()
    except (OSError, EOFError):
        pass


class FakeSSH:
    """with FakeSSH() as srv: srv.port … 인증 방식은 allowed(순서)와 require_all(2단계)로 정한다."""

    def __init__(self, user="student", password="pw-1234", otp="246810", key=None, allowed=("publickey", "password"),
                 require_all=(), home=None, host_key=None):
        self.user, self.password, self.otp, self.key = user, password, otp, key
        self.allowed = list(allowed)
        self.require_all = list(require_all)
        self.home = home or os.path.expanduser("~")
        self.host_key = host_key or paramiko.Ed25519Key.from_private_key(_new_key())
        self.env = {}
        self.log, self.commands, self.forwards, self.procs, self.transports = [], [], [], [], []
        self.direct = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(20)
        self.port = self.sock.getsockname()[1]
        self._stop = False

    def __enter__(self):
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass
        for t in self.transports:
            try:
                t.close()
            except Exception:
                pass
        for p in self.procs:
            try:
                os.killpg(p.pid, 9)
            except OSError:
                pass

    def _accept(self):
        while not self._stop:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, sock):
        t = paramiko.Transport(sock)
        t.add_server_key(self.host_key)
        server = _Server(self)
        self.transports.append(t)
        try:
            t.start_server(server=server)
        except (paramiko.SSHException, EOFError, OSError):
            return
        while t.is_active() and not self._stop:
            chan = t.accept(1)
            if chan is None:
                continue
            dest = self.direct.pop(chan.get_id(), None)
            if dest is not None:   # 점프 호스트: 받은 채널을 목적지로 잇는다
                threading.Thread(target=_forward, args=(chan, dest), daemon=True).start()


def _forward(chan, dest):
    try:
        out = socket.create_connection(dest, 10)
    except OSError:
        chan.close()
        return

    def pump(a_recv, b_send):
        try:
            while True:
                data = a_recv(65536)
                if not data:
                    break
                b_send(data)
        except (OSError, EOFError):
            pass
        finally:
            try:
                chan.close()
                out.close()
            except OSError:
                pass
    threading.Thread(target=pump, args=(chan.recv, out.sendall), daemon=True).start()
    pump(out.recv, chan.sendall)


def _new_key():
    import io

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
    return io.StringIO(pem.decode("ascii"))


def new_key():
    return paramiko.Ed25519Key.from_private_key(_new_key())
