"""PO노트의 실시간 음성 인식(STT).

마이크 소리를 16kHz로 받아 음성 구간 검출(VAD)로 말 한 마디씩 끊고, 끊은 구간을 글자로 바꾼다.

- 로컬 AI(기본): sherpa-onnx로 이 기기에서 인식한다. 인터넷·API 비용이 없고 CPU 스레드 2개만 쓴다.
  모델은 처음 쓸 때 한 번 내려받는다(한국어 약 76MB, 다국어 약 240MB).
- POSTECH GenAI 서버: POSTECH에는 음성 인식 API(/audio/transcriptions)가 없지만, OpenAI 호환 Chat Completions의
  Gemini 3.8 Flash가 음성(input_audio)을 받아 적는다. 크레딧은 거의 호출 수로 정해지므로(호출당 약 8 + 음성 1초당 약 0.05) 말 구간을 약 25초씩 묶어 보낸다.

마이크·모델 라이브러리(sounddevice, sherpa-onnx, numpy)는 데스크톱 앱에만 들어 있다. 안드로이드처럼 없으면
available()이 이유를 돌려주고, 녹음 기능만 꺼진다.
"""
import hashlib
import io
import queue
import threading
import time
import wave

import requests

import storage

SAMPLE_RATE = 16000
NUM_THREADS = 2          # 강의 내내 돌아도 노트북이 버벅이지 않도록 스레드를 적게 쓴다
PREROLL = 0.3            # VAD가 말 첫 음절을 잘라 먹지 않도록 구간 앞에 붙이는 시간(초)
MODELS_DIR = storage.APP_DIR / "stt_models"

_HF = "https://huggingface.co"
VAD_FILES = [
    ("silero_vad.onnx", f"{_HF}/csukuangfj/vad/resolve/fba88cd2e921609e7675c3aaf51e0b9b295da4bc/silero_vad.onnx",
     1807522, "a35ebf52fd3ce5f1469b2a36158dba761bc47b973ea3382b3186ca15b1f5af28"),
]
_KO = f"{_HF}/k2-fsa/sherpa-onnx-zipformer-korean-2024-06-24/resolve/0fb4b2b5c8d3e5766121481ba911961e3649c664"
_SV = f"{_HF}/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/2365baeacb507f821a0c8120fcee3d484dba7a07"
LOCAL_MODELS = {
    "ko": {
        "label": "한국어 (가벼움, 권장)",
        "desc": "한국어 전용 Zipformer 모델(KsponSpeech 학습). 내려받기 약 76MB, 가장 가볍고 한국어가 정확합니다.",
        "kind": "transducer",
        "dir": "zipformer-ko-2024-06-24",
        "files": [
            ("encoder.int8.onnx", f"{_KO}/encoder-epoch-99-avg-1.int8.onnx", 70784728,
             "8b196d723421a0513c98ec25da2c43420c029e817f5e4a90b29ff80291c0af2b"),
            ("decoder.int8.onnx", f"{_KO}/decoder-epoch-99-avg-1.int8.onnx", 2844692,
             "2cc8c04ea080a657c18ebc59702e6b049cef08163eba5d68ac5bf707925cb0fb"),
            ("joiner.int8.onnx", f"{_KO}/joiner-epoch-99-avg-1.int8.onnx", 2581421,
             "eb654db1ea2cc9d63474855f65958b6059084692a9f2eb4f3812aceb1e416a20"),
            ("tokens.txt", f"{_KO}/tokens.txt", 60246,
             "016bdf0965029263b7ad01b742366ee542ef0bef38261510e8176ff6f2e9e668"),
        ],
    },
    "multi": {
        "label": "다국어 (영어 강의·한영 혼용)",
        "desc": "SenseVoice Small 모델. 한국어·영어·일본어·중국어를 말 구간마다 알아봅니다. 내려받기 약 240MB.",
        "kind": "sense_voice",
        "dir": "sense-voice-2024-07-17",
        "files": [
            ("model.int8.onnx", f"{_SV}/model.int8.onnx", 239233841,
             "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"),
            ("tokens.txt", f"{_SV}/tokens.txt", 315894,
             "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc"),
        ],
    },
}
DEFAULT_MODEL = "ko"
LANGUAGES = {"auto": "자동 감지", "ko": "한국어", "en": "영어"}


class SttError(Exception):
    pass


# ---- 사용할 수 있는지 ----

_available = None


def available():
    """(녹음할 수 있는지, 안 되면 이유). 마이크·인식 라이브러리를 한 번만 불러 본다."""
    global _available
    if _available is None:
        try:
            import numpy  # noqa: F401
            import sherpa_onnx  # noqa: F401
            import sounddevice  # noqa: F401  PortAudio를 불러온다
            _available = (True, "")
        except (ImportError, OSError) as e:
            _available = (False, f"이 기기의 앱에는 녹음·음성 인식 기능이 들어 있지 않습니다({type(e).__name__}).")
    return _available


def selfcheck():
    """설치된 앱 진단(--selftest): 라이브러리가 함께 묶였는지와 마이크 목록."""
    ok, reason = available()
    if not ok:
        return f"FAIL {reason}"
    import sherpa_onnx
    try:
        devices = len(input_devices())
    except Exception as e:  # CI 러너처럼 오디오 장치가 없어도 라이브러리만 있으면 된다
        devices = f"? ({type(e).__name__})"
    return f"OK (sherpa-onnx {getattr(sherpa_onnx, '__version__', '?')}, 마이크 {devices}개)"


def input_devices():
    """기본 오디오 방식(Windows는 MME 등)의 입력 장치 [{index, name}]. 같은 장치가 방식별로 겹쳐 보이지 않게 한다."""
    import sounddevice as sd
    devices = sd.query_devices()
    try:
        hostapi = sd.query_devices(kind="input")["hostapi"]
    except Exception:
        hostapi = None
    return [{"index": i, "name": d["name"]} for i, d in enumerate(devices)
            if d["max_input_channels"] > 0 and (hostapi is None or d["hostapi"] == hostapi)]


# ---- 모델 내려받기 ----

def _model_dir(key):
    return MODELS_DIR / LOCAL_MODELS[key]["dir"]


def _files_ok(directory, files):
    return all((directory / name).is_file() and (directory / name).stat().st_size == size for name, _, size, _ in files)


def vad_installed():
    return _files_ok(MODELS_DIR / "vad", VAD_FILES)


def model_installed(key):
    return key in LOCAL_MODELS and _files_ok(_model_dir(key), LOCAL_MODELS[key]["files"])


def models_status():
    return [{"key": key, "label": m["label"], "desc": m["desc"], "installed": model_installed(key),
             "size_mb": round(sum(f[2] for f in m["files"]) / 1e6)} for key, m in LOCAL_MODELS.items()]


def download(key, on_progress=None, cancelled=None):
    """key 모델(None이면 VAD만)을 내려받는다. on_progress(받은 바이트, 전체 바이트). 받은 파일은 SHA-256으로 확인한다."""
    jobs = [(MODELS_DIR / "vad", f) for f in VAD_FILES]
    if key is not None:
        if key not in LOCAL_MODELS:
            raise SttError(f"알 수 없는 모델: {key}")
        jobs += [(_model_dir(key), f) for f in LOCAL_MODELS[key]["files"]]
    jobs = [(d, f) for d, f in jobs if not _files_ok(d, [f])]
    total = sum(f[2] for _, f in jobs)
    done = 0
    for directory, (name, url, size, sha256) in jobs:
        directory.mkdir(parents=True, exist_ok=True)
        target, part = directory / name, directory / (name + ".part")
        digest = hashlib.sha256()
        try:
            with requests.get(url, stream=True, timeout=(15, 60), headers={"User-Agent": "POSTECH-GenAI-Chat"}) as r:
                if r.status_code != 200:
                    raise SttError(f"모델을 내려받지 못했습니다(HTTP {r.status_code}): {name}")
                with open(part, "wb") as out:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if cancelled and cancelled():
                            raise SttError("내려받기를 취소했습니다.")
                        out.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, total)
            if part.stat().st_size != size or digest.hexdigest() != sha256:
                raise SttError(f"내려받은 모델 파일이 손상되었습니다. 다시 시도하세요: {name}")
            part.replace(target)
        except requests.RequestException as e:
            raise SttError(f"모델을 내려받지 못했습니다(네트워크 오류): {e}") from e
        finally:
            part.unlink(missing_ok=True)


def delete_model(key):
    import shutil
    if key in LOCAL_MODELS:
        shutil.rmtree(_model_dir(key), ignore_errors=True)


# ---- 인식 엔진 ----

class LocalEngine:
    """이 기기에서 인식한다(sherpa-onnx)."""

    batch_seconds = 0  # 말 구간마다 바로 인식한다

    def __init__(self, key, language="auto"):
        import sherpa_onnx
        if not model_installed(key):
            raise SttError("로컬 음성 인식 모델을 먼저 내려받으세요.")
        m, d = LOCAL_MODELS[key], _model_dir(key)
        self.key = key
        self.kind = m["kind"]
        self.label = f"로컬 AI · {m['label']}"
        if self.kind == "transducer":
            self._rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
                joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
                num_threads=NUM_THREADS, decoding_method="greedy_search")
        else:
            self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"), num_threads=NUM_THREADS,
                use_itn=True, language=language if language in ("ko", "en") else "auto")

    def transcribe(self, samples, context=""):
        stream = self._rec.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        self._rec.decode_stream(stream)
        result = stream.result
        if self.kind == "transducer" and result.tokens:
            # 한국어 Zipformer는 result.text에서 띄어쓰기가 빠진다. 토큰에는 띄어쓰기(▁)가 남아 있다.
            return "".join(result.tokens).replace("▁", " ").strip()
        return result.text.strip()


class ServerEngine:
    """POSTECH GenAI의 OpenAI 호환 API(Gemini 3.8 Flash)로 받아 적는다."""

    batch_seconds = 25  # 호출마다 드는 크레딧을 줄이려고 말 구간을 이만큼 모아 보낸다

    def __init__(self, api_key, chat_completions_url, language="auto", hint=""):
        import api
        self._key, self._url, self.model = api_key, chat_completions_url, api.STT_MODEL
        self._language = language if language in ("ko", "en") else None
        self._hint = hint  # 강의 자료에서 뽑은 용어 등. 전문 용어를 바르게 받아 적게 돕는다
        self.label = f"POSTECH GenAI · {api.model_label(self.model)}"

    def transcribe(self, samples, context=""):
        import base64
        import api
        context = "\n".join(x for x in (self._hint[:300], context[-300:]) if x)
        try:
            return api.transcribe(self._key, self._url, base64.b64encode(wav_bytes(samples)).decode("ascii"),
                                  self._language, context=context)
        except api.ApiError as e:
            raise SttError(str(e)) from e


def wav_bytes(samples):
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


# ---- 음성 구간 나누기 ----

class Segmenter:
    """VAD로 말 구간을 끊는다. feed()는 끝난 구간 [(시작 샘플, 샘플)]을 돌려준다."""

    HISTORY = 40 * SAMPLE_RATE  # 구간 앞 PREROLL을 붙이려고 최근 소리를 남겨 둔다

    def __init__(self):
        import numpy as np
        import sherpa_onnx
        if not vad_installed():
            raise SttError("음성 구간 검출 모델을 먼저 내려받으세요.")
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(MODELS_DIR / "vad" / VAD_FILES[0][0])
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = 0.6
        cfg.silero_vad.min_speech_duration = 0.25
        cfg.silero_vad.max_speech_duration = 20
        cfg.sample_rate = SAMPLE_RATE
        cfg.num_threads = 1
        self._np = np
        self._vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
        self._hist = np.zeros(0, dtype=np.float32)
        self._hist_start = 0  # _hist[0]의 샘플 위치

    def speaking(self):
        return self._vad.is_speech_detected()

    def feed(self, samples):
        np = self._np
        self._hist = np.concatenate([self._hist, samples])
        if len(self._hist) > self.HISTORY:
            cut = len(self._hist) - self.HISTORY
            self._hist = self._hist[cut:]
            self._hist_start += cut
        self._vad.accept_waveform(samples)
        return self._collect()

    def flush(self):
        self._vad.flush()
        return self._collect()

    def _collect(self):
        out = []
        while not self._vad.empty():
            seg = self._vad.front
            samples = self._np.asarray(seg.samples, dtype=self._np.float32)
            begin = max(seg.start - int(PREROLL * SAMPLE_RATE), self._hist_start)
            end = seg.start + len(samples)
            if begin < seg.start and end <= self._hist_start + len(self._hist):
                samples = self._hist[begin - self._hist_start:end - self._hist_start]
            else:
                begin = seg.start
            out.append((begin, samples))
            self._vad.pop()
        return out


class _Resampler:
    """마이크가 16kHz를 못 열 때(48kHz 등) 16kHz로 바꾼다. 간단한 평균 필터 뒤 선형 보간."""

    def __init__(self, rate):
        import numpy as np
        self._np = np
        self._ratio = rate / SAMPLE_RATE
        self._width = max(1, int(round(self._ratio)))
        self._buf = np.zeros(0, dtype=np.float32)
        self._pos = 0.0

    def __call__(self, x):
        np = self._np
        if self._width > 1:
            x = np.convolve(x, np.ones(self._width, dtype=np.float32) / self._width, mode="same").astype(np.float32)
        buf = np.concatenate([self._buf, x])
        idx = np.arange(self._pos, len(buf) - 1, self._ratio)
        out = np.interp(idx, np.arange(len(buf)), buf).astype(np.float32)
        nxt = (idx[-1] + self._ratio) if len(idx) else self._pos
        keep = min(int(nxt), len(buf))
        self._buf, self._pos = buf[keep:], nxt - keep
        return out


# ---- 녹음 세션 ----

class LiveSession:
    """마이크 → VAD → 인식을 백그라운드 스레드로 돌린다.

    on_segment({"start", "end", "text"})는 구간마다(초 단위, offset부터), on_level(0~1, 말하는 중)은 1초에 몇 번,
    on_error(문장)는 인식에 실패했을 때 부른다. fallback 엔진이 있으면 주 엔진이 실패한 구간을 그걸로 다시 인식한다.
    """

    def __init__(self, engine, on_segment, on_level=None, on_error=None, device=None, offset=0.0, fallback=None):
        self.engine, self.fallback = engine, fallback
        self._on_segment, self._on_level, self._on_error = on_segment, on_level, on_error
        self._device, self._offset = device, float(offset)
        self._audio = queue.Queue()
        self._jobs = queue.Queue()
        self._stop = threading.Event()
        self._stream = None
        self._fed = 0  # 받은 소리(16kHz 샘플 수). 녹음 길이는 벽시계가 아니라 받은 소리로 잰다
        self._context = ""
        self._threads = []

    @property
    def elapsed(self):
        return self._fed / SAMPLE_RATE

    def start(self):
        import sounddevice as sd
        self._segmenter = Segmenter()
        device = self._device if self._device not in ("", None) else None
        try:
            self._stream, rate = self._open(sd, device, SAMPLE_RATE), SAMPLE_RATE
        except Exception:
            try:
                rate = int(sd.query_devices(device, "input")["default_samplerate"])
                self._stream = self._open(sd, device, rate)
            except Exception as e:
                raise SttError(f"마이크를 열지 못했습니다. 마이크 연결과 권한을 확인하세요: {e}") from e
        self._resample = _Resampler(rate) if rate != SAMPLE_RATE else None
        self._threads = [threading.Thread(target=self._listen, daemon=True),
                         threading.Thread(target=self._transcribe, daemon=True)]
        for t in self._threads:
            t.start()
        self._stream.start()

    def _open(self, sd, device, rate):
        return sd.InputStream(samplerate=rate, channels=1, dtype="float32", blocksize=rate // 10, device=device,
                              callback=lambda data, frames, t, status: self._audio.put(data[:, 0].copy()))

    def stop(self, timeout=120):
        """녹음을 멈추고, 남은 구간을 다 인식할 때까지(최대 timeout초) 기다린다."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stop.set()
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(max(0.1, deadline - time.monotonic()))

    def _listen(self):
        np = self._segmenter._np
        last_level = 0.0
        while True:
            try:
                block = self._audio.get(timeout=0.2)
            except queue.Empty:
                if self._stop.is_set():
                    break
                continue
            if self._resample:
                block = self._resample(block)
            self._fed += len(block)
            for begin, samples in self._segmenter.feed(block):
                self._jobs.put((begin, samples))
            now = time.monotonic()
            if self._on_level and now - last_level >= 0.15:
                last_level = now
                rms = float(np.sqrt(np.mean(block * block))) if len(block) else 0.0
                self._on_level(min(1.0, (rms * 12) ** 0.6), self._segmenter.speaking())
        for begin, samples in self._segmenter.flush():
            self._jobs.put((begin, samples))
        self._jobs.put(None)

    def _transcribe(self):
        np = self._segmenter._np
        gap = np.zeros(int(0.4 * SAMPLE_RATE), dtype=np.float32)
        done = False
        while not done:
            job = self._jobs.get()
            if job is None:
                return
            begin, parts = job[0], [job[1]]
            end = begin + len(job[1])
            batch = getattr(self.engine, "batch_seconds", 0) * SAMPLE_RATE
            # 서버 엔진은 구간을 모아 보낸다. 말이 8초 넘게 끊기거나 녹음을 멈추면 모은 만큼 보낸다.
            while batch and end - begin < batch:
                try:
                    nxt = self._jobs.get(timeout=8)
                except queue.Empty:
                    break
                if nxt is None:
                    done = True
                    break
                parts += [gap, nxt[1]]
                end = nxt[0] + len(nxt[1])
            samples = np.concatenate(parts) if len(parts) > 1 else parts[0]
            text = self._run(samples)
            if text:
                self._context = (self._context + " " + text)[-400:]
                self._on_segment({"start": round(self._offset + begin / SAMPLE_RATE, 2),
                                  "end": round(self._offset + end / SAMPLE_RATE, 2), "text": text})

    def _run(self, samples):
        for engine in (self.engine, self.fallback):
            if engine is None:
                continue
            try:
                return engine.transcribe(samples, self._context)
            except Exception as e:  # 한 구간이 실패해도 녹음은 계속한다
                if self._on_error:
                    self._on_error(f"{engine.label} 인식 실패: {e}")
        return ""
