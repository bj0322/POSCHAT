"""PO노트 로컬 음성 인식의 정확도·속도 측정. 안드로이드 계측 테스트(SttBenchmarkTest)와 데스크톱 tests/가 부른다.

모델 저장소의 한국어 시험 음성 4개(정답 trans.txt 포함, 커밋 고정·SHA-256 확인)를
1) 로컬 인식기에 하나씩 넣어 글자 오류율(CER)·신뢰도·처리 시간을 재고,
2) 휴대폰 녹음과 같은 경로(android_main.mic_block → sounddevice 대신 객체 → stt.LiveSession: VAD → 인식)로
   0.1초 블록씩 넣어 전체 처리 시간과 메모리를 잰다.
"""
import hashlib
import json
import time
import wave
from pathlib import Path

import requests

_KO = "https://huggingface.co/k2-fsa/sherpa-onnx-zipformer-korean-2024-06-24/resolve/0fb4b2b5c8d3e5766121481ba911961e3649c664"
TEST_WAVS = [
    ("0.wav", "0faf0b037efe428e5e561195f4d2aa148b2a0a2a5fc540b2c184b9d5c241e984"),
    ("1.wav", "b59bf1209d0d37088335d94f21394f31d794743bc9c849e3a4c9932a985c0bae"),
    ("2.wav", "ed95184720061842e8f0f5df7e5826f97b0b26cd3c9bff18709f5be07ff18728"),
    ("3.wav", "b1d2de5f90c73dfacddc1d6ab93a41427c89573f261ed2d425a6a37b3ee32931"),
    ("trans.txt", "7dafa4e5fcdeae1552e4144494e83de6d88ead237f7fc3e851999c61b71f9f75"),
]


def fetch(wav_dir):
    """VAD·한국어 모델(stt.MODELS_DIR)과 시험 음성(wav_dir)을 내려받는다."""
    import stt
    stt.download("ko")
    wav_dir = Path(wav_dir)
    wav_dir.mkdir(parents=True, exist_ok=True)
    for name, sha in TEST_WAVS:
        path = wav_dir / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
            continue
        data = requests.get(f"{_KO}/test_wavs/{name}", timeout=60).content
        if hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError(f"시험 음성이 손상되었습니다: {name}")
        path.write_bytes(data)


def cer(ref, hyp):
    """띄어쓰기를 뺀 글자 오류율."""
    a, b = ref.replace(" ", ""), hyp.replace(" ", "")
    row = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, row[0] = row[0], i
        for j in range(1, len(b) + 1):
            cur = row[j]
            row[j] = min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
    return row[-1] / max(1, len(a))


def _pcm16(path):
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2), path
        return w.readframes(w.getnframes())


def _peak_rss_mb():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


class _FakeHost:
    """녹음 서비스 대신: 마이크를 연 것으로 하고 소리는 run()이 mic_block으로 직접 넣는다."""

    def micStart(self):
        return None

    def micStop(self):
        pass


def run(wav_dir):
    """측정 결과 dict. android_main._setup()을 부른 뒤에 쓴다."""
    import numpy as np
    import android_main
    import stt

    wav_dir = Path(wav_dir)
    refs = dict(line.split(" ", 1) for line in (wav_dir / "trans.txt").read_text(encoding="utf-8").splitlines()
                if line.strip())
    names = sorted(refs)
    report = {"backend": stt.sherpa().__name__, "available": stt.available(), "threads": stt.NUM_THREADS}

    t = time.perf_counter()
    engine = stt.LocalEngine("ko", "ko")
    report["load_seconds"] = round(time.perf_counter() - t, 2)
    files = {}
    for name in names:
        samples = np.frombuffer(_pcm16(wav_dir / name), dtype="<i2").astype(np.float32) / 32768
        t = time.perf_counter()
        text, conf = engine.recognize(samples)
        seconds = time.perf_counter() - t
        files[name] = {"text": text, "ref": refs[name], "cer": round(cer(refs[name], text), 4), "conf": round(conf, 3),
                       "audio_seconds": round(len(samples) / 16000, 2), "seconds": round(seconds, 3)}
    report["files"] = files

    # 휴대폰 녹음 경로: 말 사이에 0.5초 쉼, 끝에 1초 쉼
    silence = bytes(16000)  # 0.5초
    audio = b"".join(silence + _pcm16(wav_dir / n) for n in names) + silence * 2
    segments, errors = [], []
    old_host, android_main._host = android_main._host, _FakeHost()
    try:
        session = stt.LiveSession(engine, segments.append, on_error=errors.append)
        session.start()
        t = time.perf_counter()
        block = 3200  # 0.1초(PCM16)
        for i in range(0, len(audio), block):
            android_main.mic_block(audio[i:i + block])
        fed = time.perf_counter() - t
        while session.elapsed < len(audio) / 32000 - 0.05:
            time.sleep(0.01)
        session.stop()
        seconds = time.perf_counter() - t
    finally:
        android_main._host = old_host
    texts = [s["text"] for s in segments]
    audio_seconds = len(audio) / 32000
    report["pipeline"] = {
        "segments": texts, "errors": errors, "cer": round(cer("".join(refs[n] for n in names), "".join(texts)), 4),
        "audio_seconds": round(audio_seconds, 2), "seconds": round(seconds, 3), "feed_seconds": round(fed, 3),
        "rtf": round(seconds / audio_seconds, 4), "stats": session.stats,
    }
    report["peak_rss_mb"] = _peak_rss_mb()
    return report


def main(files_dir, res_dir, wav_dir):
    """안드로이드 계측 테스트가 부른다. JSON 문자열."""
    import android_main
    android_main._setup(files_dir, res_dir)
    fetch(wav_dir)
    return json.dumps(run(wav_dir), ensure_ascii=False)
