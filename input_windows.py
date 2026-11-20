# -*- coding: utf-8 -*-
"""
input_windows.py
-----------------
설정 탭에서 열리는 두 개의 입력 팝업 창.

- ManualArticleDialog : 크롤링 대신 사용할 원본 글을 직접 붙여넣는 창
- BrandConnectDialog  : 브랜드커넥트 링크를 1줄에 1개씩 최대 50개까지 관리하는 창
"""

import os
import subprocess
import webbrowser
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

import config_manager
import brand_link_preview

MAX_BRAND_LINKS = 50      # 등록 가능한 전체 링크 수
MAX_BRAND_CHECKED = 3     # 글에 삽입할 수 있도록 체크 가능한 링크 수

_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


def normalize_url(url: str) -> str:
    """스킴이 없는 주소도 브라우저가 열 수 있도록 https:// 를 붙여준다."""
    url = (url or "").strip()
    if url and not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def open_in_chrome(url: str) -> None:
    """크롬으로 주소를 연다. 크롬을 찾지 못하면 기본 브라우저로 대체."""
    url = normalize_url(url)
    if not url:
        return

    for path in _CHROME_CANDIDATES:
        if os.path.isfile(path):
            subprocess.Popen([path, url])
            return
    try:
        webbrowser.get("chrome").open(url)
    except webbrowser.Error:
        webbrowser.open(url)


class _BaseDialog(tk.Toplevel):
    """부모 창 중앙에 뜨는 모달 팝업 공통 동작."""

    def __init__(self, parent, title: str, geometry: str):
        super().__init__(parent)
        self.title(title)
        self.geometry(geometry)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._center_window(parent)

    def _center_window(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _build_ui(self):
        raise NotImplementedError


class ManualArticleDialog(_BaseDialog):
    """
    '직접입력'을 선택했을 때 사용할 원본 글을 작성/붙여넣는 창.
    저장하면 config.json의 manual_article_text에 기록된다.
    """

    def __init__(self, parent, on_saved=None):
        self.on_saved = on_saved
        super().__init__(parent, "✏ 직접입력 — 원본 글 작성", "620x560")
        self.resizable(True, True)
        self.minsize(520, 420)

    def _build_ui(self):
        main = ttk.Frame(self, padding=16)
        main.pack(fill="both", expand=True)

        btn_row = ttk.Frame(main)
        btn_row.pack(side=tk.BOTTOM, fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="💾 저장", command=self._on_save).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="✖ 취소", command=self.destroy).pack(
            side="left", fill="x", expand=True, padx=(4, 0))

        self.count_label = ttk.Label(main, text="", foreground="#666")
        self.count_label.pack(side=tk.BOTTOM, anchor="w", pady=(6, 0))

        header = ttk.Frame(main)
        header.pack(side=tk.TOP, fill="x")
        ttk.Label(header, text="✏ 직접입력 원본 글", font=("맑은 고딕", 12, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="여기에 쓴 글은 크롤링 대신 사용됩니다.\n"
                 "저장 후 '직접입력'을 선택하고 실행하면, 이 글을 바탕으로\n"
                 "노출전략·디자인 스타일·블로그 글 스타일 옵션을 적용해 새 글을 작성합니다.\n"
                 "첫 줄은 제목으로, 나머지는 본문으로 사용됩니다.",
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        self.text_area = scrolledtext.ScrolledText(
            main, wrap="word", font=("맑은 고딕", 10), undo=True, height=16,
        )
        self.text_area.pack(side=tk.TOP, fill="both", expand=True)
        self.text_area.insert("1.0", config_manager.load_config().get("manual_article_text", ""))
        self.text_area.focus_set()
        self.text_area.bind("<KeyRelease>", lambda _e: self._update_count())
        self._update_count()

    def _current_text(self) -> str:
        return self.text_area.get("1.0", tk.END).strip()

    def _update_count(self):
        self.count_label.config(text=f"현재 글자 수: {len(self._current_text())}자")

    def _on_save(self):
        text = self._current_text()
        cfg = config_manager.load_config()
        cfg["manual_article_text"] = text
        config_manager.save_config(cfg)

        if self.on_saved:
            self.on_saved(text)

        if text:
            messagebox.showinfo("저장 완료", f"직접입력 글이 저장되었습니다. ({len(text)}자)", parent=self)
        else:
            messagebox.showinfo("저장 완료", "직접입력 글을 비웠습니다.", parent=self)
        self.destroy()


class BrandConnectDialog(_BaseDialog):
    """
    브랜드커넥트 링크를 1줄에 1개씩 최대 50개까지 등록하는 창.
    각 링크에는 체크박스가 있고, 체크한 링크(최대 3개)만 글 중간중간에 랜덤 삽입된다.
    링크 글자를 클릭하면 크롬으로 열린다.
    저장하면 config.json의 brand_connect_links / brand_connect_checked에 기록된다.
    """

    def __init__(self, parent, on_saved=None):
        self.on_saved = on_saved
        cfg = config_manager.load_config()
        self.links = [
            str(link).strip()
            for link in cfg.get("brand_connect_links", [])
            if str(link).strip()
        ][:MAX_BRAND_LINKS]

        saved_checked = {str(link).strip() for link in cfg.get("brand_connect_checked", [])}
        self.checked = [link for link in self.links if link in saved_checked][:MAX_BRAND_CHECKED]
        self.check_vars = []
        super().__init__(parent, "🔗 브랜드커넥트 링크", "680x780")
        self.resizable(True, True)
        self.minsize(640, 720)

    def _build_ui(self):
        main = ttk.Frame(self, padding=16)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="🔗 브랜드커넥트 링크", font=("맑은 고딕", 12, "bold")).pack(anchor="w")
        ttk.Label(
            main,
            text=f"링크 하나당 1줄씩, 최대 {MAX_BRAND_LINKS}개까지 등록할 수 있습니다.\n"
                 f"체크한 링크(최대 {MAX_BRAND_CHECKED}개)만 글 중간중간에 랜덤으로 삽입됩니다.\n"
                 "링크 글자를 클릭하면 크롬 창에서 주소가 열립니다.",
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        list_box = ttk.LabelFrame(main, text="등록된 링크", padding=8)
        list_box.pack(fill="both", expand=True)
        self.rows_frame = self._build_scrollable_area(list_box)

        self.count_label = ttk.Label(list_box, text="", foreground="#666")
        self.count_label.pack(anchor="w", pady=(6, 0))

        add_box = ttk.LabelFrame(main, text="새 링크 추가 (여러 줄 붙여넣기 가능)", padding=8)
        add_box.pack(fill="x", pady=(10, 0))
        self.add_text = scrolledtext.ScrolledText(add_box, wrap="none", height=4, font=("Consolas", 9), undo=True)
        self.add_text.pack(fill="x")
        ttk.Button(add_box, text="➕ 목록에 추가", command=self._on_add).pack(fill="x", pady=(6, 0))

        btn_row = ttk.Frame(main)
        btn_row.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="🗑 체크한 링크 삭제", command=self._on_delete_checked).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="💾 저장", command=self._on_save).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(btn_row, text="✖ 취소", command=self.destroy).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self._refresh_list()

    def _build_scrollable_area(self, parent):
        """링크가 50개까지 늘어나도 볼 수 있도록 스크롤 가능한 행 영역을 만든다."""
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(wrap, highlightthickness=0, height=240)
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(inner_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return inner

    def _refresh_list(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self.check_vars = []

        if not self.links:
            ttk.Label(self.rows_frame, text="등록된 링크가 없습니다.", foreground="#999").pack(anchor="w", pady=6)
        for idx, link in enumerate(self.links):
            self._build_row(idx, link)

        self.count_label.config(
            text=f"체크 {len(self.checked)}개 / 최대 {MAX_BRAND_CHECKED}개  ·  "
                 f"전체 {len(self.links)}개 / 최대 {MAX_BRAND_LINKS}개"
        )

    def _build_row(self, idx: int, link: str):
        row = ttk.Frame(self.rows_frame)
        row.pack(fill="x", pady=1)

        var = tk.BooleanVar(value=link in self.checked)
        self.check_vars.append(var)
        ttk.Checkbutton(row, variable=var, command=lambda i=idx: self._on_check_toggled(i)).pack(side="left")

        ttk.Label(row, text=f"{idx + 1:2d}.", foreground="#999", font=("Consolas", 9)).pack(side="left")

        link_label = ttk.Label(
            row, text=link, foreground="blue", cursor="hand2",
            font=("Consolas", 9, "underline"), wraplength=470, justify="left",
        )
        link_label.pack(side="left", padx=(4, 0))
        link_label.bind("<Button-1>", lambda _e, url=link: open_in_chrome(url))

    def _on_check_toggled(self, idx: int):
        var = self.check_vars[idx]
        link = self.links[idx]

        if var.get():
            if len(self.checked) >= MAX_BRAND_CHECKED:
                var.set(False)
                messagebox.showwarning(
                    "확인",
                    f"글에 넣을 링크는 최대 {MAX_BRAND_CHECKED}개까지 체크할 수 있습니다.\n"
                    "다른 링크의 체크를 먼저 해제해주세요.",
                    parent=self,
                )
                return
            if link not in self.checked:
                self.checked.append(link)
        elif link in self.checked:
            self.checked.remove(link)

        self.count_label.config(
            text=f"체크 {len(self.checked)}개 / 최대 {MAX_BRAND_CHECKED}개  ·  "
                 f"전체 {len(self.links)}개 / 최대 {MAX_BRAND_LINKS}개"
        )

    def _on_add(self):
        raw = self.add_text.get("1.0", tk.END)
        candidates = [line.strip() for line in raw.splitlines() if line.strip()]
        if not candidates:
            messagebox.showwarning("확인", "추가할 링크를 입력해주세요.", parent=self)
            return

        added, duplicated, overflow = 0, 0, 0
        for link in candidates:
            if link in self.links:
                duplicated += 1
                continue
            if len(self.links) >= MAX_BRAND_LINKS:
                overflow += 1
                continue
            self.links.append(link)
            added += 1

        self.add_text.delete("1.0", tk.END)
        self._refresh_list()

        notes = [f"{added}개를 추가했습니다."]
        if duplicated:
            notes.append(f"중복 {duplicated}개는 건너뛰었습니다.")
        if overflow:
            notes.append(f"최대 {MAX_BRAND_LINKS}개를 넘어 {overflow}개는 추가되지 않았습니다.")
        messagebox.showinfo("추가 완료", "\n".join(notes), parent=self)

    def _on_delete_checked(self):
        if not self.checked:
            messagebox.showwarning("확인", "삭제할 링크의 체크박스를 먼저 선택해주세요.", parent=self)
            return
        if not messagebox.askyesno(
            "삭제 확인", f"체크한 {len(self.checked)}개 링크를 목록에서 삭제할까요?", parent=self
        ):
            return

        self.links = [link for link in self.links if link not in self.checked]
        self.checked = []
        self._refresh_list()

    def _on_save(self):
        cfg = config_manager.load_config()
        cfg["brand_connect_links"] = list(self.links)
        cfg["brand_connect_checked"] = list(self.checked)

        previews = dict(cfg.get("brand_connect_previews") or {})
        # 잘못 저장된 스토어 페이지 캐시는 제거
        previews = {
            url: data for url, data in previews.items()
            if brand_link_preview.is_valid_product_preview(data)
        }
        if self.checked:
            fetched = brand_link_preview.fetch_previews_for_links(self.checked, log=lambda _m: None)
            previews.update(fetched)
        cfg["brand_connect_previews"] = previews
        config_manager.save_config(cfg)

        if self.on_saved:
            self.on_saved(list(self.links), list(self.checked))

        messagebox.showinfo(
            "저장 완료",
            f"브랜드커넥트 링크 {len(self.links)}개를 저장했습니다.\n"
            f"이 중 체크된 {len(self.checked)}개가 글 중간중간에 랜덤으로 삽입됩니다.",
            parent=self,
        )
        self.destroy()
