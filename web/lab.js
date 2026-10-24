// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
/* POSCHAT Lab(1.16): 실험 관리 + 재현성 기록 + AI 분석. 사이드바의 Lab을 누르면 본문(#tool-view)에 연다.
   백엔드는 lab_api.py. 실행은 Code와 같은 승인 창을 거치고, 결과 파일은 옮기지 않고 가리킨다.
   그래프는 SVG로 직접 그린다(외부 라이브러리 없음). 통계는 전체 데이터, 점은 표본(표본이면 화면에 알린다). */

const LAB = {
  state: null, env: null, expId: null, exp: null, tab: "overview", runId: null,
  selected: new Set(), live: new Map(), chart: { file: "", x: "", y: [], type: "line" }, compare: null,
};
const LAB_TABS = [["overview", "개요"], ["setup", "실행 설정"], ["run", "Run 상세"], ["chart", "그래프"], ["compare", "비교·AI"]];
const LAB_KIND = { command: "명령", python: "Python 스크립트", notebook: "Jupyter 노트북" };
const LAB_HOW = { last: "마지막 값", first: "첫 값", max: "최댓값", min: "최솟값", mean: "평균" };
const LAB_ST = { completed: "st-ok", imported: "st-ok", running: "kind-write", queued: "", failed: "st-err", cancelled: "st-warn", interrupted: "st-warn" };
const LAB_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be185d", "#4d7c0f"];

PAGES.lab = { title: "Lab", button: "#btn-lab", render: (panel) => labRender(panel) };

async function labCall(promise) {
  const r = await promise;
  if (!r || !r.ok) { toast((r && r.error) || "요청을 처리하지 못했습니다"); return null; }
  return r;
}

function labTime(t) {
  if (!t) return "—";
  const d = new Date(t * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function labDur(s) {
  if (s == null || s === "") return "—";
  if (s < 60) return `${Number(s).toFixed(1)}초`;
  return `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초`;
}
function labNum(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  if (Number.isInteger(n)) return String(n);
  return Math.abs(n) >= 1e5 || Math.abs(n) < 1e-3 ? n.toExponential(3) : String(+n.toPrecision(6));
}
function labParams(p) { return Object.entries(p || {}).map(([k, v]) => `${k}=${v}`).join(", "); }
function labBadge(run) { return h("span", { class: `badge lab-st ${LAB_ST[run.status] || ""}` }, run.status_label || run.status); }

async function labRender(panel) {
  const st = await labCall(api().lab_state());
  if (!st) return fill(panel, h("p", { class: "mcp-error" }, "Lab을 열지 못했습니다."));
  LAB.state = st;
  if (!LAB.env) api().lab_env().then((r) => { if (r && r.ok) { LAB.env = r; if (LAB.tab === "setup") labDraw(); } });
  if (LAB.expId && !st.experiments.some((e) => e.id === LAB.expId)) LAB.expId = null;
  if (!LAB.expId && st.experiments.length) LAB.expId = st.experiments[0].id;
  if (LAB.expId) await labLoad(LAB.expId, false);
  LAB.panel = panel;
  labDraw();
}

async function labLoad(id, draw = true) {
  const r = await labCall(api().lab_experiment(id));
  if (!r) return;
  if (LAB.expId !== id) { LAB.selected.clear(); LAB.runId = null; LAB.compare = null; LAB.chart = { file: "", x: "", y: [], type: "line" }; }
  LAB.expId = id;
  LAB.exp = r.experiment;
  for (const rid of [...LAB.selected]) if (!LAB.exp.runs.some((x) => x.id === rid)) LAB.selected.delete(rid);
  if (LAB.runId && !LAB.exp.runs.some((x) => x.id === LAB.runId)) LAB.runId = null;
  if (draw) labDraw();
}

function labDraw() {
  const panel = LAB.panel;
  if (!panel || PAGE.id !== "lab") return;
  const st = LAB.state;
  const list = h("nav", { class: "lab-list", "aria-label": "실험 목록" },
    h("button", { class: "btn primary lab-new", onclick: () => labEditExperiment(null) }, "+ 새 실험"),
    st.experiments.length ? null : h("p", { class: "muted" }, "아직 실험이 없습니다."),
    ...st.experiments.map((e) => h("button", {
      class: "lab-exp" + (e.id === LAB.expId ? " active" : ""), "aria-current": e.id === LAB.expId ? "true" : null,
      onclick: async () => { await labLoad(e.id); },
    }, h("span", { class: "lab-exp-name" }, e.name), h("small", { class: "muted" }, `Run ${e.run_count}개 · ${labTime(e.last_run || e.updated)}`))));
  const detail = h("section", { class: "lab-detail", "aria-label": "실험 상세" });
  if (!LAB.exp) {
    detail.append(pageIntro("POSCHAT Lab", "실험 조건·코드 버전·실행 환경·결과를 함께 기록하고, 여러 실행(Run)을 비교하고, AI에게 해석을 묻습니다. " +
      "명령·Python 스크립트·Jupyter 노트북을 승인 뒤 실행하거나, 밖에서 만든 결과 파일(CSV·JSON·로그·그림)을 가져옵니다.",
    h("button", { class: "btn primary", onclick: () => labEditExperiment(null) }, "첫 실험 만들기")));
  } else {
    const e = LAB.exp;
    detail.append(
      h("div", { class: "lab-head" },
        h("div", { class: "lab-title" }, h("h1", {}, e.name), h("small", { class: "muted" }, `${e.id}${e.project ? " · " + e.project : ""}`)),
        h("div", { class: "row wrap" },
          h("button", { class: "btn primary", onclick: () => labRunDialog() }, "실행"),
          h("button", { class: "btn", onclick: () => labImportDialog() }, "결과 가져오기"),
          h("button", { class: "btn", onclick: () => labEditExperiment(e) }, "고치기"),
          h("button", { class: "btn danger", onclick: () => labDeleteExperiment(e) }, "지우기"))),
      e.description ? h("p", { class: "lab-desc" }, e.description) : null,
      h("div", { class: "hub-tabs", role: "tablist", "aria-label": "실험 화면" }, ...LAB_TABS.map(([id, label]) => h("button", {
        class: "hub-tab" + (LAB.tab === id ? " active" : ""), role: "tab", "aria-selected": String(LAB.tab === id), id: `lab-tab-${id}`,
        onclick: () => { LAB.tab = id; labDraw(); },
      }, label))),
      h("div", { class: "lab-body", role: "tabpanel", "aria-labelledby": `lab-tab-${LAB.tab}` }, labTab()));
  }
  fill(panel, h("div", { class: "lab-layout" }, list, detail));
}

function labTab() {
  if (LAB.tab === "setup") return labSetupTab();
  if (LAB.tab === "run") return labRunTab();
  if (LAB.tab === "chart") return labChartTab();
  if (LAB.tab === "compare") return labCompareTab();
  return labOverviewTab();
}

/* ---------- 개요: Run 표 ---------- */

function labOverviewTab() {
  const runs = [...LAB.exp.runs].reverse();
  if (!runs.length) return h("div", { class: "po-card" }, h("p", {}, "아직 Run이 없습니다. '실행'으로 실험을 돌리거나 '결과 가져오기'로 밖에서 만든 결과를 남기세요."));
  const metricNames = [...new Set(runs.flatMap((r) => Object.keys(r.metrics || {})))].slice(0, 4);
  const sel = LAB.selected;
  const table = h("table", { class: "lab-table" },
    h("thead", {}, h("tr", {}, h("th", { scope: "col" }, h("span", { class: "sr-only" }, "고르기")), h("th", { scope: "col" }, "#"),
      h("th", { scope: "col" }, "이름"), h("th", { scope: "col" }, "상태"), h("th", { scope: "col" }, "파라미터"),
      ...metricNames.map((m) => h("th", { scope: "col" }, m)), h("th", { scope: "col" }, "시각"), h("th", { scope: "col" }, "시간"),
      h("th", { scope: "col" }, h("span", { class: "sr-only" }, "동작")))),
    h("tbody", {}, ...runs.map((r) => h("tr", { class: r.id === LAB.runId ? "active" : "" },
      h("td", {}, h("input", { type: "checkbox", checked: sel.has(r.id), "aria-label": `Run #${r.seq} 고르기`,
        onchange: (ev) => { ev.target.checked ? sel.add(r.id) : sel.delete(r.id); labDraw(); } })),
      h("td", {}, `#${r.seq}`),
      h("td", {}, h("button", { class: "link-btn", title: r.id, onclick: () => { LAB.runId = r.id; LAB.tab = "run"; labDraw(); } }, r.name || r.id)),
      h("td", {}, labBadge(r)),
      h("td", { class: "lab-params", title: labParams(r.params) }, labParams(r.params) || "—"),
      ...metricNames.map((m) => h("td", { class: "num" }, r.metrics?.[m] ? `${labNum(r.metrics[m].value)}${r.metrics[m].unit ? " " + r.metrics[m].unit : ""}` : "—")),
      h("td", {}, labTime(r.started || r.created)), h("td", {}, labDur(r.seconds)),
      h("td", { class: "lab-actions" },
        r.status === "running" ? h("button", { class: "btn small", onclick: () => labStop(r) }, "멈춤") : null,
        r.status !== "imported" && r.command_template ? h("button", { class: "btn small", title: "같은 설정으로 다시 실행(승인 필요)", onclick: () => labRerun(r) }, "다시 실행") : null)))));
  return h("div", {},
    h("div", { class: "row wrap lab-toolbar" },
      h("span", { class: "muted" }, `Run ${runs.length}개 · 고른 Run ${sel.size}개`),
      h("button", { class: "btn small", disabled: sel.size < 2, onclick: () => { LAB.tab = "compare"; labDraw(); } }, "고른 Run 비교"),
      h("button", { class: "btn small", onclick: () => { LAB.tab = "chart"; labDraw(); } }, "그래프"),
      h("button", { class: "btn small", onclick: () => labAsk("summary") }, "AI: 결과 요약")),
    h("div", { class: "lab-table-wrap" }, table));
}

async function labStop(r) {
  const res = await labCall(api().lab_run_stop(r.id));
  if (res) toast("멈추라고 보냈습니다");
}

async function labRerun(r) {
  const res = await labCall(api().lab_run_rerun(r.id));
  if (!res) return;
  if (res.code && res.code.repo && LAB.exp.runs.length) toast(`원래 Run의 커밋 ${String(res.code.commit || "").slice(0, 8)}${res.code.dirty ? "(커밋하지 않은 변경 있음)" : ""} — 지금 코드로 실행합니다`);
  labRunDialog(res.spec);
}

/* ---------- 실험 만들기·고치기·지우기 ---------- */

function labEditExperiment(e) {
  const name = h("input", { type: "text", value: e ? e.name : "", "aria-label": "실험 이름", maxlength: 200 });
  const desc = h("textarea", { rows: 3, "aria-label": "설명", maxlength: 5000 }, e ? e.description : "");
  modal({
    title: e ? "실험 고치기" : "새 실험",
    body: h("div", {}, h("div", { class: "field" }, h("label", {}, "이름"), name),
      h("div", { class: "field" }, h("label", {}, "설명(목표·가설, 선택)"), desc),
      e ? null : h("small", { class: "muted" }, `작업 폴더: ${LAB.state.workspace || "(없음 — 실행하려면 작업 폴더를 고르세요)"}`)),
    buttons: [{ label: "취소", value: null }, { label: e ? "저장" : "만들기", class: "primary", action: async (close) => {
      const res = await labCall(api().lab_experiment_save({ id: e ? e.id : "", name: name.value, description: desc.value }));
      if (!res) return;
      close(true);
      LAB.expId = res.experiment.id;
      if (!e) LAB.tab = "setup";
      await labRender(LAB.panel);
    } }],
  });
}

function labDeleteExperiment(e) {
  modal({
    title: "실험 기록 지우기",
    body: h("div", {}, h("p", {}, `'${e.name}'의 기록과 Run ${e.runs.length}개를 지웁니다.`),
      h("p", { class: "muted" }, "작업 폴더의 코드·결과 파일은 지우지 않습니다. Lab이 따로 보관한 사본(실행한 노트북·변경 패치)만 지웁니다.")),
    buttons: [{ label: "취소", value: null }, { label: "기록 지우기", class: "danger", action: async (close) => {
      const res = await labCall(api().lab_experiment_delete(e.id));
      if (!res) return;
      close(true);
      LAB.expId = null; LAB.exp = null;
      await labRender(LAB.panel);
    } }],
  });
}

/* ---------- 실행 설정·실행 ---------- */

function labParamRows(params) {
  const box = h("div", { class: "lab-param-rows" });
  const add = (k = "", v = "") => {
    const row = h("div", { class: "row lab-param" },
      h("input", { type: "text", class: "code-input", value: k, placeholder: "이름(예: lr)", "aria-label": "파라미터 이름" }),
      h("input", { type: "text", class: "code-input", value: v, placeholder: "값", "aria-label": "파라미터 값" }),
      h("button", { class: "icon-btn", html: ICONS.close, title: "빼기", "aria-label": "파라미터 빼기", onclick: () => row.remove() }));
    box.append(row);
  };
  for (const [k, v] of Object.entries(params || {})) add(k, v);
  const wrap = h("div", {}, box, h("button", { class: "btn small", onclick: () => add() }, "+ 파라미터"));
  wrap.read = () => {
    const out = {};
    for (const row of box.querySelectorAll(".lab-param")) {
      const [k, v] = row.querySelectorAll("input");
      if (!k.value.trim()) continue;
      const raw = v.value.trim();
      out[k.value.trim()] = raw !== "" && !isNaN(Number(raw)) ? Number(raw) : raw === "true" ? true : raw === "false" ? false : raw;
    }
    return out;
  };
  return wrap;
}

function labSettingsForm(base) {
  const s = { kind: "python", command: "", script: "", params: {}, outputs: [], timeout: 600, ...(base || {}) };
  const kind = h("select", { "aria-label": "실행 방식" }, ...Object.entries(LAB_KIND).map(([k, v]) => h("option", { value: k, selected: s.kind === k }, v)));
  const command = h("input", { type: "text", class: "code-input", value: s.command, placeholder: "예: python sim.py --bits {bits}", "aria-label": "명령 틀" });
  const script = h("input", { type: "text", class: "code-input", value: s.script, placeholder: "작업 폴더 안 경로(예: train.py, analysis.ipynb)", "aria-label": "스크립트·노트북 경로" });
  const outputs = h("input", { type: "text", class: "code-input", value: (s.outputs || []).join(", "), placeholder: "예: out/*.csv, results/*.json", "aria-label": "결과 파일 패턴" });
  const timeout = h("input", { type: "number", class: "code-input", value: s.timeout, min: 10, max: 3600, "aria-label": "제한 시간(초)" });
  const params = labParamRows(s.params);
  const cmdField = h("div", { class: "field" }, h("label", {}, "명령 틀"), command,
    h("small", {}, "{이름}에 파라미터 값이 들어갑니다(따옴표로 감쌈). 파라미터는 환경 변수 POSCHAT_PARAM_<이름>으로도 넘깁니다."));
  const scriptField = h("div", { class: "field" }, h("label", {}, "파일"), script,
    h("small", {}, "Python 스크립트는 파라미터를 --이름 값으로 넘깁니다. 노트북은 nbconvert로 실행하고, 파라미터는 환경 변수로만 넘깁니다(실행한 노트북 사본을 Lab에 남김)."));
  const sync = () => { cmdField.hidden = kind.value !== "command"; scriptField.hidden = kind.value === "command"; };
  kind.addEventListener("change", sync);
  sync();
  const env = LAB.env;
  const envLine = env ? h("p", { class: "muted lab-env-line" },
    `Python: ${env.python ? `${env.python_version || "?"} (${env.python})` : "찾지 못함"} · Jupyter(nbconvert): ${env.notebook ? "있음" : "없음"} · ` +
    `Git: ${env.git ? "있음" : "없음"} · NVIDIA GPU 도구: ${env.nvidia_smi ? "있음" : "없음"} — 없는 도구는 설치하지 않습니다.`) : null;
  const form = h("div", { class: "lab-form" },
    h("div", { class: "field" }, h("label", {}, "실행 방식"), kind), cmdField, scriptField,
    h("div", { class: "field" }, h("label", {}, "파라미터"), params),
    h("div", { class: "field" }, h("label", {}, "결과 파일(실행 뒤 자동으로 가리킬 파일)"), outputs,
      h("small", {}, "쉼표로 여러 개. 실행 중에 바뀐 작업 폴더 안의 파일만 Run에 붙입니다(옮기지 않음).")),
    h("div", { class: "field" }, h("label", {}, "제한 시간(초)"), timeout), envLine);
  form.read = () => ({ kind: kind.value, command: command.value.trim(), script: script.value.trim(), params: params.read(),
    outputs: outputs.value.split(",").map((x) => x.trim()).filter(Boolean), timeout: Number(timeout.value) || 600 });
  return form;
}

function labSetupTab() {
  const s = LAB.exp.settings || {};
  const form = labSettingsForm(s);
  const spec = (s.metric_spec || []);
  return h("div", {}, form,
    spec.length ? h("div", { class: "field" }, h("label", {}, "자동으로 뽑는 지표"),
      h("ul", { class: "lab-spec" }, ...spec.map((m, i) => h("li", {},
        `${m.name || m.column || m.key} ← ${m.file} ${m.column ? `열 '${m.column}'` : `값 '${m.key}'`} (${LAB_HOW[m.how] || m.how || "마지막 값"})${m.unit ? " · " + m.unit : ""} `,
        h("button", { class: "link-btn", onclick: async () => {
          const next = spec.filter((_, j) => j !== i);
          if (await labCall(api().lab_experiment_save({ id: LAB.exp.id, settings: { ...s, metric_spec: next } }))) await labLoad(LAB.exp.id);
        } }, "빼기"))))) : h("p", { class: "muted" }, "지표 규칙이 없습니다. Run 상세의 결과 파일에서 '지표 뽑기'로 고르면 다음 Run에도 같은 규칙을 씁니다."),
    h("div", { class: "row wrap" },
      h("button", { class: "btn", onclick: async () => {
        if (await labCall(api().lab_experiment_save({ id: LAB.exp.id, settings: { ...s, ...form.read() } }))) { toast("실행 설정을 저장했습니다"); await labLoad(LAB.exp.id); }
      } }, "설정 저장"),
      h("button", { class: "btn primary", onclick: () => labRunDialog(form.read()) }, "이 설정으로 실행")));
}

async function labRunDialog(spec) {
  const e = LAB.exp;
  if (!spec) {
    const form = labSettingsForm(e.settings);
    const ok = await new Promise((resolve) => modal({ title: "실행할 설정", wide: true, body: form,
      buttons: [{ label: "취소", value: null }, { label: "다음", class: "primary", action: (close) => { spec = form.read(); close(true); } }], onClose: resolve }));
    if (!ok) return;
  }
  const check = await labCall(api().lab_run_check(e.id, spec));
  if (!check) return;
  const name = h("input", { type: "text", class: "code-input", placeholder: "Run 이름(선택)", "aria-label": "Run 이름" });
  const notes = h("input", { type: "text", class: "code-input", placeholder: "메모(선택: 무엇을 확인하려는지)", "aria-label": "Run 메모" });
  const body = h("div", { class: "code-approve" },
    h("p", {}, `실험 '${check.experiment}'의 Run으로 다음 명령을 실행합니다.`),
    h("pre", { class: "diff" }, h("div", {}, `${check.cwd}>\n${check.command}`)),
    Object.keys(check.params).length ? h("p", {}, `파라미터: ${labParams(check.params)}`) : null,
    h("p", { class: "muted" }, `셸: ${check.shell} · 제한 시간 ${check.timeout}초${check.inputs.length ? " · 입력 파일: " + check.inputs.join(", ") : ""}` +
      (check.outputs.length ? ` · 결과 파일: ${check.outputs.join(", ")}` : "")),
    check.network ? h("p", { class: "code-warn" }, "이 명령은 인터넷(네트워크)을 쓸 수 있습니다.") : null,
    check.dangers.length ? h("div", { class: "code-warn" }, h("strong", {}, "위험할 수 있는 동작"), h("ul", {}, ...check.dangers.map((d) => h("li", {}, d)))) : null,
    h("p", { class: "muted" }, "실행 직전의 Git 커밋·가지·커밋하지 않은 변경(패치 사본)과 실행 환경(OS·Python·패키지 목록·GPU)을 기록합니다. " +
      "작업 폴더는 시작 위치일 뿐 보안 격리가 아닙니다. API 키 같은 비밀 환경 변수는 넘기지 않고, 출력에 보이는 비밀은 가립니다."),
    name, notes);
  const ok = await new Promise((resolve) => modal({ title: "실험 실행 승인", wide: true, body,
    buttons: [{ label: "취소", value: false }, { label: "실행", class: check.dangers.length ? "danger" : "primary", value: true }], onClose: resolve }));
  if (!ok) return;
  const res = await labCall(api().lab_run_start(e.id, spec, check.token, name.value, notes.value));
  if (!res) return;
  LAB.runId = res.run.id;
  LAB.tab = "run";
  await labLoad(e.id);
}

/* ---------- 외부 결과 가져오기 ---------- */

async function labImportDialog() {
  const e = LAB.exp;
  const picked = new Map();
  const scan = await labCall(api().lab_scan());
  const runs = await api().code_runs();
  const codeRuns = (runs && runs.ok ? runs.runs : []).filter((r) => r.status !== "running" && r.status !== "stopping").slice(0, 20);
  const list = h("div", { class: "lab-pick", role: "group", "aria-label": "결과 파일" });
  const addRow = (f, checked = false) => {
    if (picked.has(f.path)) return;
    const box = h("input", { type: "checkbox", checked, "aria-label": `${f.rel || f.name} 가져오기` });
    picked.set(f.path, box);
    list.append(h("label", { class: "lab-pick-row" }, box, h("span", { title: f.path }, f.rel || f.path), h("small", { class: "muted" }, `${f.kind} · ${fmtSize(f.size)}`)));
  };
  for (const f of (scan ? scan.files : []).slice(0, 80)) addRow(f);
  if (!picked.size) list.append(h("p", { class: "muted" }, "작업 폴더에서 결과 파일(CSV·TSV·JSON·JSONL·TXT·로그·PNG·SVG)을 찾지 못했습니다."));
  const codeSel = h("select", { "aria-label": "Code 실행 기록" }, h("option", { value: "" }, "(가져오지 않음)"),
    ...codeRuns.map((r) => h("option", { value: r.id }, `${r.command.slice(0, 60)} · ${r.status} · ${labTime(r.started)}`)));
  const name = h("input", { type: "text", class: "code-input", placeholder: "Run 이름(예: 서버에서 돌린 결과)", "aria-label": "Run 이름" });
  const notes = h("input", { type: "text", class: "code-input", placeholder: "메모(선택)", "aria-label": "메모" });
  const params = labParamRows({});
  const body = h("div", {},
    h("p", { class: "muted" }, "파일은 옮기거나 복사하지 않고 경로·크기·해시로 가리킵니다. 나중에 원본이 바뀌거나 없어지면 알려 드립니다."),
    h("div", { class: "field" }, h("label", {}, "작업 폴더의 결과 파일"), list,
      h("button", { class: "btn small", onclick: async () => {
        const r = await labCall(api().lab_pick_files());
        if (r) for (const f of r.files) addRow(f, true);
      } }, "다른 파일 고르기…")),
    codeRuns.length ? h("div", { class: "field" }, h("label", {}, "Code 실행 패널의 기록(선택)"), codeSel) : null,
    h("div", { class: "field" }, h("label", {}, "이 결과의 조건(파라미터)"), params),
    h("div", { class: "field" }, h("label", {}, "이름·메모"), name, notes));
  modal({ title: "결과 가져오기", wide: true, body, buttons: [{ label: "취소", value: null }, { label: "가져오기", class: "primary", action: async (close) => {
    const files = [...picked].filter(([, b]) => b.checked).map(([p]) => p);
    const res = await labCall(api().lab_import(e.id, { files, name: name.value, notes: notes.value, params: params.read(), code_run_id: codeSel.value }));
    if (!res) return;
    close(true);
    for (const w of res.warnings || []) toast(w);
    LAB.runId = res.run.id;
    LAB.tab = "run";
    await labLoad(e.id);
  } }] });
}

/* ---------- Run 상세: 코드·환경·결과·지표·로그 ---------- */

function labRunTab() {
  const runs = LAB.exp.runs;
  if (!runs.length) return h("p", { class: "muted" }, "Run이 없습니다.");
  const r = runs.find((x) => x.id === LAB.runId) || runs[runs.length - 1];
  LAB.runId = r.id;
  const pick = h("select", { "aria-label": "Run 고르기", onchange: (ev) => { LAB.runId = ev.target.value; labDraw(); } },
    ...[...runs].reverse().map((x) => h("option", { value: x.id, selected: x.id === r.id }, `#${x.seq} ${x.name || ""} · ${x.status_label}`)));
  const code = r.code || {};
  const env = r.env || {};
  const sec = (title, ...body) => h("section", { class: "lab-sec" }, h("h3", {}, title), ...body);
  const kv = (rows) => h("dl", { class: "lab-kv" }, ...rows.filter(Boolean).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
  const live = r.status === "running" ? (LAB.live.get(r.code_run_id) || "") : "";
  const notes = h("textarea", { rows: 3, "aria-label": "Run 메모" }, r.notes || "");
  const metrics = Object.entries(r.metrics || {});
  const script = (LAB.exp.settings || {}).script;
  return h("div", { class: "lab-run" },
    h("div", { class: "row wrap lab-toolbar" }, pick, labBadge(r), h("small", { class: "muted" }, r.id),
      r.status === "running" ? h("button", { class: "btn small", onclick: () => labStop(r) }, "멈춤") : null,
      h("button", { class: "btn small", onclick: () => labRename(r) }, "이름 바꾸기"),
      r.status !== "running" ? h("button", { class: "btn small danger", onclick: () => labDeleteRun(r) }, "기록 지우기") : null),
    sec("실행", kv([["상태", `${r.status_label}${r.exit_code != null ? ` · 종료 코드 ${r.exit_code}` : ""}`],
      ["출처", { poschat: "POSCHAT에서 실행", import: "밖에서 만든 결과 가져옴", code: "Code 실행 패널 기록" }[r.source] || r.source],
      ["시작·끝", `${labTime(r.started)} → ${labTime(r.ended)} (${labDur(r.seconds)})`],
      r.command ? ["명령", h("code", { class: "lab-code" }, r.command)] : null,
      r.command_template ? ["명령 틀", h("code", { class: "lab-code" }, r.command_template)] : null,
      ["파라미터", labParams(r.params) || "없음"], r.cwd ? ["작업 폴더", r.cwd] : null])),
    sec("코드 버전", code.repo ? kv([["커밋", h("code", {}, code.commit || "—")], ["가지", code.branch || "—"],
      code.remote ? ["원격", code.remote] : null,
      ["커밋하지 않은 변경", code.dirty ? h("span", { class: "code-warn" }, `있음 ${code.changed_count}개 — 재현하려면 패치 사본이 필요합니다`) : "없음"],
      code.dirty ? ["바뀐 파일", h("div", { class: "lab-files" }, ...(code.changed || []).slice(0, 30).map((p) => {
        const path = p.includes(" -> ") ? p.split(" -> ")[1] : p;
        return h("button", { class: "link-btn", title: "Code에서 열기", onclick: () => labOpenCode(path) }, p);
      }))] : null,
      code.patch_file ? ["패치 사본", h("small", {}, `${code.patch_file} (SHA-256 ${String(code.diff_sha256).slice(0, 12)}…)`)] : null,
      code.patch_note ? ["패치", code.patch_note] : null]) : h("p", { class: "muted" }, `Git 기록 없음${code.reason ? ` (${code.reason})` : ""} — 코드 버전을 재현하기 어렵습니다.`),
    h("div", { class: "row wrap" }, script ? h("button", { class: "btn small", onclick: () => labOpenCode(script) }, `Code에서 ${script} 열기`) : null,
      (r.locations || []).slice(0, 5).map((l) => h("button", { class: "btn small", onclick: () => labOpenCode(l.path, l.line) }, `${l.path}:${l.line}`)))),
    sec("실행 환경", Object.keys(env).length ? kv([["OS", `${env.os || "—"} ${env.machine || ""}`],
      ["Python", env.python ? `${env.python} (${env.python_path || ""})` : "기록 없음(뒤에서 확인 중이거나 찾지 못함)"],
      ["패키지", env.packages ? h("details", {}, h("summary", {}, `${env.packages.length}개 (pip freeze)`), h("pre", { class: "lab-pre" }, env.packages.join("\n"))) : "기록 없음"],
      ["GPU", (env.gpus || []).length ? env.gpus.join("; ") : "없음(또는 nvidia-smi 없음)"], env.cuda ? ["CUDA(드라이버)", env.cuda] : null,
      ["환경 변수", Object.keys(env.variables || {}).length ? h("details", {}, h("summary", {}, `${Object.keys(env.variables).length}개(비밀 이름 제외)`),
        h("pre", { class: "lab-pre" }, Object.entries(env.variables).map(([k, v]) => `${k}=${v}`).join("\n"))) : "없음"]]) : h("p", { class: "muted" }, "기록 없음")),
    sec("결과 파일", (r.outputs || []).length ? h("ul", { class: "lab-outputs" }, ...r.outputs.map((o, i) => h("li", {},
      h("span", { title: o.abs || o.path }, o.path), h("small", { class: "muted" }, ` ${o.kind} · ${fmtSize(o.size)}`),
      h("button", { class: "btn small", onclick: () => labPreview(r, i) }, o.kind === "image" ? "보기" : "미리 보기·지표 뽑기")))) : h("p", { class: "muted" }, "붙은 결과 파일이 없습니다.")),
    sec("지표", metrics.length ? h("table", { class: "lab-table" }, h("thead", {}, h("tr", {}, ...["지표", "값", "단위", "출처", ""].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", {}, ...metrics.map(([k, m]) => h("tr", {}, h("td", {}, k), h("td", { class: "num" }, labNum(m.value)), h("td", {}, m.unit || "—"),
        h("td", { class: "lab-src" }, labSource(m.source)),
        h("td", {}, h("button", { class: "link-btn", "aria-label": `${k} 지표 빼기`, onclick: async () => {
          if (await labCall(api().lab_metric_delete(r.id, k))) await labLoad(LAB.exp.id);
        } }, "빼기")))))) : h("p", { class: "muted" }, "지표가 없습니다. 결과 파일에서 열을 고르거나 직접 적으세요."),
    h("button", { class: "btn small", onclick: () => labManualMetric(r) }, "+ 지표 직접 적기")),
    sec("메모", notes, h("button", { class: "btn small", onclick: async () => {
      if (await labCall(api().lab_run_update(r.id, { notes: notes.value }))) { toast("메모를 저장했습니다"); await labLoad(LAB.exp.id); }
    } }, "메모 저장")),
    sec(r.status === "running" ? "출력(실시간)" : "출력 끝부분", h("pre", { class: "lab-pre lab-log", id: "lab-log", "aria-live": "off" }, live || r.log_tail || "(출력 없음)")));
}

function labSource(s) {
  if (!s) return "—";
  if (s.manual) return "직접 입력";
  const where = s.column ? `열 '${s.column}'${s.row ? ` ${s.row}행` : ""}` : s.json_path ? `값 '${s.json_path}'` : s.line ? `${s.line}번 줄` : "";
  return `${s.file || ""} ${where} · ${LAB_HOW[s.how] || s.how || ""}`.trim();
}

async function labOpenCode(path, line) {
  if (!window.codeOpenFile) return toast("Code 화면을 열 수 없습니다");
  await codeOpenFile(path, line);
}

function labRename(r) {
  const name = h("input", { type: "text", value: r.name || "", "aria-label": "Run 이름", maxlength: 200 });
  modal({ title: "Run 이름 바꾸기", body: name, buttons: [{ label: "취소", value: null }, { label: "저장", class: "primary", action: async (close) => {
    if (await labCall(api().lab_run_update(r.id, { name: name.value }))) { close(true); await labLoad(LAB.exp.id); }
  } }] });
}

function labDeleteRun(r) {
  modal({ title: "Run 기록 지우기", body: h("p", {}, `Run #${r.seq}의 기록을 지웁니다. 결과 원본 파일은 지우지 않습니다.`),
    buttons: [{ label: "취소", value: null }, { label: "기록 지우기", class: "danger", action: async (close) => {
      if (await labCall(api().lab_run_delete(r.id))) { close(true); LAB.selected.delete(r.id); LAB.runId = null; await labLoad(LAB.exp.id); }
    } }] });
}

function labManualMetric(r) {
  const name = h("input", { type: "text", placeholder: "이름(예: SNR)", "aria-label": "지표 이름" });
  const value = h("input", { type: "text", placeholder: "숫자", "aria-label": "값", inputmode: "decimal" });
  const unit = h("input", { type: "text", placeholder: "단위(예: dB, 선택)", "aria-label": "단위" });
  modal({ title: "지표 직접 적기", body: h("div", {}, h("p", { class: "muted" }, "출처는 '직접 입력'으로 남습니다."), name, value, unit),
    buttons: [{ label: "취소", value: null }, { label: "저장", class: "primary", action: async (close) => {
      if (await labCall(api().lab_metric_set(r.id, name.value, value.value, unit.value))) { close(true); await labLoad(LAB.exp.id); }
    } }] });
}

async function labPreview(r, index) {
  const res = await labCall(api().lab_file(r.id, index, 0, 50));
  if (!res) return;
  const warn = (res.warnings || []).map((w) => h("p", { class: "code-warn" }, w));
  if (res.kind === "image") {
    // SVG도 <img>로만 보인다: 그 안의 스크립트는 실행되지 않는다
    return modal({ title: res.ref.path, wide: true, body: h("div", {}, ...warn, h("img", { class: "lab-img", src: res.src, alt: res.ref.path })), buttons: [{ label: "닫기", value: null }] });
  }
  const t = res.table;
  const table = h("div", { class: "lab-table-wrap" }, h("table", { class: "lab-table" },
    h("thead", {}, h("tr", {}, ...t.columns.map((c) => h("th", { scope: "col" }, c)))),
    h("tbody", {}, ...t.rows.map((row) => h("tr", {}, ...row.map((c) => h("td", {}, c == null ? "" : String(c))))))));
  const choices = [];
  const choiceRow = (label, base, unit) => {
    const on = h("input", { type: "checkbox", "aria-label": `${label} 지표로 쓰기` });
    const how = h("select", { "aria-label": "고르는 방식" }, ...Object.entries(LAB_HOW).map(([k, v]) => h("option", { value: k }, v)));
    const name = h("input", { type: "text", class: "code-input", value: "", placeholder: "지표 이름(비우면 열 이름)", "aria-label": "지표 이름" });
    const u = h("input", { type: "text", class: "code-input", value: unit || "", placeholder: "단위", "aria-label": "단위" });
    choices.push(() => (on.checked ? { ...base, how: base.key ? (how.value === "first" ? "first" : "last") : how.value, name: name.value, unit: u.value } : null));
    return h("div", { class: "lab-choice" }, h("label", {}, on, ` ${label}`), base.key ? null : how, name, u);
  };
  const rows = [
    ...(res.numeric || []).map((c) => choiceRow(`열 '${c.column}' (숫자 ${c.stats.numeric}/${c.stats.count}, 최소 ${labNum(c.stats.min)} · 최대 ${labNum(c.stats.max)})`, { column: c.column }, c.unit)),
    ...(res.keys || []).slice(0, 60).map((k) => choiceRow(`'${k.key}' = ${labNum(k.value)}`, { key: k.key }, k.unit)),
  ];
  const remember = h("input", { type: "checkbox", checked: true, "aria-label": "다음 Run에도 같은 규칙" });
  modal({ title: `${res.ref.path} · ${t.total}행`, wide: true, body: h("div", {}, ...warn, table,
    t.total > t.rows.length ? h("small", { class: "muted" }, `앞 ${t.rows.length}행만 보입니다.`) : null,
    h("h3", {}, "지표로 쓸 값 고르기"),
    h("p", { class: "muted" }, "고른 열·값만 지표가 됩니다. 숫자가 아닌 칸(빈 칸·NaN·글자)은 빼고 계산하고 알려 드립니다."),
    rows.length ? h("div", { class: "lab-choices" }, ...rows) : h("p", { class: "muted" }, "숫자 열·값을 찾지 못했습니다."),
    h("label", { class: "lab-check" }, remember, " 다음 Run에도 이 파일 이름에서 같은 규칙으로 뽑기")),
  buttons: [{ label: "닫기", value: null }, { label: "그래프로 보기", action: (close) => { close(null); LAB.chart.file = res.ref.path; LAB.tab = "chart"; labDraw(); } },
    { label: "지표 저장", class: "primary", action: async (close) => {
      const spec = choices.map((f) => f()).filter(Boolean);
      if (!spec.length) return toast("지표로 쓸 열이나 값을 고르세요");
      const out = await labCall(api().lab_extract(r.id, index, spec, remember.checked));
      if (!out) return;
      close(true);
      toast(out.warnings.length ? `지표 ${Object.keys(out.metrics).length}개 저장 · 주의: ${out.warnings[0]}` : `지표 ${Object.keys(out.metrics).length}개를 저장했습니다`);
      await labLoad(LAB.exp.id);
    } }] });
}

/* ---------- 그래프 ---------- */

function labTableFiles() {
  const names = new Map();
  for (const r of LAB.exp.runs) (r.outputs || []).forEach((o, i) => {
    if (o.kind === "image" || o.kind === "other") return;
    if (!names.has(o.path)) names.set(o.path, []);
    names.get(o.path).push({ run: r, index: i });
  });
  return names;
}

function labChartTab() {
  const files = labTableFiles();
  const images = LAB.exp.runs.flatMap((r) => (r.outputs || []).map((o, i) => ({ r, o, i }))).filter((x) => x.o.kind === "image");
  const box = h("div", { class: "lab-chart-area" });
  if (!files.size) {
    return h("div", {}, h("p", { class: "muted" }, "그래프로 그릴 표 결과(CSV·TSV·JSON·JSONL)가 없습니다. 실행 설정의 결과 파일 패턴을 넣거나 결과를 가져오세요."), labImages(images));
  }
  const c = LAB.chart;
  if (!files.has(c.file)) c.file = [...files.keys()][0];
  const fileSel = h("select", { "aria-label": "결과 파일" }, ...[...files.keys()].map((f) => h("option", { value: f, selected: f === c.file }, `${f} (Run ${files.get(f).length}개)`)));
  const type = h("select", { "aria-label": "그래프 종류" }, ...[["line", "선"], ["scatter", "점"], ["bar", "막대(마지막 값)"]].map(([k, v]) => h("option", { value: k, selected: c.type === k }, v)));
  const xSel = h("select", { "aria-label": "X축 열" });
  const ySel = h("div", { class: "lab-ycols", role: "group", "aria-label": "Y축 열" });
  const holders = files.get(c.file);
  const chosenRuns = holders.filter((x) => !LAB.selected.size || LAB.selected.has(x.run.id));
  const runsNote = h("small", { class: "muted" }, LAB.selected.size ? `고른 Run ${chosenRuns.length}개를 겹쳐 그립니다.` : `Run ${holders.length}개를 겹쳐 그립니다(개요에서 골라 줄일 수 있음).`);
  const draw = async () => {
    c.x = xSel.value;
    c.y = [...ySel.querySelectorAll("input:checked")].map((i) => i.value);
    c.type = type.value;
    if (!c.y.length) return fill(box, h("p", { class: "muted" }, "Y축 열을 고르세요."));
    const items = (chosenRuns.length ? chosenRuns : holders).slice(0, 8).map((x) => ({ run_id: x.run.id, index: x.index, x: c.type === "bar" ? "" : c.x, y: c.y }));
    const res = await labCall(api().lab_series(items));
    if (!res) return;
    fill(box, labSvgChart(res.series, c.type), labStatsTable(res.series));
  };
  fileSel.addEventListener("change", () => { c.file = fileSel.value; c.x = ""; c.y = []; labDraw(); });
  type.addEventListener("change", draw);
  xSel.addEventListener("change", draw);
  // 열 목록은 첫 Run의 파일에서
  labCall(api().lab_file(holders[0].run.id, holders[0].index, 0, 1)).then((res) => {
    if (!res || !res.table) return;
    const cols = res.table.columns;
    const numeric = (res.numeric || []).map((n) => n.column);
    fill(xSel, h("option", { value: "" }, "(행 번호)"), ...cols.map((col) => h("option", { value: col, selected: col === c.x }, col)));
    if (!c.x && numeric.length > 1) { c.x = numeric[0]; xSel.value = c.x; }
    if (!c.y.length) c.y = numeric.filter((n) => n !== c.x).slice(0, 1);
    fill(ySel, ...numeric.map((col) => h("label", { class: "lab-check" }, h("input", { type: "checkbox", value: col, checked: c.y.includes(col), onchange: draw }), ` ${col}`)));
    draw();
  });
  return h("div", {},
    h("div", { class: "row wrap lab-toolbar" }, fileSel, type, h("label", {}, "X ", xSel)), ySel, runsNote, box, labImages(images));
}

function labImages(images) {
  if (!images.length) return null;
  return h("section", { class: "lab-sec" }, h("h3", {}, "그림 결과"), h("div", { class: "row wrap" },
    ...images.slice(0, 12).map(({ r, o, i }) => h("button", { class: "btn small", onclick: () => labPreview(r, i) }, `#${r.seq} ${o.path}`))));
}

function labSvgChart(series, type) {
  const W = 720, H = 360, L = 64, R = 16, T = 16, B = 48;
  const lines = [];
  series.forEach((s, si) => s.series.forEach((col, ci) => lines.push({ label: `${s.label}${s.series.length > 1 ? " · " + col.name : ""}`, col, run: s, color: LAB_COLORS[(si * s.series.length + ci) % LAB_COLORS.length] })));
  const units = new Set(lines.map((l) => l.col.unit || ""));
  const notes = [];
  if (units.size > 1) notes.push(`Y축 단위가 섞여 있습니다(${[...units].map((u) => u || "단위 없음").join(", ")}). 같은 축에서 비교하지 마세요.`);
  const sampled = series.filter((s) => s.sampled);
  if (sampled.length) notes.push(`점이 많아 고르게 뽑은 표본만 그렸습니다(최대 2000점, 전체 ${sampled.map((s) => s.total).join("·")}행). 아래 통계는 전체 데이터로 계산했습니다.`);
  const skipped = lines.reduce((a, l) => a + l.col.skipped, 0);
  if (skipped) notes.push(`숫자가 아닌 점 ${skipped}개(빈 칸·NaN·글자)는 그리지 않았습니다.`);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "lab-svg");
  svg.setAttribute("role", "img");
  const yUnit = units.size === 1 ? [...units][0] : "";
  const names = new Set(lines.map((l) => l.col.name));
  const yName = names.size === 1 ? [...names][0] : "값";
  svg.setAttribute("aria-label", `${type === "bar" ? "막대" : type === "scatter" ? "점" : "선"} 그래프: ${lines.map((l) => l.label).join(", ")}`);
  const el = (tag, attrs, text) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    svg.append(n);
    return n;
  };
  let xs = [], ys = [];
  if (type === "bar") {
    ys = lines.map((l) => l.col.stats.last).filter((v) => v != null);
  } else {
    for (const l of lines) for (const [x, y] of l.col.points) { xs.push(x); ys.push(y); }
  }
  if (!ys.length) {
    const p = h("p", { class: "muted" }, "그릴 숫자 값이 없습니다.");
    return h("div", {}, ...notes.map((n) => h("p", { class: "code-warn" }, n)), p);
  }
  const ext = (a) => { let lo = Math.min(...a), hi = Math.max(...a); if (lo === hi) { lo -= 1; hi += 1; } return [lo, hi]; };
  const [y0, y1] = type === "bar" ? ext([0, ...ys]) : ext(ys);
  const [x0, x1] = type === "bar" ? [0, lines.length] : ext(xs);
  const sx = (x) => L + (x - x0) / (x1 - x0) * (W - L - R);
  const sy = (y) => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
  el("rect", { x: L, y: T, width: W - L - R, height: H - T - B, class: "lab-plot-bg" });
  for (let i = 0; i <= 4; i++) {
    const yv = y0 + (y1 - y0) * i / 4;
    el("line", { x1: L, x2: W - R, y1: sy(yv), y2: sy(yv), class: "lab-grid" });
    el("text", { x: L - 6, y: sy(yv) + 4, class: "lab-tick", "text-anchor": "end" }, labNum(yv));
    if (type !== "bar") {
      const xv = x0 + (x1 - x0) * i / 4;
      el("text", { x: sx(xv), y: H - B + 16, class: "lab-tick", "text-anchor": "middle" }, labNum(xv));
    }
  }
  const xr = series[0];
  el("text", { x: (L + W - R) / 2, y: H - 8, class: "lab-axis", "text-anchor": "middle" }, type === "bar" ? "Run" : `${xr.x}${xr.x_unit ? ` (${xr.x_unit})` : ""}`);
  el("text", { x: 14, y: (T + H - B) / 2, class: "lab-axis", "text-anchor": "middle", transform: `rotate(-90 14 ${(T + H - B) / 2})` }, `${yName}${yUnit ? ` (${yUnit})` : ""}`);
  lines.forEach((l, i) => {
    if (type === "bar") {
      const v = l.col.stats.last;
      if (v == null) return;
      const bw = (W - L - R) / lines.length * 0.7;
      const x = sx(i) + (W - L - R) / lines.length * 0.15;
      const top = sy(Math.max(v, 0)), bottom = sy(Math.min(v, 0));
      el("rect", { x, y: top, width: bw, height: Math.max(1, bottom - top), fill: l.color }).append(Object.assign(document.createElementNS("http://www.w3.org/2000/svg", "title"), { textContent: `${l.label}: ${labNum(v)}` }));
      el("text", { x: x + bw / 2, y: H - B + 16, class: "lab-tick", "text-anchor": "middle" }, `#${l.run.seq}`);
    } else if (type === "scatter") {
      for (const [x, y] of l.col.points) el("circle", { cx: sx(x), cy: sy(y), r: 2.5, fill: l.color });
    } else {
      const d = l.col.points.map(([x, y], j) => `${j ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join("");
      if (d) el("path", { d, fill: "none", stroke: l.color, "stroke-width": 1.8 });
    }
  });
  const legend = h("div", { class: "lab-legend" }, ...lines.map((l) => h("span", {}, h("i", { style: `background:${l.color}` }), l.label)));
  return h("div", {}, ...notes.map((n) => h("p", { class: "code-warn" }, n)), svg, legend);
}

function labStatsTable(series) {
  const rows = series.flatMap((s) => s.series.map((col) => ({ s, col })));
  return h("div", { class: "lab-table-wrap" }, h("table", { class: "lab-table" },
    h("caption", { class: "muted" }, "통계(전체 데이터)"),
    h("thead", {}, h("tr", {}, ...["Run", "열", "개수", "숫자", "최소", "최대", "평균", "표준편차", "마지막", "빠진 칸"].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", {}, ...rows.map(({ s, col }) => h("tr", {}, h("td", {}, s.label), h("td", {}, `${col.column}`),
      h("td", { class: "num" }, col.stats.count), h("td", { class: "num" }, col.stats.numeric),
      ...["min", "max", "mean", "std", "last"].map((k) => h("td", { class: "num" }, labNum(col.stats[k]))),
      h("td", { class: "num" }, col.stats.empty + col.stats.nan + col.stats.inf + col.stats.text))))));
}

/* ---------- 비교·AI ---------- */

function labCompareTab() {
  const ids = [...LAB.selected];
  const out = h("div", {});
  const askBox = labAskBox(ids);
  if (ids.length < 2) {
    out.append(h("p", { class: "muted" }, "개요에서 비교할 Run을 두 개 이상 고르세요."));
    out.append(askBox);
    return out;
  }
  out.append(h("p", { class: "muted" }, "불러오는 중..."));
  labCall(api().lab_compare(ids)).then((res) => {
    if (!res) return;
    const c = res.compare;
    const head = h("tr", {}, h("th", { scope: "col" }, ""), ...c.runs.map((r) => h("th", { scope: "col", title: r.id }, `#${r.seq} ${r.name || ""}`)));
    const row = (label, cells, cls = "") => h("tr", { class: cls }, h("th", { scope: "row" }, label), ...cells.map((x) => h("td", {}, x)));
    const body = [
      row("상태", c.runs.map((r) => (LAB.state.statuses || {})[r.status] || r.status)),
      row("시간", c.runs.map((r) => labDur(r.seconds))),
      row("종료 코드", c.runs.map((r) => r.exit_code ?? "—")),
      ...c.params.map((p) => row(`파라미터 ${p.name}`, p.values.map((v) => v == null ? "—" : String(v)), p.differs ? "lab-diff" : "")),
      row("커밋", c.code.map((x) => `${String(x.commit || "—").slice(0, 10)}${x.dirty ? " +변경" : ""}`), new Set(c.code.map((x) => x.commit)).size > 1 ? "lab-diff" : ""),
      row("환경", c.env.map((x) => `${x.os || "—"} · Python ${x.python || "—"}`), new Set(c.env.map((x) => x.os + x.python)).size > 1 ? "lab-diff" : ""),
      ...c.metrics.map((m) => row(`지표 ${m.name}`, m.values.map((v, i) => {
        if (v == null) return "—";
        const mark = m.comparable && c.runs.length > 1 && (v === m.max ? " ▲" : v === m.min ? " ▼" : "");
        return `${labNum(v)}${m.units[i] ? " " + m.units[i] : ""}${mark || ""}`;
      }), m.comparable ? "" : "lab-warn-row")),
      row("결과 파일", c.runs.map((r) => (r.outputs || []).join(", ") || "—")),
    ];
    fill(out, (c.warnings || []).length ? h("div", { class: "code-warn" }, h("strong", {}, "비교 주의"), h("ul", {}, ...c.warnings.map((w) => h("li", {}, w)))) : null,
      h("div", { class: "lab-table-wrap" }, h("table", { class: "lab-table lab-compare" }, h("thead", {}, head), h("tbody", {}, ...body))),
      h("small", { class: "muted" }, "▲ 가장 큰 값 · ▼ 가장 작은 값(단위가 같을 때만). 좋고 나쁨은 지표마다 다르니 직접 판단하세요. 노란 줄은 Run마다 다른 조건입니다."),
      askBox);
  });
  return out;
}

function labAskBox(ids) {
  const q = h("textarea", { rows: 2, placeholder: "직접 묻기(선택). 예: bits가 SNR에 미친 영향을 설명해 줘", "aria-label": "AI에게 물을 질문" });
  const memo = h("textarea", { rows: 3, placeholder: "프로젝트 기억에 남길 요약(직접 쓰거나 AI 답에서 골라 붙여 넣기)", "aria-label": "프로젝트 기억에 남길 요약" });
  const scope = ids.length ? `고른 Run ${ids.length}개` : "최근 Run(최대 8개)";
  return h("section", { class: "lab-sec" }, h("h3", {}, "AI 분석"),
    h("p", { class: "muted" }, `${scope}의 기록(파라미터·코드 버전·환경·지표와 출처·메모·출력 끝부분)만 채팅에 첨부합니다. 지금 고른 채팅 모델로 보내며, 보내기 전에 첨부를 확인할 수 있습니다. ` +
      "AI는 기록에 없는 값을 지어내지 않고 관찰과 해석을 나누도록 요청합니다. AI는 실험을 실행하지 않습니다."),
    h("div", { class: "row wrap" },
      h("button", { class: "btn small", onclick: () => labAsk("summary") }, "결과 요약"),
      h("button", { class: "btn small", disabled: ids.length < 2, onclick: () => labAsk("compare") }, "Run 비교 해석"),
      h("button", { class: "btn small", onclick: () => labAsk("anomaly") }, "실패·이상 찾기"),
      h("button", { class: "btn small", onclick: () => labAsk("next") }, "다음 실험 제안")),
    q, h("button", { class: "btn small", onclick: () => labAsk("custom", q.value) }, "이 질문으로 묻기"),
    h("h3", {}, "프로젝트 기억에 남기기"),
    h("p", { class: "muted" }, "남긴 요약은 이 작업 폴더의 프로젝트 기억(설정 → 기억)에 들어가 다음 대화에서 찾아 씁니다. 자동으로 남기지 않습니다."),
    memo, h("button", { class: "btn small", onclick: async () => {
      const r = await labCall(api().lab_remember(LAB.exp.id, memo.value, `Lab: ${LAB.exp.name}`, "result"));
      if (r) { toast(r.created ? "프로젝트 기억에 남겼습니다" : "이미 같은 내용이 있습니다"); memo.value = ""; }
    } }, "기억에 남기기"));
}

async function labAsk(preset, question = "") {
  if (S.attach.length >= S.attachLimits.max_files) return toast(`파일은 한 번에 ${S.attachLimits.max_files}개까지 첨부할 수 있습니다`);
  const res = await labCall(api().lab_ask(LAB.exp.id, [...LAB.selected], preset, question));
  if (!res) return;
  pageLeave();
  for (const a of res.attachments) S.attach.push({ id: a.id, name: a.name, size: a.size, kind: a.kind, status: "ready", progress: 1 });
  renderTray();
  const input = $("#input");
  if (!input.value.trim()) input.value = res.question;
  autoresize();
  updateSend();
  input.focus();
  toast(`실험 기록(Run ${res.runs.length}개)을 첨부했습니다. 확인하고 보내세요`);
}

/* ---------- 백엔드 이벤트 ---------- */

function labEvent(ev) {
  if (ev.kind !== "run" || !ev.run) return;
  if (PAGE.id !== "lab" || !LAB.exp || ev.run.experiment_id !== LAB.exp.id) return;
  const i = LAB.exp.runs.findIndex((r) => r.id === ev.run.id);
  if (i >= 0) LAB.exp.runs[i] = ev.run; else LAB.exp.runs.push(ev.run);
  labDraw();
}

// 실행 중인 Run의 출력(Code 실행기의 run_output 이벤트)
function labCodeEvent(ev) {
  if (ev.kind === "run_start" && ev.run && String(ev.run.purpose || "").startsWith("Lab ")) LAB.live.set(ev.run.id, "");
  if (ev.kind !== "run_output") return;
  const cur = LAB.live.get(ev.id);
  if (cur == null && !(LAB.exp && LAB.exp.runs.some((r) => r.code_run_id === ev.id))) return;
  const text = ((cur || "") + ev.text).slice(-200000);
  LAB.live.set(ev.id, text);
  const run = LAB.exp && LAB.exp.runs.find((r) => r.id === LAB.runId);
  const pre = $("#lab-log");
  if (pre && run && run.code_run_id === ev.id && PAGE.id === "lab" && LAB.tab === "run") {
    const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    pre.textContent = text;
    if (atEnd) pre.scrollTop = pre.scrollHeight;
  }
}

$("#btn-lab")?.addEventListener("click", () => pageOpen("lab"));
window.labEvent = labEvent;
window.labCodeEvent = labCodeEvent;
