# Universal AI Memory Hub — 외부 AI 연결 검증

POSCHAT의 통합 메모리를 다른 AI가 함께 쓰는 방법과, 각 서비스가 **실제로** 지원하는지 확인한 결과. (2026-10 기준, 공식 문서와 공개 자료로 확인. 실제 계정으로 연결해 본 것은 아님)

## 제공하는 인터페이스

| 인터페이스 | 형태 | 구현 |
|---|---|---|
| Memory Search API | MCP 도구 `memory_search` | `memory_mcp.py` → `memory_store.search` |
| Memory Write API | MCP 도구 `memory_write`, `memory_delete` | `memory_store.write/delete` |
| Project Context API | MCP 도구 `project_context` | `memory_store.project_context` |
| Agent Handoff API | MCP 도구 `handoff_create/list/accept/complete` | `handoff.py` ([schema](../api/handoff.schema.json)) |
| MCP Memory Server | stdio MCP 서버 `PostechChat --mcp-server memory` | `office_mcp.serve("memory")` |

프로젝트 키는 서버의 작업 폴더에서 ai-memory와 같은 규칙(`.ai-memory.toml` → git 원격 → 폴더 이름)으로 정한다. 그래서 같은 저장소를 연 에이전트들은 같은 프로젝트 기억을 본다. 다른 클라이언트가 쓴 기억은 `source=external:<clientInfo.name>`으로 남고, POSCHAT 프롬프트에는 "참고 자료"로만 들어간다.

## 클라이언트별 지원 여부

| 클라이언트 | 로컬 stdio MCP | 연결 방법 | 상태 |
|---|---|---|---|
| Claude Desktop | 지원 | `claude_desktop_config.json`의 `mcpServers`에 연결·도구 → 메모리·동기화의 JSON을 넣는다 | 형식 확인, 실제 연결은 사용자 환경 검증 필요 |
| Claude Code | 지원 | `claude mcp add poschat-memory -- "<실행 파일>" --mcp-server memory` | 형식 확인, 사용자 환경 검증 필요 |
| Gemini CLI | 지원 | `~/.gemini/settings.json`의 `mcpServers`(`command`·`args`) 또는 `gemini mcp add` | 형식 확인, 사용자 환경 검증 필요 |
| Codex CLI | 지원 | `~/.codex/config.toml`의 `[mcp_servers.poschat-memory]` `command`·`args` 또는 `codex mcp add poschat-memory -- "<실행 파일>" --mcp-server memory` | 형식 확인, 사용자 환경 검증 필요 |
| ai-memory 연동 에이전트 | 해당 없음 | 기존 1.6+ 기능(ai-memory 인계)과 함께 동작 | 기존 기능 유지 |
| ChatGPT (웹·앱) | **미지원** | Developer Mode의 커넥터는 원격 HTTPS(SSE·Streamable HTTP) MCP 서버만 붙는다 | 원격 게이트웨이가 있어야 함 → 향후 작업 |
| claude.ai (웹) | **미지원**(로컬) | 사용자 지정 커넥터는 원격 MCP 서버 URL | 원격 게이트웨이 필요 → 향후 작업 |
| Gemini 웹·앱 | **미지원** | 로컬 MCP를 붙이는 공개 방법을 찾지 못함 | 지원한다고 가정하지 않음 |

## 원격(HTTPS) 연결이 필요한 서비스에 대해

웹 서비스는 사용자의 PC에서 도는 stdio 서버에 닿을 수 없다. 연결하려면 인증(OAuth)·TLS가 있는 **원격 MCP 게이트웨이**를 사용자가 운영해야 하며, 개인 기억을 인터넷에 노출하는 결정이므로 이번 릴리스에서는 만들지 않았다. 설계는 [04-remote-gateway.md](../architecture/04-remote-gateway.md)에 있다.

## 참고
- ChatGPT Developer Mode MCP: https://designrevision.com/blog/add-mcp-server-to-chatgpt , https://www.speakeasy.com/docs/mcp/build/integrate/clients/using-chatgpt-developer-mode-with-gram
- Gemini CLI MCP 설정: https://www.tembo.io/blog/gemini-cli-mcp
- Codex MCP: https://developers.openai.com/codex/mcp
