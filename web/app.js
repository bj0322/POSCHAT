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
  plug: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v5"/><path d="M15 2v5"/><path d="M6 7h12v4a6 6 0 0 1-12 0Z"/><path d="M12 17v5"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  clip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m21 11-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6L15 6.6"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><path d="m6.3 6.3 2.1 2.1M15.6 15.6l2.1 2.1M6.3 17.7l2.1-2.1M15.6 8.4l2.1-2.1"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>',
  retry: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>',
};

const REPO_URL = "https://github.com/bj0322/POSCHAT";

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
  attach: [],  // 입력창에 고른 첨부 파일 { id, name, size, kind, status: "uploading"|"ready"|"error", progress, url }
  attachLimits: { max_bytes: 20 * 1024 * 1024, max_files: 10 },
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
// 아주 오래된 WebView(안드로이드)에서는 marked를 불러오지 못할 수 있다. 그때는 서식 없이 글자만 보여 준다.
if (window.marked) marked.setOptions({ gfm: true, breaks: true });

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

if (window.katex && window.marked) {
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
  if (!window.marked) {
    box.style.whiteSpace = "pre-wrap";
    box.textContent = text || "";
    return box;
  }
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
  if (window.poLeave) poLeave();
  const thread = await api().load_thread(id);
  if (!thread) return refreshThreads();
  S.currentId = id;
  S.thread = thread;
  $("#chat-title").textContent = thread.title;
  renderThreadModel();
  renderSidebar();
  renderMessages();
  if (isNarrow()) setCollapsed(true);
  else $("#input").focus();  // 휴대폰에서는 키보드가 화면을 가리지 않게 자동으로 띄우지 않는다
}

function renderThreadModel() {
  const select = $("#thread-model");
  const picker = $("#thread-model-picker");
  if (!select || !picker) return;
  const mode = S.config.api_mode || "chat_completions";
  picker.hidden = !S.thread || mode === "a1";
  if (picker.hidden) return;
  const models = mode === "responses" ? (S.responsesModels || []) : (S.models || []);
  select.replaceChildren(...models.map((m) => h("option", { value: m.id }, m.label)));
  const selected = S.thread.model || S.config.model || (models[0] || {}).id;
  select.value = models.some((m) => m.id === selected) ? selected : ((models[0] || {}).id || "");
  select.disabled = S.busy;
}

async function newThread() {
  // 이미 비어 있는 새 대화가 열려 있으면 그대로 쓴다
  if (S.thread && !S.thread.messages.length) {
    if (window.poLeave) poLeave();
    $("#input").focus();
    return;
  }
  const thread = await api().new_thread();
  S.threads.unshift({ id: thread.id, title: thread.title, updated: thread.updated });
  await openThread(thread.id);
}

function messageNode(msg) {
  if (msg.role === "user") {
    const files = msg.attachments && msg.attachments.length ? attachmentList(msg.attachments) : null;
    return h("div", { class: "msg user" + (files ? " has-files" : "") },
      files,
      msg.content ? h("div", { class: "bubble" }, msg.content) : null);
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

/* ---------- 첨부 파일 ---------- */
const IMAGE_EXT = /\.(png|jpe?g|gif|webp)$/i;
const previewCache = new Map();

function fmtSize(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

/* 보낸 메시지의 첨부 파일: 이미지는 미리보기, 나머지는 이름 칩. 누르면 알맞은 앱으로 연다. */
function attachmentList(items) {
  return h("div", { class: "msg-files" }, items.map((a) => {
    if (a.kind === "image") {
      const img = h("img", { alt: a.name });
      const node = h("button", { class: "file-img", title: a.name, onclick: () => api().open_attachment(a.id) }, img);
      const show = (url) => (url ? (img.src = url) : node.replaceWith(fileChip(a)));
      if (previewCache.has(a.id)) show(previewCache.get(a.id));
      else api().attachment_preview(a.id).then((url) => { previewCache.set(a.id, url); show(url); });
      return node;
    }
    return fileChip(a);
  }));
}

function fileChip(a) {
  return h("button", { class: "file-chip", title: a.name, onclick: () => api().open_attachment(a.id) },
    h("span", { class: "f-icon", html: ICONS.file }),
    h("span", { class: "f-text" }, h("span", { class: "f-name" }, a.name), h("small", {}, fmtSize(a.size))));
}

function newAttachId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function readBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).slice(String(r.result).indexOf(",") + 1));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

/* 파일을 512KB 조각으로 나눠 Python으로 보낸다(큰 문자열 하나를 넘기면 브리지가 느려지거나 멈춘다). */
async function uploadAttachment(file, entry) {
  const CHUNK = 512 * 1024;
  let offset = 0;
  for (;;) {
    const blob = file.slice(offset, offset + CHUNK);
    const last = offset + blob.size >= file.size;
    const res = await api().upload_attachment(entry.id, file.name, offset, await readBase64(blob), last);
    if (!S.attach.includes(entry)) return;  // 올리는 중에 뺐다
    if (!res.ok) throw new Error(res.error);
    offset += blob.size;
    entry.progress = file.size ? offset / file.size : 1;
    renderTray();
    if (last) return res.attachment;
  }
}

function addFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const room = S.attachLimits.max_files - S.attach.length;
  if (files.length > room) toast(`파일은 한 번에 ${S.attachLimits.max_files}개까지 첨부할 수 있습니다`);
  for (const file of files.slice(0, Math.max(room, 0))) {
    if (file.size > S.attachLimits.max_bytes) {
      toast(`'${file.name}'이(가) 너무 큽니다 (${fmtSize(S.attachLimits.max_bytes)} 초과)`);
      continue;
    }
    const entry = {
      id: newAttachId(), name: file.name || "붙여넣은 이미지.png", size: file.size, status: "uploading", progress: 0,
      kind: IMAGE_EXT.test(file.name || ".png") ? "image" : "file",
    };
    if (entry.kind === "image") entry.url = URL.createObjectURL(file);
    S.attach.push(entry);
    uploadAttachment(file.name ? file : new File([file], entry.name, { type: file.type }), entry)
      .then((info) => {
        if (!info) return;
        entry.status = "ready";
        entry.kind = info.kind;
        entry.name = info.name;
      })
      .catch((e) => {
        entry.status = "error";
        entry.error = e.message || String(e);
        toast(entry.error);
      })
      .finally(() => { renderTray(); updateSend(); });
  }
  renderTray();
  updateSend();
}

function removeAttachment(entry) {
  S.attach = S.attach.filter((a) => a !== entry);
  if (entry.url) URL.revokeObjectURL(entry.url);
  api().discard_attachment(entry.id);
  renderTray();
  updateSend();
}

function clearTray() {
  for (const a of S.attach) if (a.url) URL.revokeObjectURL(a.url);
  S.attach = [];
  renderTray();
}

function renderTray() {
  const tray = $("#attach-tray");
  tray.hidden = !S.attach.length;
  tray.replaceChildren(...S.attach.map((a) => {
    const remove = h("button", { class: "t-remove", title: "빼기", html: ICONS.close, onclick: () => removeAttachment(a) });
    const label = a.status === "uploading" ? `올리는 중 ${Math.round(a.progress * 100)}%`
      : a.status === "error" ? "오류 — " + a.error : fmtSize(a.size);
    return h("div", { class: "tray-item " + a.status, title: a.status === "error" ? a.error : a.name },
      a.url ? h("img", { src: a.url, alt: "" }) : h("span", { class: "f-icon", html: ICONS.file }),
      h("span", { class: "f-text" }, h("span", { class: "f-name" }, a.name), h("small", {}, label)),
      remove);
  }));
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
  ["/user", "대화를 바탕으로 내 정보(USER.md) 정리"],
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

/* 스트리밍 중인 답변: 받은 텍스트를 화면 갱신 주기에 맞춰 다시 그린다. 최종 답변이 오면 일반 메시지로 바뀐다. */
const streaming = { text: "", frame: 0 };

function showStreaming(text) {
  streaming.text = text;
  if (streaming.frame) return;
  streaming.frame = requestAnimationFrame(() => {
    streaming.frame = 0;
    let node = $("#streaming");
    if (!node) {
      node = h("div", { class: "msg assistant streaming", id: "streaming" }, h("div", { class: "avatar" }, "P"), h("div", { class: "body" }));
      const typing = $("#typing");
      if (typing) {
        typing.hidden = true;
        $("#messages").insertBefore(node, typing);
      } else {
        $("#messages").append(node);
      }
    }
    node.querySelector(".body").replaceChildren(renderMarkdown(streaming.text));
    scrollToBottom();
  });
}

function endStreaming() {
  if (streaming.frame) cancelAnimationFrame(streaming.frame);
  streaming.frame = 0;
  streaming.text = "";
  $("#streaming")?.remove();
  const typing = $("#typing");
  if (typing) typing.hidden = false;
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
    const uploading = S.attach.some((a) => a.status === "uploading");
    btn.title = uploading ? "파일을 올리는 중입니다" : "보내기";
    btn.disabled = uploading || !($("#input").value.trim() || S.attach.some((a) => a.status === "ready"));
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
  const ready = S.attach.filter((a) => a.status === "ready");
  if (S.attach.some((a) => a.status === "uploading")) return toast("파일을 올리는 중입니다");
  if (!text && !ready.length) return;
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
  const res = await api().send(S.currentId, text, $("#agent-toggle").checked, ready.map((a) => a.id));
  if (!res.ok) {
    toast(res.error);
    if (res.need_key) showSettings();
    return;
  }
  for (const a of ready) if (a.url && a.kind === "image") previewCache.delete(a.id);
  S.attach = S.attach.filter((a) => !ready.includes(a));  // 오류 난 파일은 남겨 두어 사용자가 보고 뺀다
  renderTray();
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
    { name: "user", description: "지금까지의 대화로 내 정보(USER.md) 작성·업데이트" },
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
      if (ev.message.role === "assistant") endStreaming();
      S.thread.messages.push(ev.message);
      appendMessage(ev.message);
    }
  } else if (ev.type === "delta") {
    if (ev.thread_id === S.currentId && S.thread) showStreaming(ev.text);
  } else if (ev.type === "status") {
    S.status = ev.text;
    const st = $("#status-text");
    if (st && ev.thread_id === S.currentId) st.textContent = ev.text;
  } else if (ev.type === "confirm") {
    showConfirm(ev);
  } else if (ev.type === "po") {
    if (window.poEvent) poEvent(ev);
  } else if (ev.type === "update") {
    updateEvent(ev);
  } else if (ev.type === "credit") {
    S.credit = ev.credit;
    document.querySelectorAll("[data-credit]").forEach((el) => { el.textContent = creditText(S.credit); });
  } else if (ev.type === "done") {
    S.busy = false;
    S.busyThread = null;
    endStreaming();
    $("#typing")?.remove();
    if (ev.workspace) S.workspace = ev.workspace;
    updateSend();
    refreshThreads();
  }
};

/* ---------- 크레딧 ---------- */
// POSTECH GenAI는 응답 헤더로 이번 주기(WEEKLY 등)의 크레딧 사용량과 한도를 알려 준다.
const INTERVALS = { WEEKLY: "이번 주", DAILY: "오늘", MONTHLY: "이번 달" };

function creditText(c) {
  if (!c || c.usage == null) return "아직 확인하지 않았습니다";
  const used = Math.round(c.usage).toLocaleString();
  const when = INTERVALS[(c.interval || "").toUpperCase()] || "현재 주기";
  if (!c.limit) return `${when} ${used} 크레딧 사용`;
  const left = Math.max(0, Math.round(c.limit - c.usage)).toLocaleString();
  return `${when} ${used} / ${Math.round(c.limit).toLocaleString()} 크레딧 사용 · 남은 ${left} (${Math.round(c.usage / c.limit * 100)}%)`;
}

/* 크레딧 표시 줄. 처음 그릴 때와 '확인'을 누를 때 크레딧을 쓰지 않는 요청으로 새로 받는다. */
function creditLine(auto = true) {
  const text = h("span", { "data-credit": "", style: "flex:1" }, creditText(S.credit));
  const refresh = async () => {
    btn.disabled = true;
    try {
      const res = await api().get_credit();
      if (res.ok === false) text.textContent = res.error;
      else {
        S.credit = res;
        document.querySelectorAll("[data-credit]").forEach((el) => { el.textContent = creditText(S.credit); });
      }
    } finally {
      btn.disabled = false;
    }
  };
  const btn = h("button", { class: "btn", type: "button", onclick: refresh }, "확인");
  // 화면을 다시 그릴 때마다 묻지 않도록 1분에 한 번만 저절로 확인한다
  if (auto && S.config.key_source && Date.now() - (S.creditAt || 0) > 60000) {
    S.creditAt = Date.now();
    setTimeout(refresh, 0);
  }
  return h("div", { class: "row credit-line" }, text, btn);
}

/* ---------- 모달 ---------- */
function modal({ title, body, buttons = [], wide = false, onClose }) {
  if (isNarrow()) setCollapsed(true);  // 휴대폰: 사이드바 서랍에서 연 창이면 서랍을 닫는다
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
  const notionHint = c.notion_source === "settings" ? "저장된 토큰이 있습니다. 바꾸려면 새 토큰을 입력하세요."
    : c.notion_source === "env" ? "환경 변수 NOTION_TOKEN의 토큰을 쓰고 있습니다."
    : "notion MCP 서버를 쓸 때만 필요합니다.";
  const notion = h("input", { type: "password", placeholder: c.notion_source ? "••••••••••••" : "ntn_... (선택)", autocomplete: "off" });
  const clearNotion = h("input", { type: "checkbox", style: "width:auto;margin:0 6px 0 0" });
  const fcHint = c.firecrawl_source === "settings" ? "저장된 키가 있습니다. 바꾸려면 새 키를 입력하세요."
    : c.firecrawl_source === "env" ? "환경 변수 FIRECRAWL_API_KEY의 키를 쓰고 있습니다."
    : "firecrawl MCP 서버를 쓸 때만 필요합니다.";
  const firecrawl = h("input", { type: "password", placeholder: c.firecrawl_source ? "••••••••••••" : "fc-... (선택)", autocomplete: "off" });
  const clearFirecrawl = h("input", { type: "checkbox", style: "width:auto;margin:0 6px 0 0" });
  const fmt = (n) => n >= 10000 ? (n / 10000).toFixed(n >= 100000 ? 0 : 1) + "만" : n.toLocaleString();
  const usageLine = (label, u) => h("div", { class: "row", style: "justify-content:space-between;font-size:13px;margin:2px 0" },
    h("span", {}, label),
    h("span", {}, `${u.calls.toLocaleString()}회` + (u.token_calls
      ? ` · 토큰 입력 ${fmt(u.input_tokens)} / 출력 ${fmt(u.output_tokens)}` + (u.token_calls < u.calls ? ` (${u.token_calls}회분)` : "")
      : "")));
  const usageBox = h("div", {}, h("small", {}, "불러오는 중..."));
  api().get_usage().then((u) => {
    usageBox.replaceChildren(usageLine("오늘", u.today), usageLine(`이번 달 (${u.month_name})`, u.month),
      usageLine("최근 30일", u.last30));
  }).catch(() => usageBox.replaceChildren(h("small", {}, "사용량을 불러오지 못했습니다.")));
  const hist = h("input", { type: "number", min: 0, max: 200, value: c.history_messages });
  const steps = h("input", { type: "number", min: 1, max: 100, value: c.max_steps });
  const perm = h("select", {},
    h("option", { value: "ask" }, "매번 묻기 (권장)"),
    h("option", { value: "auto_edit" }, "파일 수정은 자동 허용, 명령은 묻기"),
    h("option", { value: "auto_all" }, "모두 자동 허용 (주의)"),
  );
  perm.value = c.permission || "ask";
  const mode = h("select", {},
    h("option", { value: "chat_completions" }, "OpenAI 호환 API — GPT·Claude·Gemini (권장)"),
    h("option", { value: "responses" }, "OpenAI Responses API — GPT-5 계열"),
    h("option", { value: "a1" }, "a1/gpt 단일 호출 (예전 기본값, 모델은 서버가 정함)"),
  );
  mode.value = c.api_mode || "chat_completions";
  const url = h("input", { type: "url", placeholder: "https://.../agent/api/a번호/openai/responses", value: c.responses_url || "" });
  const compatibleUrl = h("input", { type: "url", placeholder: S.defaultChatUrl || "https://.../v1/chat/completions",
    value: c.chat_completions_url || "" });
  const responsesModels = S.responsesModels || [];
  const responsesModel = h("select", {}, responsesModels.map((m) => h("option", { value: m.id }, m.label)));
  const compatibleModel = h("select", {});
  const fillCompatible = (models, selected) => {
    compatibleModel.replaceChildren(...models.map((m) => h("option", { value: m.id }, m.label)));
    compatibleModel.value = models.some((m) => m.id === selected) ? selected : ((models[0] || {}).id || "");
  };
  const defaultModel = c.model || ((S.models || [])[0] || {}).id || "";
  responsesModel.value = responsesModels.some((m) => m.id === defaultModel)
    ? defaultModel : ((responsesModels[0] || {}).id || "");
  fillCompatible(S.models || [], defaultModel);
  const modelsHint = h("small", {}, S.modelsSource === "server"
    ? "서버에서 받은 모델 목록입니다."
    : "기본 목록입니다. 다른 OpenAI 호환 서버를 쓴다면 '모델 목록 불러오기'로 그 서버의 모델로 바꿉니다(POSTECH 서버는 목록을 알려 주지 않습니다).");
  // 불러온 목록은 저장을 눌러야 반영한다(취소하면 버린다). 주소를 다시 고치면 그 목록도 버린다.
  let serverModels = null;
  compatibleUrl.addEventListener("input", () => {
    if (!serverModels) return;
    serverModels = null;
    fillCompatible(S.models || [], compatibleModel.value);
    modelsHint.textContent = "주소를 바꿨으므로 저장하면 기본 목록을 씁니다.";
  });
  const loadModels = h("button", { class: "btn", type: "button", style: "margin-top:8px", onclick: async () => {
    loadModels.disabled = true;
    try {
      const result = await api().refresh_models({ api_key: key.value.trim(), chat_completions_url: compatibleUrl.value.trim() });
      if (result.ok === false) return toast(result.error);
      if (compatibleUrl.value.trim()) compatibleUrl.value = result.chat_completions_url;
      serverModels = result.models.map((m) => m.id);
      fillCompatible(result.models, compatibleModel.value);
      modelsHint.textContent = `서버에서 받은 모델 목록입니다 (${result.models.length}개). 저장하면 반영됩니다.`;
    } catch (error) {
      toast(`모델 목록을 불러오지 못했습니다: ${error.message || error}`);
    } finally {
      loadModels.disabled = false;
    }
  } }, "모델 목록 불러오기");
  const stream = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  stream.checked = c.stream !== false;
  const autoUpdate = h("input", { type: "checkbox", style: "width:auto;margin:0 8px 0 0" });
  autoUpdate.checked = c.update_check !== false;
  const responsesBox = h("div", {},
    h("div", { class: "field" }, h("label", {}, "Responses API 주소 (필수)"), url,
      h("small", {}, "필수 입력. POSTECH GenAI 콘솔에서 openai/responses로 끝나는 전체 HTTPS 주소를 복사하세요.")),
    h("div", { class: "field" }, h("label", {}, "모델"), responsesModel,
      h("small", {}, "GPT-5.1을 권장합니다. 에이전트는 단계마다 모델을 부르므로 비용을 줄이려면 GPT-5 mini를 고르세요.")),
  );
  const compatibleBox = h("div", {},
    h("div", { class: "field" }, h("label", {}, "OpenAI 호환 API 주소"), compatibleUrl,
      h("small", {}, "비워 두면 POSTECH GenAI 콘솔(에이전트 API → OpenAI Compatible API)의 주소를 씁니다. ",
        "다른 서버를 쓸 때만 넣으세요. 기본 주소(Base URL, 예: .../v1)만 넣어도 /chat/completions를 자동으로 붙입니다.")),
    h("div", { class: "field" }, h("label", {}, "기본 모델"), compatibleModel, modelsHint, loadModels,
      h("small", {}, "새 대화의 기본 모델입니다. 기존 대화의 모델은 대화 상단에서 개별 선택하며 각각 저장됩니다.")),
  );
  const syncMode = () => {
    responsesBox.hidden = mode.value !== "responses";
    compatibleBox.hidden = mode.value !== "chat_completions";
    url.required = mode.value === "responses";
  };
  mode.addEventListener("change", syncMode);
  syncMode();
  const body = h("div", {},
    h("div", { class: "row guide-link" },
      h("span", { style: "flex:1" }, "처음 쓰거나 기능이 궁금하면 사용법 가이드를 보세요."),
      h("button", { class: "btn", onclick: showGuide }, "사용법 가이드")),
    h("div", { class: "field" }, h("label", {}, "POSTECH GenAI API 키"), key,
      h("small", {}, keyHint, h("br"), "키는 이 PC의 사용자 데이터 폴더(config.json)에 저장됩니다.")),
    h("div", { class: "field" }, h("label", {}, "API 방식"), mode),
    responsesBox,
    compatibleBox,
    h("div", { class: "field" },
      h("label", { style: "display:flex;align-items:center;font-weight:600;cursor:pointer" }, stream, "답변을 받는 대로 표시 (스트리밍)"),
      h("small", {}, "일반 대화의 답변을 글자가 오는 대로 보여 줍니다. 에이전트 모드의 단계 진행은 그대로입니다.")),
    h("div", { class: "field" }, h("label", {}, "Notion 통합 토큰"), notion,
      h("small", {}, notionHint, " notion.so/profile/integrations에서 내부 통합을 만들어 토큰을 받고, ",
        "쓸 페이지의 ··· → 연결에서 그 통합을 추가하세요."),
      c.notion_source === "settings"
        ? h("label", { style: "display:flex;align-items:center;font-size:13px;margin-top:4px;cursor:pointer" }, clearNotion, "저장된 토큰 지우기")
        : null),
    h("div", { class: "field" }, h("label", {}, "Firecrawl API 키"), firecrawl,
      h("small", {}, fcHint, " firecrawl.dev에서 무료로 가입하면 키와 무료 크레딧을 받습니다."),
      c.firecrawl_source === "settings"
        ? h("label", { style: "display:flex;align-items:center;font-size:13px;margin-top:4px;cursor:pointer" }, clearFirecrawl, "저장된 키 지우기")
        : null),
    h("div", { class: "field" }, h("label", {}, "업데이트"),
      h("label", { style: "display:flex;align-items:center;font-weight:400;cursor:pointer" }, autoUpdate, "시작할 때 새 버전 확인"),
      h("div", { class: "row", style: "margin-top:6px" },
        h("small", { style: "flex:1;margin:0" }, `지금 버전 ${S.version}. 새 버전은 GitHub Releases에서 받아 설치합니다.`),
        h("button", { class: "btn", type: "button", onclick: async (e) => {
          e.target.disabled = true;
          try {
            const result = await api().check_for_updates(true);
            if (result.available) offerUpdate(result);
            else toast(result.error || `최신 버전(${S.version})을 쓰고 있습니다`);
          } finally {
            e.target.disabled = false;
          }
        } }, "업데이트 확인"))),
    h("div", { class: "field" }, h("label", {}, "에이전트 권한"), perm,
      h("small", {}, "에이전트가 파일을 고치거나 명령을 실행하기 전에 승인을 받을지 정합니다.")),
    h("div", { class: "row" },
      h("div", { class: "field", style: "flex:1" }, h("label", {}, "기억할 이전 메시지 수"), hist),
      h("div", { class: "field", style: "flex:1" }, h("label", {}, "에이전트 최대 단계 수"), steps)),
    h("div", { class: "field" }, h("label", {}, "POSTECH GenAI 크레딧"), creditLine(),
      h("small", {}, "POSTECH GenAI가 응답에 담아 주는 이 키의 크레딧 사용량과 한도입니다. 확인 자체는 크레딧을 쓰지 않습니다. ",
        "Claude Sonnet 5.5 기준 1크레딧은 입력 약 250토큰·출력 약 75토큰이고, 호출마다 기본 약 24크레딧이 듭니다(Opus는 두 배).")),
    h("div", { class: "field" }, h("label", {}, "모델 API 사용량 (이 앱에서 보낸 요청)"),
      usageBox,
      h("small", {}, "토큰 수는 서버가 응답에 사용량을 담아 준 요청만 셉니다.")),
    h("div", { class: "field" }, h("label", {}, "데이터 폴더"),
      h("div", { class: "row" }, h("small", { style: "flex:1;margin:0;word-break:break-all" }, S.dataDir),
        h("button", { class: "btn", onclick: () => api().open_folder("data") }, "열기"))),
  );
  body.append(h("p", { style: "margin:14px 0 0;color:var(--text-3);font-size:12px" }, `POSTECH GenAI Chat 버전 ${S.version}`),
    h("p", { style: "margin:2px 0 0;color:var(--text-3);font-size:12px" }, "서비스 대표자: 김범준"),
    h("p", { style: "margin:2px 0 0;color:var(--text-3);font-size:12px" }, "문의사항은 ",
      h("a", { href: REPO_URL, target: "_blank", style: "color:inherit" }, REPO_URL), "의 문의 메일로 보내 주세요."));
  modal({
    title: "설정",
    body,
    buttons: [
      { label: "취소", value: null },
      {
        label: "저장", class: "primary", action: async (close) => {
          if (mode.value === "responses" && !url.value.trim()) {
            url.focus();
            return toast("Responses API 주소를 입력하세요.");
          }
          const state = await api().save_settings({
            api_key: key.value.trim(), history_messages: hist.value, max_steps: steps.value, permission: perm.value,
            api_mode: mode.value, responses_url: url.value.trim(),
            chat_completions_url: compatibleUrl.value.trim(), server_models: serverModels,
            model: mode.value === "responses" ? responsesModel.value : compatibleModel.value, stream: stream.checked,
            update_check: autoUpdate.checked,
            notion_token: notion.value.trim(), clear_notion: clearNotion.checked && !notion.value.trim(),
            firecrawl_key: firecrawl.value.trim(), clear_firecrawl: clearFirecrawl.checked && !firecrawl.value.trim(),
          });
          if (state.ok === false) return toast(state.error);
          applyState(state);
          close();
          toast("설정을 저장했습니다");
        },
      },
    ],
  });
  setTimeout(() => key.focus(), 50);
}

/* ---------- 업데이트 ---------- */
const UPD = { modal: null, bar: null, text: null };

function offerUpdate(update, attempts = 0) {
  // 다른 창(설정 등)이 열려 있으면 닫힐 때까지 기다렸다가 연다
  if ($("#modal-root .modal") && !$("#modal-root .modal .update-notes")) {
    if (attempts < 120) setTimeout(() => offerUpdate(update, attempts + 1), 500);
    return;
  }
  const body = h("div", {},
    h("p", { style: "margin:0 0 10px" }, `새 버전 ${update.version}을 쓸 수 있습니다. 지금 버전은 ${update.current || S.version}입니다.`),
    update.notes ? h("div", { class: "update-notes" }, renderMarkdown(update.notes)) : null,
    h("small", { style: "display:block;margin-top:10px;color:var(--text-3)" },
      update.can_install ? "GitHub Releases에서 설치 파일을 받아 크기·SHA-256을 확인한 뒤 설치를 시작합니다. 대화·설정은 그대로 남습니다."
        : "이 기기에서는 자동으로 설치할 수 없습니다. Releases 페이지에서 받아 설치하세요."));
  modal({
    title: "업데이트",
    body,
    buttons: [
      { label: "이 버전 건너뛰기", action: (close) => { api().skip_update(update.version); close(); } },
      { label: "나중에", value: null },
      update.can_install
        ? { label: "업데이트", class: "primary", action: (close) => { close(); startUpdate(update); } }
        : { label: "Releases 열기", class: "primary", action: (close) => { api().open_release_page(); close(); } },
    ],
  });
}

async function startUpdate(update) {
  UPD.bar = h("i", { style: "width:0%" });
  UPD.text = h("p", { style: "margin:0 0 10px;color:var(--text-2)" }, `${update.version} 설치 파일을 내려받는 중…`);
  UPD.modal = modal({ title: "업데이트", body: h("div", {}, UPD.text, h("div", { class: "po-meter po-progress" }, UPD.bar)),
    onClose: () => { UPD.modal = null; } });
  const res = await api().download_update();
  if (res.ok === false) {
    UPD.modal?.close();
    toast(res.error);
  }
}

function updateEvent(ev) {
  if (ev.kind === "progress") {
    if (UPD.bar) UPD.bar.style.width = `${Math.round(ev.done / ev.total * 100)}%`;
    if (UPD.text) UPD.text.textContent = `설치 파일을 내려받는 중… ${fmtSize(ev.done)} / ${fmtSize(ev.total)}`;
  } else if (ev.kind === "installing" || ev.kind === "opened") {
    if (UPD.text) UPD.text.textContent = ev.message;
    if (UPD.bar) UPD.bar.style.width = "100%";
    if (ev.kind === "opened") setTimeout(() => UPD.modal?.close(), 6000);
  } else if (ev.kind === "error") {
    UPD.modal?.close();
    toast(`업데이트하지 못했습니다: ${ev.error}`);
  }
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
  const m = modal({
    title: "메모리",
    body,
    buttons: [
      { label: "memory.md 편집", action: () => { m.close(); showNoteEditor("memory"); } },
      { label: "닫기", class: "primary" },
    ],
  });
  setTimeout(() => input.focus(), 50);
}

/* memory.md·USER.md를 앱 안에서 고친다. 휴대폰에서도 같은 방법으로 고칠 수 있다. */
const NOTES = {
  memory: {
    title: "메모리 (memory.md)",
    desc: "\"- \"로 시작하는 줄 하나가 기억 하나입니다. 제목이나 설명을 더 써도 모두 대화에 전달되고, <!-- --> 안의 안내문만 빠집니다.",
  },
  profile: {
    title: "내 정보 (USER.md)",
    desc: "나에 대한 정보입니다. 모든 대화에 함께 전달되어 답변을 나에게 맞추는 데 쓰입니다. " +
      "직접 쓰거나, 아래 'AI로 작성·업데이트'를 누르면 지금까지의 대화를 바탕으로 AI가 정리합니다(/user).",
  },
};

async function showNoteEditor(kind) {
  const note = await api().read_note(kind);
  const info = NOTES[kind];
  const area = h("textarea", { class: "note-editor", spellcheck: "false" });
  area.value = note.text;
  const body = h("div", {},
    h("p", { style: "margin:0 0 8px;color:var(--text-2)" }, info.desc),
    area,
    h("small", { style: "display:block;margin-top:6px;color:var(--text-3);word-break:break-all" }, note.path));
  const save = async () => {
    const res = await api().save_note(kind, area.value);
    S.memory = res.memory;
    toast("저장했습니다");
  };
  const buttons = [{ label: "파일 열기", action: async () => { await save(); api().open_note(kind); } }];
  if (kind === "profile") {
    buttons.push({
      label: "AI로 작성·업데이트", action: async (close) => {
        if (area.value !== note.text) await save();
        close();
        if (S.busy) return toast("이전 응답을 기다리는 중입니다");
        const input = $("#input");
        const draft = input.value;  // 쓰던 글은 /user를 보낸 뒤 되돌려 놓는다
        input.value = "/user";
        await send();
        input.value = draft;
        autoresize();
        updateSend();
      },
    });
  }
  buttons.push({ label: "취소", value: null });
  buttons.push({ label: "저장", class: "primary", action: async (close) => { await save(); close(); } });
  modal({ title: info.title, body, wide: true, buttons });
  setTimeout(() => { area.focus(); area.setSelectionRange(0, 0); area.scrollTop = 0; }, 50);
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

function showMcp() {
  const list = h("div", {});
  const note = h("p", { style: "margin:6px 0 0;color:var(--text-3);font-size:13px" });
  const STATE = { connected: "연결됨", error: "연결 실패", idle: "대기" };
  const render = (st) => {
    list.innerHTML = "";
    note.textContent = st.config_error || "";
    for (const sv of st.servers) {
      const toggle = h("input", { type: "checkbox", style: "width:auto;margin:0", title: sv.enabled ? "끄기" : "켜기" });
      toggle.checked = sv.enabled;
      toggle.addEventListener("change", async () => render(await api().set_mcp_enabled(sv.name, toggle.checked)));
      const detail = sv.state === "connected" ? "도구: " + sv.tools.join(", ")
        : sv.error ? sv.error : (sv.command || sv.description);
      list.append(h("div", { class: "skill-item" },
        toggle,
        h("div", { class: "s-main" },
          h("b", {}, sv.name),
          h("span", { class: "badge" }, sv.builtin ? "내장" : sv.preset ? "추천" : "외부"),
          sv.enabled ? h("span", { class: "badge mcp-" + sv.state }, STATE[sv.state] || sv.state) : null,
          h("p", {}, sv.description || ""),
          detail && detail !== sv.description ? h("p", { class: sv.error ? "mcp-error" : "" }, detail) : null),
      ));
    }
  };
  const body = h("div", {},
    h("p", { style: "margin:0 0 8px;color:var(--text-2)" },
      "MCP 서버는 에이전트가 쓸 수 있는 도구를 더해 줍니다. 내장 서버로 Word·PowerPoint·Excel 문서를 만들고 고치고, ",
      "논문을 찾아 읽고(paper), Notion 페이지를 다루고(notion, 설정에 토큰 필요), ",
      "웹페이지를 읽고 검색할 수 있습니다(firecrawl, 설정에 키 필요). 파일은 작업 폴더 안의 것만 다룹니다. ",
      "추천 서버(playwright: 브라우저 자동화)는 PC에 Node.js가 있으면 켜서 씁니다. ",
      "다른 MCP 서버는 설정 파일(mcp.json)에 Claude Desktop과 같은 형식으로 추가합니다."),
    list, note,
    h("small", { style: "display:block;margin-top:10px;color:var(--text-3)" },
      "서버는 에이전트 모드에서 처음 필요할 때 연결됩니다. 작업 폴더의 파일을 고치는 도구는 파일 수정처럼, ",
      "외부 서버의 도구와 Notion에 쓰기·브라우저 조작처럼 바깥에 영향을 주는 도구는 명령 실행처럼 승인을 받습니다."),
  );
  const m = modal({
    title: "MCP",
    body,
    wide: true,
    buttons: [
      { label: "설정 파일 열기", action: () => api().open_mcp_config() },
      { label: "지금 연결", action: async () => {
        if (!S.workspace.path) return toast("먼저 작업 폴더를 선택하세요");
        toast("MCP 서버에 연결하는 중...");
        render(await api().connect_mcp());
      } },
      { label: "닫기", class: "primary", value: null },
    ],
  });
  api().get_mcp().then(render);
  return m;
}

/* ---------- 사용법 가이드 (설정 → 사용법 가이드) ---------- */
const GUIDE = [
  ["처음 시작하기", `
1. **설정 → POSTECH GenAI API 키**에 본인의 키를 넣고 저장합니다.
2. 입력창에 질문을 쓰고 **Enter**로 보냅니다(줄바꿈은 Shift+Enter).
3. 파일을 다루게 하려면 왼쪽 아래 **작업 폴더**를 고르고 오른쪽 위 **에이전트** 스위치를 켭니다.

새 대화는 왼쪽 위 **새 채팅**(Ctrl+Shift+O, 맥은 ⌘+Shift+O)으로 만들고, 대화 목록에 마우스를 올리면 이름 바꾸기·삭제 아이콘이 나옵니다.`],
  ["모델과 API 방식", `
**설정 → API 방식**에서 고릅니다.

- **OpenAI 호환 API (권장, 기본)**: 주소를 비워 두면 POSTECH GenAI 콘솔의 OpenAI Compatible API 주소를 씁니다. GPT·Claude·Gemini 모델을 고릅니다.
- **OpenAI Responses API**: 콘솔의 \`.../a번호/openai/responses\` 주소를 넣고 GPT-5 계열 모델을 고릅니다.
- **a1/gpt 단일 호출**: 예전 기본값입니다. 모델은 서버가 정합니다.
- OpenAI 호환 또는 Responses 방식에서는 화면 위쪽 메뉴에서 대화별 모델을 지정합니다.

**답변을 받는 대로 표시(스트리밍)**를 켜면 일반 대화의 답변이 글자가 오는 대로 나옵니다. 표시가 이상하면 끄세요.`],
  ["크레딧 확인", `
**설정 → POSTECH GenAI 크레딧**에서 이 키의 이번 주 크레딧 사용량·한도·남은 양을 봅니다. **확인**을 눌러도 크레딧은 줄지 않습니다. PO노트 화면 위쪽에도 같은 내용이 나옵니다.

Claude Sonnet 5.5 기준으로 1크레딧은 입력 약 250토큰, 출력 약 75토큰이고, 짧은 질문도 호출마다 약 24크레딧이 듭니다. Opus 5.5는 두 배입니다. 에이전트 모드는 단계마다 한 번씩 호출하므로 단계가 많을수록 크레딧을 많이 씁니다.`],
  ["PO노트: 강의 녹음·필기 노트", `
왼쪽 위 **PO노트**에서 강의마다 노트를 만듭니다.

1. **새 강의 노트**를 만들고 **강의 자료**(PPT·PDF·Word·한글 등)를 올립니다.
2. **녹음 시작**을 누르면 마이크 소리를 실시간으로 받아 적습니다(**전사** 탭). 강의 중 떠오른 질문은 **메모** 탭에 적어 둡니다.
3. 녹음을 멈춘 뒤 **노트 만들기**를 누르면 강의 자료의 순서에 맞춰 전사·메모를 정리한 Markdown 필기 노트(**노트** 탭)를 만듭니다. 노트는 앱 안에서 고칠 수 있습니다.

**음성 인식 설정**에서 받아 적는 방식을 고릅니다.

- **자동(기본, 권장)**: 로컬 AI가 바로 받아 적고, 약 2분치 구간 가운데 로컬 AI가 확신하지 못한 구간(흐리게 보이는 줄)이 있을 때만 POSTECH GenAI(Gemini 3.8 Flash)가 음성과 대조해 고칩니다. 1시간에 0~약 420크레딧입니다. 처음 녹음할 때 로컬 모델(한국어 약 76MB)을 내려받습니다.
- **POSTECH 서버로 모두**: 1시간에 약 1,000~1,300크레딧입니다.
- **로컬 AI만**: 크레딧·인터넷이 필요 없고 CPU를 조금만 씁니다.
- **크레딧 예산 보호**: 이번 주 남은 크레딧이 정한 비율(기본 30%) 아래로 내려가면 서버를 쓰지 않고 로컬 AI로만 받아 적습니다.

휴대폰 앱에서도 녹음할 수 있습니다. 처음 녹음할 때 마이크 권한을 묻고, 녹음하는 동안 알림이 떠 있으며 화면을 꺼도 계속 받아 적습니다(알림에서 중지).`],
  ["업데이트", `
앱이 시작할 때 GitHub Releases에서 새 버전을 확인해 알려 줍니다. **업데이트**를 누르면 설치 파일을 받아 확인한 뒤 설치를 시작합니다(Windows는 설치 프로그램이 열리고 앱이 닫힙니다). 대화·설정은 그대로 남습니다.

**설정 → 업데이트**에서 시작할 때 확인을 끄거나 지금 확인할 수 있습니다.`],
  ["파일 첨부", `
입력창의 **+** 버튼, 파일 끌어다 놓기, 이미지 붙여 넣기(Ctrl+V, 맥은 ⌘+V)로 첨부합니다. 파일은 하나에 20MB, 한 번에 10개까지입니다.

- PDF·Word·PowerPoint·Excel·한글 문서와 텍스트 파일은 내용을 읽어 질문과 함께 보냅니다.
- 이미지는 OpenAI 호환 또는 Responses API 방식에서 모델에게 전달됩니다. a1 방식은 이미지를 전달하지 않습니다.`],
  ["에이전트 모드", `
작업 폴더를 고르고 에이전트를 켜면 AI가 목표를 이룰 때까지 단계를 반복합니다: 폴더 보기·파일 읽기·검색, 파일 쓰기·수정, 명령 실행, 스킬 불러오기, MCP 도구 실행.

- 각 단계는 대화에 한 줄로 표시되고, 누르면 파일 내용·변경 diff·명령 출력이 펼쳐집니다.
- **파일 수정과 명령 실행은 실행 전에 승인을 받습니다.** 설정의 **에이전트 권한**에서 자동 허용으로 바꿀 수 있지만, 명령은 현재 사용자 권한으로 실행되므로 주의하세요.
- 단계가 너무 많으면 설정의 **에이전트 최대 단계 수**에서 멈춥니다.
- 작업 폴더가 없거나 에이전트를 끄면 일반 챗봇으로 동작합니다.`],
  ["명령어", `
입력창에 \`/\`를 입력하면 목록이 뜹니다.

| 명령 | 하는 일 |
|---|---|
| \`/init\` | 작업 폴더를 분석해 INIT.md(프로젝트 지침)를 만듭니다 |
| \`/user 요청\` | 대화 내용으로 내 정보(USER.md)를 작성·업데이트합니다 |
| \`/remember 내용\` | 모든 대화에서 기억할 내용을 저장합니다 |
| \`/memory\` | 기억 목록을 보고 지웁니다 |
| \`/스킬이름 요청\` | 그 스킬의 지침대로 요청을 수행합니다 |
| \`/help\` | 간단한 도움말 |`],
  ["기억: 메모리·내 정보·다른 대화", `
- **메모리(memory.md)**: "~를 기억해 줘"라고 하거나 \`/remember\`로 저장하면 모든 대화에 전달됩니다. 왼쪽 아래 **메모리**에서 보고 고칩니다.
- **내 정보(USER.md)**: 하는 일, 관심 분야, 원하는 답변 방식 등을 적어 두면 답변이 나에게 맞춰집니다. **내 정보**에서 직접 쓰거나 \`/user\`로 AI에게 맡깁니다. 비밀번호·키 같은 비밀은 적지 마세요.
- **다른 대화 참고**: 새 질문과 관련된 내용이 다른 대화에 있으면 자동으로 찾아 참고합니다(📎 표시). 메모리 창에서 끌 수 있습니다.`],
  ["INIT.md와 스킬", `
- **INIT.md**: 작업 폴더 최상위의 INIT.md는 모든 대화에 프로젝트 지침으로 들어갑니다. \`/init\`으로 만들 수 있습니다.
- **스킬**: \`<스킬이름>/SKILL.md\` 형식의 작업 지침입니다. 에이전트가 요청에 맞는 스킬을 스스로 불러오고, \`/스킬이름\`으로 직접 실행할 수도 있습니다. 앱 내장(요약, 코드 검토, 논문 읽기), 사용자 스킬 폴더(**스킬 → 새 스킬 만들기**), 작업 폴더의 \`skills\\\` 순서로 읽고, 이름이 같으면 뒤의 것이 우선합니다.`],
  ["MCP 도구", `
왼쪽 아래 **MCP**에서 서버를 켜고 끕니다. 에이전트 모드에서 켜진 서버의 도구를 씁니다.

- **내장 서버**(설치 필요 없음): word·powerpoint·excel(문서 만들기·고치기), paper(논문 찾기·섹션별 읽기), notion(설정에 Notion 토큰 필요), firecrawl(웹페이지 읽기·웹 검색, 설정에 Firecrawl 키 필요).
- **추천 서버**: playwright(브라우저 자동화). PC에 Node.js가 있어야 합니다.
- **외부 서버**: **MCP → 설정 파일 열기**로 \`mcp.json\`에 Claude Desktop과 같은 형식으로 추가합니다.

바깥에 영향을 주는 도구는 명령 실행처럼 승인을 받습니다.`],
  ["다른 AI 에이전트와 기억 이어 쓰기 (ai-memory)", `
Claude Code·Codex·Cursor·Gemini CLI 같은 코딩 에이전트에서 하던 작업을 POSCHAT에서 이어받고, POSCHAT에서 한 작업을 그 에이전트들이 이어받게 할 수 있습니다.

1. PC에 [ai-memory](https://github.com/akitaonrails/ai-memory)를 설치하고 \`ai-memory setup\`을 실행합니다. 다른 에이전트들도 이때 함께 연결됩니다.
2. **MCP → 설정 파일 열기**로 \`mcp.json\`에 다음을 추가하고 저장합니다.

\`\`\`json
{ "mcpServers": { "ai-memory": { "command": "ai-memory", "args": ["mcp-bridge", "--no-session-id"] } } }
\`\`\`

3. 작업 폴더를 고르고 에이전트 모드로 대화합니다.

그러면 앱이 자동으로 다음을 합니다.

- **대화 시작**: 그 폴더에 다른 에이전트가 남긴 인계(한 일·남은 질문·다음 할 일)를 받고 최근 기억을 불러옵니다(🧠 표시). 인계는 한 번 받으면 사라집니다.
- **작업 후**: 파일을 고치거나 명령·도구를 실행했다면, 다음 에이전트가 이어받을 인계를 남깁니다(📤 표시).
- **검색**: "전에 이 버그 어떻게 고쳤지?"처럼 물으면 AI가 ai-memory에서 찾아봅니다.

ChatGPT·claude.ai 같은 웹 채팅 서비스의 기억은 이어받을 수 없습니다.`],
  ["데이터와 개인정보", `
대화·설정·메모리·첨부 파일·PO노트는 이 기기의 데이터 폴더(설정 창 아래쪽 **데이터 폴더 → 열기**)에만 저장됩니다. 질문할 때 대화 내용, 첨부 내용, 메모리, 내 정보, INIT.md가 POSTECH GenAI API로 전달됩니다. PO노트는 로컬 AI로 받아 적으면 녹음이 PC 밖으로 나가지 않고, POSTECH 서버로 받아 적으면 말 구간의 소리가 POSTECH GenAI로 전달됩니다. 녹음 소리 자체는 저장하지 않습니다. API 키는 설정 파일(config.json)에 저장됩니다.`],
];

function showGuide() {
  const body = h("div", { class: "guide" },
    GUIDE.map(([title, text], i) => h("details", { open: i === 0 },
      h("summary", {}, title), renderMarkdown(text.trim()))));
  modal({ title: "사용법 가이드", body, wide: true, buttons: [{ label: "닫기", class: "primary" }] });
}

function showHelp() {
  const rows = [
    ["/init", "작업 폴더를 분석해 INIT.md를 만듭니다"],
    ["/user 요청", "지금까지의 대화로 내 정보(USER.md)를 작성·업데이트합니다"],
    ["/remember 내용", "모든 대화에서 기억할 내용(memory.md)을 저장합니다"],
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
    h("h3", { style: "margin:18px 0 6px;font-size:15px" }, "PO노트"),
    h("p", { style: "margin:0;color:var(--text-2)" },
      "왼쪽 위 PO노트에서 강의를 녹음해 실시간으로 받아 적고, 강의 자료(PPT·PDF 등)와 함께 Markdown 필기 노트를 만듭니다."),
    h("h3", { style: "margin:18px 0 6px;font-size:15px" }, "파일 첨부"),
    h("p", { style: "margin:0;color:var(--text-2)" },
      "입력창의 클립 버튼을 누르거나 파일을 끌어다 놓거나 이미지를 붙여 넣으면 첨부됩니다. ",
      "문서(PDF·Word·PowerPoint·Excel·한글)와 텍스트 파일은 내용을 읽어 함께 보내고, 이미지는 Responses 또는 OpenAI 호환 API에서 모델이 직접 봅니다."),
    h("h3", { style: "margin:18px 0 6px;font-size:15px" }, "내 정보(USER.md)와 메모리(memory.md)"),
    h("p", { style: "margin:0;color:var(--text-2)" },
      "두 파일은 Markdown이며 모든 대화에 함께 전달됩니다. 왼쪽 아래 '내 정보'와 '메모리'에서 직접 고칠 수 있습니다."),
    h("h3", { style: "margin:18px 0 6px;font-size:15px" }, "INIT.md와 스킬"),
    h("p", { style: "margin:0;color:var(--text-2)" },
      "작업 폴더 최상위의 INIT.md는 모든 대화에 프로젝트 지침으로 들어갑니다. ",
      "스킬은 <폴더>/SKILL.md 형식의 지침이며 앱 내장, 사용자 스킬 폴더, 작업 폴더의 skills\\ 에서 읽습니다."),
  );
  modal({
    title: "도움말", body,
    buttons: [{ label: "사용법 가이드", action: (close) => { close(); showGuide(); } }, { label: "닫기", class: "primary" }],
  });
}

/* ---------- 초기화 ---------- */
function applyState(state) {
  S.threads = state.threads;
  S.workspace = state.workspace;
  S.skills = state.skills;
  S.config = state.config;
  S.dataDir = state.data_dir;
  S.version = state.version || "";
  S.models = state.models || [];
  S.responsesModels = state.responses_models || [];
  S.modelsSource = state.models_source || "builtin";
  S.memory = state.memory || [];
  S.defaultChatUrl = state.default_chat_completions_url || "";
  if (state.credit) S.credit = state.credit;
  S.poAvailable = !!state.po_available;
  if (state.attach_limits) S.attachLimits = state.attach_limits;
  $("#agent-toggle").checked = !!state.config.agent_mode;
  renderThreadModel();
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

const isNarrow = () => window.matchMedia("(max-width: 720px)").matches;
const isTouch = () => window.matchMedia("(pointer: coarse)").matches;

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
    // 한글 조합 중 Enter는 무시해야 마지막 글자가 중복 전송되지 않는다.
    // 터치 화면(휴대폰)의 Enter는 줄바꿈으로 두고 보내기 버튼으로 보낸다.
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229 && !isTouch()) {
      e.preventDefault();
      if (!S.busy) send();
    }
  });
  input.addEventListener("blur", () => setTimeout(hideSlash, 100));
  $("#btn-send").addEventListener("click", send);
  const picker = $("#file-input");
  $("#btn-attach").addEventListener("click", () => picker.click());
  picker.addEventListener("change", () => { addFiles(picker.files); picker.value = ""; });
  // 파일 끌어다 놓기, 이미지 붙여 넣기
  const main = $("#main");
  main.addEventListener("dragover", (e) => {
    if (!Array.from(e.dataTransfer?.types || []).includes("Files")) return;
    e.preventDefault();
    main.classList.add("dropping");
  });
  main.addEventListener("dragleave", (e) => { if (e.target === main || !main.contains(e.relatedTarget)) main.classList.remove("dropping"); });
  main.addEventListener("drop", (e) => {
    main.classList.remove("dropping");
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault();
    addFiles(e.dataTransfer.files);
  });
  input.addEventListener("paste", (e) => {
    const files = Array.from(e.clipboardData?.items || []).filter((it) => it.kind === "file").map((it) => it.getAsFile()).filter(Boolean);
    if (!files.length) return;
    e.preventDefault();
    addFiles(files);
  });
  $("#btn-new").addEventListener("click", newThread);
  $("#btn-new-top").addEventListener("click", newThread);
  $("#btn-collapse").addEventListener("click", () => setCollapsed(true));
  $("#btn-expand").addEventListener("click", () => setCollapsed(false));
  // 좁은 화면에서 사이드바는 화면 위에 겹치는 서랍이다. 바깥(어두운 부분)을 누르면 닫는다.
  $("#app").addEventListener("click", (e) => { if (e.target === $("#app") && isNarrow()) setCollapsed(true); });
  if (isNarrow()) setCollapsed(true);
  $("#btn-workspace").addEventListener("click", chooseWorkspace);
  $("#ws-chip").addEventListener("click", chooseWorkspace);
  $("#btn-skills").addEventListener("click", showSkills);
  $("#btn-mcp").addEventListener("click", showMcp);
  $("#btn-memory").addEventListener("click", async () => { S.memory = await api().list_memory(); showMemory(); });
  $("#btn-profile").addEventListener("click", () => showNoteEditor("profile"));
  $("#btn-settings").addEventListener("click", showSettings);
  $("#thread-model").addEventListener("change", async (event) => {
    if (!S.thread) return;
    const thread = await api().set_thread_model(S.thread.id, event.target.value);
    if (thread.ok === false) {
      toast(thread.error);
      renderThreadModel();
      return;
    }
    S.thread = thread;
    S.threads = await api().list_threads();
    renderSidebar();
  });
  $("#agent-toggle").addEventListener("change", (e) => {
    S.config.agent_mode = e.target.checked;
    api().set_agent_mode(e.target.checked);
    renderWorkspaceChip();
    if (S.thread && !S.thread.messages.length) renderMessages();
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "o") { e.preventDefault(); newThread(); }
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
  // 새 버전 확인(설정에서 끌 수 있고 6시간에 한 번). 실패해도 사용에 지장이 없으므로 알리지 않는다.
  api().check_for_updates(false).then((r) => { if (r.available) offerUpdate(r); }).catch(() => {});
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init, { once: true });
