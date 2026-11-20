# -*- coding: utf-8 -*-
"""
login_window.py
----------------
프로그램 실행 시 제일 먼저 뜨는 로그인 UI 화면입니다.
아이디/비밀번호 기억하기 기능 및 관리자모드 팝업창 기능이 포함되어 있습니다.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from auth_manager import GitHubDB, get_github_auth_config
import admin_web
import config_manager


class AdminLoginDialog(tk.Toplevel):
    """관리자모드 클릭 시 떠오르는 로그인 팝업 창 클래스"""
    def __init__(self, parent, get_db_func):
        super().__init__(parent)
        self.title("⚙ 관리자 인증")
        self.geometry("340x240")
        self.resizable(False, False)
        self.get_db = get_db_func

        # 모달 팝업 설정 (부모 창 위에 고정 및 클릭 제한)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._center_window(parent)

    def _center_window(self, parent):
        """부모 창 중앙에 팝업을 위치시킵니다."""
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill="both", expand=True)

        ttk.Label(main_frame, text="🔒 관리자 계정 로그인", font=("맑은 고딕", 12, "bold")).pack(pady=(0, 15))

        # 관리자 아이디 입력창
        ttk.Label(main_frame, text="관리자 아이디").pack(anchor="w")
        self.admin_id_entry = ttk.Entry(main_frame, width=30)
        self.admin_id_entry.pack(fill="x", pady=(0, 8))
        self.admin_id_entry.focus_set()

        # 관리자 비밀번호 입력창
        ttk.Label(main_frame, text="관리자 비밀번호").pack(anchor="w")
        self.admin_pw_entry = ttk.Entry(main_frame, show="*", width=30)
        self.admin_pw_entry.pack(fill="x", pady=(0, 15))

        # 엔터키 누르면 인증 진행
        self.admin_pw_entry.bind("<Return>", lambda e: self._verify_admin())

        # 버튼 프레임
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x")

        submit_btn = ttk.Button(btn_frame, text="인증 및 접속", command=self._verify_admin)
        submit_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        cancel_btn = ttk.Button(btn_frame, text="취소", command=self.destroy)
        cancel_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

    def _verify_admin(self):
        """팝업창에서 [인증 및 접속] 버튼을 눌렀을 때만 DB에 접속하여 검증합니다."""
        username = self.admin_id_entry.get().strip()
        password = self.admin_pw_entry.get().strip()

        if not username or not password:
            messagebox.showwarning("확인", "관리자 아이디와 비밀번호를 모두 입력해주세요.", parent=self)
            return

        # 팝업창에서 제출했을 때만 DB 호출
        db = self.get_db()
        if not db:
            return

        success, role, msg = db.authenticate(username, password)

        if success and role == "admin":
            messagebox.showinfo("인증 성공", "관리자 인증되었습니다.\n관리자 웹페이지를 브라우저로 열어드립니다.", parent=self)
            self.destroy()
            admin_web.start_admin_server()
        elif success and role != "admin":
            messagebox.showerror("권한 없음", "해당 계정은 관리자 권한이 없습니다.", parent=self)
        else:
            messagebox.showerror("로그인 실패", msg, parent=self)

class InitialSetupDialog(tk.Toplevel):
    """초기 설정(GitHub 정보 입력) 팝업 창 클래스"""
    def __init__(self, parent):
        super().__init__(parent)
        self.title("⚙ 로그인 DB 설정 (관리자)")
        self.geometry("400x340")
        self.resizable(True, True)
        self.minsize(320, 300)

        # 모달 팝업 설정 (부모 창 위에 고정 및 클릭 제한)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._load_existing_config()
        self._center_window(parent)

    def _center_window(self, parent):
        """부모 창 중앙에 팝업을 위치시킵니다."""
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill="both", expand=True)

        ttk.Label(main_frame, text="⚙ 로그인 DB 설정 (관리자)", font=("맑은 고딕", 12, "bold")).pack(pady=(0, 8))
        ttk.Label(
            main_frame,
            text="일반 사용자는 배포 config에 이미 설정되어 있습니다.\n관리자만 변경이 필요할 때 입력하세요.",
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        ttk.Label(main_frame, text="GitHub 아이디(owner)").pack(anchor="w")
        self.owner_entry = ttk.Entry(main_frame, width=35)
        self.owner_entry.pack(fill="x", pady=(0, 8))
        self.owner_entry.focus_set()

        ttk.Label(main_frame, text="로그인 DB 저장소(repo)").pack(anchor="w")
        self.repo_entry = ttk.Entry(main_frame, width=35)
        self.repo_entry.pack(fill="x", pady=(0, 8))

        ttk.Label(main_frame, text="Personal Access Token").pack(anchor="w")
        self.token_entry = ttk.Entry(main_frame, show="*", width=35)
        self.token_entry.pack(fill="x", pady=(0, 15))

        # 엔터키 누르면 저장 진행
        self.token_entry.bind("<Return>", lambda e: self._save_settings())

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x")

        save_btn = ttk.Button(btn_frame, text="저장", command=self._save_settings)
        save_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        cancel_btn = ttk.Button(btn_frame, text="취소", command=self.destroy)
        cancel_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

    def _load_existing_config(self):
        """이미 저장된 값이 있으면 입력창에 미리 채워줍니다."""
        try:
            cfg = get_github_auth_config()
            if cfg.get("owner"):
                self.owner_entry.insert(0, cfg["owner"])
            if cfg.get("repo"):
                self.repo_entry.insert(0, cfg["repo"])
            if cfg.get("token"):
                self.token_entry.insert(0, cfg["token"])
        except Exception as e:
            print(f"기존 설정 로드 오류: {e}")

    def _save_settings(self):
        """입력된 GitHub 정보를 config에 저장합니다."""
        owner = self.owner_entry.get().strip()
        repo = self.repo_entry.get().strip()
        token = self.token_entry.get().strip()

        if not owner or not repo or not token:
            messagebox.showwarning("확인", "아이디, 저장소, 토큰을 모두 입력해주세요.", parent=self)
            return

        try:
            cfg = config_manager.load_config()
            cfg["github_login_owner"] = owner
            cfg["github_login_repo"] = repo
            cfg["github_login_token"] = token
            config_manager.save_config(cfg)
            messagebox.showinfo("저장 완료", "로그인 DB 설정이 저장되었습니다.\n이제 로그인을 시도해보세요.", parent=self)
            self.destroy()
        except Exception as e:
            messagebox.showerror("저장 오류", f"설정 저장 중 오류가 발생했습니다: {e}", parent=self)

class LoginWindow(tk.Tk):
    def __init__(self, on_login_success_callback):
        super().__init__()
        self.title("로그인")
        self.geometry("380x320")
        self.resizable(False, False)
        self.on_login_success = on_login_success_callback

        self._build_ui()
        self._load_remembered_info()

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill="both", expand=True)

        ttk.Label(main_frame, text="🔑 AI 블로그 자동 생성기", font=("맑은 고딕", 14, "bold")).pack(pady=(0, 15))

        # 아이디 입력
        ttk.Label(main_frame, text="아이디").pack(anchor="w")
        self.id_entry = ttk.Entry(main_frame, width=30)
        self.id_entry.pack(fill="x", pady=(0, 8))

        # 비밀번호 입력
        ttk.Label(main_frame, text="비밀번호").pack(anchor="w")
        self.pw_entry = ttk.Entry(main_frame, show="*", width=30)
        self.pw_entry.pack(fill="x", pady=(0, 8))

        # 엔터키 누르면 로그인 진행
        self.pw_entry.bind("<Return>", lambda e: self._handle_login())

        # 기억하기 체크박스
        self.remember_var = tk.BooleanVar(value=False)
        self.chk_remember = ttk.Checkbutton(
            main_frame, 
            text="아이디/비밀번호 기억하기", 
            variable=self.remember_var
        )
        self.chk_remember.pack(anchor="w", pady=(0, 12))

        # 일반 로그인 버튼
        login_btn = ttk.Button(main_frame, text="로그인", command=self._handle_login)
        login_btn.pack(fill="x")

        # 하단 레이아웃 (관리자모드 버튼)
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill="x", side="bottom", pady=(10, 0))

        setup_btn = ttk.Button(bottom_frame, text="⚙ 초기 설정", command=self._handle_initial_setup)
        setup_btn.pack(side="left")

        admin_btn = ttk.Button(bottom_frame, text="⚙ 관리자모드", command=self._handle_admin_mode)
        admin_btn.pack(side="right")

    def _load_remembered_info(self):
        """저장된 아이디/비밀번호가 있으면 입력창에 자동으로 채워줍니다."""
        try:
            cfg = config_manager.load_config()
            if cfg.get("remember_me", False):
                self.remember_var.set(True)
                saved_id = cfg.get("saved_id", "")
                saved_pw = cfg.get("saved_pw", "")
                if saved_id:
                    self.id_entry.insert(0, saved_id)
                if saved_pw:
                    self.pw_entry.insert(0, saved_pw)
        except Exception as e:
            print(f"기억하기 정보 로드 오류: {e}")

    def _save_remembered_info(self):
        """체크박스 상태에 따라 아이디/비밀번호를 저장하거나 삭제합니다."""
        try:
            cfg = config_manager.load_config()
            if self.remember_var.get():
                cfg["remember_me"] = True
                cfg["saved_id"] = self.id_entry.get().strip()
                cfg["saved_pw"] = self.pw_entry.get().strip()
            else:
                cfg["remember_me"] = False
                cfg["saved_id"] = ""
                cfg["saved_pw"] = ""
            config_manager.save_config(cfg)
        except Exception as e:
            print(f"기억하기 정보 저장 오류: {e}")

    def _get_db(self):
        cfg = get_github_auth_config()
        if not cfg["owner"] or not cfg["token"] or not cfg["repo"]:
            messagebox.showerror("설정 오류", "로그인 DB(GitHub) 설정이 없습니다.\n관리자에게 문의하거나 「⚙ 초기 설정」에서 입력하세요.")
            return None
        return GitHubDB(owner=cfg['owner'], repo=cfg['repo'], token=cfg['token'])

    def _handle_login(self):
        username = self.id_entry.get().strip()
        password = self.pw_entry.get().strip()

        if not username or not password:
            messagebox.showwarning("확인", "아이디와 비밀번호를 모두 입력해주세요.")
            return

        db = self._get_db()
        if not db:
            return

        success, role, msg = db.authenticate(username, password)
        if success:
            self._save_remembered_info()
            messagebox.showinfo("성공", f"환영합니다, {username}님!")
            self.destroy()
            self.on_login_success()
        else:
            messagebox.showerror("로그인 실패", msg)

    def _handle_initial_setup(self):
        """초기 설정 버튼 클릭 시 GitHub 설정 팝업창을 띄웁니다."""
        InitialSetupDialog(self)

    def _handle_admin_mode(self):
        """관리자모드 버튼 클릭 시 팝업창을 띄웁니다."""
        AdminLoginDialog(self, self._get_db)