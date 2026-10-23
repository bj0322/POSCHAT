"""test_sherpa_capi가 하위 프로세스로 부른다: 시험 음성을 pip 패키지(pip) 또는 C API 바인딩(capi)으로 인식해 JSON으로 출력.

    python tests/_stt_worker.py pip|capi <모델 폴더>
"""
import json
import sys
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
mode, models = sys.argv[1], Path(sys.argv[2])
if mode == "capi":
    sys.modules["sherpa_onnx"] = None  # pip 패키지를 숨겨 안드로이드처럼 sherpa_capi를 쓰게 한다
import stt  # noqa: E402


def load(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


wavs = [models / "test_wavs" / f"{i}.wav" for i in range(4)]
out = {"backend": stt.sherpa().__name__}
with patch.object(stt, "MODELS_DIR", models / "stt_models"):
    engine = stt.LocalEngine("ko", "ko")
    for p in wavs:
        text, conf = engine.recognize(load(p))
        out[p.name] = {"text": text, "conf": conf}
    seg = stt.Segmenter()
    audio = np.concatenate([np.concatenate([load(p), np.zeros(12000, np.float32)]) for p in wavs])
    found = []
    for i in range(0, len(audio), 1600):
        found += seg.feed(audio[i:i + 1600])
    found += seg.flush()
    out["vad"] = [(int(b), len(s), round(float(np.sum(s)), 3)) for b, s in found]
json.dump(out, sys.stdout, ensure_ascii=False)
