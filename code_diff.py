# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Code(1.15): AI가 제안한 파일 변경(ChangeProposal)을 덩어리(hunk)로 나누고, 사용자가 고른 덩어리만 안전하게 적용한다.

원칙
- 제안(데이터)과 적용(파일 쓰기)을 나눈다. 사용자가 받아들이기 전에는 파일을 건드리지 않는다.
- 덩어리는 같은 기준 내용(original_content, base_hash)에서 계산하므로 서로 겹치지 않는다. 일부만 적용할 때는
  기준 줄 목록을 앞에서부터 다시 짠다(문자열 찾아 바꾸기를 쓰지 않는다).
- 적용 직전에 디스크 파일의 해시가 base_hash와 같은지 본다. 다르면(검토 중에 파일이 바뀜) 그대로 덮어쓰지 않고 충돌로 둔다.
  사용자가 '현재 파일에 맞춰 적용'을 고르면 덩어리마다 앞뒤 문맥 + 바뀌기 전 줄이 현재 파일에 정확히 한 번 나오는지 확인하고
  모두 맞을 때만 적용한다(하나라도 안 맞으면 아무것도 쓰지 않는다).
- 가까이 붙은 변경은 한 덩어리로 묶는다(문맥 3줄 안): 서로 기대는 변경을 반만 적용하는 일을 줄인다. Python·JSON은
  적용 전 미리보기에서 문법 오류를 알려 준다.
- 상태가 pending일 때만 적용한다. 같은 파일·같은 기준·같은 내용의 제안이 대기 중이면 새로 만들지 않고 그것을 쓴다(중복 적용 방지).
- 줄 끝(\\r\\n)과 마지막 줄 바꿈은 원문 그대로 다룬다(splitlines(keepends=True)).
"""
import difflib
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field

import code_workspace as cw

CONTEXT = 3
MAX_PROPOSALS = 200


class ProposalError(Exception):
    pass


def split_lines(text):
    return str(text or "").splitlines(keepends=True)


def _visible(line):
    return line.rstrip("\r\n")


@dataclass
class Hunk:
    id: int
    old_start: int          # 기준 줄 목록에서 시작(0부터)
    old_end: int            # 끝(포함하지 않음)
    old_lines: list
    new_lines: list
    before: list            # 앞 문맥(기준 내용)
    after: list             # 뒤 문맥
    lines: list             # 화면용 [{"t": " "|"-"|"+", "text", "old", "new"}]
    new_start: int = 0

    @property
    def header(self):
        """unified diff 머리(문맥 포함 범위)."""
        olds = [x["old"] for x in self.lines if x["old"] is not None]
        news = [x["new"] for x in self.lines if x["new"] is not None]
        o = min(olds) if olds else self.old_start
        n = min(news) if news else self.new_start
        return f"@@ -{o},{len(olds)} +{n},{len(news)} @@"

    def to_dict(self):
        added = sum(1 for x in self.lines if x["t"] == "+")
        removed = sum(1 for x in self.lines if x["t"] == "-")
        return {"id": self.id, "header": self.header, "lines": self.lines, "added": added, "removed": removed,
                "old_start": self.old_start + 1, "old_end": self.old_end, "new_start": self.new_start + 1}


def make_hunks(old_text, new_text, context=CONTEXT):
    a, b = split_lines(old_text), split_lines(new_text)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    hunks = []
    for group in matcher.get_grouped_opcodes(context):
        changes = [op for op in group if op[0] != "equal"]
        if not changes:
            continue
        i1, j1 = changes[0][1], changes[0][3]
        i2, j2 = changes[-1][2], changes[-1][4]
        lines = []
        for tag, a1, a2, b1, b2 in group:
            if tag == "equal":
                lines += [{"t": " ", "text": _visible(a[k]), "old": k + 1, "new": b1 + (k - a1) + 1} for k in range(a1, a2)]
                continue
            if tag in ("delete", "replace"):
                lines += [{"t": "-", "text": _visible(a[k]), "old": k + 1, "new": None} for k in range(a1, a2)]
            if tag in ("insert", "replace"):
                lines += [{"t": "+", "text": _visible(b[k]), "old": None, "new": k + 1} for k in range(b1, b2)]
        hunks.append(Hunk(id=len(hunks), old_start=i1, old_end=i2, old_lines=a[i1:i2], new_lines=b[j1:j2],
                          before=a[max(0, i1 - context):i1], after=a[i2:i2 + context], lines=lines, new_start=j1))
    return hunks


def unified(rel, old_text, new_text):
    return "\n".join(difflib.unified_diff([_visible(x) for x in split_lines(old_text)],
                                          [_visible(x) for x in split_lines(new_text)],
                                          f"a/{rel}", f"b/{rel}", lineterm=""))


def apply_on_base(base_text, hunks, accepted):
    """기준 내용에 받아들인 덩어리만 적용한 결과."""
    base = split_lines(base_text)
    out, pos = [], 0
    for h in sorted(hunks, key=lambda x: x.old_start):
        out += base[pos:h.old_start]
        out += h.new_lines if h.id in accepted else base[h.old_start:h.old_end]
        pos = h.old_end
    out += base[pos:]
    return "".join(out)


def _find_unique(lines, pattern, start_hint):
    """pattern(줄 목록)이 lines에 정확히 한 번 나오는 위치. 없거나 여러 번이면 None."""
    n = len(pattern)
    if n == 0:
        return start_hint if 0 <= start_hint <= len(lines) else None
    found = [i for i in range(len(lines) - n + 1) if lines[i:i + n] == pattern]
    return found[0] if len(found) == 1 else None


def apply_on_current(current_text, hunks, accepted):
    """바뀐 현재 파일에 받아들인 덩어리를 문맥으로 맞춰 적용한다. (결과, 맞추지 못한 덩어리 id 목록)."""
    cur = split_lines(current_text)
    placed, failed = [], []
    for h in hunks:
        if h.id not in accepted:
            continue
        pattern = h.before + h.old_lines + h.after
        at = _find_unique(cur, pattern, h.old_start - len(h.before))
        if at is None and not h.old_lines:
            # 순수 추가: 앞 문맥만으로라도 정확히 한 번
            at = _find_unique(cur, h.before, h.old_start - len(h.before)) if h.before else None
            if at is not None:
                placed.append((at + len(h.before), at + len(h.before), h))
                continue
        if at is None:
            failed.append(h.id)
            continue
        start = at + len(h.before)
        placed.append((start, start + len(h.old_lines), h))
    placed.sort(key=lambda x: x[0])
    for (s1, e1, _), (s2, _, h2) in zip(placed, placed[1:]):
        if s2 < e1:
            failed.append(h2.id)
    if failed:
        return None, sorted(set(failed))
    for start, end, h in reversed(placed):
        cur[start:end] = h.new_lines
    return "".join(cur), []


def check_syntax(rel, text):
    """적용 결과의 문법 경고(실행하지 않는다). 없으면 ""."""
    lang = cw.language_of(rel)
    try:
        if lang == "python":
            compile(text, rel, "exec", dont_inherit=True)
        elif lang == "json" and text.strip():
            json.loads(text)
    except SyntaxError as e:
        return f"Python 문법 오류 {e.lineno}번째 줄: {e.msg}"
    except ValueError as e:
        return f"JSON 형식 오류: {e}"
    return ""


@dataclass
class ChangeProposal:
    proposal_id: str
    file_path: str           # 작업 폴더 기준 상대 경로
    base_hash: str           # 제안을 만들 때 디스크 내용의 SHA-256(없던 파일은 ABSENT)
    original_content: str
    proposed_content: str
    encoding: str = "utf-8"
    reason: str = ""
    title: str = ""
    source: str = "agent"
    thread_id: str = ""
    status: str = "pending"  # pending · applied · partial · edited · rejected · conflict · cancelled · auto
    created: float = field(default_factory=time.time)
    resolved: float = 0.0
    hunks: list = field(default_factory=list)
    accepted: list = field(default_factory=list)
    result_hash: str = ""
    message: str = ""

    def __post_init__(self):
        if not self.hunks:
            self.hunks = make_hunks(self.original_content, self.proposed_content)

    @property
    def key(self):
        return (self.file_path, self.base_hash, hashlib.sha256(self.proposed_content.encode("utf-8")).hexdigest())

    @property
    def is_new_file(self):
        return self.base_hash == cw.ABSENT

    def to_dict(self, full=True):
        added = sum(h.to_dict()["added"] for h in self.hunks)
        removed = sum(h.to_dict()["removed"] for h in self.hunks)
        data = {"id": self.proposal_id, "path": self.file_path, "status": self.status, "reason": self.reason,
                "title": self.title, "source": self.source, "thread_id": self.thread_id, "created": self.created,
                "resolved": self.resolved, "new_file": self.is_new_file, "added": added, "removed": removed,
                "hunk_count": len(self.hunks), "accepted": list(self.accepted), "message": self.message,
                "language": cw.language_of(self.file_path)}
        if full:
            data["hunks"] = [h.to_dict() for h in self.hunks]
            data["proposed"] = self.proposed_content
            data["original"] = self.original_content
        return data


class ProposalStore:
    """앱이 켜져 있는 동안만 기억한다(앱을 끄면 대기 중인 제안은 사라지고 파일에는 아무것도 적용되지 않는다)."""

    def __init__(self):
        self._items = {}
        self._lock = threading.RLock()

    def add(self, proposal):
        with self._lock:
            for p in self._items.values():
                if p.status == "pending" and p.key == proposal.key:
                    return p, False  # 같은 제안이 이미 기다리는 중: 다시 만들지 않는다
            self._items[proposal.proposal_id] = proposal
            done = [p for p in self._items.values() if p.status != "pending"]
            for old in sorted(done, key=lambda p: p.created)[:max(0, len(self._items) - MAX_PROPOSALS)]:
                self._items.pop(old.proposal_id, None)
            return proposal, True

    def get(self, proposal_id):
        with self._lock:
            p = self._items.get(str(proposal_id or ""))
        if p is None:
            raise ProposalError("변경 제안을 찾지 못했습니다(앱을 다시 시작하면 대기 중인 제안은 사라집니다).")
        return p

    def all(self):
        with self._lock:
            return sorted(self._items.values(), key=lambda p: p.created, reverse=True)

    def pending(self):
        return [p for p in self.all() if p.status == "pending"]


def new_proposal(workspace, rel, original, proposed, encoding="utf-8", reason="", title="", source="agent",
                 thread_id=""):
    """디스크의 현재 해시를 기준으로 제안을 만든다. original은 지금 파일 내용(없던 파일이면 "")."""
    rel = cw.clean_rel(rel)
    base = cw.current_hash(workspace, rel)
    if base != cw.ABSENT:
        disk = _read_text(workspace, rel, encoding)
        if disk != original:
            raise ProposalError("제안을 만드는 사이에 파일이 바뀌었습니다. 다시 읽고 시도하세요.")
    elif original:
        raise ProposalError("파일이 사라졌습니다.")
    return ChangeProposal(proposal_id=uuid.uuid4().hex[:16], file_path=rel, base_hash=base,
                          original_content=original, proposed_content=proposed, encoding=encoding or "utf-8",
                          reason=str(reason or "")[:500], title=str(title or "")[:200], source=source,
                          thread_id=str(thread_id or ""))


def _read_text(workspace, rel, encoding):
    path = cw.resolve(workspace, rel, must_exist=True, allow_root=False)
    raw, _ = cw._read_checked(path, cw.root_of(workspace))
    try:
        return raw.decode(encoding or "utf-8")
    except (UnicodeDecodeError, LookupError):
        return cw.decode(raw)[0]


def preview(workspace, proposal, accepted, edited=None):
    """적용하면 어떤 내용이 될지(파일은 쓰지 않는다). conflict면 현재 파일이 기준과 다르다는 뜻."""
    accepted = {int(i) for i in accepted or []}
    now = cw.current_hash(workspace, proposal.file_path)
    text = edited if edited is not None else apply_on_base(proposal.original_content, proposal.hunks, accepted)
    return {"text": text, "conflict": now != proposal.base_hash, "warning": check_syntax(proposal.file_path, text),
            "accepted": sorted(accepted)}


def apply(workspace, proposal, accepted, edited=None, rebase=False):
    """받아들인 덩어리(또는 사용자가 고친 전체 내용 edited)를 파일에 쓴다. 결과 상태를 proposal에 남기고 돌려준다."""
    if proposal.status != "pending":
        raise ProposalError(f"이미 처리한 제안입니다({proposal.status}). 같은 변경을 두 번 적용하지 않습니다.")
    ids = {h.id for h in proposal.hunks}
    accepted = {int(i) for i in accepted or [] if int(i) in ids}
    if edited is None and not accepted:
        return reject(proposal)
    now = cw.current_hash(workspace, proposal.file_path)
    if edited is not None:
        if now != proposal.base_hash:
            raise cw.ConflictError("검토하는 사이에 파일이 바뀌었습니다. 고친 내용을 그대로 덮어쓰지 않습니다.", now)
        final, status = str(edited), "edited"
    elif now == proposal.base_hash:
        final = apply_on_base(proposal.original_content, proposal.hunks, accepted)
        status = "applied" if accepted == ids else "partial"
    elif rebase and now != cw.ABSENT and not proposal.is_new_file:
        current = _read_text(workspace, proposal.file_path, proposal.encoding)
        final, failed = apply_on_current(current, proposal.hunks, accepted)
        if final is None:
            raise cw.ConflictError(f"현재 파일에서 {len(failed)}개 덩어리의 자리를 찾지 못했습니다"
                                   f"({', '.join(str(i + 1) for i in failed)}번). 적용하지 않았습니다.", now)
        status = "applied" if accepted == ids else "partial"
    else:
        raise cw.ConflictError("검토하는 사이에 파일이 바뀌었습니다(다른 프로그램이나 편집기에서 저장). "
                               "'현재 파일에 맞춰 적용'을 쓰거나 제안을 거부하세요.", now)
    data = final.encode(proposal.encoding or "utf-8")
    path = cw.resolve(workspace, proposal.file_path, allow_root=False)
    if proposal.is_new_file:
        root = cw.root_of(workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cw._inside(root, cw._real(path.parent)):
            raise ProposalError("작업 폴더 밖에는 쓸 수 없습니다.")
    # 쓰기 직전에 한 번 더(사이에 바뀌었으면 쓰지 않는다)
    if cw.current_hash(workspace, proposal.file_path) != now:
        raise cw.ConflictError("적용하는 사이에 파일이 바뀌었습니다. 다시 시도하세요.", cw.current_hash(workspace, proposal.file_path))
    cw.atomic_write(path, data)
    proposal.status = status
    proposal.accepted = sorted(accepted) if edited is None else []
    proposal.result_hash = hashlib.sha256(data).hexdigest()
    proposal.resolved = time.time()
    proposal.proposed_content = final if edited is not None else proposal.proposed_content
    proposal.message = {"applied": "모두 적용", "partial": f"{len(accepted)}/{len(ids)}개 덩어리 적용",
                        "edited": "고친 내용으로 적용"}[status]
    return {"status": status, "content": final, "accepted": sorted(accepted), "total": len(ids),
            "diff": unified(proposal.file_path, proposal.original_content, final)}


def reject(proposal, message="거부"):
    if proposal.status != "pending":
        raise ProposalError(f"이미 처리한 제안입니다({proposal.status}).")
    proposal.status = "rejected"
    proposal.resolved = time.time()
    proposal.message = message
    return {"status": "rejected", "content": None, "accepted": [], "total": len(proposal.hunks), "diff": ""}


def finish(proposal, status, message=""):
    """대기 중인 제안을 적용 없이 끝낸다(cancelled: 에이전트 중지, conflict 등)."""
    if proposal.status == "pending":
        proposal.status = status
        proposal.resolved = time.time()
        proposal.message = message
    return proposal

