# Adaptive AI 평가 방법 (1.17)

## 데이터셋 `tools/data/adaptive_benchmark.json`
`python tools/adaptive_benchmark_data.py`로 만든다(같은 입력이면 같은 파일, `test_file_matches_the_generator`가 확인). 예문은 직접 쓴 짧은 글이라
실제 논문·웹페이지·개인 정보·저작물이 없다.

| 분야 | 개수 | 내용 |
|---|---:|---|
| general | 50 | 요약 10·번역 10·감정 분류 10(JSON)·정보 추출 10·짧은 사실 질문 10 |
| browser | 30 | 10개 웹페이지(직접 쓴 글)에서 요약·값 찾기, 일부는 비판적 분석 |
| paper | 44 | 논문 발췌 3개의 값·쪽 번호·계산(허용 오차)·요약 22, 연구 추론 22(사람 평가) |
| code | 44 | 출력·설명 12, 함수 작성 12(시험 assert), 버그 고치기 20(시험 assert) |
| lab | 34 | CSV 3개(ADC 스윕·학습 곡선·칩 전력)에서 값·계산(허용 오차)·단위·통계 해석 |
| agent | 22 | 도구 목록과 목표 → 다음 단계 JSON(action·대상) |

224개, 한국어 요청 99%. 사례마다: `prompt`, `context`(기능이 감싸는 꼴), `expect`(evals 규칙 + `number{value, tol}`), `reference`(정답),
`verify`(검증 방법), `tolerance`, `difficulty`, `route_label`, `split`.
- `route_label`은 데이터를 쓴 사람이 작업 성격으로 정한 정답이다: `local_ok`(작고 검증 쉬운 일) / `cloud_needed`(연구 추론·코드 수정·에이전트·통계 해석·여러 문서 종합).
  라우터 코드에서 거꾸로 만들지 않았다.
- `split`: 분야 안에서 번갈아 dev 112 / test 112. **라우터 규칙은 dev의 틀린 사례만 보고 고쳤다.** test 값이 덜 낙관적인 추정이다.
- 정답이 적힌 사례는 정답이 자기 채점 규칙을 통과해야 한다(`test_references_pass_their_own_checks`, 129개 이상), 코드 정답은 시험을 통과(`test_reference_code_passes_its_tests`).
- 연구 추론 22개는 규칙으로 형식만 본다. 내용 품질은 사람 평가(1~5점)가 필요하다.

## 비교 구성 `tools/adaptive_benchmark.py`
| 구성 | 설명 |
|---|---|
| A cloud_only | 모든 요청을 프런티어로(기준) |
| B local_only | 모든 요청을 로컬로 |
| C rule | 규칙 라우터만(의미 분류 없음) |
| D adaptive | 규칙 + 의미 분류 |
| E cascade | D + QualityGate + 승격 |
| F tiered | 로컬 → 경량 Cloud → 프런티어, 검증·승격(앱의 `AdaptiveEngine` 그대로) |
| G consult | F + 상담(앱의 엔진 그대로) |

- `--offline`: 모델을 부르지 않고 라우팅만 평가한다(라우팅 정확도, 잘못 로컬로 보낸 비율, 놓친 로컬 비율, 로컬·경량·프런티어 비율, 프런티어 입력 토큰 비율 추정).
  품질은 재지 않는다.
- `--run`: 실제 모델로 돌린다. Cloud 비용이 드는 구성은 `--budget-calls N`(Cloud 호출 상한)과 `--yes`가 있어야 하고, 상한에 닿으면 그 자리에서 멈춘다(`중단`).
  `--repeats k`로 같은 요청을 k번 돌려 성공률의 표준편차(확률적 흔들림)를 잰다. `--run-code`를 켜면 코드 사례의 시험을 임시 폴더의 별도 Python(10초)으로 돌린다
  (믿을 수 없는 모델 출력을 실행하므로 기본 꺼짐). 벤치마크 호출은 앱의 사용량·진단 기록에 넣지 않는다.
- 지표: 작업 성공률(채점 1.0인 비율)·평균 점수·분야별 성공률, 로컬·경량 비율, 승격 비율, Cloud 호출 수, 크레딧 추정(근거 있는 모델만),
  프런티어·경량 입력 토큰 추정과 '모두 프런티어' 대비 줄임, 잘못 로컬로 보내 실패한 수, p50·p95 지연.

## 목표(달성 여부는 실제 실행으로만 판단)
- API 비용 30% 이상 절감, 핵심 작업 성공률 하락 2%p 이내, 잘못된 로컬 라우팅 감소, Local Only 위반 0건, 승인 없는 도구 실행 0건, 기존 기능 회귀 0건.
- Local Only 위반·승인 없는 도구 실행·회귀는 자동 시험으로 확인한다. 비용 절감과 성공률 차이는 사용자의 로컬 모델·Cloud 키로 `--run`을 돌려야 알 수 있다.
  결과는 [adaptive-ai-benchmark-results.md](adaptive-ai-benchmark-results.md).
