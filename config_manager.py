# -*- coding: utf-8 -*-
"""
config_manager.py
------------------
설정값(config.json)을 저장/불러오는 모듈.
API 키는 base64로 가볍게 인코딩해서 저장하고(완전한 암호화는 아님),
화면에 보여줄 때는 뒤 4자리만 노출하고 나머지는 '*' 처리한다.
"""

import json
import os
import sys
import base64

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# 예전 버전에서 쓰던 이미지 모델명 -> 지금 드롭다운에 있는 값으로 자동 변환.
# "자동 (무료 우선)"은 다른 모델로 넘어가지 않도록 HF FLUX 단일 모델로 고정한다.
LEGACY_IMAGE_MODELS = {
    "자동 (무료 우선)": "Hugging Face (FLUX Schnell, 자동 제공자)",
    "Pollinations (무료, Flux)": "Hugging Face (FLUX Schnell, 자동 제공자)",
    "Pollinations (무료, Z-Image)": "Pollinations (크레딧, Z-Image)",
    "Pollinations (무료, Klein)": "Pollinations (크레딧, Klein)",
    "Hugging Face (무료, SDXL)": "Hugging Face (SDXL, 자동 제공자)",
    "Hugging Face (무료, FLUX Schnell)": "Hugging Face (FLUX Schnell, 자동 제공자)",
    "Imagen 4 Fast Generate": "Gemini 2.5 Flash Image",
    "Imagen 4 Generate": "Gemini 2.5 Flash Image",
    "Imagen 4 Ultra Generate": "Gemini 2.5 Flash Image",
}

LEGACY_TEXT_MODELS = {
    "Gemini 3 Flash": "Gemini 3 Flash preview",
    "Gemini 2.5 Flash Lite": "Gemini 3.1 Flash Lite",
}

DEFAULT_CONFIG = {
    "text_ai_api_key": "",
    "text_ai_model": "Gemini 3.1 Flash Lite",
    "image_ai_api_key": "",
    "image_ai_model": "Hugging Face (FLUX Schnell, 자동 제공자)",
    "blog_style": "정보성",
    "exposure_strategy": "홈판",
    "design_style": "미니멀 클린형",
    "image_style": "실사",
    # 크롤링 소스: "네이트온"(네이트 뉴스 카테고리) / "구글"(구글 트렌드 실시간 인기) /
    #             "직접입력"(크롤링 없이 manual_article_text를 원본 글로 사용)
    "news_source": "네이트온",
    "news_category": "경제",
    "google_trend_menu": "구글 트랜드",
    "google_trend_hours": 4,
    "google_trend_show_browser": False,
    "manual_article_text": "",
    # 브랜드커넥트 링크 (1줄 1개, 최대 50개) / 그중 글에 삽입할 체크된 링크 (최대 3개)
    "brand_connect_links": [],
    "brand_connect_checked": [],
    # { "https://naver.me/xxx": {"image": "...", "title": "..."} }
    "brand_connect_previews": {},
    "schedule_hour": 1,
    "schedule_minute": 0,
    "api_call_delay_sec": 8,
    "max_articles_per_cycle": 3,
    # 로그인 DB (관리자 GitHub — 배포 시 config에 고정)
    "github_login_owner": "",
    "github_login_repo": "",
    "github_login_token": "",
    # HTML·이미지 업로드 (각 사용자 본인 GitHub)
    "github_upload_owner": "",
    "github_upload_token": "",
    "github_upload_repo1": "",
    "github_upload_repo2": "",
    "github_upload_repo3": "",
    # 관리자 웹(127.0.0.1:5000) 로그인 — 비워 두면 관리자 웹 로그인이 거부됨
    "admin_web_user": "",
    "admin_web_pass": "",
}

_GITHUB_TOKEN_KEYS = ("github_login_token", "github_upload_token")


def _migrate_github_config(raw: dict, cfg: dict) -> None:
    """예전 github_owner/repo1/token 필드를 login/upload 설정으로 이전."""
    login_owner = raw.get("github_login_owner") or raw.get("github_owner", "")
    login_repo = raw.get("github_login_repo") or raw.get("github_repo1", "")
    login_token = _decode(raw.get("github_login_token", "")) or raw.get("github_login_token", "")
    if not login_token:
        login_token = raw.get("github_token", "")

    cfg["github_login_owner"] = login_owner
    cfg["github_login_repo"] = login_repo
    cfg["github_login_token"] = login_token

    upload_owner = raw.get("github_upload_owner", "")
    upload_token = _decode(raw.get("github_upload_token", "")) or raw.get("github_upload_token", "")
    upload_repo1 = raw.get("github_upload_repo1", "")
    upload_repo2 = raw.get("github_upload_repo2", "")
    upload_repo3 = raw.get("github_upload_repo3", "")

    # 예전 설정: repo1=로그인 DB, repo2/3=업로드였을 수 있음 → repo1은 업로드에 넣지 않음
    if not upload_owner and (raw.get("github_repo2") or raw.get("github_repo3")):
        upload_owner = raw.get("github_owner", "")
        upload_token = raw.get("github_token", "")
        upload_repo1 = raw.get("github_repo2", "")
        upload_repo2 = raw.get("github_repo3", "")
        upload_repo3 = ""

    cfg["github_upload_owner"] = upload_owner
    cfg["github_upload_token"] = upload_token
    cfg["github_upload_repo1"] = upload_repo1
    cfg["github_upload_repo2"] = upload_repo2
    cfg["github_upload_repo3"] = upload_repo3


def get_github_login_config() -> dict:
    """로그인 DB용 GitHub 설정 (관리자 저장소)."""
    cfg = load_config()
    return {
        "owner": cfg.get("github_login_owner", ""),
        "repo": cfg.get("github_login_repo", ""),
        "token": cfg.get("github_login_token", ""),
    }


def get_github_upload_config() -> dict:
    """HTML·이미지 업로드용 GitHub 설정 (사용자 본인 저장소)."""
    cfg = load_config()
    repos = [
        r for r in [
            cfg.get("github_upload_repo1", ""),
            cfg.get("github_upload_repo2", ""),
            cfg.get("github_upload_repo3", ""),
        ] if r
    ]
    return {
        "owner": cfg.get("github_upload_owner", ""),
        "token": cfg.get("github_upload_token", ""),
        "repos": repos,
    }


def _encode(raw: str) -> str:
    if not raw:
        return ""
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode(enc: str) -> str:
    if not enc:
        return ""
    try:
        return base64.b64decode(enc.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def load_config() -> dict:
    """config.json을 읽어서 dict로 반환. 없으면 기본값 생성."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cfg = dict(DEFAULT_CONFIG)
    cfg.update(raw)
    cfg["text_ai_api_key"] = _decode(raw.get("text_ai_api_key", ""))
    cfg["image_ai_api_key"] = _decode(raw.get("image_ai_api_key", ""))
    for key in _GITHUB_TOKEN_KEYS:
        decoded = _decode(raw.get(key, ""))
        cfg[key] = decoded if decoded else raw.get(key, "")
    _migrate_github_config(raw, cfg)
    cfg["text_ai_model"] = LEGACY_TEXT_MODELS.get(
        cfg.get("text_ai_model", ""),
        cfg.get("text_ai_model", DEFAULT_CONFIG["text_ai_model"]),
    )
    cfg["image_ai_model"] = LEGACY_IMAGE_MODELS.get(
        cfg.get("image_ai_model", ""),
        cfg.get("image_ai_model", DEFAULT_CONFIG["image_ai_model"]),
    )
    return cfg


def save_config(cfg: dict) -> None:
    """dict를 config.json에 저장. API 키는 base64로 인코딩해서 저장."""
    to_save = dict(cfg)
    to_save["text_ai_api_key"] = _encode(cfg.get("text_ai_api_key", ""))
    to_save["image_ai_api_key"] = _encode(cfg.get("image_ai_api_key", ""))
    for key in _GITHUB_TOKEN_KEYS:
        to_save[key] = _encode(cfg.get(key, ""))
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)


def mask_key(raw: str) -> str:
    """API 키를 마스킹 처리: 끝 4자리만 노출, 나머지는 * 처리."""
    if not raw:
        return "(설정되지 않음)"
    if len(raw) <= 4:
        return "*" * len(raw)
    return "*" * (len(raw) - 4) + raw[-4:]