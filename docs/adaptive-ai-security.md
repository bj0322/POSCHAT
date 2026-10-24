# Adaptive AI 보안·개인정보 (1.17)

[보안 설계](security.md)의 원칙(웹페이지·PDF 같은 외부 콘텐츠에 앱 권한을 주지 않는다)은 그대로다. 1.17은 '어느 모델로 보낼지'만 정하고,
어떤 모델이 답해도 파일 수정·명령·외부 쓰기는 기존 승인 창을 거친다.

| 위협 | 대응 | 시험 |
|---|---|---|
| 로컬 AI 주소로 내부망·메타데이터 공격(SSRF) | 기본은 루프백만(`localhost`는 DNS 없이 127.0.0.1로). 다른 호스트는 '원격 허용'을 켜야 하고, 공개 인터넷은 https만. 링크 로컬(169.254.x)·0.0.0.0·멀티캐스트·`metadata.*`·100.100.100.200·IPv4 매핑 주소는 언제나 막음. 이름은 풀어서 나온 주소도 같은 규칙, 요청마다 다시 확인(DNS 리바인딩) | `EndpointPolicyTests` |
| 리다이렉트로 다른 곳에 보내기 | 모든 로컬 요청은 `allow_redirects=False`, 3xx면 오류 | `test_redirects_are_not_followed` |
| 키·프록시 자격 증명이 로컬 요청에 섞임 | 로컬 요청에는 API 키 헤더를 넣지 않고 `trust_env=False`(프록시·.netrc 안 씀) | `test_no_api_keys_or_proxy_credentials_reach_the_local_runtime` |
| 로컬 서버가 이상한 응답 | 줄 1MB·답 40만 자·응답 50MB 상한, JSON이 아니면 형식 오류, 끊기면 오류. 모델이 쓴 글은 권한 없는 글 | `test_garbage_…`, `test_huge_reply_is_capped` |
| Local Only인데 Cloud 호출 | 라우터가 Cloud 후보를 빼고, 마지막 안전장치로 `api.cloud_guard`가 `api.ask`·`transcribe`·`refine_transcript`를 막음(PO노트·대화 요약·자동 평가·직접 고른 Cloud 모델 포함). 로컬이 없으면 오류로 알림 | `test_cloud_guard_blocks_every_cloud_call_under_local_only`, `test_local_only_engine_never_calls_cloud_even_when_local_fails`, `test_local_only_works_without_a_cloud_key_and_blocks_cloud_threads` |
| 웹페이지·PDF·MCP 결과가 정책을 바꿈 | 정책은 앱 화면의 js_api로만 바뀌고 웹페이지 뷰에는 js_api가 없다. 요청 글은 작업 분류에만 쓰이며 Local Only·개인정보 제약은 글로 풀리지 않는다 | `test_page_text_cannot_lift_local_only_or_privacy_constraints` |
| 민감 정보가 Cloud로 | '민감 정보는 로컬에서만'을 켜면 키·토큰·주민번호·카드·전화·이메일이 보이는 요청은 로컬로만(없으면 오류) | `test_secrets_in_the_prompt_keep_the_request_local_when_asked` |
| 첨부 파일이 Cloud로 | '첨부를 Cloud로 보내도 됨'을 끄면 첨부가 있는 요청은 로컬로만 | 같음 |
| 로컬·경량 모델이 권한을 얻음 | 엔진은 글만 돌려준다. 에이전트 단계는 기존 승인 창을 그대로 거친다 | `test_local_model_steps_still_need_approval` |
| 다시 하기·승격으로 부작용이 두 번 | 다시 하기·승격·상담은 모델 호출 안에서 끝나고 단계 실행은 한 번 | `test_retries_and_escalation_never_repeat_a_file_write` |
| 상담 발췌 속 지시(프롬프트 주입) | 경량 모델이 고른 발췌는 `connectors.wrap_untrusted`로 감싸 프런티어에 보낸다. 질문 1,500자·발췌 4,000자 상한 | `test_consult_sends_only_the_question_to_the_frontier` |
| 끝없는 승격·상담 비용 | 요청당 승격 0~2번·상담 0~2번, 실행당 승격 6번·상담 6번, 주간 예산·요청당 한도 | `test_escalation_cap_per_run`, `test_consult_cap`, `test_budget_exceeded_keeps_work_local` |
| 기록에 내용이 남음 | telemetry에는 작업 유형·모델·시간·토큰 추정·검증 결과·실패 유형만. 프롬프트·답·첨부·상담 질문은 남기지 않음 | `test_events_have_no_content`, `test_stats_show_light_share_consults_and_frontier_tokens` |
| 개발자 데이터에 내용·키가 남음 | 개발자 모드는 설정에서 켜야 하고, 보이는 것은 telemetry 기록(내용 없음)·토큰 수·단가·설정(로컬 실행기 속도 기록 제외)뿐. API 키는 설정에 없어 나가지 않음 | `test_bridge_prices_breakeven_and_developer_data` |
| 단가·캐시 설정이 품질을 낮춤 | 단가는 규칙이 고른 경량 경로를 프런티어로 바꾸는 쪽으로만 쓴다(싸다고 경량으로 내리지 않음). 3단계·캐싱은 기본 꺼짐 | `test_breakeven_sends_expensive_light_requests_to_the_frontier`, `test_tiered_is_off_by_default` |
| 사용자에게 보이는 이유에 개인 정보 | 이유는 작업 유형·정책·제약 코드로 만든 짧은 글이며 프롬프트를 담지 않음 | `test_reason_has_no_prompt_text` |
| 모델 다운로드 | 사용자가 누를 때만. 이름은 정규식으로 검사(`../`, 공백, `;` 거부). 받기 전에 크기·출처·라이선스·디스크를 보임 | `test_pull_progress_cancel_and_errors`, `test_model_names` |

## 데이터가 가는 곳
- 로컬 AI: 이 PC의 Ollama(또는 사용자가 허용한 원격 Ollama)에만.
- 경량·프런티어 모델: 설정의 API 방식(POSTECH GenAI 또는 개인 Claude API) 그대로. 상담은 프런티어에 짧은 질문·발췌·이 대화의 지난 상담 기록만 보낸다.
- 받기 전 확인: Ollama 공개 저장소(`registry.ollama.ai`)에 모델 이름만 묻는다(사용자가 '확인'을 눌렀을 때).
- 대화 파일에 남는 것: 답변의 라우팅 요약(검증에 실패한 임시 답 앞부분 포함), 프런티어 상담 기록(질문 500자·답 1,500자, 최근 6개).

## 남는 위험
- 규칙 검증은 형식·근거의 일부만 확인한다. 통과했다고 답이 맞다는 뜻은 아니다(화면에 '검증 통과(N개 항목)'로만 적는다).
- 원격 Ollama를 허용하면 주고받는 글이 그 서버를 지난다. 믿을 수 있는 서버만 쓰세요.
- 경량 모델이 상담 질문에 넣을 발췌를 고르므로, 경량 모델이 이미 받은 내용 중 일부가 프런티어로 간다(같은 API 방식의 Cloud 안에서).
