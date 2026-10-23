"use strict";

/* ---------- 연결·도구 창: 커넥터 · MCP 서버 (이후 Phase의 탭도 여기에 더한다) ----------
   app.js의 h(), modal(), api(), toast(), renderMarkdown(), copyText()를 쓴다. */

const HUB = { tab: "connectors", modal: null, panel: null, tabs: null, open: new Set() };
const HUB_TABS = [];  // [{ id, label, render(panel) }] — 아래에서 차례로 더한다

const CONN_STATE = {
  connected: ["연결됨", "st-ok"],
  needs_auth: ["인증 필요", "st-warn"],
  error: ["연결 오류", "st-err"],
  disabled: ["비활성화", ""],
  insufficient_scope: ["사용 권한 부족", "st-warn"],
  unavailable: ["이 기기에서 사용 불가", ""],
};
const KIND_LABEL = { read: "읽기", edit: "이 기기 수정", write: "쓰기", send: "전송", destructive: "삭제", exec: "실행" };
const ALWAYS_ASK = new Set(["send", "destructive", "exec"]);

// replaceChildren은 null을 "null" 글자로 넣으므로 빈 항목을 빼고 채운다
function fill(node, ...children) {
  node.replaceChildren(...children.flat().filter((c) => c != null && c !== false));
  return node;
}

function showHub(tab) {
  if (tab) HUB.tab = tab;
  HUB.tabs = h("div", { class: "hub-tabs", role: "tablist" });
  HUB.panel = h("div", { class: "hub-panel" });
  HUB.modal = modal({
    title: "연결·도구",
    body: h("div", {}, HUB.tabs, HUB.panel),
    wide: true,
    buttons: [{ label: "닫기", class: "primary", value: null }],
    onClose: () => { HUB.modal = null; HUB.rendered = null; },
  });
  renderHub();
  return HUB.modal;
}

function renderHub() {
  if (!HUB.modal) return;
  if (!HUB_TABS.some((t) => t.id === HUB.tab)) HUB.tab = HUB_TABS[0].id;
  HUB.tabs.replaceChildren(...HUB_TABS.map((t) => h("button", {
    class: "hub-tab" + (t.id === HUB.tab ? " active" : ""), role: "tab", "aria-selected": String(t.id === HUB.tab),
    onclick: () => { HUB.tab = t.id; renderHub(); },
  }, t.label)));
  const tab = HUB_TABS.find((t) => t.id === HUB.tab);
  // 같은 탭을 다시 그릴 때는 새 내용이 올 때까지 이전 내용을 둔다(깜빡임·스크롤 위치 튐 방지)
  if (HUB.rendered !== tab.id) fill(HUB.panel, h("small", { class: "muted" }, "불러오는 중..."));
  HUB.rendered = tab.id;
  Promise.resolve(tab.render(HUB.panel)).catch((e) => {
    fill(HUB.panel, h("p", { class: "mcp-error" }, `불러오지 못했습니다: ${e.message || e}`));
  });
}

// 이 탭이 다시 그려질 때 펼쳐 둔 항목을 유지한다
function hubDetails(key, summary, ...children) {
  const d = h("details", { class: "hub-details", open: HUB.open.has(key) }, h("summary", {}, summary), ...children);
  d.addEventListener("toggle", () => (d.open ? HUB.open.add(key) : HUB.open.delete(key)));
  return d;
}

function checkbox(checked, onchange, title) {
  const box = h("input", { type: "checkbox", class: "inline-check", title });
  box.checked = !!checked;
  box.addEventListener("change", () => onchange(box.checked, box));
  return box;
}

async function hubCall(promise, okText) {
  const res = await promise;
  if (res && res.ok === false) {
    toast(res.error || "실패했습니다");
    return null;
  }
  if (okText) toast(okText);
  if (res && res.message) toast(res.message);
  return res;
}

function featureToggle(features, name, note) {
  const f = (features || {})[name];
  if (!f) return null;
  return h("label", { class: "feature-toggle" },
    checkbox(f.enabled, async (on) => {
      await hubCall(api().set_feature(name, on), on ? `${f.label}을(를) 켰습니다` : `${f.label}을(를) 껐습니다`);
      renderHub();
    }),
    h("span", {}, h("b", {}, f.label), note ? h("small", {}, note) : null));
}

/* ---------- 커넥터 탭 ---------- */

function stateBadge(c) {
  const [label, cls] = CONN_STATE[c.state] || [c.state, ""];
  return h("span", { class: "badge " + cls }, label);
}

function secretRow(c, f) {
  const input = h("input", { type: "password", autocomplete: "off",
    placeholder: f.has ? `저장됨 ${f.masked}` : (f.placeholder || "") });
  return h("div", { class: "field" }, h("label", {}, f.label),
    h("div", { class: "row" }, input,
      h("button", { class: "btn", onclick: async () => {
        if (!input.value.trim()) return toast("값을 입력하세요");
        if (await hubCall(api().set_connector_secret(c.id, f.name, input.value.trim()), "저장했습니다")) renderHub();
      } }, "저장")),
    f.help ? h("small", {}, f.help) : null);
}

function optionRow(c, f) {
  if (f.name === "readonly") {
    return h("label", { class: "feature-toggle" },
      checkbox(String(f.value) === "true", async (on) => {
        if (await hubCall(api().set_connector_option(c.id, "readonly", on ? "true" : ""),
          on ? "읽기 전용으로 바꿨습니다. 다시 로그인하면 읽기 권한만 요청합니다." : "쓰기 권한을 쓰려면 다시 로그인하세요.")) renderHub();
      }),
      h("span", {}, f.label));
  }
  const input = h("input", { type: "text", value: f.value || "", placeholder: f.placeholder || "" });
  return h("div", { class: "field" }, h("label", {}, f.label),
    h("div", { class: "row" }, input, h("button", { class: "btn", onclick: async () => {
      if (await hubCall(api().set_connector_option(c.id, f.name, input.value.trim()), "저장했습니다")) renderHub();
    } }, "저장")), f.help ? h("small", {}, f.help) : null);
}

function toolPolicyTable(c) {
  const rows = c.tools.map((t) => {
    const sel = h("select", { class: "policy-select", title: "이 도구의 승인 정책" },
      h("option", { value: "" }, "기본"),
      h("option", { value: "allow", disabled: ALWAYS_ASK.has(t.kind) }, "묻지 않고 허용"),
      h("option", { value: "ask" }, "항상 묻기"),
      h("option", { value: "deny" }, "차단(모델에게 숨김)"));
    sel.value = t.policy || "";
    sel.addEventListener("change", async () => {
      if (await hubCall(api().set_connector_policy(c.id, t.name, sel.value))) toast("정책을 바꿨습니다");
    });
    return h("tr", {}, h("td", { class: "mono" }, t.name),
      h("td", {}, h("span", { class: `badge kind-${t.kind}` }, KIND_LABEL[t.kind] || t.kind)), h("td", {}, sel));
  });
  return h("div", {},
    h("small", { class: "muted" }, "기본: 읽기는 묻지 않고, 쓰기는 '에이전트 권한' 설정을 따르며, 전송·삭제·실행은 설정과 관계없이 매번 묻습니다."),
    h("table", { class: "help-table policy-table" }, rows));
}

async function showConnectorLog(c, box) {
  const rows = await api().connector_log(c.id, 30);
  if (!rows.length) return fill(box, h("small", { class: "muted" }, "아직 호출 기록이 없습니다."));
  fill(box, h("table", { class: "help-table log-table" }, rows.map((r) => h("tr", {},
    h("td", {}, new Date(r.ts * 1000).toLocaleString()),
    h("td", { class: "mono" }, r.tool),
    h("td", {}, r.ok ? "성공" : (r.approval === "denied" ? "거부됨" : r.approval === "blocked" ? "차단됨" : "실패")),
    h("td", {}, `${r.ms}ms`),
    h("td", { class: "muted" }, r.error || "")))),
  h("small", { class: "muted" }, "기록에는 인자 요약만 남고(비밀·긴 내용·메일 주소는 가림) 결과 내용은 남지 않습니다. 30일 보관."));
}

function connectorCard(c, data) {
  const toggle = checkbox(c.enabled, async (on, box) => {
    box.disabled = true;
    const res = await hubCall(api().set_connector_enabled(c.id, on), on ? `${c.name}을(를) 켰습니다` : `${c.name}을(를) 껐습니다`);
    if (res) renderHub();
    else box.disabled = false;
  }, c.enabled ? "끄기" : "켜기");
  if (c.state === "unavailable") toggle.disabled = true;
  const actions = h("div", { class: "row wrap" });
  const oauthReady = c.auth === "oauth" || (c.device_flow && (data.oauth_clients[c.provider] || {}).client_id);
  if (oauthReady) {
    actions.append(h("button", { class: "btn", onclick: async () => {
      if (await hubCall(api().connector_login(c.id))) toast("브라우저에서 로그인을 마치세요");
    } }, c.has_oauth_token ? "다시 로그인" : (c.auth === "oauth" ? "로그인" : "OAuth로 로그인")));
  }
  actions.append(
    h("button", { class: "btn", onclick: async () => {
      toast("확인하는 중...");
      const res = await hubCall(api().connector_verify(c.id));
      if (res) {
        const v = res.verified || {};
        toast(v.state === "connected" ? `연결됨${v.account ? ": " + v.account : ""}` : (v.detail || "확인하지 못했습니다"));
        renderHub();
      }
    } }, "연결 확인"),
    h("button", { class: "btn danger", onclick: async () => {
      if (!confirm(`${c.name} 연결을 해제할까요? 이 기기에 저장된 인증 정보를 지웁니다.`)) return;
      if (await hubCall(api().connector_logout(c.id))) renderHub();
    } }, "연결 해제"));
  const logBox = h("div", {});
  const detail = c.detail && c.state !== "disabled" ? h("p", { class: c.state === "error" ? "mcp-error" : "" }, c.detail) : null;
  const missing = (c.missing_scopes || []).length
    ? h("p", { class: "mcp-error" }, "허용받지 못한 권한: " + c.missing_scopes.map((s) => s.split("/").pop()).join(", ")) : null;
  return h("div", { class: "conn-card" },
    h("div", { class: "skill-item" }, toggle,
      h("div", { class: "s-main" },
        h("b", {}, c.name), stateBadge(c), c.desktop_only ? h("span", { class: "badge" }, "데스크톱 전용") : null,
        c.account ? h("span", { class: "badge" }, c.account) : null,
        h("p", {}, c.description), detail, missing)),
    hubDetails(`conn:${c.id}`, "연결 설정 · 권한 · 기록",
      c.setup ? h("div", { class: "conn-setup" }, renderMarkdown(c.setup)) : null,
      ...c.secrets.map((f) => secretRow(c, f)),
      c.device_flow ? oauthClientRow("github", data, "GitHub OAuth App의 Client ID (선택, Device Flow 사용 설정 필요)", false) : null,
      ...c.options.map((f) => optionRow(c, f)),
      c.scopes.length ? h("div", { class: "field" }, h("label", {}, c.auth === "oauth" ? "요청하는 권한(scope)" : "토큰에 필요한 권한"),
        h("ul", { class: "scope-list" }, c.scopes.map((s) => h("li", { class: "mono" }, s)))) : null,
      actions,
      h("div", { class: "field" }, h("label", {}, `도구 ${c.tools.length}개와 승인 정책`), toolPolicyTable(c)),
      h("div", { class: "field" }, h("label", {}, "최근 호출 기록"),
        h("button", { class: "btn", onclick: () => showConnectorLog(c, logBox) }, "불러오기"), logBox)));
}

function oauthClientRow(provider, data, label, withSecret = true) {
  const client = data.oauth_clients[provider] || {};
  const id = h("input", { type: "text", value: client.client_id || "", placeholder: "클라이언트 ID", autocomplete: "off" });
  const secret = withSecret ? h("input", { type: "password", autocomplete: "off",
    placeholder: client.has_secret ? "저장됨 — 바꾸려면 새로 입력" : "클라이언트 보안 비밀번호" }) : null;
  return h("div", { class: "field" }, h("label", {}, label),
    h("div", { class: "row wrap" }, id, secret,
      h("button", { class: "btn", onclick: async () => {
        if (await hubCall(api().set_oauth_client(provider, id.value.trim(), secret ? secret.value.trim() : null), "저장했습니다")) renderHub();
      } }, "저장"),
      client.client_id ? h("button", { class: "btn danger", onclick: async () => {
        if (await hubCall(api().set_oauth_client(provider, "", null, true), "지웠습니다")) renderHub();
      } }, "지우기") : null));
}

async function renderConnectors(panel) {
  const data = await api().get_connectors();
  const groups = {};
  for (const c of data.connectors) (groups[c.group] = groups[c.group] || []).push(c);
  const backend = data.secret_backend.startsWith("os:") ? "OS 보안 저장소(Windows 자격 증명 관리자·macOS 키체인)"
    : data.android ? "앱 전용 저장소(안드로이드 샌드박스)" : "앱 전용 파일(secrets.json, 이 사용자만 읽기 가능)";
  fill(panel, 
    h("p", { class: "hub-intro" }, "외부 서비스를 연결하면 에이전트 모드에서 그 서비스의 도구를 씁니다. 커넥터는 기본으로 꺼져 있고, ",
      "켠 커넥터의 도구만 모델에게 보입니다. 쓰기는 승인을 받고, 메일 전송·리뷰 제출 같은 작업은 매번 묻습니다."),
    featureToggle(data.features, "connectors", "끄면 모든 커넥터를 한 번에 멈춥니다(설정은 남습니다)."),
    h("small", { class: "muted block" }, `인증 정보 저장 위치: ${backend}. 토큰은 설정 파일·동기화·로그에 들어가지 않습니다.`),
    ...Object.entries(groups).map(([group, items]) => h("section", { class: "hub-group" },
      h("h3", {}, group),
      group === "Google Workspace" ? hubDetails("google-client", "Google OAuth 클라이언트 (처음 한 번)",
        h("div", { class: "conn-setup" }, renderMarkdown(items[0].setup)),
        oauthClientRow("google", data, "데스크톱 앱 OAuth 클라이언트")) : null,
      ...items.map((c) => connectorCard(c, data)))));
}

/* ---------- MCP 서버 탭 (1.9의 MCP 창) ---------- */

async function renderMcpPanel(panel, st) {
  st = st || await api().get_mcp();
  const STATE = { connected: "연결됨", error: "연결 실패", idle: "대기" };
  const list = h("div", {});
  for (const sv of st.servers) {
    const toggle = checkbox(sv.enabled, async (on) => renderMcpPanel(panel, await api().set_mcp_enabled(sv.name, on)),
      sv.enabled ? "끄기" : "켜기");
    if (sv.connector) toggle.disabled = true;  // 커넥터 서버는 커넥터 탭에서 켜고 끈다
    const detail = sv.state === "connected" ? "도구: " + sv.tools.join(", ")
      : sv.error ? sv.error : (sv.command || sv.description);
    const strict = !sv.builtin ? h("label", { class: "inline-label" },
      checkbox(sv.policy === "ask_all", async (on) => renderMcpPanel(panel, await api().set_server_policy(sv.name, on ? "ask_all" : ""))),
      "읽기 도구도 항상 묻기") : null;
    list.append(h("div", { class: "skill-item" }, toggle,
      h("div", { class: "s-main" },
        h("b", {}, sv.name),
        h("span", { class: "badge" }, sv.connector ? "커넥터" : sv.builtin ? "내장" : sv.preset ? "추천" : "외부"),
        sv.enabled ? h("span", { class: "badge mcp-" + sv.state }, STATE[sv.state] || sv.state) : null,
        h("p", {}, sv.description || ""),
        detail && detail !== sv.description ? h("p", { class: sv.error ? "mcp-error" : "" }, detail) : null,
        strict)));
  }
  fill(panel, 
    h("p", { class: "hub-intro" },
      "MCP 서버는 에이전트가 쓸 수 있는 도구를 더해 줍니다. 내장 서버로 Word·PowerPoint·Excel 문서를 만들고 고치고, ",
      "논문을 찾아 읽고(paper), Notion 페이지를 다루고(notion, 설정에 토큰 필요), ",
      "웹페이지를 읽고 검색할 수 있습니다(firecrawl, 설정에 키 필요). 파일은 작업 폴더 안의 것만 다룹니다. ",
      "추천 서버(playwright: 브라우저 자동화)는 PC에 Node.js가 있으면 켜서 씁니다. ",
      "다른 MCP 서버는 설정 파일(mcp.json)에 Claude Desktop과 같은 형식으로 추가합니다. 커넥터의 서버는 커넥터 탭에서 켭니다."),
    list,
    st.config_error ? h("p", { class: "mcp-error" }, st.config_error) : null,
    h("div", { class: "row wrap", style: "margin-top:10px" },
      h("button", { class: "btn", onclick: () => api().open_mcp_config() }, "설정 파일 열기"),
      h("button", { class: "btn", onclick: async () => {
        if (!S.workspace.path) return toast("먼저 작업 폴더를 선택하세요");
        toast("MCP 서버에 연결하는 중...");
        renderMcpPanel(panel, await api().connect_mcp());
      } }, "지금 연결")),
    h("small", { class: "muted block" },
      "서버는 에이전트 모드에서 처음 필요할 때 연결됩니다. 작업 폴더의 파일을 고치는 도구는 파일 수정처럼, ",
      "외부 서버의 도구와 Notion에 쓰기·브라우저 조작처럼 바깥에 영향을 주는 도구는 명령 실행처럼 승인을 받습니다. ",
      "외부 서버의 도구 결과는 '외부 데이터'로 표시되어 모델이 그 안의 지시를 따르지 않도록 합니다."));
}

HUB_TABS.push({ id: "connectors", label: "커넥터", render: renderConnectors },
  { id: "mcp", label: "MCP 서버", render: (panel) => renderMcpPanel(panel) });

/* ---------- 연구 라이브러리 탭 (Phase 2) ---------- */

const RESEARCH = { query: "", tag: "", progress: null };

function paperItem(p) {
  const authors = (p.authors || []).slice(0, 4).join(", ") + ((p.authors || []).length > 4 ? ` 외 ${p.authors.length - 4}명` : "");
  const ids = [p.doi ? `DOI ${p.doi}` : "", p.arxiv ? `arXiv ${p.arxiv}` : "", p.pdf ? `PDF ${p.pdf}` : ""].filter(Boolean).join(" · ");
  const edit = (field, label, join) => async () => {
    const current = Array.isArray(p[field]) ? p[field].join(", ") : (p[field] || "");
    const value = prompt(label, current);
    if (value == null) return;
    const res = await hubCall(api().research_update(p.id, { [field]: join ? value.split(",").map((t) => t.trim()).filter(Boolean) : value }));
    if (res) renderHub();
  };
  return h("div", { class: "skill-item paper-item" },
    h("div", { class: "s-main" },
      h("b", { class: "paper-title" }, p.title || "(제목 없음)"), h("span", { class: "badge" }, p.year || "연도 미상"),
      p.citations != null ? h("span", { class: "badge" }, `인용 ${p.citations}`) : null,
      h("p", {}, [authors, p.venue].filter(Boolean).join(" · ")),
      ids ? h("p", { class: "mono small" }, ids) : null,
      (p.tags || []).length ? h("p", {}, (p.tags || []).map((t) => h("span", { class: "badge tag", onclick: () => { RESEARCH.tag = t; renderHub(); } }, `#${t}`))) : null,
      p.notes ? h("p", { class: "muted" }, `메모: ${p.notes}`) : null,
      h("div", { class: "row wrap paper-actions" },
        h("button", { class: "link-btn", onclick: edit("tags", "태그(쉼표로 구분)", true) }, "태그"),
        h("button", { class: "link-btn", onclick: edit("notes", "메모") }, "메모"),
        h("button", { class: "link-btn", onclick: async () => {
          const res = await hubCall(api().research_bibtex([p.id]));
          if (res) showBibtex(res);
        } }, "BibTeX"),
        h("button", { class: "link-btn danger", onclick: async () => {
          if (!confirm(`'${p.title}'을(를) 라이브러리에서 지울까요?`)) return;
          if (await hubCall(api().research_remove(p.id), "지웠습니다")) renderHub();
        } }, "지우기"))));
}

function showBibtex(res) {
  const pre = h("pre", { class: "diff bib" }, h("div", {}, res.bibtex));
  modal({
    title: `BibTeX (${res.count}편)`, body: pre, wide: true,
    buttons: [{ label: "복사", action: () => copyText(res.bibtex) },
      { label: "파일로 저장", action: async () => { const r = await hubCall(api().research_bibtex(null, RESEARCH.tag || null, true)); if (r) toast(`저장했습니다: ${r.path}`); } },
      { label: "닫기", class: "primary" }],
  });
}

async function renderResearch(panel) {
  const st = await api().research_state(RESEARCH.query, RESEARCH.tag);
  const add = h("input", { type: "text", placeholder: "arXiv 번호(1706.03762)·DOI·논문 주소" });
  const addTags = h("input", { type: "text", placeholder: "태그(선택, 쉼표로 구분)" });
  const addBtn = h("button", { class: "btn", onclick: async () => {
    addBtn.disabled = true;
    try {
      const tags = addTags.value.split(",").map((t) => t.trim()).filter(Boolean);
      if (await hubCall(api().research_add(add.value.trim(), tags), "라이브러리에 더했습니다")) renderHub();
    } finally { addBtn.disabled = false; }
  } }, "더하기");
  const search = h("input", { type: "search", placeholder: "제목·저자·초록·메모 검색", value: RESEARCH.query });
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") { RESEARCH.query = search.value.trim(); renderHub(); } });
  const tags = Object.entries(st.tags || {});
  const docs = st.index.documents || [];
  const progress = h("small", { class: "muted block" }, RESEARCH.progress || (st.indexing ? "인덱싱 중..." : ""));
  RESEARCH.progressNode = progress;
  const ragQuery = h("input", { type: "search", placeholder: "인덱스에서 찾기(출처가 붙은 원문 조각)" });
  const ragOut = h("div", {});
  ragQuery.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || !ragQuery.value.trim()) return;
    const res = await hubCall(api().research_search(ragQuery.value.trim()));
    if (!res) return;
    fill(ragOut, res.results.length ? res.results.map((r) => h("div", { class: "rag-hit" },
      h("small", { class: "mono" }, r.cite), h("p", {}, r.text.length > 400 ? r.text.slice(0, 400) + "…" : r.text)))
      : [h("small", { class: "muted" }, "맞는 내용이 없습니다.")]);
  });
  const v = st.vector || {};
  const vEnabled = checkbox(v.enabled, () => {});
  const vUrl = h("input", { type: "url", value: v.qdrant_url || "", placeholder: "http://127.0.0.1:6333" });
  const vColl = h("input", { type: "text", value: v.collection || "poschat" });
  const vEmbUrl = h("input", { type: "url", value: v.embedding_url || "", placeholder: "https://.../v1/embeddings" });
  const vModel = h("input", { type: "text", value: v.embedding_model || "", placeholder: "임베딩 모델 ID" });
  const vQKey = h("input", { type: "password", placeholder: v.has_qdrant_key ? "저장됨" : "Qdrant API 키(선택)" });
  const vEKey = h("input", { type: "password", placeholder: v.has_embedding_key ? "저장됨" : "임베딩 API 키" });
  fill(panel,
    h("p", { class: "hub-intro" }, "논문을 모아 태그로 분류하고 BibTeX으로 내보내며, 작업 폴더의 PDF·문서를 인덱싱해 쪽·섹션이 붙은 원문으로 찾습니다. ",
      "에이전트는 커넥터 '연구 라이브러리'를 켜면 research 도구(더하기·추천·인용 관계·문서 검색)를 씁니다. 모든 데이터는 이 기기에만 저장됩니다."),
    featureToggle({ research: { label: "연구 워크스페이스", enabled: st.feature } }, "research"),
    st.feature && !st.enabled ? h("div", { class: "row wrap" }, h("small", { class: "muted" }, "에이전트 도구(research 서버)가 꺼져 있습니다."),
      h("button", { class: "btn", onclick: async () => { if (await hubCall(api().set_connector_enabled("research", true), "켰습니다")) renderHub(); } }, "에이전트 도구 켜기")) : null,
    h("section", { class: "hub-group" }, h("h3", {}, `논문 라이브러리 (${st.total}편)`),
      h("div", { class: "row wrap" }, add, addTags, addBtn),
      h("div", { class: "row wrap", style: "margin-top:8px" }, search,
        h("button", { class: "btn", onclick: async () => { const r = await hubCall(api().research_bibtex(null, RESEARCH.tag || null)); if (r) showBibtex(r); } },
          RESEARCH.tag ? `#${RESEARCH.tag} BibTeX` : "전체 BibTeX"),
        st.zotero !== "disabled" ? h("button", { class: "btn", onclick: async () => {
          toast("Zotero에서 가져오는 중...");
          const r = await hubCall(api().zotero_import_now(false));
          if (r) { toast(r.result); renderHub(); }
        } }, "Zotero에서 가져오기") : null),
      tags.length ? h("p", { class: "tag-row" }, h("span", { class: "badge tag" + (RESEARCH.tag ? "" : " active"), onclick: () => { RESEARCH.tag = ""; renderHub(); } }, "전체"),
        tags.map(([t, n]) => h("span", { class: "badge tag" + (RESEARCH.tag === t ? " active" : ""), onclick: () => { RESEARCH.tag = t; renderHub(); } }, `#${t} ${n}`))) : null,
      st.papers.length ? st.papers.map(paperItem) : h("small", { class: "muted block" }, st.total ? "맞는 논문이 없습니다." : "아직 논문이 없습니다. 위에서 arXiv 번호나 DOI로 더해 보세요.")),
    h("section", { class: "hub-group" }, h("h3", {}, `문서 인덱스 (문서 ${docs.length}개, 청크 ${st.index.chunks}개, 검색 방식 ${st.index.fts}${v.enabled ? " + 벡터" : ""})`),
      h("div", { class: "row wrap" },
        h("small", { class: "muted", style: "flex:1" }, st.workspace ? `작업 폴더: ${st.workspace}` : "작업 폴더를 고르면 그 폴더의 문서를 인덱싱합니다."),
        h("button", { class: "btn", disabled: !st.workspace || st.indexing, onclick: async () => {
          RESEARCH.progress = "인덱싱을 시작합니다...";
          if (await hubCall(api().research_index())) renderHub();
        } }, "작업 폴더 인덱싱")),
      progress,
      st.index.error ? h("p", { class: "mcp-error" }, st.index.error) : null,
      docs.length ? hubDetails("rag-docs", `인덱싱한 문서 ${docs.length}개`, h("table", { class: "help-table log-table" }, docs.map((d) => h("tr", {},
        h("td", { class: "mono" }, d.path.split(/[\\/]/).pop()), h("td", {}, d.collection === "library" ? "라이브러리" : "작업 폴더"),
        h("td", {}, `${d.pages || "-"}쪽 · 청크 ${d.chunks}`),
        h("td", {}, h("button", { class: "link-btn danger", onclick: async () => { if (await hubCall(api().research_remove_document(d.doc_id))) renderHub(); } }, "빼기")))))) : null,
      h("div", { class: "row" }, ragQuery), ragOut,
      hubDetails("vector", "벡터 검색(선택: Qdrant + 임베딩 API)",
        h("small", { class: "muted block" }, "켜면 인덱싱할 때 문서 조각을 임베딩 API로 보내 벡터를 만들고 Qdrant에 저장해, 키워드 검색과 섞어(RRF) 찾습니다. ",
          "문서 내용이 그 서버로 전송되므로 직접 운영하거나 신뢰하는 서버만 쓰세요. 끄면 키워드 검색만 씁니다."),
        h("label", { class: "feature-toggle" }, vEnabled, h("span", {}, "벡터 검색 켜기")),
        h("div", { class: "field" }, h("label", {}, "Qdrant 주소 · 컬렉션"), h("div", { class: "row wrap" }, vUrl, vColl)),
        h("div", { class: "field" }, h("label", {}, "임베딩 API(OpenAI 호환 /embeddings) 주소 · 모델"), h("div", { class: "row wrap" }, vEmbUrl, vModel)),
        h("div", { class: "field" }, h("label", {}, "키"), h("div", { class: "row wrap" }, vQKey, vEKey)),
        h("button", { class: "btn", onclick: async () => {
          const r = await hubCall(api().set_vector_config({ enabled: vEnabled.checked, qdrant_url: vUrl.value.trim(), collection: vColl.value.trim(),
            embedding_url: vEmbUrl.value.trim(), embedding_model: vModel.value.trim(), qdrant_key: vQKey.value.trim(), embedding_key: vEKey.value.trim() }), "저장했습니다");
          if (r) renderHub();
        } }, "저장"))));
}

HUB_TABS.push({ id: "research", label: "연구 라이브러리", render: renderResearch });

/* ---------- 백엔드 이벤트 ---------- */

function hubEvent(ev) {
  if (ev.type === "hub") return hubPanelEvent(ev);
  if (ev.type !== "connector") return;
  if (ev.kind === "device_code") {
    modal({
      title: "GitHub 로그인",
      body: h("div", {},
        h("p", {}, "브라우저에서 열린 GitHub 페이지에 아래 코드를 입력하세요."),
        h("div", { class: "device-code" }, ev.user_code),
        h("p", {}, h("a", { href: ev.url, target: "_blank" }, ev.url))),
      buttons: [{ label: "코드 복사", action: () => copyText(ev.user_code) },
        { label: "취소", action: (close) => { api().connector_cancel_login(ev.id); close(); } },
        { label: "닫기", class: "primary" }],
    });
  } else if (ev.kind === "login_url") {
    toast("브라우저에서 로그인을 마치세요. 창이 열리지 않으면 연결 설정에서 다시 시도하세요.");
  } else if (ev.kind === "login_done") {
    toast(ev.status && ev.status.state === "connected" ? "연결했습니다" : (ev.status.detail || "로그인했습니다"));
    renderHub();
  } else if (ev.kind === "login_error") {
    toast(ev.error);
    renderHub();
  }
}

function hubPanelEvent(ev) {
  if (ev.kind === "index_progress") {
    RESEARCH.progress = `인덱싱 중... ${ev.done}/${ev.total} ${ev.name}`;
    if (RESEARCH.progressNode) RESEARCH.progressNode.textContent = RESEARCH.progress;
  } else if (ev.kind === "index_done") {
    const s = ev.summary;
    RESEARCH.progress = `인덱싱 완료: 새로 ${s.indexed}개, 그대로 ${s.unchanged}개, 지움 ${s.removed}개, 청크 ${s.chunks}개` +
      (s.failed.length ? ` · 실패 ${s.failed.length}개 (${s.failed.slice(0, 3).join("; ")})` : "");
    if (HUB.tab === "research") renderHub();
  } else if (ev.kind === "index_error") {
    RESEARCH.progress = `인덱싱 실패: ${ev.error}`;
    if (HUB.tab === "research") renderHub();
  } else if (window.hubExtraEvent) {
    hubExtraEvent(ev);
  }
}
