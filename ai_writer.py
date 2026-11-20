# -*- coding: utf-8 -*-
"""
ai_writer.py
-------------
스크랩된 원본 뉴스 1건을 받아서, 선택된 AI 모델(Anthropic Claude 또는 Google Gemini)에게
"질문 한 번"으로 아래 내용을 모두 요청한다.
  1) 선택한 노출전략(SEO / 홈판 / GEO)에 최적화된 블로그 기사(제목/본문)
  2) 본문 내용에 맞는 해시태그 30개
  3) 홈판 클릭을 유도하는 썸네일 이미지 프롬프트(선택한 이미지 스타일 반영)

결과는 JSON으로 받아 파싱한 뒤, 뉴스는 rewritten_news 폴더에,
이미지 프롬프트는 image_prompts 폴더에 각각 저장한다.
"""

import os
import re
import json
import time
import requests
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REWRITTEN_DIR = os.path.join(BASE_DIR, "data", "rewritten_news")
IMAGE_PROMPT_DIR = os.path.join(BASE_DIR, "data", "image_prompts")

# API URLs
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# 모델명 매핑 (UI용 이름 -> 실제 API 모델 ID)
MODEL_MAPPING = {
    "Gemini 3 Flash preview": "gemini-3-flash-preview",
    "Gemini 2.5 Flash": "gemini-2.5-flash",
    "Gemini 2.5 Flash Lite": "gemini-2.5-flash-lite",
    "Gemini 3.1 Flash Lite": "gemini-3.1-flash-lite",
}

STYLE_GUIDE = {
    "블로그": (
        "친근한 1인칭 구어체, 짧은 문단(2~3문장), 독자와 대화하듯 공감·경험담을 섞은 블로그 말투. "
        "'솔직히', '직접 살펴보니', '이런 분들 많으시죠?' 같은 표현으로 홈판 체류를 유도"
    ),
    "정보성": (
        "객관적 사실 전달 중심, 항목별 정리, 초보자도 이해하기 쉬운 정보성 말투. "
        "첫 문단에서 핵심 결론·수치를 바로 제시하고, 단계별·FAQ형 소제목으로 스크롤 유도"
    ),
    "전문성": (
        "경제/산업 전문 기자 톤, 데이터·수치·배경 분석을 포함한 전문적이고 분석적인 말투. "
        "트렌드 분석형 홈판 콘텐츠처럼 '전문가가 본 진짜 이유', '대부분이 놓치는 포인트' 관점 제시"
    ),
}

# 네이버 홈판(홈피드) 노출 최적화 가이드 (2025~2026 AI 추천·D.I.A 품질 기준 반영)
HOMEPAN_EXPOSURE_GUIDE = """
[네이버 홈판 노출 핵심 원칙]
홈판은 검색이 아닌 AI 개인화 추천 피드입니다. 사용자가 스크롤만 해도 노출되며,
초기 1~3초 체류·클릭·완독률이 2차 확산을 결정합니다. 100% 모바일 가독성을 전제로 작성하세요.

[제목 공식 — 검색용 키워드 나열 금지, 홈판용 호기심 제목]
- ❌ "코스피 하락 원인 분석"  →  ✅ "코스피 6% 폭락, 개미들이 놓친 3가지 신호"
- ❌ "대출 규제 총량제 설명"  →  ✅ "대출에도 유통기한? 내 집 마련 실수요자만 울리는 이유"
- 아래 공식 중 1~2개를 자연스럽게 조합:
  · 숫자+베네핏: "30대가 꼭 알아야 할 ○○ 5가지"
  · 호기심 갭: "○○ 업계가 말 안 해주는 진짜 이유"
  · 대비·반전: "전문가는 A라지만, 실제 데이터는 B"
  · 시의성: "2026년 ○○, 지금부터 달라집니다"
- 25~40자 내외, 문장형 제목. 허위·과장·낚시는 금지, 사실 기반 유지.

[첫 문단 — 3초 안에 이탈 방지 (가장 중요)]
- 서론·인사·배경 설명 없이 바로 시작.
- ① 독자 고민/궁금증 한 줄 ② 핵심 결론·충격 포인트·구체 수치 ③ "이 글에서 ○○을 정리합니다" 예고.
- 예: "코스피가 하루 만에 6% 빠졌습니다. 겉으론 중동 리스크지만, 실제로는 ○○이 더 큰 변수였습니다."

[본문 구조 — 체류시간·완독률 최적화]
- 분량: 1000~1500자 (너무 짧으면 체류 부족, 너무 길면 이탈).
- 문단: 2~3문장씩 짧게. 한 문단 80자 이내 권장.
- 소제목(##): 4~6개. 3~4문단마다 배치해 스크롤 리듬 유지.
- 소제목도 호기심형으로: "## 왜 지금인가?", "## 대부분이 놓치는 ○○", "## 앞으로 어떻게 될까?"
- 콘텐츠 유형 (뉴스 주제에 맞게 1~2개 혼합):
  · 트렌드 분석형: 이슈에 대한 독자적 견해, 데이터·수치 인용
  · 실용 정보형: "지금 당장 확인할 것", "이렇게 대비하세요" actionable 조언
  · 경험·공감형: "많은 직장인·투자자가 느끼는" 공감 + 구체 시나리오
- 마지막 ## 소제목: "## 정리" 또는 "## 핵심만 요약" — 3~5줄 bullet로 핵심 정리 (AI 브리핑 인용 유리).
- FAQ 1~2개를 본문에 자연스럽게 포함 (예: "## ○○, 정말 ○○일까?" 형태).

[후킹 문구 — 클릭·스크롤 유도]
- 첫 문단·소제목·중간 전환에 아래 패턴을 자연스럽게 2~3회 사용:
  · "대부분이 모르는", "아직도 ○○만 보고 있다면", "진짜 변수는 따로 있다"
  · "숫자로 보면", "현장 반응은", "업계 내부에서는"
- 과장·낚시는 금지. 사실 기반 긴장감·호기심만 사용.

[피해야 할 것]
- 키워드만 나열한 딱딱한 SEO 제목·첫 문단
- "안녕하세요", "오늘은 ~에 대해 알아보겠습니다" 같은 늘어지는 서론
- AI 티 나는 반복 문장, 추상적 설명만 나열
- 원문 그대로 재구성한 듯한 표절 느낌
"""

SEO_EXPOSURE_GUIDE = """
[SEO 노출 핵심 원칙 — 네이버·구글 검색 상위 노출]
검색엔진은 '검색 의도 충족'과 '구조화된 정보'를 우선합니다.
제목·첫 문단·소제목·FAQ에 핵심 키워드를 자연스럽게 배치하고, 스니펫(검색 미리보기)에 잡히도록 작성하세요.

[키워드 전략]
- 핵심 키워드 1개(메인) + 연관 키워드 3~5개(서브)를 본문 전체에 분산.
- 메인 키워드: 제목 앞 15자 이내, 첫 문단 1~2회, H2 소제목 2회 이상.
- 롱테일 키워드: "○○ 방법", "○○ 원인", "○○ 영향", "○○ 대응" 형태를 FAQ·소제목에 활용.
- 키워드 나열·과밀 반복(스터핑) 금지. 문맥 속 자연스러운 문장으로만 사용.

[제목 공식 — 검색 클릭률(CTR) 최적화]
- 25~35자 권장. 메인 키워드를 앞쪽에 배치.
- 패턴 예시:
  · "○○ 뜻과 원인, ○○ 대응 방법 총정리"
  · "2026 ○○ 최신 동향 — ○○이 바뀌는 3가지"
  · "○○ vs ○○ 차이, ○○ 선택 기준"
- 숫자·연도·구체 명사를 포함해 검색 의도와 일치시키기.

[첫 문단 — Featured Snippet(직접 답변) 최적화]
- 첫 2~3문장 안에 검색 질문에 대한 '직접 답'을 제시 (정의·결론·핵심 수치).
- 형식: "○○(주제)은/는 ~이다. (핵심 사실 1~2문장). 이 글에서는 ○○의 원인·영향·대응을 정리합니다."
- 150자 내외로 요약 가능한 밀도 높은 서두 작성.

[본문 구조 — 검색 크롤러·사용자 모두 만족]
- 분량: 1200~1800자 (정보 깊이 + 키워드 커버리지).
- 소제목(##): 5~7개. 질문형·키워드형 혼합:
  · "## ○○이란? (정의와 배경)"
  · "## ○○의 원인과 배경"
  · "## ○○이 미치는 영향"
  · "## ○○ 대응·활용 방법"
  · "## 자주 묻는 질문(FAQ)"
  · "## 핵심 정리"
- 각 섹션 첫 문장에 해당 섹션 키워드를 포함.
- 번호 목록(1. 2. 3.)·불릿(-)을 적극 활용해 스캔 가능성 향상.
- FAQ 2~3개: "## ○○, ○○일까?" 형태로 검색어와 동일한 질문 문장 사용.

[신뢰·품질(E-E-A-T) 신호]
- 날짜·수치·기관명·인물명을 구체적으로 명시.
- "○○ 보도에 따르면", "2026년 ○월 기준" 등 출처·시점 표기.
- 추측과 사실을 구분해 서술.

[해시태그 — 검색 키워드 정렬]
- 30개 중 15개 이상을 실제 검색 가능한 키워드·연관어로 구성 (#뉴스, #이슈 같은 범용 태그만 쓰지 말 것).

[피해야 할 것]
- 홈판용 낚시·과장 제목 (검색 의도와 불일치 시 이탈·순위 하락)
- 키워드 없는 추상적 소제목 ("배경", "전망"만 단독 사용)
- 첫 문단에 결론 없이 배경 설명만 길게 나열
"""

GEO_EXPOSURE_GUIDE = """
[GEO 노출 핵심 원칙 — ChatGPT·Perplexity·Gemini·Copilot 등 AI 인용 최적화]
생성형 AI는 '인용하기 쉬운' 콘텐츠를 선호합니다.
한 문장=한 사실, 명확한 주어·수치·출처, 구조화된 요약이 AI 답변에 그대로 인용될 확률을 높입니다.

[AI 인용 친화 작성 원칙]
- 모호한 대명사(그, 이, 해당) 최소화. 매 문장에 주어·대상을 명시.
- "~것으로 보인다"보다 "~했다", "~이다" 등 사실 진술형 우선.
- 수치·날짜·기관명·인물명을 문장마다 구체적으로 포함.
- 한 문장에 하나의 인용 가능한 팩트만 담기 (AI가 잘라 인용하기 쉬움).

[제목 — AI가 주제를 정확히 파악하도록]
- 30~45자. "주제 + 핵심 사실/수치" 형식.
- 예: "2026년 코스피 6% 급락, 중동 리스크와 외국인 매도가 겹친 배경"
- 클릭 유도형 낚시보다 사실·주제 명확성 우선.

[첫 문단 — AI 요약 블록]
- "## 핵심 요약" 없이도 첫 3~4문장이 독립 요약으로 작동하게 작성.
- 또는 본문 최상단에 "## 핵심 요약" 섹션을 두고 3~5개 불릿으로 팩트 나열:
  · "○○은 2026년 ○월 ○일 ~했다."
  · "주요 원인은 A, B, C이다."
  · "○○ 기관/언론은 ~라고 보도했다."

[본문 구조 — 인용 밀도·구조화]
- 분량: 1000~1400자. 팩트 밀도 높게, 수식어·감탄 최소화.
- 소제목(##): 4~6개. 정의·원인·영향·전망·FAQ·요약 순서:
  · "## ○○이란?"
  · "## ○○의 핵심 사실"
  · "## ○○이/가 미치는 영향"
  · "## 전문가·언론은 어떻게 보나"
  · "## 자주 묻는 질문"
  · "## 한 줄 요약"
- FAQ 2~3개: 반드시 "Q. ... / A. ..." 형식으로 명시 (AI 추출 최적).
- 비교·인과 관계는 "~ 때문에 ~했다", "A는 B보다 ~하다"처럼 명확한 논리 연결.

[인용 유도 문장 패턴]
- "○○에 따르면, ~이다."
- "2026년 ○월 ○일 기준, ~이다."
- "핵심은 세 가지다. 첫째, ~. 둘째, ~. 셋째, ~."
- "한 줄로 정리하면, ~이다."

[해시태그 — 엔티티·주제 태그]
- 인물·기관·이슈·분야 키워드를 #태그로 30개 (AI 주제 분류에 도움).

[피해야 할 것]
- 감정 과장, "충격", "경악" 등 주관적 수식만 있는 문장
- 출처·시점 없는 단정 ("업계 전망은 ~") — 가능하면 "○○ 보도/발표 기준"
- 긴 수사적 문단 (AI가 핵심 팩트 추출 어려움)
"""

EXPOSURE_STRATEGY_GUIDE = {
    "SEO": SEO_EXPOSURE_GUIDE,
    "홈판": HOMEPAN_EXPOSURE_GUIDE,
    "GEO": GEO_EXPOSURE_GUIDE,
}

EXPOSURE_STRATEGY_ROLE = {
    "SEO": "20년차 SEO 콘텐츠 전략가이자 네이버·구글 검색 노출 전문 에디터",
    "홈판": "20년차 경제 전문 기자이자 네이버 홈판(홈피드) 노출 최적화 전문 에디터",
    "GEO": "생성형 AI(GEO) 인용 최적화 전문 에디터이자 팩트 기반 콘텐츠 아키텍트",
}

EXPOSURE_STRATEGY_GOAL = {
    "SEO": "네이버·구글 검색 결과 상위 노출과 스니펫(직접 답변) 획득에 최적화된",
    "홈판": "네이버 홈판(홈피드) AI 추천·체류·완독에 최적화된",
    "GEO": "ChatGPT·Perplexity·Gemini 등 AI 답변에 인용·참조되기 쉬운",
}

EXPOSURE_STRATEGY_TITLE_RULE = {
    "SEO": "위 [제목 공식]을 따른 검색 의도·키워드 최적화 제목 (메인 키워드 앞쪽 배치)",
    "홈판": "위 [제목 공식]을 따른 홈판용 호기심 제목 (검색 키워드 나열형 금지)",
    "GEO": "위 [제목 공식]을 따른 AI가 주제·사실을 정확히 파악할 수 있는 명확한 제목",
}

EXPOSURE_STRATEGY_BODY_RULE = {
    "SEO": "위 [첫 문단]·[본문 구조]·[FAQ] 가이드를 반드시 준수. 소제목(##) 5~7개 포함.",
    "홈판": "위 [첫 문단]·[본문 구조]·[후킹 문구] 가이드를 반드시 준수. 소제목(##) 4~6개 포함.",
    "GEO": "위 [첫 문단]·[본문 구조]·[FAQ Q/A 형식] 가이드를 반드시 준수. 소제목(##) 4~6개 포함.",
}

# 하위 호환
NAVER_HOMEPAN_GUIDE = HOMEPAN_EXPOSURE_GUIDE

IMAGE_STYLE_GUIDE = {
    "실사": (
        "photorealistic editorial photography, shot on full-frame DSLR, 35mm lens, "
        "natural soft daylight, shallow depth of field, realistic skin texture, "
        "clean modern Korean urban environment"
    ),
    "차비": (
        "stylized flat illustration, clean chabi-style vector art, bold simple shapes, "
        "limited color palette (3-4 colors max), smooth gradients, modern infographic feel, "
        "no photorealism"
    ),
    "영화": (
        "cinematic wide-angle movie still, dramatic rim lighting, deep shadows, "
        "anamorphic lens flare, film grain, moody color grading, epic composition"
    ),
    "스틱맨": (
        "minimalist stick figure illustration, simple black line art on plain white background, "
        "doodle/whiteboard sketch style, no shading, no color except one small accent color, "
        "exaggerated body language, clear symbolic props (chart, coin, house icon)"
    ),
    "동양로맨스 2D": (
        "2D Korean webtoon illustration, soft pastel colors, delicate clean line art, "
        "expressive character poses, warm emotional atmosphere, not photorealistic"
    ),
}

# 썸네일 이미지 프롬프트 작성 가이드 (영어 프롬pt, FLUX/SDXL 최적화)
IMAGE_PROMPT_GUIDE = """
[이미지 프롬프트 작성 규칙 — image_prompt 필드]
영어로 100~180단어, 아래 8요소를 반드시 모두 포함해 한 장면으로 구체적으로 묘사하세요.

1. 주제(Subject): 기사 핵심을 상징하는 단 하나의 명확한 피사체 (사람·사물·장면)
2. 행동(Action): 피사체가 무엇을 하고 있는지 (looking at, holding, pointing, walking toward...)
3. 배경(Setting): 구체적 장소 (Korean apartment living room, Seoul stock exchange hall, office desk...)
4. 구도(Composition): 16:9 wide thumbnail, single focal point, rule of thirds, generous negative space
5. 조명(Lighting): soft morning light / dramatic side light / warm golden hour 등
6. 분위기(Mood): tense, hopeful, shocking, calm, urgent 등 기사 톤과 일치
7. 색감(Color): dominant colors 2~3개 명시 (deep blue and gold, red accent on white...)
8. 스타일(Style): 사용자가 선택한 이미지 스타일 키워드를 그대로 반영

[절대 금지 — 최우선]
- 이미지 안에 어떤 텍스트도 넣지 마세요. NO TEXT AT ALL.
- 금지: letters, words, numbers, captions, titles, headlines, subtitles, labels, signs, banners,
  watermarks, logos, speech bubbles with writing, chart axis labels, UI text, Korean/English/Chinese characters
- 프롬프트에 "text saying", "with title", "headline", "sign that reads" 같은 표현 사용 금지
- 실존 유명인·정치인·연예인·브랜드 로고·상표 실물 묘사 금지

[사람이 나올 때]
- 반드시 Korean person/people, East Asian features
- 얼굴은 medium shot 이하, 표정과 몸짓으로 감정 전달 (텍스트 대신)

[좋은 예]
"A Korean man in his 30s sitting at a kitchen table, staring at a laptop screen showing only abstract green and red candlestick shapes without any labels, worried expression, hands clasped together. Minimalist stick figure style, black lines on white background, one red accent on the chart. Wide 16:9 composition, empty white space on left third. Absolutely no text, no letters, no numbers anywhere in the image."

[나쁜 예 — 금지]
"A thumbnail with the title 'Stock Market Crash' in bold Korean text" (텍스트 요청)
"A news banner showing headlines" (텍스트·배너)
"Infographic with labeled chart" (라벨·텍스트)
"""


def _build_prompt(article: dict, blog_style: str, image_style: str,
                  exposure_strategy: str = "홈판") -> str:
    strategy = exposure_strategy if exposure_strategy in EXPOSURE_STRATEGY_GUIDE else "홈판"
    strategy_guide = EXPOSURE_STRATEGY_GUIDE[strategy]
    role = EXPOSURE_STRATEGY_ROLE[strategy]
    goal = EXPOSURE_STRATEGY_GOAL[strategy]
    title_rule = EXPOSURE_STRATEGY_TITLE_RULE[strategy]
    body_rule = EXPOSURE_STRATEGY_BODY_RULE[strategy]
    style_desc = STYLE_GUIDE.get(blog_style, STYLE_GUIDE["정보성"])
    img_style_desc = IMAGE_STYLE_GUIDE.get(image_style, IMAGE_STYLE_GUIDE["실사"])

    prompt = f"""당신은 {role}입니다.
아래 원본 뉴스를 참고하여 표절이 아닌 새로운 관점과 표현으로 재구성한
{goal} 블로그용 기사를 작성해주세요.

{strategy_guide}

[원본 뉴스]
제목: {article.get('title','')}
언론사: {article.get('press','')}
본문:
{article.get('body','')[:8000]}

[작성 조건]
1. 문체: {style_desc}
2. 제목: {title_rule}
3. 본문: {body_rule}
4. 해시태그: 본문 주제 + 트렌드·관심사 키워드를 섞어 정확히 30개 (모두 # 으로 시작, 중복 없이)
5. 이미지 프롬프트(image_prompt):
{IMAGE_PROMPT_GUIDE}
   - 선택된 이미지 스타일: {img_style_desc}
   - image_prompt 마지막에 반드시 포함: "Absolutely no text, no letters, no numbers, no captions, no watermarks, no logos, no signs with writing anywhere in the image."

[출력 형식]
다른 설명 없이 아래 JSON 형식으로만 응답하세요.
{{
  "title": "새 제목",
  "body_markdown": "마크다운 형식의 본문",
  "hashtags": ["#태그1", "#태그2", "... 총 30개"],
  "image_prompt": "이미지 생성용 영어 프롬프트"
}}
"""
    return prompt


def _extract_json(text: str) -> dict:
    """모델이 코드블록(```json ... ```)으로 감싸서 응답해도 안전하게 JSON을 추출."""
    try:
        cleaned = text.strip()
        # 코드 블록 제거
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.MULTILINE).strip()
        cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
        
        # JSON 부분만 찾기 (가장 바깥쪽 { })
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
            
        return json.loads(cleaned)
    except Exception as e:
        # JSON 추출 실패 시 원본 응답 일부를 로그로 남겨 원인 파악에 활용
        print(f"[JSON 파싱 실패] {e} / 원본 응답 앞부분: {text[:500]}")
        return {}


def _call_anthropic(prompt: str, api_key: str, model: str, log=print) -> dict:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return _extract_json("\n".join(text_parts))


def _call_gemini(prompt: str, api_key: str, model_name: str, log=print) -> dict:
    # 모델명 변환
    real_model_id = MODEL_MAPPING.get(model_name, "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{real_model_id}:generateContent"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 16000,
            "responseMimeType": "application/json",  # JSON 응답 강제
        }
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        log(f"[AI작성] Gemini API 오류 ({resp.status_code}): {resp.text[:300]}")
    resp.raise_for_status()
    data = resp.json()
    
    try:
        text = data['candidates'][0]['content']['parts'][0]['text']
        return _extract_json(text)
    except (KeyError, IndexError):
        raise ValueError("Gemini API 응답 형식이 올바르지 않습니다.")


def generate_new_article(article: dict, api_key: str, model: str,
                          blog_style: str, image_style: str,
                          exposure_strategy: str = "홈판",
                          log=print, max_retries: int = 2) -> dict:
    """
    선택된 모델에 따라 적절한 API를 호출해 새 기사 + 이미지 프롬프트를 동시에 생성한다.
    반환: {"title","body_markdown","hashtags":[...30개],"image_prompt"}
    """
    if not api_key:
        log("[AI작성] 텍스트 AI API 키가 설정되어 있지 않습니다.")
        return {}

    prompt = _build_prompt(article, blog_style, image_style, exposure_strategy)
    
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            if "Gemini" in model:
                result = _call_gemini(prompt, api_key, model, log)
            else:
                # 기본값은 Anthropic (또는 모델명에 따라 분기 가능)
                result = _call_anthropic(prompt, api_key, model, log)

            if not result:
                raise ValueError("AI 응답에서 유효한 JSON을 추출하지 못했습니다.")

            # 해시태그 개수 보정
            tags = result.get("hashtags", [])
            if len(tags) > 30:
                result["hashtags"] = tags[:30]
            elif len(tags) < 1:
                result["hashtags"] = ["#뉴스", "#블로그"] # 기본 태그
                
            return result
        except Exception as e:
            last_err = e
            log(f"[AI작성] 시도 {attempt}/{max_retries} 실패: {e}")
            time.sleep(3)

    log(f"[AI작성] 최종 실패: {last_err}")
    return {}


def save_rewritten_news(article_source: dict, generated: dict, log=print) -> str:
    """재편집된 뉴스를 txt 파일로 저장하고 파일 경로를 반환."""
    os.makedirs(REWRITTEN_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r"[^0-9A-Za-z가-힣]+", "_", generated.get("title", "untitled")).strip("_")[:40]
    filepath = os.path.join(REWRITTEN_DIR, f"{ts}_{safe_title}.txt")

    hashtags_line = " ".join(generated.get("hashtags", []))

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"제목: {generated.get('title','')}\n")
        f.write(f"원문URL: {article_source.get('url','')}\n")
        f.write("-" * 40 + "\n")
        f.write(generated.get("body_markdown", ""))
        f.write("\n\n")
        f.write(hashtags_line)

    log(f"[AI작성] 재편집 뉴스 저장 완료: {filepath}")
    return filepath


def save_image_prompt(generated: dict, log=print) -> str:
    """이미지 프롬프트를 txt 파일로 저장하고 파일 경로를 반환."""
    os.makedirs(IMAGE_PROMPT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r"[^0-9A-Za-z가-힣]+", "_", generated.get("title", "untitled")).strip("_")[:40]
    filepath = os.path.join(IMAGE_PROMPT_DIR, f"{ts}_{safe_title}_prompt.txt")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(generated.get("image_prompt", ""))

    log(f"[AI작성] 이미지 프롬프트 저장 완료: {filepath}")
    return filepath
