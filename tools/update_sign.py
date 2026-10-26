# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""업데이트 서명 도구(Ed25519). 서명 방식은 updates.py의 signed_message를 따른다.

    python tools/update_sign.py keygen | gh secret set UPDATE_SIGNING_KEY
        새 키 쌍을 만든다. 개인키는 표준 출력으로만 나오고(파일에 저장하지 않는다) 공개키는 표준 오류로 나온다.
        공개키를 updates.UPDATE_PUBLIC_KEYS에 넣는다.
    UPDATE_SIGNING_KEY=<개인키> python tools/update_sign.py sign --tag v1.2.3 파일...
        파일마다 <파일>.sig를 만든다. 앱에 들어 있는 공개키로 다시 확인해, 키가 다르면 실패한다.
"""
import argparse
import base64
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import updates  # noqa: E402


def _crypto():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return serialization, Ed25519PrivateKey


def keygen():
    serialization, Ed25519PrivateKey = _crypto()
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    sys.stdout.write(base64.b64encode(private).decode())
    sys.stdout.flush()
    print("공개키(updates.UPDATE_PUBLIC_KEYS):", base64.b64encode(public).decode(), file=sys.stderr)
    return 0


def sign(tag, files):
    _, Ed25519PrivateKey = _crypto()
    secret = os.environ.get("UPDATE_SIGNING_KEY", "").strip()
    if not secret:
        print("UPDATE_SIGNING_KEY 환경 변수가 없습니다.", file=sys.stderr)
        return 1
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret, validate=True))
    for name in files:
        path = Path(name)
        sha, size = hashlib.sha256(), 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(chunk)
                size += len(chunk)
        message = updates.signed_message(tag, path.name, size, sha.hexdigest())
        signature = base64.b64encode(key.sign(message)).decode()
        try:
            updates.verify_signature(message, signature)
        except updates.UpdateError as e:
            print(f"{path.name}: 앱에 들어 있는 공개키와 맞지 않습니다. {e}", file=sys.stderr)
            return 1
        Path(str(path) + ".sig").write_text(signature + "\n", encoding="ascii")
        print(f"signed {path.name} ({size} bytes)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("keygen")
    sign_parser = commands.add_parser("sign")
    sign_parser.add_argument("--tag", required=True, help="릴리스 태그(예: v1.2.3)")
    sign_parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    return keygen() if args.command == "keygen" else sign(args.tag, args.files)


if __name__ == "__main__":
    sys.exit(main())
