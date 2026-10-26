# POSCHAT — Claude Code 작업 지침

새 세션은 이 파일과 [docs/roadmap.md](docs/roadmap.md)를 먼저 읽고 시작한다. 다음 할 일은 roadmap의 **지금 할 일**이다.

## 프로젝트
- POSTECH 학생용 AI 데스크톱·안드로이드 앱. Python + pywebview 6.2(Windows: WinForms+WebView2/pythonnet, macOS: Cocoa+WKWebView/pyobjc),
  안드로이드는 Chaquopy(Python 3.11) + Kotlin `MainActivity.kt`. 화면은 `web/`(바닐라 JS, 빌드 도구 없음).
- 진입점 `main.py`의 `Bridge`가 화면 API(js_api)다. 기능별 화면 API는 믹스인으로 나눈다:
  `workspace_api.WorkspaceApi`, `browser_api.BrowserApi`(1.13), `paper_api.PaperApi`(1.14), `code_api.CodeApi`(1.15),
  `code_agent.CodeAgentApi`(1.16 Code 에이전트, 1.17.1 권한 모드·슬래시 명령·worktree — 도우미 `code_project.py`), `lab_api.LabApi`(1.16 Lab),
  `adaptive_api.AdaptiveApi`(1.17 AI 실행 정책·로컬 AI).
  브라우저 에이전트는 `browser_agent.py` + agent의 `browser_*` 단계.
- 1.17 Adaptive AI: 모델 호출은 `Agent._ask(prompt, purpose=…)` → `adaptive_engine.AdaptiveEngine`(대화 모델이 `auto`·`local:…`일 때) 또는 `api.ask`.
  라우터 `adaptive_router.py`, 검증 `quality_gate.py`, 로컬 실행기 `local_ai.py`(Ollama). Local Only는 `api.cloud_guard`가 마지막으로 막는다.
  구조 [docs/architecture/adaptive-ai.md](docs/architecture/adaptive-ai.md). 벤치마크 `tools/adaptive_benchmark.py`(데이터는 `tools/adaptive_benchmark_data.py`로 다시 만든다).
- Python → 화면 이벤트는 `Bridge._push` → `ui_events.EventPump`(전용 스레드). UI 스레드(네이티브 처리기)에서 `evaluate_js`를 직접 부르지 않는다(B1).
- 에이전트(`agent.py`)는 JSON 단계(`{"action": ...}`)를 `_tool_<이름>` 메서드로 실행한다. 외부에서 온 글(웹페이지·논문·MCP 결과)은
  `connectors.wrap_untrusted`로 감싼다.
- 라이선스 AGPL-3.0-only. 새 소스 파일(.py .js .css .html .kt)에는 SPDX 머리말 두 줄을 넣는다(`tools/license_check.py repo`가 검사).
  제3자 파일은 `web/vendor/`와 `licenses/`, 고지는 `THIRD_PARTY_NOTICES.md`.

## 규칙
- **플랫폼**: 안드로이드 앱은 사용자가 따로 요청하지 않으면 기능을 맞추지 않는다(데스크톱만). 공유 모듈 목록·CI android 작업은 그대로 유지하고, 안 되는 기능은 막는다.
- 화면 글·주석·문서는 한국어, 쉬운 말(주변 코드의 말투를 따른다). 커밋 메시지도 한국어.
- 새 Python 모듈은 `android/app/build.gradle.kts`의 공유 모듈 목록에 더한다(`tests/test_connectors.py`가 검사). 데스크톱 전용 모듈은 그 테스트의 제외 목록에.
- 안드로이드 Python은 3.11: f-string 식 안에 백슬래시를 쓰지 않는다.
- 웹페이지·PDF 같은 외부 콘텐츠에 앱 권한(js_api·파일·실행·MCP·API 키)을 주지 않는다. 사용자 요구사항이다(docs/security.md).
- 커밋·PR·코드에 모델 ID를 적지 않는다. 커밋 끝에:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: <세션 URL>
  ```

## 시험
```
python -m unittest discover -s tests             # 전체(Playwright가 있으면 화면 시험 포함)
python -m unittest tests.test_ui_smoke           # 화면 시험만(Chromium)
POSTECH_UI_SHOTS=<폴더> python -m unittest tests.test_ui_smoke   # 스크린숏
python tools/license_check.py repo               # SPDX·고지 점검
```
- `tests/support.py`의 `isolated_app_dir()`로 데이터 폴더를 격리한다. `tests/ui_harness.py`는 실제 Bridge에 붙은 화면을 HTTP로 띄운다.
- `tests/browser_spike.py`는 CI의 `browser-spike` 작업(windows·macos 실제 창)에서만 돈다.
- 로컬 AI 시험은 `tests/fake_ollama.py`(Ollama API 흉내)를 쓴다. 실제 Ollama 점검은 사용자 PC에서 `python tools/local_ai_check.py --model <모델>`.

## 릴리스 절차(사용자가 요청할 때만)
1. 작업 브랜치에서 `version.py`, `docs/release-notes/vX.Y.Z.md`, README 첫 줄·기능 표, `web/app.js` 사용법 가이드를 고친다.
2. 푸시만으로는 CI가 돌지 않는다. PR을 열거나 `build.yml`을 workflow_dispatch로 실행한다.
3. CI(license·tests·ui·windows·macos·android·browser-spike)가 모두 통과하면 PR을 머지한다.
4. main에서 `build.yml`을 workflow_dispatch로 `release=vX.Y.Z` 입력과 함께 실행 → 태그·릴리스·자산 10개
   (POSCHAT-Setup.exe, POSCHAT-Store-Setup.exe, POSCHAT-mac.dmg, POSCHAT.apk, 서명 파일 .sig 3개와 옛 이름 PostechChat-* 사본 3개).
   앱은 업데이트 서버(`updates.UPDATE_BASE_URL` = `https://pidstech.com`, [docs/update-server.md](docs/update-server.md))에서 받는다. 서버가 10분마다 GitHub 릴리스를 가져오므로 릴리스 뒤 `curl https://pidstech.com/api/releases/latest`와 옛 주소 `http://3.38.118.65/api/releases/latest`에서 새 태그가 보이는지 확인한다. 태그는 모든 사용자에게
   자동 업데이트로 나가므로 사용자 승인 없이 만들지 않는다. 한 번 올린 릴리스 자산은 바꾸지 않는다(Store 제출 주소, 정책 10.2.9).
5. 머지 뒤 작업 브랜치는 `git fetch origin main && git checkout -B <브랜치> origin/main`으로 다시 시작한다.
6. Microsoft Store(EXE 방식, [docs/microsoft-store.md](docs/microsoft-store.md)): 사용자가 파트너 센터에서 패키지 URL을 새 버전의
   `…/releases/download/vX.Y.Z/POSCHAT-Store-Setup.exe`로 바꿔 제출한다(서명된 빌드일 때만). Store판은 스스로 업데이트하지 않는다(`version.distribution()`).
