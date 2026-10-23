"""sherpa_capi(안드로이드에서 쓰는 sherpa-onnx C API 바인딩) 시험.

구조체 크기·필드 위치는 언제나 확인한다. 모델과 시험 음성이 있으면(POSCHAT_TEST_MODELS, tests/fetch_test_models.py)
pip 패키지와 같은 결과를 내는지, 안드로이드 앱의 녹음 경로(android_main → stt.LiveSession → sherpa_capi)를
이 컴퓨터에서 그대로 돌려 정확도와 속도도 확인한다. 휴대폰(에뮬레이터)에서는 SttBenchmarkTest가 같은 측정을 한다.
"""
import json
import os
import subprocess
import sys
import unittest
from ctypes import sizeof
from pathlib import Path

import sherpa_capi

HERE = Path(__file__).resolve().parent
ANDROID_PY = HERE.parent / "android" / "app" / "src" / "main" / "python"
MODELS = os.environ.get("POSCHAT_TEST_MODELS")
sys.path.insert(0, str(ANDROID_PY))
from po_bench import cer  # noqa: E402

# 안드로이드 앱처럼: android_main._setup(sounddevice 대신 객체, sherpa_onnx 패키지 없음) 뒤 po_bench로 잰다
ANDROID_PATH = """
import json, sys, tempfile
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import android_main, po_bench
files = tempfile.mkdtemp()
android_main._setup(files, files)
import stt
stt.MODELS_DIR = Path(sys.argv[3]) / "stt_models"
print(json.dumps(po_bench.run(Path(sys.argv[3]) / "test_wavs"), ensure_ascii=False))
"""


def capi_library():
    try:
        import sherpa_onnx
    except ImportError:
        return None
    lib = Path(sherpa_onnx.__file__).parent / "lib"
    for name in ("libsherpa-onnx-c-api.so", "libsherpa-onnx-c-api.dylib", "sherpa-onnx-c-api.dll"):
        if (lib / name).is_file():
            return lib / name
    return None


def worker(mode, *extra):
    env = dict(os.environ, SHERPA_ONNX_CAPI=str(capi_library()))
    out = subprocess.run([sys.executable, str(HERE / "_stt_worker.py"), mode, MODELS, *extra],
                         capture_output=True, text=True, env=env, timeout=600)
    if out.returncode:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout)


class LayoutTests(unittest.TestCase):
    def test_structs_match_the_c_header(self):
        # tests/data/sherpa_capi_layout.txt는 v1.13.8 c-api.h를 C 컴파일러로 컴파일해 sizeof·offsetof를 찍은 값이다.
        checked = 0
        for line in (HERE / "data" / "sherpa_capi_layout.txt").read_text().splitlines():
            key, value = line.split()
            if "." in key:
                struct, field = key.split(".")
                got = getattr(getattr(sherpa_capi, struct), field).offset
            else:
                got = sizeof(getattr(sherpa_capi, key))
            self.assertEqual(got, int(value), key)
            checked += 1
        self.assertGreater(checked, 150)


@unittest.skipUnless(MODELS and capi_library(), "POSCHAT_TEST_MODELS와 sherpa-onnx pip 패키지가 있어야 합니다")
class BackendTests(unittest.TestCase):
    def test_c_api_binding_gives_the_same_results_as_the_python_package(self):
        pip, capi = worker("pip"), worker("capi")
        self.assertEqual((pip["backend"], capi["backend"]), ("sherpa_onnx", "sherpa_capi"))
        for name in ("0.wav", "1.wav", "2.wav", "3.wav", "vad"):
            self.assertEqual(capi[name], pip[name], name)
        refs = dict(line.split(" ", 1) for line in (Path(MODELS) / "test_wavs" / "trans.txt").read_text(encoding="utf-8").splitlines() if line.strip())
        for name, ref in refs.items():
            self.assertLess(cer(ref, capi[name]["text"]), 0.05, (ref, capi[name]))
            self.assertGreater(capi[name]["conf"], 0.8)  # 깨끗한 음성은 하이브리드에서 서버로 보내지 않는다

    def test_android_recording_path(self):
        env = dict(os.environ, SHERPA_ONNX_CAPI=str(capi_library()))
        out = subprocess.run([sys.executable, "-c", ANDROID_PATH, str(ANDROID_PY), str(HERE.parent), MODELS],
                             capture_output=True, text=True, env=env, timeout=600)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        report = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(report["backend"], "sherpa_capi")
        pipe = report["pipeline"]
        self.assertEqual(len(pipe["segments"]), 4, pipe)
        self.assertLess(pipe["cer"], 0.05, pipe)
        self.assertEqual(pipe["errors"], [])
        print(f"\n  안드로이드 녹음 경로(이 컴퓨터): 음성 {pipe['audio_seconds']:.1f}초를 {pipe['seconds']:.2f}초에 처리"
              f" (RTF {pipe['rtf']:.3f}), 최대 메모리 {report['peak_rss_mb']}MB")
        self.assertLess(pipe["rtf"], 1.0)  # 실시간보다 빨라야 녹음이 밀리지 않는다


if __name__ == "__main__":
    unittest.main()
