# -*- coding: utf-8 -*-
"""
html_builder.py
-----------------
AI가 재편집한 뉴스(제목/본문/해시태그)와 생성된 썸네일 이미지를 조합해
SEO 메타태그가 포함된 블로그용 HTML 파일을 만든다.
"""

import os
import re
import sys
import time
import random
import html as html_lib
from urllib.parse import urlparse

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_OUTPUT_DIR = os.path.join(BASE_DIR, "data", "html_output")

DESIGN_STYLE_ALIASES = {
    "minimal": "미니멀 클린형",
    "magazine": "매거진/카드형",
    "dark": "다크모드 프리미엄형",
}

BODY_LINE_HEIGHT = 2.2  # 220% — 디자인 스타일 공통 본문 줄간격


def _body_line_height_override(body_class: str) -> str:
    """테마별 본문·문단·리스트 줄간격을 공통 값으로 고정한다."""
    return (
        f"\n  body.{body_class}, body.{body_class} p, body.{body_class} li,\n"
        f"  body.{body_class} .deck, body.{body_class} .lead,\n"
        f"  body.{body_class} .premium-open p "
        f"{{ line-height: {BODY_LINE_HEIGHT}; }}\n"
    )


def _normalize_design_style(design_style: str) -> str:
    style = (design_style or "").strip()
    return DESIGN_STYLE_ALIASES.get(style, style or "미니멀 클린형")


def _build_tags_html(hashtags: list, design_style: str) -> str:
    tags = [html_lib.escape(t) for t in hashtags]
    if not tags:
        return ""

    if design_style == "매거진/카드형":
        badge_colors = ["#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed"]
        parts = []
        for idx, tag in enumerate(tags):
            color = badge_colors[idx % len(badge_colors)]
            parts.append(
                f'<span class="tag" style="border:2px solid {color}; color:{color};">{tag}</span>'
            )
        return "\n".join(parts)

    if design_style == "다크모드 프리미엄형":
        return "\n".join(
            f'<span class="tag">{tag}</span>'
            for tag in tags
        )

    # 미니멀 클린형: 칩(pill) 없이 가운뎃점으로 구분한 담백한 텍스트 목록
    return '<span class="tag-list">' + "<span class=\"tag-sep\">·</span>".join(
        f'<span class="tag">{tag}</span>' for tag in tags
    ) + "</span>"


def _paragraph_open(design_style: str, is_first: bool) -> str:
    if not is_first:
        return "<p>"
    if design_style == "매거진/카드형":
        return '<p class="deck">'
    if design_style == "다크모드 프리미엄형":
        return '<blockquote class="premium-open"><p>'
    return '<p class="lead">'


def _paragraph_close(design_style: str, is_first: bool) -> str:
    if design_style == "다크모드 프리미엄형" and is_first:
        return "</p></blockquote>"
    return "</p>"


def _format_h2(text: str, design_style: str, section_idx: int) -> str:
    safe = html_lib.escape(text)
    if design_style == "매거진/카드형":
        prefix = f'<span class="section-num">{section_idx:02d}</span>'
        rule = '<hr class="section-rule">' if section_idx > 1 else ""
        return f'{rule}<h2>{prefix}<span class="section-txt">{safe}</span></h2>'
    if design_style == "다크모드 프리미엄형":
        rule = '<hr class="gold-rule">' if section_idx > 1 else ""
        return (
            f'{rule}<div class="section-head">'
            f'<span class="section-mark">❖</span>'
            f"<h2>{safe}</h2></div>"
        )
    rule = '<hr class="thin-rule">' if section_idx > 1 else ""
    prefix = f'<span class="h2-mark">{section_idx:02d}</span>'
    return f'{rule}<h2>{prefix}{safe}</h2>'


def _get_design_assets(design_style: str) -> dict:
    """디자인 스타일별 CSS와 글 앞 장식 HTML을 반환 (배경색 없음)."""
    if design_style == "매거진/카드형":
        return {
            "body_class": "theme-magazine",
            "css": """
  body.theme-magazine {
    font-family: 'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
    max-width: 860px; margin: 0 auto; padding: 20px 16px 36px;
    line-height: 1.5; color: #111; font-size: 17px;
  }
  body.theme-magazine .article-head {
    border-bottom: 6px solid #111; padding-bottom: 16px; margin-bottom: 26px;
  }
  body.theme-magazine .badge {
    display: inline-block; border: 2px solid #111; color: #111;
    font-size: 12px; font-weight: 800; letter-spacing: 0.12em;
    padding: 5px 12px; margin-bottom: 14px; transform: rotate(-2deg);
  }
  body.theme-magazine h1 {
    font-size: 36px; font-weight: 900; line-height: 1.22; margin: 0;
    word-break: keep-all; letter-spacing: -0.04em;
  }
  body.theme-magazine .section-rule {
    border: 0; border-top: 3px dashed #111; margin: 30px 0 18px;
  }
  body.theme-magazine h2 {
    display: flex; align-items: center; gap: 10px;
    font-size: 22px; font-weight: 800; margin: 0 0 1.5em;
    line-height: 1.5; word-break: keep-all;
  }
  body.theme-magazine .section-num {
    flex: none; display: inline-flex; align-items: center; justify-content: center;
    width: 34px; height: 34px; border-radius: 50%; border: 2px solid #2563eb;
    color: #2563eb; font-weight: 900; font-size: 14px; letter-spacing: -0.03em;
  }
  body.theme-magazine .deck {
    font-size: 19px; font-weight: 700; line-height: 1.5;
    margin: 20px 0 16px; padding: 14px 16px;
    border: 2px solid #111; border-left: 8px solid #2563eb; word-break: keep-all;
  }
  body.theme-magazine p { font-size: 17px; line-height: 1.5; margin: 12px 0; word-break: keep-all; }
  body.theme-magazine ul { margin: 10px 0 18px; padding-left: 4px; list-style: none; }
  body.theme-magazine li {
    font-size: 16px; margin: 9px 0; line-height: 1.5; word-break: keep-all;
    padding-left: 22px; position: relative;
  }
  body.theme-magazine li::before {
    content: "▪"; position: absolute; left: 0; color: #2563eb; font-size: 14px;
  }
  body.theme-magazine .figure-frame {
    margin: 22px 0 8px; padding: 0; border: 4px solid #111; position: relative;
  }
  body.theme-magazine .figure-caption {
    font-size: 12px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; margin: 8px 0 22px; color: #444; text-align: right;
  }
  body.theme-magazine .thumbnail { width: 100%; display: block; margin: 0; }
  body.theme-magazine .tags {
    margin-top: 34px; padding-top: 16px; border-top: 6px solid #111;
    display: flex; flex-wrap: wrap; gap: 8px;
  }
  body.theme-magazine .tag {
    display: inline-block; padding: 5px 14px; margin: 0;
    border-radius: 0; font-size: 13px; font-weight: 800;
  }
  body.theme-magazine a.source { color: #666; font-size: 12px; }
""" + _body_line_height_override("theme-magazine"),
            "head_open": '<div class="article-head">',
            "head_close": "</div>",
            "badge_html": '<span class="badge">FEATURE</span>',
            "thumbnail_wrapper_open": '<figure class="figure-frame">',
            "thumbnail_wrapper_close": '<figcaption class="figure-caption">Cover Image</figcaption></figure>',
        }

    if design_style == "다크모드 프리미엄형":
        return {
            "body_class": "theme-premium",
            "css": """
  body.theme-premium {
    font-family: Georgia, 'Times New Roman', 'Noto Serif KR', serif;
    max-width: 700px; margin: 0 auto; padding: 30px 16px 44px;
    line-height: 1.5; color: #2a2a2a; font-size: 17px; text-align: center;
  }
  body.theme-premium .premium-top {
    margin-bottom: 18px;
    letter-spacing: 0.5em; color: #b8860b; font-size: 13px;
  }
  body.theme-premium .premium-top::before,
  body.theme-premium .premium-top::after {
    content: "❖"; margin: 0 10px; font-size: 11px;
  }
  body.theme-premium h1 {
    font-size: 29px; font-weight: 700; line-height: 1.5; margin: 0 auto 18px;
    max-width: 560px; word-break: keep-all;
    padding: 18px 0; border-top: 3px double #b8860b; border-bottom: 3px double #b8860b;
  }
  body.theme-premium .gold-rule {
    border: 0; height: 1px; width: 140px; margin: 34px auto 18px;
    background: repeating-linear-gradient(90deg, #b8860b 0 6px, transparent 6px 12px);
  }
  body.theme-premium .section-head { margin: 0; }
  body.theme-premium .section-mark {
    display: block; color: #b8860b; font-size: 15px; margin-bottom: 8px;
  }
  body.theme-premium h2 {
    font-size: 22px; font-weight: 700; margin: 0 0 1.5em; font-style: italic;
    line-height: 1.5; word-break: keep-all;
  }
  body.theme-premium p, body.theme-premium ul { text-align: left; }
  body.theme-premium .premium-open {
    margin: 26px auto; padding: 6px 34px; max-width: 560px;
    font-style: italic; color: #4a4a4a; position: relative; text-align: center;
  }
  body.theme-premium .premium-open::before {
    content: "“"; position: absolute; left: 0; top: -14px;
    font-size: 46px; color: #b8860b; font-style: normal; font-family: Georgia, serif;
  }
  body.theme-premium .premium-open::after {
    content: "”"; position: absolute; right: 0; bottom: -34px;
    font-size: 46px; color: #b8860b; font-style: normal; font-family: Georgia, serif;
  }
  body.theme-premium .premium-open p { margin: 0; font-size: 18px; line-height: 1.5; }
  body.theme-premium p { font-size: 17px; line-height: 1.5; margin: 12px 0; word-break: keep-all; }
  body.theme-premium ul { margin: 10px 0 18px; padding-left: 4px; list-style: none; }
  body.theme-premium li {
    font-size: 16px; margin: 8px 0; line-height: 1.5; word-break: keep-all;
    padding-left: 20px; position: relative;
  }
  body.theme-premium li::before {
    content: "❦"; position: absolute; left: 0; color: #b8860b; font-size: 13px;
  }
  body.theme-premium .figure-frame {
    margin: 26px auto 10px; padding: 14px; max-width: 100%;
    border-top: 1px solid #b8860b; border-bottom: 1px solid #b8860b;
  }
  body.theme-premium .figure-frame::before {
    content: "❖"; display: block; text-align: center; color: #b8860b;
    font-size: 13px; margin-bottom: 12px;
  }
  body.theme-premium .thumbnail { width: 100%; display: block; margin: 0; }
  body.theme-premium .tags {
    margin-top: 38px; padding-top: 20px; border-top: 1px double #b8860b;
  }
  body.theme-premium .tag {
    display: inline-block; padding: 4px 16px; margin: 4px 4px 0 4px;
    border-left: 1px solid #b8860b; border-right: 1px solid #b8860b;
    font-size: 13px; letter-spacing: 0.05em; font-style: italic; color: #8a6d1f;
  }
  body.theme-premium a.source { color: #999; font-size: 12px; letter-spacing: 0.1em; }
""" + _body_line_height_override("theme-premium"),
            "head_open": "",
            "head_close": "",
            "badge_html": '<div class="premium-top">PREMIUM EDITION</div>',
            "thumbnail_wrapper_open": '<figure class="figure-frame">',
            "thumbnail_wrapper_close": "</figure>",
        }

    return {
        "body_class": "theme-minimal",
        "css": """
  body.theme-minimal {
    font-family: 'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
    max-width: 640px; margin: 0 auto; padding: 40px 16px 48px;
    line-height: 1.5; color: #333; font-size: 16px; font-weight: 300;
    text-align: center;
  }
  body.theme-minimal .minimal-mark {
    font-family: Georgia, 'Times New Roman', serif; font-weight: 400;
    color: #aaa; letter-spacing: 0.5em; font-size: 11px; margin-bottom: 22px;
    text-transform: uppercase; text-align: left;
  }
  body.theme-minimal h1 {
    font-family: 'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
    font-size: 26px; font-weight: 300; line-height: 1.55; margin: 0 0 36px;
    word-break: keep-all; letter-spacing: -0.01em; color: #111; text-align: left;
  }
  body.theme-minimal .thin-rule {
    border: 0; border-top: 1px solid #e5e5e5; margin: 40px 0 0;
  }
  body.theme-minimal h2 {
    font-family: 'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
    font-size: 19px; font-weight: 600; margin: 28px 0 1.5em;
    line-height: 1.5; word-break: keep-all;
    display: flex; align-items: baseline; justify-content: center; gap: 10px;
  }
  body.theme-minimal .h2-mark {
    font-family: Georgia, 'Times New Roman', serif; font-weight: 400;
    font-size: 13px; color: #bbb; letter-spacing: 0.05em;
  }
  body.theme-minimal .lead {
    font-size: 17px; line-height: 1.5; margin: 0 0 8px; color: #555;
    word-break: keep-all;
  }
  body.theme-minimal .lead::first-letter {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 26px; font-weight: 400; color: #111;
  }
  body.theme-minimal p { font-size: 16px; line-height: 1.5; margin: 16px 0; word-break: keep-all; }
  body.theme-minimal ul { margin: 14px 0 22px; padding-left: 0; list-style: none; }
  body.theme-minimal li {
    font-size: 15px; margin: 10px 0; line-height: 1.5; word-break: keep-all;
    color: #444;
  }
  body.theme-minimal li::before {
    content: "– "; color: #aaa;
  }
  body.theme-minimal .thumbnail {
    width: 100%; margin: 32px 0 32px;
  }
  body.theme-minimal .tags {
    margin-top: 48px; padding-top: 0; border-top: none;
    text-align: center;
  }
  body.theme-minimal .tag-list { font-size: 12px; letter-spacing: 0.03em; }
  body.theme-minimal .tag { display: inline; color: #999; }
  body.theme-minimal .tag-sep { color: #ccc; margin: 0 10px; }
  body.theme-minimal a.source {
    display: block; margin-top: 20px; text-align: center;
    color: #bbb; font-size: 11px; letter-spacing: 0.1em;
  }
""" + _body_line_height_override("theme-minimal"),
        "head_open": "",
        "head_close": "",
        "badge_html": '<div class="minimal-mark">Editorial</div>',
        "thumbnail_wrapper_open": "",
        "thumbnail_wrapper_close": "",
    }


def _wrap_thumbnail(img_tag: str, assets: dict) -> str:
    if not img_tag:
        return ""
    if assets["thumbnail_wrapper_open"]:
        return f'{assets["thumbnail_wrapper_open"]}{img_tag}{assets["thumbnail_wrapper_close"]}'
    return img_tag


BRAND_DISCLAIMER_TEXT = "이 포스팅은 브랜드커넥트 활동으로 판매시 일정 수수료를 받습니다"

BRAND_LINK_CSS = """
  .brand-disclaimer,
  body.theme-magazine .brand-disclaimer,
  body.theme-premium .brand-disclaimer,
  body.theme-minimal .brand-disclaimer {
    font-size: 10pt; color: #888; margin: 0 0 18px;
    line-height: 1.5; text-align: center !important;
  }
  .brand-og-card {
    margin: 28px auto; max-width: 312px; width: 60%;
    border: 1px solid #e0e0e0; border-radius: 10px;
    overflow: hidden; background: #fff;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  .brand-og-card a {
    display: block; text-decoration: none; color: inherit;
  }
  .brand-og-image-wrap {
    width: 100%; background: #f7f7f7; line-height: 0;
  }
  .brand-og-image-wrap img {
    width: 100%; height: auto; display: block; border: 0;
  }
  .brand-og-body {
    padding: 14px 16px 12px; text-align: left;
  }
  .brand-og-title {
    font-size: 15px; font-weight: 600; color: #222;
    line-height: 1.45; margin: 0 0 6px;
    display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden;
    word-break: keep-all;
  }
  .brand-og-store {
    font-size: 13px; color: #888; margin: 0 0 10px;
  }
  .brand-og-domain {
    font-size: 12px; color: #03c75a; font-weight: 700;
  }
  .brand-link-url {
    margin: 28px 0; text-align: center; font-size: 14px;
    color: #1a73e8; word-break: break-all;
  }
"""


def _brand_disclaimer_html() -> str:
    text = html_lib.escape(BRAND_DISCLAIMER_TEXT)
    return (
        f'<p align="center" class="brand-disclaimer" '
        f'style="text-align:center;font-size:10pt;color:#888;'
        f'margin:0 0 18px;line-height:1.5;">{text}</p>'
    )


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url and not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def _brand_link_domain(url: str) -> str:
    host = urlparse(_normalize_url(url)).netloc.lower()
    if "naver.me" in host:
        return "naver.me"
    return host or "naver.me"


def _brand_link_html(url: str, preview: dict = None) -> str:
    """브랜드커넥트 링크 — 네이버 OGP 카드 형식(이미지+제목+스토어+도메인)으로 출력."""
    safe_url = html_lib.escape(_normalize_url(url))
    preview = preview or {}
    image = (preview.get("image") or "").strip()
    full_title = (preview.get("title") or "").strip()
    product_title = (preview.get("product_title") or "").strip()
    store = (preview.get("store") or "").strip()
    if not product_title and " : " in full_title:
        product_title, store = full_title.rsplit(" : ", 1)
        product_title, store = product_title.strip(), store.strip()
    if not product_title:
        product_title = full_title or "브랜드커넥트 상품"
    domain = html_lib.escape(_brand_link_domain(url))

    if image:
        safe_image = html_lib.escape(image)
        safe_product = html_lib.escape(product_title)
        store_html = (
            f'<div class="brand-og-store">{html_lib.escape(store)}</div>'
            if store else ""
        )
        return (
            f'<div class="brand-og-card" '
            f'style="max-width:312px;width:60%;margin:28px auto;">'
            f'<a href="{safe_url}" target="_blank" rel="nofollow sponsored noopener">'
            f'<div class="brand-og-image-wrap">'
            f'<img src="{safe_image}" alt="{safe_product}">'
            f"</div>"
            f'<div class="brand-og-body">'
            f'<div class="brand-og-title">{safe_product}</div>'
            f"{store_html}"
            f'<div class="brand-og-domain">{domain}</div>'
            f"</div></a></div>"
        )

    return f'<p class="brand-link-url">{safe_url}</p>'


MIN_LINES_BEFORE_FIRST_BRAND_LINK = 7
MIN_LINES_BETWEEN_BRAND_LINKS = 3


def _insertable_positions(html_lines: list) -> list:
    """리스트(<ul>) 내부나 소제목·이미지 바로 뒤를 피한 '문단 사이' 삽입 지점을 찾는다."""
    positions = []
    in_list = False
    for idx, line in enumerate(html_lines):
        if line == "<ul>":
            in_list = True
        if idx > 0 and not in_list:
            prev = html_lines[idx - 1]
            if not ("<h2" in prev or "<h1" in prev or "<img" in prev or "<figure" in prev):
                positions.append(idx)
        if line == "</ul>":
            in_list = False
    return positions


def _insert_brand_links(html_lines: list, brand_links: list, brand_previews: dict = None) -> list:
    """체크된 브랜드커넥트 링크를 글 중간중간에 고르게 흩어서 랜덤 삽입한다."""
    links = [link for link in (brand_links or []) if str(link).strip()]
    if not links:
        return html_lines

    previews = brand_previews or {}
    links = random.sample(links, len(links))
    positions = _insertable_positions(html_lines)
    if not positions:
        return html_lines + [
            _brand_link_html(link, previews.get(_normalize_url(link)))
            for link in links
        ]

    # 글이 짧아서 7줄 지점 자체가 없으면 기준을 낮춰서라도 본문 중간에 삽입한다.
    min_before_first = min(MIN_LINES_BEFORE_FIRST_BRAND_LINK, positions[-1])
    eligible = [pos for pos in positions if pos >= min_before_first]
    if not eligible:
        eligible = positions

    # 링크 수만큼 구간을 나눠 각 구간에서 하나씩 골라, 줄 간격을 두고 고르게 흩어 삽입한다.
    chosen = []
    used = set()
    chunk = len(eligible) / len(links)
    for i in range(len(links)):
        low = int(i * chunk)
        high = min(max(int((i + 1) * chunk) - 1, low), len(eligible) - 1)
        candidates = [eligible[j] for j in range(low, high + 1) if eligible[j] not in used]
        if not candidates:
            candidates = [pos for pos in eligible if pos not in used]
        if not candidates:
            break
        pick = random.choice(candidates)
        if chosen and (pick - chosen[-1]) < MIN_LINES_BETWEEN_BRAND_LINKS:
            farther = [
                pos for pos in eligible
                if pos not in used and (pos - chosen[-1]) >= MIN_LINES_BETWEEN_BRAND_LINKS
            ]
            if farther:
                pick = farther[0]
        chosen.append(pick)
        used.add(pick)

    result = list(html_lines)
    for link, position in sorted(zip(links[:len(chosen)], chosen), key=lambda pair: pair[1], reverse=True):
        result.insert(position, _brand_link_html(link, previews.get(_normalize_url(link))))
    return result


def _markdown_to_html(md_text: str, img_tag: str = "", design_style: str = "미니멀 클린형",
                      brand_links: list = None, brand_previews: dict = None) -> str:
    """아주 단순한 마크다운 -> HTML 변환 (## 소제목, - bullet, 빈 줄 기준 문단).

    img_tag가 있으면 첫 번째 ## 소제목(h2) 바로 아래에 삽입한다.
    """
    lines = md_text.split("\n")
    html_lines = []
    image_inserted = False
    in_list = False
    para_idx = 0
    section_idx = 0

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_list()
            continue
        if stripped.startswith("## "):
            close_list()
            section_idx += 1
            html_lines.append(_format_h2(stripped[3:], design_style, section_idx))
            if img_tag and not image_inserted:
                html_lines.append(img_tag)
                image_inserted = True
        elif stripped.startswith("# "):
            close_list()
            html_lines.append(f"<h1>{html_lib.escape(stripped[2:])}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{html_lib.escape(stripped[2:])}</li>")
        else:
            close_list()
            para_idx += 1
            is_first = para_idx == 1
            html_lines.append(
                f'{_paragraph_open(design_style, is_first)}{html_lib.escape(stripped)}'
                f'{_paragraph_close(design_style, is_first)}'
            )

    close_list()

    if img_tag and not image_inserted:
        html_lines.insert(0, img_tag)

    html_lines = _insert_brand_links(html_lines, brand_links, brand_previews)

    return "\n".join(html_lines)


def build_html(generated: dict, image_path: str,
               design_style: str = "미니멀 클린형", brand_links: list = None,
               brand_previews: dict = None, log=print) -> str:
    """
    generated: {"title","body_markdown","hashtags":[...]}
    image_path: 로컬 이미지 파일 경로 (없으면 이미지 없이 생성)
    design_style: HTML 레이아웃/테마 스타일
    brand_links: 본문 중간중간에 랜덤 삽입할 브랜드커넥트 링크 목록
    brand_previews: {url: {image, title}} 미리보기 캐시
    반환: 생성된 html 파일 경로
    """
    os.makedirs(HTML_OUTPUT_DIR, exist_ok=True)

    design_style = _normalize_design_style(design_style)
    assets = _get_design_assets(design_style)

    title = generated.get("title", "제목 없음")
    hashtags = generated.get("hashtags", [])
    hashtags_html = _build_tags_html(hashtags, design_style)
    keywords = ", ".join(t.lstrip("#") for t in hashtags)

    img_filename = os.path.basename(image_path) if image_path else ""
    img_rel_path = f"../images/{img_filename}" if img_filename else ""

    img_tag = ""
    if img_rel_path:
        img_tag = f'<img class="thumbnail" src="{img_rel_path}" alt="{html_lib.escape(title)}">'

    has_brand_links = bool(brand_links)
    brand_disclaimer_html = _brand_disclaimer_html() if has_brand_links else ""
    brand_css = BRAND_LINK_CSS if has_brand_links else ""

    body_html = _markdown_to_html(
        generated.get("body_markdown", ""),
        img_tag=_wrap_thumbnail(img_tag, assets),
        design_style=design_style,
        brand_links=brand_links,
        brand_previews=brand_previews,
    )
    # 요약문에는 삽입된 브랜드커넥트 링크·고지 문구가 섞이지 않도록 제외한다.
    desc_source = re.sub(
        r'<div class="brand-og-card">.*?</a>\s*</div>',
        " ",
        body_html,
        flags=re.DOTALL,
    )
    desc_source = re.sub(
        r'<p class="brand-(?:link-url|disclaimer)">.*?</p>',
        " ",
        desc_source,
        flags=re.DOTALL,
    )
    description = re.sub(r"<[^>]+>", "", desc_source)[:150].replace("\n", " ")

    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{html_lib.escape(title)}</title>
<meta name="description" content="{html_lib.escape(description)}">
<meta name="keywords" content="{html_lib.escape(keywords)}">
<meta property="og:title" content="{html_lib.escape(title)}">
<meta property="og:description" content="{html_lib.escape(description)}">
<meta property="og:image" content="{img_rel_path}">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
{assets["css"]}
{brand_css}
</style>
</head>
<body class="{assets["body_class"]}">
{brand_disclaimer_html}
{assets["badge_html"]}
{assets["head_open"]}
<h1>{html_lib.escape(title)}</h1>
{assets["head_close"]}

{body_html}
<div class="tags">
{hashtags_html}
</div>
</body>
</html>
"""

    log(f"[HTML생성] 디자인 스타일: {design_style}")

    safe_title = re.sub(r"[^0-9A-Za-z가-힣]+", "_", title).strip("_")[:40]
    ts = time.strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(HTML_OUTPUT_DIR, f"{ts}_{safe_title}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_doc)

    log(f"[HTML생성] 완료: {filepath}")
    time.sleep(10)
    return filepath
