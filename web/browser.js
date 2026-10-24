// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
"use strict";

/* ---------- 브라우저(1.13): 채팅 옆 웹페이지 ----------
   웹페이지는 앱 창 오른쪽의 네이티브 웹 뷰가 그리고(browser.py), 여기에는 주소 표시줄과 AI 연결 버튼만 둔다.
   웹페이지 쪽에는 POSCHAT API가 없다. 이 화면이 browser_* 를 불러 페이지를 읽고 채팅 첨부로 만든다. */

const BR = { open: false, available: true, url: "", title: "", loading: false, can_back: false, can_forward: false,
  mode: "", busy: "" };

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
      h("span", { class: "browser-status", id: "browser-status", role: "status", "aria-live": "polite" })));
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

function browserEvent(ev) {
  if (ev.kind === "blocked") return toast(`${ev.reason} (${ev.url.slice(0, 80)})`);
  for (const k of ["url", "title", "loading", "can_back", "can_forward", "mode"]) if (k in ev) BR[k] = ev[k];
  if ("visible" in ev) BR.open = ev.visible;
  renderBrowserBar();
}

async function browserInit() {
  const st = await api().browser_state();
  BR.available = !!st.available;
  $("#btn-browser").hidden = !BR.available;
  browserEvent(st);
}

$("#btn-browser").addEventListener("click", browserToggle);
if (window.pywebview && window.pywebview.api) browserInit();
else window.addEventListener("pywebviewready", browserInit, { once: true });
