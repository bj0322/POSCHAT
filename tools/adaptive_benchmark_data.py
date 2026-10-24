# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive AI 벤치마크 데이터셋(1.17)을 만든다: python tools/adaptive_benchmark_data.py → tools/data/adaptive_benchmark.json

요청마다 정답(reference)·채점 규칙(expect)·허용 오차·검증 방법·예상 난이도·라우팅 정답(route_label)을 함께 둔다.
- 글은 이 파일에서 직접 쓴 짧은 예문이다(실제 논문·웹페이지·개인 정보를 쓰지 않는다 — 저작권·개인정보 문제 없음).
- route_label은 데이터를 만든 사람이 작업 성격으로 정한 정답이다(라우터 코드에서 거꾸로 만들지 않는다):
    local_ok      작고 검증하기 쉬운 일(짧은 요약·번역·분류·추출, 주어진 글에서 사실 찾기, 단순 계산)
    cloud_needed  틀리면 비용이 큰 일(연구 추론·비판, 코드 수정·작성, 에이전트 계획, 통계 해석, 여러 문서 종합)
- expect는 evals.score 규칙(contains·any·not_contains·regex·json_keys·max_chars)에 number({"value", "tol"})를 더한 것.
같은 입력이면 늘 같은 JSON이 나온다(무작위 없음).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "adaptive_benchmark.json"


def case(cid, category, task, difficulty, route, prompt, expect, reference, verify, context=None, tolerance=None, lang="ko"):
    return {"id": cid, "category": category, "task": task, "difficulty": difficulty, "route_label": route, "lang": lang,
            "prompt": prompt, "context": context, "expect": expect, "reference": reference, "verify": verify,
            "tolerance": tolerance}


def general():
    out = []
    facts = [
        ("예산 회의", "다음 주 금요일까지 발표 자료를 만들고, 예산은 300만 원으로 확정했다. 담당은 김 연구원이다.", ["300만", "금요일"]),
        ("세미나 공지", "3월 14일 오후 4시 무은재기념관 101호에서 반도체 소자 세미나가 열린다. 사전 신청은 필요 없다.", ["3월 14일", "101호"]),
        ("동아리 모임", "이번 모임은 토요일 오전 10시 학생회관 앞에서 출발하며 회비는 2만 원이다.", ["토요일", "2만"]),
        ("실험실 안전", "레이저 실험 전에는 보안경을 반드시 쓰고, 실험 일지에 시작 시각을 적어야 한다.", ["보안경", "일지"]),
        ("기숙사 공지", "기숙사 정기 점검은 5월 2일에 있으며 그날 오후 1시부터 3시까지 방을 비워야 한다.", ["5월 2일", "1시"]),
        ("수강 신청", "수강 정정 기간은 2월 26일부터 3월 4일까지이고, 정정은 하루 세 번까지 가능하다.", ["2월 26일", "3월 4일"]),
        ("도서관", "중앙도서관은 시험 기간 동안 24시간 열고, 4층 열람실은 대학원생 전용으로 바뀐다.", ["24시간", "4층"]),
        ("연구 미팅", "다음 미팅에서는 ADC 해상도 실험 결과를 발표하고, 박사과정 학생이 노이즈 분석을 맡는다.", ["ADC", "노이즈"]),
        ("장학금", "성적 우수 장학금은 직전 학기 평점 3.8 이상이고 18학점 이상 들은 학생에게 준다.", ["3.8", "18학점"]),
        ("학회 출장", "학회 출장비는 항공료와 숙박비를 합쳐 150만 원까지 지원하며 영수증을 꼭 내야 한다.", ["150만", "영수증"]),
    ]
    for i, (title, text, keys) in enumerate(facts):
        out.append(case(f"gen-sum-{i:02d}", "general", "summarization", "easy", "local_ok",
                        f"다음 '{title}' 글을 한 문장으로 요약해 줘.\n\n{text}",
                        {"contains": keys}, text, "핵심 사실 두 가지가 들어 있는지(포함 검사)"))
    trans = [
        ("오늘 회의는 3시에 시작합니다.", ["3"], ["meeting"]), ("실험 결과를 다음 주에 공유하겠습니다.", [], ["result", "next week"]),
        ("이 논문은 새로운 학습 방법을 제안한다.", [], ["paper", "propos"]), ("배터리가 거의 다 떨어졌어요.", [], ["battery"]),
        ("도서관은 밤 11시에 닫습니다.", ["11"], ["library"]), ("시험 범위는 5장부터 8장까지입니다.", ["5", "8"], ["chapter"]),
        ("데이터를 백업해 두세요.", [], ["back"]), ("교수님께 메일을 보냈습니다.", [], ["professor", "email"]),
        ("이 모델은 정확도가 높지만 느립니다.", [], ["accura", "slow"]), ("내일 비가 올 것 같아요.", [], ["rain", "tomorrow"]),
    ]
    for i, (ko, nums, words) in enumerate(trans):
        expect = {"contains": nums}
        if words:
            expect["any"] = words + [w.capitalize() for w in words]
        out.append(case(f"gen-tr-{i:02d}", "general", "translation", "easy", "local_ok",
                        f"다음 문장을 자연스러운 영어로 번역해 줘. 번역문만 써 줘.\n{ko}", expect,
                        {"0": "The meeting starts at 3 today."}.get(str(i), " ".join(words) + " " + " ".join(nums)),
                        "핵심 낱말이 영어로 있는지(any)", lang="ko"))
    out[-10]["reference"] = "Today's meeting starts at 3 o'clock."
    out[-9]["reference"] = "I will share the result of the experiment next week."
    out[-8]["reference"] = "This paper proposes a new learning method."
    out[-7]["reference"] = "My battery is almost dead."
    out[-6]["reference"] = "The library closes at 11 p.m."
    out[-5]["reference"] = "The exam covers chapter 5 through chapter 8."
    out[-4]["reference"] = "Please back up the data."
    out[-3]["reference"] = "I sent an email to the professor."
    out[-2]["reference"] = "This model has high accuracy but it is slow."
    out[-1]["reference"] = "I think it will rain tomorrow."
    senti = [
        ("배송이 빠르고 품질도 기대 이상이에요.", "긍정"), ("두 번 썼는데 바로 고장 났습니다.", "부정"), ("그냥 무난합니다. 특별한 건 없어요.", "중립"),
        ("강의가 정말 알차고 재미있었어요!", "긍정"), ("설명서가 엉망이라 하나도 못 알아듣겠네요.", "부정"),
        ("가격 대비 괜찮은 편이에요.", "긍정"), ("다시는 이 식당에 안 갑니다.", "부정"), ("평범한 하루였다.", "중립"),
        ("발표가 생각보다 잘 끝나서 기분이 좋다.", "긍정"), ("서버가 또 멈춰서 실험을 다시 해야 한다.", "부정"),
    ]
    for i, (text, label) in enumerate(senti):
        out.append(case(f"gen-cls-{i:02d}", "general", "classification", "easy", "local_ok",
                        f'다음 문장의 감정을 JSON 객체 하나로만 답해 줘. 형식: {{"label": "긍정|부정|중립"}}\n문장: {text}',
                        {"json_keys": ["label"], "contains": [label]}, json.dumps({"label": label}, ensure_ascii=False),
                        "JSON 형식과 정답 라벨(포함 검사)"))
    extract = [
        ("김민수(kim.ms@example.org)가 4월 3일 오후 2시에 연구실 B204에서 면담을 요청했다.", ["4월 3일", "B204"], "날짜와 장소"),
        ("주문 번호 A-1029, 수량 3개, 총액 45,000원, 배송지는 포항시 남구.", ["A-1029", "45,000"], "주문 번호와 총액"),
        ("ICML 2026 마감은 1월 30일, 결과 발표는 5월 8일, 학회는 7월 서울에서 열린다.", ["1월 30일", "5월 8일"], "마감일과 발표일"),
        ("측정 결과: 전압 3.3V, 전류 120mA, 온도 41도.", ["3.3", "120"], "전압과 전류"),
        ("참가자는 이지은, 박준호, 최서연 세 명이며 박준호가 발표를 맡는다.", ["박준호"], "발표자"),
        ("버스는 07:40, 08:10, 08:40에 출발하고 마지막 차는 22:30이다.", ["22:30"], "마지막 차 시각"),
        ("이번 학기 조교는 정하늘(대학원 2년차)이고 상담 시간은 화요일 3시다.", ["정하늘", "화요일"], "조교 이름과 상담 요일"),
        ("논문 심사위원은 세 명이며, 위원장은 한도윤 교수, 외부 위원은 KAIST 소속이다.", ["한도윤"], "위원장"),
        ("모델 A는 파라미터 7B, 모델 B는 13B, 모델 C는 70B이다.", ["70B"], "가장 큰 모델"),
        ("예약: 3명, 6월 12일 저녁 7시, 창가 자리 요청.", ["6월 12일", "7시"], "날짜와 시각"),
    ]
    for i, (text, keys, what) in enumerate(extract):
        out.append(case(f"gen-ext-{i:02d}", "general", "extraction", "easy", "local_ok",
                        f"다음 글에서 {what}만 뽑아 줘.\n{text}", {"contains": keys}, " ".join(keys), "뽑은 값이 원문과 같은지(포함 검사)"))
    chat = [
        ("POSTECH의 정식 한국어 이름을 한 줄로 알려 줘.", {"contains": ["포항공과대학교"]}, "포항공과대학교"),
        ("17 × 23은 얼마야? 숫자만 답해 줘.", {"regex": r"^\D*391\D*$", "max_chars": 20}, "391"),
        ("물의 화학식을 알려 줘.", {"any": ["H2O", "H₂O"]}, "H2O"),
        ("한 주는 며칠이야? 숫자로만.", {"regex": r"7", "max_chars": 20}, "7"),
        ("'인공지능'을 영어로 한두 단어로만.", {"any": ["Artificial Intelligence", "artificial intelligence", "AI"], "max_chars": 40}, "Artificial Intelligence"),
        ("1부터 10까지 더하면? 숫자만.", {"regex": r"^\D*55\D*$", "max_chars": 20}, "55"),
        ("빛의 삼원색을 알려 줘.", {"contains": ["빨", "초", "파"]}, "빨강, 초록, 파랑"),
        ("대한민국의 수도는?", {"contains": ["서울"]}, "서울"),
        ("2의 10제곱은? 숫자만.", {"regex": r"1024|1,024", "max_chars": 20}, "1024"),
        ("고마워! 오늘도 수고했어.", {"not_contains": ["```"]}, "천만에요. 오늘도 수고 많으셨어요!"),
    ]
    for i, (prompt, expect, ref) in enumerate(chat):
        out.append(case(f"gen-chat-{i:02d}", "general", "general_chat", "easy", "local_ok", prompt, expect, ref, "정답 글자·정규식"))
    return out


def web(text, url):
    return {"kind": "web", "source": f"웹페이지 {url}", "text": f"주소: {url}\n{text}"}


def browser():
    out = []
    pages = [
        ("https://lab.example.ac.kr/news/42", "AIMC 연구실은 2026년 10월 아날로그 인메모리 컴퓨팅 칩을 발표했다. 칩은 8비트 ADC를 쓰며 전력 효율은 25 TOPS/W이다. 자세한 내용은 https://lab.example.ac.kr/paper 에 있다.",
         [("이 페이지의 핵심을 한 문장으로 요약해 줘.", {"contains": ["칩"]}, "AIMC 연구실이 8비트 ADC를 쓴 25 TOPS/W 칩을 발표했다.", "easy", "local_ok", "summarization"),
          ("이 칩의 전력 효율은 얼마라고 적혀 있어?", {"contains": ["25"]}, "25 TOPS/W", "easy", "local_ok", "extraction"),
          ("ADC 비트 수를 알려 줘.", {"contains": ["8"]}, "8비트", "easy", "local_ok", "extraction"),
          ("이 발표가 업계 경쟁 구도에 어떤 영향을 줄지 근거를 들어 비판적으로 분석해 줘.", {"contains": ["25"]}, "25 TOPS/W는 ...", "hard", "cloud_needed", "research")]),
        ("https://news.example.com/campus/123", "포항공대 총학생회는 11월 3일부터 7일까지 축제를 연다고 밝혔다. 올해는 친환경 컵을 쓰고, 공연은 대운동장에서 열린다.",
         [("기사 요점만 알려 줘.", {"contains": ["11월"]}, "11월 3일부터 7일까지 축제", "easy", "local_ok", "summarization"),
          ("공연 장소는 어디야?", {"contains": ["대운동장"]}, "대운동장", "easy", "local_ok", "extraction"),
          ("축제 기간은?", {"contains": ["3일", "7일"]}, "11월 3일부터 7일까지", "easy", "local_ok", "extraction")]),
        ("https://docs.example.org/install", "설치 방법: 1) 파이썬 3.11을 설치한다. 2) pip install poschat-tools 를 실행한다. 3) 설정 파일 config.toml에 키를 넣는다. 윈도우에서는 관리자 권한이 필요 없다.",
         [("설치 단계를 순서대로 정리해 줘.", {"contains": ["3.11", "config.toml"]}, "1) 파이썬 3.11 2) pip 설치 3) config.toml", "easy", "local_ok", "summarization"),
          ("어떤 파이썬 버전이 필요해?", {"contains": ["3.11"]}, "3.11", "easy", "local_ok", "extraction"),
          ("윈도우에서 관리자 권한이 필요해?", {"any": ["필요 없", "필요하지 않"]}, "필요 없다", "easy", "local_ok", "extraction")]),
        ("https://shop.example.com/item/77", "무선 키보드 K7. 가격 59,000원. 배터리 6개월. 블루투스 5.3. 한글 각인. 리뷰 평점 4.6/5 (1,203개).",
         [("이 상품의 가격과 평점을 알려 줘.", {"contains": ["59,000", "4.6"]}, "59,000원, 4.6점", "easy", "local_ok", "extraction"),
          ("배터리는 얼마나 가?", {"contains": ["6개월"]}, "6개월", "easy", "local_ok", "extraction"),
          ("상품 정보를 한 줄로 요약해 줘.", {"contains": ["K7"]}, "무선 키보드 K7, 59,000원", "easy", "local_ok", "summarization")]),
        ("https://wiki.example.org/transformer", "트랜스포머는 2017년에 소개된 모델 구조로, 순환 구조 없이 어텐션만으로 문장을 처리한다. 인코더와 디코더로 이루어지며 병렬 학습이 쉽다.",
         [("이 문서를 세 줄로 요약해 줘.", {"contains": ["2017", "어텐션"]}, "2017년, 어텐션만으로", "easy", "local_ok", "summarization"),
          ("트랜스포머가 소개된 해는?", {"contains": ["2017"]}, "2017년", "easy", "local_ok", "extraction"),
          ("이 설명에서 빠진 한계점과, 순환 신경망과의 비교 실험을 어떻게 설계할지 제안해 줘.", {"contains": ["어텐션"]}, "...", "hard", "cloud_needed", "research")]),
        ("https://seminar.example.ac.kr/2026", "세미나 일정: 10/28 저전력 회로(김교수), 11/4 뉴로모픽 칩(이교수), 11/11 양자 소자(박교수). 장소는 모두 공학1동 112호.",
         [("뉴로모픽 칩 세미나는 언제야?", {"contains": ["11/4"]}, "11/4", "easy", "local_ok", "extraction"),
          ("세미나 장소는?", {"contains": ["112"]}, "공학1동 112호", "easy", "local_ok", "extraction"),
          ("일정을 표로 정리해 줘.", {"contains": ["10/28", "11/11"]}, "|날짜|주제|...", "easy", "local_ok", "extraction")]),
        ("https://policy.example.go.kr/notice", "2027년부터 대학원생 연구장려금은 월 80만 원에서 100만 원으로 오른다. 대상은 전일제 학생이며 신청은 학기 시작 2주 전까지다.",
         [("바뀌는 금액을 알려 줘.", {"contains": ["80만", "100만"]}, "80만 원 → 100만 원", "easy", "local_ok", "extraction"),
          ("이 공지를 한 문장으로 요약해 줘.", {"contains": ["100만"]}, "2027년부터 장려금이 월 100만 원으로 오른다", "easy", "local_ok", "summarization"),
          ("이 정책이 연구실 운영과 학생 수급에 미칠 영향을 장단점으로 분석해 줘.", {"contains": ["100만"]}, "...", "hard", "cloud_needed", "research")]),
        ("https://blog.example.com/post/9", "Rust로 바꾼 뒤 서버 응답 시간이 120ms에서 45ms로 줄었다. 메모리는 1.2GB에서 300MB로 줄었다. 대신 빌드 시간은 두 배가 되었다.",
         [("응답 시간이 어떻게 바뀌었어?", {"contains": ["120", "45"]}, "120ms → 45ms", "easy", "local_ok", "extraction"),
          ("단점은 뭐라고 했어?", {"contains": ["빌드"]}, "빌드 시간이 두 배", "easy", "local_ok", "extraction"),
          ("글 요점을 정리해 줘.", {"contains": ["45"]}, "응답 45ms, 메모리 300MB, 빌드 두 배", "easy", "local_ok", "summarization")]),
        ("https://forum.example.com/t/55", "질문: 파이썬에서 리스트를 복사하면 원본도 바뀌어요. 답변: b = a 는 같은 객체를 가리킵니다. a.copy() 나 copy.deepcopy(a) 를 쓰세요.",
         [("해결 방법을 알려 줘.", {"any": ["copy()", "deepcopy"]}, "a.copy() 또는 copy.deepcopy(a)", "easy", "local_ok", "extraction"),
          ("이 스레드를 요약해 줘.", {"any": ["copy", "복사"]}, "b = a는 같은 객체라 copy를 쓴다", "easy", "local_ok", "summarization")]),
        ("https://jobs.example.com/77", "채용: 반도체 설계 엔지니어. 자격: 석사 이상, Verilog 경력 2년. 근무지 판교. 마감 12월 15일.",
         [("자격 요건을 정리해 줘.", {"contains": ["석사", "Verilog"]}, "석사 이상, Verilog 2년", "easy", "local_ok", "extraction"),
          ("마감일은?", {"contains": ["12월 15일"]}, "12월 15일", "easy", "local_ok", "extraction"),
          ("이 공고와 위 연구장려금 공지를 함께 보고 석사 졸업생의 진로를 비교 분석해 줘.", {"contains": ["석사"]}, "...", "hard", "cloud_needed", "research")]),
    ]
    n = 0
    for url, text, asks in pages:
        for prompt, expect, ref, diff, route, task in asks:
            out.append(case(f"web-{n:02d}", "browser", task if task != "research" else "research", diff, route,
                            prompt, expect, ref, "원문에 있는 사실·숫자인지(포함 검사), 답에 나온 주소가 원문에 있는지(QualityGate)",
                            context=web(text, url)))
            n += 1
    return out


def paper_ctx(text, title="Efficient AIMC", pages="pp. 1-12"):
    return {"kind": "paper", "source": f"논문 PDF '{title}' {pages}", "text": text, "pages": 12}


def paper():
    out = []
    p1 = ("[p. 3] We propose a 6-bit ADC sharing scheme for analog in-memory computing. "
          "[p. 7] Table 2: accuracy 91.2% on CIFAR-10 with 6-bit ADC, 88.4% with 4-bit ADC; energy 12.5 pJ/MAC. "
          "[p. 9] Limitations: device variation above 5% reduces accuracy by up to 3.1 points.")
    p2 = ("[p. 2] Transformers with 12 layers were trained on 4 GPUs for 3.5 days. "
          "[p. 5] BLEU 28.4 on WMT14 En-De, 41.0 on En-Fr. [p. 6] Dropout 0.1, label smoothing 0.1. "
          "[p. 8] Removing positional encoding drops BLEU by 2.2.")
    p3 = ("[p. 4] The SNN chip consumes 3.8 mW at 0.8 V. [p. 6] Latency is 1.2 ms per inference. "
          "[p. 10] Compared to a GPU baseline, energy is reduced 45 times, while accuracy is 1.4 points lower.")
    rows = [
        (p1, "Efficient AIMC", "이 논문이 제안한 것을 한 문장으로 요약해 줘.", {"contains": ["ADC"]}, "6비트 ADC 공유 방식", "moderate", "local_ok", "summarization"),
        (p1, "Efficient AIMC", "6비트 ADC일 때 CIFAR-10 정확도는? 쪽 번호도.", {"contains": ["91.2"], "regex": r"p\.?\s*7|7\s*쪽"}, "91.2% (p. 7)", "easy", "local_ok", "extraction"),
        (p1, "Efficient AIMC", "4비트와 6비트의 정확도 차이를 계산해 줘.", {"number": {"value": 2.8, "tol": 0.05}}, "2.8%p", "easy", "local_ok", "extraction"),
        (p1, "Efficient AIMC", "에너지 수치를 단위와 함께 알려 줘.", {"contains": ["12.5", "pJ"]}, "12.5 pJ/MAC", "easy", "local_ok", "extraction"),
        (p1, "Efficient AIMC", "한계점을 정리해 줘.", {"contains": ["5%", "3.1"]}, "소자 편차 5% 이상이면 최대 3.1점 하락", "easy", "local_ok", "extraction"),
        (p1, "Efficient AIMC", "이 결과로 ADC 비트 수와 정확도 사이의 인과 관계를 주장할 수 있는지 비판적으로 검토해 줘.", {"contains": ["91.2", "88.4"]}, "...", "hard", "cloud_needed", "research"),
        (p1, "Efficient AIMC", "소자 편차를 줄이는 후속 실험을 설계하고, 통제 변수와 기대 결과를 제안해 줘.", {"any": ["편차", "variation"]}, "...", "hard", "cloud_needed", "research"),
        (p1, "Efficient AIMC", "이 논문의 기여를 관련 연구와 비교해 한계점과 함께 평가해 줘.", {"any": ["ADC"]}, "...", "hard", "cloud_needed", "research"),
        (p2, "Attention Study", "학습 설정(층 수, GPU, 기간)을 뽑아 줘.", {"contains": ["12", "3.5"]}, "12층, GPU 4개, 3.5일", "easy", "local_ok", "extraction"),
        (p2, "Attention Study", "En-De BLEU는? 쪽 번호와 함께.", {"contains": ["28.4"], "regex": r"p\.?\s*5|5\s*쪽"}, "28.4 (p. 5)", "easy", "local_ok", "extraction"),
        (p2, "Attention Study", "En-Fr와 En-De의 BLEU 차이를 계산해 줘.", {"number": {"value": 12.6, "tol": 0.05}}, "12.6", "easy", "local_ok", "extraction"),
        (p2, "Attention Study", "이 논문을 세 줄로 요약해 줘.", {"contains": ["28.4"]}, "BLEU 28.4 ...", "moderate", "local_ok", "summarization"),
        (p2, "Attention Study", "위치 인코딩을 빼면 어떻게 돼?", {"contains": ["2.2"]}, "BLEU가 2.2 떨어진다", "easy", "local_ok", "extraction"),
        (p2, "Attention Study", "위치 인코딩 제거 실험의 해석이 타당한지, 대안 가설과 추가 실험으로 검증해 줘.", {"contains": ["2.2"]}, "...", "hard", "cloud_needed", "research"),
        (p2, "Attention Study", "정규화 설정(드롭아웃·라벨 스무딩)을 뽑아 줘.", {"contains": ["0.1"]}, "드롭아웃 0.1, 라벨 스무딩 0.1", "easy", "local_ok", "extraction"),
        (p2, "Attention Study", "이 결과를 재현하려면 무엇이 더 필요한지, 보고되지 않은 정보와 그 영향을 분석해 줘.", {"any": ["GPU", "재현"]}, "...", "hard", "cloud_needed", "research"),
        (p3, "Low-power SNN", "소비 전력과 전압을 알려 줘.", {"contains": ["3.8", "0.8"]}, "3.8 mW, 0.8 V", "easy", "local_ok", "extraction"),
        (p3, "Low-power SNN", "추론 한 번의 지연은?", {"contains": ["1.2"]}, "1.2 ms", "easy", "local_ok", "extraction"),
        (p3, "Low-power SNN", "GPU 대비 결과를 요약해 줘.", {"contains": ["45"]}, "에너지 45배 감소, 정확도 1.4점 낮음", "easy", "local_ok", "summarization"),
        (p3, "Low-power SNN", "에너지 절감과 정확도 손실의 트레이드오프가 실제 응용에서 정당화되는지 비판적으로 논해 줘.", {"contains": ["1.4"]}, "...", "hard", "cloud_needed", "research"),
        (p3, "Low-power SNN", "이 논문과 Efficient AIMC 논문의 에너지 효율을 공정하게 비교할 수 있는지 단위와 조건을 따져 검증해 줘.", {"any": ["단위", "조건"]}, "...", "hard", "cloud_needed", "research"),
        (p3, "Low-power SNN", "초록을 한국어로 번역하듯 핵심을 두 문장으로 정리해 줘.", {"contains": ["3.8"]}, "...", "moderate", "local_ok", "summarization"),
    ]
    for i, (text, title, prompt, expect, ref, diff, route, task) in enumerate(rows):
        out.append(case(f"paper-{i:02d}", "paper", task, diff, route, prompt, expect, ref,
                        "원문의 수치·쪽 번호와 같은지(포함·정규식·허용 오차), 원문에 없는 수치를 지어내지 않았는지(QualityGate)",
                        context=paper_ctx(text, title), tolerance=(expect.get("number") or {}).get("tol")))
    research = [
        "강화학습과 지도학습을 반도체 배치 최적화에 쓸 때 장단점을 비교하고 어떤 실험으로 검증할지 제안해 줘.",
        "아날로그 인메모리 컴퓨팅의 정확도 한계가 어디서 오는지 원인을 나눠 분석하고 각 원인을 검증할 실험을 설계해 줘.",
        "작은 언어 모델로 연구 요약을 자동화할 때 생길 수 있는 오류 유형과 이를 측정할 평가 방법을 제안해 줘.",
        "같은 데이터셋에서 두 모델의 정확도 차이가 0.5%p일 때 통계적으로 유의한지 판단하는 방법을 설명해 줘.",
        "뉴로모픽 칩과 GPU의 에너지 효율 비교에서 흔히 생기는 함정과 공정한 비교 기준을 제시해 줘.",
        "저전력 ADC 설계에서 해상도와 전력의 트레이드오프를 수식으로 유도하고 가정의 한계를 설명해 줘.",
        "연구실의 실험 기록 방식이 재현성에 주는 영향을 분석하고 개선안을 우선순위와 함께 제안해 줘.",
        "트랜스포머의 어텐션 복잡도를 줄이는 방법들을 비교하고 어떤 상황에서 무엇을 고를지 기준을 세워 줘.",
        "양자 소자 연구에서 측정 잡음과 신호를 구분하는 실험 설계를 비판적으로 검토해 줘.",
        "모델 압축(가지치기·양자화·증류)이 정확도와 지연에 주는 영향을 인과적으로 분리해 측정하는 방법을 제안해 줘.",
        "같은 실험을 세 번 반복했을 때 결과가 크게 다르면 어떤 원인을 의심하고 어떻게 검증할지 단계별로 설명해 줘.",
        "논문 리뷰어 입장에서 '정확도 99%' 주장을 검증하려면 무엇을 요구해야 하는지 체크리스트로 만들어 줘.",
        "온디바이스 AI와 클라우드 AI를 비용·지연·개인정보 측면에서 비교하고 연구실 도입 기준을 제안해 줘.",
        "데이터 누수(leakage)가 의심될 때 원인을 찾는 절차와 재발 방지책을 설명해 줘.",
        "하드웨어 가속기 논문에서 TOPS/W 수치를 비교할 때 주의할 점과 정규화 방법을 제시해 줘.",
        "작은 표본(n=8)으로 얻은 실험 결과를 일반화할 수 있는지 통계적·실험적 관점에서 비판해 줘.",
        "연구 가설 '정밀도를 낮춰도 정확도는 유지된다'를 반증하려면 어떤 실험이 필요한지 설계해 줘.",
        "두 가지 설계안 중 하나를 고를 때 의사결정 기준과 가중치를 정하고 민감도 분석을 해 줘.",
        "시뮬레이션 결과와 실제 칩 측정 결과가 다를 때 원인을 체계적으로 분석하는 방법을 설명해 줘.",
        "새 연구 주제를 정할 때 선행 연구 공백을 찾는 방법과 위험을 평가하는 기준을 제안해 줘.",
        "벤치마크 점수 향상이 실제 사용 품질 향상으로 이어지는지 검증하는 방법을 제안해 줘.",
        "연구 데이터 공개 시 개인정보와 재현성 사이의 균형을 어떻게 맞출지 분석해 줘.",
    ]
    for i, prompt in enumerate(research):
        out.append(case(f"research-{i:02d}", "paper", "research", "hard", "cloud_needed", prompt, {"max_chars": 20000, "not_contains": ["```diff"]},
                        "(사람이 평가: 논리·근거·한계 서술)", "규칙으로는 형식만 본다. 내용 품질은 사람 평가(1~5점)가 필요하다"))
    return out


def code_ctx(path, text):
    return {"kind": "code", "source": f"작업 폴더 파일 {path}", "text": f"파일: {path}\n```python\n{text}\n```"}


def code():
    out = []
    explain = [
        ("a.py", "def mean(xs):\n    return sum(xs) / len(xs)", "이 함수가 하는 일을 한 문장으로 설명해 줘.", {"any": ["평균", "mean"]}),
        ("b.py", "import json\nwith open('c.json') as f:\n    cfg = json.load(f)", "이 코드가 하는 일을 설명해 줘.", {"any": ["JSON", "json", "설정"]}),
        ("c.py", "for i in range(3):\n    print(i * i)", "출력 결과를 알려 줘.", {"contains": ["0", "1", "4"]}),
        ("d.py", "def f(n):\n    return 1 if n <= 1 else n * f(n - 1)", "f(5)의 값은?", {"contains": ["120"]}),
        ("e.py", "xs = [3, 1, 2]\nxs.sort()\nprint(xs[0])", "출력은?", {"regex": r"\b1\b"}),
        ("f.py", "s = 'poschat'\nprint(s[::-1])", "출력은?", {"contains": ["tahcsop"]}),
        ("g.py", "d = {'a': 1}\nprint(d.get('b', 0))", "출력은?", {"regex": r"\b0\b"}),
        ("h.py", "print(len(set([1, 1, 2, 3, 3])))", "출력은?", {"regex": r"\b3\b"}),
        ("i.py", "x = 7\nprint('홀수' if x % 2 else '짝수')", "출력은?", {"contains": ["홀수"]}),
        ("j.py", "print(sum(range(1, 11)))", "출력은?", {"contains": ["55"]}),
        ("k.py", "def g(a, b=2):\n    return a ** b\nprint(g(3))", "출력은?", {"contains": ["9"]}),
        ("l.py", "print(' '.join(['a', 'b', 'c']).upper())", "출력은?", {"contains": ["A B C"]}),
    ]
    for i, (path, src, prompt, expect) in enumerate(explain):
        out.append(case(f"code-exp-{i:02d}", "code", "coding", "moderate", "local_ok", prompt, expect, "(정답 값)",
                        "출력값·설명 낱말(포함·정규식)", context=code_ctx(path, src)))
    tasks = [
        ("add", "두 수를 더하는 함수 add(a, b)를 파이썬으로 작성해 줘. 코드 블록 하나로만.", "def add(a, b):\n    return a + b", "assert add(2, 3) == 5"),
        ("is_prime", "소수인지 판별하는 is_prime(n) 함수를 파이썬으로 작성해 줘.", "def is_prime(n):\n    if n < 2:\n        return False\n    i = 2\n    while i * i <= n:\n        if n % i == 0:\n            return False\n        i += 1\n    return True", "assert is_prime(7) and not is_prime(9) and not is_prime(1)"),
        ("fib", "n번째 피보나치 수를 돌려주는 fib(n)을 반복문으로 작성해 줘(fib(0)=0).", "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a", "assert fib(10) == 55"),
        ("reverse_words", "문장의 단어 순서를 뒤집는 reverse_words(s) 함수를 작성해 줘.", "def reverse_words(s):\n    return ' '.join(s.split()[::-1])", "assert reverse_words('a b c') == 'c b a'"),
        ("count_vowels", "영어 모음 개수를 세는 count_vowels(s)를 작성해 줘.", "def count_vowels(s):\n    return sum(c in 'aeiouAEIOU' for c in s)", "assert count_vowels('Hello World') == 3"),
        ("flatten", "중첩 리스트를 한 단계 펼치는 flatten(xs)를 작성해 줘.", "def flatten(xs):\n    return [y for x in xs for y in x]", "assert flatten([[1], [2, 3]]) == [1, 2, 3]"),
        ("dedupe", "순서를 지키며 중복을 없애는 dedupe(xs)를 작성해 줘.", "def dedupe(xs):\n    seen = set()\n    out = []\n    for x in xs:\n        if x not in seen:\n            seen.add(x)\n            out.append(x)\n    return out", "assert dedupe([3, 1, 3, 2, 1]) == [3, 1, 2]"),
        ("clamp", "값을 lo와 hi 사이로 자르는 clamp(x, lo, hi)를 작성해 줘.", "def clamp(x, lo, hi):\n    return max(lo, min(hi, x))", "assert clamp(5, 0, 3) == 3 and clamp(-1, 0, 3) == 0"),
        ("word_count", "단어별 개수를 dict로 돌려주는 word_count(s)를 작성해 줘.", "def word_count(s):\n    out = {}\n    for w in s.split():\n        out[w] = out.get(w, 0) + 1\n    return out", "assert word_count('a b a') == {'a': 2, 'b': 1}"),
        ("moving_avg", "길이 k 이동 평균 리스트를 돌려주는 moving_avg(xs, k)를 작성해 줘.", "def moving_avg(xs, k):\n    return [sum(xs[i:i + k]) / k for i in range(len(xs) - k + 1)]", "assert moving_avg([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]"),
        ("binary_search", "정렬된 리스트에서 값의 위치(없으면 -1)를 찾는 binary_search(xs, x)를 작성해 줘.", "def binary_search(xs, x):\n    lo, hi = 0, len(xs) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if xs[mid] == x:\n            return mid\n        if xs[mid] < x:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1", "assert binary_search([1, 3, 5, 7], 5) == 2 and binary_search([1, 3], 2) == -1"),
        ("gcd", "최대공약수 gcd(a, b)를 유클리드 방법으로 작성해 줘.", "def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a", "assert gcd(12, 18) == 6"),
    ]
    for i, (name, prompt, ref, test) in enumerate(tasks):
        out.append(case(f"code-write-{i:02d}", "code", "coding", "hard", "cloud_needed", prompt,
                        {"contains": [f"def {name}"], "regex": r"```(python|py)?\n"}, f"```python\n{ref}\n```",
                        f"코드 블록의 함수가 문법에 맞는지(QualityGate)와 시험 `{test}`(--run-code를 켰을 때만 따로 실행)",
                        context=None) | {"test": test, "function": name})
    fixes = [
        ("m.py", "def mean(xs):\n    return sum(xs) / len(xs) - 1", "mean", "assert mean([2, 4]) == 3"),
        ("n.py", "def last(xs):\n    return xs[len(xs)]", "last", "assert last([1, 2, 3]) == 3"),
        ("o.py", "def is_even(n):\n    return n % 2 == 1", "is_even", "assert is_even(4) and not is_even(3)"),
        ("p.py", "def area(r):\n    return 3.14159 * r * 2", "area", "assert abs(area(2) - 12.566) < 0.01"),
        ("q.py", "def total(prices):\n    s = 0\n    for p in prices:\n        s = p\n    return s", "total", "assert total([1, 2, 3]) == 6"),
        ("r.py", "def first_upper(s):\n    return s[0].lower() + s[1:]", "first_upper", "assert first_upper('abc') == 'Abc'"),
        ("s.py", "def safe_div(a, b):\n    return a / b", "safe_div", "assert safe_div(1, 0) is None and safe_div(4, 2) == 2"),
        ("t.py", "def count(xs, x):\n    return len([y for y in xs if y != x])", "count", "assert count([1, 2, 1], 1) == 2"),
        ("u.py", "def maximum(xs):\n    m = 0\n    for x in xs:\n        if x > m:\n            m = x\n    return m", "maximum", "assert maximum([-3, -1, -2]) == -1"),
        ("v.py", "def avg_len(words):\n    return sum(len(w) for w in words) // len(words)", "avg_len", "assert avg_len(['ab', 'abc']) == 2.5"),
        ("w.py", "def celsius(f):\n    return f - 32 * 5 / 9", "celsius", "assert abs(celsius(212) - 100) < 1e-9"),
        ("x.py", "def range_sum(a, b):\n    return sum(range(a, b))", "range_sum", "assert range_sum(1, 3) == 6"),
        ("y.py", "def unique_sorted(xs):\n    return sorted(xs)", "unique_sorted", "assert unique_sorted([3, 1, 3]) == [1, 3]"),
        ("z.py", "def percent(part, whole):\n    return part / whole * 10", "percent", "assert percent(1, 4) == 25"),
        ("aa.py", "def middle(xs):\n    return xs[len(xs) / 2]", "middle", "assert middle([1, 2, 3]) == 2"),
        ("ab.py", "def join_path(a, b):\n    return a + b", "join_path", "assert join_path('dir', 'f.txt') in ('dir/f.txt', 'dir\\\\f.txt')"),
        ("ac.py", "def words(s):\n    return s.split(',')", "words", "assert words('a b  c') == ['a', 'b', 'c']"),
        ("ad.py", "def square_all(xs):\n    for x in xs:\n        x = x * x\n    return xs", "square_all", "assert square_all([1, 2]) == [1, 4]"),
        ("ae.py", "def contains(s, sub):\n    return s.find(sub) > 0", "contains", "assert contains('abc', 'a') and not contains('abc', 'z')"),
        ("af.py", "def reverse(xs):\n    xs.reverse()", "reverse", "assert reverse([1, 2]) == [2, 1]"),
    ]
    for i, (path, src, name, test) in enumerate(fixes):
        out.append(case(f"code-fix-{i:02d}", "code", "coding", "hard", "cloud_needed",
                        f"이 함수의 버그를 고쳐 줘. 고친 함수 전체를 코드 블록 하나로 보여 줘. 시험: `{test}`",
                        {"contains": [f"def {name}"], "regex": r"```(python|py)?\n"}, "(고친 함수)",
                        "고친 함수가 문법에 맞는지(QualityGate)와 시험(--run-code를 켰을 때만)", context=code_ctx(path, src))
                   | {"test": test, "function": name})
    return out


def lab_ctx(name, text):
    return {"kind": "lab", "source": f"Lab 실험 기록 {name}", "text": text}


def lab():
    out = []
    runs = ("run,adc_bits,noise,accuracy,latency_ms\nrun1,4,0.01,0.861,12.9\nrun2,6,0.01,0.884,15.2\nrun3,8,0.01,0.902,18.7\n"
            "run4,6,0.05,0.842,15.1\nrun5,8,0.05,0.879,18.9")
    rows = [
        ("가장 정확도가 높은 run은?", {"contains": ["run3"]}, "run3 (0.902)", "easy", "local_ok", "extraction"),
        ("run2의 지연은?", {"contains": ["15.2"]}, "15.2 ms", "easy", "local_ok", "extraction"),
        ("noise 0.01인 세 run의 평균 정확도를 계산해 줘.", {"number": {"value": 0.8823, "tol": 0.001}}, "0.8823", "easy", "local_ok", "extraction"),
        ("열 이름과 각 열의 단위를 정리해 줘.", {"contains": ["latency_ms", "accuracy"]}, "run, adc_bits, noise, accuracy(비율), latency_ms(ms)", "easy", "local_ok", "extraction"),
        ("ADC 4비트에서 8비트로 바꾸면 정확도가 몇 %p 오르는지 계산해 줘(noise 0.01).", {"number": {"value": 4.1, "tol": 0.05}}, "4.1%p", "easy", "local_ok", "extraction"),
        ("noise가 0.01에서 0.05로 늘 때 6비트 정확도 변화는?", {"number": {"value": -0.042, "tol": 0.001}}, "-0.042", "easy", "local_ok", "extraction"),
        ("지연이 가장 긴 run은?", {"contains": ["run5"]}, "run5", "easy", "local_ok", "extraction"),
        ("이 결과로 ADC 비트와 정확도의 관계를 통계적으로 해석하고 유의성을 판단해 줘.", {"contains": ["0.902"]}, "...", "hard", "cloud_needed", "data_lab"),
        ("Noise에 가장 민감한 조건을 찾고 그 근거를 수치로 설명해 줘.", {"contains": ["0.05"]}, "...", "hard", "cloud_needed", "data_lab"),
        ("다음 실험에서 측정하면 좋을 조건을 제안하고 이유를 근거와 함께 설명해 줘.", {"any": ["noise", "비트", "bit"]}, "...", "hard", "cloud_needed", "data_lab"),
        ("run1과 run3의 차이를 조건과 결과로 나눠 설명해 줘.", {"contains": ["0.861", "0.902"]}, "...", "moderate", "local_ok", "data_lab"),
        ("정확도 대비 지연 효율(accuracy/latency)이 가장 좋은 run은?", {"contains": ["run1"]}, "run1", "moderate", "local_ok", "data_lab"),
    ]
    for i, (prompt, expect, ref, diff, route, task) in enumerate(rows):
        out.append(case(f"lab-a-{i:02d}", "lab", task, diff, route, prompt, expect, ref,
                        "기록에 있는 값·계산 값(허용 오차), 기록에 없는 수치는 '추정'이라고 밝혔는지(QualityGate)",
                        context=lab_ctx("AIMC ADC/DAC Sweep", runs), tolerance=(expect.get("number") or {}).get("tol")))
    train = ("epoch,loss,val_acc\n1,1.92,0.41\n2,1.31,0.58\n3,0.98,0.66\n4,0.81,0.71\n5,0.77,0.72\n6,0.79,0.71\n7,0.84,0.70")
    rows2 = [
        ("검증 정확도가 가장 높은 epoch은?", {"contains": ["5"]}, "5 (0.72)", "easy", "local_ok", "extraction"),
        ("마지막 epoch의 loss는?", {"contains": ["0.84"]}, "0.84", "easy", "local_ok", "extraction"),
        ("loss가 다시 오르기 시작한 epoch은?", {"contains": ["6"]}, "6", "easy", "local_ok", "extraction"),
        ("epoch 1과 5의 정확도 차이를 계산해 줘.", {"number": {"value": 0.31, "tol": 0.001}}, "0.31", "easy", "local_ok", "extraction"),
        ("과적합이 일어났는지 근거와 함께 판단하고, 조기 종료 기준을 통계적으로 정해 줘.", {"contains": ["5"]}, "...", "hard", "cloud_needed", "data_lab"),
        ("이 학습 곡선을 요약해 줘.", {"contains": ["0.72"]}, "...", "moderate", "local_ok", "summarization"),
        ("학습률 스케줄을 바꾸는 실험 계획을 세우고 결과 해석 기준을 제안해 줘.", {"any": ["학습률", "learning rate"]}, "...", "hard", "cloud_needed", "data_lab"),
        ("loss 열의 평균을 계산해 줘.", {"number": {"value": 1.0571, "tol": 0.001}}, "1.0571", "easy", "local_ok", "extraction"),
        ("이 데이터의 스키마(열·형식)를 설명해 줘.", {"contains": ["epoch", "loss", "val_acc"]}, "...", "easy", "local_ok", "extraction"),
        ("그래프로 그릴 축을 추천해 줘.", {"contains": ["epoch"]}, "x: epoch, y: loss/val_acc", "easy", "local_ok", "data_lab"),
        ("두 번째 실험(학습률 절반)이 val_acc 0.74를 냈다면 차이가 의미 있는지, 반복 실험 없이 결론 내려도 되는지 분석해 줘.", {"contains": ["0.74"]}, "...", "hard", "cloud_needed", "data_lab"),
    ]
    for i, (prompt, expect, ref, diff, route, task) in enumerate(rows2):
        out.append(case(f"lab-b-{i:02d}", "lab", task, diff, route, prompt, expect, ref,
                        "기록 값·계산 값(허용 오차)", context=lab_ctx("ResNet 학습", train), tolerance=(expect.get("number") or {}).get("tol")))
    meas = ("chip,vdd_V,power_mW,freq_MHz,temp_C\nA1,0.8,3.8,200,41\nA2,0.9,5.1,250,45\nA3,1.0,6.9,300,52\nB1,0.8,3.2,180,39\nB2,0.9,4.6,220,43")
    rows3 = [
        ("소비 전력이 가장 낮은 칩은?", {"contains": ["B1"]}, "B1", "easy", "local_ok", "extraction"),
        ("A3의 온도는?", {"contains": ["52"]}, "52도", "easy", "local_ok", "extraction"),
        ("A 계열의 평균 전력을 계산해 줘.", {"number": {"value": 5.2667, "tol": 0.01}}, "5.27 mW", "easy", "local_ok", "extraction"),
        ("전압이 0.8V에서 1.0V로 오를 때 A 계열 전력이 몇 배가 되는지 계산해 줘.", {"number": {"value": 1.8158, "tol": 0.01}}, "약 1.82배", "easy", "local_ok", "extraction"),
        ("주파수당 전력(mW/MHz)이 가장 좋은 칩은?", {"contains": ["B1"]}, "B1", "moderate", "local_ok", "data_lab"),
        ("열 단위를 확인하고 단위가 다른 값을 같은 값으로 비교하면 안 되는 경우를 설명해 줘.", {"contains": ["mW"]}, "...", "moderate", "local_ok", "data_lab"),
        ("전압·온도·전력의 관계를 물리적으로 해석하고 누설 전류 영향을 추정하는 실험을 설계해 줘.", {"any": ["누설", "leakage"]}, "...", "hard", "cloud_needed", "data_lab"),
        ("A와 B 계열 중 저전력 설계에 더 나은 쪽을 표본 수의 한계와 함께 판단해 줘.", {"contains": ["B"]}, "...", "hard", "cloud_needed", "data_lab"),
        ("측정 표를 마크다운 표로 바꿔 줘.", {"contains": ["|"]}, "|chip|...", "easy", "local_ok", "extraction"),
        ("온도가 45도를 넘는 칩을 모두 알려 줘.", {"contains": ["A3"]}, "A3", "easy", "local_ok", "extraction"),
        ("B2의 주파수와 전압을 알려 줘.", {"contains": ["220", "0.9"]}, "220 MHz, 0.9 V", "easy", "local_ok", "extraction"),
    ]
    for i, (prompt, expect, ref, diff, route, task) in enumerate(rows3):
        out.append(case(f"lab-c-{i:02d}", "lab", task, diff, route, prompt, expect, ref,
                        "기록 값·계산 값(허용 오차)·단위", context=lab_ctx("칩 전력 측정", meas), tolerance=(expect.get("number") or {}).get("tol")))
    return out


def agent():
    out = []
    tools = ("[단계 종류]\n" + "\n".join([
        '{"action": "list", "path": "."}  폴더 보기', '{"action": "read", "path": "파일"}  파일 읽기',
        '{"action": "search", "pattern": "글자"}  찾기', '{"action": "write", "path": "파일", "content": "내용"}  파일 쓰기(승인)',
        '{"action": "edit", "path": "파일", "old": "", "new": ""}  고치기(승인)', '{"action": "run", "command": "명령"}  명령 실행(승인)',
        '{"action": "done", "answer": "답"}  끝']))
    rows = [
        ("README.md를 읽어 줘.", "read", "README.md"), ("작업 폴더에 무엇이 있는지 보여 줘.", "list", None),
        ("코드에서 TODO를 찾아 줘.", "search", "TODO"), ("테스트를 돌려 줘(python -m pytest).", "run", "pytest"),
        ("notes.txt에 '회의 3시'라고 써 줘.", "write", "notes.txt"), ("config.json의 debug를 true로 바꿔 줘.", "edit", "config.json"),
        ("main.py 내용을 보여 줘.", "read", "main.py"), ("src 폴더를 보여 줘.", "list", "src"),
        ("'import numpy'가 들어간 파일을 찾아 줘.", "search", "numpy"), ("빌드해 줘(make).", "run", "make"),
        ("할 일이 없으면 끝내 줘. 이미 다 했어.", "done", None), ("data.csv를 열어 봐.", "read", "data.csv"),
        ("로그에서 ERROR를 찾아 줘.", "search", "ERROR"), ("requirements.txt를 읽어 줘.", "read", "requirements.txt"),
        ("tests 폴더를 보여 줘.", "list", "tests"), ("린트를 돌려 줘(ruff check .).", "run", "ruff"),
        ("hello.py에 print('hi')를 써 줘.", "write", "hello.py"), ("setup.cfg의 version을 1.2로 고쳐 줘.", "edit", "setup.cfg"),
        ("작업이 끝났으면 요약해서 마무리해 줘.", "done", None), ("docs 폴더 목록을 보여 줘.", "list", "docs"),
        ("CHANGELOG.md를 읽어 줘.", "read", "CHANGELOG.md"), ("함수 parse_args를 찾아 줘.", "search", "parse_args"),
    ]
    for i, (goal, action, arg) in enumerate(rows):
        expect = {"json_keys": ["action"], "contains": [f'"{action}"'] + ([arg] if arg else [])}
        side = action in ("write", "edit", "run")
        out.append(case(f"agent-{i:02d}", "agent", "agent_planning", "critical" if side else "moderate",
                        "cloud_needed", f"다음 단계 JSON 하나만 답하세요.\n{tools}\n[목표]\n{goal}", expect,
                        json.dumps({"action": action, **({"path": arg} if action in ("read", "write", "edit") or (action == "list" and arg) else {}),
                                    **({"pattern": arg} if action == "search" else {}), **({"command": arg} if action == "run" else {}),
                                    **({"answer": "끝"} if action == "done" else {})}, ensure_ascii=False),
                        "JSON 단계 형식과 고른 action·대상(포함 검사). 실제 실행은 하지 않는다"))
    return out


def build():
    cases = general() + browser() + paper() + code() + lab() + agent()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "id 중복"
    # 개발용(dev)·시험용(test) 나누기: 분야 안에서 번갈아. 라우터 규칙은 dev의 틀린 사례만 보고 고치고, 결과는 test로도 따로 보고한다.
    seen = {}
    for c in cases:
        n = seen.get(c["category"], 0)
        c["split"] = "dev" if n % 2 == 0 else "test"
        seen[c["category"]] = n + 1
    return {"name": "poschat-adaptive-v1", "version": 1,
            "description": "POSCHAT 1.17 Adaptive AI 벤치마크: 일반·브라우저·논문/연구·코드·Lab·에이전트 요청과 정답·검증 방법·라우팅 정답",
            "license": "AGPL-3.0-only (이 저장소의 일부, 예문은 직접 작성)", "cases": cases}


if __name__ == "__main__":
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = {}
    for c in data["cases"]:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    print(f"{OUT} — {len(data['cases'])}개 {counts}")
