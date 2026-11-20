# -*- coding: utf-8 -*-
"""
brand_link_preview.py
---------------------
브랜드커넥트(naver.me) 링크의 상품 미리보기(이미지·제목)를 조회한다.
네이버 브랜드커넥트 페이지는 SPA라 Playwright로 렌더링 후 og:image / 상품 이미지를 추출한다.
"""

from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urlparse

import requests

_PREVIEW_CACHE: dict[str, dict] = {}
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_STORE_TITLE_RE = re.compile(r":\s*네이버\s*스마트스토어\s*$")


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url and not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def is_valid_product_preview(preview: dict) -> bool:
    """스토어 페이지(상품 아님) 미리보기인지 판별한다."""
    if not preview:
        return False
    image = (preview.get("image") or "").strip()
    title = (preview.get("title") or "").strip()
    if not image or "shop-phinf.pstatic.net" not in image:
        return False
    if not title or _STORE_TITLE_RE.search(title):
        return False
    return True


def _is_naver_brand_url(url: str) -> bool:
    host = urlparse(normalize_url(url)).netloc.lower()
    return host in {"naver.me", "brandconnect.naver.com"} or host.endswith(".naver.me")


def _meta_content(html: str, prop: str) -> str:
    m = re.search(rf'(?:property|name)="{re.escape(prop)}" content="([^"]+)"', html)
    return m.group(1).strip() if m else ""


def _read_og_from_page(page) -> dict:
    image = ""
    title = ""
    og_image = page.locator('meta[property="og:image"]')
    if og_image.count():
        image = (og_image.first.get_attribute("content") or "").strip()
    og_title = page.locator('meta[property="og:title"]')
    if og_title.count():
        title = (og_title.first.get_attribute("content") or "").strip()
    if not title:
        title = (page.title() or "").strip()
    if not image:
        image = _pick_product_image(page)
    preview = {"image": image, "title": title}
    return _enrich_preview(preview)


def _enrich_preview(preview: dict) -> dict:
    """og:title에서 상품명·스토어명을 분리한다. (예: '상품명 : 스토어명')"""
    title = (preview.get("title") or "").strip()
    if " : " in title:
        product, store = title.rsplit(" : ", 1)
        preview["product_title"] = product.strip()
        preview["store"] = store.strip()
    else:
        preview["product_title"] = title
        preview["store"] = ""
    return preview


def _pick_product_image(page) -> str:
    """shop-phinf 상품 이미지 중 가장 적합한 후보를 고른다."""
    imgs = page.eval_on_selector_all(
        "img",
        """els => els.map(e => ({
            src: e.currentSrc || e.src || '',
            alt: (e.alt || '').trim(),
            w: e.naturalWidth || e.width || 0,
            h: e.naturalHeight || e.height || 0
        }))""",
    )

    candidates = []
    for img in imgs:
        src = (img.get("src") or "").strip()
        if not src or "shop-phinf.pstatic.net" not in src:
            continue
        if "favicon" in src or "brandconnect.pstatic.net" in src:
            continue

        w = int(img.get("w") or 0)
        h = int(img.get("h") or 0)
        if w < 120 or h < 120:
            continue

        alt = img.get("alt") or ""
        if _STORE_TITLE_RE.search(alt) or alt.endswith("스마트스토어"):
            continue

        score = w * h
        if alt:
            score += 50000
        candidates.append((score, src, alt))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _wait_for_product_preview(page, log: Callable = print, max_wait_ms: int = 15000) -> dict:
    """SPA 렌더링이 끝날 때까지 기다리며 유효한 상품 미리보기를 찾는다."""
    elapsed = 0
    step = 1000
    best: dict = {}

    while elapsed <= max_wait_ms:
        preview = _read_og_from_page(page)
        if is_valid_product_preview(preview):
            return preview
        if preview.get("image") or preview.get("title"):
            best = preview
        page.wait_for_timeout(step)
        elapsed += step

    if is_valid_product_preview(best):
        return best

    log(f"[브랜드커넥트] 상품 미리보기 대기 시간 초과 — title={best.get('title', '')[:40]}")
    return best


def _fetch_with_playwright(url: str, log: Callable = print, browser=None) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("[브랜드커넥트] Playwright 미설치 — 링크 미리보기 이미지를 가져오지 못했습니다.")
        return {}

    normalized = normalize_url(url)
    own_browser = browser is None

    try:
        if own_browser:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
        else:
            pw = None

        context = browser.new_context(
            locale="ko-KR",
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(25000)
        page.goto(normalized, wait_until="commit", timeout=25000)
        preview = _wait_for_product_preview(page, log=log)
        context.close()

        if own_browser:
            browser.close()
            if pw:
                pw.stop()
    except Exception as e:
        log(f"[브랜드커넥트] 미리보기 조회 실패 ({normalized}): {e}")
        return {}

    if not is_valid_product_preview(preview):
        if preview.get("image") or preview.get("title"):
            log(f"[브랜드커넥트] 유효하지 않은 미리보기 — title={preview.get('title', '')[:50]}")
        return {}
    return _enrich_preview(preview)


def fetch_link_preview(url: str, log: Callable = print, use_cache: bool = True, browser=None) -> dict:
    """
    링크 1개의 미리보기 정보를 반환한다.
    반환: {"image": "...", "title": "..."}  (없으면 {})
    """
    normalized = normalize_url(url)
    if not normalized:
        return {}

    if use_cache and normalized in _PREVIEW_CACHE:
        cached = dict(_PREVIEW_CACHE[normalized])
        if is_valid_product_preview(cached):
            return _enrich_preview(cached)
        del _PREVIEW_CACHE[normalized]

    preview = {}
    if _is_naver_brand_url(normalized):
        preview = _fetch_with_playwright(normalized, log=log, browser=browser)
    else:
        try:
            resp = requests.get(normalized, headers={"User-Agent": _USER_AGENT}, timeout=12, allow_redirects=True)
            image = _meta_content(resp.text, "og:image")
            title = _meta_content(resp.text, "og:title")
            if image or title:
                preview = {"image": image, "title": title}
        except Exception as e:
            log(f"[브랜드커넥트] 미리보기 조회 Failed ({normalized}): {e}")

    if is_valid_product_preview(preview) and use_cache:
        _PREVIEW_CACHE[normalized] = _enrich_preview(dict(preview))
    return _enrich_preview(preview) if is_valid_product_preview(preview) else {}


def fetch_previews_for_links(links: list, log: Callable = print) -> dict[str, dict]:
    """여러 링크의 미리보기를 {url: {image, title}} 형태로 반환한다."""
    previews: dict[str, dict] = {}
    normalized_links = [normalize_url(link) for link in links if normalize_url(link)]
    if not normalized_links:
        return previews

    naver_links = [u for u in normalized_links if _is_naver_brand_url(u)]
    other_links = [u for u in normalized_links if u not in naver_links]

    for url in other_links:
        preview = fetch_link_preview(url, log=log)
        if preview:
            previews[url] = preview

    if not naver_links:
        return previews

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        for url in naver_links:
            preview = fetch_link_preview(url, log=log)
            if preview:
                previews[url] = preview
        return previews

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for url in naver_links:
                preview = fetch_link_preview(url, log=log, use_cache=True, browser=browser)
                if preview:
                    previews[url] = preview
            browser.close()
    except Exception as e:
        log(f"[브랜드커넥트] Playwright 일괄 조회 실패: {e}")
        for url in naver_links:
            preview = fetch_link_preview(url, log=log, use_cache=False)
            if preview:
                previews[url] = preview

    return previews
