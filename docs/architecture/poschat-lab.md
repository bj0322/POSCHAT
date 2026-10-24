# POSCHAT Lab 구조 (1.16)

사용법은 [../lab-guide.md](../lab-guide.md).

## 파일
| 파일 | 하는 일 |
|---|---|
| `lab_store.py` | 실험·Run 저장소(SQLite `<데이터 폴더>/lab/lab.db`, WAL, 외래 키). 형식 버전 `PRAGMA user_version`(지금 1). 더 새 형식이면 열지 않고 업데이트를 안내. `recover()`·`recover_once()` |
| `lab_results.py` | 결과 파일 읽기(CSV·TSV·JSON·JSONL·로그), 숫자 판정(`to_number`: ok·empty·nan·inf·text), 단위(`split_unit`), 통계·표본(`stats`·`series`), 지표 뽑기(`extract`), 비교(`compare`). 저장소·화면과 무관한 순수 함수 |
| `lab_api.py` | `LabApi` 믹스인(`main.Bridge`가 상속). 실행 승인·시작, 재현성 기록(`capture_code`·`capture_env`), 가져오기, 미리 보기, 지표, 그래프 점, 비교, AI 묻기 첨부, 프로젝트 기억 |
| `web/lab.js`, `web/lab.css` | 화면. hub.js의 `PAGES.lab`로 등록되어 `#tool-view`(본문)에 열린다. 그래프는 SVG로 직접 그린다 |
| `code_runner.py` | 실행기(1.15)를 그대로 쓴다. 1.16에서 `start(..., extra_env=, on_exit=)`를 더함 |

## 데이터 구조
```
experiments(id "exp-xxxxxxxx", name, project, description, workspace, tags[], settings{}, created, updated)
  settings = {kind: command|python|notebook, command, script, params{}, outputs[glob], timeout,
              metric_spec: [{file(glob), column | key, how, name, unit}]}
runs(id "run-xxxxxxxxxx", experiment_id → experiments ON DELETE CASCADE, seq(실험 안 1,2,3… UNIQUE),
     name, status, source(poschat|import|code), started, ended, seconds, command, command_template, cwd,
     params{}, code{}, env{}, inputs[], outputs[], exit_code, metrics{}, notes, log_tail, locations[], code_run_id, created, updated)
  status: queued · running · completed · failed · cancelled · interrupted · imported
  code  = {repo, top, commit, branch, remote(계정·토큰 뺌), changed[], changed_count, dirty, untracked[],
           diff_sha256, diff_bytes, patch_file(<lab>/files/<run>/uncommitted.diff, 2MB 이하)}
  env   = {os, machine, host_python, python, python_path, packages[] (pip freeze), packages_sha256,
           gpus[], cuda, variables{비밀 이름 제외, CUDA_·OMP_·PYTHONHASHSEED 등 + POSCHAT_PARAM_*}}
  outputs[] = {path(작업 폴더 기준 또는 절대), abs, size, mtime, sha256(50MB 이하), kind(csv·json·log·image…), copy?}
  metrics{이름} = {value(유한한 수), unit, source: {file, sha256, column|json_path|line, row, how, rows} | {manual: true}}
```
JSON 칸은 `allow_nan=False`로 쓴다(NaN·Inf는 기록에 들어가지 않는다). 한 번의 쓰기는 한 트랜잭션이다.

## 실행 흐름
1. 화면 `lab_run_check(exp, spec)` → 명령을 만든다(`build_command`: 파라미터 이름 검사, 값은 셸 따옴표, 노트북은 nbconvert). 승인 토큰 =
   `sha256("lab\n" + 명령)`(Code 실행 패널 토큰과 섞이지 않게 접두어), 5분, 한 번.
2. 사용자가 승인 → `lab_run_start(exp, spec, token)`: 같은 spec으로 명령을 다시 만들어 토큰과 맞는지 확인 → Run(queued) 만들기 →
   `capture_code`(git status/diff, 패치 사본) → 상태 running·시작 시각 → `RunManager.start(extra_env=파라미터, on_exit=_lab_finish)` →
   뒤 스레드에서 `capture_env`(pip freeze·nvidia-smi, 시간 제한).
3. 명령이 끝나면 `_lab_finish`(실행기 스레드): 상태 매핑(done→completed, failed/timeout/error→failed, stopped→cancelled), 출력 끝부분·소스 위치,
   결과 파일 수집(설정의 패턴, 실행 중에 바뀐 파일), 지표 규칙 적용 → `{"type": "lab", "kind": "run"}` 이벤트. 실행 출력은 Code와 같은 `run_output` 이벤트로 흐른다.
4. 앱이 실행 중에 꺼지면 다음에 Lab을 처음 열 때 `recover_once()`가 running·queued를 interrupted로 바꾼다(프로세스는 앱 종료 때 `RunManager.shutdown()`이 끝냄).

## 가져오기의 경로 제한
`lab_import`는 작업 폴더 안 파일 또는 이번 세션에 `lab_pick_files`(파일 고르기 창)로 사용자가 고른 파일만 받는다. 화면이 임의 경로를 넘겨 다른 파일을 읽게 하지 못한다.

## AI 분석
`lab_ask`는 실험 설명과 고른 Run(최대 12개)의 상태·명령·파라미터·코드 버전·환경 요약·지표와 출처·결과 파일·메모·출력 끝부분, 비교 경고를 Markdown으로 만들어
`connectors.wrap_untrusted`로 감싼 채팅 첨부로 돌려준다. 질문 앞에 분석 규칙(`ANALYSIS_RULES`)을 붙인다. 보내기는 사용자가 채팅에서 한다(지금 고른 모델·API).
에이전트 도구에는 Lab 실행이 없다: AI는 실험을 실행하지 않는다.

## 시험
저장소는 `tests/test_lab_api.py`의 StoreTests, `tests/test_lab_results.py`, `tests/test_lab_api.py`, `tests/test_lab_ui.py`(Chromium).
