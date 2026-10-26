// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
"use strict";

/* ---------- Code 화면 아래 패널의 터미널(1.18) ----------
   진짜 대화형 셸(Windows PowerShell·cmd는 ConPTY, macOS·Linux는 로그인 셸)을 xterm.js로 보인다. 백엔드는 terminal.py·code_api.code_term_*.
   - 코드 화면을 열면 아래 패널에 터미널 하나를 연다(작업 폴더에서 시작). + 로 더 열고, 탭으로 오간다(6개까지).
   - 키 입력은 차례가 섞이지 않게 하나씩 보낸다(js_api 호출은 순서를 지키지 않을 수 있다).
   - 복사: 고른 글이 있으면 Ctrl+C(또는 Ctrl+Shift+C), 없으면 Ctrl+C는 셸에 보낸다(중단). 붙여 넣기: Ctrl+V·Ctrl+Shift+V.
   - Ctrl+` : 아래 패널 열기·닫기. 'AI에게 묻기'는 고른 글(없으면 끝부분 200줄)을 채팅에 첨부한다. */

const TERM = { sessions: [], active: null, early: new Map(), loaded: false, opening: false };
const TERM_FONT = '"Cascadia Code", Consolas, "D2Coding", Menlo, monospace';

function termAvailable() { return codeFeature("terminal") && !!window.Terminal && !!window.FitAddon; }

function termTheme() {
  return CODE.dark
    ? { background: "#151515", foreground: "#e4e4e4", cursor: "#e4e4e4", selectionBackground: "#3a4a63" }
    : { background: "#fbfaf8", foreground: "#1f1f1f", cursor: "#1f1f1f", selectionBackground: "#c7d7f0",
      black: "#1f1f1f", brightBlack: "#6b6b6b", white: "#bfbfbf", brightWhite: "#e6e6e6", yellow: "#946200", brightYellow: "#7a5200" };
}

function termSession(id) { return TERM.sessions.find((s) => s.id === id); }

/* 아래 패널을 그린다(머리: 터미널 탭·새 터미널·AI에게 묻기·닫기, 몸: 터미널들) */
function termRenderHead() {
  const tabs = $("#code-term-tabs");
  if (!tabs) return;
  tabs.replaceChildren(...TERM.sessions.map((s) => h("span", { class: "code-ttab" + (s.id === TERM.active ? " active" : "") + (s.alive ? "" : " dead") },
    h("button", { class: "code-ttab-name", role: "tab", "aria-selected": String(s.id === TERM.active), title: s.cwd || s.title,
      onclick: () => termShow(s.id, true) }, s.title + (s.alive ? "" : " (끝남)")),
    h("button", { class: "code-ttab-close", title: "터미널 닫기", "aria-label": `${s.title} 닫기`, html: ICONS.close, onclick: () => termClose(s.id) }))));
  const ask = $("#code-term-ask");
  if (ask) ask.disabled = !TERM.active;
}

function termEmpty(text) {
  const body = $("#code-bottom-body");
  if (!body) return;
  body.querySelectorAll(".code-term-empty").forEach((x) => x.remove());
  if (TERM.sessions.length) return;
  body.append(h("div", { class: "code-term-empty muted" }, text || "",
    termAvailable() ? h("button", { class: "btn", id: "code-term-start", onclick: () => termNew() }, "새 터미널") : null));
}

/* 처음 보일 때: 이미 열린 터미널(앱 화면을 다시 불렀을 때)을 다시 붙이고, 없으면 하나 연다 */
async function termEnsure() {
  if (!termAvailable()) {
    termEmpty(CODE.state && CODE.state.platform === "android" ? "이 기기에서는 터미널을 쓸 수 없습니다(PC 앱에서 쓰세요)."
      : "터미널을 쓸 수 없습니다.");
    return;
  }
  if (!TERM.loaded) {
    TERM.loaded = true;
    const r = await codeCall(api().code_terms(), true);
    for (const t of (r && r.terminals) || []) if (t.alive) termAttach(t, t.scrollback || "");
  }
  // 저절로 열 때는 초점을 가져가지 않는다(작업 탭의 입력 칸이 먼저). 터미널을 누르거나 Ctrl+`이면 터미널로
  // 1.18: 작업 폴더가 바뀌면(로컬 ↔ SSH 서버) 그 폴더의 터미널이 없을 때 하나 더 연다(예전 터미널은 그대로 둔다)
  const ws = CODE.state && CODE.state.workspace.path;
  const here = TERM.sessions.find((s) => s.alive && ws && s.cwd === ws);
  if (!TERM.opening && (!TERM.sessions.length || (ws && !here))) await termNew(false);
  else {
    if (here && here.id !== TERM.active) termShow(here.id);
    termFit();
  }
}

function termView() {
  const el = h("div", { class: "code-term", hidden: true });
  $("#code-bottom-body").append(el);
  const term = new Terminal({ fontFamily: TERM_FONT, fontSize: 13, lineHeight: 1.15, cursorBlink: true, scrollback: 5000,
    theme: termTheme(), macOptionIsMeta: true, rightClickSelectsWord: false, screenReaderMode: false });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(el);
  return { el, term, fit };
}

function termAttach(info, scrollback, focus = false) {
  const v = termView();
  const s = { id: info.id, title: info.title, cwd: info.cwd, alive: info.alive !== false, queue: "", sending: false, ...v };
  TERM.sessions.push(s);
  if (scrollback) s.term.write(scrollback);
  for (const text of TERM.early.get(s.id) || []) s.term.write(text);
  TERM.early.delete(s.id);
  s.term.onData((d) => termSend(s, d));
  s.term.onResize(({ cols, rows }) => { if (s.alive) api().code_term_resize(s.id, cols, rows); });
  s.term.attachCustomKeyEventHandler((e) => termKey(s, e));
  termShow(s.id, focus);
  return s;
}

async function termNew(focus = true) {
  if (!termAvailable() || TERM.opening) return;
  TERM.opening = true;
  try {
    // 크기를 먼저 맞춘 화면으로 셸을 연다(첫 프롬프트가 알맞은 폭으로 나오게)
    const probe = termView();
    probe.el.hidden = false;
    try { probe.fit.fit(); } catch { /* 숨어 있으면 기본 크기 */ }
    const cols = probe.term.cols || 80, rows = probe.term.rows || 24;
    probe.term.dispose();
    probe.el.remove();
    const r = await codeCall(api().code_term_open(cols, rows));
    if (!r) { termEmpty(""); return; }
    termAttach(r.terminal, "", focus);
    termEmpty();
  } finally {
    TERM.opening = false;
  }
}

/* 키 입력: 차례대로 하나씩 보낸다(앞 요청이 끝나면 그동안 쌓인 것을 한 번에) */
async function termSend(s, data) {
  if (!s.alive) { termClose(s.id); return; }   // 끝난 터미널은 아무 키나 누르면 닫는다
  s.queue += data;
  if (s.sending) return;
  s.sending = true;
  try {
    while (s.queue && s.alive) {
      const chunk = s.queue;
      s.queue = "";
      const r = await api().code_term_write(s.id, chunk);
      if (r && r.ok === false) { s.term.write(`\r\n\x1b[31m${r.error}\x1b[0m\r\n`); break; }
    }
  } finally {
    s.sending = false;
  }
}

function termKey(s, e) {
  if (e.type !== "keydown") return true;
  const k = e.key.toLowerCase();
  const mod = e.ctrlKey && !e.altKey && !e.metaKey;
  if (mod && k === "c" && s.term.hasSelection()) {   // 복사(고른 글이 있을 때만, 없으면 셸에 Ctrl+C)
    copyText(s.term.getSelection());
    s.term.clearSelection();
    e.preventDefault();
    return false;
  }
  if (mod && e.shiftKey && k === "v") return false;   // 붙여 넣기는 브라우저의 paste 이벤트로(아래 Ctrl+V와 같음)
  if (mod && (k === "`" || e.code === "Backquote")) { e.preventDefault(); codeBottom("terminal", true); return false; }
  return true;
}

function termShow(id, focus = false) {
  TERM.active = id;
  for (const s of TERM.sessions) s.el.hidden = s.id !== id;
  termRenderHead();
  termFit();
  const s = termSession(id);
  if (s && focus) setTimeout(() => s.term.focus(), 0);
}

function termFocus() {
  const s = termSession(TERM.active);
  if (s) s.term.focus();
}

function termFit() {
  const s = termSession(TERM.active);
  if (!s || s.el.hidden || !s.el.isConnected || !s.el.offsetParent) return;
  try { s.fit.fit(); } catch { /* 크기를 잴 수 없을 때(숨김) */ }
}

async function termClose(id) {
  const s = termSession(id);
  if (!s) return;
  if (s.alive) await codeCall(api().code_term_close(id), true);
  s.alive = false;
  s.term.dispose();
  s.el.remove();
  TERM.sessions = TERM.sessions.filter((x) => x.id !== id);
  if (TERM.active === id) TERM.active = TERM.sessions.length ? TERM.sessions[TERM.sessions.length - 1].id : null;
  if (TERM.active) termShow(TERM.active, true);
  termRenderHead();
  termEmpty("터미널이 없습니다. ");
}

async function termAsk() {
  const s = termSession(TERM.active);
  if (!s) return;
  if (S.attach.length >= S.attachLimits.max_files) return toast(`파일은 한 번에 ${S.attachLimits.max_files}개까지 첨부할 수 있습니다`);
  let text = s.term.getSelection();
  if (!text) {   // 고른 글이 없으면 끝부분 200줄
    const buf = s.term.buffer.active;
    const lines = [];
    for (let i = Math.max(0, buf.length - 200); i < buf.length; i++) lines.push(buf.getLine(i)?.translateToString(true) ?? "");
    text = lines.join("\n");
  }
  const res = await codeCall(api().code_term_ask(text, s.title));
  if (!res) return;
  for (const a of res.attachments) S.attach.push({ id: a.id, name: a.name, size: a.size, kind: a.kind, status: "ready", progress: 1 });
  renderTray();
  const input = $("#input");
  if (!input.value.trim()) input.value = res.question;
  autoresize();
  updateSend();
  codeLeave();
  input.focus();
  toast("터미널 출력을 첨부했습니다. 질문을 고쳐 보내세요");
}

function termSetTheme() {
  for (const s of TERM.sessions) s.term.options.theme = termTheme();
}

/* code.js의 codeEvent가 넘겨 준다 */
function termEvent(ev) {
  const s = termSession(ev.id);
  if (ev.kind === "term_output") {
    if (s) s.term.write(ev.data);
    else {   // 셸을 연 응답보다 출력이 먼저 왔다
      const list = TERM.early.get(ev.id) || [];
      list.push(ev.data);
      TERM.early.set(ev.id, list);
    }
  } else if (ev.kind === "term_exit" && s && s.alive) {
    s.alive = false;
    s.term.write(`\r\n\x1b[2m[터미널이 끝났습니다${ev.code != null ? ` — 종료 코드 ${ev.code}` : ""}. 아무 키나 누르면 닫습니다]\x1b[0m\r\n`);
    termRenderHead();
  }
}

window.termEnsure = termEnsure;
window.termNew = termNew;
window.termEvent = termEvent;
window.termFit = termFit;
window.termFocus = termFocus;
window.termAsk = termAsk;
window.termSetTheme = termSetTheme;
