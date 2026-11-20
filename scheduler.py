# -*- coding: utf-8 -*-
"""
scheduler.py
-------------
전체 파이프라인을 한 사이클 실행하고, 설정된 시간 간격(시/분)마다 반복 실행한다.
- 실행 버튼을 누르면 즉시 1회 실행 후, 지정된 간격마다 계속 실행된다.
- 분당 토큰(API 호출) 제한을 아끼기 위해, 각 API 호출 사이에 딜레이를 둔다.
- 별도 스레드에서 동작하며, threading.Event로 안전하게 중지할 수 있다.
"""

import time
import threading

import news_scraper
import google_trends_scraper
import ai_writer
import image_generator
import html_builder
import github_uploader
import config_manager
import brand_link_preview


def _build_manual_articles(config: dict, log=print) -> list:
    """'직접입력' 모드에서 사용자가 저장해둔 글을 기사 1건 형태로 변환한다."""
    manual_text = (config.get("manual_article_text", "") or "").strip()
    if not manual_text:
        log("[직접입력] 저장된 글이 없습니다. 설정 탭 ▸ '직접입력' 버튼에서 글을 먼저 저장하세요.")
        return []

    lines = [line.strip() for line in manual_text.splitlines() if line.strip()]
    title = lines[0][:80] if lines else "직접입력 글"
    body = "\n".join(lines[1:]).strip() or manual_text

    log(f"[직접입력] 글 {len(manual_text)}자를 원본으로 사용합니다. (제목 후보: {title})")
    return [{"title": title, "press": "직접입력", "body": body, "url": ""}]


def _resolve_brand_previews(brand_links: list, config: dict, log=print) -> dict:
    """체크된 브랜드커넥트 링크의 미리보기(상품 이미지)를 config 캐시에서 읽거나 새로 조회한다."""
    saved = dict(config.get("brand_connect_previews") or {})
    previews = {}
    updated = False

    for link in brand_links:
        url = brand_link_preview.normalize_url(link)
        if not url:
            continue
        cached = saved.get(url) or saved.get(link)
        if cached and brand_link_preview.is_valid_product_preview(cached):
            previews[url] = cached
            continue

        if cached and cached.get("image"):
            log(f"[브랜드커넥트] 잘못된 캐시 미리보기 감지 — 다시 조회: {url}")

        log(f"[브랜드커넥트] 상품 미리보기 조회 중: {url}")
        fetched = brand_link_preview.fetch_link_preview(url, log=log, use_cache=False)
        if brand_link_preview.is_valid_product_preview(fetched):
            previews[url] = fetched
            saved[url] = fetched
            updated = True
        elif cached:
            previews[url] = cached

    if updated:
        cfg = config_manager.load_config()
        cfg["brand_connect_previews"] = saved
        config_manager.save_config(cfg)

    return previews


def run_one_cycle(config: dict, log=print, stop_event=None, on_github_uploaded=None) -> None:
    """스크랩 -> AI 재작성 -> 이미지 생성 -> HTML 조합 -> 해당 HTML만 깃허브 업로드."""
    if stop_event is None:
        stop_event = threading.Event()

    source = config.get("news_source", "네이트온")
    category = config.get("news_category", "경제")
    google_menu = config.get("google_trend_menu", "구글 트랜드")
    trend_hours = int(config.get("google_trend_hours", 4))

    max_articles = config.get("max_articles_per_cycle", 3)
    delay = config.get("api_call_delay_sec", 8)
    brand_links = [
        str(link).strip()
        for link in config.get("brand_connect_checked", [])
        if str(link).strip()
    ]
    brand_previews = _resolve_brand_previews(brand_links, config, log=log) if brand_links else {}

    log("=" * 50)
    if source == "직접입력":
        label = "직접입력"
        log("[사이클 시작] 직접입력 글을 사용합니다 (크롤링 건너뜀).")
    elif source == "구글":
        label = google_menu
        log(f"[사이클 시작] 구글 트렌드 실시간 인기(지난 {trend_hours}시간) 확인 중...")
    else:
        label = f"{category} 뉴스"
        log(f"[사이클 시작] 네이트 뉴스 '{category}' 카테고리 확인 중...")
    log(f"[노출전략] {config.get('exposure_strategy', '홈판')}")

    if source == "직접입력":
        new_articles = _build_manual_articles(config, log=log)
    elif source == "구글":
        new_articles = google_trends_scraper.scrape_new_articles(
            max_articles=max_articles,
            hours=trend_hours,
            show_browser=bool(config.get("google_trend_show_browser", False)),
            log=log,
        )
    else:
        new_articles = news_scraper.scrape_new_articles(category=category, max_articles=max_articles, log=log)

    if not new_articles:
        log("[사이클 종료] 새로 처리할 기사가 없습니다.")
        return

    for idx, article in enumerate(new_articles, start=1):
        if stop_event.is_set():
            log("[사이클] 중지 요청으로 남은 기사 처리를 건너뜁니다.")
            break
        log(f"\n--- ({idx}/{len(new_articles)}) '{article['title']}' 처리 시작 ---")

        # 1) 뉴스 재작성 + 이미지 프롬프트 생성을 AI 질문 1회로 동시 처리
        generated = ai_writer.generate_new_article(
            article=article,
            api_key=config.get("text_ai_api_key", ""),
            model=config.get("text_ai_model", "claude-sonnet-5"),
            blog_style=config.get("blog_style", "정보성"),
            image_style=config.get("image_style", "실사"),
            exposure_strategy=config.get("exposure_strategy", "홈판"),
            log=log,
        )
        if not generated:
            log("[사이클] AI 생성 실패로 이 기사는 건너뜁니다.")
            continue

        # 2) 각각 다른 폴더에 저장 (재작성 뉴스 / 이미지 프롬프트)
        ai_writer.save_rewritten_news(article, generated, log=log)
        ai_writer.save_image_prompt(generated, log=log)

        log(f"[속도 조절] API 제한 보호를 위해 {delay}초 대기...")
        if stop_event.wait(timeout=delay):
            log("[사이클] 중지 요청으로 작업을 중단합니다.")
            break

        # 3) 저장된 프롬프트로 썸네일 이미지 생성
        import re as _re
        safe_title = _re.sub(r"[^0-9A-Za-z가-힣]+", "_", generated.get("title", "untitled")).strip("_")[:40]
        base_filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_title}"

        if config.get("image_style") == "텍스트 썸네일":
            log("[이미지생성] '텍스트 썸네일' 스타일 — AI 이미지 생성 없이 제목 썸네일을 만듭니다.")
            image_path = image_generator._create_local_fallback_thumbnail(
                base_filename, generated.get("title", ""), label
            )
        else:
            image_path = image_generator.generate_thumbnail(
                prompt_text=generated.get("image_prompt", ""),
                api_key=config.get("image_ai_api_key", ""),
                model=config.get("image_ai_model", "Hugging Face (FLUX Schnell, 자동 제공자)"),
                base_filename=base_filename,
                log=log,
                fallback_api_key=config.get("text_ai_api_key", ""),
                title_text=generated.get("title", ""),
                label=label,
            )

        if not image_path:
            log("[사이클] 이미지 생성 실패 — 이미지 없이 HTML을 생성합니다.")

        # 4) 이미지 + 재작성 뉴스를 조합해 HTML 생성 (체크된 브랜드커넥트 링크 포함)
        if brand_links:
            log(f"[브랜드커넥트] 체크된 링크 {len(brand_links)}개를 본문 중간에 랜덤 삽입합니다.")
        html_path = html_builder.build_html(
            generated=generated,
            image_path=image_path,
            design_style=config.get("design_style", "미니멀 클린형"),
            brand_links=brand_links,
            brand_previews=brand_previews,
            log=log,
        )

        if stop_event.is_set():
            log("[사이클] 중지 요청으로 작업을 중단합니다.")
            break

        upload_cfg = config_manager.get_github_upload_config()
        owner = upload_cfg.get("owner", "")
        token = upload_cfg.get("token", "")
        repos = upload_cfg.get("repos", [])

        if owner and token and repos:
            github_uploader.upload_single_html(
                html_path=html_path,
                images_folder=image_generator.IMAGES_DIR,
                owner=owner,
                token=token,
                repos=repos,
                log=log,
                stop_event=stop_event,
                after_upload=on_github_uploaded,
            )
        else:
            log("[깃허브] GitHub 설정이 없어 자동 업로드를 건너뜁니다.")

        if idx < len(new_articles):
            log(f"[속도 조절] 다음 기사 처리 전 {delay}초 대기...")
            if stop_event.wait(timeout=delay):
                log("[사이클] 중지 요청으로 작업을 중단합니다.")
                break

    log("\n[사이클 종료] 모든 신규 기사 처리를 완료했습니다.")


class NewsScheduler:
    """
    실행 버튼 클릭 -> 즉시 1회 실행 -> 이후 설정된 간격(시*60+분)마다 반복.
    stop()을 호출하면 안전하게 중단된다(대기 중이면 즉시 깨어나서 종료).
    """

    def __init__(self, get_config_func, log=print, on_github_uploaded=None):
        self.get_config_func = get_config_func  # 최신 설정을 매 사이클마다 다시 읽기 위한 콜백
        self.log = log
        self.on_github_uploaded = on_github_uploaded
        self._stop_event = threading.Event()
        self._thread = None

    def _interval_seconds(self, config: dict) -> int:
        hour = int(config.get("schedule_hour", 0))
        minute = int(config.get("schedule_minute", 0))
        total_minutes = hour * 60 + minute
        if total_minutes <= 0:
            total_minutes = 10  # 최소 10분 간격 보호
            self.log("[스케줄러] 간격이 0이라 최소 10분으로 보정합니다.")
        return total_minutes * 60

    def _run_loop(self):
        while not self._stop_event.is_set():
            config = self.get_config_func()
            try:
                run_one_cycle(
                    config,
                    log=self.log,
                    stop_event=self._stop_event,
                    on_github_uploaded=self.on_github_uploaded,
                )
            except Exception as e:
                self.log(f"[스케줄러] 사이클 실행 중 오류 발생: {e}")

            interval_sec = self._interval_seconds(config)
            self.log(f"[스케줄러] 다음 실행까지 {interval_sec // 60}분 대기합니다.")
            # wait()는 stop()이 호출되면 즉시 반환되어 빠르게 종료 가능
            self._stop_event.wait(timeout=interval_sec)

        self.log("[스케줄러] 중지되었습니다.")

    def start(self):
        if self._thread and self._thread.is_alive():
            self.log("[스케줄러] 이미 실행 중입니다.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log("[스케줄러] 시작되었습니다. 즉시 첫 사이클을 실행합니다.")

    def stop(self):
        if not self._thread or not self._thread.is_alive():
            self.log("[스케줄러] 실행 중이 아닙니다.")
            return
        self._stop_event.set()
        self.log("[스케줄러] 중지 요청됨. 현재 사이클 완료 후 종료됩니다.")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
