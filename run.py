# -*- coding: utf-8 -*-
"""
run.py
------
로그인 UI를 먼저 띄운 후, 로그인 성공 시 메인 앱(MainApp)을 구동합니다.
"""

from login_window import LoginWindow
from gui import MainApp

def launch_main_app():
    app = MainApp()
    app.mainloop()

if __name__ == "__main__":
    login_app = LoginWindow(on_login_success_callback=launch_main_app)
    login_app.mainloop()