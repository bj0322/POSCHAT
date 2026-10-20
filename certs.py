"""서버가 중간 인증서를 보내지 않을 때 인증서의 AIA(CA Issuers) 주소에서 받아 와 검증에 쓴다.

genai.postech.ac.kr은 중간 인증서를 보내지 않는다. Windows는 운영체제가 중간 인증서를 받아 오므로
truststore로 해결되지만, 안드로이드의 Python처럼 certifi만 쓰는 환경에서는 검증에 실패한다.
이때 서버 인증서에 적힌 발급자 인증서 주소에서 중간 인증서를 한 단계만 받아 certifi 묶음에 더한다.

받은 인증서는 서버 인증서의 발급자와 이름이 같아야 하고 자체 서명(루트)이면 안 된다. 그래서 검증은 여전히
certifi에 원래 있던 루트까지 서명으로 이어져야 통과하며, 공격자가 자기 루트를 신뢰 목록에 넣을 수 없다.
"""
import re
import socket
import ssl
from pathlib import Path
from urllib.parse import urlparse

# OID 1.3.6.1.5.5.7.48.2(id-ad-caIssuers) 다음의 [6] uniformResourceIdentifier
CA_ISSUERS_RE = re.compile(rb"\x06\x08\x2b\x06\x01\x05\x05\x07\x30\x02\x86(.)", re.DOTALL)


class CertError(Exception):
    pass


def _peer_cert(host, port, timeout=15):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # 발급자 주소를 읽기 위해서만 받는다. 이 연결로는 아무것도 보내지 않는다.
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True)


def _tlv(data, i):
    """DER 항목 하나: (태그, 값 시작, 값 끝)."""
    tag, length = data[i], data[i + 1]
    i += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[i:i + n], "big")
        i += n
    return tag, i, i + length


def issuer_and_subject(der):
    """X.509 인증서(DER)의 발급자·주체 이름(DER 그대로)."""
    _, start, _ = _tlv(der, 0)          # Certificate
    _, i, _ = _tlv(der, start)          # TBSCertificate
    tag, _, end = _tlv(der, i)
    if tag == 0xA0:                     # [0] version
        i = end
        tag, _, end = _tlv(der, i)
    i = end                             # serialNumber 다음
    _, _, i = _tlv(der, i)              # signature 알고리즘
    _, _, end = _tlv(der, i)
    issuer, i = der[i:end], end
    _, _, i = _tlv(der, i)              # validity
    _, _, end = _tlv(der, i)
    return issuer, der[i:end]


def issuer_url(der):
    m = CA_ISSUERS_RE.search(der)
    if not m:
        return None
    url = der[m.end():m.end() + m.group(1)[0]].decode("ascii", errors="replace")
    return url if url.startswith(("http://", "https://")) else None


def build_bundle(url, base_bundle, out_path, get):
    """url의 서버에 맞춰 base_bundle에 중간 인증서 하나를 더한 CA 묶음 파일을 만들고 경로를 돌려준다.

    get(url) -> bytes: 중간 인증서를 받는 함수. 중간 인증서는 보통 http:// 주소에 DER로 있다.
    """
    parsed = urlparse(url)
    leaf = _peer_cert(parsed.hostname, parsed.port or 443)
    issuer = issuer_url(leaf)
    if not issuer:
        raise CertError("서버 인증서에 발급자 인증서 주소(AIA)가 없습니다.")
    data = get(issuer)
    if b"-----BEGIN CERTIFICATE-----" in data:
        data = ssl.PEM_cert_to_DER_cert(data.decode("ascii", errors="replace"))
    try:
        inter_issuer, inter_subject = issuer_and_subject(data)
        leaf_issuer, _ = issuer_and_subject(leaf)
    except (IndexError, ValueError) as e:
        raise CertError(f"받은 인증서를 해석하지 못했습니다: {e}")
    if inter_subject != leaf_issuer:
        raise CertError("받은 인증서가 서버 인증서의 발급자가 아닙니다.")
    if inter_issuer == inter_subject:
        raise CertError("받은 인증서가 루트(자체 서명) 인증서라서 쓰지 않습니다.")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(Path(base_bundle).read_text(encoding="utf-8") + "\n" + ssl.DER_cert_to_PEM_cert(data),
                        encoding="utf-8")
    return str(out_path)
