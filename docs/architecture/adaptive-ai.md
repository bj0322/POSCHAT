# Adaptive Hybrid AI Engine 구조 (1.17)

요청마다 **로컬 AI(Ollama)**, **경량 Cloud 모델**(Claude Haiku 5.5·GPT-5 mini 등, 선택), **프런티어 모델**(설정의 기본 Cloud 모델) 중 하나를 고르고,
로컬·경량 모델의 답을 규칙으로 검증해 필요하면 위 단계로 올린다. 목표는 최소 비용이 아니라 **품질 제약 아래에서 Cloud 비용을 줄이는 것**이다.
기본은 꺼짐(`config["adaptive"]["enabled"] = false`)이라 켜기 전에는 1.16과 똑같이 대화마다 고른 Cloud 모델만 쓴다.

```
사용자 ─▶ Agent._ask(prompt, purpose)
            │ engine 없음(꺼짐·직접 고른 Cloud 모델) ──▶ api.ask (1.16과 같음)
            ▼
      AdaptiveEngine.ask
        1 analyze()      작업 유형·난이도·민감 정보·문맥 길이·이미지·첨부·부작용
        2 route()        규칙 제약 → 의미 분류 → 측정 성공률·비용   ─▶ local | cloud | none
        3 tier()         (경량 모델을 켰을 때) cloud ─▶ light | light+상담 | frontier
        4 실행·검증       local: Ollama 스트리밍 → QualityGate → (형식 문제면 같은 모델로 한 번 더)
                          light: 경량 모델 → (<<CONSULT>>면 프런티어에 짧게 묻고 다시) → QualityGate
        5 승격(cascade)  local ─▶ light ─▶ frontier (정책·상한·예산이 허용할 때만)
        6 기록           telemetry: routing_decision · local_inference · cloud_inference · quality_check · escalation · consult · routing_failure
```

## 모듈과 책임
| 모듈 | 책임 |
|---|---|
| `local_ai.py` | Provider. `LocalModelProvider`(is_available·health_check·list_models·capabilities·generate·stream) 꼴과 `OllamaProvider`(Ollama 기본 API `/api/*`), 주소 정책 `check_endpoint`, 받기 전 확인 `pull_preview`, 이 PC 자원 `system_resources`·`memory_budget`·`estimate_memory`. llama.cpp 서버는 같은 꼴의 클래스를 더하면 된다(이번에는 번들하지 않음) |
| `adaptive_router.py` | Analyzer(`analyze`, `semantic`, `sensitive`, `estimate_tokens`)·Policy(`POLICIES`, `LOCAL_ELIGIBLE`, `LIGHT_DIRECT`, `FLOORS`)·Router(`route`, `tier`)·측정 기록(`record_outcome`, `success_rate`, 데이터 폴더 `adaptive/stats.json`) |
| `quality_gate.py` | QualityGate: 작업별 규칙 검증(`check`, `area_for`) |
| `adaptive_engine.py` | Cascade(`AdaptiveEngine`: 실행·다시 하기·승격·상담·상한)·`LocalRuntime`(연결·모델·기능·자원 캐시)·설정 기본값(`settings`)·Metrics(`summary`, `budget_state`) |
| `adaptive_api.py` | 화면 API(`AdaptiveApi` 믹스인): 정책 창·로컬 모델 관리·대화별 엔진 만들기·프런티어 세션 저장·Local Only 차단(`api.cloud_guard`) |
| `web/adaptive.js`, `web/adaptive.css` | 정책 창, 대화 모델 목록의 '자동'·'로컬 · 모델', 답변 아래 라우팅 표시·펼친 이유, 받는 중 '검증 전'·'상담 중' 표시 |

## 호출 목적(purpose)
`Agent._ask(prompt, purpose=…)`: `chat`(일반 답) · `memory_extract` · `profile` · `agent_step`(다음 단계 JSON) · `agent_convert` · `agent_final` ·
`code_agent_step`(Code 에이전트) · `po_note`(PO노트 노트 만들기) · `thread_summary`(대화 요약). 분류는 앱의 지시문이 아니라 사용자 요청 글(`task_text`)로 한다.
`agent_step`·`code_agent_step`은 파일·명령·외부 쓰기로 이어지므로 '중요·위험'이고 Local Only가 아니면 언제나 프런티어로 간다.

기능별 첨부는 `connectors.wrap_untrusted`의 출처 이름으로 알아본다: `웹페이지`(Browser), `논문 PDF`(Paper), `Lab 실험 기록`(Lab), `작업 폴더 파일`·`명령 출력`(Code).
그래서 Browser·Paper·Code·Lab의 '채팅에 첨부해 묻기'는 따로 고치지 않아도 알맞은 작업 유형과 검증 영역을 얻는다.

## 라우팅 알고리즘
1. **규칙(제약, 비용보다 먼저)**: Local Only → Cloud 제외. 개인정보 설정(민감 정보·첨부를 Cloud로 보내지 않음) → 로컬만.
   이미지 + 로컬 vision 없음, 입력 > 로컬 문맥의 90%, 메모리 부족 → 로컬 제외. 주간 예산·요청당 크레딧 한도 → Cloud 제외(근거 있는 비용만).
   보낼 곳이 없으면 `provider="none"`으로 오류를 알린다(조용히 다른 곳으로 보내지 않는다).
2. **의미 분류**: 규칙 낱말에 걸리지 않으면 글자 3개 n-gram 코사인으로 작업별 예시와 비교한다. 1위 비슷함 < 0.10 또는 1·2위 차이 < 0.02면
   '분포 밖(ood)'으로 보고 Balanced·Quality에서는 Cloud. 비슷함은 답 품질이 아니다(라우팅에만 쓴다).
3. **품질·비용**: 정책표(`LOCAL_ELIGIBLE`)가 허용한 (작업, 난이도)만 로컬 후보. 측정 표본이 20개 이상이면 측정 성공률이 정책 하한
   (Economy 80%·Balanced 90%·Quality 95%) 이상일 때만 로컬. 표본이 적으면 규칙 기본값(Quality는 Cloud).
4. **3단계(tier)**: 경량 모델을 켰으면 Cloud로 정한 요청을 다시 나눈다. 중요·위험 → 프런티어. `LIGHT_DIRECT`(Economy: 어려움까지,
   Balanced·Quality: 보통까지) → 경량 모델 혼자. 더 어려우면 Economy·Balanced에서 상담을 켰을 때 경량 모델 + 상담, 아니면 프런티어.

외부 라이브러리 검토(2026-10 PyPI 기준): semantic-router 1.1.1(MIT)은 openai·cohere·mistralai·pydantic·tiktoken 등을, fastembed 0.9.0(Apache-2.0)은
onnxruntime과 Hugging Face 모델 내려받기를, routellm 0.2.0(PyPI에 라이선스 표시 없음)은 torch·transformers를 요구한다. 안드로이드(Chaquopy)에서 쓸 수 없고
설치 용량이 커서 이번에는 의존성을 더하지 않고 같은 꼴의 경량 라우터를 직접 만들었다. RouteLLM의 학습된 라우터는 영어·Chatbot Arena 기준이라
POSCHAT의 한국어·연구 작업에 그대로 맞는다고 보지 않았다. 측정 기록(`stats.json`)과 벤치마크가 쌓이면 임베딩 분류기를 같은 자리에 넣을 수 있다.

## QualityGate
`check(area, answer, ctx)` → `GateResult(ok, verifiable, failures, checks, retryable, detail)`. 모델이 말한 '확신'은 보지 않는다.
| 영역 | 확인 |
|---|---|
| 공통 | 빈 답, 길이 제한으로 끊김(`done_reason=length`), 같은 줄 반복, 한국어 요청에 한국어 답(코드 블록 제외), JSON 요구 시 JSON |
| `agent_step` | `{"action": …}` JSON이고 action이 허용 목록 안 |
| `browser` | 답의 주소가 원문에 있는지, 따옴표 인용이 원문에 있는지 |
| `paper` | 쪽 번호가 문서 범위 안, 측정값처럼 보이는 수(소수·단위·100 이상, 'Run 7'·'표 2' 같은 번호 제외)가 원문에 있는지, 인용 |
| `lab` | 수치가 기록에 있는지. 없으면 '추정·계산'이라고 밝혔을 때만 통과(`unsupported_number_disclosed`) |
| `code` | Python·JSON 코드 블록 문법 |
형식 문제(빈 답·JSON·단계 형식·반복·끊김)만 `retryable`이라 같은 로컬 모델로 한 번 더 한다(`local_retries`). 근거 문제는 다시 해도 나아지지 않아 바로 승격을 본다.

## Cascade와 상담
- 승격 조건: `escalation` 켜짐, Local Only 아님, Cloud 키 있음, 주간 예산 안, 요청당 `max_escalations`(0~2, 기본 2: 로컬 → 경량 → 프런티어),
  실행 하나에 `RUN_ESCALATION_CAP`=6. 승격 대상은 경량 모델이 허용되는 일이면 경량 모델, 아니면 프런티어.
- **임시 답을 조용히 덮지 않는다**: 받는 동안 화면에 '로컬 답 · 검증 전'을 붙이고, 승격하면 '검증 실패 → Cloud로 다시 답하는 중'과 접은 임시 답을 보인다.
  최종 메시지의 `routing.provisional`에 임시 답 앞부분(4000자)을 남겨 펼쳐 볼 수 있다. 승격 중 Cloud도 실패하면 임시 답을 '검증 실패' 표시와 함께 돌려준다.
- **상담**: 경량 모델 프롬프트 끝에 `CONSULT_RULE`을 붙인다. 경량 모델이 `<<CONSULT>>{"question", "context"}` 한 줄만 쓰면 앱이 그 질문(1,500자)과
  발췌(4,000자, 외부 데이터로 감쌈)만 프런티어에 보낸다. 이 대화의 지난 상담 기록(최근 6개, 질문 500자·답 1,500자)을 붙여 프런티어가 앞의 결론을 잇는다.
  프런티어의 답은 '참고 자료'로 경량 모델 맥락에 넣어 최종 답을 받는다. 상담 줄은 화면에 흘리지 않는다. 요청당 `consult_max`(0~2), 실행당 6번.
  형식이 틀리거나 상담 뒤에도 답하지 못하면 프런티어가 전체를 다시 답한다.
- **부작용 중복 방지**: `ask()`는 글만 돌려주는 순수한 호출이다. 다시 하기·승격·상담은 모두 그 안에서 끝나고, 에이전트는 돌려받은 단계 하나를 한 번만 실행한다
  (`test_retries_and_escalation_never_repeat_a_file_write`). 모델이 바뀌어도 파일 수정·명령·외부 쓰기는 기존 승인 창을 그대로 거친다.

## 비용 계산
- Cloud 요청 하나: `telemetry.credit_estimate(모델, 입력 토큰 추정, 600)` — 앱 안내에 근거가 있는 POSTECH 크레딧(Claude Sonnet·Opus 5.5)과 사용자가
  `config["telemetry"]["rates"]`에 넣은 값만. 근거가 없으면 `None`('추정 불가')이고 예산·한도 계산에 넣지 않는다.
- 로컬은 **Cloud API 비용만 0**이다. 전기·하드웨어 비용은 재지 않고 따로라고 화면에 밝힌다. POSTECH 크레딧과 Claude API 요금(USD)은 바꾸거나 더하지 않는다.
- 토큰은 글자 수로 어림한다(한글 1자 ≈ 1토큰, 그 밖 3.5자 ≈ 1토큰). 3단계 통계의 '프런티어 입력 토큰 줄임'은 이 추정치다.

## 대화 모델과 상태
- 대화의 `model`: `"auto"`(엔진이 고름), `"local:<모델>"`(그 로컬 모델만, 실패해도 Cloud로 바꾸지 않음 — `manual_fallback`을 켠 경우만),
  그 밖의 Cloud 모델 ID(엔진을 거치지 않음). 자동 선택을 켜면 새 대화는 `auto`로 시작한다. 끄면 `auto`·`local:` 대화는 기본 Cloud 모델로 돌아간다.
- 대화에 남는 것: 답변 메시지의 `routing`(요약), `frontier_session`(상담 기록). Python → 화면 이벤트 `{"type": "route", "kind": provisional|retry|escalating|consulted|verified|final|unverified}`.
- 모든 모델 호출은 작업 스레드에서 하고 화면 이벤트는 `Bridge._push`(EventPump)로 보낸다(B1 원칙 유지).

## 플랫폼
| | Windows·macOS | Android |
|---|---|---|
| 로컬 AI(Ollama) | 연결·모델 관리·추론(사용자가 설치) | 쓸 수 없음(`local_ai.SUPPORTED=False`, 화면에 표시) |
| 라우터·검증·3단계·통계 | 됨 | 됨(로컬 후보 없이 Cloud 경량·프런티어만) |
| 모듈 | 공유 모듈(`android/app/build.gradle.kts`) | 같음 |
