# POSCHAT

버전 1.17.1 — **Code 에이전트가 Claude Code·Codex처럼**: 권한 모드 4가지(**계획 모드**로 먼저 계획을 받고 승인하면 진행, 매번 묻기, 수정 자동, **전체 자동**), 명령 승인 창의 **다시 묻지 않기**, 일하는 중에 보내는 **추가 지시**, 슬래시 명령(`/init` `/review` `/test` `/plan` `/undo` `/compact`), **마지막 지시 되돌리기**, 프로젝트 지침 **AGENTS.md·CLAUDE.md**와 테스트·빌드 명령 자동 파악, **격리 작업 공간(git worktree)**에서 고친 뒤 적용·버리기, 줄 번호 읽기·파일 찾기(glob)·여러 곳 한 번에 고치기·백그라운드 명령. [릴리스 노트](docs/release-notes/v1.17.1.md) · [사용법](docs/code-editor-guide.md#code-에이전트-2-claude-codecodex처럼-1171) · [이전 버전 기록](#버전-기록)

POSTECH GenAI API(기본) 또는 본인의 Claude API 키를 쓰는 Windows·macOS 데스크톱·안드로이드 챗봇 POSCHAT입니다(1.10까지의 이름은 POSTECH GenAI Chat). PIDS Tech. 팀이 개발·관리하는 비공식 프로젝트이며, POSTECH의 공식 제품이나 지원 서비스가 아닙니다. POSTECH 명칭은 연동 대상 서비스를 설명하기 위해 사용합니다. 사용하려면 본인에게 발급된 유효한 API 키와 해당 서비스 이용 권한이 필요하며, 서비스 제공자의 이용 조건을 따라야 합니다. 저장소 공개나 소프트웨어 라이선스(AGPL-3.0-only, 과거 버전은 MIT)는 API 접근 권한을 제공하지 않습니다. 화면은 ChatGPT처럼 생겼고, 작업 폴더를 지정하면 Claude Code·Codex처럼 파일을 읽고, 고치고, 명령을 실행하는 에이전트로 일합니다.

## 문의

- 개발: PIDS Tech. 팀
- 서비스 대표자: 김범준
- 문의 메일: [beomjoon@pidstech.com](mailto:beomjoon@pidstech.com)

## 설치

설치 파일(`POSCHAT-Setup.exe`)은 저장소의 [Releases](https://github.com/bj0322/POSCHAT/releases)에서 받습니다. 저장소 자체에는 exe를 넣지 않습니다. 설치 파일 하나에 Python, 화면 라이브러리(marked·DOMPurify·KaTeX), 문서 라이브러리, 내장 MCP 서버가 모두 들어 있으므로 npm·curl·Python을 따로 설치할 필요가 없습니다. 직접 빌드하려면 아래 [개발](#개발)을 보세요.

1. Releases에서 받은 `POSCHAT-Setup.exe`(또는 직접 빌드한 `release\POSCHAT-Setup.exe`)를 실행합니다.
2. 설치 프로그램에는 아직 코드 서명이 없어서 Windows가 "Windows의 PC 보호" 경고를 띄울 수 있습니다. 파일을 Releases에서 받았는지 확인한 뒤 **추가 정보 → 실행**을 누르세요. 경고를 없애려면 코드 서명 인증서가 필요합니다([배포](#배포) 참고). 보호 기능을 끄거나 예외를 추가하는 것을 설치 절차로 요구하지 않습니다.
3. **설치**를 누릅니다. 관리자 권한은 필요 없습니다.
   - 설치 위치: `%LOCALAPPDATA%\Programs\PostechChat` (이전 버전에서 그대로 업데이트되도록 폴더·실행 파일·데이터 폴더 이름은 1.10과 같습니다)
   - 시작 메뉴와 바탕화면에 바로가기가 생깁니다.
4. 처음 실행하면 설정 창이 열립니다. POSTECH GenAI API 키를 입력하세요. 본인 Claude API 키로 쓰려면 API 방식에서 **일반 AI 모델 (Claude)**를 고르고 Claude API 키를 넣습니다.

제거는 **설정 → 앱 → 설치된 앱 → POSCHAT → 제거**에서 합니다. 대화 기록과 설정(`%APPDATA%\PostechChat`)은 지우지 않고 남겨 둡니다.

### macOS

Releases의 `POSCHAT-mac.dmg`를 받아 엽니다. Apple Silicon(M1 이후) 맥용이며 Intel 맥은 지원하지 않습니다.

1. 열린 창에서 **POSCHAT**(앱 파일 이름은 PostechChat.app)을 **Applications(응용 프로그램)** 폴더로 끌어다 놓습니다.
2. 앱에는 Apple 개발자 서명·공증이 없어서, 처음 실행하면 "확인되지 않은 개발자" 또는 "열 수 없음" 경고가 뜹니다. 응용 프로그램 폴더에서 앱을 **Control 키를 누른 채 클릭 → 열기**를 누르세요. macOS 15 이후에서는 **시스템 설정 → 개인정보 보호 및 보안**의 아래쪽에서 **그래도 열기**를 누릅니다. 한 번 허용하면 이후에는 그대로 실행됩니다.
3. 처음 실행하면 설정 창이 열립니다. POSTECH GenAI API 키를 입력하세요.

대화 기록과 설정은 `~/Library/Application Support/PostechChat`에 저장됩니다. 에이전트의 `run` 단계는 macOS 셸(`/bin/sh`)로 실행됩니다. 제거는 응용 프로그램 폴더의 앱을 휴지통으로 옮기면 됩니다(대화 기록 폴더는 남습니다).

### 설치 문제 해결

설치 중 오류나 지연이 발생하면 보안 제품의 알림과 설치 로그를 확인하세요. 조직에서 관리하는 PC는 관리자 정책을 따르세요.

- 시작 메뉴에 `POSCHAT (2)`라는 이름으로 바로가기가 생길 수 있습니다. 같은 이름의 이전 바로가기를 탐색기가 아직 붙잡고 있을 때 생기며, 재부팅하면 풀립니다.
- 바로가기를 만들지 못해도 설치는 끝납니다. 이때는 `%LOCALAPPDATA%\Programs\PostechChat\PostechChat.exe`로 실행하세요.
- 조용한 설치 로그: `%TEMP%\PostechChat-install.log`

### 안드로이드

Releases의 `POSCHAT.apk`를 휴대폰에서 받아 설치합니다(Android 7.0 이상, 64비트 ARM). 스토어 앱이 아니므로 처음 설치할 때 "출처를 알 수 없는 앱 설치"를 허용해야 합니다. 새 버전도 APK를 그대로 설치하면 대화·설정을 유지한 채 업데이트됩니다. 1.9.1부터는 앱이 새 버전을 알려 주고 APK를 받아 설치 화면을 엽니다.

데스크톱과 같은 화면과 Python 코드(에이전트, 문서 읽기, 내장 MCP 서버, 스트리밍, 수식)를 앱 안에서 그대로 실행합니다. 다른 점은 다음과 같습니다.

- 사이드바는 왼쪽 위 버튼으로 여는 서랍이고, 뒤로 가기로 창·사이드바를 닫습니다. 입력창의 Enter는 줄바꿈이며 보내기 버튼으로 보냅니다.
- 작업 폴더를 고르면 "모든 파일 접근" 권한을 요청합니다. 에이전트가 휴대폰 저장소의 일반 폴더(예: `Documents/보고서`)를 읽고 고치려면 필요합니다. 작업 폴더 없이 대화만 할 때는 필요 없습니다.
- `run` 단계는 안드로이드 셸(`/system/bin/sh`)로 실행됩니다. Python·Node 같은 개발 도구는 없습니다.
- 내장 MCP 서버(Word·PowerPoint·Excel·paper·notion·firecrawl)는 앱 안에서 바로 동작합니다. 추천 서버(Playwright)는 보이지 않습니다. `npx`·`uvx`가 필요한 외부 MCP 서버는 휴대폰에서 실행할 수 없습니다.
- 대화 기록과 설정은 앱 전용 저장소에 따로 있으며 PC와 동기화되지 않습니다.

## 사용법

| 기능 | 방법 |
|---|---|
| 사용법 가이드 | 왼쪽 아래 **설정** → **사용법 가이드**, 또는 `/help` → **사용법 가이드** |
| 새 대화 | 왼쪽 위 **새 채팅** (Ctrl+Shift+O) |
| 대화 이름 변경·삭제 | 대화 목록에 마우스를 올리면 나오는 연필·휴지통 아이콘 |
| 작업 폴더 지정 | 왼쪽 아래 **작업 폴더**, 또는 입력창의 폴더 칩 |
| 에이전트 켜기·끄기 | 오른쪽 위 **에이전트** 스위치 |
| 명령어·스킬 | 입력창에 `/`를 입력하면 목록이 뜹니다 |
| 파일 첨부 | 입력창의 + 버튼, 파일 끌어다 놓기, 이미지 붙여 넣기(Ctrl+V) |
| 내 정보(USER.md) | 왼쪽 아래 **내 정보**, `/user` |
| 메모리(memory.md) | 왼쪽 아래 **메모리**, `/remember 내용`, `/memory` |
| MCP 서버 켜기·끄기, 외부 서버 추가 | 왼쪽 아래 **연결·도구** → MCP 서버 |
| AI 실행 정책·로컬 AI | **설정 → AI 실행 정책**. 자동 모델 선택(Economy·Balanced·Quality·Local Only), Ollama 연결·모델 받기, 3단계(경량 Cloud 모델과 프런티어 상담)·단가·손익분기·프롬프트 캐싱, 대화 위 모델 목록의 **자동**·**로컬**, **설정 → 개발자 모드** ([설정](docs/adaptive-ai-setup.md), 1.17) |
| Code 에이전트(작업 맡기기) | **코드** → 맨 앞 **작업** 탭. 할 일을 적고 Ctrl+Enter. 계획·diff·실행 출력, 이어서 지시, 바뀐 파일 되돌리기 ([사용법](docs/code-editor-guide.md#code-에이전트-작업-맡기기-116), 1.16). 권한 모드(계획·전체 자동), 다시 묻지 않기, 작업 중 추가 지시, `/init` `/review` `/test` `/plan` `/undo` `/compact`, AGENTS.md, 격리 작업 공간(git worktree) (1.17.1) |
| Lab(실험 기록·비교·AI 분석) | 왼쪽 위 **Lab**. 실험·Run, 승인 실행, 재현성 기록, 결과 가져오기, 지표·그래프·비교, AI 분석 ([사용법](docs/lab-guide.md), 1.16) |
| 브라우저 에이전트 | 브라우저를 연 채 에이전트에게 웹 작업을 맡기면 페이지를 직접 조작합니다. 브라우저 막대에서 일시정지·멈춤 ([보안](docs/browser-agent-security.md), 1.16) |
| 코드(채팅 옆 편집기) | 왼쪽 위 **코드**. 파일 트리·편집·저장(Ctrl+S), 선택한 코드 AI에게 묻기, 에이전트 변경 덩어리별 검토, Git 상태·차이·스테이지·커밋, 명령 실행(승인) ([사용법](docs/code-editor-guide.md), 1.15) |
| 논문(채팅 옆 PDF) | 왼쪽 위 **논문**. PDF 열기·arXiv 번호, 선택한 부분·이 쪽·영역 잘라 묻기, 논문 요약, 라이브러리 논문 비교표 (1.14) |
| 브라우저(채팅 옆 웹페이지) | 왼쪽 위 **브라우저**. 주소창, 이 페이지에 대해 묻기·선택한 부분 묻기·연구 라이브러리에 저장 (1.13) |
| 플러그인(직무별 스킬 묶음) | 왼쪽 위 **플러그인**에서 설치·켜기·끄기. 입력창에 `/플러그인:스킬` (1.12) |
| 연구 라이브러리·에이전트 자동화 | 왼쪽 위 **연구 라이브러리**·**에이전트 자동화** (1.11부터 PO노트처럼 본문 화면) |
| 본인 Claude API 키로 쓰기 | **설정 → API 방식 → 일반 AI 모델 (Claude)** ([아래](#모델과-스트리밍)) |
| PO노트(강의 녹음·전사·필기 노트) | 왼쪽 위 **PO노트** ([아래](#po노트)) |
| 대화별 모델 선택 | OpenAI 호환·Responses API·일반 AI 모델(Claude)에서 위쪽 **대화 모델** 메뉴로 고릅니다. 각 대화의 선택은 따로 저장됩니다. |
| 크레딧 확인 | 왼쪽 아래 **설정** → POSTECH GenAI 크레딧(PO노트 화면에도 표시). 이 키의 이번 주 사용량·한도·남은 양. 확인 자체는 크레딧을 쓰지 않습니다. |
| 모델 API 사용량 보기 | 왼쪽 아래 **설정** → 모델 API 사용량. 이 앱에서 보낸 요청의 오늘·이번 달·최근 30일 호출 수와(서버가 알려 주면) 토큰 수. |

### 대화 간 정보 공유 (메모리 · 다른 대화 참고)

대화(스레드)마다 기록은 따로 저장되지만, 다음 두 가지 방법으로 서로 정보를 주고받습니다.

- **메모리**: 모든 대화에 공통으로 전달되는 기억입니다. 대화 중에 "~를 기억해 줘", "잊지 마"라고 하면 앱이 기억할 내용을 한 문장으로 정리해 저장합니다. 이때 대화에 `🧠 기억: …` 줄이 표시됩니다. `/remember 내용`으로 직접 추가할 수도 있습니다. "기억해?"처럼 묻는 말은 저장하지 않습니다.
- **다른 대화 참고**: 새 질문과 관련된 내용이 다른 대화에 있으면 자동으로 찾아 함께 참고합니다. 참고한 대화는 `📎 다른 대화 참고: …`로 표시됩니다. 에이전트 모드에서는 "지난번에 얘기한 …"처럼 말하면 `recall` 단계로 다른 대화를 직접 검색합니다. 메모리 창에서 끌 수 있습니다.

메모리는 `%APPDATA%\PostechChat\memory.md`에 Markdown으로 저장됩니다. `- `로 시작하는 줄 하나가 기억 하나이고, 메모리 창에서 항목을 보거나 지울 수 있으며 **memory.md 편집**으로 파일 전체를 직접 고칠 수 있습니다. 제목이나 설명을 더 써도 모두 대화에 전달되고, `<!-- -->` 안의 안내문만 빠집니다. 1.4 이전의 `memory.json`은 처음 실행할 때 memory.md로 옮겨집니다(원래 파일은 그대로 둡니다).

### 내 정보 (USER.md)

`%APPDATA%\PostechChat\USER.md`는 나에 대한 정보(하는 일, 관심 분야, 선호하는 답변 방식 등)이며, 작업 폴더의 INIT.md처럼 모든 대화에 함께 전달되어 답변을 나에게 맞추는 데 쓰입니다.

- **직접 쓰기**: 왼쪽 아래 **내 정보**에서 고치고 저장합니다.
- **AI로 작성·업데이트**: `/user`를 입력하면(또는 내 정보 창의 **AI로 작성·업데이트**) AI가 모든 대화의 최근 사용자 메시지와 메모리를 살펴보고 USER.md를 새로 쓰거나 고칩니다. 기존 내용은 어긋나지 않는 한 유지하고, 근거 없는 내용은 쓰지 않습니다. `/user 소속은 빼 줘`처럼 요청을 덧붙이거나 이력서 같은 파일을 첨부해 함께 보낼 수 있습니다. 바뀐 내용은 대화에 `📝 USER.md` 줄로 비교해 보여 줍니다.
- 비밀번호나 API 키 같은 비밀 정보는 적지 마세요. 내용은 질문할 때마다 POSTECH GenAI API로 전달됩니다.

### 파일 첨부

입력창 왼쪽 아래의 + 버튼으로 파일을 고르거나, 파일을 창에 끌어다 놓거나, 이미지를 붙여 넣으면 첨부됩니다. 파일은 하나에 20MB, 한 번에 10개까지입니다.

- **문서·텍스트**: PDF·Word·PowerPoint·Excel·한글 문서와 텍스트 파일(코드, CSV, Markdown 등)은 글자를 뽑아 질문과 함께 보냅니다(파일 하나에 2만 자, 한 번에 4만 자까지). 기억하는 이전 메시지 범위 안이면 다음 질문에서도 그 파일 내용을 다시 참고합니다.
- **이미지**(PNG·JPEG·GIF·WebP): 설정의 API 방식이 **OpenAI Responses API** 또는 **OpenAI 호환 API**일 때 모델이 이미지를 직접 봅니다. 기본 방식(a1)은 글자만 보낼 수 없습니다.
- 첨부한 파일은 `%APPDATA%\PostechChat\attachments`에 복사해 두고, 대화를 지우면 함께 지웁니다. 보낸 메시지의 파일을 누르면 알맞은 앱으로 엽니다.

### PO노트

강의를 녹음해 실시간으로 받아 적고, 강의 자료와 함께 복습용 필기 노트를 만듭니다. 왼쪽 위 **PO노트**에서 강의마다 노트를 만듭니다.

1. **새 강의 노트**를 만들고 **강의 자료**(PPT·PDF·Word·Excel·한글·텍스트, 노트 하나에 10개까지)를 올립니다.
2. **녹음 시작**을 누르면 마이크 소리를 말 구간마다 끊어 받아 적고 **전사** 탭에 `[분:초] 글`로 쌓습니다. 강의 중 떠오른 질문이나 칠판 필기는 **메모** 탭에 적습니다. 멈췄다가 **이어서 녹음**할 수 있습니다.
3. **노트 만들기**를 누르면 고른 모델이 강의 자료의 순서(슬라이드·페이지)를 뼈대로 전사와 메모를 합쳐 Markdown 필기 노트를 씁니다. 말로만 나온 설명은 `💬`, 시험·과제 같은 강조는 `⭐`로 표시하고, 끝에 핵심 정리·용어 정리·확인할 것을 둡니다. 전사가 길면 부분별로 정리한 뒤 합칩니다.
4. 노트·전사·자료 내용은 앱 안에서 보고, 노트는 **고치기**로 직접 고칩니다. **폴더 열기**로 `note.md`·`transcript.md`를 다른 앱에서 열 수 있습니다.

**음성 인식 설정**(PO노트 화면)에서 받아 적는 방식을 고릅니다.

| 방식 | 처리 | 비용 | 특징 |
|---|---|---|---|
| 자동 (기본, 권장) | 하이브리드: 로컬 AI가 바로 받아 적고, 약 2분치 구간 가운데 로컬 AI가 확신하지 못한 구간이 있을 때만 POSTECH 서버가 음성과 초안을 대조해 고칩니다 | 1시간에 0~약 420크레딧 | 글이 바로 뜨고, 서버가 실패해도 로컬 글이 남습니다. 줄마다 시각을 유지합니다. API 키가 없으면 로컬 AI만 씁니다. |
| POSTECH 서버로 모두 | OpenAI 호환 API의 Gemini 3.8 Flash가 음성(`input_audio`)을 받아 적습니다 | 1시간에 약 1,000~1,300크레딧(주간 한도 15,000의 약 7~9%) | 말 구간을 약 25초씩 모아 보냅니다. 실패하면 로컬 AI(있으면)로 받아 적습니다. |
| 로컬 AI만 | 이 PC에서 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)로 처리 | 없음(인터넷도 필요 없음) | CPU 스레드 2개만 쓰는 가벼운 모델. |

- **크레딧은 거의 호출 수로 정해집니다**(호출당 약 8크레딧 + 음성 1초당 약 0.05크레딧, 5초 9 · 23초 9 · 60초 10 · 120초 14크레딧으로 측정). 그래서 하이브리드는 서버 보정을 약 2분씩 모아 한 번에 보냅니다.
- **로컬 신뢰도**: 한국어 모델은 토큰 확률의 평균을 신뢰도로 냅니다. 0.8 아래인 줄은 전사 화면에서 흐리게 보이고, 그런 줄이 든 묶음은 서버가 보정합니다. 다국어 모델은 신뢰도를 내지 않아 모든 묶음을 보정합니다.
- **로컬 AI 정확도**(1.10.0, 독립 공개 데이터의 글자 오류율, 숫자 표기 차이는 뺌):
  - 측정 데이터: Zeroth-Korean(낭독 뉴스, 60문장)과 FLEURS 한국어(위키 문장 낭독, 60문장).

  | 로컬 모델 | Zeroth | FLEURS | 처리 속도(이 PC 기준, 실시간 대비) |
  |---|---|---|---|
  | 한국어 | 약 27% | 약 11% | 약 50배 빠름 |
  | 다국어 | 약 4% | 약 5% | 약 20배 빠름 |

  - 한국어 모델은 대화체(KsponSpeech)로 학습해 낭독 음성에 약하고, 신뢰도 0.8 이상인 줄도 10~17%가 틀렸습니다. 서버 보정이 이를 메웁니다.
  - 다국어 모델의 수치는 이 공개 데이터를 학습에 썼을 수 있어 낙관적일 수 있습니다.
  - 1.10.0부터 작은 소리(강의실 뒤쪽 등)를 키워서 인식합니다. 전에는 한국어 모델이 작은 소리에 빈 글을 냈습니다(FLEURS 오류율 46%→11%).
  - 영어가 섞이거나 정확도가 더 중요하면 다국어 모델을 고르세요.
- **크레딧 예산 보호**(기본: 30% 남기기): 이번 주 남은 크레딧이 한도의 이 비율 아래면 서버를 쓰지 않고 로컬 AI로만 받아 적어, 채팅과 노트 만들기에 쓸 크레딧을 남깁니다. 0~50% 또는 끄기로 바꿉니다.
- 자동 방식에서 로컬 모델이 아직 없으면 첫 녹음은 서버로 받아 적으면서 한국어 모델을 내려받고, 다음 녹음부터 하이브리드로 동작합니다.
- POSTECH GenAI에는 음성 인식 전용 API(`/audio/transcriptions`)가 없어서 Chat Completions의 음성 입력으로 받아 적습니다.

로컬 AI 모델은 둘 중에서 고릅니다.

| 모델 | 내려받기 | 언어 | 비고 |
|---|---|---|---|
| 한국어 (권장) | 약 76MB | 한국어 | k2-fsa Zipformer(KsponSpeech 학습). 가장 가볍고 한국어 띄어쓰기까지 정확합니다. |
| 다국어 | 약 240MB | 한국어·영어·일본어·중국어 | SenseVoice Small. 영어 강의나 한영 혼용 강의용입니다. |

- 말 구간은 음성 구간 검출(Silero VAD, 약 2MB, 첫 녹음 때 자동으로 내려받음)로 끊습니다. 녹음 소리 자체는 저장하지 않고 전사 글만 저장합니다.
- 마이크는 설정에서 고릅니다(기본: 시스템 기본 마이크). macOS는 처음 녹음할 때 마이크 권한을 묻습니다.
- **안드로이드**(1.10.0부터): 처음 녹음할 때 마이크 권한(과 Android 13부터 알림 권한)을 묻습니다. 녹음하는 동안 "PO노트 녹음 중" 알림이 떠 있고, 화면을 끄거나 다른 앱으로 가도 계속 받아 적습니다. 알림의 **녹음 중지**로도 멈춥니다. 인식은 휴대폰 안에서 하며(데스크톱과 같은 sherpa-onnx를 C 라이브러리로 넣었습니다), 이 때문에 APK가 이전보다 커졌습니다. 녹음 중에는 휴대폰 CPU를 써서 배터리가 평소보다 빨리 닳습니다.
- 데이터는 `%APPDATA%\PostechChat\po_notes\<id>\`(`meta.json`, `transcript.json`, `note.md`, `memo.md`, `materials\`)에, 로컬 AI 모델은 `stt_models\`에 저장합니다.

### 에이전트 모드

작업 폴더를 지정하고 에이전트를 켜면, AI가 목표를 이룰 때까지 단계를 반복합니다.

- `list` 폴더 보기 · `read` 파일 읽기 · `search` 내용 검색
- `write` 파일 작성 · `edit` 부분 수정 · `run` 명령 실행(Windows cmd)
- `skill` 스킬 불러오기 · `recall` 다른 대화 검색 · `done` 최종 답변
- `mcp` MCP 도구 실행(아래 [MCP](#mcp))

각 단계는 대화에 한 줄씩 표시되고, 누르면 자세한 내용(파일 내용, 변경 diff, 명령 출력)이 펼쳐집니다. **파일 수정과 명령 실행은 실행 전에 diff나 명령을 보여 주고 승인을 받습니다.** 설정에서 "파일 수정은 자동 허용" 등으로 바꿀 수 있습니다. 파일 도구는 경로를 검사해 작업 폴더 밖의 접근을 차단합니다. 다만 `run`은 작업 폴더를 시작 위치로 하는 일반 셸 명령이며, 운영체제 수준의 샌드박스가 아닙니다. 승인한 명령은 현재 사용자 권한으로 다른 위치나 네트워크에 접근할 수 있습니다.

작업 폴더가 없거나 에이전트를 끄면 일반 챗봇으로 동작합니다.

### 모델과 스트리밍

**설정 → API 방식**에서 고릅니다. 1.9부터 기본은 OpenAI 호환 API이며, 주소를 비워 두면 POSTECH GenAI 콘솔(에이전트 API → OpenAI Compatible API)의 `https://genai.postech.ac.kr/agent/openai_compatible/a1/v1/chat/completions`를 씁니다. Responses 방식은 콘솔에서 확인한 HTTPS 주소를 넣어야 저장할 수 있습니다. 새 대화의 기본 모델은 설정에서 고르고, 현재 대화 모델은 화면 위쪽 **대화 모델** 메뉴에서 바꿉니다. 각 대화는 생성 당시의 기본 모델 또는 직접 선택한 모델을 따로 저장하므로, 기본 설정을 바꿔도 기존 대화의 모델은 유지됩니다.

| 방식 | 주소 | 모델 | 특징 |
|---|---|---|---|
| OpenAI 호환 (기본, 권장) | 비워 두면 POSTECH 주소. 기본 주소(`.../v1`)만 넣어도 됨 | GPT·Claude·Gemini | Chat Completions, 표준 SSE 스트리밍. 인증은 `x-api-key`(다른 OpenAI 호환 서버를 위해 Bearer도 함께 보냄) |
| Responses | 콘솔에서 확인한 `.../a<번호>/openai/responses` | GPT-5 계열 | OpenAI Responses API, 표준 SSE 스트리밍 |
| a1/gpt (예전 기본값) | `agent/api/a1/gpt` | 서버가 정함 | 2026년 10월 현재 서버가 답변 대신 오류 코드 10000만 돌려줍니다. 1.9는 a1을 쓰던 설정을 한 번 OpenAI 호환으로 옮깁니다. |
| 일반 AI 모델 (Claude) (1.11) | `api.anthropic.com` (Claude Messages API) | Claude Opus 5.5(권장)·Sonnet 5.5·Haiku 5.5·Fable 5.1, 또는 키로 쓸 수 있는 모델 전체 | 본인 Claude API 키. 공식 Anthropic SDK(데스크톱)·같은 HTTP 요청(안드로이드), SSE 스트리밍, 이미지 첨부 |

모델 선택 방식에서 고를 수 있는 GPT 모델은 POSTECH 게이트웨이가 허용하는 목록입니다. 가격은 OpenAI 공개 가격(입력/출력 100만 토큰당, USD)이며, 학교 계정의 실제 과금·한도는 POSTECH GenAI 콘솔에서 확인하세요.

| 모델 | 용도 | 가격(입력/출력) |
|---|---|---|
| **GPT-5.1 (기본, 권장)** | 성능과 비용의 균형 | $1.25 / $10 |
| GPT-5.2 | 가장 좋은 성능 | $1.75 / $14 |
| GPT-5 | GPT-5.1의 이전 버전 | $1.25 / $10 |
| GPT-5 mini | 빠르고 저렴, 에이전트 단계가 많을 때 | $0.25 / $2 |
| GPT-4.1 mini | 추론 없는 저렴한 모델 | — |
| GPT-6.1 Sol | POSTECH GenAI 2026년 10월 안내 모델 | 콘솔에서 확인 |
| GPT-6 Astra | POSTECH GenAI 2026년 10월 안내 모델 | 콘솔에서 확인 |
| Claude Opus 5.5 | POSTECH GenAI 2026년 10월 안내 모델 | 콘솔에서 확인 |
| Claude Sonnet 5.5 | POSTECH GenAI 2026년 10월 안내 모델 | 콘솔에서 확인 |
| Gemini 3.8 Flash | POSTECH GenAI 2026년 10월 안내 모델 | 콘솔에서 확인 |

표의 10개 모델은 모두 OpenAI 호환 API에서 응답하는 것을 확인했습니다(2026년 10월). Claude 모델 ID는 점이 아니라 `-`를 씁니다(`claude-opus-5-5`, `claude-sonnet-5-5`). POSTECH 서버는 모델 목록(`GET .../models`)을 알려 주지 않으므로 기본 목록을 씁니다. 다른 OpenAI 호환 서버는 **모델 목록 불러오기**로 그 서버의 모델을 받아 저장할 때 반영합니다. GPT-5 계열은 Responses API에서도 계속 사용할 수 있습니다.

**일반 AI 모델 (Claude)** (1.11): [Anthropic 콘솔](https://console.anthropic.com)에서 발급한 본인 Claude API 키(`sk-ant-...`, 또는 환경 변수 `ANTHROPIC_API_KEY`)로 대화·에이전트·PO노트 노트 만들기·대화 요약·모델 평가를 모두 Claude API로 보냅니다. 요금은 그 키의 Anthropic 계정으로 청구되고 POSTECH 크레딧은 쓰지 않습니다. 키와 기본 모델은 POSTECH 쪽과 따로 저장되므로 방식만 바꿔 오갈 수 있고, 동기화되지 않습니다. Claude API는 음성을 받지 않으므로 PO노트의 서버 음성 보정과 크레딧 확인은 POSTECH 키가 있을 때만 씁니다(없으면 로컬 AI로만 받아 적습니다). Opus 5.5·Sonnet 5.5·Fable 5.1은 안전 정책으로 답하지 않으면 Anthropic이 권하는 다른 모델로 다시 답하게 합니다(server-side fallback).

**크레딧**: POSTECH GenAI는 모든 응답 헤더(`x-role-ratelimit-credit-usage`, `-limit`, `-interval`)에 이 키의 이번 주 크레딧 사용량과 한도를 담아 줍니다. 앱은 이 값을 설정 창과 PO노트에 보여 주고, **확인**을 누르면 크레딧을 쓰지 않는 요청(404가 나는 `GET .../models`)으로 새로 받습니다. 직접 잰 값(Claude Sonnet 5.5): 1크레딧 ≈ 입력 약 250토큰 또는 출력 약 75토큰이고, 짧은 질문도 호출마다 약 24크레딧이 듭니다. Claude Opus 5.5는 모두 두 배입니다. 에이전트 모드는 단계마다 모델을 한 번씩 부르므로 단계 수만큼 이 기본 비용이 붙습니다.

**스트리밍**(설정 → 답변을 받는 대로 표시)을 켜면 일반 대화의 답변이 글자가 오는 대로 표시됩니다. 기본으로 켜져 있습니다. 에이전트 모드는 단계 선택이 JSON이라 단계 진행만 표시하고 최종 답변은 한 번에 표시합니다. 모델 선택 방식은 OpenAI 표준 SSE를 씁니다. a1 방식은 스트리밍 형식이 문서에 없어서 SSE·JSON Lines·일반 텍스트를 모두 받아 주며, 알 수 없는 형식이면 자동으로 한 번에 받는 방식으로 다시 요청합니다. 표시가 이상하면 스트리밍을 끄세요.

### 문서 읽기

`read`와 `search`는 텍스트 파일뿐 아니라 다음 문서도 읽습니다. 문서에서 글자만 뽑아 AI에게 전달하며, 이미지·도형 안의 그림은 읽지 못합니다.

| 형식 | 읽는 내용 |
|---|---|
| PDF (`.pdf`) | 페이지별 텍스트. 스캔한 이미지 PDF와 암호 걸린 PDF는 읽지 못합니다. |
| Word (`.docx`) | 문단, 제목 단계, 글머리 기호, 표 |
| PowerPoint (`.pptx`) | 슬라이드별 텍스트, 표, 발표자 노트 |
| Excel (`.xlsx`, `.xlsm`) | 시트별 셀 값과 셀 주소(예: `B3=90`). 계산 값이 없는 수식은 수식으로 표시 |
| 한글 (`.hwp`, `.hwpx`) | 본문·표·글상자 텍스트. 암호·배포용 문서와 HWP 3.x 이하는 읽지 못합니다. |

예전 Office 형식(`.doc`, `.ppt`, `.xls`)은 읽지 못하므로 Office에서 새 형식으로 저장한 뒤 사용하세요. 문서는 50MB까지 읽고, `search`는 20MB 이하 문서만 검색합니다.

### MCP

1.10부터 MCP 목록은 **연결·도구 → MCP 서버** 탭에 있고, 커넥터(GitHub·Google 등)의 서버는 **커넥터** 탭에서 켭니다([API 레퍼런스](docs/api/reference.md)).

MCP(Model Context Protocol)는 AI 도구를 연결하는 표준입니다. 에이전트 모드에서 켜진 MCP 서버의 도구가 `mcp` 단계로 제공됩니다. 서버는 처음 필요할 때 작업 폴더를 현재 폴더로 해서 실행되고, 작업 폴더나 설정이 바뀌면 다시 실행됩니다. 앱을 닫으면 함께 종료됩니다.

**내장 서버**는 앱에 들어 있어 따로 설치할 것이 없고, 작업 폴더 안의 파일만 다룹니다. 모두 무료로 쓸 수 있습니다.

| 서버 | 도구 |
|---|---|
| `word` | `create_document`(마크다운으로 새 .docx), `append_content`(끝에 덧붙이기), `replace_text`(글자 바꾸기, 서식 유지) |
| `powerpoint` | `create_presentation`(슬라이드 목록으로 새 .pptx, 16:9), `add_slides`, `replace_text` |
| `excel` | `create_workbook`(시트·행으로 새 .xlsx, `=`로 시작하면 수식), `write_cells`(셀 주소부터 값 쓰기) |
| `paper` | `search`(arXiv·Semantic Scholar에서 논문 찾기), `info`(저자·게재처·인용 수·한 줄 요약·초록), `read`(목차를 찾아 섹션·쪽 단위로 본문 읽기), `related`(참고한 논문·인용한 논문), `download`(PDF를 작업 폴더에 저장) |
| `notion` | `search`, `read_page`(페이지를 마크다운으로), `query_database`(데이터베이스 행 보기·필터), `create_page`(마크다운으로 새 페이지·데이터베이스 행), `append_content`, `update_page`(제목·속성 바꾸기) |
| `firecrawl` | `scrape`(웹페이지를 마크다운으로), `search`(웹 검색, 본문까지 가져오기 선택), `map`(사이트의 페이지 주소 목록), `crawl`(여러 페이지 따라가며 읽기), `crawl_status` |

**추천 서버**는 앱이 실행 방법을 아는 외부 서버입니다. 기본으로 꺼져 있고 **MCP** 창에서 켭니다. PC에 [Node.js](https://nodejs.org)가 있어야 하며 휴대폰에서는 쓸 수 없습니다.

| 서버 | 내용 |
|---|---|
| `playwright` | [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp)(`@playwright/mcp@0.0.83`). 브라우저를 열어 페이지 이동·클릭·입력·스크린샷·폼 채우기. Windows에서는 설치된 Edge를 씁니다. 스냅숏·스크린샷은 작업 폴더의 `.playwright-mcp/`에 저장됩니다. 모든 조작은 명령 실행처럼 승인을 받습니다. |

#### 논문 읽기 (`paper`)

"이 논문 쉽게 설명해 줘: 1706.03762"처럼 arXiv 번호, DOI, 논문 URL, 작업 폴더의 PDF 경로, 또는 제목으로 요청합니다. 에이전트가 `paper-reading` 스킬에 따라 정보 → 목차 → 필요한 섹션 순서로 나눠 읽고 핵심 아이디어·방법·결과·용어 정리를 풀어 줍니다. 논문 검색과 PDF는 arXiv API(키 없음), 인용 수·한 줄 요약(TLDR)·arXiv 밖의 논문은 Semantic Scholar API를 씁니다. Semantic Scholar는 키 없이 쓸 수 있지만 요청이 몰리면 잠시 거절하므로, 자주 쓰면 무료 API 키를 받아 `SEMANTIC_SCHOLAR_API_KEY` 환경 변수로 넣으세요. 구독이 필요한 논문은 학교 도서관 등에서 PDF를 받아 작업 폴더에 넣으면 같은 방법으로 읽습니다. 스캔한 이미지 PDF는 글자를 읽지 못합니다.

#### Notion (`notion`)

1. https://www.notion.so/profile/integrations 에서 **새 통합**(내부)을 만들고 토큰(`ntn_...`)을 복사합니다.
2. 앱의 **설정 → Notion 통합 토큰**에 넣고 저장합니다(또는 `NOTION_TOKEN` 환경 변수).
3. Notion에서 다룰 페이지(또는 상위 페이지)의 오른쪽 위 **··· → 연결**에서 만든 통합을 추가합니다. 통합은 연결된 페이지와 그 하위 페이지만 볼 수 있습니다.

Notion에 쓰는 도구는 바깥 서비스를 바꾸므로 명령 실행처럼 승인을 받습니다.

#### 웹페이지 읽기 (`firecrawl`)

[Firecrawl](https://www.firecrawl.dev) API로 자바스크립트로 그리는 페이지까지 깔끔한 마크다운으로 읽습니다. firecrawl.dev에서 무료로 가입해 API 키(`fc-...`)를 받고 **설정 → Firecrawl API 키**에 넣으세요(또는 `FIRECRAWL_API_KEY` 환경 변수). 무료 요금제는 크레딧과 분당 요청 수(약 10회)에 한도가 있고, `crawl`은 쪽마다 크레딧을 씁니다. 직접 띄운 Firecrawl 서버는 `FIRECRAWL_API_URL`에 주소를 넣으면 씁니다.

**외부 서버**는 **MCP → 설정 파일 열기**로 `%APPDATA%\PostechChat\mcp.json`을 열어 Claude Desktop과 같은 형식으로 추가합니다. `npx`·`uvx` 같은 실행 도구가 필요한 서버는 그 도구가 PC에 설치되어 있어야 합니다. 내장 서버 이름(`word`, `powerpoint`, `excel`, `paper`, `notion`, `firecrawl`)은 쓸 수 없습니다. 추천 서버와 같은 이름(`playwright`)으로 적으면 적은 설정이 대신 쓰입니다.

```json
{
  "mcpServers": {
    "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."] }
  }
}
```

작업 폴더의 파일만 고치는 내장 도구는 파일 수정처럼, 외부 서버의 도구와 바깥에 영향을 주는 내장 도구(Notion에 쓰기)는 명령 실행처럼 실행 전에 승인을 받습니다(논문 검색·읽기, Notion 읽기처럼 서버가 읽기 전용이라고 밝힌 도구는 제외). 텍스트 파일용 `write`·`edit`로는 Office·PDF·한글 문서를 쓸 수 없습니다.

#### 다른 AI 에이전트와 기억 이어 쓰기 (ai-memory)

[ai-memory](https://github.com/akitaonrails/ai-memory)를 PC에 설치하고(`ai-memory setup`) 외부 서버로 등록하면, Claude Code·Codex·Cursor·Gemini CLI 같은 코딩 에이전트와 같은 기억을 씁니다. 그 에이전트들도 같은 ai-memory 서버에 연결되어 있어야 합니다.

```json
{
  "mcpServers": {
    "ai-memory": { "command": "ai-memory", "args": ["mcp-bridge", "--no-session-id"] }
  }
}
```

에이전트 모드에서 작업 폴더가 있으면 앱이 다음을 자동으로 합니다.

- 대화에서 처음 에이전트를 실행할 때 그 작업 폴더에 남은 인계(다른 에이전트가 하던 일·남은 질문·다음 할 일)를 받고 최근 기억 페이지를 불러와, 그 대화 내내 참고 자료로 넣습니다. 인계는 한 번 받으면 사라지는 방식이라 다른 에이전트가 같은 인계를 다시 받지는 않습니다.
- 파일을 고치거나 명령·도구를 실행한 뒤에는 요청과 결과, 고친 파일 목록으로 인계를 남겨, 다음에 Claude Code 등을 같은 폴더에서 열면 이어받게 합니다. 같은 대화에서 다시 남기면 앞의 인계는 취소되어 대화마다 하나만 열려 있습니다.
- 모델이 부르는 ai-memory 도구에는 `workspace`·`project`를 앱이 채웁니다. 이름은 ai-memory 규칙대로 정합니다: 가장 가까운 `.ai-memory.toml`의 값 → git 원격(`upstream`, 없으면 `origin`)의 호스트를 뺀 경로(예: `bj0322-poschat`) → 원격이 없으면 폴더 이름.

ChatGPT·claude.ai 같은 웹 채팅 서비스의 기억은 ai-memory가 기록하지 않으므로 이어받을 수 없습니다. `.ai-memory.toml`의 홈 폴더 경로 규칙(`[routes]`)은 아직 지원하지 않으니, 필요하면 작업 폴더의 `.ai-memory.toml`에 `workspace`와 `project`를 적으세요.

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

1. 앱 내장: `summarize`(문서 요약), `code-review`(코드 검토), `paper-reading`(논문을 나눠 읽고 쉽게 설명)
2. 사용자 공용: `%APPDATA%\PostechChat\skills\`. 앱의 **스킬 → 새 스킬 만들기**로 템플릿을 만들 수 있습니다.
3. 작업 폴더 전용: `<작업 폴더>\skills\`

## 동작 방식과 한계

POSTECH GenAI 서버의 모델은 자체 시스템 프롬프트 때문에 "사용자 PC에 접근하라"는 형식의 도구 호출을 거부합니다. 그래서 이 앱은 "진행 기록을 보고 다음 단계를 JSON으로 고르는 작업"으로 요청합니다. 모델이 그래도 형식을 거부하고 사용자에게 할 일을 안내하면, 앱이 그 안내문을 다음 단계로 바꾸거나 언급된 파일을 직접 읽어 진행을 이어 갑니다.

- 에이전트는 단계마다 API를 한 번씩 호출하므로, 여러 단계짜리 작업은 1~2분 걸릴 수 있습니다. 스트리밍은 일반 대화의 답변에만 적용됩니다.
- 모델이 가끔 같은 파일을 여러 번 읽는 등 불필요한 단계를 거칠 수 있습니다. 최대 단계 수는 설정에서 바꿉니다.
- 오류가 나면 `%APPDATA%\PostechChat\error.log`를 확인하세요.

## 개발

| 파일 | 역할 |
|---|---|
| `main.py` | pywebview 창과 JS↔Python 브리지 |
| `agent.py` | INIT.md·스킬 로딩, 에이전트 단계 루프와 도구 |
| `documents.py` | PDF·Word·PowerPoint·Excel·한글 문서의 텍스트 추출 |
| `mcp_client.py` | MCP 클라이언트: 서버 실행·연결·도구 호출, `mcp.json` 읽기 |
| `ai_memory.py` | ai-memory 연동: 작업 폴더의 workspace·project 결정, 인계 받기·남기기 |
| `office_mcp.py` | 내장 MCP 서버(word·powerpoint·excel)와 모든 내장 서버의 공통 실행 루프. 앱 exe를 `--mcp-server <이름>`으로 실행하면 이 서버가 됩니다. |
| `paper_mcp.py` · `notion_mcp.py` · `firecrawl_mcp.py` | 내장 MCP 서버 paper(arXiv·Semantic Scholar), notion(Notion API), firecrawl(Firecrawl API) |
| `api.py` | POSTECH GenAI API 호출(OpenAI 호환 Chat Completions / OpenAI Responses / a1), 스트리밍 해석, 이미지·음성 입력, 사용량·크레딧 기록 |
| `po_note.py` | PO노트 저장(전사·노트·메모·강의 자료)과 필기 노트 프롬프트·생성(긴 전사는 나눠 정리 후 합치기) |
| `updates.py` | 자동 업데이트: GitHub Releases 확인, 이 기기용 설치 파일 내려받기(크기·SHA-256 확인) |
| `stt.py` | PO노트 음성 인식: 마이크(sounddevice) → 음성 구간 검출(Silero VAD) → 로컬 AI(sherpa-onnx) 또는 POSTECH 서버, 모델 내려받기 |
| `attachments.py` | 채팅창 첨부 파일: 조각 업로드, 종류 확인, 문서·텍스트 내용 뽑기, 이미지 |
| `storage.py` | 대화·설정 저장(`%APPDATA%\PostechChat`), memory.md·USER.md, 첨부 파일 폴더, 모델 API 사용량, 다른 대화 검색 |
| `web/` | 화면(HTML/CSS/JS, marked·DOMPurify·KaTeX 포함). PO노트 화면은 `web/po.js` |
| `tests/` | 단위 테스트(`python -m unittest discover -s tests`) |
| `.github/workflows/build.yml` | 단위 테스트, Windows·macOS·Android 빌드와 플랫폼별 자가 진단, 태그 push 때 Release에 첨부 |
| `android/` | 안드로이드 앱(Kotlin WebView + Chaquopy). 빌드할 때 저장소 최상위의 Python 모듈·`web/`·`skills/`를 복사해 넣고, `android_main.py`가 pywebview 대신 화면과 Python을 연결합니다. |
| `certs.py` | 중간 인증서를 보내지 않는 서버를 위해 AIA로 중간 인증서를 받아 검증(Windows는 운영체제가 처리) |
| `installer/installer.py` | 설치 프로그램(`--silent --dir=<경로> --no-desktop` 지원) |
| `assets/` | 앱 아이콘 |
| `build_installer.py` | 앱과 설치 프로그램 빌드 |

- 소스로 실행: `run.bat`
- 진단: `PostechChat.exe --selftest`를 실행하면 API 연결, 문서 라이브러리, 내장 MCP 서버 연결 결과가 `%APPDATA%\PostechChat\selftest.txt`에 기록됩니다. 제거 명령은 `PostechChat.exe --uninstall`입니다.
- 설치 파일 빌드: `build.bat`, 또는 `python build_installer.py`. 결과는 `release\POSCHAT-Setup.exe`입니다.
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

빌드는 `%TEMP%\PostechChat-build`를 사용하며 결과는 `release\POSCHAT-Setup.exe`입니다. 빌드 결과는 Git에 포함하지 않습니다.

## 배포

안드로이드 APK는 `android/`에서 `./gradlew assembleRelease`(JDK 17, Android SDK, Python 3.11 필요)로 빌드합니다. 결과는 `android/app/build/outputs/apk/release/app-release.apk`입니다. 모든 빌드는 저장소의 공용 키(`android/app/poschat-shared.keystore`)로 서명해 덮어 설치가 되게 합니다. 공개 스토어에 올릴 때는 따로 보관한 키로 바꾸세요.

설치 파일은 GitHub Releases에 올립니다. `.github/workflows/build.yml`이 Windows·macOS·Android 빌드와 플랫폼별 검증을 자동으로 수행합니다.

- PR을 올리거나 Actions에서 **Build installer**를 수동 실행하면, 빌드한 `POSCHAT-Setup.exe`를 실행 결과의 Artifacts에서 받을 수 있습니다.
- 버전 태그를 push하면 같은 빌드가 그 태그의 Release에 첨부됩니다. 단위 테스트가 실패하면 Release를 만들지 않습니다.

  ```powershell
  git tag v1.2.0
  git push origin v1.2.0
  ```

  태그를 직접 push하지 않고 Actions에서 **Build installer → Run workflow**의 `release` 칸에 `v1.2.0`을 넣어 실행해도 됩니다. 이 경우 실행한 커밋에 태그와 Release가 만들어집니다.
- 사용자에게는 항상 최신 버전을 가리키는 링크 `https://github.com/bj0322/POSCHAT/releases/latest/download/POSCHAT-Setup.exe`를 안내하면 됩니다. 저장소가 비공개이면 저장소 권한이 있는 사용자만 받을 수 있습니다.
- **자동 업데이트**(1.9.1부터): 앱이 시작할 때(6시간에 한 번) `https://api.github.com/repos/bj0322/POSCHAT/releases/latest`로 최신 정식 릴리스를 확인합니다. 새 버전이 있으면 릴리스 노트와 함께 알리고, **업데이트**를 누르면 이 기기용 파일(`POSCHAT-Setup.exe`·`POSCHAT-mac.dmg`·`POSCHAT.apk`, 1.11부터의 이름. 릴리스에는 1.9.1~1.10.0 앱을 위해 예전 이름 `PostechChat-*`도 함께 올립니다)을 받아 Releases가 알려 준 크기와 SHA-256(digest)을 확인합니다.
  - Windows: 설치 프로그램을 지금 설치 폴더로 열고 앱이 스스로 닫힙니다. 설치 프로그램에서 **설치**를 누르면 앱이 완전히 닫히기를 기다렸다가(1.11부터, 한 번만 누르면 됨) 대화·설정을 유지한 채 바뀝니다. 30초가 지나도 닫히지 않으면 강제로 종료할지 묻습니다.
  - macOS: 디스크 이미지를 엽니다. 앱을 끝낸 뒤 응용 프로그램 폴더로 끌어다 놓아 바꿉니다.
  - Android: 설치 화면을 엽니다(처음 한 번 "이 출처 허용"이 필요합니다).
  - 토큰 없이 공개 API를 쓰므로 **저장소가 공개일 때만** 동작합니다. 비공개인 동안은 확인하지 못했다고만 알리고(시작할 때는 알리지 않음) 사용에는 지장이 없습니다.
  - **설정 → 업데이트**에서 시작할 때 확인을 끄거나 지금 확인할 수 있고, 알림 창에서 **이 버전 건너뛰기**를 고를 수 있습니다.

- 설치 파일에는 코드 서명이 없어서 처음 실행할 때 Windows SmartScreen 경고가 뜰 수 있습니다. 경고는 코드 서명 인증서로 서명해야만 없앨 수 있습니다. 인증서(.pfx)를 base64로 바꿔 저장소 Secrets의 `WINDOWS_SIGN_PFX_BASE64`에, 비밀번호를 `WINDOWS_SIGN_PASSWORD`에 넣으면 빌드가 앱 exe와 설치 파일에 서명합니다(로컬 빌드는 `WINDOWS_SIGN_PFX`·`WINDOWS_SIGN_PASSWORD` 환경 변수). 서명한 파일도 다운로드가 쌓여 평판이 생길 때까지는 경고가 남을 수 있습니다.

## v1.1.0 아키텍처

1. `web/app.js`가 `window.pywebview.api`를 통해 `main.py`의 `Bridge`를 호출합니다. `/remember`, `/memory`, `/help`는 화면에서 처리합니다.
2. `Bridge`는 대화와 설정을 관리하고 백그라운드 스레드에서 `Agent`를 실행합니다. 진행 상황·도구 결과·승인 요청은 `window.onBackendEvent`로 화면에 전달합니다.
3. `agent.py`는 공통 메모리, 관련 대화, 최근 메시지와 INIT.md·스킬을 조합합니다. 일반 대화는 한 번의 답변 요청으로, 에이전트는 JSON 단계 선택과 로컬 도구 실행의 반복으로 처리합니다.
4. `api.py`는 POSTECH GenAI 엔드포인트를 지원합니다. a1은 `X-Api-Key`, Responses는 `x-api-key`, OpenAI 호환 Chat Completions는 Bearer 토큰으로 인증합니다. 일반 대화는 스트리밍으로 받아 `delta` 이벤트로 화면에 보냅니다. TLS 검증에는 `truststore`를 통해 운영체제 인증서 저장소를 사용합니다.
5. `storage.py`는 JSON 파일을 임시 파일에 쓴 뒤 교체합니다. 다른 대화 검색은 한국어·영문·숫자의 문자 bigram 겹침을 사용하며 벡터 DB나 임베딩 서버를 사용하지 않습니다.

자동 대화 참고는 기본 활성화되며 메모리 창에서 끌 수 있습니다. 현재 구현에서 이 설정은 자동 참고를 제어하며, 에이전트의 명시적 `recall` 검색은 별도로 실행될 수 있습니다. 기본 에이전트 단계 한도는 25, 대화 이력은 20개 메시지이고 설정에서 바꿀 수 있습니다.

## 데이터와 저장소 관리

- API 키를 설정 창에 입력하면 `%APPDATA%\PostechChat\config.json`에 평문으로 저장됩니다. 공용 PC에서는 환경 변수를 사용하는 등 보관 방식을 신중히 선택하세요.
- 대화·공통 메모리·사용자 정보(USER.md)·첨부 파일 내용·관련 대화 발췌·읽은 파일 및 명령 출력은 답변 생성에 필요할 때 POSTECH GenAI API로 전달됩니다.
- 사용자 대화, 메모리, 설정, 로그, 개인 API 키는 소스 저장소에 포함하지 않습니다. `.gitignore`는 이 파일들과 가상환경·캐시·빌드 결과·실행 파일을 제외합니다.
- 앱 소스, 설치 프로그램 소스, 실행·빌드 스크립트, 기본 스킬 3종, 아이콘, 정적 UI와 번들 JavaScript 라이브러리를 포함합니다. `web/vendor/` 파일은 UI 실행에 필요한 배포 의존성이므로 포함하며, 원본 저작권·라이선스 주석을 유지합니다.
- 이 저장소는 v1.1.0 소스 스냅샷을 시작점으로 합니다. 이전 버전의 코드·변경 이력은 가져오지 않습니다.

## 버전 기록

각 버전의 자세한 내용은 [docs/release-notes](docs/release-notes)에 있습니다.

- 1.17.0 — **AI 실행 정책(Adaptive Hybrid AI)**: 켜면 요청의 종류·난이도·개인정보·비용을 보고 **로컬 AI(Ollama)**, **경량 Cloud 모델**(Haiku·GPT-5 mini 등), **프런티어 모델** 중 하나를 자동으로 고르고, 로컬·경량 답을 규칙으로 검증해 필요하면 위 단계로 다시 답합니다. 경량 모델이 대화를 이끌며 필요한 부분만 프런티어에 짧게 상담하는 3단계(실험, 켜야 씀), 단가 비율로 요청마다 계산하는 손익분기·프롬프트 캐싱, Economy·Balanced·Quality·Local Only 정책, 답변 아래 '왜 이 모델인지' 표시, 비용·통계, 개발자 모드(실측 토큰·손익분기 원자료). 기본은 꺼짐. [릴리스 노트](docs/release-notes/v1.17.0.md) · [설정](docs/adaptive-ai-setup.md) · [보안](docs/adaptive-ai-security.md) · [벤치마크](docs/adaptive-ai-benchmark-results.md)

- 1.16.0 — **Code 에이전트**: 코드 화면의 **작업** 탭에서 할 일을 맡기면 Codex·Claude Code처럼 에이전트가 계획을 세우고, 코드를 읽고·고치고·테스트를 실행해 확인합니다(수정은 바로 적용하고 되돌리기 가능, 명령은 매번 승인). **POSCHAT Lab**: 실험 조건·코드 버전(Git)·실행 환경·결과를 Run마다 기록하고, 결과 파일에서 고른 지표를 뽑아 그래프·비교표로 보고, 고른 Run만 AI에게 해석을 묻습니다. **AI 브라우저 에이전트**: 에이전트가 옆 브라우저를 직접 조작합니다(제출·삭제·로그인·결제·다운로드 등은 언제나 승인). 사이드바의 채팅 목록이 더 길어졌습니다. [릴리스 노트](docs/release-notes/v1.16.0.md) · [Lab 사용법](docs/lab-guide.md) · [브라우저 에이전트 보안](docs/browser-agent-security.md)

- 1.15.0 — **POSCHAT Code**: 왼쪽 사이드바의 코드를 누르면 채팅 옆에 작업 폴더의 파일 트리와 편집기(CodeMirror 6, Python·C/C++·JS/TS·Verilog/SystemVerilog 강조)가 열립니다. 안전하게 저장하고(원자적 저장·줄 끝·인코딩 유지·외부 변경 감지), 선택한 코드를 경로·줄 번호와 함께 AI에게 묻고, 에이전트가 고친 내용을 덩어리(hunk)마다 받아들이거나 거부하고, Git 변경을 보고 고른 파일만 스테이지·커밋하고, 승인한 명령(Verilator·iverilog 등)을 실행해 출력을 봅니다. **브라우저를 열면 앱이 멈추던 문제(B1) 수정**. [릴리스 노트](docs/release-notes/v1.15.0.md) · [사용법](docs/code-editor-guide.md) · [보안](docs/code-security.md)

- 1.14.0 — **논문 읽기(POSCHAT Paper)**: 왼쪽 사이드바의 논문을 누르면 채팅 옆에 PDF가 열립니다(이 기기의 PDF, arXiv 번호·PDF 주소, 연구 라이브러리 논문). 드래그한 문장·보고 있는 쪽·잘라 낸 그림·표·수식을 바로 묻고, 쪽 번호가 붙은 요약과 여러 논문의 실험 조건·결과 비교표를 만듭니다. 에이전트는 열린 논문을 필요한 쪽만 읽습니다(`paper_read`). [릴리스 노트](docs/release-notes/v1.14.0.md)

- 1.13.0 — **브라우저**: 왼쪽 사이드바의 브라우저를 누르면 채팅 옆에 웹페이지가 열리고, 보고 있는 페이지(또는 선택한 부분)를 AI에게 묻거나 논문 페이지를 연구 라이브러리에 저장합니다. 에이전트도 열린 페이지를 읽습니다. 웹페이지 쪽에는 POSCHAT의 파일·실행·MCP·API 키에 닿는 통로가 없습니다. [릴리스 노트](docs/release-notes/v1.13.0.md)

- 1.12.0 — **플러그인**: 왼쪽 사이드바에서 Anthropic의 Knowledge Work Plugins(직무별 스킬 묶음: Productivity·Bio Research·Data·Engineering·Legal 등)를 둘러보고 설치하면, 에이전트가 그 분야의 절차대로 일하고 `/플러그인:스킬`로 직접 부를 수 있습니다. 대화상자·초점·스위치 등 접근성 개선. 설치 프로그램 안정화(설치 전 필수 파일·손상 확인, 설치 후 실행 확인, 되돌리기 실패 감지와 백업 보존). [릴리스 노트](docs/release-notes/v1.12.0.md)

- 1.11.1 — 업데이트 뒤 앱이 열리지 않던 문제(python312.dll·VCRUNTIME140.dll 오류) 수정: 새 파일을 먼저 풀고 이전 파일과 바꾸며, 실패하면 이전 버전을 되돌립니다. 1.11.0에서 앱이 열리지 않으면 Releases의 `POSCHAT-Setup.exe`를 받아 설치하세요. [릴리스 노트](docs/release-notes/v1.11.1.md)

- 1.11.0 — **이름을 POSCHAT으로 정식 변경**, **일반 AI 모델(Claude)**: 설정 → API 방식에서 고르면 본인 Claude API 키로 대화·에이전트·노트 만들기 등 모든 모델 호출을 합니다(기본은 그대로 POSTECH GenAI). **연구 라이브러리·에이전트 자동화를 PO노트처럼 사이드바에서 여는 화면으로** 옮겼고, 업데이트할 때 설치 프로그램에서 '설치'를 두 번 눌러야 하던 문제를 고쳤습니다. 자세히: [릴리스 노트](docs/release-notes/v1.11.0.md)

- 1.10.0 — **POSCHAT 2.0: 연결·도구**. 왼쪽 아래 **연결·도구**에서(모두 기본 꺼짐) GitHub·Google Workspace(Drive·Docs·Sheets·Slides·Gmail·Calendar)·Zotero 커넥터, 통합 논문 검색·라이브러리·BibTeX·출처가 붙은 문서 검색(RAG), 프로젝트·연구 메모리와 에이전트 인계, 기기 사이 종단간 암호화 동기화, Python·Jupyter·SSH 실행(PC, 매번 승인), 사용량·진단과 모델 평가. 메일 전송·리뷰 제출·삭제·코드 실행은 자동 허용 설정이어도 매번 묻습니다. 1.6부터 에이전트의 MCP 도구 호출이 실패하던 버그 수정. 자세히: [릴리스 노트](docs/release-notes/v1.10.0.md) · [설치·설정](docs/setup.md) · [마이그레이션](docs/migration-1.10.md) · [보안](docs/security.md) · [API](docs/api/reference.md) · [아키텍처](docs/architecture/) **안드로이드 앱에서도 PO노트 녹음**: 휴대폰의 로컬 AI(sherpa-onnx)가 받아 적고 불확실한 구간만 POSTECH GenAI가 보정하는 하이브리드를 데스크톱과 같이 씁니다(화면을 꺼도 녹음 유지, 알림에서 중지). 로컬 AI가 작은 소리를 받아 적지 못하던 문제 수정. 데스크톱의 sherpa-onnx를 1.13.8로 고정

- 1.9.2 — 자동 업데이트 시험용 릴리스(기능 변경 없음). 1.9.1에서 업데이트 알림부터 설치까지 확인하는 데 씁니다

- 1.9.1 — **자동 업데이트**(시작할 때 GitHub Releases에서 새 버전을 확인하고, 받은 설치 파일의 크기·SHA-256을 확인한 뒤 설치 시작), 설정 창의 버전 정보 아래에 서비스 대표자(김범준)와 문의 안내, README에 문의 메일

- 1.9.0 — **PO노트**: 강의를 녹음해 실시간으로 받아 적고(이 PC의 로컬 AI가 바로 받아 적고 불확실한 구간만 POSTECH GenAI가 보정하는 하이브리드, 크레딧 예산 보호), 강의 자료(PPT·PDF·Word·한글)와 함께 Markdown 필기 노트를 만들어 앱 안에서 보고 고칩니다. **POSTECH GenAI 크레딧 확인**(이번 주 사용량·한도·남은 양). OpenAI 호환 API를 기본 방식으로 바꾸고 POSTECH 주소를 내장(a1/gpt는 현재 서버 오류만 돌려줌), 게이트웨이 인증(`x-api-key`)과 Claude 모델 ID(`claude-opus-5-5`) 수정, 주소의 `?쿼리` 유지, 설정 창에서 취소하면 불러온 모델 목록을 버림, 사용법 가이드의 표 깨짐 수정. 설치 파일 코드 서명 준비(인증서를 넣으면 빌드가 서명)

- 1.8.2 — OpenAI 호환 API의 모델 목록을 서버에서 불러오기, 기본 주소(Base URL)만 넣어도 동작, 필수 API 주소 검증, 대화별 모델 선택. 앱 안의 자동 업데이트(CDN)는 빼고 새 버전은 Releases에서 받습니다

- 1.7.0 — 다른 AI 코딩 에이전트(Claude Code·Codex 등)와 기억 이어 쓰기(ai-memory 연동: 인계 받기·남기기, 기억 범위 자동 지정), 설정 창의 사용법 가이드

- 1.6.0 — 채팅창 파일 첨부(이미지·문서·텍스트), 메모리를 Markdown 파일(memory.md)로 관리, 사용자 정보 파일(USER.md)과 `/user`, 웹페이지 읽기·웹 검색 내장 MCP 서버(firecrawl), 브라우저 자동화 추천 서버(Playwright, MCP 창에서 켜기), 설정 창에서 모델 API 사용량 보기. 잘 동작하지 않던 HTML 영상 서버(hyperframes) 제거

- 1.5.0 — 내장 MCP 서버 추가: 논문 찾기·섹션별 읽기(paper), Notion 페이지·데이터베이스(notion), HTML로 영상 만들기(hyperframes). 논문을 쉽게 풀어 주는 `paper-reading` 스킬

- 1.4.0 — 안드로이드 앱(같은 화면·에이전트·문서 읽기·MCP를 휴대폰에서)

- 1.3.1 — 설치 프로그램과 Windows 앱 목록에 표시되는 버전을 앱 버전과 맞춤

- 1.3.0 — 답변 스트리밍 표시, GPT 모델 선택(OpenAI Responses API, 기본 권장 GPT-5.1)

- 1.2.0 — PDF·Word·PowerPoint·Excel·한글 문서 읽기, MCP 지원과 내장 오피스 MCP 서버(Word·PowerPoint·Excel 만들기·고치기), 답변의 LaTeX 수식 표시

## 라이선스 (License)

Copyright © 2026 Beomjoon Kim (bj0322)

POSCHAT의 새 공식 배포본은 **GNU Affero General Public License v3.0 only (AGPL-3.0-only)**를 따릅니다. 전문은 [LICENSE](LICENSE), 전환 이력은 [LICENSE_HISTORY.md](LICENSE_HISTORY.md)에 있습니다. "or later"(이후 버전 선택)는 적용하지 않습니다.

1. **적용 범위**: v1.10.0부터의 공식 배포본과, 전환 커밋 `3edf859` 이후의 이 저장소 코드에 AGPL-3.0-only가 적용됩니다.
2. **할 수 있는 것**: AGPL 조건에 따라 누구나 사용·연구·수정·재배포할 수 있습니다.
3. **소스 제공 의무**: 수정한 버전을 배포하거나, 수정한 버전을 네트워크로 다른 사람이 이용하게 하는 경우 등 AGPL이 요구하는 경우에는 그 버전의 해당 소스코드(Corresponding Source)를 AGPL로 제공해야 합니다.
4. **상업적 이용**: AGPL은 판매·유료 제공 같은 상업적 이용 자체를 금지하지 않습니다. 이 프로젝트는 AGPL 원문 외의 추가 금지 조항을 두지 않습니다.
5. **과거 MIT 배포본**: v1.2.0~v1.9.2(태그)와 전환 커밋 이전의 코드는 MIT License로 배포되었고, 그 버전을 받은 사람의 MIT 권리는 그대로 유지됩니다(철회하지 않습니다).
6. **POSTECH GenAI API는 별개**: 이 소프트웨어 라이선스는 POSTECH GenAI API 이용 권한이나 POSTECH 명칭·상표 사용권을 주지 않습니다. API는 본인에게 발급된 키와 서비스 제공자의 이용 조건을 따릅니다.
7. **제3자 구성 요소**: 번들 라이브러리와 설치 파일에 들어가는 패키지, 실행 중에 내려받는 모델·도구는 각자의 라이선스를 따릅니다.

앱의 **설정** 맨 아래에서 라이선스 전문(**라이선스 보기**), 설치한 버전과 같은 태그의 소스코드(**소스 코드 보기**), 제3자 라이선스를 볼 수 있습니다. 각 Release 본문에도 그 바이너리에 대응하는 소스(같은 태그)를 적습니다. 의존성별 호환성 검토는 [docs/license-audit.md](docs/license-audit.md)에 있습니다.

번들 라이브러리의 버전, 출처, 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리했습니다. 원문은 `licenses/`에 보관하며, 제3자 파일은 각 원본 라이선스를 따릅니다.
