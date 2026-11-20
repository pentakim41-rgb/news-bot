# -*- coding: utf-8 -*-
"""
main.py
--------
프로그램 실행 진입점. GUI를 띄운다.

실행 방법:
    python main.py
"""

import os
import sys
from gui import MainApp

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIRED_DIRS = [
    "data/scraped_news",
    "data/rewritten_news",
    "data/image_prompts",
    "data/images",
    "data/html_output",
]


def ensure_directories():
    for d in REQUIRED_DIRS:
        os.makedirs(os.path.join(BASE_DIR, d), exist_ok=True)


if __name__ == "__main__":
    ensure_directories()
    app = MainApp()
    app.mainloop()
