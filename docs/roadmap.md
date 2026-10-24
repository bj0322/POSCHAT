# POSCHAT 로드맵과 다음 작업 (v1.16부터)

마지막 갱신: 2026-10-24, v1.16.0 릴리스 뒤 v1.17(Adaptive Hybrid AI Engine) 개발 시작 시점. 작업 지침은 저장소 최상위 [CLAUDE.md](../CLAUDE.md).

**플랫폼 정책(2026-10, 사용자 지시)**: 안드로이드 앱은 따로 요청하지 않으면 기능을 맞추지 않는다. 데스크톱(Windows·macOS)만 손본다.
공유 Python·화면 코드는 안드로이드 빌드에도 들어가므로 새 모듈은 계속 공유 목록에 넣고, 안드로이드에서 안 되는 기능은 '쓸 수 없음'으로 막는다. CI의 android 작업과 APK 자산은 그대로 둔다.

## 지금까지
| 버전 | 내용 | 상태 |
|---|---|---|
| 1.12 | 설치 프로그램 안정화, Knowledge Work Plugins, 접근성 | 릴리스 |
| 1.13 | 브라우저: 채팅 옆 네이티브 웹 뷰, 격리, 페이지 읽기·첨부, 에이전트 browser_read/open | 릴리스(B1은 1.15에서 수정) |
| 1.14 | 논문 읽기(POSCHAT Paper) | 릴리스 |
| 1.15 | B1 수정(ui_events 큐) + POSCHAT Code(편집기·변경 검토·Git·실행) | 릴리스 |
| 1.16 | Code 에이전트(작업 탭), POSCHAT Lab, AI 브라우저 에이전트, 사이드바 정리, 보안 검토 반영(사이트 승인 kind `site`, `.git` 수정 금지) | 릴리스 |
| 1.17 | Adaptive Hybrid AI Engine: 로컬 AI(Ollama)·자동 모델 선택·품질 검증·Cloud 승격·비용 기록 | 개발 중 |

## 지금 할 일

### 1. v1.17 Adaptive Hybrid AI Engine (개발 중)
- 로컬 AI(Ollama, 기본 꺼짐) 연결·모델 목록·기능 확인, 요청 분석 → 정책(Economy·Balanced·Quality·Local Only) → 모델 선택, 작업별 품질 검증과 Cloud 승격,
  라우팅 이유 표시, 비용·지연 기록과 통계, 벤치마크 데이터셋. 기본값은 기존 동작(자동 선택 꺼짐). 구조·진행은 [architecture/adaptive-ai.md](architecture/adaptive-ai.md).
- 1.16 실제 앱 손 확인(아래 '알려진 한계')은 계속 남아 있다.

### 2. 다음 후보(v1.18 이후)
- Code 에이전트: 작업마다 git worktree/브랜치로 격리, 하위 작업(서브에이전트), 테스트 명령 자동 찾기, 긴 출력 요약, 이미지(스크린숏) 입력.
- 대화형 터미널(ConPTY/PTY, SSH 세션), SystemVerilog 문법 트리.
- Lab: papermill식 노트북 파라미터, 원격(SSH) 실행 기록, 실험 보고서 내보내기(Markdown·PDF), 지표 단위 변환 규칙.
- 브라우저 에이전트: iframe·shadow DOM 요소, 드래그·호버, 탭 여러 개, 사이트별 허용 목록 설정.

### 구현 기록
- 1.16 구조: [architecture/poschat-lab.md](architecture/poschat-lab.md), [architecture/browser-agent.md](architecture/browser-agent.md), [architecture/poschat-code.md](architecture/poschat-code.md)(Code 에이전트 절).
- 1.15 B1: 네이티브 이벤트 처리기(UI 스레드) → `Bridge._push()` → `evaluate_js()` 교착 → `ui_events.EventPump`로 해결. 시험 `tests/test_ui_events.py`, `tests/browser_spike.py`(`--legacy-push`로 재현).

## 알려진 한계·확인할 것
- 1.14 논문 화면은 Chromium 화면 시험과 CI 빌드만 통과했다. 실제 Windows(WebView2)·macOS(WKWebView)·안드로이드 앱에서 PDF 열기·드래그 선택·영역 자르기·파일 고르기를 손으로 확인하지 않았다.
  특히 macOS WKWebView의 ES 모듈 워커(`pdf.worker.min.js`)와 안드로이드 `appassets` 주소에서의 모듈 불러오기.
- 1.13 브라우저의 네이티브 붙이기는 CI 창에서 확인했다. B1은 1.15에서 고쳤고 CI 창 시험(열기·이동·이벤트 폭주·닫기 중 앱 응답)은 통과했지만, 실제 앱에서 손으로 확인하는 일은 남았다.
- 1.15 Code 화면은 Chromium 화면 시험과 CI 빌드만 통과했다. WebView2·WKWebView·안드로이드 WebView에서의 편집기 입력·IME·키보드는 손으로 확인해야 한다.
- macOS WKWebView 백엔드는 제목·주소가 바뀌어도(SPA의 pushState 등) 페이지가 다 열릴 때만 알린다(KVO 없음).
- 1.16 브라우저 에이전트·Lab·Code 에이전트 화면은 Chromium 화면 시험과 CI로 확인했다. 실제 앱에서 손으로 확인하는 일이 남았다.
