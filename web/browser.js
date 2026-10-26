// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
"use strict";

/* ---------- 브라우저(1.13): 채팅 옆 웹페이지 ----------
   웹페이지는 앱 창 오른쪽의 네이티브 웹 뷰가 그리고(browser.py), 여기에는 주소 표시줄과 AI 연결 버튼만 둔다.
   웹페이지 쪽에는 POSCHAT API가 없다. 이 화면이 browser_* 를 불러 페이지를 읽고 채팅 첨부로 만든다. */

const BR = { open: false, available: true, url: "", title: "", loading: false, can_back: false, can_forward: false,
  mode: "", busy: "", agent: null };  // agent: 1.16 브라우저 에이전트 진행 {action, status, count, limit, elapsed, summary, paused}
const BR_ACTION = { snapshot: "페이지 살펴보기", click: "누르기", type: "입력", select: "고르기", scroll: "스크롤", wait: "기다리기",
  extract: "글 읽기", screenshot: "화면 캡처", open: "주소 열기", back: "뒤로", forward: "앞으로", refresh: "새로 고침" };
const BR_STATUS = { running: "하는 중", done: "완료", denied: "거부됨", error: "실패", paused: "일시정지" };

function browserBar() {
  let bar = $("#browser-bar");
  if (bar) return bar;
  const btn = (icon, label, onclick, extra = {}) => h("button", { class: "icon-btn", title: label, "aria-label": label,
    html: ICONS[icon], onclick, ...extra });
  const address = h("input", { id: "browser-address", type: "text", inputmode: "url", autocomplete: "off", spellcheck: "false",
    placeholder: "주소 또는 검색어", "aria-label": "주소 또는 검색어" });
  const form = h("form", { class: "browser-address", role: "search", onsubmit: (e) => {
    e.preventDefault();
    browserOpen(address.value);
  } }, address);
  const action = (id, label, title, onclick) => h("button", { class: "btn browser-action", id, title, onclick }, label);
  bar = h("section", { id: "browser-bar", "aria-label": "브라우저", hidden: true },
    h("div", { class: "browser-row" },
      btn("back", "뒤로", () => browserNav("back"), { id: "browser-back" }),
      btn("forward", "앞으로", () => browserNav("forward"), { id: "browser-forward" }),
      btn("retry", "새로 고침", () => browserNav(BR.loading ? "stop" : "reload"), { id: "browser-reload" }),
      form,
      btn("external", "기본 브라우저로 열기", () => browserCall(api().browser_external())),
      btn("close", "브라우저 닫기", () => browserClose())),
    h("div", { class: "browser-row browser-actions" },
      action("browser-ask-page", "이 페이지에 대해 묻기", "지금 보는 페이지의 글을 채팅에 첨부합니다", () => browserAttach("page")),
      action("browser-ask-selection", "선택한 부분 묻기", "페이지에서 드래그한 글만 첨부합니다", () => browserAttach("selection")),
      action("browser-save-paper", "연구 라이브러리에 저장", "arXiv·DOI 논문 페이지를 라이브러리에 더합니다", () => browserSavePaper()),
      h("span", { class: "browser-status", id: "browser-status", role: "status", "aria-live": "polite" })),
    // 1.16: 에이전트가 이 브라우저를 조작하는 동안의 진행 표시
    h("div", { class: "browser-row browser-agent", id: "browser-agent", hidden: true, role: "status", "aria-live": "polite" },
      h("span", { class: "browser-agent-dot", "aria-hidden": "true" }),
      h("span", { class: "browser-agent-text", id: "browser-agent-text" }),
      h("button", { class: "btn browser-action", id: "browser-agent-pause", onclick: () => browserAgentPause() }, "일시정지"),
      h("button", { class: "btn browser-action danger", id: "browser-agent-stop", title: "에이전트 작업을 멈춥니다(채팅의 중지와 같음)",
        onclick: () => { api().stop(); toast("에이전트를 멈췄습니다"); } }, "멈춤")));
  $("#topbar").after(bar);
  return bar;
}

function renderBrowserBar() {
  const bar = browserBar();
  // PO노트·도구 화면에서는 막대를 숨긴다(웹페이지 뷰는 오른쪽에 그대로 남는다)
  bar.hidden = !BR.open || (typeof PO !== "undefined" && PO.open) || (typeof PAGE !== "undefined" && !!PAGE.id);
  $("#btn-browser")?.classList.toggle("active", BR.open);
  $("#btn-browser")?.setAttribute("aria-pressed", String(BR.open));
  const address = $("#browser-address");
  if (address && document.activeElement !== address) address.value = BR.url || "";
  $("#browser-back").disabled = !BR.can_back;
  $("#browser-forward").disabled = !BR.can_forward;
  const reload = $("#browser-reload");
  reload.innerHTML = BR.loading ? ICONS.close : ICONS.retry;
  reload.title = BR.loading ? "멈추기" : "새로 고침";
  reload.setAttribute("aria-label", reload.title);
  for (const id of ["browser-ask-page", "browser-ask-selection", "browser-save-paper"]) $(`#${id}`).disabled = !BR.url || !!BR.busy;
  const ag = BR.agent;
  const strip = $("#browser-agent");
  strip.hidden = !ag;
  if (ag) {
    const what = `${BR_ACTION[ag.action] || ag.action || "준비"}${ag.summary ? ` · ${ag.summary}` : ag.target ? ` · ${ag.target}` : ""}`;
    $("#browser-agent-text").textContent = `에이전트 조작 중 — ${what} (${BR_STATUS[ag.paused ? "paused" : ag.status] || ag.status || ""}) · ` +
      `${ag.count || 0}/${ag.limit || 40}번 · ${Math.round(ag.elapsed || 0)}초`;
    strip.classList.toggle("paused", !!ag.paused);
    strip.classList.toggle("error", ag.status === "error" || ag.status === "denied");
    $("#browser-agent-pause").textContent = ag.paused ? "계속" : "일시정지";
  }
  const status = $("#browser-status");
  status.textContent = BR.busy || (BR.loading ? "불러오는 중…" : (BR.title || ""));
  status.title = BR.title || "";
}

async function browserCall(promise) {
  const res = await promise;
  if (res && res.ok === false) {
    toast(res.error || "브라우저 오류");
    return null;
  }
  return res;
}

async function browserToggle() {
  if (BR.open) return browserClose();
  leaveViews();
  if (window.paperLeave) paperLeave();  // 오른쪽 화면은 하나만(1.14 논문 화면)
  if (window.codeLeave) codeLeave();  // 1.15 코드 화면(열린 탭은 그대로 남는다)
  if (!BR.available) return toast("이 실행 방식에서는 브라우저를 쓸 수 없습니다.");
  BR.open = true;
  renderBrowserBar();
  const res = await browserCall(api().browser_show());
  if (!res) {
    BR.open = false;
    renderBrowserBar();
    return;
  }
  if (isNarrow()) setCollapsed(true);
  setTimeout(() => $("#browser-address")?.focus(), 50);
}

async function browserOpen(text) {
  if (!String(text || "").trim()) return;
  BR.open = true;
  const res = await browserCall(api().browser_open(text));
  if (res) {
    BR.url = res.url;
    BR.loading = true;
    const address = $("#browser-address");
    if (address) address.value = res.url;  // 입력한 글 대신 실제로 연 주소(검색이면 검색 주소)
  }
  renderBrowserBar();
}

function browserNav(action) {
  browserCall(api().browser_nav(action));
}

async function browserClose() {
  BR.open = false;
  renderBrowserBar();
  await browserCall(api().browser_hide());
}

async function browserAttach(kind) {
  if (S.attach.length >= S.attachLimits.max_files) return toast(`파일은 한 번에 ${S.attachLimits.max_files}개까지 첨부할 수 있습니다`);
  BR.busy = kind === "selection" ? "선택한 부분을 읽는 중…" : "페이지를 읽는 중…";
  renderBrowserBar();
  try {
    const res = await browserCall(api().browser_attach(kind));
    if (!res) return;
    const a = res.attachment;
    S.attach.push({ id: a.id, name: a.name, size: a.size, kind: a.kind, status: "ready", progress: 1 });
    renderTray();
    updateSend();
    const input = $("#input");
    if (!input.value.trim()) {
      input.value = kind === "selection" ? "선택한 부분을 쉽게 설명해 줘." : "이 페이지의 핵심을 요약해 줘.";
      autoresize();
      updateSend();
    }
    input.focus();
    input.select();
    toast(kind === "selection" ? "선택한 부분을 첨부했습니다. 질문을 고쳐 보내세요" : "페이지를 첨부했습니다. 질문을 고쳐 보내세요");
  } finally {
    BR.busy = "";
    renderBrowserBar();
  }
}

async function browserSavePaper() {
  BR.busy = "논문 정보를 찾는 중…";
  renderBrowserBar();
  try {
    const res = await api().browser_save_paper();
    if (res.ok === false) {
      if (res.need_feature === "research") {
        if (confirm(res.error + "\n\n지금 연구 라이브러리를 열까요?")) pageOpen("research");
        return;
      }
      return toast(res.error);
    }
    toast(`연구 라이브러리에 더했습니다: ${res.paper}`);
  } finally {
    BR.busy = "";
    renderBrowserBar();
  }
}

async function browserAgentPause() {
  const paused = !(BR.agent && BR.agent.paused);
  await api().browser_agent_pause(paused);
}

function browserEvent(ev) {
  if (ev.kind === "blocked") return toast(`${ev.reason} (${ev.url.slice(0, 80)})`);
  if (ev.kind === "agent") {
    if (ev.status === "finished") BR.agent = null;
    else if (ev.status === "paused" || ev.status === "resumed") { if (BR.agent) BR.agent.paused = ev.status === "paused"; }
    else BR.agent = { ...(BR.agent || {}), ...ev, paused: ev.status === "paused" ? true : (BR.agent ? BR.agent.paused : false) };
    if (ev.url) BR.url = ev.url;
    return renderBrowserBar();
  }
  for (const k of ["url", "title", "loading", "can_back", "can_forward", "mode"]) if (k in ev) BR[k] = ev[k];
  if ("visible" in ev) BR.open = ev.visible;
  renderBrowserBar();
}

async function browserInit() {
  const st = await api().browser_state();
  BR.available = !!st.available;
  $("#btn-browser").hidden = !BR.available;
  $("#btn-plms").hidden = !BR.available;
  browserEvent(st);
}

$("#btn-browser").addEventListener("click", browserToggle);
if (window.pywebview && window.pywebview.api) browserInit();
else window.addEventListener("pywebviewready", browserInit, { once: true });


/* PLMS: 인증은 네이티브 웹 뷰에서, 조회 결과만 앱 화면에서 다룬다. */
function plmsPanel() {
  const content = h("div", { id: "plms-content", role: "status", "aria-live": "polite" },
    h("p", {}, "내장 브라우저에서 POSTECH SSO·StonePASS 인증을 직접 마친 뒤 ‘내 수업 불러오기’를 누르세요."),
    h("p", {}, "요청한 공지·자료는 선택한 AI 서비스로 전송될 수 있습니다. 비밀번호·인증 코드·쿠키는 AI에 보내지 않습니다."));
  let generation = 0, closed = false;
  const showError = (message) => content.replaceChildren(h("p", { role: "alert" }, message));
  const call = async (fn, render) => {
    const current = ++generation;
    content.replaceChildren(h("p", {}, "PLMS에서 읽는 중…"));
    try {
      const res = await fn();
      if (closed || current !== generation) return;
      if (!res || res.ok === false) return showError(res?.error || "PLMS를 읽지 못했습니다.");
      render(res);
    } catch (_) {
      if (!closed && current === generation) showError("PLMS 요청에 실패했습니다. 다시 시도하세요.");
    }
  };
  const ask = (prompt) => {
    close();
    leaveViews();
    S.config.agent_mode = true;
    $("#agent-toggle").checked = true;
    api().set_agent_mode(true);
    $("#input").value = prompt;
    autoresize(); updateSend(); $("#input").focus();
  };
  const list = (items, onclick) => h("div", { class: "plms-list" }, items.map((item) =>
    h("button", { class: "btn", onclick: () => onclick(item) }, item.title)));
  const read = (course, item, parents) => call(() => api().plms_read(course.id, item.url, "", 0, parents), (res) => {
    const doc = res.document;
    const renderDoc = (data) => {
      content.replaceChildren(h("button", { class: "btn", onclick: () => openCourse(course) }, "수업으로 돌아가기"),
        h("h3", {}, data.title), h("p", {}, data.url),
        h("pre", { class: "plms-text" }, data.text),
        h("button", { class: "btn primary", onclick: () => ask(`PLMS 수업 ${course.title} (course_id=${course.id})의 자료를 읽고 요약해 줘.\n주소: ${item.url}\nparent: ${JSON.stringify(parents)}`) }, "에이전트에게 이 자료 묻기"),
        data.next_offset == null ? null : h("button", { class: "btn", onclick: () => call(
          () => api().plms_read(course.id, item.url, "", data.next_offset, parents), (r) => renderDoc(r.document)) }, "이어서 읽기"),
        list(data.items || [], (child) => read(course, child, [...parents, item.url])));
    };
    renderDoc(doc);
  });
  const openCourse = (course) => call(() => api().plms_course(course.id), (res) => {
    const c = res.course;
    content.replaceChildren(h("h3", {}, c.title),
      h("button", { class: "btn primary", onclick: () => ask(`PLMS 수업 ${c.title} (course_id=${c.id})의 공지와 강의자료를 확인해서 정리해 줘. 원문 링크도 알려 줘.`) }, "에이전트에게 수업 정리 맡기기"),
      h("pre", { class: "plms-text" }, c.text),
      list(c.items, (item) => read(c, item, [])));
  });
  const { close } = modal({ title: "PLMS 수업·공지·자료", wide: true, body: content,
    onClose: () => { closed = true; ++generation; }, buttons: [
      { label: "SSO 로그인", action: async (dismiss) => {
        dismiss(); leaveViews();
        if (window.paperLeave) paperLeave();
        if (window.codeLeave) codeLeave();
        const res = await browserCall(api().plms_login());
        if (res) { BR.open = true; BR.url = res.url; renderBrowserBar(); toast("SSO 인증 후 PLMS → 내 수업 불러오기를 누르세요."); }
      } },
      { label: "내 수업 불러오기", class: "primary", action: () => call(() => api().plms_courses(), (res) => {
        content.replaceChildren(h("h3", {}, `참여 수업 ${res.courses.length}개`),
          res.courses.length ? list(res.courses, openCourse) : h("p", {}, "표시할 수업이 없습니다. PLMS의 내 강좌 화면도 확인하세요."));
      }) },
      { label: "연결 해제", action: () => call(() => api().plms_disconnect(), () => {
        content.replaceChildren(h("p", {}, "PLMS 조회 연결을 끄고 PLMS 전용 쿠키를 지웠습니다. 학교 공통 SSO 세션과 기존 대화 기록은 유지됩니다."));
      }) },
      { label: "닫기" }
    ] });
}
$("#btn-plms").addEventListener("click", plmsPanel);
