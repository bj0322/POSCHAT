# POSCHAT Code 구조 (1.15)

채팅 옆 코드 편집기. 사용 방법은 [code-editor-guide.md](../code-editor-guide.md), 보안은 [code-security.md](../code-security.md).

## 한눈에

```
web/code.js (화면)                         Python (main.Bridge가 상속하는 CodeApi)
┌───────────────────────────────┐          ┌────────────────────────────────────────────┐
│ 파일 트리 · 탭 · CodeMirror 6 │──js_api─▶│ code_api.py  입력 검사·승인 토큰·에이전트 연결 │
│ 변경 검토 · Git · 실행 패널   │          │   ├ code_workspace.py  경로·읽기·저장·찾기      │
└──────────▲────────────────────┘          │   ├ code_diff.py       제안·덩어리·적용         │
           │ {"type":"code"} 이벤트          │   ├ code_git.py        git status/diff/add/commit│
           └──── ui_events.EventPump ◀──────│   └ code_runner.py     명령 실행·출력·기록       │
                 (전용 스레드, 막지 않음)    └────────────────────────────────────────────┘
                                                      ▲ review 훅
                                            agent.py  _save() ── write/edit
```

- 파일 로직(`code_workspace`)·Git(`code_git`)·변경 데이터와 적용(`code_diff`)·실행(`code_runner`)은 화면과 상관없는 모듈이고
  각자 시험이 있다. `code_api`만 Bridge·설정·이벤트를 안다.
- pywebview는 js_api 호출을 각각 새 스레드에서 실행하므로 파일 I/O·Git·찾기가 UI 스레드를 막지 않는다. Python → 화면 알림은
  1.15부터 모두 `ui_events.EventPump`를 거친다(B1 수정, 아래).

## 오른쪽 작업 영역

`#app`은 `사이드바 | #main(채팅) | 크기 막대 | 오른쪽 창`인 가로 배치다. 논문(`#paper-pane`)과 코드(`#code-pane`)는 HTML 창이고
브라우저는 앱 창 옆에 붙는 네이티브 웹 뷰다. 셋은 한 번에 하나만 보인다(`paperShow`·`browserToggle`·`codeShow`가 서로 닫는다).
닫는 것은 `hidden`만 바꾸므로 Code의 탭·편집기 상태·저장하지 않은 내용은 남는다. 너비(`--code-w`)와 아래 패널 높이(`--code-bottom-h`)는
화면 저장소(localStorage)에 기억한다. 720px 이하에서는 코드 창이 채팅을 덮는다.

## 편집기 묶음

- `tools/codemirror/`(package.json·entry.js·build.mjs)에서 `npm ci && npm run build`로 `web/vendor/codemirror/codemirror.min.js`(전역 `CM`, IIFE, ES2019)를 만든다.
  배포·실행에는 npm이 필요 없다. 묶음에 들어간 패키지 목록과 라이선스는 빌드가 `licenses/codemirror/`에 쓴다.
- `CM.createEditor({parent, doc, lang, readOnly, dark, wrap, onChange, onSave, onCursor})`가 돌려주는 객체만 화면이 쓴다
  (`getText`·`setText`·`isDirty`·`markClean`·`selection`·`blockRange`·`gotoLine`·`setLanguage`·`setReadOnly`·`setWrap`·`setDark`…).
  `web/code.js`의 `codeEditorTab()`과 `codeRunPanel()`은 v1.16 Lab이 같은 편집기·실행 패널을 쓰도록 나눠 둔 입구다.
- 편집기는 줄 끝을 `\n`으로 다룬다. Python이 읽을 때 원래 줄 끝·인코딩을 알려 주고 저장할 때 되돌린다.

## 파일 읽기·저장 (`code_workspace`)

| 단계 | 하는 일 |
|---|---|
| 경로 | `clean_rel`: 상대 경로만, `..`·절대 경로·드라이브·UNC·제어 문자 거절 → `resolve`: `realpath`가 작업 폴더의 `realpath` 안인지 |
| 읽기 | `O_NOFOLLOW`(POSIX)로 열고, 연 핸들의 장치·inode와 다시 구한 실제 경로를 비교, 8MB 상한, 바이너리 판정, 인코딩(BOM·UTF-8·CP949) |
| 응답 | `text`(\n), `encoding`, `newline`, `mixed_newlines`, `final_newline`, `hash`(SHA-256), `readonly`+`reason`(1MB 초과·인코딩 불명·쓰기 권한 없음) |
| 저장 | 디스크 해시 ≠ `base_hash`면 `ConflictError` → 같은 폴더 임시 파일에 쓰기·fsync → 권한 복사 → `os.replace` |

## 변경 제안과 적용 (`code_diff`)

```python
@dataclass
class ChangeProposal:
    proposal_id: str; file_path: str; base_hash: str
    original_content: str; proposed_content: str; encoding: str
    reason: str; title: str; source: str; thread_id: str
    status: str          # pending · applied · partial · edited · rejected · conflict · cancelled · auto
    hunks: list[Hunk]    # difflib.SequenceMatcher.get_grouped_opcodes(3) — 문맥 3줄 안의 변경은 한 덩어리
    accepted: list[int]; result_hash: str
```

- **일부 적용**(`apply_on_base`): 기준 줄 목록(`splitlines(keepends=True)`)을 앞에서부터 다시 짜며, 받아들인 덩어리는 새 줄, 나머지는 원래 줄.
  덩어리는 같은 기준에서 나와 겹치지 않으므로 문자열 찾아 바꾸기가 필요 없다. 줄 끝·마지막 줄 바꿈이 그대로 남는다.
- **충돌**: 적용 직전 디스크 해시 ≠ `base_hash`면 쓰지 않는다. 사용자가 '현재 파일에 맞춰 적용'을 고르면(`apply_on_current`)
  덩어리마다 `앞 문맥 + 바뀌기 전 줄 + 뒤 문맥`이 현재 파일에 정확히 한 번 나오는 자리를 찾고, 하나라도 없거나 겹치면 아무것도 쓰지 않는다.
- **중복**: `status == "pending"`일 때만 적용. 저장소(`ProposalStore`, 앱이 켜져 있는 동안만)는 같은 (파일, 기준 해시, 제안 내용)이 대기 중이면 새로 만들지 않는다.
- **미리보기**: Python은 `compile`, JSON은 `json.loads`로 결과의 문법 경고만 낸다(실행하지 않는다).

## 에이전트 연결

```
Agent._tool_write/_tool_edit → Agent._save(p, old, new, enc, title, reason)
   └ self.review(rel, old, new, title, reason, enc)      # Bridge._code_review_edit
        ├ None  → 예전 confirm("edit") 승인 창 → 승인 대기 중 파일이 바뀌었으면 쓰지 않음 → atomic_write
        └ dict  → Agent._reviewed(): applied·partial·edited·rejected·unchanged·conflict·cancelled를 관찰 글로
```

`_code_review_edit`가 `None`을 돌려주는 경우: Code 화면이 닫혀 있음, 안드로이드, Code 설정 '항상 승인 창으로'.
권한이 자동 허용(`auto_edit`·`auto_all`·이번 실행 동안 허용)이면 바로 적용하고 `auto`로 남긴다. 그 밖에는 제안을 만들고
`{"type":"code","kind":"proposal"}`을 보낸 뒤 Event를 0.5초마다 기다리며 `alive()`(중지 버튼)를 본다. 화면이 닫히면
(`code_set_active(false)`) 대기 중인 제안을 `cancelled`로 끝내고 `"fallback"`을 넘겨 예전 승인 창으로 묻는다.

## Git (`code_git`)

`git -c core.fsmonitor=false -c core.quotepath=off -c diff.external= --literal-pathspecs --no-pager <명령>`을 인자 목록으로 부른다.
`status --porcelain=v2 --branch -z`를 읽고, 작업 폴더가 저장소의 하위 폴더면 `rev-parse --show-prefix`로 그 안의 파일만 보인다.
경로는 `code_workspace`로 검사한 뒤 `--` 뒤에 둔다. 공개 함수는 `status`·`diff`·`diff_all`·`stage`·`unstage`·`commit`뿐이다.

## 실행 (`code_runner`)

- `code_run_check(command)` → 분석(네트워크·위험 동작)과 한 번 쓰는 승인 토큰(명령 SHA-256에 묶임, 5분) → 화면의 승인 창 →
  `code_run_start(command, token)`. 토큰이 없거나 명령이 다르면 실행하지 않는다.
- `Popen(shell=True)`(Windows cmd, POSIX `/bin/sh` + 새 세션), stdout+stderr를 한 통로로 읽는 스레드, 0.1초마다 모아 `run_output` 이벤트.
  출력은 `Masker`(알려진 비밀 값 + `privacy.redact_text`)를 거친다. 줄 단위로 내보내고, 줄이 끝나지 않은 출력은 0.5초 뒤 비밀 경계를 지켜 내보낸다.
- 중지·시간 초과·앱 종료(`Bridge._code_shutdown`): POSIX는 프로세스 그룹에 SIGTERM→SIGKILL, Windows는 `taskkill /T /F`.
- `RunRecord`(명령·작업 폴더·입력 파일·종료 코드·시간·출력 끝부분·소스 위치·목적)를 데이터 폴더 `code/runs.jsonl`에 한 줄씩 남긴다.
  v1.16 Lab은 이 기록을 실험 실행 기록으로, `codeRunPanel`을 실행 화면으로 다시 쓴다.

## 화면 이벤트 큐 (`ui_events`, B1)

| 항목 | 내용 |
|---|---|
| 넣기 | `Bridge._push(event)` → `EventPump.push` (잠금 안에서 deque에 넣고 바로 반환) |
| 보내기 | 데몬 스레드 하나가 앞에서부터 `window.evaluate_js("window.onBackendEvent(...)")` |
| 합치기 | 큐 맨 끝이 같은 키의 상태 이벤트일 때만 바꿔 끼움: 브라우저 상태(`type=browser`, `kind` 없음), `delta`(대화별), PO노트 `level`·`download`, 업데이트 `progress` |
| 상한 | 1000개를 넘으면 합칠 수 있는 이벤트부터 오래된 것을 버리고, 5000개를 넘으면 가장 오래된 것부터 버린다(화면이 멈춘 경우) |
| 끝내기 | `run_app`의 finally에서 `stop()` — 남은 이벤트를 버리고 스레드를 1초까지만 기다린다 |

## 플랫폼

| | Windows | macOS | 안드로이드 |
|---|---|---|---|
| 편집·저장·찾기·묻기 | ○ | ○ | ○ |
| 변경 검토(덩어리) | ○ | ○ | ✕ (승인 창) |
| Git | ○ (git 설치 시) | ○ | ✕ |
| 실행 패널 | ○ cmd | ○ /bin/sh | ✕ |

안드로이드는 `browser_api.android_factory`가 있으면 안드로이드로 보고 `code_state().features`에서 끈다. 모듈은 모두 APK에 들어간다
(`android/app/build.gradle.kts`, Chaquopy Python 3.11).

## Code 에이전트 (1.16)
| 파일 | 하는 일 |
|---|---|
| `code_agent.py` | `TaskStore`(작업 세션 JSON, 원본 백업), `CodeAgent(agent.Agent)`(plan 단계, 코딩 지침, `run`을 RunManager로), `CodeAgentApi` 믹스인(`code_agent_*`) |
| `web/code-agent.js` | Code 화면 맨 앞 '작업' 탭(`kind: "agent"`, 닫지 않음): 작업 목록·승인 방식·진행 기록·계획·바뀐 파일·되돌리기·입력 |

- 흐름: `code_agent_start(text, task_id)` → 작업 JSON에 지시 추가 → 뒤 스레드 `_ca_work`에서 `CodeAgent.run(이전 대화, 지시)` →
  `on_tool`·`on_plan`·`on_run`·`review`가 작업 JSON을 고치고 `{"type": "code", "kind": "agent_*"}` 이벤트를 보낸다 → 끝나면 답을 대화에 넣고 `agent_done`.
- 파일 수정: `Agent._save` → `review` 콜백(`_ca_review`). '수정 자동'이면 원본 백업 → 원자적 쓰기 → `{"status": "applied", "diff"}`. '모두 묻기'면 None → 예전 승인 창.
- 한 번에 하나의 작업만 돈다. 채팅 응답을 기다리는 중에는 시작하지 않는다. 앱이 닫히면 `_ca_shutdown`이 멈춘다.
