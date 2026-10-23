# 03. 구현 계획과 체크리스트

각 Phase는 `config["features"]` 플래그로 독립적으로 켜고 끈다. 커밋은 Phase·기능 단위로 나눈다. 외부 자격 증명이 없는 연동은 Mock 테스트까지 하고 "외부 인증·환경 검증 필요"로 보고한다.

## Phase 0 — 기준선과 기존 버그
- [x] 저장소 분석(01 문서), 기준 테스트 41개 통과 확인
- [x] B1: MCP 도구 호출 NameError 수정 + 회귀 테스트
- [x] B2: "이번 실행 동안 모두 허용"을 실행 단위로 초기화

## Phase 1 — Connector Framework · GitHub · Google Workspace
- [x] `secret_store.py`: keyring/파일 폴백, 마스킹, 테스트
- [x] `oauth.py`: PKCE·state·루프백·코드 교환·갱신·폐기·GitHub 디바이스 흐름, 테스트(가짜 토큰 서버)
- [x] `connectors.py`: 레지스트리·상태·정책·게이트웨이(타임아웃·재시도·속도 제한·정규화·감사 로그), 테스트
- [x] `mcp_client`: 커넥터 서버를 specs에 포함, 호출 타임아웃 인자, 추천 서버 `github-official`
- [x] `agent._tool_mcp`를 게이트웨이로 연결(승인 종류 확장), 외부 데이터 규칙
- [x] `github_mcp.py`: 저장소·파일·코드 검색·이슈·PR·diff·리뷰·커밋·Actions·실패 로그, 테스트(가짜 HTTP)
- [x] `google_mcp.py`: Drive·Docs·Sheets·Slides·Gmail·Calendar, 테스트(가짜 HTTP)
- [x] Bridge API: 커넥터 목록·켜기/끄기·토큰 저장·OAuth 로그인·재인증·연결 해제·확인·정책·로그
- [x] UI: 연결·도구 창(커넥터 탭, MCP 탭 이전)
- [x] 안드로이드: URL 열기(openPath), 모듈 동기화 목록

## Phase 2 — Research Workspace
- [x] `paper.search` Crossref·OpenAlex·all 병합(DOI/arXiv/제목)
- [x] `research_library.py`: 저장·분류·태그·PDF·메타데이터 추출·BibTeX
- [x] `rag.py`: 인덱싱·증분·출처 인용·컬렉션 접근 제한
- [x] `vector_store.py`: Qdrant + 임베딩(선택), 하이브리드 RRF
- [x] `research_mcp.py`: research·zotero 서버
- [x] UI: 연구 라이브러리 탭
- [x] 스킬: paper-compare

## Phase 3 — Unified Memory · Sync
- [x] `memory_store.py`: 계층·검색·중복 제거·출처
- [x] `handoff.py`: 표준 형식·상태 기계·idempotency
- [x] `memory_mcp.py`: 외부 에이전트용 MCP 서버
- [x] 에이전트 프롬프트에 프로젝트 메모리(기능 켜짐일 때)
- [x] `sync.py`: 암호화·폴더/Drive 백엔드·충돌 해결·삭제·상태
- [x] UI: 메모리·동기화 탭
- [x] 문서: Universal AI Memory Hub 연동 검증표

## Phase 4 — Agent Automation
- [x] 에이전트 실행 후 표준 인계 자동 기록(ai-memory와 병행)
- [x] `runner_mcp.py`: python·ssh(기본 비활성, 정책·제한·로그)
- [x] UI: 에이전트 자동화 탭

## Phase 5 — Observability · 평가
- [x] `telemetry.py`: 로컬 기록·집계·마스킹·Langfuse 내보내기
- [x] api·agent·게이트웨이 계측
- [x] 답변 피드백(👍/👎)
- [x] `evals.py`: 평가 실행기
- [x] UI: 사용량·진단 탭

## 마무리
- [x] 버전 1.10.0, Release Notes, Migration Guide, 설치·설정 문서, API 문서
- [x] CI selftest 문자열·안드로이드 계측 테스트 갱신
- [x] `docs/development-progress.md` 최종 상태

## 결과 상태 (1.10.0)
- 구현 및 테스트 완료(자동 테스트 153개, Python 3.11·3.12·3.13, 화면 Chromium 점검): 위 체크리스트 전부.
- 외부 인증·환경 검증 필요: 실제 GitHub·Google·Zotero·Langfuse 계정, Qdrant·임베딩 API, SSH 서버, Docker 격리, 안드로이드 Google 루프백 로그인, 패키징된 앱(Windows·macOS·Android CI에서 확인).
- 향후 작업: 원격 게이트웨이(04 문서), HTTP MCP 클라이언트, 기존 API 키의 secret_store 이동, Jupyter 상주 커널.
