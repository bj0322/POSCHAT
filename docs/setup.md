# 설치·설정 가이드 (1.10)

설치는 1.9와 같다(README의 '설치'). 1.10의 새 기능은 **모두 기본으로 꺼져 있으며** 왼쪽 아래 **연결·도구**에서 켠다. 아래는 기능별로 사용자가 직접 준비해야 하는 것이다. 앱은 공용 OAuth 클라이언트·서버 자격 증명을 포함하지 않는다.

## 인증 정보 저장 위치
- 커넥터 토큰·키(GitHub·Google·Zotero·Langfuse·벡터 DB·동기화 키): Windows 자격 증명 관리자, macOS 키체인. 쓸 수 없으면 데이터 폴더의 `secrets.json`(POSIX 0600). 안드로이드는 앱 전용 저장소.
- POSTECH API 키·Notion·Firecrawl 키: 1.9와 같이 `config.json`(하위 호환).

## GitHub
1. https://github.com/settings/personal-access-tokens/new 에서 **Fine-grained token**을 만든다. 필요한 저장소만 고르고 권한은 Metadata(읽기), Contents(읽기), Issues·Pull requests(읽기, 이슈·리뷰 작성을 하려면 읽기/쓰기), Actions(읽기).
2. 연결·도구 → 커넥터 → GitHub를 켜고 토큰을 저장 → **연결 확인**.
- (선택) OAuth: GitHub OAuth App을 만들고 *Enable Device Flow*를 켠 뒤 Client ID를 넣고 **OAuth로 로그인**(디바이스 코드). 안드로이드에서도 된다.
- (선택) GitHub Enterprise: 옵션 'API 주소'에 `https://<host>/api/v3`.
- (선택, 데스크톱) 공식 `github-mcp-server` 바이너리가 PATH에 있으면 MCP 서버 탭에 추천 서버 `github-official`(읽기 전용)이 나타난다.

## Google Workspace (Drive·Docs·Sheets·Slides·Gmail·Calendar, 동기화 저장소)
1. Google Cloud Console에서 프로젝트를 만들고 쓸 API를 사용 설정(Drive API, Docs API, Sheets API, Slides API, Gmail API, Calendar API).
2. OAuth 동의 화면: 외부, 테스트 모드, 본인 계정을 테스트 사용자로 추가.
3. 사용자 인증 정보 → OAuth 클라이언트 ID → **데스크톱 앱**. 클라이언트 ID·보안 비밀번호를 연결·도구 → 커넥터 → Google OAuth 클라이언트에 저장.
4. 쓸 서비스만 켜고 **로그인**. 브라우저가 열리고 그 서비스의 scope만 묻는다(로컬 `127.0.0.1` 리디렉트, PKCE·state 검증).
- 읽기 전용 옵션을 켜면 읽기 scope만 요청한다(바꾼 뒤 다시 로그인).
- 테스트 모드의 Google 토큰은 7일 뒤 만료될 수 있다(Google 정책). 그러면 상태가 '인증 필요'가 되고 다시 로그인하면 된다.
- 안드로이드: 브라우저 로그인 후 앱으로 돌아오는 루프백 흐름은 **실기기 검증이 필요**하다. 동기화만 필요하면 PC에서 쓰는 폴더 동기화 대신 Drive 동기화 저장소를 쓴다.

## 연구 라이브러리·Zotero·벡터 검색
- 연구 라이브러리: 커넥터 '연구 라이브러리'를 켠다. 설정할 것 없음. (선택) Semantic Scholar API 키.
- Zotero: https://www.zotero.org/settings/keys 에서 키를 만들어 넣는다. 그룹 라이브러리는 옵션에 종류 `group`과 그룹 번호.
- 벡터 검색(선택): Qdrant(예: `docker run -p 6333:6333 qdrant/qdrant`)와 OpenAI 호환 `/embeddings` API가 필요하다. 연구 라이브러리 탭 → 벡터 검색. **문서 조각이 임베딩 API로 전송된다.** POSTECH 게이트웨이가 임베딩 API를 제공하는지는 확인하지 못했다.

## 통합 메모리·다른 AI 클라이언트
- 메모리·동기화 탭에서 '통합 메모리'를 켜고 '에이전트 도구 켜기'.
- Claude Desktop 등에 같은 기억을 연결하려면 같은 탭의 JSON·명령을 복사한다. 지원 범위: [integrations/universal-memory-hub.md](integrations/universal-memory-hub.md).

## 동기화 (Opt-in)
- 폴더: OneDrive·Dropbox·Google Drive 데스크톱·iCloud Drive 폴더를 고른다(그 클라이언트가 실제 업로드를 한다).
- Google Drive 앱 전용 폴더: 커넥터 'Google Drive 동기화 저장소'에 로그인(`drive.appdata`만).
- 모든 기기에서 **같은 동기화 암호**. 암호를 잊으면 복구할 수 없다(서버에 키가 없다).
- 기기 해제: '이 기기 연결 해제'(이 기기 키만 삭제). 전체 삭제: '원격 데이터 삭제'.

## 에이전트 자동화 (데스크톱)
- Python: PATH의 Python 또는 경로 지정. Jupyter 노트북 실행에는 그 Python에 `nbconvert`·`ipykernel`. Docker 격리는 Docker Desktop 필요.
- SSH: OS의 `ssh` 클라이언트와 키(ssh-agent). 처음 연결하는 호스트는 터미널에서 직접 한 번 접속해 호스트 키를 저장. 호스트 별칭·허용 명령을 자동화 탭에서 등록.

## 사용량·진단 / Langfuse
- 로컬 기록은 기본으로 켜져 있다(내용 없음). 끌 수 있다.
- Langfuse(선택): Langfuse Cloud 또는 자체 호스팅 주소(https), 프로젝트의 공개·비밀 키.
