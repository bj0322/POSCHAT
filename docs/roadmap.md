# POSCHAT 로드맵과 다음 작업 (v1.15부터)

마지막 갱신: 2026-10-24, v1.15.0(B1 수정·POSCHAT Code) 개발 완료 시점(릴리스 전). 작업 지침은 저장소 최상위 [CLAUDE.md](../CLAUDE.md).

## 지금까지
| 버전 | 내용 | 상태 |
|---|---|---|
| 1.11 | POSCHAT 이름, 일반 AI 모델(Claude), 연구·자동화 본문 화면, 업데이트 설치 수정 | 릴리스 |
| 1.12 | 설치 프로그램 안정화, Knowledge Work Plugins, 접근성 | 릴리스 |
| 1.13 | 브라우저: 채팅 옆 네이티브 웹 뷰(WebView2·WKWebView·Android WebView), 격리, 페이지 읽기·첨부, 에이전트 browser_read/open | 릴리스 — **멈춤 버그 B1 있음** |
| 1.14 | 논문 읽기(POSCHAT Paper): PDF.js 화면, 선택·쪽·영역 묻기, 요약·비교표, 에이전트 paper_read | 릴리스 |
| 1.15 | **B1 수정** + POSCHAT Code(편집기·변경 검토·Git·실행) | 구현·자동 시험 완료, 실제 기기 확인·릴리스 대기 |
| 1.16 | POSCHAT Lab | 다음 |

## 지금 할 일

### 1. v1.15 마무리: 실제 기기 확인 → 릴리스(사용자 승인 뒤)
v1.15(B1 수정 + POSCHAT Code)는 작업 브랜치에서 구현과 자동 시험을 마쳤다. 남은 일:
- 실제 Windows(WebView2)·macOS(WKWebView) 앱에서 브라우저를 열고 몇 분 써 보며 "응답 없음"이 없는지 손으로 확인(CI 창 시험은 통과).
- 실제 앱(WebView2·WKWebView·안드로이드 WebView)에서 Code 화면: 편집기 입력(한글 IME 포함), Ctrl+S, 덩어리 검토, 실행 패널 출력, 휴대폰 키보드.
- 확인되면 CLAUDE.md의 릴리스 절차(PR 머지 → main에서 `release=v1.15.0`). 태그는 사용자 승인 없이 만들지 않는다.

### B1 처리 기록 (1.15에서 수정)
- 원인: 네이티브 이벤트 처리기(UI 스레드) → `Browser.navigated()` → `Bridge._push()` → `window.evaluate_js()`가 UI 스레드의 결과를 기다리며 교착.
- 수정: `ui_events.EventPump`(큐 + 전용 스레드, 순서 유지, 연달은 상태 이벤트만 합침, 상한, 예외 격리, 종료). `Bridge._push`는 바로 돌아온다.
- 시험: `tests/test_ui_events.py`(UI 스레드 흉내 창으로 예전 방식 교착 재현·새 방식 해결), `tests/browser_spike.py`(실제 창, 단계마다 앱 응답 확인,
  `--legacy-push`로 교착 재현 — Windows CI에서 재현 확인).

### 2. v1.15 POSCHAT Code — 구현됨
구조 [architecture/poschat-code.md](architecture/poschat-code.md), 사용법 [code-editor-guide.md](code-editor-guide.md), 보안 [code-security.md](code-security.md).
- 파일 트리·CodeMirror 6 편집기(오프라인 묶음)·안전한 저장·외부 변경 감지·찾기·최근 파일·Git 표시.
- 선택한 코드·블록·파일·관련 파일 AI에게 묻기.
- 에이전트 `write`/`edit` → ChangeProposal → 덩어리별 받아들이기·거부·고쳐서 적용, 충돌·문맥 맞춤·중복 방지, 닫으면 예전 승인 창.
- Git 상태·차이·스테이지·커밋(푸시 없음)·AI 설명/리뷰/커밋 메시지.
- 실행 패널(승인 토큰·출력 스트리밍·중지·시간/출력 제한·비밀 가리기·실행 기록·소스 위치).
- 안드로이드: 열기·편집·저장·찾기·묻기만.
- 다음 단계로 미룸: 대화형 터미널(ConPTY/PTY, SSH 세션), SystemVerilog 문법 트리, 제안을 앱 재시작 뒤에도 남기기, 브라우저 2단계 자동화.

### 3. v1.16 POSCHAT Lab (실험 작업 공간)
- Code의 편집기·실행 패널을 다시 쓴다: 화면 `codeEditorTab()`·`codeRunPanel()`(web/code.js), Python `code_runner.RunManager`·`RunRecord`
  (명령·입력 파일·출력·종료 코드·시간·소스 위치, 데이터 폴더 `code/runs.jsonl`).
- 실험 기록: 설정(하이퍼파라미터)·명령·결과 파일·메모를 실험 단위로 남기고 비교표(논문 비교표와 같은 표 형식). 메모리의 실험·결과 기록 종류(`memory_store`)와 연결.
- 노트북 실행(이미 있는 `runner_mcp`의 Jupyter·Python, 매번 승인), 그래프 미리보기.
- PC 전용(안드로이드는 프로세스 실행 불가).

## 알려진 한계·확인할 것
- 1.14 논문 화면은 Chromium 화면 시험과 CI 빌드만 통과했다. 실제 Windows(WebView2)·macOS(WKWebView)·안드로이드 앱에서 PDF 열기·드래그 선택·영역 자르기·파일 고르기를 손으로 확인하지 않았다.
  특히 macOS WKWebView의 ES 모듈 워커(`pdf.worker.min.js`)와 안드로이드 `appassets` 주소에서의 모듈 불러오기.
- 1.13 브라우저의 네이티브 붙이기는 CI 창에서 확인했다. B1은 1.15에서 고쳤고 CI 창 시험(열기·이동·이벤트 폭주·닫기 중 앱 응답)은 통과했지만, 실제 앱에서 손으로 확인하는 일은 남았다.
- 1.15 Code 화면은 Chromium 화면 시험과 CI 빌드만 통과했다. WebView2·WKWebView·안드로이드 WebView에서의 편집기 입력·IME·키보드는 손으로 확인해야 한다.
- macOS WKWebView 백엔드는 제목·주소가 바뀌어도(SPA의 pushState 등) 페이지가 다 열릴 때만 알린다(KVO 없음).
- 브라우저 2단계(클릭·입력 자동화, 매번 승인)는 Code 이후로 미룸.
