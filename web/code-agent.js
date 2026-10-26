// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
"use strict";

/* ---------- Code 에이전트: Code 화면 맨 앞의 '작업' 탭 ----------
   1.16: 작업을 맡기면 에이전트가 작업 폴더에서 계획 → 읽기 → 수정 → 실행·테스트 → 정리를 스스로 한다. 백엔드는 code_agent.py.
   1.17.1: 권한 모드 4가지, 계획 승인, 작업 중 추가 지시, 슬래시 명령, 마지막 지시 되돌리기, 격리 작업 공간(git worktree).
   1.17.2(CLI처럼): 탭 전체가 Claude Code 같은 터미널이다. 맨 아래 '>' 줄에 쓰고 Enter, 진행은 위로 쌓인다(● Read(calc.py) ⎿ 2줄 읽음).
   승인·계획 승인·작업 고르기는 대화 상자 대신 기록 안의 선택지(↑↓·숫자·Enter·Esc)로 묻는다. 마우스 없이 키보드만으로 다 된다.
   - 단축키: Enter 보내기 · Shift+Enter(또는 \ 다음 Enter) 줄 바꿈 · Esc 멈춤 · Esc 두 번 되돌리기 · Shift+Tab 권한 모드 ·
     ↑↓ 지난 입력 · Tab 자동 완성 · Ctrl+O 출력 펼치기 · Ctrl+L 화면 비우기 · Ctrl+C 입력 지우기(비었으면 멈춤) · ? 단축키
   - 입력 앞글자: / 명령 · ! 명령 바로 실행(출력은 다음 지시의 맥락) · # 프로젝트 지침에 메모 · @파일 붙이기(자동 완성) */

const CA = {
  state: null, task: null, status: "", tab: null, el: null, draft: "",
  live: "", runId: null, runCommand: "", shell: null,   // 에이전트가 실행 중인 명령 · ! 명령 {run_id, command}
  startedAt: 0, spinTimer: null, verbose: false, open: new Set(), clearedAt: 0,
  sys: [],              // 화면에서만 보이는 출력(/help·/status 등) [{at, task, node}]
  select: null,         // 기록 안의 선택지 {kind, title, body, question, options:[{label, value, id}], index, onPick, onCancel}
  feedback: null,       // 승인에서 '아니요, 다르게 하라고 알려 주기'를 고름 {cid}
  menu: null,           // 자동 완성 {kind: "slash"|"file", items:[{value, label, desc, arg}], index, start, end}
  keys: false,          // ? 단축키 목록
  hint: "", hintTimer: null, escAt: 0, planDismissed: 0, completeSeq: 0,
  hist: [], histPos: -1, histDraft: "",
  doneRuns: new Set(),  // 끝난 ! 명령(끝남 알림이 시작 응답보다 먼저 올 수 있다)
};
// Shift+Tab 순서: 매번 묻기 → 수정 자동 → 계획 → 전체 자동(Claude Code의 default → accept edits → plan → bypass처럼)
const CA_MODES = [
  ["ask", "매번 묻기", "수정·명령 모두 승인", "●"],
  ["auto_edit", "수정 자동", "명령은 묻기", "⏵⏵"],
  ["plan", "계획 모드", "읽기만 하고 계획 제안", "⏸"],
  ["full_auto", "전체 자동", "위험·네트워크 명령만 묻기", "⏵⏵⏵"],
];
// 화면에 보일 도구 이름(Claude Code처럼)
const CA_TOOL = { read: "Read", write: "Write", edit: "Update", multi_edit: "Update", list: "List", glob: "Glob", search: "Search",
  run: "Bash", job_output: "BashOutput", job_stop: "KillBash", skill: "Skill", recall: "Recall", mcp: "MCP", plan: "Update Todos",
  browser_read: "Browser", paper_read: "Paper", attach: "Attach", memory: "Memory", shell: "!",
  web_search: "WebSearch", web_fetch: "WebFetch", paper_search: "PaperSearch", web_download: "Download" };
const CA_SPIN = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"];
const CA_HIST_KEY = "poschat.caHistory";
const CA_PREVIEW = 4;      // 접힌 출력에 보이는 줄 수
const CA_DIFF_LINES = 40;  // 접힌 diff에 보이는 줄 수

function caMode(v) { return CA_MODES.find(([m]) => m === v) || CA_MODES[1]; }
function caRunning() { return !!(CA.state && CA.state.running && CA.task && CA.state.running === CA.task.id); }
function caBusy() { return caRunning() || !!CA.shell; }
function caVisible() {
  const pane = $("#code-pane");
  return !!(CA.tab && CODE.active === CA.tab.id && pane && !pane.hidden && CA.el && CA.el.root.isConnected);
}

function caTab() {
  let t = CODE.tabs.find((x) => x.kind === "agent");
  if (!t) {
    t = codeNewTab({ kind: "agent", title: "작업", path: "" });
    CODE.tabs.splice(CODE.tabs.indexOf(t), 1);
    CODE.tabs.unshift(t);  // 맨 앞에 고정
  }
  CA.tab = t;
  return t;
}

async function caOpen(activate = true) {
  const t = caTab();
  caLoadHistory();
  await caRefresh();
  if (activate) codeActivate(t.id);
  else codeRenderTabs();
}

async function caRefresh() {
  const st = await codeCall(api().code_agent_state(), true);
  if (!st) return;
  CA.state = st;
  const keep = CA.task && st.tasks.some((x) => x.id === CA.task.id) ? CA.task.id : (st.running || (st.shell && st.shell.task_id) || "");
  if (keep) {
    const r = await codeCall(api().code_agent_task(keep), true);
    CA.task = r ? r.task : null;
  } else if (CA.task && CA.task.workspace !== st.workspace) CA.task = null;
  if (st.shell && !CA.shell) CA.shell = { run_id: st.shell.run_id, command: st.shell.command };
  if (!st.shell) CA.shell = null;
  if (caRunning() && !CA.startedAt) {
    const users = (CA.task.turns || []).filter((x) => x.role === "user" && !x.steer);
    CA.startedAt = users.length ? users[users.length - 1].at * 1000 : Date.now();
  }
  caRender();
}

/* ---------- 틀: 한 번 만들고, 기록·아래 줄만 다시 그린다(입력 칸의 글·커서를 지키려고) ---------- */

function caMount() {
  const t = CA.tab || caTab();
  if (CA.el && CA.el.root.isConnected && t.el.contains(CA.el.root)) return;
  const log = h("div", { class: "ca-log", id: "ca-log", role: "log", "aria-live": "polite", "aria-label": "에이전트 진행 기록" });
  const spin = h("div", { class: "ca-spin", id: "ca-spin", role: "status" });
  const menu = h("div", { class: "ca-menu", id: "ca-menu", role: "listbox", "aria-label": "자동 완성", hidden: true });
  const caret = h("span", { class: "ca-caret", "aria-hidden": "true" }, ">");
  const input = h("textarea", { class: "ca-input", id: "ca-input", rows: 1, spellcheck: "false", autocomplete: "off",
    "aria-label": "에이전트에게 지시 · /명령 · !명령 실행 · #메모 · @파일" });
  const box = h("div", { class: "ca-box", id: "ca-box" }, caret, input);
  const line = h("div", { class: "ca-line", id: "ca-line" });
  const root = h("div", { class: "ca-term", id: "ca-term" }, log, h("div", { class: "ca-foot" }, spin, menu, box, line));
  input.value = CA.draft;
  input.addEventListener("input", caOnInput);
  input.addEventListener("keydown", caKey);
  input.addEventListener("click", () => caUpdateMenu());
  // 기록을 누르면(글을 고르는 중이 아니면) 입력 칸으로 — 터미널처럼
  log.addEventListener("mouseup", (e) => {
    if (e.target.closest("button, a, input, textarea, select, summary")) return;
    if (!String(window.getSelection() || "")) input.focus({ preventScroll: true });
  });
  t.el.replaceChildren(root);
  CA.el = { root, log, spin, menu, caret, input, box, line, atBottom: true };
  // 아래(자동 완성·입력 칸)가 커져 기록이 줄어도, 맨 아래를 보고 있었으면 맨 아래에 붙여 둔다
  log.addEventListener("scroll", () => { CA.el.atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60; });
  if (window.ResizeObserver) new ResizeObserver(() => { if (CA.el && CA.el.atBottom) log.scrollTop = log.scrollHeight; }).observe(log);
}

function caRender() {
  if (!CA.tab && !CODE.tabs.some((x) => x.kind === "agent")) return;
  caMount();
  caRenderLog();
  caRenderFoot();
}

/* ---------- 기록 ---------- */

function caRenderLog(stick) {
  if (!CA.el) return;
  const log = CA.el.log;
  const atBottom = stick || log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  const st = CA.state || { tasks: [] };
  const task = CA.task;
  const running = caRunning();
  const nodes = [caBanner()];
  const items = [];
  if (task) {
    for (const x of task.turns || []) items.push({ at: x.at, turn: x });
    for (const x of task.steps || []) items.push({ at: x.at, step: x });
  }
  for (const s of CA.sys) if (s.task === (task ? task.id : null)) items.push({ at: s.at, sys: s });
  items.sort((a, b) => a.at - b.at);
  for (const it of items) {
    if (it.at < CA.clearedAt) continue;
    if (it.turn) nodes.push(caTurnNode(it.turn, task));
    else if (it.step) nodes.push(caStepNode(it.step));
    else nodes.push(it.sys.node);
  }
  if (running && CA.runId) nodes.push(caLiveNode("run", CA.runCommand || "명령"));
  if (CA.shell) nodes.push(caLiveNode("shell", CA.shell.command));
  if (task && !running && !CA.shell) {
    const wt = caWorktreeHint(task);
    if (wt) nodes.push(wt);
  }
  caOfferPlan(task, running);
  if (CA.select) nodes.push(caSelectNode());
  if (!st.workspace && !task) nodes.push(h("div", { class: "ca-sys error" }, "작업 폴더가 없습니다. 사이드바 아래 '작업 폴더'에서 폴더를 고르세요."));
  log.replaceChildren(...nodes);
  if (atBottom) log.scrollTop = log.scrollHeight;
  CA.el.atBottom = atBottom;
}

function caBanner() {
  const st = CA.state || {};
  const p = st.project || {};
  const box = h("div", { class: "ca-banner-box" },
    h("div", { class: "ca-banner-title" }, h("span", { class: "ca-star", "aria-hidden": "true" }, "✻ "), "POSCHAT Code에 오신 것을 환영합니다!"),
    h("div", { class: "ca-dim" }, "/help 명령·단축키 · /status 상태 · /resume 지난 작업"),
    h("div", { class: "ca-dim" }, "cwd: ", st.workspace || "(작업 폴더 없음)"));
  if (CA.task) return h("div", { class: "ca-banner" }, box);
  const tips = st.android ? [h("li", {}, "안드로이드에서는 Code 에이전트를 쓸 수 없습니다(PC 앱에서 쓰세요).")] : [
    h("li", {}, "할 일을 쓰고 Enter — 에이전트가 코드를 찾아 읽고, 고치고, 테스트로 확인합니다"),
    p.instructions && p.instructions.length ? h("li", {}, `프로젝트 지침: ${p.instructions.join(", ")} (따릅니다)`)
      : h("li", {}, h("code", {}, "/init"), "으로 AGENTS.md(프로젝트 지침)를 만들 수 있습니다"),
    h("li", {}, h("code", {}, "!"), " 명령 바로 실행 · ", h("code", {}, "@"), " 파일 붙이기 · ", h("code", {}, "#"), " 지침에 메모 · ",
      h("code", {}, "/"), " 명령"),
    h("li", {}, "Shift+Tab 권한 모드 · Esc 멈춤 · Esc 두 번 되돌리기 · ", h("code", {}, "?"), " 단축키"),
    h("li", {}, "명령은 권한 모드에 따라 승인해야 실행됩니다. 작업 폴더는 보안 격리가 아니니 승인할 명령을 읽으세요."),
  ];
  return h("div", { class: "ca-banner" }, box, h("ul", { class: "ca-tips" }, ...tips));
}

function caTurnNode(turn, task) {
  if (turn.role === "user") {
    const tag = turn.steer ? "작업 중 보냄" : turn.compacted ? "" : turn.mode === "plan" ? "계획 모드" : "";
    return h("div", { class: "ca-row ca-u" + (turn.steer ? " steer" : "") },
      h("span", { class: "ca-mark", "aria-hidden": "true" }, ">"),
      h("div", { class: "ca-body" }, h("span", { class: "sr-only" }, "지시: "), turn.text, tag ? h("span", { class: "ca-tag" }, `(${tag})`) : null));
  }
  const err = turn.status === "error";
  const node = h("div", { class: "ca-row ca-a" + (err ? " error" : "") + (turn.plan_proposal ? " proposal" : "") },
    h("span", { class: "ca-mark", "aria-hidden": "true" }, "●"),
    h("div", { class: "ca-body" },
      turn.plan_proposal ? h("div", { class: "ca-dim" }, "제안한 계획 (파일은 아직 고치지 않았습니다)") : null,
      err ? h("div", {}, turn.text) : renderMarkdown(turn.text)));
  const extra = [];
  if (turn.status === "stopped") extra.push(h("div", { class: "ca-res" }, h("span", { class: "ca-elbow" }, "⎿"), h("span", { class: "ca-err" }, "멈췄습니다 · 무엇을 할지 알려 주세요")));
  if (turn.elapsed != null && !turn.compacted) {
    const bits = [`${caSecs(turn.elapsed)} 동안 일했습니다`];
    if (turn.changed) bits.push(`파일 ${turn.changed}개 바꿈 (/diff 차이 · /undo 되돌리기)`);
    extra.push(h("div", { class: "ca-sum" }, h("span", { class: "ca-star", "aria-hidden": "true" }, "✻"), bits.join(" · ")));
  }
  return extra.length ? h("div", { class: "ca-turn" }, node, ...extra) : node;
}

function caSecs(s) {
  s = Math.max(0, Math.round(Number(s) || 0));
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
}

/* 단계 → {name, arg, result, cls}: 백엔드가 남긴 tool(1.17.2)을 쓰고, 옛 기록은 제목에서 읽는다 */
function caStepView(s) {
  const title = String(s.title || "");
  const paren = /\(([^()]*)\)\s*$/.exec(title);
  const tail = paren ? paren[1] : "";
  const tool = s.tool || null;
  let name = tool ? tool.name : "";
  let arg = tool ? tool.arg : "";
  if (!tool) {
    const m = /^\S+\s+(read|list|search|glob|run|job_output|job_stop|skill|recall|mcp|browser_\w+|paper_read)\s+(.+?)(?:\s+\([^()]*\))?$/.exec(title);
    if (m) { name = m[1]; arg = m[2]; }
  }
  if (s.kind === "edit") {
    const created = /새 파일/.test(title);
    const path = arg || title.replace(/^\S+\s+/, "").replace(/\s*\([^()]*\)\s*$/, "").replace(/^(파일 수정(\(\d+곳\))?|새 파일|파일 덮어쓰기)\s+/, "");
    const nums = /\+(\d+)\s+−(\d+)/.exec(tail);
    const extra = tail.split(", ").slice(1).filter((x) => x !== "Code 검토: 적용").join(", ");  // 수정 자동이면 늘 '적용'이라 뺀다
    const res = nums ? `${Number(nums[1])}줄 더함, ${Number(nums[2])}줄 지움${extra ? ` (${extra})` : ""}` : tail;
    return { name: created ? "Write" : "Update", arg: path, result: res };
  }
  if (s.kind === "denied") return { name: CA_TOOL[name] || (/^⛔ run/.test(title) ? "Bash" : "Update"), arg: arg || title.replace(/^\S+\s+[^:]*:\s*/, ""),
    result: "사용자가 거부했습니다", cls: "ca-err" };
  if (s.kind === "error") return { name: CA_TOOL[name] || "오류", arg, result: title.replace(/^⚠\s*/, "") + (s.detail ? ` — ${s.detail.split("\n")[0].slice(0, 300)}` : ""), cls: "ca-err" };
  if (name === "run" || s.kind === "run") {
    const failed = /종료 코드 (?!0\b)|시간 초과|멈춤/.test(tail);
    return { name: "Bash", arg: arg || title.replace(/^\S+\s+run\s+/, "").replace(/\s*\([^()]*\)\s*$/, ""), result: tail || "끝남", cls: failed ? "ca-err" : "" };
  }
  if (s.kind === "shell") {
    const failed = /종료 코드 (?!0\b)|시간 초과|멈춤/.test(tail);
    return { name: "!", arg: arg || title.replace(/^❯\s*!\s*/, "").replace(/\s*\([^()]*\)\s*$/, ""), result: tail, cls: failed ? "ca-err" : "" };
  }
  if (name === "read") return { name: "Read", arg, result: tail ? `${tail} 읽음` : "읽음" };
  if (name === "attach") return { name: "Attach", arg, result: "지시에 붙였습니다" };
  if (name === "memory") return { name: "Memory", arg, result: `더함: ${s.detail || ""}` };
  if (name === "list") return { name: "List", arg, result: `${(s.detail || "").split("\n").filter(Boolean).length}개 항목` };
  if (name === "glob") return { name: "Glob", arg, result: tail ? `${tail.replace(/개$/, "")}개 찾음` : "" };
  if (name === "search") return { name: "Search", arg, result: s.detail && !/^\(/.test(s.detail) ? `${s.detail.split("\n").filter(Boolean).length}줄 찾음` : "찾지 못함" };
  if (name && CA_TOOL[name]) return { name: CA_TOOL[name], arg, result: tail };
  return null;
}

function caStepNode(s) {
  if (s.kind === "note") return h("div", { class: "ca-row ca-a note" }, h("span", { class: "ca-mark", "aria-hidden": "true" }, "●"),
    h("div", { class: "ca-body" }, s.title.replace(/^💬\s*/, "")));
  if (s.kind === "steer") return h("div", { class: "ca-res" }, h("span", { class: "ca-elbow" }, "⎿"), h("span", {}, "추가 지시를 반영합니다"));
  if (s.kind === "plan") return caTodosNode(s);
  const v = caStepView(s);
  const open = CA.verbose || CA.open.has(s.n);
  const head = (name, arg) => h("button", { type: "button", class: "ca-tool-head", "aria-expanded": String(open),
    onclick: () => { CA.open.has(s.n) ? CA.open.delete(s.n) : CA.open.add(s.n); caRenderLog(); } },
  h("span", { class: "ca-mark", "aria-hidden": "true" }, "●"),
  h("span", {}, h("span", { class: "ca-tname" }, name), arg ? h("span", { class: "ca-targ" }, `(${arg})`) : null));
  if (!v) {  // 정보·되돌리기·규칙·모드 바꾸기 등: 한 줄
    const text = s.title.replace(/^\S+\s+/, "");
    return h("div", { class: `ca-tool ${s.kind}` }, head(text, ""), open && s.detail ? h("pre", { class: "ca-out" }, s.detail) : null);
  }
  const body = [];
  const detail = String(s.detail || "");
  if (detail && (s.kind === "edit" || (s.kind === "denied" && /^--- a\//.test(detail)))) {
    body.push(caDiffNode(detail, open ? 0 : CA_DIFF_LINES));
  } else if (detail && (s.kind === "run" || s.kind === "shell" || s.kind === "error" || open)) {
    if (s.kind === "error" && !open) { /* 오류는 결과 줄에 첫 줄을 보였다 */ } else body.push(...caOutput(detail, open));
  }
  const hint = !open && detail && !body.length ? " (ctrl+o로 펼치기)" : "";
  return h("div", { class: `ca-tool ${s.kind}` }, head(v.name, v.arg),
    h("div", { class: "ca-res" }, h("span", { class: "ca-elbow", "aria-hidden": "true" }, "⎿"),
      h("span", { class: v.cls || "" }, (v.result || "끝남") + hint)),
    ...body);
}

function caOutput(text, open) {
  const lines = String(text).replace(/\s+$/, "").split("\n");
  if (open || lines.length <= CA_PREVIEW + 1) return [h("pre", { class: "ca-out" }, lines.join("\n") || "(출력 없음)")];
  return [h("pre", { class: "ca-out" }, lines.slice(0, CA_PREVIEW).join("\n")),
    h("div", { class: "ca-more" }, `… +${lines.length - CA_PREVIEW}줄 (ctrl+o로 펼치기)`)];
}

function caTodosNode(s) {
  const items = String(s.detail || "").split("\n").filter(Boolean).map((l) => ({ done: l.startsWith("[x]"), text: l.replace(/^\[[x ]\]\s*/, "") }));
  const next = items.findIndex((x) => !x.done);
  return h("div", { class: "ca-tool plan" },
    h("div", { class: "ca-tool-head" }, h("span", { class: "ca-mark", "aria-hidden": "true" }, "●"), h("span", { class: "ca-tname" }, "Update Todos")),
    h("ul", { class: "ca-todos", "aria-label": "계획" }, ...items.map((x, i) => h("li", { class: x.done ? "done" : i === next ? "next" : "" },
      h("span", { "aria-hidden": "true" }, x.done ? "☒ " : "☐ "), h("span", { class: "sr-only" }, x.done ? "끝남: " : "남음: "), x.text))));
}

/* unified diff → 줄 번호가 붙은 diff(Claude Code처럼). diff가 아니면 그냥 글 */
function caDiffNode(text, limit) {
  if (!/^(--- |@@ )/m.test(text)) return h("pre", { class: "ca-out" }, text);
  const rows = [];
  let o = 0, n = 0, shown = 0, more = 0;
  for (const line of String(text).split("\n")) {
    if (line.startsWith("--- ") || line.startsWith("+++ ") || line.startsWith("diff --git") || line.startsWith("index ")) continue;
    const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (m) {
      o = Number(m[1]); n = Number(m[2]);
      if (rows.length && !(limit && shown >= limit)) rows.push(h("div", { class: "ca-dl hunk" }, h("span", { class: "ca-ln" }, ""), h("span", { class: "ca-sg" }, ""), "⋮"));
      continue;
    }
    let cls = "", no, sign = " ";
    if (line.startsWith("+")) { cls = "add"; no = n++; sign = "+"; }
    else if (line.startsWith("-")) { cls = "del"; no = o++; sign = "-"; }
    else if (line.startsWith("\\")) continue;
    else { no = n; o++; n++; }
    if (limit && shown >= limit) { more++; continue; }
    shown++;
    rows.push(h("div", { class: "ca-dl " + cls }, h("span", { class: "ca-ln" }, String(no)), h("span", { class: "ca-sg" }, sign), line.slice(1) || " "));
  }
  const box = h("div", { class: "ca-diff" }, ...rows);
  return more ? h("div", {}, box, h("div", { class: "ca-more" }, `… +${more}줄 (ctrl+o로 펼치기)`)) : box;
}

function caLiveText() {
  const lines = CA.live.replace(/\s+$/, "").split("\n");
  const shown = CA.verbose ? lines : lines.slice(-8);
  return (lines.length > shown.length ? `… 앞 ${lines.length - shown.length}줄\n` : "") + shown.join("\n");
}

function caLiveNode(kind, command) {
  return h("div", { class: `ca-tool ${kind} live` },
    h("div", { class: "ca-tool-head" }, h("span", { class: "ca-mark", "aria-hidden": "true" }, "●"),
      h("span", {}, h("span", { class: "ca-tname" }, kind === "shell" ? "!" : "Bash"), h("span", { class: "ca-targ" }, `(${command})`))),
    h("div", { class: "ca-res" }, h("span", { class: "ca-elbow" }, "⎿"), h("span", {}, "실행 중… (esc로 멈춤)")),
    h("pre", { class: "ca-out", id: "ca-live" }, caLiveText()));
}

function caWorktreeHint(task) {
  if (!task.worktree) return null;
  if (task.worktree_removed) return null;
  return h("div", { class: "ca-sys" }, "⎇ 격리 작업 공간 ", h("code", {}, task.branch || ""), "에서 일합니다(원래 폴더는 그대로). ",
    h("code", {}, "/diff"), " 차이 · ", h("code", {}, "/apply"), " 원래 폴더에 적용 · ", h("code", {}, "/keep"), " 브랜치로 남기기 · ",
    h("code", {}, "/discard"), " 버리기");
}

/* 화면에서만 보이는 출력(명령 결과·오류) */
function caPrint(content, cls = "") {
  const node = content instanceof Node ? content : h("div", {}, String(content));
  if (!node.classList.contains("ca-sys")) node.classList.add("ca-sys");
  if (cls) node.classList.add(...cls.split(" "));
  CA.sys.push({ at: Date.now() / 1000, task: CA.task ? CA.task.id : null, node });
  if (CA.sys.length > 200) CA.sys.splice(0, CA.sys.length - 200);
  caRenderLog(true);
}

/* 실패는 토스트 대신 기록에 빨간 줄로(터미널처럼). 탭이 안 보이면 토스트 */
async function caCall(promise) {
  let res;
  try { res = await promise; } catch (e) { res = { ok: false, error: e.message || String(e) }; }
  if (res && res.ok === false) {
    if (caVisible()) caPrint("오류: " + res.error, "error"); else toast(res.error);
    return null;
  }
  return res;
}

/* ---------- 선택지(승인·계획 승인·작업 고르기) ---------- */

function caAsk(sel) {
  CA.select = { index: 0, ...sel };
  CA.menu = null;
  caRender();
  caFocus();
}

function caSelectNode() {
  const sel = CA.select;
  const opts = sel.options.map((o, i) => h("button", { type: "button", class: "ca-opt" + (i === sel.index ? " cur" : ""), role: "option",
    id: o.id || null, "aria-selected": String(i === sel.index), onclick: () => { sel.index = i; caPick(); } },
  h("span", { class: "ca-ptr", "aria-hidden": "true" }, "❯"), `${i + 1}. ${o.label}`));
  return h("div", { class: "ca-select " + (sel.kind || ""), id: "ca-select", role: "listbox", "aria-label": sel.title },
    h("div", { class: "ca-select-title" }, sel.title),
    sel.body ? h("div", { class: "ca-select-body" }, sel.body) : null,
    sel.question ? h("div", {}, sel.question) : null,
    h("div", { class: "ca-opts" }, ...opts),
    h("div", { class: "ca-select-hint" }, CA.feedback ? "아래에 무엇을 다르게 할지 쓰고 Enter (비우고 Enter면 그냥 거부)"
      : "↑↓로 고르고 Enter · 숫자 · Esc " + (sel.escLabel || "취소")));
}

function caPick(i) {
  const sel = CA.select;
  if (!sel) return;
  const o = sel.options[i == null ? sel.index : i];
  if (!o) return;
  if (!o.keep) CA.select = null;
  sel.onPick(o.value);   // 먼저 부른다(계획 승인이 다시 뜨지 않게 onPick이 먼저 표시를 남긴다)
  caRender();
}

function caCancelSelect() {
  const sel = CA.select;
  if (!sel) return;
  if (sel.onCancel) sel.onCancel();
  else { CA.select = null; caRender(); }
}

/* Bridge의 승인 요청(source: code_agent). 탭이 보이면 기록 안에서 묻고 true, 아니면 false(예전처럼 대화 상자) */
function caConfirm(ev) {
  if (!caVisible()) return false;
  const run = ev.kind === "run";
  const detail = String(ev.detail || "");
  let body;
  if (run) {
    const [where, ...rest] = detail.split("\n");
    const note = (x) => /^(위험할 수 있는 동작:|이 명령은 인터넷|\(백그라운드로)/.test(x);
    const cmd = rest.filter((x) => !note(x)).join("\n").trim();
    body = h("div", {}, h("pre", {}, cmd), ...rest.filter(note).map((x) => h("pre", { class: "ca-warn" }, x)), h("div", { class: "ca-dim" }, where));
  } else if (ev.kind === "site" || /^파일 받기/.test(ev.title || "")) body = h("pre", {}, detail);   // 1.18.1: 웹 주소 확인·파일 받기
  else body = caDiffNode(detail, 60);
  const options = [{ label: "예", value: "allow", id: "ca-yes" }];
  if (run && ev.remember) options.push({ label: `예, 이 작업 폴더에서 '${ev.remember}' 명령은 다시 묻지 않기`, value: "remember", id: "ca-remember" });
  if (ev.kind === "edit") options.push({ label: "예, 이 작업 동안 수정은 묻지 않기 (shift+tab)", value: "always", id: "ca-always" });
  options.push({ label: "아니요, 다르게 하라고 알려 주기 (esc)", value: "feedback", id: "ca-no", keep: true });
  const answer = (v) => {
    if (v === "feedback") { CA.feedback = { cid: ev.id }; caRender(); caFocus(); return; }
    api().resolve_confirm(ev.id, v);
  };
  caAsk({ kind: "confirm", cid: ev.id, title: run ? "Bash 명령" : ev.title || "파일 수정", body,
    question: run ? "이 명령을 실행할까요?" : ev.kind === "edit" ? (/^파일 받기/.test(ev.title || "") ? "받을까요?" : "이렇게 고칠까요?") : "허용할까요?", options, onPick: answer,
    escLabel: "거부",
    onCancel: () => { if (CA.feedback) caFeedback(""); else { CA.select.index = options.length - 1; caPick(); } } });
  return true;
}

async function caFeedback(text) {
  const fb = CA.feedback;
  CA.feedback = null;
  CA.select = null;
  if (!fb) return;
  if (text) await caCall(api().code_agent_steer(text));
  api().resolve_confirm(fb.cid, "deny");
  caRender();
}

/* 계획 모드의 답 뒤: 진행할지 묻는다(Claude Code처럼) */
function caOfferPlan(task, running) {
  if (!task || running || CA.select || CA.shell || task.worktree_removed) return;
  const last = (task.turns || [])[task.turns.length - 1];
  if (!last || !last.plan_proposal || last.at <= CA.planDismissed || last.at < CA.clearedAt) return;
  CA.select = { kind: "plan", index: 0, title: "계획을 제안했습니다. 이 계획으로 진행할까요?", escLabel: "계획 더 다듬기",
    options: [{ label: "예, 수정 자동으로 진행", value: "auto_edit", id: "ca-approve" }, { label: "예, 수정할 때마다 묻기", value: "ask" },
      { label: "아니요, 계획을 더 다듬기", value: "" }],
    onPick: (m) => {
      CA.planDismissed = last.at;
      if (m) caSend("위 계획대로 진행하세요. 계획의 각 단계를 실행하고 확인까지 하세요.", m);
      else { caRender(); caFocus("계획을 이렇게 바꿔 주세요: "); }
    },
    onCancel: () => { CA.planDismissed = last.at; CA.select = null; caRender(); } };
}

/* ---------- 아래: 진행 줄 · 입력 · 상태 줄 ---------- */

function caRenderFoot() {
  if (!CA.el) return;
  const st = CA.state || {};
  const { input, box, caret, line } = CA.el;
  const v = input.value;
  const kind = v.startsWith("!") ? "bash" : v.startsWith("#") ? "memory" : "";
  const off = !st.workspace || st.android;
  box.className = "ca-box" + (kind ? " " + kind : "") + (off ? " disabled" : "");
  caret.textContent = kind === "bash" ? "!" : kind === "memory" ? "#" : ">";
  input.disabled = !!off;
  input.placeholder = off ? "작업 폴더를 고르면 쓸 수 있습니다"
    : CA.feedback ? "무엇을 다르게 할지 쓰고 Enter (비우면 그냥 거부)"
    : caRunning() ? "작업 중 — 쓰고 Enter면 다음 단계에 반영합니다 · esc 멈춤"
    : CA.task ? "이어서 지시하기 · ? 단축키" : "할 일을 쓰고 Enter · / 명령 · ! 실행 · @ 파일 · ? 단축키";
  caAutosize();
  // 상태 줄: 권한 모드(누르면 바뀜) · 안내 · 작업·브랜치
  const [mode, label, desc, icon] = caMode(st.approval);
  const p = st.project || {};
  const right = [];
  if (CA.hint) right.push(CA.hint);
  else {
    if (CA.task) right.push(CA.task.title + (CA.task.worktree && !CA.task.worktree_removed ? " · 격리" : ""));
    if (p.branch) right.push("⎇ " + p.branch);
    if (!v && !caBusy()) right.push("? 단축키");
  }
  line.replaceChildren(
    h("button", { type: "button", class: "ca-modebtn " + mode, id: "ca-mode", title: `권한 모드: ${label} — ${desc}. 누르거나 Shift+Tab으로 바꿉니다`,
      "aria-label": `권한 모드 ${label}. 바꾸기`, onclick: () => caCycleMode() }, `${icon} ${label} (shift+tab으로 바꾸기)`),
    h("span", { class: "ca-right" }, right.join(" · ")));
  caRenderMenu();
  caSpin();
}

function caAutosize() {
  const input = CA.el && CA.el.input;
  if (!input) return;
  input.style.height = "auto";
  const sh = input.scrollHeight;   // 탭이 숨어 있으면 0: 그때는 CSS 기본 높이(한 줄)
  input.style.height = sh ? Math.min(sh, 220) + "px" : "";
}

function caSpin() {
  const busy = caBusy();
  const el = CA.el && CA.el.spin;
  if (!el) return;
  if (!busy) {
    if (CA.spinTimer) { clearInterval(CA.spinTimer); CA.spinTimer = null; }
    el.textContent = "";
    return;
  }
  if (!CA.startedAt) CA.startedAt = Date.now();
  const draw = () => {
    if (!caBusy()) return caSpin();
    const secs = Math.floor((Date.now() - CA.startedAt) / 1000);
    const frame = CA_SPIN[Math.floor(Date.now() / 130) % CA_SPIN.length];
    const what = CA.shell && !caRunning() ? `! ${CA.shell.command}` : (CA.status || "생각하는 중...").replace(/\.\.\.$/, "…");
    el.replaceChildren(`${frame} ${what} `, h("span", { class: "ca-dim" }, `(${caSecs(secs)} · esc로 멈춤)`));
  };
  draw();
  if (!CA.spinTimer) CA.spinTimer = setInterval(draw, 130);
}

function caFocus(text) {
  const input = CA.el && CA.el.input;
  if (!input) return;
  if (text != null) { input.value = text; CA.draft = text; caRenderFoot(); }
  input.focus({ preventScroll: true });
  input.setSelectionRange(input.value.length, input.value.length);
}

function caSetInput(text) {
  if (!CA.el) return;
  CA.el.input.value = text;
  CA.draft = text;
  CA.histPos = -1;
  CA.menu = null;
  caRenderFoot();
}

function caFlash(text) {
  CA.hint = text;
  clearTimeout(CA.hintTimer);
  CA.hintTimer = setTimeout(() => { CA.hint = ""; caRenderFoot(); }, 1600);
  caRenderFoot();
}

/* ---------- 자동 완성(/명령 · @파일) ---------- */

function caOnInput() {
  CA.draft = CA.el.input.value;
  CA.keys = false;
  if (CA.histPos >= 0) CA.histPos = -1;
  caUpdateMenu();
  caRenderFoot();
}

function caUpdateMenu() {
  const input = CA.el.input;
  const v = input.value;
  const pos = input.selectionStart;
  if (v.startsWith("/") && !/\s/.test(v)) {
    const q = v.toLowerCase();
    const all = (CA.state?.slash || []).map(([c, d]) => ({ value: c.split(" ")[0], label: c, desc: d, arg: c.includes(" ") ? (c.includes("[") ? "opt" : "need") : "" }));
    const items = [...all.filter((x) => x.value.startsWith(q)), ...all.filter((x) => !x.value.startsWith(q) && x.value.includes(q.slice(1)))];
    CA.menu = items.length ? { kind: "slash", items, index: 0, start: 0, end: v.length } : null;
    return caRenderMenu();
  }
  const m = /(^|\s)@([^\s@]*)$/.exec(v.slice(0, pos));
  if (m && !v.startsWith("!") && !v.startsWith("#")) {
    const q = m[2];
    const seq = ++CA.completeSeq;
    const start = pos - q.length - 1;
    setTimeout(async () => {
      if (seq !== CA.completeSeq) return;
      const r = await codeCall(api().code_agent_complete(q, CA.task ? CA.task.id : ""), true);
      if (!r || seq !== CA.completeSeq) return;
      CA.menu = r.items.length ? { kind: "file", items: r.items.map((p) => ({ value: p, label: p, desc: "" })), index: 0, start, end: pos } : null;
      caRenderMenu();
    }, 90);
    return;
  }
  CA.completeSeq++;
  CA.menu = null;
  caRenderMenu();
}

function caRenderMenu() {
  if (!CA.el) return;
  const el = CA.el.menu;
  if (CA.keys) {
    el.hidden = false;
    el.replaceChildren(h("div", { class: "ca-keys", id: "ca-keys" }, ...[
      ["/", "명령"], ["!", "명령 바로 실행"], ["@", "파일 붙이기"], ["#", "지침(AGENTS.md)에 메모"],
      ["Enter", "보내기 (작업 중이면 추가 지시)"], ["Shift+Enter", "줄 바꿈 (\\ 다음 Enter도)"], ["Esc", "멈춤 · 자동 완성 닫기"],
      ["Esc 두 번", "마지막 지시 되돌리기"], ["Shift+Tab", "권한 모드 바꾸기"], ["↑ ↓", "지난 입력"], ["Tab", "자동 완성"],
      ["Ctrl+O", "출력 모두 펼치기·접기"], ["Ctrl+L", "화면 비우기"], ["Ctrl+C", "입력 지우기 · 비었으면 멈춤"],
    ].map(([k, d]) => h("div", {}, h("b", {}, k), " ", d))));
    return;
  }
  const menu = CA.menu;
  if (!menu || !menu.items.length) { el.hidden = true; el.replaceChildren(); return; }
  el.hidden = false;
  el.replaceChildren(...menu.items.slice(0, 30).map((it, i) => h("button", { type: "button", class: "ca-mi" + (i === menu.index ? " cur" : ""),
    role: "option", "aria-selected": String(i === menu.index), onmousedown: (e) => e.preventDefault(),
    onclick: () => { menu.index = i; caMenuAccept(false); } },
  h("b", {}, it.label), it.desc ? h("span", {}, it.desc) : null)));
  el.querySelector(".cur")?.scrollIntoView({ block: "nearest" });
}

function caMenuAccept(enter) {
  const menu = CA.menu;
  if (!menu) return false;
  const it = menu.items[menu.index];
  const input = CA.el.input;
  CA.menu = null;
  if (menu.kind === "slash") {
    const text = it.value + (it.arg ? " " : "");
    caSetInput(text);
    caFocus();
    if (enter && it.arg !== "need") { caSubmit(); return true; }
    return true;
  }
  const v = input.value;
  const add = "@" + it.value + (it.value.endsWith("/") ? "" : " ");
  input.value = v.slice(0, menu.start) + add + v.slice(menu.end);
  const at = menu.start + add.length;
  input.setSelectionRange(at, at);
  CA.draft = input.value;
  caRenderFoot();
  if (it.value.endsWith("/")) caUpdateMenu();
  return true;
}

/* ---------- 키 ---------- */

function caKey(e) {
  if (e.isComposing || e.keyCode === 229) return;  // 한글 조합 중
  const input = e.target;
  const v = input.value;
  const key = e.key;
  const ctrl = e.ctrlKey || e.metaKey;
  if (CA.menu && CA.menu.items.length && !CA.keys) {
    if (key === "ArrowDown" || key === "ArrowUp") {
      e.preventDefault();
      const n = Math.min(CA.menu.items.length, 30);
      CA.menu.index = (CA.menu.index + (key === "ArrowDown" ? 1 : -1) + n) % n;
      return caRenderMenu();
    }
    if (key === "Tab" && !e.shiftKey) { e.preventDefault(); caMenuAccept(false); return; }
    if (key === "Enter" && !e.shiftKey && !ctrl) { e.preventDefault(); caMenuAccept(true); return; }
    if (key === "Escape") { e.preventDefault(); CA.menu = null; caRenderMenu(); return; }
  }
  if (CA.keys && (key === "Escape" || key === "?")) { e.preventDefault(); CA.keys = false; return caRenderMenu(); }
  if (CA.select && !CA.feedback && v === "") {
    const n = CA.select.options.length;
    if (key === "ArrowDown" || key === "ArrowUp") {
      e.preventDefault();
      CA.select.index = (CA.select.index + (key === "ArrowDown" ? 1 : -1) + n) % n;
      return caRenderLog(true);
    }
    if (key === "Enter" && !e.shiftKey) { e.preventDefault(); return caPick(); }
    if (/^[1-9]$/.test(key) && Number(key) <= n && !ctrl) { e.preventDefault(); return caPick(Number(key) - 1); }
    if (key === "Escape") { e.preventDefault(); return caCancelSelect(); }
  }
  if (key === "Tab" && e.shiftKey) { e.preventDefault(); return caCycleMode(); }
  if (key === "Escape") { e.preventDefault(); return caEscape(v); }
  if (key === "Enter" && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    const pos = input.selectionStart;
    if (!ctrl && pos > 0 && pos === input.selectionEnd && v[pos - 1] === "\\") {  // \ 다음 Enter: 줄 바꿈
      input.setRangeText("\n", pos - 1, pos, "end");
      return caOnInput();
    }
    return caSubmit();
  }
  if (ctrl && !e.shiftKey && !e.altKey) {
    const k = key.toLowerCase();
    if (k === "o") { e.preventDefault(); CA.verbose = !CA.verbose; caFlash(CA.verbose ? "출력을 모두 펼쳤습니다 (ctrl+o로 접기)" : "출력을 접었습니다"); return caRenderLog(); }
    if (k === "l" && e.ctrlKey) { e.preventDefault(); CA.clearedAt = Date.now() / 1000; return caRenderLog(true); }
    if (k === "c" && e.ctrlKey && !e.metaKey && input.selectionStart === input.selectionEnd) {
      if (v) { e.preventDefault(); return caSetInput(""); }
      if (caBusy()) { e.preventDefault(); return caStop(); }
    }
  }
  if (key === "ArrowUp" && !e.shiftKey && !ctrl && !v.slice(0, input.selectionStart).includes("\n")) {
    if (caHistory(1)) e.preventDefault();
  } else if (key === "ArrowDown" && !e.shiftKey && !ctrl && !v.slice(input.selectionEnd).includes("\n")) {
    if (caHistory(-1)) e.preventDefault();
  } else if (key === "?" && v === "" && !ctrl) {
    e.preventDefault();
    CA.keys = true;
    caRenderMenu();
  }
}

function caEscape(v) {
  if (CA.feedback) return caFeedback("");
  if (caBusy()) return caStop();
  const now = Date.now();
  if (now - CA.escAt < 700) {
    CA.escAt = 0;
    if (v) return caSetInput("");
    return caRewind();
  }
  CA.escAt = now;
  caFlash(v ? "Esc를 한 번 더 누르면 입력을 지웁니다" : "Esc를 한 번 더 누르면 마지막 지시를 되돌립니다");
}

async function caStop() {
  caFlash("멈추는 중…");
  await codeCall(api().code_agent_stop(), true);
}

async function caCycleMode() {
  const st = CA.state;
  if (!st) return;
  const i = CA_MODES.findIndex(([m]) => m === st.approval);
  await caSetMode(CA_MODES[(i + 1) % CA_MODES.length][0], true);
}

async function caSetMode(mode, quiet) {
  const r = await caCall(api().code_agent_set_approval(mode));
  if (!r || !CA.state) return;
  CA.state.approval = r.approval;
  const [, label, desc] = caMode(r.approval);
  if (!quiet && !caRunning()) caPrint(`권한 모드: ${label} — ${desc}`);
  caRenderFoot();
}

/* ↑↓ 지난 입력(이 컴퓨터에 200개까지) */
function caLoadHistory() {
  try { CA.hist = JSON.parse(localStorage.getItem(CA_HIST_KEY) || "[]").filter((x) => typeof x === "string").slice(0, 200); } catch { CA.hist = []; }
}

function caPushHistory(text) {
  CA.hist = [text, ...CA.hist.filter((x) => x !== text)].slice(0, 200);
  CA.histPos = -1;
  try { localStorage.setItem(CA_HIST_KEY, JSON.stringify(CA.hist)); } catch { /* 저장하지 못해도 지금 창에서는 된다 */ }
}

function caHistory(dir) {
  if (!CA.hist.length || CA.menu) return false;
  if (CA.histPos === -1 && dir < 0) return false;
  if (CA.histPos === -1) CA.histDraft = CA.el.input.value;
  const next = Math.min(CA.hist.length - 1, CA.histPos + dir);
  if (next === CA.histPos) return true;
  CA.histPos = next;
  const text = next < 0 ? CA.histDraft : CA.hist[next];
  CA.el.input.value = text;
  CA.draft = text;
  CA.el.input.setSelectionRange(text.length, text.length);
  caRenderFoot();
  return true;
}

/* ---------- 보내기 ---------- */

async function caSubmit() {
  const input = CA.el.input;
  const raw = input.value;
  const text = raw.trim();
  if (CA.feedback) { caSetInput(""); return caFeedback(text); }
  if (!text) { if (CA.select) caPick(); return; }
  if (CA.select && CA.select.kind === "confirm") return caFlash("먼저 위 선택지에 답하세요 (1·2·3, Esc)");
  if (CA.select && CA.select.kind === "plan") { CA.planDismissed = Date.now() / 1000; CA.select = null; }
  else if (CA.select) CA.select = null;
  const st = CA.state || {};
  if (!st.workspace || st.android) return;
  caPushHistory(text);
  caSetInput("");
  if (text.startsWith("!")) return caShell(text.slice(1).trim());
  if (text.startsWith("#")) return caMemory(text.slice(1).trim());
  if (text.startsWith("/") && await caLocalSlash(text)) return;
  if (caRunning()) return caSteer(text);
  if (CA.shell) return caFlash("! 명령이 끝나거나 멈춘 뒤 보내세요 (esc로 멈춤)");
  return caSend(text);
}

async function caSend(text, mode, isolate) {
  const dirty = CODE.tabs.filter((t) => t.kind === "file" && t.editor.isDirty());
  if (dirty.length) caPrint(`저장하지 않은 파일 ${dirty.length}개가 있습니다. 에이전트는 디스크의 내용을 봅니다.`, "ca-warn");
  const options = { isolate: !!isolate && !CA.task, ...(mode ? { mode } : {}) };
  const r = await caCall(api().code_agent_start(text, CA.task ? CA.task.id : "", options));
  if (!r) return;
  if (mode && CA.state && CA.state.approval === "plan" && mode !== "plan") {
    // 계획을 승인하면 계획 모드를 벗어난다(Claude Code처럼). 다음 지시도 그 모드로
    const m = await codeCall(api().code_agent_set_approval(mode), true);
    if (m) CA.state.approval = m.approval;
  }
  CA.task = r.task;
  CA.status = "생각하는 중...";
  CA.live = "";
  CA.runId = null;
  CA.startedAt = Date.now();
  if (CA.state) {
    CA.state.running = r.task.id;
    if (!CA.state.tasks.some((x) => x.id === r.task.id)) CA.state.tasks.unshift({ id: r.task.id, title: r.task.title, status: "running" });
  }
  caRenderLog(true);
  caRenderFoot();
}

async function caSteer(text) {
  if (text.startsWith("/")) return caPrint("작업 중에는 슬래시 명령을 쓸 수 없습니다. 끝나거나 멈춘 뒤(esc) 쓰세요.", "error");
  await caCall(api().code_agent_steer(text));
}

async function caShell(cmd) {
  if (!cmd) return caPrint("! 뒤에 실행할 명령을 쓰세요. 예: !git status", "error");
  if (caRunning()) return caPrint("에이전트가 일하는 중에는 ! 명령을 쓸 수 없습니다. 끝나거나 멈춘 뒤(esc) 하세요.", "error");
  const chk = await caCall(api().code_run_check(cmd));
  if (!chk) return;
  const go = async () => {
    CA.live = "";
    const r = await caCall(api().code_agent_shell(cmd, chk.token, CA.task ? CA.task.id : ""));
    if (!r) return;
    CA.task = r.task;
    if (CA.state && !CA.state.tasks.some((x) => x.id === r.task.id)) CA.state.tasks.unshift({ id: r.task.id, title: r.task.title, status: "idle" });
    if (CA.doneRuns.has(r.run_id)) {   // 벌써 끝났다: 기록을 다시 읽는다
      const t = await codeCall(api().code_agent_task(r.task.id), true);
      if (t) CA.task = t.task;
      CA.shell = null;
    } else {
      CA.shell = { run_id: r.run_id, command: cmd };
      if (!CA.startedAt) CA.startedAt = Date.now();
    }
    caRender();
  };
  const warn = [...(chk.dangers || []).map((d) => `위험할 수 있는 동작: ${d}`), chk.network ? "이 명령은 인터넷(네트워크)을 쓸 수 있습니다." : ""].filter(Boolean);
  if (!warn.length) return go();
  caAsk({ kind: "shell", title: "! 명령", body: h("div", {}, h("pre", {}, cmd), ...warn.map((x) => h("pre", { class: "ca-warn" }, x))),
    question: "그래도 실행할까요?", options: [{ label: "예, 실행", value: true }, { label: "아니요", value: false }],
    onPick: (ok) => { if (ok) go(); } });
}

async function caMemory(text) {
  if (!text) return caPrint("# 뒤에 기억할 내용을 쓰세요. 예: # 테스트는 python -m pytest -q로 돌린다", "error");
  const r = await caCall(api().code_agent_memory(text, CA.task ? CA.task.id : ""));
  if (!r) return;
  if (!CA.task) caPrint(`# ${r.text}\n⎿ ${r.file}에 메모를 더했습니다. 에이전트가 다음 지시부터 읽습니다.`);
  else {
    const t = await codeCall(api().code_agent_task(CA.task.id), true);
    if (t) CA.task = t.task;
    caRenderLog(true);
  }
  if (CA.state && CA.state.project && !CA.state.project.instructions.includes(r.file)) CA.state.project.instructions.push(r.file);
  codeCheckDisk();
}

/* ---------- 슬래시 명령(화면에서 처리하는 것). 처리했으면 true(/init /review /test /plan 할 일·프로젝트 명령은 백엔드) ---------- */

async function caLocalSlash(text) {
  const [cmd0, ...rest] = text.split(/\s+/);
  const cmd = cmd0.toLowerCase();
  const arg = rest.join(" ").trim();
  const st = CA.state || {};
  const task = CA.task;
  const need = () => { if (!task) caPrint("먼저 작업을 시작하거나 /resume으로 지난 작업을 고르세요.", "error"); return !task; };
  const idle = () => { if (caBusy()) caPrint("작업이 진행 중입니다. 끝나거나 멈춘 뒤(esc) 하세요.", "error"); return caBusy(); };
  switch (cmd) {
    case "/help": caHelp(); return true;
    case "/clear": case "/new": case "/reset":
      if (idle()) return true;
      CA.task = null; CA.sys = []; CA.clearedAt = 0; CA.open.clear(); CA.select = null;
      caRender();
      return true;
    case "/resume": caResume(arg); return true;
    case "/status": caStatus(); return true;
    case "/usage": caUsage(); return true;
    case "/todos": {
      if (need()) return true;
      const plan = task.plan || [];
      caPrint(plan.length ? h("div", {}, h("h4", {}, `계획 ${plan.filter((p) => p.done).length}/${plan.length}`),
        ...plan.map((p) => h("div", { class: p.done ? "ca-dim" : "" }, (p.done ? "☒ " : "☐ ") + p.text))) : "아직 계획이 없습니다.");
      return true;
    }
    case "/mode":
      if (!arg) {
        const cur = CA_MODES.findIndex(([m]) => m === st.approval);
        caAsk({ kind: "mode", title: "권한 모드", index: Math.max(0, cur), options: CA_MODES.map(([m, label, desc]) => ({ label: `${label} — ${desc}`, value: m })),
          onPick: (m) => caSetMode(m) });
        return true;
      }
      { const m = CA_MODES.find(([v, label]) => v === arg || label.startsWith(arg) || label.replace(/\s/g, "") === arg.replace(/\s/g, ""));
        if (!m) caPrint("모드: " + CA_MODES.map(([v, label]) => `${v}(${label})`).join(", "), "error");
        else await caSetMode(m[0]); }
      return true;
    case "/plan":
      if (arg) return false;   // '/plan 할 일'은 이번 지시만 계획 모드(백엔드)
      await caSetMode("plan");
      return true;
    case "/permissions": case "/allowed-tools": caPermissions(); return true;
    case "/memory": {
      const file = (st.project && st.project.memory_file) || "AGENTS.md";
      if (!(st.project && st.project.instructions || []).includes(file)) { caPrint(`${file}가 아직 없습니다. /init으로 만들거나 # 메모로 시작하세요.`); return true; }
      codeOpenFile(file);
      return true;
    }
    case "/compact":
      if (need() || idle()) return true;
      caFlash("지난 대화를 요약하는 중…");
      { const r = await caCall(api().code_agent_compact(task.id));
        if (r) { CA.task = r.task; caPrint(`⎿ 지난 대화 ${r.summarized}개를 요약했습니다. 다음 지시는 요약에서 이어 갑니다.`); } }
      return true;
    case "/undo": case "/rewind":
      if (need() || idle()) return true;
      caRewind();
      return true;
    case "/diff": if (!need()) caShowDiff(task); return true;
    case "/revert":
      if (need() || idle()) return true;
      caRevert(task, arg);
      return true;
    case "/apply": case "/keep": case "/discard":
      if (need() || idle()) return true;
      if (!task.worktree || task.worktree_removed) { caPrint("격리 작업 공간이 없는 작업입니다. /worktree 할 일 로 시작하세요.", "error"); return true; }
      caWorktree(task, cmd.slice(1));
      return true;
    case "/worktree":
      if (idle()) return true;
      if (!arg) { caPrint("/worktree 뒤에 할 일을 쓰세요. 예: /worktree 로그인 화면에 비밀번호 찾기 추가", "error"); return true; }
      if (!(st.project && st.project.git)) { caPrint("격리 작업 공간은 Git 저장소(커밋 1개 이상)에서만 됩니다.", "error"); return true; }
      CA.task = null;
      await caSend(arg, null, true);
      return true;
    case "/report": {   // 1.18: 마지막 답변을 부적절한 응답으로 신고(GitHub 이슈, app.js의 reportAiResponse)
      const last = task && [...(task.turns || [])].reverse().find((t) => t.role === "assistant" && !t.compacted);
      if (!last) { caPrint("신고할 답변이 없습니다.", "error"); return true; }
      if (window.reportAiResponse) reportAiResponse({ content: last.text, model: (CA.state && CA.state.model) || "" });
      return true;
    }
    case "/delete":
      if (need() || idle()) return true;
      caAsk({ kind: "delete", title: `'${task.title}' 작업 기록을 지울까요?`, question: "작업 폴더의 파일은 그대로 둡니다(되돌리기용 백업은 지워집니다).",
        options: [{ label: "예, 지우기", value: true }, { label: "아니요", value: false }],
        onPick: async (ok) => { if (ok && await caCall(api().code_agent_delete(task.id))) { CA.task = null; await caRefresh(); caPrint("작업 기록을 지웠습니다."); } } });
      return true;
    default: return false;
  }
}

function caHelp() {
  const st = CA.state || {};
  const rows = (st.slash || []).map(([c, d]) => h("tr", {}, h("td", {}, h("code", {}, c)), h("td", { class: "ca-dim" }, d)));
  caPrint(h("div", { class: "ca-help" },
    h("h4", {}, "명령"), h("table", {}, ...rows),
    h("h4", {}, "입력 앞글자"),
    h("table", {}, ...[["!명령", "작업 폴더에서 바로 실행(출력은 다음 지시의 맥락으로)"], ["#메모", "프로젝트 지침(AGENTS.md)에 한 줄 더하기"],
      ["@파일", "파일·폴더를 지시에 붙이기(Tab으로 완성)"], [".poschat/commands/이름.md", "프로젝트 명령 /이름 ($ARGUMENTS에 인자)"]]
      .map(([k, d]) => h("tr", {}, h("td", {}, h("code", {}, k)), h("td", { class: "ca-dim" }, d)))),
    h("h4", {}, "단축키"),
    h("div", { class: "ca-dim" }, "Enter 보내기 · Shift+Enter 줄 바꿈 · Esc 멈춤 · Esc 두 번 되돌리기 · Shift+Tab 권한 모드 · ↑↓ 지난 입력 · " +
      "Tab 자동 완성 · Ctrl+O 출력 펼치기 · Ctrl+L 화면 비우기 · Ctrl+C 입력 지우기")));
}

function caStatus() {
  const st = CA.state || {};
  const p = st.project || {};
  const task = CA.task;
  const [, label, desc] = caMode(st.approval);
  const rows = [
    ["작업 폴더", st.workspace || "(없음)"],
    ["Git", p.git ? `브랜치 ${p.branch || "?"} · 커밋하지 않은 파일 ${p.changed || 0}개` : "Git 저장소가 아님"],
    ["권한 모드", `${label} — ${desc}`],
    ["모델", st.auto_model ? `자동 선택(Adaptive AI)${st.model ? ` · 기본 ${st.model}` : ""}` : st.model || "(설정의 모델)"],
    ["프로젝트 지침", p.instructions && p.instructions.length ? p.instructions.join(", ") : "없음 (/init)"],
    ["짐작한 명령", (p.commands || []).map((c) => c.command).join(" · ") || "없음"],
    ["다시 묻지 않는 명령", `${(p.rules || []).length}개 (/permissions)`],
    ["작업", task ? `${task.title} · 지시 ${(task.turns || []).filter((x) => x.role === "user").length}번 · 바뀐 파일 ` +
      `${Object.values(task.changes || {}).filter((c) => !c.reverted).length}개` : "(새 작업)"],
  ];
  if (task && task.worktree) rows.push(["격리 작업 공간", task.worktree_removed ? (task.kept_branch ? `브랜치 ${task.kept_branch}에 남김` : "정리함") : `브랜치 ${task.branch}`]);
  caPrint(h("div", {}, h("h4", {}, "POSCHAT Code 상태"), h("table", {}, ...rows.map(([k, v]) => h("tr", {}, h("td", { class: "ca-dim" }, k), h("td", {}, v))))));
}

/* /usage(1.18.1): 이 앱의 AI 호출·토큰(app.js usageRows·usageText)과 POSTECH GenAI 크레딧 */
async function caUsage() {
  let u;
  try { u = await api().get_usage(); } catch { return caPrint("사용량을 불러오지 못했습니다.", "error"); }
  const rows = usageRows(u).map(([k, v]) => [k, usageText(v)]);
  const task = CA.task;
  if (task) rows.push(["이 작업", `지시 ${(task.turns || []).filter((x) => x.role === "user").length}번 · 단계 ${(task.steps || []).length}개`]);
  const cfg = S.config || {};
  if (cfg.key_source) {
    let c = S.credit;
    try { const r = await api().get_credit(); if (r && r.ok !== false) c = S.credit = r; } catch { /* 지난 값 */ }
    rows.push(["POSTECH GenAI 크레딧", creditText(c)]);
  }
  caPrint(h("div", {}, h("h4", {}, "사용량"), h("table", {}, ...rows.map(([k, v]) => h("tr", {}, h("td", { class: "ca-dim" }, k), h("td", {}, v)))),
    h("div", { class: "ca-dim" }, "이 기기에서 이 앱이 보낸 호출입니다(채팅·에이전트·Code 포함). 토큰은 서버가 알려 줄 때만 셉니다.")));
}

function caResume(arg) {
  if (caBusy()) return caPrint("작업이 진행 중입니다. 끝나거나 멈춘 뒤(esc) 하세요.", "error");
  const tasks = (CA.state && CA.state.tasks) || [];
  if (!tasks.length) return caPrint("이 작업 폴더에 지난 작업이 없습니다.");
  const pick = async (id) => {
    const r = await caCall(api().code_agent_task(id));
    if (!r) return;
    CA.task = r.task;
    CA.open.clear();
    CA.clearedAt = 0;
    caRender();
  };
  const n = Number(arg);
  if (n >= 1 && n <= tasks.length) return pick(tasks[n - 1].id);
  const when = (t) => new Date((t.updated || 0) * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  caAsk({ kind: "resume", title: "이어서 할 작업을 고르세요", options: tasks.slice(0, 20).map((t) => ({
    label: `${t.title} · ${when(t)} · 지시 ${Math.ceil((t.turns || 0) / 2)}번` + (t.changed ? ` · 파일 ${t.changed}개` : "") + (t.status === "running" ? " (진행 중)" : ""),
    value: t.id })), onPick: pick });
}

function caPermissions() {
  const rules = ((CA.state && CA.state.project) || {}).rules || [];
  if (!rules.length) return caPrint("다시 묻지 않는 명령이 없습니다. 명령 승인에서 '예, … 다시 묻지 않기'를 고르면 생깁니다.");
  caAsk({ kind: "rules", title: "다시 묻지 않는 명령(이 작업 폴더) — 고르면 지웁니다", options: [
    ...rules.map((r) => ({ label: `지우기: ${r}`, value: r })), { label: "닫기", value: "" }],
  onPick: async (r) => {
    if (!r) return;
    const x = await caCall(api().code_agent_rule_delete(r));
    if (x && CA.state) { CA.state.project.rules = x.rules; caPrint(`'${r}' 규칙을 지웠습니다. 다음부터 다시 묻습니다.`); }
  } });
}

function caRewind() {
  const task = CA.task;
  if (!task) return caFlash("되돌릴 작업이 없습니다");
  const live = Object.values(task.changes || {}).filter((c) => !c.reverted);
  const turns = live.flatMap((c) => Object.keys(c.turns || {}).map(Number));
  if (!turns.length) return caPrint("되돌릴 지시가 없습니다(이 작업이 바꾼 파일이 없음).");
  const last = Math.max(...turns);
  const files = live.filter((c) => (c.turns || {})[last]).map((c) => c.path);
  caAsk({ kind: "rewind", title: `${last}번째 지시로 바뀐 파일 ${files.length}개를 그 지시 전으로 되돌릴까요?`,
    body: h("pre", {}, files.join("\n")), question: "그 뒤 사람이 고친 파일은 건너뜁니다.",
    options: [{ label: "예, 되돌리기", value: true, id: "ca-rewind-yes" }, { label: "아니요", value: false }],
    onPick: async (ok) => {
      if (!ok) return;
      const r = await caCall(api().code_agent_undo(task.id));
      if (!r) return;
      CA.task = r.task;
      caPrint(`⎿ ${r.turn}번째 지시를 되돌렸습니다: ${r.reverted.length}개` + (r.skipped.length ? ` · 건너뜀 ${r.skipped.length}개(그 뒤 바뀜)` : ""));
      codeCheckDisk();
    } });
}

async function caShowDiff(task) {
  if (task.worktree && !task.worktree_removed) {
    const r = await caCall(api().code_agent_worktree_diff(task.id));
    if (r) caPrint(h("div", {}, h("h4", {}, `격리 작업 공간의 변경 — 파일 ${r.files}개`), r.diff ? caDiffNode(r.diff, 0) : "(변경 없음)"));
    return;
  }
  const live = Object.values(task.changes || {}).filter((c) => !c.reverted);
  if (!live.length) return caPrint("이 작업이 바꾼 파일이 없습니다.");
  const parts = [h("h4", {}, `이 작업이 바꾼 파일 ${live.length}개 (작업 전 → 지금)`)];
  for (const c of live) {
    const r = await codeCall(api().code_agent_diff(task.id, c.path), true);
    if (!r) continue;
    parts.push(h("div", {}, h("b", {}, c.path), c.created ? h("span", { class: "ca-dim" }, " (새 파일)") : null,
      r.changed_after ? h("span", { class: "ca-warn" }, " (에이전트가 쓴 뒤 또 바뀜)") : null),
    r.diff ? caDiffNode(r.diff, 0) : h("div", { class: "ca-dim" }, "(차이 없음)"));
  }
  parts.push(h("div", { class: "ca-dim" }, "/revert 파일 — 파일 되돌리기 · /undo — 마지막 지시 되돌리기 · /memory·편집기에서 열기는 파일 트리에서"));
  caPrint(h("div", {}, ...parts));
}

function caRevert(task, path) {
  const live = Object.values(task.changes || {}).filter((c) => !c.reverted);
  if (path && !live.some((c) => c.path === path)) return caPrint(`'${path}'는 이 작업이 바꾼 파일이 아닙니다. 바뀐 파일: ${live.map((c) => c.path).join(", ") || "없음"}`, "error");
  if (!live.length) return caPrint("되돌릴 파일이 없습니다.");
  const what = path ? `'${path}'` : `이 작업이 바꾼 파일 ${live.length}개`;
  caAsk({ kind: "revert", title: `${what}를 작업 전 내용으로 되돌릴까요?`,
    question: "새로 만든 파일은 지웁니다. 에이전트가 쓴 뒤 다른 변경이 생긴 파일은 건너뜁니다.",
    options: [{ label: "예, 되돌리기", value: true }, { label: "아니요", value: false }],
    onPick: async (ok) => {
      if (!ok) return;
      const r = await caCall(api().code_agent_revert(task.id, path));
      if (!r) return;
      CA.task = r.task;
      caPrint(`⎿ 되돌림 ${r.reverted.length}개` + (r.skipped.length ? ` · 건너뜀 ${r.skipped.length}개(그 뒤 바뀜)` : ""));
      codeCheckDisk();
    } });
}

function caWorktree(task, what) {
  const text = {
    apply: ["원래 폴더에 적용할까요?", "격리 작업 공간의 변경(새 파일 포함)을 원래 작업 폴더에 적용하고 격리 공간과 브랜치를 정리합니다. 겹치면 3-way로 합치고, 그래도 안 되면 아무것도 바꾸지 않습니다.", "예, 적용"],
    keep: ["브랜치로 남길까요?", `변경을 브랜치 ${task.branch}에 커밋해 남기고 작업 공간만 정리합니다. 원래 폴더는 그대로이며 Git으로 직접 합칩니다(git merge). 커밋 훅은 돌리지 않습니다.`, "예, 남기기"],
    discard: ["격리 작업을 버릴까요?", "격리 작업 공간과 브랜치를 지웁니다. 원래 작업 폴더는 그대로입니다.", "예, 버리기"],
  }[what];
  caAsk({ kind: "worktree", title: text[0], question: text[1], options: [{ label: text[2], value: true, id: `ca-${what}` }, { label: "아니요", value: false }],
    onPick: async (ok) => {
      if (!ok) return;
      const fn = { apply: "code_agent_apply", keep: "code_agent_keep_branch", discard: "code_agent_discard" }[what];
      const r = await caCall(api()[fn](task.id));
      if (!r) return;
      CA.task = r.task;
      if (what === "apply") caPrint(r.applied ? `⎿ 적용했습니다: 파일 ${r.files.length}개${r.three_way ? " (3-way)" : ""}` : r.message || "적용할 변경이 없습니다");
      else if (what === "keep") caPrint(`⎿ 브랜치 ${r.branch}에 남겼습니다. 합치기: git merge ${r.branch}`);
      else caPrint("⎿ 격리 작업 공간을 버렸습니다(원래 작업 폴더는 그대로).");
      codeCheckDisk();
    } });
}

/* ---------- 이벤트: code.js의 codeEvent가 넘겨 준다 ---------- */

function caEvent(ev) {
  const task = CA.task;
  if (ev.kind === "run_output") {
    if (ev.id === CA.runId || (CA.shell && ev.id === CA.shell.run_id)) {
      CA.live = (CA.live + ev.text).slice(-100000);
      const pre = $("#ca-live");   // 출력만 바꾼다(기록 전체를 다시 그리지 않음)
      if (pre && CA.el) {
        const log = CA.el.log;
        const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
        pre.textContent = caLiveText();
        if (atBottom) log.scrollTop = log.scrollHeight;
      }
    }
    return;
  }
  if (!ev.kind || !ev.kind.startsWith("agent_")) return;
  if (ev.kind === "agent_task") {
    CA.task = ev.task;
    if (CA.state) CA.state.running = ev.task.id;
    if (!CA.startedAt) CA.startedAt = Date.now();
    return caRender();
  }
  if (ev.kind === "agent_shell") {
    if ((!task || task.id === ev.task_id) && !CA.doneRuns.has(ev.run_id)) {
      CA.shell = { run_id: ev.run_id, command: ev.command };
      if (!CA.startedAt) CA.startedAt = Date.now();
      caRender();
    }
    return;
  }
  if (ev.kind === "agent_shell_done") {
    CA.doneRuns.add(ev.run_id);
    CA.shell = null;
    CA.live = "";
    CA.startedAt = 0;
    if (task && task.id === ev.task_id) codeCall(api().code_agent_task(task.id), true).then((r) => { if (r && CA.task && CA.task.id === r.task.id) CA.task = r.task; caRender(); });
    else caRender();
    codeCheckDisk();
    return;
  }
  if (ev.kind === "agent_mode") {   // 작업 중 권한 모드가 바뀜(승인에서 '이 작업 동안 수정은 묻지 않기' 등)
    if (CA.state) CA.state.approval = ev.mode;
    return caRenderFoot();
  }
  if (!task || ev.task_id !== task.id) {
    if (ev.kind === "agent_done") caRefresh();
    return;
  }
  if (ev.kind === "agent_status") {
    CA.status = ev.text;
    return;
  }
  if (ev.kind === "agent_step") { if (!task.steps.some((s) => s.n === ev.step.n)) task.steps.push(ev.step); }
  else if (ev.kind === "agent_plan") task.plan = ev.plan;
  else if (ev.kind === "agent_change") { task.changes[ev.path] = ev.change; codeCheckDisk(); }
  else if (ev.kind === "agent_run") { CA.runId = ev.run_id; CA.runCommand = ev.command || ""; if (ev.run_id) CA.live = ""; }
  else if (ev.kind === "agent_done") {
    if (ev.task) CA.task = ev.task;
    if (CA.state) CA.state.running = null;
    CA.runId = null;
    CA.startedAt = 0;
    CA.feedback = null;
    if (CA.select && CA.select.kind === "confirm") CA.select = null;   // 멈추면 기다리던 승인은 거부로 끝났다
    caRefresh();
    codeCheckDisk();
    if (!caVisible() && ev.status === "done") toast("에이전트가 작업을 마쳤습니다");
    return;
  }
  caRenderLog();
}

window.caOpen = caOpen;
window.caRefresh = caRefresh;
window.caEvent = caEvent;
window.caConfirm = caConfirm;
window.caFocus = caFocus;
window.caVisible = caVisible;
window.caWorktreeHint = caWorktreeHint;
