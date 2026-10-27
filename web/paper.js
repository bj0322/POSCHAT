// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
"use strict";

/* ---------- 논문 읽기(1.14): 채팅 옆 PDF ----------
   PDF는 PDF.js(web/vendor/pdfjs)로 그린다. 바이트는 paper_chunk로 받고, 질문할 글자·쪽은 paper.py가 뽑는다.
   PDF 안의 스크립트·링크·양식은 쓰지 않는다(글자 층과 그림만 그린다). 논문의 글은 외부 데이터로 감싸 첨부한다. */

const PAPER = { open: false, doc: null, pdf: null, scale: 1.2, fit: true, page: 1, capture: false, busy: "",
  state: null, pick: new Set(), observer: null, rendered: new Map(), lib: null, loadToken: 0 };
const PAPER_ZOOMS = [0.6, 0.8, 1, 1.2, 1.5, 1.8, 2.2, 3];

function paperLib() {
  if (!PAPER.lib) {
    PAPER.lib = import("./vendor/pdfjs/pdf.min.js").then((lib) => {
      lib.GlobalWorkerOptions.workerSrc = new URL("vendor/pdfjs/pdf.worker.min.js", location.href).href;
      return lib;
    }).catch((e) => {
      PAPER.lib = null;
      throw new Error("PDF 보기 모듈을 불러오지 못했습니다: " + (e.message || e));
    });
  }
  return PAPER.lib;
}

function paperPane() {
  let pane = $("#paper-pane");
  if (pane) return pane;
  pane = h("section", { id: "paper-pane", "aria-label": "논문 읽기", hidden: true });
  const resizer = h("div", { id: "paper-resizer", role: "separator", "aria-orientation": "vertical", tabindex: "0",
    "aria-label": "논문 화면 너비 조절 (왼쪽·오른쪽 화살표)", title: "끌어서 너비 조절" });
  resizer.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    resizer.setPointerCapture(e.pointerId);
    const move = (ev) => paperSetWidth(window.innerWidth - ev.clientX);
    const up = () => {
      resizer.removeEventListener("pointermove", move);
      resizer.removeEventListener("pointerup", up);
      if (PAPER.fit) paperRelayout();
    };
    resizer.addEventListener("pointermove", move);
    resizer.addEventListener("pointerup", up);
  });
  resizer.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    paperSetWidth(pane.getBoundingClientRect().width + (e.key === "ArrowLeft" ? 40 : -40));
    if (PAPER.fit) paperRelayout();
  });
  $("#app").append(resizer, pane);
  try {
    const w = Number(localStorage.getItem("poschat.paperWidth"));
    if (w) paperSetWidth(w);
  } catch { /* 저장소를 못 쓰면 기본 너비 */ }
  return pane;
}

function paperSetWidth(px) {
  const max = Math.max(360, window.innerWidth - 420);
  const w = Math.round(Math.min(max, Math.max(340, px)));
  document.documentElement.style.setProperty("--paper-w", w + "px");
  try { localStorage.setItem("poschat.paperWidth", String(w)); } catch { /* 무시 */ }
}

function paperStatus(text) {
  PAPER.busy = text || "";
  const s = $("#paper-status");
  if (s) s.textContent = PAPER.busy;
  for (const b of document.querySelectorAll("#paper-pane [data-needs-doc]")) b.disabled = !!PAPER.busy || !PAPER.doc;
}

async function paperCall(promise) {
  let res;
  try {
    res = await promise;
  } catch (e) {
    toast(e.message || String(e));
    return null;
  }
  if (res && res.ok === false) {
    toast(res.error || "논문 오류");
    return null;
  }
  return res;
}

/* ---------- 열기·닫기 ---------- */

async function paperToggle() {
  if (PAPER.open) return paperLeave();
  return paperShow();
}

async function paperShow() {
  if (window.BR && BR.open && window.browserClose) await browserClose();  // 오른쪽 화면은 하나만
  if (window.codeLeave) codeLeave();  // 1.15 코드 화면(열린 탭·저장하지 않은 내용은 그대로 남는다)
  if (window.pageLeave) pageLeave();
  if (window.poLeave) poLeave();
  PAPER.open = true;
  const pane = paperPane();
  pane.hidden = false;
  $("#paper-resizer").hidden = isNarrow();
  $("#app").classList.add("paper-open");
  $("#btn-paper")?.classList.add("active");
  $("#btn-paper")?.setAttribute("aria-pressed", "true");
  setCollapsed(true);
  if (PAPER.doc && PAPER.pdf) return paperRenderReader();
  const st = await paperCall(api().paper_state());
  PAPER.state = st;
  if (st && st.current && !PAPER.doc) return paperLoad(st.current);
  paperRenderHome();
}

function paperLeave() {
  if (!PAPER.open) return;
  PAPER.open = false;
  paperSetCapture(false);
  $("#paper-pane").hidden = true;
  $("#paper-resizer").hidden = true;
  $("#app").classList.remove("paper-open");
  $("#btn-paper")?.classList.remove("active");
  $("#btn-paper")?.setAttribute("aria-pressed", "false");
}

function paperHeader(title, ...extra) {
  return h("div", { class: "paper-head" },
    h("button", { class: "icon-btn paper-sidebar-open", title: "사이드바 열기", "aria-label": "사이드바 열기",
      html: ICONS.sidebar, onclick: () => setCollapsed(false) }),
    h("h2", { class: "paper-title", id: "paper-title", title }, title),
    ...extra,
    h("button", { class: "icon-btn", title: "논문 화면 닫기", "aria-label": "논문 화면 닫기", html: ICONS.close,
      onclick: () => paperLeave() }));
}

/* ---------- 첫 화면: 열 논문 고르기 ---------- */

function paperRenderHome() {
  const pane = paperPane();
  const st = PAPER.state || { recent: [], library: [] };
  const file = h("input", { type: "file", accept: "application/pdf,.pdf", hidden: true,
    onchange: () => { if (file.files[0]) paperOpenFile(file.files[0]); file.value = ""; } });
  const url = h("input", { type: "text", class: "paper-url", placeholder: "arXiv 번호(예: 1706.03762) 또는 PDF 주소",
    "aria-label": "arXiv 번호 또는 PDF 주소", autocomplete: "off", spellcheck: "false" });
  const openForm = h("form", { class: "paper-open-row", onsubmit: (e) => {
    e.preventDefault();
    if (url.value.trim()) paperOpen({ url: url.value.trim() });
  } }, url, h("button", { class: "btn", type: "submit" }, "열기"));

  const recent = (st.recent || []).map((r) => h("li", {},
    h("button", { class: "paper-item", onclick: () => paperOpen({ path: r.path }) },
      h("span", { class: "paper-item-title" }, r.title || r.path),
      h("small", {}, `${r.pages || "?"}쪽`))));

  const openable = (st.library || []).filter((p) => p.has_pdf || p.arxiv);
  const compareBtn = h("button", { class: "btn", id: "paper-compare", disabled: PAPER.pick.size < 2,
    onclick: () => paperCompare() }, "선택한 논문 비교");
  const library = (st.library || []).map((p) => {
    const box = h("input", { type: "checkbox", "aria-label": `비교에 넣기: ${p.title}`, checked: PAPER.pick.has(p.id),
      onchange: () => {
        if (box.checked) PAPER.pick.add(p.id); else PAPER.pick.delete(p.id);
        if (PAPER.pick.size > 6) { box.checked = false; PAPER.pick.delete(p.id); toast("한 번에 6편까지 비교할 수 있습니다"); }
        compareBtn.disabled = PAPER.pick.size < 2;
        compareBtn.textContent = PAPER.pick.size >= 2 ? `선택한 ${PAPER.pick.size}편 비교` : "선택한 논문 비교";
      } });
    const canOpen = p.has_pdf || p.arxiv;
    return h("li", { class: "paper-lib-row" },
      box,
      h("button", { class: "paper-item", disabled: !canOpen, title: canOpen ? "열기" : "PDF가 없는 논문(초록으로만 비교)",
        onclick: () => paperOpen({ pid: p.id }) },
        h("span", { class: "paper-item-title" }, p.title),
        h("small", {}, [p.year, (p.authors || []).join(", "), canOpen ? "" : "PDF 없음"].filter(Boolean).join(" · "))));
  });

  pane.replaceChildren(
    paperHeader("논문"),
    h("div", { class: "paper-home" },
      h("p", { class: "paper-lead" }, "PDF를 채팅 옆에 열고, 선택한 문장·쪽·그림을 바로 물어보세요. 답에는 쪽 번호가 붙습니다."),
      h("div", { class: "paper-open-row" },
        h("button", { class: "btn primary", onclick: () => file.click() }, "PDF 파일 열기"), file),
      openForm,
      recent.length ? h("section", {}, h("h3", {}, "최근에 연 논문"), h("ul", { class: "paper-list" }, recent)) : null,
      h("section", {},
        h("div", { class: "paper-sec-head" }, h("h3", {}, "연구 라이브러리"), library.length ? compareBtn : null),
        library.length
          ? h("ul", { class: "paper-list" }, library)
          : h("p", { class: "muted" }, "라이브러리가 비어 있습니다. 연구 라이브러리나 브라우저에서 논문을 더하면 여기서 열고 비교할 수 있습니다."),
        library.length && !openable.length ? h("p", { class: "muted" }, "PDF나 arXiv 번호가 있는 논문만 열 수 있습니다.") : null),
      h("div", { class: "paper-status", id: "paper-status", role: "status", "aria-live": "polite" })));
}

async function paperOpenFile(file) {
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") return toast("PDF 파일을 고르세요");
  if (file.size > 60 * 1024 * 1024) return toast("PDF가 너무 큽니다(60MB 초과)");
  const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
  const CHUNK = 512 * 1024;
  paperStatus("PDF를 여는 중… 0%");
  try {
    for (let offset = 0; ;) {
      const blob = file.slice(offset, offset + CHUNK);
      const last = offset + blob.size >= file.size;
      const res = await paperCall(api().paper_upload(id, offset, await readBase64(blob), last));
      if (!res) return;
      offset += blob.size;
      paperStatus(`PDF를 여는 중… ${Math.round((offset / Math.max(1, file.size)) * 100)}%`);
      if (last) break;
    }
    await paperOpen({ upload_id: id, name: file.name });
  } finally {
    paperStatus("");
  }
}

async function paperOpen(source) {
  paperStatus(source.url ? "PDF를 받는 중…" : "PDF를 여는 중…");
  try {
    const res = await paperCall(api().paper_open(source));
    if (res) await paperLoad(res.doc);
  } finally {
    paperStatus("");
  }
}

async function paperLoad(doc) {
  const token = ++PAPER.loadToken;
  paperStatus("PDF를 불러오는 중…");
  try {
    const parts = [];
    let size = 0;
    for (let offset = 0; ;) {
      const res = await paperCall(api().paper_chunk(doc.id, offset));
      if (!res || token !== PAPER.loadToken) return;
      const bin = atob(res.data);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      parts.push(bytes);
      size += bytes.length;
      offset += bytes.length;
      if (res.done || !bytes.length) break;
    }
    const data = new Uint8Array(size);
    let at = 0;
    for (const p of parts) { data.set(p, at); at += p.length; }
    const lib = await paperLib();
    const base = new URL("vendor/pdfjs/", location.href).href;
    const pdf = await lib.getDocument({
      data, cMapUrl: base + "cmaps/", cMapPacked: true, standardFontDataUrl: base + "standard_fonts/",
      wasmUrl: base + "wasm/", isEvalSupported: false, enableXfa: false, disableAutoFetch: true,
    }).promise;
    if (token !== PAPER.loadToken) return;
    if (PAPER.pdf) PAPER.pdf.destroy();
    PAPER.pdf = pdf;
    PAPER.doc = { ...doc, pages: pdf.numPages };
    PAPER.page = 1;
    PAPER.fit = true;
    await paperRenderReader();
  } catch (e) {
    toast(e.message || String(e));
  } finally {
    if (token === PAPER.loadToken) paperStatus("");
  }
}

/* ---------- 읽기 화면 ---------- */

async function paperRenderReader() {
  const pane = paperPane();
  const doc = PAPER.doc;
  const btn = (icon, label, onclick, extra = {}) => h("button", { class: "icon-btn", title: label, "aria-label": label,
    html: ICONS[icon], onclick, ...extra });
  const pageInput = h("input", { id: "paper-page", type: "number", min: "1", max: String(doc.pages), value: String(PAPER.page),
    "aria-label": "쪽 번호", onchange: () => paperGo(Number(pageInput.value)) });
  const action = (id, label, title, onclick) => h("button", { class: "btn paper-action", id, title, onclick,
    "data-needs-doc": "1" }, label);
  const pages = h("div", { id: "paper-pages", tabindex: "0", "aria-label": `${doc.title} 본문` });
  pane.replaceChildren(
    paperHeader(doc.title,
      btn("back", "다른 논문 열기", () => { PAPER.doc = null; paperShow(); })),
    h("div", { class: "paper-toolbar" },
      h("span", { class: "paper-pager" }, pageInput, h("span", {}, `/ ${doc.pages}`)),
      btn("minus", "축소", () => paperZoom(-1)),
      h("span", { class: "paper-zoom", id: "paper-zoom" }, ""),
      btn("plus", "확대", () => paperZoom(1)),
      h("button", { class: "btn paper-fit", onclick: () => { PAPER.fit = true; paperRelayout(); } }, "너비 맞춤")),
    h("div", { class: "paper-toolbar paper-actions" },
      action("paper-ask-selection", "선택한 부분 묻기", "PDF에서 드래그한 글을 첨부합니다", () => paperAskSelection()),
      action("paper-ask-page", "이 쪽 묻기", "지금 보는 쪽의 글을 첨부합니다", () => paperAttach("page")),
      h("button", { class: "btn paper-action", id: "paper-capture", "aria-pressed": String(PAPER.capture), "data-needs-doc": "1",
        title: "그림·표·수식을 드래그해 잘라 이미지로 묻습니다 (Esc: 그만)", onclick: () => paperSetCapture(!PAPER.capture) },
      "영역 잘라 묻기"),
      action("paper-summary", "논문 요약", "실험 조건·결과 위주로 발췌해 요약을 요청합니다", () => paperAttach("paper")),
      doc.pid ? null : action("paper-save", "라이브러리에 저장", "이 PDF를 연구 라이브러리에 더합니다", () => paperSave())),
    h("div", { class: "paper-status", id: "paper-status", role: "status", "aria-live": "polite" }),
    pages);
  pages.addEventListener("scroll", paperTrackPage, { passive: true });
  await paperRelayout();
  paperStatus(PAPER.busy);
}

async function paperPageSize(num) {
  const page = await PAPER.pdf.getPage(num);
  return page.getViewport({ scale: 1 });
}

async function paperRelayout() {
  const box = $("#paper-pages");
  if (!box || !PAPER.pdf) return;
  const first = await paperPageSize(1);
  if (PAPER.fit) {
    const avail = Math.max(240, box.clientWidth - 32);
    PAPER.scale = Math.max(0.4, Math.min(4, avail / first.width));
  }
  $("#paper-zoom").textContent = `${Math.round(PAPER.scale * 100)}%`;
  const keep = PAPER.page;
  if (PAPER.observer) PAPER.observer.disconnect();
  PAPER.rendered.clear();
  box.replaceChildren();
  // 쪽마다 크기는 다를 수 있지만 대부분 같다. 첫 쪽 크기로 자리를 잡고 그릴 때 맞춘다.
  for (let n = 1; n <= PAPER.pdf.numPages; n++) {
    box.append(h("div", { class: "pdf-page", "data-page": String(n), role: "region", "aria-label": `${n}쪽`,
      style: `width:${Math.floor(first.width * PAPER.scale)}px;height:${Math.floor(first.height * PAPER.scale)}px` }));
  }
  PAPER.observer = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) paperRenderPage(Number(e.target.dataset.page));
  }, { root: box, rootMargin: "600px 0px" });
  for (const el of box.children) PAPER.observer.observe(el);
  paperGo(keep, true);
}

async function paperRenderPage(num) {
  if (PAPER.rendered.has(num)) return;
  const scale = PAPER.scale;
  PAPER.rendered.set(num, scale);
  const el = document.querySelector(`#paper-pages .pdf-page[data-page="${num}"]`);
  if (!el) return;
  try {
    const page = await PAPER.pdf.getPage(num);
    const viewport = page.getViewport({ scale });
    const ratio = window.devicePixelRatio || 1;
    const canvas = h("canvas", { "aria-hidden": "true" });
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = Math.floor(viewport.width) + "px";
    canvas.style.height = Math.floor(viewport.height) + "px";
    el.style.width = Math.floor(viewport.width) + "px";
    el.style.height = Math.floor(viewport.height) + "px";
    el.style.setProperty("--total-scale-factor", String(scale));
    el.style.setProperty("--scale-factor", String(scale));
    const text = h("div", { class: "textLayer" });
    el.replaceChildren(canvas, text);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport,
      transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null }).promise;
    if (PAPER.rendered.get(num) !== scale) return;
    const lib = await paperLib();
    await new lib.TextLayer({ textContentSource: page.streamTextContent(), container: text, viewport }).render();
  } catch (e) {
    PAPER.rendered.delete(num);
    if (!/cancel/i.test(String(e && e.name))) el.replaceChildren(h("p", { class: "muted pdf-page-error" }, `${num}쪽을 그리지 못했습니다`));
  }
}

function paperTrackPage() {
  const box = $("#paper-pages");
  if (!box) return;
  const mid = box.scrollTop + box.clientHeight / 3;
  let current = 1;
  for (const el of box.children) {
    if (el.offsetTop <= mid) current = Number(el.dataset.page); else break;
  }
  if (current !== PAPER.page) {
    PAPER.page = current;
    const input = $("#paper-page");
    if (input && document.activeElement !== input) input.value = String(current);
  }
}

function paperGo(num, instant = false) {
  if (!PAPER.pdf) return;
  num = Math.max(1, Math.min(PAPER.pdf.numPages, Number(num) || 1));
  PAPER.page = num;
  const el = document.querySelector(`#paper-pages .pdf-page[data-page="${num}"]`);
  if (el) $("#paper-pages").scrollTo({ top: el.offsetTop - 8, behavior: instant ? "auto" : "smooth" });
  const input = $("#paper-page");
  if (input) input.value = String(num);
}

function paperZoom(dir) {
  const i = PAPER_ZOOMS.findIndex((z) => z >= PAPER.scale - 0.001);
  const next = dir > 0 ? PAPER_ZOOMS[Math.min(PAPER_ZOOMS.length - 1, (i < 0 ? PAPER_ZOOMS.length - 1 : i) + (PAPER_ZOOMS[i] > PAPER.scale + 0.001 ? 0 : 1))]
    : PAPER_ZOOMS[Math.max(0, (i < 0 ? PAPER_ZOOMS.length : i) - 1)];
  PAPER.fit = false;
  PAPER.scale = next;
  paperRelayout();
}

/* ---------- 채팅에 묻기 ---------- */

function paperPushAttachment(a) {
  S.attach.push({ id: a.id, name: a.name, size: a.size, kind: a.kind, status: "ready", progress: 1 });
}

function paperToChat(question, message) {
  renderTray();
  const input = $("#input");
  if (!input.value.trim()) input.value = question;
  autoresize();
  updateSend();
  if (isNarrow()) paperLeave();  // 휴대폰: 채팅으로 돌아간다(사이드바의 '논문'으로 다시 열면 같은 쪽)
  input.focus();
  input.select();
  toast(message);
}

function paperRoom(n = 1) {
  if (S.attach.length + n > S.attachLimits.max_files) {
    toast(`파일은 한 번에 ${S.attachLimits.max_files}개까지 첨부할 수 있습니다`);
    return false;
  }
  return true;
}

function paperSelection() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return null;
  const node = sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
  const pageEl = node && node.closest && node.closest("#paper-pages .pdf-page");
  if (!pageEl) return null;
  return { text: sel.toString(), page: Number(pageEl.dataset.page) };
}

async function paperAskSelection() {
  const sel = paperSelection();
  if (!sel || !sel.text.trim()) return toast("PDF에서 묻고 싶은 부분을 먼저 드래그하세요");
  return paperAttach("selection", sel);
}

async function paperAttach(kind, sel = null) {
  if (!PAPER.doc || !paperRoom()) return;
  paperStatus(kind === "paper" ? "논문을 발췌하는 중…" : "글을 읽는 중…");
  try {
    const res = await paperCall(api().paper_attach(PAPER.doc.id, kind, sel ? sel.page : PAPER.page, sel ? sel.text : ""));
    if (!res) return;
    paperPushAttachment(res.attachment);
    paperToChat(res.question, kind === "selection" ? "선택한 부분을 첨부했습니다. 질문을 고쳐 보내세요"
      : kind === "page" ? `${PAPER.page}쪽을 첨부했습니다. 질문을 고쳐 보내세요` : "논문 발췌를 첨부했습니다. 질문을 고쳐 보내세요");
  } finally {
    paperStatus("");
  }
}

function paperSetCapture(on) {
  PAPER.capture = !!on;
  const btn = $("#paper-capture");
  if (btn) {
    btn.setAttribute("aria-pressed", String(PAPER.capture));
    btn.classList.toggle("active", PAPER.capture);
  }
  const box = $("#paper-pages");
  if (box) box.classList.toggle("capturing", PAPER.capture);
  if (PAPER.capture) paperStatus("잘라 낼 영역을 드래그하세요 (Esc: 그만)");
  else if (PAPER.busy.startsWith("잘라 낼")) paperStatus("");
}

function paperCaptureStart(e) {
  if (!PAPER.capture || e.button !== 0) return;
  const pageEl = e.target.closest && e.target.closest(".pdf-page");
  if (!pageEl) return;
  e.preventDefault();
  const rect = pageEl.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const mark = h("div", { class: "paper-mark" });
  pageEl.append(mark);
  const place = (ev) => {
    const x = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
    const y = Math.max(0, Math.min(rect.height, ev.clientY - rect.top));
    Object.assign(mark.style, { left: Math.min(sx, x) + "px", top: Math.min(sy, y) + "px",
      width: Math.abs(x - sx) + "px", height: Math.abs(y - sy) + "px" });
    return { x: Math.min(sx, x), y: Math.min(sy, y), w: Math.abs(x - sx), h: Math.abs(y - sy) };
  };
  let box = place(e);
  const move = (ev) => { box = place(ev); };
  const up = async () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    if (box.w < 12 || box.h < 12) { mark.remove(); return; }
    await paperCaptureRegion(Number(pageEl.dataset.page), box, rect.width);
    mark.remove();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

async function paperCaptureRegion(num, box, shownWidth) {
  if (!paperRoom()) return;
  paperStatus("영역을 이미지로 만드는 중…");
  try {
    const page = await PAPER.pdf.getPage(num);
    const base = page.getViewport({ scale: 1 });
    // 화면보다 선명하게(최소 2배, 긴 변 2400px 이하) 다시 그린 뒤 잘라 낸다
    const shownScale = shownWidth / base.width;
    let scale = Math.max(2, shownScale * 2);
    const longest = Math.max(box.w, box.h) * (scale / shownScale);
    if (longest > 2400) scale *= 2400 / longest;
    const viewport = page.getViewport({ scale });
    const full = document.createElement("canvas");
    full.width = Math.ceil(viewport.width);
    full.height = Math.ceil(viewport.height);
    await page.render({ canvasContext: full.getContext("2d"), viewport }).promise;
    const k = scale / shownScale;
    const out = document.createElement("canvas");
    out.width = Math.max(1, Math.round(box.w * k));
    out.height = Math.max(1, Math.round(box.h * k));
    const ctx = out.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(full, box.x * k, box.y * k, out.width, out.height, 0, 0, out.width, out.height);
    const res = await paperCall(api().paper_attach_image(PAPER.doc.id, num, out.toDataURL("image/png")));
    if (!res) return;
    paperPushAttachment(res.attachment);
    paperSetCapture(false);
    paperToChat(res.question, `${num}쪽의 영역을 이미지로 첨부했습니다. 질문을 고쳐 보내세요`);
  } catch (e) {
    toast("영역을 잘라 내지 못했습니다: " + (e.message || e));
  } finally {
    paperStatus("");
  }
}

async function paperCompare() {
  const ids = [...PAPER.pick];
  if (ids.length < 2 || !paperRoom(ids.length)) return;
  paperStatus(`논문 ${ids.length}편을 발췌하는 중… (arXiv PDF는 처음 한 번 받습니다)`);
  try {
    const res = await paperCall(api().paper_compare(ids));
    if (!res) return;
    for (const a of res.attachments) paperPushAttachment(a);
    PAPER.pick.clear();
    const skipped = (res.skipped || []).length ? ` (PDF·초록이 없어 뺀 논문: ${res.skipped.join(", ")})` : "";
    paperToChat(res.question, `논문 ${res.attachments.length}편을 첨부했습니다. 보내면 비교표를 만듭니다${skipped}`);
    if (PAPER.open && !PAPER.doc) paperRenderHome();
  } finally {
    paperStatus("");
  }
}

async function paperSave() {
  paperStatus("논문 정보를 찾는 중…");
  try {
    const res = await api().paper_save(PAPER.doc.id);
    if (res.ok === false) return toast(res.error);
    PAPER.doc.pid = res.pid;
    $("#paper-save")?.remove();
    toast(res.already ? "이미 라이브러리에 있는 논문입니다" : `라이브러리에 저장했습니다: ${res.title || PAPER.doc.title}`);
  } finally {
    paperStatus("");
  }
}

function paperInit() {
  $("#btn-paper")?.addEventListener("click", () => paperToggle());
  document.addEventListener("pointerdown", (e) => { if (PAPER.capture && e.target.closest("#paper-pages")) paperCaptureStart(e); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && PAPER.capture) paperSetCapture(false); });
  let timer = null;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!PAPER.open) return;
      $("#paper-resizer").hidden = isNarrow();
      if (PAPER.fit) paperRelayout();
    }, 200);
  });
}

window.paperShow = paperShow;
window.paperLeave = paperLeave;
paperInit();
