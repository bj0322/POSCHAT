# 인수인계 메모: v1.10.0 안드로이드 PO노트 녹음 (임시)

> **v1.10.0을 출시하는 PR에서 이 파일(`CLAUDE.md`)과 `handoff/` 폴더를 지운다.**
> 작성: 2026-10-23. 작업 브랜치 `claude/bold-ritchie-x45m6j`, PR https://github.com/bj0322/POSCHAT/pull/14 (열림, 머지 안 함).

## 목표
안드로이드 앱에서 PO노트 녹음을 지원한다. 방식은 데스크톱과 같은 하이브리드다.
휴대폰의 로컬 AI(sherpa-onnx)가 바로 받아 적고, 로컬 신뢰도가 0.8보다 낮은 구간이 든 약 2분 묶음만 POSTECH GenAI가 보정한다.
사용자는 "성능도 확실히 테스트되면 좋겠다"고 했다. 정 안 되면 안드로이드 녹음은 v1.10에서 빼도 된다고 했다.

## 지금 상태 (PR #14, 커밋 fd9f509)
구현이 끝난 것:
- `sherpa_capi.py`: sherpa-onnx 1.13.8의 C API를 ctypes로 묶은 것이다.
  - sherpa-onnx Kotlin API는 토큰 확률(`ys_log_probs`)을 주지 않는다. 하이브리드에 신뢰도가 필요해서 C API를 쓴다.
  - 구조체 배치 171개를 C 헤더와 맞춰 확인했다(`tests/data/sherpa_capi_layout.txt`).
  - pip 패키지와 결과(글·신뢰도·VAD 구간)가 같다.
- `stt.sherpa()`: pip `sherpa_onnx`가 있으면 그것을, 없으면 `sherpa_capi`를 쓴다.
  - `LiveSession.start`는 같은 빠르기(16kHz)로 마이크를 다시 열지 않는다.
- `android/app/build.gradle.kts`:
  - 공식 AAR(v1.13.8, SHA-256 고정)을 받아 `libsherpa-onnx-c-api.so`와 `libonnxruntime.so`만 jniLibs에 넣는다.
  - `sherpa_capi.py`를 동기화 목록에 넣었다. `requirements-android.txt`에 numpy를 넣었다.
- `RecordingService.kt`(마이크 포그라운드 서비스):
  - 16kHz PCM16을 0.1초씩 읽어 `android_main.mic_block`으로 넘긴다.
  - 알림의 "녹음 중지"는 `po_stop`을 부른다. 웨이크락을 잡는다.
- `MainActivity.Host.micStart()/micStop()`: 마이크·알림 권한을 요청하고 서비스를 시작한다.
- `android_main.py`:
  - `sounddevice` 대신 객체(`_InputStream`)를 쓴다. 만들 때 `host.micStart()`를 부른다.
  - `sherpa_onnx=None`으로 두어 `sherpa_capi`를 쓰게 한다.
  - `mic_block`, `mic_error`, `mic_stats`가 있다. selftest에 `stt` 항목을 넣었다.
- `android/app/src/main/python/po_bench.py`:
  - 시험 음성 4개로 인식 CER·RTF를 잰다.
  - 휴대폰 녹음 경로(mic_block → LiveSession)로도 잰다.
  - `tests/fetch_test_models.py`와 `tests/test_sherpa_capi.py`가 이것을 같이 쓴다.
- 계측 테스트 `PoNoteRecordingTest.kt`:
  - a: po_bench로 정확도와 속도를 잰다. logcat 태그는 `PoschatBench`다.
  - b: 녹음 서비스가 마이크 블록을 넘기는지 본다.
  - c: 브리지에서 `po_start`·`po_stop`을 부른다.
- CI(`build.yml`):
  - tests 작업이 시험 모델을 받아 `POSCHAT_TEST_MODELS`로 돌린다.
  - 에뮬레이터 옵션에서 `-noaudio`를 뺐다. 가상 마이크가 필요하기 때문이다.
  - 성공하면 logcat `PoschatBench`를 출력한다.
- `requirements.txt`: `sherpa-onnx==1.13.8`로 고정했다.
  - 2026-10-23에 2.0.0이 나왔다. 2.0.0도 같은 결과를 냈지만, 안드로이드 C 라이브러리와 버전을 맞춘다.
  - 버전을 올릴 때는 세 곳을 함께 올린다: requirements.txt, build.gradle.kts의 `sherpaVersion`과 SHA-256, `sherpa_capi.VERSION`.
- 버전 1.10.0. README, 앱 가이드(web/app.js), THIRD_PARTY_NOTICES를 고쳤다.

CI 결과: tests, windows, macos는 통과했다. **android는 실패했다. 아래 1번이 원인이다.**

## 할 일 (순서대로)

### 1. android CI 빌드 실패 고치기
`build.gradle.kts`에서 `java.security.MessageDigest`와 `java.net.URI`를 전체 이름으로 쓴 곳이 컴파일되지 않는다.
Kotlin DSL 안에서는 `java`가 Gradle의 `java {}` 확장으로 풀려 `Unresolved reference: security`가 난다.
파일 맨 위에 `import java.net.URI`와 `import java.security.MessageDigest`를 넣고, 본문에서는 짧은 이름을 쓴다.
이 컨테이너에는 Android SDK가 없어서 로컬에서 빌드할 수 없다. 확인은 CI 에뮬레이터로 한다.
빌드가 되면 다음을 확인한다:
- 안드로이드에서 맨 이름(`ctypes.CDLL("libsherpa-onnx-c-api.so")`)으로 라이브러리가 열리는지. 안 열리면 Kotlin에서 `System.loadLibrary("sherpa-onnx-c-api")`로 먼저 올리는 방안이 있다.
- 에뮬레이터 가상 마이크로 AudioRecord가 열리는지(테스트 b, c).
- numpy가 Chaquopy 3.11에서 설치되는지.

### 2. 로컬 한국어 모델의 정확도 문제 (중요, 데스크톱 v1.9에도 해당)
지금까지 쓴 시험 음성 4개(모델 저장소 것)로는 오류가 0이었다. 독립 데이터로 재 보니 결과가 크게 달랐다.
`handoff/asr_eval.py`로 다시 잴 수 있다.

| 로컬 모델 | Zeroth-Korean test (115문장 표본) | FLEURS ko dev (숫자 없는 176개) |
|---|---|---|
| 한국어 Zipformer (지금 기본, `ko`) | CER 33% | CER 51%, 그중 71개는 빈 결과 |
| 다국어 SenseVoice (`multi`) | CER 1.8% | CER 5.0% |

- **원인 1: 한국어 Zipformer는 작은 소리에 빈 결과를 낸다.** FLEURS 녹음은 최고점이 약 0.02다. 소리 크기를 맞추면 대부분 제대로 나온다.
  - 10개 표본: FLEURS CER이 0.33에서 0.11로 내려갔다(`rms0.05_up`).
  - 강의실 뒤쪽에서 녹음하거나, 안드로이드 `VOICE_RECOGNITION` 입력(자동 음량 없음)을 쓰면 바로 이 상황이 된다.
  - 할 일: `stt.LocalEngine.recognize`(또는 Segmenter가 낸 구간)에 소리 크기 맞춤을 넣는다.
  - 후보는 `asr_eval.py`의 `rms_up`이다: RMS를 0.05로 맞추되 키우기만 하고, 최대 30배, 잘림을 막는다.
  - 전체 데이터로 방식을 비교한 뒤 정하고, 단위 테스트를 단다.
- **원인 2: Zipformer(KsponSpeech 대화체로 학습)가 낭독 뉴스 같은 음성에서 약하다.** Zeroth는 소리를 키워도 그대로 약 35%였다.
  - SenseVoice가 Zeroth나 FLEURS로 학습했을 수 있다. 수치를 그대로 믿지 않는다.
  - 실제 강의 음성으로 확인하는 것이 가장 좋다. 사용자에게 녹음 표본을 받을 수 있는지 물어본다.
- **신뢰도 문턱 0.8은 생각보다 약하다.** 0.8 이상인 줄도 CER이 13~17%였다(Zeroth, FLEURS).
  - README의 "0.8 이상은 오류율이 거의 0%" 문장은 시험 음성 4개로 잰 것이라 틀렸다. 고친다.
  - 하이브리드의 서버 보정 상한(1시간 약 420크레딧)은 그대로다. 실제로는 대부분의 묶음이 보정된다.
- 정할 것: 기본 로컬 모델을 SenseVoice로 바꿀지.
  - 내려받기가 76MB에서 240MB로 늘고, RTF가 0.02에서 0.05로 느려진다. 그래도 충분히 빠르다.
  - SenseVoice는 신뢰도를 내지 않는다. 하이브리드에서는 모든 묶음을 보정하므로 늘 상한 크레딧을 쓴다.
  - 대안으로 Zipformer와 소리 크기 맞춤을 함께 쓰는 방안이 있다. 실측으로 비교해 사용자에게 권고와 함께 묻는다.
- 잡음 내성(Zeroth, 흰 잡음, Zipformer, 소리 크기 맞춤 전):

  | 조건 | CER |
  |---|---|
  | 깨끗한 음성 | 35% |
  | SNR 20dB | 34% |
  | SNR 10dB | 55% |
  | SNR 5dB | 72% |

### 3. 하이브리드 실측 (선택)
실제 POSTECH API 키로 짧게(약 10분 분량, 100크레딧 이하) 돌려, 보정 전후 CER과 실제 크레딧을 잰다.
키는 저장소나 파일에 절대 넣지 않는다. 사용자에게 받아 환경 변수로만 쓴다.

### 4. 출시
1. CI가 모두 초록인지 확인한다.
2. logcat `PoschatBench` 수치(에뮬레이터라 실제 휴대폰 성능은 아님)를 PR과 사용자에게 보고한다.
3. README의 정확도 문장을 고친다.
4. 이 파일과 `handoff/`를 지운다.
5. 머지 커밋으로 PR을 머지한다.
6. `build.yml`을 workflow_dispatch로 돌린다(ref main, 입력 `release: v1.10.0`).
7. Releases에 세 파일이 있는지 확인한다.

## 참고
- 이 저장소의 커밋·PR 문장은 한국어로 쓴다. 코드 주석도 주변 코드처럼 한국어로 쓴다.
- 데스크톱 테스트: `python -m unittest discover -s tests`.
  - 모델이 필요한 테스트는 `python tests/fetch_test_models.py <폴더>` 뒤에 `POSCHAT_TEST_MODELS=<폴더>`로 돌린다.
- sherpa-onnx pip 패키지를 숨기고 C API로 돌리려면 `SHERPA_ONNX_CAPI=<pip 패키지의 lib/libsherpa-onnx-c-api.so>`를 쓴다.
  - 테스트(`tests/test_sherpa_capi.py`)는 이렇게 안드로이드 녹음 경로를 Linux에서 재현한다.
- v1.9.2는 출시되어 있다. 1.9.1 앱이 자동 업데이트로 1.9.2를 찾는 것까지 확인했다.
