# -*- coding: utf-8 -*-
"""
updater.py
-----------
GitHub 릴리스 기준으로 최신 버전을 확인하고, 배포 zip을 내려받는다.
(공개 저장소라 토큰이 필요 없다. exe는 실행 중 자기 자신을 교체할 수 없으므로
 새 zip을 '다운로드' 폴더에 받아 주고, 교체는 사용자가 직접 한다.)

릴리스를 올릴 때마다 APP_VERSION을 릴리스 태그(v1.0.1 → "1.0.1")와 맞춰야 한다.
"""

import os
import re
import requests

APP_VERSION = "1.0.2"
GITHUB_REPO = "pentakim41-rgb/news-bot"
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
_ALLOWED_HOSTS = ("github.com", "githubusercontent.com")


def _version_tuple(text: str) -> tuple:
    """'v1.0.1' → (1, 0, 1). 숫자가 없으면 (0,)."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums) or (0,)


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    a, b = list(_version_tuple(latest)), list(_version_tuple(current))
    size = max(len(a), len(b))
    a += [0] * (size - len(a))
    b += [0] * (size - len(b))
    return a > b


def fetch_latest_release(timeout: int = 10) -> dict:
    """
    최신 릴리스 정보를 반환한다.
    {"version": "1.0.1", "tag": "v1.0.1", "asset_name": "...zip", "asset_url": "...", "page": "..."}
    실패하면 예외를 그대로 던진다(호출하는 쪽에서 처리).
    """
    resp = requests.get(
        LATEST_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "news-bot-updater"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    tag = data.get("tag_name", "")
    asset = next(
        (a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".zip")),
        None,
    )
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "asset_name": asset["name"] if asset else "",
        "asset_url": asset["browser_download_url"] if asset else "",
        "asset_size": asset.get("size", 0) if asset else 0,
        "page": data.get("html_url", RELEASES_PAGE),
    }


def default_download_dir() -> str:
    path = os.path.join(os.path.expanduser("~"), "Downloads")
    return path if os.path.isdir(path) else os.path.expanduser("~")


def download_asset(url: str, filename: str, dest_dir: str = "", progress=None,
                   cancel_check=None) -> str:
    """
    zip을 dest_dir(기본: 다운로드 폴더)에 저장하고 파일 경로를 반환한다.
    progress(받은바이트, 전체바이트) 콜백을 주기적으로 호출한다.
    """
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _ALLOWED_HOSTS):
        raise ValueError(f"허용되지 않은 다운로드 주소입니다: {host}")

    dest_dir = dest_dir or default_download_dir()
    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(filename) or "news-bot-latest.zip"
    final_path = os.path.join(dest_dir, safe_name)
    part_path = final_path + ".part"

    try:
        with requests.get(url, stream=True, timeout=30,
                          headers={"User-Agent": "news-bot-updater"}) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(part_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if cancel_check and cancel_check():
                        raise InterruptedError("다운로드가 취소되었습니다.")
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        os.replace(part_path, final_path)
    except BaseException:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass
        raise
    return final_path
