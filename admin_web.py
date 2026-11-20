# -*- coding: utf-8 -*-
"""
admin_web.py
-------------
관리자 모드 접속 시 127.0.0.1:5000 에서 실행되는 로컬 웹 서버입니다.
계정 목록 조회, 새 계정 추가(메모 기능 포함), 비밀번호 초기화, 계정 삭제 기능을 제공합니다.
"""

from flask import Flask, render_template_string, request, redirect, url_for, flash
from config_manager import load_config
from auth_manager import GitHubDB, hash_password, get_github_auth_config
import hmac
import secrets
import threading
import webbrowser
from datetime import datetime
from functools import wraps
from flask import Response

app = Flask(__name__)
# 세션 키는 실행할 때마다 무작위로 만든다 (소스에 고정값을 두지 않음)
app.secret_key = secrets.token_hex(32)


def _admin_credentials():
    """관리자 웹 로그인 정보는 config.json(admin_web_user / admin_web_pass)에서 읽는다."""
    cfg = load_config()
    return str(cfg.get("admin_web_user", "") or ""), str(cfg.get("admin_web_pass", "") or "")


def check_auth(username, password):
    user, pw = _admin_credentials()
    if not user or not pw:  # 설정이 비어 있으면 모든 로그인을 거부
        return False
    return hmac.compare_digest(str(username), user) and hmac.compare_digest(str(password), pw)

def authenticate():
    return Response(
        '인증이 필요합니다.', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>관리자모드 - 사용자 관리</title>
    <style>
        body { font-family: sans-serif; margin: 30px; background-color: #f5f5f5; }
        .container { max-width: 900px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        h2 { color: #333; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background-color: #007bff; color: white; }
        .btn { padding: 6px 12px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; font-size: 13px; }
        .btn-danger { background: #dc3545; }
        .btn-warning { background: #ffc107; color: #333; }
        .form-box { margin-top: 20px; padding: 15px; background: #e9ecef; border-radius: 6px; }
        input, select { padding: 6px; margin: 4px 0; }
    </style>
</head>
<body>
<div class="container">
    <h2>🛠 관리자 모드 - 사용자 계정 관리</h2>
    <p style="color:#666;">보안상 비밀번호는 암호화(해시) 저장되므로 원본은 표시되지 않으며, 필요 시 재설정할 수 있습니다.</p>
    
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <ul style="color: red;">
        {% for message in messages %}
          <li>{{ message }}</li>
        {% endfor %}
        </ul>
      {% endif %}
    {% endwith %}

    <table>
        <tr>
            <th>아이디</th>
            <th>권한 (Role)</th>
            <th>생성일</th>
            <th>메모</th>
            <th>작업</th>
        </tr>
        {% for username, info in users.items() %}
        <tr>
            <td><b>{{ username }}</b></td>
            <td>{{ info.role }}</td>
            <td>{{ info.created_at }}</td>
            <td>{{ info.get('memo', '-') }}</td>
            <td>
                <!-- 비밀번호 재설정 -->
                <form action="/reset_pw" method="post" style="display:inline;">
                    <input type="hidden" name="username" value="{{ username }}">
                    <input type="text" name="new_password" placeholder="새 비밀번호" required style="width:100px;">
                    <button type="submit" class="btn btn-warning">비번 변경</button>
                </form>
                <!-- 삭제 -->
                {% if info.role != 'admin' or users|length > 1 %}
                <a href="/delete/{{ username }}" class="btn btn-danger" onclick="return confirm('정말 삭제하시겠습니까?');">삭제</a>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>

    <div class="form-box">
        <h3>➕ 새 사용자 추가</h3>
        <form action="/add_user" method="post">
            <input type="text" name="username" placeholder="아이디" required>
            <input type="password" name="password" placeholder="비밀번호" required>
            <input type="text" name="memo" placeholder="메모 (최대 30자)" maxlength="30" style="width: 150px;">
            <select name="role">
                <option value="user">일반 사용자 (user)</option>
                <option value="admin">관리자 (admin)</option>
            </select>
            <button type="submit" class="btn">계정 생성</button>
        </form>
    </div>
</div>
</body>
</html>
"""

def get_db():
    cfg = get_github_auth_config()
    return GitHubDB(owner=cfg['owner'], repo=cfg['repo'], token=cfg['token'])

@app.route("/")
def index():
    try:
        db = get_db()
        users_data, _ = db.load_users()
        return render_template_string(HTML_TEMPLATE, users=users_data.get("users", {}))
    except Exception as e:
        return f"DB 연결 오류: {e}"

@app.route("/add_user", methods=["POST"])
def add_user():
    username = request.form.get("username").strip()
    password = request.form.get("password").strip()
    role = request.form.get("role", "user")
    memo = request.form.get("memo", "").strip()[:30]  # 메모 가져오기 (최대 30자)

    if not username or not password:
        flash("아이디와 비밀번호를 입력해주세요.")
        return redirect(url_for("index"))

    db = get_db()
    users_data, sha = db.load_users()
    
    if username in users_data.get("users", {}):
        flash("이미 존재하는 아이디입니다.")
        return redirect(url_for("index"))

    pw_hash, pw_salt = hash_password(password)
    users_data["users"][username] = {
        "hash": pw_hash,
        "salt": pw_salt,
        "role": role,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "memo": memo  # 메모 데이터 추가
    }
    
    db.save_users(users_data, sha, f"User {username} added")
    flash(f"계정 '{username}'이 성공적으로 생성되었습니다.")
    return redirect(url_for("index"))

@app.route("/reset_pw", methods=["POST"])
def reset_pw():
    username = request.form.get("username")
    new_password = request.form.get("new_password").strip()

    db = get_db()
    users_data, sha = db.load_users()

    if username in users_data.get("users", {}):
        pw_hash, pw_salt = hash_password(new_password)
        users_data["users"][username]["hash"] = pw_hash
        users_data["users"][username]["salt"] = pw_salt
        db.save_users(users_data, sha, f"Reset password for {username}")
        flash(f"'{username}' 계정의 비밀번호가 변경되었습니다.")

    return redirect(url_for("index"))

@app.route("/delete/<username>")
def delete_user(username):
    db = get_db()
    users_data, sha = db.load_users()

    if username in users_data.get("users", {}):
        del users_data["users"][username]
        db.save_users(users_data, sha, f"Deleted user {username}")
        flash(f"계정 '{username}'이 삭제되었습니다.")

    return redirect(url_for("index"))

def start_admin_server():
    """백그라운드에서 웹서버를 실행하고 브라우저를 엽니다."""
    def run():
        app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    webbrowser.open("http://127.0.0.1:5000")