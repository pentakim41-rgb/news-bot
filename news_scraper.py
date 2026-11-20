# -*- coding: utf-8 -*-
"""
news_scraper.py
-----------------
네이트 뉴스 경제 카테고리(https://news.nate.com/section?mid=n0300)에서
최신 뉴스 목록을 가져와, '조선방송(TV조선)'/'SBS' 관련 기사는 제외하고,
이미 스크랩한 기사는 중복 저장하지 않는다.

!! 주의 !!
- 네이트 뉴스는 robots.txt로 자동 수집을 제한하고 있습니다.
  본 스크립트는 개인용 학습/테스트 목적의 예시 코드이며,
  실제 운영 시에는 반드시 네이트의 이용약관/robots.txt 정책을 확인하고,
  과도한 요청(초당 다중 요청 등)을 피해야 합니다.
- 사이트 HTML 구조는 예고 없이 바뀔 수 있습니다. 목록/본문 파싱이
  안 될 경우, 브라우저 개발자도구(F12)로 실제 태그 구조를 확인해
  아래 SELECTOR 관련 부분을 수정해주세요.
"""

import os
import re
import json
import time
import hashlib
import requests
import sys
from bs4 import BeautifulSoup

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 카테고리별 목록 페이지 URL
# 주의: '스포츠'는 news.nate.com이 아닌 별도 도메인(sports.news.nate.com)이라
# 페이지 구조가 달라 실제 크롤링 시 선택자 조정이 필요할 수 있습니다.
NATE_CATEGORY_URLS = {
    "경제": "https://news.nate.com/section?mid=n0300",
    "사회": "https://news.nate.com/section?mid=n0400",
    "스포츠": "https://sports.news.nate.com/",
    "연예": "https://news.nate.com/ent/section?mid=e01",
}
DEFAULT_CATEGORY = "경제"
SCRAPED_NEWS_DIR = os.path.join(BASE_DIR, "data", "scraped_news")
SEEN_URLS_PATH = os.path.join(BASE_DIR, "data", "scraped_urls.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# 조선일보/TV조선 계열, SBS 계열 언론사 제외
# (언론사명에 아래 키워드가 포함되면 제외. 제목이 아닌 '언론사명'만 검사한다.)
EXCLUDE_PRESS_KEYWORDS = [
    # 조선 계열
    "조선일보", "TV조선", "조선비즈", "스포츠조선", "디지털조선일보",
    "주간조선", "월간조선", "조선에듀", "조선펍",
    # SBS 계열
    "SBS", "sbs",
]


def _load_seen_urls() -> set:
    if not os.path.exists(SEEN_URLS_PATH):
        return set()
    with open(SEEN_URLS_PATH, "r", encoding="utf-8") as f:
        try:
            return set(json.load(f))
        except Exception:
            return set()


def _save_seen_urls(url_set: set) -> None:
    os.makedirs(os.path.dirname(SEEN_URLS_PATH), exist_ok=True)
    with open(SEEN_URLS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(list(url_set)), f, ensure_ascii=False, indent=2)


def _safe_filename(title: str, url: str) -> str:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    clean_title = re.sub(r"[^0-9A-Za-z가-힣]+", "_", title).strip("_")[:40]
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{clean_title}_{h}.txt"


def _is_excluded_press(press_name: str, title: str) -> bool:
    # 언론사명만 검사 (제목에 '조선'/'SBS' 같은 단어가 들어가도 오탐되지 않도록)
    return any(kw in press_name for kw in EXCLUDE_PRESS_KEYWORDS)


def fetch_article_list(category: str = DEFAULT_CATEGORY, log=print) -> list:
    """
    선택한 카테고리의 목록 페이지에서 (제목, 링크, 언론사) 리스트를 추출한다.
    네이트 뉴스 목록 페이지 구조가 바뀌면 아래 파싱 로직을 조정해야 한다.
    """
    list_url = NATE_CATEGORY_URLS.get(category, NATE_CATEGORY_URLS[DEFAULT_CATEGORY])
    try:
        resp = requests.get(list_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        log(f"[스크래퍼] 목록 페이지 요청 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    # 네이트 뉴스는 기사 링크가 보통 /view/ 를 포함한다.
    # 언론사명은 각 li/div 안의 별도 span/img alt 등에 들어있는 경우가 많아
    # 우선 title/link만 안정적으로 뽑고, 언론사명은 상세 페이지에서 재확인한다.
    seen_in_page = set()
    for a_tag in soup.select("a[href*='/view/']"):
        href = a_tag.get("href", "").strip()
        if not href:
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://news.nate.com" + href

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 4:
            # 썸네일 이미지만 감싼 a태그 등 텍스트 없는 경우 스킵
            continue

        if href in seen_in_page:
            continue
        seen_in_page.add(href)

        articles.append({"title": title, "url": href})

    log(f"[스크래퍼] 목록에서 후보 기사 {len(articles)}건 발견")
    return articles


def fetch_article_detail(url: str, log=print) -> dict:
    """상세 페이지에서 본문, 언론사명, 발행시각을 추출한다."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        log(f"[스크래퍼] 상세 페이지 요청 실패({url}): {e}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")

    # 언론사명 추정: og:site_name, 혹은 언론사 로고 img의 alt 속성
    press_name = ""
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        press_name = og_site["content"].strip()

    if not press_name:
        press_img = soup.select_one("img[alt]")
        if press_img:
            press_name = press_img.get("alt", "").strip()

    # 본문 추정: article 태그 또는 흔히 쓰이는 기사 본문 div id/class
    body_candidates = [
        soup.select_one("#realArtcContents"),
        soup.select_one("#articleContents"),
        soup.select_one(".articleView"),
        soup.select_one("article"),
    ]
    body_text = ""
    for cand in body_candidates:
        if cand:
            body_text = cand.get_text("\n", strip=True)
            if len(body_text) > 50:
                break

    if not body_text:
        # 최후 수단: 전체 텍스트에서 가장 긴 <p> 모음 사용
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        body_text = "\n".join([p for p in paragraphs if len(p) > 20])

    title_tag = soup.find("meta", property="og:title")
    title = title_tag["content"].strip() if title_tag and title_tag.get("content") else ""

    return {"press": press_name, "body": body_text, "title": title}


def scrape_new_articles(category: str = DEFAULT_CATEGORY, max_articles: int = 3, log=print) -> list:
    """
    새로운(미스크랩) 기사만 골라서, 조선/SBS 관련은 제외하고,
    txt 파일로 저장한 뒤 결과 리스트를 반환한다.
    반환값: [{"title", "url", "press", "body", "filepath"}, ...]
    """
    os.makedirs(SCRAPED_NEWS_DIR, exist_ok=True)
    seen_urls = _load_seen_urls()

    candidates = fetch_article_list(category=category, log=log)
    results = []

    for item in candidates:
        if len(results) >= max_articles:
            break
        url = item["url"]
        if url in seen_urls:
            continue

        detail = fetch_article_detail(url, log=log)
        if not detail or not detail.get("body"):
            log(f"[스크래퍼] 본문 추출 실패, 건너뜀: {url}")
            continue

        press = detail.get("press", "")
        title = detail.get("title") or item["title"]

        if _is_excluded_press(press, title):
            log(f"[스크래퍼] 제외 대상(조선/SBS) 스킵: {title} ({press})")
            seen_urls.add(url)  # 다시 검사하지 않도록 스킵한 것도 seen 처리
            continue

        filepath = os.path.join(SCRAPED_NEWS_DIR, _safe_filename(title, url))
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"제목: {title}\n")
            f.write(f"언론사: {press}\n")
            f.write(f"원문URL: {url}\n")
            f.write("-" * 40 + "\n")
            f.write(detail["body"])

        seen_urls.add(url)
        results.append({
            "title": title,
            "url": url,
            "press": press,
            "body": detail["body"],
            "filepath": filepath,
        })
        log(f"[스크래퍼] 저장 완료: {title}")

    _save_seen_urls(seen_urls)
    log(f"[스크래퍼] 이번 사이클 신규 기사 {len(results)}건 처리")
    return results
