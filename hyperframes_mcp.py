"""내장 MCP 서버 hyperframes: HTML로 영상을 만든다(HeyGen HyperFrames, Apache-2.0, 무료).

HyperFrames는 data-* 속성으로 시간을 매긴 HTML과 GSAP 애니메이션을 헤드리스 Chrome으로 한 장씩 찍어
MP4 등으로 렌더링한다. 프로젝트 만들기·형식 안내·기본 검사는 이 모듈이 직접 하고, 정식 검사(lint)·미리보기·
렌더링은 `npx hyperframes@<고정 버전>`을 부른다. 그래서 그 셋은 PC에 Node.js 22 이상과 FFmpeg가 있어야 한다.
렌더링은 오래 걸릴 수 있어 백그라운드 작업으로 돌리고 render_status로 진행을 본다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from office_mcp import BOOL, INT, READ_ONLY, STR, ToolFailure, _rel, _root, _schema

HYPERFRAMES_VERSION = "0.8.181"  # 같은 프로젝트가 늘 같게 렌더링되도록 버전을 고정한다
NODE_MIN = 22
RENDER_WAIT = 120     # render가 끝나기를 기다리는 시간(초). MCP 호출 제한(180초)보다 짧아야 한다
LINT_TIMEOUT = 150
FORMATS = ("mp4", "webm", "mov", "gif")
QUALITIES = ("draft", "standard", "high")
FILE_WRITES = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
RUNS_NPX = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}

GUIDE = """HyperFrames 작성 규칙 (index.html 하나가 영상 하나)

1. 루트 요소: id, data-composition-id(예: "main"), data-start="0", data-width, data-height, data-duration(초).
   CSS에서 html·body·루트 크기를 data-width×data-height px로 고정하고 overflow: hidden.
2. 시간이 있는 요소(장면·글자·이미지): 고유한 id, class="clip", data-start(초), data-duration(초).
   data-track-index는 편집 화면의 줄 번호일 뿐이고 겹침 순서는 CSS z-index로 정한다.
   data-start는 "intro + 0.5"처럼 다른 클립 id 기준으로도 쓸 수 있다.
3. 애니메이션: GSAP 타임라인 하나를 { paused: true }로 만들고 트윈을 모두 넣은 뒤 등록한다.
     window.__timelines = window.__timelines || {};
     const tl = gsap.timeline({ paused: true });
     tl.fromTo("#title", { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.8, ease: "power3.out" }, 0.2);
     window.__timelines["main"] = tl;   // 키는 data-composition-id와 같아야 한다
   애니메이션이 전혀 없으면 루트에 data-no-timeline을 붙인다.
   GSAP: <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
4. 결정적이어야 한다: Math.random()·Date.now()·fetch 같은 네트워크 요청·무한 반복(repeat: -1) 금지.
   미디어의 play()·pause()·currentTime은 건드리지 않는다(HyperFrames가 시간을 맞춘다).
5. 미디어: <video>는 소리가 없으면 muted, 소리를 쓰면 data-has-audio="true"(muted 없이).
   음악·내레이션은 따로 <audio data-start data-duration data-volume="0.5" src="...">.
   data-media-start는 원본에서 시작할 위치(초). 파일은 프로젝트 폴더(assets/ 등)에 두고 상대 경로로 쓴다.
6. 장면 여러 개: 클립마다 data-start를 이어 붙이고(0, 3, 6 …) 타임라인에서도 같은 시각에 트윈을 둔다.
   큰 프로젝트는 compositions/장면.html을 <template>으로 감싸 만들고
   <div data-composition-id="scene1" data-composition-src="compositions/scene1.html" data-start data-duration ...>로 넣는다.
7. 글꼴: 쓰는 글꼴마다 @font-face를 밝힌다. 설치된 글꼴은 src: local("Malgun Gothic"),
   프로젝트 폴더의 글꼴 파일은 src: url("assets/fonts/글꼴.woff2"). 밝히지 않으면 lint 오류가 난다.
8. 클립 안에 다른 요소를 여럿 넣는 장면은 6번의 compositions/ 파일로 나누는 것이 좋다(lint 경고).

작업 순서: create_project → index.html을 write/edit로 고치기 → lint → (preview로 확인) → render → render_status.
"""

STARTER = """<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={w}, height={h}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      /* 렌더러가 쓸 글꼴을 밝힌다: 이 PC에 설치된 글꼴을 쓴다(local) */
      @font-face {{ font-family: "Malgun Gothic"; src: local("Malgun Gothic"); }}
      @font-face {{ font-family: "Apple SD Gothic Neo"; src: local("Apple SD Gothic Neo"); }}
      @font-face {{ font-family: "Noto Sans KR"; src: local("Noto Sans KR"); }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: #0a0a0a; }}
      #root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden;
               font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif; color: #f4f4f5; }}
      .clip {{ position: absolute; inset: 0; display: grid; place-items: center; }}
      #title {{ font-size: {fs}px; font-weight: 700; letter-spacing: -0.02em; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{d}" data-width="{w}" data-height="{h}">
      <h1 id="title" class="clip" data-start="0" data-duration="{d}" data-track-index="0">{title}</h1>
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#title", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.8, ease: "power3.out" }}, 0.2);
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


# ---- 경로·환경 ----

def _inside(p):
    root = _root()
    p = p.resolve()
    if p != root and root not in p.parents:
        raise ToolFailure("작업 폴더 밖의 경로는 쓸 수 없습니다.")
    return p


def _project(path):
    return _inside(_root() / str(path or "."))


def _composition(project):
    index = project / "index.html"
    if not index.is_file():
        raise ToolFailure(f"{_rel(project) if project != _root() else '작업 폴더'}에 index.html이 없습니다. create_project로 먼저 만드세요.")
    return index


def _environment():
    """(npx 경로 또는 None, 문제 목록)."""
    if hasattr(sys, "getandroidapilevel"):
        return None, ["안드로이드 앱에서는 Node.js를 쓸 수 없어 렌더링·미리보기·정식 검사를 할 수 없습니다. 같은 프로젝트를 PC 앱에서 렌더링하세요."]
    problems = []
    node = shutil.which("node")
    npx = shutil.which("npx")
    if not node or not npx:
        problems.append(f"Node.js {NODE_MIN} 이상이 필요합니다. https://nodejs.org 에서 LTS를 설치한 뒤 앱을 다시 시작하세요.")
    else:
        try:
            out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15, **_no_window()).stdout
            major = int(re.match(r"v(\d+)", out.strip()).group(1))
            if major < NODE_MIN:
                problems.append(f"Node.js {out.strip()}는 너무 오래됐습니다. {NODE_MIN} 이상으로 업데이트하세요(https://nodejs.org).")
        except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
            problems.append("Node.js 버전을 확인하지 못했습니다.")
    if not shutil.which("ffmpeg"):
        problems.append("FFmpeg가 필요합니다. Windows는 명령 프롬프트에서 `winget install Gyan.FFmpeg`로 설치한 뒤 앱을 다시 시작하세요.")
    return (npx if not problems else None), problems


def _no_window():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _npx_command(*args):
    npx, problems = _environment()
    if problems:
        raise ToolFailure("HyperFrames를 실행할 수 없습니다.\n- " + "\n- ".join(problems))
    rest = ["--yes", f"hyperframes@{HYPERFRAMES_VERSION}", *args]
    if os.name == "nt" and npx.lower().endswith((".cmd", ".bat")):
        # npx.cmd를 cmd /c로 부르면 공백 있는 경로의 따옴표가 깨진다. npx.cmd가 하는 대로 node로 직접 부른다.
        cli = Path(npx).parent / "node_modules" / "npm" / "bin" / "npx-cli.js"
        node = shutil.which("node")
        return [node, str(cli), *rest] if cli.is_file() and node else ["cmd", "/c", npx, *rest]
    return [npx, *rest]


def _env():
    env = dict(os.environ, HYPERFRAMES_SKIP_SKILLS="1", NO_COLOR="1", FORCE_COLOR="0", CI="1")
    env.pop("ELECTRON_RUN_AS_NODE", None)
    return env


def _run(args, cwd, timeout):
    try:
        r = subprocess.run(_npx_command(*args), cwd=str(cwd), capture_output=True, timeout=timeout,
                           env=_env(), stdin=subprocess.DEVNULL, **_no_window())
    except subprocess.TimeoutExpired:
        raise ToolFailure(f"HyperFrames가 {timeout}초 안에 끝나지 않았습니다(처음 실행은 패키지를 받느라 오래 걸릴 수 있습니다). 다시 시도하세요.")
    except OSError as e:
        raise ToolFailure(f"npx를 실행하지 못했습니다: {e}")
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _tail(text, lines=15):
    keep = [ANSI_RE.sub("", x).rstrip() for x in text.splitlines()]
    keep = [x for x in keep if x.strip() and not x.startswith(("@hf-progress", "[INFO] [Render:trace]"))
            and "█" not in x and "░" not in x]
    return "\n".join(keep[-lines:])


# ---- 기본 검사(Node 없이) ----

def _static_check(html):
    problems = []
    root = re.search(r"<[a-z]+[^>]*\bdata-composition-id=\"([^\"]+)\"[^>]*>", html, re.I)
    if not root:
        return ["루트 요소에 data-composition-id가 없습니다."]
    tag, comp = root.group(0), root.group(1)
    for attr in ("data-width", "data-height", "data-start"):
        if attr not in tag:
            problems.append(f"루트 요소에 {attr}가 없습니다.")
    if "data-duration" not in tag:
        problems.append("루트 요소에 data-duration(초)이 없습니다. 길이를 정할 수 있게 넣으세요.")
    registered = re.search(r"__timelines\s*(?:\[\s*['\"]" + re.escape(comp) + r"['\"]\s*\]|\." + re.escape(comp) + r"\b)\s*=", html)
    if not registered and "data-no-timeline" not in tag:
        problems.append(f"window.__timelines[\"{comp}\"]에 타임라인을 등록하지 않았습니다(애니메이션이 없으면 루트에 data-no-timeline).")
    if re.search(r"gsap\.timeline\(\s*\)", html):
        problems.append("gsap.timeline()은 { paused: true }로 만들어야 합니다.")
    for name, pattern in (("Math.random()", r"Math\.random\s*\("), ("Date.now()", r"Date\.now\s*\("),
                          ("new Date()", r"new\s+Date\s*\(\s*\)"), ("repeat: -1", r"repeat\s*:\s*-1"),
                          ("fetch()", r"\bfetch\s*\(")):
        if re.search(pattern, html):
            problems.append(f"{name}는 렌더링을 매번 다르게 만들므로 쓰면 안 됩니다.")
    for video in re.findall(r"<video\b[^>]*>", html, re.I):
        if " muted" not in video and "data-has-audio" not in video:
            problems.append("<video>에 muted(소리 없음)나 data-has-audio=\"true\"(소리 사용)가 필요합니다.")
    ids = re.findall(r"\bid=\"([^\"]+)\"", html)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        problems.append("id가 겹칩니다: " + ", ".join(dup))
    for el in re.findall(r"<[a-z]+[^>]*\bclass=\"[^\"]*\bclip\b[^\"]*\"[^>]*>", html, re.I):
        if "data-start" not in el:
            problems.append(f"clip 요소에 data-start가 없습니다: {el[:80]}")
    return problems


# ---- 도구 ----

def guide():
    return GUIDE


def create_project(path="video", title="제목", width=1920, height=1080, duration=5, overwrite=False):
    project = _project(path)
    if project == _root():
        raise ToolFailure("작업 폴더 안에 프로젝트용 하위 폴더 이름을 path로 주세요(예: \"video\").")
    index = project / "index.html"
    if index.exists() and not overwrite:
        raise ToolFailure(f"{_rel(index)}이 이미 있습니다. 고치려면 write/edit를 쓰고, 새로 만들려면 overwrite를 true로 주세요.")
    w, h = int(width or 1920), int(height or 1080)
    d = float(duration or 5)
    if not (16 <= w <= 7680 and 16 <= h <= 7680 and 0 < d <= 3600):
        raise ToolFailure("width·height는 16~7680, duration은 0~3600초여야 합니다.")
    d = int(d) if d == int(d) else d
    (project / "assets").mkdir(parents=True, exist_ok=True)
    safe_title = str(title or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    index.write_text(STARTER.format(w=w, h=h, d=d, title=safe_title, fs=max(24, min(w, h) // 15)), encoding="utf-8")
    name = re.sub(r"[^\w\-]+", "-", project.name).strip("-").lower() or "video"
    pin = f"npx --yes hyperframes@{HYPERFRAMES_VERSION}"
    files = {
        "meta.json": {"id": name, "name": project.name, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "hyperframes.json": {"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
                             "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
                             "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
                             "media": {"autoProxy": True}},
        "package.json": {"name": name, "private": True, "type": "module",
                         "scripts": {"dev": f"{pin} preview", "check": f"{pin} check", "render": f"{pin} render"}},
    }
    for fname, data in files.items():
        target = project / fname
        if overwrite or not target.exists():
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return (f"{_rel(project)}에 HyperFrames 프로젝트를 만들었습니다({w}×{h}, {d}초).\n"
            f"- {_rel(index)}: 영상 내용(이 파일을 write/edit로 고치세요)\n- {_rel(project / 'assets')}/: 이미지·영상·음악 파일\n"
            "작성 규칙은 guide를 보세요. 다 고치면 lint로 검사하고 render로 영상을 만드세요.")


def lint(path="video"):
    project = _project(path)
    html = _composition(project).read_text(encoding="utf-8", errors="replace")
    basic = _static_check(html)
    npx, problems = _environment()
    if problems:
        head = "기본 검사만 했습니다(정식 검사에는 " + " ".join(problems) + ")\n"
        return head + ("문제 없음" if not basic else "- " + "\n- ".join(basic))
    code, out, err = _run(["lint", "--json"], project, LINT_TIMEOUT)
    try:
        report = json.loads(out[out.index("{"):])
    except ValueError:
        raise ToolFailure("HyperFrames lint 결과를 읽지 못했습니다.\n" + _tail(out + "\n" + err))
    lines = [f"HyperFrames lint: 오류 {report.get('errorCount', 0)} · 경고 {report.get('warningCount', 0)}"]
    for f in report.get("findings") or []:
        where = str(f.get("file") or "")
        if os.path.isabs(where):
            where = os.path.relpath(where, project)
        where += f":{f['line']}" if f.get("line") else ""
        lines.append(f"- [{f.get('severity', '')}] {f.get('code', '')} {where}: {f.get('message', '')}"
                     + (f" → {f['fixHint']}" if f.get("fixHint") else ""))
    if not report.get("findings"):
        lines.append("문제 없음. render로 영상을 만들 수 있습니다.")
    return "\n".join(lines)


_JOBS = {}
_JOBS_LOCK = threading.Lock()


def _job_text(job_id, job):
    proc = job["proc"]
    try:
        log = job["log"].read_text(encoding="utf-8", errors="replace")
    except OSError:
        log = ""
    progress = None
    for m in re.finditer(r"@hf-progress (\{.*\})", log):
        try:
            progress = json.loads(m.group(1))
        except ValueError:
            pass
    elapsed = int(time.time() - job["started"])
    code = proc.poll()
    if code is None:
        pct = f"{progress.get('pct', 0)}% ({progress.get('code', '')} {progress.get('done', '')}/{progress.get('total', '')})" if progress else "준비 중"
        return (f"렌더링 중입니다: {pct}, {elapsed}초 지남.\njob: {job_id}\n"
                "render_status로 다시 확인하세요(처음에는 패키지와 Chrome을 받느라 몇 분 걸릴 수 있습니다).")
    out = job["output"]
    if code == 0 and out.is_file():
        size = out.stat().st_size / 1024 / 1024
        return f"렌더링 완료: {_rel(out)} ({size:.1f}MB, {elapsed}초)"
    return f"렌더링 실패(종료 코드 {code}). 로그: {_rel(job['log'])}\n" + _tail(log, 25)


def render(path="video", output=None, format="mp4", quality="standard", fps=None):
    project = _project(path)
    _composition(project)
    format = str(format or "mp4").lower()
    quality = str(quality or "standard").lower()
    if format not in FORMATS:
        raise ToolFailure(f"format은 {', '.join(FORMATS)} 중 하나여야 합니다.")
    if quality not in QUALITIES:
        raise ToolFailure(f"quality는 {', '.join(QUALITIES)} 중 하나여야 합니다.")
    default = re.sub(r"[^\w\-]+", "_", project.name) or "video"
    out = _inside(project / (output or f"renders/{default}.{format}"))
    if out.suffix.lower() != f".{format}":
        raise ToolFailure(f"output 파일 확장자는 .{format}이어야 합니다.")
    with _JOBS_LOCK:
        for job_id, job in _JOBS.items():
            if job["proc"].poll() is None and job["project"] == project:
                return "이미 이 프로젝트를 렌더링하고 있습니다.\n" + _job_text(job_id, job)
    args = ["render", "-o", os.path.relpath(out, project), "--format", format, "--quality", quality]
    if fps:
        args += ["--fps", str(int(fps))]
    cmd = _npx_command(*args)
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.parent / f"{out.stem}.render.log"
    with open(log, "wb") as f:
        try:
            proc = subprocess.Popen(cmd, cwd=str(project), stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    env=_env(), **_no_window())
        except OSError as e:
            raise ToolFailure(f"npx를 실행하지 못했습니다: {e}")
    job_id = uuid.uuid4().hex[:8]
    job = {"proc": proc, "log": log, "output": out, "project": project, "started": time.time()}
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    deadline = time.time() + RENDER_WAIT
    while proc.poll() is None and time.time() < deadline:
        time.sleep(1)
    return _job_text(job_id, job)


def render_status(job=None):
    with _JOBS_LOCK:
        jobs = dict(_JOBS)
    if not jobs:
        return "이번 세션에서 시작한 렌더링이 없습니다. (앱이나 작업 폴더가 바뀌면 목록이 초기화되지만, 진행 중이던 렌더링은 계속되어 renders/ 폴더에 결과가 생깁니다.)"
    if job:
        if job not in jobs:
            raise ToolFailure(f"job '{job}'이 없습니다. 있는 job: {', '.join(jobs)}")
        jobs = {job: jobs[job]}
    else:
        jobs = dict(list(jobs.items())[-3:])
    return "\n\n".join(_job_text(k, v) for k, v in jobs.items())


def preview(path="video", stop=False):
    project = _project(path)
    if stop:
        code, out, err = _run(["preview", "--stop"], project, 60)
        return "미리보기 서버를 껐습니다.\n" + _tail(out + "\n" + err, 5)
    _composition(project)
    code, out, err = _run(["preview", "--background", "--open", "--json"], project, 150)
    try:
        result = json.loads(out[out.index("{"):]).get("result") or {}
    except ValueError:
        result = {}
    url = result.get("studioUrl") or result.get("serverUrl")
    if code != 0 or not url:
        raise ToolFailure("미리보기를 시작하지 못했습니다.\n" + _tail(out + "\n" + err, 12))
    return (f"브라우저에서 HyperFrames 미리보기(Studio)를 열었습니다: {url}\n"
            "파일을 고치면 바로 반영됩니다. 다 보면 preview(stop=true)로 끄세요.")


def doctor():
    npx, problems = _environment()
    if problems:
        return "준비되지 않음:\n- " + "\n- ".join(problems) + "\n\ncreate_project·guide·lint(기본 검사)는 지금도 쓸 수 있습니다."
    return (f"Node.js와 FFmpeg가 있습니다. render·preview·lint를 쓸 수 있습니다(HyperFrames {HYPERFRAMES_VERSION}, "
            "처음 실행할 때 npm에서 패키지를 받습니다). 렌더링에는 Chrome이 쓰이며 없으면 HyperFrames가 받습니다.")


DIR_HELP = "path: 프로젝트 폴더(작업 폴더 기준, 기본 \"video\")"

TOOLS = {
    "guide": (guide, "HyperFrames 영상 HTML 작성 규칙과 작업 순서를 봅니다. 영상을 만들기 전에 먼저 읽으세요.",
              _schema({}, []), {**READ_ONLY, "openWorldHint": False}),
    "create_project": (create_project, "HTML로 영상을 만드는 HyperFrames 프로젝트(index.html 등)를 새로 만듭니다. "
                                       "width·height 기본 1920×1080(세로 영상은 1080×1920), duration 초. " + DIR_HELP,
                       _schema({"path": STR, "title": STR, "width": INT, "height": INT, "duration": {"type": "number"},
                                "overwrite": BOOL}, []), FILE_WRITES),
    "lint": (lint, "index.html이 HyperFrames 규칙에 맞는지 검사합니다(Node.js가 있으면 정식 검사). 렌더링 전에 쓰세요. " + DIR_HELP,
             _schema({"path": STR}, []), RUNS_NPX),
    "render": (render, "영상을 렌더링합니다(Node.js 22+·FFmpeg 필요). format: mp4|webm|mov|gif, quality: draft|standard|high, "
                       "output 기본 renders/<폴더>.<형식>. 오래 걸리면 진행 중으로 돌아오니 render_status로 확인하세요. " + DIR_HELP,
               _schema({"path": STR, "output": STR, "format": STR, "quality": STR, "fps": INT}, []), RUNS_NPX),
    "render_status": (render_status, "렌더링 진행 상황과 결과를 봅니다. job을 비우면 최근 작업들.",
                      _schema({"job": STR}, []), {**READ_ONLY, "openWorldHint": False}),
    "preview": (preview, "브라우저에서 영상을 미리 봅니다(HyperFrames Studio, 고치면 바로 반영). stop=true면 끕니다. " + DIR_HELP,
                _schema({"path": STR, "stop": BOOL}, []), RUNS_NPX),
    "doctor": (doctor, "렌더링에 필요한 Node.js·FFmpeg가 있는지 확인합니다.", _schema({}, []), {**READ_ONLY, "openWorldHint": False}),
}
