"use strict";

/* ---------- 아이콘 ---------- */
const ICONS = {
  sidebar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>',
  puzzle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3h4v3a2 2 0 1 0 4 0V3h3v7h-3a2 2 0 1 0 0 4h3v7h-7v-3a2 2 0 1 0-4 0v3H3v-7h3a2 2 0 1 0 0-4H3V3h7Z"/></svg>',
  brain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3 3 3 0 0 0 3-3V7a3 3 0 0 0-3-3Z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3 3 3 0 0 1-3-3"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>',
  up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/></svg>',
  pencil: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  retry: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>',
};

/* ---------- 상태 ---------- */
const S = {
  threads: [],
  currentId: null,
  thread: null,
  busy: false,
  busyThread: null,
  status: "",
  workspace: { path: "", name: "", has_init: false },
  skills: [],
  config: {},
  dataDir: "",
  version: "",
  memory: [],
  slash: { items: [], index: 0 },
};

const $ = (sel, root = document) => root.querySelector(sel);
const api = () => window.pywebview.api;

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => (t.hidden = true), 2200);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = h("textarea", { style: "position:fixed;opacity:0" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast("복사했습니다");
}

/* ---------- 마크다운 ---------- */
marked.setOptions({ gfm: true, breaks: true });

// 수식: \( \)와 $ $는 문장 안 수식, \[ \]와 $$ $$는 독립 수식으로 KaTeX가 그린다.
// marked 확장으로 처리하므로 코드 블록과 `인라인 코드` 안은 수식으로 바뀌지 않는다.
// $ 한 개는 금액("$5와 $10")과 헷갈리지 않도록 $ 바로 안쪽에 공백이 없고 닫는 $ 뒤에 숫자가 없을 때만 수식으로 본다.
const MATH_INLINE = [
  [/^\$\$([\s\S]+?)\$\$/, true],
  [/^\\\[([\s\S]+?)\\\]/, true],
  [/^\\\(([\s\S]+?)\\\)/, false],
  [/^\$(?![\s$])((?:\\[\s\S]|[^\\$\n])+?)(?<!\s)\$(?!\d)/, false],
];
const MATH_BLOCK = /^ {0,3}(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\])[ \t]*(?:\n+|$)/;

function renderMath(tex, displayMode) {
  // throwOnError: false — 문법이 틀린 수식은 오류 대신 원문을 빨간색으로 보여 준다.
  return katex.renderToString(tex.trim(), { displayMode, throwOnError: false, output: "html", strict: "ignore" });
}

if (window.katex) {
  marked.use({
    extensions: [
      {
        name: "mathBlock",
        level: "block",
        start: (src) => src.match(/^ {0,3}(?:\$\$|\\\[)/m)?.index,
        tokenizer(src) {
          const m = MATH_BLOCK.exec(src);
          if (m) return { type: "mathBlock", raw: m[0], text: m[1] ?? m[2] };
        },
        renderer: (token) => renderMath(token.text, true) + "\n",
      },
      {
        name: "mathInline",
        level: "inline",
        start: (src) => {
          const i = src.search(/\$|\\[([]/);
          return i < 0 ? undefined : i;
        },
        tokenizer(src) {
          for (const [re, display] of MATH_INLINE) {
            const m = re.exec(src);
            if (m) return { type: "mathInline", raw: m[0], text: m[1], display };
          }
        },
        renderer: (token) => renderMath(token.text, token.display),
      },
    ],
  });
}

// CommonMark는 "**`코드`**로"처럼 닫는 ** 바로 뒤에 한글이 오면 굵게로 인식하지 않는다.
// 코드 블록 밖의 **...**를 미리 <strong>으로 바꿔 둔다(안쪽 마크다운은 그대로 처리된다).
function fixKoreanBold(text) {
  return text.split(/(```[\s\S]*?```)/).map((part, i) =>
    i % 2 ? part : part.replace(/\*\*(?=\S)([^*\n]*?\S)\*\*/g, "<strong>$1</strong>")).join("");
}

function renderMarkdown(text) {
  const box = h("div", { class: "md" });
  box.innerHTML = DOMPurify.sanitize(marked.parse(fixKoreanBold(text || "")));
  box.querySelectorAll("a").forEach((a) => a.setAttribute("target", "_blank"));
  box.querySelectorAll("pre").forEach((pre) => {
    const code = pre.querySelector("code");
    const lang = ((code && code.className.match(/language-(\S+)/)) || [])[1] || "code";
    const btn = h("button", { html: ICONS.copy + "<span>복사</span>" });
    btn.addEventListener("click", () => copyText(code ? code.textContent : pre.textContent));
    pre.prepend(h("div", { class: "code-head" }, h("span", {}, lang), btn));
  });
  return box;
}

/* ---------- 사이드바 ---------- */
function groupLabel(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = (today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000;
  if (diff <= 0) return "오늘";
  if (diff === 1) return "어제";
  if (diff < 7) return "지난 7일";
  if (diff < 30) return "지난 30일";
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
}

function renderSidebar() {
  const list = $("#thread-list");
  list.innerHTML = "";
  let last = null;
  for (const t of S.threads) {
    const g = groupLabel(t.updated);
    if (g !== last) {
      list.append(h("div", { class: "group-title" }, g));
      last = g;
    }
    const item = h("div", { class: "thread" + (t.id === S.currentId ? " active" : ""), title: t.title },
      h("span", { class: "t-title" }, t.title),
      S.busy && S.busyThread === t.id ? h("span", { class: "spinner-dot" }) : null,
      h("span", { class: "t-actions" },
        h("button", { title: "이름 변경", html: ICONS.pencil, onclick: (e) => { e.stopPropagation(); startRename(item, t); } }),
        h("button", { title: "삭제", html: ICONS.trash, onclick: (e) => { e.stopPropagation(); deleteThread(t); } }),
      ),
    );
    item.addEventListener("click", () => openThread(t.id));
    item.addEventListener("dblclick", () => startRename(item, t));
    list.append(item);
  }
  const ws = S.workspace;
  $("#ws-name").textContent = ws.path ? ws.name + (ws.has_init ? " · INIT.md" : "") : "선택 안 됨";
  $("#btn-workspace").title = ws.path || "작업 폴더를 선택하세요";
}

function startRename(item, t) {
  const input = h("input", { value: t.title });
  const done = async (save) => {
    if (save && input.value.trim() && input.value.trim() !== t.title) {
      S.threads = await api().rename_thread(t.id, input.value.trim());
      if (t.id === S.currentId) {
        S.thread.title = input.value.trim();
        $("#chat-title").textContent = S.thread.title;
      }
    }
    renderSidebar();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing) done(true);
    if (e.key === "Escape") done(false);
  });
  input.addEventListener("blur", () => done(true));
  input.addEventListener("click", (e) => e.stopPropagation());
  item.replaceChildren(input);
  input.focus();
  input.select();
}

async function deleteThread(t) {
  if (!confirm(`'${t.title}' 대화를 삭제할까요?`)) return;
  S.threads = await api().delete_thread(t.id);
  if (t.id === S.currentId) {
    if (S.threads.length) await openThread(S.threads[0].id);
    else await newThread();
  } else renderSidebar();
}

async function refreshThreads() {
  S.threads = await api().list_threads();
  renderSidebar();
}

/* ---------- 대화 ---------- */
async function openThread(id) {
  const thread = await api().load_thread(id);
  if (!thread) return refreshThreads();
  S.currentId = id;
  S.thread = thread;
  $("#chat-title").textContent = thread.title;
  renderSidebar();
  renderMessages();
  $("#input").focus();
}

async function newThread() {
  // 이미 비어 있는 새 대화가 열려 있으면 그대로 쓴다
  if (S.thread && !S.thread.messages.length) {
    $("#input").focus();
    return;
  }
  const thread = await api().new_thread();
  S.threads.unshift({ id: thread.id, title: thread.title, updated: thread.updated });
  await openThread(thread.id);
}

function messageNode(msg) {
  if (msg.role === "user") {
    return h("div", { class: "msg user" }, h("div", { class: "bubble" }, msg.content));
  }
  if (msg.role === "assistant") {
    return h("div", { class: "msg assistant" },
      h("div", { class: "avatar" }, "P"),
      h("div", { class: "body" },
        renderMarkdown(msg.content),
        h("div", { class: "msg-actions" },
          h("button", { title: "복사", html: ICONS.copy, onclick: () => copyText(msg.content) }),
        ),
      ),
    );
  }
  if (msg.role === "tool") {
    const summary = h("summary", { html: ICONS.chev }, h("span", { class: "t-sum" }, msg.content));
    const d = h("details", {}, summary);
    if (msg.detail) d.append(diffOrPre(msg.detail));
    return h("div", { class: "msg tool" }, d);
  }
  if (msg.role === "error") {
    return h("div", { class: "msg error" }, "⚠ " + msg.content);
  }
  return h("div");
}

function diffOrPre(text) {
  const isDiff = /^--- a\//.test(text);
  if (!isDiff) return h("pre", {}, text);
  const box = h("pre", { class: "diff" });
  for (const line of text.split("\n")) {
    let cls = "";
    if (line.startsWith("+") && !line.startsWith("+++")) cls = "add";
    else if (line.startsWith("-") && !line.startsWith("---")) cls = "del";
    else if (line.startsWith("@@")) cls = "hunk";
    box.append(h("div", { class: cls }, line || " "));
  }
  return box;
}

function typingNode() {
  return h("div", { class: "typing", id: "typing" },
    h("div", { class: "avatar" }, "P"),
    h("div", { class: "status" }, h("span", { class: "dots" }, h("i"), h("i"), h("i")), h("span", { id: "status-text" }, S.status || "생각하는 중...")),
  );
}

const SUGGESTIONS = [
  ["이 작업 폴더 구조 설명해줘", "어떤 파일이 있고 무슨 역할인지"],
  ["/init", "폴더를 분석해 INIT.md 만들기"],
  ["/summarize", "문서를 핵심 위주로 요약"],
  ["/remember", "모든 대화에서 기억할 내용 저장"],
];

function renderMessages() {
  const box = $("#messages");
  box.innerHTML = "";
  const msgs = S.thread ? S.thread.messages : [];
  if (!msgs.length) {
    const sug = h("div", { class: "suggestions" },
      SUGGESTIONS.map(([title, sub]) => h("button", {
        class: "suggestion",
        onclick: () => {
          const input = $("#input");
          input.value = title.startsWith("/") ? title + " " : title;
          autoresize();
          updateSend();
          input.focus();
        },
      }, h("b", {}, title), h("span", {}, sub))));
    const sub = S.workspace.path
      ? `작업 폴더: ${S.workspace.name}` + (S.config.agent_mode ? " · 에이전트 모드 켜짐" : "")
      : "왼쪽 아래에서 작업 폴더를 고르면 파일을 읽고 고치는 에이전트로 일합니다";
    box.append(h("div", { class: "empty" }, h("h1", {}, "무엇을 도와드릴까요?"), h("p", {}, sub), sug));
  } else {
    for (const m of msgs) box.append(messageNode(m));
  }
  if (S.busy && S.busyThread === S.currentId) box.append(typingNode());
  scrollToBottom(true);
}

function appendMessage(msg) {
  const box = $("#messages");
  if (box.querySelector(".empty")) box.innerHTML = "";
  const typing = $("#typing");
  const node = messageNode(msg);
  if (typing) box.insertBefore(node, typing);
  else box.append(node);
  scrollToBottom();
}

function scrollToBottom(force) {
  const sc = $("#scroll");
  const near = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 200;
  if (force || near) requestAnimationFrame(() => (sc.scrollTop = sc.scrollHeight));
}

/* ---------- 입력창 ---------- */
function autoresize() {
  const input = $("#input");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 220) + "px";
}

function updateSend() {
  const btn = $("#btn-send");
  if (S.busy) {
    btn.innerHTML = ICONS.stop;
    btn.title = "중지";
    btn.disabled = false;
  } else {
    btn.innerHTML = ICONS.up;
    btn.title = "보내기";
    btn.disabled = !$("#input").value.trim();
  }
}

function renderWorkspaceChip() {
  const chip = $("#ws-chip");
  const ws = S.workspace;
  const agent = $("#agent-toggle").checked;
  let label;
  if (!ws.path) label = "작업 폴더 선택";
  else label = ws.name + (agent ? "" : " (일반 대화)");
  chip.innerHTML = ICONS.folder;
  chip.append(h("span", {}, label));
  chip.title = ws.path ? `${ws.path}\n클릭해서 바꾸기` : "작업 폴더를 고르면 에이전트가 파일을 다룰 수 있습니다";
}

async function send() {
  if (S.busy) {
    await api().stop();
    S.busy = false;
    S.busyThread = null;
    $("#typing")?.remove();
    updateSend();
    renderSidebar();
    toast("중지했습니다");
    return;
  }
  const input = $("#input");
  const text = input.value.trim();
  if (!text) return;
  if (/^\/help\b/i.test(text)) {
    input.value = "";
    autoresize();
    updateSend();
    return showHelp();
  }
  if (/^\/memory\b/i.test(text)) {
    input.value = "";
    autoresize();
    updateSend();
    return showMemory();
  }
  const remember = text.match(/^\/remember\s+([\s\S]+)/i);
  if (remember) {
    const res = await api().add_memory(remember[1]);
    S.memory = res.memory;
    input.value = "";
    autoresize();
    updateSend();
    return toast(res.ok ? "기억했습니다. 모든 대화에서 참고합니다" : "이미 기억하고 있는 내용입니다");
  }
  hideSlash();
  const res = await api().send(S.currentId, text, $("#agent-toggle").checked);
  if (!res.ok) {
    toast(res.error);
    if (res.need_key) showSettings();
    return;
  }
  input.value = "";
  autoresize();
  S.thread.messages.push(res.message);
  S.thread.title = res.title;
  $("#chat-title").textContent = res.title;
  S.busy = true;
  S.busyThread = S.currentId;
  S.status = "생각하는 중...";
  appendMessage(res.message);
  $("#messages").append(typingNode());
  scrollToBottom(true);
  updateSend();
  refreshThreads();
}

/* 슬래시 명령 메뉴 */
function slashItems(query) {
  const base = [
    { name: "init", description: "작업 폴더를 분석해 INIT.md 만들기" },
    { name: "remember", description: "모든 대화에서 기억할 내용 저장 (/remember 내용)" },
    { name: "memory", description: "기억 목록 보기·지우기" },
    { name: "help", description: "도움말" },
    ...S.skills.map((s) => ({ name: s.name, description: s.description })),
  ];
  const q = query.toLowerCase();
  return base.filter((it) => it.name.toLowerCase().startsWith(q) || (q && it.name.toLowerCase().includes(q)));
}

function updateSlash() {
  const value = $("#input").value;
  const m = value.match(/^\/(\S*)$/);
  if (!m) return hideSlash();
  const items = slashItems(m[1]);
  if (!items.length) return hideSlash();
  S.slash.items = items;
  S.slash.index = Math.min(S.slash.index, items.length - 1);
  const menu = $("#slash-menu");
  menu.innerHTML = "";
  items.forEach((it, i) => {
    menu.append(h("div", {
      class: "slash-item" + (i === S.slash.index ? " sel" : ""),
      onmousedown: (e) => { e.preventDefault(); pickSlash(i); },
    }, h("b", {}, "/" + it.name), h("span", {}, it.description)));
  });
  menu.hidden = false;
}

function hideSlash() {
  $("#slash-menu").hidden = true;
  S.slash.items = [];
  S.slash.index = 0;
}

function pickSlash(i) {
  const it = S.slash.items[i];
  if (!it) return;
  const input = $("#input");
  input.value = "/" + it.name + " ";
  hideSlash();
  updateSend();
  input.focus();
}

/* ---------- 백엔드 이벤트 ---------- */
window.onBackendEvent = (ev) => {
  if (ev.type === "message") {
    if (ev.thread_id === S.currentId && S.thread) {
      S.thread.messages.push(ev.message);
      appendMessage(ev.message);
    }
  } else if (ev.type === "status") {
    S.status = ev.text;
    const st = $("#status-text");
    if (st && ev.thread_id === S.currentId) st.textContent = ev.text;
  } else if (ev.type === "confirm") {
    showConfirm(ev);
  } else if (ev.type === "done") {
    S.busy = false;
    S.busyThread = null;
    $("#typing")?.remove();
    if (ev.workspace) S.workspace = ev.workspace;
    updateSend();
    refreshThreads();
  }
};

/* ---------- 모달 ---------- */
function modal({ title, body, buttons = [], wide = false, onClose }) {
  const root = $("#modal-root");
  const close = (value) => {
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
    onClose && onClose(value);
  };
  const onKey = (e) => { if (e.key === "Escape") close(null); };
  const foot = h("div", { class: "modal-foot" },
    buttons.map((b) => h("button", { class: "btn " + (b.class || ""), onclick: () => (b.action ? b.action(close) : close(b.value)) }, b.label)));
  const box = h("div", { class: "modal" + (wide ? " wide" : "") },
    h("div", { class: "modal-head" }, h("h2", {}, title), h("button", { class: "icon-btn", html: ICONS.close, onclick: () => close(null) })),
    h("div", { class: "modal-body" }, body),
    buttons.length ? foot : null,
  );
  const backdrop = h("div", { class: "modal-backdrop" }, box);
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(null); });
  document.addEventListener("keydown", onKey);
  root.append(backdrop);
  return { close, box };
}

function showConfirm(ev) {
  const isRun = ev.kind === "run";
  const body = h("div", {},
    h("p", { style: "margin:0 0 10px;color:var(--text-2)" },
      isRun ? "에이전트가 작업 폴더에서 다음 명령을 실행하려고 합니다." : "에이전트가 다음과 같이 파일을 바꾸려고 합니다."),
    isRun ? h("pre", { class: "diff" }, h("div", {}, ev.detail)) : diffOrPre(ev.detail),
  );
  let answered = false;
  const answer = (decision) => (close) => {
    answered = true;
    api().resolve_confirm(ev.id, decision);
    close(decision);
  };
  modal({
    title: ev.title,
    body,
    wide: true,
    buttons: [
      { label: "거부", class: "danger", action: answer("deny") },
      { label: isRun ? "이번 실행 동안 명령 모두 허용" : "이번 실행 동안 수정 모두 허용", action: answer("always") },
      { label: "허용", class: "primary", action: answer("allow") },
    ],
    onClose: () => { if (!answered) api().resolve_confirm(ev.id, "deny"); },
  });
}

function showSettings() {
  const c = S.config;
  const keyHint = c.key_source === "settings" ? "저장된 키가 있습니다. 바꾸려면 새 키를 입력하세요."
    : c.key_source === "env" ? "환경 변수 POSTECH_GENAI_API_KEY의 키를 쓰고 있습니다."
    : "API 키가 없습니다.";
  const key = h("input", { type: "password", placeholder: c.key_source ? "••••••••••••" : "API 키 입력", autocomplete: "off" });
  const hist = h("input", { type: "number", min: 0, max: 200, value: c.history_messages });
  const steps = h("input", { type: "number", min: 1, max: 100, value: c.max_steps });
  const perm = h("select", {},
    h("option", { value: "ask" }, "매번 묻기 (권장)"),
    h("option", { value: "auto_edit" }, "파일 수정은 자동 허용, 명령은 묻기"),
    h("option", { value: "auto_all" }, "모두 자동 허용 (주의)"),
  );
  perm.value = c.permission || "ask";
  const body = h("div", {},
    h("div", { class: "field" }, h("label", {}, "POSTECH GenAI API 키"), key,
      h("small", {}, keyHint, h("br"), "키는 이 PC의 사용자 데이터 폴더(config.json)에 저장됩니다.")),
    h("div", { class: "field" }, h("label", {}, "에이전트 권한"), perm,
      h("small", {}, "에이전트가 파일을 고치거나 명령을 실행하기 전에 승인을 받을지 정합니다.")),
    h("div", { class: "row" },
      h("div", { class: "field", style: "flex:1" }, h("label", {}, "기억할 이전 메시지 수"), hist),
      h("div", { class: "field", style: "flex:1" }, h("label", {}, "에이전트 최대 단계 수"), steps)),
    h("div", { class: "field" }, h("label", {}, "데이터 폴더"),
      h("div", { class: "row" }, h("small", { style: "flex:1;margin:0;word-break:break-all" }, S.dataDir),
        h("button", { class: "btn", onclick: () => api().open_folder("data") }, "열기"))),
  );
  body.append(h("p", { style: "margin:14px 0 0;color:var(--text-3);font-size:12px" }, `POSTECH GenAI Chat 버전 ${S.version}`));
  modal({
    title: "설정",
    body,
    buttons: [
      { label: "취소", value: null },
      {
        label: "저장", class: "primary", action: async (close) => {
          const state = await api().save_settings({
            api_key: key.value.trim(), history_messages: hist.value, max_steps: steps.value, permission: perm.value,
          });
          applyState(state);
          close();
          toast("설정을 저장했습니다");
        },
      },
    ],
  });
  setTimeout(() => key.focus(), 50);
}

function showMemory() {
  const list = h("div", {});
  const render = () => {
    list.innerHTML = "";
    if (!S.memory.length) {
      list.append(h("p", { style: "color:var(--text-3);margin:6px 0" }, "아직 기억한 내용이 없습니다."));
    }
    for (const m of S.memory) {
      list.append(h("div", { class: "skill-item" },
        h("div", { class: "s-main" }, h("p", { style: "margin:0;color:var(--text)" }, m.text)),
        h("button", {
          class: "icon-btn", title: "지우기", html: ICONS.trash,
          onclick: async () => { S.memory = await api().delete_memory(m.id); render(); },
        }),
      ));
    }
  };
  render();
  const input = h("input", { placeholder: "예: 답변은 항상 존댓말로, 핵심부터 짧게" });
  const add = async () => {
    if (!input.value.trim()) return;
    const res = await api().add_memory(input.value.trim());
    S.memory = res.memory;
    input.value = "";
    render();
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) add(); });
  const share = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  share.checked = S.config.share_threads !== false;
  share.addEventListener("change", async () => {
    applyState(await api().save_settings({ share_threads: share.checked }));
    toast(share.checked ? "다른 대화 참고를 켰습니다" : "다른 대화 참고를 껐습니다");
  });
  const body = h("div", {},
    h("p", { style: "margin:0 0 8px;color:var(--text-2)" },
      "여기 있는 내용은 모든 대화에 함께 전달됩니다. 대화 중에 \"~를 기억해 줘\", \"잊지 마\"라고 하면 자동으로 추가되고, /remember 내용 으로도 추가할 수 있습니다."),
    list,
    h("div", { class: "field" }, h("label", {}, "새로 기억할 내용"),
      h("div", { class: "row" }, input, h("button", { class: "btn primary", onclick: add }, "추가"))),
    h("div", { class: "field" },
      h("label", { style: "display:flex;align-items:center;font-weight:600;cursor:pointer" }, share, "다른 대화 내용 참고"),
      h("small", {}, "새 질문과 관련된 내용이 다른 대화에 있으면 찾아서 함께 참고합니다. 참고한 대화는 답변 위에 📎로 표시됩니다. ",
        "에이전트 모드에서는 \"지난번에 얘기한 ...\"처럼 말하면 다른 대화를 직접 검색합니다.")),
  );
  modal({ title: "메모리", body, buttons: [{ label: "닫기", class: "primary" }] });
  setTimeout(() => input.focus(), 50);
}

function showSkills() {
  const list = h("div", {});
  const render = () => {
    list.innerHTML = "";
    if (!S.skills.length) list.append(h("p", { style: "color:var(--text-3)" }, "등록된 스킬이 없습니다."));
    for (const s of S.skills) {
      list.append(h("div", { class: "skill-item", title: s.path },
        h("div", { class: "s-main" }, h("b", {}, "/" + s.name), h("span", { class: "badge" }, s.source), h("p", {}, s.description)),
        h("button", { class: "btn", onclick: () => { m.close(); $("#input").value = `/${s.name} `; updateSend(); $("#input").focus(); } }, "사용"),
      ));
    }
  };
  render();
  const name = h("input", { placeholder: "새 스킬 이름 (예: meeting-notes)" });
  const body = h("div", {},
    h("p", { style: "margin:0 0 8px;color:var(--text-2)" },
      "스킬은 SKILL.md 지침 파일입니다. 에이전트가 요청에 맞는 스킬을 스스로 불러오고, /스킬이름 으로 직접 실행할 수도 있습니다."),
    list,
    h("div", { class: "field" }, h("label", {}, "새 스킬 만들기"),
      h("div", { class: "row" }, name, h("button", {
        class: "btn primary", onclick: async () => {
          if (!name.value.trim()) return;
          const res = await api().create_skill(name.value.trim());
          if (!res.ok) return toast(res.error);
          S.skills = res.skills;
          name.value = "";
          render();
          toast("SKILL.md 템플릿을 열었습니다. 내용을 채워 저장하세요");
        },
      }, "만들기")),
      h("small", {}, "사용자 스킬 폴더에 템플릿이 만들어지고 메모장 등으로 열립니다. 작업 폴더의 skills\\ 폴더에 둔 스킬은 그 폴더에서만 쓰입니다.")),
  );
  const m = modal({
    title: "스킬",
    body,
    buttons: [
      { label: "스킬 폴더 열기", action: () => api().open_folder("skills") },
      { label: "닫기", class: "primary", value: null },
    ],
  });
}

function showHelp() {
  const rows = [
    ["/init", "작업 폴더를 분석해 INIT.md를 만듭니다"],
    ["/remember 내용", "모든 대화에서 기억할 내용을 저장합니다"],
    ["/memory", "기억 목록을 보고 지웁니다"],
    ["/스킬이름 요청", "해당 스킬 지침을 적용해 요청을 수행합니다"],
    ["/help", "이 도움말"],
    ["Enter / Shift+Enter", "보내기 / 줄바꿈"],
  ];
  const body = h("div", {},
    h("table", { class: "help-table" }, rows.map(([a, b]) => h("tr", {}, h("td", {}, a), h("td", {}, b)))),
    h("h3", { style: "margin:18px 0 6px;font-size:15px" }, "에이전트 모드"),
    h("p", { style: "margin:0;color:var(--text-2)" },
      "작업 폴더를 고르고 에이전트를 켜면, AI가 파일을 읽고 검색하고 고치고 명령을 실행하면서 목표를 이룰 때까지 단계적으로 일합니다. ",
      "파일 수정과 명령 실행은 설정에 따라 실행 전에 승인을 받습니다."),
    h("h3", { style: "margin:18px 0 6px;font-size:15px" }, "INIT.md와 스킬"),
    h("p", { style: "margin:0;color:var(--text-2)" },
      "작업 폴더 최상위의 INIT.md는 모든 대화에 프로젝트 지침으로 들어갑니다. ",
      "스킬은 <폴더>/SKILL.md 형식의 지침이며 앱 내장, 사용자 스킬 폴더, 작업 폴더의 skills\\ 에서 읽습니다."),
  );
  modal({ title: "도움말", body, buttons: [{ label: "닫기", class: "primary" }] });
}

/* ---------- 초기화 ---------- */
function applyState(state) {
  S.threads = state.threads;
  S.workspace = state.workspace;
  S.skills = state.skills;
  S.config = state.config;
  S.dataDir = state.data_dir;
  S.version = state.version || "";
  S.memory = state.memory || [];
  $("#agent-toggle").checked = !!state.config.agent_mode;
  renderSidebar();
  renderWorkspaceChip();
}

async function chooseWorkspace() {
  const res = await api().choose_workspace();
  S.workspace = res.workspace;
  S.skills = res.skills;
  renderSidebar();
  renderWorkspaceChip();
  if (S.thread && !S.thread.messages.length) renderMessages();
}

function setCollapsed(collapsed) {
  $("#app").classList.toggle("collapsed", collapsed);
  $("#btn-expand").hidden = !collapsed;
  $("#btn-new-top").hidden = !collapsed;
}

function bindUI() {
  document.querySelectorAll("[data-icon]").forEach((el) => {
    el.insertAdjacentHTML("afterbegin", ICONS[el.dataset.icon]);
  });
  const input = $("#input");
  input.addEventListener("input", () => { autoresize(); updateSend(); updateSlash(); });
  input.addEventListener("keydown", (e) => {
    const menuOpen = !$("#slash-menu").hidden;
    if (menuOpen && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      const n = S.slash.items.length;
      S.slash.index = (S.slash.index + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
      updateSlash();
      return;
    }
    if (menuOpen && (e.key === "Tab" || (e.key === "Enter" && !e.isComposing))) {
      e.preventDefault();
      pickSlash(S.slash.index);
      return;
    }
    if (menuOpen && e.key === "Escape") return hideSlash();
    // 한글 조합 중 Enter는 무시해야 마지막 글자가 중복 전송되지 않는다
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      if (!S.busy) send();
    }
  });
  input.addEventListener("blur", () => setTimeout(hideSlash, 100));
  $("#btn-send").addEventListener("click", send);
  $("#btn-new").addEventListener("click", newThread);
  $("#btn-new-top").addEventListener("click", newThread);
  $("#btn-collapse").addEventListener("click", () => setCollapsed(true));
  $("#btn-expand").addEventListener("click", () => setCollapsed(false));
  $("#btn-workspace").addEventListener("click", chooseWorkspace);
  $("#ws-chip").addEventListener("click", chooseWorkspace);
  $("#btn-skills").addEventListener("click", showSkills);
  $("#btn-memory").addEventListener("click", async () => { S.memory = await api().list_memory(); showMemory(); });
  $("#btn-settings").addEventListener("click", showSettings);
  $("#agent-toggle").addEventListener("change", (e) => {
    S.config.agent_mode = e.target.checked;
    api().set_agent_mode(e.target.checked);
    renderWorkspaceChip();
    if (S.thread && !S.thread.messages.length) renderMessages();
  });
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "o") { e.preventDefault(); newThread(); }
  });
}

async function init() {
  bindUI();
  const state = await api().get_state();
  applyState(state);
  S.busy = state.busy;
  if (S.threads.length) await openThread(S.threads[0].id);
  else await newThread();
  updateSend();
  if (!state.config.key_source) showSettings();
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init, { once: true });
