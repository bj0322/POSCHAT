# 보안 설계 (1.10)

| 위협 | 대응 | 위치 |
|---|---|---|
| 토큰이 Git·설정·동기화·로그로 새어 나감 | 새 비밀은 OS 보안 저장소(폴백: 0600 파일). config.json·동기화 대상·로그·`get_state`에 넣지 않음. 로그·관측은 `privacy.redact_*`로 키·토큰·이메일·긴 본문을 가림 | `secret_store.py`, `privacy.py`, `sync.py` |
| OAuth 가로채기·CSRF | PKCE(S256), 32바이트 state를 상수 시간 비교, `127.0.0.1` 임의 포트, 첫 정상 콜백만, 5분 제한, 요청 줄 로그 안 남김. 갱신 거절(invalid_grant) 시 토큰 삭제·'인증 필요'. 연결 해제 시 Google revoke | `oauth.py` |
| 프롬프트 주입으로 권한 상승 | 도구 종류는 앱 정의(서버 주석 불신). 전송·삭제·실행은 '모두 자동 허용'이어도 매번 승인, "이번 실행 동안 허용" 불가. 외부 결과는 '외부 데이터' 표시로 감싸고 위조 표시는 무력화. 정책을 바꾸는 도구 없음. 사용자가 차단한 도구는 모델에게 숨김 | `connectors.py`, `agent.py` |
| 메일 초안 바꿔치기 | `send_draft`는 승인 창에 보인 받는 사람·제목이 실제 초안과 같을 때만 전송 | `google_mcp.py` |
| 작업 폴더 밖 접근 | 업로드·인덱싱·BibTeX·PDF 연결·노트북 실행은 작업 폴더 안만. RAG 검색은 지금 작업 폴더+라이브러리 컬렉션만 | 각 서버, `rag.py` |
| 임의 코드 실행 | 기본 꺼짐, 데스크톱 전용, 매번 승인 + 앱이 만든 실행 대상 설명, 시간 제한·리소스 제한·비밀 환경 변수 제거, 선택적 Docker(`--network none`), SSH 허용 목록·셸 메타문자 차단·StrictHostKeyChecking, 실행 기록 | `runner_mcp.py` |
| 동기화 저장소 유출 | 종단간 AES-256-GCM, scrypt 키, 객체 이름 HMAC, 원격에 키 없음, 손상·다른 암호는 복호화 실패로 거부 | `sync.py` |
| 다른 클라이언트가 기억을 읽고 씀 | memory 서버는 POSCHAT이 아닌 MCP 클라이언트를 거부(외부 공유 기능 없음) | `memory_mcp.py` |
| 외부 관측 서비스 | 기본 꺼짐, 메타데이터만. 내용 포함은 별도 동의 + 가림 + 2000자 | `telemetry.py` |
| 웹페이지가 앱 권한에 닿음(1.13 브라우저) | 웹페이지 쪽 네이티브 뷰(WebView2·WKWebView·Android WebView)에 js_api·host object·WebMessage·스크립트 메시지 핸들러·JavascriptInterface를 주지 않음. 앱이 페이지를 읽기만 함. 읽은 내용은 '외부 데이터'로 감쌈. http·https만(file·javascript·data·앱 내부·링크 로컬 차단), 새 창은 같은 뷰, 다운로드·권한 요청 거절, 별도 프로필 폴더. 에이전트가 주소를 열 때는 주소를 보이고 승인(주소에 정보를 실어 보내는 주입 차단). 네이티브 실패 시 옆 창은 pywebview 메시지 통로를 닫음 | `browser.py`, `browser_win.py`, `browser_mac.py`, `MainActivity.kt` |
| 네트워크 장애 | 모든 새 기능은 로컬 우선. 커넥터 실패는 도구 오류로만 보이고 대화·로컬 기능은 그대로 | 전반 |

알려진 한계: 격리 없이 실행한 Python은 사용자 권한으로 돈다(승인 창에 명시). keyring을 쓸 수 없는 환경의 파일 폴백은 같은 OS 사용자에게는 읽힌다. Windows는 Python 실행에 메모리 제한을 걸지 않는다.
