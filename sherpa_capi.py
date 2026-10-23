# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""sherpa-onnx C API를 ctypes로 부른다. 안드로이드 앱에는 sherpa-onnx Python 패키지가 없어서, stt.py가 쓰는
sherpa_onnx의 일부(오프라인 인식기·VAD)를 같은 이름으로 흉내 낸다. 데스크톱은 pip 패키지를 그대로 쓴다.

구조체는 sherpa-onnx v1.13.8의 c-api.h에서 필드 순서와 형식을 그대로 옮겨 만들었다(아래 "생성된 구조체").
다른 버전의 라이브러리는 구조체가 달라 메모리를 망가뜨릴 수 있으므로 load()가 버전을 확인하고 거부한다.
"""
import ctypes
import os
from ctypes import POINTER, Structure, byref, c_char_p, c_float, c_int32, c_void_p

VERSION = "1.13.8"  # 아래 구조체를 만든 c-api.h의 버전
__version__ = VERSION
_lib = None


class CapiError(Exception):
    pass


# ---- 생성된 구조체: sherpa-onnx v1.13.8 sherpa-onnx/c-api/c-api.h (커밋 11afbd0) ----
# 바꾸지 말 것. 필드 하나라도 어긋나면 C 쪽이 엉뚱한 메모리를 읽는다. tests/test_sherpa_capi.py가 크기와 위치를 확인한다.

class SherpaOnnxFeatureConfig(Structure):
    _fields_ = [
        ("sample_rate", c_int32),
        ("feature_dim", c_int32),
    ]


class SherpaOnnxOfflineTransducerModelConfig(Structure):
    _fields_ = [
        ("encoder", c_char_p),
        ("decoder", c_char_p),
        ("joiner", c_char_p),
    ]


class SherpaOnnxOfflineParaformerModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineNemoEncDecCtcModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineWhisperModelConfig(Structure):
    _fields_ = [
        ("encoder", c_char_p),
        ("decoder", c_char_p),
        ("language", c_char_p),
        ("task", c_char_p),
        ("tail_paddings", c_int32),
        ("enable_token_timestamps", c_int32),
        ("enable_segment_timestamps", c_int32),
    ]


class SherpaOnnxOfflineTdnnModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineSenseVoiceModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
        ("language", c_char_p),
        ("use_itn", c_int32),
    ]


class SherpaOnnxOfflineMoonshineModelConfig(Structure):
    _fields_ = [
        ("preprocessor", c_char_p),
        ("encoder", c_char_p),
        ("uncached_decoder", c_char_p),
        ("cached_decoder", c_char_p),
        ("merged_decoder", c_char_p),
    ]


class SherpaOnnxOfflineFireRedAsrModelConfig(Structure):
    _fields_ = [
        ("encoder", c_char_p),
        ("decoder", c_char_p),
    ]


class SherpaOnnxOfflineDolphinModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineZipformerCtcModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineCanaryModelConfig(Structure):
    _fields_ = [
        ("encoder", c_char_p),
        ("decoder", c_char_p),
        ("src_lang", c_char_p),
        ("tgt_lang", c_char_p),
        ("use_pnc", c_int32),
    ]


class SherpaOnnxOfflineWenetCtcModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineOmnilingualAsrCtcModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineMedAsrCtcModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineFunASRNanoModelConfig(Structure):
    _fields_ = [
        ("encoder_adaptor", c_char_p),
        ("llm", c_char_p),
        ("embedding", c_char_p),
        ("tokenizer", c_char_p),
        ("system_prompt", c_char_p),
        ("user_prompt", c_char_p),
        ("max_new_tokens", c_int32),
        ("temperature", c_float),
        ("top_p", c_float),
        ("seed", c_int32),
        ("language", c_char_p),
        ("itn", c_int32),
        ("hotwords", c_char_p),
    ]


class SherpaOnnxOfflineFireRedAsrCtcModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
    ]


class SherpaOnnxOfflineQwen3ASRModelConfig(Structure):
    _fields_ = [
        ("conv_frontend", c_char_p),
        ("encoder", c_char_p),
        ("decoder", c_char_p),
        ("tokenizer", c_char_p),
        ("max_total_len", c_int32),
        ("max_new_tokens", c_int32),
        ("temperature", c_float),
        ("top_p", c_float),
        ("seed", c_int32),
        ("hotwords", c_char_p),
    ]


class SherpaOnnxOfflineCohereTranscribeModelConfig(Structure):
    _fields_ = [
        ("encoder", c_char_p),
        ("decoder", c_char_p),
        ("language", c_char_p),
        ("use_punct", c_int32),
        ("use_itn", c_int32),
    ]


class SherpaOnnxOfflineModelConfig(Structure):
    _fields_ = [
        ("transducer", SherpaOnnxOfflineTransducerModelConfig),
        ("paraformer", SherpaOnnxOfflineParaformerModelConfig),
        ("nemo_ctc", SherpaOnnxOfflineNemoEncDecCtcModelConfig),
        ("whisper", SherpaOnnxOfflineWhisperModelConfig),
        ("tdnn", SherpaOnnxOfflineTdnnModelConfig),
        ("tokens", c_char_p),
        ("num_threads", c_int32),
        ("debug", c_int32),
        ("provider", c_char_p),
        ("model_type", c_char_p),
        ("modeling_unit", c_char_p),
        ("bpe_vocab", c_char_p),
        ("telespeech_ctc", c_char_p),
        ("sense_voice", SherpaOnnxOfflineSenseVoiceModelConfig),
        ("moonshine", SherpaOnnxOfflineMoonshineModelConfig),
        ("fire_red_asr", SherpaOnnxOfflineFireRedAsrModelConfig),
        ("dolphin", SherpaOnnxOfflineDolphinModelConfig),
        ("zipformer_ctc", SherpaOnnxOfflineZipformerCtcModelConfig),
        ("canary", SherpaOnnxOfflineCanaryModelConfig),
        ("wenet_ctc", SherpaOnnxOfflineWenetCtcModelConfig),
        ("omnilingual", SherpaOnnxOfflineOmnilingualAsrCtcModelConfig),
        ("medasr", SherpaOnnxOfflineMedAsrCtcModelConfig),
        ("funasr_nano", SherpaOnnxOfflineFunASRNanoModelConfig),
        ("fire_red_asr_ctc", SherpaOnnxOfflineFireRedAsrCtcModelConfig),
        ("qwen3_asr", SherpaOnnxOfflineQwen3ASRModelConfig),
        ("cohere_transcribe", SherpaOnnxOfflineCohereTranscribeModelConfig),
    ]


class SherpaOnnxOfflineLMConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
        ("scale", c_float),
    ]


class SherpaOnnxHomophoneReplacerConfig(Structure):
    _fields_ = [
        ("dict_dir", c_char_p),
        ("lexicon", c_char_p),
        ("rule_fsts", c_char_p),
    ]


class SherpaOnnxOfflineRecognizerConfig(Structure):
    _fields_ = [
        ("feat_config", SherpaOnnxFeatureConfig),
        ("model_config", SherpaOnnxOfflineModelConfig),
        ("lm_config", SherpaOnnxOfflineLMConfig),
        ("decoding_method", c_char_p),
        ("max_active_paths", c_int32),
        ("hotwords_file", c_char_p),
        ("hotwords_score", c_float),
        ("rule_fsts", c_char_p),
        ("rule_fars", c_char_p),
        ("blank_penalty", c_float),
        ("hr", SherpaOnnxHomophoneReplacerConfig),
    ]


class SherpaOnnxOfflineRecognizerResult(Structure):
    _fields_ = [
        ("text", c_char_p),
        ("timestamps", POINTER(c_float)),
        ("count", c_int32),
        ("tokens", c_char_p),
        ("tokens_arr", POINTER(c_char_p)),
        ("json", c_char_p),
        ("lang", c_char_p),
        ("emotion", c_char_p),
        ("event", c_char_p),
        ("durations", POINTER(c_float)),
        ("ys_log_probs", POINTER(c_float)),
        ("segment_timestamps", POINTER(c_float)),
        ("segment_durations", POINTER(c_float)),
        ("segment_texts", c_char_p),
        ("segment_texts_arr", POINTER(c_char_p)),
        ("segment_count", c_int32),
    ]


class SherpaOnnxSileroVadModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
        ("threshold", c_float),
        ("min_silence_duration", c_float),
        ("min_speech_duration", c_float),
        ("window_size", c_int32),
        ("max_speech_duration", c_float),
    ]


class SherpaOnnxTenVadModelConfig(Structure):
    _fields_ = [
        ("model", c_char_p),
        ("threshold", c_float),
        ("min_silence_duration", c_float),
        ("min_speech_duration", c_float),
        ("window_size", c_int32),
        ("max_speech_duration", c_float),
    ]


class SherpaOnnxVadModelConfig(Structure):
    _fields_ = [
        ("silero_vad", SherpaOnnxSileroVadModelConfig),
        ("sample_rate", c_int32),
        ("num_threads", c_int32),
        ("provider", c_char_p),
        ("debug", c_int32),
        ("ten_vad", SherpaOnnxTenVadModelConfig),
    ]


class SherpaOnnxSpeechSegment(Structure):
    _fields_ = [
        ("start", c_int32),
        ("samples", POINTER(c_float)),
        ("n", c_int32),
    ]


# ---- 라이브러리 ----

def load(path=None):
    """libsherpa-onnx-c-api를 불러 함수 형식을 정한다. 버전이 다르면 CapiError."""
    global _lib
    if _lib is not None:
        return _lib
    candidates = [path] if path else []
    if os.environ.get("SHERPA_ONNX_CAPI"):
        candidates.append(os.environ["SHERPA_ONNX_CAPI"])
    candidates += ["libsherpa-onnx-c-api.so", "libsherpa-onnx-c-api.dylib", "sherpa-onnx-c-api.dll"]
    errors = []
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError as e:
            errors.append(f"{name}: {e}")
    else:
        raise CapiError("sherpa-onnx C API를 불러오지 못했습니다: " + "; ".join(errors))
    lib.SherpaOnnxGetVersionStr.restype = c_char_p
    version = lib.SherpaOnnxGetVersionStr().decode()
    if version != VERSION:
        raise CapiError(f"sherpa-onnx C API 버전이 맞지 않습니다({version}, 필요: {VERSION}).")
    sig = {
        "SherpaOnnxCreateOfflineRecognizer": (c_void_p, [POINTER(SherpaOnnxOfflineRecognizerConfig)]),
        "SherpaOnnxDestroyOfflineRecognizer": (None, [c_void_p]),
        "SherpaOnnxCreateOfflineStream": (c_void_p, [c_void_p]),
        "SherpaOnnxDestroyOfflineStream": (None, [c_void_p]),
        "SherpaOnnxAcceptWaveformOffline": (None, [c_void_p, c_int32, POINTER(c_float), c_int32]),
        "SherpaOnnxDecodeOfflineStream": (None, [c_void_p, c_void_p]),
        "SherpaOnnxGetOfflineStreamResult": (POINTER(SherpaOnnxOfflineRecognizerResult), [c_void_p]),
        "SherpaOnnxDestroyOfflineRecognizerResult": (None, [POINTER(SherpaOnnxOfflineRecognizerResult)]),
        "SherpaOnnxCreateVoiceActivityDetector": (c_void_p, [POINTER(SherpaOnnxVadModelConfig), c_float]),
        "SherpaOnnxDestroyVoiceActivityDetector": (None, [c_void_p]),
        "SherpaOnnxVoiceActivityDetectorAcceptWaveform": (None, [c_void_p, POINTER(c_float), c_int32]),
        "SherpaOnnxVoiceActivityDetectorEmpty": (c_int32, [c_void_p]),
        "SherpaOnnxVoiceActivityDetectorDetected": (c_int32, [c_void_p]),
        "SherpaOnnxVoiceActivityDetectorPop": (None, [c_void_p]),
        "SherpaOnnxVoiceActivityDetectorFront": (POINTER(SherpaOnnxSpeechSegment), [c_void_p]),
        "SherpaOnnxDestroySpeechSegment": (None, [POINTER(SherpaOnnxSpeechSegment)]),
        "SherpaOnnxVoiceActivityDetectorFlush": (None, [c_void_p]),
    }
    for name, (restype, argtypes) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = restype, argtypes
    _lib = lib
    return lib


def _floats(samples):
    """samples(numpy float32 배열 또는 float 목록)를 C float 배열로. numpy 배열은 복사하지 않는다."""
    try:
        import numpy as np
        arr = np.ascontiguousarray(samples, dtype=np.float32)
        return arr, arr.ctypes.data_as(POINTER(c_float)), len(arr)
    except ImportError:
        arr = (c_float * len(samples))(*samples)
        return arr, arr, len(samples)


def _b(value):
    return value.encode() if isinstance(value, str) else value


# ---- sherpa_onnx와 같은 이름의 오프라인 인식기 ----

class _Result:
    def __init__(self, text, tokens, ys_log_probs, lang):
        self.text, self.tokens, self.ys_log_probs, self.lang = text, tokens, ys_log_probs, lang


class OfflineStream:
    def __init__(self, recognizer):
        self._lib = recognizer._lib
        self._ptr = self._lib.SherpaOnnxCreateOfflineStream(recognizer._ptr)
        if not self._ptr:
            raise CapiError("인식 스트림을 만들지 못했습니다.")
        self.result = None

    def accept_waveform(self, sample_rate, samples):
        keep, ptr, n = _floats(samples)
        self._lib.SherpaOnnxAcceptWaveformOffline(self._ptr, int(sample_rate), ptr, n)
        del keep

    def _read(self):
        r = self._lib.SherpaOnnxGetOfflineStreamResult(self._ptr)
        if not r:
            return _Result("", [], [], "")
        try:
            res = r.contents
            n = max(0, res.count)
            tokens = [res.tokens_arr[i].decode("utf-8", "replace") for i in range(n)] if res.tokens_arr else []
            probs = [res.ys_log_probs[i] for i in range(n)] if res.ys_log_probs else []
            text = res.text.decode("utf-8", "replace") if res.text else ""
            lang = res.lang.decode("utf-8", "replace") if res.lang else ""
            return _Result(text, tokens, probs, lang)
        finally:
            self._lib.SherpaOnnxDestroyOfflineRecognizerResult(r)

    def __del__(self):
        if getattr(self, "_ptr", None):
            self._lib.SherpaOnnxDestroyOfflineStream(self._ptr)
            self._ptr = None


class OfflineRecognizer:
    def __init__(self, config):
        self._lib = load()
        self._config = config  # 문자열 버퍼가 만들 때까지 살아 있도록 붙잡아 둔다
        self._ptr = self._lib.SherpaOnnxCreateOfflineRecognizer(byref(config))
        if not self._ptr:
            raise CapiError("음성 인식기를 만들지 못했습니다(모델 파일을 확인하세요).")

    @classmethod
    def from_transducer(cls, encoder, decoder, joiner, tokens, num_threads=1, decoding_method="greedy_search",
                        sample_rate=16000, feature_dim=80, provider="cpu"):
        c = SherpaOnnxOfflineRecognizerConfig()
        c.feat_config.sample_rate, c.feat_config.feature_dim = sample_rate, feature_dim
        t = c.model_config.transducer
        t.encoder, t.decoder, t.joiner = _b(encoder), _b(decoder), _b(joiner)
        c.model_config.tokens, c.model_config.num_threads = _b(tokens), int(num_threads)
        c.model_config.provider, c.decoding_method = _b(provider), _b(decoding_method)
        return cls(c)

    @classmethod
    def from_sense_voice(cls, model, tokens, num_threads=1, use_itn=False, language="", provider="cpu",
                         sample_rate=16000, feature_dim=80):
        c = SherpaOnnxOfflineRecognizerConfig()
        c.feat_config.sample_rate, c.feat_config.feature_dim = sample_rate, feature_dim
        sv = c.model_config.sense_voice
        sv.model, sv.language, sv.use_itn = _b(model), _b(language or ""), 1 if use_itn else 0
        c.model_config.tokens, c.model_config.num_threads = _b(tokens), int(num_threads)
        c.model_config.provider, c.decoding_method = _b(provider), b"greedy_search"
        return cls(c)

    def create_stream(self):
        return OfflineStream(self)

    def decode_stream(self, stream):
        self._lib.SherpaOnnxDecodeOfflineStream(self._ptr, stream._ptr)
        stream.result = stream._read()

    def __del__(self):
        if getattr(self, "_ptr", None):
            self._lib.SherpaOnnxDestroyOfflineRecognizer(self._ptr)
            self._ptr = None


# ---- sherpa_onnx와 같은 이름의 VAD ----

class _SileroConfig:
    def __init__(self):
        self.model, self.threshold, self.window_size = "", 0.5, 512
        self.min_silence_duration, self.min_speech_duration, self.max_speech_duration = 0.5, 0.25, 20.0


class VadModelConfig:
    def __init__(self):
        self.silero_vad = _SileroConfig()
        self.sample_rate, self.num_threads, self.provider = 16000, 1, "cpu"


class _Segment:
    def __init__(self, start, samples):
        self.start, self.samples = start, samples


class VoiceActivityDetector:
    def __init__(self, config, buffer_size_in_seconds=60):
        self._lib = load()
        c = SherpaOnnxVadModelConfig()
        s = config.silero_vad
        c.silero_vad.model = _b(s.model)
        c.silero_vad.threshold, c.silero_vad.window_size = float(s.threshold), int(s.window_size)
        c.silero_vad.min_silence_duration = float(s.min_silence_duration)
        c.silero_vad.min_speech_duration = float(s.min_speech_duration)
        c.silero_vad.max_speech_duration = float(s.max_speech_duration)
        c.sample_rate, c.num_threads, c.provider = int(config.sample_rate), int(config.num_threads), _b(config.provider)
        self._config = c
        self._ptr = self._lib.SherpaOnnxCreateVoiceActivityDetector(byref(c), float(buffer_size_in_seconds))
        if not self._ptr:
            raise CapiError("음성 구간 검출기를 만들지 못했습니다(모델 파일을 확인하세요).")

    def accept_waveform(self, samples):
        keep, ptr, n = _floats(samples)
        self._lib.SherpaOnnxVoiceActivityDetectorAcceptWaveform(self._ptr, ptr, n)
        del keep

    def empty(self):
        return bool(self._lib.SherpaOnnxVoiceActivityDetectorEmpty(self._ptr))

    def is_speech_detected(self):
        return bool(self._lib.SherpaOnnxVoiceActivityDetectorDetected(self._ptr))

    @property
    def front(self):
        seg = self._lib.SherpaOnnxVoiceActivityDetectorFront(self._ptr)
        if not seg:
            raise CapiError("음성 구간이 없습니다.")
        try:
            s = seg.contents
            try:
                import numpy as np
                samples = np.ctypeslib.as_array(s.samples, shape=(s.n,)).copy() if s.n else np.zeros(0, np.float32)
            except ImportError:
                samples = [s.samples[i] for i in range(s.n)]
            return _Segment(int(s.start), samples)
        finally:
            self._lib.SherpaOnnxDestroySpeechSegment(seg)

    def pop(self):
        self._lib.SherpaOnnxVoiceActivityDetectorPop(self._ptr)

    def flush(self):
        self._lib.SherpaOnnxVoiceActivityDetectorFlush(self._ptr)

    def __del__(self):
        if getattr(self, "_ptr", None):
            self._lib.SherpaOnnxDestroyVoiceActivityDetector(self._ptr)
            self._ptr = None
