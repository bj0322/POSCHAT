"""채팅창에 첨부한 파일(이미지·문서·텍스트).

화면은 고른 파일을 조각(base64)으로 나눠 upload_chunk로 보내고, 마지막 조각에서 파일 종류를 확인한다.
보낼 때 문서·텍스트는 글자로 바꿔 프롬프트에 넣고, 이미지는 Responses API 요청에 그림으로 붙인다.
뽑은 글자는 attachments/<id>/.text에 저장해 두고 다음 질문에서도 다시 쓴다.
"""
import base64
import re
import tempfile
from pathlib import Path

import documents
import storage

MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 10
MAX_TEXT_CHARS = 20000       # 파일 하나에서 프롬프트에 넣는 글자 수
MAX_TOTAL_CHARS = 40000      # 한 번의 요청에 넣는 첨부 글자 수 합계
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
TEXT_CACHE = ".text"


class AttachmentError(Exception):
    pass


def _safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", Path(str(name or "")).name).strip(" .")
    return name[:120] or "file"


def kind_of(path):
    """"image" | "document" | "text". 다룰 수 없는 파일이면 AttachmentError."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES:
        return "image"
    if suffix in documents.LEGACY_EXTS:
        raise AttachmentError(f"예전 형식({suffix})은 읽을 수 없습니다. {documents.LEGACY_EXTS[suffix]}로 저장한 뒤 첨부하세요.")
    if documents.is_document(path):
        return "document"
    with open(path, "rb") as f:
        head = f.read(8192)
    if b"\x00" in head:
        raise AttachmentError(f"'{path.name}'은(는) 첨부할 수 없는 형식입니다. 이미지, 문서(PDF·Office·한글), 텍스트 파일을 첨부하세요.")
    return "text"


def upload_chunk(attach_id, name, offset, data_b64, last):
    """조각 하나를 저장한다. 마지막 조각이면 확인을 마치고 첨부 정보를 돌려준다."""
    d = storage.attachment_dir(attach_id)
    name = _safe_name(name)
    if offset == 0:
        if d.exists():
            raise AttachmentError("이미 올린 첨부 파일입니다.")
        d.mkdir(parents=True)
        (d / storage.STAGED_MARK).touch()
    path = d / name
    if not (d / storage.STAGED_MARK).exists():
        raise AttachmentError("첨부 파일을 찾을 수 없습니다. 다시 첨부하세요.")
    size = path.stat().st_size if path.exists() else 0
    if size != offset:
        storage.delete_attachment(attach_id)
        raise AttachmentError("파일을 받는 중 순서가 어긋났습니다. 다시 첨부하세요.")
    chunk = base64.b64decode(data_b64 or "")
    if size + len(chunk) > MAX_BYTES:
        storage.delete_attachment(attach_id)
        raise AttachmentError(f"'{name}'이(가) 너무 큽니다({MAX_BYTES // 1024 // 1024}MB 초과).")
    with open(path, "ab") as f:
        f.write(chunk)
    if not last:
        return None
    try:
        kind = kind_of(path)
    except (AttachmentError, OSError):
        storage.delete_attachment(attach_id)
        raise
    return {"id": attach_id, "name": name, "kind": kind, "size": path.stat().st_size}


def info(attach_id):
    path = storage.attachment_file(attach_id)
    if path is None:
        return None
    try:
        kind = kind_of(path)
    except (AttachmentError, OSError):
        return None
    return {"id": attach_id, "name": path.name, "kind": kind, "size": path.stat().st_size}


def commit(ids):
    """보낼 메시지에 붙일 첨부 정보 목록. 보내기 전 표시(.staged)를 지운다."""
    if len(ids) > MAX_FILES:
        raise AttachmentError(f"파일은 한 번에 {MAX_FILES}개까지 첨부할 수 있습니다.")
    out = []
    for attach_id in ids:
        item = info(attach_id)
        if item is None:
            raise AttachmentError("첨부 파일을 찾을 수 없습니다. 다시 첨부하세요.")
        (storage.attachment_dir(attach_id) / storage.STAGED_MARK).unlink(missing_ok=True)
        out.append(item)
    return out


def text_of(item):
    """문서·텍스트 첨부의 글자. 처음 한 번 뽑아서 저장해 둔다. 읽지 못하면 이유를 담은 문장."""
    path = storage.attachment_file(item["id"])
    if path is None:
        return "(파일이 지워져 내용을 볼 수 없습니다)"
    cache = path.parent / TEXT_CACHE
    try:
        return cache.read_text(encoding="utf-8")
    except OSError:
        pass
    if item["kind"] == "document":
        try:
            text = documents.extract_text(path)
        except documents.DocumentError as e:
            return f"(읽지 못했습니다: {e})"
    else:
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
    try:
        cache.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text


def image_data(item):
    """(MIME 형식, base64) — Responses API의 input_image로 보낸다."""
    path = storage.attachment_file(item["id"])
    if path is None:
        return None
    return IMAGE_TYPES[path.suffix.lower()], base64.b64encode(path.read_bytes()).decode("ascii")


def preview(attach_id, max_bytes=8 * 1024 * 1024):
    """화면의 미리보기용 data: URL(이미지만)."""
    item = info(attach_id)
    if not item or item["kind"] != "image" or item["size"] > max_bytes:
        return None
    mime, data = image_data(item)
    return f"data:{mime};base64,{data}"


# 1x1 PNG
_CHECK_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def selfcheck():
    """설치 진단(--selftest, 안드로이드 계측 테스트)용: 임시 폴더에서 텍스트·이미지 첨부를 올리고 읽어 본다."""
    saved = storage.ATTACH_DIR
    with tempfile.TemporaryDirectory() as tmp:
        storage.ATTACH_DIR = Path(tmp)
        try:
            text = upload_chunk("0" * 31 + "1", "확인.txt", 0, base64.b64encode("첨부 확인".encode("cp949")).decode(), True)
            image = upload_chunk("0" * 31 + "2", "확인.png", 0, _CHECK_PNG, True)
            if text["kind"] != "text" or "첨부 확인" not in text_of(text):
                return f"FAIL text {text}"
            if image["kind"] != "image" or not preview(image["id"]).startswith("data:image/png;base64,"):
                return f"FAIL image {image}"
            return "OK"
        except Exception as e:
            return f"FAIL {type(e).__name__}: {e}"
        finally:
            storage.ATTACH_DIR = saved


def prompt_block(title, items, budget):
    """첨부 파일 내용을 프롬프트 블록으로. (블록 또는 None, 남은 글자 수)"""
    parts = []
    for item in items:
        if item["kind"] == "image":
            continue
        if budget <= 0:
            parts.append(f"=== {item['name']} ===\n(글자 수 한도로 내용을 넣지 못했습니다)")
            continue
        text = text_of(item)
        limit = min(MAX_TEXT_CHARS, budget)
        if len(text) > limit:
            text = text[:limit] + f"\n... (생략됨, 전체 {len(text):,}자)"
        budget -= len(text)
        parts.append(f"=== {item['name']} ===\n{text}")
    if not parts:
        return None, budget
    return f"[{title}]\n" + "\n\n".join(parts), budget
