# -*- coding: utf-8 -*-
"""
gui.py
-------
좌측: 설정 패널 (설정 / API설정 / 깃허브 / 업로드된 글 탭)
우측: 실시간 로그 패널
두 패널을 동시에 볼 수 있도록 좌우로 배치한다.
"""

import json
import os
import queue
import webbrowser
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

import config_manager
import html_builder
from scheduler import NewsScheduler
from github_uploader import load_upload_log, save_upload_log
from tkinter import messagebox
from login_window import AdminLoginDialog
from auth_manager import GitHubDB, get_github_auth_config
from input_windows import (
    ManualArticleDialog,
    BrandConnectDialog,
    MAX_BRAND_LINKS,
    MAX_BRAND_CHECKED,
)


GITHUB_UPLOAD_LOG_PATH = "github_uploaded_log.json"  # 업로드 완료된 html 경로를 기록해두는 파일

HOURS = [str(h) for h in range(0, 24)]          # 0~23시 (24시간제)
MINUTES = ["00", "10", "20", "30", "40", "50"]  # 10분 단위

TEXT_MODELS = ["Gemini 3 Flash preview", "Gemini 2.5 Flash", "Gemini 3.1 Flash Lite"]
IMAGE_MODELS = [
    "Hugging Face (FLUX Schnell, 자동 제공자)",
    "Hugging Face (SDXL, 자동 제공자)",
    "ChatGPT (GPT Image 2)",
    "ChatGPT (GPT Image 1.5)",
    "ChatGPT (GPT Image 1)",
    "ChatGPT (GPT Image 1 Mini)",
    "Kling (Text-to-Image)",
    "HeyGen (Prompt-to-Avatar)",
    "Pollinations (크레딧, Z-Image)",
    "Pollinations (크레딧, Klein)",
    "Pollinations (API 키)",
    "Gemini 3.1 Flash Image",
    "Gemini 2.5 Flash Image",
]
NEWS_CATEGORIES = ["경제", "사회", "스포츠", "연예"]
NEWS_SOURCES = ["네이트온", "구글", "직접입력"]
GOOGLE_TREND_MENUS = ["구글 트랜드"]
DESIGN_STYLES = [
    ("미니멀 클린형", "세리프 제목, 도입 리드 단락, 얇은 구분선"),
    ("매거진/카드형", "번호 소제목, 좌측 강조 단락, 굵은 테두리 프레임"),
    ("다크모드 프리미엄형", "골드 장식선, 인용형 도입문, ◆ 프리미엄 헤더"),
]
EXPOSURE_STRATEGIES = [
    ("SEO", "검색 노출 — 키워드·구조·스니펫(직접답변) 최적화"),
    ("홈판", "홈피드 노출 — 후킹·체류·완독률·클릭 유도 최적화"),
    ("GEO", "AI 인용 — ChatGPT·Perplexity 등 생성형 AI 인용 최적화"),
]

# 화면 드롭다운 목록에 더 이상 존재하지 않는 예전(레거시) 모델명 -> 새 모델명 매핑.
# "자동 (무료 우선)"은 다른 모델로 넘기지 않도록 HF FLUX로 고정한다.
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


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("네이트 뉴스 AI 블로그 자동 생성기")

        self.config_data = config_manager.load_config()
        self.log_queue = queue.Queue()

        # 저장된 창 크기가 있으면 그 크기로, 없으면 기본값으로 시작
        saved_geometry = self.config_data.get("window_geometry", "1200x900")
        self.geometry(saved_geometry)
        self.minsize(1000, 900)

        self._build_layout()
        self._load_values_into_widgets()
        self.after_idle(self._apply_pane_ratio)

        self.scheduler = NewsScheduler(
            get_config_func=self._get_current_config,
            log=self._log_from_thread,
            on_github_uploaded=lambda _path: self.after(0, self._refresh_uploaded_list),
        )

        self.after(200, self._poll_log_queue)

        # 창을 닫을 때 현재 크기를 저장
        self.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _on_close(self):
        """창을 닫을 때 현재 크기를 config에 저장해서 다음 실행 때 복원."""
        cfg = config_manager.load_config()
        cfg["window_geometry"] = self.geometry()
        config_manager.save_config(cfg)
        self.destroy()

    def _apply_pane_ratio(self):
        """설정 탭 영역 : 로그 영역 = 1 : 2 비율로 분할."""
        self.update_idletasks()
        total = self.paned_container.winfo_width()
        if total > 1:
            self.paned_container.sashpos(0, max(self.paned_container.pane(0)["minsize"], total // 3))

    # ---------------------------------------------------------- 레이아웃
    def _build_layout(self):
        self.paned_container = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        self.paned_container.pack(fill=tk.BOTH, expand=True)

        settings_frame = ttk.Frame(self.paned_container, padding=12)
        log_frame = ttk.Frame(self.paned_container, padding=12)
        self.paned_container.add(settings_frame, minsize=280)
        self.paned_container.add(log_frame, minsize=400)

        settings_notebook = ttk.Notebook(settings_frame)
        settings_notebook.pack(fill="both", expand=True)

        settings_tab = ttk.Frame(settings_notebook)
        api_tab = ttk.Frame(settings_notebook)
        github_tab = ttk.Frame(settings_notebook)
        uploaded_tab = ttk.Frame(settings_notebook)
        settings_notebook.add(settings_tab, text="⚙ 설정")
        settings_notebook.add(api_tab, text="🔑 API설정")
        settings_notebook.add(github_tab, text="🐙 깃허브")
        settings_notebook.add(uploaded_tab, text="📋 업로드된 글")
        settings_notebook.select(settings_tab)

        self._build_settings_panel(settings_tab)
        self._build_api_panel(api_tab)
        self._build_github_panel(github_tab)
        self._build_uploaded_list_panel(uploaded_tab)
        self._build_log_panel(log_frame)

    def _build_scrollable_panel(self, parent):
        """스크롤 가능한 내부 프레임을 만들어 (canvas, scroll_frame) 튜플로 반환."""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(canvas_window, width=event.width)

        scroll_frame.bind("<Configure>", _on_frame_configure)
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel, add="+")
            for child in widget.winfo_children():
                _bind_mousewheel(child)

        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        _bind_mousewheel(scroll_frame)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return canvas, scroll_frame

    def _build_api_panel(self, parent):
        _, scroll_frame = self._build_scrollable_panel(parent)

        api_box = ttk.LabelFrame(scroll_frame, text="① AI API 설정", padding=10)
        api_box.pack(fill="x", pady=6)

        ttk.Label(api_box, text="뉴스 재작성 AI API 키 (예: Anthropic Claude)").pack(anchor="w")
        link_label = ttk.Label(api_box, text="API 발급받기", foreground="blue", cursor="hand2")
        link_label.pack(anchor="w", pady=(0, 6))
        link_label.bind("<Button-1>", lambda e: webbrowser.open("https://aistudio.google.com/api-keys?project=gen-lang-client-0636498628"))
        self.text_api_entry = ttk.Entry(api_box, show="*", width=42)
        self.text_api_entry.pack(fill="x")
        self.text_api_mask_label = ttk.Label(api_box, text="현재 저장된 키: -", foreground="#666")
        self.text_api_mask_label.pack(anchor="w", pady=(0, 6))

        ttk.Label(api_box, text="뉴스 재작성 AI 모델명").pack(anchor="w")
        self.text_model_combo = ttk.Combobox(api_box, values=TEXT_MODELS, width=40, state="readonly")
        self.text_model_combo.pack(fill="x", pady=(0, 10))

        ttk.Label(
            api_box,
            text="이미지 생성 AI API 키\n"
                 "(HF: hf_… / OpenAI: sk-… / Google: AIza… /\n"
                 "Pollinations: sk_… / Kling: 액세스키:시크릿키 / HeyGen: API키)",
            justify="left",
        ).pack(anchor="w")
        pollinations_link = ttk.Label(api_box, text="Pollinations 키 발급 (enter.pollinations.ai)", foreground="blue", cursor="hand2")
        pollinations_link.pack(anchor="w")
        pollinations_link.bind("<Button-1>", lambda e: webbrowser.open("https://enter.pollinations.ai/keys"))
        hf_link = ttk.Label(api_box, text="Hugging Face 토큰 발급 (Inference Providers 권한 필요)", foreground="blue", cursor="hand2")
        hf_link.pack(anchor="w")
        hf_link.bind("<Button-1>", lambda e: webbrowser.open("https://huggingface.co/settings/tokens"))
        openai_link = ttk.Label(api_box, text="OpenAI(ChatGPT) API 키 발급", foreground="blue", cursor="hand2")
        openai_link.pack(anchor="w")
        openai_link.bind("<Button-1>", lambda e: webbrowser.open("https://platform.openai.com/api-keys"))
        kling_link = ttk.Label(api_box, text="Kling API 키 발급 (액세스키:시크릿키 형식으로 입력)", foreground="blue", cursor="hand2")
        kling_link.pack(anchor="w")
        kling_link.bind("<Button-1>", lambda e: webbrowser.open("https://app.klingai.com/global/dev"))
        heygen_link = ttk.Label(api_box, text="HeyGen API 키 발급", foreground="blue", cursor="hand2")
        heygen_link.pack(anchor="w", pady=(0, 6))
        heygen_link.bind("<Button-1>", lambda e: webbrowser.open("https://app.heygen.com/settings/api"))
        self.image_api_entry = ttk.Entry(api_box, show="*", width=42)
        self.image_api_entry.pack(fill="x")
        self.image_api_mask_label = ttk.Label(api_box, text="현재 저장된 키: -", foreground="#666")
        self.image_api_mask_label.pack(anchor="w", pady=(0, 6))

        ttk.Label(api_box, text="이미지 생성 AI 모델명").pack(anchor="w")
        self.image_model_combo = ttk.Combobox(api_box, values=IMAGE_MODELS, width=40, state="readonly")
        self.image_model_combo.pack(fill="x")

        btn_box = ttk.Frame(scroll_frame, padding=(0, 12))
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="💾 설정저장", command=self._on_api_save_clicked).pack(fill="x", pady=4)

    def _build_settings_panel(self, parent):
        _, scroll_frame = self._build_scrollable_panel(parent)

        # --- 노출 전략 ---
        exposure_box = ttk.LabelFrame(scroll_frame, text="① 노출전략", padding=10)
        exposure_box.pack(fill="x", pady=6)
        self.exposure_strategy_var = tk.StringVar()
        for name, desc in EXPOSURE_STRATEGIES:
            row = ttk.Frame(exposure_box)
            row.pack(fill="x", anchor="w", pady=2)
            ttk.Radiobutton(row, text=name, value=name, variable=self.exposure_strategy_var).pack(side="left")
            ttk.Label(row, text=f"— {desc}", foreground="#666", wraplength=280, justify="left").pack(
                side="left", padx=(4, 0)
            )

        # --- 디자인 스타일 ---
        design_box = ttk.LabelFrame(scroll_frame, text="② 디자인 스타일", padding=10)
        design_box.pack(fill="x", pady=6)
        self.design_style_var = tk.StringVar()
        for name, desc in DESIGN_STYLES:
            row = ttk.Frame(design_box)
            row.pack(fill="x", anchor="w", pady=2)
            ttk.Radiobutton(row, text=name, value=name, variable=self.design_style_var).pack(side="left")
            ttk.Label(row, text=f"— {desc}", foreground="#666", wraplength=280, justify="left").pack(
                side="left", padx=(4, 0)
            )

        # --- 글 스타일 ---
        style_box = ttk.LabelFrame(scroll_frame, text="③ 블로그 글 스타일", padding=10)
        style_box.pack(fill="x", pady=6)
        self.blog_style_var = tk.StringVar()
        for style in ["블로그", "정보성", "전문성"]:
            ttk.Radiobutton(style_box, text=style, value=style, variable=self.blog_style_var).pack(side="left", padx=(0, 15))

        # --- 이미지 스타일 ---
        img_style_box = ttk.LabelFrame(scroll_frame, text="④ 썸네일 이미지 스타일", padding=10)
        img_style_box.pack(fill="x", pady=6)
        self.image_style_var = tk.StringVar()
        for style in ["실사", "차비", "영화", "스틱맨", "동양로맨스 2D", "텍스트 썸네일"]:
            ttk.Radiobutton(img_style_box, text=style, value=style, variable=self.image_style_var).pack(anchor="w")

        # --- 뉴스 카테고리 ---
        category_box = ttk.LabelFrame(scroll_frame, text="⑤ 크롤링할 뉴스 카테고리", padding=10)
        category_box.pack(fill="x", pady=6)
        self.news_source_var = tk.StringVar(value=NEWS_SOURCES[0])

        nate_row = ttk.Frame(category_box)
        nate_row.pack(fill="x", anchor="w", pady=2)
        ttk.Radiobutton(
            nate_row, text="네이트온", value="네이트온", width=9,
            variable=self.news_source_var, command=self._on_news_source_changed,
        ).pack(side="left")
        self.news_category_combo = ttk.Combobox(nate_row, values=NEWS_CATEGORIES, width=15, state="readonly")
        self.news_category_combo.pack(side="left", padx=(8, 0))

        google_row = ttk.Frame(category_box)
        google_row.pack(fill="x", anchor="w", pady=2)
        ttk.Radiobutton(
            google_row, text="구글", value="구글", width=9,
            variable=self.news_source_var, command=self._on_news_source_changed,
        ).pack(side="left")
        self.google_menu_combo = ttk.Combobox(google_row, values=GOOGLE_TREND_MENUS, width=15, state="readonly")
        self.google_menu_combo.pack(side="left", padx=(8, 0))

        manual_row = ttk.Frame(category_box)
        manual_row.pack(fill="x", anchor="w", pady=2)
        ttk.Radiobutton(
            manual_row, text="직접입력", value="직접입력", width=9,
            variable=self.news_source_var, command=self._on_news_source_changed,
        ).pack(side="left")
        self.manual_input_button = ttk.Button(
            manual_row, text="✏ 직접입력", width=17, command=self._on_manual_input_clicked,
        )
        self.manual_input_button.pack(side="left", padx=(8, 0))

        self.manual_status_label = ttk.Label(category_box, text="", foreground="#666")
        self.manual_status_label.pack(anchor="w", pady=(2, 0))

        ttk.Label(
            category_box,
            text="구글 트랜드: 실시간 인기 ▸ '지난 4시간' 상위 검색어를 클릭해\n"
                 "우측에 나오는 관련 뉴스 3건을 수집합니다.\n"
                 "직접입력: 크롤링하지 않고 직접 쓴 글에 노출전략·디자인 스타일·\n"
                 "글 스타일 옵션을 적용해 새 글을 작성합니다.",
            foreground="#666",
            wraplength=300,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # --- 브랜드커넥트 링크 ---
        brand_box = ttk.LabelFrame(scroll_frame, text="🔗 브랜드커넥트 링크", padding=10)
        brand_box.pack(fill="x", pady=6)
        ttk.Button(
            brand_box, text="🔗 브랜드커넥트 링크 넣기", command=self._on_brand_connect_clicked,
        ).pack(fill="x")
        self.brand_link_status_label = ttk.Label(brand_box, text="", foreground="#666")
        self.brand_link_status_label.pack(anchor="w", pady=(6, 0))

        # --- 실행 주기 ---
        schedule_box = ttk.LabelFrame(scroll_frame, text="⑥ 기사 생성 실행 주기", padding=10)
        schedule_box.pack(fill="x", pady=6)

        row1 = ttk.Frame(schedule_box)
        row1.pack(fill="x")
        ttk.Label(row1, text="시간(0~23시)").pack(side="left")
        self.hour_combo = ttk.Combobox(row1, values=HOURS, width=6, state="readonly")
        self.hour_combo.pack(side="left", padx=8)

        ttk.Label(row1, text="분(10분 단위)").pack(side="left", padx=(12, 0))
        self.minute_combo = ttk.Combobox(row1, values=MINUTES, width=6, state="readonly")
        self.minute_combo.pack(side="left", padx=8)

        row2 = ttk.Frame(schedule_box)
        row2.pack(fill="x", pady=(10, 0))
        ttk.Label(row2, text="API 호출 간 딜레이(초)").pack(side="left")
        self.delay_entry = ttk.Entry(row2, width=8)
        self.delay_entry.pack(side="left", padx=8)

        row3 = ttk.Frame(schedule_box)
        row3.pack(fill="x", pady=(10, 0))
        ttk.Label(row3, text="사이클당 최대 기사 수").pack(side="left")
        self.max_articles_entry = ttk.Entry(row3, width=8)
        self.max_articles_entry.pack(side="left", padx=8)

        # --- 버튼 영의 ---
        btn_box = ttk.Frame(scroll_frame, padding=(0, 12))
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="💾 설정 저장", command=self._on_save_clicked).pack(fill="x", pady=4)
        self.run_button = ttk.Button(btn_box, text="▶ 실행 시작", command=self._on_run_clicked)
        self.run_button.pack(fill="x", pady=4)
        self.stop_button = ttk.Button(btn_box, text="■ 실행 중지", command=self._on_stop_clicked)
        self.stop_button.pack(fill="x", pady=4)
        
        # 관리자모드 버튼 추가 (팝업창 연동)
        self.admin_button = ttk.Button(btn_box, text="🛠 관리자모드", command=self._on_admin_clicked)
        self.admin_button.pack(fill="x", pady=4)

        self.status_label = ttk.Label(scroll_frame, text="상태: 대기 중", foreground="#0a6")
        self.status_label.pack(anchor="w", pady=(4, 0))

    def _on_news_source_changed(self):
        """선택된 소스(네이트온/구글/직접입력)에 해당하는 입력만 활성화한다."""
        source = self.news_source_var.get()
        self.news_category_combo.config(state="readonly" if source == "네이트온" else "disabled")
        self.google_menu_combo.config(state="readonly" if source == "구글" else "disabled")

    def _on_manual_input_clicked(self):
        ManualArticleDialog(self, on_saved=self._on_manual_text_saved)

    def _on_manual_text_saved(self, text: str):
        self.config_data = config_manager.load_config()
        self._refresh_manual_status()
        self._append_log(f"[직접입력] 원본 글 저장 완료 ({len(text)}자).")

    def _refresh_manual_status(self):
        text = (self.config_data.get("manual_article_text", "") or "").strip()
        if text:
            preview = text.splitlines()[0][:24]
            self.manual_status_label.config(text=f"저장된 글: {len(text)}자 — {preview}…")
        else:
            self.manual_status_label.config(text="저장된 글 없음")

    def _on_brand_connect_clicked(self):
        BrandConnectDialog(self, on_saved=self._on_brand_links_saved)

    def _on_brand_links_saved(self, links: list, checked: list):
        self.config_data = config_manager.load_config()
        self._refresh_brand_link_status()
        self._append_log(f"[브랜드커넥트] 링크 {len(links)}개 저장 완료 (글 삽입용 체크 {len(checked)}개).")

    def _refresh_brand_link_status(self):
        links = self.config_data.get("brand_connect_links", []) or []
        checked = self.config_data.get("brand_connect_checked", []) or []
        self.brand_link_status_label.config(
            text=f"등록 {len(links)}개 / 최대 {MAX_BRAND_LINKS}개  ·  "
                 f"글에 넣을 체크 {len(checked)}개 / 최대 {MAX_BRAND_CHECKED}개"
        )

    def _build_log_panel(self, parent):
        ttk.Label(parent, text="실시간 로그", font=("", 12, "bold")).pack(anchor="w")
        self.log_text = scrolledtext.ScrolledText(parent, state="disabled", wrap="word", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, pady=(6, 0))

    def _build_github_panel(self, parent):
        box = ttk.Frame(parent, padding=12)
        box.pack(fill="both", expand=True)

        ttk.Label(
            box,
            text="본인 GitHub 저장소에 HTML·이미지를 업로드합니다.\n"
                 "설정 탭 ▶ 실행 시작 시 글 생성 후 자동 업로드됩니다.\n"
                 "로그인 DB(관리자 저장소)와 별개 — 각자 repo를 만들어 입력하세요.",
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        auth_box = ttk.LabelFrame(box, text="① 본인 GitHub 인증 (업로드용)", padding=10)
        auth_box.pack(fill="x", pady=6)

        ttk.Label(auth_box, text="본인 GitHub 아이디(owner)").pack(anchor="w")
        self.github_upload_owner_entry = ttk.Entry(auth_box, width=42)
        self.github_upload_owner_entry.pack(fill="x", pady=(0, 6))

        ttk.Label(auth_box, text="본인 Personal Access Token (repo 권한)").pack(anchor="w")
        self.github_upload_token_entry = ttk.Entry(auth_box, show="*", width=42)
        self.github_upload_token_entry.pack(fill="x")
        self.github_upload_token_mask_label = ttk.Label(auth_box, text="현재 저장된 토큰: -", foreground="#666")
        self.github_upload_token_mask_label.pack(anchor="w", pady=(0, 6))

        repo_box = ttk.LabelFrame(box, text="② 본인 업로드 저장소 (1→2→3 순서 반복)", padding=10)
        repo_box.pack(fill="x", pady=6)

        ttk.Label(repo_box, text="저장소 1 (필수)").pack(anchor="w")
        self.github_upload_repo1_entry = ttk.Entry(repo_box, width=42)
        self.github_upload_repo1_entry.pack(fill="x", pady=(0, 6))

        ttk.Label(repo_box, text="저장소 2 (선택)").pack(anchor="w")
        self.github_upload_repo2_entry = ttk.Entry(repo_box, width=42)
        self.github_upload_repo2_entry.pack(fill="x", pady=(0, 6))

        ttk.Label(repo_box, text="저장소 3 (선택)").pack(anchor="w")
        self.github_upload_repo3_entry = ttk.Entry(repo_box, width=42)
        self.github_upload_repo3_entry.pack(fill="x")

        btn_box = ttk.Frame(box, padding=(0, 12))
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="💾 업로드 설정 저장", command=self._on_github_save_clicked).pack(fill="x", pady=4)

    def _build_uploaded_list_panel(self, parent):
        box = ttk.Frame(parent, padding=12)
        box.pack(fill="both", expand=True)

        ttk.Label(
            box,
            text="이 PC에서 생성하여 GitHub에 업로드한 글만 표시됩니다.\n"
                 "항목을 더블클릭하면 브라우저로 바로 열립니다.\n"
                 "(열린 화면에서 전체 선택 후 복사해서 블로그에 붙여넣으세요)",
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        columns = ("title", "repo", "uploaded_at")
        self.uploaded_tree = ttk.Treeview(box, columns=columns, show="headings", height=20)
        self.uploaded_tree.heading("title", text="제목")
        self.uploaded_tree.heading("repo", text="저장소")
        self.uploaded_tree.heading("uploaded_at", text="업로드 시각")
        self.uploaded_tree.column("title", width=180)
        self.uploaded_tree.column("repo", width=100)
        self.uploaded_tree.column("uploaded_at", width=140)
        self.uploaded_tree.pack(fill="both", expand=True)
        self.uploaded_tree.bind("<Double-1>", self._on_uploaded_item_double_click)

        btn_row = ttk.Frame(box)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="🔄 새로고침", command=self._refresh_uploaded_list).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="🗑 선택 삭제", command=self._on_delete_uploaded_item).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.uploaded_link_map = {}      # treeview row id -> url
        self.uploaded_path_map = {}      # treeview row id -> html 원본 경로
        self._refresh_uploaded_list()

    def _local_html_path(self, file_key: str) -> str:
        return os.path.join(html_builder.HTML_OUTPUT_DIR, file_key)

    def _is_local_created_html(self, file_key: str) -> bool:
        return os.path.isfile(self._local_html_path(file_key))

    def _refresh_uploaded_list(self):
        for row in self.uploaded_tree.get_children():
            self.uploaded_tree.delete(row)
        self.uploaded_link_map = {}
        self.uploaded_path_map = {}

        uploaded_log = self._load_github_upload_log()
        items = sorted(uploaded_log.items(), key=lambda kv: kv[1].get("uploaded_at", ""), reverse=True)
        for file_key, info in items:
            if not self._is_local_created_html(file_key):
                continue
            row_id = self.uploaded_tree.insert(
                "", "end",
                values=(info.get("title", ""), info.get("repo", ""), info.get("uploaded_at", "")),
            )
            self.uploaded_link_map[row_id] = info.get("url", "")
            self.uploaded_path_map[row_id] = file_key

    def _on_uploaded_item_double_click(self, _event):
        selected = self.uploaded_tree.selection()
        if not selected:
            return
        url = self.uploaded_link_map.get(selected[0])
        if url:
            webbrowser.open(url)
        else:
            messagebox.showwarning("확인", "이 항목에는 저장된 링크가 없습니다.")

    def _on_delete_uploaded_item(self):
        selected = self.uploaded_tree.selection()
        if not selected:
            messagebox.showwarning("확인", "삭제할 항목을 목록에서 먼저 선택해주세요.")
            return

        count = len(selected)
        confirm = messagebox.askyesno(
            "삭제 확인",
            f"선택한 {count}개 항목을 목록에서 삭제할까요?\n"
            "(GitHub에 올라간 파일은 지워지지 않고, 이 목록 기록만 삭제됩니다.)",
        )
        if not confirm:
            return

        uploaded_log = self._load_github_upload_log()
        for row_id in selected:
            file_key = self.uploaded_path_map.get(row_id)
            if file_key and file_key in uploaded_log:
                del uploaded_log[file_key]

        self._save_github_upload_log(uploaded_log)
        self._refresh_uploaded_list()
        self._append_log(f"[업로드 목록] {count}개 항목을 목록에서 삭제했습니다.")

    # ---------------------------------------------------------- 깃허브 탭 로직
    def _load_github_upload_log(self) -> dict:
        return load_upload_log(GITHUB_UPLOAD_LOG_PATH)

    def _save_github_upload_log(self, uploaded_dict: dict):
        save_upload_log(GITHUB_UPLOAD_LOG_PATH, uploaded_dict)

    def _on_github_save_clicked(self):
        cfg = config_manager.load_config()

        new_token = self.github_upload_token_entry.get().strip()
        if new_token:
            cfg["github_upload_token"] = new_token

        cfg["github_upload_owner"] = self.github_upload_owner_entry.get().strip()
        cfg["github_upload_repo1"] = self.github_upload_repo1_entry.get().strip()
        cfg["github_upload_repo2"] = self.github_upload_repo2_entry.get().strip()
        cfg["github_upload_repo3"] = self.github_upload_repo3_entry.get().strip()

        config_manager.save_config(cfg)
        self.config_data = config_manager.load_config()

        self.github_upload_token_entry.delete(0, tk.END)
        self.github_upload_token_mask_label.config(
            text=f"현재 저장된 토큰: {config_manager.mask_key(self.config_data.get('github_upload_token', ''))}")

        self._append_log("[깃허브] 업로드 설정 저장 완료.")
        messagebox.showinfo("저장 완료", "본인 GitHub 업로드 설정이 저장되었습니다.")

    # ---------------------------------------------------------- 값 로딩/저장
    def _load_values_into_widgets(self):
        cfg = self.config_data
        text_model = cfg.get("text_ai_model", TEXT_MODELS[0])

        raw_image_model = cfg.get("image_ai_model", IMAGE_MODELS[0])
        if raw_image_model in IMAGE_MODELS:
            corrected_image_model = raw_image_model
        else:
            corrected_image_model = LEGACY_IMAGE_MODELS.get(raw_image_model, IMAGE_MODELS[0])

        if corrected_image_model != raw_image_model:
            fixed_cfg = config_manager.load_config()
            fixed_cfg["image_ai_model"] = corrected_image_model
            config_manager.save_config(fixed_cfg)
            self.config_data = config_manager.load_config()
            cfg = self.config_data
            self._log_after_ui_ready = getattr(self, "_log_after_ui_ready", [])
            self._log_after_ui_ready.append(
                f"[설정] 이미지 모델 저장값이 인식할 수 없는 값('{raw_image_model}')이라 "
                f"'{corrected_image_model}'(으)로 자동 교정하여 config.json에 다시 저장했습니다."
            )

        self.text_model_combo.set(text_model if text_model in TEXT_MODELS else TEXT_MODELS[0])
        self.image_model_combo.set(corrected_image_model)
        exposure = cfg.get("exposure_strategy", "홈판")
        self.exposure_strategy_var.set(exposure if exposure in [s[0] for s in EXPOSURE_STRATEGIES] else "홈판")
        self.design_style_var.set(cfg.get("design_style", DESIGN_STYLES[0][0]))
        self.blog_style_var.set(cfg.get("blog_style", "정보성"))
        self.image_style_var.set(cfg.get("image_style", "실사"))
        self.news_category_combo.set(cfg.get("news_category", NEWS_CATEGORIES[0]))
        source = cfg.get("news_source", NEWS_SOURCES[0])
        self.news_source_var.set(source if source in NEWS_SOURCES else NEWS_SOURCES[0])
        google_menu = cfg.get("google_trend_menu", GOOGLE_TREND_MENUS[0])
        self.google_menu_combo.set(google_menu if google_menu in GOOGLE_TREND_MENUS else GOOGLE_TREND_MENUS[0])
        self._on_news_source_changed()
        self._refresh_manual_status()
        self._refresh_brand_link_status()
        self.hour_combo.set(str(cfg.get("schedule_hour", 1)))
        self.minute_combo.set(f"{int(cfg.get('schedule_minute', 0)):02d}")
        self.delay_entry.insert(0, str(cfg.get("api_call_delay_sec", 8)))
        self.max_articles_entry.insert(0, str(cfg.get("max_articles_per_cycle", 3)))

        self.text_api_mask_label.config(
            text=f"현재 저장된 키: {config_manager.mask_key(cfg.get('text_ai_api_key',''))}")
        self.image_api_mask_label.config(
            text=f"현재 저장된 키: {config_manager.mask_key(cfg.get('image_ai_api_key',''))}")

        self.github_upload_owner_entry.insert(0, cfg.get("github_upload_owner", ""))
        self.github_upload_repo1_entry.insert(0, cfg.get("github_upload_repo1", ""))
        self.github_upload_repo2_entry.insert(0, cfg.get("github_upload_repo2", ""))
        self.github_upload_repo3_entry.insert(0, cfg.get("github_upload_repo3", ""))
        self.github_upload_token_mask_label.config(
            text=f"현재 저장된 토큰: {config_manager.mask_key(cfg.get('github_upload_token', ''))}")

        for msg in getattr(self, "_log_after_ui_ready", []):
            self._append_log(msg)
        self._log_after_ui_ready = []

    def _get_current_config(self) -> dict:
        return config_manager.load_config()

    def _on_api_save_clicked(self):
        new_text_key = self.text_api_entry.get().strip()
        new_image_key = self.image_api_entry.get().strip()

        cfg = config_manager.load_config()
        if new_text_key:
            cfg["text_ai_api_key"] = new_text_key
        if new_image_key:
            cfg["image_ai_api_key"] = new_image_key

        cfg["text_ai_model"] = self.text_model_combo.get()
        cfg["image_ai_model"] = self.image_model_combo.get()

        config_manager.save_config(cfg)
        self.config_data = config_manager.load_config()

        self.text_api_entry.delete(0, tk.END)
        self.image_api_entry.delete(0, tk.END)
        self.text_api_mask_label.config(
            text=f"현재 저장된 키: {config_manager.mask_key(self.config_data.get('text_ai_api_key',''))}")
        self.image_api_mask_label.config(
            text=f"현재 저장된 키: {config_manager.mask_key(self.config_data.get('image_ai_api_key',''))}")

        self._append_log("[API설정] 저장 완료.")
        messagebox.showinfo("저장 완료", "API 설정이 저장되었습니다.")

    def _on_save_clicked(self):
        cfg = config_manager.load_config()
        cfg["exposure_strategy"] = self.exposure_strategy_var.get()
        cfg["design_style"] = self.design_style_var.get()
        cfg["blog_style"] = self.blog_style_var.get()
        cfg["image_style"] = self.image_style_var.get()
        cfg["news_category"] = self.news_category_combo.get()
        cfg["news_source"] = self.news_source_var.get()
        cfg["google_trend_menu"] = self.google_menu_combo.get()
        cfg["schedule_hour"] = int(self.hour_combo.get() or 0)
        cfg["schedule_minute"] = int(self.minute_combo.get() or 0)

        try:
            cfg["api_call_delay_sec"] = int(self.delay_entry.get())
            cfg["max_articles_per_cycle"] = int(self.max_articles_entry.get())
        except ValueError:
            messagebox.showerror("입력 오류", "딜레이(초)와 최대 기사 수는 숫자로 입력해주세요.")
            return

        config_manager.save_config(cfg)
        self.config_data = config_manager.load_config()

        self._append_log("[설정] 저장 완료.")
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")

    # ---------------------------------------------------------- 실행/중지/관리자모드
    def _on_run_clicked(self):
        cfg = config_manager.load_config()
        if not cfg.get("text_ai_api_key"):
            messagebox.showwarning("확인", "뉴스 재작성 AI API 키를 먼저 저장해주세요.")
            return
        if cfg.get("news_source") == "직접입력" and not (cfg.get("manual_article_text", "") or "").strip():
            messagebox.showwarning("확인", "'직접입력' 버튼을 눌러 사용할 원본 글을 먼저 저장해주세요.")
            return
        self.scheduler.start()
        self.status_label.config(text="상태: 실행 중", foreground="#c00")

    def _on_stop_clicked(self):
        self.scheduler.stop()
        self.status_label.config(text="상태: 중지 요청됨", foreground="#666")

    def _get_db(self):
        """깃허브 DB 접속 객체를 생성하여 반환합니다."""
        cfg = get_github_auth_config()
        if not cfg.get("owner") or not cfg.get("token") or not cfg.get("repo"):
            messagebox.showerror("설정 오류", "깃허브 로그인 DB 설정이 없습니다.\nconfig.json의 github_login_* 항목을 확인하세요.")
            return None
        return GitHubDB(owner=cfg['owner'], repo=cfg['repo'], token=cfg['token'])

    def _on_admin_clicked(self):
        """관리자모드 버튼 클릭 시 팝업창을 띄우고 DB 인증을 거쳐 관리자 웹페이지를 엽니다."""
        AdminLoginDialog(self, self._get_db)

    # ---------------------------------------------------------- 로그 처리
    def _log_from_thread(self, message: str):
        self.log_queue.put(message)

    def _poll_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self._append_log(message)
        except queue.Empty:
            pass
        self.after(200, self._poll_log_queue)

    def _append_log(self, message: str):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    from main import ensure_directories

    ensure_directories()

    def on_login_success():
        app = MainApp()
        app.mainloop()

    from login_window import LoginWindow
    login = LoginWindow(on_login_success)
    login.mainloop()