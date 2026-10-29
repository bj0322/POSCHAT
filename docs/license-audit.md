# 라이선스 감사 (AGPL-3.0-only 전환, v1.10.0)

작성: 2026-10-23. 이 문서는 개발자의 점검 기록이며 법률 자문이 아닙니다.
자동 점검(`tools/license_check.py`, CI의 `license` 작업)은 사람이 검토할 재료를 만들 뿐, 법적 호환성을 확정하지 않습니다.

## 1. 전환 전 상태

- **LICENSE**: MIT, Copyright (c) 2026 Beomjoon Kim.
  - 커밋 `b0bacc5`(2026-10-18)에서 처음 들어왔습니다.
  - 그 앞의 커밋에는 LICENSE가 없었습니다(v1.1.0 소스 스냅샷).
- **MIT로 배포된 태그**: v1.2.0, v1.3.0, v1.3.1, v1.4.0, v1.5.0, v1.6.0, v1.7.0, v1.7.1, v1.8.0, v1.8.2, v1.9.0, v1.9.1, v1.9.2.
  - 각 태그의 Release에 Windows 설치 파일, macOS DMG, Android APK가 있습니다.
- **README**: "MIT License" 절이 있었고, 소스 파일에는 저작권·SPDX 머리말이 없었습니다.
- **제3자 파일**: `web/vendor/`(marked, DOMPurify, KaTeX, PDF.js)와 그 원문(`licenses/`), `THIRD_PARTY_NOTICES.md`.
- **배포**:
  - Windows·macOS: `build_installer.py`(PyInstaller)가 앱에 `LICENSE`·`THIRD_PARTY_NOTICES.md`·`licenses/`를 넣었습니다.
  - Android: `android/app/build.gradle.kts`가 같은 파일을 APK assets에 넣었습니다.
  - 앱 화면에는 라이선스 표시가 없었습니다.
- **다른 기여자**: MIT 시기에 다른 기여자의 커밋이 있습니다(`b807f38`, `b5451df`, PR #8). MIT는 이 코드를 AGPL 저작물에 넣어 배포하는 것을 허용합니다. 저작권 표시는 해당 기여자에게 남습니다(LICENSE_HISTORY.md).

## 2. 전환 내용

- **적용 시작**: 커밋 `3edf859`(2026-10-23, "chore(license): license new versions under AGPL-3.0-only").
  - 첫 공식 배포본은 **v1.10.0**입니다.
- **LICENSE**: https://www.gnu.org/licenses/agpl-3.0.txt 원문을 그대로 넣었습니다.
  - SHA-256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`이고, CI가 확인합니다.
  - 추가 조건·금지 조항은 없습니다. "or later"는 쓰지 않습니다(`AGPL-3.0-only`).
- **프로젝트 소스 머리말**: `SPDX-FileCopyrightText: 2026 Beomjoon Kim`과 `SPDX-License-Identifier: AGPL-3.0-only`를 넣었습니다.
  - 대상: Python, JS, CSS, HTML, Kotlin, Gradle, bat, workflow.
  - shebang·`@echo off`·doctype 다음 줄에 둡니다.
  - 제3자 파일(`web/vendor/`, `licenses/`, Gradle wrapper)에는 넣지 않습니다.
- **과거 MIT 배포본**: 권리를 철회하지 않습니다(README, LICENSE_HISTORY.md).

## 3. 의존성과 호환성

판단 기준은 AGPL-3.0-only 저작물과 함께 배포할 수 있는지입니다.
MIT, BSD, ISC, Apache-2.0, MPL-2.0, PSF, Zlib, CC0, 0BSD는 GPLv3/AGPLv3와 함께 배포할 수 있다고 FSF가 밝힌 라이선스입니다.
- Apache-2.0은 GPLv3 계열과 호환되고, GPLv2와는 호환되지 않습니다.
- MPL-2.0은 §3.3 "Secondary License" 조항으로 GPL 계열과 함께 쓸 수 있습니다. certifi에는 "Incompatible With Secondary Licenses" 표시가 없습니다.

표의 "고지" 열은 배포본에 그 저작권·라이선스 고지를 함께 실어야 하는지를 뜻합니다.
`THIRD_PARTY_NOTICES.md`와 `licenses/`가 이 고지를 담고, 앱의 **설정 → 제3자 라이선스**에서 볼 수 있습니다.

### 앱 화면(번들 JavaScript)
| 구성 요소 | 버전 | 라이선스 | 번들 | 호환 | 고지 |
|---|---|---|---|---|---|
| marked | 12.0.2 | MIT(+ Markdown BSD 고지) | 예 | 예 | 예(`licenses/marked-LICENSE.md`) |
| DOMPurify | 3.1.6 | Apache-2.0 OR MPL-2.0 | 예 | 예 | 예(`licenses/DOMPurify-LICENSE.txt`) |
| KaTeX(+ 글꼴) | 0.16.22 | MIT | 예 | 예 | 예(`licenses/KaTeX-LICENSE.txt`) |

### 데스크톱 앱(Windows·macOS, PyInstaller가 묶는 Python 패키지)
CI가 `python tools/license_check.py deps`로 설치된 버전의 메타데이터 목록을 만들어 작업 결과물(`dependency-licenses.md`)로 올립니다. 아래는 2026-10-23 기준입니다.

| 패키지 | 라이선스 | 번들 | 호환 | 고지 |
|---|---|---|---|---|
| CPython 런타임(OpenSSL 3, libffi, SQLite 등 포함) | PSF-2.0(OpenSSL 3: Apache-2.0) | 예 | 예 | 예 |
| requests, urllib3, charset-normalizer, idna, certifi | Apache-2.0, MIT, MIT, BSD-3-Clause, MPL-2.0 | 예 | 예 | 예 |
| truststore | MIT | 예 | 예 | 예 |
| cryptography, cffi, pycparser | Apache-2.0 OR BSD-3-Clause, MIT-0, BSD-3-Clause | 예 | 예 | 예 |
| keyring, jaraco.*, more-itertools(+ Linux: SecretStorage, jeepney) | MIT, BSD-3-Clause | 예 | 예 | 예 |
| pywebview, bottle, proxy_tools | BSD-3-Clause, MIT, MIT | 예 | 예 | 예 |
| pythonnet, clr_loader(Windows의 pywebview) | MIT | 예 | 예 | 예 |
| pyobjc(macOS의 pywebview) | MIT | 예 | 예 | 예 |
| pypdf, olefile, openpyxl, et-xmlfile | BSD-3-Clause, BSD-2-Clause, MIT, MIT | 예 | 예 | 예 |
| python-docx, python-pptx, lxml, Pillow, XlsxWriter, typing_extensions | MIT, MIT, BSD-3-Clause, MIT-CMU, BSD-2-Clause, PSF-2.0 | 예 | 예 | 예 |
| numpy | BSD-3-Clause(+ 0BSD, MIT, Zlib, CC0 일부) | 예 | 예 | 예 |
| sounddevice + PortAudio | MIT + MIT 계열 | 예 | 예 | 예 |
| sherpa-onnx 1.13.8 + ONNX Runtime | Apache-2.0 + MIT | 예 | 예 | 예 |
| PyInstaller 부트로더 | GPL-2.0-or-later + 부트로더 예외 | 예(실행 파일) | 예(예외 조항이 어떤 라이선스의 프로그램에도 쓰도록 허용) | 아니요 |
| Tcl/Tk(설치 프로그램 화면) | Tcl/Tk 라이선스(BSD 계열) | 설치 프로그램만 | 예 | 예 |
| comtypes(설치 프로그램 바로가기) | MIT | 설치 프로그램만 | 예 | 예 |

### Android 앱(APK)
| 구성 요소 | 라이선스 | 번들 | 호환 | 고지 |
|---|---|---|---|---|
| Chaquopy 런타임 + CPython 3.11 | MIT + PSF-2.0 | 예 | 예 | 예 |
| 위 Python 패키지 중 안드로이드용(requests, certifi, pypdf, olefile, openpyxl, python-docx, python-pptx, lxml, Pillow, numpy, cryptography 42.0.8) | 위와 같음 | 예 | 예 | 예 |
| `libsherpa-onnx-c-api.so`, `libonnxruntime.so`(sherpa-onnx 1.13.8 공식 AAR에서 그대로) | Apache-2.0, MIT | 예 | 예 | 예 |
| AndroidX(core-ktx, activity-ktx, webkit), Kotlin 표준 라이브러리 | Apache-2.0 | 예 | 예 | 예 |
| Android 시스템 WebView, AudioRecord 등 | 기기의 시스템 구성 요소 | 아니요 | 해당 없음(GPL의 System Library) | 아니요 |

### 배포본에 들어 있지 않은 것(실행 중에 받거나 부르는 것)
| 항목 | 라이선스·조건 | 비고 |
|---|---|---|
| Silero VAD 모델 | MIT | 첫 녹음 때 내려받습니다(커밋·SHA-256 고정). |
| 한국어 Zipformer 모델(k2-fsa, KsponSpeech 학습) | Apache-2.0(원 모델 johnBamma/icefall-asr-ksponspeech-zipformer-2024-06-24) | 사용자가 내려받을 때만 받습니다. |
| SenseVoice Small(다국어) | **FunASR Model Open Source License Agreement 1.1** | 출처·모델 이름을 유지해야 합니다. 자유 소프트웨어 라이선스가 아니며 앱에 넣지 않습니다. 사용자가 고를 때만 내려받습니다. |
| Playwright MCP(추천 서버) | Apache-2.0 | 사용자가 켜면 `npx`로 받습니다. |
| GitHub, Google Workspace, Zotero, Semantic Scholar, arXiv, Notion, Firecrawl, POSTECH GenAI API, (선택) Qdrant·Langfuse | 각 서비스 이용 약관 | 네트워크 서비스입니다. 소스 라이선스와 관계없습니다. |

**AGPL과 함께 쓸 수 없는 구성 요소는 찾지 못했습니다.**
따라서 대체 라이브러리, 별도 구성, 추가 허가, 기능 분리 가운데 어느 조치도 필요하지 않았습니다.

## 4. 배포본과 해당 소스(Corresponding Source)

| 배포본 | 라이선스 전문 | 제3자 고지 | 앱 안 표시 | CI 확인 |
|---|---|---|---|---|
| Windows 설치 파일 | 설치된 앱의 `_internal/LICENSE` | `_internal/THIRD_PARTY_NOTICES.md`, `licenses/` | 설정 → 라이선스 | 앱 묶음(payload.zip)을 `license_check.py package`로 확인 |
| macOS DMG·앱 | DMG 맨 위 `LICENSE.txt`, 앱 안 `Contents/Resources/LICENSE` | DMG 맨 위와 앱 안 | 설정 → 라이선스 | 마운트한 DMG를 확인 |
| Android APK | `assets/LICENSE`(앱이 처음 실행할 때 `files/res/`로 복사) | `assets/THIRD_PARTY_NOTICES.md`, `assets/licenses/` | 설정 → 라이선스 | APK(zip)를 확인 |
| GitHub Release | 같은 태그의 소스 아카이브(zip·tar.gz)에 `LICENSE` | 소스 아카이브 | 릴리스 노트에 라이선스·소스 안내 | 릴리스 작업이 본문에 덧붙임 |

**해당 소스 제공 방식**:
- 공식 배포본은 `build.yml`이 한 커밋에서 빌드합니다. 릴리스할 때 그 커밋에 `v<버전>` 태그를 만들고, 같은 태그의 GitHub 소스 아카이브를 해당 소스로 안내합니다.
- 앱의 **소스 코드 보기**는 저장소 첫 화면이 아니라 `https://github.com/bj0322/POSCHAT/tree/v<앱 버전>`을 엽니다. 제3자 라이선스 창은 `archive/refs/tags/v<버전>.zip`도 보여 줍니다.
- 빌드·설치 스크립트(`build_installer.py`, `installer/`, `android/`, `.github/workflows/build.yml`)도 같은 소스에 들어 있습니다.
  - 빌드 때 받는 제3자 바이너리(sherpa-onnx AAR, Chaquopy 패키지)는 버전과 SHA-256을 고정해 같은 결과를 재현할 수 있습니다.
- 바이너리와 소스가 같은지:
  - 앱 버전(`version.py`)을 Windows 설치 프로그램 등록 버전·macOS `CFBundleShortVersionString`·APK selftest 버전과 CI가 비교합니다. APK `versionName`은 빌드할 때 `version.py`에서 읽습니다.
  - 릴리스 태그는 빌드한 커밋에 만듭니다(`workflow_dispatch`의 `release` 입력).

**AGPL §13(네트워크 상호작용)**:
- POSCHAT은 사용자 기기에서 도는 앱입니다.
- 내장 MCP 서버는 같은 기기에서 표준 입출력이나 앱 안 스레드로만 통신하고, 다른 사람에게 네트워크 서비스로 열려 있지 않습니다.
- 그래서 지금 §13이 요구하는 원격 사용자 대상 소스 제공 지점은 없습니다.
- 수정한 POSCHAT을 다른 사람이 네트워크로 쓰게 하는 경우에는 §13에 따라 그 사용자에게 소스를 제공해야 합니다. README 라이선스 절 3번이 이를 안내합니다.
  - 예: 설계만 된 원격 게이트웨이(docs/architecture/04)를 구현해 운영하는 경우.
  - 그런 기능을 만들 때는 서비스 화면이나 응답에 이 버전의 소스 주소를 넣어야 합니다.

## 5. 남은 위험(사람이 결정할 것)

1. **SenseVoice 모델 약관**: 자유 소프트웨어 라이선스가 아닌 FunASR 모델 약관을 따릅니다.
   - 앱에 넣지 않고 사용자가 고를 때만 받으므로 POSCHAT 배포본의 라이선스와 충돌하지 않습니다.
   - 다만 사용자에게 약관을 알려야 하고, 기본 모델로 바꾼다면 다시 검토해야 합니다.
2. **KsponSpeech 학습 데이터**: 한국어 Zipformer 모델 자체는 Apache-2.0이지만, 학습 데이터(AI Hub KsponSpeech)에는 별도 이용 조건이 있습니다.
   - 학습 데이터 조건이 모델 사용에 미치는 영향은 확인하지 못했습니다.
3. **다른 기여자의 MIT 코드**: MIT 조건(저작권·허가 고지 유지)을 지키려고 LICENSE_HISTORY.md에 기여 커밋을 남겼습니다.
   - 해당 파일 머리말에는 프로젝트 저작자만 적혀 있습니다. 기여자 표시를 파일마다 따로 넣을지는 저작권자가 정할 일입니다.
4. **pip 메타데이터의 한계**:
   - `license_check.py deps`는 패키지가 스스로 적은 메타데이터를 읽습니다. 실제 번들 안의 하위 구성 요소(예: numpy·Pillow에 정적으로 묶인 C 라이브러리)는 다 드러나지 않습니다.
   - 데스크톱 빌드는 각 패키지가 싣는 `LICENSE`·`*.dist-info/licenses/` 파일을 `licenses/python/`에 넣고 CI가 그 폴더가 있는지 확인합니다. 원문 파일을 싣지 않은 패키지(proxy_tools, sherpa-onnx-core)는 메타데이터의 라이선스 이름만 남습니다.
   - 안드로이드는 Chaquopy가 설치한 패키지 정보(dist-info)에서 같은 파일을 읽어 보여 줍니다. 에뮬레이터 시험에서 실제로 보이는지는 CI 결과로 확인해야 합니다.
5. **코드 서명 인증서·스토어 정책**: 라이선스와 관계없지만, 스토어 배포 때는 스토어 약관과 AGPL의 관계를 다시 검토해야 합니다.
