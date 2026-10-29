# POSCHAT Code 보안 (1.15)

[보안 설계(1.10)](security.md)의 원칙(웹페이지·PDF·외부 데이터에 앱 권한을 주지 않는다, 쓰기·실행은 승인)을 Code 화면에 적용한 내용이다.
구조는 [architecture/poschat-code.md](architecture/poschat-code.md).

## 누가 코드 API를 부를 수 있나
- 코드 API(`code_*`)는 `main.Bridge`의 js_api이고, 앱 화면(`web/index.html`)만 부를 수 있다.
- 브라우저의 웹페이지 뷰(WebView2·WKWebView·안드로이드 WebView)에는 js_api·host object·메시지 통로가 없다(1.13, `tests/browser_spike.py`가 확인).
- PDF는 PDF.js로 그리며 `isEvalSupported: false`, 스크립트·양식을 실행하지 않는다(1.14).
- MCP 결과·웹페이지 글·논문 글·Git 출력·파일 내용·명령 출력은 AI에게 넘길 때 `connectors.wrap_untrusted`로 감싸고, 그 안의 닫는 표시는 무력화한다.
  그래서 파일이나 출력 안의 "이전 지시를 무시하고…"는 지시가 아니라 자료로 읽힌다.
- 에이전트가 파일을 고치는 길은 예전과 같다(`write`·`edit` → 승인). Code 화면은 그 승인을 덩어리 단위로 하는 다른 창일 뿐, 새 권한을 주지 않는다.

## 작업 폴더 밖 차단 (`code_workspace`)

| 공격 | 막는 방법 | 시험 |
|---|---|---|
| `../`, `a/../../x` | `clean_rel`이 `..` 조각을 거절 | `test_dotdot_absolute_and_odd_paths_are_refused` |
| 절대 경로·`C:\`·`\\server\share`·`~` | 거절 | 같음 |
| 심볼릭 링크·Windows 정션 | `realpath`가 작업 폴더 `realpath` 안인지 확인. 트리·찾기는 링크를 따라 들어가지 않음 | `test_symlinks_pointing_outside_are_refused` |
| 확인과 열기 사이 바꿔치기(TOCTOU) | POSIX `O_NOFOLLOW`, 연 뒤 실제 경로 재확인과 장치·inode 비교, 저장 직전 폴더 재확인, 링크 파일에는 저장하지 않음 | `test_file_swapped_for_a_link_after_the_check_is_refused` |
| URL 인코딩(`%2e%2e%2f`) | 풀지 않는다. 그런 이름의 파일(작업 폴더 안)일 뿐 | `test_backslashes_and_url_encoding_stay_inside` |
| NUL·제어 문자·긴 이름·Windows 예약 이름 | 거절 | |
| 권한 밖 파일 | 운영체제가 막는다(앱은 사용자 권한으로만 동작). 쓰기 권한이 없으면 읽기 전용으로 연다 | |

남는 위험: TOCTOU는 "가능한 범위의 방어"다. 공격자가 작업 폴더 안에서 동시에 링크를 바꿀 수 있는 PC라면 아주 짧은 틈은 남는다.
Windows에는 `O_NOFOLLOW`가 없어 연 뒤 확인에 기댄다.

## 데이터 무결성
- 저장·적용은 임시 파일 + `os.replace`. 도중에 실패하거나 앱이 꺼져도 원본이 남고, 임시 파일은 지운다.
  원본 권한을 옮기고 새 파일은 umask대로(보통 0644) 만든다. 쓰기 권한이 없는(읽기 전용) 파일은 바꾸지 않는다(에이전트 승인 창 경로 포함).
- 변경 제안은 만든 작업 폴더에 묶인다. 검토 중에 작업 폴더를 바꿔도 다른 폴더의 같은 이름 파일에 쓰지 않는다.
- 이름 바꾸기·지우기는 대상이 든 폴더의 실제 경로도 작업 폴더 안인지 본다(밖을 가리키는 폴더 링크를 거쳐 밖의 파일을 옮기지 못한다).
- 열 때의 SHA-256과 디스크가 다르면 덮어쓰지 않는다(편집기 저장·변경 제안 적용·에이전트 승인 창 모두).
- 변경 제안은 받아들이기 전에는 파일에 쓰지 않고, 앱이 꺼지면 사라진다(적용되지 않음). 같은 제안은 두 번 적용하지 않는다.
- 지우기는 데이터 폴더의 `code-trash/<시각>/`으로 옮긴다. 비어 있지 않은 폴더는 지우지 않는다.

## Git (`code_git`)
- 셸 없이 인자 목록, 경로는 검사 후 `--` 뒤, `--literal-pathspecs`(경로 마법 끔). `-rf`·`--output=x`·`:(glob)*` 같은 이름도 그냥 파일 이름이다.
- 저장소 설정으로 프로그램이 실행되는 길을 끈다: `core.fsmonitor=false`, `diff.external=`, `--no-ext-diff`, `--no-textconv`, 페이저 끔, `GIT_TERMINAL_PROMPT=0`.
  저장소 안의 설정(`.git/config`·worktree 설정과 그 `include`)에 적힌 `filter.*.clean/smudge/process`, `diff.*.textconv/command`,
  `gpg.*program`은 매 호출마다 `-c`로 비운다(압축 파일·공유 폴더로 받은 저장소가 diff·add만으로 프로그램을 실행하지 못하게).
  사용자 전역·시스템 설정(예: git-lfs)은 그대로 쓴다.
- 화면에서 부를 수 있는 것은 status·diff·add·restore --staged(또는 rm --cached)·commit뿐이다. `reset --hard`·`clean`·강제 checkout·push·이력 고치기는 없다.
  커밋은 사용자가 스테이지한 변경만, 확인 창을 거쳐 한다. 저장소에 커밋 훅(pre-commit 등)이 있으면 확인 창에 이름을 보이고,
  '이번 커밋에서 훅을 실행하지 않기(--no-verify)'를 고를 수 있다(기본은 실행 — 린트 훅을 쓰는 사용자를 위해).

## 명령 실행 (`code_runner`)
- 실행은 화면의 승인 창을 거친다. 승인 창은 명령·작업 폴더·셸·제한 시간·입력 파일·네트워크 사용 가능성·위험할 수 있는 동작을 보인다.
  Python 쪽은 한 번 쓰는 승인 토큰(명령의 SHA-256에 묶임, 5분)이 있어야 실행한다.
- **작업 폴더는 시작 위치일 뿐 샌드박스가 아니다.** 명령은 사용자 계정 권한으로 PC의 다른 파일·네트워크에 닿는다. 승인 창에 이를 적는다.
- 이름에 key·token·secret·password·credential·auth·cookie·session이 든 환경 변수는 넘기지 않는다. 출력은 화면·기록에 남기기 전에
  앱이 아는 비밀 값(설정의 키·커넥터 토큰·비밀 이름 환경 변수 값)과 흔한 키 모양(sk-…, ghp_…, Bearer … 등)을 `[가림]`으로 바꾼다.
  출력 조각 경계에 걸친 비밀도 가린다(`test_masker_handles_a_secret_split_across_chunks`).
- 제한: 시간(기본 600초, 10~3600초), 화면 출력 2MB, 기록 64KB, 동시 실행 4개. 중지·시간 초과·앱 종료 때 프로세스 트리를 끝낸다
  (POSIX: 새 세션의 프로세스 그룹 전체, Windows: 작업 개체(Job Object)로 묶어 한꺼번에, 실패하면 `taskkill /T`).
  셸은 끝났는데 뒤에 띄운 하위 프로세스가 남아 출력 통로를 쥐고 있으면 2초 뒤 끝내고 실행을 마친다(프로세스를 남기지 않는다).
- 줄 바꿈 없이 멈춘 출력을 내보낼 때는 공백에서 잘라, 키 모양 글자가 반으로 나뉘어 일부만 가려지는 일을 막는다.
- 위험 동작 판정은 도움말일 뿐 차단이 아니다(셸 문법을 완전히 해석하지 않는다). 승인 창의 명령을 직접 읽고 승인하세요.
- 에이전트의 `run`은 예전처럼 따로 승인한다(파일 수정 승인과 분리).

## 터미널 (`terminal`, 1.18)
- 코드 화면 아래의 대화형 셸(Windows ConPTY는 pywinpty, macOS·Linux는 pty). 사용자가 직접 키를 치는 터미널이라 승인 창이 없다.
  에이전트·웹페이지·PDF는 터미널을 열거나 쓸 수 없다(`code_term_*`는 앱 화면의 js_api에만 있고, 에이전트 도구가 아니다).
- 셸은 작업 폴더에서 시작하지만 **샌드박스가 아니다.** 사용자 계정 권한으로 돈다.
- 환경 변수는 명령 실행과 같은 규칙으로 비밀 이름(`SECRET_ENV`)을 넘기지 않는다. 셸이 제대로 돌도록 `SSH_AUTH_SOCK`·`SESSIONNAME`·
  `DBUS_SESSION_BUS_ADDRESS`·`XDG_SESSION_*`만 예외로 넘긴다. 터미널 화면의 출력은 가리지 않는다(사용자 자신의 셸). 'AI에게 묻기'로
  채팅에 보낼 때만 제어 글자를 빼고 앱이 아는 비밀을 가린 뒤 외부 데이터로 감싼다.
- 6개까지 열고, 닫기·앱 종료 때 셸과 자식 프로세스를 끝낸다(POSIX: 세션의 프로세스 그룹에 SIGHUP→SIGKILL, Windows: `taskkill /T`).
- 키 입력은 화면이 하나씩 차례대로 보낸다(한 번에 64KB까지). 출력은 약 30ms마다 모아 화면 이벤트로 보내고, 끝부분 200KB만 메모리에 둔다.

## SSH 원격 작업 폴더 (`ssh_remote`·`remote_helper`, 1.18)
- 연결은 사용자가 코드 화면에서 고른 서버에만 한다. 에이전트·웹페이지·PDF는 연결을 만들 수 없다(`code_ssh_*`는 앱 화면의 js_api에만 있다).
  에이전트는 사용자가 연 원격 작업 폴더 안에서만 로컬과 같은 도구·같은 승인 규칙으로 일한다.
- 호스트 키: `~/.ssh/known_hosts`와 앱의 `ssh/known_hosts`로 확인한다. 처음 보는 서버는 지문을 보이고 사용자가 받아들일 때만 앱의 파일에
  남긴다. 알던 서버의 키가 다르면 연결하지 않는다(덮어쓰기 단추가 없다).
- 암호·OTP는 그 연결의 인증에만 쓰고 저장·기록하지 않는다. 키 암호문은 불러온 키를 앱을 끌 때까지 메모리에 둔다.
- 서버에서는 작은 도우미(`remote_helper`와 `code_workspace`·`code_git`·`code_project` 소스)를 python3로 메모리에서 실행한다(파일을 남기지 않음).
  그래서 작업 폴더 밖 차단·링크 검사·안전한 저장·외부 변경 감지·Git 안전 설정이 서버의 파일 시스템에서 그대로 지켜진다.
  도우미는 사용자의 서버 권한으로 돌고, 연결이 끊기면 띄운 명령을 끝내고 스스로 끝난다.
- 서버에서 실행하는 명령(에이전트 `run`·`!명령`)에도 비밀 이름의 환경 변수를 넘기지 않는다(서버의 환경에서 뺀다). 출력의 비밀 가리기도 같다.
- 원격 경로(`remote_fs.RPath`)는 일부러 `os.fspath`를 지원하지 않는다: 원격 경로로 같은 이름의 로컬 파일을 건드리는 실수를 막는다.

## AI에게 보내는 내용
- 사용자가 누른 범위(선택·블록·파일·고른 파일 최대 6개, Git 차이, 실행 출력)만 첨부한다. 작업 폴더 전체를 보내지 않는다.
- 첨부는 보낼 때 지금 고른 모델 API(POSTECH GenAI 또는 Claude)로 전송된다. 개인정보·비밀이 든 코드는 보내기 전에 확인하세요.

## Code 에이전트 (1.16)
- 에이전트 루프는 채팅 에이전트(`agent.Agent`)와 같다: 같은 도구, 작업 폴더 밖 차단(`_resolve`·`code_workspace.resolve`), 외부 데이터 감싸기.
- **파일 수정**: 기본 '수정 자동'이면 승인 없이 쓰지만, 처음 고치기 전에 원본을 데이터 폴더 `code/tasks/<작업>/backup/`에 보관하고, 읽은 내용과 디스크가 다르면 쓰지 않는다
  (`test_file_changed_after_read_is_not_overwritten`). 되돌리기는 에이전트가 쓴 내용(SHA-256)이 그대로일 때만 한다(`test_new_file_revert_deletes_and_user_changes_are_kept`).
  '모두 묻기'면 승인 창(`test_ask_mode_asks_before_edits`).
- **실행으로 이어지는 파일**: 에이전트(채팅·Code)는 `.git` 안(`.git/config`의 `core.fsmonitor`·`core.hooksPath`, `.git/hooks`)을 고치지 않는다 — 다음 git 명령이나
  편집기의 git 상태 확인 때 명령 승인 없이 프로그램이 돌기 때문이다(`agent._in_git_dir`: Windows의 `.GIT.`·`.git::$INDEX_ALLOCATION`·`GIT~1` 꼴도 막음).
  `.husky/`·`.githooks/`·`.pre-commit-config.yaml`·`lefthook.yml`·`.envrc`·`.vscode/tasks.json`·`settings.json`·`launch.json`·`.idea/`·`.devcontainer/`·`.gitattributes`·`.gitmodules`는
  '수정 자동'이어도 승인 창으로 묻는다(`code_agent.AUTO_RUN_FILES`, `test_git_dir_is_never_written_and_auto_run_files_ask`).
- **명령**: 채팅 설정의 자동 허용과 관계없이 매번 묻고 '이번 실행 동안 허용'이 없다(`test_task_plans_edits_runs_and_records`, `test_denied_command_is_not_run`).
  실행은 `code_runner.RunManager`(비밀 환경 변수 빼기·출력 가리기·제한·프로세스 트리 끝내기, `test_secrets_are_not_passed_to_commands`, `test_stop_kills_running_command`).
- 작업 기록(`code/tasks/*.json`)에는 진행 단계와 출력 끝부분이 남는다. 출력은 가린 뒤의 것이다. 작업 ID는 형식을 검사해 다른 경로를 열지 못한다(`test_guards`).

## Code 에이전트 2 (1.17.1)
- **권한 모드**: 기본은 그대로 '수정 자동 · 명령은 묻기'다. '계획 모드'는 write·edit·multi_edit·run을 막는다(`test_plan_mode_reads_but_never_edits_or_runs`).
  '전체 자동'은 명령을 묻지 않지만 `code_runner.analyze`가 위험한 동작(삭제·초기화·강제 푸시 등)이나 네트워크(curl·git push 등)로 본 명령은 승인 창으로 묻는다
  (`test_full_auto_runs_commands_but_asks_for_dangerous_ones`). 셸 명령을 완전히 분석할 수는 없으므로 전체 자동은 믿는 저장소에서만 쓰도록 화면에 적었다.
- **다시 묻지 않기 규칙**: 사용자가 승인 창에서 고를 때만 생긴다(작업 폴더별, 최대 50개). 실행 파일 + 하위 명령·스크립트까지의 접두어이고, 해석기 이름만 남는 규칙(`python`, `node`, `bash`…)은
  만들지 않는다. 규칙이 있어도 셸 연결(`&&` `||` `;` `|` `>` `<` `` ` `` `$(`)·위험·네트워크가 있는 명령은 묻는다
  (`test_remember_rule_skips_the_next_confirm_but_not_chained_commands`, `test_command_prefix_and_rules`).
- **프로젝트 지침(AGENTS.md·CLAUDE.md)·Git 변경(/review)**: 저장소의 글이므로 '지시가 아닌 프로젝트 지침/데이터'로 표시해 붙이고, 앱의 승인·작업 폴더 밖 금지 규칙보다 앞서지 않는다고 적는다.
  지침이 명령 실행을 시켜도 권한 모드의 승인은 그대로다.
- **격리 작업 공간**: 데이터 폴더의 git worktree에서 일하고, 적용은 사용자가 누를 때만 `git apply --check` → 적용(→ `--3way`)으로 한다. 3-way에서 겹치면
  건드린 파일 내용과 인덱스(`ls-files -s` → `update-index --index-info`)를 적용 전으로 되돌려 충돌 표시를 남기지 않는다(`test_isolated_worktree_discard_and_conflict`).
  '브랜치로 남기기'는 worktree에서 `commit --no-verify`(훅이 승인 없이 돌지 않게)로 커밋한다. Git 이름·메일이 없으면 POSCHAT 이름을 쓴다. worktree도 작업 폴더와 같은 경로 차단·`.git` 수정 금지를 받는다.
- **백그라운드 명령**: 같은 RunManager(비밀 빼기·출력 가리기·동시 4개)로 돌고, 작업이 끝나거나 멈추면 끝낸다(`test_background_jobs_stop_when_the_task_ends`).
