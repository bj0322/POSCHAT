# 개발 진행 상황 (POSCHAT 2.0 / v1.10)

> 1.11 이후의 진행과 다음 작업은 [roadmap.md](roadmap.md), 작업 지침은 [CLAUDE.md](../CLAUDE.md)에 있다. 아래는 1.10 당시 기록.

다음 Claude Code 세션이 이어서 작업할 수 있도록 남기는 기록. 브랜치: `ccr-ecc78b3f-abovre` → `claude/bold-ritchie-x45m6j`에 합침(PR #14).

## 끝난 단계

| 단계 | 커밋 | 내용 |
|---|---|---|
| 기존 버그 B1 | `d395b23` | MCP 도구 호출 NameError 수정 + 회귀 테스트 |
| 분석·설계 | `4065f3f` | docs/architecture/01~03 |
| Phase 1 | `9f460c4`, `18dd3bf`, `db948ae` | 커넥터 프레임워크·secret_store·oauth·게이트웨이, GitHub·Google 서버, 연결·도구 창 |
| Phase 2 | `996501b` | 통합 논문 검색, 라이브러리, RAG, 벡터(선택), Zotero |
| Phase 3 | `7a709a9` | 통합 메모리, 인계, memory MCP 서버, 암호화 동기화 |
| Phase 4 | `d18466e` | Python·Jupyter·SSH 실행(기본 비활성, 데스크톱) |
| Phase 5 | `9527506` | 관측·피드백·평가 |
| 릴리스 준비 | `5beb84d` + 문서 커밋 | 1.10.0, selftest·CI, 첫 실행 백업, 문서 |

## 2026-10-23 추가(PR #14)
- 안드로이드 PO노트 녹음(RecordingService·sherpa_capi), 작은 소리 키우기(stt.level), sherpa-onnx 1.13.8 고정
- AGPL 4~9: 앱 안 라이선스 표시, 배포본 라이선스(licenses/python), CI license 작업(tools/license_check.py), docs/license-audit.md
- 음성 인식 정확도 측정 스크립트: tools/asr_eval.py

## 상태
- 모든 Phase 구현 완료. 테스트 153개(Python 3.11·3.12·3.13 통과, 화면 6개는 Playwright가 있을 때).
- **릴리스(태그 v1.10.0)는 하지 않았다**: 태그를 올리면 모든 사용자에게 자동 업데이트가 나가므로, PR을 만들어 Windows·macOS·Android CI(패키징·selftest·에뮬레이터)가 통과한 것을 확인한 뒤 사용자가 결정한다.

## 다음에 할 일
1. PR을 열어 CI 결과 확인(특히 PyInstaller가 keyring·cryptography·새 모듈을 묶는지, Chaquopy가 cryptography 42.0.8을 받는지).
2. 실제 계정으로 커넥터 검증: GitHub PAT, Google OAuth 클라이언트(데스크톱·안드로이드), Zotero, Langfuse.
3. 향후: 원격 게이트웨이(docs/architecture/04), HTTP MCP 클라이언트, 기존 API 키의 secret_store 이동.

## 테스트 실행
```
python -m unittest discover -s tests          # 전체(Playwright가 있으면 화면 점검 포함)
POSTECH_UI_SHOTS=<폴더> python -m unittest discover -s tests -p test_ui_smoke.py   # 스크린숏 남기기
```
- `tests/support.py`: 데이터 폴더 격리(`isolated_app_dir`), 가짜 HTTP(`FakeHttp`)
- `tests/ui_harness.py`: 실제 Bridge에 붙은 화면을 브라우저로 띄우는 하네스

## 주의
- 새 Python 모듈은 `android/app/build.gradle.kts`의 `syncSharedPython` 목록에 더한다(테스트가 검사한다).
- 커넥터 도구를 더하면 `connectors.TOOL_KINDS`에 종류를 정한다(테스트가 검사한다).
- 태그(v*)를 올리면 모든 사용자에게 자동 업데이트가 배포된다. 사용자 승인 없이 태그하지 않는다.
