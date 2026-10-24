# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""POSCHAT Lab(1.16): 결과 파일 읽기·지표 뽑기·통계·그래프용 표본·Run 비교. 화면·저장소와 상관없는 순수 함수.

원칙
- 추측하지 않는다: 숫자로 읽히지 않는 칸, 빈 칸, NaN, ±Infinity는 값으로 쓰지 않고 경고로 남긴다.
- 단위: 머리글의 "latency (ms)"·"latency[ms]"·"latency_ms"에서 읽는다. 변환 규칙이 없으면 단위가 다른 같은 이름의 지표를
  같은 것으로 보지 않는다(비교 표에서 경고).
- 지표마다 원본 파일·행·열(또는 JSON 경로)과 파일 해시를 남겨 어디서 왔는지 되짚을 수 있게 한다.
- 통계(최솟값·최댓값·평균·표준편차·개수)는 파일 전체로 계산하고, 그래프는 표본(최대 MAX_POINTS점)만 보낸다(sampled 표시).
"""
import csv
import hashlib
import io
import json
import math
import os
import re

MAX_FILE_BYTES = 200 * 1024 * 1024     # 이보다 큰 표 파일은 읽지 않는다
MAX_ROWS = 2_000_000
MAX_POINTS = 2000
TABLE_EXT = {".csv": "csv", ".tsv": "tsv", ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl", ".txt": "log",
             ".log": "log", ".out": "log"}
IMAGE_EXT = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
UNIT_RE = re.compile(r"^(?P<name>.*?)\s*(?:\((?P<u1>[^()]{1,16})\)|\[(?P<u2>[^\[\]]{1,16})\])\s*$")
SUFFIX_UNITS = ("ms", "us", "ns", "s", "sec", "mv", "v", "mw", "w", "mhz", "ghz", "hz", "db", "pct", "percent", "pj", "nj",
                "fj", "um", "nm", "mm", "mb", "gb", "kb", "bits", "bit")
LOG_RE = re.compile(r"(?P<name>[A-Za-z_][\w./-]{0,60})\s*[:=]\s*(?P<value>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|nan|NaN|inf|-inf)"
                    r"\s*(?P<unit>%|[A-Za-zµ]{1,6})?(?=[\s,;)]|$)")


class ResultError(Exception):
    pass


def kind_of(path):
    ext = os.path.splitext(str(path))[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    return TABLE_EXT.get(ext, "other")


def sha256_file(path, limit=MAX_FILE_BYTES):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        read = 0
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            read += len(chunk)
            if read > limit:
                return ""
            h.update(chunk)
    return h.hexdigest()


def file_ref(path, rel=None):
    """결과 파일 참조: 경로·크기·수정 시각·해시. 원본은 옮기지 않는다."""
    st = os.stat(path)
    return {"path": rel or str(path), "abs": str(path), "size": st.st_size, "mtime": st.st_mtime,
            "sha256": sha256_file(path) if st.st_size <= 50 * 1024 * 1024 else "", "kind": kind_of(path)}


def check_ref(ref):
    """참조가 아직 유효한지: ok · missing(없어짐) · changed(내용이 바뀜)."""
    p = ref.get("abs") or ref.get("path")
    if not p or not os.path.isfile(p):
        return "missing"
    st = os.stat(p)
    if st.st_size != ref.get("size") or (ref.get("sha256") and abs(st.st_mtime - ref.get("mtime", 0)) > 1e-6
                                         and sha256_file(p) != ref["sha256"]):
        return "changed"
    return "ok"


# ---- 숫자·단위 ----

def to_number(text):
    """(값, 상태). 상태: ok · empty · nan · inf · text. ok가 아니면 값은 None(추측하지 않는다)."""
    if text is None:
        return None, "empty"
    if isinstance(text, bool):
        return None, "text"
    if isinstance(text, (int, float)):
        if isinstance(text, float) and math.isnan(text):
            return None, "nan"
        if isinstance(text, float) and math.isinf(text):
            return None, "inf"
        return float(text), "ok"
    s = str(text).strip()
    if not s:
        return None, "empty"
    low = s.lower()
    if low in ("nan", "na", "n/a", "null", "none"):
        return None, "nan"
    if low.lstrip("+-") in ("inf", "infinity"):
        return None, "inf"
    try:
        v = float(s)
    except ValueError:
        return None, "text"
    if math.isnan(v):
        return None, "nan"
    if math.isinf(v):
        return None, "inf"
    return v, "ok"


def split_unit(header):
    """'latency (ms)' → ('latency', 'ms'), 'power_mw' → ('power_mw', 'mw'), 'acc' → ('acc', '')."""
    h = str(header or "").strip()
    m = UNIT_RE.match(h)
    if m and m.group("name"):
        return m.group("name").strip(), (m.group("u1") or m.group("u2")).strip()
    low = h.lower()
    for suffix in SUFFIX_UNITS:
        if low.endswith("_" + suffix):
            return h, suffix
    return h, ""


# ---- 표 읽기 ----

def _check_size(path):
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise ResultError(f"결과 파일을 읽지 못했습니다: {e.strerror or e}")
    if size > MAX_FILE_BYTES:
        raise ResultError(f"파일이 너무 큽니다({size / 1048576:.0f}MB). {MAX_FILE_BYTES // 1048576}MB까지 읽습니다.")


def _flatten(obj, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list) and obj and all(not isinstance(x, (dict, list)) for x in obj) and len(obj) <= 50:
        for i, v in enumerate(obj):
            out[f"{prefix}[{i}]"] = v
    else:
        out[prefix] = obj
    return out


def read_table(path, limit=MAX_ROWS):
    """표로 읽는다: {"kind", "columns", "rows"(목록의 목록, 원래 글자/값), "truncated", "duplicates", "scalars"}.
    JSON 객체 하나는 scalars(경로 → 값), 객체 목록·JSONL은 표, 로그는 '이름: 숫자' 줄들의 표(이름·값·단위·줄)."""
    _check_size(path)
    kind = kind_of(path)
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")
    if kind in ("csv", "tsv") or (kind == "other" and "," in text[:2000]):
        return _read_csv(text, "\t" if kind == "tsv" else None, limit)
    if kind == "json":
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ResultError(f"JSON 형식이 아닙니다: {e}")
        if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
            return _records_table([_flatten(x) for x in data[:limit]], "json", len(data) > limit)
        if isinstance(data, dict):
            # 실험 결과 JSON 흔한 모양: {"history": [{...}, ...], "final": {...}} → 표가 있으면 표도 준다
            flat = _flatten({k: v for k, v in data.items() if not (isinstance(v, list) and v and isinstance(v[0], dict))})
            table = next((k for k, v in data.items() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)), None)
            out = _records_table([_flatten(x) for x in data[table][:limit]], "json", False) if table else \
                {"kind": "json", "columns": [], "rows": [], "truncated": False, "duplicates": []}
            out["scalars"] = flat
            out["table_key"] = table or ""
            return out
        raise ResultError("JSON에서 표(객체 목록)나 값(객체)을 찾지 못했습니다.")
    if kind == "jsonl":
        records, bad = [], 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(obj, dict):
                records.append(_flatten(obj))
            if len(records) >= limit:
                break
        out = _records_table(records, "jsonl", len(records) >= limit)
        out["bad_lines"] = bad
        return out
    if kind == "log" or kind == "other":
        rows, seen, dups = [], {}, set()
        for no, line in enumerate(text.splitlines(), 1):
            for m in LOG_RE.finditer(line):
                name = m.group("name")
                if name in seen:
                    dups.add(name)
                seen[name] = no
                rows.append([name, m.group("value"), m.group("unit") or "", no])
            if len(rows) >= limit:
                break
        return {"kind": "log", "columns": ["name", "value", "unit", "line"], "rows": rows, "truncated": len(rows) >= limit,
                "duplicates": sorted(dups)}
    raise ResultError("표로 읽을 수 없는 파일입니다(CSV·TSV·JSON·JSONL·로그).")


def _read_csv(text, delimiter, limit):
    sample = text[:20000]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ResultError("빈 표입니다.")
    if all(to_number(h)[1] == "ok" for h in header if h.strip()):
        # 머리글이 없는 숫자 표: 열 이름을 c1, c2…로
        rows = [header]
        header = [f"c{i + 1}" for i in range(len(header))]
    else:
        rows = []
    dups = sorted({h for h in header if header.count(h) > 1})
    truncated = False
    for row in reader:
        if not row:
            continue
        rows.append(row)
        if len(rows) >= limit:
            truncated = True
            break
    return {"kind": "csv", "columns": [h.strip() for h in header], "rows": rows, "truncated": truncated,
            "duplicates": dups, "delimiter": delimiter}


def _records_table(records, kind, truncated):
    columns = []
    for r in records:
        for k in r:
            if k not in columns:
                columns.append(k)
    rows = [[r.get(c) for c in columns] for r in records]
    return {"kind": kind, "columns": columns, "rows": rows, "truncated": truncated, "duplicates": []}


# ---- 통계·표본 ----

def column_values(table, column):
    if column not in table["columns"]:
        raise ResultError(f"열이 없습니다: {column}")
    i = table["columns"].index(column)
    return [row[i] if i < len(row) else None for row in table["rows"]]


def stats(values):
    """전체 값으로 계산한 통계와 칸 상태 수."""
    counts = {"ok": 0, "empty": 0, "nan": 0, "inf": 0, "text": 0}
    nums = []
    for v in values:
        n, st = to_number(v)
        counts[st] += 1
        if st == "ok":
            nums.append(n)
    out = {"count": len(values), "numeric": counts["ok"], "empty": counts["empty"], "nan": counts["nan"],
           "inf": counts["inf"], "text": counts["text"]}
    if nums:
        mean = sum(nums) / len(nums)
        var = sum((x - mean) ** 2 for x in nums) / (len(nums) - 1) if len(nums) > 1 else 0.0
        out.update(min=min(nums), max=max(nums), mean=mean, std=math.sqrt(var), first=nums[0], last=nums[-1])
    return out


def numeric_columns(table, min_ratio=0.5):
    """숫자 칸이 절반 넘는 열(지표 후보)."""
    out = []
    for c in table["columns"]:
        vals = column_values(table, c)
        st = stats(vals)
        if st["count"] and st["numeric"] / st["count"] >= min_ratio:
            name, unit = split_unit(c)
            out.append({"column": c, "name": name, "unit": unit, "stats": st})
    return out


def series(table, x_col, y_cols, max_points=MAX_POINTS):
    """그래프용 점. x_col이 비면 행 번호. 숫자가 아닌 점은 뺀다(뺀 수를 알린다). 많으면 고르게 표본을 뽑는다."""
    n = len(table["rows"])
    xs = column_values(table, x_col) if x_col else list(range(1, n + 1))
    out = {"x": x_col or "행", "x_unit": split_unit(x_col)[1] if x_col else "", "total": n, "series": []}
    step = max(1, math.ceil(n / max_points)) if max_points else 1
    out["sampled"] = step > 1
    out["step"] = step
    for col in y_cols:
        ys = column_values(table, col)
        pts, skipped = [], 0
        for i in range(0, n, step):
            x, sx = to_number(xs[i])
            y, sy = to_number(ys[i])
            if sx != "ok" or sy != "ok":
                skipped += 1
                continue
            pts.append([x, y])
        name, unit = split_unit(col)
        out["series"].append({"column": col, "name": name, "unit": unit, "points": pts, "skipped": skipped,
                              "stats": stats(ys)})
    return out


def page(table, offset=0, limit=100):
    offset = max(0, int(offset or 0))
    limit = max(1, min(500, int(limit or 100)))
    rows = [[_cell(c) for c in r] for r in table["rows"][offset:offset + limit]]
    return {"columns": table["columns"], "rows": rows, "offset": offset, "total": len(table["rows"]),
            "truncated": table.get("truncated", False)}


def _cell(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return str(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:200]
    return v


# ---- 지표 뽑기 ----

AGGREGATES = ("last", "first", "max", "min", "mean")


def extract(path, spec, ref=None):
    """spec: [{"column" 또는 "key", "name"(선택), "unit"(선택), "how": last|first|max|min|mean|row:N}].
    돌려줌: {"metrics": {이름: {"value", "unit", "source": {...}}}, "warnings": [...]}. 값이 없으면 지표를 만들지 않는다."""
    table = read_table(path)
    ref = ref or {}
    metrics, warnings = {}, []
    if table.get("duplicates"):
        warnings.append(f"이름이 겹치는 열·항목: {', '.join(table['duplicates'][:10])} (마지막 것을 씁니다)")
    for item in spec or []:
        how = str(item.get("how") or "last")
        unit_given = str(item.get("unit") or "").strip()
        if item.get("key"):  # JSON 값 하나(경로) 또는 로그 이름
            key = str(item["key"])
            if table["kind"] == "log":
                rows = [r for r in table["rows"] if r[0] == key]
                if not rows:
                    warnings.append(f"로그에서 '{key}'를 찾지 못했습니다.")
                    continue
                pick = rows[-1] if how != "first" else rows[0]
                v, st = to_number(pick[1])
                src = {"line": pick[3]}
                unit = unit_given or pick[2]
            else:
                scalars = table.get("scalars") or {}
                if key not in scalars:
                    warnings.append(f"JSON에서 '{key}'를 찾지 못했습니다.")
                    continue
                v, st = to_number(scalars[key])
                src = {"json_path": key}
                unit = unit_given or split_unit(key.split(".")[-1])[1]
            if st != "ok":
                warnings.append(f"'{key}' 값이 숫자가 아닙니다({st}). 지표로 쓰지 않습니다.")
                continue
            name = str(item.get("name") or key)
            metrics[name] = {"value": v, "unit": unit, "source": {**_src(path, ref), **src, "how": how}}
            continue
        col = str(item.get("column") or "")
        if col not in table["columns"]:
            warnings.append(f"열이 없습니다: {col}")
            continue
        vals = column_values(table, col)
        name = str(item.get("name") or split_unit(col)[0] or col)
        unit = unit_given or split_unit(col)[1]
        value, row_no, problem = _aggregate(vals, how)
        if problem:
            warnings.append(f"'{col}': {problem}")
        if value is None:
            continue
        st = stats(vals)
        if st["nan"] or st["inf"] or st["text"] or st["empty"]:
            warnings.append(f"'{col}'에 숫자가 아닌 칸이 있습니다(빈 칸 {st['empty']}, NaN {st['nan']}, ±Inf {st['inf']}, 글자 "
                            f"{st['text']}). 그 칸은 빼고 계산했습니다.")
        metrics[name] = {"value": value, "unit": unit,
                         "source": {**_src(path, ref), "column": col, "row": row_no, "how": how, "rows": st["count"]}}
    return {"metrics": metrics, "warnings": warnings}


def _src(path, ref):
    return {"file": ref.get("path") or str(path), "sha256": ref.get("sha256", "")}


def _aggregate(vals, how):
    """(값, 행 번호(1부터, 집계면 None), 문제)."""
    nums = [(i, to_number(v)) for i, v in enumerate(vals)]
    ok = [(i, n) for i, (n, st) in nums if st == "ok"]
    if how.startswith("row:"):
        try:
            idx = int(how[4:]) - 1
        except ValueError:
            return None, None, "행 번호가 올바르지 않습니다."
        if not 0 <= idx < len(vals):
            return None, None, f"{idx + 1}행이 없습니다."
        n, st = nums[idx][1]
        if st != "ok":
            return None, None, f"{idx + 1}행 값이 숫자가 아닙니다({st}). 지표로 쓰지 않습니다."
        return n, idx + 1, ""
    if not ok:
        return None, None, "숫자 값이 없습니다. 지표로 쓰지 않습니다."
    if how == "last":
        return ok[-1][1], ok[-1][0] + 1, ""
    if how == "first":
        return ok[0][1], ok[0][0] + 1, ""
    if how == "max":
        i, n = max(ok, key=lambda t: t[1])
        return n, i + 1, ""
    if how == "min":
        i, n = min(ok, key=lambda t: t[1])
        return n, i + 1, ""
    if how == "mean":
        return sum(n for _, n in ok) / len(ok), None, ""
    return None, None, f"알 수 없는 방식입니다: {how}"


def suggest(path):
    """지표 후보(사용자가 고르게): 표의 숫자 열, JSON 값, 로그 이름."""
    table = read_table(path)
    out = {"kind": table["kind"], "columns": numeric_columns(table) if table["columns"] and table["kind"] != "log" else [],
           "keys": [], "warnings": []}
    if table.get("scalars"):
        for k, v in table["scalars"].items():
            n, st = to_number(v)
            if st == "ok":
                out["keys"].append({"key": k, "value": n, "unit": split_unit(k.split(".")[-1])[1]})
    if table["kind"] == "log":
        last = {}
        for name, value, unit, line in table["rows"]:
            last[name] = {"key": name, "value": to_number(value)[0], "unit": unit, "line": line}
        out["keys"] = list(last.values())[:100]
    if table.get("duplicates"):
        out["warnings"].append(f"이름이 겹칩니다: {', '.join(table['duplicates'][:10])}")
    if table.get("truncated"):
        out["warnings"].append("파일이 커서 앞부분만 읽었습니다.")
    return out


# ---- 비교 ----

def compare(runs):
    """Run 여러 개를 나란히: 파라미터·코드 버전·환경·상태·지표·시간. 다른 값·비교할 수 없는 지표를 표시한다."""
    if len(runs) < 2:
        raise ResultError("비교할 실행을 두 개 이상 고르세요.")
    ids = [r["id"] for r in runs]
    params = sorted({k for r in runs for k in (r.get("params") or {})})
    param_rows = []
    for k in params:
        values = [(r.get("params") or {}).get(k) for r in runs]
        param_rows.append({"name": k, "values": values, "differs": len({json.dumps(v, sort_keys=True) for v in values}) > 1})
    names = sorted({k for r in runs for k in (r.get("metrics") or {})})
    metric_rows, warnings = [], []
    for k in names:
        cells = [(r.get("metrics") or {}).get(k) for r in runs]
        units = {c.get("unit", "") for c in cells if c}
        comparable = len(units) <= 1
        if not comparable:
            warnings.append(f"지표 '{k}'의 단위가 다릅니다({', '.join(sorted(u or '단위 없음' for u in units))}). "
                            "변환 규칙이 없어 같은 값으로 비교하지 않습니다.")
        missing = [r["id"] for r, c in zip(runs, cells) if not c]
        if missing:
            warnings.append(f"지표 '{k}'가 없는 실행: {', '.join(missing)}")
        values = [c["value"] if c else None for c in cells]
        present = [v for v in values if v is not None]
        metric_rows.append({"name": k, "values": values, "units": [c.get("unit", "") if c else "" for c in cells],
                            "comparable": comparable, "min": min(present) if comparable and present else None,
                            "max": max(present) if comparable and present else None})
    code = [{"commit": (r.get("code") or {}).get("commit", ""), "dirty": (r.get("code") or {}).get("dirty"),
             "branch": (r.get("code") or {}).get("branch", "")} for r in runs]
    if len({c["commit"] for c in code}) > 1:
        warnings.append("코드 버전(커밋)이 다른 실행이 섞여 있습니다.")
    if any(c["dirty"] for c in code):
        warnings.append("커밋하지 않은 변경이 있는 상태에서 실행한 Run이 있어 재현성이 제한됩니다.")
    env = [{"python": (r.get("env") or {}).get("python", ""), "os": (r.get("env") or {}).get("os", "")} for r in runs]
    if len({json.dumps(e, sort_keys=True) for e in env}) > 1:
        warnings.append("실행 환경(OS·Python)이 다른 실행이 섞여 있습니다.")
    return {"runs": [{"id": r["id"], "seq": r.get("seq"), "name": r.get("name", ""), "status": r.get("status"),
                      "seconds": r.get("seconds"), "exit_code": r.get("exit_code"),
                      "outputs": [o.get("path") for o in r.get("outputs") or []]} for r in runs],
            "ids": ids, "params": param_rows, "metrics": metric_rows, "code": code, "env": env, "warnings": warnings}
