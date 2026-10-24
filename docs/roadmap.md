# POSCHAT 로드맵과 다음 작업 (v1.15부터)

마지막 갱신: 2026-10-24, v1.14.0(논문 읽기) 릴리스 시점. 작업 지침은 저장소 최상위 [CLAUDE.md](../CLAUDE.md).

## 지금까지
| 버전 | 내용 | 상태 |
|---|---|---|
| 1.11 | POSCHAT 이름, 일반 AI 모델(Claude), 연구·자동화 본문 화면, 업데이트 설치 수정 | 릴리스 |
| 1.12 | 설치 프로그램 안정화, Knowledge Work Plugins, 접근성 | 릴리스 |
| 1.13 | 브라우저: 채팅 옆 네이티브 웹 뷰(WebView2·WKWebView·Android WebView), 격리, 페이지 읽기·첨부, 에이전트 browser_read/open | 릴리스 — **멈춤 버그 B1 있음** |
| 1.14 | 논문 읽기(POSCHAT Paper): PDF.js 화면, 선택·쪽·영역 묻기, 요약·비교표, 에이전트 paper_read | 릴리스 |
| 1.15 | **B1 수정** + POSCHAT Code | 다음 |
| 1.16 | POSCHAT Lab | 계획 |

## 지금 할 일

### 1. B1: 브라우저를 쓰면 앱이 "응답 없음"으로 멈춤 (가장 먼저, 1.14.1 핫픽스로 내도 된다)

**증상**: 데스크톱(Windows, macOS도 같은 구조)에서 사이드바 **브라우저**로 페이지를 열면 앱 창이 "프로그램이 응답하지 않음"이 된다.

**원인(코드로 확인함, 실제 기기에서 재현은 아직)**: UI 스레드 교착.
1. 웹페이지 뷰의 네이티브 이벤트 처리기는 UI 스레드에서 돈다.
   - Windows `browser_win.py`: `_on_starting`, `_on_completed`, `SourceChanged`·`DocumentTitleChanged`·`HistoryChanged` 람다(`_report`), `_on_download`, `_on_ready`.
   - macOS `browser_mac.py`: `_Delegate`의 `webView_didStartProvisionalNavigation_`, `webView_didFinishNavigation_`, `decidePolicy…`(blocked) 등은 메인 스레드.
2. 이 처리기들이 `browser.Browser.navigated()`/`blocked()` → `_emit()` → `BrowserApi._browser_event()` → `Bridge._push()`(`main.py`)를 부른다.
3. `Bridge._push()`는 `self._window.evaluate_js(...)`를 부른다. pywebview의 `evaluate_js`는
   - Windows(`webview/platforms/edgechromium.py`): `webview.Invoke(...ExecuteScriptAsync(...).ContinueWith(..., syncContextTaskScheduler))`로 UI 스레드에 결과 처리를 맡기고 `Semaphore.acquire()`로 기다린다.
   - macOS(`webview/platforms/cocoa.py`): `AppHelper.callAfter(eval)` 뒤 `result_semaphore.acquire()`.
   UI 스레드에서 부르면, 결과를 넘겨줄 UI 스레드가 바로 자기 자신이라 영원히 기다린다 → 창이 멈춘다.
4. 안드로이드는 `MainActivity.browserEvent()`가 `executor`(백그라운드)에서 Python을 부르므로 해당 없음.
5. CI의 `tests/browser_spike.py`는 `on_event`가 목록에 더하기만 해서(실제 앱처럼 `evaluate_js`를 부르지 않아) 이 버그를 못 잡았다.

**고칠 방법(권장)**:
- `Bridge._push()`를 막지 않게 바꾼다: 순서를 지키는 전용 백그라운드 스레드 하나와 큐(`queue.Queue`)를 두고, `_push`는 큐에 넣고 바로 돌아온다.
  스레드가 `evaluate_js`를 부른다. 창이 닫히면(`run_app`의 finally) 멈춤 표시를 넣어 끝낸다. 모든 기능(PO노트·허브 진행 이벤트 등)이 같은 경로를 쓰므로
  다른 UI 스레드 호출 경로도 함께 막힌다.
- 같은 이유로 UI 스레드에서 막는 호출이 더 없는지 본다: `browser_win.WebView2Backend._invoke`(form.Invoke)는 UI 스레드에서 부르면 바로 실행하므로 괜찮다.
  `browser.Browser.open()`은 `_lock`을 쥔 채 백엔드를 부른다 — UI 스레드 처리기가 `_lock`을 잡지 않게 유지한다(`navigated`는 잠그지 않는다).
- 브라우저 이벤트가 짧은 시간에 많이 오므로(SourceChanged·TitleChanged·HistoryChanged·Completed) 큐에서 같은 종류(type "browser")는 마지막 것만 보내도 된다.

**회귀 시험**:
- `tests/browser_spike.py`: `on_event`를 실제 앱처럼 `window.evaluate_js("window.__ev = ...")`를 부르게 바꾸고, 열기·뒤로 가기 뒤 앱 창이 응답하는지(`evaluate_js`가 5초 안에 돌아오는지) 확인한다. 고치기 전에는 Windows·macOS에서 실패해야 한다.
- 단위 시험: `_push`가 느린 `evaluate_js`(가짜 창, 1초 대기)에서도 바로 돌아오고, 순서가 지켜지는지.

### 2. v1.15 POSCHAT Code (AI 코드 편집기)
목표: 작업 폴더의 코드를 앱 안에서 보고 고치고, 에이전트가 고친 내용을 변경 단위로 받아들이거나 되돌린다.

범위(1단계):
1. 사이드바 **코드** → 채팅 옆(논문 화면과 같은 오른쪽 자리, `web/paper.js`의 창 구조를 본뜬다) 파일 트리 + 편집기.
   - 편집기: CodeMirror 6(MIT, 가볍고 Python·C/C++·JS·SystemVerilog 강조). Monaco(~10MB)는 쓰지 않는다. `web/vendor/codemirror/`에 묶음 하나로 넣고 고지 추가.
   - 열기·저장(작업 폴더 안만, `agent._resolve`와 같은 경로 검사), 찾기, 줄 번호, 탭.
2. **변경 검토**: 에이전트가 `edit`/`write`로 파일을 바꿀 때 지금의 승인 창 대신(또는 함께) 편집기에 diff를 보이고 덩어리(hunk)마다 받아들이기·되돌리기.
   - `agent.py`의 `confirm("edit", ...)` 경로와 `diffOrPre`(web/app.js)를 출발점으로.
3. **Git**: 변경 파일 목록, 파일별 diff(`git diff`), 스테이지·커밋 메시지 초안(에이전트). 푸시는 하지 않는다(사용자가 외부 도구로).
4. **실행 패널**: 명령 실행(지금의 에이전트 `run`과 같은 승인), 출력 스트리밍. 진짜 대화형 터미널(ConPTY/pywinpty)은 다음 단계.
5. 선택한 코드 묻기(논문 화면의 "선택한 부분 묻기"와 같은 흐름) — 파일 경로·줄 범위를 붙여 첨부.
6. RTL: Verilator/iverilog 명령을 실행 패널에서 쓸 수 있게(설치 안내만).
- 안드로이드: 읽기·간단한 편집만(실행 패널 없음) 또는 숨김 — 결정 필요.
- 시험: 경로 검사, 저장, diff 적용·되돌리기 단위 시험, 화면 시험(Chromium에서 파일 열기·고치기·hunk 받아들이기).

위험: 편집기 묶음 크기·안드로이드 키보드, 큰 파일(1MB 넘으면 읽기 전용), 줄 끝(CRLF) 보존.

### 3. v1.16 POSCHAT Lab (실험 작업 공간)
- Code의 편집기·실행 패널을 다시 쓴다(그래서 Code 다음).
- 실험 기록: 설정(하이퍼파라미터)·명령·결과 파일·메모를 실험 단위로 남기고 비교표(논문 비교표와 같은 표 형식). 메모리의 실험·결과 기록 종류(`memory_store`)와 연결.
- 노트북 실행(이미 있는 `runner_mcp`의 Jupyter·Python, 매번 승인), 그래프 미리보기.
- PC 전용(안드로이드는 프로세스 실행 불가).

## 알려진 한계·확인할 것
- 1.14 논문 화면은 Chromium 화면 시험과 CI 빌드만 통과했다. 실제 Windows(WebView2)·macOS(WKWebView)·안드로이드 앱에서 PDF 열기·드래그 선택·영역 자르기·파일 고르기를 손으로 확인하지 않았다.
  특히 macOS WKWebView의 ES 모듈 워커(`pdf.worker.min.js`)와 안드로이드 `appassets` 주소에서의 모듈 불러오기.
- 1.13 브라우저의 네이티브 붙이기는 CI 창에서 확인했지만 B1 때문에 실제 사용은 멈춘다.
- 브라우저 2단계(클릭·입력 자동화, 매번 승인)는 Code 이후로 미룸.
