# 네이트 뉴스 AI 블로그 자동 생성기

네이트 뉴스 경제 카테고리(`news.nate.com/section?mid=n0300`)에서 최신 뉴스를 수집해
AI로 재편집한 블로그 글 + 썸네일 이미지 + HTML을 자동으로 만들어주는 프로그램입니다.

## 폴더 / 파일 구성 (총 8개 파이썬 파일)

| 파일 | 역할 |
|---|---|
| `main.py` | 프로그램 실행 진입점 |
| `gui.py` | 설정창/로그창 UI (Tkinter) |
| `config_manager.py` | 설정 저장/불러오기, API 키 마스킹 |
| `news_scraper.py` | 네이트 뉴스 스크래핑, 조선/SBS 제외, 중복 방지 |
| `ai_writer.py` | AI로 새 기사 + 이미지 프롬프트 동시 생성 |
| `image_generator.py` | 이미지 프롬프트로 썸네일 생성 |
| `html_builder.py` | 뉴스 + 썸네일 → HTML 조합 |
| `scheduler.py` | 전체 파이프라인 실행 + 주기적 반복 실행 |

데이터는 실행 시 아래 폴더에 자동 저장됩니다.

```
data/scraped_news/     원본 스크랩 뉴스 (txt)
data/rewritten_news/   AI 재작성 뉴스 (txt)
data/image_prompts/    이미지 생성 프롬프트 (txt)
data/images/           생성된 썸네일 (png)
data/html_output/      최종 블로그 HTML
data/scraped_urls.json 중복 방지용 이미 처리한 기사 URL 목록
config.json            저장된 설정값 (API 키는 base64로 가볍게 인코딩되어 저장됨)
```

## 설치

```bash
pip install -r requirements.txt
python main.py
```

## 사용 방법

1. GUI 왼쪽 패널에서 뉴스 재작성용 AI API 키(기본값: Anthropic Claude API 형식)와
   이미지 생성용 AI API 키(기본값: OpenAI 이미지 API 형식)를 입력합니다.
2. 블로그 글 스타일(블로그/정보성/전문성), 썸네일 이미지 스타일(실사/차비/영화)을 선택합니다.
3. 기사 생성 주기를 시간(0~23시, 24시간제)과 분(10분 단위)으로 설정합니다.
4. **💾 설정 저장** 버튼을 눌러 저장합니다. 저장 후에는 입력창이 비워지고,
   "현재 저장된 키: ****1234" 형태로 뒤 4자리만 표시됩니다.
5. **▶ 실행 시작**을 누르면 즉시 1회 전체 파이프라인이 실행되고,
   이후 설정한 시간 간격마다 자동으로 반복 실행됩니다.
6. 오른쪽 로그창에서 진행 상황(스크랩 → AI 작성 → 이미지 생성 → HTML 생성)을 실시간으로 확인할 수 있습니다.
7. **■ 실행 중지**를 누르면 현재 사이클 완료 후 안전하게 중지됩니다.

## 꼭 확인해주세요

- **robots.txt / 이용약관**: `news.nate.com`은 자동 수집을 제한하는 robots.txt를 두고 있습니다.
  본 코드는 개인 학습/테스트 목적의 예시이며, 실제 사용 전 네이트의 이용약관을 확인하고
  과도한 트래픽을 유발하지 않도록 (딜레이 유지) 책임 있게 사용해주세요.
- **HTML 구조 변경 가능성**: `news_scraper.py`의 CSS 선택자는 일반적인 뉴스 목록/본문 구조를
  가정해 작성되었습니다. 만약 "후보 기사 0건"처럼 스크랩이 안 되면, 브라우저 개발자도구(F12)로
  실제 태그 구조를 확인 후 `fetch_article_list` / `fetch_article_detail` 함수의 선택자를 조정해주세요.
- **API 기본값**: 텍스트 생성은 Anthropic Messages API(`api.anthropic.com`), 이미지 생성은
  OpenAI 이미지 API(`api.openai.com`) 형식을 기본으로 구현했습니다. 다른 AI 서비스를 쓰신다면
  `ai_writer.py` / `image_generator.py`의 요청 URL과 payload 형식만 바꿔주면 됩니다.
- **저작권**: 원본 기사를 참고해 "새로운 표현"으로 재구성하도록 프롬프트를 설계했지만,
  최종 발행 전 표절/저작권 이슈가 없는지 직접 검토하시는 것을 권장합니다.
- **API 키 보안**: `config.json`에는 base64로 인코딩되어 저장되지만 이는 난독화 수준이며
  강력한 암호화가 아닙니다. 이 파일을 외부에 공유하거나 공개 저장소에 올리지 마세요.
- **비용 관리**: 사이클당 최대 기사 수(`max_articles_per_cycle`)와 API 호출 딜레이로
  토큰/요청 사용량을 조절할 수 있습니다.
