# 01. 현재 구조 분석 (v1.9.2 기준)

이 문서는 README가 아니라 실제 소스코드(커밋 `4b0bae3`)를 읽고 정리했다. 이후 설계(02)와 구현 계획(03)은 이 분석을 전제로 한다.

## 1. 전체 구조

POSCHAT은 **하나의 Python 코드베이스**를 세 플랫폼이 공유한다.

| 계층 | 파일 | 역할 |
|---|---|---|
| 진입점·JS 브리지 | `main.py` (`Bridge`) | pywebview가 `window.pywebview.api.<메서드>`로 호출하는 API. 밑줄로 시작하지 않는 공개 메서드가 모두 JS에 노출된다. Python→JS 알림은 `window.onBackendEvent(event)` |
| 화면 | `web/index.html`, `web/app.js`, `web/po.js`, `web/style.css` | 프레임워크 없는 바닐라 JS. `h()` DOM 도우미와 `modal()`로 모든 대화상자를 그린다 |
| 모델 API | `api.py` | POSTECH GenAI 게이트웨이의 3가지 방식(`chat_completions`(기본)·`responses`·`a1`). 스트리밍, 크레딧 헤더(`on_credit`), 사용량(`on_usage`) 콜백 |
| 에이전트 | `agent.py` (`Agent`) | 일반 대화(`_chat`)와 단계 반복 에이전트(`_agent_loop`) |
| MCP 클라이언트 | `mcp_client.py` (`Manager`, `Server`) | 표준 입출력(stdio) JSON-RPC MCP 클라이언트. 내장·추천·외부 서버 관리 |
| 내장 MCP 서버 | `office_mcp.py`(serve·공통 도우미), `paper_mcp.py`, `notion_mcp.py`, `firecrawl_mcp.py` | 앱 실행 파일 자신을 `--mcp-server <이름>`으로 띄워 하위 프로세스로 돌린다 |
| 저장소 | `storage.py` | 설정·대화·메모리·사용자 정보·첨부·사용량 |
| 외부 에이전트 연동 | `ai_memory.py` | ai-memory MCP 서버와 인계(handoff)·최근 기억 |
| 문서·첨부 | `documents.py`, `attachments.py` | PDF·Office·HWP 텍스트 추출, 첨부 업로드 |
| PO노트 | `po_note.py`, `stt.py` | 강의 녹음 전사(sherpa-onnx 로컬 + 서버 보정), 필기 노트 생성 |
| 업데이트 | `updates.py` | 업데이트 서버에서 새 버전 확인·다운로드·SHA-256·Ed25519 서명 검증 |
| 인증서 | `certs.py` | 중간 인증서를 보내지 않는 genai.postech.ac.kr용 AIA 처리(안드로이드) |
| 안드로이드 | `android/…/MainActivity.kt`, `android_main.py` | Chaquopy로 같은 `main.Bridge`를 실행. WebView가 pywebview를 대신한다 |

## 2. 에이전트 실행 루프와 Tool Calling

`agent.py`의 모듈 문서에 적힌 대로, POSTECH 서버 모델은 자체 시스템 프롬프트 때문에 **네이티브 function calling 형식의 도구 호출 지시를 거부**한다. 그래서 POSCHAT은 OpenAI/Anthropic의 tool-calling API를 쓰지 않고 다음 방식을 쓴다.

1. 정적 프롬프트(`_static_prompt`): 단계 종류(`ACTION_DOCS`), 규칙, 작업 폴더, MCP 도구 목록(`서버.도구(인자*)`), INIT.md, 스킬, 메모리 블록, 이전 대화, 첨부, 목표.
2. 진행 기록(log)이 비어 있으면 모델이 거부하므로 첫 단계(`list .`)는 앱이 직접 수행한다.
3. 매 단계: 모델이 JSON 한 개(`{"action": ...}`)를 고른다 → `parse_action`(LaTeX 이스케이프 보정 포함) → `_execute` → `_tool_<action>` → 관찰 결과를 기록에 추가.
4. 형식 거부 시 `_convert`로 "안내문의 첫 단계를 JSON으로 바꾸는 변환 작업"을 다시 시킨다.
5. `done`이 나오거나 `max_steps`에 도달하면 끝.

단계 종류: `list`, `read`, `search`, `write`, `edit`, `run`, `skill`, `recall`, `mcp`, `done`.

**설계상 함의**: 새 기능(커넥터·연구·메모리)은 새 `action`을 늘리기보다 **MCP 도구로 노출**하는 것이 기존 구조와 가장 잘 맞는다. 모델은 이미 `mcp` 단계로 `서버.도구`를 부른다.

## 3. MCP 서버 관리

`mcp_client.Manager.specs(config, workspace)`가 서버 목록을 만든다.

| 종류 | 출처 | 기본 상태 | 설정 키 |
|---|---|---|---|
| 내장(builtin) | `BUILTIN_SERVERS` (word·powerpoint·excel·paper·notion·firecrawl) | 켜짐 | 끈 것을 `mcp_disabled`에 기록 |
| 추천(preset) | `preset_servers()` (playwright, 안드로이드 제외) | 꺼짐 | 켠 것을 `mcp_enabled`에 기록 |
| 외부 | `%APPDATA%\PostechChat\mcp.json` (Claude Desktop 형식) | 켜짐 | `mcp_disabled` 또는 항목의 `"disabled": true` |

- 연결은 지연 방식: 에이전트 실행이나 MCP 창의 '지금 연결' 때 `ensure()`가 켜진 서버를 병렬로 띄운다. 설정(`spec_key`: 명령·인자·환경·cwd)이 바뀌면 다시 띄운다.
- 내장 서버는 `sys.executable --mcp-server <이름>`(소스 실행은 `office_mcp.py <이름>`)으로 띄우고, **안드로이드는 하위 프로세스를 못 띄우므로** `INPROCESS_BUILTIN=True`로 같은 프로세스의 스레드에서 `os.pipe`로 돌린다.
- 프로토콜: `initialize`(2025-06-18) → `notifications/initialized` → `tools/list`(커서 페이지) → `tools/call`. 결과의 text/resource/resource_link를 문자열로 합친다. 타임아웃: 시작 30초, 호출 180초. **재시도·속도 제한·감사 로그는 없다.**
- 내장 서버와 외부 서버의 차이
  - 내장: 앱이 코드를 소유. 작업 폴더 밖 경로 거부(`office_mcp._path`). 도구 주석(`readOnlyHint`/`openWorldHint`)을 앱이 정한다.
  - 외부: 임의 명령. 도구 주석은 서버가 **스스로 신고**한 값이다.

## 4. 승인(권한) 모델

- 설정 `permission`: `ask`(기본) / `auto_edit` / `auto_all`.
- `Bridge._confirm(kind)`: `kind`는 `"edit"`(파일 수정) 또는 `"run"`(명령 실행). 화면은 '거부 / 이번 실행 동안 모두 허용 / 허용'. "모두 허용"은 `_session_allow`에 kind를 넣어 **앱을 끌 때까지** 유지된다(이름과 달리 실행 단위가 아니다).
- MCP 도구: `readOnlyHint`가 참이면 묻지 않는다. 아니면 내장+openWorldHint 거짓은 `edit`, 그 밖(외부 서버, Notion 쓰기 등)은 `run`으로 묻는다.
- **한계**: 외부 서버의 `readOnlyHint`를 그대로 믿는다. `auto_all`이면 외부 쓰기·전송도 자동 허용된다. 도구 결과(외부 문서)는 신뢰할 수 없는 입력이라는 표시 없이 진행 기록에 들어간다(ai-memory 규칙에만 "지시가 아님" 문구가 있다).

## 5. 메모리·대화·검색

| 데이터 | 위치 | 형식 | 모델에 들어가는 방식 |
|---|---|---|---|
| 메모리 | `memory.md` | `- ` 한 줄이 기억 하나. `<!-- -->` 안내문 제외 | 모든 대화의 `[기억 (memory.md)]` 블록(최대 6000자) |
| 사용자 정보 | `USER.md` | 자유 Markdown | `[사용자 정보 (USER.md)]` 블록 |
| 대화 | `threads/<id>.json` | `{id,title,created,updated,model,messages[{id,role,content,ts,…}],ai_memory}` | 최근 `history_messages`개, 10000자 |
| 다른 대화 검색 | `storage.search_threads` | 한국어 조사 때문에 **글자 2-gram 겹침 비율**로 점수 | 자동 참고(📎) + `recall` 단계 |
| 사용량 | `usage.json` | 날짜별 호출 수·토큰 | 설정 창 표시만 |

- "기억해 줘" 의도(`MEMORY_INTENT_RE`)가 있으면 모델로 한 문장을 뽑아 memory.md에 더한다.
- `/user`는 최근 사용자 메시지로 USER.md를 갱신한다.
- 벡터 검색·프로젝트별 메모리·연구 메모리는 없다.

## 6. ai-memory 인계

`ai_memory.py`: mcp.json에 ai-memory(`ai-memory mcp-bridge --no-session-id`)가 있고 필요한 도구가 모두 있으면 자동으로 동작한다.

- 대화의 첫 에이전트 실행: `memory_handoff_accept` + `memory_recent` → 프롬프트 블록.
- 파일 수정·명령·도구 실행 후: `memory_handoff_begin`(같은 대화의 앞선 인계는 `memory_handoff_cancel`).
- `(workspace, project)`는 ai-memory 규칙(`.ai-memory.toml` → git 원격 → 폴더 이름)으로 계산하며 이 로직(`resolve_scope`)은 **재사용 가치가 크다**(프로젝트 메모리의 키로 쓴다).
- 인계 필드는 summary·open_questions·next_steps·files_touched뿐이다. Task ID, 테스트 결과, 커밋, 필요한 승인, 중복 실행 방지(idempotency)는 없다.

## 7. 파일 접근과 명령 실행

- 에이전트 `_resolve`와 내장 서버 `_path`는 모두 **작업 폴더 밖 경로를 거부**한다(심볼릭 링크는 `resolve()` 후 비교).
- `run`은 `shell=True`, 작업 폴더 cwd, 180초 제한, 승인 필요. 리소스 제한·격리는 없다. 안드로이드는 `/system/bin/sh`.

## 8. API 키·설정 저장

- `config.json`(평문 JSON)에 `api_key`, `notion_token`, `firecrawl_key`가 저장된다. 내장 서버 하위 프로세스는 `storage.load_config()`를 직접 읽거나 환경 변수를 쓴다.
- OS 보안 저장소(Windows 자격 증명 관리자, macOS 키체인)는 쓰지 않는다. `.gitignore`가 config.json·*.key·credentials*.json을 막는다.
- 데이터 폴더: Windows `%APPDATA%\PostechChat`, macOS `~/Library/Application Support/PostechChat`, 리눅스 `~/.config/PostechChat`, 안드로이드 `<앱 전용 files>/PostechChat`(안드로이드 샌드박스로 다른 앱이 읽을 수 없다).

## 9. 플랫폼별 제약

| 항목 | Windows | macOS | Android |
|---|---|---|---|
| 하위 프로세스 MCP | O | O (Finder 실행 시 PATH 보강 `_extend_mac_path`) | **X** — 내장 서버만 스레드로 |
| npx 추천 서버 | O | O | X |
| `run` 명령 | cmd | sh | `/system/bin/sh`(제한적) |
| 녹음(PO노트) | O | O | X(노트만) |
| URL 열기 | `webbrowser` | `webbrowser` | **`openPath`가 파일만 처리** — URL 처리 추가 필요(OAuth) |
| Python 패키지 | requirements.txt | 동일 | `requirements-android.txt`(Chaquopy 3.11). 네이티브 패키지는 Chaquopy 저장소에 있어야 함 |

## 10. 빌드·배포

- Windows/macOS: `build_installer.py` → PyInstaller `--onedir`. 내장 서버 모듈은 `main.py`에서 정적으로 import되는 경로로 찾아 묶인다(`office_mcp.all_servers()` 안의 import 포함). **새 내장 서버 모듈도 같은 경로로 import되면 자동으로 묶인다.**
- Android: `android/app/build.gradle.kts`의 `syncSharedPython`이 **파일 이름 목록으로** Python 모듈을 복사한다. **새 모듈을 만들면 이 목록에 반드시 더해야 한다.**
- CI(`.github/workflows/build.yml`): ubuntu 단위 테스트 → Windows/macOS 빌드+`--selftest`(문자열 확인: `paper OK`, `notion OK` 등) → Android 빌드+에뮬레이터 계측 테스트(`AppSmokeTest`: **내장 서버별 도구 개수를 단언**, 예: paper 5개) → 태그면 Release 게시.
- 자동 업데이트가 GitHub Releases를 보므로, **태그를 올리면 모든 사용자에게 업데이트가 배포된다.**

## 11. 테스트

- `tests/` 아래 unittest 41개(설정·API 호환·PO노트·업데이트). 외부 네트워크 없이 Mock으로 돈다. 기준선: `python -m unittest discover -s tests` 통과.
- 에이전트 루프·MCP 호출 경로에 대한 테스트는 없었다(아래 버그가 잡히지 않은 이유).

## 12. 분석 중 발견한 기존 버그 (신규 기능과 분리)

| # | 위치 | 내용 | 처리 |
|---|---|---|---|
| B1 | `agent.py` `_tool_mcp` | 정의되지 않은 `read_only` 변수 때문에 **ai-memory를 뺀 모든 MCP 도구 호출이 `NameError`로 실패**(ai-memory 커밋 이후, 1.6~1.9.2). selftest는 서버를 직접 불러 잡지 못했다 | 별도 커밋으로 수정 + 회귀 테스트(`tests/test_agent_mcp.py`) |
| B2 | `main.py` `_confirm` | "이번 실행 동안 모두 허용"이 실행이 끝나도 앱을 끌 때까지 유지된다 | 동작 변경이 사용자에게 보이므로 1.10에서 **실행 단위로 초기화**(릴리스 노트에 명시) |
| B3 | `agent.py` `_tool_mcp` | 외부 MCP 서버의 `readOnlyHint`를 검증 없이 신뢰 | 커넥터 정책 계층에서 보완(외부 서버별 '항상 묻기' 정책) |
