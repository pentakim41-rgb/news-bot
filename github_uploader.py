# -*- coding: utf-8 -*-
"""
github_uploader.py
--------------------
완성된 HTML 파일(및 그 안에서 참조하는 이미지 파일)을 깃허브 저장소에
자동으로 업로드하는 모듈.

사용 전 준비물:
    1. 깃허브 저장소(Repository) - Public 으로 생성해야 이미지 URL이 외부에서 보입니다.
    2. 개인 액세스 토큰(Personal Access Token) - Settings > Developer settings 에서 발급.
    3. pip install requests

사용 방법 (다른 파이썬 파일에서 import 해서 쓰는 경우):

    from github_uploader import GithubUploader

    uploader = GithubUploader(
        token="ghp_xxxxxxxxxxxxxxxxxxxx",
        owner="내깃허브아이디",
        repo="my-blog-images",
        branch="main",
    )

    # html_path: 로컬에 저장된 html 파일 경로
    # image_paths: 그 html이 참조하는 이미지 파일들의 로컬 경로 리스트
    result = uploader.upload_post(
        html_path="output/post_20260718.html",
        image_paths=["output/images/thumb1.png", "output/images/thumb2.png"],
        remote_folder="posts/20260718",
    )

    print(result["html_url"])       # 브라우저로 열어볼 수 있는 html 미리보기 링크
    print(result["html_raw_url"])   # html 원본 텍스트 링크
    print(result["image_urls"])     # 이미지들의 공개 URL 리스트 (블로그에 그대로 써도 보임)

이 파일을 직접 실행(python github_uploader.py)하면 맨 아래 __main__ 부분의
예시 코드로 테스트할 수 있습니다. (본인 정보로 값을 바꿔서 실행하세요)
"""

import base64
import glob
import os
import json
import re
import threading
from datetime import datetime
from typing import List, Dict

import requests


_upload_lock = threading.Lock()


def is_upload_in_progress() -> bool:
    return _upload_lock.locked()


def upload_log_key(html_path: str) -> str:
    """PC/폴더 경로가 바뀌어도 동일 파일을 인식하도록 파일명만 키로 사용."""
    return os.path.basename(html_path).lower()


def normalize_upload_log(raw_log) -> dict:
    """옛날 절대경로 키를 파일명 키로 통일. 중복은 URL이 있는 항목을 우선."""
    if isinstance(raw_log, list):
        raw_log = {
            path: {
                "title": os.path.splitext(os.path.basename(path))[0],
                "url": "",
                "repo": "",
                "uploaded_at": "",
            }
            for path in raw_log
        }
    if not isinstance(raw_log, dict):
        return {}

    normalized = {}
    for key, info in raw_log.items():
        if not isinstance(info, dict):
            info = {
                "title": os.path.splitext(os.path.basename(str(key)))[0],
                "url": "",
                "repo": "",
                "uploaded_at": "",
            }

        file_key = upload_log_key(key)
        entry = {
            "title": info.get("title") or os.path.splitext(file_key)[0],
            "url": info.get("url", ""),
            "repo": info.get("repo", ""),
            "uploaded_at": info.get("uploaded_at", ""),
        }

        existing = normalized.get(file_key)
        if existing is None:
            normalized[file_key] = entry
            continue

        if entry.get("url") and not existing.get("url"):
            normalized[file_key] = entry
        elif entry.get("uploaded_at", "") > existing.get("uploaded_at", ""):
            normalized[file_key] = entry

    return normalized


def load_upload_log(log_path: str) -> dict:
    if not os.path.exists(log_path):
        return {}
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            raw_log = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    normalized = normalize_upload_log(raw_log)
    if normalized != raw_log:
        save_upload_log(log_path, normalized)
    return normalized


def save_upload_log(log_path: str, uploaded_log: dict) -> None:
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(uploaded_log, f, ensure_ascii=False, indent=2)


def is_uploaded(html_path: str, uploaded_log: dict) -> bool:
    return upload_log_key(html_path) in uploaded_log


def filter_pending_uploads(all_html_files: List[str], uploaded_log: dict) -> List[str]:
    return [path for path in all_html_files if not is_uploaded(path, uploaded_log)]


def make_upload_log_entry(html_path: str, result: Dict, repo_name: str) -> dict:
    return {
        "title": os.path.splitext(os.path.basename(html_path))[0],
        "url": result["html_url"],
        "repo": repo_name,
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


class GithubUploader:
    def __init__(self, token: str, owner: str, repo: str, branch: str = "main"):
        """
        token  : 깃허브 개인 액세스 토큰 (ghp_로 시작하는 문자열)
        owner  : 깃허브 아이디 (예: myusername)
        repo   : 저장소 이름 (예: my-blog-images)
        branch : 브랜치 이름 (보통 main, 옛날 저장소는 master 인 경우도 있음)
        """
        self.token = token
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.api_base = f"https://api.github.com/repos/{owner}/{repo}/contents"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }

    # ---------------------------------------------------------- 내부 유틸
    def _get_existing_sha(self, remote_path: str) -> str | None:
        """
        같은 경로에 파일이 이미 있으면 업데이트(덮어쓰기)를 위해 sha 값이 필요함.
        없으면 None 반환 (새 파일로 처리).
        """
        url = f"{self.api_base}/{remote_path}"
        resp = requests.get(url, headers=self.headers, params={"ref": self.branch})
        if resp.status_code == 200:
            return resp.json().get("sha")
        return None

    def _upload_single_file(self, local_path: str, remote_path: str, commit_message: str) -> str:
        """
        파일 하나를 깃허브에 업로드(또는 덮어쓰기)하고, raw 파일 공개 URL을 반환.
        """
        with open(local_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")

        existing_sha = self._get_existing_sha(remote_path)

        payload = {
            "message": commit_message,
            "content": content_b64,
            "branch": self.branch,
        }
        if existing_sha:
            payload["sha"] = existing_sha  # 기존 파일 업데이트인 경우 필요

        url = f"{self.api_base}/{remote_path}"
        resp = requests.put(url, headers=self.headers, json=payload)

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"업로드 실패 ({local_path} -> {remote_path}): "
                f"status={resp.status_code}, body={resp.text}"
            )

        # 공개적으로 접근 가능한 raw 파일 URL 조립
        raw_url = (
            f"https://raw.githubusercontent.com/{self.owner}/{self.repo}"
            f"/{self.branch}/{remote_path}"
        )
        return raw_url

    # ---------------------------------------------------------- 공개 메서드
    def upload_file(self, local_path: str, remote_path: str, commit_message: str = None) -> str:
        """
        파일 하나만 업로드하고 싶을 때 사용. 이미지든 html이든 상관없음.
        remote_path 예: "posts/20260718/thumb1.png"
        """
        if commit_message is None:
            commit_message = f"Upload {os.path.basename(local_path)}"
        return self._upload_single_file(local_path, remote_path, commit_message)

    
    def upload_html_with_images_folder(
        self,
        html_path: str,
        images_folder: str,
        remote_folder: str = None,
    ) -> Dict:
        """
        html 파일 하나와, 그 html이 쓰는 이미지들이 별도의 images 폴더에 들어있는
        경우 사용합니다. html 내용 안의 <img src="..."> 에 적힌 파일 이름들을 읽어서,
        images_folder(하위 폴더 포함) 안에서 이름이 같은 파일을 자동으로 찾아 매칭합니다.
        """
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        referenced_names = set(
            re.findall(
                r'src=["\'](?:[^"\']*/)?([^"\'/]+\.(?:png|jpg|jpeg|gif|webp))["\']',
                html_content,
                flags=re.IGNORECASE,
            )
        )

        image_paths = []
        if referenced_names:
            all_images = glob.glob(os.path.join(images_folder, "**", "*"), recursive=True)
            for path in all_images:
                if os.path.isfile(path) and os.path.basename(path) in referenced_names:
                    image_paths.append(path)

        if remote_folder is None:
            base_name = os.path.splitext(os.path.basename(html_path))[0]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            remote_folder = f"posts/{base_name}_{timestamp}"

        return self.upload_post(
            html_path=html_path,
            image_paths=image_paths,
            remote_folder=remote_folder,
        )

    def upload_post(
        self,
        html_path: str,
        image_paths: List[str],
        remote_folder: str,
        rewrite_image_src: bool = True,
    ) -> Dict:
        """
        html 파일 하나와 그에 딸린 이미지들을 한 번에 업로드.

        html_path         : 로컬 html 파일 경로
        image_paths       : 그 html이 사용하는 이미지들의 로컬 경로 리스트
        remote_folder     : 깃허브 저장소 안에 만들 폴더 경로 (예: "posts/20260718")
        rewrite_image_src : True면 html 안의 <img src="..."> 를 업로드된 깃허브 URL로
                             자동 치환한 뒤 업로드함. (블로그에 붙여넣었을 때 이미지가
                             바로 보이도록 하기 위함 - 강력히 권장)

        반환값:
            {
                "html_url": 브라우저에서 렌더링된 형태로 볼 수 있는 링크,
                "html_raw_url": html 원본 텍스트 링크,
                "image_urls": [업로드된 이미지들의 공개 URL, ...],
            }
        """
        image_urls = []
        image_name_to_url = {}

        # 1) 이미지들 먼저 업로드
        for img_path in image_paths:
            img_filename = os.path.basename(img_path)
            remote_img_path = f"{remote_folder}/images/{img_filename}"
            url = self._upload_single_file(
                img_path, remote_img_path, f"Upload image {img_filename}"
            )
            image_urls.append(url)
            image_name_to_url[img_filename] = url

        # 2) html 내용 읽기
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 3) 필요하면 html 안의 이미지 경로를 깃허브 URL로 교체
        if rewrite_image_src:
            for filename, url in image_name_to_url.items():
                # src="thumb1.png" 또는 src="images/thumb1.png" 등 다양한 상대경로 형태를 처리
                pattern = re.compile(
                    r'src=["\'](?:[^"\']*/)?' + re.escape(filename) + r'["\']'
                )
                html_content = pattern.sub(f'src="{url}"', html_content)

            # 치환한 내용을 임시로 저장 후 업로드 (원본 로컬 파일은 건드리지 않음)
            temp_path = html_path + ".tmp_upload.html"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            upload_source = temp_path
        else:
            upload_source = html_path

        # 4) html 업로드
        html_filename = os.path.basename(html_path)
        remote_html_path = f"{remote_folder}/{html_filename}"
        html_raw_url = self._upload_single_file(
            upload_source, remote_html_path, f"Upload post {html_filename}"
        )

        # 임시 파일 정리
        if rewrite_image_src and os.path.exists(upload_source) and upload_source != html_path:
            os.remove(upload_source)

        # 브라우저에서 바로 렌더링해서 보고 싶을 때 쓰는 링크 (raw는 텍스트로만 보임)
        # htmlpreview.github.io 를 사용하면 raw html을 렌더링해서 볼 수 있음
        html_preview_url = (
            f"https://htmlpreview.github.io/?{html_raw_url}"
        )

        return {
            "html_url": html_preview_url,
            "html_raw_url": html_raw_url,
            "image_urls": image_urls,
        }

        return {
            "html_url": html_preview_url,
            "html_raw_url": html_raw_url,
            "image_urls": image_urls,
        }


def upload_folder(
    html_folder: str,
    images_folder: str,
    owner: str,
    token: str,
    repos: List[str],
    log_path: str = "github_uploaded_log.json",
    log=print,
    stop_event=None,
    stop_events=None,
    after_each_upload=None,
) -> bool:
    """업로드 실행. stop_event/stop_events가 set되면 중단하고 False 반환."""

    if not _upload_lock.acquire(blocking=False):
        log("[깃허브] 다른 업로드 작업이 이미 진행 중입니다.")
        return False

    try:
        return _upload_folder_impl(
            html_folder=html_folder,
            images_folder=images_folder,
            owner=owner,
            token=token,
            repos=repos,
            log_path=log_path,
            log=log,
            stop_event=stop_event,
            stop_events=stop_events,
            after_each_upload=after_each_upload,
        )
    finally:
        _upload_lock.release()


def _upload_folder_impl(
    html_folder: str,
    images_folder: str,
    owner: str,
    token: str,
    repos: List[str],
    log_path: str = "github_uploaded_log.json",
    log=print,
    stop_event=None,
    stop_events=None,
    after_each_upload=None,
) -> bool:
    """upload_folder 내부 구현 (락은 upload_folder에서 처리)."""

    _stop_events = []
    if stop_event is not None:
        _stop_events.append(stop_event)
    if stop_events:
        _stop_events.extend(event for event in stop_events if event is not None)

    def _should_stop() -> bool:
        return any(event.is_set() for event in _stop_events)

    if _should_stop():
        log("[깃허브] 사용자 요청으로 업로드를 중지했습니다.")
        return False
    if not repos:
        log("[깃허브] 업로드할 저장소가 설정되어 있지 않습니다.")
        return True

    all_html_files = []
    for root, _dirs, files in os.walk(html_folder):
        for f in files:
            if f.lower().endswith(".html"):
                all_html_files.append(os.path.abspath(os.path.join(root, f)))
    all_html_files.sort()

    if not all_html_files:
        log(f"[깃허브] '{html_folder}' 안에서 html 파일을 찾지 못했습니다.")
        return True

    uploaded_log = load_upload_log(log_path)

    html_files = filter_pending_uploads(all_html_files, uploaded_log)
    skipped_count = len(all_html_files) - len(html_files)
    if skipped_count:
        log(f"[깃허브] 이미 업로드된 {skipped_count}개 파일은 건너뜁니다. (파일명 기준)")

    if not html_files:
        log("[깃허브] 새로 업로드할 파일이 없습니다. (모두 업로드 완료된 상태)")
        return True

    log(f"[깃허브] 새로 업로드할 게시물 {len(html_files)}개. 업로드를 시작합니다.")

    already_uploaded_count = len(uploaded_log)  # 누적 업로드 개수 (저장소 순번을 이어가기 위함)

    uploaders = {}
    stopped = False
    for idx, html_path in enumerate(html_files):
        if _should_stop():
            stopped = True
            break

        repo_name = repos[(already_uploaded_count + idx) % len(repos)]
        if repo_name not in uploaders:
            uploaders[repo_name] = GithubUploader(token=token, owner=owner, repo=repo_name, branch="main")
        uploader = uploaders[repo_name]

        log(f"[깃허브] ({idx + 1}/{len(html_files)}) '{os.path.basename(html_path)}' -> 저장소 '{repo_name}' 업로드 중...")
        try:
            result = uploader.upload_html_with_images_folder(html_path, images_folder)
            log(f"[깃허브] 완료: {result['html_url']}")
            uploaded_log[upload_log_key(html_path)] = make_upload_log_entry(
                html_path, result, repo_name
            )
            save_upload_log(log_path, uploaded_log)
            if after_each_upload:
                after_each_upload(html_path)
        except Exception as e:
            log(f"[깃허브] 실패 ('{html_path}'): {e}")

    if stopped:
        log("[깃허브] 사용자 요청으로 업로드를 중지했습니다.")
        return False

    log("[깃허브] 모든 업로드 작업이 끝났습니다.")
    return True


def upload_single_html(
    html_path: str,
    images_folder: str,
    owner: str,
    token: str,
    repos: List[str],
    log_path: str = "github_uploaded_log.json",
    log=print,
    stop_event=None,
    stop_events=None,
    after_upload=None,
) -> bool:
    """방금 생성된 HTML 1개만 업로드. 이미 업로드된 파일은 건너뜀."""

    if not html_path or not os.path.isfile(html_path):
        return False
    if not repos:
        log("[깃허브] 업로드할 저장소가 설정되어 있지 않습니다.")
        return False
    if not owner or not token:
        log("[깃허브] GitHub 아이디/토큰이 없어 업로드를 건너뜁니다.")
        return False

    _stop_events = []
    if stop_event is not None:
        _stop_events.append(stop_event)
    if stop_events:
        _stop_events.extend(event for event in stop_events if event is not None)

    def _should_stop() -> bool:
        return any(event.is_set() for event in _stop_events)

    if _should_stop():
        log("[깃허브] 사용자 요청으로 업로드를 중지했습니다.")
        return False

    uploaded_log = load_upload_log(log_path)
    if is_uploaded(html_path, uploaded_log):
        log(f"[깃허브] '{os.path.basename(html_path)}'은(는) 이미 업로드되어 건너뜁니다.")
        return True

    if not _upload_lock.acquire(blocking=False):
        log("[깃허브] 다른 업로드 작업 진행 중 — 이 글은 깃허브 탭에서 나중에 업로드하세요.")
        return False

    try:
        if _should_stop():
            log("[깃허브] 사용자 요청으로 업로드를 중지했습니다.")
            return False

        repo_name = repos[len(uploaded_log) % len(repos)]
        uploader = GithubUploader(token=token, owner=owner, repo=repo_name, branch="main")

        log(f"[깃허브] '{os.path.basename(html_path)}' -> 저장소 '{repo_name}' 업로드 중...")
        result = uploader.upload_html_with_images_folder(html_path, images_folder)
        log(f"[깃허브] 완료: {result['html_url']}")
        uploaded_log[upload_log_key(html_path)] = make_upload_log_entry(
            html_path, result, repo_name
        )
        save_upload_log(log_path, uploaded_log)
        if after_upload:
            after_upload(html_path)
        return True
    except Exception as e:
        log(f"[깃허브] 실패 ('{html_path}'): {e}")
        return False
    finally:
        _upload_lock.release()
