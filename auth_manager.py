# -*- coding: utf-8 -*-
"""
auth_manager.py
----------------
GitHub 저장소의 users.json을 데이터베이스로 활용합니다.
비밀번호는 PBKDF2-HMAC-SHA256 해시로 안전하게 저장 및 검증합니다.
새 사용자 추가 시 메모 기능(최대 30자)이 포함되어 있습니다.
"""

import base64
import hashlib
import json
import os
import requests
from datetime import datetime

# GitHub API 설정 (config.json에서 불러오거나 기본값 사용)
def get_github_auth_config():
    import config_manager
    cfg = config_manager.get_github_login_config()
    return {
        "owner": cfg["owner"],
        "token": cfg["token"],
        "repo": cfg["repo"],
        "file_path": "users.json",
    }

def hash_password(password: str, salt: bytes = None) -> tuple:
    """비밀번호를 Salt와 함께 PBKDF2로 해시화합니다."""
    if salt is None:
        salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return key.hex(), salt.hex()

def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """입력된 비밀번호가 저장된 해시와 일치하는지 검증합니다."""
    salt = bytes.fromhex(stored_salt)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return key.hex() == stored_hash

class GitHubDB:
    def __init__(self, owner: str, repo: str, token: str, file_path: str = "users.json"):
        self.owner = owner
        self.repo = repo
        self.token = token
        self.file_path = file_path
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.url = f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/{self.file_path}"

    def load_users(self) -> tuple:
        """GitHub에서 users.json 데이터를 가져옵니다. (dict, sha) 반환"""
        res = requests.get(self.url, headers=self.headers)
        if res.status_code == 200:
            data = res.json()
            content = base64.b64decode(data['content']).decode('utf-8')
            sha = data['sha']
            return json.loads(content), sha
        elif res.status_code == 404:
            # 파일이 없으면 기본 관리자 계정 생성
            # 소스에 고정 비밀번호를 두지 않는다: 설정값 → 없으면 무작위 생성 후 1회 출력
            import secrets
            try:
                from config_manager import load_config
                init_pw = str(load_config().get("admin_web_pass", "") or "")
            except Exception:
                init_pw = ""
            if not init_pw:
                init_pw = secrets.token_urlsafe(12)
                print(f"[로그인DB] 기본 관리자(admin) 계정을 새로 만들었습니다. 임시 비밀번호: {init_pw}")
            init_hash, init_salt = hash_password(init_pw)
            initial_db = {
                "users": {
                    "admin": {
                        "hash": init_hash,
                        "salt": init_salt,
                        "role": "admin",
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "memo": "기본 관리자 계정"
                    }
                }
            }
            sha = self.save_users(initial_db, None, "초기 users.json 생성")
            return initial_db, sha
        else:
            raise Exception(f"GitHub DB 로드 실패 (Status: {res.status_code})")

    def save_users(self, db_data: dict, sha: str = None, commit_message: str = "Update users") -> str:
        """users.json 데이터를 GitHub에 저장합니다."""
        content_bytes = json.dumps(db_data, ensure_ascii=False, indent=2).encode('utf-8')
        encoded_content = base64.b64encode(content_bytes).decode('utf-8')

        payload = {
            "message": commit_message,
            "content": encoded_content
        }
        if sha:
            payload["sha"] = sha

        res = requests.put(self.url, headers=self.headers, json=payload)
        if res.status_code in (200, 201):
            return res.json()['content']['sha']
        else:
            raise Exception(f"GitHub DB 저장 실패: {res.text}")

    def authenticate(self, username, password) -> tuple:
        """사용자 인증 (성공 여부, 역할, 메시지)"""
        try:
            db, _ = self.load_users()
            user_info = db.get("users", {}).get(username)
            if not user_info:
                return False, None, "존재하지 않는 아이디입니다."
            
            if verify_password(password, user_info["hash"], user_info["salt"]):
                return True, user_info.get("role", "user"), "인증 성공"
            else:
                return False, None, "비밀번호가 올바르지 않습니다."
        except Exception as e:
            return False, None, f"DB 오류: {str(e)}"

    def add_user(self, username, password, role="user", memo="") -> tuple:
        """새 사용자를 추가합니다. (메모 기능 포함, 최대 30자)"""
        try:
            db, sha = self.load_users()
            users = db.get("users", {})
            
            if username in users:
                return False, "이미 존재하는 아이디입니다."

            # 비밀번호 해시화
            pwd_hash, pwd_salt = hash_password(password)
            
            # 메모는 앞뒤 공백 제거 후 최대 30자까지 자릅니다.
            safe_memo = memo.strip()[:30] if memo else ""

            users[username] = {
                "hash": pwd_hash,
                "salt": pwd_salt,
                "role": role,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "memo": safe_memo
            }
            db["users"] = users
            self.save_users(db, sha, f"Add user: {username}")
            return True, "계정이 성공적으로 생성되었습니다."
        except Exception as e:
            return False, f"계정 생성 오류: {str(e)}"

    def delete_user(self, username) -> tuple:
        """사용자를 삭제합니다."""
        try:
            db, sha = self.load_users()
            users = db.get("users", {})
            
            if username not in users:
                return False, "존재하지 않는 아이디입니다."

            del users[username]
            db["users"] = users
            self.save_users(db, sha, f"Delete user: {username}")
            return True, "계정이 성공적으로 삭제되었습니다."
        except Exception as e:
            return False, f"계정 삭제 오류: {str(e)}"

    def update_password(self, username, new_password) -> tuple:
        """사용자의 비밀번호를 변경합니다."""
        try:
            db, sha = self.load_users()
            users = db.get("users", {})
            
            if username not in users:
                return False, "존재하지 않는 아이디입니다."

            pwd_hash, pwd_salt = hash_password(new_password)
            users[username]["hash"] = pwd_hash
            users[username]["salt"] = pwd_salt
            
            db["users"] = users
            self.save_users(db, sha, f"Update password for {username}")
            return True, "비밀번호가 성공적으로 변경되었습니다."
        except Exception as e:
            return False, f"비밀번호 변경 오류: {str(e)}"