# AI 브라우저 에이전트 구조 (1.16)

보안 정책은 [../browser-agent-security.md](../browser-agent-security.md). 브라우저 자체(네이티브 웹 뷰, 격리)는 1.13 `browser.py`.

## 파일
| 파일 | 하는 일 |
|---|---|
| `browser_agent.py` | `BrowserAgent`(에이전트 한 번 실행 동안의 상태), 페이지에 넣는 스크립트(`SNAPSHOT_SCRIPT`·`ACTION_SCRIPT`·`PAGE_SCRIPT`), 위험 판단 `classify`, 사이트 범위 `site_of`·`local_host` |
| `agent.py` | 단계 `browser_snapshot`·`browser_click`·`browser_type`·`browser_select`·`browser_scroll`·`browser_wait`·`browser_extract`·`browser_screenshot`·`browser_open`·`browser_back`·`browser_forward`·`browser_refresh`(+ 1.13의 `browser_read`). 관찰은 외부 데이터로 감싼다 |
| `browser.py` | `Browser.watch`: 주소가 바뀌면 에이전트에 알린다(네이티브 처리기에서 오므로 표시만) |
| `browser_win.py`·`browser_mac.py` | `screenshot()`: WebView2 `CapturePreviewAsync`, WKWebView `takeSnapshot` → PNG |
| `browser_api.py` | `browser_agent_pause`(일시정지·계속), `_browser_pause_event` |
| `main.py` | `_work`가 Agent에 `browser_progress`(화면 이벤트)·`browser_paused`를 넘기고, 끝나면 `watch`를 풀고 캡처를 채팅에 파일로 남긴다 |
| `web/browser.js` | 브라우저 막대의 진행 줄(동작·상태·횟수·시간, 일시정지·계속·멈춤) |

## 동작 방식
페이지 조작은 모두 `backend.read(스크립트)`(1.13에 있던 '페이지에서 스크립트 실행 → JSON 문자열')로 한다. 새 네이티브 통로를 열지 않는다.

1. **snapshot**: 보이는 상호작용 요소(링크·버튼·입력·선택·role 요소·contenteditable)를 화면에 가까운 순으로 최대 150개 고르고, 요소에
   `data-poschat-id="<스냅샷 토큰>-eN"`을 단다. 이름(aria-label·label·글·placeholder), 종류, 주소, 값(민감한 칸은 ●●●●), 비활성·체크·화면 밖,
   폼 정보(제출 버튼·보낼 곳·비밀번호 칸 있음), 다운로드·파일 칸 표시를 돌려준다. 같은 이름이 여럿이거나 이름이 없으면 '이름 모호'.
   새 스냅샷은 이전 표시를 모두 지우고 새 토큰을 쓴다.
2. **동작**: Python이 스냅샷에서 요소를 찾고 → 위험 판단·승인 → 스크립트가 같은 토큰·ID의 요소를 찾아 태그·이름이 스냅샷과 같은지 확인한 뒤 동작
   (click: `scrollIntoView`+`click()`, type: 값 setter + input/change 이벤트, enter면 `requestSubmit`, select: 값 또는 보이는 이름).
   요소가 없거나 바뀌었으면 동작하지 않고 '다시 snapshot'을 요구한다.
3. **확인**: 동작 뒤 페이지가 다 열리기를 기다리고 주소·제목을 다시 읽는다. 주소가 바뀌면 스냅샷을 무효로 한다. 허용하지 않는 주소(오류 페이지·file: 등)면 뒤로 간다.
   다른 사이트로 옮겨 갔으면(리다이렉트 포함) 관찰에 적는다. 그 사이트에서 누르기·입력·고르기를 하려면 `_check_page`가 그 호스트의 승인을 받는다.
   관찰에 들어가는 주소·제목·요소 이름은 모두 `connectors.wrap_untrusted` 안에 넣는다(페이지 제목 속 지시도 외부 데이터).
4. **사용자 조작과 다시 맞추기**: 사용자가 직접 이동하면(`Browser.watch`로 감지, 에이전트가 기다리던 이동이 아니면) 스냅샷을 무효로 하고 다음 관찰에
   "사용자가 직접 페이지를 바꿨습니다"를 붙인다. 같은 페이지 안의 변화는 동작 직전의 요소 확인이 잡는다.

## 사이트 승인(kind `site`)
`site`는 `connectors.ALWAYS_ASK`에 있어 설정의 '모두 자동'·'이번 실행 동안 허용'이 듣지 않는다. 승인 단위는 호스트 전체(`site_of`: 앞의 `www.`만 뗌 —
`github.io`·`vercel.app`처럼 남과 함께 쓰는 주소를 한 사이트로 묶지 않는다). 승인한 호스트는 `BrowserAgent.approved`에 이번 실행 동안만 남는다.
- `open`(에이전트가 만든 주소): 승인한 호스트가 아니면 묻는다. 시작 페이지의 호스트도 처음 한 번은 묻는다(주소에 정보를 실어 보내는 길).
- 링크 누르기: 시작 호스트·승인한 호스트 안이면 바로(`sites`), 다른 호스트면 묻는다. 링크 주소는 페이지가 정한 것이라 에이전트의 정보가 실리지 않는다.
- 누르기·입력·고르기: 지금 페이지의 호스트가 `approved`에 없으면 묻는다(`_check_page`). 페이지 스크립트는 넣은 글을 읽을 수 있어서다.
- 로컬·사설 네트워크(`local_host`: 사설·루프백·링크 로컬 IP, `2130706433`·`0x7f.1` 같은 숫자 꼴, `*.local`·`*.lan`, `nip.io` 같은 이름→IP DNS)로의 이동은 매번 묻는다.

## 제한
`MAX_ACTIONS`=40(한 번 실행), `MAX_SECONDS`=600, 같은 동작(인자까지) 세 번 연속 금지(기다리기·스크롤·스냅샷 제외), 기다리기 최대 15초, 요소 150개, 페이지 글 6000자.
일시정지는 다음 동작 전에 기다리고, 채팅의 중지(`stop`)는 일시정지 중이어도 멈춘다.

## 스레드
에이전트는 작업 스레드에서 돈다. `backend.read`는 UI 스레드에 스크립트를 맡기고 결과를 기다리므로 네이티브 처리기(UI 스레드)에서 부르지 않는다(B1).
`Browser.watch`(UI 스레드에서 옴)는 변수만 바꾸고 바로 돌아온다. 진행 이벤트는 `Bridge._push` → `ui_events.EventPump`(kind가 있어 합치지 않음).

## 시험
- `tests/test_browser_agent_live_ui.py`: Playwright Chromium을 backend로 끼워 실제 스크립트로 로컬 페이지를 조작(스냅샷·같은 사이트 이동·ID 무효·스크롤·기다리기·읽기·입력·고르기·제출 승인·
  비밀번호 가림·위험 버튼·모호한 요소·다운로드·리다이렉트·막힌 주소·새 사이트·로컬망·사용자 이동·DOM 바뀜·제한·일시정지·캡처·에이전트 루프 연동).
- `tests/test_browser_agent_ui.py`: 진행 줄·일시정지·멈춤(Chromium 화면).
- `tests/browser_spike.py`(CI windows·macos 실제 창): 네이티브 뷰에서 스냅샷·입력·고르기·제출·캡처.
