// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
"use strict";

/* ---------- Code 에이전트(1.16): Codex·Claude Code처럼 작업을 맡기는 '작업' 탭 ----------
   Code 화면을 열면 맨 앞에 '작업' 탭이 있다. 작업을 적어 맡기면 에이전트가 작업 폴더에서 계획 → 읽기 → 수정 → 실행·테스트 →
   정리를 스스로 하고, 단계마다 이 탭에 쌓인다. 파일 트리·편집기·Git·실행 패널은 그대로 옆에 있다.
   기본 승인: 파일 수정은 자동(원본을 백업해 작업·파일 단위로 되돌릴 수 있음), 명령 실행은 매번 묻는다. 백엔드는 code_agent.py.
   1.17.1(Claude Code·Codex처럼): 권한 모드 4가지(계획·매번 묻기·수정 자동·전체 자동), 계획 승인 후 진행, 작업 중 추가 지시,
   슬래시 명령(/init /review /test /plan /undo /compact /new /help), 마지막 지시 되돌리기, 격리 작업 공간(git worktree) 적용·버리기. */

const CA = { state: null, task: null, status: "", live: "", runId: null, tab: null, draft: "", expanded: new Set(), isolate: false };
const CA_ICON = { plan: "📋", read: "📄", list: "📂", search: "🔍", edit: "✏️", run: "▶", denied: "⛔", error: "⚠", revert: "↩", info: "•",
  note: "💬", steer: "🗣", job: "📟", rule: "✅", apply: "📥" };
const CA_MODES = [
  ["plan", "계획 모드 · 읽기만 하고 계획 제안"],
  ["ask", "매번 묻기 · 수정·명령 모두 승인"],
  ["auto_edit", "수정 자동 · 명령은 묻기"],
  ["full_auto", "전체 자동 · 위험한 명령만 묻기"],
];

function caTab() {
  let t = CODE.tabs.find((x) => x.kind === "agent");
  if (!t) {
    t = codeNewTab({ kind: "agent", title: "작업", path: "" });
    CODE.tabs.splice(CODE.tabs.indexOf(t), 1);
    CODE.tabs.unshift(t);  // 맨 앞에 고정
    CA.tab = t;
  }
  return t;
}

async function caOpen(activate = true) {
  const t = caTab();
  await caRefresh();
  if (activate) codeActivate(t.id);
  else codeRenderTabs();
}

async function caRefresh() {
  const st = await codeCall(api().code_agent_state(), true);
  if (!st) return;
  CA.state = st;
  const keep = CA.task && st.tasks.some((x) => x.id === CA.task.id) ? CA.task.id : (st.running || "");
  if (keep) {
    const r = await codeCall(api().code_agent_task(keep), true);
    CA.task = r ? r.task : null;
  } else if (CA.task && CA.task.workspace !== st.workspace) CA.task = null;
  caRender();
}

function caRender() {
  const t = CA.tab || CODE.tabs.find((x) => x.kind === "agent");
  if (!t) return;
  const st = CA.state || { tasks: [], approval: "auto_edit" };
  const task = CA.task;
  const running = !!(st.running && task && st.running === task.id);
  const pick = h("select", { class: "ca-pick", "aria-label": "작업 고르기", onchange: (e) => caSelect(e.target.value) },
    h("option", { value: "" }, "+ 새 작업"),
    ...st.tasks.map((x) => h("option", { value: x.id, selected: task && task.id === x.id }, `${x.title}${x.status === "running" ? " (진행 중)" : ""}`)));
  const approval = h("select", { class: "ca-approval", "aria-label": "권한 모드",
    title: "계획: 읽기만 하고 계획을 제안(승인하면 진행). 수정 자동: 바로 고치고 되돌리기를 남김. 전체 자동: 명령도 바로 실행(위험·네트워크 명령은 물음).",
    onchange: async (e) => { const r = await codeCall(api().code_agent_set_approval(e.target.value)); if (r) st.approval = r.approval; } },
  ...CA_MODES.map(([v, label]) => h("option", { value: v, selected: st.approval === v }, label)));
  const head = h("div", { class: "ca-head" }, pick, approval,
    task && !running ? h("button", { class: "icon-btn", title: "이 작업 기록 지우기", "aria-label": "이 작업 기록 지우기", html: ICONS.trash || ICONS.close,
      onclick: () => caDelete(task) }) : null);
  const log = h("div", { class: "ca-log", id: "ca-log", role: "log", "aria-live": "polite", "aria-label": "에이전트 진행 기록" });
  if (!st.workspace) log.append(h("p", { class: "muted" }, "작업 폴더가 없습니다. 사이드바 아래 '작업 폴더'에서 폴더를 고르세요."));
  else if (!task) log.append(caIntro());
  else caFillLog(log, task, running);
  const input = h("textarea", { class: "ca-input", id: "ca-input", rows: 3,
    "aria-label": running ? "작업 중 추가 지시" : task ? "이어서 지시하기" : "맡길 작업",
    placeholder: running ? "작업 중에 추가 지시 보내기 — 다음 단계부터 반영합니다 (Ctrl+Enter)"
      : task ? "이어서 지시하기 · /로 명령 (Ctrl+Enter로 보내기)"
      : "무엇을 할까요? 예: test_calc.py가 통과하도록 calc.py를 고쳐 줘 · /init /review /test /plan (Ctrl+Enter)",
    disabled: !st.workspace || st.android });
  input.value = CA.draft;
  const hints = h("div", { class: "ca-slash", id: "ca-slash", hidden: true, role: "listbox", "aria-label": "슬래시 명령" });
  const showHints = () => {
    const v = input.value;
    const items = !running && v.startsWith("/") && !v.includes("\n") ? (st.slash || []).filter(([c]) => c.split(" ")[0].startsWith(v.split(" ")[0])) : [];
    hints.hidden = !items.length || v.includes(" ");
    hints.replaceChildren(...items.map(([c, d]) => h("button", { type: "button", class: "ca-slash-item", role: "option",
      onclick: () => { input.value = c.split(" ")[0] + (c.includes(" ") ? " " : ""); CA.draft = input.value; hints.hidden = true; input.focus(); } },
    h("code", {}, c), h("span", { class: "muted" }, d))));
  };
  input.addEventListener("input", () => { CA.draft = input.value; showHints(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); running ? caSteer() : caSend(); }
    if (e.key === "Escape") hints.hidden = true;
  });
  const isolate = !task && st.project && st.project.git ? h("label", { class: "ca-isolate", title: "Codex처럼 작업마다 따로 만든 Git 작업 공간(worktree·브랜치)에서 고칩니다. 끝나면 '원래 폴더에 적용' 또는 '버리기'." },
    h("input", { type: "checkbox", checked: CA.isolate, onchange: (e) => { CA.isolate = e.target.checked; } }), "격리 작업 공간(git worktree)에서") : null;
  const foot = h("div", { class: "ca-foot" }, hints, input,
    h("div", { class: "ca-actions" },
      h("span", { class: "ca-status muted", id: "ca-status", role: "status" }, running ? (CA.status || "작업 중...") : ""),
      isolate,
      running ? h("button", { class: "btn", id: "ca-steer", onclick: () => caSteer() }, "추가 지시") : null,
      running ? h("button", { class: "btn danger", id: "ca-stop", onclick: () => api().code_agent_stop() }, "멈춤")
        : h("button", { class: "btn primary", id: "ca-send", disabled: !st.workspace || st.android, onclick: () => caSend() }, task ? "이어서 지시" : "맡기기")));
  const side = task ? caSide(task, running) : null;
  t.el.replaceChildren(h("div", { class: "ca-wrap" }, head, h("div", { class: "ca-main" }, log, side), foot));
  log.scrollTop = log.scrollHeight;
}

function caIntro() {
  return h("div", { class: "ca-intro" },
    h("h3", {}, "Code 에이전트"),
    h("p", {}, "할 일을 적어 맡기면 에이전트가 작업 폴더에서 코드를 찾아 읽고, 고치고, 테스트·빌드를 실행해 확인한 뒤 결과를 정리합니다. " +
      "진행하는 동안 계획·읽은 파일·바꾼 내용(diff)·실행 출력이 여기에 쌓이고, 끝난 뒤 이어서 지시할 수 있습니다."),
    h("ul", {},
      h("li", {}, "파일 수정은 바로 적용하고, 원래 내용을 보관해 '되돌리기'로 작업 전으로 돌릴 수 있습니다(위에서 '모두 묻기'로 바꿀 수 있음)."),
      h("li", {}, "명령 실행은 매번 승인 창에서 묻습니다. API 키 같은 비밀 환경 변수는 넘기지 않고, 출력의 비밀은 가립니다."),
      h("li", {}, "작업 폴더는 보안 격리가 아닙니다. 승인 창의 명령을 읽고 허용하세요."),
      h("li", {}, "위에서 권한 모드를 고릅니다: 계획 모드는 읽기만 하고 계획을 제안하며, '이 계획으로 진행'을 누르면 고치기 시작합니다. " +
        "전체 자동은 명령도 묻지 않고 실행합니다(위험하거나 인터넷을 쓰는 명령은 물음)."),
      h("li", {}, "일하는 중에도 아래 칸에 추가 지시를 보낼 수 있습니다. /로 시작하면 명령입니다: " +
        (CA.state?.slash || []).map(([c]) => c.split(" ")[0]).join(" "))),
    caProjectInfo());
}

function caProjectInfo() {
  const p = (CA.state && CA.state.project) || {};
  if (!CA.state || !CA.state.workspace) return null;
  const rules = p.rules || [];
  return h("div", { class: "ca-project" },
    h("h4", {}, "이 작업 폴더"),
    h("p", { class: "muted" }, p.instructions && p.instructions.length ? `프로젝트 지침: ${p.instructions.join(", ")}(에이전트가 따릅니다)`
      : "프로젝트 지침(AGENTS.md·CLAUDE.md)이 없습니다. /init으로 만들 수 있습니다."),
    p.commands && p.commands.length ? h("p", { class: "muted" }, "짐작한 명령: ", ...p.commands.map((c) => h("code", { title: c.why }, c.command)).flatMap((x, i) => i ? [" · ", x] : [x])) : null,
    rules.length ? h("div", {}, h("p", { class: "muted" }, "다시 묻지 않는 명령:"),
      h("ul", { class: "ca-rules" }, ...rules.map((r) => h("li", {}, h("code", {}, r),
        h("button", { class: "link-btn", onclick: async () => { const x = await codeCall(api().code_agent_rule_delete(r)); if (x) { CA.state.project.rules = x.rules; caRender(); } } }, "지우기"))))) : null);
}

function caFillLog(log, task, running) {
  const items = [
    ...task.turns.map((x) => ({ at: x.at, turn: x })),
    ...task.steps.map((x) => ({ at: x.at, step: x })),
  ].sort((a, b) => a.at - b.at);
  for (const it of items) {
    if (it.turn) {
      if (it.turn.role === "user") log.append(h("div", { class: "ca-user" + (it.turn.steer ? " steer" : "") + (it.turn.compacted ? " compacted" : "") },
        it.turn.steer ? h("small", { class: "muted block" }, "작업 중 추가 지시") : it.turn.mode === "plan" ? h("small", { class: "muted block" }, "계획 모드") : null,
        it.turn.text));
      else log.append(h("div", { class: "ca-answer" + (it.turn.status === "error" ? " error" : "") + (it.turn.plan_proposal ? " proposal" : "") },
        it.turn.plan_proposal ? h("small", { class: "muted block" }, "제안한 계획 (파일은 아직 고치지 않았습니다)")
          : it.turn.status && it.turn.status !== "done" ? h("small", { class: "muted" }, { stopped: "멈춤", error: "오류" }[it.turn.status] || it.turn.status) : null,
        renderMarkdown(it.turn.text)));
    } else log.append(caStepNode(it.step));
  }
  const last = task.turns[task.turns.length - 1];
  if (!running && last && last.plan_proposal && !task.worktree_removed) {
    const go = CA.state && CA.state.approval !== "plan" ? CA.state.approval : "auto_edit";
    log.append(h("div", { class: "ca-proposal-actions" },
      h("button", { class: "btn primary", id: "ca-approve", onclick: () => caSend("위 계획대로 진행하세요. 계획의 각 단계를 실행하고 확인까지 하세요.", go) },
        `이 계획으로 진행 (${(CA_MODES.find(([v]) => v === go) || ["", go])[1].split(" · ")[0]})`),
      h("button", { class: "btn", onclick: () => { const i = $("#ca-input"); if (i) { i.value = "계획을 이렇게 바꿔 주세요: "; i.focus(); } } }, "계획 고치기")));
  }
  if (running && CA.runId) log.append(h("div", { class: "ca-step run live" }, h("div", { class: "ca-step-title" }, "▶ 명령 실행 중…"),
    h("pre", { class: "ca-live", id: "ca-live" }, CA.live || "")));
  if (running) log.append(h("div", { class: "ca-thinking muted" }, CA.status || "작업 중..."));
}

function caStepNode(s) {
  const open = CA.expanded.has(s.n) || (s.kind === "edit" && s.detail.length < 3000);
  const body = s.detail ? (s.kind === "edit" || s.kind === "denied" ? diffOrPre(s.detail) : h("pre", {}, s.detail)) : null;
  const icon = CA_ICON[s.kind] || "•";
  const title = s.title.replace(/^[^\s]+\s/, "");  // 앞의 기호는 아이콘으로
  if (!body) return h("div", { class: `ca-step ${s.kind}` }, h("div", { class: "ca-step-title" }, h("span", { class: "ca-ico", "aria-hidden": "true" }, icon), title));
  const d = h("details", { class: `ca-step ${s.kind}`, open },
    h("summary", { class: "ca-step-title" }, h("span", { class: "ca-ico", "aria-hidden": "true" }, icon), title), body);
  d.addEventListener("toggle", () => { d.open ? CA.expanded.add(s.n) : CA.expanded.delete(s.n); });
  return d;
}

function caSide(task, running) {
  const plan = task.plan || [];
  const changes = Object.values(task.changes || {});
  if (!plan.length && !changes.length && !task.worktree) return null;
  const live = changes.filter((c) => !c.reverted);
  const turns = live.some((c) => Object.keys(c.turns || {}).length);
  const wt = task.worktree ? h("section", { class: "ca-worktree" }, h("h4", {}, "격리 작업 공간"),
    task.worktree_removed ? h("p", { class: "muted" }, task.applied_at ? "원래 작업 폴더에 적용하고 정리했습니다."
      : task.kept_branch ? h("span", {}, "브랜치 ", h("code", {}, task.kept_branch), "에 남겼습니다. Git으로 합치세요(git merge).")
      : "버렸습니다(원래 작업 폴더는 그대로).")
      : h("div", {},
        h("p", { class: "muted" }, "브랜치 ", h("code", {}, task.branch || ""), "에서 일합니다. 원래 작업 폴더는 적용할 때까지 그대로입니다."),
        h("button", { class: "btn small", onclick: () => caWorktreeDiff(task) }, "전체 차이"),
        !running ? h("button", { class: "btn small primary", id: "ca-apply", onclick: () => caApply(task) }, "원래 폴더에 적용") : null,
        !running ? h("button", { class: "btn small", onclick: () => caKeepBranch(task) }, "브랜치로 남기기") : null,
        !running ? h("button", { class: "btn small danger", onclick: () => caDiscard(task) }, "버리기") : null)) : null;
  return h("aside", { class: "ca-side", "aria-label": "계획과 바뀐 파일" }, wt,
    plan.length ? h("section", {}, h("h4", {}, `계획 ${plan.filter((p) => p.done).length}/${plan.length}`),
      h("ul", { class: "ca-plan" }, ...plan.map((p) => h("li", { class: p.done ? "done" : "" },
        h("span", { "aria-hidden": "true" }, p.done ? "☑" : "☐"), h("span", { class: "sr-only" }, p.done ? "끝남: " : "남음: "), p.text)))) : null,
    changes.length ? h("section", {}, h("h4", {}, `바뀐 파일 ${live.length}`),
      h("ul", { class: "ca-changes" }, ...changes.map((c) => h("li", { class: c.reverted ? "reverted" : "" },
        h("button", { class: "link-btn", title: "편집기에서 열기", onclick: () => c.created && c.reverted ? null : codeOpenFile(c.path) }, c.path),
        h("small", { class: "muted" }, c.reverted ? " 되돌림" : c.created ? " 새 파일" : ""),
        h("span", { class: "ca-change-actions" },
          h("button", { class: "link-btn", onclick: () => caDiff(task, c.path) }, "차이"),
          !c.reverted && !running ? h("button", { class: "link-btn", onclick: () => caRevert(task, c.path) }, "되돌리기") : null)))),
      turns && !running ? h("button", { class: "btn small", id: "ca-undo", onclick: () => caUndo(task) }, "마지막 지시 되돌리기") : null,
      live.length && !running ? h("button", { class: "btn small", onclick: () => caRevert(task, "") }, "이 작업의 변경 모두 되돌리기") : null,
      live.length && !running && codeFeature("git") && !task.worktree ? h("button", { class: "btn small", onclick: () => codeBottom("git") }, "Git에서 보기·커밋") : null) : null);
}

async function caSelect(id) {
  if (!id) { CA.task = null; caRender(); $("#ca-input")?.focus(); return; }
  const r = await codeCall(api().code_agent_task(id));
  if (r) { CA.task = r.task; CA.expanded.clear(); caRender(); }
}

async function caSend(preset, mode) {
  const input = $("#ca-input");
  const text = (preset || (input ? input.value : "")).trim();
  if (!text) return toast("맡길 작업을 입력하세요");
  if (!preset && text.startsWith("/") && await caLocalSlash(text)) return;
  const dirty = CODE.tabs.filter((t) => t.kind === "file" && t.editor.isDirty());
  if (dirty.length) toast(`저장하지 않은 파일 ${dirty.length}개가 있습니다. 에이전트는 디스크의 내용을 봅니다`);
  const options = { isolate: !CA.task && CA.isolate, ...(mode ? { mode } : {}) };
  const r = await codeCall(api().code_agent_start(text, CA.task ? CA.task.id : "", options));
  if (!r) return;
  if (mode && CA.state && CA.state.approval === "plan" && mode !== "plan") {
    // 계획을 승인하면 계획 모드를 벗어난다(Claude Code처럼). 다음 지시도 그 모드로
    const m = await codeCall(api().code_agent_set_approval(mode), true);
    if (m) CA.state.approval = m.approval;
  }
  if (!preset) CA.draft = "";
  CA.task = r.task;
  CA.status = "작업을 시작했습니다...";
  CA.live = "";
  CA.runId = null;
  if (CA.state) {
    CA.state.running = r.task.id;
    if (!CA.state.tasks.some((x) => x.id === r.task.id)) CA.state.tasks.unshift({ id: r.task.id, title: r.task.title, status: "running" });
  }
  caRender();
}

/* 화면에서 처리하는 슬래시 명령. 처리했으면 true(나머지 /init /review /test /plan은 백엔드가 풀어 쓴다) */
async function caLocalSlash(text) {
  const [cmd, ...rest] = text.split(/\s+/);
  const arg = rest.join(" ");
  const done = () => { CA.draft = ""; const i = $("#ca-input"); if (i) i.value = ""; return true; };
  if (cmd === "/help") {
    modal({ title: "Code 에이전트 명령", body: h("table", { class: "route-table" }, ...(CA.state?.slash || []).map(([c, d]) => h("tr", {}, h("th", {}, h("code", {}, c)), h("td", {}, d)))),
      buttons: [{ label: "닫기", value: null }] });
    return done();
  }
  if (cmd === "/new") { CA.task = null; caRender(); return done(); }
  if (cmd === "/undo") { if (!CA.task) toast("되돌릴 작업이 없습니다"); else await caUndo(CA.task); return done(); }
  if (cmd === "/compact") { if (!CA.task) toast("줄일 작업이 없습니다"); else await caCompact(CA.task); return done(); }
  if (cmd === "/mode") {
    const m = CA_MODES.find(([v, label]) => v === arg || label.startsWith(arg));
    if (!m) { toast("모드: " + CA_MODES.map(([v]) => v).join(", ")); return true; }
    const r = await codeCall(api().code_agent_set_approval(m[0]));
    if (r && CA.state) { CA.state.approval = r.approval; caRender(); toast(`권한 모드: ${m[1]}`); }
    return done();
  }
  return false;
}

async function caSteer() {
  const input = $("#ca-input");
  const text = (input ? input.value : "").trim();
  if (!text) return toast("보낼 지시를 쓰세요");
  const r = await codeCall(api().code_agent_steer(text));
  if (!r) return;
  CA.draft = "";
  if (input) input.value = "";
  toast("추가 지시를 보냈습니다. 다음 단계부터 반영합니다");
}

async function caUndo(task) {
  const r = await codeCall(api().code_agent_undo(task.id));
  if (!r) return;
  CA.task = r.task;
  toast(`${r.turn}번째 지시를 되돌렸습니다: ${r.reverted.length}개${r.skipped.length ? ` · 건너뜀 ${r.skipped.length}개(그 뒤 바뀜)` : ""}`);
  caRender();
  codeCheckDisk();
}

async function caCompact(task) {
  toast("지난 대화를 요약하는 중...");
  const r = await codeCall(api().code_agent_compact(task.id));
  if (!r) return;
  CA.task = r.task;
  toast(`지난 대화 ${r.summarized}개를 요약했습니다`);
  caRender();
}

async function caWorktreeDiff(task) {
  const r = await codeCall(api().code_agent_worktree_diff(task.id));
  if (!r) return;
  modal({ title: `격리 작업 공간의 변경 — 파일 ${r.files}개`, wide: true, body: diffOrPre(r.diff || "(변경 없음)"),
    buttons: [{ label: "닫기", value: null }] });
}

async function caApply(task) {
  const ok = await codeChoose("원래 폴더에 적용", h("p", {}, "격리 작업 공간의 변경(새 파일 포함)을 원래 작업 폴더에 적용하고, 격리 공간과 브랜치를 정리합니다. " +
    "그 사이 원래 폴더의 같은 곳이 바뀌었으면 3-way로 합치고, 그래도 안 되면 아무것도 바꾸지 않습니다."), [{ label: "취소", value: false }, { label: "적용", class: "primary", value: true }]);
  if (!ok) return;
  const r = await codeCall(api().code_agent_apply(task.id));
  if (!r) return;
  CA.task = r.task;
  toast(r.applied ? `적용했습니다: 파일 ${r.files.length}개${r.three_way ? " (3-way)" : ""}` : r.message || "적용할 변경이 없습니다");
  caRender();
  codeCheckDisk();
}

async function caKeepBranch(task) {
  const ok = await codeChoose("브랜치로 남기기", h("p", {}, `격리 작업 공간의 변경을 브랜치 ${task.branch}에 커밋해 남기고 작업 공간만 정리합니다. ` +
    "원래 작업 폴더는 그대로이며, Git에서 직접 합칩니다(git merge). 커밋 훅은 돌리지 않습니다."), [{ label: "취소", value: false }, { label: "남기기", class: "primary", value: true }]);
  if (!ok) return;
  const r = await codeCall(api().code_agent_keep_branch(task.id));
  if (r) { CA.task = r.task; caRender(); toast(`브랜치 ${r.branch}에 남겼습니다`); }
}

async function caDiscard(task) {
  const ok = await codeChoose("격리 작업 버리기", h("p", {}, "격리 작업 공간과 브랜치를 지웁니다. 원래 작업 폴더는 그대로입니다."),
    [{ label: "취소", value: false }, { label: "버리기", class: "danger", value: true }]);
  if (!ok) return;
  const r = await codeCall(api().code_agent_discard(task.id));
  if (r) { CA.task = r.task; caRender(); }
}

async function caDiff(task, path) {
  const r = await codeCall(api().code_agent_diff(task.id, path));
  if (!r) return;
  modal({ title: `${path} — 작업 전과 지금의 차이`, wide: true,
    body: h("div", {}, r.changed_after ? h("p", { class: "code-warn" }, "에이전트가 쓴 뒤 파일이 또 바뀌었습니다(되돌리기는 건너뜁니다).") : null,
      diffOrPre(r.diff || "(차이 없음)")),
    buttons: [{ label: "닫기", value: null }, { label: "편집기에서 열기", action: (close) => { close(); codeOpenFile(path); } }] });
}

async function caRevert(task, path) {
  const what = path ? `'${path}'` : `이 작업이 바꾼 파일 ${Object.values(task.changes).filter((c) => !c.reverted).length}개`;
  const ok = await codeChoose("되돌리기", h("p", {}, `${what}를 작업 전 내용으로 되돌립니다. 새로 만든 파일은 지웁니다. ` +
    "에이전트가 쓴 뒤 다른 변경이 생긴 파일은 덮어쓰지 않고 건너뜁니다."), [{ label: "취소", value: false }, { label: "되돌리기", class: "danger", value: true }]);
  if (!ok) return;
  const r = await codeCall(api().code_agent_revert(task.id, path));
  if (!r) return;
  CA.task = r.task;
  toast(`되돌림 ${r.reverted.length}개${r.skipped.length ? ` · 건너뜀 ${r.skipped.length}개(그 뒤 바뀜)` : ""}`);
  caRender();
  codeCheckDisk();
}

async function caDelete(task) {
  const ok = await codeChoose("작업 기록 지우기", h("p", {}, `'${task.title}'의 기록을 지웁니다. 작업 폴더의 파일은 그대로 둡니다(되돌리기용 백업도 지워집니다).`),
    [{ label: "취소", value: false }, { label: "지우기", class: "danger", value: true }]);
  if (!ok) return;
  if (await codeCall(api().code_agent_delete(task.id))) { CA.task = null; await caRefresh(); }
}

/* code.js의 codeEvent가 넘겨 준다 */
function caEvent(ev) {
  const task = CA.task;
  if (ev.kind === "run_output") {
    if (ev.id === CA.runId) {
      CA.live = (CA.live + ev.text).slice(-100000);
      const pre = $("#ca-live");
      if (pre) { pre.textContent = CA.live; const log = $("#ca-log"); if (log) log.scrollTop = log.scrollHeight; }
    }
    return;
  }
  if (!ev.kind || !ev.kind.startsWith("agent_")) return;
  if (ev.kind === "agent_task") { CA.task = ev.task; if (CA.state) CA.state.running = ev.task.id; caRender(); return; }
  if (!task || ev.task_id !== task.id) {
    if (ev.kind === "agent_done") caRefresh();
    return;
  }
  if (ev.kind === "agent_status") {
    CA.status = ev.text;
    const s = $("#ca-status");
    if (s) s.textContent = ev.text;
    const th = document.querySelector(".ca-thinking");
    if (th) th.textContent = ev.text;
    return;
  }
  if (ev.kind === "agent_step") { if (!task.steps.some((s) => s.n === ev.step.n)) task.steps.push(ev.step); }
  else if (ev.kind === "agent_plan") task.plan = ev.plan;
  else if (ev.kind === "agent_change") { task.changes[ev.path] = ev.change; codeCheckDisk(); }
  else if (ev.kind === "agent_run") { CA.runId = ev.run_id; if (ev.run_id) CA.live = ""; }
  else if (ev.kind === "agent_done") {
    if (ev.task) CA.task = ev.task;
    if (CA.state) CA.state.running = null;
    CA.runId = null;
    caRefresh();
    codeCheckDisk();
    if (ev.status === "done") toast("에이전트가 작업을 마쳤습니다");
    return;
  }
  caRender();
}

window.caOpen = caOpen;
window.caRefresh = caRefresh;
window.caEvent = caEvent;
window.caSide = caSide;
