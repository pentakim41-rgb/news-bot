# -*- coding: utf-8 -*-
"""PyInstaller frozen 실행 시 Playwright 크로미움 경로를 exe 옆 ms-playwright로 고정."""
import os
import sys

if getattr(sys, "frozen", False):
    browser_dir = os.path.join(os.path.dirname(sys.executable), "ms-playwright")
    if os.path.isdir(browser_dir):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browser_dir
