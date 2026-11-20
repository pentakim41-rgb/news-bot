# -*- coding: utf-8 -*-
"""
thumbnail_maker.py
-------------------
외부 이미지 생성 API(Pollinations / Gemini / Hugging Face)를 쓸 수 없을 때,
기사 제목을 큼직하게 얹은 썸네일 PNG를 로컬에서 직접 만들어 준다.

제목 해시로 색 테마(10종)와 레이아웃(15종)을 독립적으로 고른다.
같은 제목은 항상 같은 조합, 다른 제목은 최대 150가지 조합이 나올 수 있다.
"""

import hashlib
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1280, 720
MARGIN = 96

# 색상환을 골고루 벌린 10종 그라데이션 (진한색 -> 중간 -> 밝은색)
COLOR_THEMES = [
    ((14, 32, 78), (37, 99, 235), (56, 189, 248)),       # 0 네이비-블루
    ((49, 15, 62), (147, 51, 234), (236, 72, 153)),      # 1 보라-핑크
    ((66, 20, 12), (220, 38, 38), (251, 146, 60)),       # 2 빨강-주황
    ((8, 47, 47), (13, 148, 136), (52, 211, 153)),       # 3 틸-민트
    ((23, 23, 23), (71, 85, 105), (148, 163, 184)),      # 4 차콜-실버
    ((55, 30, 8), (180, 120, 20), (252, 211, 77)),       # 5 브라운-골드
    ((12, 55, 18), (22, 163, 74), (134, 239, 172)),      # 6 포레스트-라임
    ((80, 10, 40), (190, 24, 93), (251, 113, 133)),      # 7 와인-로즈
    ((15, 45, 80), (14, 116, 144), (103, 232, 249)),     # 8 딥시안-아쿠아
    ((40, 20, 60), (109, 40, 217), (167, 139, 250)),     # 9 인디고-라벤더
]

# 레이아웃 15종 — 알약·제목 정렬·장식 배치가 눈에 띄게 다르게 구성
LAYOUTS = [
    {  # 0: 좌정렬 + 우하 빗금 + 하단 띠 (기존)
        "align": "left", "badge": "top-left", "title_y": "center",
        "glow": ("tr", "bl"), "band": "bottom_up", "slashes": "br",
        "vbar": None, "frame": False, "underline": "left",
    },
    {  # 1: 우정렬 + 좌하 빗금
        "align": "right", "badge": "top-right", "title_y": "center",
        "glow": ("tl", "br"), "band": "bottom_down", "slashes": "bl",
        "vbar": None, "frame": False, "underline": "right",
    },
    {  # 2: 가운데 + 장식 최소
        "align": "center", "badge": "top-center", "title_y": "center",
        "glow": ("tr",), "band": None, "slashes": None,
        "vbar": None, "frame": False, "underline": "center",
    },
    {  # 3: 좌정렬 + 좌측 세로 바
        "align": "left", "badge": "top-left", "title_y": "center",
        "glow": ("br",), "band": None, "slashes": None,
        "vbar": "left", "frame": False, "underline": "left",
    },
    {  # 4: 우정렬 + 우측 세로 바
        "align": "right", "badge": "top-right", "title_y": "center",
        "glow": ("bl",), "band": None, "slashes": None,
        "vbar": "right", "frame": False, "underline": "right",
    },
    {  # 5: 좌정렬 + 상단 띠 + 우상 빗금
        "align": "left", "badge": "top-left", "title_y": "center",
        "glow": ("bl", "tr"), "band": "top_down", "slashes": "tr",
        "vbar": None, "frame": False, "underline": "left",
    },
    {  # 6: 좌정렬 + 제목 하단 배치
        "align": "left", "badge": "top-left", "title_y": "bottom",
        "glow": ("tr", "tl"), "band": None, "slashes": "br",
        "vbar": None, "frame": False, "underline": "wide",
    },
    {  # 7: 좌정렬 + 사각 프레임
        "align": "left", "badge": "top-left", "title_y": "center",
        "glow": ("tr", "bl"), "band": None, "slashes": None,
        "vbar": None, "frame": True, "underline": None,
    },
    {  # 8: 좌정렬 + 좌상 빗금 (원만 반대 코너)
        "align": "left", "badge": "top-right", "title_y": "center",
        "glow": ("tl", "br"), "band": None, "slashes": "tl",
        "vbar": None, "frame": False, "underline": "left",
    },
    {  # 9: 우정렬 + 대각 분할 띠
        "align": "right", "badge": "top-left", "title_y": "center",
        "glow": ("tr", "bl"), "band": "diagonal", "slashes": "br",
        "vbar": None, "frame": False, "underline": "right",
    },
    {  # 10: 가운데 + 상단 알약 + 하단 글로우
        "align": "center", "badge": "top-center", "title_y": "top",
        "glow": ("bl", "br"), "band": "bottom_up", "slashes": None,
        "vbar": None, "frame": False, "underline": "center",
    },
    {  # 11: 좌정렬 + 넓은 밑줄 바
        "align": "left", "badge": "bottom-left", "title_y": "center",
        "glow": ("tr",), "band": None, "slashes": "br",
        "vbar": None, "frame": False, "underline": "wide",
    },
    {  # 12: 가운데 + 상하 이중 띠
        "align": "center", "badge": "top-left", "title_y": "center",
        "glow": ("tr", "bl"), "band": "double", "slashes": None,
        "vbar": None, "frame": False, "underline": "center",
    },
    {  # 13: 좌정렬 + 좌측 대형 글로우 + 우하 빗금
        "align": "left", "badge": "top-right", "title_y": "center",
        "glow": ("bl",), "band": None, "slashes": "br",
        "vbar": None, "frame": False, "underline": "left",
    },
    {  # 14: 우정렬 + 알약 없음 + 좌하 빗금 + 프레임
        "align": "right", "badge": None, "title_y": "center",
        "glow": ("tr", "tl"), "band": "bottom_down", "slashes": "bl",
        "vbar": "right", "frame": True, "underline": "right",
    },
]

GLOW_ELLIPSES = {
    "tr": [880, -220, 1500, 400],
    "bl": [-260, 420, 360, 1040],
    "tl": [-260, -220, 360, 400],
    "br": [880, 420, 1500, 1040],
}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\NanumGothicBold.ttf",
    r"C:\Windows\Fonts\NanumGothic.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _pick_combo(seed_text: str):
    """제목 해시로 색 테마와 레이아웃을 독립적으로 선택한다."""
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    theme = COLOR_THEMES[int(digest[:8], 16) % len(COLOR_THEMES)]
    layout = LAYOUTS[int(digest[8:16], 16) % len(LAYOUTS)]
    return theme, layout


def _make_gradient(theme) -> Image.Image:
    """3색 세로 그라데이션 배경."""
    top, mid, bottom = theme
    base = Image.new("RGB", (1, HEIGHT))
    draw = ImageDraw.Draw(base)

    half = HEIGHT / 2
    for y in range(HEIGHT):
        if y < half:
            ratio = y / half
            start, end = top, mid
        else:
            ratio = (y - half) / half
            start, end = mid, bottom
        color = tuple(int(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
        draw.point((0, y), fill=color)

    return base.resize((WIDTH, HEIGHT), Image.BILINEAR)


def _draw_glow(img: Image.Image, theme, glow_keys) -> Image.Image:
    if not glow_keys:
        return img
    glow = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for key in glow_keys:
        box = GLOW_ELLIPSES.get(key)
        if box:
            color_idx = {"tr": 2, "bl": 1, "tl": 0, "br": 2}.get(key, 1)
            gdraw.ellipse(box, fill=theme[color_idx])
    glow = glow.filter(ImageFilter.GaussianBlur(130))
    return Image.blend(img, glow, 0.35)


def _draw_band(odraw: ImageDraw.ImageDraw, band: str | None) -> None:
    if band == "bottom_up":
        odraw.polygon([(0, HEIGHT), (WIDTH, HEIGHT), (WIDTH, HEIGHT - 210), (0, HEIGHT - 90)],
                      fill=(0, 0, 0, 90))
    elif band == "bottom_down":
        odraw.polygon([(0, HEIGHT), (WIDTH, HEIGHT), (WIDTH, HEIGHT - 90), (0, HEIGHT - 210)],
                      fill=(0, 0, 0, 90))
    elif band == "top_down":
        odraw.polygon([(0, 0), (WIDTH, 0), (WIDTH, 180), (0, 90)],
                      fill=(0, 0, 0, 70))
    elif band == "diagonal":
        odraw.polygon([(0, 0), (WIDTH, HEIGHT), (WIDTH, HEIGHT - 160), (0, HEIGHT - 320)],
                      fill=(0, 0, 0, 80))
    elif band == "double":
        odraw.polygon([(0, 0), (WIDTH, 0), (WIDTH, 120), (0, 60)], fill=(0, 0, 0, 60))
        odraw.polygon([(0, HEIGHT), (WIDTH, HEIGHT), (WIDTH, HEIGHT - 120), (0, HEIGHT - 60)],
                      fill=(0, 0, 0, 60))


def _draw_slashes(odraw: ImageDraw.ImageDraw, slashes: str | None) -> None:
    if not slashes:
        return
    configs = {
        "br": {"x_start": 1015, "y1": 640, "y2": 470, "dx": 105, "sign": 1},
        "bl": {"x_start": 65, "y1": 640, "y2": 470, "dx": -105, "sign": -1},
        "tr": {"x_start": 1015, "y1": 80, "y2": 250, "dx": 105, "sign": 1},
        "tl": {"x_start": 65, "y1": 80, "y2": 250, "dx": -105, "sign": -1},
    }
    cfg = configs.get(slashes)
    if not cfg:
        return
    for i in range(6):
        x = cfg["x_start"] + i * 42 * cfg["sign"]
        odraw.line([(x, cfg["y1"]), (x + cfg["dx"], cfg["y2"])],
                   fill=(255, 255, 255, 26), width=16)


def _draw_vbar(odraw: ImageDraw.ImageDraw, vbar: str | None) -> None:
    if vbar == "left":
        odraw.rectangle([MARGIN - 20, 80, MARGIN - 4, HEIGHT - 80], fill=(255, 255, 255, 40))
    elif vbar == "right":
        odraw.rectangle([WIDTH - MARGIN + 4, 80, WIDTH - MARGIN + 20, HEIGHT - 80],
                        fill=(255, 255, 255, 40))


def _draw_frame(odraw: ImageDraw.ImageDraw) -> None:
    odraw.rectangle([48, 48, WIDTH - 48, HEIGHT - 48], outline=(255, 255, 255, 50), width=4)
    odraw.rectangle([56, 56, WIDTH - 56, HEIGHT - 56], outline=(255, 255, 255, 25), width=2)


def _add_decorations(img: Image.Image, theme, layout: dict) -> Image.Image:
    img = _draw_glow(img, theme, layout.get("glow"))

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    _draw_band(odraw, layout.get("band"))
    _draw_slashes(odraw, layout.get("slashes"))
    _draw_vbar(odraw, layout.get("vbar"))
    if layout.get("frame"):
        _draw_frame(odraw)

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw):
    lines = []
    current = ""

    def width_of(s: str) -> int:
        return int(draw.textlength(s, font=font))

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if width_of(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if width_of(word) <= max_width:
            current = word
            continue
        chunk = ""
        for ch in word:
            if width_of(chunk + ch) <= max_width:
                chunk += ch
            else:
                lines.append(chunk)
                chunk = ch
        current = chunk

    if current:
        lines.append(current)
    return lines


def _text_x(align: str, line: str, font, draw: ImageDraw.ImageDraw) -> int:
    line_width = int(draw.textlength(line, font=font))
    if align == "right":
        return WIDTH - MARGIN - line_width
    if align == "center":
        return (WIDTH - line_width) // 2
    return MARGIN


def _badge_position(badge: str | None, label_width: int, title_block_top: int,
                    title_block_bottom: int) -> tuple[int, int] | None:
    if not badge:
        return None
    positions = {
        "top-left": (MARGIN, title_block_top - 104),
        "top-right": (WIDTH - MARGIN - label_width, title_block_top - 104),
        "top-center": ((WIDTH - label_width) // 2, 48),
        "bottom-left": (MARGIN, title_block_bottom + 24),
    }
    return positions.get(badge)


def _title_start_y(title_y: str, block_height: int) -> int:
    if title_y == "top":
        return 180
    if title_y == "bottom":
        return HEIGHT - block_height - 80
    return (HEIGHT - block_height) // 2 + 26


def _draw_underline(draw: ImageDraw.ImageDraw, underline: str | None,
                    align: str, title_bottom_y: int, title_left_x: int,
                    title_right_x: int) -> None:
    if not underline:
        return
    bar_h = 12
    if underline == "wide":
        draw.rounded_rectangle([MARGIN, title_bottom_y + 16, WIDTH - MARGIN, title_bottom_y + 28],
                               radius=6, fill=(255, 255, 255))
    elif underline == "center":
        cx = WIDTH // 2
        draw.rounded_rectangle([cx - 200, title_bottom_y + 16, cx + 200, title_bottom_y + 28],
                               radius=6, fill=(255, 255, 255))
    elif underline == "left":
        draw.rounded_rectangle([title_left_x, title_bottom_y + 16,
                                title_left_x + 150, title_bottom_y + 28],
                               radius=6, fill=(255, 255, 255))
    elif underline == "right":
        draw.rounded_rectangle([title_right_x - 150, title_bottom_y + 16,
                                title_right_x, title_bottom_y + 28],
                               radius=6, fill=(255, 255, 255))


def _draw_title(img: Image.Image, title: str, label: str, layout: dict) -> None:
    draw = ImageDraw.Draw(img)
    align = layout.get("align", "left")
    max_width = WIDTH - MARGIN * 2

    for size in (92, 84, 76, 68, 60, 54):
        font = _load_font(size)
        lines = _wrap_text(title, font, max_width, draw)
        if len(lines) <= 4:
            break
    lines = lines[:4]

    line_height = int(size * 1.28)
    block_height = line_height * len(lines)
    y = _title_start_y(layout.get("title_y", "center"), block_height)

    label_font = _load_font(34)
    badge = layout.get("badge")
    if label and badge:
        label_width = int(draw.textlength(label, font=label_font)) + 44
        pos = _badge_position(badge, label_width, y, y + block_height)
        if pos:
            bx, by = pos
            draw.rounded_rectangle([bx, by, bx + label_width, by + 60],
                                   radius=30, fill=(255, 255, 255))
            draw.text((bx + 22, by + 12), label, font=label_font, fill=(17, 24, 39))

    title_left_x = WIDTH
    title_right_x = 0
    for line in lines:
        x = _text_x(align, line, font, draw)
        title_left_x = min(title_left_x, x)
        title_right_x = max(title_right_x, x + int(draw.textlength(line, font=font)))
        draw.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_height

    _draw_underline(draw, layout.get("underline"), align, y, title_left_x, title_right_x)


def create_thumbnail(output_path: str, title: str, label: str = "") -> str:
    """제목 텍스트를 얹은 1280x720 썸네일 PNG를 만들고 경로를 반환한다."""
    title = (title or "오늘의 뉴스").strip()
    theme, layout = _pick_combo(title)

    img = _make_gradient(theme)
    img = _add_decorations(img, theme, layout)
    _draw_title(img, title, label, layout)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    return output_path


if __name__ == "__main__":
    sample = sys.argv[1] if len(sys.argv) > 1 else "국민연금 50조 매물 폭탄 공포에 떨던 개미들이 몰랐던 진짜 반전"
    print(create_thumbnail("sample_thumbnail.png", sample, "경제 뉴스"))
