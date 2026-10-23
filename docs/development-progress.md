# 개발 진행 상황 (POSCHAT 2.0 / v1.10)

다음 Claude Code 세션이 이어서 작업할 수 있도록 남기는 기록. 브랜치: `ccr-ecc78b3f-abovre`.

## 끝난 단계

| 단계 | 커밋 | 내용 |
|---|---|---|
| 기존 버그 B1 | `d395b23` | MCP 도구 호출 NameError 수정 + 회귀 테스트 |
| 분석·설계 | `4065f3f` | docs/architecture/01~03 |
| Phase 1 | `9f460c4`, `18dd3bf`, `db948ae` | 커넥터 프레임워크·secret_store·oauth·게이트웨이, GitHub·Google 서버, 연결·도구 창 |
| Phase 2 | `996501b` | 통합 논문 검색, 라이브러리, RAG, 벡터(선택), Zotero |
| Phase 3 | `7a709a9` | 통합 메모리, 인계, memory MCP 서버, 암호화 동기화 |

## 남은 단계
- Phase 4: `runner_mcp.py`(python·ssh, 기본 비활성, 데스크톱 전용), 자동화 탭
- Phase 5: `telemetry.py`, `evals.py`, 피드백, 사용량·진단 탭
- 마무리: 버전 1.10.0, 문서(설치·설정·API·Migration·Release Notes), CI selftest 문자열, 안드로이드 selftest 확장

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
