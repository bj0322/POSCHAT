# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive AI 라우터(1.17): 요청을 분석하고, 사용자 정책 안에서 로컬 모델과 Cloud 모델 중 하나를 고른다.

세 단계로 고른다(모델을 부르지 않으므로 라우팅 자체에는 API 비용이 없다).
1. 규칙: 반드시 지킬 제약을 먼저 본다 — Local Only, 민감 정보·첨부를 Cloud로 보내지 않는 설정, 이미지(로컬 vision 지원),
   문맥 길이(로컬 모델의 context window), 이 PC의 메모리, Cloud 예산·요청당 비용 한도. 비용보다 앞선다.
2. 의미 분류: 사용자 요청 글을 글자 3개 단위(n-gram) 벡터로 바꿔 작업 유형별 예시와 비교한다(외부 라이브러리 없음, 안드로이드에서도 돈다).
   비슷함이 낮거나 1·2위 차이가 작으면 '분류 불확실(분포 밖)'로 보고 보수적으로(Cloud 쪽) 고른다. 비슷함은 답의 품질이 아니다.
3. 품질·비용: 정책이 정한 성공률 하한을 넘는다고 측정된(또는 규칙으로 허용된) 후보 중 Cloud API 비용이 적은 쪽.
   측정 기록이 MIN_SAMPLES보다 적으면 확신하지 않고 규칙의 기본값을 따른다(Quality 정책은 이 경우 Cloud).

route()는 Route를 돌려준다. 이유(reason)는 사용자에게 보이는 짧은 한국어이며 프롬프트·개인 정보를 담지 않는다.
"""
import json
import math
import re
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field

import privacy
import storage

POLICIES = ("economy", "balanced", "quality", "local_only")
POLICY_LABELS = {"economy": "Economy(절약)", "balanced": "Balanced(균형)", "quality": "Quality(품질)", "local_only": "Local Only(로컬 전용)"}
TASKS = ("general_chat", "translation", "summarization", "classification", "extraction", "browser", "paper", "research",
         "coding", "agent_planning", "tool_execution", "data_lab", "other")
TASK_LABELS = {
    "general_chat": "일반 대화", "translation": "번역", "summarization": "요약", "classification": "분류",
    "extraction": "정보 추출", "browser": "웹페이지 분석", "paper": "논문 읽기", "research": "연구 추론", "coding": "코딩",
    "agent_planning": "에이전트 계획", "tool_execution": "도구 실행", "data_lab": "데이터·실험 분석", "other": "기타",
}
DIFFICULTIES = ("easy", "moderate", "hard", "critical")
DIFF_LABELS = {"easy": "쉬움", "moderate": "보통", "hard": "어려움", "critical": "중요·위험"}
FLOORS = {"economy": 0.80, "balanced": 0.90, "quality": 0.95, "local_only": 0.0}   # 측정 성공률 하한
MIN_SAMPLES = 20      # 이보다 적게 측정한 (모델, 작업)은 측정값을 믿지 않는다
SEMANTIC_MIN = 0.10   # 의미 분류 1위 비슷함의 하한
SEMANTIC_MARGIN = 0.02

# 정책별로 로컬을 먼저 써 볼 수 있는 (작업 → 가장 어려운 난이도). 없으면 Cloud.
# 연구 추론·코드 수정·에이전트 계획은 검증 전까지 Cloud를 먼저 쓴다(오답 비용이 크다).
LOCAL_ELIGIBLE = {
    "economy": {"general_chat": "moderate", "translation": "moderate", "summarization": "moderate", "classification": "moderate",
                "extraction": "moderate", "browser": "moderate", "paper": "easy", "coding": "easy", "data_lab": "easy",
                "other": "easy"},
    "balanced": {"general_chat": "easy", "translation": "moderate", "summarization": "moderate", "classification": "moderate",
                 "extraction": "moderate", "browser": "easy", "paper": "easy", "data_lab": "easy", "coding": "easy"},
    "quality": {"classification": "easy", "extraction": "easy", "translation": "easy"},
}
# 앱 내부 보조 호출(사용자에게 바로 보이지 않는 작은 일). 목적(purpose) → (작업, 난이도)
PURPOSES = {
    "memory_extract": ("extraction", "easy"),       # '기억해 줘'에서 한 문장 뽑기(JSON)
    "agent_convert": ("classification", "moderate"),  # 안내문을 단계 JSON으로 바꾸기
    "agent_step": ("agent_planning", "critical"),     # 다음 단계 고르기(파일·명령·외부 도구로 이어질 수 있다)
    "agent_final": ("agent_planning", "hard"),
    "code_agent_step": ("coding", "critical"),
    "profile": ("summarization", "moderate"),         # USER.md 정리
    "thread_summary": ("summarization", "easy"),
    "po_note": ("summarization", "moderate"),
}

# ---- 분석 ----

HANGUL = re.compile(r"[가-힣]")
FRESH_RE = re.compile(r"(?i)(최신 (정보|뉴스|소식|버전|논문|동향)|요즘 (뉴스|소식|동향)|(오늘|어제|이번 주)(의)? (뉴스|날씨|주가|환율|경기|소식)|"
                      r"현재 (가격|시세|날씨|주가|환율)|뉴스|속보|실시간|latest (news|version)|breaking news|current (price|weather))")
GROUND_RE = re.compile(r"(?i)(근거|인용|출처|몇 쪽|페이지 번호|원문|citation|cite|source)")
PROOF_RE = re.compile(r"(?i)(증명|유도|도출|검증(?! ?(정확도|손실|세트|데이터|집합))|비판|가설|인과|통계적으로|유의|p-?value|회귀|분산 분석|anova|prove|derive|critique)")
# 방법·실험을 새로 짜게 하는 요청(요약이라는 낱말이 들어 있어도 연구 추론이다)
DESIGN_RE = re.compile(r"(?i)(제안해|설계해|설계하고|평가 방법|기준을 (세워|정해)|방법을 제시|체크리스트|propose|design an? )")
# 주어진 글·표에서 값 하나를 찾는 짧은 질문(무엇·얼마·언제·어디·누구·몇·가장 …·~은?)
LOOKUP_RE = re.compile(r"(?i)(얼마|언제|어디|누구|몇|무엇|뭐야|뭐라고|알려 ?줘|뽑아|가장 \S+ (높|낮|긴|짧|큰|작|많|적)|"
                       r"(은|는|이|가)\?\s*$|\?\s*$|^(what|when|where|who|how (much|many))\b)")
EDIT_RE = re.compile(r"(?i)(고쳐|수정해|바꿔|리팩터|구현해|만들어 ?줘|추가해|작성해 ?줘|fix|implement|refactor|rewrite|write (a|the) (function|class|code))")
CODE_WORD_RE = re.compile(r"(?i)(코드|함수|버그|에러|오류 메시지|컴파일|스택 트레이스|traceback|exception|\bcode\b|\bbug\b|\bfunction\b|compile)")
CODE_RE = re.compile(r"(?m)```|^\s*(def |class |import |#include|function |public |fn |module |always @)|\b\w+\.(py|js|ts|c|cpp|h|java|rs|go|sv|v|vhd|kt)\b|"
                     r"\b[a-z][a-z0-9]*_[a-z0-9_]*\([^)]*\)")
TRANSLATE_RE = re.compile(r"(?i)(번역|영어로|한국어로 (옮|바꿔)|일본어로|중국어로|translate|in english|into korean)")
SUMMARY_RE = re.compile(r"(?i)(요약|정리해|핵심만|간단히 줄|tl;?dr|summari[sz]e)")
CLASSIFY_RE = re.compile(r"(?i)(분류|감정|긍정|부정|카테고리|라벨|어느 쪽|classify|sentiment|label)")
EXTRACT_RE = re.compile(r"(?i)(추출|뽑아|찾아서 (표|목록)|json으로|목록으로 정리|이름만|날짜만|extract|parse)")
MARKERS = (  # 기능이 첨부를 감싸는 표시(connectors.wrap_untrusted의 출처 이름)
    ("browser", "[외부 데이터: 웹페이지"),
    ("paper", "[외부 데이터: 논문 PDF"),
    ("data_lab", "[외부 데이터: Lab 실험 기록"),
    ("coding", "[외부 데이터: 작업 폴더 파일"),
    ("coding", "[외부 데이터: 명령 출력"),
)
SENSITIVE_RE = [re.compile(r"\b\d{6}-[1-4]\d{6}\b"),                 # 주민등록번호
                re.compile(r"\b(?:\d{4}[- ]){3}\d{4}\b"),             # 카드 번호 꼴
                re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b")]        # 휴대전화


def estimate_tokens(text):
    """토큰 수 어림(보수적으로 크게): 한글 1자 ≈ 1토큰, 그 밖의 글자 3.5자 ≈ 1토큰."""
    text = str(text or "")
    hangul = len(HANGUL.findall(text))
    return int(hangul + (len(text) - hangul) / 3.5) + 1


def sensitive(text):
    """비밀(키·토큰)이나 개인 정보(주민번호·카드·전화·이메일)가 있어 보이는지. 내용은 돌려주지 않는다."""
    text = str(text or "")
    if privacy.redact_text(text, emails=True) != text:
        return True
    return any(rx.search(text) for rx in SENSITIVE_RE)


# 의미 분류(2단계)에 쓰는 작업별 예시. 한국어 위주. 예시는 짧은 요청 글이다(앱의 지시문은 넣지 않는다).
EXAMPLES = {
    "general_chat": ["안녕 오늘 기분이 어때", "점심 메뉴 추천해 줘", "고마워", "이거 어떻게 생각해", "주말에 뭐 하면 좋을까",
                     "포항에서 가볼 만한 곳", "간단히 설명해 줘", "what do you think", "hello how are you",
                     "인공지능이 뭐야", "블랙홀의 원리를 설명해 줘", "미래 전망은 어때", "역사에 대해 알려 줘", "차이가 뭐야",
                     "왜 그런 거야", "어떻게 하면 좋을까", "장점과 단점", "의미가 뭐야", "what is", "explain how"],
    "translation": ["이 문장을 영어로 번역해 줘", "다음 글을 한국어로 옮겨 줘", "일본어로 번역", "translate this to korean",
                    "자연스러운 영어 표현으로 바꿔 줘", "이메일을 영어로 써 줘"],
    "summarization": ["이 글을 세 줄로 요약해 줘", "핵심만 정리해 줘", "회의록 요약", "강의 내용을 정리해 줘", "summarize this",
                      "요점만 불릿으로", "긴 글을 짧게 줄여 줘"],
    "classification": ["이 리뷰가 긍정인지 부정인지 알려 줘", "카테고리로 분류해 줘", "스팸인지 판단", "감정 분석해 줘",
                       "어느 주제에 속하는지", "classify the sentiment"],
    "extraction": ["이 글에서 날짜와 장소만 뽑아 줘", "이름과 이메일을 표로 정리", "JSON으로 추출해 줘", "핵심 수치만 뽑아 줘",
                   "참고문헌 목록만 뽑아", "extract the names"],
    "browser": ["이 웹페이지 요약해 줘", "이 사이트에서 정보를 찾아 줘", "페이지 내용 설명", "이 기사의 요점", "검색 결과에서 찾아 줘"],
    "paper": ["이 논문의 기여가 뭐야", "3쪽의 실험 설정을 설명해 줘", "논문 요약", "이 논문의 방법론", "abstract 번역해 줘",
              "이 표의 결과를 설명", "관련 연구와 비교"],
    "research": ["이 실험 결과로 가설을 검증할 수 있을까", "두 방법의 장단점을 비판적으로 비교", "이 수식을 유도해 줘",
                 "연구 방향을 제안해 줘", "이 결과의 한계점과 원인", "인과 관계를 분석", "증명해 줘"],
    "coding": ["이 코드 버그 고쳐 줘", "파이썬 함수 만들어 줘", "이 에러 메시지 원인", "리팩터링해 줘", "테스트 코드 작성",
               "이 코드 설명해 줘", "verilog 모듈 작성", "fix this bug", "write a function", "코드 리뷰해 줘"],
    "agent_planning": ["작업 폴더의 파일을 정리해 줘", "여러 단계로 처리해 줘", "프로젝트 전체를 분석해서 계획 세워 줘",
                       "자동으로 해 줘", "순서대로 실행해 줘"],
    "tool_execution": ["명령을 실행해 줘", "테스트를 돌려 줘", "깃허브 이슈 만들어 줘", "메일 보내 줘", "파일 저장해 줘"],
    "data_lab": ["이 CSV 데이터 분석해 줘", "실험 결과 비교해 줘", "평균과 표준편차 계산", "그래프로 그릴 열 추천", "데이터 스키마 설명",
                 "Run 7과 Run 12의 차이", "정확도가 어떻게 달라지는지"],
}


# 어느 작업에나 나오는 말(요청 표현). 의미 분류에서 빼야 '설명해 줘' 같은 말에 끌려가지 않는다.
STOPWORDS = {"이", "그", "저", "좀", "줘", "해", "해줘", "해서", "하고", "주세요", "알려", "알려줘", "설명해", "설명", "부탁해", "다음",
             "이거", "이것", "그거", "뭐", "the", "a", "an", "this", "that", "please", "me", "it", "to", "of", "is"}


def _grams(text):
    text = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    grams = Counter()
    for word in re.findall(r"[0-9a-z가-힣]+", text):
        if word in STOPWORDS:
            continue
        padded = f" {word} "
        if len(padded) < 3:
            continue
        grams.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return grams


def _cos(a, b):
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


_PROTOS = None


def semantic(text):
    """(작업, 1위 비슷함, 1·2위 차이). 예시마다 비슷함을 재고 작업마다 가장 높은 값을 쓴다."""
    global _PROTOS
    if _PROTOS is None:
        _PROTOS = {task: [_grams(e) for e in examples] for task, examples in EXAMPLES.items()}
    q = _grams(str(text or "")[:2000])
    scores = sorted(((max(_cos(q, p) for p in protos), task) for task, protos in _PROTOS.items()), reverse=True)
    (top, task), (second, _) = scores[0], scores[1]
    return task, round(top, 3), round(top - second, 3)


@dataclass
class Analysis:
    task: str = "other"
    difficulty: str = "moderate"
    confidence: float = 0.0           # 분류 확신(0~1). 규칙으로 정했으면 1
    method: str = "rule"              # rule | semantic | purpose | ood
    est_tokens: int = 0
    images: bool = False
    attachments: bool = False
    needs_tools: bool = False
    needs_fresh: bool = False
    grounding: str = "normal"         # normal | high
    side_effects: bool = False
    sensitive: bool = False
    korean: bool = False


def analyze(prompt, task_text="", purpose="chat", images=False, attachments=False, side_effects=False):
    """요청 분석. prompt는 모델에 보낼 전체 글, task_text는 사용자가 쓴 요청(분류는 이것으로 한다)."""
    a = Analysis(est_tokens=estimate_tokens(prompt), images=bool(images), attachments=bool(attachments),
                 side_effects=bool(side_effects), sensitive=sensitive(prompt))
    text = str(task_text or prompt or "")
    a.korean = len(HANGUL.findall(text)) >= max(2, len(text) // 20)
    a.needs_fresh = bool(FRESH_RE.search(text))
    a.grounding = "high" if GROUND_RE.search(text) else "normal"
    if purpose in PURPOSES:
        a.task, a.difficulty = PURPOSES[purpose]
        a.method, a.confidence = "purpose", 1.0
        a.needs_tools = purpose in ("agent_step", "code_agent_step")
        a.side_effects = a.side_effects or a.needs_tools
        return _adjust(a, text)
    marker = next((task for task, mark in MARKERS if mark in str(prompt or "")), None)
    rule = None
    if PROOF_RE.search(text) or (DESIGN_RE.search(text) and not CODE_RE.search(text)):
        rule = "research" if marker != "data_lab" else "data_lab"
    elif marker == "coding" or (CODE_RE.search(text) and (EDIT_RE.search(text) or marker is None)) or \
            (CODE_WORD_RE.search(text) and marker is None and not TRANSLATE_RE.search(text) and not SUMMARY_RE.search(text)):
        rule = "coding"
    elif marker in ("browser", "paper", "data_lab"):
        rule = marker
    elif TRANSLATE_RE.search(text):
        rule = "translation"
    elif SUMMARY_RE.search(text):
        rule = "summarization"
    elif CLASSIFY_RE.search(text):
        rule = "classification"
    elif EXTRACT_RE.search(text):
        rule = "extraction"
    elif a.images and not CODE_WORD_RE.search(text):
        rule = "general_chat"  # 이미지 설명·질문(로컬 vision 지원 여부는 제약 단계가 본다)
    elif a.needs_fresh:
        rule = "general_chat"  # 최신 정보
    elif marker is None and len(text) <= 60 and LOOKUP_RE.search(text) and not EDIT_RE.search(text):
        rule = "general_chat"  # 짧은 사실 질문(분류 불확실로 보내지 않는다): 로컬·Cloud 모두 학습 이후 소식을 모른다(난이도를 올려 보수적으로)
    if rule:
        a.task, a.method, a.confidence = rule, "rule", 1.0
    else:
        task, top, margin = semantic(text)
        if top < SEMANTIC_MIN or margin < SEMANTIC_MARGIN:
            a.task, a.method, a.confidence = "other", "ood", round(top, 3)
        else:
            a.task, a.method, a.confidence = task, "semantic", round(min(1.0, top + margin), 3)
    a.difficulty = _difficulty(a, text)
    return _adjust(a, text)


def _difficulty(a, text):
    t = a.task
    short_lookup = len(text) <= 80 and LOOKUP_RE.search(text) and not PROOF_RE.search(text) and not DESIGN_RE.search(text)
    if t in ("agent_planning", "tool_execution"):
        return "critical"
    if t == "research" or (t == "data_lab" and PROOF_RE.search(text)):
        return "hard"
    if t == "coding":
        if EDIT_RE.search(text):
            return "hard"
        return "easy" if short_lookup or (len(text) <= 80 and re.search(r"설명|출력|뭐 하는|하는 일", text)) else "moderate"
    if t in ("paper", "data_lab", "browser"):
        if short_lookup and not SUMMARY_RE.search(text):
            return "easy"  # 첨부한 글·표에서 값 하나 찾기
        if (SUMMARY_RE.search(text) or EXTRACT_RE.search(text)) and a.est_tokens < 3000:
            return "easy"
        if t == "browser":
            return "moderate"
        return "moderate" if SUMMARY_RE.search(text) or EXTRACT_RE.search(text) else "hard"
    if t in ("translation", "summarization", "classification", "extraction"):
        return "easy" if a.est_tokens < 2500 else "moderate"
    if t == "general_chat":
        return "easy" if len(text) < 300 else "moderate"
    return "moderate"


def _adjust(a, text):
    """공통 보정: 아주 긴 입력, 높은 근거 요구, 최신 정보는 한 단계 어렵게."""
    order = list(DIFFICULTIES)
    level = order.index(a.difficulty)
    if a.est_tokens > 12000:
        level = max(level, order.index("hard"))
    if a.grounding == "high" and a.task in ("paper", "browser", "research", "data_lab"):
        level = max(level, order.index("moderate")) + (1 if level >= order.index("moderate") else 0)
    if a.needs_fresh:
        level = max(level, order.index("moderate"))
    if a.method == "ood":
        level = max(level, order.index("moderate"))
    a.difficulty = order[min(level, len(order) - 1)]
    return a


# ---- 측정 기록(로컬 모델 × 작업의 성공률) ----

_stats_lock = threading.Lock()


def stats_path():
    return storage.APP_DIR / "adaptive" / "stats.json"


def load_stats():
    try:
        data = json.loads(stats_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_outcome(model, task, ok, source="gate"):
    """로컬 모델 답의 검증 결과(또는 사용자 👍👎·벤치마크)를 더한다. 내용은 남기지 않는다."""
    with _stats_lock:
        data = load_stats()
        row = data.setdefault(str(model)[:200], {}).setdefault(str(task), {"n": 0, "ok": 0})
        row["n"] += 1
        row["ok"] += 1 if ok else 0
        row.setdefault("sources", {})
        row["sources"][source] = row["sources"].get(source, 0) + 1
        path = stats_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def success_rate(stats, model, task):
    """(성공률, 표본 수). 표본이 없으면 (None, 0)."""
    row = ((stats or {}).get(model) or {}).get(task) or {}
    n = int(row.get("n") or 0)
    return (round(row.get("ok", 0) / n, 3) if n else None), n


# ---- 결정 ----

@dataclass
class Candidate:
    provider: str                 # local | cloud
    model: str
    context_length: int = 0
    vision: bool = False
    json: bool = True
    memory_ok: bool = True
    available: bool = True
    tokens_per_s: float = 0.0
    cost: object = None           # Cloud 요청 하나의 크레딧 추정(근거 없으면 None). 로컬은 0(Cloud API 비용만)


@dataclass
class Route:
    provider: str = "cloud"       # local | cloud | none(보낼 곳 없음: 오류로 알린다)
    model: str = ""
    policy: str = "balanced"
    reason_code: str = ""
    reason: str = ""              # 사용자에게 보이는 짧은 이유
    analysis: dict = field(default_factory=dict)
    constraints: list = field(default_factory=list)   # 적용한 제약 코드
    escalation: bool = False      # 로컬 답이 검증에 실패하면 Cloud로 다시 할 수 있는지
    fallback_model: str = ""      # 승격할 Cloud 모델
    est_cost: object = None
    stage: str = "rule"           # rule | semantic | measured | default
    tier: str = ""                # local | light | frontier (1.17 3단계: 경량 Cloud 모델을 켰을 때)
    consult: bool = False         # 경량 모델이 필요할 때 프런티어 모델에 짧게 상담할 수 있는지

    def to_dict(self):
        return asdict(self)


# 경량 Cloud 모델(예: Claude Haiku, GPT-5 mini)이 혼자 답해도 되는 가장 어려운 난이도. 그보다 어려우면 상담 또는 프런티어.
LIGHT_DIRECT = {"economy": "hard", "balanced": "moderate", "quality": "moderate"}
# 상담(경량 모델이 이끌고 프런티어에 짧게 묻기)을 쓰는 정책. Quality는 어려운 일을 처음부터 프런티어가 맡는다.
CONSULT_POLICIES = ("economy", "balanced")


def tier(route, a, light, settings, allow_consult=True):
    """route()가 Cloud로 정한 요청을 경량 모델·상담·프런티어 중 하나로 나눈다(경량 모델을 켰을 때만). route를 고쳐 돌려준다.
    - 파일·명령·외부 작업으로 이어지는 단계(중요·위험)는 언제나 프런티어.
    - 정책이 허용하는 난이도까지는 경량 모델이 혼자 답한다(검증에 실패하면 프런티어로 승격).
    - 더 어려운 일은 상담을 켰으면 경량 모델이 맥락을 들고 답하며 필요한 부분만 프런티어에 묻는다. 아니면 프런티어."""
    settings = settings or {}
    if route.provider != "cloud" or light is None or not light.available:
        if route.provider == "cloud":
            route.tier = "frontier"
        elif route.provider == "local":
            route.tier = "local"
        return route
    task_label = TASK_LABELS.get(a.task, a.task)
    consult_ok = allow_consult and bool(settings.get("consult", True)) and route.policy in CONSULT_POLICIES \
        and int(settings.get("consult_max", 1) or 0) > 0
    if a.side_effects or a.difficulty == "critical":
        route.tier = "frontier"
        return route
    limit = LIGHT_DIRECT.get(route.policy)
    direct = limit is not None and DIFFICULTIES.index(a.difficulty) <= DIFFICULTIES.index(limit) \
        and not (a.method == "ood" and route.policy == "quality")
    if direct:
        route.provider, route.model, route.tier, route.consult = "light", light.model, "light", consult_ok
        route.reason_code, route.est_cost = "light", light.cost
        route.reason = f"{task_label}({DIFF_LABELS[a.difficulty]}) · 경량 Cloud 모델로 충분" + (" · 필요하면 프런티어에 상담" if consult_ok else "")
        return route
    if consult_ok:
        route.provider, route.model, route.tier, route.consult = "light", light.model, "light", True
        route.reason_code, route.est_cost = "light_consult", light.cost
        route.reason = f"{task_label}({DIFF_LABELS[a.difficulty]}) · 경량 모델이 이끌고 필요한 부분만 프런티어에 상담"
        return route
    route.tier = "frontier"
    return route


def light_ok_for(policy, a):
    """로컬 답이 검증에 실패했을 때 경량 모델로 먼저 올려도 되는지(아니면 바로 프런티어)."""
    limit = LIGHT_DIRECT.get(policy)
    return limit is not None and not a.side_effects and a.difficulty != "critical" and \
        DIFFICULTIES.index(a.difficulty) <= DIFFICULTIES.index(limit)


def _eligible(policy, task, difficulty):
    limit = LOCAL_ELIGIBLE.get(policy, {}).get(task)
    return limit is not None and DIFFICULTIES.index(difficulty) <= DIFFICULTIES.index(limit)


def route(analysis, policy, local, cloud, settings, stats=None, budget=None):
    """analysis: Analysis, local: Candidate 또는 None(로컬 모델 없음), cloud: Candidate 또는 None(Cloud 키 없음 등),
    settings: config["adaptive"], budget: {"exceeded": bool, "reason": str}. 반드시 Route를 돌려준다."""
    policy = policy if policy in POLICIES else "balanced"
    a = analysis
    privacy_cfg = (settings or {}).get("privacy") or {}
    r = Route(policy=policy, analysis=asdict(a))
    reasons_local_out = []

    def local_usable():
        if local is None or not local.available:
            reasons_local_out.append(("local_unavailable", "로컬 모델 없음"))
            return False
        if a.images and not local.vision:
            reasons_local_out.append(("no_vision", "로컬 모델이 이미지를 읽지 못함"))
            return False
        if local.context_length and a.est_tokens > int(local.context_length * 0.9):
            reasons_local_out.append(("context", "입력이 로컬 모델의 문맥 길이를 넘음"))
            return False
        if not local.memory_ok:
            reasons_local_out.append(("memory", "이 PC의 메모리가 모자랄 수 있음"))
            return False
        return True

    must_local = policy == "local_only"
    if not must_local and privacy_cfg.get("sensitive_local_only") and a.sensitive:
        must_local = True
        r.constraints.append("sensitive_local")
    if not must_local and privacy_cfg.get("attachments_to_cloud") is False and a.attachments:
        must_local = True
        r.constraints.append("attachments_local")
    use_local = local_usable()
    cloud_ok = cloud is not None and cloud.available and not must_local
    if cloud_ok and budget and budget.get("exceeded"):
        cloud_ok = False
        r.constraints.append("budget")
    limit = float((settings or {}).get("max_cost_per_request") or 0)
    if cloud_ok and limit and cloud.cost is not None and cloud.cost > limit:
        cloud_ok = False
        r.constraints.append("cost_limit")
    r.fallback_model = cloud.model if cloud_ok else ""

    def go_local(code, why, stage):
        r.provider, r.model, r.reason_code, r.reason, r.stage = "local", local.model, code, why, stage
        r.escalation = cloud_ok and bool((settings or {}).get("escalation", True)) and policy != "local_only"
        r.est_cost = 0
        return r

    def go_cloud(code, why, stage):
        r.provider, r.model, r.reason_code, r.reason, r.stage = "cloud", cloud.model, code, why, stage
        r.est_cost = cloud.cost
        return r

    task_label = TASK_LABELS.get(a.task, a.task)
    # 1단계: 반드시 지킬 제약
    if must_local:
        r.constraints.append("local_only" if policy == "local_only" else "privacy")
        if use_local:
            return go_local("local_required", "로컬 전용" if policy == "local_only" else "개인정보 보호 설정: 로컬에서만", "rule")
        r.provider, r.reason_code, r.stage = "none", "local_required_unavailable", "rule"
        r.reason = ("로컬 전용 정책인데 " if policy == "local_only" else "개인정보 보호 설정상 Cloud로 보낼 수 없는데 ") + \
            (reasons_local_out[0][1] if reasons_local_out else "로컬 모델을 쓸 수 없음")
        return r
    if not cloud_ok:
        if use_local:
            why = {"budget": "Cloud 예산 초과", "cost_limit": "요청당 비용 한도 초과"}.get(r.constraints[-1] if r.constraints else "",
                                                                                     "Cloud를 쓸 수 없음")
            return go_local("cloud_unavailable", f"{why}: 로컬로", "rule")
        r.provider, r.reason_code, r.stage = "none", "nothing_available", "rule"
        r.reason = "쓸 수 있는 모델이 없음(" + ", ".join([x[1] for x in reasons_local_out] + (
            ["Cloud 예산 초과"] if "budget" in r.constraints else ["요청당 비용 한도 초과"] if "cost_limit" in r.constraints
            else ["Cloud 키 없음"])) + ")"
        return r
    if not use_local:
        why = reasons_local_out[0][1] if reasons_local_out else "로컬 사용 불가"
        return go_cloud(reasons_local_out[0][0] if reasons_local_out else "local_unavailable", f"{task_label} · {why}", "rule")
    if a.side_effects or a.difficulty == "critical":
        return go_cloud("critical", f"{task_label} · 파일·명령·외부 작업으로 이어질 수 있어 Cloud", "rule")
    # 2단계: 분류 결과가 불확실하면 보수적으로
    if a.method == "ood" and policy != "economy":
        return go_cloud("ood", "요청 종류가 불확실해 Cloud", "semantic")
    eligible = _eligible(policy, a.task, a.difficulty)
    fast = (settings or {}).get("latency") == "fast" and a.difficulty == "easy" and local.tokens_per_s >= 15
    if not eligible and not fast:
        return go_cloud("policy", f"{task_label}({DIFF_LABELS[a.difficulty]}) · {POLICY_LABELS[policy]} 정책상 Cloud", "rule")
    # 3단계: 측정 기록
    rate, n = success_rate(stats, local.model, a.task)
    floor = FLOORS[policy]
    if n >= MIN_SAMPLES and rate is not None:
        if rate < floor:
            return go_cloud("measured_low", f"{task_label} · 로컬 측정 성공률 {round(rate * 100)}%가 기준 {round(floor * 100)}%보다 낮음",
                            "measured")
        return go_local("measured_ok", f"{task_label} · 로컬 측정 성공률 {round(rate * 100)}% (표본 {n})", "measured")
    if policy == "quality" and not fast:
        return go_cloud("unmeasured", f"{task_label} · 로컬 품질이 아직 측정되지 않아 Cloud", "default")
    return go_local("rule_default", f"{task_label}" + (" · 빠른 응답 우선" if fast and not eligible else " · 로컬로 충분한 작업"),
                    "default")
