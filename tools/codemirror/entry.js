// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
/* POSCHAT Code(1.15) 편집기 묶음의 입구. build.mjs가 esbuild로 web/vendor/codemirror/codemirror.min.js(전역 CM)를 만든다.
   화면(web/code.js)은 CM.createEditor(...)만 쓴다. CodeMirror 6 패키지는 MIT 라이선스(licenses/codemirror/).

   언어 지원 범위(사실대로 표시한다):
   - 문법 트리(Lezer): Python, C, C++, JavaScript, TypeScript, JSX/TSX, JSON, Markdown, HTML, CSS — 강조·들여쓰기·접기·블록 인식
   - 줄 단위 강조(CodeMirror 5 legacy 모드): Verilog, SystemVerilog(IEEE 1800 키워드 포함), Tcl, Shell — 키워드·주석·문자열·숫자
     강조와 들여쓰기만, 접기·구조 인식 없음
   - SPICE 넷리스트: 이 묶음의 간단한 규칙(주석·점 명령·소자 이름·숫자 단위)만 */
import { EditorState, Compartment, EditorSelection } from "@codemirror/state";
import {
  EditorView, keymap, lineNumbers, highlightActiveLineGutter, highlightActiveLine, drawSelection,
  dropCursor, rectangularSelection, crosshairCursor, highlightSpecialChars,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab, undo, redo } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches, openSearchPanel } from "@codemirror/search";
import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import {
  syntaxHighlighting, defaultHighlightStyle, indentOnInput, bracketMatching, foldGutter, foldKeymap,
  StreamLanguage, syntaxTree, indentUnit,
} from "@codemirror/language";
import { oneDarkHighlightStyle } from "@codemirror/theme-one-dark";
import { python } from "@codemirror/lang-python";
import { cpp } from "@codemirror/lang-cpp";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { html } from "@codemirror/lang-html";
import { css } from "@codemirror/lang-css";
import { verilog } from "@codemirror/legacy-modes/mode/verilog";
import { tcl } from "@codemirror/legacy-modes/mode/tcl";
import { shell } from "@codemirror/legacy-modes/mode/shell";

/* SPICE 넷리스트: 첫 줄 제목, * 주석, ; $ 줄 끝 주석, .명령, + 이어 쓰기, 소자 이름, 단위 붙은 숫자 */
const spice = {
  name: "spice",
  startState: () => ({ line: 0 }),
  token(stream) {
    if (stream.sol() && stream.match(/^\s*\*.*/)) return "comment";
    if (stream.match(/^[;$].*/)) return "comment";
    if (stream.sol()) {
      if (stream.match(/^\s*\.[A-Za-z_]+/)) return "keyword";
      if (stream.match(/^\s*\+/)) return "operator";
      if (stream.match(/^\s*[A-Za-z][\w.]*/)) return "def";
    }
    if (stream.eatSpace()) return null;
    if (stream.match(/^'[^']*'?/) || stream.match(/^\{[^}]*\}?/)) return "string";
    if (stream.match(/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?(meg|mil|[tgkmunpfa])?[a-z]*/i)) return "number";
    if (stream.match(/^[=(),]/)) return "operator";
    stream.next();
    return null;
  },
};

const LANGS = {
  python: { label: "Python", tree: true, make: () => python() },
  c: { label: "C", tree: true, make: () => cpp() },
  cpp: { label: "C++", tree: true, make: () => cpp() },
  javascript: { label: "JavaScript", tree: true, make: () => javascript() },
  jsx: { label: "JavaScript (JSX)", tree: true, make: () => javascript({ jsx: true }) },
  typescript: { label: "TypeScript", tree: true, make: () => javascript({ typescript: true }) },
  tsx: { label: "TypeScript (TSX)", tree: true, make: () => javascript({ typescript: true, jsx: true }) },
  json: { label: "JSON", tree: true, make: () => json() },
  markdown: { label: "Markdown", tree: true, make: () => markdown() },
  html: { label: "HTML", tree: true, make: () => html() },
  css: { label: "CSS", tree: true, make: () => css() },
  verilog: { label: "Verilog", tree: false, make: () => StreamLanguage.define(verilog) },
  systemverilog: { label: "SystemVerilog", tree: false, make: () => StreamLanguage.define(verilog) },
  tcl: { label: "Tcl", tree: false, make: () => StreamLanguage.define(tcl) },
  shell: { label: "Shell", tree: false, make: () => StreamLanguage.define(shell) },
  spice: { label: "SPICE", tree: false, make: () => StreamLanguage.define(spice) },
  text: { label: "일반 텍스트", tree: false, make: () => [] },
};

const EXT = {
  py: "python", pyw: "python", pyi: "python",
  c: "c", h: "c",
  cc: "cpp", cpp: "cpp", cxx: "cpp", "c++": "cpp", hpp: "cpp", hh: "cpp", hxx: "cpp", ipp: "cpp", inl: "cpp",
  js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "jsx",
  ts: "typescript", mts: "typescript", cts: "typescript", tsx: "tsx",
  json: "json", jsonc: "json",
  md: "markdown", markdown: "markdown",
  html: "html", htm: "html",
  css: "css",
  v: "verilog", vh: "verilog", vl: "verilog",
  sv: "systemverilog", svh: "systemverilog", svi: "systemverilog",
  tcl: "tcl", sdc: "tcl", xdc: "tcl", upf: "tcl",
  sh: "shell", bash: "shell", zsh: "shell", ksh: "shell",
  sp: "spice", spi: "spice", spice: "spice", cir: "spice", ckt: "spice", net: "spice", lib: "spice",
};

function languageFor(path) {
  const name = String(path || "").split(/[\\/]/).pop().toLowerCase();
  if (name === "makefile" || name === "dockerfile") return "text";
  if (/^\.?(bashrc|zshrc|profile|bash_profile)$/.test(name)) return "shell";
  const ext = name.includes(".") ? name.split(".").pop() : "";
  return EXT[ext] || "text";
}

const PHRASES = {
  "Find": "찾기", "Replace": "바꿀 내용", "next": "다음", "previous": "이전", "all": "모두",
  "match case": "대소문자 구분", "regexp": "정규식", "by word": "단어 단위", "replace": "바꾸기",
  "replace all": "모두 바꾸기", "close": "닫기", "Go to line": "줄로 이동", "go": "이동",
  "current match": "현재 일치", "on line": "줄", "replaced match on line $": "$번째 줄에서 바꿈",
  "replaced $ matches": "$개를 바꿈", "Folded lines": "접힌 줄", "Unfolded lines": "펼친 줄", "to": "~",
  "folded code": "접힌 코드", "unfold": "펼치기", "Fold line": "줄 접기", "Unfold line": "줄 펼치기",
  "Control character": "제어 문자", "Selection deleted": "선택한 부분을 지움",
};

const baseTheme = EditorView.theme({
  "&": { height: "100%", fontSize: "13px", backgroundColor: "var(--bg)", color: "var(--text)" },
  ".cm-scroller": { fontFamily: "var(--mono)", lineHeight: "1.55" },
  ".cm-content": { caretColor: "var(--text)" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--text)" },
  ".cm-gutters": { backgroundColor: "var(--bubble)", color: "var(--text-3)", borderRight: "1px solid var(--border)" },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--hover) 60%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--hover)", color: "var(--text)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: "color-mix(in srgb, #3b82f6 28%, transparent) !important" },
  ".cm-panels": { backgroundColor: "var(--bubble)", color: "var(--text)" },
  ".cm-panels.cm-panels-top": { borderBottom: "1px solid var(--border)" },
  ".cm-panel input, .cm-panel button, .cm-panel label": { fontSize: "12.5px" },
  ".cm-textfield": { backgroundColor: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "6px" },
  ".cm-button": { backgroundImage: "none", backgroundColor: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "6px" },
  ".cm-searchMatch": { backgroundColor: "color-mix(in srgb, #f59e0b 30%, transparent)" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "color-mix(in srgb, #f59e0b 55%, transparent)" },
  ".cm-foldPlaceholder": { backgroundColor: "var(--hover)", border: "none", color: "var(--text-2)" },
  ".cm-tooltip": { backgroundColor: "var(--bg)", border: "1px solid var(--border)" },
});

/* 커서가 있는 함수·클래스·블록의 줄 범위 [from, to](1부터). 문법 트리가 있으면 트리로, 없으면 줄 모양으로 찾는다. */
const BLOCK_NODES = /^(FunctionDefinition|ClassDefinition|DecoratedStatement|FunctionDeclaration|ClassDeclaration|MethodDeclaration|ArrowFunction|FunctionExpression|ClassSpecifier|StructSpecifier|NamespaceDefinition|EnumSpecifier|UnionSpecifier|RuleSet|Element)$/;
const RTL_HEAD = /^\s*(module|macromodule|interface|program|package|class|function|task|always|always_ff|always_comb|always_latch|initial|final|generate)\b/;
const RTL_END = { module: /^\s*endmodule\b/, macromodule: /^\s*endmodule\b/, interface: /^\s*endinterface\b/,
  program: /^\s*endprogram\b/, package: /^\s*endpackage\b/, class: /^\s*endclass\b/, function: /^\s*endfunction\b/,
  task: /^\s*endtask\b/, generate: /^\s*endgenerate\b/ };

function blockRange(state, langId) {
  const pos = state.selection.main.head;
  const doc = state.doc;
  if (LANGS[langId] && LANGS[langId].tree) {
    let node = syntaxTree(state).resolveInner(pos, -1);
    for (; node; node = node.parent) {
      if (BLOCK_NODES.test(node.name)) {
        return { from: doc.lineAt(node.from).number, to: doc.lineAt(node.to).number, kind: node.name };
      }
    }
  }
  const at = doc.lineAt(pos).number;
  if (langId === "verilog" || langId === "systemverilog") {
    for (let n = at; n >= 1; n--) {
      const m = RTL_HEAD.exec(doc.line(n).text);
      if (!m) continue;
      const end = RTL_END[m[1]];
      if (end) {
        for (let k = n; k <= doc.lines; k++) if (end.test(doc.line(k).text)) {
          if (k >= at) return { from: n, to: k, kind: m[1] };
          break;
        }
        continue;
      }
      // always·initial: begin…end 짝을 센다
      let depth = 0, seen = false;
      for (let k = n; k <= doc.lines; k++) {
        const text = doc.line(k).text.replace(/\/\/.*$/, "");
        const opens = (text.match(/\bbegin\b|\bfork\b|\bcase[xz]?\b/g) || []).length;
        const closes = (text.match(/\bend\b|\bjoin(_any|_none)?\b|\bendcase\b/g) || []).length;
        depth += opens - closes;
        if (opens) seen = true;
        if ((seen && depth <= 0) || (!seen && k > n && /;\s*$/.test(text))) {
          if (k >= at) return { from: n, to: k, kind: m[1] };
          break;
        }
      }
    }
  }
  // 그 밖: 들여쓰기가 같은 문단(빈 줄로 나뉜 덩어리)
  let from = at, to = at;
  while (from > 1 && doc.line(from - 1).text.trim()) from--;
  while (to < doc.lines && doc.line(to + 1).text.trim()) to++;
  return { from, to, kind: "paragraph" };
}

function createEditor(opts) {
  const langC = new Compartment(), roC = new Compartment(), wrapC = new Compartment(), themeC = new Compartment();
  let langId = LANGS[opts.lang] ? opts.lang : "text";
  let saved = null;
  const highlight = (dark) => syntaxHighlighting(dark ? oneDarkHighlightStyle : defaultHighlightStyle, { fallback: true });
  const listeners = EditorView.updateListener.of((u) => {
    if (u.docChanged && opts.onChange) opts.onChange(api);
    if ((u.selectionSet || u.docChanged) && opts.onCursor) opts.onCursor(api);
  });
  const saveKeys = keymap.of([
    { key: "Mod-s", preventDefault: true, run: () => { if (opts.onSave) opts.onSave(api); return true; } },
    { key: "Mod-h", preventDefault: true, run: (v) => openSearchPanel(v) },
  ]);
  const state = EditorState.create({
    doc: opts.doc || "",
    extensions: [
      EditorState.phrases.of(PHRASES),
      lineNumbers(), highlightActiveLineGutter(), highlightSpecialChars(), history(), foldGutter(), drawSelection(),
      dropCursor(), EditorState.allowMultipleSelections.of(true), indentOnInput(), bracketMatching(), closeBrackets(),
      rectangularSelection(), crosshairCursor(), highlightActiveLine(), highlightSelectionMatches(),
      indentUnit.of(opts.indent || "    "), EditorState.tabSize.of(opts.tabSize || 4),
      saveKeys,
      keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap, ...foldKeymap, indentWithTab]),
      baseTheme,
      themeC.of([highlight(!!opts.dark), EditorView.theme({}, { dark: !!opts.dark })]),
      langC.of(LANGS[langId].make()),
      roC.of([EditorState.readOnly.of(!!opts.readOnly), EditorView.editable.of(!opts.readOnly)]),
      wrapC.of(opts.wrap ? EditorView.lineWrapping : []),
      listeners,
      EditorView.contentAttributes.of({ "aria-label": opts.label || "코드 편집기", spellcheck: "false" }),
    ],
  });
  const view = new EditorView({ state, parent: opts.parent });
  saved = view.state.doc;

  const api = {
    view,
    get lang() { return langId; },
    setLanguage(id) {
      langId = LANGS[id] ? id : "text";
      view.dispatch({ effects: langC.reconfigure(LANGS[langId].make()) });
    },
    setReadOnly(ro) {
      view.dispatch({ effects: roC.reconfigure([EditorState.readOnly.of(!!ro), EditorView.editable.of(!ro)]) });
    },
    setWrap(on) { view.dispatch({ effects: wrapC.reconfigure(on ? EditorView.lineWrapping : []) }); },
    setDark(dark) { view.dispatch({ effects: themeC.reconfigure([highlight(dark), EditorView.theme({}, { dark })]) }); },
    getText() { return view.state.doc.toString(); },
    setText(text, keepClean = true) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
      if (keepClean) saved = view.state.doc;
    },
    isDirty() { return !view.state.doc.eq(saved); },
    markClean() { saved = view.state.doc; },
    undo() { return undo(view); },
    redo() { return redo(view); },
    find() { return openSearchPanel(view); },
    selection() {
      const r = view.state.selection.main;
      const doc = view.state.doc;
      const a = doc.lineAt(r.from), b = doc.lineAt(r.to);
      // 줄 맨 앞에서 끝난 선택은 그 줄을 넣지 않는다
      const endLine = r.to > r.from && r.to === b.from && b.number > a.number ? b.number - 1 : b.number;
      return { empty: r.empty, text: doc.sliceString(r.from, r.to), fromLine: a.number, toLine: endLine,
        cursorLine: doc.lineAt(r.head).number, cursorCol: r.head - doc.lineAt(r.head).from + 1, lines: doc.lines };
    },
    lineText(from, to) {
      const doc = view.state.doc;
      from = Math.max(1, Math.min(doc.lines, from));
      to = Math.max(from, Math.min(doc.lines, to));
      return doc.sliceString(doc.line(from).from, doc.line(to).to);
    },
    blockRange() { return blockRange(view.state, langId); },
    gotoLine(line, col = 1) {
      const doc = view.state.doc;
      const l = doc.line(Math.max(1, Math.min(doc.lines, line || 1)));
      const pos = Math.min(l.to, l.from + Math.max(0, (col || 1) - 1));
      view.dispatch({ selection: EditorSelection.cursor(pos), effects: EditorView.scrollIntoView(pos, { y: "center" }) });
      view.focus();
    },
    selectLines(from, to) {
      const doc = view.state.doc;
      const a = doc.line(Math.max(1, Math.min(doc.lines, from))), b = doc.line(Math.max(1, Math.min(doc.lines, to)));
      view.dispatch({ selection: EditorSelection.range(a.from, b.to), effects: EditorView.scrollIntoView(a.from, { y: "center" }) });
    },
    focus() { view.focus(); },
    destroy() { view.destroy(); },
  };
  return api;
}

export const VERSION = "codemirror 6 (POSCHAT 1.15 bundle)";
export { createEditor, languageFor, LANGS, blockRange };
