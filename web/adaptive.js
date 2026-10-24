// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
/* Adaptive AI 화면(1.17): 'AI 실행 정책' 창, 로컬 AI(Ollama) 관리, 대화 모델 목록의 '자동'·'로컬' 선택지,
   답변 아래 라우팅 표시(Local · 요약 / Cloud · 연구 추론 / Local → Cloud · 근거 검증 실패), 승격할 때 임시 답 표시.
   로컬 모델이 보낸 글·모델 이름·라이선스는 모두 글자(text)로만 넣는다(HTML로 해석하지 않는다). */

const ADAPT = { state: null, localModels: [], live: null, pull: null, modalBody: null };
const POLICY_INFO = {
  economy: ["Economy (절약)", "가벼운 일(요약·번역·분류·추출·일상 대화)은 로컬을 먼저 씁니다. 검증에 실패하면 허용한 범위에서 Cloud로 다시 합니다."],
  balanced: ["Balanced (균형, 권장)", "요청 종류와 난이도에 따라 고릅니다. 연구 추론·코드 수정·에이전트 작업은 Cloud를 먼저 씁니다."],
  quality: ["Quality (품질)", "Cloud를 먼저 씁니다. 로컬은 측정해서 품질이 확인된 가벼운 일에만 씁니다."],
  local_only: ["Local Only (로컬 전용)", "Cloud 모델을 전혀 부르지 않습니다(라우팅·검증·요약도 로컬). 로컬 모델이 없거나 못 하는 일이면 오류로 알립니다."],
};
const ROUTE_STATUS = {
  verified: "검증 통과", unchecked: "검증할 항목 없음", unverified: "검증 실패(그대로 표시)", escalated: "Cloud로 다시 답함",
  cloud: "Cloud", provisional: "검증 전", cancelled: "멈춤", blocked: "보낼 곳 없음", failed: "실패", manual: "직접 고른 모델",
};

function adaptiveOn() {
  return !!(S.config && S.config.adaptive && S.config.adaptive.enabled);
}

/* 대화 모델 목록(app.js modeModels)에 '자동'과 로컬 모델을 더한다 */
function adaptiveModelOptions(base) {
  if (!adaptiveOn()) return base;
  const local = ADAPT.localModels.map((m) => ({ id: "local:" + m.id, label: `로컬 · ${m.id}` }));
  const cloud = S.config.adaptive.policy === "local_only" ? [] : base;
  return [{ id: "auto", label: "자동 (AI 실행 정책)" }, ...local, ...cloud];
}

async function adaptiveRefreshModels() {
  if (!adaptiveOn()) { ADAPT.localModels = []; return; }
  try {
    const st = await api().adaptive_state(false);
    ADAPT.state = st;
    ADAPT.localModels = st.models || [];
  } catch { ADAPT.localModels = []; }
  if (typeof renderThreadModel === "function") renderThreadModel();
}

/* ---------- 라우팅 표시 ---------- */

function routeBadge(route) {
  if (!route) return null;
  const local = route.provider === "local";
  const cls = "route-badge " + (route.escalated ? "esc" : local ? "local" : "cloud") + (route.status === "unverified" ? " warn" : "");
  const details = h("div", { class: "route-detail", hidden: true });
  const fmtMs = (x) => (x == null ? "-" : x >= 1000 ? `${(x / 1000).toFixed(1)}초` : `${x}ms`);
  const rows = [
    ["실행", route.escalated ? "로컬 → Cloud" : local ? "로컬(이 PC)" : "Cloud"],
    ["모델", route.model || "-"],
    ["이유", route.reason || "-"],
    ["작업·난이도", `${route.task_label || route.task || "-"} · ${route.difficulty_label || route.difficulty || "-"}`],
    ["정책", (POLICY_INFO[route.policy] || [route.policy || "-"])[0]],
    ["상태", ROUTE_STATUS[route.status] || route.status || "-"],
    ["응답 시간", fmtMs(route.ms)],
    ["Cloud API 호출", route.api_call ? "있음" : "없음"],
    ["비용 추정", route.est_cost == null ? (route.api_call ? "추정 불가(근거 있는 모델만 추정)" : "Cloud API 비용 없음") : `약 ${route.est_cost} 크레딧`],
  ];
  if (route.gate && route.gate.checks) {
    rows.push(["검증", route.gate.ok ? `통과 (${route.gate.checks.length}개 항목)` : `실패: ${route.gate.detail || ""}`]);
  }
  if (route.escalated) rows.push(["승격 이유", route.escalation_reason || "-"]);
  if (route.escalation_error) rows.push(["승격 실패", route.escalation_error]);
  if (route.calls > 1 && route.counts) rows.push(["이번 실행의 모델 호출", `${route.calls}번 (로컬 ${route.counts.local}, Cloud ${route.counts.cloud}, 승격 ${route.counts.escalated})`]);
  details.append(h("table", { class: "route-table" }, rows.map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, String(v))))));
  if (route.provisional) {
    details.append(h("details", { class: "route-provisional" }, h("summary", {}, "검증에 실패한 로컬 임시 답 보기"),
      h("pre", {}, route.provisional)));
  }
  const btn = h("button", { class: cls, type: "button", title: "모델 선택 이유 보기", "aria-expanded": "false" }, route.label || (local ? "Local" : "Cloud"));
  btn.addEventListener("click", () => {
    details.hidden = !details.hidden;
    btn.setAttribute("aria-expanded", String(!details.hidden));
  });
  return h("div", { class: "route-wrap" }, btn, details);
}

/* 받는 중인 답 위에 붙는 표시: 로컬은 '검증 전', 승격 중이면 접어 둔 임시 답 */
function streamingRouteNode() {
  const live = ADAPT.live;
  if (!live || live.thread_id !== S.currentId) return null;
  if (live.kind === "escalating") {
    return h("div", { class: "route-live esc" }, h("span", {}, `로컬 답이 검증을 통과하지 못해(${live.reason || "검증 실패"}) Cloud로 다시 답하는 중`),
      live.provisional ? h("details", { class: "route-provisional" }, h("summary", {}, "로컬 임시 답(검증 실패)"), h("pre", {}, live.provisional)) : null);
  }
  if (live.kind === "provisional" || live.kind === "retry") {
    return h("div", { class: "route-live local" }, live.kind === "retry" ? "로컬 답 형식이 맞지 않아 다시 받는 중" : "로컬 답 · 검증 전");
  }
  return null;
}

function routeEvent(ev) {
  if (ev.kind === "provisional" || ev.kind === "retry") {
    ADAPT.live = { thread_id: ev.thread_id, kind: ev.kind };
  } else if (ev.kind === "escalating") {
    ADAPT.live = { thread_id: ev.thread_id, kind: "escalating", reason: ev.reason,
      provisional: (typeof streaming !== "undefined" && streaming.text) || (ev.route && ev.route.provisional) || "" };
    if (ev.thread_id === S.currentId && typeof showStreaming === "function") showStreaming("");
  } else if (ev.kind === "verified" || ev.kind === "final" || ev.kind === "unverified") {
    if (ADAPT.live && ADAPT.live.kind !== "escalating") ADAPT.live = null;
  }
}

function adaptiveDone() {
  ADAPT.live = null;
}

/* ---------- AI 실행 정책 창 ---------- */

function adaptiveStatusText() {
  const a = S.config.adaptive || {};
  if (!a.enabled) return "꺼짐 — 대화마다 고른 모델을 그대로 씁니다(예전과 같음).";
  return `켜짐 · ${(POLICY_INFO[a.policy] || [a.policy])[0]}` + (a.default_model ? ` · 기본 로컬 모델 ${a.default_model}` : " · 로컬 모델 없음");
}

function fmtBytes(n) {
  if (!n) return "-";
  const gb = n / 2 ** 30;
  return gb >= 1 ? `${gb.toFixed(1)}GB` : `${Math.round(n / 2 ** 20)}MB`;
}

async function showAdaptive() {
  let st;
  try {
    st = await api().adaptive_state(true);
  } catch (e) {
    return toast(`AI 실행 정책을 불러오지 못했습니다: ${e.message || e}`);
  }
  ADAPT.state = st;
  ADAPT.localModels = st.models || [];
  const s = st.settings;
  const enabled = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  enabled.checked = !!s.enabled;
  const policyName = `adaptive-policy-${Date.now()}`;
  const policyBoxes = Object.entries(POLICY_INFO).map(([id, [label, desc]]) => {
    const radio = h("input", { type: "radio", name: policyName, value: id, style: "width:auto;margin:3px 8px 0 0" });
    radio.checked = s.policy === id;
    return h("label", { class: "adaptive-policy" }, radio, h("span", {}, h("b", {}, label), h("small", {}, desc)));
  });
  const policyValue = () => (policyBoxes.map((l) => l.querySelector("input")).find((r) => r.checked) || {}).value || "balanced";

  // 로컬 AI
  const health = st.health || {};
  const statusLine = h("div", { class: "adaptive-health " + (health.ok ? "ok" : "bad") },
    !st.supported ? "이 기기(안드로이드)에서는 로컬 AI를 쓸 수 없습니다. 자동 선택을 켜도 Cloud 모델만 고릅니다."
      : health.ok ? `연결됨 · Ollama ${health.version || ""} · ${health.endpoint}${health.loopback ? " (이 PC)" : " (원격)"}`
      : `연결 안 됨 — ${health.error || "Ollama가 실행 중이 아닙니다."}`);
  const endpoint = h("input", { type: "url", value: s.local.endpoint || "http://127.0.0.1:11434", placeholder: "http://127.0.0.1:11434" });
  const remote = h("input", { type: "checkbox", style: "width:auto;margin:0 6px 0 0" });
  remote.checked = !!s.local.allow_remote;
  const testBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    testBtn.disabled = true;
    try {
      const r = await api().adaptive_test_connection(endpoint.value.trim(), remote.checked);
      statusLine.className = "adaptive-health " + (r.ok ? "ok" : "bad");
      statusLine.textContent = r.ok ? `연결됨 · Ollama ${r.health.version} · 모델 ${r.models.length}개 (저장하면 이 주소를 씁니다)` : `연결 안 됨 — ${r.error}`;
    } finally { testBtn.disabled = false; }
  } }, "연결 시험");

  const defaultModel = h("select", {}, h("option", { value: "" }, "(고르지 않음 — 로컬을 쓰지 않음)"),
    (st.models || []).map((m) => h("option", { value: m.id }, `${m.id} (${m.size_label || fmtBytes(m.size)})`)));
  defaultModel.value = s.local.default_model || "";
  const numCtx = h("input", { type: "number", min: 2048, max: 262144, step: 1024, value: s.local.num_ctx || 8192 });
  const modelTable = h("div", { class: "table-scroll" });
  const fillModels = (models) => {
    if (!models.length) {
      modelTable.replaceChildren(h("small", { class: "muted block" }, st.supported && health.ok
        ? "설치된 모델이 없습니다. 아래 '모델 받기'에서 받거나 터미널에서 ollama pull로 받으세요."
        : "Ollama를 설치하고 실행하면 여기에 모델이 보입니다(ollama.com/download)."));
      return;
    }
    modelTable.replaceChildren(h("table", { class: "help-table adaptive-models" },
      h("tr", {}, ["모델", "크기", "양자화", "메모리(추정)", "속도", ""].map((c) => h("th", {}, c))),
      models.map((m) => {
        const info = h("td", { class: "adaptive-actions" });
        const row = h("tr", {}, h("td", {}, m.id, h("small", { class: "muted block" }, [m.family, m.parameter_size].filter(Boolean).join(" · "))),
          h("td", {}, m.size_label || fmtBytes(m.size)), h("td", {}, m.quantization || "-"),
          h("td", { class: m.memory_ok ? "" : "warn" }, `${fmtBytes(m.memory_est)}${m.memory_ok ? "" : " · 부족할 수 있음"}`),
          h("td", {}, m.speed && m.speed.tokens_per_s ? `${m.speed.tokens_per_s} 토큰/초` : "-"), info);
        const out = h("div", { class: "adaptive-out", hidden: true });
        info.append(
          h("button", { class: "btn small", type: "button", onclick: async () => {
            const r = await api().adaptive_model_info(m.id);
            out.hidden = false;
            if (r.ok === false) return out.replaceChildren(r.error);
            const c = r.capabilities;
            out.replaceChildren(h("div", {}, `기능: ${["글", c.vision && "이미지", c.tools && "도구 호출", c.json && "구조화 출력(JSON)", c.thinking && "추론"].filter(Boolean).join(", ")}`
              + ` · 문맥 ${c.context_length ? c.context_length.toLocaleString() + " 토큰" : "알 수 없음"}` + (c.known ? "" : " (Ollama가 기능 목록을 주지 않아 글만 씁니다)")),
            h("details", {}, h("summary", {}, "라이선스"), h("pre", { class: "adaptive-license" }, c.license || "(모델에 라이선스 정보가 없습니다)")));
          } }, "기능·라이선스"),
          h("button", { class: "btn small", type: "button", onclick: async (e) => {
            e.target.disabled = true;
            out.hidden = false;
            out.textContent = "속도를 재는 중… (이 PC에서만 돕니다)";
            const r = await api().adaptive_measure(m.id);
            e.target.disabled = false;
            out.textContent = r.ok === false ? r.error : `${r.speed.tokens_per_s} 토큰/초 · 첫 글자까지 ${r.speed.first_ms}ms · 불러오기 ${r.speed.load_ms}ms`;
          } }, "속도 측정"),
          h("button", { class: "btn small", type: "button", onclick: () => adaptiveTestChat(m.id) }, "시험 대화"),
          h("button", { class: "btn small danger", type: "button", onclick: async () => {
            if (!confirm(`${m.id} 모델을 이 PC에서 지울까요? (다시 쓰려면 받아야 합니다)`)) return;
            const r = await api().adaptive_delete_model(m.id);
            if (r.ok === false) return toast(r.error);
            toast("지웠습니다");
            row.remove();
          } }, "지우기"));
        return [row, h("tr", {}, h("td", { colspan: 6 }, out))];
      }).flat()));
  };
  fillModels(st.models || []);

  // 모델 받기
  const pullName = h("input", { type: "text", placeholder: "예: qwen2.5:7b, gemma3:4b, llama3.2:3b" });
  const pullBox = h("div", { class: "adaptive-pull" });
  const previewBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    const name = pullName.value.trim();
    if (!name) return toast("받을 모델 이름을 쓰세요");
    previewBtn.disabled = true;
    pullBox.textContent = "Ollama 공개 저장소에서 크기와 라이선스를 확인하는 중…";
    try {
      const p = await api().adaptive_pull_preview(name);
      if (p.ok === false) { pullBox.textContent = p.error; return; }
      const go = h("button", { class: "btn primary", type: "button", disabled: !p.disk_ok, onclick: async () => {
        const r = await api().adaptive_pull(name);
        if (r.ok === false) return toast(r.error);
        ADAPT.pull = { model: name, done: 0, total: p.size, status: "시작" };
        renderPull();
      } }, "받기");
      pullBox.replaceChildren(
        h("div", {}, `크기 약 ${p.size_label} · 출처 ${p.source}`),
        h("div", {}, `라이선스: ${p.license_name}`, " · ", h("a", { href: p.page, target: "_blank" }, "모델 페이지")),
        p.license ? h("details", {}, h("summary", {}, "라이선스 전문(앞부분)"), h("pre", { class: "adaptive-license" }, p.license)) : null,
        h("small", { class: p.disk_ok ? "muted block" : "warn block" }, p.disk_free == null ? "남은 디스크 공간을 알 수 없습니다."
          : `남은 디스크 ${fmtBytes(p.disk_free)}` + (p.disk_ok ? "" : " — 공간이 모자랍니다. 정리한 뒤 다시 시도하세요.")),
        h("small", { class: "muted block" }, "모델마다 라이선스가 다릅니다(상업적 이용·재배포 제한이 있을 수 있음). 위 내용을 읽고 받으세요. POSCHAT은 모델을 함께 배포하지 않습니다."),
        go);
    } finally { previewBtn.disabled = false; }
  } }, "크기·라이선스 확인");
  const renderPull = () => {
    const p = ADAPT.pull;
    if (!p) return;
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    pullBox.replaceChildren(h("div", {}, `${p.model} 받는 중 · ${p.status} · ${pct}%`),
      h("progress", { max: 100, value: pct, style: "width:100%" }),
      h("button", { class: "btn", type: "button", onclick: () => api().adaptive_pull_cancel() }, "멈춤"));
  };
  ADAPT.renderPull = renderPull;
  ADAPT.afterPull = async (ok, text) => {
    ADAPT.pull = null;
    pullBox.textContent = text;
    if (ok) {
      const fresh = await api().adaptive_state(true);
      ADAPT.state = fresh;
      ADAPT.localModels = fresh.models || [];
      fillModels(fresh.models || []);
      defaultModel.replaceChildren(h("option", { value: "" }, "(고르지 않음 — 로컬을 쓰지 않음)"),
        (fresh.models || []).map((m) => h("option", { value: m.id }, `${m.id} (${m.size_label})`)));
      defaultModel.value = s.local.default_model || "";
    }
  };
  if (st.download) { ADAPT.pull = st.download; renderPull(); }

  // Cloud·승격
  const cloudModel = h("select", {}, h("option", { value: "" }, "새 대화의 기본 모델과 같게"),
    (st.cloud_models || []).map((m) => h("option", { value: m.id }, m.label)));
  cloudModel.value = s.cloud_model || "";
  const escalation = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  escalation.checked = s.escalation !== false;
  const maxEsc = h("select", {}, [0, 1, 2].map((n) => h("option", { value: n }, `${n}번`)));
  maxEsc.value = String(s.max_escalations ?? 1);
  const retries = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  retries.checked = (s.local_retries ?? 1) > 0;
  const manualFallback = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  manualFallback.checked = !!s.manual_fallback;

  // 비용·지연
  const weeklyCalls = h("input", { type: "number", min: 0, value: s.budget.weekly_calls || 0 });
  const weeklyCredits = h("input", { type: "number", min: 0, value: s.budget.weekly_credits || 0 });
  const perRequest = h("input", { type: "number", min: 0, value: s.max_cost_per_request || 0 });
  const latency = h("select", {}, h("option", { value: "normal" }, "보통(품질 우선)"), h("option", { value: "fast" }, "빠른 응답 우선(속도를 잰 로컬 모델만)"));
  latency.value = s.latency || "normal";
  const b = st.budget || {};

  // 개인정보
  const sensitiveLocal = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  sensitiveLocal.checked = !!s.privacy.sensitive_local_only;
  const attachCloud = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  attachCloud.checked = s.privacy.attachments_to_cloud !== false;
  const tools = h("select", {}, h("option", { value: "allow" }, "그대로 쓰기(MCP·웹 검색 같은 외부 도구는 각 연결 설정을 따름)"),
    h("option", { value: "block" }, "막기(Local Only일 때 에이전트가 외부 도구를 쓰지 않음)"));
  tools.value = s.local_only_tools || "allow";
  const badge = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  badge.checked = s.show_badge !== false;

  const check = (box, label, hint) => h("div", { class: "field" },
    h("label", { style: "display:flex;align-items:center;font-weight:600;cursor:pointer" }, box, label), hint ? h("small", {}, hint) : null);
  const section = (title, ...kids) => h("section", { class: "adaptive-section" }, h("h3", {}, title), ...kids);
  const body = h("div", { class: "adaptive-body" },
    h("p", { class: "muted" }, "요청의 종류·난이도·개인정보·이 PC의 로컬 모델·비용을 보고 로컬 AI와 Cloud 모델 중 하나를 자동으로 고릅니다. ",
      "켜도 대화 위에서 직접 고른 모델은 바꾸지 않습니다. 새 대화는 '자동'으로 시작합니다."),
    check(enabled, "자동 모델 선택 켜기", "끄면 예전처럼 대화마다 고른 Cloud 모델만 씁니다."),
    section("정책", ...policyBoxes),
    section("로컬 AI (Ollama)", statusLine,
      h("div", { class: "field" }, h("label", {}, "주소"), h("div", { class: "row" }, endpoint, testBtn),
        h("label", { style: "display:flex;align-items:center;font-size:13px;margin-top:6px;cursor:pointer" }, remote, "다른 PC의 Ollama 허용(원격)"),
        h("small", {}, "기본은 이 PC(127.0.0.1)만 씁니다. 원격은 사설망(http)이나 인터넷(https만)에 둔 서버를 직접 허용할 때만 씁니다. ",
          "클라우드 메타데이터·링크 로컬 주소는 언제나 막고, 리다이렉트를 따라가지 않으며, API 키를 보내지 않습니다.")),
      h("div", { class: "row" },
        h("div", { class: "field", style: "flex:2" }, h("label", {}, "기본 로컬 모델"), defaultModel),
        h("div", { class: "field", style: "flex:1" }, h("label", {}, "문맥 길이(토큰)"), numCtx)),
      h("small", { class: "muted block" }, st.resources && st.resources.reliable
        ? `이 PC: RAM ${fmtBytes(st.resources.ram_total)} (남은 ${fmtBytes(st.resources.ram_available)})` +
          (st.resources.gpus && st.resources.gpus.length ? ` · GPU ${st.resources.gpus.map((g) => `${g.name} ${fmtBytes(g.vram_free)}/${fmtBytes(g.vram_total)}`).join(", ")}` : "") +
          (st.resources.apple_silicon ? " · Apple Silicon(통합 메모리)" : "") + ` · 모델에 쓸 수 있다고 보는 메모리 약 ${fmtBytes(st.memory_budget)}(추정)`
        : `이 PC의 자원을 알아내지 못해 보수적으로(약 ${fmtBytes(st.memory_budget)}) 봅니다.`),
      modelTable,
      h("div", { class: "field" }, h("label", {}, "모델 받기"), h("div", { class: "row" }, pullName, previewBtn), pullBox,
        h("small", {}, "누를 때만 받습니다. 받기 전에 크기·출처·라이선스를 먼저 보여 줍니다. 받은 모델은 Ollama 폴더에 저장됩니다."))),
    section("Cloud와 승격",
      h("div", { class: "field" }, h("label", {}, "기본 Cloud 모델"), cloudModel),
      check(escalation, "로컬 답이 검증을 통과하지 못하면 Cloud로 다시 답하기", "Local Only에서는 하지 않습니다. 이미 받은 로컬 답은 접어서 함께 보여 줍니다."),
      h("div", { class: "field" }, h("label", {}, "요청 하나에서 Cloud 승격 최대 횟수"), maxEsc),
      check(retries, "형식 문제(빈 답·JSON 아님)면 같은 로컬 모델로 한 번 더", null),
      check(manualFallback, "직접 고른 로컬 모델이 실패하면 Cloud 허용", "끄면(기본) 직접 고른 로컬 모델이 실패할 때 그대로 오류로 알립니다.")),
    section("비용",
      h("div", { class: "row" },
        h("div", { class: "field", style: "flex:1" }, h("label", {}, "주간 Cloud 호출 수 한도"), weeklyCalls),
        h("div", { class: "field", style: "flex:1" }, h("label", {}, "주간 크레딧 한도(추정)"), weeklyCredits),
        h("div", { class: "field", style: "flex:1" }, h("label", {}, "요청당 크레딧 한도(추정)"), perRequest)),
      h("small", { class: "muted block" }, `0이면 한도 없음. 지난 7일 Cloud 호출 ${b.calls ?? 0}번` + (b.limit_credits ? ` · 추정 크레딧 ${b.credits}` : "") +
        ". 크레딧은 앱 안내에 근거가 있는 모델(Claude Sonnet·Opus 5.5)만 추정하고, 근거가 없는 모델의 비용은 한도에 넣지 않습니다. POSTECH 크레딧과 Claude API 요금(USD)은 서로 바꾸거나 더하지 않습니다."),
      h("div", { class: "field" }, h("label", {}, "응답 속도"), latency)),
    section("개인정보·파일 전송",
      check(sensitiveLocal, "비밀번호·키·주민번호·카드번호·연락처가 보이는 요청은 로컬에서만", "로컬 모델이 없으면 Cloud로 보내지 않고 오류로 알립니다."),
      check(attachCloud, "첨부한 파일·페이지·논문 내용을 Cloud로 보내도 됨", "끄면 첨부가 있는 요청은 로컬에서만 처리합니다."),
      h("div", { class: "field" }, h("label", {}, "Local Only일 때 외부 도구"), tools),
      check(badge, "답변 아래에 고른 모델과 이유 표시", null)));
  ADAPT.modalBody = body;
  modal({
    title: "AI 실행 정책", body, wide: true,
    onClose: () => { ADAPT.modalBody = null; ADAPT.renderPull = null; ADAPT.afterPull = null; },
    buttons: [
      { label: "취소", value: null },
      { label: "저장", class: "primary", action: async (close) => {
        const values = {
          enabled: enabled.checked, policy: policyValue(), endpoint: endpoint.value.trim(), allow_remote: remote.checked,
          default_model: defaultModel.value, num_ctx: numCtx.value, cloud_model: cloudModel.value, escalation: escalation.checked,
          max_escalations: maxEsc.value, local_retries: retries.checked ? 1 : 0, manual_fallback: manualFallback.checked,
          budget: { weekly_calls: weeklyCalls.value, weekly_credits: weeklyCredits.value }, max_cost_per_request: perRequest.value,
          latency: latency.value, privacy: { sensitive_local_only: sensitiveLocal.checked, attachments_to_cloud: attachCloud.checked },
          local_only_tools: tools.value, show_badge: badge.checked,
        };
        if (values.enabled && values.policy === "local_only" && !values.default_model) {
          return toast("Local Only 정책을 쓰려면 기본 로컬 모델을 고르세요.");
        }
        const r = await api().adaptive_save(values);
        if (r.ok === false) return toast(r.error);
        ADAPT.state = r;
        ADAPT.localModels = r.models || [];
        applyState(r.app);
        close();
        toast("AI 실행 정책을 저장했습니다");
      } },
    ],
  });
}

async function adaptiveTestChat(model) {
  const input = h("textarea", { rows: 3, placeholder: "로컬 모델에게 보낼 글(대화 기록에 남지 않습니다)" });
  const out = h("pre", { class: "adaptive-license", hidden: true });
  const send = h("button", { class: "btn primary", type: "button", onclick: async () => {
    send.disabled = true;
    out.hidden = false;
    out.textContent = "답을 기다리는 중…";
    const r = await api().adaptive_test_chat(model, input.value);
    send.disabled = false;
    out.textContent = r.ok === false ? r.error : `${r.text}\n\n— ${r.ms}ms · ${r.tokens_per_s} 토큰/초`;
  } }, "보내기");
  modal({ title: `시험 대화 · ${model}`, body: h("div", {}, input, h("div", { class: "row", style: "margin:8px 0" }, send), out),
    buttons: [{ label: "닫기", value: null }] });
}

function adaptiveEvent(ev) {
  if (ev.kind === "pull") {
    ADAPT.pull = ev;
    if (ADAPT.renderPull) ADAPT.renderPull();
  } else if (ev.kind === "pull_done") {
    toast(`${ev.model} 모델을 받았습니다`);
    ADAPT.afterPull ? ADAPT.afterPull(true, `${ev.model}을(를) 받았습니다. '기본 로컬 모델'에서 고르고 저장하세요.`) : (ADAPT.pull = null);
    adaptiveRefreshModels();
  } else if (ev.kind === "pull_error") {
    toast(ev.error);
    ADAPT.afterPull ? ADAPT.afterPull(false, ev.error) : (ADAPT.pull = null);
  }
}

/* 설정 창에 넣는 칸 */
function adaptiveSettingsField() {
  const line = h("small", { style: "flex:1;margin:0" }, adaptiveStatusText());
  return h("div", { class: "field" }, h("label", {}, "AI 실행 정책 (자동 모델 선택·로컬 AI)"),
    h("div", { class: "row" }, line, h("button", { class: "btn", type: "button", onclick: () => showAdaptive() }, "열기")),
    h("small", {}, "요청에 따라 로컬 AI(Ollama)와 Cloud 모델 중 알맞은 쪽을 고르게 합니다. 기본은 꺼짐입니다."));
}

window.adaptiveModelOptions = adaptiveModelOptions;
window.routeBadge = routeBadge;
window.streamingRouteNode = streamingRouteNode;
window.routeEvent = routeEvent;
window.adaptiveEvent = adaptiveEvent;
window.adaptiveDone = adaptiveDone;
window.showAdaptive = showAdaptive;
window.adaptiveSettingsField = adaptiveSettingsField;
window.adaptiveRefreshModels = adaptiveRefreshModels;
