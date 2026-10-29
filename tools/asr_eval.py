# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""한국어 로컬 음성 인식 정확도 측정(README의 'PO노트 → 로컬 AI 정확도' 표).

    pip install pyarrow soundfile        # requirements.txt 외에 필요
    python tools/asr_eval.py <작업 폴더> [--limit N]

<작업 폴더>에 Zeroth-Korean test(457문장, 60MB)와 FLEURS ko_kr dev(226개, 126MB)를 받고(리비전 고정),
stt.LocalEngine의 한국어(ko)·다국어(multi) 모델을 '소리 크기 맞춤' 방식별로 돌려 글자 오류율(CER)을 낸다.
모델은 <작업 폴더>/stt_models에 받는다(stt.download). 숫자가 든 FLEURS 문장은 표기(아홉/9) 차이로 뺀다.
SHERPA_ONNX_CAPI 환경 변수와 함께 sys.modules["sherpa_onnx"]=None로 돌리면 안드로이드 경로(sherpa_capi)로 잰다
(결과는 pip 패키지와 같음을 확인했다).
"""
import csv
import io
import re
import sys
import tarfile
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import requests
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stt  # noqa: E402

ZEROTH = ("https://huggingface.co/datasets/kresnik/zeroth_korean/resolve/1fe937899f828af822293d05e086200946088bdf"
          "/data/test-00000-of-00001.parquet")
FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/70bb2e84b976b7e960aa89f1c648e09c59f894dd/data/ko_kr"


def get(url, path):
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(path, "wb") as out:
                for chunk in r.iter_content(1 << 20):
                    out.write(chunk)
    return path


def norm(s):
    return re.sub(r"[^가-힣A-Za-z]", "", s)


def edits(a, b):
    row = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, row[0] = row[0], i
        for j in range(1, len(b) + 1):
            cur = row[j]
            row[j] = min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
    return row[-1]


def datasets(work, limit):
    z = pq.read_table(get(ZEROTH, work / "zeroth_test.parquet")).to_pylist()
    zeroth = [(r["text"], sf.read(io.BytesIO(r["audio"]["bytes"]), dtype="float32")[0]) for r in z]
    tsv = get(f"{FLEURS}/dev.tsv", work / "fleurs" / "dev.tsv")
    tar = get(f"{FLEURS}/audio/dev.tar.gz", work / "fleurs" / "dev.tar.gz")
    wavs = {}
    with tarfile.open(tar) as t:
        for m in t.getmembers():
            if m.isfile():
                wavs[Path(m.name).name] = sf.read(io.BytesIO(t.extractfile(m).read()), dtype="float32")[0]
    rows = csv.reader(open(tsv, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
    fleurs = [(r[3], wavs[r[1]]) for r in rows if r[1] in wavs and not re.search(r"\d", r[2])]
    return {"zeroth": zeroth[:limit], "fleurs": fleurs[:limit]}


def rms_up(x, target=0.05, cap=30.0):
    """조용한 구간만 키운다(최대 cap배, 잘림 방지)."""
    r = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return np.clip(x * min(cap, max(1.0, target / r)), -1, 1).astype(np.float32) if r > 0 else x


VARIANTS = {
    "none": lambda x: x,
    "peak0.5": lambda x: (x * min(30.0, 0.5 / max(1e-9, float(np.abs(x).max())))).astype(np.float32),
    "rms0.05_up": rms_up,
    "rms0.1_up": lambda x: rms_up(x, 0.1),
}


def main():
    work = Path(sys.argv[1])
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    stt.MODELS_DIR = work / "stt_models"
    stt.download("ko")
    stt.download("multi")
    data = datasets(work, limit)
    for key in ("ko", "multi"):
        engine = stt.LocalEngine(key, "ko")
        for name, f in VARIANTS.items():
            line = [f"{key:5s} {name:11s}"]
            for dname, items in data.items():
                errors = chars = empty = hi_e = hi_n = hi_c = 0
                t, dur = time.perf_counter(), 0.0
                for ref, x in items:
                    text, conf = engine.recognize(f(x))
                    e = edits(norm(ref), norm(text))
                    errors, chars, empty, dur = errors + e, chars + len(norm(ref)), empty + (not text), dur + len(x) / 16000
                    if conf is not None and conf >= stt.CONF_THRESHOLD:
                        hi_e, hi_c, hi_n = hi_e + e, hi_c + len(norm(ref)), hi_n + 1
                rtf = (time.perf_counter() - t) / dur
                conf_part = f" conf>={stt.CONF_THRESHOLD}: n={hi_n} CER={hi_e / max(1, hi_c):.3f}" if key == "ko" else ""
                line.append(f"{dname}[{len(items)}] CER={errors / chars:.3f} 빈결과={empty} RTF={rtf:.3f}{conf_part}")
            print(" | ".join(line), flush=True)


if __name__ == "__main__":
    main()
