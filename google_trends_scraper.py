# -*- coding: utf-8 -*-
"""
google_trends_scraper.py
-------------------------
구글 트렌드 '실시간 인기'(trends.google.com/trending) 화면에서
'지난 4시간' 기준 인기 검색어를 불러온 뒤, 목록 상위부터 한 줄씩 클릭해서
우측에 표시되는 뉴스 카드(제목/언론사/링크)를 수집한다.

동작 방식은 사람이 브라우저에서 하는 것과 동일하게 Playwright로 재현한다.
  1) https://trends.google.co.kr/trending?geo=KR&hl=ko&hours=4 접속
     (hours=4 가 화면의 '지난 4시간' 필터와 같다)
  2) 좌측 표의 트렌드를 상위부터 클릭
  3) 클릭할 때 우측에 나타나는 뉴스 링크를 수집
  4) 각 뉴스 링크에 접속해 본문 텍스트를 추출하고 txt로 저장

!! 주의 !!
- 구글 트렌드는 공개 API가 아니라 화면 구조(HTML)가 예고 없이 바뀔 수 있다.
  뉴스가 하나도 잡히지 않으면 아래 SELECTOR 목록을 실제 구조에 맞게 보강해야 한다.
- Playwright와 크로미움이 필요하다:
      pip install playwright
      playwright install chromium
"""

import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from news_scraper import (
    HEADERS,
    SCRAPED_NEWS_DIR,
    _is_excluded_press,
    _load_seen_urls,
    _safe_filename,
    _save_seen_urls,
)

TRENDS_URL = "https://trends.google.co.kr/trending?geo={geo}&hl=ko&hours={hours}"
RSS_URL = "https://trends.google.co.kr/trending/rss?geo={geo}"
GOOGLE_TREND_MENU ="구글 트랜드"
DEFAULT_HOURS = 4
DEFAULT_NEWS_PER_TREND = 3

PLAYWRIGHT_GUIDE = (
    "Playwright가 설치되지 않았습니다. 명령 프롬프트에서 아래 두 줄을 실행해주세요.\n"
    "    pip install playwright\n"
    "    playwright install chromium"
)

# 트렌드 표의 한 줄(row)을 찾기 위한 후보 선택자 (위에서부터 먼저 잡히는 것을 사용)
TREND_ROW_SELECTORS = [
    "tr.enOdEe-wZVHld-xMGwsb",
    "table tbody tr[jsaction]",
    "div[role='rowgroup'] div[role='row']",
]
# 한 줄 안에서 실제로 클릭할 부분 (체크박스를 누르지 않도록 검색어 칸을 클릭)
TREND_CLICK_SELECTORS = ["div.mZ3RIc", "td:nth-child(2)", "td:nth-child(1)"]
# 쿠키/약관 동의 팝업이 떴을 때 눌러줄 버튼 후보
CONSENT_SELECTORS = [
    "button:has-text('모두 수락')",
    "button:has-text('모두 동의')",
    "button:has-text('Accept all')",
    "button[aria-label='Accept all']",
]

# 뉴스 링크로 볼 수 없는 도메인 (구글 자체 링크, 소셜 공유 링크 등)
_NON_NEWS_HOST = re.compile(
    r"(google|gstatic|googleusercontent|youtube|blogger|facebook|twitter|x\.com|instagram)\.",
    re.IGNORECASE,
)
# '3시간 전', '어제' 같은 시각 표기 (언론사명과 구분하기 위해 걸러낸다)
_RELATIVE_TIME = re.compile(r"^((방금|초|분|시간|일|주|개월|년)|\d+\s*(초|분|시간|일|주|개월|년))\s*전$|^(어제|오늘|그저께)$")
# 언론사명에 더해 도메인으로도 제외 여부를 판단 (Chosunbiz 처럼 영문 표기가 오는 경우)
_EXCLUDE_HOST_KEYWORDS = ["chosun", "sbs.co.kr", "sbs.com"]
# 한국어 기사만 사용 (제목에 한글이 한 글자도 없으면 외국어 기사로 보고 건너뜀)
_HANGUL = re.compile(r"[가-힣]")


def _is_korean_title(title: str) -> bool:
    return bool(_HANGUL.search(title or ""))

_COLLECT_NEWS_JS = """
() => {
  const bad = /(google|gstatic|googleusercontent|youtube|blogger|facebook|twitter|x\\.com|instagram)\\./i;
  const seen = new Set();
  const out = [];
  document.querySelectorAll('a[href^="http"]').forEach((a) => {
    let host = '';
    try { host = new URL(a.href).hostname; } catch (e) { return; }
    if (!host || bad.test(host)) return;
    const text = (a.innerText || '').trim();
    if (text.length < 8) return;
    if (seen.has(a.href)) return;
    seen.add(a.href);
    const box = a.getBoundingClientRect();
    out.push({ url: a.href, text: text, top: box.top + window.scrollY, left: box.left });
  });
  return out;
}
"""


def _log_lines(log, message: str) -> None:
    for line in message.splitlines():
        log(line)


def _clean_text(raw: str) -> str:
    return re.sub(r"[ \t\u00a0\u200b]+", " ", raw or "").strip()


def _press_from_line(line: str) -> str:
    """'7시간 전 · 머니투데이' 처럼 시각과 언론사가 붙어 있는 줄에서 언론사만 뽑는다."""
    parts = [_clean_text(p) for p in re.split(r"[·|•‧]", line)]
    parts = [p for p in parts if p and not _RELATIVE_TIME.match(p) and len(p) <= 30]
    return parts[-1] if parts else ""


def _parse_news_card(card: dict) -> dict:
    """뉴스 카드의 텍스트 덩어리에서 제목과 언론사를 분리한다."""
    lines = [_clean_text(ln) for ln in card.get("text", "").splitlines()]
    lines = [ln for ln in lines if ln]
    title = lines[0] if lines else ""
    press = ""
    for line in reversed(lines[1:]):
        press = _press_from_line(line)
        if press:
            break
    return {"title": title, "press": press, "url": card.get("url", "")}


def _click_trend_row(row) -> bool:
    for selector in TREND_CLICK_SELECTORS:
        target = row.query_selector(selector)
        if target:
            try:
                target.click(timeout=5000)
                return True
            except Exception:
                continue
    try:
        row.click(timeout=5000)
        return True
    except Exception:
        return False


def _trend_name(row, index: int) -> str:
    title_el = row.query_selector("div.mZ3RIc")
    if title_el:
        name = _clean_text(title_el.inner_text())
        if name:
            return name
    for line in (row.inner_text() or "").splitlines():
        line = _clean_text(line)
        if line and not line.isdigit():
            return line
    return f"트렌드{index + 1}"


def _dismiss_consent(page, log=print) -> None:
    for selector in CONSENT_SELECTORS:
        try:
            button = page.query_selector(selector)
        except Exception:
            continue
        if button:
            try:
                button.click(timeout=3000)
                log("[구글트렌드] 동의 팝업을 닫았습니다.")
                page.wait_for_timeout(1000)
                return
            except Exception:
                pass


def _find_trend_rows(page, log=print) -> tuple:
    """트렌드 표에서 줄 목록과 사용된 선택자를 (rows, selector)로 반환."""
    for selector in TREND_ROW_SELECTORS:
        try:
            page.wait_for_selector(selector, timeout=8000)
        except Exception:
            continue
        rows = page.query_selector_all(selector)
        rows = [r for r in rows if (r.inner_text() or "").strip()]
        if rows:
            log(f"[구글트렌드] 트렌드 목록 {len(rows)}건 발견 (선택자: {selector})")
            return rows, selector
    return [], ""


def _collect_news_after_click(page, previous_urls: set, log=print) -> list:
    """트렌드를 클릭한 뒤 우측에 새로 나타난 뉴스 링크를 위에서부터 정렬해 반환."""
    cards = []
    for _ in range(12):
        page.wait_for_timeout(500)
        try:
            found = page.evaluate(_COLLECT_NEWS_JS)
        except Exception as e:
            log(f"[구글트렌드] 뉴스 영역 파싱 실패: {e}")
            return []
        fresh = [c for c in found if c["url"] not in previous_urls]
        if fresh:
            cards = fresh
            break
        cards = found
    cards.sort(key=lambda c: (c.get("top", 0), c.get("left", 0)))
    return [_parse_news_card(c) for c in cards]


def _fetch_trend_news_rss(
    geo: str, hours: int, max_trends: int, news_per_trend: int, log=print
) -> list:
    """
    구글 트렌드 RSS에서 트렌드별 뉴스(제목/언론사/원문 링크)를 가져온다.
    화면(HTML) 구조 변경과 무관하게 동작하는 1순위 방법.
    """
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    from datetime import datetime, timezone

    ns = {"ht": "https://trends.google.com/trending/rss"}
    try:
        resp = requests.get(RSS_URL.format(geo=geo), headers=HEADERS, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        log(f"[구글트렌드] RSS 요청 실패: {e}")
        return []

    now = datetime.now(timezone.utc)
    trends = []
    for item in root.iter("item"):
        name = _clean_text(item.findtext("title", ""))
        if not name:
            continue
        age_hours = None
        try:
            age_hours = (now - parsedate_to_datetime(item.findtext("pubDate", ""))).total_seconds() / 3600
        except Exception:
            pass
        news = []
        for n in item.findall("ht:news_item", ns):
            url = _clean_text(n.findtext("ht:news_item_url", "", ns))
            if not url:
                continue
            news.append({
                "trend": name,
                "title": _clean_text(n.findtext("ht:news_item_title", "", ns)),
                "press": _clean_text(n.findtext("ht:news_item_source", "", ns)),
                "url": url,
            })
        trends.append((name, age_hours, news))

    log(f"[구글트렌드] RSS 트렌드 {len(trends)}건 확인")
    recent = [t for t in trends if t[1] is None or t[1] <= hours]
    if not recent:
        recent = trends  # 시간 필터로 전부 걸러지면 전체 사용
    if max_trends > 0:
        recent = recent[:max_trends]

    collected, seen = [], set()
    for name, _, news in recent:
        picked = 0
        for n in news:
            if picked >= news_per_trend:
                break
            if n["url"] in seen:
                continue
            if not _is_korean_title(n["title"]):
                log(f"[구글트렌드] 외국어 기사 제외: {n['title'][:40]} ({n['press']})")
                continue
            seen.add(n["url"])
            collected.append(n)
            picked += 1
        log(f"[구글트렌드] '{name}' 관련 뉴스 {picked}건 확인")
    log(f"[구글트렌드] 후보 뉴스 총 {len(collected)}건 수집")
    return collected


def fetch_trend_news(
    geo: str = "KR",
    hours: int = DEFAULT_HOURS,
    max_trends: int = 5,
    news_per_trend: int = DEFAULT_NEWS_PER_TREND,
    show_browser: bool = False,
    log=print,
) -> list:
    """
    실시간 인기 검색어별 뉴스 목록을 [{"trend", "title", "press", "url"}, ...] 형태로 반환한다.
    1순위: 구글 트렌드 RSS / 예비: 화면을 열어 상위부터 클릭하며 수집(Playwright).
    """
    collected = _fetch_trend_news_rss(geo, hours, max_trends, news_per_trend, log=log)
    if collected:
        return collected
    log("[구글트렌드] RSS에서 뉴스를 얻지 못해 화면 수집 방식으로 시도합니다.")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log_lines(log, f"[구글트렌드] {PLAYWRIGHT_GUIDE}")
        return []

    url = TRENDS_URL.format(geo=geo, hours=hours)
    collected = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=not show_browser)
        except Exception as e:
            log(f"[구글트렌드] 크로미움 실행 실패: {e}")
            _log_lines(log, f"[구글트렌드] {PLAYWRIGHT_GUIDE}")
            return []

        context = browser.new_context(
            locale="ko-KR",
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1440, "height": 960},
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        try:
            log(f"[구글트렌드] 접속: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            _dismiss_consent(page, log=log)

            rows, row_selector = _find_trend_rows(page, log=log)
            if not rows:
                log("[구글트렌드] 트렌드 목록을 찾지 못했습니다. 화면 구조가 바뀐 것 같습니다.")
                return []

            seen_news_urls = set()
            total = len(rows) if max_trends <= 0 else min(len(rows), max_trends)

            for index in range(total):
                rows = page.query_selector_all(row_selector)
                rows = [r for r in rows if (r.inner_text() or "").strip()]
                if index >= len(rows):
                    break

                row = rows[index]
                name = _trend_name(row, index)
                if not _click_trend_row(row):
                    log(f"[구글트렌드] '{name}' 클릭 실패, 다음 트렌드로 넘어갑니다.")
                    continue

                news_items = _collect_news_after_click(page, seen_news_urls, log=log)
                picked = 0
                for item in news_items:
                    if picked >= news_per_trend:
                        break
                    if not item["url"] or item["url"] in seen_news_urls:
                        continue
                    seen_news_urls.add(item["url"])
                    item["trend"] = name
                    collected.append(item)
                    picked += 1

                log(f"[구글트렌드] '{name}' 관련 뉴스 {picked}건 확인")
        finally:
            context.close()
            browser.close()

    log(f"[구글트렌드] 후보 뉴스 총 {len(collected)}건 수집")
    return collected


def fetch_article_body(url: str, log=print) -> str:
    """뉴스 링크에 접속해 기사 본문 텍스트를 추출한다."""
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if text and len(text) > 200:
                return text.strip()
    except ImportError:
        pass
    except Exception as e:
        log(f"[구글트렌드] trafilatura 본문 추출 실패({url}): {e}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
    except Exception as e:
        log(f"[구글트렌드] 기사 요청 실패({url}): {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    candidates = [
        soup.select_one("#dic_area"),
        soup.select_one("#articleBodyContents"),
        soup.select_one("#article-view-content-div"),
        soup.select_one("#newsct_article"),
        soup.select_one(".article_body"),
        soup.select_one(".news_body"),
        soup.select_one("article"),
    ]
    for cand in candidates:
        if cand:
            text = cand.get_text("\n", strip=True)
            if len(text) > 200:
                return text

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    return "\n".join([p for p in paragraphs if len(p) > 20])


def _hostname(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _detect_press(url: str, fallback: str) -> str:
    return fallback or _hostname(url)


def _is_excluded(press: str, title: str, url: str) -> bool:
    """조선·SBS 계열은 언론사명 또는 기사 도메인으로 걸러낸다."""
    if _is_excluded_press(press, title):
        return True
    host = _hostname(url)
    return any(keyword in host for keyword in _EXCLUDE_HOST_KEYWORDS)


def scrape_new_articles(
    max_articles: int = DEFAULT_NEWS_PER_TREND,
    hours: int = DEFAULT_HOURS,
    geo: str = "KR",
    show_browser: bool = False,
    log=print,
) -> list:
    """
    구글 트렌드 뉴스 중 아직 스크랩하지 않은 기사만 골라 txt로 저장하고 결과를 반환한다.
    반환 형식은 news_scraper.scrape_new_articles와 동일하다.
    """
    os.makedirs(SCRAPED_NEWS_DIR, exist_ok=True)
    seen_urls = _load_seen_urls()

    candidates = fetch_trend_news(
        geo=geo,
        hours=hours,
        max_trends=5,
        news_per_trend=max(max_articles, DEFAULT_NEWS_PER_TREND),
        show_browser=show_browser,
        log=log,
    )

    results = []
    for item in candidates:
        if len(results) >= max_articles:
            break

        url = item["url"]
        if url in seen_urls:
            continue

        press = _detect_press(url, item.get("press", ""))
        title = item.get("title", "").strip()
        if not _is_korean_title(title):
            log(f"[구글트렌드] 외국어 기사 제외: {title[:40] or url}")
            seen_urls.add(url)
            continue
        if _is_excluded(press, title, url):
            log(f"[구글트렌드] 제외 대상(조선/SBS) 스킵: {title} ({press})")
            seen_urls.add(url)
            continue

        body = fetch_article_body(url, log=log)
        if len(body) < 200:
            log(f"[구글트렌드] 본문이 너무 짧아 건너뜀: {title or url}")
            continue

        filepath = os.path.join(SCRAPED_NEWS_DIR, _safe_filename(title or "google_trend", url))
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"제목: {title}\n")
            f.write(f"언론사: {press}\n")
            f.write(f"트렌드검색어: {item.get('trend', '')}\n")
            f.write(f"원문URL: {url}\n")
            f.write("-" * 40 + "\n")
            f.write(body)

        seen_urls.add(url)
        results.append({
            "title": title,
            "url": url,
            "press": press,
            "body": body,
            "filepath": filepath,
            "trend": item.get("trend", ""),
        })
        log(f"[구글트렌드] 저장 완료: {title}")

    _save_seen_urls(seen_urls)
    log(f"[구글트렌드] 이번 사이클 신규 기사 {len(results)}건 처리")
    return results


if __name__ == "__main__":
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="구글 트렌드 실시간 인기 뉴스 크롤러")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="4 / 24 / 48 / 168")
    parser.add_argument("--geo", default="KR")
    parser.add_argument("--max-articles", type=int, default=DEFAULT_NEWS_PER_TREND)
    parser.add_argument("--show-browser", action="store_true", help="브라우저 창을 띄워서 확인")
    parser.add_argument("--titles-only", action="store_true", help="본문 없이 제목/링크만 출력")
    args = parser.parse_args()

    if args.titles_only:
        items = fetch_trend_news(
            geo=args.geo, hours=args.hours, show_browser=args.show_browser
        )
        for i, it in enumerate(items, start=1):
            print(f"{i}. [{it['trend']}] {it['title']} / {it['press']}\n   {it['url']}")
        sys.exit(0)

    articles = scrape_new_articles(
        max_articles=args.max_articles,
        hours=args.hours,
        geo=args.geo,
        show_browser=args.show_browser,
    )
    for i, a in enumerate(articles, start=1):
        print(f"{i}. {a['title']} ({a['press']}) -> {a['filepath']}")
