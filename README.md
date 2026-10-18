# POSTECH GenAI Chat

버전 1.1.0 — 대화 간 정보 공유(메모리·다른 대화 참고) 추가, 기본 스킬을 범용 스킬로 정리

POSTECH GenAI API를 쓰는 Windows 데스크톱 챗봇입니다. 개인이 개발·관리하는 비공식 프로젝트이며, POSTECH의 공식 제품이나 지원 서비스가 아닙니다. POSTECH 명칭은 연동 대상 서비스를 설명하기 위해 사용합니다. 사용하려면 본인에게 발급된 유효한 API 키와 해당 서비스 이용 권한이 필요하며, 서비스 제공자의 이용 조건을 따라야 합니다. 저장소 공개나 MIT 라이선스는 API 접근 권한을 제공하지 않습니다. 화면은 ChatGPT처럼 생겼고, 작업 폴더를 지정하면 Claude Code·Codex처럼 파일을 읽고, 고치고, 명령을 실행하는 에이전트로 일합니다.

## 설치

이 저장소는 소스 배포용이며 설치 파일을 포함하지 않습니다. 아래 개발 절차로 실행하거나 설치 프로그램을 직접 빌드하세요. 빌드한 설치 프로그램은 다음과 같이 사용할 수 있습니다.

1. 직접 빌드한 `release\PostechChat-Setup.exe`를 로컬 폴더에서 실행합니다.
2. 설치 프로그램에는 코드 서명이 없습니다. Windows 또는 보안 제품이 실행을 차단하면 경고 내용과 파일 출처를 확인하고, 필요하면 소스로 실행하세요. 보호 기능을 끄거나 예외를 추가하는 것을 설치 절차로 요구하지 않습니다.
3. **설치**를 누릅니다. 관리자 권한은 필요 없습니다.
   - 설치 위치: `%LOCALAPPDATA%\Programs\PostechChat`
   - 시작 메뉴와 바탕화면에 바로가기가 생깁니다.
4. 처음 실행하면 설정 창이 열립니다. POSTECH GenAI API 키를 입력하세요.

제거는 **설정 → 앱 → 설치된 앱 → POSTECH GenAI Chat → 제거**에서 합니다. 대화 기록과 설정(`%APPDATA%\PostechChat`)은 지우지 않고 남겨 둡니다.

### 설치 문제 해결

설치 중 오류나 지연이 발생하면 보안 제품의 알림과 설치 로그를 확인하세요. 조직에서 관리하는 PC는 관리자 정책을 따르세요.

- 시작 메뉴에 `POSTECH GenAI Chat (2)`라는 이름으로 바로가기가 생길 수 있습니다. 같은 이름의 이전 바로가기를 탐색기가 아직 붙잡고 있을 때 생기며, 재부팅하면 풀립니다.
- 바로가기를 만들지 못해도 설치는 끝납니다. 이때는 `%LOCALAPPDATA%\Programs\PostechChat\PostechChat.exe`로 실행하세요.
- 조용한 설치 로그: `%TEMP%\PostechChat-install.log`

## 사용법

| 기능 | 방법 |
|---|---|
| 새 대화 | 왼쪽 위 **새 채팅** (Ctrl+Shift+O) |
| 대화 이름 변경·삭제 | 대화 목록에 마우스를 올리면 나오는 연필·휴지통 아이콘 |
| 작업 폴더 지정 | 왼쪽 아래 **작업 폴더**, 또는 입력창의 폴더 칩 |
| 에이전트 켜기·끄기 | 오른쪽 위 **에이전트** 스위치 |
| 명령어·스킬 | 입력창에 `/`를 입력하면 목록이 뜹니다 |
| 메모리 | 왼쪽 아래 **메모리**, `/remember 내용`, `/memory` |

### 대화 간 정보 공유 (메모리 · 다른 대화 참고)

대화(스레드)마다 기록은 따로 저장되지만, 다음 두 가지 방법으로 서로 정보를 주고받습니다.

- **메모리**: 모든 대화에 공통으로 전달되는 기억입니다. 대화 중에 "~를 기억해 줘", "잊지 마"라고 하면 앱이 기억할 내용을 한 문장으로 정리해 저장합니다. 이때 대화에 `🧠 기억: …` 줄이 표시됩니다. `/remember 내용`으로 직접 추가할 수도 있습니다. "기억해?"처럼 묻는 말은 저장하지 않습니다.
- **다른 대화 참고**: 새 질문과 관련된 내용이 다른 대화에 있으면 자동으로 찾아 함께 참고합니다. 참고한 대화는 `📎 다른 대화 참고: …`로 표시됩니다. 에이전트 모드에서는 "지난번에 얘기한 …"처럼 말하면 `recall` 단계로 다른 대화를 직접 검색합니다. 메모리 창에서 끌 수 있습니다.

메모리는 `%APPDATA%\PostechChat\memory.json`에 저장됩니다. 메모리 창에서 항목을 보거나 지울 수 있습니다.

### 에이전트 모드

작업 폴더를 지정하고 에이전트를 켜면, AI가 목표를 이룰 때까지 단계를 반복합니다.

- `list` 폴더 보기 · `read` 파일 읽기 · `search` 내용 검색
- `write` 파일 작성 · `edit` 부분 수정 · `run` 명령 실행(Windows cmd)
- `skill` 스킬 불러오기 · `recall` 다른 대화 검색 · `done` 최종 답변

각 단계는 대화에 한 줄씩 표시되고, 누르면 자세한 내용(파일 내용, 변경 diff, 명령 출력)이 펼쳐집니다. **파일 수정과 명령 실행은 실행 전에 diff나 명령을 보여 주고 승인을 받습니다.** 설정에서 "파일 수정은 자동 허용" 등으로 바꿀 수 있습니다. 파일 도구는 경로를 검사해 작업 폴더 밖의 접근을 차단합니다. 다만 `run`은 작업 폴더를 시작 위치로 하는 일반 셸 명령이며, 운영체제 수준의 샌드박스가 아닙니다. 승인한 명령은 현재 사용자 권한으로 다른 위치나 네트워크에 접근할 수 있습니다.

작업 폴더가 없거나 에이전트를 끄면 일반 챗봇으로 동작합니다.

### INIT.md

작업 폴더 최상위의 `INIT.md`는 모든 대화에 프로젝트 지침으로 들어갑니다(Claude Code의 CLAUDE.md와 같은 역할). `/init`을 입력하면 AI가 폴더를 살펴보고 INIT.md를 써 줍니다.

### 스킬

스킬은 `<스킬이름>/SKILL.md` 형식의 지침 파일입니다. 에이전트가 요청에 맞는 스킬을 스스로 불러오고, `/스킬이름 요청`으로 직접 실행할 수도 있습니다.

```markdown
---
name: meeting-notes
description: 회의 녹취를 회의록 형식으로 정리할 때 사용
---

# 회의록 스킬
## 절차
1. ...
```

스킬을 읽는 위치는 다음과 같습니다. 이름이 같으면 아래쪽이 우선합니다.

1. 앱 내장: `summarize`(문서 요약), `code-review`(코드 검토)
2. 사용자 공용: `%APPDATA%\PostechChat\skills\`. 앱의 **스킬 → 새 스킬 만들기**로 템플릿을 만들 수 있습니다.
3. 작업 폴더 전용: `<작업 폴더>\skills\`

## 동작 방식과 한계

POSTECH GenAI 서버의 모델은 자체 시스템 프롬프트 때문에 "사용자 PC에 접근하라"는 형식의 도구 호출을 거부합니다. 그래서 이 앱은 "진행 기록을 보고 다음 단계를 JSON으로 고르는 작업"으로 요청합니다. 모델이 그래도 형식을 거부하고 사용자에게 할 일을 안내하면, 앱이 그 안내문을 다음 단계로 바꾸거나 언급된 파일을 직접 읽어 진행을 이어 갑니다.

- API가 스트리밍을 지원하지 않아서 답변이 한 번에 표시됩니다. 단계마다 API를 한 번씩 호출하므로, 여러 단계짜리 작업은 1~2분 걸릴 수 있습니다.
- 모델이 가끔 같은 파일을 여러 번 읽는 등 불필요한 단계를 거칠 수 있습니다. 최대 단계 수는 설정에서 바꿉니다.
- 오류가 나면 `%APPDATA%\PostechChat\error.log`를 확인하세요.

## 개발

| 파일 | 역할 |
|---|---|
| `main.py` | pywebview 창과 JS↔Python 브리지 |
| `agent.py` | INIT.md·스킬 로딩, 에이전트 단계 루프와 도구 |
| `api.py` | POSTECH GenAI API 호출 |
| `storage.py` | 대화·설정·메모리 저장(`%APPDATA%\PostechChat`), 다른 대화 검색 |
| `web/` | 화면(HTML/CSS/JS, marked·DOMPurify 포함) |
| `installer/installer.py` | 설치 프로그램(`--silent --dir=<경로> --no-desktop` 지원) |
| `assets/` | 앱 아이콘 |
| `build_installer.py` | 앱과 설치 프로그램 빌드 |

- 소스로 실행: `run.bat`
- 진단: `PostechChat.exe --selftest`를 실행하면 API 연결 결과가 `%APPDATA%\PostechChat\selftest.txt`에 기록됩니다. 제거 명령은 `PostechChat.exe --uninstall`입니다.
- 설치 파일 빌드: `build.bat`, 또는 `python build_installer.py`. 결과는 `release\PostechChat-Setup.exe`입니다.
  - **python.org 공식 Python(3.10 이상, tcl/tk 포함)으로 빌드하세요.** Anaconda Python으로 빌드한 exe는 HTTPS 요청 때 `OPENSSL_Uplink: no OPENSSL_Applink` 오류로 꺼집니다. 빌드 스크립트가 이 경우를 미리 막습니다.
- 앱의 HTTPS 요청은 `truststore`를 통해 운영체제 인증서 저장소를 사용합니다. 인증서 오류가 발생하면 Windows 인증서와 네트워크 설정을 확인하세요. TLS 검증을 비활성화하지 마세요.


## 소스 설치와 개발 환경

Windows와 Python 3.10 이상을 기준으로 합니다. 데스크톱 화면에는 Microsoft Edge WebView2 런타임이 필요합니다. 프로젝트 폴더에서 다음 명령을 실행하세요.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

첫 실행의 설정 창에서 본인의 POSTECH GenAI API 키를 입력합니다. 또는 실행할 프로세스에 `POSTECH_GENAI_API_KEY` 환경 변수를 설정할 수 있습니다. 설정에 저장한 키가 환경 변수보다 우선합니다. `.env` 파일을 자동으로 읽는 기능은 없습니다. 프런트엔드는 정적 HTML/CSS/JavaScript이므로 npm 설치나 별도 웹 서버가 필요하지 않습니다.

개발 중 브리지 디버깅은 `POSTECH_CHAT_DEBUG=1` 환경 변수를 설정해 켤 수 있습니다. `run.bat`은 사용 가능한 Python을 찾아 의존성을 설치하고 실행하는 편의 스크립트이며, 위의 가상환경 직접 실행 방법은 사용할 Python을 명확하게 고정합니다.

설치 프로그램은 python.org Python(tcl/tk 포함)에서 다음과 같이 빌드합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe build_installer.py
```

빌드는 `%TEMP%\PostechChat-build`를 사용하며 결과는 `release\PostechChat-Setup.exe`입니다. 빌드 결과는 Git에 포함하지 않습니다.

## v1.1.0 아키텍처

1. `web/app.js`가 `window.pywebview.api`를 통해 `main.py`의 `Bridge`를 호출합니다. `/remember`, `/memory`, `/help`는 화면에서 처리합니다.
2. `Bridge`는 대화와 설정을 관리하고 백그라운드 스레드에서 `Agent`를 실행합니다. 진행 상황·도구 결과·승인 요청은 `window.onBackendEvent`로 화면에 전달합니다.
3. `agent.py`는 공통 메모리, 관련 대화, 최근 메시지와 INIT.md·스킬을 조합합니다. 일반 대화는 한 번의 답변 요청으로, 에이전트는 JSON 단계 선택과 로컬 도구 실행의 반복으로 처리합니다.
4. `api.py`는 POSTECH GenAI 엔드포인트에 `X-Api-Key` 헤더로 인증하고 비스트리밍 요청을 보냅니다. TLS 검증에는 `truststore`를 통해 운영체제 인증서 저장소를 사용합니다.
5. `storage.py`는 JSON 파일을 임시 파일에 쓴 뒤 교체합니다. 다른 대화 검색은 한국어·영문·숫자의 문자 bigram 겹침을 사용하며 벡터 DB나 임베딩 서버를 사용하지 않습니다.

자동 대화 참고는 기본 활성화되며 메모리 창에서 끌 수 있습니다. 현재 구현에서 이 설정은 자동 참고를 제어하며, 에이전트의 명시적 `recall` 검색은 별도로 실행될 수 있습니다. 기본 에이전트 단계 한도는 25, 대화 이력은 20개 메시지이고 설정에서 바꿀 수 있습니다.

## 데이터와 저장소 관리

- API 키를 설정 창에 입력하면 `%APPDATA%\PostechChat\config.json`에 평문으로 저장됩니다. 공용 PC에서는 환경 변수를 사용하는 등 보관 방식을 신중히 선택하세요.
- 대화·공통 메모리·관련 대화 발췌·읽은 파일 및 명령 출력은 답변 생성에 필요할 때 POSTECH GenAI API로 전달됩니다.
- 사용자 대화, 메모리, 설정, 로그, 개인 API 키는 소스 저장소에 포함하지 않습니다. `.gitignore`는 이 파일들과 가상환경·캐시·빌드 결과·실행 파일을 제외합니다.
- 앱 소스, 설치 프로그램 소스, 실행·빌드 스크립트, 기본 스킬 2종, 아이콘, 정적 UI와 번들 JavaScript 라이브러리를 포함합니다. `web/vendor/` 파일은 UI 실행에 필요한 배포 의존성이므로 포함하며, 원본 저작권·라이선스 주석을 유지합니다.
- 이 저장소는 v1.1.0 소스 스냅샷을 시작점으로 합니다. 이전 버전의 코드·변경 이력은 가져오지 않습니다.

## 라이선스

이 프로젝트의 자체 코드와 문서는 [MIT License](LICENSE)로 배포합니다. 저작권 표시는 Beomjoon Kim (bj0322)이며, 제3자 코드와 자산의 권리는 각 권리자에게 있습니다. POSTECH의 명칭·상표나 API 서비스 이용 권한은 이 라이선스에 포함되지 않습니다.

번들 라이브러리의 버전, 출처, 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리했습니다. 원문은 `licenses/`에 보관하며, 제3자 파일은 각 원본 라이선스를 따릅니다.
